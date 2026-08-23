"""The raw message envelope.

Every intake channel - SMS, chat webhook, social reader, web form, 112
transcript, control-room entry - normalizes into exactly this shape before the
sensing layer sees it. Adding a channel means writing an adapter, never
changing this file.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from .enums import Channel


class AttachedGeo(BaseModel):
    """Coordinates the channel itself supplied, if any.

    `accuracy_m` is the channel's own claim. A dropped pin is metres; a cell
    tower is kilometres. The geo cascade uses it to pick a resolution level.
    """

    lat: float
    lon: float
    accuracy_m: float | None = None


class MessageEnvelope(BaseModel):
    message_id: str
    channel: Channel
    raw_text: str
    sender_hash: str = Field(
        description="Salted hash of the sender identifier. Raw identifiers never leave intake."
    )
    received_at: datetime
    attached_geo: AttachedGeo | None = None
    channel_metadata: dict = Field(default_factory=dict)

    # Populated by the normalization stage; the original is always retained so
    # the operator's provenance view can show what the citizen actually wrote.
    normalized_text: str | None = None
    detected_language: str | None = None
    language_confidence: float | None = None

    def text_for_analysis(self) -> str:
        return self.normalized_text or self.raw_text
