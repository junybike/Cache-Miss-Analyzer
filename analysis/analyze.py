import json, sys, argparse
from collections import defaultdict


def main():
    arg_parser = argparse.ArgumentParser(
        description="Correlate AST variable accesses with perf cache-miss data."
    )
    arg_parser.add_argument("ast_file", help="path to ast_accesses.json")
    arg_parser.add_argument("perf_file", help="path to perf_cache_lines.json")
    args = arg_parser.parse_args()

    with open(args.ast_file) as f:
        ast_data = json.load(f)

    if "accesses" not in ast_data:
        print("Error: AST JSON missing 'accesses' key", file=sys.stderr)
        sys.exit(1)
    if "structs" not in ast_data:
        print("Warning: AST JSON missing 'structs' key", file=sys.stderr)

    with open(args.perf_file) as f:
        perf_data = json.load(f)

    if not perf_data:
        print("Warning: perf data is empty — profiling may have failed", file=sys.stderr)

    # Map source lines to the AST accesses on that line
    line_to_vars = defaultdict(list)
    for acc in ast_data["accesses"]:
        line_to_vars[acc["line"]].append(acc)

    # Correlate perf miss counts with AST variable info
    var_info = {}

    for line_str, count in perf_data.items():
        line_number = int(line_str)
        if line_number not in line_to_vars:
            continue

        for acc in line_to_vars[line_number]:
            var = acc["var"]
            is_struct = acc["kind"] in ("struct_member", "aos_member")

            if var not in var_info:
                var_info[var] = {"misses": 0, "kinds": set()}
                if acc.get("element_type"):
                    var_info[var]["element_type"] = acc["element_type"]
                if acc.get("struct_type"):
                    var_info[var]["struct_type"] = acc["struct_type"]
                if is_struct:
                    var_info[var]["fields_accessed"] = set()
                    var_info[var]["has_ptr_advance"] = False

            var_info[var]["misses"] += count
            var_info[var]["kinds"].add(acc["kind"])

            if is_struct:
                if acc.get("field"):
                    var_info[var]["fields_accessed"].add(acc["field"])
                if acc.get("is_ptr_advance"):
                    var_info[var]["has_ptr_advance"] = True

    # Sets aren't JSON-serializable
    for info in var_info.values():
        info["kinds"] = sorted(info["kinds"])
        if "fields_accessed" in info:
            info["fields_accessed"] = sorted(info["fields_accessed"])

    # Human-readable summary on stderr, JSON on stdout
    print("=== Cache Misses by Variable ===", file=sys.stderr)
    for var, info in sorted(var_info.items(), key=lambda x: -x[1]["misses"]):
        print(f"{var}: {info['misses']}", file=sys.stderr)

    print(json.dumps(var_info, indent=2))


if __name__ == "__main__":
    main()
