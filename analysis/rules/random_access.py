"""Indirect / random access via an index array in a hot loop.

The pattern is purely syntactic — `arr[idx[i]]` looks random but may be fully
sequential if `idx` has been sorted. We can't prove that statically, so we
cross-check against the observed miss counts: a truly random access misses
the cache on nearly every read, so the data array's misses should be at
least comparable to the index array's. If the data array has noticeably
fewer misses than the index array, the index is probably monotone in
practice and the rule is likely misfiring.
"""

from .common import lines_of, misses_of, var_key

LOCALITY_MISFIRE_RATIO = 0.5


def run(ctx):
    seen = set()
    for a in ctx["accesses"]:
        key = var_key(a)
        if a["kind"] not in ("indirect_array", "indirect_vector"):
            continue
        if not a.get("in_loop") or key in seen:
            continue
        misses = misses_of(ctx, a)
        if misses <= ctx["miss_threshold"]:
            continue
        seen.add(key)

        index_var = a.get("index_var", "")
        index_misses = misses_of(ctx, index_var) if index_var else 0
        likely_sequential = (
            index_misses > ctx["miss_threshold"]
            and misses < index_misses * LOCALITY_MISFIRE_RATIO
        )

        problem = (
            f"Array '{a['var']}' is accessed through an index array"
            f"{f' ({index_var})' if index_var else ''}. If indices are "
            f"non-sequential, each access can land on a different cache line."
        )
        fix = (
            "Sort the index array to improve spatial locality, or copy "
            "needed elements into a contiguous temporary buffer."
        )
        if likely_sequential:
            problem += (
                f" However, '{a['var']}' has {misses} misses versus "
                f"{index_misses} on '{index_var}' — observed locality is high, "
                f"so the index array is likely already monotone and this "
                f"flag may be a false positive."
            )

        yield {
            "severity": "SUSPECT",
            "pattern": "random_access",
            "variable": a["var"],
            "index_var": index_var,
            "lines": lines_of(ctx, a),
            "cache_misses": misses,
            "likely_misfire": likely_sequential,
            "problem": problem,
            "fix": fix,
        }
