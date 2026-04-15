"""
Generates a bar chart of cache miss counts per variable from variable_cache.json
Output: plot/images/miss_counts.png
"""

import json
import os
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

DATA_PATH = os.path.join(os.path.dirname(__file__), "../data/results/variable_cache.json")
OUT_PATH = os.path.join(os.path.dirname(__file__), "images/miss_counts.png")

# color mapping derived from miss count thresholds
def severity_color(misses):
    if misses >= 1000:
        return "#d62728"   # red (high miss)
    elif misses >= 200:
        return "#ff7f0e"   # orange (medium)
    else:
        return "#2ca02c"   # green (low)

def main():
    with open(DATA_PATH) as f:
        data = json.load(f)

    # sort variables by miss count (greatest -> lowest)
    variables = sorted(data.items(), key=lambda x: x[1]["misses"], reverse=True)
    names   = [v[0] for v in variables]
    counts  = [v[1]["misses"] for v in variables]
    colors  = [severity_color(c) for c in counts]

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(names, counts, color=colors, edgecolor="black", linewidth=0.6)

    # display exact counts on each bar
    for bar, count in zip(bars, counts):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(counts) * 0.01,
            str(count),
            ha="center", va="bottom", fontsize=9
        )

    ax.set_xlabel("Variable", fontsize=12)
    ax.set_ylabel("Cache Miss Count", fontsize=12)
    ax.set_title("Cache Miss Counts per Variable", fontsize=14)
    ax.set_ylim(0, max(counts) * 1.15)

    legend_handles = [
        mpatches.Patch(color="#d62728", label="HIGH  (≥ 1000 misses)"),
        mpatches.Patch(color="#ff7f0e", label="MEDIUM (≥ 200 misses)"),
        mpatches.Patch(color="#2ca02c", label="LOW   (< 200 misses)"),
    ]
    ax.legend(handles=legend_handles, loc="upper right", fontsize=9)

    plt.tight_layout()
    plt.savefig(OUT_PATH, dpi=150)
    print(f"Saved: {OUT_PATH}")

if __name__ == "__main__":
    main()
