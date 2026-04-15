"""
Generates a two-panel chart visualizing hot vs cold fields from recommendations.json

Panel 1: Struct memory split - hot vs cold byte sizes (from hot_cold_partition entries)
Panel 2: Hot vs cold field counts per struct (from aos_to_soa entries)

Output: plot/images/hot_cold_fields.png
"""

import json
import os
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

DATA_PATH = os.path.join(os.path.dirname(__file__), "../data/results/recommendations.json")
OUT_PATH  = os.path.join(os.path.dirname(__file__), "images/hot_cold_fields.png")

HOT_COLOR  = "#d62728"   # red
COLD_COLOR = "#1f77b4"   # blue

def main():
    with open(DATA_PATH) as f:
        data = json.load(f)

    recommendations = data["recommendations"]

    # collect hot_cold_partition entries (in byte sizes)
    partition_entries = [
        r for r in recommendations if r.get("pattern") == "hot_cold_partition"
    ]

    # collect aos_to_soa entries (field lists)
    aos_entries = [
        r for r in recommendations if r.get("pattern") == "aos_to_soa"
    ]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle("Hot vs Cold Field Analysis", fontsize=15, fontweight="bold", y=1.01)

    # first panel for struct byte sizes (hot vs cold)
    structs_p   = [r["struct_type"] for r in partition_entries]
    hot_sizes   = [r["hot_size"]    for r in partition_entries]
    cold_sizes  = [r["cold_size"]   for r in partition_entries]
    total_sizes = [r["struct_size"] for r in partition_entries]

    y_pos = range(len(structs_p))

    ax1.barh(y_pos, hot_sizes,  color=HOT_COLOR,  label="Hot bytes",  edgecolor="black", linewidth=0.6)
    ax1.barh(y_pos, cold_sizes, left=hot_sizes, color=COLD_COLOR, label="Cold bytes", edgecolor="black", linewidth=0.6)

    # annotate each bar with the field names
    for i, r in enumerate(partition_entries):
        hot_label  = ", ".join(r["hot_fields"])
        cold_label = ", ".join(r["cold_fields"])
        pct_cold   = r["cold_size"] / r["struct_size"] * 100

        ax1.text(
            r["hot_size"] / 2, i,
            hot_label,
            ha="center", va="center", fontsize=8, color="white", fontweight="bold"
        )
        ax1.text(
            r["hot_size"] + r["cold_size"] / 2, i,
            f"{cold_label}\n({pct_cold:.0f}% of struct)",
            ha="center", va="center", fontsize=7.5, color="white"
        )

        # total size label on the right
        ax1.text(
            r["struct_size"] + max(total_sizes) * 0.01, i,
            f"{r['struct_size']} B  |  {r['cache_misses']} misses",
            va="center", fontsize=8.5
        )

    ax1.set_yticks(list(y_pos))
    ax1.set_yticklabels(structs_p, fontsize=10)
    ax1.set_xlabel("Bytes", fontsize=11)
    ax1.set_title("Struct Memory: Hot vs Cold Bytes", fontsize=12)
    ax1.set_xlim(0, max(total_sizes) * 1.45)
    ax1.legend(loc="lower right", fontsize=9)
    ax1.invert_yaxis()

    # second panel for field counts per struct (hot vs cold)
    # deduplicate by struct_type, keeping first occurrence
    seen = {}
    for r in aos_entries:
        st = r.get("struct_type", r.get("variable", "?"))
        if st not in seen:
            seen[st] = r

    structs_a  = list(seen.keys())
    hot_counts  = [len(seen[s]["fields_accessed"])     for s in structs_a]
    cold_counts = [len(seen[s]["fields_not_accessed"]) for s in structs_a]
    misses_a    = [seen[s]["cache_misses"]             for s in structs_a]

    x = range(len(structs_a))
    bar_w = 0.35

    bars_hot  = ax2.bar([i - bar_w/2 for i in x], hot_counts,  bar_w,
                        color=HOT_COLOR,  label="Hot fields",  edgecolor="black", linewidth=0.6)
    bars_cold = ax2.bar([i + bar_w/2 for i in x], cold_counts, bar_w,
                        color=COLD_COLOR, label="Cold fields", edgecolor="black", linewidth=0.6)

    # count labels on bars
    for bar in bars_hot:
        ax2.text(bar.get_x() + bar.get_width() / 2,
                 bar.get_height() + 0.08,
                 str(int(bar.get_height())),
                 ha="center", va="bottom", fontsize=9, fontweight="bold")
    for bar in bars_cold:
        ax2.text(bar.get_x() + bar.get_width() / 2,
                 bar.get_height() + 0.08,
                 str(int(bar.get_height())),
                 ha="center", va="bottom", fontsize=9, fontweight="bold")

    # annotate with miss count below x-axis label
    ax2.set_xticks(list(x))
    ax2.set_xticklabels(
        [f"{s}\n({misses_a[i]:,} misses)" for i, s in enumerate(structs_a)],
        fontsize=10
    )

    # field name annotations inside bars
    for i, s in enumerate(structs_a):
        r = seen[s]
        ax2.text(i - bar_w/2, hot_counts[i] / 2,
                 "\n".join(r["fields_accessed"]),
                 ha="center", va="center", fontsize=7, color="white", fontweight="bold")
        ax2.text(i + bar_w/2, cold_counts[i] / 2,
                 "\n".join(r["fields_not_accessed"]),
                 ha="center", va="center", fontsize=7, color="white")

    ax2.set_ylabel("Number of Fields", fontsize=11)
    ax2.set_title("Hot vs Cold Field Counts per Struct", fontsize=12)
    ax2.set_ylim(0, max(hot_counts + cold_counts) * 1.3)
    ax2.legend(loc="upper right", fontsize=9)

    plt.tight_layout()
    plt.savefig(OUT_PATH, dpi=150, bbox_inches="tight")
    print(f"Saved: {OUT_PATH}")

if __name__ == "__main__":
    main()
