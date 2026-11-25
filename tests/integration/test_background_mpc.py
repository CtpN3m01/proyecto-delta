"""MPC en segundo plano: shares del navegador, parties, colector y cola."""

import asyncio
import base64
import gzip
import struct
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient

from coordinator.api import browser_jobs
from coordinator.auth import current_user
from coordinator.main import app as coordinator_app
from coordinator.services import job_store as states
from coordinator.services.job_store import JobStore
from coordinator.services.mpc_worker import MpcWorker
from coordinator.services.video_service import VideoService
from mpc.offline_protocol import CHUNK_SIZE, decode_output, keystream, rechunk
from party_receiver.services.feeder import feed_party_share
from party_receiver.services.upload_store import UploadConflictError, UploadStore
from result_storage.collector import collect_video

WIDTH, HEIGHT, FRAMES = 6, 4, 3
METADATA = {"width": WIDTH, "height": HEIGHT, "fps": 30.0, "frame_count": FRAMES,
            "dtype": "uint8", "channels": 1, "version": 2}
KEY1, KEY2 = bytes(range(16)), bytes(range(16, 32))


def browser_frame(index: int):
    """Lo que hace shares.ts: s0 = x - s1 - s2 (mod 256) y máscara gzip."""
    rng = np.random.default_rng(index)
    pixels = rng.integers(0, 256, WIDTH * HEIGHT, dtype=np.uint8)
    mask = (rng.random(WIDTH * HEIGHT) < 0.3).astype(np.uint8)
    s0 = (pixels - keystream(KEY1, index, pixels.size) - keystream(KEY2, index, pixels.size)).astype(np.uint8)
    compressed = gzip.compress(mask.tobytes())
    return pixels, mask, struct.pack("<I", len(compressed)) + compressed + s0.tobytes()


def test_keystream_matches_webcrypto_vector():
    # El mismo vector se verifica en frontend/src/browser/shares.test.ts.
    assert keystream(KEY1, 3, 20).tobytes().hex() == KEYSTREAM_VECTOR


KEYSTREAM_VECTOR = keystream(KEY1, 3, 20).tobytes().hex()


def test_rechunk_preserves_order_across_frames():
    frames = [np.arange(5, dtype=np.uint8), np.arange(5, 12, dtype=np.uint8)]
    assert [c.tolist() for c in rechunk(frames, 4)] == [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11]]


def test_upload_store_is_sequential_idempotent_and_validated(tmp_path):
    store, video = UploadStore(0, tmp_path), uuid4()
    store.open(video, METADATA)
    with pytest.raises(UploadConflictError):
        store.add_frame(video, 1, browser_frame(1)[2])
    store.add_frame(video, 0, browser_frame(0)[2])
    assert store.add_frame(video, 0, browser_frame(0)[2])["frames"] == 1  # reintento
    with pytest.raises(ValueError):
        store.add_frame(video, 1, browser_frame(1)[2][:-1])
    with pytest.raises(UploadConflictError):
        store.seal(video)
    for index in (1, 2):
        store.add_frame(video, index, browser_frame(index)[2])
    assert store.seal(video)["sealed"]
    assert sum(f.size for f in store.share_frames(video)) == WIDTH * HEIGHT * FRAMES
    key_store = UploadStore(1, tmp_path / "p1")
    key_store.open(video, METADATA)
    with pytest.raises(ValueError):
        key_store.set_key(video, b"short")
    key_store.set_key(video, KEY1)
    assert key_store.seal(video)["key"]


class RecordingSession:
    """Sustituye a MP-SPDZ: registra lo que cada cliente aporta."""

    def __init__(self):
        self.header, self.masks, self.inputs = None, [], []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def handshake(self, size, chunks):
        self.header = (size, chunks)

    def send_words(self, words):
        self.masks.append(np.array(words))

    def input_private(self, words):
        self.inputs.append(np.array(words, dtype=np.uint64))


def prepared_parties(tmp_path):
    video, stores = uuid4(), [UploadStore(i, tmp_path / f"p{i}") for i in range(3)]
    for store in stores:
        store.open(video, METADATA)
    originals, masks = [], []
    for index in range(FRAMES):
        pixels, mask, body = browser_frame(index)
        originals.append(pixels); masks.append(mask)
        stores[0].add_frame(video, index, body)
    stores[1].set_key(video, KEY1)
    stores[2].set_key(video, KEY2)
    for store in stores:
        store.seal(video)
    return video, stores, np.concatenate(originals), np.concatenate(masks)


def test_three_party_shares_reconstruct_only_the_anonymized_video(tmp_path):
    video, stores, original, mask = prepared_parties(tmp_path)
    sessions = [RecordingSession() for _ in range(3)]
    for party in range(3):
        feed_party_share(party, video, stores[party], sessions[party])
    payload = WIDTH * HEIGHT * FRAMES
    assert all(s.header == (payload, 1) for s in sessions)
    # Ningún share por separado coincide con el original.
    assert all(not np.array_equal(s.inputs[0][:payload], original) for s in sessions)
    # Lo que calcula delta_video_offline.mpc en Z(2^64):
    public_mask = sessions[0].masks[0]
    z = sum(s.inputs[0] for s in sessions) * (1 - public_mask.astype(np.uint64))
    assert np.array_equal(decode_output(z, payload), original * (1 - mask))


def test_decode_output_rejects_out_of_range_and_padding():
    with pytest.raises(RuntimeError):
        decode_output(np.array([766, 0], dtype=np.uint64), 1)
    with pytest.raises(RuntimeError):
        decode_output(np.array([1, 5], dtype=np.uint64), 1)


class OutputSession(RecordingSession):
    def __init__(self, z):
        super().__init__()
        self.z = z

    def receive_sum(self, count):
        words = np.zeros(count, dtype=np.uint64)
        words[: len(self.z)] = self.z
        return words


class FakeEncoder:
    def __init__(self, path, *_):
        import io
        self.path, self.stdin, self.killed = path, io.BytesIO(), False
        self.stdin.close = lambda: None

    def wait(self):
        self.path.write_bytes(self.stdin.getvalue())
        return 0

    def kill(self):
        self.killed = True


def test_collector_writes_anonymized_frames(tmp_path):
    expected = np.arange(WIDTH * HEIGHT * FRAMES, dtype=np.uint64) % 200
    output = tmp_path / "out.mp4"
    collect_video(METADATA, OutputSession(expected + 256), output, FakeEncoder)
    assert output.read_bytes() == expected.astype(np.uint8).tobytes()


# --- coordinator: cola durable, propiedad del historial y worker -------------

class FakeCluster:
    def __init__(self):
        self.calls, self.collect_status = [], "COMPLETED"

    async def parties(self, method, path, json=None, *, missing_ok=False):
        self.calls.append((method, path))
        if path.endswith("/prepare"):  # callback real de cada Node Agent
            for party in range(3):
                self.video_service.mark_party_ready(UUID(path.split("/")[4]), party)
        return [{"party_id": i, "feed": {"status": "RUNNING"}} for i in range(3)]

    async def storage(self, method, path, json=None):
        self.calls.append((method, path))
        return {"status": self.collect_status, "result_id": "result-1"}


@pytest.fixture
def coordinator(tmp_path, monkeypatch):
    svc = browser_jobs.Service.__new__(browser_jobs.Service)
    svc.store, svc.cluster, svc.lease = JobStore(tmp_path / "jobs.sqlite3"), FakeCluster(), 90
    svc.worker = MpcWorker(svc.store, svc.cluster, VideoService(["http://p0", "http://p1", "http://p2"]), poll_seconds=0)
    svc.cluster.video_service = svc.worker.video_service
    monkeypatch.setattr(browser_jobs, "background", lambda _svc: asyncio.sleep(0))
    user = {"id": "user-a"}
    coordinator_app.dependency_overrides[browser_jobs.get_service] = lambda: svc
    coordinator_app.dependency_overrides[current_user] = lambda: user["id"]
    with TestClient(coordinator_app) as client:
        yield client, svc, user
    coordinator_app.dependency_overrides.clear()


def create_job(client, name="Calle.mp4"):
    response = client.post("/api/v1/browser-jobs", json={"filename": name, "format": "mp4", "metadata": METADATA})
    assert response.status_code == 201, response.text
    return response.json()


def test_history_is_private_and_shows_only_name_and_status(coordinator):
    client, _, user = coordinator
    job = create_job(client)
    assert set(job) == {"id", "filename", "status", "position"}
    assert job["status"] == states.UPLOADING and job["filename"] == "Calle.mp4"
    user["id"] = "user-b"
    assert client.get("/api/v1/browser-jobs").json() == []
    assert client.get(f"/api/v1/browser-jobs/{job['id']}").status_code == 404
    user["id"] = "user-a"
    assert [j["id"] for j in client.get("/api/v1/browser-jobs").json()] == [job["id"]]


def test_requires_session():
    with TestClient(coordinator_app) as client:
        assert client.get("/api/v1/browser-jobs").status_code == 401


def test_mpc_continues_without_browser_and_queue_is_fifo(coordinator):
    client, svc, _ = coordinator
    first, second = create_job(client, "a.mp4"), create_job(client, "b.mp4")
    for job in (first, second):
        assert client.post(f"/api/v1/browser-jobs/{job['id']}/uploaded", json={"counts": {"people": 1}}).json()["status"] == states.QUEUED
    assert client.get(f"/api/v1/browser-jobs/{second['id']}").json()["position"] == 2
    # Sin heartbeats del navegador: el worker procesa en orden de llegada.
    asyncio.run(svc.worker.run_job(svc.store.next_queued()))
    assert svc.store.get(first["id"])["status"] == states.COMPLETED
    assert svc.store.get(first["id"])["result_id"] == "result-1"
    assert client.get(f"/api/v1/browser-jobs/{second['id']}").json()["position"] == 1
    assert ("DELETE", f"/api/v1/uploads/{first['id']}") in svc.cluster.calls
    svc.cluster.collect_status = "FAILED"
    asyncio.run(svc.worker.run_job(svc.store.next_queued()))
    assert svc.store.get(second["id"])["status"] == states.FAILED


def test_closing_tab_during_detection_fails_only_that_video(coordinator):
    client, svc, _ = coordinator
    job = create_job(client)
    svc.store.update(job["id"], touched=0)
    asyncio.run(svc.expire())
    assert client.get(f"/api/v1/browser-jobs/{job['id']}").json()["status"] == states.FAILED
    assert client.post(f"/api/v1/browser-jobs/{job['id']}/uploaded", json={}).status_code == 409


def test_restart_requeues_interrupted_mpc(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    job = store.create("u", "x.mp4", METADATA)
    store.update(job["id"], status=states.PROCESSING, queued_at=states.now_iso())
    JobStore(tmp_path / "jobs.sqlite3").recover()
    assert store.get(job["id"])["status"] == states.QUEUED


def test_key_upload_endpoint_accepts_base64(tmp_path, monkeypatch):
    monkeypatch.setenv("PARTY_ID", "1")
    monkeypatch.setenv("PARTY_UPLOAD_DIR", str(tmp_path))
    from party_receiver.main import create_app
    from party_receiver.runtime import MpcRuntimeManager

    client = TestClient(create_app(MpcRuntimeManager(1, enabled=False)))
    video = uuid4()
    assert client.post(f"/api/v1/uploads/{video}", json={"metadata": METADATA}).status_code == 201
    assert client.post(f"/api/v1/uploads/{video}/key", json={"key": base64.b64encode(KEY1).decode()}).status_code == 200
    assert client.post(f"/api/v1/uploads/{video}/seal").json()["sealed"]
    assert client.delete(f"/api/v1/uploads/{video}").status_code == 204
    assert not any(Path(tmp_path).rglob("share.key"))
