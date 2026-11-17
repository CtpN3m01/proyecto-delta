"""Generate local lossless frames and OpenCV model results for browser parity.

Run from repo: python scripts/t49_reference.py. No frame is sent to a server.
The matching Playwright test transfers these files only to a local worker.
"""
import json
from pathlib import Path
import cv2
from client.preprocessing.yunet import YuNet, DEFAULT_YUNET_MODEL
from client.detection.lpd_yunet import LPDYuNet
from client.detection.yolo_counter import YOLODetector

root = Path(__file__).resolve().parents[1]
out = root / ".runtime" / "t49-reference"
out.mkdir(parents=True, exist_ok=True)
face, plate, objects = YuNet(DEFAULT_YUNET_MODEL), LPDYuNet(), YOLODetector()
reference = {}
for name in ("video1.mp4", "video2.mp4", "video3.mp4"):
    capture = cv2.VideoCapture(str(root.parent / name))
    try:
        for index in (0, 45):
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, image = capture.read()
            if not ok:
                raise RuntimeError(f"Missing frame {name}:{index}")
            frame = f"{name}.{index}.png"
            cv2.imwrite(str(out / frame), image)
            face.setInputSize([image.shape[1], image.shape[0]])
            faces = face.infer(image)
            reference[frame] = {
                "faces": [{"box": [float(v) for v in d[:4]], "score": float(d[-1])} for d in faces if d[-1] > .6],
                "plates": [{"box": [d.region.x, d.region.y, d.region.width, d.region.height], "score": d.confidence} for d in plate.detect(image)],
                "objects": [{"box": list(d.box), "score": d.confidence, "kind": d.kind} for d in objects.detect(image)],
            }
    finally:
        capture.release()
(out / "reference.json").write_text(json.dumps(reference, indent=2), encoding="utf-8")
print(f"{len(reference)} lossless local reference frames prepared in {out}")
