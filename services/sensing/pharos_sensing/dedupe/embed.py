"""Message embeddings for duplicate detection.

Two backends behind one interface:

  hashing   Default. Deterministic, zero download, runs offline. Concatenates
            hashed character n-grams with the *extracted semantic frame* -
            need type, headcount bucket, vulnerability, urgency. The semantic
            half is what makes it cross-lingual: a Hindi and an English report
            of the same event produce the same frame, because the extractor
            recognises cues in both registers. The lexical half separates two
            different events that happen to share a frame.

  labse     sentence-transformers/LaBSE. Genuinely cross-lingual in the
            embedding itself. ~1.8GB on first use, so it is opt-in via
            PHAROS_EMBEDDER=labse rather than the default.

Nothing downstream knows which backend produced the vectors.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from dataclasses import dataclass

import numpy as np
from pharos_core import MedicalUrgency, NeedType

LEXICAL_DIM = 256
_VULNS = ("infant", "elderly", "pregnant", "disabled", "injured")
_URGENCY = tuple(MedicalUrgency)
_NEEDS = tuple(NeedType)

SEMANTIC_DIM = len(_NEEDS) + len(_VULNS) + len(_URGENCY) + 4  # +4 headcount buckets

# How much of the vector is semantic frame versus surface wording.
#
# The frame is what survives translation: a Hindi and an English report of the
# same event produce the same need type, headcount and urgency, while their
# character n-grams share almost nothing. Weighted toward the frame for that
# reason.
#
# This does put a floor of roughly 0.65 on the cosine between any two messages
# with the same frame, so the similarity threshold must sit above that floor to
# mean anything. Separating two unrelated events that share a frame is the
# clusterer's job, not the embedder's - need type, headcount and distance are
# hard gates there.
LEXICAL_WEIGHT = 0.55
SEMANTIC_WEIGHT = 0.75

_NGRAM_RANGE = (3, 5)
_CLEAN = re.compile(r"[^a-z0-9 ]+")


class Embedder:
    """Interface. `encode` returns L2-normalized rows, so cosine is a dot."""

    dim: int

    def encode(self, items) -> np.ndarray:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass
class EmbedInput:
    """What the embedder sees: surface text plus the extracted frame."""

    text: str
    need_type: NeedType
    people: int
    vulnerability_flags: tuple[str, ...] = ()
    medical_urgency: MedicalUrgency = MedicalUrgency.NONE


class HashingEmbedder(Embedder):
    def __init__(self, lexical_dim: int = LEXICAL_DIM):
        self.lexical_dim = lexical_dim
        self.dim = lexical_dim + SEMANTIC_DIM

    def encode(self, items: list[EmbedInput]) -> np.ndarray:
        out = np.zeros((len(items), self.dim), dtype=np.float32)
        for i, it in enumerate(items):
            lex = self._lexical(it.text)
            sem = self._semantic(it)
            out[i, : self.lexical_dim] = lex * LEXICAL_WEIGHT
            out[i, self.lexical_dim :] = sem * SEMANTIC_WEIGHT
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        np.divide(out, np.maximum(norms, 1e-9), out=out)
        return out

    def _lexical(self, text: str) -> np.ndarray:
        v = np.zeros(self.lexical_dim, dtype=np.float32)
        s = _CLEAN.sub(" ", text.lower())
        s = f" {' '.join(s.split())} "
        lo, hi = _NGRAM_RANGE
        for n in range(lo, hi + 1):
            for j in range(len(s) - n + 1):
                g = s[j : j + n]
                h = int.from_bytes(hashlib.blake2b(g.encode(), digest_size=4).digest(), "big")
                # Signed hashing: halves the collision bias for free.
                v[h % self.lexical_dim] += 1.0 if (h >> 31) & 1 else -1.0
        norm = np.linalg.norm(v)
        return v / norm if norm > 0 else v

    def _semantic(self, it: EmbedInput) -> np.ndarray:
        v = np.zeros(SEMANTIC_DIM, dtype=np.float32)
        v[_NEEDS.index(it.need_type)] = 1.0
        off = len(_NEEDS)
        for f in it.vulnerability_flags:
            if f in _VULNS:
                v[off + _VULNS.index(f)] = 0.7
        off += len(_VULNS)
        v[off + _URGENCY.index(it.medical_urgency)] = 0.8
        off += len(_URGENCY)
        # Headcount as a soft log bucket: 7 and 8 people are the same event
        # reported twice; 7 and 70 are not.
        b = min(3.0, math.log1p(max(0, it.people)) / math.log(60.0) * 4.0)
        lo = int(b)
        frac = b - lo
        v[off + lo] += (1.0 - frac) * 0.9
        if lo + 1 < 4:
            v[off + lo + 1] += frac * 0.9
        norm = np.linalg.norm(v)
        return v / norm if norm > 0 else v


class LabseEmbedder(Embedder):
    """sentence-transformers/LaBSE. Opt-in; imported lazily."""

    def __init__(self, model_name: str = "sentence-transformers/LaBSE"):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)
        self.dim = int(self.model.get_sentence_embedding_dimension())

    def encode(self, items: list[EmbedInput]) -> np.ndarray:
        return self.model.encode(
            [it.text for it in items],
            normalize_embeddings=True,
            batch_size=128,
            show_progress_bar=False,
        ).astype(np.float32)


def get_embedder(name: str | None = None) -> Embedder:
    name = (name or os.getenv("PHAROS_EMBEDDER") or "hashing").lower()
    if name == "labse":
        return LabseEmbedder()
    if name == "hashing":
        return HashingEmbedder()
    raise ValueError(f"unknown embedder {name!r}; expected 'hashing' or 'labse'")
