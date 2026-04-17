"""Linked-list traversal in a hot loop: each node load is a cache miss."""

from .common import lines_of, misses_of, var_key


def run(ctx):
    seen = set()
    for a in ctx["accesses"]:
        key = var_key(a)
        if not (a["kind"] == "struct_member" and a.get("in_loop")
                and a.get("is_ptr_advance") and key not in seen):
            continue
        misses = misses_of(ctx, a)
        if misses <= ctx["miss_threshold"]:
            continue
        seen.add(key)

        struct_type = a.get("struct_type", "") or "T"
        yield {
            "severity": "HIGH",
            "pattern": "pointer_chasing",
            "variable": a["var"],
            "struct_type": a.get("struct_type", ""),
            "lines": lines_of(ctx, a),
            "cache_misses": misses,
            "problem": (
                f"Each node is separately heap-allocated. Traversing "
                f"{a['var']}->{a['field']} causes a cache miss per node since "
                f"nodes are scattered in memory."
            ),
            "fix": (
                f"Replace the linked list with std::vector<{struct_type}> and "
                f"integer next-indices, or use a pool allocator so nodes stay "
                f"contiguous."
            ),
        }
