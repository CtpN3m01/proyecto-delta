"""Cliente ExternalIO 3: recibe el video YA anonimizado y lo codifica en MP4.

Solo recibe z = x * (1 - máscara) (ver delta_video_offline.mpc), es decir, el
mismo contenido que después se publica en el catálogo. Nunca ve un original.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import shutil
import subprocess
from threading import Lock, Thread
from typing import Any, Callable
from uuid import UUID

from mpc.offline_protocol import (
    CHUNK_SIZE,
    OUTPUT_CLIENT_ID,
    ExternalIoSession,
    chunk_count,
    decode_output,
)

logger = logging.getLogger(__name__)


@dataclass
class CollectState:
    status: str = "RUNNING"
    chunks: int = 0
    total_chunks: int = 0
    result_id: str | None = None
    error: str | None = None


def ffmpeg_encoder(path: Path, width: int, height: int, fps: float) -> subprocess.Popen:
    binary = shutil.which("ffmpeg")
    if binary is None:
        raise RuntimeError("ffmpeg no está instalado en result-storage")
    return subprocess.Popen(
        [binary, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{width}x{height}", "-framerate", f"{fps:.6f}",
         "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", "-f", "mp4", str(path)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def collect_video(
    metadata: dict[str, Any],
    session: ExternalIoSession,
    output: Path,
    encoder_factory: Callable[[Path, int, int, float], subprocess.Popen] = ffmpeg_encoder,
    progress: Callable[[int], None] = lambda _: None,
) -> None:
    width, height, frames = metadata["width"], metadata["height"], metadata["frame_count"]
    payload = width * height * frames
    total_chunks = chunk_count(payload)
    encoder = encoder_factory(output, width, height, float(metadata["fps"]))
    try:
        with session:
            session.handshake(payload, total_chunks)
            remaining = payload
            for index in range(total_chunks):
                length = min(CHUNK_SIZE, remaining)
                pixels = decode_output(session.receive_sum(CHUNK_SIZE), length)
                encoder.stdin.write(pixels.tobytes())
                remaining -= length
                progress(index + 1)
        encoder.stdin.close()
        if encoder.wait() != 0:
            raise RuntimeError("ffmpeg no pudo codificar el resultado")
    except BaseException:
        encoder.kill()
        encoder.wait()
        output.unlink(missing_ok=True)
        raise


class ResultCollector:
    def __init__(self, root: Path, store: Callable[[Path, dict[str, Any]], str],
                 session_factory: Callable[[int], ExternalIoSession] = ExternalIoSession,
                 encoder_factory: Callable[[Path, int, int, float], subprocess.Popen] = ffmpeg_encoder) -> None:
        self.root = root
        self.store = store
        self.session_factory = session_factory
        self.encoder_factory = encoder_factory
        self._jobs: dict[UUID, CollectState] = {}
        self._lock = Lock()

    def start(self, video_id: UUID, metadata: dict[str, Any], counts: dict[str, Any]) -> CollectState:
        with self._lock:
            current = self._jobs.get(video_id)
            if current is not None and current.status == "RUNNING":
                return current
            state = CollectState(
                total_chunks=chunk_count(metadata["width"] * metadata["height"] * metadata["frame_count"])
            )
            self._jobs[video_id] = state

        def run() -> None:
            output = self.root / f"{video_id}.collecting.mp4"
            try:
                collect_video(metadata, self.session_factory(OUTPUT_CLIENT_ID), output,
                              self.encoder_factory, progress=lambda n: setattr(state, "chunks", n))
                state.result_id = self.store(output, counts)
                state.status = "COMPLETED"
            except Exception as exc:
                logger.exception("Falló la recolección del resultado MPC")
                state.status = "FAILED"
                state.error = type(exc).__name__
            finally:
                output.unlink(missing_ok=True)

        Thread(target=run, name=f"collect-{video_id}", daemon=True).start()
        return state

    def get(self, video_id: UUID) -> CollectState | None:
        with self._lock:
            return self._jobs.get(video_id)

    def forget(self, video_id: UUID) -> None:
        with self._lock:
            self._jobs.pop(video_id, None)


def as_dict(state: CollectState) -> dict[str, Any]:
    return {"status": state.status, "chunks": state.chunks, "total_chunks": state.total_chunks,
            "result_id": state.result_id, "error": state.error}

