"""HTTP contract for starting the trusted client from the local web UI."""

import time
from pathlib import Path
from collections.abc import Callable
from uuid import UUID

from fastapi.testclient import TestClient

from client.local_api import create_app


def _client() -> TestClient:
    async def process_runner(
        video_path: Path,
        output_root: Path,
        log_path: Path,
        update_stage: Callable[[int], None],
    ) -> Path:
        assert video_path.read_bytes() == b"local video bytes"
        update_stage(4)
        destination = output_root / "video-id" / "reconstructed.mp4"
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"anonymized video")
        return destination

    return TestClient(
        create_app(
            allowed_origins=("http://127.0.0.1:5173",),
            process_runner=process_runner,
        )
    )


def test_local_upload_runs_client_and_serves_anonymized_result(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DELTA_OUTPUT_DIR", str(tmp_path / "output"))
    with _client() as client:
        response = client.post(
            "/api/v1/jobs",
            headers={"Origin": "http://127.0.0.1:5173"},
            files={"video": ("sample.mp4", b"local video bytes", "video/mp4")},
        )
        assert response.status_code == 202
        job_id = response.json()["id"]
        UUID(job_id)

        for _ in range(100):
            status = client.get(
                f"/api/v1/jobs/{job_id}",
                headers={"Origin": "http://127.0.0.1:5173"},
            )
            if status.json()["status"] != "PROCESSING":
                break
            time.sleep(0.01)

        assert status.status_code == 200
        assert status.json()["status"] == "COMPLETED"
        assert status.json()["stage"] == 4
        result = client.get(
            status.json()["result_url"],
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        assert result.status_code == 200
        assert result.content == b"anonymized video"
        assert result.headers["content-disposition"].endswith(
            'filename="video-anonimizado.mp4"'
        )


def test_local_client_rejects_untrusted_origin_and_non_mp4() -> None:
    with _client() as client:
        untrusted = client.post(
            "/api/v1/jobs",
            headers={"Origin": "https://untrusted.example"},
            files={"video": ("sample.mp4", b"data", "video/mp4")},
        )
        assert untrusted.status_code == 403

        unsupported = client.post(
            "/api/v1/jobs",
            headers={"Origin": "http://127.0.0.1:5173"},
            files={"video": ("sample.mov", b"data", "video/quicktime")},
        )
        assert unsupported.status_code == 415
