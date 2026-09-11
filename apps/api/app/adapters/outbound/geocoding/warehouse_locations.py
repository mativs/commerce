"""Fixed synthetic warehouse locations in Mar del Plata.

Separate from the shipping address pool; no coordinate pair overlaps it.
Points use the same researched inland area documented in sample_locations.py.
Selection is with replacement, so multiple warehouses may share a location.
"""

from random import choice

WAREHOUSE_LOCATIONS: tuple[tuple[float, float], ...] = (
    (-37.991000, -57.566000),
    (-37.991000, -57.570000),
    (-37.991000, -57.574000),
    (-37.991000, -57.578000),
    (-37.991000, -57.582000),
    (-37.995000, -57.566000),
    (-37.995000, -57.570000),
    (-37.995000, -57.574000),
    (-37.995000, -57.578000),
    (-37.995000, -57.582000),
    (-37.999000, -57.566000),
    (-37.999000, -57.570000),
    (-37.999000, -57.574000),
    (-37.999000, -57.578000),
    (-37.999000, -57.582000),
    (-38.003000, -57.566000),
    (-38.003000, -57.570000),
    (-38.003000, -57.574000),
    (-38.003000, -57.578000),
    (-38.003000, -57.582000),
)


def random_warehouse_coordinates() -> tuple[float, float]:
    return choice(WAREHOUSE_LOCATIONS)
