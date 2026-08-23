"""Duplicate clustering, gated by space, time and semantics.

The gate is the whole trick. Two messages saying "we need a boat, water
rising" are near-identical in embedding space and are *not* duplicates if they
are four kilometres apart. Text similarity alone merges half a district into
one demand, and a merged demand is a family nobody comes for.

Four things had to be right before the gate worked at all, and each of them
came out of measuring against generator ground truth rather than guessing:

  Resolution-aware radius.  A fixed 350m gate missed half of all true pairs,
      because one report of an event may carry a GPS pin while another only
      names a landmark 600m away. The gate radius is now the base tolerance
      plus each message's own positional uncertainty, so two coarse reports
      get a wide gate and two precise reports get a tight one.

  Need type must agree.  Two different resource requirements at one address
      are two demands, not one. A household that needs both a boat and a
      medic generates two records on purpose - they are served by different
      assets.

  Headcount must agree.  Two reports of the same household agree roughly on
      how many people are in it. This is what separates eight different
      emergencies that all resolved to the same landmark, where the distance
      gate carries no information whatsoever.

  Unlocatable messages are not deduplicated at all.  A quarter of intake
      resolves to nothing better than the district centroid. Merging those on
      distance would mean merging on a coordinate we invented, and merging
      them on text alone is worse: measured against ground truth it produced a
      single cluster of 87 messages spanning 61 unrelated emergencies across
      the whole district, because "5 people need a boat" reads the same
      wherever it was sent from. They stay separate and are flagged for the
      operator's disambiguation queue. We cannot tell whether two reports we
      could not locate are one household or two, and guessing costs a family
      the boat that was coming for them.

Finally, connected components are refined against the cluster centroid:
A-B similar and B-C similar does not make A-C the same emergency. We bias
toward under-merging throughout and leave manual merge to the operator,
because an operator can merge two records in a second and cannot un-strand a
family.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

import h3
import numpy as np

EARTH_RADIUS_M = 6_371_000.0

# Base tolerance, before each message's own positional uncertainty is added.
DEFAULT_RADIUS_M = 180.0
DEFAULT_WINDOW_MIN = 90.0
# Chosen by sweeping against generator ground truth, not by taste. At 0.68 the
# gate holds pairwise precision at 0.84 on locatable messages for a recall of
# 0.43. Raising it buys precision at a steep cost in recall; lowering it loses
# precision fast. Precision is the number to protect: a wrongly merged demand
# is a family nobody comes for, while a missed merge only costs a second of
# operator time to fix.
DEFAULT_SIM_THRESHOLD = 0.68

# How far a location of each resolution level may actually be from the truth.
# These are measured from the geo cascade, not assumed - see the resolution
# accuracy table in the evaluation output.
POSITION_UNCERTAINTY_M = {
    "point": 60.0,
    "building": 180.0,
    "street": 550.0,
    "ward": 2600.0,
    "unknown": float("inf"),
}

# A member must be at least this similar to its cluster's centroid to stay in
# it. Lower than the pairwise threshold, because a centroid is an average.
CENTROID_THRESHOLD_RATIO = 0.88


@dataclass
class ClusterItem:
    """One message, reduced to what the gate needs to compare."""

    key: str
    lat: float
    lon: float
    minutes: float  # minutes since scenario start
    vector: np.ndarray = field(repr=False)

    need_type: str = "unknown"
    people: int = 0
    people_confident: bool = False
    resolution: str = "unknown"

    @property
    def uncertainty_m(self) -> float:
        return POSITION_UNCERTAINTY_M.get(self.resolution, float("inf"))

    @property
    def locatable(self) -> bool:
        return math.isfinite(self.uncertainty_m)


@dataclass
class DedupeParams:
    radius_m: float = DEFAULT_RADIUS_M
    window_min: float = DEFAULT_WINDOW_MIN
    sim_threshold: float = DEFAULT_SIM_THRESHOLD

    # Two reports of the same household should agree on its size to within
    # about this factor. Beyond it they are different events. Only a headcount
    # the extractor read directly off the text gates on this - a figure derived
    # from a household multiplier is too soft to reject a pair with.
    max_headcount_ratio: float = 1.6

    # Merging messages we could not locate. Off by default and deliberately
    # so - see the module docstring. Available as a switch because it is one
    # row of the ablation table.
    merge_unlocatable: bool = False
    unlocatable_sim_threshold: float = 0.93

    require_need_type_match: bool = True
    max_block_size: int = 600

    # A gate radius grows with both messages' positional uncertainty, and past
    # a point it stops being a gate: two ward-level reports need a 5km radius,
    # and inside 5km of an Indian district there are dozens of unrelated
    # emergencies. Beyond `precise_pair_radius_m` the pair must clear a much
    # higher text bar and agree closely on headcount; beyond
    # `max_pair_radius_m` it is not merged at all.
    # 1400m admits point-point (300m), point-street (790m) and street-street
    # (1280m) to the normal threshold - the three pair types that make up most
    # of intake. Anything involving a ward-level report needs more than that
    # and gets the coarse treatment instead.
    precise_pair_radius_m: float = 1400.0
    max_pair_radius_m: float = 3000.0
    coarse_sim_threshold: float = 0.86
    coarse_headcount_ratio: float = 1.35


def dedupe(items: list[ClusterItem], params: DedupeParams | None = None) -> list[list[int]]:
    """Returns clusters as lists of indices into `items`. Singletons included."""
    p = params or DedupeParams()
    n = len(items)
    if n == 0:
        return []
    if n == 1:
        return [[0]]

    edges = _candidate_edges(items, p)
    components = _connected_components(n, edges)
    return _refine(components, items, p)


# --------------------------------------------------------------------------
# blocking
# --------------------------------------------------------------------------

# H3 resolutions and the disk radius each one covers, finest first.
_TIER_REACH_M = {10: 200.0, 9: 500.0, 8: 1400.0, 7: 3700.0, 6: 9800.0}
_BLOCK_TIERS = sorted(_TIER_REACH_M)


def _tier_for(reach_m: float) -> int:
    for res in _BLOCK_TIERS:
        if _TIER_REACH_M[res] >= reach_m:
            return res
    return _BLOCK_TIERS[-1]


def _tiers_for_item(uncertainty_m: float, base_radius_m: float) -> set[int]:
    """Every tier at which this message might need to meet a partner.

    A pair's gate radius is the base plus BOTH positional uncertainties, so the
    tier a pair meets at depends on the partner too. Registering an item at
    only its own tier means a GPS-pinned report and a landmark-resolved one
    never share a block and can never be compared - which measured as a
    recall ceiling of 0.24 no similarity threshold could lift, because the
    pairs were never scored at all.
    """
    return {
        _tier_for(base_radius_m + uncertainty_m + partner)
        for partner in POSITION_UNCERTAINTY_M.values()
        if math.isfinite(partner)
    }


def _headcount_bucket(n: int) -> int:
    """Coarse log bucket, used only to partition unlocatable messages."""
    return 0 if n <= 0 else int(math.log1p(n) / math.log(3.0))


def _candidate_edges(items, p: DedupeParams) -> list[tuple[int, int, float]]:
    blocks: dict[tuple, list[int]] = defaultdict(list)

    for i, it in enumerate(items):
        tb = int(it.minutes // p.window_min)
        if not it.locatable:
            if not p.merge_unlocatable:
                # Left as a singleton on purpose. It becomes its own demand and
                # carries a disambiguation flag for the operator.
                continue
            # Partition on what we do know - the need, roughly how many people,
            # and when - and let text similarity do the rest under a much
            # higher bar.
            for t in (tb - 1, tb):
                blocks[("u", it.need_type, _headcount_bucket(it.people), t)].append(i)
            continue

        # Register at every tier this message might need, so a coarse report
        # and a precise one actually meet somewhere.
        for res in _tiers_for_item(it.uncertainty_m, p.radius_m):
            cell = h3.latlng_to_cell(it.lat, it.lon, res)
            for c in h3.grid_disk(cell, 1):
                for t in (tb - 1, tb):
                    blocks[("g", res, c, t)].append(i)

    seen: set[tuple[int, int]] = set()
    edges: list[tuple[int, int, float]] = []

    for idxs in blocks.values():
        if len(idxs) < 2:
            continue
        # A pathologically large block means the gate is not discriminating.
        # Cap it rather than degenerating to all-pairs inside one cell.
        if len(idxs) > p.max_block_size:
            idxs = idxs[: p.max_block_size]

        V = np.stack([items[i].vector for i in idxs])
        S = V @ V.T
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                i, j = idxs[a], idxs[b]
                key = (i, j) if i < j else (j, i)
                if key in seen:
                    continue
                seen.add(key)
                sim = float(S[a, b])
                if _passes_gate(items[i], items[j], sim, p):
                    edges.append((key[0], key[1], sim))
    return edges


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------


def _passes_gate(x: ClusterItem, y: ClusterItem, sim: float, p: DedupeParams) -> bool:
    # --- time -------------------------------------------------------------
    if abs(x.minutes - y.minutes) > p.window_min:
        return False

    # --- need type --------------------------------------------------------
    # Two different resource requirements at one address are two demands.
    if p.require_need_type_match and x.need_type != y.need_type:
        return False

    # --- headcount --------------------------------------------------------
    # The signal that separates eight emergencies behind the same mill, where
    # every one of them resolved to the identical landmark coordinate.
    if x.people_confident and y.people_confident and x.people > 0 and y.people > 0:
        lo, hi = sorted((x.people, y.people))
        if hi > lo * p.max_headcount_ratio:
            return False

    # --- space ------------------------------------------------------------
    if x.locatable and y.locatable:
        radius = p.radius_m + x.uncertainty_m + y.uncertainty_m
        if radius > p.max_pair_radius_m:
            # Neither report is precise enough for distance to mean anything
            # between them. Refusing to merge is the honest answer.
            return False
        if metres(x.lat, x.lon, y.lat, y.lon) > radius:
            return False
        if radius <= p.precise_pair_radius_m:
            return sim >= p.sim_threshold
        # A wide gate has to be paid for somewhere. Both reports must agree
        # closely on how many people, and read much more alike.
        if x.people > 0 and y.people > 0:
            lo, hi = sorted((x.people, y.people))
            if hi > lo * p.coarse_headcount_ratio:
                return False
        return sim >= p.coarse_sim_threshold

    # Neither has a usable coordinate. Distance would be a comparison of two
    # invented positions, so it is not consulted at all and the text bar rises.
    # Reached only when merge_unlocatable is explicitly turned on.
    return sim >= p.unlocatable_sim_threshold


def metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


# --------------------------------------------------------------------------
# components and the anti-chaining pass
# --------------------------------------------------------------------------


def _connected_components(n: int, edges) -> list[list[int]]:
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i, j, _ in edges:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)
    return list(groups.values())


def _refine(components, items, p: DedupeParams) -> list[list[int]]:
    """Break chains: every member must resemble the cluster, not just a peer.

    A-B and B-C both clearing the pairwise bar does not make A and C the same
    emergency. Anything that falls away from the centroid is split back out as
    its own demand - under-merging, deliberately.
    """
    out: list[list[int]] = []
    for comp in components:
        if len(comp) <= 2:
            out.append(sorted(comp))
            continue

        members = list(comp)
        guard = 0
        while members and guard < 64:
            guard += 1
            V = np.stack([items[i].vector for i in members])
            centroid = V.mean(axis=0)
            norm = np.linalg.norm(centroid)
            if norm < 1e-9:
                out.append(sorted(members))
                break
            sims = V @ (centroid / norm)
            bar = p.sim_threshold * CENTROID_THRESHOLD_RATIO

            keep = [m for m, s in zip(members, sims, strict=True) if s >= bar]
            drop = [m for m, s in zip(members, sims, strict=True) if s < bar]
            if not keep:
                out.extend([m] for m in members)
                break
            out.append(sorted(keep))
            if not drop:
                break
            members = drop
            if len(members) <= 2:
                out.append(sorted(members))
                break
    return out


def cluster_spread_m(cluster: list[int], items) -> float:
    """Widest separation inside a cluster. A sanity check the operator can see."""
    located = [i for i in cluster if items[i].locatable]
    if len(located) < 2:
        return 0.0
    return max(
        metres(items[i].lat, items[i].lon, items[j].lat, items[j].lon)
        for a, i in enumerate(located)
        for j in located[a + 1 :]
    )


def needs_disambiguation(cluster: list[int], items) -> bool:
    """True when a cluster was formed without any usable location.

    These go to the operator's disambiguation queue rather than being silently
    trusted - the demand is real, but where it is remains an open question.
    """
    return all(not items[i].locatable for i in cluster)
