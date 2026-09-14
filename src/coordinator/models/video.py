"""Request and response models for video coordination."""

from enum import Enum
from typing import Dict, List, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class VideoStatus(str, Enum):
    """Lifecycle states currently supported by the T09 Coordinator."""

    WAITING_FOR_SHARES = "WAITING_FOR_SHARES"
    READY_FOR_MPC = "READY_FOR_MPC"


class PartyShareStatus(str, Enum):
    """Receipt state for one party's share."""

    PENDING = "PENDING"
    RECEIVED = "RECEIVED"


class PartyEndpoint(BaseModel):
    """Public endpoint assigned to a party."""

    id: int
    url: str


class VideoRegistrationRequest(BaseModel):
    """Metadata accepted when a trusted client registers a video."""

    filename: str = Field(min_length=1, max_length=255)
    format: str = Field(min_length=1, max_length=20)


class VideoRegistrationResponse(BaseModel):
    """New job information and direct upload destinations."""

    id: UUID
    status: VideoStatus
    parties: List[PartyEndpoint]


class VideoStateResponse(BaseModel):
    """Current state of a registered video job."""

    id: UUID
    status: VideoStatus
    parties: Dict[str, PartyShareStatus]


class ConfirmationRequest(BaseModel):
    """Metadata sent by a party after it persisted its share."""

    party_id: int = Field(ge=0, le=2, strict=True)
    status: Literal["RECEIVED"]
