"""Travel-time cost matrix - the bridge between the geo layer and the solver.

Asset types see different graphs. A truck cannot cross a flooded segment; a
boat can, slowly. Computing one matrix per asset *type* rather than per asset
keeps this cheap: a dozen boats at three depots is three Dijkstra runs, not
twelve.

This is the hot path. Recompute only the slice the change touched.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import networkx as nx
import numpy as np
from pharos_core import AssetType

from .graph import FLOODED_BOAT_SPEED_KMH, RoadGraph

# Types that can traverse flooded roads.
AMPHIBIOUS = frozenset({AssetType.BOAT})

# Verification assets do not travel. A callback costs the same from anywhere.
VERIFICATION_FIXED_COST_S = 180.0

UNREACHABLE = None


def _weight_fn(asset_type: AssetType):
    """Edge cost in seconds for this asset type, or None if impassable."""
    amphibious = asset_type in AMPHIBIOUS

    def w(u, v, d):
        if d.get("disabled"):
            return None  # collapsed. nothing crosses.
        if d.get("flooded"):
            if not amphibious:
                return None
            return d["length_m"] / (FLOODED_BOAT_SPEED_KMH * 1000.0 / 3600.0)
        return d["travel_time"]

    return w


@dataclass
class Snapper:
    """Nearest-node lookup. Built once per graph, reused for every query."""

    rg: RoadGraph
    _nodes: np.ndarray = field(init=False)
    _coords: np.ndarray = field(init=False)

    def __post_init__(self):
        ns = list(self.rg.G.nodes())
        self._nodes = np.array(ns)
        self._coords = np.array([[self.rg.G.nodes[n]["y"], self.rg.G.nodes[n]["x"]] for n in ns])

    def snap(self, lat: float, lon: float) -> int:
        # Equirectangular is plenty at district scale and far faster than
        # haversine over every node.
        dlat = self._coords[:, 0] - lat
        dlon = (self._coords[:, 1] - lon) * math.cos(math.radians(lat))
        return int(self._nodes[np.argmin(dlat * dlat + dlon * dlon)])


@dataclass
class CostMatrix:
    """cost[asset_id][demand_id] = travel seconds, or absent if unreachable."""

    cost: dict[str, dict[str, float]]
    asset_node: dict[str, int]
    demand_node: dict[str, int]
    rg: RoadGraph
    snapper: Snapper

    def get(self, asset_id: str, demand_id: str) -> float | None:
        return self.cost.get(asset_id, {}).get(demand_id)

    def reachable_assets(self, demand_id: str) -> list[str]:
        return [a for a, row in self.cost.items() if demand_id in row]

    def nearest_asset(self, demand_id: str) -> tuple[str | None, float | None]:
        best, best_t = None, None
        for a, row in self.cost.items():
            t = row.get(demand_id)
            if t is not None and (best_t is None or t < best_t):
                best, best_t = a, t
        return best, best_t

    def route(self, asset_id: str, demand_id: str, asset_type: AssetType) -> list[tuple[float, float]]:
        """(lat, lon) polyline for the map. Computed lazily, assigned pairs only."""
        u, v = self.asset_node.get(asset_id), self.demand_node.get(demand_id)
        if u is None or v is None:
            return []
        try:
            path = nx.shortest_path(self.rg.G, u, v, weight=_weight_fn(asset_type))
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []
        return [self.rg.node_latlon(n) for n in path]


def build(
    rg: RoadGraph,
    assets,
    demands,
    snapper: Snapper | None = None,
    max_seconds: float = 4 * 3600.0,
) -> CostMatrix:
    """One Dijkstra per (asset type, depot node). Cutoff keeps it bounded."""
    snapper = snapper or Snapper(rg)

    demand_node = {d.demand_id: snapper.snap(d.location.lat, d.location.lon) for d in demands}
    asset_node = {a.asset_id: snapper.snap(a.lat, a.lon) for a in assets}

    # Group assets so co-located same-type assets share one shortest-path run.
    groups: dict[tuple[AssetType, int], list[str]] = {}
    for a in assets:
        if a.is_verifier:
            continue
        groups.setdefault((a.type, asset_node[a.asset_id]), []).append(a.asset_id)

    cost: dict[str, dict[str, float]] = {}

    for (atype, node), asset_ids in groups.items():
        try:
            dist = nx.single_source_dijkstra_path_length(
                rg.G, node, cutoff=max_seconds, weight=_weight_fn(atype)
            )
        except nx.NodeNotFound:
            dist = {}
        row = {
            did: dist[dnode] for did, dnode in demand_node.items() if dnode in dist
        }
        for aid in asset_ids:
            cost[aid] = dict(row)

    # Verification assets reach every demand at a flat, cheap cost. They are a
    # phone call, not a vehicle.
    for a in assets:
        if a.is_verifier:
            cost[a.asset_id] = {d.demand_id: VERIFICATION_FIXED_COST_S for d in demands}

    return CostMatrix(
        cost=cost, asset_node=asset_node, demand_node=demand_node, rg=rg, snapper=snapper
    )


def prune(cm: CostMatrix, demands, top_k: int = 10) -> CostMatrix:
    """Keep only the nearest `top_k` assets per demand.

    Every asset paired with every demand is how a CP-SAT model goes from 10
    seconds to 90. Pruning here costs almost nothing in solution quality - the
    eleventh-nearest boat was never going to win.
    """
    keep: set[tuple[str, str]] = set()
    for d in demands:
        cands = [
            (t, aid) for aid, row in cm.cost.items() if (t := row.get(d.demand_id)) is not None
        ]
        cands.sort()
        for _, aid in cands[:top_k]:
            keep.add((aid, d.demand_id))

    pruned = {
        aid: {did: t for did, t in row.items() if (aid, did) in keep}
        for aid, row in cm.cost.items()
    }
    return CostMatrix(
        cost=pruned,
        asset_node=cm.asset_node,
        demand_node=cm.demand_node,
        rg=cm.rg,
        snapper=cm.snapper,
    )
