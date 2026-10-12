"""Diagnóstico T022 de placas a color y resolución nativa; no utiliza MPC."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from typing import Callable, Sequence

import cv2 as cv
import numpy as np

from client.detection.lpd_yunet import (
    DEFAULT_PLATE_CONFIDENCE_THRESHOLD, LPDYuNet, MODEL_REVISION, PlateDetection,
)


class PlateDemoError(RuntimeError):
    """La evaluación no puede presentarse como completa."""


@dataclass
class _FrameClock:
    """Prefiere PTS nativos; no inventa una corrección para PTS que retroceden."""

    pts_count: int = 0
    fallback_count: int = 0
    last_positive_pts: float | None = None
    last_timestamp: float | None = None

    def timestamp(self, capture, frame_index: int, fps: float) -> tuple[float, str]:
        try:
            pts = float(capture.get(cv.CAP_PROP_POS_MSEC)) / 1000.0
        except (TypeError, ValueError, OverflowError):
            pts = math.nan
        if math.isfinite(pts) and pts > 0:
            if self.last_positive_pts is not None and pts <= self.last_positive_pts:
                raise PlateDemoError(f"PTS original no monótono en el cuadro {frame_index}: {pts}s")
            self.last_positive_pts = pts
            timestamp, basis = pts, "source_pts"
            self.pts_count += 1
        elif math.isfinite(pts) and pts == 0 and frame_index == 0:
            timestamp, basis = pts, "source_pts"
            self.pts_count += 1
        else:
            if math.isfinite(pts) and pts == 0 and self.last_positive_pts is not None:
                raise PlateDemoError(f"PTS original retrocedió a cero en el cuadro {frame_index}")
            timestamp, basis = frame_index / fps, "frame_index/source_fps_fallback"
            self.fallback_count += 1
        if self.last_timestamp is not None and timestamp <= self.last_timestamp:
            raise PlateDemoError(f"La referencia temporal retrocede o se repite en el cuadro {frame_index}")
        self.last_timestamp = timestamp
        return timestamp, basis

    @property
    def basis(self) -> str:
        if self.pts_count and self.fallback_count:
            return "mixed_source_pts_and_frame_index/source_fps_fallback"
        if self.pts_count:
            return "source_pts_CAP_PROP_POS_MSEC"
        return "frame_index/source_fps_fallback"


@dataclass
class _SecondStats:
    frames_analyzed: int = 0
    frames_with_detections: int = 0
    detection_observations: int = 0
    max_plates_in_frame: int = 0
    confidence_sum: float = 0.0
    confidence_min: float = math.inf
    confidence_max: float = 0.0
    box_area_sum: float = 0.0
    max_box_area: float = 0.0
    max_box_width: float = 0.0
    max_box_height: float = 0.0

    def add(self, detections: Sequence[PlateDetection]) -> None:
        self.frames_analyzed += 1
        self.frames_with_detections += bool(detections)
        self.detection_observations += len(detections)
        self.max_plates_in_frame = max(self.max_plates_in_frame, len(detections))
        for detection in detections:
            self.confidence_sum += detection.confidence
            self.confidence_min = min(self.confidence_min, detection.confidence)
            self.confidence_max = max(self.confidence_max, detection.confidence)
            area = detection.region.width * detection.region.height
            self.box_area_sum += area
            if area > self.max_box_area:
                self.max_box_area = area
                self.max_box_width = detection.region.width
                self.max_box_height = detection.region.height

    def as_dict(self, second: int) -> dict:
        count = self.detection_observations
        return {
            "second": second,
            "frames_analyzed": self.frames_analyzed,
            "frames_with_detections": self.frames_with_detections,
            "detection_observations": count,
            "max_plates_in_frame": self.max_plates_in_frame,
            "confidence_mean": self.confidence_sum / count if count else None,
            "confidence_min": self.confidence_min if count else None,
            "confidence_max": self.confidence_max if count else None,
            "mean_box_area": self.box_area_sum / count if count else None,
            "max_box_area": self.max_box_area if count else None,
            "max_box_width": self.max_box_width if count else None,
            "max_box_height": self.max_box_height if count else None,
        }


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: dict) -> None:
    with path.open("w", encoding="utf-8") as output:
        json.dump(value, output, indent=2, ensure_ascii=False, allow_nan=False)
        output.write("\n")


def _validate_frame(frame: np.ndarray, expected_size: tuple[int, int] | None = None) -> tuple[int, int]:
    if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
        raise PlateDemoError("Se requiere un cuadro BGR uint8 de tres canales")
    size = (int(frame.shape[1]), int(frame.shape[0]))
    if min(size) <= 0:
        raise PlateDemoError("El cuadro no tiene dimensiones válidas")
    if expected_size is not None and size != expected_size:
        raise PlateDemoError("Las dimensiones cambiaron durante el video; no se redimensionará")
    return size


def _serialize_detection(detection: PlateDetection) -> dict:
    region = detection.region
    return {
        "confidence": float(detection.confidence),
        "quadrilateral": [[float(x), float(y)] for x, y in detection.quadrilateral],
        "region": {
            "region_type": region.region_type.value,
            "x": region.x,
            "y": region.y,
            "width": region.width,
            "height": region.height,
        },
    }


def annotate_frame(frame: np.ndarray, detections: Sequence[PlateDetection], *, frame_index: int, timestamp: float) -> np.ndarray:
    """Dibuja únicamente sobre una copia; conserva tamaño y canales."""
    _validate_frame(frame)
    annotated = frame.copy()
    width, height = frame.shape[1], frame.shape[0]
    for detection in detections:
        region = detection.region
        x = max(0, min(width - 1, math.floor(region.x)))
        y = max(0, min(height - 1, math.floor(region.y)))
        end_x = max(x, min(width - 1, math.ceil(region.x + region.width) - 1))
        end_y = max(y, min(height - 1, math.ceil(region.y + region.height) - 1))
        cv.rectangle(annotated, (x, y), (end_x, end_y), (0, 255, 0), 2)
        # Clipping is for drawing only; diagnostic JSON retains the original quad.
        points = np.asarray(detection.quadrilateral, dtype=np.float64)
        points[:, 0] = np.clip(points[:, 0], 0, width - 1)
        points[:, 1] = np.clip(points[:, 1], 0, height - 1)
        cv.polylines(annotated, [np.rint(points).astype(np.int32)], True, (255, 255, 0), 1)
        cv.putText(annotated, f"plate {detection.confidence:.3f}", (x, max(15, y - 5)),
                   cv.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1, cv.LINE_AA)
    cv.putText(annotated, f"frame {frame_index}  {timestamp:.2f}s  plates {len(detections)}",
               (5, 20), cv.FONT_HERSHEY_SIMPLEX, 0.43, (255, 255, 255), 1, cv.LINE_AA)
    return annotated


def _model_metadata(detector: LPDYuNet, confidence_threshold: float) -> dict:
    raw_path = getattr(detector, "model_path", None)
    model_path = Path(raw_path) if raw_path is not None else None
    return {
        "name": "LPD-YuNet",
        "file": "license_plate_detection_lpd_yunet_2023mar.onnx",
        "variant": "FP32",
        "resource_revision": MODEL_REVISION,
        "path": str(model_path.resolve()) if model_path is not None else None,
        "sha256": _hash_file(model_path) if model_path is not None and model_path.is_file() else None,
        "confidence_threshold": confidence_threshold,
        "nms_threshold": getattr(detector, "nms_threshold", 0.3),
        "source": "https://huggingface.co/opencv/license_plate_detection_yunet",
    }


def _prepare_output(source: Path, output_dir: Path, media_name: str) -> dict[str, Path]:
    names = [media_name, "detections.jsonl", "summary.json", "detections_by_second.csv"]
    if media_name.endswith(".mp4"):
        names.append("annotated.partial.mp4")
    paths = {name: output_dir / name for name in names}
    for path in paths.values():
        if path.resolve() == source.resolve():
            raise PlateDemoError("La salida no puede sobrescribir el archivo original")
        if path.exists():
            raise PlateDemoError(f"La salida ya existe; usa otro --output-dir: {path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    return paths


def _write_seconds(path: Path, seconds: dict[int, _SecondStats]) -> list[dict]:
    rows = [stats.as_dict(second) for second, stats in sorted(seconds.items())]
    fields = list(_SecondStats().as_dict(0))
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def _verify_video(path: Path, expected_size: tuple[int, int], expected_frames: int, expected_fps: float) -> dict:
    capture = cv.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise PlateDemoError("No se pudo abrir el video anotado para validarlo")
        actual_fps = float(capture.get(cv.CAP_PROP_FPS))
        if not math.isfinite(actual_fps) or abs(actual_fps - expected_fps) > max(0.01, expected_fps * 0.001):
            raise PlateDemoError("El FPS del video anotado no coincide con el original")
        count = 0
        while True:
            success, frame = capture.read()
            if not success:
                break
            _validate_frame(frame, expected_size)
            count += 1
        if count != expected_frames:
            raise PlateDemoError(f"El video anotado tiene {count} cuadros; se esperaban {expected_frames}")
        return {"decoded_frame_count": count, "width": expected_size[0], "height": expected_size[1], "fps": actual_fps}
    finally:
        capture.release()


def evaluate_video(source: str | Path, output_dir: str | Path, detector: LPDYuNet, *, confidence_threshold: float = DEFAULT_PLATE_CONFIDENCE_THRESHOLD,
                   progress: Callable[[str], None] | None = print) -> dict:
    """Evalúa todos los cuadros decodificados en orden, sin límites del MVP MPC."""
    source, output_dir = Path(source), Path(output_dir)
    if not source.is_file():
        raise PlateDemoError(f"No existe el video: {source}")
    paths = _prepare_output(source, output_dir, "annotated.mp4")
    started = time.perf_counter()
    source_hash = _hash_file(source)
    capture = cv.VideoCapture(str(source))
    writer = None
    seconds: dict[int, _SecondStats] = {}
    frame_index = 0
    inference_seconds = 0.0
    clock = _FrameClock()
    summary = {
        "complete": False,
        "source": str(source.resolve()),
        "source_sha256": source_hash,
        "analysis_scope": "all decoded frames; native BGR; no crop, resize or sampling",
        "frame_index_semantics": "zero-based individual index in this full-video sequence; not an MPC batch or sampled index",
        "opencv_version": cv.__version__,
        "numpy_version": np.__version__,
        "model": _model_metadata(detector, confidence_threshold),
        "audio_preserved": False,
        "codec": "mp4v",
        "output_timing": "CFR at source average FPS; original VFR timing is not preserved by VideoWriter",
        "note": "Detection observations are not unique vehicles. Encoding preserves dimensions, not lossless pixel values.",
    }
    try:
        if not capture.isOpened():
            raise PlateDemoError("No se pudo abrir el video original")
        fps = float(capture.get(cv.CAP_PROP_FPS))
        reported_count = int(capture.get(cv.CAP_PROP_FRAME_COUNT))
        if not math.isfinite(fps) or fps <= 0:
            raise PlateDemoError("El video no informa un FPS válido")
        summary.update(source_fps=fps, reported_frame_count=reported_count)
        expected_size = None
        with paths["detections.jsonl"].open("w", encoding="utf-8") as records:
            while True:
                success, frame = capture.read()
                if not success:
                    break
                size = _validate_frame(frame, expected_size)
                if expected_size is None:
                    expected_size = size
                    if size[0] % 2 or size[1] % 2:
                        raise PlateDemoError("MP4V requiere dimensiones pares para conservar la imagen nativa sin recortarla")
                    summary.update(width=size[0], height=size[1], channels=3)
                    writer = cv.VideoWriter(str(paths["annotated.partial.mp4"]), cv.VideoWriter_fourcc(*"mp4v"), fps, size)
                    if not writer.isOpened():
                        raise PlateDemoError("No se pudo crear el video anotado")
                timestamp, timestamp_source = clock.timestamp(capture, frame_index, fps)
                inference_started = time.perf_counter()
                try:
                    detections = tuple(detector.detect(frame))
                except Exception as exc:
                    record = {"frame_index": frame_index, "timestamp_seconds": timestamp,
                              "timestamp_source": timestamp_source, "status": "failed", "error": str(exc)}
                    records.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                    raise PlateDemoError(f"Fallo técnico del detector en el cuadro {frame_index}: {exc}") from exc
                inference_seconds += time.perf_counter() - inference_started
                record = {"frame_index": frame_index, "timestamp_seconds": timestamp,
                          "timestamp_source": timestamp_source, "status": "success",
                          "detections": [_serialize_detection(detection) for detection in detections]}
                records.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                seconds.setdefault(math.floor(timestamp), _SecondStats()).add(detections)
                writer.write(annotate_frame(frame, detections, frame_index=frame_index, timestamp=timestamp))
                frame_index += 1
                if progress is not None and (frame_index == 1 or frame_index % 100 == 0):
                    progress(f"T022: {frame_index}/{reported_count or '?'} cuadros, {timestamp:.2f}s de video, "
                             f"{time.perf_counter() - started:.1f}s de evaluación")
        if frame_index == 0:
            raise PlateDemoError("No se pudo decodificar ningún cuadro")
        if reported_count > 0 and frame_index != reported_count:
            raise PlateDemoError(f"Decodificación incompleta: {frame_index} cuadros frente a {reported_count} declarados")
        writer.release()
        writer = None
        summary["output_validation"] = _verify_video(paths["annotated.partial.mp4"], expected_size, frame_index, fps)
        if _hash_file(source) != source_hash:
            raise PlateDemoError("El archivo original cambió durante la evaluación")
        paths["annotated.partial.mp4"].rename(paths["annotated.mp4"])
        summary.update(complete=True, frame_count=frame_index, duration_seconds=frame_index / fps,
                       output_cfr_duration_seconds=frame_index / fps,
                       annotated_video=str(paths["annotated.mp4"].resolve()))
    except Exception as exc:
        summary["error"] = str(exc)
        raise
    finally:
        capture.release()
        if writer is not None:
            writer.release()
        rows = _write_seconds(paths["detections_by_second.csv"], seconds)
        summary.update(analyzed_frame_count=frame_index, inference_seconds=inference_seconds,
                       timestamp_basis=clock.basis, timestamp_fallback_count=clock.fallback_count,
                       source_last_frame_timestamp_seconds=clock.last_timestamp,
                       elapsed_seconds=time.perf_counter() - started, detections_by_second=rows,
                       total_detection_observations=sum(row["detection_observations"] for row in rows),
                       frames_with_detections=sum(row["frames_with_detections"] for row in rows))
        _write_json(paths["summary.json"], summary)
    return summary


def evaluate_image(source: str | Path, output_dir: str | Path, detector: LPDYuNet, *, confidence_threshold: float = DEFAULT_PLATE_CONFIDENCE_THRESHOLD) -> dict:
    source, output_dir = Path(source), Path(output_dir)
    if not source.is_file():
        raise PlateDemoError(f"No existe la imagen: {source}")
    paths = _prepare_output(source, output_dir, "annotated.png")
    started = time.perf_counter()
    frame = cv.imread(str(source), cv.IMREAD_COLOR)
    width, height = _validate_frame(frame)
    try:
        detections = tuple(detector.detect(frame))
    except Exception as exc:
        _write_json(paths["summary.json"], {"complete": False, "error": str(exc), "frame_index": 0})
        raise PlateDemoError(f"Fallo técnico del detector: {exc}") from exc
    annotated = annotate_frame(frame, detections, frame_index=0, timestamp=0.0)
    if not cv.imwrite(str(paths["annotated.png"]), annotated):
        raise PlateDemoError("No se pudo escribir la imagen anotada")
    record = {"frame_index": 0, "timestamp_seconds": 0.0, "status": "success",
              "detections": [_serialize_detection(detection) for detection in detections]}
    with paths["detections.jsonl"].open("w", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
    stats = _SecondStats()
    stats.add(detections)
    rows = _write_seconds(paths["detections_by_second.csv"], {0: stats})
    summary = {"complete": True, "source": str(source.resolve()), "source_sha256": _hash_file(source),
               "width": width, "height": height, "channels": 3, "frame_count": 1,
               "model": _model_metadata(detector, confidence_threshold), "opencv_version": cv.__version__,
               "total_detection_observations": len(detections), "detections_by_second": rows,
               "elapsed_seconds": time.perf_counter() - started,
               "annotated_image": str(paths["annotated.png"].resolve())}
    _write_json(paths["summary.json"], summary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T022: placas con LPD-YuNet, a color y resolución original, sin MPC")
    parser.add_argument("input", type=Path, help="Imagen o video original")
    parser.add_argument("--output-dir", type=Path, default=Path("results/T022"), help="Directorio de diagnóstico (no se sobrescriben salidas)")
    parser.add_argument("--confidence-threshold", type=float, default=DEFAULT_PLATE_CONFIDENCE_THRESHOLD, help="Umbral LPD-YuNet, predeterminado 0.6")
    parser.add_argument("--model-path", type=Path, help="Archivo ONNX FP32; por defecto se utiliza el recurso versionado")
    parser.add_argument("--media-type", choices=("image", "video"), help="Forzar el tipo; por defecto se deduce por extensión")
    args = parser.parse_args(argv)
    if not math.isfinite(args.confidence_threshold) or not 0 < args.confidence_threshold <= 1:
        parser.error("--confidence-threshold debe ser mayor que 0 y menor o igual a 1")
    media_type = args.media_type or ("image" if args.input.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"} else "video")
    try:
        detector = LPDYuNet(model_path=args.model_path, confidence_threshold=args.confidence_threshold)
        if media_type == "image":
            summary = evaluate_image(args.input, args.output_dir, detector, confidence_threshold=args.confidence_threshold)
        else:
            summary = evaluate_video(args.input, args.output_dir, detector, confidence_threshold=args.confidence_threshold,
                                     progress=lambda message: print(message, flush=True))
    except Exception as exc:
        print(f"[ERROR] T022 incompleta: {exc}", file=sys.stderr)
        return 1
    print(f"[OK] T022: {summary['frame_count']} cuadros nativos {summary['width']}x{summary['height']}, "
          f"{summary['total_detection_observations']} observaciones de placas")
    print(f"Resultados: {args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
