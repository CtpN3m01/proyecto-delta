"""Video registration and share-confirmation endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from coordinator.models.video import (
    ConfirmationRequest,
    VideoRegistrationRequest,
    VideoRegistrationResponse,
    VideoStateResponse,
)
from coordinator.services.video_service import (
    UnsupportedVideoFormatError,
    VideoNotFoundError,
    VideoService,
    load_party_urls,
)


router = APIRouter(prefix="/api/v1/videos", tags=["videos"])
video_service = VideoService(load_party_urls())


@router.post(
    "",
    response_model=VideoRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_video(payload: VideoRegistrationRequest) -> VideoRegistrationResponse:
    """Register metadata only; the original MP4 is never accepted here."""

    try:
        return video_service.register_video(payload.filename, payload.format)
    except UnsupportedVideoFormatError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get("/{video_id}", response_model=VideoStateResponse)
async def get_video(video_id: UUID) -> VideoStateResponse:
    """Read the aggregate status and individual party receipt states."""

    try:
        return video_service.get_video(video_id)
    except VideoNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post("/{video_id}/confirmations", response_model=VideoStateResponse)
async def confirm_share(
    video_id: UUID,
    payload: ConfirmationRequest,
) -> VideoStateResponse:
    """Record receipt metadata from a party; no share bytes pass through here."""

    try:
        return video_service.confirm_share(video_id, payload.party_id)
    except VideoNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

