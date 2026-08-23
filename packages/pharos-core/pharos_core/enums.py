"""Controlled vocabularies shared across every PHAROS service.

These are frozen on day two. Changing a member here changes the meaning of a
stored record, so it is a migration, not an edit.
"""

from enum import Enum


class NeedType(str, Enum):
    EVACUATION = "evacuation"
    MEDICAL = "medical"
    WATER = "water"
    FOOD = "food"
    SHELTER = "shelter"
    SANITATION = "sanitation"
    MISSING_PERSON = "missing_person"
    INFRASTRUCTURE = "infrastructure"


class MedicalUrgency(str, Enum):
    NONE = "none"
    MILD = "mild"
    MODERATE = "moderate"
    CRITICAL = "critical"


class GeoResolution(str, Enum):
    """How precisely we actually know where this is.

    The ordering matters: never upgrade a demand to a finer resolution than the
    method that resolved it supports. Inventing precision is the documented
    Kerala 2018 supply-drop failure.
    """

    POINT = "point"
    BUILDING = "building"
    STREET = "street"
    WARD = "ward"
    UNKNOWN = "unknown"


class TimeDecay(str, Enum):
    ESCALATING = "escalating"
    STABLE = "stable"
    RESOLVING = "resolving"


class DemandStatus(str, Enum):
    UNASSIGNED = "unassigned"
    VERIFYING = "verifying"
    ASSIGNED = "assigned"
    RESOLVED = "resolved"
    NOT_FOUND = "not_found"
    REFUSED = "refused"
    ESCALATED = "escalated"


class AssetType(str, Enum):
    BOAT = "boat"
    AMBULANCE = "ambulance"
    TRUCK = "truck"
    HELICOPTER = "helicopter"
    # Verification assets: cheap, non-physical, dispatched by the same solver.
    OPERATOR = "operator"
    VOLUNTEER = "volunteer"


VERIFICATION_ASSET_TYPES = frozenset({AssetType.OPERATOR, AssetType.VOLUNTEER})


class AssetState(str, Enum):
    IDLE = "idle"
    ASSIGNED = "assigned"
    EN_ROUTE = "en_route"
    ON_SITE = "on_site"
    RETURNING = "returning"
    OUT_OF_SERVICE = "out_of_service"


class Channel(str, Enum):
    SMS = "sms"
    CHAT = "chat"
    SOCIAL = "social"
    WEB_FORM = "web_form"
    CALL_TRANSCRIPT = "call_transcript"
    FIELD_REPORT = "field_report"
    CONTROL_ROOM = "control_room"


class Outcome(str, Enum):
    RESOLVED = "resolved"
    NOT_FOUND = "not_found"
    REFUSED = "refused"
    ESCALATED = "escalated"


class PlanMode(str, Enum):
    """Whether the system is permitted to auto-assign physical assets."""

    AUTONOMOUS = "autonomous"
    DECISION_SUPPORT = "decision_support"


class TaskKind(str, Enum):
    RESCUE = "rescue"
    VERIFICATION = "verification"
