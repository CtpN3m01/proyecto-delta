"""API de control del Node Agent de una computing party."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from mpc.video_profile import MAX_CONFIGURED_FPS, MpcVideoProfile

from party_receiver.runtime import MpcRuntimeError
from party_receiver.services.job_service import (
    CoordinatorNotificationError,
    PartyJobConflictError,
    PartyJobNotFoundError,
    PartyJobService,
)


router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


class JobMetadata(BaseModel):
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    fps: float = Field(gt=0, le=MAX_CONFIGURED_FPS)
    frame_count: int = Field(ge=1)
    dtype: Literal["uint8"]
    channels: Literal[1]
    version: Literal[2]

    @model_validator(mode="after")
    def validate_resolution(self) -> "JobMetadata":
        profile = MpcVideoProfile.from_environment()
        if self.width > profile.max_width:
            raise ValueError(f"width no puede superar {profile.max_width}")
        if self.height > profile.max_height:
            raise ValueError(f"height no puede superar {profile.max_height}")
        return self


class PrepareJobRequest(BaseModel):
    metadata: JobMetadata
    program: Literal["delta_video_anonymize", "delta_video_offline"] | None = None


class FailJobRequest(BaseModel):
    detail: str = Field(min_length=1, max_length=1000)


class PartyJobResponse(BaseModel):
    video_id: UUID
    party_id: int
    status: Literal["READY", "PROCESSING", "COMPLETED", "FAILED", "CLEANED"]
    runtime: str
    error: str | None = None
    feed: dict[str, Any] | None = None


def get_job_service(request: Request) -> PartyJobService:
    return request.app.state.job_service


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PartyJobNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (PartyJobConflictError, MpcRuntimeError)):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, CoordinatorNotificationError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _with_feed(request: Request, video_id: UUID, response: dict[str, Any]) -> dict[str, Any]:
    state = request.app.state.feeder.get(video_id)
    if state is not None:
        response["feed"] = {
            "status": state.status,
            "chunks": state.chunks,
            "total_chunks": state.total_chunks,
            "error": state.error,
        }
    return response


@router.post("/reset", status_code=204)
async def reset_jobs(
    service: Annotated[PartyJobService, Depends(get_job_service)],
) -> None:
    service.reset()


@router.get("/{video_id}", response_model=PartyJobResponse)
async def get_job(
    video_id: UUID,
    request: Request,
    service: Annotated[PartyJobService, Depends(get_job_service)],
) -> dict[str, Any]:
    try:
        return _with_feed(request, video_id, service.get(video_id))
    except PartyJobNotFoundError as exc:
        raise _http_error(exc) from exc


@router.post("/{video_id}/feed", response_model=PartyJobResponse)
async def feed_job(
    video_id: UUID,
    request: Request,
    service: Annotated[PartyJobService, Depends(get_job_service)],
) -> dict[str, Any]:
    """Aporta el share almacenado de esta party al programa offline."""

    try:
        job = service.get(video_id)
        if job["status"] != "PROCESSING":
            raise PartyJobConflictError("El job debe estar PROCESSING")
        request.app.state.feeder.start(video_id)
        return _with_feed(request, video_id, job)
    except (PartyJobNotFoundError, PartyJobConflictError) as exc:
        raise _http_error(exc) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="No hay shares para este job") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{video_id}/prepare", response_model=PartyJobResponse)
async def prepare_job(
    video_id: UUID,
    payload: PrepareJobRequest,
    service: Annotated[PartyJobService, Depends(get_job_service)],
) -> dict[str, Any]:
    try:
        return await service.prepare(
            video_id, payload.metadata.model_dump(), payload.program
        )
    except (
        PartyJobConflictError,
        MpcRuntimeError,
        CoordinatorNotificationError,
    ) as exc:
        raise _http_error(exc) from exc


@router.post("/{video_id}/start", response_model=PartyJobResponse)
async def start_job(
    video_id: UUID,
    service: Annotated[PartyJobService, Depends(get_job_service)],
) -> dict[str, Any]:
    try:
        return service.start(video_id)
    except (PartyJobNotFoundError, PartyJobConflictError, MpcRuntimeError) as exc:
        raise _http_error(exc) from exc


@router.post("/{video_id}/complete", response_model=PartyJobResponse)
async def complete_job(
    video_id: UUID,
    service: Annotated[PartyJobService, Depends(get_job_service)],
) -> dict[str, Any]:
    try:
        return service.complete(video_id)
    except (PartyJobNotFoundError, PartyJobConflictError) as exc:
        raise _http_error(exc) from exc


@router.post("/{video_id}/fail", response_model=PartyJobResponse)
async def fail_job(
    video_id: UUID,
    payload: FailJobRequest,
    service: Annotated[PartyJobService, Depends(get_job_service)],
) -> dict[str, Any]:
    try:
        return service.fail(video_id, payload.detail)
    except PartyJobNotFoundError as exc:
        raise _http_error(exc) from exc


@router.post("/{video_id}/cleanup", response_model=PartyJobResponse)
async def cleanup_job(
    video_id: UUID,
    request: Request,
    service: Annotated[PartyJobService, Depends(get_job_service)],
) -> dict[str, Any]:
    try:
        response = service.cleanup(video_id)
        request.app.state.feeder.forget(video_id)
        return response
    except (PartyJobNotFoundError, PartyJobConflictError) as exc:
        raise _http_error(exc) from exc
