"""Local HTTP bridge that starts the trusted video client from the browser."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys
import tempfile
from threading import Lock
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse


ROOT = Path(__file__).resolve().parents[2]
CHUNK_SIZE = 1024 * 1024
logger = logging.getLogger("uvicorn.error")
DEFAULT_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:4173",
    "http://localhost:4173",
)


@dataclass
class VideoJob:
    id: UUID
    status: Literal["PROCESSING", "COMPLETED", "FAILED"] = "PROCESSING"
    stage: int = 0
    error: str | None = None
    result: Path | None = None
    log_path: Path | None = None
    counts: dict | None = None


ProgressCallback = Callable[[int], None]
ProcessRunner = Callable[[Path, Path, Path, ProgressCallback], Awaitable[Path]]


def _configured_origins() -> tuple[str, ...]:
    raw = os.getenv("DELTA_WEB_ORIGINS")
    if raw is None:
        return DEFAULT_ORIGINS
    origins = tuple(origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip())
    if not origins:
        raise RuntimeError("DELTA_WEB_ORIGINS debe contener al menos un origen")
    return origins


async def _run_client(
    video_path: Path,
    output_root: Path,
    log_path: Path,
    update_stage: ProgressCallback,
) -> Path:
    command = [
        sys.executable,
        "-u",
        "-m",
        "client",
        "upload",
        str(video_path),
        "--processing-mode",
        "anonymize",
        "--detect-faces",
        "--detect-plates",
        "--count-objects",
    ]
    environment = os.environ.copy()
    environment["DELTA_OUTPUT_DIR"] = str(output_root)
    environment["PYTHONIOENCODING"] = "utf-8"

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=ROOT,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            async for raw_line in process.stdout:
                line = raw_line.decode("utf-8", errors="replace")
                log.write(line)
                log.flush()
                if line.startswith(("[OK]", "[PROGRESO]", "[AVISO]", "[TIEMPO]", "[MODO]")):
                    logger.info("cliente: %s", line.rstrip())
                if "[OK] Datos enviados y recibidos" in line:
                    update_stage(3)
                elif "[OK] MPC listo" in line:
                    update_stage(2)
                elif "[OK] YuNet:" in line or "[OK] Placas:" in line or "[PROGRESO] Detección" in line:
                    update_stage(1)
            await process.wait()
        except BaseException:
            if process.returncode is None:
                process.terminate()
                await process.wait()
            raise

    if process.returncode != 0:
        try:
            details = log_path.read_text(encoding="utf-8", errors="replace")[-2000:].strip()
        except OSError:
            details = ""
        raise RuntimeError(details or f"El cliente terminó con código {process.returncode}.")

    results = tuple(output_root.glob("*/reconstructed.mp4"))
    if len(results) != 1:
        raise RuntimeError("El cliente terminó pero no se encontró exactamente un video reconstruido.")
    update_stage(4)
    return results[0]


def create_app(
    *,
    allowed_origins: tuple[str, ...] | None = None,
    process_runner: ProcessRunner = _run_client,
) -> FastAPI:
    origins = allowed_origins if allowed_origins is not None else _configured_origins()
    application = FastAPI(
        title="Proyecto Delta Local Client",
        description="Puente local para iniciar el cliente confiable de video desde el navegador.",
        version="0.1.0",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    application.state.jobs = {}
    application.state.jobs_lock = Lock()
    application.state.active_job_id = None
    application.state.tasks = set()
    application.state.process_runner = process_runner
    application.state.allowed_origins = frozenset(origins)

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/api/v1/jobs", status_code=202)
    async def start_job(request: Request, video: UploadFile = File(...)) -> dict[str, str]:
        origin = request.headers.get("origin")
        if origin not in request.app.state.allowed_origins:
            raise HTTPException(status_code=403, detail="Origen web no autorizado.")
        if not video.filename or Path(video.filename).suffix.lower() != ".mp4":
            raise HTTPException(status_code=415, detail="Solo se admiten archivos MP4.")

        with request.app.state.jobs_lock:
            if request.app.state.active_job_id is not None:
                raise HTTPException(status_code=409, detail="Ya hay un procesamiento en curso.")
            job_id = uuid4()
            request.app.state.active_job_id = job_id

        try:
            directory = Path(tempfile.mkdtemp(prefix=f"delta-{job_id}-"))
        except Exception:
            with request.app.state.jobs_lock:
                request.app.state.active_job_id = None
            raise
        job = VideoJob(id=job_id)
        request.app.state.jobs[job_id] = job
        video_path = directory / "input.mp4"
        size = 0
        try:
            raw_limit = os.getenv("DELTA_MAX_UPLOAD_MB", "").strip()
            try:
                upload_limit = int(raw_limit) * 1024 * 1024 if raw_limit else None
            except ValueError as exc:
                raise HTTPException(status_code=503, detail="DELTA_MAX_UPLOAD_MB debe ser un entero positivo.") from exc
            if upload_limit is not None and upload_limit <= 0:
                raise HTTPException(status_code=503, detail="DELTA_MAX_UPLOAD_MB debe ser positivo.")
            with video_path.open("wb") as destination:
                while chunk := await video.read(CHUNK_SIZE):
                    size += len(chunk)
                    if upload_limit is not None and size > upload_limit:
                        raise HTTPException(
                            status_code=413,
                            detail=f"El video supera el límite configurado de {upload_limit // (1024 * 1024)} MiB.",
                        )
                    destination.write(chunk)
            if size == 0:
                raise HTTPException(status_code=422, detail="El archivo está vacío.")
        except Exception:
            try:
                shutil.rmtree(directory)
            finally:
                request.app.state.jobs.pop(job_id, None)
                with request.app.state.jobs_lock:
                    request.app.state.active_job_id = None
            raise
        finally:
            await video.close()

        async def run() -> None:
            def update_stage(stage: int) -> None:
                job.stage = max(job.stage, stage)

            try:
                output_root = (Path(os.getenv("DELTA_OUTPUT_DIR", str(ROOT / "output")))
                               .expanduser().resolve() / "web" / str(job_id))
                output_root.mkdir(parents=True, exist_ok=True)
                job.log_path = output_root / "client.log"
                job.result = await request.app.state.process_runner(
                    video_path,
                    output_root,
                    job.log_path,
                    update_stage,
                )
                report = job.result.with_name("counts.json")
                if report.is_file():
                    job.counts = json.loads(report.read_text(encoding="utf-8"))
                job.status = "COMPLETED"
            except Exception as exc:
                job.status = "FAILED"
                job.error = str(exc)[:2000]
            finally:
                try:
                    shutil.rmtree(directory)
                except OSError as exc:
                    if job.status == "COMPLETED":
                        job.status = "FAILED"
                        job.error = f"El resultado está listo, pero no se pudo limpiar el archivo temporal: {exc}"
                with request.app.state.jobs_lock:
                    if request.app.state.active_job_id == job_id:
                        request.app.state.active_job_id = None

        task = asyncio.create_task(run())
        request.app.state.tasks.add(task)
        task.add_done_callback(request.app.state.tasks.discard)
        return {"id": str(job_id), "status": job.status}

    @application.get("/api/v1/jobs/{job_id}")
    async def get_job(job_id: UUID, request: Request) -> dict[str, object]:
        if request.headers.get("origin") not in request.app.state.allowed_origins:
            raise HTTPException(status_code=403, detail="Origen web no autorizado.")
        job = request.app.state.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Procesamiento no encontrado.")
        response: dict[str, object] = {
            "id": str(job.id),
            "status": job.status,
            "stage": job.stage,
        }
        if job.error:
            response["error"] = job.error
        if job.counts is not None:
            response["counts"] = job.counts
        if job.log_path is not None and job.log_path.is_file():
            with job.log_path.open("rb") as log:
                log.seek(max(0, job.log_path.stat().st_size - 8192))
                response["logs"] = log.read().decode("utf-8", errors="replace").splitlines()[-20:]
        if job.status == "COMPLETED":
            response["result_url"] = f"/api/v1/jobs/{job.id}/result"
        return response

    @application.get("/api/v1/jobs/{job_id}/result")
    async def get_result(job_id: UUID, request: Request) -> FileResponse:
        if request.headers.get("origin") not in request.app.state.allowed_origins:
            raise HTTPException(status_code=403, detail="Origen web no autorizado.")
        job = request.app.state.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Procesamiento no encontrado.")
        if job.status != "COMPLETED" or job.result is None or not job.result.is_file():
            raise HTTPException(status_code=409, detail="El video anonimizado todavía no está disponible.")
        return FileResponse(
            job.result,
            media_type="video/mp4",
            filename="video-anonimizado.mp4",
        )

    return application


app = create_app()
