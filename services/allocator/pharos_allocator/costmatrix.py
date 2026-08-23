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


def prune(cm: CostMatrix, demands, top_k: int = 10, verifier_ids=frozenset()) -> CostMatrix:
    """Keep only the nearest `top_k` physical assets per demand.

    Every asset paired with every demand is how a CP-SAT model goes from 10
    seconds to 90. Pruning here costs almost nothing in solution quality - the
    eleventh-nearest boat was never going to win.

    Verification assets are exempt and never pruned. Their cost is a flat
    three minutes because a callback costs the same from anywhere, which makes
    them the "nearest" asset to every demand in the district. Ranking them
    against boats on travel time silently deleted the entire physical fleet
    from the model and the solver spent a whole scenario dispatching nothing
    but phone calls.
    """
    keep: set[tuple[str, str]] = set()
    for d in demands:
        cands = [
            (t, aid)
            for aid, row in cm.cost.items()
            if aid not in verifier_ids and (t := row.get(d.demand_id)) is not None
        ]
        cands.sort()
        for _, aid in cands[:top_k]:
            keep.add((aid, d.demand_id))
        for aid in verifier_ids:
            if d.demand_id in cm.cost.get(aid, {}):
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


# --------------------------------------------------------------------------
# incremental cost lookup for the rolling replan
# --------------------------------------------------------------------------


class RouteOracle:
    """Caches shortest-path distances so a replan does not redo Dijkstra.

    Assets stage from depots and return to them, so the set of sources is
    small and stable: one Dijkstra per (asset type, depot node) per road
    state, reused across every replan tick until the road changes.

    `bump_road_version()` is the invalidation. Recomputing only what the change
    touched is the difference between a replan that feels live and one that
    feels dead - the operator is watching, and a full matrix rebuild over a
    few thousand demands takes seconds.
    """

    def __init__(self, rg: RoadGraph, max_seconds: float = 4 * 3600.0):
        self.rg = rg
        self.snapper = Snapper(rg)
        self.max_seconds = max_seconds
        self.road_version = 0
        self._dist: dict[tuple, dict[int, float]] = {}
        self._node_of: dict[str, int] = {}

    def bump_road_version(self) -> None:
        self.road_version += 1
        self._dist.clear()

    def node_for(self, key: str, lat: float, lon: float) -> int:
        node = self._node_of.get(key)
        if node is None:
            node = self.snapper.snap(lat, lon)
            self._node_of[key] = node
        return node

    def _distances(self, asset_type: AssetType, source: int) -> dict[int, float]:
        ck = (asset_type, source, self.road_version)
        hit = self._dist.get(ck)
        if hit is None:
            try:
                hit = nx.single_source_dijkstra_path_length(
                    self.rg.G, source, cutoff=self.max_seconds, weight=_weight_fn(asset_type)
                )
            except nx.NodeNotFound:
                hit = {}
            self._dist[ck] = hit
        return hit

    def build(self, assets, demands, top_k: int | None = None) -> CostMatrix:
        demand_node = {
            d.demand_id: self.node_for(d.demand_id, d.location.lat, d.location.lon)
            for d in demands
        }
        asset_node = {
            a.asset_id: self.node_for(f"asset::{a.asset_id}", a.lat, a.lon) for a in assets
        }

        cost: dict[str, dict[str, float]] = {}
        for a in assets:
            if a.is_verifier:
                cost[a.asset_id] = {d.demand_id: VERIFICATION_FIXED_COST_S for d in demands}
                continue
            dist = self._distances(a.type, asset_node[a.asset_id])
            cost[a.asset_id] = {
                did: dist[node] for did, node in demand_node.items() if node in dist
            }

        cm = CostMatrix(
            cost=cost,
            asset_node=asset_node,
            demand_node=demand_node,
            rg=self.rg,
            snapper=self.snapper,
        )
        if not top_k:
            return cm
        verifiers = frozenset(a.asset_id for a in assets if a.is_verifier)
        return prune(cm, demands, top_k, verifier_ids=verifiers)
