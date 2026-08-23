"""The plan: what the solver decided, and why.

Every assignment carries a machine-readable justification. The `alternatives`
reason is what makes an operator trust the system - it shows what was
rejected and on what grounds.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from .enums import PlanMode, TaskKind


class Reason(BaseModel):
    factor: str
    value: str
    contribution: float | None = Field(
        default=None, description="Share of this assignment's objective value, where numeric."
    )


class Assignment(BaseModel):
    assignment_id: str
    asset_id: str
    demand_id: str
    kind: TaskKind = TaskKind.RESCUE
    zone: str | None = None
    travel_minutes: float
    people_committed: int = 0
    objective_value: float = 0.0
    reasons: list[Reason] = Field(default_factory=list)
    route: list[tuple[float, float]] = Field(default_factory=list)


class UnservedDemand(BaseModel):
    """Why a demand has no asset. Silence here is how people get missed."""

    demand_id: str
    explanation: str
    nearest_asset_id: str | None = None
    nearest_travel_minutes: float | None = None


class ReserveDecision(BaseModel):
    """Capacity deliberately held back against unconfirmed demand."""

    assets_held: int
    total_assets: int
    mean_confidence: float
    rationale: str


class Plan(BaseModel):
    plan_id: str
    created_at: datetime
    mode: PlanMode = PlanMode.AUTONOMOUS
    banner: str | None = None

    assignments: list[Assignment] = Field(default_factory=list)
    unserved: list[UnservedDemand] = Field(default_factory=list)
    reserve: ReserveDecision | None = None

    equity_weight: float = 0.5
    solve_time_ms: float = 0.0
    solver_status: str = "UNKNOWN"
    objective_value: float = 0.0

    @property
    def rescue_assignments(self) -> list[Assignment]:
        return [a for a in self.assignments if a.kind == TaskKind.RESCUE]

    @property
    def verification_assignments(self) -> list[Assignment]:
        return [a for a in self.assignments if a.kind == TaskKind.VERIFICATION]
