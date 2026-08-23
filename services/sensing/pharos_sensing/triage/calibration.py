"""Confidence calibration.

Raw softmax is not probability. The extractor's need-type head reports 0.99 on
almost every message it matches at all, which is useless to a solver that has
to decide whether to commit a boat.

Isotonic regression per head, fit on a held-out split, maps raw scores onto
observed correctness. After this step "0.7" means "right about 70% of the
time", and only then can `quantity_confidence` be an input to an optimizer
rather than decoration on a dashboard.

The reliability curve this module produces belongs on a slide.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from sklearn.isotonic import IsotonicRegression

HEADS = ("need_type", "headcount", "vulnerability", "medical_urgency")

# Below this many observations a head is left uncalibrated rather than fitted
# to noise. Saying "not enough data" beats a curve drawn through six points.
MIN_SAMPLES = 40


@dataclass
class Calibrator:
    models: dict[str, IsotonicRegression] = field(default_factory=dict)
    fitted_on: dict[str, int] = field(default_factory=dict)

    # ------------------------------------------------------------------
    def fit(self, head: str, raw: list[float], correct: list[bool]) -> bool:
        if len(raw) < MIN_SAMPLES or len(set(bool(c) for c in correct)) < 2:
            return False
        iso = IsotonicRegression(y_min=0.02, y_max=0.98, out_of_bounds="clip")
        iso.fit(np.asarray(raw, dtype=float), np.asarray(correct, dtype=float))
        self.models[head] = iso
        self.fitted_on[head] = len(raw)
        return True

    def fit_all(self, samples: dict[str, tuple[list[float], list[bool]]]) -> dict[str, bool]:
        return {head: self.fit(head, r, c) for head, (r, c) in samples.items()}

    # ------------------------------------------------------------------
    def apply(self, head: str, raw: float) -> float:
        model = self.models.get(head)
        if model is None:
            # Uncalibrated. Shrink toward the base rate so an uncalibrated head
            # never masquerades as a confident one.
            return float(np.clip(0.5 + 0.6 * (raw - 0.5), 0.05, 0.95))
        return float(np.clip(model.predict([raw])[0], 0.02, 0.98))

    def apply_many(self, head: str, raws: list[float]) -> list[float]:
        model = self.models.get(head)
        if model is None:
            return [self.apply(head, r) for r in raws]
        return [float(v) for v in np.clip(model.predict(np.asarray(raws, dtype=float)), 0.02, 0.98)]

    @property
    def is_fitted(self) -> bool:
        return bool(self.models)

    # ------------------------------------------------------------------
    def save(self, path: str | Path) -> None:
        """Store the fitted step function as plain JSON - no pickle, so a
        calibration file can be read, diffed and reviewed."""
        payload = {
            head: {
                "x": [float(v) for v in m.X_thresholds_],
                "y": [float(v) for v in m.y_thresholds_],
                "n": self.fitted_on.get(head, 0),
            }
            for head, m in self.models.items()
        }
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> Calibrator:
        payload = json.loads(Path(path).read_text())
        c = cls()
        for head, d in payload.items():
            iso = IsotonicRegression(y_min=0.02, y_max=0.98, out_of_bounds="clip")
            iso.fit(np.asarray(d["x"], dtype=float), np.asarray(d["y"], dtype=float))
            c.models[head] = iso
            c.fitted_on[head] = d.get("n", 0)
        return c


# ----------------------------------------------------------------------
# reliability
# ----------------------------------------------------------------------


@dataclass
class ReliabilityBin:
    lower: float
    upper: float
    mean_predicted: float
    observed_rate: float
    count: int


def reliability_curve(confidences, correctness, bins: int = 10) -> list[ReliabilityBin]:
    """Predicted probability against observed frequency, per bin.

    A perfectly calibrated head sits on the diagonal. The gap is the story.
    """
    conf = np.asarray(confidences, dtype=float)
    corr = np.asarray(correctness, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    out: list[ReliabilityBin] = []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (conf >= lo) & (conf < hi) if i < bins - 1 else (conf >= lo) & (conf <= hi)
        n = int(mask.sum())
        if not n:
            continue
        out.append(
            ReliabilityBin(
                lower=round(float(lo), 3),
                upper=round(float(hi), 3),
                mean_predicted=round(float(conf[mask].mean()), 4),
                observed_rate=round(float(corr[mask].mean()), 4),
                count=n,
            )
        )
    return out


def expected_calibration_error(confidences, correctness, bins: int = 10) -> float:
    """ECE: the average gap between claimed and actual, weighted by bin size.

    One number for the slide. Lower is better; report it before and after.
    """
    curve = reliability_curve(confidences, correctness, bins)
    n = sum(b.count for b in curve)
    if not n:
        return 0.0
    return round(
        sum(b.count * abs(b.mean_predicted - b.observed_rate) for b in curve) / n, 4
    )


def brier_score(confidences, correctness) -> float:
    conf = np.asarray(confidences, dtype=float)
    corr = np.asarray(correctness, dtype=float)
    return round(float(np.mean((conf - corr) ** 2)), 4) if conf.size else 0.0


# ----------------------------------------------------------------------
# confidence -> interval
# ----------------------------------------------------------------------

# At confidence 1.0 the interval collapses to the point estimate; at 0.0 it
# spans roughly an order of magnitude. Tuned so a 0.9-confidence extraction
# gives about +-10%, which is the drift a careful human reporter introduces.
INTERVAL_SPREAD = 1.05
MIN_HALF_WIDTH = 0.04
MAX_HALF_WIDTH = 0.95


def headcount_interval(point: int, confidence: float) -> tuple[int, int, int]:
    """(lower, point, upper) for a calibrated headcount confidence.

    This interval is what the solver hedges on. Capacity is planned against
    `upper` so nobody arrives with too few seats; value is credited against
    `lower` so an uncertain demand is never over-counted.
    """
    hw = float(np.clip((1.0 - confidence) * INTERVAL_SPREAD, MIN_HALF_WIDTH, MAX_HALF_WIDTH))
    lower = max(0, int(round(point * (1.0 - hw))))
    upper = max(lower, int(round(point * (1.0 + hw))))
    # An interval of width zero on an uncertain estimate is a lie. Force at
    # least one person of slack whenever confidence is not near-certain.
    if confidence < 0.9 and upper == lower:
        upper = lower + 1
    return lower, max(lower, min(point, upper)), upper
