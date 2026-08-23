"""Scenario specification.

Every dial in here is an ablation axis. That is the point: setting
`duplicate_rate` to 0.25 reproduces the documented Kerala 2018 condition, and
setting it to 0.0 tells you what deduplication was worth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from pharos_core import NeedType


@dataclass
class RegionSpec:
    centre: tuple[float, float] = (9.9312, 76.2673)
    radius_km: float = 25.0
    h3_resolution: int = 8
    gazetteer_entries: int = 200


@dataclass
class ArrivalSpec:
    """Lognormal arrival curve. Real crisis traffic is not uniform - it spikes."""

    curve: str = "lognormal"
    peak_hour: float = 2.0
    sigma: float = 0.8


@dataclass
class AmplificationSpec:
    """Social re-sharing on top of the base duplicate rate.

    Kerala 2018 documented ~25% duplicates among structured form submissions.
    The 2021 and 2023 cases show that on social channels the same event is
    re-shared many times over - which is a different, larger effect.
    """

    enabled: bool = True
    share_fraction: float = 0.55
    mean_extra: float = 4.0


@dataclass
class MessageSpec:
    total: int = 6000
    arrival: ArrivalSpec = field(default_factory=ArrivalSpec)
    duplicate_rate: float = 0.25
    amplification: AmplificationSpec = field(default_factory=AmplificationSpec)
    language_mix: dict[str, float] = field(
        default_factory=lambda: {"en": 0.45, "hi": 0.25, "mixed": 0.30}
    )
    channel_mix: dict[str, float] = field(
        default_factory=lambda: {
            "chat": 0.34,
            "social": 0.30,
            "sms": 0.18,
            "web_form": 0.10,
            "call_transcript": 0.05,
            "control_room": 0.03,
        }
    )
    typo_rate: float = 0.08
    shorthand_rate: float = 0.15
    geo_present_rate: float = 0.35
    landmark_mention_rate: float = 0.55
    hoax_rate: float = 0.03

    @property
    def expected_messages_per_demand(self) -> float:
        base = 1.0 / max(1e-6, 1.0 - self.duplicate_rate)
        amp = (
            self.amplification.share_fraction * self.amplification.mean_extra
            if self.amplification.enabled
            else 0.0
        )
        return base + amp


@dataclass
class NeedMix:
    weights: dict[NeedType, float] = field(
        default_factory=lambda: {
            NeedType.EVACUATION: 0.40,
            NeedType.MEDICAL: 0.20,
            NeedType.WATER: 0.15,
            NeedType.FOOD: 0.15,
            NeedType.SHELTER: 0.10,
        }
    )


@dataclass
class AssetSpec:
    type: str
    count: int
    capacity: int
    speed_kmh: float
    depots: int = 3


@dataclass
class DegradationEvent:
    at_hour: float
    disable_fraction: float
    mode: str = "flood"  # flood | collapse


@dataclass
class ScenarioSpec:
    name: str = "kerala_flood_demo"
    seed: int = 42
    duration_hours: float = 6.0
    replan_minutes: float = 15.0
    region: RegionSpec = field(default_factory=RegionSpec)
    messages: MessageSpec = field(default_factory=MessageSpec)
    needs: NeedMix = field(default_factory=NeedMix)
    assets: list[AssetSpec] = field(default_factory=list)
    road_degradation: list[DegradationEvent] = field(default_factory=list)
    population_affected: int = 40000

    @property
    def n_truth_demands(self) -> int:
        return max(1, int(self.messages.total / self.messages.expected_messages_per_demand))


def load(path: str | Path) -> ScenarioSpec:
    raw = yaml.safe_load(Path(path).read_text())
    return from_dict(raw)


def from_dict(raw: dict) -> ScenarioSpec:
    region = RegionSpec(**{**RegionSpec().__dict__, **_get(raw, "region")})
    region.centre = tuple(region.centre)

    mraw = _get(raw, "messages")
    arrival = ArrivalSpec(**{**ArrivalSpec().__dict__, **mraw.pop("arrival", {})})
    amp = AmplificationSpec(**{**AmplificationSpec().__dict__, **mraw.pop("amplification", {})})
    messages = MessageSpec(
        **{**{k: v for k, v in MessageSpec().__dict__.items() if k not in ("arrival", "amplification")}, **mraw}
    )
    messages.arrival = arrival
    messages.amplification = amp

    needs = NeedMix(weights={NeedType(k): float(v) for k, v in _get(raw, "needs").items()} or None)
    if not needs.weights:
        needs = NeedMix()

    assets = [AssetSpec(**a) for a in raw.get("assets", [])]
    degradation = [DegradationEvent(**d) for d in raw.get("road_degradation", [])]

    return ScenarioSpec(
        name=raw.get("name", "unnamed"),
        seed=int(raw.get("seed", 42)),
        duration_hours=float(raw.get("duration_hours", 6.0)),
        replan_minutes=float(raw.get("replan_minutes", 15.0)),
        region=region,
        messages=messages,
        needs=needs,
        assets=assets,
        road_degradation=degradation,
        population_affected=int(raw.get("population", {}).get("affected", 40000)),
    )


def _get(raw: dict, key: str) -> dict:
    return dict(raw.get(key) or {})
