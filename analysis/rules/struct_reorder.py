"""Hot fields spread across >1 cache line due to interleaved cold fields."""


def run(ctx):
    cache_line = ctx["cache_line"]
    threshold = ctx["miss_threshold"]

    for name, layout in ctx["structs"].items():
        heat = ctx["field_heat"].get(name, {})
        hot = [f for f in layout["fields"] if heat.get(f["name"], 0) > threshold]
        if len(hot) < 2:
            continue

        offsets = [f["offset"] for f in hot]
        span = max(offsets) - min(offsets)
        if span < cache_line:
            continue

        cold = [f["name"] for f in layout["fields"]
                if heat.get(f["name"], 0) <= threshold]

        yield {
            "severity": "LOW",
            "pattern": "struct_reorder",
            "struct_type": name,
            "hot_fields": [f["name"] for f in hot],
            "cold_fields": cold,
            "struct_size": layout.get("size", 0),
            "cache_misses": round(sum(heat.get(f["name"], 0) for f in hot)),
            "problem": (
                f"Hot fields ({', '.join(f['name'] for f in hot)}) are "
                f"separated by cold fields, spanning {span} bytes "
                f"(>{cache_line}-byte cache line)."
            ),
            "fix": (
                f"Move hot fields to the top of struct {name}; move cold "
                f"fields ({', '.join(cold)}) to the end."
            ),
        }
