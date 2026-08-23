"""Text normalization: shorthand expansion and typo repair.

Crisis-text models are documented as brittle against typos and SMS shorthand,
so this stage is measured rather than assumed - the scenario's `typo_rate` and
`shorthand_rate` dials exist precisely to test it.

Typo repair is a SymSpell-style delete index: for a domain vocabulary of a few
thousand words, precomputing every single-character deletion makes lookup a
dict hit instead of an edit-distance scan over the vocabulary. That is the
difference between real-time and not, at 40,000 messages.
"""

from __future__ import annotations

import re
from collections import defaultdict

# The reverse of the generator's corruption table, plus shorthand the
# generator does not produce but real traffic does.
EXPANSIONS = {
    "pls": "please", "plz": "please", "plss": "please",
    "urgnt": "urgent", "urgent!": "urgent",
    "ppl": "people", "peeps": "people",
    "immdtly": "immediately", "immdt": "immediate",
    "watr": "water", "wtr": "water",
    "nd": "need", "hlp": "help",
    "b4": "before", "msg": "message", "no.": "number",
    "hosp": "hospital", "med": "medicine", "meds": "medicine",
    "kids": "children", "tmrw": "tomorrow",
    "u": "you", "r": "are", "n": "and", "ur": "your",
    "asap": "urgently", "sos": "sos",
    "govt": "government", "amb": "ambulance",
    "kms": "kilometres", "hrs": "hours", "mins": "minutes",
    "info": "information", "loc": "location", "lat": "latitude",
}

_TOKEN = re.compile(r"[a-z0-9]+|[^\sa-z0-9]")
_WS = re.compile(r"\s+")


class Normalizer:
    """Holds the domain vocabulary and its delete index."""

    def __init__(self, vocabulary: set[str] | None = None, max_edit: int = 1):
        self.max_edit = max_edit
        self.vocab: set[str] = set(vocabulary or set()) | _BASE_VOCAB
        self._deletes: dict[str, list[str]] = defaultdict(list)
        # Per-instance memo. A module-level lru_cache would be shared across
        # normalizers with different vocabularies, and would pin `self`.
        self._memo: dict[str, str] = {}
        self._build_index()

    def add_vocabulary(self, words) -> None:
        new = {w.lower() for w in words if w}
        if new - self.vocab:
            self.vocab |= new
            self._build_index()

    def _build_index(self) -> None:
        self._deletes = defaultdict(list)
        for w in self.vocab:
            self._deletes[w].append(w)
            if len(w) > 3:
                for i in range(len(w)):
                    self._deletes[w[:i] + w[i + 1 :]].append(w)
        self._memo.clear()

    def correct(self, token: str) -> str:
        """Nearest vocabulary word within one edit, or the token unchanged."""
        if len(token) < 4 or token in self.vocab or token.isdigit():
            return token
        hit = self._memo.get(token)
        if hit is not None:
            return hit
        result = self._correct_uncached(token)
        self._memo[token] = result
        return result

    def _correct_uncached(self, token: str) -> str:
        cands = set(self._deletes.get(token, ()))
        for i in range(len(token)):
            cands.update(self._deletes.get(token[:i] + token[i + 1 :], ()))
        if not cands:
            return token
        # Rank by edit distance, then by how common the word is in this domain,
        # then by length. Without the frequency tie-break, "nera" corrects to
        # "mera" instead of "near" - both are one edit away, and alphabetical
        # order is not a reason to prefer one.
        return min(
            cands,
            key=lambda c: (_edit1_cost(token, c), _FREQ_RANK.get(c, 9_999), -len(c), c),
        )

    def normalize(self, text: str) -> str:
        low = _WS.sub(" ", text.strip().lower())
        out: list[str] = []
        for tok in _TOKEN.findall(low):
            if not tok.isalnum():
                out.append(tok)
                continue
            tok = EXPANSIONS.get(tok, tok)
            out.append(self.correct(tok))
        return _detokenize(out)


def _edit1_cost(a: str, b: str) -> int:
    """0 if identical, 1 if within one edit, 2 otherwise. Cheap and enough."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return 2
    if la == lb:
        diffs = sum(1 for x, y in zip(a, b, strict=True) if x != y)
        if diffs == 1:
            return 1
        # transposition
        if diffs == 2:
            i = next(i for i, (x, y) in enumerate(zip(a, b, strict=True)) if x != y)
            if a[i] == b[i + 1] and a[i + 1] == b[i]:
                return 1
        return 2
    long, short = (a, b) if la > lb else (b, a)
    for i in range(len(long)):
        if long[:i] + long[i + 1 :] == short:
            return 1
    return 2


def _detokenize(tokens: list[str]) -> str:
    out = ""
    for t in tokens:
        if not out:
            out = t
        elif t in ",.!?;:%)" or t == "'":
            out += t
        elif out.endswith("("):
            out += t
        else:
            out += " " + t
    return out


# Domain words the corrector must never "fix" away, plus the vocabulary the
# templates draw on. Extended at runtime with gazetteer names.
_BASE_VOCAB = set(
    """
    water food medical shelter sanitation evacuation missing infrastructure
    boat ambulance truck helicopter rescue relief camp shelter tanker packet
    people person persons family families household households children child
    baby infant elderly old pregnant disabled injured unconscious sick patient
    doctor nurse hospital clinic medicine dialysis insulin oxygen bleeding fever
    please help urgent urgently need needed needs required send bhejo bhejiye
    trapped stranded stuck submerged flooded rising drowning collapsed damaged
    roof floor ground house home building road street bridge jetty ferry
    panchayat office school church temple mosque masjid market bazaar colony
    anganwadi tank well pump station depot junction stand
    north south east west near behind opposite past close beside around
    about above below under across along through between beyond towards
    completely fully partly still already again more less most least
    another other some many few several all both each every any none
    since yesterday morning evening night today tomorrow hours minutes days
    contact phone number reachable unreachable
    pani paani khana rashan ghar madad chahiye zarurat
    """.split()
)

# Roman-script Hindi function words are vocabulary, not typos. Without this the
# corrector "fixes" paas to past and log to logs, which is worse than leaving
# the token alone.
from .language import HI_MARKERS  # noqa: E402

_BASE_VOCAB |= set(HI_MARKERS)
_BASE_VOCAB |= set(
    """
    fasa fase phase bhara bhar tuta tut kata kat gira gir khatam
    makan sadak rasta pul palam gaadi kadavu chanta mandir kshetram
    balwadi padam padashekharam milma
    ke ki ka ko se me mein par pe paas peeche saamne nazdeek
    """.split()
)


# Domain frequency order, most common first. Used only to break ties between
# corrections that are the same edit distance away.
_FREQUENT = """
    the a an is are was were be to of in on at for with from and or but not
    we us our you your they it he she people person help need needs needed
    please urgent urgently send required water food medical house home road
    near behind opposite around close family families children child baby
    stuck trapped stranded rising flooded submerged boat ambulance truck
    rescue relief camp shelter since yesterday morning evening night hours
    hai hain ke ki ka ko se me par paas peeche log hum madad chahiye pani
    nahi gaya gayi bhejo bhejiye turant jaldi bahut ghar khana
""".split()
_FREQ_RANK = {w: i for i, w in enumerate(_FREQUENT)}


_DEFAULT: Normalizer | None = None


def default() -> Normalizer:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Normalizer()
    return _DEFAULT
