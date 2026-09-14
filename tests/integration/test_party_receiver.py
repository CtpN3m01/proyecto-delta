"""Integración liviana de la API, servicio y almacenamiento de una party."""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from party_receiver.main import _party_id_from_environment, create_app
from party_receiver.services import share_service as share_service_module
from party_receiver.services.share_service import ShareService
from party_receiver.storage.local_storage import LocalStorage


@pytest.fixture
def party_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Path, AsyncMock]]:
    storage_directory = tmp_path / "party-1"
    monkeypatch.setenv("PARTY_ID", "1")
    monkeypatch.setenv("PARTY_STORAGE_DIR", str(storage_directory))
    monkeypatch.setenv("COORDINATOR_INTERNAL_URL", "http://coordinator-api:8000")
    app = create_app()
    notification = AsyncMock()
    monkeypatch.setattr(app.state.share_service, "_notify_coordinator", notification)

    with TestClient(app) as client:
        yield client, storage_directory, notification


def test_health_exposes_configured_party_identity(
    party_client: tuple[TestClient, Path, AsyncMock],
) -> None:
    client, _, _ = party_client

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "party_id": 1}


def test_receive_octet_stream_persists_exact_bytes_and_returns_receipt(
    party_client: tuple[TestClient, Path, AsyncMock],
) -> None:
    client, storage_directory, notification = party_client
    video_id = uuid4()
    payload = b"\x00\xffopaque\x00share"

    response = client.post(
        f"/api/v1/shares/{video_id}",
        content=payload,
        headers={"content-type": "application/octet-stream"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "video_id": str(video_id),
        "party_id": 1,
        "status": "RECEIVED",
    }
    assert (storage_directory / f"{video_id}.share").read_bytes() == payload
    notification.assert_awaited_once_with(video_id)


def test_receive_accepts_case_and_parameters_in_octet_stream_content_type(
    party_client: tuple[TestClient, Path, AsyncMock],
) -> None:
    client, storage_directory, notification = party_client
    video_id = uuid4()

    response = client.post(
        f"/api/v1/shares/{video_id}",
        content=b"share",
        headers={"content-type": "Application/Octet-Stream; charset=binary"},
    )

    assert response.status_code == 200
    assert (storage_directory / f"{video_id}.share").read_bytes() == b"share"
    notification.assert_awaited_once_with(video_id)


@pytest.mark.parametrize(
    "content_type",
    [None, "application/json", "text/plain", "multipart/form-data"],
)
def test_receive_rejects_non_binary_content_types_before_storage(
    party_client: tuple[TestClient, Path, AsyncMock], content_type: str | None
) -> None:
    client, storage_directory, notification = party_client
    headers = {} if content_type is None else {"content-type": content_type}

    response = client.post(
        f"/api/v1/shares/{uuid4()}", content=b"share", headers=headers
    )

    assert response.status_code == 415
    assert "application/octet-stream" in response.json()["detail"]
    assert list(storage_directory.iterdir()) == []
    notification.assert_not_awaited()


def test_receive_rejects_empty_binary_payload_before_storage(
    party_client: tuple[TestClient, Path, AsyncMock],
) -> None:
    client, storage_directory, notification = party_client

    response = client.post(
        f"/api/v1/shares/{uuid4()}",
        content=b"",
        headers={"content-type": "application/octet-stream"},
    )

    assert response.status_code == 400
    assert "vacío" in response.json()["detail"]
    assert list(storage_directory.iterdir()) == []
    notification.assert_not_awaited()


def test_storage_failure_returns_500_and_skips_confirmation(
    party_client: tuple[TestClient, Path, AsyncMock],
) -> None:
    client, storage_directory, notification = party_client
    storage_directory.rmdir()
    storage_directory.write_bytes(b"this path is no longer a directory")

    response = client.post(
        f"/api/v1/shares/{uuid4()}",
        content=b"share",
        headers={"content-type": "application/octet-stream"},
    )

    assert response.status_code == 500
    assert "almacenar" in response.json()["detail"]
    notification.assert_not_awaited()


@pytest.mark.parametrize("invalid_id", ["not-a-uuid", "123", "null"])
def test_receive_rejects_malformed_uuid_without_writing(
    party_client: tuple[TestClient, Path, AsyncMock], invalid_id: str
) -> None:
    client, storage_directory, notification = party_client

    response = client.post(
        f"/api/v1/shares/{invalid_id}",
        content=b"share",
        headers={"content-type": "application/octet-stream"},
    )

    assert response.status_code == 422
    assert list(storage_directory.iterdir()) == []
    notification.assert_not_awaited()


@pytest.mark.parametrize(
    "malicious_path",
    ["..%2F..%2Fescaped", "%2E%2E%2F%2E%2E%2Fescaped"],
)
def test_path_traversal_request_cannot_escape_party_storage(
    party_client: tuple[TestClient, Path, AsyncMock], malicious_path: str
) -> None:
    client, storage_directory, notification = party_client

    response = client.post(
        f"/api/v1/shares/{malicious_path}",
        content=b"secret",
        headers={"content-type": "application/octet-stream"},
    )

    assert response.status_code in {404, 422}
    assert list(storage_directory.parent.rglob("*.share")) == []
    notification.assert_not_awaited()


def test_receive_handles_five_mib_payload_without_truncation(
    party_client: tuple[TestClient, Path, AsyncMock],
) -> None:
    client, storage_directory, notification = party_client
    video_id = uuid4()
    payload = bytes(range(256)) * (5 * 1024 * 1024 // 256)

    response = client.post(
        f"/api/v1/shares/{video_id}",
        content=payload,
        headers={"content-type": "application/octet-stream"},
    )

    destination = storage_directory / f"{video_id}.share"
    assert response.status_code == 200
    assert destination.stat().st_size == 5 * 1024 * 1024
    assert destination.read_bytes() == payload
    notification.assert_awaited_once_with(video_id)


def test_three_apps_keep_party_identity_and_storage_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video_id = uuid4()
    shares = [b"share-0", b"share-1", b"share-2"]
    apps = []

    for party_id in range(3):
        storage_directory = tmp_path / f"party-{party_id}"
        monkeypatch.setenv("PARTY_ID", str(party_id))
        monkeypatch.setenv("PARTY_STORAGE_DIR", str(storage_directory))
        monkeypatch.setenv(
            "COORDINATOR_INTERNAL_URL", "http://coordinator-api:8000"
        )
        app = create_app()
        monkeypatch.setattr(app.state.share_service, "_notify_coordinator", AsyncMock())
        apps.append(app)

    for party_id, app in enumerate(apps):
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/shares/{video_id}",
                content=shares[party_id],
                headers={"content-type": "application/octet-stream"},
            )
            assert response.status_code == 200
            assert response.json()["party_id"] == party_id

    for party_id, expected_share in enumerate(shares):
        directory = tmp_path / f"party-{party_id}"
        files = list(directory.glob("*.share"))
        assert files == [directory / f"{video_id}.share"]
        assert files[0].read_bytes() == expected_share


@pytest.mark.parametrize("party_id", ["-1", "3", "99", "abc", "1.5", ""])
def test_invalid_party_id_configuration_fails_fast(
    monkeypatch: pytest.MonkeyPatch, party_id: str
) -> None:
    monkeypatch.setenv("PARTY_ID", party_id)

    with pytest.raises(RuntimeError, match="PARTY_ID"):
        _party_id_from_environment()


@pytest.mark.parametrize("party_id", ["0", "1", "2"])
def test_valid_party_id_configuration_is_accepted(
    monkeypatch: pytest.MonkeyPatch, party_id: str
) -> None:
    monkeypatch.setenv("PARTY_ID", party_id)

    assert _party_id_from_environment() == int(party_id)


def test_blank_coordinator_configuration_fails_fast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PARTY_ID", "0")
    monkeypatch.setenv("PARTY_STORAGE_DIR", str(tmp_path / "party-0"))
    monkeypatch.setenv("COORDINATOR_INTERNAL_URL", "   ")

    with pytest.raises(RuntimeError, match="COORDINATOR_INTERNAL_URL"):
        create_app()


def test_invalid_storage_configuration_fails_during_app_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage_file = tmp_path / "not-a-directory"
    storage_file.write_bytes(b"occupied")
    monkeypatch.setenv("PARTY_ID", "0")
    monkeypatch.setenv("PARTY_STORAGE_DIR", str(storage_file))
    monkeypatch.setenv("COORDINATOR_INTERNAL_URL", "http://coordinator-api:8000")

    with pytest.raises(FileExistsError):
        create_app()


def test_share_service_rejects_invalid_party_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="party_id"):
        ShareService(
            party_id=3,
            storage=LocalStorage(tmp_path / "party"),
            coordinator_url="http://coordinator-api:8000",
        )


def _mock_coordinator_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> None:
    real_async_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def client_factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return real_async_client(transport=transport, *args, **kwargs)

    monkeypatch.setattr(share_service_module.httpx, "AsyncClient", client_factory)


@pytest.mark.anyio
async def test_notification_sends_only_expected_confirmation_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def coordinator(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["content_type"] = request.headers.get("content-type")
        captured["body"] = request.read()
        return httpx.Response(200, json={"status": "WAITING_FOR_SHARES"})

    _mock_coordinator_transport(monkeypatch, coordinator)
    service = ShareService(
        party_id=2,
        storage=LocalStorage(tmp_path / "party-2"),
        coordinator_url="http://coordinator-api:8000/",
        notification_timeout=0.25,
    )
    video_id = uuid4()

    receipt = await service.receive(video_id, b"opaque-share")

    assert receipt == {
        "video_id": str(video_id),
        "party_id": 2,
        "status": "RECEIVED",
    }
    assert captured == {
        "method": "POST",
        "url": (
            f"http://coordinator-api:8000/api/v1/videos/{video_id}/confirmations"
        ),
        "content_type": "application/json",
        "body": b'{"party_id":2,"status":"RECEIVED"}',
    }


@pytest.mark.anyio
async def test_coordinator_connection_failure_is_mapped_and_share_remains_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def offline_coordinator(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    _mock_coordinator_transport(monkeypatch, offline_coordinator)
    storage_directory = tmp_path / "party-0"
    service = ShareService(
        party_id=0,
        storage=LocalStorage(storage_directory),
        coordinator_url="http://coordinator-api:8000",
    )
    app = create_app()
    app.state.share_service = service
    video_id = uuid4()

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/api/v1/shares/{video_id}",
            content=b"stored-before-callback",
            headers={"content-type": "application/octet-stream"},
        )

    assert response.status_code == 502
    assert "no se pudo contactar" in response.json()["detail"]
    assert "reenviar" in response.json()["detail"]
    assert (storage_directory / f"{video_id}.share").read_bytes() == (
        b"stored-before-callback"
    )


@pytest.mark.anyio
async def test_coordinator_http_rejection_is_mapped_and_includes_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def rejecting_coordinator(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "unknown video"})

    _mock_coordinator_transport(monkeypatch, rejecting_coordinator)
    storage_directory = tmp_path / "party-0"
    service = ShareService(
        party_id=0,
        storage=LocalStorage(storage_directory),
        coordinator_url="http://coordinator-api:8000",
    )
    app = create_app()
    app.state.share_service = service
    video_id = uuid4()

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/api/v1/shares/{video_id}",
            content=b"share",
            headers={"content-type": "application/octet-stream"},
        )

    assert response.status_code == 502
    assert "HTTP 404" in response.json()["detail"]
    assert (storage_directory / f"{video_id}.share").read_bytes() == b"share"
