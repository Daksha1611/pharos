"""Scenario generator.

Ground truth first, then messages generated *from* it - including the
duplicates. That ordering is what makes deduplication measurable: we know
exactly which messages should collapse into which demand, so precision and
recall are computed against a known answer rather than eyeballed.

Ground-truth linkage rides in `channel_metadata["_truth_id"]`. Keys prefixed
with an underscore are evaluation-only. No module under `pharos_sensing` may
read one, and a test enforces that.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from pharos_core import AttachedGeo, Channel, MedicalUrgency, MessageEnvelope, NeedType
from pharos_sensing.geo import gazetteer as gz

from . import corpus
from .spec import ScenarioSpec

T0 = datetime(2026, 8, 17, 4, 0, 0)  # scenario clock origin

VULNERABILITIES = ["infant", "elderly", "pregnant", "disabled", "injured"]

# Household and group sizes, by need type. Water and food requests come from
# camps and clusters of families; evacuation comes from single households.
_SIZE_BANDS = {
    "household": [(1, 3, 0.38), (4, 6, 0.37), (7, 12, 0.19), (13, 30, 0.06)],
    "cluster": [(5, 15, 0.30), (16, 40, 0.40), (41, 90, 0.22), (91, 200, 0.08)],
}
_CLUSTER_NEEDS = {NeedType.WATER, NeedType.FOOD, NeedType.SANITATION, NeedType.SHELTER}

# Place references with no prefix. Every district has a dozen of each, so these
# are worth a ward and nothing finer.
_GENERIC_PLACES = {
    "en": [
        "near the panchayat office", "near the temple", "near the bus stop",
        "behind the school", "near the jetty", "in our colony",
        "opposite the church", "near the water tank",
    ],
    "hi": [
        "panchayat office ke paas", "mandir ke paas", "bus stop ke paas",
        "school ke peeche", "kadavu ke paas", "hamari colony me",
        "masjid ke saamne", "paani ki tanki ke paas",
    ],
    "mixed": [
        "panchayat office ke paas", "temple ke paas", "bus stop ke near",
        "school ke behind", "jetty ke paas", "hamari colony me",
        "church ke saamne", "water tank ke paas",
    ],
}


@dataclass
class TruthDemand:
    """What is actually happening. The sensing layer never sees this."""

    truth_id: str
    lat: float
    lon: float
    need: NeedType
    people: int
    vulnerability_flags: list[str]
    medical_urgency: MedicalUrgency
    onset: datetime
    landmark: gz.GazetteerEntry | None
    is_hoax: bool = False
    message_ids: list[str] = field(default_factory=list)
    h3_cell: str | None = None


@dataclass
class ScenarioData:
    spec: ScenarioSpec
    truth: list[TruthDemand]
    messages: list[MessageEnvelope]
    gazetteer: gz.Gazetteer
    t0: datetime = T0

    @property
    def real_truth(self) -> list[TruthDemand]:
        return [t for t in self.truth if not t.is_hoax]

    @property
    def hoax_truth(self) -> list[TruthDemand]:
        return [t for t in self.truth if t.is_hoax]

    def truth_by_id(self) -> dict[str, TruthDemand]:
        return {t.truth_id: t for t in self.truth}

    def message_truth_map(self) -> dict[str, str]:
        return {m.message_id: m.channel_metadata["_truth_id"] for m in self.messages}

    def realized_duplicate_rate(self) -> float:
        n = len(self.messages)
        return 0.0 if not n else 1.0 - (len(self.truth) / n)


def generate(spec: ScenarioSpec) -> ScenarioData:
    rng = random.Random(spec.seed)
    gazetteer = gz.build(
        spec.region.centre, spec.region.radius_km, spec.region.gazetteer_entries, spec.seed
    )

    truth = _generate_truth(spec, gazetteer, rng)
    messages = _generate_messages(spec, truth, rng)

    return ScenarioData(spec=spec, truth=truth, messages=messages, gazetteer=gazetteer)


# --------------------------------------------------------------------------
# ground truth
# --------------------------------------------------------------------------


def _generate_truth(spec: ScenarioSpec, gazetteer: gz.Gazetteer, rng: random.Random):
    n = spec.n_truth_demands
    n_hoax = int(n * spec.messages.hoax_rate)

    need_types = list(spec.needs.weights.keys())
    need_weights = list(spec.needs.weights.values())

    truth: list[TruthDemand] = []
    for i in range(n):
        need = rng.choices(need_types, weights=need_weights, k=1)[0]
        landmark = rng.choice(gazetteer.entries)

        # Demands sit near a landmark, not on it. People report the nearest
        # thing they can name, which is what makes landmark resolution
        # street-accurate rather than building-accurate.
        jitter = landmark.radius_m * rng.uniform(0.2, 2.4)
        th = rng.uniform(0, 2 * math.pi)
        lat, lon = gz._offset(landmark.lat, landmark.lon, jitter * math.cos(th), jitter * math.sin(th))

        people = _sample_size(need, rng)
        vulns = _sample_vulnerabilities(rng)
        urgency = _sample_urgency(need, rng)
        onset = T0 + timedelta(hours=_sample_arrival(spec, rng))

        truth.append(
            TruthDemand(
                truth_id=f"T-{i:06d}",
                lat=round(lat, 6),
                lon=round(lon, 6),
                need=need,
                people=people,
                vulnerability_flags=vulns,
                medical_urgency=urgency,
                onset=onset,
                landmark=landmark,
                is_hoax=False,
            )
        )

    # Hoaxes: fabricated events that look exactly like real ones on the surface.
    # Their signature is in corroboration structure, not in content.
    for t in rng.sample(truth, min(n_hoax, len(truth))):
        t.is_hoax = True

    return truth


def _sample_size(need: NeedType, rng: random.Random) -> int:
    bands = _SIZE_BANDS["cluster" if need in _CLUSTER_NEEDS else "household"]
    lo, hi, _ = rng.choices(bands, weights=[b[2] for b in bands], k=1)[0]
    return rng.randint(lo, hi)


def _sample_vulnerabilities(rng: random.Random) -> list[str]:
    if rng.random() > 0.45:
        return []
    k = 1 if rng.random() < 0.75 else 2
    return sorted(rng.sample(VULNERABILITIES, k))


def _sample_urgency(need: NeedType, rng: random.Random) -> MedicalUrgency:
    if need is NeedType.MEDICAL:
        return rng.choices(
            [MedicalUrgency.MILD, MedicalUrgency.MODERATE, MedicalUrgency.CRITICAL],
            weights=[0.30, 0.45, 0.25],
            k=1,
        )[0]
    if need is NeedType.EVACUATION:
        return rng.choices(
            [MedicalUrgency.NONE, MedicalUrgency.MILD, MedicalUrgency.MODERATE],
            weights=[0.68, 0.24, 0.08],
            k=1,
        )[0]
    return rng.choices([MedicalUrgency.NONE, MedicalUrgency.MILD], weights=[0.88, 0.12], k=1)[0]


def _sample_arrival(spec: ScenarioSpec, rng: random.Random) -> float:
    """Hours from scenario start. Lognormal: crisis traffic spikes, then tails."""
    a = spec.messages.arrival
    if a.curve != "lognormal":
        return rng.uniform(0.0, spec.duration_hours)
    mu = math.log(max(0.15, a.peak_hour)) + a.sigma**2
    h = rng.lognormvariate(mu, a.sigma)
    return min(h, spec.duration_hours * 0.995)


# --------------------------------------------------------------------------
# messages derived from ground truth
# --------------------------------------------------------------------------


def _generate_messages(spec: ScenarioSpec, truth: list[TruthDemand], rng: random.Random):
    ms = spec.messages
    langs, lang_w = list(ms.language_mix), list(ms.language_mix.values())
    chans, chan_w = list(ms.channel_mix), list(ms.channel_mix.values())

    messages: list[MessageEnvelope] = []
    counter = 0

    for t in truth:
        n_reports = _report_count(ms, t, rng)

        # A hoax cluster is pushed by a small number of accounts. Real events
        # are reported by unrelated people. That difference is the whole
        # signal the trust layer reads.
        hoax_senders = (
            [f"hoax-{t.truth_id}-{k}" for k in range(rng.randint(1, 2))] if t.is_hoax else []
        )

        for r in range(n_reports):
            counter += 1
            mid = f"MSG-{counter:07d}"
            lang = rng.choices(langs, weights=lang_w, k=1)[0]
            channel = Channel(rng.choices(chans, weights=chan_w, k=1)[0])

            # Re-reports trail the original by minutes to an hour or two.
            delay = 0.0 if r == 0 else abs(rng.gauss(22.0, 26.0))
            ts = t.onset + timedelta(minutes=delay)

            # Reported headcount drifts from the truth. People estimate.
            reported_n = max(1, int(round(t.people * rng.gauss(1.0, 0.18))))

            text, mentioned_landmark = _compose(spec, t, lang, reported_n, rng)
            text = corpus.corrupt(text, ms.typo_rate, ms.shorthand_rate, rng)

            geo = None
            if rng.random() < ms.geo_present_rate:
                # A dropped pin or a phone fix. Accuracy varies by an order of
                # magnitude, and the geo cascade has to respect that.
                acc = rng.choice([12.0, 35.0, 90.0, 400.0, 1500.0])
                dl = acc / 111_320.0
                geo = AttachedGeo(
                    lat=round(t.lat + rng.gauss(0, dl), 6),
                    lon=round(t.lon + rng.gauss(0, dl), 6),
                    accuracy_m=acc,
                )

            sender = (
                rng.choice(hoax_senders)
                if hoax_senders
                else f"{t.truth_id}-{r}" if rng.random() < 0.72 else f"relay-{rng.randrange(400)}"
            )

            messages.append(
                MessageEnvelope(
                    message_id=mid,
                    channel=channel,
                    raw_text=text,
                    sender_hash=_hash(sender),
                    received_at=ts,
                    attached_geo=geo,
                    channel_metadata={
                        "_truth_id": t.truth_id,
                        "_is_hoax": t.is_hoax,
                        "_mentioned_landmark": mentioned_landmark,
                        "language": lang,
                    },
                )
            )
            t.message_ids.append(mid)

    messages.sort(key=lambda m: m.received_at)
    return messages


def _report_count(ms, t: TruthDemand, rng: random.Random) -> int:
    """How many messages report this one event."""
    n = 1
    # Base duplicate rate: the Kerala form-resubmission effect.
    while rng.random() < ms.duplicate_rate:
        n += 1
        if n >= 6:
            break
    # Social amplification on top. Hoaxes amplify harder - that is what a
    # coordinated push looks like from the outside.
    if ms.amplification.enabled and rng.random() < ms.amplification.share_fraction:
        mean = ms.amplification.mean_extra * (2.2 if t.is_hoax else 1.0)
        n += max(0, int(rng.expovariate(1.0 / max(0.5, mean))))
    return min(n, 40)


def _compose(spec, t: TruthDemand, lang: str, n: int, rng: random.Random):
    """Build the place phrase. Most reports name a landmark; some are vague."""
    ms = spec.messages
    mentioned = None
    if t.landmark and rng.random() < ms.landmark_mention_rate:
        if rng.random() < 0.45 and t.landmark.aliases:
            label = rng.choice(t.landmark.aliases)
        else:
            label = t.landmark.name
        mentioned = t.landmark.name
        place = corpus.place_phrase(t.landmark.name, lang, rng, use_alias=label)
    else:
        # A generic place-word. Tells us the neighbourhood, never the building,
        # and the geo cascade must not pretend otherwise.
        place = rng.choice(_GENERIC_PLACES[lang])
    return corpus.render(t.need, lang, n, place, t.vulnerability_flags, rng), mentioned


def _hash(s: str) -> str:
    """Salted sender hash. Raw identifiers never leave intake."""
    return hashlib.sha256(f"pharos-demo-salt::{s}".encode()).hexdigest()[:24]
