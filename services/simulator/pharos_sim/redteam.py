"""Red team: fabricated traffic injected into a live intake.

Three attacks, each modelled on something documented rather than invented:

  hoax_cluster          A fabricated event pushed hard by a handful of
                        accounts. Kerala 2018 saw fabricated dam-level alerts
                        and non-existent power shutdowns circulate alongside
                        genuine distress.

  amplification_cascade A real emergency, already resolved, re-shared until it
                        looks like the largest event on the map. This is the
                        2021 pattern: a bed or a cylinder was gone within
                        minutes, but the post kept circulating and kept
                        generating calls.

  stale_reports         Genuine emergencies, genuinely resolved, still in
                        circulation. No malice at all, and it still consumes
                        assets.

The point is not that the trust layer detects "fake news". The point is that
each of these consumes a physical asset, and the counterfactual - the plan with
and without trust scoring - is measurable in boats.
"""

from __future__ import annotations

import hashlib
import math
import random
from datetime import timedelta

from pharos_core import AttachedGeo, Channel, MessageEnvelope

from . import corpus
from .generator import TruthDemand

ATTACKS = ("hoax_cluster", "amplification_cascade", "stale_reports")


def inject(sensing, data, spec, now, kind: str = "hoax_cluster", **kw) -> dict:
    """Inject an attack into a live session's sensing state.

    Returns a summary the console can show. Injected messages are appended to
    the existing sensing result, so the next snapshot picks them up exactly as
    if they had arrived through intake.
    """
    if kind not in ATTACKS:
        raise ValueError(f"unknown attack {kind!r}; have {', '.join(ATTACKS)}")
    return {
        "hoax_cluster": _hoax_cluster,
        "amplification_cascade": _amplification_cascade,
        "stale_reports": _stale_reports,
    }[kind](sensing, data, spec, now, **kw)


# --------------------------------------------------------------------------


def _hoax_cluster(sensing, data, spec, now, n: int = 40, centre=None, people: int = 45) -> dict:
    """A fabricated mass-casualty event, pushed by two accounts.

    Its content is indistinguishable from a real report. Its signature is
    entirely in the corroboration structure: many messages, almost no
    independent voices, all arriving inside a few minutes.
    """
    rng = random.Random(spec.seed + int(now.timestamp()) % 10_000)
    lat, lon = centre or _offset_from(spec.region.centre, rng, 6_000.0)

    truth = TruthDemand(
        truth_id=f"T-HOAX-{len(data.truth):05d}",
        lat=lat,
        lon=lon,
        need=list(spec.needs.weights)[0],
        people=people,
        vulnerability_flags=["infant", "elderly"],
        medical_urgency=_worst_urgency(),
        onset=now,
        landmark=None,
        is_hoax=True,
    )
    data.truth.append(truth)

    # Two accounts. That is the tell, and it is the only tell.
    senders = [_hash(f"hoax-{truth.truth_id}-{i}") for i in range(2)]
    messages = []
    for i in range(n):
        lang = rng.choices(["en", "hi", "mixed"], weights=[0.4, 0.25, 0.35], k=1)[0]
        place = rng.choice(
            ["near the panchayat office", "near the bus stop", "behind the school"]
            if lang == "en"
            else ["panchayat office ke paas", "bus stop ke paas", "school ke peeche"]
        )
        text = corpus.render(truth.need, lang, people, place, truth.vulnerability_flags, rng)
        text = corpus.corrupt(text, 0.05, 0.10, rng)
        messages.append(
            MessageEnvelope(
                message_id=f"MSG-HOAX-{truth.truth_id}-{i:03d}",
                channel=Channel.SOCIAL,
                raw_text=text,
                sender_hash=rng.choice(senders),
                # All inside four minutes. Real events do not arrive like this.
                received_at=now + timedelta(seconds=rng.uniform(0, 240)),
                attached_geo=AttachedGeo(
                    lat=round(lat + rng.gauss(0, 0.0006), 6),
                    lon=round(lon + rng.gauss(0, 0.0006), 6),
                    accuracy_m=40.0,
                ),
                channel_metadata={"_truth_id": truth.truth_id, "_is_hoax": True, "language": lang},
            )
        )

    _append(sensing, data, messages, truth)
    return {
        "attack": "hoax_cluster",
        "messages": len(messages),
        "distinct_senders": len(senders),
        "claimed_people": people,
        "lat": lat,
        "lon": lon,
        "window_seconds": 240,
    }


def _amplification_cascade(sensing, data, spec, now, n: int = 25) -> dict:
    """A real, already-resolved case, re-shared until it dominates the map."""
    rng = random.Random(spec.seed + 7717)
    candidates = [t for t in data.truth if not t.is_hoax and t.onset < now - timedelta(minutes=90)]
    if not candidates:
        return {"attack": "amplification_cascade", "messages": 0, "reason": "nothing old enough"}
    source = rng.choice(candidates)

    senders = [_hash(f"amp-{source.truth_id}-{i}") for i in range(3)]
    messages = []
    for i in range(n):
        lang = rng.choice(["en", "hi", "mixed"])
        place = corpus.place_phrase(
            source.landmark.name if source.landmark else "the jetty", lang, rng
        )
        text = corpus.render(
            source.need, lang, source.people, place, source.vulnerability_flags, rng
        )
        messages.append(
            MessageEnvelope(
                message_id=f"MSG-AMP-{source.truth_id}-{i:03d}",
                channel=Channel.SOCIAL,
                raw_text=corpus.corrupt(text, 0.04, 0.20, rng),
                sender_hash=rng.choice(senders),
                received_at=now + timedelta(seconds=rng.uniform(0, 420)),
                attached_geo=AttachedGeo(
                    lat=round(source.lat + rng.gauss(0, 0.0004), 6),
                    lon=round(source.lon + rng.gauss(0, 0.0004), 6),
                    accuracy_m=45.0,
                ),
                channel_metadata={
                    "_truth_id": source.truth_id,
                    "_is_hoax": False,
                    "_amplified": True,
                    "language": lang,
                },
            )
        )

    _append(sensing, data, messages, source)
    return {
        "attack": "amplification_cascade",
        "messages": len(messages),
        "distinct_senders": len(senders),
        "source_event": source.truth_id,
        "original_onset_minutes_ago": round((now - source.onset).total_seconds() / 60.0, 1),
        "lat": source.lat,
        "lon": source.lon,
    }


def _stale_reports(sensing, data, spec, now, delay_hours: float = 2.0, n: int = 20) -> dict:
    """Genuine emergencies, resolved hours ago, still circulating.

    The 2021 failure with no bad actor in it. Freshness decay is the answer:
    a lead nobody has re-confirmed in three hours quietly stops competing.
    """
    rng = random.Random(spec.seed + 3313)
    old = [
        t for t in data.truth
        if not t.is_hoax and t.onset < now - timedelta(hours=delay_hours)
    ]
    if not old:
        return {"attack": "stale_reports", "messages": 0, "reason": "nothing old enough"}

    chosen = rng.sample(old, min(n, len(old)))
    messages = []
    for i, source in enumerate(chosen):
        lang = rng.choice(["en", "hi", "mixed"])
        place = corpus.place_phrase(
            source.landmark.name if source.landmark else "the colony", lang, rng
        )
        text = corpus.render(
            source.need, lang, source.people, place, source.vulnerability_flags, rng
        )
        messages.append(
            MessageEnvelope(
                message_id=f"MSG-STALE-{source.truth_id}-{i:03d}",
                channel=Channel.CHAT,
                raw_text=corpus.corrupt(text, 0.06, 0.15, rng),
                sender_hash=_hash(f"stale-relay-{rng.randrange(40)}"),
                received_at=now + timedelta(seconds=rng.uniform(0, 600)),
                attached_geo=None,
                channel_metadata={
                    "_truth_id": source.truth_id,
                    "_is_hoax": False,
                    "_stale": True,
                    "language": lang,
                },
            )
        )
        _append(sensing, data, [messages[-1]], source)

    return {
        "attack": "stale_reports",
        "messages": len(messages),
        "distinct_events": len(chosen),
        "delay_hours": delay_hours,
    }


# --------------------------------------------------------------------------


def _append(sensing, data, messages, truth) -> None:
    """Push injected messages through the live pipeline as one new cluster.

    They enter through the same normalize-extract-resolve path as anything
    else. Nothing about the attack is special-cased downstream: the trust layer
    reads the same corroboration structure it always reads.
    """
    pipeline = sensing.pipeline
    start = len(sensing.processed)
    for m in messages:
        data.messages.append(m)
        truth.message_ids.append(m.message_id)
        sensing.processed.append(pipeline._process_one(m, data.t0))

    members = list(range(start, len(sensing.processed)))
    sensing.clusters.append(members)
    rec = pipeline._reconcile(members, sensing.processed, messages[0].received_at)
    rec.truth_id = truth.truth_id
    sensing.demands.append(rec)

    # New cluster, so the snapshot cache and arrival index must be rebuilt.
    sensing._arrival_order = None
    sensing._cache.clear()


def _offset_from(centre, rng: random.Random, radius_m: float):
    lat, lon = centre
    th = rng.uniform(0, 2 * math.pi)
    r = radius_m * math.sqrt(rng.random())
    dlat = (r * math.sin(th) / 6_371_000.0) * (180.0 / math.pi)
    dlon = (r * math.cos(th) / (6_371_000.0 * math.cos(math.radians(lat)))) * (180.0 / math.pi)
    return round(lat + dlat, 6), round(lon + dlon, 6)


def _worst_urgency():
    from pharos_core import MedicalUrgency

    return MedicalUrgency.CRITICAL


def _hash(s: str) -> str:
    return hashlib.sha256(f"pharos-demo-salt::{s}".encode()).hexdigest()[:24]
