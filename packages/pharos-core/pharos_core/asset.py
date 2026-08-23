"""Assets and depots.

Verification assets (operator, volunteer) live in the same registry as boats
and ambulances on purpose: they are dispatched by the same solver, competing
for the same scheduling budget. That is what makes verification a dispatch
class rather than a side channel.
"""

from pydantic import BaseModel, Field

from .enums import VERIFICATION_ASSET_TYPES, AssetState, AssetType


class Depot(BaseModel):
    depot_id: str
    name: str
    lat: float
    lon: float


class Asset(BaseModel):
    asset_id: str
    type: AssetType
    capacity: int = Field(ge=0, description="People per sortie, or tasks per window for verifiers.")
    speed_kmh: float = Field(gt=0.0)
    depot_id: str
    lat: float
    lon: float
    state: AssetState = AssetState.IDLE
    h3_cell: str | None = None

    # Which need types this asset can actually serve. Empty means all.
    serves: list[str] = Field(default_factory=list)

    @property
    def is_verifier(self) -> bool:
        return self.type in VERIFICATION_ASSET_TYPES

    @property
    def is_available(self) -> bool:
        return self.state in (AssetState.IDLE, AssetState.RETURNING)


class InventoryItem(BaseModel):
    """Consumables held at a depot, in Sphere-standard units."""

    depot_id: str
    resource: str
    on_hand: float
    reserved: float = 0.0
    unit: str = "person_days"

    @property
    def available(self) -> float:
        return max(0.0, self.on_hand - self.reserved)


# Sphere Handbook minimums, per person per day. Cited so the numbers in the
# demo are not invented.
SPHERE_MINIMUMS = {
    "water_litres": 15.0,
    "food_kcal": 2100.0,
    "shelter_m2": 3.5,
    "latrines_per_person": 1.0 / 20.0,
}
