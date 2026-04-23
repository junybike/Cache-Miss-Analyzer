"""Shared helpers, tunable thresholds, and context builders for the rules.

A rule is a function `run(ctx) -> Iterable[dict]` that yields recommendation
dicts. `ctx` is the dict constructed in recommend.py and contains:

    accesses        list   — AST access records
    var_misses      dict   — variable -> {"misses": int, ...}
    structs         dict   — struct_type -> layout
    field_heat      dict   — struct_type -> field -> attributed misses
    cache_line      int    — L1d line size in bytes
    miss_threshold  int    — minimum misses to flag a variable
"""

import subprocess
from collections import defaultdict

# --- Tunables -------------------------------------------------------------

# A struct field counts as "hot" if its heat exceeds this fraction of the
# hottest field's heat. Uses max (not total) so noisy init loops don't
# inflate the cutoff.
FIELD_HEAT_RATIO = 0.2

# AoS->SoA fires when this fraction of a struct's *bytes* is cold.
AOS_WASTE_THRESHOLD = 0.25
MIN_FIELDS_AOS = 2

# A struct must span at least this many cache lines before we suggest a
# hot/cold partition.
HOT_COLD_MIN_SIZE_LINES = 2

# Absolute floor; variables below this are ignored regardless of totals.
MISS_FLOOR = 50
MISS_RATIO_OF_TOTAL = 0.02

DEFAULT_CACHE_LINE = 64

STRUCT_KINDS = ("struct_member", "aos_member")


# --- Context builders (invoked by recommend.py) ---------------------------

def detect_cache_line():
    try:
        r = subprocess.run(
            ["getconf", "LEVEL1_DCACHE_LINESIZE"],
            capture_output=True, text=True, timeout=5,
        )
        v = int(r.stdout.strip())
        if v > 0:
            return v
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return DEFAULT_CACHE_LINE


def compute_miss_threshold(var_misses):
    """Use total misses (not max) so a single dominant variable doesn't
    push the threshold up and mask other significant issues."""
    if not var_misses:
        return 0
    total = sum(v.get("misses", 0) for v in var_misses.values())
    return max(MISS_FLOOR, int(total * MISS_RATIO_OF_TOTAL))


def compute_field_heat(accesses, hot_lines):
    """struct_type -> field -> attributed miss count. When a line has
    multiple field accesses, the line's miss count is split evenly."""
    per_line = defaultdict(int)
    for a in accesses:
        if a["kind"] in STRUCT_KINDS and a.get("field") and a["line"] in hot_lines:
            per_line[a["line"]] += 1

    heat = defaultdict(lambda: defaultdict(float))
    for a in accesses:
        if a["kind"] in STRUCT_KINDS and a.get("field") and a["line"] in hot_lines:
            share = per_line[a["line"]]
            heat[a.get("struct_type", "")][a["field"]] += hot_lines[a["line"]] / share
    return heat


# --- Per-rule helpers -----------------------------------------------------

def var_key(a):
    fn = a.get("function", "")
    return f"{fn}::{a['var']}" if fn else a["var"]


def misses_of(ctx, var_or_access):
    if isinstance(var_or_access, dict):
        key = var_key(var_or_access)
    else:
        key = var_or_access
    return ctx["var_misses"].get(key, {}).get("misses", 0)


def lines_of(ctx, var_or_access):
    if isinstance(var_or_access, dict):
        fn = var_or_access.get("function", "")
        var = var_or_access["var"]
        return sorted({a["line"] for a in ctx["accesses"]
                       if a["var"] == var and a.get("function", "") == fn})
    return sorted({a["line"] for a in ctx["accesses"]
                   if a["var"] == var_or_access})
