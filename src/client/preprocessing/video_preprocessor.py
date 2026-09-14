"""Decodificación local de MP4 y serialización binaria por frames."""

from dataclasses import dataclass
from io import BytesIO
import json
from pathlib import Path
import struct

import cv2
import numpy as np


_PAYLOAD_MAGIC = b"DELTA-T09-JPEG\x00"
_METADATA_CAPACITY = 512
_LENGTH = struct.Struct(">I")
_JPEG_PARAMETERS = (cv2.IMWRITE_JPEG_QUALITY, 90)


class VideoPreprocessingError(RuntimeError):
    """El MP4 no pudo convertirse a la representación binaria de T09."""


@dataclass(frozen=True)
class VideoMetadata:
    frame_count: int
    height: int
    width: int
    channels: int
    fps: float
    dtype: str


@dataclass(frozen=True)
class PreprocessedVideo:
    payload: bytes
    metadata: VideoMetadata


class VideoPreprocessor:
    """Lee el MP4 local y produce un payload binario; no realiza operaciones de red.

    Cada frame decodificado se codifica inmediatamente como JPEG. El contenedor
    resultante incluye magic, metadata JSON y bloques de longitud prefijada. De
    este modo nunca se mantienen simultáneamente todos los frames crudos en RAM.
    """

    def process(self, video_path: str | Path) -> PreprocessedVideo:
        path = Path(video_path)
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            capture.release()
            raise VideoPreprocessingError(f"OpenCV no pudo abrir el MP4: {path}")

        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if not np.isfinite(fps) or fps < 0:
            fps = 0.0

        buffer = BytesIO()
        buffer.write(_PAYLOAD_MAGIC)
        buffer.write(_LENGTH.pack(0))
        buffer.write(bytes(_METADATA_CAPACITY))

        frame_count = 0
        expected_shape: tuple[int, ...] | None = None
        expected_dtype: np.dtype[np.generic] | None = None
        try:
            while True:
                success, frame = capture.read()
                if not success:
                    break
                if expected_shape is None:
                    expected_shape = frame.shape
                    expected_dtype = frame.dtype
                elif frame.shape != expected_shape or frame.dtype != expected_dtype:
                    raise VideoPreprocessingError(
                        "El video contiene frames con dimensiones o dtype inconsistentes."
                    )

                encoded_ok, encoded_frame = cv2.imencode(
                    ".jpg",
                    frame,
                    _JPEG_PARAMETERS,
                )
                if not encoded_ok:
                    raise VideoPreprocessingError(
                        "OpenCV no pudo codificar uno de los frames del MP4."
                    )
                encoded_bytes = encoded_frame.tobytes()
                buffer.write(_LENGTH.pack(len(encoded_bytes)))
                buffer.write(encoded_bytes)
                frame_count += 1
        except VideoPreprocessingError:
            buffer.close()
            raise
        except (cv2.error, OverflowError, struct.error) as exc:
            buffer.close()
            raise VideoPreprocessingError(
                "No se pudo codificar la representación binaria del video."
            ) from exc
        finally:
            capture.release()

        if frame_count == 0:
            buffer.close()
            raise VideoPreprocessingError("El MP4 no contiene frames decodificables.")

        assert expected_shape is not None
        assert expected_dtype is not None
        height, width = expected_shape[:2]
        channels = expected_shape[2] if len(expected_shape) == 3 else 1
        metadata = VideoMetadata(
            frame_count=frame_count,
            height=int(height),
            width=int(width),
            channels=int(channels),
            fps=fps,
            dtype=str(expected_dtype),
        )

        try:
            metadata_bytes = json.dumps(
                {
                    "version": 1,
                    "frame_encoding": "jpeg",
                    "frame_count": metadata.frame_count,
                    "height": metadata.height,
                    "width": metadata.width,
                    "channels": metadata.channels,
                    "fps": metadata.fps,
                    "dtype": metadata.dtype,
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            if len(metadata_bytes) > _METADATA_CAPACITY:
                raise VideoPreprocessingError(
                    "La metadata del video excede la capacidad del contenedor."
                )

            end_position = buffer.tell()
            buffer.seek(len(_PAYLOAD_MAGIC))
            buffer.write(_LENGTH.pack(len(metadata_bytes)))
            buffer.write(metadata_bytes)
            buffer.seek(end_position)
            payload = buffer.getvalue()
        except VideoPreprocessingError:
            raise
        except (OverflowError, struct.error, TypeError, ValueError) as exc:
            raise VideoPreprocessingError(
                "No se pudo serializar la representación binaria del video."
            ) from exc
        finally:
            buffer.close()

        return PreprocessedVideo(payload=payload, metadata=metadata)
