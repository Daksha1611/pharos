"""H3 hex tessellation of the disaster footprint.

Equal-area cells are what make "worst-off zone" a defensible metric instead of
an argument about ward boundaries, which vary wildly in size. Resolution 8
gives cells of roughly 0.7 km2 - right for a district-scale flood.
"""

from __future__ import annotations

from collections import defaultdict

import h3

DEFAULT_RESOLUTION = 8

# Approximate average edge length in metres, by H3 resolution.
_EDGE_M = {7: 1220.0, 8: 461.0, 9: 174.0}


def cell(lat: float, lon: float, res: int = DEFAULT_RESOLUTION) -> str:
    return h3.latlng_to_cell(lat, lon, res)


def cell_centre(c: str) -> tuple[float, float]:
    return h3.cell_to_latlng(c)


def cell_boundary(c: str) -> list[tuple[float, float]]:
    """(lat, lon) ring, for drawing the hex on the map."""
    return [tuple(p) for p in h3.cell_to_boundary(c)]


def cells_in_region(
    centre: tuple[float, float], radius_km: float, res: int = DEFAULT_RESOLUTION
) -> list[str]:
    origin = cell(centre[0], centre[1], res)
    k = max(1, int((radius_km * 1000.0) / (_EDGE_M.get(res, 461.0) * 1.5)))
    return list(h3.grid_disk(origin, k))


def assign_cells(records, res: int = DEFAULT_RESOLUTION) -> None:
    """Stamp every demand with its hex. Mutates in place."""
    for r in records:
        r.location.h3_cell = cell(r.location.lat, r.location.lon, res)


def group_by_zone(records) -> dict[str, list]:
    out: dict[str, list] = defaultdict(list)
    for r in records:
        out[r.location.h3_cell or "unzoned"].append(r)
    return dict(out)


def zone_demand_totals(records) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for r in records:
        totals[r.location.h3_cell or "unzoned"] += r.need.people
    return dict(totals)


def zone_deficits(records, assignments) -> dict[str, float]:
    """Fraction of each zone's people still unserved, in [0, 1].

    This is the equity signal the objective consumes. A zone at 1.0 has had
    nothing at all; a zone at 0.0 is fully covered.
    """
    demanded = zone_demand_totals(records)
    served: dict[str, int] = defaultdict(int)
    by_id = {r.demand_id: r for r in records}
    for a in assignments:
        r = by_id.get(a.demand_id)
        if r is not None:
            served[r.location.h3_cell or "unzoned"] += a.people_committed
    return {
        z: 1.0 - min(1.0, served.get(z, 0) / total) if total else 0.0
        for z, total in demanded.items()
    }
