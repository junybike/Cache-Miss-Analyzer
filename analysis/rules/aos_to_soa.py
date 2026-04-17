"""AoS->SoA: a hot loop over an array of structs where most fields are cold."""

from .common import (
    AOS_WASTE_THRESHOLD,
    FIELD_HEAT_RATIO,
    MIN_FIELDS_AOS,
    lines_of,
    misses_of,
    var_key,
)


def run(ctx):
    structs = ctx["structs"]
    heat_all = ctx["field_heat"]
    threshold = ctx["miss_threshold"]

    var_struct = {}
    var_access = {}
    for a in ctx["accesses"]:
        if a["kind"] == "aos_member" and a.get("in_loop"):
            key = var_key(a)
            var_struct[key] = a.get("struct_type", "")
            var_access[key] = a

    for key, stype in var_struct.items():
        layout = structs.get(stype)
        if not layout:
            continue

        a = var_access[key]
        heat = heat_all.get(stype, {})
        fields = layout["fields"]
        all_names = {f["name"] for f in fields}
        if len(all_names) < MIN_FIELDS_AOS:
            continue

        if sum(heat.values()) <= threshold:
            continue

        max_heat = max(heat.values()) if heat else 0
        hot = {f for f in all_names if heat.get(f, 0) > max_heat * FIELD_HEAT_RATIO}
        cold = all_names - hot

        sizes = {f["name"]: f["size"] for f in fields}
        hot_bytes = sum(sizes.get(f, 0) for f in hot)
        total_bytes = sum(sizes.values())
        waste = 1 - hot_bytes / total_bytes if total_bytes else 0

        misses = misses_of(ctx, a)
        if waste <= AOS_WASTE_THRESHOLD or misses <= threshold:
            continue

        yield {
            "severity": "MEDIUM",
            "pattern": "aos_to_soa",
            "variable": a["var"],
            "struct_type": stype,
            "fields_accessed": sorted(hot),
            "fields_not_accessed": sorted(cold),
            "lines": lines_of(ctx, a),
            "cache_misses": misses,
            "problem": (
                f"Hot fields ({', '.join(sorted(hot))}) account for most "
                f"cache misses but struct has {len(cold)} cold field(s) "
                f"({', '.join(sorted(cold))}). Each cache line loads "
                f"unused bytes."
            ),
            "fix": (
                f"Split into separate arrays per field "
                f"({', '.join(f'{f}[]' for f in sorted(hot))}). Access only "
                f"the relevant arrays in the hot loop."
            ),
        }
