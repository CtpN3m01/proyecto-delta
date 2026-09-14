"""Pruebas de los contratos HTTP usados por el cliente confiable."""

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import httpx
import pytest

from client.networking import (
    CoordinatorClient,
    CoordinatorClientError,
    PartyClient,
    PartyClientError,
)
from client.networking import coordinator_client as coordinator_module
from client.networking import party_client as party_module


def _response(status_code: int, **kwargs: Any) -> httpx.Response:
    return httpx.Response(
        status_code,
        request=httpx.Request("POST", "http://test.invalid"),
        **kwargs,
    )


def test_coordinator_registers_metadata_only_and_orders_party_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video_id = str(uuid4())
    observed: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        observed["url"] = url
        observed.update(kwargs)
        return _response(
            201,
            json={
                "id": video_id,
                "status": "WAITING_FOR_SHARES",
                "parties": [
                    {"id": 2, "url": "http://localhost:8102/"},
                    {"id": 0, "url": "http://localhost:8100"},
                    {"id": 1, "url": "http://localhost:8101"},
                ],
            },
        )

    monkeypatch.setattr(coordinator_module.httpx, "post", fake_post)

    registration = CoordinatorClient(" http://localhost:8000/ ", timeout=2.5).register_video(
        "video.mp4", "mp4"
    )

    assert observed == {
        "url": "http://localhost:8000/api/v1/videos",
        "json": {"filename": "video.mp4", "format": "mp4"},
        "timeout": 2.5,
    }
    assert registration.id == video_id
    assert registration.status == "WAITING_FOR_SHARES"
    assert [(party.id, party.url) for party in registration.parties] == [
        (0, "http://localhost:8100"),
        (1, "http://localhost:8101"),
        (2, "http://localhost:8102"),
    ]


def test_coordinator_gets_video_state(monkeypatch: pytest.MonkeyPatch) -> None:
    video_id = str(uuid4())

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        assert url == f"http://coordinator/api/v1/videos/{video_id}"
        assert kwargs["timeout"] == 4.0
        return _response(
            200,
            json={
                "id": video_id,
                "status": "READY_FOR_MPC",
                "parties": {"0": "RECEIVED", "1": "RECEIVED", "2": "RECEIVED"},
            },
        )

    monkeypatch.setattr(coordinator_module.httpx, "get", fake_get)

    state = CoordinatorClient("http://coordinator", timeout=4.0).get_video(video_id)

    assert state.id == video_id
    assert state.status == "READY_FOR_MPC"
    assert state.parties == {"0": "RECEIVED", "1": "RECEIVED", "2": "RECEIVED"}


@pytest.mark.parametrize(
    ("response", "message"),
    [
        pytest.param(
            _response(422, json={"detail": "Formato no permitido."}),
            "HTTP 422.*Formato no permitido",
            id="http-error-json",
        ),
        pytest.param(
            _response(503, text="servicio no disponible"),
            "HTTP 503.*servicio no disponible",
            id="http-error-text",
        ),
        pytest.param(
            _response(200, content=b"esto no es JSON"),
            "respuesta que no es JSON",
            id="invalid-json",
        ),
        pytest.param(
            _response(200, json=["not", "an", "object"]),
            "respuesta JSON inv.lida",
            id="wrong-json-type",
        ),
    ],
)
def test_coordinator_turns_invalid_http_responses_into_clear_errors(
    monkeypatch: pytest.MonkeyPatch,
    response: httpx.Response,
    message: str,
) -> None:
    monkeypatch.setattr(coordinator_module.httpx, "post", lambda *args, **kwargs: response)

    with pytest.raises(CoordinatorClientError, match=message):
        CoordinatorClient("http://coordinator").register_video("video.mp4", "mp4")


def test_coordinator_rejects_invalid_registration_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _response(
        201,
        json={
            "id": str(uuid4()),
            "status": "WAITING_FOR_SHARES",
            "parties": [{"id": 0, "url": "http://party-0"}],
        },
    )
    monkeypatch.setattr(coordinator_module.httpx, "post", lambda *args, **kwargs: response)

    with pytest.raises(CoordinatorClientError, match="exactamente las parties 0, 1 y 2"):
        CoordinatorClient("http://coordinator").register_video("video.mp4", "mp4")


@pytest.mark.parametrize(
    "error_factory",
    [
        pytest.param(
            lambda request: httpx.ConnectError("connection refused", request=request),
            id="connection",
        ),
        pytest.param(
            lambda request: httpx.ReadTimeout("timed out", request=request),
            id="timeout",
        ),
    ],
)
def test_coordinator_turns_connection_failures_into_manageable_errors(
    monkeypatch: pytest.MonkeyPatch,
    error_factory: Callable[[httpx.Request], httpx.RequestError],
) -> None:
    def fail(url: str, **kwargs: Any) -> httpx.Response:
        raise error_factory(httpx.Request("POST", url))

    monkeypatch.setattr(coordinator_module.httpx, "post", fail)

    with pytest.raises(CoordinatorClientError, match="No se pudo contactar al Coordinator"):
        CoordinatorClient("http://coordinator").register_video("video.mp4", "mp4")


def test_coordinator_reports_missing_video(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _response(404, json={"detail": "Video no encontrado."})
    monkeypatch.setattr(coordinator_module.httpx, "get", lambda *args, **kwargs: response)

    with pytest.raises(CoordinatorClientError, match="HTTP 404.*Video no encontrado"):
        CoordinatorClient("http://coordinator").get_video(str(uuid4()))


def test_party_sends_raw_octet_stream_and_validates_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video_id = str(uuid4())
    share = bytes(range(256)) * 4
    observed: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        observed["url"] = url
        observed.update(kwargs)
        return _response(
            200,
            json={"video_id": video_id, "party_id": 1, "status": "RECEIVED"},
        )

    monkeypatch.setattr(party_module.httpx, "post", fake_post)
    timeout = httpx.Timeout(30.0)

    PartyClient(timeout=timeout).send_share(1, "http://localhost:8101/", video_id, share)

    assert observed["url"] == f"http://localhost:8101/api/v1/shares/{video_id}"
    assert observed["content"] == share
    assert observed["headers"] == {"Content-Type": "application/octet-stream"}
    assert observed["timeout"] is timeout
    assert "json" not in observed


@pytest.mark.parametrize(
    ("response", "message"),
    [
        pytest.param(
            _response(400, json={"detail": "share vacío"}),
            "Party 2 rechaz.*HTTP 400.*share vac.o",
            id="http-error",
        ),
        pytest.param(
            _response(200, content=b"respuesta no JSON"),
            "Party 2 devolvi.*confirmaci.n inv.lida",
            id="invalid-json",
        ),
        pytest.param(
            _response(
                200,
                json={"video_id": str(uuid4()), "party_id": 1, "status": "RECEIVED"},
            ),
            "confirmaci.n que no coincide",
            id="mismatched-receipt",
        ),
    ],
)
def test_party_turns_bad_http_responses_into_clear_errors(
    monkeypatch: pytest.MonkeyPatch,
    response: httpx.Response,
    message: str,
) -> None:
    monkeypatch.setattr(party_module.httpx, "post", lambda *args, **kwargs: response)

    with pytest.raises(PartyClientError, match=message):
        PartyClient().send_share(2, "http://party-2", str(uuid4()), b"share")


@pytest.mark.parametrize(
    "error_factory",
    [
        pytest.param(
            lambda request: httpx.ConnectError("connection refused", request=request),
            id="connection",
        ),
        pytest.param(
            lambda request: httpx.WriteTimeout("timed out", request=request),
            id="timeout",
        ),
    ],
)
def test_party_identifies_itself_on_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
    error_factory: Callable[[httpx.Request], httpx.RequestError],
) -> None:
    def fail(url: str, **kwargs: Any) -> httpx.Response:
        raise error_factory(httpx.Request("POST", url))

    monkeypatch.setattr(party_module.httpx, "post", fail)

    with pytest.raises(PartyClientError, match="Party 2 no est.* disponible"):
        PartyClient().send_share(2, "http://party-2", str(uuid4()), b"share")


@pytest.mark.parametrize("party_id", [-1, 3, 99])
def test_party_rejects_invalid_party_id_before_network(
    monkeypatch: pytest.MonkeyPatch,
    party_id: int,
) -> None:
    def unexpected_request(*args: Any, **kwargs: Any) -> httpx.Response:
        pytest.fail("No debe realizarse una solicitud para un party_id inválido")

    monkeypatch.setattr(party_module.httpx, "post", unexpected_request)

    with pytest.raises(ValueError, match="party_id debe ser 0, 1 o 2"):
        PartyClient().send_share(party_id, "http://party", str(uuid4()), b"share")


def test_party_rejects_empty_share_before_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_request(*args: Any, **kwargs: Any) -> httpx.Response:
        pytest.fail("No debe realizarse una solicitud para un share vacío")

    monkeypatch.setattr(party_module.httpx, "post", unexpected_request)

    with pytest.raises(ValueError, match="share vac"):
        PartyClient().send_share(0, "http://party-0", str(uuid4()), b"")
