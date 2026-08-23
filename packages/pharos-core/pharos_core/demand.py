"""THE SEAM.

A DemandRecord is what the sensing layer produces and the allocation layer
consumes. It is the only object both halves of PHAROS agree on.

Four fields here do not exist in comparable systems, and everything novel in
this project consumes one of them:

    duplicate_collapse_count   how many reports collapsed into this demand
    quantity_confidence        calibrated, so 0.7 means 70% - not raw softmax
    trust_score                continuous, an optimizer input, never a filter
    location.resolution        how precisely we actually know where this is
"""

from datetime import datetime, timedelta

from pydantic import BaseModel, Field, model_validator

from .enums import DemandStatus, GeoResolution, MedicalUrgency, NeedType, TimeDecay

# Trust decays with a 90-minute half-life from last corroboration. A lead
# nobody has re-confirmed in three hours quietly stops competing for assets,
# instead of generating calls forever - the 2021 stale-lead failure.
FRESHNESS_HALF_LIFE = timedelta(minutes=90)


class Location(BaseModel):
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    resolution: GeoResolution
    geo_confidence: float = Field(ge=0.0, le=1.0)
    method: str = Field(description="Which cascade step resolved this, for the provenance view.")
    h3_cell: str | None = None

    @property
    def is_mappable_as_point(self) -> bool:
        """Ward- and unknown-resolution demands render as a hex or a list row,
        never as a pin. That visual honesty is a feature."""
        return self.resolution in (GeoResolution.POINT, GeoResolution.BUILDING)


class Need(BaseModel):
    type: NeedType
    people: int = Field(ge=0, description="Point estimate. Never used by the solver on its own.")
    people_lower: int = Field(ge=0, description="Confidence interval lower bound.")
    people_upper: int = Field(ge=0, description="Confidence interval upper bound.")
    vulnerability_flags: list[str] = Field(default_factory=list)
    medical_urgency: MedicalUrgency = MedicalUrgency.NONE

    @model_validator(mode="after")
    def check_interval(self):
        if not (self.people_lower <= self.people <= self.people_upper):
            raise ValueError(
                f"headcount interval violated: {self.people_lower} <= {self.people} "
                f"<= {self.people_upper} is false"
            )
        return self

    @property
    def interval_width(self) -> int:
        return self.people_upper - self.people_lower


class FieldConfidence(BaseModel):
    """Per-field confidence, not one score per message.

    A model that says "evacuation, 7 people, confidence 0.62 on the headcount"
    is far more useful than one that says "high priority".
    """

    need_type: float = Field(ge=0.0, le=1.0, default=0.5)
    headcount: float = Field(ge=0.0, le=1.0, default=0.5)
    vulnerability: float = Field(ge=0.0, le=1.0, default=0.5)
    medical_urgency: float = Field(ge=0.0, le=1.0, default=0.5)


class DemandRecord(BaseModel):
    demand_id: str
    source_message_ids: list[str] = Field(default_factory=list)
    duplicate_collapse_count: int = Field(ge=1, default=1)

    location: Location
    need: Need
    field_confidence: FieldConfidence = Field(default_factory=FieldConfidence)

    quantity_confidence: float = Field(
        ge=0.0, le=1.0, description="Calibrated. Enters the solver as an interval, not a point."
    )
    trust_score: float = Field(
        ge=0.0,
        le=1.0,
        default=1.0,
        description="Suppresses asset commitment. Never filters the record out.",
    )

    first_reported_at: datetime
    last_corroborated_at: datetime
    time_decay_class: TimeDecay = TimeDecay.STABLE
    status: DemandStatus = DemandStatus.UNASSIGNED
    escalation_weight: float = Field(ge=1.0, default=1.0)

    # Provenance, for the operator's detail panel.
    channels: list[str] = Field(default_factory=list)
    raw_texts: list[str] = Field(default_factory=list)
    truth_id: str | None = Field(
        default=None, description="Ground-truth link. Evaluation only; never read by the solver."
    )

    @model_validator(mode="after")
    def check_times(self):
        if self.last_corroborated_at < self.first_reported_at:
            raise ValueError("last_corroborated_at precedes first_reported_at")
        if self.duplicate_collapse_count != max(1, len(self.source_message_ids)):
            # Records built by hand or by the generator may not carry sources.
            if self.source_message_ids:
                raise ValueError(
                    f"duplicate_collapse_count {self.duplicate_collapse_count} disagrees with "
                    f"{len(self.source_message_ids)} source messages"
                )
        return self

    def age_minutes(self, now: datetime) -> float:
        return (now - self.first_reported_at).total_seconds() / 60.0

    def staleness_minutes(self, now: datetime) -> float:
        return (now - self.last_corroborated_at).total_seconds() / 60.0

    @property
    def is_uncertain(self) -> bool:
        return self.need.interval_width > 0
