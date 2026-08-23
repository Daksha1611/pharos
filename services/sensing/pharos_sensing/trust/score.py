"""Trust scoring.

Output is a continuous score, never a binary verdict, and it is an input to
the optimizer's objective rather than a filter on the feed. A hoax at trust
0.15 contributes 15% of its apparent value and loses to any real demand
nearby - suppressed, not deleted, and still visible to the operator.

That is the whole reframing: existing work treats disaster misinformation as a
content-moderation problem. Here it is a resource-contention problem. A hoax
does not just pollute a feed; it pulls a boat away from a real family.

Five components:

  corroboration   how many INDEPENDENT voices, not how many messages
  diversity       across channels and senders - ten posts from one group is
                  one voice, three posts from three channels is three
  consistency     do the member reports agree with each other
  freshness       decays from last_corroborated_at, 90-minute half-life
  propagation     a tight burst from very few accounts is what coordinated
                  amplification looks like from the outside

The freshness term is the 2021 stale-lead failure fixed in one line. A lead
nobody has re-confirmed in three hours quietly stops competing for assets,
instead of generating calls forever - which is exactly what happened with
oxygen and bed leads.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

HALF_LIFE = timedelta(minutes=90)

WEIGHTS = {
    "corroboration": 0.28,
    "diversity": 0.24,
    "consistency": 0.18,
    "freshness": 0.22,
    "propagation": 0.08,
}

# Independent voices needed before corroboration saturates. Three unrelated
# people reporting the same thing is strong; the fourth adds little.
CORROBORATION_SATURATION = 3.0

# A single uncorroborated report is not a hoax - most real emergencies are
# reported once. This is the floor a lone credible report keeps.
SINGLE_REPORT_BASE = 0.52


@dataclass
class TrustEvidence:
    """What the score was computed from. Goes straight to the operator panel."""

    corroboration: float = 0.0
    diversity: float = 0.0
    consistency: float = 1.0
    freshness: float = 1.0
    propagation: float = 1.0

    distinct_senders: int = 1
    distinct_channels: int = 1
    message_count: int = 1
    staleness_minutes: float = 0.0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "corroboration": round(self.corroboration, 3),
            "diversity": round(self.diversity, 3),
            "consistency": round(self.consistency, 3),
            "freshness": round(self.freshness, 3),
            "propagation": round(self.propagation, 3),
            "distinct_senders": self.distinct_senders,
            "distinct_channels": self.distinct_channels,
            "message_count": self.message_count,
            "staleness_minutes": round(self.staleness_minutes, 1),
            "notes": self.notes,
        }


@dataclass
class ReportSignal:
    """One member message of a demand, reduced to what trust cares about."""

    sender_hash: str
    channel: str
    received_at: datetime
    need_type: str
    people: int


def score(
    reports: list[ReportSignal],
    last_corroborated_at: datetime,
    now: datetime,
    enable_freshness: bool = True,
) -> tuple[float, TrustEvidence]:
    if not reports:
        return 0.0, TrustEvidence(message_count=0)

    ev = TrustEvidence(message_count=len(reports))
    senders = {r.sender_hash for r in reports}
    channels = {r.channel for r in reports}
    ev.distinct_senders = len(senders)
    ev.distinct_channels = len(channels)

    ev.corroboration = _corroboration(len(senders))
    ev.diversity = _diversity(reports)
    ev.consistency = _consistency(reports, ev)
    ev.staleness_minutes = max(0.0, (now - last_corroborated_at).total_seconds() / 60.0)
    ev.freshness = _freshness(ev.staleness_minutes) if enable_freshness else 1.0
    ev.propagation = _propagation(reports, len(senders), ev)

    raw = (
        WEIGHTS["corroboration"] * ev.corroboration
        + WEIGHTS["diversity"] * ev.diversity
        + WEIGHTS["consistency"] * ev.consistency
        + WEIGHTS["freshness"] * ev.freshness
        + WEIGHTS["propagation"] * ev.propagation
    )

    # A lone report from one person is the ordinary case, not a red flag. Lift
    # single-source demands toward a neutral floor so the system does not
    # systematically starve people who only had time to message once.
    if len(senders) == 1 and ev.propagation > 0.6:
        raw = max(raw, SINGLE_REPORT_BASE * ev.freshness)

    return round(min(1.0, max(0.0, raw)), 4), ev


# --------------------------------------------------------------------------


def _corroboration(distinct_senders: int) -> float:
    """Counts voices, not messages. One person posting eight times is one."""
    return min(1.0, distinct_senders / CORROBORATION_SATURATION)


def _diversity(reports: list[ReportSignal]) -> float:
    """Normalized entropy over channels, tempered by sender concentration.

    Ten reports from one WhatsApp group are one voice. Three from three
    channels are three.
    """
    channel_counts = Counter(r.channel for r in reports)
    sender_counts = Counter(r.sender_hash for r in reports)

    ch = _normalized_entropy(channel_counts)
    sd = _normalized_entropy(sender_counts)

    # A single channel caps diversity regardless of how many accounts posted -
    # one group chat is one vantage point on the event.
    channel_ceiling = min(1.0, len(channel_counts) / 3.0)
    return round(min(channel_ceiling, 0.45 * ch + 0.55 * sd), 4)


def _normalized_entropy(counts: Counter) -> float:
    n = sum(counts.values())
    k = len(counts)
    if n <= 1 or k <= 1:
        return 0.0
    h = -sum((c / n) * math.log(c / n) for c in counts.values())
    return h / math.log(k)


def _consistency(reports: list[ReportSignal], ev: TrustEvidence) -> float:
    """Do the member reports actually agree?

    Disagreement on the need type is a strong signal that clustering merged two
    different events, or that someone is embellishing. Disagreement on
    headcount is normal - people estimate - so it is penalised gently.
    """
    if len(reports) < 2:
        return 1.0

    types = Counter(r.need_type for r in reports)
    type_agreement = types.most_common(1)[0][1] / len(reports)

    counts = [r.people for r in reports if r.people > 0]
    spread = 1.0
    if len(counts) >= 2:
        mean = sum(counts) / len(counts)
        if mean > 0:
            cv = (max(counts) - min(counts)) / mean
            spread = max(0.0, 1.0 - min(1.0, cv / 2.5))

    if type_agreement < 0.7:
        ev.notes.append(
            f"members disagree on need type ({types.most_common(1)[0][0]} in "
            f"{type_agreement:.0%} of reports)"
        )

    return round(0.7 * type_agreement + 0.3 * spread, 4)


def _freshness(staleness_minutes: float) -> float:
    """Exponential decay, 90-minute half-life.

    At three hours a lead is worth a quarter of what it was. This is the fix
    for leads that stayed in circulation long after the bed or the cylinder
    was gone.
    """
    return round(0.5 ** (staleness_minutes / (HALF_LIFE.total_seconds() / 60.0)), 4)


def _propagation(reports: list[ReportSignal], distinct_senders: int, ev: TrustEvidence) -> float:
    """Coordinated amplification: many messages, very few accounts, tight window.

    Real events accumulate reports from unrelated people over time. A push
    campaign arrives all at once from the same handful of sources.
    """
    n = len(reports)
    if n < 4:
        return 1.0

    per_sender = n / max(1, distinct_senders)
    times = sorted(r.received_at for r in reports)
    span_min = max(1.0, (times[-1] - times[0]).total_seconds() / 60.0)
    rate = n / span_min  # messages per minute

    penalty = 0.0
    if per_sender >= 3.0:
        penalty += min(0.55, 0.16 * (per_sender - 2.0))
        ev.notes.append(f"{n} reports from only {distinct_senders} account(s)")
    if rate > 0.5 and distinct_senders <= 2:
        penalty += 0.25
        ev.notes.append(f"burst pattern: {rate:.1f} reports/min from {distinct_senders} account(s)")

    return round(max(0.05, 1.0 - penalty), 4)


# --------------------------------------------------------------------------


def decay_existing(current_trust: float, staleness_minutes: float, floor: float = 0.05) -> float:
    """Re-apply freshness to a demand nothing new has arrived for.

    Called on every replan tick, so an unconfirmed demand loses its claim on
    assets gradually rather than at some arbitrary expiry.
    """
    return round(max(floor, current_trust * _freshness(staleness_minutes)), 4)
