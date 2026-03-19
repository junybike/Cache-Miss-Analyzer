import re, subprocess, argparse, os
from collections import defaultdict

# Convert addresses to source lines
def addr_to_line(binary, addresses):
    input_data = "\n".join("0x" + a for a in addresses)

    result = subprocess.run(
        ["addr2line", "-e", binary, "-f", "-p"],
        input=input_data,
        capture_output=True,
        text=True
    )
    return result.stdout.splitlines()

def normalize_line(line):
    line = re.sub(r'\s*\(discriminator.*\)', '', line)
    return line



address_counts = defaultdict(int)
line_counts = defaultdict(int)

parser = argparse.ArgumentParser()
parser.add_argument("binary", help="path to binary")
parser.add_argument("perf_script", help="perf script output file")

args = parser.parse_args()

binary = args.binary
perf_file = args.perf_script
binary_name = os.path.basename(binary)

# Get instruction addresses
with open(perf_file) as file:
    for line in file:
        m = re.match(r'\s*([0-9a-f]+)\s', line)

        if m and "(" in line and binary_name in line:
            addr = m.group(1)
            address_counts[addr] += 1

# Map addresses to source lines
addresses = list(address_counts.keys())
lines = addr_to_line(binary, addresses)

# print(address_counts)
# print(lines)

# Get counts per line
for addr, line in zip(addresses, lines):
    line = normalize_line(line)

    if line.startswith("??"):
        continue

    line_counts[line] += address_counts[addr]

# Results (Number of count: highest to lowest)
for line, count in sorted(line_counts.items(), key=lambda x: x[1], reverse=True):
    if binary not in line:
        continue
    print(line, count)
