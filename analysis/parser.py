import re, subprocess, argparse, os, json
from collections import defaultdict


def addr_to_line(binary, addresses):
    """Batch-convert instruction addresses to source lines via addr2line."""
    input_data = "\n".join("0x" + a for a in addresses)
    result = subprocess.run(
        ["addr2line", "-e", binary, "-f", "-p"],
        input=input_data,
        capture_output=True,
        text=True
    )
    return result.stdout.splitlines()


def strip_discriminator(line):
    return re.sub(r'\s*\(discriminator.*\)', '', line)


parser = argparse.ArgumentParser(
    description="Map perf cache-miss addresses to source line numbers."
)
parser.add_argument("binary", help="path to binary")
parser.add_argument("perf_script", help="perf script output file")
parser.add_argument("--source", help="source file path (for filtering addr2line output)")
args = parser.parse_args()

binary_name = os.path.basename(args.binary)
# Use source basename for addr2line filtering when available, since the
# addr2line output contains the source path (not the binary path).
# Falling back to binary_name works when the two share a name.
source_name = os.path.basename(args.source) if args.source else binary_name

# Count how many cache-miss samples landed on each instruction address
address_counts = defaultdict(int)
with open(args.perf_script) as f:
    for line in f:
        m = re.match(r'\s*([0-9a-f]+)\s', line)
        if m and "(" in line and binary_name in line:
            address_counts[m.group(1)] += 1

# Resolve addresses to source lines, then aggregate by line number
addresses = list(address_counts.keys())
resolved = addr_to_line(args.binary, addresses)

line_counts = defaultdict(int)
for addr, resolved_line in zip(addresses, resolved):
    resolved_line = strip_discriminator(resolved_line)

    if resolved_line.startswith("??") or source_name not in resolved_line:
        continue

    m = re.search(r':(\d+)', resolved_line)
    if m:
        line_counts[m.group(1)] += address_counts[addr]

print(json.dumps(line_counts, indent=2))
