"""Large struct where hot fields fit in one line but cold fields dominate."""

from .common import HOT_COLD_MIN_SIZE_LINES


def run(ctx):
    cache_line = ctx["cache_line"]
    threshold = ctx["miss_threshold"]

    for name, layout in ctx["structs"].items():
        size = layout.get("size", 0)
        if size <= HOT_COLD_MIN_SIZE_LINES * cache_line:
            continue

        heat = ctx["field_heat"].get(name, {})
        if not heat:
            continue

        hot = [f for f in layout["fields"] if heat.get(f["name"], 0) > threshold]
        cold = [f for f in layout["fields"] if heat.get(f["name"], 0) <= threshold]
        if not hot or not cold:
            continue

        hot_bytes = sum(f["size"] for f in hot)
        cold_bytes = sum(f["size"] for f in cold)
        if hot_bytes > cache_line or cold_bytes <= cache_line:
            continue

        yield {
            "severity": "MEDIUM",
            "pattern": "hot_cold_partition",
            "struct_type": name,
            "hot_fields": [f["name"] for f in hot],
            "cold_fields": [f["name"] for f in cold],
            "struct_size": size,
            "hot_size": hot_bytes,
            "cold_size": cold_bytes,
            "cache_misses": round(sum(heat.get(f["name"], 0) for f in hot)),
            "problem": (
                f"struct {name} is {size} bytes but only {hot_bytes} bytes "
                f"({', '.join(f['name'] for f in hot)}) are frequently "
                f"accessed. Each access loads {size - hot_bytes} bytes of "
                f"cold data."
            ),
            "fix": (
                f"Split into a hot struct ({', '.join(f['name'] for f in hot)}, "
                f"{hot_bytes} bytes) and a cold struct "
                f"({', '.join(f['name'] for f in cold)}, {cold_bytes} bytes). "
                f"Link cold data via pointer or parallel array."
            ),
        }
