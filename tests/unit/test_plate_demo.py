"""T022: flujo diagnóstico nativo y distinción entre vacío y fallo."""

import csv
import json
import math
from pathlib import Path

import cv2 as cv
import numpy as np
import pytest

from client import plate_demo
from client.detection.lpd_yunet import PlateDetection
from client.regions import DetectedRegion, RegionType


def _plate(x=2.0, y=3.0, width=5.0, height=4.0, confidence=0.9):
    return PlateDetection(
        ((x, y), (x + width, y), (x + width, y + height), (x, y + height)),
        confidence,
        DetectedRegion(RegionType.PLATE, x, y, width, height),
    )


class _Detector:
    model_path = None
    nms_threshold = 0.3

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.inputs = []

    def detect(self, image):
        self.inputs.append(image.copy())
        result = next(self.outputs)
        if isinstance(result, Exception):
            raise result
        return result


class _Capture:
    def __init__(self, frames, fps, reported_count=None, timestamps=None):
        self.frames = list(frames)
        self.fps = fps
        self.reported_count = len(frames) if reported_count is None else reported_count
        self.index = 0
        self.released = False
        self.timestamps = timestamps

    def isOpened(self):
        return True

    def read(self):
        if self.index == len(self.frames):
            return False, None
        frame = self.frames[self.index]
        self.index += 1
        return True, frame.copy()

    def get(self, prop):
        if prop == cv.CAP_PROP_POS_MSEC:
            return self.timestamps[self.index - 1] * 1000 if self.timestamps is not None else math.nan
        return self.fps if prop == cv.CAP_PROP_FPS else self.reported_count

    def release(self):
        self.released = True


class _Writer:
    def __init__(self, path, fps, size):
        self.path = Path(path)
        self.path.write_bytes(b"fake-video")
        self.fps, self.size = fps, size
        self.frames = []
        self.released = False

    def isOpened(self):
        return True

    def write(self, frame):
        self.frames.append(frame.copy())

    def release(self):
        self.released = True


def _video_fixture(monkeypatch, tmp_path, frames, *, fps=2.5, reported_count=None, timestamps=None):
    source = tmp_path / "input.mp4"
    source.write_bytes(b"original-video")
    captures, writers = [], []

    def capture(path):
        if Path(path) == source:
            result = _Capture(frames, fps, reported_count, timestamps)
        else:
            result = _Capture(writers[0].frames, writers[0].fps)
        captures.append(result)
        return result

    def writer(path, fourcc, output_fps, size):
        result = _Writer(path, output_fps, size)
        writers.append(result)
        return result

    monkeypatch.setattr(plate_demo.cv, "VideoCapture", capture)
    monkeypatch.setattr(plate_demo.cv, "VideoWriter", writer)
    monkeypatch.setattr(plate_demo.cv, "resize", lambda *args, **kwargs: pytest.fail("No debe redimensionar"))
    return source, tmp_path / "out", captures, writers


def test_full_video_native_color_order_empty_and_multiple(monkeypatch, tmp_path):
    frames = [np.full((40, 60, 3), (index, index + 30, index + 60), np.uint8) for index in range(6)]
    source, output, captures, writers = _video_fixture(monkeypatch, tmp_path, frames)
    detector = _Detector([(_plate(),), (), (_plate(), _plate(20, confidence=0.85)), (), (), (_plate(),)])
    progress = []
    summary = plate_demo.evaluate_video(source, output, detector, progress=progress.append)

    assert summary["complete"] is True
    assert summary["frame_count"] == 6
    assert summary["analyzed_frame_count"] == 6
    assert (summary["width"], summary["height"], summary["channels"]) == (60, 40, 3)
    assert summary["source_fps"] == 2.5
    assert summary["timestamp_basis"] == "frame_index/source_fps_fallback"
    assert summary["timestamp_fallback_count"] == 6
    assert summary["duration_seconds"] == 2.4
    assert summary["total_detection_observations"] == 4
    assert summary["frames_with_detections"] == 3
    assert summary["audio_preserved"] is False
    assert summary["output_validation"]["decoded_frame_count"] == 6
    assert source.read_bytes() == b"original-video"
    assert writers[0].size == (60, 40)
    assert writers[0].fps == 2.5
    assert len(writers[0].frames) == 6
    assert all(capture.released for capture in captures)
    assert writers[0].released
    assert progress
    for original, detector_input in zip(frames, detector.inputs):
        np.testing.assert_array_equal(original, detector_input)
    assert (output / "annotated.mp4").is_file()
    assert not (output / "annotated.partial.mp4").exists()

    records = [json.loads(line) for line in (output / "detections.jsonl").read_text().splitlines()]
    assert [record["frame_index"] for record in records] == list(range(6))
    assert [record["timestamp_seconds"] for record in records] == [index / 2.5 for index in range(6)]
    assert all(record["status"] == "success" for record in records)
    assert records[1]["detections"] == []
    assert len(records[2]["detections"]) == 2
    assert records[0]["detections"][0]["region"]["region_type"] == "plate"
    with (output / "detections_by_second.csv").open(newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert [int(row["frames_analyzed"]) for row in rows] == [3, 2, 1]
    assert [int(row["detection_observations"]) for row in rows] == [3, 0, 1]
    assert rows[1]["confidence_mean"] == ""
    assert int(rows[0]["max_plates_in_frame"]) == 2
    saved = json.loads((output / "summary.json").read_text())
    assert saved["complete"] is True


def test_annotation_does_not_modify_original():
    frame = np.full((40, 60, 3), (7, 17, 27), np.uint8)
    untouched = frame.copy()
    output = plate_demo.annotate_frame(frame, (_plate(),), frame_index=5, timestamp=1.5)
    np.testing.assert_array_equal(frame, untouched)
    assert output is not frame
    assert output.shape == frame.shape
    assert output.dtype == frame.dtype
    assert not np.array_equal(output, frame)


def test_native_vfr_pts_define_seconds_not_average_fps(monkeypatch, tmp_path):
    frames = [np.zeros((40, 60, 3), np.uint8) for _ in range(4)]
    timestamps = [0.0, 0.2, 1.1, 1.3]
    source, output, _, writers = _video_fixture(monkeypatch, tmp_path, frames, fps=10, timestamps=timestamps)
    summary = plate_demo.evaluate_video(source, output, _Detector([(), (), (), ()]), progress=None)
    records = [json.loads(line) for line in (output / "detections.jsonl").read_text().splitlines()]
    assert [record["timestamp_seconds"] for record in records] == timestamps
    assert all(record["timestamp_source"] == "source_pts" for record in records)
    assert summary["timestamp_basis"] == "source_pts_CAP_PROP_POS_MSEC"
    assert summary["timestamp_fallback_count"] == 0
    assert [row["frames_analyzed"] for row in summary["detections_by_second"]] == [2, 2]
    assert summary["source_last_frame_timestamp_seconds"] == 1.3
    assert summary["output_cfr_duration_seconds"] == 0.4
    assert writers[0].fps == 10


def test_always_zero_pts_uses_explicit_fallback(monkeypatch, tmp_path):
    frames = [np.zeros((40, 60, 3), np.uint8) for _ in range(3)]
    source, output, _, _ = _video_fixture(monkeypatch, tmp_path, frames, fps=2, timestamps=[0.0, 0.0, 0.0])
    summary = plate_demo.evaluate_video(source, output, _Detector([(), (), ()]), progress=None)
    records = [json.loads(line) for line in (output / "detections.jsonl").read_text().splitlines()]
    assert [record["timestamp_seconds"] for record in records] == [0.0, 0.5, 1.0]
    assert summary["timestamp_fallback_count"] == 2
    assert summary["timestamp_basis"] == "mixed_source_pts_and_frame_index/source_fps_fallback"
    assert records[1]["timestamp_source"] == "frame_index/source_fps_fallback"


@pytest.mark.parametrize("timestamps", [[0.0, 0.5, 0.4], [0.0, 0.5, 0.0], [0.0, 0.5, 0.5]])
def test_regressing_or_repeated_positive_pts_is_explicit_failure(monkeypatch, tmp_path, timestamps):
    frames = [np.zeros((40, 60, 3), np.uint8) for _ in range(3)]
    source, output, _, _ = _video_fixture(monkeypatch, tmp_path, frames, fps=10, timestamps=timestamps)
    with pytest.raises(plate_demo.PlateDemoError, match="PTS original"):
        plate_demo.evaluate_video(source, output, _Detector([(), (), ()]), progress=None)
    summary = json.loads((output / "summary.json").read_text())
    assert summary["complete"] is False
    assert "PTS original" in summary["error"]
    assert not (output / "annotated.mp4").exists()


def test_detector_failure_never_becomes_empty_success(monkeypatch, tmp_path):
    frames = [np.zeros((40, 60, 3), np.uint8) for _ in range(3)]
    source, output, captures, writers = _video_fixture(monkeypatch, tmp_path, frames)
    detector = _Detector([(), RuntimeError("fallo ONNX"), ()])
    with pytest.raises(plate_demo.PlateDemoError, match="cuadro 1"):
        plate_demo.evaluate_video(source, output, detector, progress=None)
    records = [json.loads(line) for line in (output / "detections.jsonl").read_text().splitlines()]
    assert records[0]["status"] == "success"
    assert records[0]["detections"] == []
    assert records[1]["status"] == "failed"
    assert records[1]["error"] == "fallo ONNX"
    assert "detections" not in records[1]
    summary = json.loads((output / "summary.json").read_text())
    assert summary["complete"] is False
    assert summary["analyzed_frame_count"] == 1
    assert "fallo ONNX" in summary["error"]
    assert not (output / "annotated.mp4").exists()
    assert (output / "annotated.partial.mp4").exists()
    assert captures[0].released
    assert writers[0].released


def test_incomplete_decode_is_not_complete(monkeypatch, tmp_path):
    frames = [np.zeros((40, 60, 3), np.uint8)]
    source, output, _, _ = _video_fixture(monkeypatch, tmp_path, frames, reported_count=2)
    with pytest.raises(plate_demo.PlateDemoError, match="Decodificación incompleta"):
        plate_demo.evaluate_video(source, output, _Detector([()]), progress=None)
    assert json.loads((output / "summary.json").read_text())["complete"] is False
    assert not (output / "annotated.mp4").exists()


def test_unknown_reported_count_still_analyzes_all_frames(monkeypatch, tmp_path):
    frames = [np.zeros((40, 60, 3), np.uint8) for _ in range(3)]
    source, output, _, _ = _video_fixture(monkeypatch, tmp_path, frames, reported_count=0)
    summary = plate_demo.evaluate_video(source, output, _Detector([(), (), ()]), progress=None)
    assert summary["frame_count"] == 3
    assert summary["complete"]


@pytest.mark.parametrize("size", [(61, 40), (60, 41)])
def test_odd_dimensions_refused_instead_of_silent_crop(monkeypatch, tmp_path, size):
    frames = [np.zeros((size[1], size[0], 3), np.uint8)]
    source, output, _, writers = _video_fixture(monkeypatch, tmp_path, frames)
    with pytest.raises(plate_demo.PlateDemoError, match="dimensiones pares"):
        plate_demo.evaluate_video(source, output, _Detector([()]), progress=None)
    assert not writers
    assert json.loads((output / "summary.json").read_text())["complete"] is False


def test_dimensions_must_stay_native(monkeypatch, tmp_path):
    frames = [np.zeros((40, 60, 3), np.uint8), np.zeros((42, 60, 3), np.uint8)]
    source, output, _, _ = _video_fixture(monkeypatch, tmp_path, frames)
    with pytest.raises(plate_demo.PlateDemoError, match="dimensiones cambiaron"):
        plate_demo.evaluate_video(source, output, _Detector([(), ()]), progress=None)


@pytest.mark.parametrize("fps", [0, -1, float("nan"), float("inf")])
def test_invalid_fps_is_technical_failure(monkeypatch, tmp_path, fps):
    source, output, _, writers = _video_fixture(monkeypatch, tmp_path, [np.zeros((40, 60, 3), np.uint8)], fps=fps)
    with pytest.raises(plate_demo.PlateDemoError, match="FPS válido"):
        plate_demo.evaluate_video(source, output, _Detector([()]), progress=None)
    assert not writers


def test_existing_outputs_are_not_overwritten(tmp_path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"source")
    output = tmp_path / "out"
    output.mkdir()
    existing = output / "summary.json"
    existing.write_text("keep")
    with pytest.raises(plate_demo.PlateDemoError, match="ya existe"):
        plate_demo.evaluate_video(source, output, _Detector([]), progress=None)
    assert existing.read_text() == "keep"


def test_source_can_never_be_the_output(tmp_path):
    source = tmp_path / "annotated.mp4"
    source.write_bytes(b"source")
    with pytest.raises(plate_demo.PlateDemoError, match="original"):
        plate_demo.evaluate_video(source, tmp_path, _Detector([]), progress=None)
    assert source.read_bytes() == b"source"


def test_image_native_confidence_and_multiple(tmp_path, monkeypatch):
    source = tmp_path / "input.png"
    source.write_bytes(b"source-image")
    frame = np.full((31, 57, 3), (10, 30, 90), np.uint8)
    monkeypatch.setattr(plate_demo.cv, "imread", lambda path, mode: frame)
    saved = []

    def imwrite(path, annotated):
        saved.append(annotated.copy())
        Path(path).write_bytes(b"png")
        return True

    monkeypatch.setattr(plate_demo.cv, "imwrite", imwrite)
    detector = _Detector([(_plate(confidence=0.88), _plate(20, confidence=0.91))])
    output = tmp_path / "out"
    summary = plate_demo.evaluate_image(source, output, detector, confidence_threshold=0.85)
    assert summary["complete"]
    assert summary["model"]["confidence_threshold"] == 0.85
    assert (summary["width"], summary["height"]) == (57, 31)
    assert summary["total_detection_observations"] == 2
    assert saved[0].shape == frame.shape
    np.testing.assert_array_equal(detector.inputs[0], frame)
    assert source.read_bytes() == b"source-image"
    assert (output / "annotated.png").exists()


def test_image_failure_is_not_success(tmp_path, monkeypatch):
    source = tmp_path / "input.png"
    source.write_bytes(b"source-image")
    monkeypatch.setattr(plate_demo.cv, "imread", lambda path, mode: np.zeros((40, 60, 3), np.uint8))
    output = tmp_path / "out"
    with pytest.raises(plate_demo.PlateDemoError, match="Fallo técnico"):
        plate_demo.evaluate_image(source, output, _Detector([RuntimeError("no inferencia")]))
    assert not (output / "annotated.png").exists()
    assert not json.loads((output / "summary.json").read_text())["complete"]


@pytest.mark.parametrize("flags, threshold", [([], 0.6), (["--confidence-threshold", "0.72"], 0.72)])
def test_cli_threshold_argument(monkeypatch, tmp_path, flags, threshold):
    constructed = []
    calls = []

    def detector(**kwargs):
        constructed.append(kwargs)
        return object()

    def image(source, output, model, **kwargs):
        calls.append((source, output, kwargs))
        return {"frame_count": 1, "width": 478, "height": 850, "total_detection_observations": 2}

    monkeypatch.setattr(plate_demo, "LPDYuNet", detector)
    monkeypatch.setattr(plate_demo, "evaluate_image", image)
    assert plate_demo.main(["photo.png", *flags, "--output-dir", str(tmp_path)]) == 0
    assert constructed == [{"model_path": None, "confidence_threshold": threshold}]
    assert calls[0][2]["confidence_threshold"] == threshold


@pytest.mark.parametrize("threshold", ["0", "-1", "1.1", "nan", "inf"])
def test_cli_rejects_invalid_threshold(threshold):
    with pytest.raises(SystemExit) as exc:
        plate_demo.main(["photo.png", "--confidence-threshold", threshold])
    assert exc.value.code == 2


def test_cli_failure_returns_nonzero(monkeypatch, capsys):
    def detector(**kwargs):
        raise RuntimeError("modelo ausente")

    monkeypatch.setattr(plate_demo, "LPDYuNet", detector)
    assert plate_demo.main(["video.mp4"]) == 1
    assert "incompleta" in capsys.readouterr().err


def test_real_codec_preserves_native_dimensions_fps_and_count(tmp_path):
    source = tmp_path / "real.mp4"
    fps, width, height, count = 7.5, 64, 48, 4
    writer = cv.VideoWriter(str(source), cv.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    assert writer.isOpened()
    for index in range(count):
        writer.write(np.full((height, width, 3), (index * 30, 100, 200), np.uint8))
    writer.release()
    summary = plate_demo.evaluate_video(source, tmp_path / "real-output", _Detector([(), (_plate(),), (), ()]), progress=None)
    assert summary["complete"]
    assert summary["output_validation"] == {"decoded_frame_count": count, "width": width, "height": height, "fps": fps}
