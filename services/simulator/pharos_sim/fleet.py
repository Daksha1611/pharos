"""Asset fleet and depot placement.

Depots go on the road network, spread across the region rather than clustered
at the centre - a district response stages from several points, and putting
every boat in one place would make the equity metric trivially bad for reasons
that have nothing to do with the solver.
"""

from __future__ import annotations

import math
import random

from pharos_allocator.graph import RoadGraph, haversine_m
from pharos_allocator.zones import cell
from pharos_core import Asset, AssetType, Depot

from .spec import ScenarioSpec

# Which need types each asset type can serve. Empty means all.
SERVES = {
    AssetType.BOAT: ["evacuation", "missing_person", "medical"],
    AssetType.AMBULANCE: ["medical"],
    AssetType.TRUCK: ["water", "food", "shelter", "sanitation", "infrastructure"],
    AssetType.HELICOPTER: [],
    AssetType.OPERATOR: [],
    AssetType.VOLUNTEER: [],
}


def build(spec: ScenarioSpec, rg: RoadGraph) -> tuple[list[Asset], list[Depot]]:
    rng = random.Random(spec.seed + 991)
    depots: list[Depot] = []
    assets: list[Asset] = []

    for aspec in spec.assets:
        atype = AssetType(aspec.type)
        type_depots = _place_depots(spec, rg, atype, aspec.depots, rng)
        depots.extend(type_depots)

        for i in range(aspec.count):
            d = type_depots[i % len(type_depots)]
            assets.append(
                Asset(
                    asset_id=f"{atype.value}-{i + 1:02d}",
                    type=atype,
                    capacity=aspec.capacity,
                    speed_kmh=aspec.speed_kmh,
                    depot_id=d.depot_id,
                    lat=d.lat,
                    lon=d.lon,
                    h3_cell=cell(d.lat, d.lon, spec.region.h3_resolution),
                    serves=list(SERVES.get(atype, [])),
                )
            )
    return assets, depots


def _place_depots(
    spec: ScenarioSpec, rg: RoadGraph, atype: AssetType, count: int, rng: random.Random
) -> list[Depot]:
    clat, clon = spec.region.centre

    # Verification assets are people at desks and phones. One control room.
    if atype in (AssetType.OPERATOR, AssetType.VOLUNTEER):
        return [
            Depot(depot_id=f"{atype.value}-control-room", name="District control room",
                  lat=clat, lon=clon)
        ]

    # Physical depots sit on a ring at roughly 55% of the region radius, evenly
    # spaced, then snapped to the nearest actual road node.
    out: list[Depot] = []
    ring_m = spec.region.radius_km * 1000.0 * 0.55
    phase = rng.uniform(0, 2 * math.pi)

    for i in range(max(1, count)):
        th = phase + (2 * math.pi * i / max(1, count))
        dlat = (ring_m * math.sin(th) / 6_371_000.0) * (180.0 / math.pi)
        dlon = (ring_m * math.cos(th) / (6_371_000.0 * math.cos(math.radians(clat)))) * (
            180.0 / math.pi
        )
        tlat, tlon = clat + dlat, clon + dlon

        node = min(
            rg.G.nodes,
            key=lambda n: haversine_m(rg.G.nodes[n]["y"], rg.G.nodes[n]["x"], tlat, tlon),
        )
        out.append(
            Depot(
                depot_id=f"{atype.value}-depot-{i + 1}",
                name=f"{atype.value.title()} staging {i + 1}",
                lat=rg.G.nodes[node]["y"],
                lon=rg.G.nodes[node]["x"],
            )
        )
    return out


def service_minutes(asset: Asset, people: int) -> float:
    """Time on scene, before the asset is free again.

    Loading people onto a boat in a flood is not instantaneous, and pretending
    it is would inflate every coverage number in the evaluation.
    """
    if asset.is_verifier:
        return 3.0
    base = {AssetType.BOAT: 6.0, AssetType.AMBULANCE: 8.0, AssetType.TRUCK: 10.0}.get(
        asset.type, 6.0
    )
    return base + 0.7 * max(0, people)
