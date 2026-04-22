#!/usr/bin/env python3
"""Generate benchmark visualizations from summary data.

Legacy mode (default):  reads summary.json, produces before/after plots.
Grid mode (--grid):     reads grid_summary.json, produces publication-quality plots.
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

RESULTS_DIR = Path(__file__).resolve().parent / "results"
SUMMARY = RESULTS_DIR / "summary.json"
GRID_SUMMARY = RESULTS_DIR / "grid_summary.json"

MODELS = ["haiku", "sonnet", "opus"]
CONDITIONS = ["blind", "tool_guided"]
CONDITION_LABELS = {"blind": "Blind", "tool_guided": "Tool-Guided"}
MODEL_LABELS = {"haiku": "Haiku", "sonnet": "Sonnet", "opus": "Opus"}

# Colorblind-safe palette: blues for blind, greens for tool_guided
# Lighter → darker = haiku → sonnet → opus
COLORS = {
    ("blind", "haiku"):        "#a6cee3",
    ("blind", "sonnet"):       "#1f78b4",
    ("blind", "opus"):         "#08306b",
    ("tool_guided", "haiku"):  "#b2df8a",
    ("tool_guided", "sonnet"): "#33a02c",
    ("tool_guided", "opus"):   "#00441b",
}


def _apply_style():
    plt.rcParams.update({
        "font.family": "serif",
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 0.8,
        "axes.grid": False,
        "xtick.direction": "out",
        "ytick.direction": "out",
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.1,
    })


def _save(fig, name):
    for ext in ("pdf", "png"):
        path = RESULTS_DIR / f"{name}.{ext}"
        fig.savefig(path)
    print(f"  Saved {name}.{{pdf,png}}")
    plt.close(fig)


def _short_name(name):
    return name.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Grid plots
# ---------------------------------------------------------------------------

def _load_grid():
    if not GRID_SUMMARY.exists():
        sys.exit(f"No grid_summary.json found at {GRID_SUMMARY}. Run: python benchmark/compare.py --grid")
    with open(GRID_SUMMARY) as f:
        return json.load(f)


def _grid_values(summary, metric="miss_reduction_pct"):
    examples = summary["meta"]["examples"]
    vals = {}
    stds = {}
    std_key = f"{metric}_std"
    for condition in CONDITIONS:
        for model in MODELS:
            key = (condition, model)
            vals[key] = []
            stds[key] = []
            for name in examples:
                cell = summary["results"].get(name, {}).get(condition, {}).get(model, {})
                if cell.get("status") == "success":
                    vals[key].append(cell.get(metric, 0))
                    stds[key].append(cell.get(std_key, 0))
                else:
                    vals[key].append(None)
                    stds[key].append(None)
    return examples, vals, stds


def _clamp_bars(ax, bars_list, y_min=-100, y_max=100):
    """Clamp y-axis and truncate bars that exceed the range."""
    ax.set_ylim(y_min * 1.1, y_max * 1.1)
    for bars, values in bars_list:
        for bar, val in zip(bars, values):
            if val is not None and (val < y_min or val > y_max):
                bar.set_height(y_min if val < y_min else y_max)


def plot_grid_miss_reduction(summary):
    """Grouped bar chart: miss reduction % by example, grouped by condition x model."""
    examples, vals, stds = _grid_values(summary, "miss_reduction_pct")
    n = len(examples)
    n_bars = len(CONDITIONS) * len(MODELS)
    width = 0.8 / n_bars
    x = np.arange(n)

    fig, ax = plt.subplots(figsize=(10, 5))

    all_bars = []
    for i, condition in enumerate(CONDITIONS):
        for j, model in enumerate(MODELS):
            idx = i * len(MODELS) + j
            key = (condition, model)
            raw = vals[key]
            raw_std = stds[key]
            values = [v if v is not None else 0 for v in raw]
            errs = [s if s is not None and s > 0 else 0 for s in raw_std]
            has_data = [v is not None for v in raw]
            offset = x - 0.4 + width * (idx + 0.5)
            bars = ax.bar(offset, values, width * 0.9,
                          yerr=errs if any(e > 0 for e in errs) else None,
                          capsize=2, error_kw={"linewidth": 0.8},
                          color=COLORS[key],
                          label=f"{CONDITION_LABELS[condition]} {MODEL_LABELS[model]}",
                          edgecolor="white", linewidth=0.3)
            all_bars.append((bars, raw))
            for bar, has in zip(bars, has_data):
                if not has:
                    bar.set_hatch("///")
                    bar.set_alpha(0.3)

    ax.set_ylabel("Cache Miss Reduction (%)")
    ax.set_title("Cache Miss Reduction by Example and Method")
    ax.set_xticks(x)
    ax.set_xticklabels([_short_name(e) for e in examples], rotation=30, ha="right", fontsize=9)
    ax.axhline(y=0, color="black", linewidth=0.5)
    ax.legend(fontsize=7, ncol=2, loc="upper right", bbox_to_anchor=(1.0, 1.0), framealpha=0.9)
    _clamp_bars(ax, all_bars)

    fig.tight_layout()
    _save(fig, "grid_miss_reduction")


def plot_grid_heatmap(summary):
    """Heatmap: examples (rows) x model x condition (columns)."""
    examples = summary["meta"]["examples"]
    columns = [(c, m) for c in CONDITIONS for m in MODELS]
    n_rows = len(examples)
    n_cols = len(columns)

    data = np.full((n_rows, n_cols), np.nan)
    status = [[None] * n_cols for _ in range(n_rows)]

    for i, name in enumerate(examples):
        for j, (condition, model) in enumerate(columns):
            cell = summary["results"].get(name, {}).get(condition, {}).get(model, {})
            if cell.get("status") == "success":
                data[i, j] = cell.get("miss_reduction_pct", 0)
                status[i][j] = "success"
            elif cell.get("status") == "failed":
                status[i][j] = "failed"

    fig, ax = plt.subplots(figsize=(8, 5))
    cmap = matplotlib.colormaps["RdYlGn"]
    cmap.set_bad(color="#d9d9d9")

    masked = np.ma.array(data, mask=np.isnan(data))
    vmax = max(abs(np.nanmin(data)) if not np.all(np.isnan(data)) else 50,
               abs(np.nanmax(data)) if not np.all(np.isnan(data)) else 50)
    im = ax.imshow(masked, cmap=cmap, aspect="auto", vmin=-vmax, vmax=vmax)

    for i in range(n_rows):
        for j in range(n_cols):
            if status[i][j] == "failed":
                ax.text(j, i, "F", ha="center", va="center",
                        fontsize=9, fontweight="bold", color="#666666")
            elif status[i][j] == "success":
                val = data[i, j]
                color = "white" if abs(val) > vmax * 0.6 else "black"
                ax.text(j, i, f"{val:.1f}%", ha="center", va="center",
                        fontsize=8, color=color)

    ax.set_xticks(range(n_cols))
    col_labels = [f"{CONDITION_LABELS[c]}\n{MODEL_LABELS[m]}" for c, m in columns]
    ax.set_xticklabels(col_labels, fontsize=8)
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels([_short_name(e) for e in examples], fontsize=9)

    ax.set_xticks([len(MODELS) - 0.5], minor=True)
    ax.tick_params(which="minor", length=0)
    ax.vlines(len(MODELS) - 0.5, -0.5, n_rows - 0.5, colors="black", linewidths=1.5)

    cb = fig.colorbar(im, ax=ax, shrink=0.8, label="Miss Reduction (%)")
    ax.set_title("Cache Miss Reduction Heatmap")

    fig.tight_layout()
    _save(fig, "grid_heatmap")


def plot_grid_tool_impact(summary):
    """3 subplots (one per model): blind vs tool_guided for each example."""
    examples = summary["meta"]["examples"]
    n = len(examples)
    x = np.arange(n)
    width = 0.35

    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5), sharey=True)

    for ax_i, model in enumerate(MODELS):
        ax = axes[ax_i]
        blind_vals = []
        guided_vals = []
        blind_errs = []
        guided_errs = []

        for name in examples:
            bc = summary["results"].get(name, {}).get("blind", {}).get(model, {})
            gc = summary["results"].get(name, {}).get("tool_guided", {}).get(model, {})
            blind_vals.append(bc.get("miss_reduction_pct", 0) if bc.get("status") == "success" else 0)
            guided_vals.append(gc.get("miss_reduction_pct", 0) if gc.get("status") == "success" else 0)
            blind_errs.append(bc.get("miss_reduction_pct_std", 0) if bc.get("status") == "success" else 0)
            guided_errs.append(gc.get("miss_reduction_pct_std", 0) if gc.get("status") == "success" else 0)

        has_errs = any(e > 0 for e in blind_errs + guided_errs)
        bars_b = ax.bar(x - width / 2, blind_vals, width,
               yerr=blind_errs if has_errs else None, capsize=2, error_kw={"linewidth": 0.8},
               color=COLORS[("blind", model)], label="Blind", edgecolor="white", linewidth=0.3)
        bars_g = ax.bar(x + width / 2, guided_vals, width,
               yerr=guided_errs if has_errs else None, capsize=2, error_kw={"linewidth": 0.8},
               color=COLORS[("tool_guided", model)], label="Tool-Guided", edgecolor="white", linewidth=0.3)

        ax.set_title(f"{MODEL_LABELS[model]}", fontsize=11, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels([_short_name(e) for e in examples], rotation=45, ha="right", fontsize=7)
        ax.axhline(y=0, color="black", linewidth=0.5)
        ax.set_ylim(-110, 110)
        for bars, raw_vals in [(bars_b, blind_vals), (bars_g, guided_vals)]:
            for bar, val in zip(bars, raw_vals):
                if val < -100 or val > 100:
                    bar.set_height(-100 if val < -100 else 100)
        if ax_i == 0:
            ax.set_ylabel("Cache Miss Reduction (%)")
        ax.legend(fontsize=7, loc="lower right")

    fig.suptitle("Tool Impact: Blind vs Tool-Guided by Model", fontsize=12, y=1.02)
    fig.tight_layout()
    _save(fig, "grid_tool_impact")


def plot_grid_runtime(summary):
    """Grouped bar chart: runtime speedup % by example, grouped by condition x model."""
    examples, vals, stds = _grid_values(summary, "speedup_pct")
    n = len(examples)
    n_bars = len(CONDITIONS) * len(MODELS)
    width = 0.8 / n_bars
    x = np.arange(n)

    fig, ax = plt.subplots(figsize=(10, 5))

    all_bars_rt = []
    for i, condition in enumerate(CONDITIONS):
        for j, model in enumerate(MODELS):
            idx = i * len(MODELS) + j
            key = (condition, model)
            raw = vals[key]
            raw_std = stds[key]
            values = [v if v is not None else 0 for v in raw]
            errs = [s if s is not None and s > 0 else 0 for s in raw_std]
            offset = x - 0.4 + width * (idx + 0.5)
            bars = ax.bar(offset, values, width * 0.9,
                          yerr=errs if any(e > 0 for e in errs) else None,
                          capsize=2, error_kw={"linewidth": 0.8},
                          color=COLORS[key],
                          label=f"{CONDITION_LABELS[condition]} {MODEL_LABELS[model]}",
                          edgecolor="white", linewidth=0.3)
            all_bars_rt.append((bars, raw))

    ax.set_ylabel("Runtime Speedup (%)")
    ax.set_title("Runtime Speedup by Example and Method")
    ax.set_xticks(x)
    ax.set_xticklabels([_short_name(e) for e in examples], rotation=30, ha="right", fontsize=9)
    ax.axhline(y=0, color="black", linewidth=0.5)
    ax.legend(fontsize=7, ncol=2, loc="upper right", bbox_to_anchor=(1.0, 1.0), framealpha=0.9)
    _clamp_bars(ax, all_bars_rt)

    fig.tight_layout()
    _save(fig, "grid_runtime")


def plot_grid_summary_box(summary):
    """Box plots: distribution of miss_reduction_pct per model x condition."""
    groups = []
    labels = []
    colors_list = []

    for condition in CONDITIONS:
        for model in MODELS:
            values = []
            for name in summary["meta"]["examples"]:
                cell = summary["results"].get(name, {}).get(condition, {}).get(model, {})
                if cell.get("status") == "success":
                    values.append(cell.get("miss_reduction_pct", 0))
            if values:
                groups.append(values)
                labels.append(f"{CONDITION_LABELS[condition]}\n{MODEL_LABELS[model]}")
                colors_list.append(COLORS[(condition, model)])

    if not groups:
        print("  No data for box plots.")
        return

    clamped_groups = [[max(-100, min(100, v)) for v in g] for g in groups]

    fig, ax = plt.subplots(figsize=(8, 5))
    bp = ax.boxplot(clamped_groups, patch_artist=True, widths=0.6, medianprops={"color": "black", "linewidth": 1.5})
    for patch, color in zip(bp["boxes"], colors_list):
        patch.set_facecolor(color)
        patch.set_alpha(0.8)

    for i, vals in enumerate(clamped_groups):
        jitter = np.random.default_rng(42).uniform(-0.15, 0.15, len(vals))
        ax.scatter(np.full(len(vals), i + 1) + jitter, vals,
                   color="black", alpha=0.5, s=15, zorder=3)

    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("Cache Miss Reduction (%)")
    ax.set_title("Distribution of Cache Miss Reduction Across Examples")
    ax.axhline(y=0, color="black", linewidth=0.5, linestyle="--")
    ax.set_ylim(-110, 110)

    n_models = len(MODELS)
    ax.axvline(x=n_models + 0.5, color="gray", linewidth=0.8, linestyle=":")

    fig.tight_layout()
    _save(fig, "grid_summary_box")


# ---------------------------------------------------------------------------
# Legacy plots (before/after)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grid", action="store_true",
                    help="generate grid benchmark plots instead of before/after")
    ap.add_argument("--plot", choices=["miss_reduction", "heatmap", "tool_impact",
                                        "runtime", "summary_box"],
                    help="(grid mode) generate a single plot instead of all")
    args = ap.parse_args()

    _apply_style()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.grid:
        summary = _load_grid()
        grid_plots = {
            "miss_reduction": plot_grid_miss_reduction,
            "heatmap":        plot_grid_heatmap,
            "tool_impact":    plot_grid_tool_impact,
            "runtime":        plot_grid_runtime,
            "summary_box":    plot_grid_summary_box,
        }
        if args.plot:
            print(f"Generating {args.plot}...")
            grid_plots[args.plot](summary)
        else:
            print("Generating all grid plots...")
            for name, fn in grid_plots.items():
                print(f"  {name}...")
                fn(summary)
        print("Done.")
        return

    if not SUMMARY.exists():
        print(f"No summary.json found at {SUMMARY}. Run compare.py first.", file=sys.stderr)
        sys.exit(1)

    with open(SUMMARY) as f:
        summary = json.load(f)

    examples = summary.get("examples", {})
    if not examples:
        print("No example data in summary.json.")
        return

    plot_miss_comparison(examples, RESULTS_DIR / "miss_comparison.png")
    plot_speedup(examples, RESULTS_DIR / "speedup.png")


if __name__ == "__main__":
    main()
