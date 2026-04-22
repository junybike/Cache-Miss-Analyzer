#!/usr/bin/env python3
"""Compare before/after traces and produce summary metrics.

Legacy mode (default):  compares before/ vs after/ traces.
Grid mode (--grid):     compares baseline/ vs all (condition x model) cells.
"""

import argparse
import json
import math
import sys
from datetime import datetime
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

MODELS = ["haiku", "sonnet", "opus"]
CONDITIONS = ["blind", "tool_guided"]


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


def _detect_runs(cell_dir: Path) -> list[Path]:
    runs = sorted(cell_dir.glob("run_*/"))
    return runs if runs else [cell_dir]


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals)


def _stddev(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = _mean(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))


def _load_runs(cell_dir: Path) -> dict | None:
    """Load all runs from a cell directory and return averaged metrics."""
    runs = _detect_runs(cell_dir)
    totals = []
    runtimes = []
    failed_reasons = []

    for run_dir in runs:
        fail_file = run_dir / "FAILED.json"
        if fail_file.exists():
            fail_data = json.loads(fail_file.read_text())
            failed_reasons.append(fail_data.get("reason", "unknown"))
            continue
        misses = load_misses(run_dir)
        if not misses:
            continue
        totals.append(sum(misses.values()))
        rt = load_runtime(run_dir)
        if rt is not None:
            runtimes.append(rt)

    if not totals and failed_reasons:
        return {"status": "failed", "reason": failed_reasons[0],
                "num_runs": len(runs), "num_failed": len(failed_reasons)}

    if not totals:
        return None

    result = {
        "total_misses": round(_mean(totals)),
        "runtime_ms": round(_mean(runtimes), 1) if runtimes else None,
        "num_runs": len(totals),
        "status": "success",
    }
    if len(totals) >= 2:
        result["total_misses_std"] = round(_stddev(totals), 1)
    if len(runtimes) >= 2:
        result["runtime_ms_std"] = round(_stddev(runtimes), 1)
    if failed_reasons:
        result["num_failed"] = len(failed_reasons)
    return result


def compare_grid():
    summary = {
        "meta": {
            "models": MODELS,
            "conditions": CONDITIONS,
            "examples": EXAMPLES,
            "generated_at": datetime.now().isoformat(),
        },
        "baselines": {},
        "results": {},
        "failures": [],
        "aggregates": {},
    }

    for name in EXAMPLES:
        baseline_dir = TRACES_DIR / name / "baseline"
        if not baseline_dir.exists():
            continue

        baseline = _load_runs(baseline_dir)
        if not baseline or baseline.get("status") != "success":
            continue

        b_total = baseline["total_misses"]
        b_runtime = baseline.get("runtime_ms")
        summary["baselines"][name] = baseline

        summary["results"][name] = {}
        for condition in CONDITIONS:
            summary["results"][name][condition] = {}
            for model in MODELS:
                cell_dir = TRACES_DIR / name / f"{condition}_{model}"
                if not cell_dir.exists():
                    continue

                cell = _load_runs(cell_dir)
                if cell is None:
                    continue

                if cell.get("status") == "failed":
                    summary["results"][name][condition][model] = cell
                    summary["failures"].append({
                        "example": name, "condition": condition,
                        "model": model, "reason": cell.get("reason", "unknown"),
                    })
                    continue

                c_total = cell["total_misses"]
                c_runtime = cell.get("runtime_ms")
                cell["miss_reduction_pct"] = round(pct_change(b_total, c_total), 1)
                if b_runtime and c_runtime:
                    cell["speedup_pct"] = round(pct_change(b_runtime, c_runtime), 1)

                if "total_misses_std" in cell and b_total > 0:
                    cell["miss_reduction_pct_std"] = round(
                        cell["total_misses_std"] / b_total * 100, 1)
                if "runtime_ms_std" in cell and b_runtime:
                    cell["speedup_pct_std"] = round(
                        cell["runtime_ms_std"] / b_runtime * 100, 1)

                summary["results"][name][condition][model] = cell

    _compute_aggregates(summary)
    return summary


def _compute_aggregates(summary):
    by_model = {m: {"reductions": [], "speedups": []} for m in MODELS}
    by_condition = {c: {"reductions": [], "speedups": []} for c in CONDITIONS}
    by_mc = {}

    for name, conds in summary["results"].items():
        for condition, models in conds.items():
            for model, data in models.items():
                if data.get("status") != "success":
                    continue
                r = data.get("miss_reduction_pct", 0)
                s = data.get("speedup_pct")

                by_model[model]["reductions"].append(r)
                by_condition[condition]["reductions"].append(r)
                key = f"{model}_{condition}"
                by_mc.setdefault(key, {"reductions": [], "speedups": []})
                by_mc[key]["reductions"].append(r)

                if s is not None:
                    by_model[model]["speedups"].append(s)
                    by_condition[condition]["speedups"].append(s)
                    by_mc[key]["speedups"].append(s)

    def avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    def success_rate(model):
        total = sum(1 for conds in summary["results"].values()
                    for m_data in conds.values() if model in m_data)
        ok = sum(1 for conds in summary["results"].values()
                 for m_data in conds.values()
                 if model in m_data and m_data[model].get("status") == "success")
        return round(ok / total, 3) if total else 0

    summary["aggregates"] = {
        "by_model": {
            m: {
                "avg_miss_reduction_pct": avg(d["reductions"]),
                "avg_speedup_pct": avg(d["speedups"]),
                "success_rate": success_rate(m),
            }
            for m, d in by_model.items()
        },
        "by_condition": {
            c: {
                "avg_miss_reduction_pct": avg(d["reductions"]),
                "avg_speedup_pct": avg(d["speedups"]),
            }
            for c, d in by_condition.items()
        },
        "by_model_condition": {
            k: {
                "avg_miss_reduction_pct": avg(d["reductions"]),
                "avg_speedup_pct": avg(d["speedups"]),
            }
            for k, d in by_mc.items()
        },
    }


def print_grid_table(summary):
    col_w = 18
    cols = [(c, m) for c in CONDITIONS for m in MODELS]
    header_labels = [f"{c[:5]}_{m}" for c, m in cols]

    print(f"\n{'Example':<20} {'Baseline':>10}", end="")
    for label in header_labels:
        print(f" {label:>{col_w}}", end="")
    print()
    print("-" * (20 + 10 + (col_w + 1) * len(cols)))

    for name in EXAMPLES:
        baseline = summary["baselines"].get(name, {})
        b_total = baseline.get("total_misses", 0)
        print(f"{name:<20} {b_total:>10}", end="")

        for condition, model in cols:
            cell = summary["results"].get(name, {}).get(condition, {}).get(model, {})
            if cell.get("status") == "failed":
                print(f" {'FAIL':>{col_w}}", end="")
            elif cell.get("status") == "success":
                r = cell.get("miss_reduction_pct", 0)
                std = cell.get("miss_reduction_pct_std")
                if std is not None:
                    label = f"{r:+.1f}±{std:.1f}%"
                else:
                    label = f"{r:+.1f}%"
                print(f" {label:>{col_w}}", end="")
            else:
                print(f" {'-':>{col_w}}", end="")
        print()

    agg = summary.get("aggregates", {}).get("by_model_condition", {})
    if agg:
        print("-" * (20 + 10 + (col_w + 1) * len(cols)))
        print(f"{'AVERAGE':<20} {'':>10}", end="")
        for condition, model in cols:
            key = f"{model}_{condition}"
            val = agg.get(key, {}).get("avg_miss_reduction_pct")
            if val is not None:
                print(f" {f'{val:+.1f}%':>{col_w}}", end="")
            else:
                print(f" {'-':>{col_w}}", end="")
        print()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grid", action="store_true",
                    help="compare grid benchmark results instead of before/after")
    args = ap.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.grid:
        summary = compare_grid()
        out = RESULTS_DIR / "grid_summary.json"
        with open(out, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"Grid summary written to {out}")
        print_grid_table(summary)
        if summary["failures"]:
            print(f"\n{len(summary['failures'])} failures:")
            for fail in summary["failures"]:
                print(f"  {fail['example']} / {fail['condition']} / {fail['model']}: {fail['reason']}")
        return

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

    out = RESULTS_DIR / "summary.json"
    with open(out, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Summary written to {out}")

    print_table(summary)


if __name__ == "__main__":
    main()
