from collections import defaultdict
import re, sys

ast_file = sys.argv[1]
perf_file = sys.argv[2]

line_to_vars = defaultdict(set)

# Parse ast 
with open(ast_file) as file:
    for line in file:
        m = re.search(r'Line (\d+): .* access (\w+)', line)
        if m:
            line_number = int(m.group(1))
            var_name = m.group(2)
            line_to_vars[line_number].add(var_name)


line_freq = defaultdict(int)

# Parse perf
with open(perf_file) as file:
    for line in file:
        m = re.search(r':(\d+)\s+(\d+)', line)
        if m:
            line_number = int(m.group(1))
            count = int(m.group(2))
            line_freq[line_number] += count


var_miss = defaultdict(int)

# Maps perf and ast data
for line_number, freq in line_freq.items():
    if line_number in line_to_vars:
        for var in line_to_vars[line_number]:
            var_miss[var] += freq


print("=== Cache Misses by Variable ===")
for var, count in sorted(var_miss.items(), key=lambda x: -x[1]):
    print(f"{var}: {count}")

