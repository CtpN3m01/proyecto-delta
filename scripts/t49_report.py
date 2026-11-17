"""Collect small, reviewable acceptance evidence; never copy images or shares."""
import argparse
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--available", action="store_true", help="Report completed videos and explicitly list pending acceptance")
args = parser.parse_args()
evidence = root / ".runtime/t49-evidence"
videos = []
pending = []
for name, frames in (("video1.mp4", 596), ("video2.mp4", 2438), ("video3.mp4", 90)):
    summary_path = evidence / f"{name}.summary.json"
    if args.available and not summary_path.is_file():
        pending.append(name)
        continue
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    target = evidence / f"{name}.anonymous.mp4"
    assert summary["result"]["metadata"]["frame_count"] == frames
    assert summary["result"]["counts"]["frames_analyzed"] == frames
    assert target.is_file()
    metadata = summary["result"]["metadata"]
    pixel_count = metadata["width"] * metadata["height"] * frames
    chunks = (pixel_count + 262143) // 262144
    videos.append({
        "source": name, "source_sha256": hashlib.sha256((root.parent / name).read_bytes()).hexdigest(),
        "mpc_input_pixels": pixel_count, "mpc_chunks": chunks,
        "external_io_body_bytes_calculated_before_transport_compression": chunks * 262144 * 96 + 132,
        "frames": frames, "metadata": summary["result"]["metadata"],
        "counts": summary["result"]["counts"], "face_observations": summary["result"]["faceCount"],
        "plate_observations": summary["result"]["plateCount"], "timings": summary["result"]["timings"],
        "total_seconds_including_wait": summary["seconds"], "ticket": summary["ticket"],
        "result_id": summary["resultId"], "result_bytes": target.stat().st_size,
        "result_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "http_posts": summary["http"], "user_agent": summary["browser"],
    })
report = {"base_commit": "bcebf198c53db39e91e5ba0ea54f639d67529c58", "acceptance_complete": not pending, "pending_videos": pending, "videos": videos}
report["models"] = json.loads((root / "frontend/public/models/manifest.json").read_text(encoding="utf-8"))
report["circuit_source_sha256"] = hashlib.sha256((root / "mpc/Programs/Source/delta_video_anonymize.mpc").read_bytes()).hexdigest()
for filename, key in (("parity.json", "model_parity"), ("persistence.json", "storage_restart"), ("transport.json", "private_transport"), ("decoded-validation.json", "decoded_results"), ("media-validation.json", "media_tracks")):
    report[key] = json.loads((evidence / filename).read_text(encoding="utf-8"))
(root / "docs/T49-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("Wrote docs/T49-validation.json (metadata only)")
