"""Shared-variable cache rules: false sharing, true sharing, shared containers.

Fires on ctx["shared_candidates"] populated by ast_analyzer.cpp.  Each entry
describes a variable passed to or captured by a threading API.  When
ctx["c2c_hitm"] is present (populated by c2c_parser), HITM counts are attached
to the recommendation; otherwise cache_misses falls back to var_misses totals.

share_kind values (from ast_analyzer.cpp):
    global_or_static   global/static read or written inside thread functions
    passed_by_ref      std::ref(x) or reference parameter
    passed_by_ptr      &x / pointer argument
    captured_by_ref    [&] lambda capture
"""

_KIND_SEVERITY = {
    "global_or_static": "HIGH",
    "captured_by_ref":  "MEDIUM",
    "passed_by_ref":    "MEDIUM",
    "passed_by_ptr":    "MEDIUM",
}

_CONTAINER_KINDS = frozenset(
    ("vector", "array", "indirect_vector", "indirect_array", "strided")
)


def _sum_var_misses(var_misses, var_name):
    """Sum perf miss counts across all functions that accessed var_name."""
    suffix = "::" + var_name
    return sum(v.get("misses", 0) for k, v in var_misses.items() if k.endswith(suffix))


def _has_write_access(accesses, var_name):
    """Return True if var_name has at least one non-const (write) container access.
    When no container accesses are found at all we return True (conservative:
    can't confirm read-only, so keep the candidate).
    """
    relevant = [a for a in accesses
                if a.get("var") == var_name and a.get("kind") in _CONTAINER_KINDS]
    if not relevant:
        return True
    return any(not a.get("element_type", "").startswith("const") for a in relevant)


def run(ctx):
    candidates = ctx.get("shared_candidates", [])
    if not candidates:
        return

    c2c_hitm   = ctx.get("c2c_hitm", {})
    var_misses = ctx.get("var_misses", {})
    accesses   = ctx.get("accesses", [])
    structs    = ctx.get("structs", {})
    cache_line = ctx.get("cache_line", 64)

    seen = set()
    for cand in candidates:
        var = cand["var"]
        if var in seen:
            continue
        seen.add(var)

        type_  = cand.get("type", "")
        kind   = cand.get("share_kind", "")
        line   = cand.get("line", 0)
        api    = cand.get("thread_api", "")
        hitm   = c2c_hitm.get(line, 0) or _sum_var_misses(var_misses, var)

        struct_info  = structs.get(type_)
        is_struct    = struct_info is not None
        struct_size  = struct_info["size"] if is_struct else 0
        fields       = struct_info["fields"] if is_struct else []
        is_container = any(t in type_ for t in ("vector", "array", "deque", "list"))

        # Read-only containers cannot cause false sharing — skip entirely.
        if is_container and not _has_write_access(accesses, var):
            continue

        # FALSE SHARING: struct small enough to fit in one cache line but holds multiple fields written by different threads.
        if is_struct and struct_size <= cache_line and len(fields) >= 2:
            field_names = [f["name"] for f in fields]
            padded_fields = "".join(
                f"    alignas({cache_line}) {f['type']} {f['name']};\n"
                for f in fields
            )
            yield {
                "severity":    "HIGH",
                "pattern":     "false_sharing",
                "variable":    var,
                "struct_type": type_,
                "lines":       [line],
                "cache_misses": hitm,
                "share_kind":  kind,
                "thread_api":  api,
                "problem": (
                    f"'{var}' ({type_}, {struct_size} B) fits in one "
                    f"{cache_line}-byte cache line. Fields "
                    f"{', '.join(field_names)} are written by separate threads, "
                    f"causing cache-line ping-pong on every store."
                ),
                "fix": (
                    f"Pad each per-thread field to its own cache line:\n"
                    f"  struct {type_} {{\n"
                    f"{padded_fields}"
                    f"  }};\n"
                    f"Or use per-thread local variables and reduce after joining."
                ),
            }
            continue

        # TRUE SHARING: global/static variable written by multiple threads.
        if kind == "global_or_static":
            if is_struct:
                fix = (
                    f"Protect '{var}' with a std::mutex, or split into per-thread "
                    f"instances of {type_} and merge results after all threads join."
                )
            elif is_container:
                fix = (
                    f"Give each thread a private partition or separate buffer; "
                    f"merge into '{var}' after joining all threads."
                )
            else:
                fix = (
                    f"Replace '{var}' with 'std::atomic<{type_}>' for lock-free "
                    f"updates, use per-thread accumulators reduced under a mutex, "
                    f"or declare 'thread_local {type_} {var}' for independent copies."
                )
            yield {
                "severity":    "HIGH",
                "pattern":     "true_sharing",
                "variable":    var,
                "struct_type": type_ if is_struct else "",
                "lines":       [line],
                "cache_misses": hitm,
                "share_kind":  kind,
                "thread_api":  api,
                "problem": (
                    f"Global/static '{var}' ({type_}) is read or written by "
                    f"multiple threads without visible synchronization. Concurrent "
                    f"writes force repeated cache-line ownership transfers and risk "
                    f"data races."
                ),
                "fix": fix,
            }
            continue

        # SHARED CONTAINER: vector/array passed by ref across threads.
        if is_container and kind in ("passed_by_ref", "captured_by_ref"):
            elem_bytes = struct_size or 4
            pad_elems  = max(1, cache_line // elem_bytes)
            yield {
                "severity":    "MEDIUM",
                "pattern":     "shared_container",
                "variable":    var,
                "struct_type": "",
                "lines":       [line],
                "cache_misses": hitm,
                "share_kind":  kind,
                "thread_api":  api,
                "problem": (
                    f"'{var}' ({type_}) is shared by reference across threads. "
                    f"Writes to adjacent elements can fall on the same "
                    f"{cache_line}-byte cache line, causing false sharing."
                ),
                "fix": (
                    f"Give each thread its own output buffer and merge after "
                    f"joining. Or ensure thread ranges are separated by at least "
                    f"{pad_elems} elements so adjacent writes land on different "
                    f"cache lines."
                ),
            }
            continue

        # GENERIC: passed by ref/ptr — catch-all for remaining cases.
        severity = _KIND_SEVERITY.get(kind, "SUSPECT")
        if kind == "passed_by_ptr":
            problem = (
                f"'{var}' ({type_}) is passed by pointer to multiple threads. "
                f"Concurrent writes trigger repeated cache-line ownership transfers."
            )
            fix = (
                f"Split '{var}' into per-thread structs padded to {cache_line} "
                f"bytes with 'alignas({cache_line})', then merge results after all "
                f"threads join."
            )
        else:
            problem = (
                f"'{var}' ({type_}) is shared via {kind.replace('_', ' ')} across "
                f"threads ({api}). Concurrent accesses risk cache thrashing and "
                f"data races."
            )
            fix = (
                f"Use 'std::atomic' wrappers or a scoped mutex for shared state in "
                f"'{var}'. Prefer passing read-only data as const-ref and collecting "
                f"per-thread results separately."
            )
        yield {
            "severity":    severity,
            "pattern":     "shared_variable",
            "variable":    var,
            "struct_type": type_ if is_struct else "",
            "lines":       [line],
            "cache_misses": hitm,
            "share_kind":  kind,
            "thread_api":  api,
            "problem":     problem,
            "fix":         fix,
        }
