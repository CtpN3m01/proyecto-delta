"""Inspect downloaded results, including decoded pixels after lossy encoding.

The browser already checks every uncompressed MPC pixel exactly. These checks
are independent codec/container checks on the files downloaded from the catalog.
"""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("--available", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
evidence = root / ".runtime/t49-evidence"
reference = json.loads((root / ".runtime/t49-reference/reference.json").read_text(encoding="utf-8"))
reports = []
for name, expected_count, expected_fps, size in [
    ("video1.mp4", 596, 30., (368, 368)),
    ("video2.mp4", 2438, 29.671399594320487, (478, 850)),
    ("video3.mp4", 90, 30., (478, 850)),
]:
    target = evidence / f"{name}.anonymous.mp4"
    if args.available and not target.is_file():
        continue
    capture = cv2.VideoCapture(str(target))
    assert capture.isOpened(), target
    fps = capture.get(cv2.CAP_PROP_FPS)
    assert abs(fps - expected_fps) < 1e-4, (name, fps)
    count, maximum_chroma_difference, samples = 0, 0, []
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            assert frame.shape[:2] == (size[1], size[0])
            maximum_chroma_difference = max(maximum_chroma_difference, int(np.ptp(frame.astype(np.int16), axis=2).max()))
            if count in (0, 45):
                source = cv2.imread(str(root / f".runtime/t49-reference/{name}.{count}.png"))
                original = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                mask = np.zeros(gray.shape, np.uint8)
                black_means = []
                detections = reference[f"{name}.{count}.png"]
                for detection in detections["faces"] + detections["plates"]:
                    x, y, width, height = detection["box"]
                    left, top = max(0, int(np.floor(x))), max(0, int(np.floor(y)))
                    right, bottom = min(size[0], int(np.ceil(x + width))), min(size[1], int(np.ceil(y + height)))
                    mask[top:bottom, left:right] = 1
                    interior = gray[top + 6:bottom - 6, left + 6:right - 6]
                    if interior.size:
                        black_means.append(float(interior.mean()))
                        assert interior.mean() < 8, (name, count, "mask is not black", interior.mean())
                expanded = cv2.dilate(mask, np.ones((17, 17), np.uint8))
                outside = np.abs(gray.astype(np.int16) - original.astype(np.int16))[expanded == 0]
                mean_error = float(outside.mean())
                assert mean_error < 12, (name, count, "outside image changed", mean_error)
                samples.append({"frame": count, "black_region_means": black_means, "outside_mean_absolute_error": mean_error})
            count += 1
    finally:
        capture.release()
    assert count == expected_count, (name, count, expected_count)
    assert maximum_chroma_difference <= 2, (name, maximum_chroma_difference)
    reports.append({"source": name, "decoded_frames": count, "fps": fps, "width": size[0], "height": size[1], "duration_seconds": count / fps, "maximum_chroma_difference": maximum_chroma_difference, "samples": samples})
assert reports, "No downloaded results to inspect"
(evidence / "decoded-validation.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
print(json.dumps(reports, indent=2))
