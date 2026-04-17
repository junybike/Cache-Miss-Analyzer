"""Correlate AST variable accesses with perf cache-miss data.

Each line with a nonzero miss count credits its full count to every
variable accessed on that line. This is a simple model — a single line
with N variable accesses contributes to all N variables.
"""

import argparse
import json
import sys
from collections import defaultdict

from rules.common import STRUCT_KINDS


def var_key(a):
    """Scope variable names by function to prevent false merging of common
    names like 'i' or 'data' across different functions."""
    fn = a.get("function", "")
    return f"{fn}::{a['var']}" if fn else a["var"]


def correlate(accesses, perf_data):
    by_line = defaultdict(list)
    for a in accesses:
        by_line[a["line"]].append(a)

    info = {}
    for line_str, count in perf_data.items():
        for a in by_line.get(int(line_str), []):
            key = var_key(a)
            v = info.setdefault(key, {"misses": 0, "kinds": set()})
            v["misses"] += count
            v["kinds"].add(a["kind"])

            if a.get("element_type"):
                v.setdefault("element_type", a["element_type"])
            if a.get("struct_type"):
                v.setdefault("struct_type", a["struct_type"])

            if a["kind"] in STRUCT_KINDS:
                v.setdefault("fields_accessed", set())
                v.setdefault("has_ptr_advance", False)
                if a.get("field"):
                    v["fields_accessed"].add(a["field"])
                if a.get("is_ptr_advance"):
                    v["has_ptr_advance"] = True
    return info


def finalize_sets(info):
    """Convert the in-place set fields to sorted lists so the dict is
    JSON-serializable. Mutates and returns info."""
    for v in info.values():
        v["kinds"] = sorted(v["kinds"])
        if "fields_accessed" in v:
            v["fields_accessed"] = sorted(v["fields_accessed"])
    return info


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ast_file")
    ap.add_argument("perf_file")
    args = ap.parse_args()

    with open(args.ast_file) as f:
        ast_data = json.load(f)
    with open(args.perf_file) as f:
        perf_data = json.load(f)

    if not perf_data:
        print("Warning: perf data is empty — profiling may have failed",
              file=sys.stderr)

    info = finalize_sets(correlate(ast_data.get("accesses", []), perf_data))

    print("=== Cache Misses by Variable ===", file=sys.stderr)
    for var, v in sorted(info.items(), key=lambda kv: -kv[1]["misses"]):
        print(f"{var}: {v['misses']}", file=sys.stderr)

    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
