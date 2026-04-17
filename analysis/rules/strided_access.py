"""Column-major / strided traversal of row-major 2D arrays."""

from .common import lines_of, misses_of, var_key


def run(ctx):
    seen = set()
    for a in ctx["accesses"]:
        key = var_key(a)
        if a["kind"] != "strided" or key in seen:
            continue
        misses = misses_of(ctx, a)
        if misses <= ctx["miss_threshold"]:
            continue
        seen.add(key)

        yield {
            "severity": "HIGH",
            "pattern": "strided_access",
            "variable": a["var"],
            "lines": lines_of(ctx, a),
            "cache_misses": misses,
            "problem": (
                f"Array '{a['var']}' is traversed column-major (outer index "
                f"varies in the inner loop). Each access jumps by a whole "
                f"row, missing cache on nearly every read."
            ),
            "fix": (
                "Swap the loop nesting so the last array dimension varies "
                "in the innermost loop, or transpose the data layout."
            ),
        }
