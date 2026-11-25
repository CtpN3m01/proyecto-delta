"""Carga de shares desde el navegador para el MPC en segundo plano.

El coordinator abre la carga (UUID no adivinable) y el navegador sube a cada
party solo lo suyo: cuadros s0 + máscara a la party 0, una clave a 1 y 2.
"""

import base64
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from party_receiver.api.jobs import JobMetadata
from party_receiver.services.upload_store import (
    UploadConflictError,
    UploadNotFoundError,
    UploadStore,
)

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])
MAX_FRAME_BODY = 1920 * 1080 + 4 + 8 * 1024 * 1024


class OpenUploadRequest(BaseModel):
    metadata: JobMetadata


class KeyRequest(BaseModel):
    key: str = Field(min_length=1, max_length=64)


def _store(request: Request) -> UploadStore:
    return request.app.state.upload_store


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, UploadNotFoundError):
        return HTTPException(404, "Carga no encontrada")
    if isinstance(exc, UploadConflictError):
        return HTTPException(409, str(exc))
    return HTTPException(422, str(exc))


@router.post("/{video_id}", status_code=201)
async def open_upload(video_id: UUID, payload: OpenUploadRequest, request: Request) -> dict[str, Any]:
    try:
        return _store(request).open(video_id, payload.metadata.model_dump())
    except (UploadConflictError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/{video_id}")
async def get_upload(video_id: UUID, request: Request) -> dict[str, Any]:
    try:
        return _store(request).get(video_id)
    except UploadNotFoundError as exc:
        raise _translate(exc) from exc


@router.post("/{video_id}/frames/{index}")
async def upload_frame(video_id: UUID, index: int, request: Request) -> dict[str, Any]:
    if index < 0:
        raise HTTPException(422, "Índice inválido")
    body = bytearray()
    async for part in request.stream():
        body += part
        if len(body) > MAX_FRAME_BODY:
            raise HTTPException(413, "Cuadro demasiado grande")
    try:
        return _store(request).add_frame(video_id, index, bytes(body))
    except (UploadNotFoundError, UploadConflictError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/{video_id}/key")
async def upload_key(video_id: UUID, payload: KeyRequest, request: Request) -> dict[str, Any]:
    try:
        key = base64.b64decode(payload.key, validate=True)
        return _store(request).set_key(video_id, key)
    except (UploadNotFoundError, UploadConflictError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/{video_id}/seal")
async def seal_upload(video_id: UUID, request: Request) -> dict[str, Any]:
    try:
        return _store(request).seal(video_id)
    except (UploadNotFoundError, UploadConflictError) as exc:
        raise _translate(exc) from exc


@router.delete("/{video_id}", status_code=204)
async def delete_upload(video_id: UUID, request: Request) -> None:
    _store(request).delete(video_id)
