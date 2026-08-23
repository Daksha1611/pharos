"""Message text generation.

A template grammar per need type per language, with typo and shorthand
corruption applied afterwards. Committed and versioned, never generated at
demo time - a demo that needs a model to produce its own input has one more
way to fail on stage.

Three registers, matching the documented mix in Indian crisis traffic:
  en      English, the register most volunteer channels default to
  hi      Hindi written in Roman script, which is how people actually type it
  mixed   Hindi-English code-mixed within one sentence

Slots: {n} headcount, {place} landmark phrase, {vuln} vulnerability clause.
"""

from __future__ import annotations

import random

from pharos_core import NeedType

# --------------------------------------------------------------------------
# templates
# --------------------------------------------------------------------------

TEMPLATES: dict[NeedType, dict[str, list[str]]] = {
    NeedType.EVACUATION: {
        "en": [
            "water rising fast {place}, {n} people trapped on the roof{vuln}, need a boat urgently",
            "we are {n} stuck {place}, ground floor fully submerged{vuln}, please send rescue",
            "SOS {place} - {n} of us cannot get out, water is chest deep{vuln}",
            "please help, {n} people {place} waiting since morning for evacuation{vuln}",
            "boat needed {place}. {n} persons including{vuln} still inside the house",
            "urgent evacuation required {place}, {n} stranded, road completely cut off",
        ],
        "hi": [
            "pani tezi se badh raha hai {place}, {n} log chhat par fase hue hain{vuln}, boat bhejiye",
            "hum {n} log {place} fase hain, ghar me pani bhar gaya{vuln}, madad kijiye",
            "SOS {place} - {n} log nikal nahi pa rahe, pani gale tak aa gaya{vuln}",
            "kripya madad kare, {place} par {n} log subah se rescue ka intezar kar rahe hain{vuln}",
            "boat chahiye {place}. {n} log{vuln} abhi bhi ghar ke andar hain",
        ],
        "mixed": [
            "urgent help {place} - {n} log trapped hain roof pe{vuln}, boat bhejo please",
            "pani bahut badh gaya {place}, {n} people stuck{vuln}, rescue team needed asap",
            "{place} me {n} log fase hue hain{vuln}, ground floor puri tarah submerged, need boat",
            "SOS - {n} members{vuln} stranded {place}, koi boat nahi aayi abhi tak",
        ],
    },
    NeedType.MEDICAL: {
        "en": [
            "medical emergency {place}, {n} injured{vuln}, need ambulance immediately",
            "{place} - patient{vuln} needs dialysis, missed two sessions, {n} affected",
            "urgent: {n} people {place} with{vuln}, one is unconscious, send medical help",
            "we need a doctor {place}, {n} sick{vuln}, high fever since two days",
            "critical case {place}, {n} person{vuln} bleeding heavily, ambulance please",
        ],
        "hi": [
            "medical emergency {place}, {n} log ghayal hain{vuln}, ambulance bhejiye turant",
            "{place} par {n} log bimar hain{vuln}, doctor ki zarurat hai",
            "urgent - {n} vyakti{vuln} behosh ho gaya {place}, madad chahiye",
            "{place} me dawai khatam ho gayi, {n} patients{vuln} ko turant chahiye",
        ],
        "mixed": [
            "medical help chahiye {place}, {n} injured{vuln}, ambulance kab aayegi",
            "{place} par ek patient{vuln} critical hai, {n} affected, doctor bhejo urgently",
            "urgent medicine needed {place} - {n} log{vuln}, insulin khatam ho gaya hai",
        ],
    },
    NeedType.WATER: {
        "en": [
            "no drinking water {place} for two days, {n} people{vuln} affected",
            "{place} - {n} families need clean water, well is contaminated{vuln}",
            "water tanker required {place}, around {n} people{vuln} with nothing to drink",
            "please send drinking water {place}, {n} of us{vuln} have been without since yesterday",
        ],
        "hi": [
            "peene ka pani nahi hai {place}, {n} log{vuln} pareshan hain",
            "{place} me {n} parivar ko saaf pani chahiye, kuan kharab ho gaya{vuln}",
            "pani ka tanker bhejiye {place}, karib {n} log{vuln} bina pani ke hain",
        ],
        "mixed": [
            "drinking water nahi hai {place} se do din, {n} people{vuln} affected",
            "{place} par water tanker chahiye urgently, {n} log{vuln} without water",
        ],
    },
    NeedType.FOOD: {
        "en": [
            "no food {place} since yesterday, {n} people{vuln} in the shelter",
            "{place} - {n} families need dry rations{vuln}, shops all closed",
            "food supplies exhausted {place}, roughly {n} people{vuln} waiting",
            "need food packets {place}, {n} of us{vuln} including children",
        ],
        "hi": [
            "khana nahi hai {place} kal se, {n} log{vuln} bhookhe hain",
            "{place} me {n} parivar ko rashan chahiye{vuln}, sabhi dukaan band hain",
            "food packet bhejiye {place}, karib {n} log{vuln} intezar me hain",
        ],
        "mixed": [
            "food packets chahiye {place}, {n} log{vuln} kal se bhookhe hain",
            "{place} par ration khatam, {n} families{vuln} need dry food urgently",
        ],
    },
    NeedType.SHELTER: {
        "en": [
            "house collapsed {place}, {n} people{vuln} have nowhere to stay tonight",
            "{place} - {n} of us{vuln} need shelter, camp is already full",
            "roof gone {place}, {n} people{vuln} out in the rain since evening",
        ],
        "hi": [
            "ghar gir gaya {place}, {n} log{vuln} ke paas rehne ki jagah nahi hai",
            "{place} par {n} log{vuln} ko shelter chahiye, camp bhar gaya hai",
        ],
        "mixed": [
            "ghar collapse ho gaya {place}, {n} people{vuln} need shelter tonight",
            "{place} me shelter chahiye {n} logo ko{vuln}, camp already full hai",
        ],
    },
    NeedType.SANITATION: {
        "en": [
            "toilets flooded {place}, {n} people{vuln} in the camp, disease risk rising",
            "{place} - sewage backing up, {n} affected{vuln}, need sanitation team",
        ],
        "hi": [
            "shauchalay bhar gaya {place}, {n} log{vuln} camp me hain, bimari ka khatra",
            "{place} me safai ki zarurat hai, {n} log{vuln} pareshan",
        ],
        "mixed": [
            "toilets flooded {place}, {n} log{vuln} camp me, sanitation team bhejo",
        ],
    },
    NeedType.MISSING_PERSON: {
        "en": [
            "{n} family members missing {place} since the water came{vuln}, please search",
            "cannot contact {n} relatives {place}{vuln}, phones not reachable since morning",
        ],
        "hi": [
            "{n} log lapata hain {place} se{vuln}, kripya khoj kijiye",
            "{place} me {n} rishtedaron se sampark nahi ho raha{vuln}, phone band hai",
        ],
        "mixed": [
            "{n} family members missing {place} se{vuln}, phone bhi nahi lag raha, please search",
        ],
    },
    NeedType.INFRASTRUCTURE: {
        "en": [
            "bridge {place} looks damaged, no vehicle can cross, {n} households cut off",
            "power line down {place}, {n} houses without electricity{vuln}, live wire in water",
        ],
        "hi": [
            "pul {place} tut gaya hai, koi gaadi nahi ja sakti, {n} ghar kat gaye",
            "bijli ka taar gira hai {place}, {n} ghar bina bijli{vuln}, pani me current hai",
        ],
        "mixed": [
            "bridge {place} damaged lag raha hai, {n} households completely cut off",
        ],
    },
}

# --------------------------------------------------------------------------
# slot fillers
# --------------------------------------------------------------------------

PLACE_PATTERNS = {
    "en": ["at {L}", "near {L}", "behind {L}", "opposite {L}", "just past {L}", "close to {L}"],
    "hi": ["{L} ke paas", "{L} ke peeche", "{L} par", "{L} ke saamne", "{L} ke nazdeek"],
    "mixed": ["{L} ke paas", "near {L}", "{L} ke behind", "{L} par"],
}

VULN_PHRASES = {
    "infant": {"en": " including a small baby", "hi": " ek chhota bacha bhi hai", "mixed": " ek baby bhi hai"},
    "elderly": {"en": " including two elderly people", "hi": " do budhe log bhi hain", "mixed": " elderly log bhi hain"},
    "pregnant": {"en": " one is pregnant", "hi": " ek garbhvati mahila hai", "mixed": " ek pregnant lady hai"},
    "disabled": {"en": " one cannot walk", "hi": " ek chal nahi sakta", "mixed": " ek disabled person hai"},
    "injured": {"en": " two are injured", "hi": " do log ghayal hain", "mixed": " do log injured hain"},
}

# SMS shorthand people actually type under stress.
SHORTHAND = {
    "please": "pls", "urgent": "urgnt", "people": "ppl", "immediately": "immdtly",
    "water": "watr", "need": "nd", "and": "n", "you": "u", "are": "r",
    "help": "hlp", "before": "b4", "message": "msg", "number": "no",
    "hospital": "hosp", "medicine": "med", "children": "kids", "tomorrow": "tmrw",
}

_KEY_NEIGHBOURS = {
    "a": "qsz", "b": "vgn", "c": "xvd", "d": "sfe", "e": "wrd", "f": "dgr",
    "g": "fhv", "h": "gjb", "i": "uok", "j": "hkn", "k": "jlm", "l": "kop",
    "m": "nkj", "n": "bmh", "o": "ipl", "p": "ol", "q": "wa", "r": "etf",
    "s": "adw", "t": "ryg", "u": "yij", "v": "cbg", "w": "qes", "x": "zcs",
    "y": "tuh", "z": "asx",
}


def render(
    need: NeedType,
    lang: str,
    n: int,
    landmark_phrase: str,
    vulnerabilities: list[str],
    rng: random.Random,
) -> str:
    bank = TEMPLATES.get(need, {}).get(lang) or TEMPLATES[NeedType.EVACUATION]["en"]
    tpl = rng.choice(bank)

    vuln = ""
    if vulnerabilities and "{vuln}" in tpl:
        flag = rng.choice(vulnerabilities)
        phrase = VULN_PHRASES.get(flag, {}).get(lang, "")
        if phrase:
            vuln = "," + phrase if rng.random() < 0.6 else phrase

    return tpl.format(n=n, place=landmark_phrase, vuln=vuln).strip()


def place_phrase(landmark_name: str, lang: str, rng: random.Random, use_alias: str | None = None) -> str:
    label = use_alias or landmark_name
    return rng.choice(PLACE_PATTERNS.get(lang, PLACE_PATTERNS["en"])).format(L=label)


def corrupt(text: str, typo_rate: float, shorthand_rate: float, rng: random.Random) -> str:
    """Apply the noise real messages carry.

    Crisis-text models are documented as brittle against exactly this, which is
    why the noise dials are ablation axes rather than decoration.
    """
    words = text.split()
    out = []
    for w in words:
        low = w.lower().strip(",.!?")
        if low in SHORTHAND and rng.random() < shorthand_rate:
            out.append(SHORTHAND[low])
            continue
        if len(w) > 3 and rng.random() < typo_rate:
            out.append(_typo(w, rng))
            continue
        out.append(w)
    s = " ".join(out)
    if rng.random() < 0.30:
        s = s.lower()
    if rng.random() < 0.12:
        s = s.upper()
    if rng.random() < 0.18:
        s = s.replace(" ", "  ", 1)
    return s


def _typo(w: str, rng: random.Random) -> str:
    kind = rng.random()
    i = rng.randrange(1, len(w) - 1)
    if kind < 0.35:  # neighbouring-key substitution
        c = w[i].lower()
        if c in _KEY_NEIGHBOURS:
            return w[:i] + rng.choice(_KEY_NEIGHBOURS[c]) + w[i + 1 :]
        return w
    if kind < 0.60:  # transposition
        return w[:i] + w[i + 1] + w[i] + w[i + 2 :]
    if kind < 0.85:  # dropped character
        return w[:i] + w[i + 1 :]
    return w[:i] + w[i] + w[i:]  # doubled character
