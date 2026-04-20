#!/usr/bin/env python3
"""Compare before/after traces and produce summary metrics."""

import json
import sys
from pathlib import Path

TRACES_DIR = Path(__file__).resolve().parent / "traces"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

EXAMPLES = [
    "aos_vs_soa",
    "column_major",
    "hot_cold",
    "pointer_chase",
    "random_access",
    "shared_variable",
    "comprehensive",
]


def load_misses(trace_dir: Path) -> dict:
    vc = trace_dir / "variable_cache.json"
    if not vc.exists():
        return {}
    with open(vc) as f:
        data = json.load(f)
    return {var: info["misses"] for var, info in data.items()}


def load_runtime(trace_dir: Path) -> float | None:
    rt = trace_dir / "runtime_ms.txt"
    if not rt.exists():
        return None
    return float(rt.read_text().strip())


def pct_change(before: float, after: float) -> float:
    if before == 0:
        return 0.0
    return (before - after) / before * 100


def compare_example(name: str) -> dict | None:
    before_dir = TRACES_DIR / name / "before"
    after_dir = TRACES_DIR / name / "after"

    if not before_dir.exists():
        return None

    before_misses = load_misses(before_dir)
    before_runtime = load_runtime(before_dir)
    before_total = sum(before_misses.values())

    result = {
        "before": {
            "total_misses": before_total,
            "runtime_ms": before_runtime,
            "variables": before_misses,
        },
    }

    if not after_dir.exists():
        return result

    after_misses = load_misses(after_dir)
    after_runtime = load_runtime(after_dir)
    after_total = sum(after_misses.values())

    result["after"] = {
        "total_misses": after_total,
        "runtime_ms": after_runtime,
        "variables": after_misses,
    }
    result["reduction_pct"] = round(pct_change(before_total, after_total), 1)

    if before_runtime and after_runtime:
        result["speedup_pct"] = round(pct_change(before_runtime, after_runtime), 1)

    all_vars = sorted(set(before_misses) | set(after_misses))
    top = []
    for var in all_vars:
        b = before_misses.get(var, 0)
        a = after_misses.get(var, 0)
        if b > 0 or a > 0:
            top.append({
                "variable": var,
                "before": b,
                "after": a,
                "reduction_pct": round(pct_change(b, a), 1),
            })
    top.sort(key=lambda x: x["before"], reverse=True)
    result["top_variables"] = top

    return result


def print_table(summary: dict):
    print(f"\n{'Example':<20} {'Before':>10} {'After':>10} {'Miss Reduction':>16} {'Speedup':>10}")
    print("-" * 70)
    for name, data in summary["examples"].items():
        before = data["before"]["total_misses"]
        after_str = "-"
        reduction_str = "-"
        speedup_str = "-"

        if "after" in data:
            after_str = str(data["after"]["total_misses"])
            reduction_str = f"{data['reduction_pct']}%"
            if "speedup_pct" in data:
                speedup_str = f"{data['speedup_pct']}%"

        print(f"{name:<20} {before:>10} {after_str:>10} {reduction_str:>16} {speedup_str:>10}")

    if "overall" in summary:
        o = summary["overall"]
        print("-" * 70)
        print(f"{'AVERAGE':<20} {'':>10} {'':>10} {o['avg_miss_reduction_pct']:>15.1f}% {o.get('avg_speedup_pct', 0):>9.1f}%")


def main():
    summary = {"examples": {}}
    reductions = []
    speedups = []

    for name in EXAMPLES:
        result = compare_example(name)
        if result:
            summary["examples"][name] = result
            if "reduction_pct" in result:
                reductions.append(result["reduction_pct"])
            if "speedup_pct" in result:
                speedups.append(result["speedup_pct"])

    if reductions:
        summary["overall"] = {
            "avg_miss_reduction_pct": round(sum(reductions) / len(reductions), 1),
        }
        if speedups:
            summary["overall"]["avg_speedup_pct"] = round(sum(speedups) / len(speedups), 1)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "summary.json"
    with open(out, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Summary written to {out}")

    print_table(summary)


if __name__ == "__main__":
    main()
