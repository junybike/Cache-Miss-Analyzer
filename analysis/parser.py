"""Map perf cache-miss sample addresses to source line numbers."""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict

ADDR = re.compile(r"\s*([0-9a-f]+)\s")
LINE = re.compile(r":(\d+)(?:\s|$)")
DISCRIMINATOR = re.compile(r"\s*\(discriminator.*\)")


def addr_to_line(binary, addresses):
    """Batch addr2line. Fails loudly if the tool errors out."""
    r = subprocess.run(
        ["addr2line", "-e", binary, "-f", "-p"],
        input="\n".join("0x" + a for a in addresses),
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        sys.exit(f"addr2line failed (rc={r.returncode}): {r.stderr.strip()}")
    return r.stdout.splitlines()


def read_sample_counts(perf_script, binary_path):
    """Count samples per instruction address. Filter by full binary path
    or perf's parenthesized DSO notation."""
    binary_name = os.path.basename(binary_path)
    counts = defaultdict(int)
    with open(perf_script) as f:
        for line in f:
            m = ADDR.match(line)
            if not m:
                continue
            if binary_path in line or f"({binary_name})" in line:
                counts[m.group(1)] += 1
    return counts


def aggregate_by_line(counts, resolved, source_name):
    """Sum sample counts per source-line number."""
    lines = defaultdict(int)
    for addr, text in zip(counts, resolved):
        text = DISCRIMINATOR.sub("", text)
        if text.startswith("??") or source_name not in text:
            continue
        m = LINE.search(text)
        if m:
            lines[m.group(1)] += counts[addr]
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("binary")
    ap.add_argument("perf_script", help="perf script output file")
    ap.add_argument("--source", help="source file (for filtering addr2line output)")
    args = ap.parse_args()

    binary_path = os.path.realpath(args.binary)
    source_name = os.path.basename(args.source) if args.source else os.path.basename(binary_path)

    counts = read_sample_counts(args.perf_script, binary_path)
    if not counts:
        print("{}")
        return

    addrs = list(counts)
    resolved = addr_to_line(args.binary, addrs)
    if len(resolved) < len(addrs):
        print(f"Warning: addr2line returned {len(resolved)}/{len(addrs)} entries, "
              f"padding remainder as unresolved", file=sys.stderr)
        resolved.extend(["??"] * (len(addrs) - len(resolved)))

    lines = aggregate_by_line(counts, resolved, source_name)
    print(json.dumps(lines, indent=2))


if __name__ == "__main__":
    main()
