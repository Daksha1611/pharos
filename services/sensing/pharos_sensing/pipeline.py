"""The sensing pipeline: raw messages in, demand records out.

    normalize -> extract -> geo-resolve -> dedupe -> reconcile -> trust

One ordering note. The project document lists deduplication before
geo-resolution; this runs geo first, on purpose. The spatio-temporal gate is
what stops text similarity from merging half a district into one demand, and
the gate cannot run before every message has a location and a resolution
level. Resolving first also means the gate can widen itself for messages only
known to ward level instead of treating them as precise.

Every stage is switchable from SensingConfig, because each switch is one row
of the ablation table.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from pharos_core import (
    DemandRecord,
    FieldConfidence,
    MedicalUrgency,
    MessageEnvelope,
    Need,
    NeedType,
    TimeDecay,
)

from .dedupe import cluster as clustering
from .dedupe.embed import EmbedInput, get_embedder
from .geo.gazetteer import Gazetteer
from .geo.resolve import GeoResolver, consensus
from .normalize.language import detect
from .normalize.text import Normalizer
from .triage.calibration import Calibrator, headcount_interval
from .triage.extract import Extraction, extract
from .trust.score import ReportSignal, decay_existing
from .trust.score import score as trust_score


@dataclass
class SensingConfig:
    enable_normalization: bool = True
    enable_dedup: bool = True
    enable_calibration: bool = True
    enable_trust: bool = True
    enable_geo_cascade: bool = True
    enable_freshness_decay: bool = True

    embedder: str | None = None
    dedupe: clustering.DedupeParams = field(default_factory=clustering.DedupeParams)

    @classmethod
    def ablation(cls, name: str, **kw) -> SensingConfig:
        variants = {
            "full": {},
            "no_dedup": {"enable_dedup": False},
            "no_calibration": {"enable_calibration": False},
            "no_trust": {"enable_trust": False},
            "no_normalization": {"enable_normalization": False},
            "no_geo_cascade": {"enable_geo_cascade": False},
        }
        if name not in variants:
            raise KeyError(f"unknown sensing ablation {name!r}; have {sorted(variants)}")
        return cls(**{**variants[name], **kw})


@dataclass
class ProcessedMessage:
    """One message after normalization, extraction and geo-resolution."""

    envelope: MessageEnvelope
    extraction: Extraction
    location: object
    language: str
    minutes: float


@dataclass
class SensingResult:
    demands: list[DemandRecord]
    processed: list[ProcessedMessage]
    clusters: list[list[int]]
    pipeline: SensingPipeline | None = field(default=None, repr=False)

    # Per-cluster reconciliation cache, keyed by how many members were visible.
    _cache: dict[int, tuple[int, DemandRecord]] = field(default_factory=dict, repr=False)
    _arrival_order: list[list[int]] | None = field(default=None, repr=False)

    def cluster_of(self, message_id: str) -> int | None:
        for ci, members in enumerate(self.clusters):
            if any(self.processed[i].envelope.message_id == message_id for i in members):
                return ci
        return None

    def snapshot(self, now: datetime) -> list[DemandRecord]:
        """Demand state as it stood at `now`.

        A demand exists once its first message has arrived, and is built only
        from the member messages received by that moment. Corroboration that
        has not happened yet cannot raise its trust, and a lead that stopped
        being re-reported an hour ago decays exactly as it should.

        Clustering itself is computed once over the whole corpus rather than
        incrementally. That is a deliberate evaluation simplification: it keeps
        a six-hour scenario running in seconds, and every quantity the solver
        reads - headcount, confidence, trust, corroboration - still respects
        the clock. A live deployment clusters each intake window against the
        active demand set through this same interface.
        """
        if self.pipeline is None:
            raise RuntimeError("snapshot needs the pipeline that produced this result")

        # Members sorted by arrival, once, so "what was visible at `now`" is a
        # bisect rather than a scan of every member on every tick.
        if self._arrival_order is None:
            self._arrival_order = [
                sorted(m, key=lambda i: self.processed[i].envelope.received_at)
                for m in self.clusters
            ]

        out: list[DemandRecord] = []
        for ci, members in enumerate(self._arrival_order):
            n = _visible_count(members, self.processed, now)
            if not n:
                continue

            # A cluster whose visible members have not changed since the last
            # tick only needs its trust re-decayed, not a full re-reconcile.
            # Rebuilding every cluster on every replan cost 21 seconds a run.
            cached = self._cache.get(ci)
            if cached is not None and cached[0] == n:
                rec = cached[1].model_copy(deep=True)
                if self.pipeline.config.enable_trust and self.pipeline.config.enable_freshness_decay:
                    rec.trust_score = decay_existing(
                        cached[1].trust_score, rec.staleness_minutes(now)
                    )
            else:
                rec = self.pipeline._reconcile(members[:n], self.processed, now)
                # Stable identity across ticks, so the console and the audit
                # trail follow one demand rather than a new one every replan.
                rec.demand_id = self.demands[ci].demand_id
                rec.truth_id = self.demands[ci].truth_id
                self._cache[ci] = (n, rec.model_copy(deep=True))
            out.append(rec)
        return out


def _visible_count(members_sorted, processed, now) -> int:
    """How many of this cluster's messages had arrived by `now`.

    Members are pre-sorted by arrival, so this is a bisect over their
    timestamps rather than a scan.
    """
    lo, hi = 0, len(members_sorted)
    while lo < hi:
        mid = (lo + hi) // 2
        if processed[members_sorted[mid]].envelope.received_at <= now:
            lo = mid + 1
        else:
            hi = mid
    return lo


class SensingPipeline:
    def __init__(
        self,
        gazetteer: Gazetteer,
        region_centre: tuple[float, float],
        config: SensingConfig | None = None,
        calibrator: Calibrator | None = None,
        nominatim_url: str | None = None,
    ):
        self.config = config or SensingConfig()
        self.gazetteer = gazetteer
        self.region_centre = region_centre
        self.resolver = GeoResolver(
            gazetteer=gazetteer, region_centre=region_centre, nominatim_url=nominatim_url
        )
        self.embedder = get_embedder(self.config.embedder)
        self.calibrator = calibrator or Calibrator()

        self.normalizer = Normalizer()
        # Place names are vocabulary, not typos. Without this the corrector
        # "fixes" Vaikom into something else and the gazetteer stops matching.
        self.normalizer.add_vocabulary(
            w for e in gazetteer.entries for n in e.all_names() for w in n.lower().split()
        )

    # ------------------------------------------------------------------
    def process(
        self, messages: list[MessageEnvelope], now: datetime, t0: datetime
    ) -> SensingResult:
        processed = [self._process_one(m, t0) for m in messages]

        if self.config.enable_dedup:
            clusters = self._cluster(processed)
        else:
            # The naive column of the dedup comparison: every message is its
            # own emergency, which is what a system without this stage
            # believes.
            clusters = [[i] for i in range(len(processed))]

        demands = [self._reconcile(c, processed, now) for c in clusters]
        return SensingResult(
            demands=demands, processed=processed, clusters=clusters, pipeline=self
        )

    # ------------------------------------------------------------------
    def _process_one(self, msg: MessageEnvelope, t0: datetime) -> ProcessedMessage:
        if self.config.enable_normalization:
            lang = detect(msg.raw_text)
            msg.detected_language = lang.language
            msg.language_confidence = lang.confidence
            msg.normalized_text = self.normalizer.normalize(msg.raw_text)
        else:
            msg.normalized_text = msg.raw_text
            msg.detected_language = "unknown"

        ex = extract(msg.text_for_analysis())

        if self.config.enable_geo_cascade:
            loc = self.resolver.resolve(msg)
        else:
            # Without the cascade there is only what the channel attached, and
            # everything else lands on the region centroid as though it were
            # known. That is the failure mode the cascade exists to prevent.
            loc = self.resolver._from_attached_geo(msg) or self.resolver._unknown()

        return ProcessedMessage(
            envelope=msg,
            extraction=ex,
            location=loc,
            language=msg.detected_language or "unknown",
            minutes=(msg.received_at - t0).total_seconds() / 60.0,
        )

    # ------------------------------------------------------------------
    def _cluster(self, processed: list[ProcessedMessage]) -> list[list[int]]:
        vectors = self.embedder.encode(
            [
                EmbedInput(
                    text=p.envelope.text_for_analysis(),
                    need_type=p.extraction.need_type,
                    people=p.extraction.people,
                    vulnerability_flags=tuple(p.extraction.vulnerability_flags),
                    medical_urgency=p.extraction.medical_urgency,
                )
                for p in processed
            ]
        )
        items = [
            clustering.ClusterItem(
                key=p.envelope.message_id,
                lat=p.location.lat,
                lon=p.location.lon,
                minutes=p.minutes,
                vector=vectors[i],
                need_type=p.extraction.need_type.value,
                people=p.extraction.people,
                # Only a headcount read directly off the text may gate. A
                # household multiplier or a bare number is too soft to reject
                # a pair with, and a fallback prior would gate every message
                # against the same invented figure.
                people_confident=p.extraction.people_raw >= 0.85,
                resolution=p.location.resolution.value,
            )
            for i, p in enumerate(processed)
        ]
        return clustering.dedupe(items, self.config.dedupe)

    # ------------------------------------------------------------------
    def _reconcile(
        self, members: list[int], processed: list[ProcessedMessage], now: datetime
    ) -> DemandRecord:
        """Collapse a cluster into one demand record."""
        group = [processed[i] for i in members]
        exts = [p.extraction for p in group]

        need, need_conf_raw = _vote_need_type(exts)
        people, people_conf_raw = _reconcile_headcount(exts, need)
        vulns, vuln_raw = _union_vulnerabilities(exts)
        urgency, urg_raw = _max_urgency(exts)

        cal = self.calibrator if self.config.enable_calibration else None
        conf = FieldConfidence(
            need_type=_calibrate(cal, "need_type", need_conf_raw),
            headcount=_calibrate(cal, "headcount", people_conf_raw),
            vulnerability=_calibrate(cal, "vulnerability", vuln_raw),
            medical_urgency=_calibrate(cal, "medical_urgency", urg_raw),
        )

        # Corroboration sharpens a headcount: three independent people saying
        # "seven" is better evidence than one person saying it.
        distinct_senders = len({p.envelope.sender_hash for p in group})
        quantity_confidence = min(
            0.97, conf.headcount * (1.0 + 0.06 * min(3, distinct_senders - 1))
        )
        lower, point, upper = headcount_interval(people, quantity_confidence)

        location = consensus([p.location for p in group])

        first = min(p.envelope.received_at for p in group)
        last = max(p.envelope.received_at for p in group)

        if self.config.enable_trust:
            trust, _evidence = trust_score(
                [
                    ReportSignal(
                        sender_hash=p.envelope.sender_hash,
                        channel=p.envelope.channel.value,
                        received_at=p.envelope.received_at,
                        need_type=p.extraction.need_type.value,
                        people=p.extraction.people,
                    )
                    for p in group
                ],
                last_corroborated_at=last,
                now=now,
                enable_freshness=self.config.enable_freshness_decay,
            )
        else:
            trust = 1.0

        return DemandRecord(
            demand_id=f"DR-{uuid.uuid4().hex[:12]}",
            source_message_ids=[p.envelope.message_id for p in group],
            duplicate_collapse_count=len(group),
            location=location,
            need=Need(
                type=need,
                people=point,
                people_lower=lower,
                people_upper=upper,
                vulnerability_flags=vulns,
                medical_urgency=urgency,
            ),
            field_confidence=conf,
            quantity_confidence=round(quantity_confidence, 4),
            trust_score=trust,
            first_reported_at=first,
            last_corroborated_at=last,
            time_decay_class=_decay_class(need, urgency),
            channels=sorted({p.envelope.channel.value for p in group}),
            raw_texts=[p.envelope.raw_text for p in group][:8],
        )


# --------------------------------------------------------------------------
# reconciliation helpers
# --------------------------------------------------------------------------


def _calibrate(cal: Calibrator | None, head: str, raw: float) -> float:
    if cal is None:
        # Uncalibrated raw score, passed through as-is. This is the "before"
        # column of the reliability curve, and it is systematically
        # overconfident by design.
        return round(min(0.99, max(0.01, raw)), 4)
    return round(cal.apply(head, raw), 4)


def _vote_need_type(exts: list[Extraction]) -> tuple[NeedType, float]:
    """Confidence-weighted vote. Agreement across members raises confidence."""
    weights: dict[NeedType, float] = {}
    for e in exts:
        weights[e.need_type] = weights.get(e.need_type, 0.0) + e.need_type_raw

    winner = max(weights, key=weights.get)
    total = sum(weights.values()) or 1.0
    agreement = weights[winner] / total

    best_raw = max(e.need_type_raw for e in exts if e.need_type == winner)
    if len(exts) == 1:
        return winner, best_raw
    return winner, min(0.995, best_raw * (0.80 + 0.20 * agreement))


def _reconcile_headcount(exts: list[Extraction], need: NeedType) -> tuple[int, float]:
    """Median of the members that agree on the need type.

    Median, not mean: one person typing 200 instead of 20 should not move the
    committed capacity for everyone else in the cluster.
    """
    relevant = [e for e in exts if e.need_type == need] or exts
    weighted = sorted((e.people, e.people_raw) for e in relevant)
    values = [v for v, _ in weighted]
    point = values[len(values) // 2]

    best = max(e.people_raw for e in relevant)
    if len(relevant) == 1:
        return point, best

    # Members agreeing on a number is real evidence; disagreeing is real doubt.
    lo, hi = min(values), max(values)
    spread = (hi - lo) / max(1.0, point)
    agreement = max(0.0, 1.0 - min(1.0, spread / 1.5))
    return point, min(0.97, best * (0.72 + 0.28 * agreement))


def _union_vulnerabilities(exts: list[Extraction]) -> tuple[list[str], float]:
    """Union, not intersection. One reporter mentioning an infant is enough to
    plan for one; requiring consensus would drop exactly the detail that
    changes how an asset is equipped."""
    flags = sorted({f for e in exts for f in e.vulnerability_flags})
    raw = max(e.vulnerability_raw for e in exts)
    if flags and len(exts) > 1:
        mentions = Counter(f for e in exts for f in e.vulnerability_flags)
        top = max(mentions.values())
        raw = min(0.96, raw + 0.05 * (top - 1))
    return flags, raw


def _max_urgency(exts: list[Extraction]) -> tuple[MedicalUrgency, float]:
    """Take the worst urgency any member reported. Under-triaging a critical
    case is not a symmetric error with over-triaging a mild one."""
    order = list(MedicalUrgency)
    worst = max(exts, key=lambda e: order.index(e.medical_urgency))
    return worst.medical_urgency, worst.medical_urgency_raw


def _decay_class(need: NeedType, urgency: MedicalUrgency) -> TimeDecay:
    if urgency in (MedicalUrgency.CRITICAL, MedicalUrgency.MODERATE):
        return TimeDecay.ESCALATING
    if need in (NeedType.EVACUATION, NeedType.MISSING_PERSON):
        return TimeDecay.ESCALATING
    if need in (NeedType.FOOD, NeedType.SHELTER):
        return TimeDecay.STABLE
    return TimeDecay.STABLE
