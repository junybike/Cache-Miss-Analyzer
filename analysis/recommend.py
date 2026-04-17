"""Generate cache-optimization recommendations from AST + profiling data.

This module is the orchestrator: it loads inputs, builds a context dict,
runs every rule in `rules.RULES`, and prints/serializes the results.
"""

import argparse
import json

from rules import (
    RULES,
    compute_field_heat,
    compute_miss_threshold,
    detect_cache_line,
)

SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "SUSPECT": 2, "LOW": 3}


def build_ctx(ast_data, var_misses, perf_data, cache_line, miss_threshold):
    accesses = ast_data.get("accesses", [])
    hot_lines = {int(k): v for k, v in perf_data.items()}
    return {
        "accesses": accesses,
        "var_misses": var_misses,
        "structs": ast_data.get("structs", {}),
        "field_heat": compute_field_heat(accesses, hot_lines),
        "cache_line": cache_line,
        "miss_threshold": miss_threshold,
    }


def print_text(recs):
    if not recs:
        print("No cache optimization recommendations (all variables below threshold).")
        return
    print("=== Cache Optimization Recommendations ===\n")
    for r in recs:
        head = f"[{r['severity']}] {r['pattern']}"
        if "variable" in r:
            head += f" — variable: {r['variable']}"
            if r.get("struct_type"):
                head += f" ({r['struct_type']}*)"
        else:
            head += f" — struct: {r.get('struct_type', '?')}"
        if r.get("lines"):
            head += f", lines {', '.join(str(l) for l in r['lines'])}"
        print(head)
        print(f"  Problem: {r['problem']}")
        print(f"  Fix:     {r['fix']}")
        print(f"  Misses:  ~{r['cache_misses']}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ast_file")
    ap.add_argument("cache_file")
    ap.add_argument("perf_file")
    ap.add_argument("--json", action="store_true",
                    help="print JSON to stdout instead of text")
    ap.add_argument("--json-output", metavar="FILE",
                    help="also write JSON output to FILE")
    ap.add_argument("--cache-line", type=int,
                    help="cache line size in bytes (default: auto-detect)")
    ap.add_argument("--miss-threshold", type=int,
                    help="minimum cache misses to flag a variable "
                         "(default: max(50, 2%% of total))")
    args = ap.parse_args()

    with open(args.ast_file) as f:
        ast_data = json.load(f)
    with open(args.cache_file) as f:
        var_misses = json.load(f)
    with open(args.perf_file) as f:
        perf_data = json.load(f)

    ctx = build_ctx(
        ast_data, var_misses, perf_data,
        cache_line=args.cache_line or detect_cache_line(),
        miss_threshold=(args.miss_threshold if args.miss_threshold is not None
                        else compute_miss_threshold(var_misses)),
    )

    recs = [rec for rule in RULES for rec in rule(ctx)]
    recs.sort(key=lambda r: SEVERITY_ORDER.get(r["severity"], 99))

    if args.json:
        print(json.dumps({"recommendations": recs}, indent=2))
    else:
        print_text(recs)

    if args.json_output:
        with open(args.json_output, "w") as f:
            json.dump({"recommendations": recs}, f, indent=2)
            f.write("\n")


if __name__ == "__main__":
    main()
