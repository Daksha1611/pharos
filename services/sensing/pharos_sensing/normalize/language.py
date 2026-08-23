"""Language identification for short, noisy, code-mixed crisis text.

Generic language detectors fail badly here for two reasons: the messages are
ten words long, and Hindi is written in Roman script, which most detectors
label as English. A lexicon scorer over function words is both more accurate
on this input and fully deterministic, which matters for a reproducible demo.

Swapping in fasttext-langdetect or MuRIL's own tokenizer is a matter of
replacing `detect()`; the rest of the pipeline reads only its return value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Roman-script Hindi function words and high-frequency verbs. These are what
# actually separate the registers - content words are often English in both.
HI_MARKERS = frozenset(
    """
    hai hain ho gaya gayi gaye raha rahi rahe kar karo kare kijiye bhejiye bhejo
    ke ki ka ko se me mein par paas peeche saamne nazdeek aur nahi nahin
    log logo hum ham humein hamari hamare aap tum mera meri mere uska unka
    chahiye zarurat jarurat madad kripya please1 turant abhi jaldi bahut
    yaha wahan idhar udhar kal aaj subah shaam raat din
    pani paani khana rashan ghar makan gaadi sadak rasta pul palam
    fase fasa phase bhar bhara gir gira tut tuta kat kata khatam
    bimar ghayal behosh mar mara zinda bacha bache budhe
    ek do teen char paanch chhe saat aath nau das
    """.split()
)

# English function words that rarely appear in Roman-script Hindi.
EN_MARKERS = frozenset(
    """
    the a an is are was were be been being have has had do does did
    of to in on at for with from by about into over after
    we us our you your they them their he she it its
    and but or if because while when where which who what
    need needs needed please help urgent please send required
    people person family families house home road water food medical
    stuck trapped stranded rising submerged cannot cant
    """.split()
)

_WORD = re.compile(r"[a-z]+")


@dataclass
class LanguageResult:
    language: str  # "en" | "hi" | "mixed"
    confidence: float
    hi_hits: int
    en_hits: int


def detect(text: str) -> LanguageResult:
    words = _WORD.findall(text.lower())
    if not words:
        return LanguageResult("en", 0.20, 0, 0)

    hi = sum(1 for w in words if w in HI_MARKERS)
    en = sum(1 for w in words if w in EN_MARKERS)
    total = max(1, hi + en)

    if hi == 0 and en == 0:
        # No function words at all - a terse SMS. Unknowable, and saying so is
        # better than guessing.
        return LanguageResult("en", 0.25, 0, 0)

    hi_share = hi / total
    if hi_share >= 0.72:
        lang, conf = "hi", hi_share
    elif hi_share <= 0.18:
        lang, conf = "en", 1.0 - hi_share
    else:
        # Both registers present in one sentence. This is the majority case in
        # Indian crisis traffic and the one generic detectors get wrong.
        lang, conf = "mixed", 1.0 - abs(hi_share - 0.45) * 1.6

    # Short messages carry less evidence. Discount accordingly.
    evidence = min(1.0, (hi + en) / 5.0)
    return LanguageResult(lang, round(max(0.2, min(0.98, conf * (0.55 + 0.45 * evidence))), 3), hi, en)
