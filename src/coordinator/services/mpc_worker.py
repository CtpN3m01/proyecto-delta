"""Procesa la cola MPC en segundo plano: un video a la vez, en orden FIFO.

El navegador ya no participa: cada Node Agent aporta su share y
result-storage recibe el resultado anonimizado (delta_video_offline.mpc).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any
from uuid import UUID

import httpx

from coordinator.models.video import VideoMetadata
from coordinator.services import job_store as states
from coordinator.services.job_store import JobStore
from coordinator.services.video_service import VideoService

logger = logging.getLogger(__name__)


class MpcJobError(RuntimeError):
    pass


class Cluster:
    """Llamadas HTTP internas a los Node Agents y a result-storage."""

    def __init__(self, party_urls: list[str] | None = None, storage_url: str | None = None) -> None:
        raw = os.getenv("PARTY_CONTROL_URLS", "http://party-0:8000,http://party-1:8000,http://party-2:8000")
        self.party_urls = party_urls or [url.strip().rstrip("/") for url in raw.split(",") if url.strip()]
        self.storage_url = (storage_url or os.getenv("STORAGE_INTERNAL_URL", "http://result-storage:8000")).rstrip("/")

    async def parties(self, method: str, path: str, json: Any = None, *, missing_ok: bool = False) -> list[dict]:
        async with httpx.AsyncClient(timeout=60) as client:
            replies = await asyncio.gather(*(
                client.request(method, f"{url}{path}", json=json) for url in self.party_urls
            ))
        bodies = []
        for reply in replies:
            if missing_ok and reply.status_code == 404:
                bodies.append({})
                continue
            reply.raise_for_status()
            bodies.append(reply.json() if reply.content else {})
        return bodies

    async def storage(self, method: str, path: str, json: Any = None) -> dict:
        async with httpx.AsyncClient(timeout=60) as client:
            reply = await client.request(method, f"{self.storage_url}{path}", json=json)
        reply.raise_for_status()
        return reply.json() if reply.content else {}


class MpcWorker:
    def __init__(self, store: JobStore, cluster: Cluster, video_service: VideoService,
                 poll_seconds: float = 2.0) -> None:
        self.store = store
        self.cluster = cluster
        self.video_service = video_service
        self.poll_seconds = poll_seconds
        self.program = os.getenv("MPC_OFFLINE_PROGRAM", "delta_video_offline")
        self.wake = asyncio.Event()

    async def run_forever(self) -> None:
        while True:
            job = self.store.next_queued()
            if job is None:
                self.wake.clear()
                try:
                    await asyncio.wait_for(self.wake.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass
                continue
            try:
                await self.run_job(job)
            except Exception:
                logger.exception("Error inesperado del worker MPC")
                await asyncio.sleep(self.poll_seconds)

    async def run_job(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        if not self.store.transition(job_id, {states.QUEUED}, states.PROCESSING):
            return
        try:
            result_id = await self._process(job)
        except Exception:
            logger.exception("Falló el MPC del video %s", job_id)
            await self._release(job_id, success=False)
            self.store.update(job_id, status=states.FAILED, error="El procesamiento MPC falló")
        else:
            await self._release(job_id, success=True)
            self.store.update(job_id, status=states.COMPLETED, result_id=result_id, error=None)
        await self._discard_shares(job_id)

    async def _process(self, job: dict[str, Any]) -> str:
        job_id, metadata = job["id"], VideoMetadata(**job["metadata"])
        # Un job anterior interrumpido no puede dejar a una party ocupada.
        await self.cluster.parties("POST", "/api/v1/jobs/reset")
        self.video_service.register_video(job["filename"], "mp4", video_id=_uuid(job_id))
        self.video_service.prepare(_uuid(job_id), metadata)
        await self.cluster.parties("POST", f"/api/v1/jobs/{job_id}/prepare",
                                   {"metadata": metadata.model_dump(), "program": self.program})
        await self.cluster.parties("POST", f"/api/v1/jobs/{job_id}/start")
        self.video_service.start(_uuid(job_id))
        await self.cluster.storage("POST", f"/api/v1/internal/collect/{job_id}",
                                   {"metadata": metadata.model_dump(), "counts": job["counts"]})
        await self.cluster.parties("POST", f"/api/v1/jobs/{job_id}/feed")
        while True:
            await asyncio.sleep(self.poll_seconds)
            collected = await self.cluster.storage("GET", f"/api/v1/internal/collect/{job_id}")
            if collected["status"] == "COMPLETED":
                return str(collected["result_id"])
            if collected["status"] == "FAILED":
                raise MpcJobError("result-storage no pudo reconstruir el resultado")
            for party in await self.cluster.parties("GET", f"/api/v1/jobs/{job_id}"):
                if (party.get("feed") or {}).get("status") == "FAILED":
                    raise MpcJobError(f"La party {party.get('party_id')} no pudo aportar su share")

    async def _release(self, job_id: str, *, success: bool) -> None:
        video_id = _uuid(job_id)
        try:
            if success:
                await self.cluster.parties("POST", f"/api/v1/jobs/{job_id}/complete")
            else:
                await self.cluster.parties("POST", f"/api/v1/jobs/{job_id}/fail",
                                           {"detail": "MPC en segundo plano fallido"}, missing_ok=True)
            await self.cluster.parties("POST", f"/api/v1/jobs/{job_id}/cleanup", missing_ok=True)
        except Exception:
            logger.exception("No se pudo liberar a las parties; se reiniciarán en el próximo job")
        try:
            await self.cluster.storage("DELETE", f"/api/v1/internal/collect/{job_id}")
        except Exception:
            logger.warning("No se pudo limpiar el estado de result-storage")
        try:
            if success:
                self.video_service.complete(video_id)
            else:
                self.video_service.fail(video_id, "MPC en segundo plano fallido")
            self.video_service.cleanup(video_id)
        except Exception:
            pass

    async def _discard_shares(self, job_id: str) -> None:
        try:
            await self.cluster.parties("DELETE", f"/api/v1/uploads/{job_id}", missing_ok=True)
        except Exception:
            logger.warning("No se pudieron borrar los shares del video %s", job_id)


def _uuid(value: str) -> UUID:
    return UUID(str(value))
