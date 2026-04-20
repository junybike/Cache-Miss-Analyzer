#!/usr/bin/env python3
"""Generate benchmark visualizations from summary.json."""

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

RESULTS_DIR = Path(__file__).resolve().parent / "results"
SUMMARY = RESULTS_DIR / "summary.json"


def plot_miss_comparison(examples: dict, out: Path):
    names = []
    before_vals = []
    after_vals = []

    for name, data in examples.items():
        if "after" not in data:
            continue
        names.append(name.replace("_", "\n"))
        before_vals.append(data["before"]["total_misses"])
        after_vals.append(data["after"]["total_misses"])

    if not names:
        print("No before/after pairs to plot for miss comparison.")
        return

    x = np.arange(len(names))
    width = 0.35

    fig, ax = plt.subplots(figsize=(12, 6))
    bars_b = ax.bar(x - width / 2, before_vals, width, label="Before", color="#e74c3c")
    bars_a = ax.bar(x + width / 2, after_vals, width, label="After", color="#2ecc71")

    ax.set_ylabel("Total Cache Misses")
    ax.set_title("Cache Misses: Before vs After Optimization")
    ax.set_xticks(x)
    ax.set_xticklabels(names)
    ax.legend()
    ax.ticklabel_format(axis="y", style="scientific", scilimits=(0, 0))

    for bar_group in [bars_b, bars_a]:
        for bar in bar_group:
            h = bar.get_height()
            ax.annotate(f"{h:,.0f}", xy=(bar.get_x() + bar.get_width() / 2, h),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", va="bottom", fontsize=7)

    fig.tight_layout()
    fig.savefig(out, dpi=150)
    print(f"Saved {out}")
    plt.close(fig)


def plot_speedup(examples: dict, out: Path):
    names = []
    miss_reductions = []
    speedups = []

    for name, data in examples.items():
        if "reduction_pct" not in data:
            continue
        names.append(name.replace("_", "\n"))
        miss_reductions.append(data["reduction_pct"])
        speedups.append(data.get("speedup_pct", 0))

    if not names:
        print("No reduction data to plot.")
        return

    x = np.arange(len(names))
    width = 0.35

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.bar(x - width / 2, miss_reductions, width, label="Miss Reduction %", color="#3498db")
    ax.bar(x + width / 2, speedups, width, label="Runtime Speedup %", color="#f39c12")

    ax.set_ylabel("Improvement (%)")
    ax.set_title("Cache Miss Reduction and Runtime Speedup per Example")
    ax.set_xticks(x)
    ax.set_xticklabels(names)
    ax.legend()
    ax.axhline(y=0, color="black", linewidth=0.5)

    fig.tight_layout()
    fig.savefig(out, dpi=150)
    print(f"Saved {out}")
    plt.close(fig)


def main():
    if not SUMMARY.exists():
        print(f"No summary.json found at {SUMMARY}. Run compare.py first.", file=sys.stderr)
        sys.exit(1)

    with open(SUMMARY) as f:
        summary = json.load(f)

    examples = summary.get("examples", {})
    if not examples:
        print("No example data in summary.json.")
        return

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    plot_miss_comparison(examples, RESULTS_DIR / "miss_comparison.png")
    plot_speedup(examples, RESULTS_DIR / "speedup.png")


if __name__ == "__main__":
    main()
