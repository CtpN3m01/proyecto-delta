"""HTTP contract tests for the T09 Coordinator API."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from coordinator.api import videos as videos_api
from coordinator.main import app
from coordinator.services.video_service import DEFAULT_PARTY_URLS, VideoService


@pytest.fixture
def client(monkeypatch) -> TestClient:
    """Give every test a new in-memory store."""

    monkeypatch.setattr(videos_api, "video_service", VideoService(DEFAULT_PARTY_URLS))
    with TestClient(app) as test_client:
        yield test_client


def register_video(client: TestClient, filename: str = "camera.mp4") -> dict:
    response = client.post(
        "/api/v1/videos",
        json={"filename": filename, "format": "mp4"},
    )
    assert response.status_code == 201
    return response.json()


def test_register_video_returns_uuid4_initial_state_and_expected_urls(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/videos",
        json={"filename": "camera-01.mp4", "format": "mp4"},
    )

    assert response.status_code == 201
    body = response.json()
    parsed_id = UUID(body["id"])
    assert parsed_id.version == 4
    assert body == {
        "id": str(parsed_id),
        "status": "WAITING_FOR_SHARES",
        "parties": [
            {"id": 0, "url": "http://localhost:8100"},
            {"id": 1, "url": "http://localhost:8101"},
            {"id": 2, "url": "http://localhost:8102"},
        ],
    }


def test_multiple_registrations_return_distinct_ids(client: TestClient) -> None:
    ids = {
        register_video(client, f"video-{index}.mp4")["id"] for index in range(10)
    }

    assert len(ids) == 10


def test_concurrent_api_registrations_have_unique_independent_jobs(
    client: TestClient,
) -> None:
    def post_registration(index: int) -> str:
        response = client.post(
            "/api/v1/videos",
            json={"filename": f"parallel-{index}.mp4", "format": "mp4"},
        )
        assert response.status_code == 201
        return response.json()["id"]

    with ThreadPoolExecutor(max_workers=5) as executor:
        video_ids = list(executor.map(post_registration, range(10)))

    assert len(video_ids) == len(set(video_ids)) == 10
    for video_id in video_ids:
        state = client.get(f"/api/v1/videos/{video_id}")
        assert state.status_code == 200
        assert state.json()["status"] == "WAITING_FOR_SHARES"


@pytest.mark.parametrize("video_format", ["avi", "mov", "mkv", "txt", "MP3"])
def test_registration_rejects_non_mp4_formats(
    client: TestClient,
    video_format: str,
) -> None:
    response = client.post(
        "/api/v1/videos",
        json={"filename": f"video.{video_format.lower()}", "format": video_format},
    )

    assert response.status_code == 415
    assert "Only MP4" in response.json()["detail"]


def test_registration_accepts_normalized_mp4_format(client: TestClient) -> None:
    for video_format in ("MP4", ".mp4", " .MP4 "):
        response = client.post(
            "/api/v1/videos",
            json={"filename": "video.mp4", "format": video_format},
        )
        assert response.status_code == 201


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"filename": "video.mp4"},
        {"format": "mp4"},
        {"filename": "video.mp4", "format": ""},
        {"filename": "video.mp4", "format": None},
        {"filename": "", "format": "mp4"},
        {"filename": None, "format": "mp4"},
        {"filename": "x" * 256, "format": "mp4"},
        {"filename": "video.mp4", "format": "x" * 21},
    ],
)
def test_registration_rejects_missing_empty_null_or_oversized_fields(
    client: TestClient,
    payload: dict,
) -> None:
    assert client.post("/api/v1/videos", json=payload).status_code == 422


def test_registration_rejects_blank_filename_and_malformed_body(
    client: TestClient,
) -> None:
    blank = client.post(
        "/api/v1/videos",
        json={"filename": "   ", "format": "mp4"},
    )
    malformed = client.post(
        "/api/v1/videos",
        content="{not-json",
        headers={"content-type": "application/json"},
    )
    binary = client.post(
        "/api/v1/videos",
        content=b"secret-share-bytes",
        headers={"content-type": "application/octet-stream"},
    )

    assert blank.status_code == 422
    assert malformed.status_code == 422
    assert binary.status_code == 422


def test_get_returns_initial_state_and_unknown_video_is_404(
    client: TestClient,
) -> None:
    registration = register_video(client)

    response = client.get(f"/api/v1/videos/{registration['id']}")
    assert response.status_code == 200
    assert response.json() == {
        "id": registration["id"],
        "status": "WAITING_FOR_SHARES",
        "parties": {"0": "PENDING", "1": "PENDING", "2": "PENDING"},
    }

    unknown = client.get(f"/api/v1/videos/{uuid4()}")
    assert unknown.status_code == 404
    assert "was not found" in unknown.json()["detail"]


def test_get_rejects_malformed_uuid(client: TestClient) -> None:
    assert client.get("/api/v1/videos/not-a-uuid").status_code == 422


def test_confirmations_progress_and_ready_requires_all_three_parties(
    client: TestClient,
) -> None:
    video_id = register_video(client)["id"]

    expected_parties = {"0": "PENDING", "1": "PENDING", "2": "PENDING"}
    for party_id in (0, 1, 2):
        response = client.post(
            f"/api/v1/videos/{video_id}/confirmations",
            json={"party_id": party_id, "status": "RECEIVED"},
        )
        assert response.status_code == 200
        expected_parties[str(party_id)] = "RECEIVED"
        assert response.json()["parties"] == expected_parties
        expected_status = "READY_FOR_MPC" if party_id == 2 else "WAITING_FOR_SHARES"
        assert response.json()["status"] == expected_status

    assert client.get(f"/api/v1/videos/{video_id}").json()["status"] == "READY_FOR_MPC"


def test_repeated_confirmation_is_idempotent(client: TestClient) -> None:
    video_id = register_video(client)["id"]
    responses = [
        client.post(
            f"/api/v1/videos/{video_id}/confirmations",
            json={"party_id": 0, "status": "RECEIVED"},
        )
        for _ in range(3)
    ]

    assert all(response.status_code == 200 for response in responses)
    assert responses[0].json() == responses[1].json() == responses[2].json()
    assert responses[-1].json()["status"] == "WAITING_FOR_SHARES"


@pytest.mark.parametrize("party_id", [-1, 3, 99])
def test_confirmation_rejects_out_of_range_party_ids(
    client: TestClient,
    party_id: int,
) -> None:
    video_id = register_video(client)["id"]
    response = client.post(
        f"/api/v1/videos/{video_id}/confirmations",
        json={"party_id": party_id, "status": "RECEIVED"},
    )

    assert response.status_code == 422
    state = client.get(f"/api/v1/videos/{video_id}").json()
    assert state["parties"] == {"0": "PENDING", "1": "PENDING", "2": "PENDING"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"party_id": None, "status": "RECEIVED"},
        {"party_id": True, "status": "RECEIVED"},
        {"party_id": False, "status": "RECEIVED"},
        {"party_id": "0", "status": "RECEIVED"},
        {"party_id": "party-zero", "status": "RECEIVED"},
        {"party_id": 1.0, "status": "RECEIVED"},
        {"party_id": 0.5, "status": "RECEIVED"},
        {"party_id": [], "status": "RECEIVED"},
        {"party_id": 0},
        {"party_id": 0, "status": "PENDING"},
        {"party_id": 0, "status": "received"},
    ],
)
def test_confirmation_rejects_invalid_types_or_status(
    client: TestClient,
    payload: dict,
) -> None:
    video_id = register_video(client)["id"]
    response = client.post(
        f"/api/v1/videos/{video_id}/confirmations",
        json=payload,
    )

    assert response.status_code == 422
    assert client.get(f"/api/v1/videos/{video_id}").json()["status"] == "WAITING_FOR_SHARES"


def test_confirmation_for_unknown_video_returns_404_without_creating_job(
    client: TestClient,
) -> None:
    unknown_id = uuid4()

    response = client.post(
        f"/api/v1/videos/{unknown_id}/confirmations",
        json={"party_id": 0, "status": "RECEIVED"},
    )

    assert response.status_code == 404
    assert client.get(f"/api/v1/videos/{unknown_id}").status_code == 404


def test_jobs_keep_independent_confirmation_state(client: TestClient) -> None:
    first_id = register_video(client, "first.mp4")["id"]
    second_id = register_video(client, "second.mp4")["id"]

    first_confirmation = client.post(
        f"/api/v1/videos/{first_id}/confirmations",
        json={"party_id": 2, "status": "RECEIVED"},
    )
    second = client.get(f"/api/v1/videos/{second_id}")

    assert first_confirmation.json()["parties"]["2"] == "RECEIVED"
    assert second.json()["parties"] == {
        "0": "PENDING",
        "1": "PENDING",
        "2": "PENDING",
    }


def test_health_and_openapi_expose_coordinator_routes(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/docs").status_code == 200

    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    paths = openapi.json()["paths"]
    assert "/api/v1/videos" in paths
    assert "/api/v1/videos/{video_id}" in paths
    assert "/api/v1/videos/{video_id}/confirmations" in paths
