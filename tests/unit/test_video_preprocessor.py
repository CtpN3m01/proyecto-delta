"""Pruebas del preprocesamiento local y su contenedor binario de frames JPEG."""

import json
from pathlib import Path
import struct

import cv2
import numpy as np
import pytest

from client.preprocessing import VideoPreprocessingError, VideoPreprocessor


_PAYLOAD_MAGIC = b"DELTA-T09-JPEG\x00"
_METADATA_CAPACITY = 512
_LENGTH = struct.Struct(">I")


def _deserialize_payload(payload: bytes) -> tuple[dict[str, object], list[np.ndarray]]:
    assert payload.startswith(_PAYLOAD_MAGIC)
    metadata_length_offset = len(_PAYLOAD_MAGIC)
    (metadata_length,) = _LENGTH.unpack_from(payload, metadata_length_offset)
    metadata_offset = metadata_length_offset + _LENGTH.size
    metadata = json.loads(
        payload[metadata_offset : metadata_offset + metadata_length].decode("utf-8")
    )

    frames: list[np.ndarray] = []
    offset = metadata_offset + _METADATA_CAPACITY
    for _ in range(int(metadata["frame_count"])):
        (frame_length,) = _LENGTH.unpack_from(payload, offset)
        offset += _LENGTH.size
        assert frame_length > 0
        encoded = np.frombuffer(payload[offset : offset + frame_length], dtype=np.uint8)
        frame = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
        assert frame is not None
        frames.append(frame)
        offset += frame_length
    assert offset == len(payload)
    return metadata, frames


@pytest.fixture
def tiny_mp4(tmp_path: Path) -> Path:
    """Crea el MP4 mínimo necesario para probar el decodificador real."""

    path = tmp_path / "tiny.mp4"
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        5.0,
        (64, 48),
    )
    assert writer.isOpened(), "OpenCV no pudo crear el MP4 temporal de prueba"
    try:
        for value in (0, 80, 160):
            writer.write(np.full((48, 64, 3), value, dtype=np.uint8))
    finally:
        writer.release()
    assert path.stat().st_size > 0
    return path


def test_processes_real_mp4_and_serializes_frames_and_metadata(tiny_mp4: Path) -> None:
    result = VideoPreprocessor().process(tiny_mp4)

    assert result.payload
    assert result.metadata.frame_count == 3
    assert result.metadata.height == 48
    assert result.metadata.width == 64
    assert result.metadata.channels == 3
    assert result.metadata.fps == pytest.approx(5.0, abs=0.25)
    assert result.metadata.dtype == "uint8"

    metadata, frames = _deserialize_payload(result.payload)

    assert metadata == {
        "version": 1,
        "frame_encoding": "jpeg",
        "frame_count": result.metadata.frame_count,
        "height": result.metadata.height,
        "width": result.metadata.width,
        "channels": result.metadata.channels,
        "fps": result.metadata.fps,
        "dtype": result.metadata.dtype,
    }
    assert len(frames) == 3
    assert all(frame.shape == (48, 64, 3) for frame in frames)
    assert all(frame.dtype == np.uint8 for frame in frames)
    assert [float(frame.mean()) for frame in frames] == sorted(
        float(frame.mean()) for frame in frames
    )
    assert len(result.payload) < sum(frame.nbytes for frame in frames)


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        pytest.param("empty.mp4", b"", id="empty"),
        pytest.param("corrupto.mp4", b"esto no es un archivo MP4", id="corrupt"),
    ],
)
def test_rejects_empty_or_corrupt_mp4(
    tmp_path: Path,
    filename: str,
    content: bytes,
) -> None:
    path = tmp_path / filename
    path.write_bytes(content)

    with pytest.raises(VideoPreprocessingError, match="OpenCV no pudo abrir|no contiene frames"):
        VideoPreprocessor().process(path)


def test_rejects_nonexistent_video(tmp_path: Path) -> None:
    missing = tmp_path / "missing.mp4"

    with pytest.raises(VideoPreprocessingError, match="OpenCV no pudo abrir"):
        VideoPreprocessor().process(missing)
