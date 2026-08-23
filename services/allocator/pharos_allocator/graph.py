"""Road network for the disaster footprint.

Two ways to get a graph:

  build_from_osm()    real OpenStreetMap extract via OSMnx. Correct, but needs
                      a network call and a multi-minute download, so it is
                      built once, pickled, and committed.
  build_synthetic()   deterministic offline generator. Grid core, radial
                      arterials, and a river with a small number of bridges.

The demo runs on the synthetic graph so it never touches the network. The
bridges are the point: a delta town has chokepoints, and a chokepoint is what
makes road degradation change the plan instead of nudging it.

Edges carry `flooded`. Road vehicles cannot traverse a flooded edge; boats can,
slowly. That asymmetry is why the solver's answer to a flood is not simply
"everything got further away".
"""

from __future__ import annotations

import math
import pickle
import random
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

EARTH_RADIUS_M = 6_371_000.0

# Speeds by road class, km/h.
ROAD_SPEEDS = {"arterial": 55.0, "secondary": 35.0, "local": 22.0}

# A boat crossing a flooded road segment. Slow, but passable.
FLOODED_BOAT_SPEED_KMH = 9.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _offset(lat: float, lon: float, dx_m: float, dy_m: float) -> tuple[float, float]:
    """Metres east/north to degrees, equirectangular. Fine at district scale."""
    dlat = (dy_m / EARTH_RADIUS_M) * (180.0 / math.pi)
    dlon = (dx_m / (EARTH_RADIUS_M * math.cos(math.radians(lat)))) * (180.0 / math.pi)
    return lat + dlat, lon + dlon


@dataclass
class RoadGraph:
    """A routable graph plus the metadata the console and solver need."""

    G: nx.Graph
    centre: tuple[float, float]
    radius_km: float
    river: list[tuple[float, float]]
    bridges: list[tuple[int, int]]

    def node_latlon(self, n: int) -> tuple[float, float]:
        d = self.G.nodes[n]
        return d["y"], d["x"]

    def edge_ids(self) -> list[tuple[int, int]]:
        return list(self.G.edges())

    def bbox(self) -> tuple[float, float, float, float]:
        ys = [d["y"] for _, d in self.G.nodes(data=True)]
        xs = [d["x"] for _, d in self.G.nodes(data=True)]
        return min(xs), min(ys), max(xs), max(ys)


def _segments_intersect(p, q, r, s) -> bool:
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    d1, d2 = cross(r, s, p), cross(r, s, q)
    d3, d4 = cross(p, q, r), cross(p, q, s)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _crosses_river(a, b, river) -> bool:
    for i in range(len(river) - 1):
        if _segments_intersect(a, b, river[i], river[i + 1]):
            return True
    return False


def build_synthetic(
    centre: tuple[float, float],
    radius_km: float = 25.0,
    spacing_m: float = 1100.0,
    seed: int = 42,
    drop_edge_fraction: float = 0.18,
) -> RoadGraph:
    """Deterministic road network. Same seed, same graph, every time."""
    rng = random.Random(seed)
    clat, clon = centre
    radius_m = radius_km * 1000.0
    steps = int(radius_m / spacing_m)

    # --- nodes on a jittered grid, clipped to the region circle ------------
    G = nx.Graph()
    index: dict[tuple[int, int], int] = {}
    nid = 0
    for iy in range(-steps, steps + 1):
        for ix in range(-steps, steps + 1):
            dx = ix * spacing_m + rng.uniform(-spacing_m * 0.22, spacing_m * 0.22)
            dy = iy * spacing_m + rng.uniform(-spacing_m * 0.22, spacing_m * 0.22)
            if math.hypot(dx, dy) > radius_m:
                continue
            lat, lon = _offset(clat, clon, dx, dy)
            G.add_node(nid, x=lon, y=lat, gx=ix, gy=iy)
            index[(ix, iy)] = nid
            nid += 1

    # --- the river: a meander running roughly north-south through the region
    river: list[tuple[float, float]] = []
    for t in range(-steps, steps + 1):
        dy = t * spacing_m
        dx = 0.30 * radius_m * math.sin(dy / (radius_m * 0.42)) + 0.12 * radius_m
        lat, lon = _offset(clat, clon, dx, dy)
        river.append((lon, lat))

    # --- edges between grid neighbours -------------------------------------
    bridges: list[tuple[int, int]] = []
    river_crossings: list[tuple[int, int]] = []

    for (ix, iy), u in index.items():
        for dix, diy in ((1, 0), (0, 1)):
            v = index.get((ix + dix, iy + diy))
            if v is None:
                continue
            # thin the grid so it reads as a road network, not graph paper
            if rng.random() < drop_edge_fraction:
                continue
            a = (G.nodes[u]["x"], G.nodes[u]["y"])
            b = (G.nodes[v]["x"], G.nodes[v]["y"])
            if _crosses_river(a, b, river):
                river_crossings.append((u, v))
                continue
            _add_edge(G, u, v, "local")

    # Only a handful of crossings become bridges. Chokepoints are the point.
    rng.shuffle(river_crossings)
    for u, v in river_crossings[:5]:
        _add_edge(G, u, v, "arterial", bridge=True)
        bridges.append((u, v))

    # --- arterials: upgrade straight runs radiating from the centre --------
    centre_node = min(
        G.nodes, key=lambda n: haversine_m(G.nodes[n]["y"], G.nodes[n]["x"], clat, clon)
    )
    _upgrade_arterials(G, index, centre_node, steps)

    # --- keep only the largest connected component -------------------------
    if G.number_of_nodes():
        biggest = max(nx.connected_components(G), key=len)
        G = G.subgraph(biggest).copy()
        bridges = [(u, v) for u, v in bridges if G.has_edge(u, v)]

    return RoadGraph(G=G, centre=centre, radius_km=radius_km, river=river, bridges=bridges)


def _add_edge(G: nx.Graph, u: int, v: int, road_class: str, bridge: bool = False) -> None:
    length = haversine_m(G.nodes[u]["y"], G.nodes[u]["x"], G.nodes[v]["y"], G.nodes[v]["x"])
    speed = ROAD_SPEEDS[road_class]
    G.add_edge(
        u,
        v,
        edge_id=f"E{min(u, v)}-{max(u, v)}",
        length_m=length,
        speed_kmh=speed,
        base_speed_kmh=speed,
        travel_time=length / (speed * 1000.0 / 3600.0),
        road_class=road_class,
        bridge=bridge,
        flooded=False,
        disabled=False,
    )


def _upgrade_arterials(G: nx.Graph, index: dict, centre_node: int, steps: int) -> None:
    """Promote the axis rows and columns through the centre to arterial."""
    cx, cy = G.nodes[centre_node]["gx"], G.nodes[centre_node]["gy"]
    for t in range(-steps, steps + 1):
        for a, b in (
            ((cx + t, cy), (cx + t + 1, cy)),
            ((cx, cy + t), (cx, cy + t + 1)),
        ):
            u, v = index.get(a), index.get(b)
            if u is None or v is None or not G.has_edge(u, v):
                continue
            e = G.edges[u, v]
            e["road_class"] = "arterial"
            e["speed_kmh"] = e["base_speed_kmh"] = ROAD_SPEEDS["arterial"]
            e["travel_time"] = e["length_m"] / (ROAD_SPEEDS["arterial"] * 1000.0 / 3600.0)


def build_from_osm(centre, radius_km: float, path: str | Path) -> RoadGraph:
    """Real OSM extract. Needs `osmnx`; run once, offline afterwards."""
    import osmnx as ox  # optional dependency, imported lazily on purpose

    g = ox.graph_from_point(centre, dist=radius_km * 1000, network_type="drive")
    g = ox.add_edge_speeds(g)
    g = ox.add_edge_travel_times(g)
    G = nx.Graph()
    for n, d in g.nodes(data=True):
        G.add_node(n, x=d["x"], y=d["y"])
    for u, v, d in g.edges(data=True):
        if G.has_edge(u, v):
            continue
        speed = float(d.get("speed_kph", 30.0))
        G.add_edge(
            u,
            v,
            edge_id=f"E{min(u, v)}-{max(u, v)}",
            length_m=float(d.get("length", 1.0)),
            speed_kmh=speed,
            base_speed_kmh=speed,
            travel_time=float(d.get("travel_time", 1.0)),
            road_class="secondary",
            bridge=bool(d.get("bridge", False)),
            flooded=False,
            disabled=False,
        )
    rg = RoadGraph(G=G, centre=centre, radius_km=radius_km, river=[], bridges=[])
    save(rg, path)
    return rg


def load_or_build(path: str | Path, centre, radius_km: float, seed: int = 42) -> RoadGraph:
    """Load a pickled graph, else generate the synthetic one. Never downloads."""
    p = Path(path)
    if p.exists():
        with p.open("rb") as fh:
            return pickle.load(fh)
    rg = build_synthetic(centre, radius_km, seed=seed)
    save(rg, p)
    return rg


def save(rg: RoadGraph, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("wb") as fh:
        pickle.dump(rg, fh)


# --------------------------------------------------------------------------
# Degradation
# --------------------------------------------------------------------------


def flood_edges(rg: RoadGraph, edges, penalty: float = 5.0) -> None:
    """Flood road segments in place.

    A flooded edge is impassable to road vehicles and slow for boats. We do not
    delete it, because deleting it would lose the information that a boat could
    still get through - which is exactly the decision the solver has to make.
    """
    for u, v in edges:
        if not rg.G.has_edge(u, v):
            continue
        e = rg.G.edges[u, v]
        e["flooded"] = True
        e["travel_time"] = e["length_m"] / (e["base_speed_kmh"] * 1000.0 / 3600.0) * penalty


def disable_edges(rg: RoadGraph, edges) -> None:
    """Hard failure - a collapsed bridge. Nothing crosses, not even a boat."""
    for u, v in edges:
        if rg.G.has_edge(u, v):
            rg.G.edges[u, v]["disabled"] = True


def restore(rg: RoadGraph) -> None:
    for _, _, e in rg.G.edges(data=True):
        e["flooded"] = False
        e["disabled"] = False
        e["travel_time"] = e["length_m"] / (e["base_speed_kmh"] * 1000.0 / 3600.0)


def pick_degradable_edges(rg: RoadGraph, fraction: float, seed: int) -> list[tuple[int, int]]:
    """Choose which segments flood. Low-lying land is near the river, so
    crossings and their neighbours go first - degradation is not uniform."""
    rng = random.Random(seed)
    edges = list(rg.G.edges())
    near_river = [(u, v) for u, v in edges if rg.G.edges[u, v].get("bridge")]
    rest = [e for e in edges if e not in set(near_river)]
    rng.shuffle(rest)
    n = int(len(edges) * fraction)
    chosen = near_river[: max(1, n // 8)] + rest[: max(0, n - max(1, n // 8))]
    return chosen[:n]
