"""Evaluation harness: scenario in, one comparable metrics row out.

    generate -> sense -> dispatch -> measure -> append to results.jsonl

Every configuration - the two baselines and each ablation - runs through this
same function, so a row is comparable to every other row. That is the whole
value of building the ruler before the thing being measured.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from pharos_allocator import graph as roads
from pharos_allocator.objective import SolverConfig, Weights
from pharos_allocator.zones import assign_cells
from pharos_sensing.dedupe.cluster import metres
from pharos_sensing.pipeline import SensingConfig, SensingPipeline
from pharos_sensing.triage.calibration import (
    Calibrator,
    brier_score,
    expected_calibration_error,
    reliability_curve,
)

from . import dispatch, fleet, generator, metrics, spec
from .metrics import MetricsRow

RESULTS_PATH = Path("data/results/results.jsonl")
GRAPH_CACHE = Path("data/road_graph.pkl")


@dataclass
class RunConfig:
    """One row of the ablation table."""

    name: str
    sensing: SensingConfig = field(default_factory=SensingConfig)
    solver: SolverConfig = field(default_factory=SolverConfig)
    weights: Weights = field(default_factory=Weights)
    policy: str = "pharos"
    calibrate: bool = True

    def describe(self) -> dict:
        return {
            "policy": self.policy,
            "dedup": self.sensing.enable_dedup,
            "calibration": self.sensing.enable_calibration,
            "trust_sensing": self.sensing.enable_trust,
            "geo_cascade": self.sensing.enable_geo_cascade,
            "confidence": self.solver.use_confidence,
            "reserve": self.solver.use_reserve,
            "verification": self.solver.use_verification,
            "trust_objective": self.solver.use_trust,
            "equity": self.solver.use_equity,
            "equity_weight": self.solver.equity_weight,
        }


# --------------------------------------------------------------------------
# the named configurations
# --------------------------------------------------------------------------


def configurations() -> dict[str, RunConfig]:
    """Each row removed from `full` is one novelty claim, quantified."""
    return {
        "fifo": RunConfig("fifo", policy="fifo"),
        "nearest": RunConfig("nearest", policy="nearest"),
        "full": RunConfig("full"),
        "no_dedup": RunConfig("no_dedup", sensing=SensingConfig.ablation("no_dedup")),
        "no_calibration": RunConfig(
            "no_calibration", sensing=SensingConfig.ablation("no_calibration"), calibrate=False
        ),
        "no_confidence": RunConfig(
            "no_confidence", solver=SolverConfig.ablation("no_confidence")
        ),
        "no_reserve": RunConfig("no_reserve", solver=SolverConfig.ablation("no_reserve")),
        "no_verification": RunConfig(
            "no_verification", solver=SolverConfig.ablation("no_verification")
        ),
        "no_trust": RunConfig(
            "no_trust",
            sensing=SensingConfig.ablation("no_trust"),
            solver=SolverConfig.ablation("no_trust"),
        ),
        "no_equity": RunConfig("no_equity", solver=SolverConfig.ablation("no_equity")),
        "no_geo_cascade": RunConfig(
            "no_geo_cascade", sensing=SensingConfig.ablation("no_geo_cascade")
        ),
    }


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------


def run(
    scenario_path: str | Path,
    config: RunConfig | None = None,
    seed: int | None = None,
    verbose: bool = False,
) -> MetricsRow:
    cfg = config or RunConfig("full")
    s = spec.load(scenario_path)
    if seed is not None:
        s.seed = seed

    # --- scenario ---------------------------------------------------------
    data = generator.generate(s)
    truth_index = _index_truth(data, s)

    rg = roads.load_or_build(GRAPH_CACHE, s.region.centre, s.region.radius_km, seed=s.seed)
    roads.restore(rg)  # every run starts from an undamaged network
    assets, _depots = fleet.build(s, rg)

    # --- sensing ----------------------------------------------------------
    calibrator = _fit_calibrator(data, s, cfg) if cfg.calibrate else Calibrator()
    pipeline = SensingPipeline(
        data.gazetteer, s.region.centre, cfg.sensing, calibrator=calibrator
    )
    t_sense = time.perf_counter()
    sensing = pipeline.process(list(data.messages), now=_end(data, s), t0=data.t0)
    sensing_seconds = time.perf_counter() - t_sense

    _attach_truth_ids(sensing, data)
    assign_cells(sensing.demands, s.region.h3_resolution)

    # --- dispatch ---------------------------------------------------------
    result = dispatch.run(
        sensing,
        truth_index,
        s,
        rg,
        assets,
        t0=data.t0,
        config=dispatch.DispatchConfig(
            policy=cfg.policy, solver=cfg.solver, weights=cfg.weights, verbose=verbose
        ),
    )

    # --- measure ----------------------------------------------------------
    return _measure(
        s, cfg, data, sensing, result, truth_index, sensing_seconds
    )


# --------------------------------------------------------------------------


def _end(data, s):
    return data.t0 + timedelta(hours=s.duration_hours)


def _index_truth(data, s) -> dict:
    """Ground truth, keyed by id, with H3 cell and onset minute stamped on."""
    from pharos_allocator.zones import cell

    idx = {}
    for t in data.truth:
        t.h3_cell = cell(t.lat, t.lon, s.region.h3_resolution)
        t._onset_min = (t.onset - data.t0).total_seconds() / 60.0
        idx[t.truth_id] = t
    return idx


def _attach_truth_ids(sensing, data) -> None:
    """Link each demand to the real event most of its messages came from.

    Evaluation wiring only. Nothing in the sensing or allocation path reads
    `truth_id`, and a test enforces that.
    """
    mmap = data.message_truth_map()
    for demand in sensing.demands:
        votes = Counter(mmap[mid] for mid in demand.source_message_ids if mid in mmap)
        demand.truth_id = votes.most_common(1)[0][0] if votes else None


def _fit_calibrator(data, s, cfg: RunConfig) -> Calibrator:
    """Fit isotonic calibration on a held-out split of the same scenario.

    Held out by message id so the calibration set and the evaluation set do not
    share events - otherwise the reliability curve is measuring memorisation.
    """
    from pharos_sensing.triage.extract import extract

    holdout = [m for i, m in enumerate(data.messages) if i % 5 == 0]
    if len(holdout) < 200:
        return Calibrator()

    truth = data.truth_by_id()
    mmap = data.message_truth_map()
    pipeline = SensingPipeline(data.gazetteer, s.region.centre, cfg.sensing)

    raw = {h: ([], []) for h in ("need_type", "headcount", "vulnerability", "medical_urgency")}
    for m in holdout:
        t = truth.get(mmap.get(m.message_id, ""))
        if t is None:
            continue
        text = pipeline.normalizer.normalize(m.raw_text)
        e = extract(text)
        raw["need_type"][0].append(e.need_type_raw)
        raw["need_type"][1].append(e.need_type == t.need)
        raw["headcount"][0].append(e.people_raw)
        raw["headcount"][1].append(abs(e.people - t.people) <= max(1, 0.25 * t.people))
        raw["vulnerability"][0].append(e.vulnerability_raw)
        raw["vulnerability"][1].append(
            set(e.vulnerability_flags) == set(t.vulnerability_flags)
        )
        raw["medical_urgency"][0].append(e.medical_urgency_raw)
        raw["medical_urgency"][1].append(e.medical_urgency == t.medical_urgency)

    c = Calibrator()
    c.fit_all(raw)
    return c


def _measure(s, cfg, data, sensing, result, truth_index, sensing_seconds) -> MetricsRow:
    served = result.served
    people_in_need = sum(t.people for t in data.real_truth)

    med_first, p95_first = metrics.time_to_first_assignment(served, truth_index)
    labels = [
        data.message_truth_map()[p.envelope.message_id] for p in sensing.processed
    ]

    row = MetricsRow(
        scenario=s.name,
        policy=cfg.name,
        seed=s.seed,
        coverage=metrics.coverage(served, people_in_need),
        coverage_within_window=metrics.coverage_within_window(served, truth_index),
        urgent_coverage_within_window=metrics.urgent_coverage_within_window(served, truth_index),
        urgency_weighted_coverage=metrics.urgency_weighted_coverage(served, truth_index),
        worst_off_zone_coverage=metrics.worst_off_zone_coverage(served, truth_index),
        zones_reached_fraction=metrics.zones_reached_fraction(served, truth_index),
        zone_gini=metrics.zone_coverage_gini(served, truth_index),
        median_time_to_reach_min=metrics.median_time_to_reach(served),
        median_time_to_first_assignment_min=med_first,
        p95_time_to_first_assignment_min=p95_first,
        people_reached=metrics._people_reached(served),
        people_in_need=people_in_need,
        wasted=metrics.assets_wasted(served),
        verification=metrics.verification_stats(served),
        dedup=metrics.dedup_precision_recall(sensing.clusters, labels),
        geo=metrics.geo_accuracy_by_level(sensing.demands, truth_index, metres),
        extraction=metrics.extraction_accuracy(sensing.demands, truth_index),
        calibration=_calibration_report(sensing, truth_index),
        messages=len(data.messages),
        demands=len(sensing.demands),
        sensing_seconds=round(sensing_seconds, 3),
        solve_seconds_total=result.solve_seconds_total,
        solve_seconds_p95=round(result.solve_ms_p95 / 1000.0, 4),
        replans=result.ticks,
        config=cfg.describe(),
    )
    return row


def _calibration_report(sensing, truth_index) -> dict:
    """Reliability of the headcount confidence the solver actually consumes."""
    conf, correct = [], []
    for d in sensing.demands:
        t = truth_index.get(d.truth_id or "")
        if t is None:
            continue
        conf.append(d.quantity_confidence)
        correct.append(abs(d.need.people - t.people) <= max(1, 0.25 * t.people))
    if not conf:
        return {}
    return {
        "n": len(conf),
        "ece": expected_calibration_error(conf, correct),
        "brier": brier_score(conf, correct),
        "curve": [
            {
                "bin": f"{b.lower:.1f}-{b.upper:.1f}",
                "predicted": b.mean_predicted,
                "observed": b.observed_rate,
                "n": b.count,
            }
            for b in reliability_curve(conf, correct)
        ],
    }


# --------------------------------------------------------------------------


def append_result(row: MetricsRow, path: Path = RESULTS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(row.to_dict()) + "\n")
