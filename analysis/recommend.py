import json, argparse, subprocess
from collections import defaultdict

# A field is "hot" if its misses exceed this fraction of the hottest field
FIELD_HEAT_RATIO = 0.2
# AoS rule fires when this fraction of struct fields are unused in the hot loop
AOS_WASTE_THRESHOLD = 0.4
# Struct needs at least this many fields before AoS→SoA is worth suggesting
MIN_FIELDS_AOS = 2
# Struct must span this many cache lines to consider a hot/cold split
HOT_COLD_MIN_SIZE_LINES = 2
# Absolute floor: ignore variables with fewer misses than this
MISS_FLOOR = 50
# Variable must cause at least this fraction of total misses to be flagged
MISS_RATIO_OF_TOTAL = 0.02
# Fallback L1 data cache line size when getconf auto-detection fails
DEFAULT_CACHE_LINE = 64


def detect_cache_line():
    """Query the system for L1 data cache line size"""
    try:
        result = subprocess.run(
            ["getconf", "LEVEL1_DCACHE_LINESIZE"],
            capture_output=True, text=True, timeout=5,
        )
        value = int(result.stdout.strip())
        if value > 0:
            return value
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return DEFAULT_CACHE_LINE


def compute_miss_threshold(var_misses):
    """Adaptive threshold: absolute floor or percentage of total misses, whichever is larger.

    Using total misses (not max) prevents a single dominant variable from
    pushing the threshold up and masking other significant issues."""
    if not var_misses:
        return 0
    total_misses = sum(v.get("misses", 0) for v in var_misses.values())
    return max(MISS_FLOOR, int(total_misses * MISS_RATIO_OF_TOTAL))


def get_misses(var_misses, var):
    return var_misses.get(var, {}).get("misses", 0)


def collect_lines(accesses, var):
    return sorted({acc["line"] for acc in accesses if acc["var"] == var})


def compute_field_heat(accesses, var_misses, hot_lines):
    """Map struct_type -> field_name -> total attributed misses.
    Only counts accesses on lines that actually had cache misses.
    When multiple field accesses share a line, misses are split evenly."""
    # Count field accesses per line so we can split misses fairly
    line_field_count = defaultdict(int)
    for acc in accesses:
        if acc["kind"] in ("struct_member", "aos_member") and acc.get("field"):
            if acc["line"] in hot_lines:
                line_field_count[acc["line"]] += 1

    heat = defaultdict(lambda: defaultdict(float))
    for acc in accesses:
        if acc["kind"] in ("struct_member", "aos_member") and acc.get("field"):
            if acc["line"] not in hot_lines:
                continue
            line_misses = hot_lines[acc["line"]]
            share = line_field_count[acc["line"]]
            heat[acc.get("struct_type", "")][acc["field"]] += line_misses / share
    return heat


# Rule 1: linked-list pointer chasing in loops
def rule_pointer_chasing(accesses, var_misses, miss_threshold):
    seen = set()
    for acc in accesses:
        if (acc["kind"] == "struct_member"
                and acc.get("in_loop")
                and acc.get("is_ptr_advance")
                and acc["var"] not in seen):
            misses = get_misses(var_misses, acc["var"])
            if misses > miss_threshold:
                seen.add(acc["var"])
                yield {
                    "severity": "HIGH",
                    "pattern": "pointer_chasing",
                    "variable": acc["var"],
                    "struct_type": acc.get("struct_type", ""),
                    "lines": collect_lines(accesses, acc["var"]),
                    "cache_misses": misses,
                    "problem": (
                        f"Each node is separately heap-allocated. "
                        f"Traversing {acc['var']}->{acc['field']} causes "
                        f"a cache miss per node since nodes are scattered in memory."
                    ),
                    "fix": (
                        f"Replace linked list with std::vector<{acc.get('struct_type', 'T')}> "
                        f"and integer next indices, or use a pool allocator to keep nodes contiguous."
                    ),
                }


# Rule 2: Array-of-Structs where few fields dominate cache misses
def rule_aos_to_soa(accesses, var_misses, structs, field_heat, miss_threshold):
    # Group variables by struct type
    var_struct = {}
    var_lines = defaultdict(set)

    for acc in accesses:
        if acc["kind"] == "aos_member" and acc.get("in_loop"):
            var_struct[acc["var"]] = acc.get("struct_type", "")
            var_lines[acc["var"]].add(acc["line"])

    for var, struct_type in var_struct.items():
        if struct_type not in structs:
            continue

        heat = field_heat.get(struct_type, {})
        all_fields = {f["name"] for f in structs[struct_type]["fields"]}
        if len(all_fields) < MIN_FIELDS_AOS:
            continue

        # A field is "hot" if its misses are significant relative to the
        # hottest field. Using 20% of max (not total) so that init-loop
        # noise doesn't inflate the count, while cache-adjacent fields
        # (fewer samples due to shared cache lines) are still included.
        #
        # Two thresholds: total_heat filters structs with negligible aggregate
        # misses; per-variable misses (below) filters variables that aren't
        # individually significant.
        total_heat = sum(heat.values())
        if total_heat <= miss_threshold:
            continue

        max_heat = max(heat.values()) if heat else 0
        hot_fields = {f for f in all_fields if heat.get(f, 0) > max_heat * FIELD_HEAT_RATIO}
        cold_fields = all_fields - hot_fields

        # Byte-weighted waste: a struct with 3 hot 4-byte fields and 1 cold
        # 256-byte field should show high waste, not 25% by field count.
        field_sizes = {f["name"]: f["size"] for f in structs[struct_type]["fields"]}
        hot_bytes = sum(field_sizes.get(f, 0) for f in hot_fields)
        total_bytes = sum(field_sizes.values())
        waste = 1 - hot_bytes / total_bytes if total_bytes > 0 else 0
        misses = get_misses(var_misses, var)

        if waste > AOS_WASTE_THRESHOLD and misses > miss_threshold:
            yield {
                "severity": "MEDIUM",
                "pattern": "aos_to_soa",
                "variable": var,
                "struct_type": struct_type,
                "fields_accessed": sorted(hot_fields),
                "fields_not_accessed": sorted(cold_fields),
                "lines": sorted(var_lines[var]),
                "cache_misses": misses,
                "problem": (
                    f"Hot fields ({', '.join(sorted(hot_fields))}) account for "
                    f"most cache misses but struct has {len(cold_fields)} cold "
                    f"field(s) ({', '.join(sorted(cold_fields))}). "
                    f"Each cache line loads unused bytes."
                ),
                "fix": (
                    f"Split into separate arrays per field "
                    f"({', '.join(f'{f}[]' for f in sorted(hot_fields))}). "
                    f"Access only the relevant arrays in the hot loop."
                ),
            }


# Rule 3: hot fields span multiple cache lines due to interleaved cold fields
def rule_struct_reorder(accesses, var_misses, structs, field_heat, cache_line, miss_threshold):
    for struct_name, layout in structs.items():
        heat = field_heat.get(struct_name, {})
        hot = [f for f in layout["fields"]
               if heat.get(f["name"], 0) > miss_threshold]

        if len(hot) < 2:
            continue

        offsets = [f["offset"] for f in hot]
        span = max(offsets) - min(offsets)

        if span >= cache_line:
            cold = [f["name"] for f in layout["fields"]
                    if heat.get(f["name"], 0) <= miss_threshold]
            yield {
                "severity": "LOW",
                "pattern": "struct_reorder",
                "struct_type": struct_name,
                "hot_fields": [f["name"] for f in hot],
                "cold_fields": cold,
                "struct_size": layout.get("size", 0),
                "cache_misses": round(sum(heat.get(f["name"], 0) for f in hot)),
                "problem": (
                    f"Hot fields ({', '.join(f['name'] for f in hot)}) "
                    f"are separated by cold fields, spanning {span} bytes "
                    f"(>{cache_line}-byte cache line)."
                ),
                "fix": (
                    f"Move hot fields to the top of struct {struct_name}; "
                    f"move cold fields ({', '.join(cold)}) to the end."
                ),
            }


# Rule 4: large struct where hot fields fit in one cache line but cold fields dominate
def rule_hot_cold_partition(accesses, var_misses, structs, field_heat, cache_line, miss_threshold):
    for struct_name, layout in structs.items():
        struct_size = layout.get("size", 0)
        if struct_size <= HOT_COLD_MIN_SIZE_LINES * cache_line:
            continue

        heat = field_heat.get(struct_name, {})
        if not heat:
            continue

        hot = [f for f in layout["fields"]
               if heat.get(f["name"], 0) > miss_threshold]
        cold = [f for f in layout["fields"]
                if heat.get(f["name"], 0) <= miss_threshold]

        if not hot or not cold:
            continue

        hot_size = sum(f["size"] for f in hot)
        cold_size = sum(f["size"] for f in cold)

        if hot_size <= cache_line and cold_size > cache_line:
            yield {
                "severity": "MEDIUM",
                "pattern": "hot_cold_partition",
                "struct_type": struct_name,
                "hot_fields": [f["name"] for f in hot],
                "cold_fields": [f["name"] for f in cold],
                "struct_size": struct_size,
                "hot_size": hot_size,
                "cold_size": cold_size,
                "cache_misses": round(sum(heat.get(f["name"], 0) for f in hot)),
                "problem": (
                    f"struct {struct_name} is {struct_size} bytes but only "
                    f"{hot_size} bytes ({', '.join(f['name'] for f in hot)}) "
                    f"are frequently accessed. Each access loads {struct_size - hot_size} "
                    f"bytes of cold data into cache."
                ),
                "fix": (
                    f"Split into a hot struct ({', '.join(f['name'] for f in hot)}, "
                    f"{hot_size} bytes) and a cold struct "
                    f"({', '.join(f['name'] for f in cold)}, {cold_size} bytes). "
                    f"Link cold data via pointer or parallel array."
                ),
            }


# Rule 5: column-major / strided traversal of row-major arrays
def rule_strided_access(accesses, var_misses, miss_threshold):
    seen = set()
    for acc in accesses:
        if acc["kind"] != "strided":
            continue

        var = acc["var"]
        if var in seen:
            continue

        misses = get_misses(var_misses, var)
        if misses > miss_threshold:
            seen.add(var)
            yield {
                "severity": "HIGH",
                "pattern": "strided_access",
                "variable": var,
                "lines": collect_lines(accesses, var),
                "cache_misses": misses,
                "problem": (
                    f"Array '{var}' is traversed column-major "
                    f"(row index varies in the inner loop). Each access jumps "
                    f"by an entire row, missing cache on nearly every read."
                ),
                "fix": (
                    f"Swap the loop nesting so the last array dimension "
                    f"varies in the innermost loop, or transpose the data layout."
                ),
            }


# Rule 6: indirect / random access via index array
def rule_random_access(accesses, var_misses, miss_threshold):
    seen = set()
    for acc in accesses:
        if acc["kind"] not in ("indirect_array", "indirect_vector"):
            continue
        if not acc.get("in_loop"):
            continue

        var = acc["var"]
        if var in seen:
            continue

        misses = get_misses(var_misses, var)
        if misses > miss_threshold:
            seen.add(var)
            yield {
                "severity": "HIGH",
                "pattern": "random_access",
                "variable": var,
                "lines": collect_lines(accesses, var),
                "cache_misses": misses,
                "problem": (
                    f"Array '{var}' is accessed through an index array "
                    f"(indirect access). If indices are non-sequential, each "
                    f"access can land on a different cache line."
                ),
                "fix": (
                    f"Sort the index array to improve spatial locality, or "
                    f"copy needed elements into a contiguous temporary buffer "
                    f"before processing."
                ),
            }


def print_recommendations(recs):
    if not recs:
        print("No cache optimization recommendations (all variables below threshold).")
        return

    print("=== Cache Optimization Recommendations ===\n")
    for rec in recs:
        sev = rec["severity"]
        pattern = rec["pattern"]

        if "variable" in rec:
            header = f"[{sev}] {pattern} — variable: {rec['variable']}"
            if rec.get("struct_type"):
                header += f" ({rec['struct_type']}*)"
        else:
            header = f"[{sev}] {pattern} — struct: {rec.get('struct_type', '?')}"

        if rec.get("lines"):
            header += f", lines {', '.join(str(l) for l in rec['lines'])}"

        print(header)
        print(f"  Problem: {rec['problem']}")
        print(f"  Fix:     {rec['fix']}")
        print(f"  Misses:  ~{rec['cache_misses']}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Generate cache optimization recommendations from AST and profiling data."
    )
    parser.add_argument("ast_file", help="path to ast_accesses.json")
    parser.add_argument("cache_file", help="path to variable_cache.json")
    parser.add_argument("perf_file", help="path to perf_cache_lines.json")
    parser.add_argument("--json", action="store_true",
                        help="output machine-readable JSON instead of text")
    parser.add_argument("--json-output", metavar="FILE", default=None,
                        help="also write JSON output to FILE (alongside text on stdout)")
    parser.add_argument("--cache-line", type=int, default=None,
                        help="cache line size in bytes (default: auto-detect from system)")
    parser.add_argument("--miss-threshold", type=int, default=None,
                        help="minimum cache misses to flag a variable (default: max(50, 2%% of total))")
    args = parser.parse_args()

    with open(args.ast_file) as f:
        ast_data = json.load(f)

    with open(args.cache_file) as f:
        var_misses = json.load(f)

    with open(args.perf_file) as f:
        perf_data = json.load(f)

    cache_line = args.cache_line if args.cache_line is not None else detect_cache_line()
    miss_threshold = args.miss_threshold if args.miss_threshold is not None else compute_miss_threshold(var_misses)

    # Convert string line keys to ints
    hot_lines = {int(k): v for k, v in perf_data.items()}

    accesses = ast_data["accesses"]
    structs = ast_data.get("structs", {})
    field_heat = compute_field_heat(accesses, var_misses, hot_lines)

    recommendations = []
    recommendations.extend(rule_pointer_chasing(accesses, var_misses, miss_threshold))
    recommendations.extend(rule_aos_to_soa(accesses, var_misses, structs, field_heat, miss_threshold))
    recommendations.extend(rule_struct_reorder(accesses, var_misses, structs, field_heat, cache_line, miss_threshold))
    recommendations.extend(rule_hot_cold_partition(accesses, var_misses, structs, field_heat, cache_line, miss_threshold))
    recommendations.extend(rule_strided_access(accesses, var_misses, miss_threshold))
    recommendations.extend(rule_random_access(accesses, var_misses, miss_threshold))

    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    recommendations.sort(key=lambda r: severity_order.get(r["severity"], 99))

    if args.json:
        print(json.dumps({"recommendations": recommendations}, indent=2))
    else:
        print_recommendations(recommendations)

    if args.json_output:
        with open(args.json_output, "w") as f:
            json.dump({"recommendations": recommendations}, f, indent=2)
            f.write("\n")


if __name__ == "__main__":
    main()
