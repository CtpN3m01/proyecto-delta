"""Videos de cada usuario: el navegador detecta y sube shares; el MPC sigue
en segundo plano aunque el usuario cierre la pestaña.

Ciclo: UPLOADING (navegador) -> QUEUED -> PROCESSING -> COMPLETED | FAILED.
Mientras está en UPLOADING, el navegador debe enviar heartbeats; si se va
antes de terminar la detección el video queda FAILED, porque los cuadros
originales solo existen en ese navegador.
"""

import asyncio
import logging
import os
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from coordinator.api.videos import video_service
from coordinator.auth import current_user
from coordinator.models.video import VideoMetadata
from coordinator.services import job_store as states
from coordinator.services.job_store import JobStore
from coordinator.services.mpc_worker import Cluster, MpcWorker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/browser-jobs", tags=["browser jobs"])
User = Annotated[str, Depends(current_user)]


class CreateJobRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    format: str = Field(min_length=1, max_length=20)
    metadata: VideoMetadata


class UploadedRequest(BaseModel):
    counts: dict[str, Any] = Field(default_factory=dict)


class Service:
    def __init__(self) -> None:
        self.store = JobStore()
        self.cluster = Cluster()
        self.worker = MpcWorker(self.store, self.cluster, video_service)
        self.lease = float(os.getenv("DELTA_LEASE_SECONDS", "90"))

    def snapshot(self, job: dict[str, Any]) -> dict[str, Any]:
        """Lo único que el usuario ve: nombre original y estado."""
        return {"id": job["id"], "filename": job["filename"], "status": job["status"],
                "position": self.store.queue_position(job)}

    def owned(self, job_id: UUID, user: str) -> dict[str, Any]:
        job = self.store.get(job_id)
        if job is None or job["owner"] != user:
            raise HTTPException(404, "Video no encontrado")
        return job

    async def abandon(self, job_id: str, status: str, error: str | None = None) -> bool:
        if not self.store.transition(job_id, {states.UPLOADING, states.QUEUED}, status, error=error):
            return False
        try:
            await self.cluster.parties("DELETE", f"/api/v1/uploads/{job_id}", missing_ok=True)
        except Exception:
            logger.warning("No se pudieron borrar los shares de %s", job_id)
        return True

    async def expire(self) -> None:
        for job in self.store.stale_uploads(self.lease):
            await self.abandon(job["id"], states.FAILED, "El navegador se cerró antes de terminar la detección")


service: Service | None = None


def get_service() -> Service:
    global service
    if service is None:
        service = Service()
    return service


Svc = Annotated[Service, Depends(get_service)]


@router.post("", status_code=201)
async def create(payload: CreateJobRequest, user: User, svc: Svc):
    if payload.format.strip().lower().lstrip(".") != "mp4":
        raise HTTPException(415, "Solo MP4")
    filename = payload.filename.strip()
    if not filename:
        raise HTTPException(422, "El nombre no puede estar vacío")
    job = svc.store.create(user, filename, payload.metadata.model_dump())
    try:
        await svc.cluster.parties("POST", f"/api/v1/uploads/{job['id']}", {"metadata": payload.metadata.model_dump()})
    except Exception as exc:
        await svc.abandon(job["id"], states.FAILED, "Las parties no aceptaron la carga")
        raise HTTPException(502, "Las parties MPC no están disponibles") from exc
    return svc.snapshot(job)


@router.get("")
async def mine(user: User, svc: Svc):
    return [svc.snapshot(job) for job in svc.store.list_for(user)]


@router.get("/{job_id}")
async def heartbeat(job_id: UUID, user: User, svc: Svc):
    job = svc.owned(job_id, user)
    if job["status"] == states.UPLOADING:
        svc.store.touch(job_id)
    return svc.snapshot(job)


@router.post("/{job_id}/uploaded")
async def uploaded(job_id: UUID, payload: UploadedRequest, user: User, svc: Svc):
    """El navegador terminó: desde aquí el usuario ya puede irse."""
    job = svc.owned(job_id, user)
    if job["status"] != states.UPLOADING:
        raise HTTPException(409, "El video no está esperando la carga")
    if len(str(payload.counts)) > 4096:
        raise HTTPException(422, "Conteos inválidos")
    try:
        await svc.cluster.parties("POST", f"/api/v1/uploads/{job_id}/seal")
    except Exception as exc:
        raise HTTPException(409, "Las parties todavía no tienen todos los shares") from exc
    if not svc.store.transition(job_id, {states.UPLOADING}, states.QUEUED,
                                counts=payload.counts, queued_at=states.now_iso()):
        raise HTTPException(409, "El video ya no está esperando la carga")
    svc.worker.wake.set()
    return svc.snapshot(svc.store.get(job_id))


@router.delete("/{job_id}")
async def cancel(job_id: UUID, user: User, svc: Svc):
    job = svc.owned(job_id, user)
    if job["status"] in states.TERMINAL:
        return svc.snapshot(job)
    if not await svc.abandon(str(job_id), states.CANCELLED):
        raise HTTPException(409, "El MPC ya comenzó; no se puede cancelar")
    return svc.snapshot(svc.store.get(job_id))


async def background(svc: Service) -> None:
    """Worker MPC + barrido de pestañas cerradas durante la detección."""
    svc.store.recover()

    async def sweep() -> None:
        while True:
            await asyncio.sleep(5)
            try:
                await svc.expire()
            except Exception:
                logger.exception("Falló el barrido de cargas vencidas")

    await asyncio.gather(svc.worker.run_forever(), sweep())
