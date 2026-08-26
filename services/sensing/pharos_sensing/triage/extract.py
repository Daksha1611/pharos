"""Triage extraction - not classification.

The difference matters. A model that says "evacuation, 7 people, confidence
0.62 on the headcount" is useful downstream; one that says "high priority" is
not, because priority is not a property of a message (it depends on what
assets are free to serve it).

Four heads, each emitting its own confidence:
    need type          which resource is required
    headcount          how many people
    vulnerability      infant, elderly, pregnant, disabled, injured
    medical urgency    none / mild / moderate / critical

The scores this module produces are RAW. They are systematically
overconfident, the way raw softmax is - which is the point. Calibration
(`triage.calibration`) is what turns them into numbers the solver can act on.
Nothing downstream should read a raw score.
"""

from __future__ import annotations

import re as _re
from dataclasses import dataclass, field

from pharos_core import MedicalUrgency, NeedType

# --------------------------------------------------------------------------
# need type
# --------------------------------------------------------------------------

# (pattern, weight). Weights reflect how diagnostic a cue is: "boat" almost
# always means evacuation; "water" alone is ambiguous between drinking water
# and flooding, so it is weak on its own and strong in combination.
NEED_CUES: dict[NeedType, list[tuple[str, float]]] = {
    NeedType.EVACUATION: [
        (r"\bboat\b|\bnaav\b|\bnav\b", 3.0),
        (r"\brescue\b|\bevacuat", 3.0),
        (r"\btrapped\b|\bstranded\b|\bstuck\b|\bfase\b|\bfasa\b|\bphase\b", 2.5),
        (r"\bsubmerged\b|\bchest deep\b|\bgale tak\b|\broof\b|\bchhat\b", 2.0),
        (r"\bwater (is )?rising\b|\bpani.{0,12}badh\b", 2.0),
        (r"\bcannot get out\b|\bnikal nahi\b|\bcut off\b|\bkat gay", 1.8),
        (r"\bsos\b", 1.2),
    ],
    NeedType.MEDICAL: [
        (r"\bambulance\b|\bamb\b", 3.2),
        (r"\bdoctor\b|\bnurse\b|\bhospital\b|\bhosp\b", 2.8),
        (r"\bmedicine\b|\bmedical\b|\bdawai\b|\binsulin\b|\bdialysis\b|\boxygen\b", 3.0),
        (r"\binjured\b|\bghayal\b|\bbleeding\b|\bunconscious\b|\bbehosh\b", 2.6),
        (r"\bpatient\b|\bsick\b|\bbimar\b|\bfever\b|\bcritical\b", 2.0),
    ],
    NeedType.WATER: [
        (r"\bdrinking water\b|\bpeene ka pani\b|\bsaaf pani\b|\bclean water\b", 3.4),
        (r"\bwater tanker\b|\bpani ka tanker\b|\btanker\b", 3.0),
        (r"\bcontaminated\b|\bwell is\b|\bkuan\b|\bwater tank\b", 1.6),
        (r"\bnothing to drink\b|\bbina pani\b|\bwithout water\b", 2.4),
    ],
    NeedType.FOOD: [
        (r"\bfood\b|\bkhana\b|\bration\b|\brashan\b", 3.2),
        (r"\bfood packet\b|\bdry ration\b|\bfood suppl", 3.0),
        (r"\bhungry\b|\bbhookh|\bstarv", 2.4),
        (r"\bshops (all )?closed\b|\bdukaan band\b", 1.4),
    ],
    NeedType.SHELTER: [
        (r"\bshelter\b|\bcamp\b", 2.8),
        (r"\bhouse collapsed\b|\bghar gir\b|\bcollapse\b|\broof gone\b", 3.0),
        (r"\bnowhere to stay\b|\brehne ki jagah\b|\bout in the rain\b", 2.6),
    ],
    NeedType.SANITATION: [
        (r"\btoilet|\bshauchalay\b|\blatrine\b", 3.2),
        (r"\bsewage\b|\bsanitation\b|\bsafai\b", 3.0),
        (r"\bdisease risk\b|\bbimari ka khatra\b", 1.8),
    ],
    NeedType.MISSING_PERSON: [
        (r"\bmissing\b|\blapata\b|\bnot reachable\b|\bunreachable\b", 3.2),
        (r"\bcannot contact\b|\bsampark nahi\b|\bphone.{0,12}(band|nahi)\b", 2.8),
        (r"\bsearch\b|\bkhoj\b", 1.6),
    ],
    NeedType.INFRASTRUCTURE: [
        (r"\bbridge\b|\bpul\b|\bpalam\b", 2.6),
        (r"\bpower line\b|\belectricity\b|\bbijli\b|\blive wire\b|\bcurrent\b", 3.0),
        (r"\bdamaged\b|\btut gaya\b|\bno vehicle can cross\b", 1.8),
    ],
}

# Pre-compiled at import time so the hot path (one call per message) never
# pays the compile cost. Python's regex cache caps at 512 entries; explicit
# compilation is the only guarantee against silent evictions.
_COMPILED_NEED_CUES: dict = {
    nt: [(_re.compile(pat), w) for pat, w in cues]
    for nt, cues in NEED_CUES.items()
}

# --------------------------------------------------------------------------
# headcount
# --------------------------------------------------------------------------

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
    "ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5, "panch": 5,
    "chhe": 6, "che": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10, "bees": 20,
}

# Words that mark the preceding or following number as a count of PEOPLE.
PERSON_UNITS = r"(?:people|persons?|ppl|of us|members?|log|logo|vyakti|adults?|children|kids?|patients?|injured|sick|stranded|stuck|trapped)"
# Words that mark it as a count of HOUSEHOLDS, which needs a multiplier.
HOUSEHOLD_UNITS = r"(?:famil(?:y|ies)|households?|houses?|homes?|parivar|ghar)"

MEAN_HOUSEHOLD_SIZE = 4.6  # Kerala census average, rounded

_NUM = r"(\d{1,4})"
_PAT_PEOPLE_AFTER = _re.compile(rf"{_NUM}\s+(?:\w+\s+){{0,2}}?{PERSON_UNITS}\b")
_PAT_PEOPLE_BEFORE = _re.compile(rf"\b{PERSON_UNITS}\W{{0,4}}{_NUM}\b")
_PAT_HOUSEHOLD = _re.compile(rf"{_NUM}\s+(?:\w+\s+){{0,2}}?{HOUSEHOLD_UNITS}\b")
_PAT_WE_ARE = _re.compile(rf"\b(?:we are|hum|ham)\s+{_NUM}\b")
_PAT_BARE = _re.compile(rf"\b{_NUM}\b")

# --------------------------------------------------------------------------
# vulnerability and urgency
# --------------------------------------------------------------------------

VULN_CUES = {
    "infant": r"\b(baby|infant|newborn|bacha|bache|toddler)\b",
    "elderly": r"\b(elderly|old (man|woman|people|person)|budhe|budha|senior citizen)\b",
    "pregnant": r"\b(pregnant|garbhvati|expecting mother)\b",
    "disabled": r"\b(disabled|cannot walk|chal nahi sakta|wheelchair|handicapped)\b",
    "injured": r"\b(injured|ghayal|wounded|bleeding|fracture|broken (leg|arm|bone))\b",
}
_COMPILED_VULN_CUES: dict = {flag: _re.compile(pat) for flag, pat in VULN_CUES.items()}

URGENCY_CUES = [
    (MedicalUrgency.CRITICAL, r"\b(unconscious|behosh|bleeding heavily|critical|cardiac|not breathing|dialysis|oxygen)\b", 3.0),
    (MedicalUrgency.MODERATE, r"\b(injured|ghayal|fracture|insulin|missed two sessions|high fever|severe)\b", 2.0),
    (MedicalUrgency.MILD, r"\b(sick|bimar|fever|unwell|weak|medicine|dawai)\b", 1.0),
]
_COMPILED_URGENCY_CUES = [
    (level, _re.compile(pat), w) for level, pat, w in URGENCY_CUES
]


@dataclass
class Extraction:
    """Per-field output with per-field RAW confidence."""

    need_type: NeedType
    need_type_raw: float

    people: int
    people_raw: float
    people_method: str

    vulnerability_flags: list[str] = field(default_factory=list)
    vulnerability_raw: float = 0.5

    medical_urgency: MedicalUrgency = MedicalUrgency.NONE
    medical_urgency_raw: float = 0.5

    need_type_scores: dict = field(default_factory=dict)


def extract(text: str) -> Extraction:
    t = text.lower()
    need, need_raw, scores = _need_type(t)
    people, people_raw, method = _headcount(t)
    vulns, vuln_raw = _vulnerabilities(t)
    urgency, urg_raw = _urgency(t, need)

    return Extraction(
        need_type=need,
        need_type_raw=need_raw,
        people=people,
        people_raw=people_raw,
        people_method=method,
        vulnerability_flags=vulns,
        vulnerability_raw=vuln_raw,
        medical_urgency=urgency,
        medical_urgency_raw=urg_raw,
        need_type_scores=scores,
    )


def _need_type(t: str) -> tuple[NeedType, float, dict]:
    scores: dict[NeedType, float] = {}
    for nt, cues in _COMPILED_NEED_CUES.items():
        s = sum(w for pat, w in cues if pat.search(t))
        if s:
            scores[nt] = s

    if not scores:
        # Nothing matched. Evacuation is the base rate in a flood, but say so
        # with a low score rather than pretending to have decided.
        return NeedType.EVACUATION, 0.18, {}

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    top, top_s = ranked[0]
    runner_s = ranked[1][1] if len(ranked) > 1 else 0.0
    total = sum(scores.values())

    # Margin over the runner-up carries more information than the raw share.
    share = top_s / total
    margin = (top_s - runner_s) / top_s
    raw = 0.55 * share + 0.45 * margin
    # Strong absolute evidence should also count - two 3.0-weight cues is a
    # different situation from one 1.2-weight cue, even at the same share.
    raw = min(0.995, raw * (0.72 + 0.28 * min(1.0, top_s / 5.0)) + 0.12 * min(1.0, top_s / 6.0))
    return top, round(raw, 4), {k.value: round(v, 2) for k, v in scores.items()}


def _headcount(t: str) -> tuple[int, float, str]:
    t = _spell_numbers(t)

    m = _PAT_WE_ARE.search(t)
    if m:
        return _clamp(int(m.group(1))), 0.93, "first_person_count"

    m = _PAT_PEOPLE_AFTER.search(t) or _PAT_PEOPLE_BEFORE.search(t)
    if m:
        return _clamp(int(m.group(1))), 0.90, "number_with_person_unit"

    m = _PAT_HOUSEHOLD.search(t)
    if m:
        # Households, not people. The multiplier is a population statistic, so
        # the number is real but the uncertainty is genuinely wider.
        n = int(m.group(1))
        return _clamp(int(round(n * MEAN_HOUSEHOLD_SIZE))), 0.58, "households_x_mean_size"

    nums = [int(x) for x in _PAT_BARE.findall(t) if 0 < int(x) <= 400]
    if nums:
        # A bare number with no unit. Could be a headcount, could be a house
        # number or a time. Plausible, not confident.
        return _clamp(max(nums)), 0.44, "bare_number"

    # Nothing at all. Fall back to the population prior and be honest about it.
    return 5, 0.15, "household_prior"


def _spell_numbers(t: str) -> str:
    def sub(m):
        return str(NUMBER_WORDS[m.group(0)])

    return _re.sub(rf"\b({'|'.join(NUMBER_WORDS)})\b", sub, t)


def _clamp(n: int) -> int:
    return max(1, min(n, 500))


def _vulnerabilities(t: str) -> tuple[list[str], float]:
    hits = [flag for flag, pat in _COMPILED_VULN_CUES.items() if pat.search(t)]
    if not hits:
        # Absence of evidence. Most messages simply do not mention it, so a
        # negative here is weak, and the confidence says so.
        return [], 0.55
    return sorted(hits), min(0.95, 0.68 + 0.10 * len(hits))


def _urgency(t: str, need: NeedType) -> tuple[MedicalUrgency, float]:
    for level, pat, weight in _COMPILED_URGENCY_CUES:
        if pat.search(t):
            return level, min(0.95, 0.52 + 0.13 * weight)
    if need is NeedType.MEDICAL:
        return MedicalUrgency.MILD, 0.42
    if need is NeedType.EVACUATION:
        return MedicalUrgency.NONE, 0.62
    return MedicalUrgency.NONE, 0.70
