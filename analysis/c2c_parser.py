"""Parse perf-c2c report output to extract HITM (cache-to-cache transfer) data.

perf c2c tracks Hardware Invalidated To Modified (HITM) events, which are the
hardware signal for false/true sharing between threads.

CLI usage:
    # Parse a pre-generated report text file:
    python3 c2c_parser.py report.txt

    # Run perf c2c on an existing perf.data and parse inline:
    python3 c2c_parser.py perf.data --run [--binary <elf>]

    # Write JSON output:
    python3 c2c_parser.py report.txt --output data/perf/c2c_report.json
"""

import argparse
import json
import re
import subprocess
import sys

# Matches rows in the "Shared Data Cache Line Table":
# index  0x<addr>  ...  <hitm_pct>%  <hitm>  <lcl>  <rmt>
_ROW_RE = re.compile(
    r"^\s*(\d+)\s+(0x[0-9a-fA-F]+)\s+\S+\s+\d+\s+\S+\s+(\d+\.\d+)%\s+(\d+)\s+(\d+)\s+(\d+)",
    re.MULTILINE,
)
_TOTAL_RECORDS_RE = re.compile(r"Total records\s*:\s*(\d+)")
_TOTAL_HITM_RE    = re.compile(r"Total[^\n]*[Hh]itm\s*:\s*(\d+)")



# Parse perf c2c report --stdio text.
# Returns a dict:
#     total_records   int   — total perf samples
#     total_hitm      int   — total HITM events across all shared lines
#     cache_lines     list  — one entry per shared cache line: {index, address, hitm_pct, hitm, lcl, rmt}
#     hitm_by_address dict  — "0x..." -> hitm count
#     hitm_by_line    dict  — source line (int) -> hitm count  (populated by map_addresses_to_lines; empty when not resolved)
def parse_c2c_report(text):
    
    data = {
        "total_records": 0,
        "total_hitm": 0,
        "cache_lines": [],
        "hitm_by_address": {},
        "hitm_by_line": {},
    }

    m = _TOTAL_RECORDS_RE.search(text)
    if m:
        data["total_records"] = int(m.group(1))

    m = _TOTAL_HITM_RE.search(text)
    if m:
        data["total_hitm"] = int(m.group(1))

    for m in _ROW_RE.finditer(text):
        entry = {
            "index":    int(m.group(1)),
            "address":  m.group(2),
            "hitm_pct": float(m.group(3)),
            "hitm":     int(m.group(4)),
            "lcl":      int(m.group(5)),
            "rmt":      int(m.group(6)),
        }
        data["cache_lines"].append(entry)
        data["hitm_by_address"][entry["address"]] = entry["hitm"]

    return data


def map_addresses_to_lines(data, binary):
    """Resolve cache-line addresses to source line numbers via addr2line. 
    Adds/updates data["hitm_by_line"] in-place and returns data. """
    
    addresses = [cl["address"] for cl in data["cache_lines"]]
    if not addresses:
        return data

    try:
        proc = subprocess.run(
            ["addr2line", "-e", binary, "-f", "-s"] + addresses,
            capture_output=True, text=True, timeout=30,
        )
        lines = proc.stdout.strip().splitlines()
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"Warning: addr2line failed: {exc}", file=sys.stderr)
        return data

    hitm_by_line = {}
    for i, addr in enumerate(addresses):
        fn_idx  = i * 2
        loc_idx = i * 2 + 1
        if loc_idx >= len(lines):
            continue
        loc = lines[loc_idx]
        if ":" not in loc or "?" in loc:
            continue
        try:
            lineno = int(loc.rsplit(":", 1)[1])
        except ValueError:
            continue
        hitm_by_line[lineno] = (
            hitm_by_line.get(lineno, 0) + data["hitm_by_address"].get(addr, 0)
        )

    data["hitm_by_line"] = hitm_by_line
    return data


def run_c2c(perf_data_file, binary=None):
    """Run `perf c2c report --stdio` on perf_data_file and return parsed data."""
    try:
        proc = subprocess.run(
            ["perf", "c2c", "report", "--stdio", "-i", perf_data_file],
            capture_output=True, text=True, timeout=120,
        )
        text = proc.stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"Warning: perf c2c failed: {exc}", file=sys.stderr)
        return _empty()

    data = parse_c2c_report(text)
    if binary:
        map_addresses_to_lines(data, binary)
    return data


def load(path):
    """Load and parse a pre-generated perf c2c report text file."""
    try:
        with open(path) as f:
            text = f.read()
    except OSError as exc:
        print(f"Warning: cannot read c2c report {path!r}: {exc}", file=sys.stderr)
        return _empty()
    return parse_c2c_report(text)


def _empty():
    return {
        "total_records": 0,
        "total_hitm": 0,
        "cache_lines": [],
        "hitm_by_address": {},
        "hitm_by_line": {},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="perf c2c report text file (or perf.data with --run)")
    ap.add_argument("--run", action="store_true",
                    help="treat INPUT as perf.data and invoke perf c2c report")
    ap.add_argument("--binary", metavar="ELF",
                    help="compiled binary for addr2line address resolution")
    ap.add_argument("--output", "-o", metavar="FILE",
                    help="write JSON to FILE instead of stdout")
    args = ap.parse_args()

    data = run_c2c(args.input, binary=args.binary) if args.run else load(args.input)
    if args.binary and not args.run:
        map_addresses_to_lines(data, args.binary)

    out = json.dumps(data, indent=2) + "\n"
    if args.output:
        with open(args.output, "w") as f:
            f.write(out)
        print(f"Wrote {args.output}")
    else:
        print(out, end="")


if __name__ == "__main__":
    main()
