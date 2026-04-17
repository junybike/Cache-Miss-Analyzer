"""Cache-optimization rules.

Each rule lives in its own module and exports a `run(ctx)` generator.
To add a rule: create `mymod.py` with a `run(ctx)` function, then import
it below and append it to `RULES`.
"""

from .common import (
    compute_field_heat,
    compute_miss_threshold,
    detect_cache_line,
)
from . import (
    aos_to_soa,
    hot_cold_partition,
    pointer_chasing,
    random_access,
    strided_access,
    struct_reorder,
)

RULES = [
    pointer_chasing.run,
    aos_to_soa.run,
    struct_reorder.run,
    hot_cold_partition.run,
    strided_access.run,
    random_access.run,
]

__all__ = [
    "RULES",
    "compute_field_heat",
    "compute_miss_threshold",
    "detect_cache_line",
]
