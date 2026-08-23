"""Local landmark gazetteer.

"Near the old mill", "behind the panchayat office" - the names people actually
use, which no commercial geocoder knows. Two hundred entries for one district
is plenty, and it catches exactly what Nominatim misses.

For the demo the entries are generated deterministically over the region so the
whole pipeline runs offline. Swapping in a real district gazetteer is a matter
of replacing `build()` with a CSV load; nothing downstream changes.
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field

EARTH_RADIUS_M = 6_371_000.0

# Place-name components a Kerala district would plausibly carry. Combined into
# names that read naturally in English, Roman-script Malayalam and Hindi.
_PREFIX = [
    "Vaikom", "Aluva", "Cheranallur", "Kadamakkudy", "Paravur", "Chellanam",
    "Kumbalangi", "Mulavukad", "Varapuzha", "Nedumbassery", "Thrikkakara",
    "Elamkulam", "Kalamassery", "Perumbavoor", "Kothamangalam", "Piravom",
    "Maradu", "Panangad", "Edappally", "Palluruthy", "Njarakkal", "Vypin",
    "Cherai", "Munambam", "Pallippuram", "Kuzhuppilly", "Ezhikkara",
    "Chittattukara", "Karumalloor", "Alangad", "Kunnukara", "Kanjoor",
    "Manjapra", "Sreemoolanagaram", "Choornikkara", "Vazhakkulam",
    "Rayamangalam", "Keezhmad", "Puthenvelikkara", "Chendamangalam",
]
_SUFFIX = [
    ("Panchayat Office", ["panchayat", "panchayath office", "panchayat ofc"]),
    ("Government LP School", ["govt school", "lp school", "sarkari school"]),
    ("Community Health Centre", ["chc", "health centre", "phc"]),
    ("Milk Society", ["milk society", "dairy", "milma"]),
    ("Old Mill", ["old mill", "purana mill", "mill compound"]),
    ("Church", ["church", "palli"]),
    ("Temple", ["temple", "kshetram", "mandir"]),
    ("Mosque", ["mosque", "juma masjid", "masjid"]),
    ("Ferry Jetty", ["jetty", "kadavu", "boat jetty"]),
    ("Market", ["market", "chanta", "bazaar"]),
    ("Bus Stand", ["bus stand", "bus stop", "stand"]),
    ("Bridge", ["bridge", "palam", "pul"]),
    ("Water Tank", ["water tank", "tank", "overhead tank"]),
    ("Colony", ["colony", "housing colony"]),
    ("Padashekharam", ["padam", "paddy field", "field"]),
    ("Anganwadi", ["anganwadi", "balwadi"]),
    ("Ration Shop", ["ration shop", "maveli store", "supply co"]),
    ("Post Office", ["post office", "postal"]),
    ("Village Office", ["village office", "village ofc"]),
    ("Krishi Bhavan", ["krishi bhavan", "agri office"]),
    ("Youth Club", ["youth club", "arts club", "reading room"]),
    ("Petrol Pump", ["petrol pump", "fuel station", "bunk"]),
    ("Pumping Station", ["pumping station", "pump house"]),
    ("Sub Station", ["sub station", "kseb substation", "kseb"]),
    ("Boat Club", ["boat club", "canoe club"]),
    ("Rice Mill", ["rice mill", "arimill"]),
]

# Districts really do carry qualified variants of the same base name. These
# extend the name space so a dense gazetteer stays generatable without
# repeating itself.
_QUALIFIER = ["", "", "", "North", "South", "East", "West", "Old", "New",
              "Ward 3", "Ward 7", "Ward 11", "Upper", "Lower"]


# Bare place-words that name many locations in one district. Seeing one of
# these without a prefix tells us the neighbourhood, never the building.
GENERIC_TERMS = frozenset(
    {
        "panchayat", "panchayath", "panchayat office", "school", "lp school",
        "govt school", "chc", "phc", "health centre", "church", "palli",
        "temple", "kshetram", "mandir", "mosque", "masjid", "juma masjid",
        "jetty", "kadavu", "market", "chanta", "bazaar", "bus stand",
        "bus stop", "bridge", "palam", "pul", "water tank", "colony",
        "anganwadi", "balwadi", "old mill", "mill compound", "dairy", "milma",
    }
)


_GENERIC_BY_LENGTH = sorted(GENERIC_TERMS, key=len, reverse=True)


@dataclass
class GazetteerEntry:
    name: str
    aliases: list[str]
    lat: float
    lon: float
    radius_m: float = 250.0

    def all_names(self) -> list[str]:
        return [self.name, *self.aliases]


@dataclass
class Gazetteer:
    entries: list[GazetteerEntry] = field(default_factory=list)
    _lookup: dict[str, GazetteerEntry] = field(default_factory=dict, repr=False)
    _by_token: dict[str, list[str]] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        self.reindex()

    def reindex(self) -> None:
        """Build a token-inverted index over place names.

        Scanning every name against every message is 600 regex searches per
        message, which at 40,000 messages is the difference between the intake
        keeping up and falling behind. Instead, index each name by its rarest
        token: a message only tests the handful of names that share a word
        with it.
        """
        self._lookup = {}
        for e in self.entries:
            for n in e.all_names():
                self._lookup.setdefault(_norm(n), e)
        # Longest names first so "vaikom old mill" beats "old mill".
        self._sorted_keys = sorted(self._lookup, key=len, reverse=True)

        counts: dict[str, int] = {}
        for key in self._lookup:
            for tok in key.split():
                counts[tok] = counts.get(tok, 0) + 1

        self._by_token: dict[str, list[str]] = {}
        for key in self._sorted_keys:
            toks = [t for t in key.split() if len(t) >= 4]
            if not toks:
                continue
            rarest = min(toks, key=lambda t: (counts[t], -len(t)))
            self._by_token.setdefault(rarest, []).append(key)

    def match(self, text: str) -> GazetteerEntry | None:
        """Most specific landmark named in the text, or None.

        Longest candidate first, so "Vaikom Old Mill" beats a shorter alias
        that happens to be a substring of it.
        """
        t = _norm(text)
        tokens = set(t.split())

        candidates: set[str] = set()
        for tok in tokens:
            candidates.update(self._by_token.get(tok, ()))
        if not candidates:
            return None

        for key in sorted(candidates, key=len, reverse=True):
            if len(key) < 6:
                continue
            # Every token of the name must be present before the substring
            # check runs - a cheap filter that removes almost all the work.
            if not set(key.split()) <= tokens:
                continue
            if f" {key} " in f" {t} ":
                return self._lookup[key]
        return None

    def mentions_generic_place(self, text: str) -> str | None:
        """A place-word with no prefix. Good enough for a ward, not a pin."""
        t = f" {_norm(text)} "
        for term in _GENERIC_BY_LENGTH:
            if f" {term} " in t:
                return term
        return None

    def __len__(self) -> int:
        return len(self.entries)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


def _offset(lat: float, lon: float, dx_m: float, dy_m: float) -> tuple[float, float]:
    dlat = (dy_m / EARTH_RADIUS_M) * (180.0 / math.pi)
    dlon = (dx_m / (EARTH_RADIUS_M * math.cos(math.radians(lat)))) * (180.0 / math.pi)
    return lat + dlat, lon + dlon


def build(centre: tuple[float, float], radius_km: float, count: int = 200, seed: int = 42) -> Gazetteer:
    """Deterministic gazetteer over the region. Same seed, same places."""
    rng = random.Random(seed)
    clat, clon = centre
    radius_m = radius_km * 1000.0
    entries: list[GazetteerEntry] = []
    used: set[str] = set()

    capacity = len(_PREFIX) * len(_SUFFIX) * len(set(_QUALIFIER))
    if count > capacity:
        raise ValueError(
            f"gazetteer of {count} entries exceeds the {capacity} distinct names this "
            f"generator can produce; widen _PREFIX, _SUFFIX or _QUALIFIER"
        )

    attempts = 0
    while len(entries) < count:
        attempts += 1
        prefix = rng.choice(_PREFIX)
        suffix, alias_stems = rng.choice(_SUFFIX)
        qual = rng.choice(_QUALIFIER)
        name = f"{prefix} {qual} {suffix}".replace("  ", " ").strip()
        if name in used:
            # Rejection sampling gets slow as the space fills. Past a sensible
            # bound, walk the space deterministically instead of retrying.
            if attempts > count * 12:
                name = f"{prefix} {suffix} {len(entries) + 1}"
                if name in used:
                    continue
            else:
                continue
        used.add(name)

        # Uniform over the disc, not over (r, theta) - otherwise everything
        # bunches at the centre.
        r = radius_m * math.sqrt(rng.random())
        th = rng.uniform(0, 2 * math.pi)
        lat, lon = _offset(clat, clon, r * math.cos(th), r * math.sin(th))

        # Prefixed aliases only. A bare "panchayat office" names a dozen
        # places in one district; resolving it to a point would be inventing
        # precision, so it goes to GENERIC_TERMS and falls back to ward level.
        stem = f"{prefix} {qual}".strip().lower()
        aliases = [f"{stem} {a}" for a in alias_stems]
        if qual:
            # People drop the qualifier as often as they use it.
            aliases += [f"{prefix.lower()} {a}" for a in alias_stems[:1]]
        entries.append(
            GazetteerEntry(
                name=name,
                aliases=aliases,
                lat=round(lat, 6),
                lon=round(lon, 6),
                radius_m=rng.choice([150.0, 250.0, 400.0]),
            )
        )
    return Gazetteer(entries=entries)
