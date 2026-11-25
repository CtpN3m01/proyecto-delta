"""Shares que el navegador deja en una party para el MPC en segundo plano.

Party 0 guarda, por cuadro y en orden: su share s0 (ancho*alto bytes) y la
máscara pública comprimida con gzip. Parties 1 y 2 guardan solo una clave de
16 bytes con la que regeneran su share (ver mpc.offline_protocol.keystream).
Ninguna party recibe nunca un píxel original.
"""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
import shutil
import struct
from threading import RLock
from typing import Any, Iterator
from uuid import UUID

import numpy as np

from mpc.offline_protocol import KEY_SIZE

MAX_MASK_BYTES = 8 * 1024 * 1024


class UploadNotFoundError(LookupError):
    pass


class UploadConflictError(RuntimeError):
    pass


class UploadStore:
    def __init__(self, party_id: int, root: str | Path | None = None) -> None:
        self.party_id = party_id
        self.root = Path(root or os.getenv("PARTY_UPLOAD_DIR", "/data/party")) / "uploads"
        self._lock = RLock()

    # -- ciclo de vida -------------------------------------------------
    def open(self, video_id: UUID, metadata: dict[str, Any]) -> dict[str, Any]:
        directory = self._dir(video_id)
        with self._lock:
            if directory.exists():
                state = self._state(video_id)
                if state["metadata"] != metadata:
                    raise UploadConflictError("La carga ya existe con otro perfil")
                return self._public(state)
            directory.mkdir(parents=True)
            state = {"metadata": metadata, "frames": 0, "key": False, "sealed": False}
            self._write_state(video_id, state)
            return self._public(state)

    def add_frame(self, video_id: UUID, index: int, body: bytes) -> dict[str, Any]:
        if self.party_id != 0:
            raise UploadConflictError("Solo la party 0 recibe cuadros")
        with self._lock:
            state = self._state(video_id)
            metadata = state["metadata"]
            if state["sealed"]:
                raise UploadConflictError("La carga ya está sellada")
            if index < state["frames"]:
                return self._public(state)  # reintento idempotente del navegador
            if index != state["frames"] or index >= metadata["frame_count"]:
                raise UploadConflictError(f"Se esperaba el cuadro {state['frames']}")
            frame_size = metadata["width"] * metadata["height"]
            if len(body) < 4:
                raise ValueError("Cuadro vacío")
            (mask_length,) = struct.unpack("<I", body[:4])
            if not 0 < mask_length <= MAX_MASK_BYTES or len(body) != 4 + mask_length + frame_size:
                raise ValueError("Tamaño de cuadro incompatible con el perfil")
            compressed = body[4 : 4 + mask_length]
            try:
                mask = gzip.decompress(compressed)
            except (OSError, EOFError) as exc:
                raise ValueError("Máscara comprimida inválida") from exc
            if len(mask) != frame_size or np.frombuffer(mask, dtype=np.uint8).max() > 1:
                raise ValueError("La máscara debe tener un 0/1 por píxel")
            directory = self._dir(video_id)
            # Truncar a lo confirmado en state.json: una escritura interrumpida
            # no puede desplazar los cuadros siguientes.
            mask_bytes = state.get("mask_bytes", 0)
            with (directory / "share.bin").open("ab") as shares:
                shares.truncate(index * frame_size)
                shares.write(body[4 + mask_length :])
            with (directory / "mask.bin").open("ab") as masks:
                masks.truncate(mask_bytes)
                masks.write(struct.pack("<I", mask_length) + compressed)
            state["mask_bytes"] = mask_bytes + 4 + mask_length
            state["frames"] = index + 1
            self._write_state(video_id, state)
            return self._public(state)

    def set_key(self, video_id: UUID, key: bytes) -> dict[str, Any]:
        if self.party_id == 0:
            raise UploadConflictError("La party 0 no usa clave")
        if len(key) != KEY_SIZE:
            raise ValueError("La clave debe tener 16 bytes")
        with self._lock:
            state = self._state(video_id)
            if state["sealed"]:
                raise UploadConflictError("La carga ya está sellada")
            (self._dir(video_id) / "share.key").write_bytes(key)
            state["key"] = True
            self._write_state(video_id, state)
            return self._public(state)

    def seal(self, video_id: UUID) -> dict[str, Any]:
        with self._lock:
            state = self._state(video_id)
            complete = (
                state["frames"] == state["metadata"]["frame_count"]
                if self.party_id == 0
                else state["key"]
            )
            if not complete:
                raise UploadConflictError("La carga de esta party está incompleta")
            state["sealed"] = True
            self._write_state(video_id, state)
            return self._public(state)

    def delete(self, video_id: UUID) -> None:
        with self._lock:
            shutil.rmtree(self._dir(video_id), ignore_errors=True)

    def get(self, video_id: UUID) -> dict[str, Any]:
        with self._lock:
            return self._public(self._state(video_id))

    # -- lectura para el feeder ---------------------------------------
    def metadata(self, video_id: UUID) -> dict[str, Any]:
        state = self._state(video_id)
        if not state["sealed"]:
            raise UploadConflictError("La carga no está sellada")
        return state["metadata"]

    def key(self, video_id: UUID) -> bytes:
        return (self._dir(video_id) / "share.key").read_bytes()

    def share_frames(self, video_id: UUID) -> Iterator[np.ndarray]:
        metadata = self.metadata(video_id)
        frame_size = metadata["width"] * metadata["height"]
        with (self._dir(video_id) / "share.bin").open("rb") as shares:
            for _ in range(metadata["frame_count"]):
                data = shares.read(frame_size)
                if len(data) != frame_size:
                    raise UploadConflictError("Share incompleto en disco")
                yield np.frombuffer(data, dtype=np.uint8)

    def mask_frames(self, video_id: UUID) -> Iterator[np.ndarray]:
        metadata = self.metadata(video_id)
        with (self._dir(video_id) / "mask.bin").open("rb") as masks:
            for _ in range(metadata["frame_count"]):
                (length,) = struct.unpack("<I", masks.read(4))
                yield np.frombuffer(gzip.decompress(masks.read(length)), dtype=np.uint8)

    # -- internos -------------------------------------------------------
    def _dir(self, video_id: UUID) -> Path:
        return self.root / str(UUID(str(video_id)))

    def _state(self, video_id: UUID) -> dict[str, Any]:
        path = self._dir(video_id) / "state.json"
        if not path.is_file():
            raise UploadNotFoundError(f"Carga {video_id} no encontrada")
        return json.loads(path.read_text("utf-8"))

    def _write_state(self, video_id: UUID, state: dict[str, Any]) -> None:
        path = self._dir(video_id) / "state.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state), "utf-8")
        temporary.replace(path)

    def _public(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "party_id": self.party_id,
            "frames": state["frames"],
            "key": state["key"],
            "sealed": state["sealed"],
        }
