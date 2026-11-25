import asyncio
import struct
from unittest.mock import AsyncMock
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from party_receiver.api.browser import read_packet, MAX_MESSAGE, external_io
from fastapi import WebSocketDisconnect
from result_storage.main import create_app


def test_storage_atomic_publication_and_restart(tmp_path):
    payload = b"\0\0\0\x18ftypisom" + b"anonymized-test-container"
    client = TestClient(create_app(tmp_path))
    result = client.post("/api/v1/results", files={"video": ("../../source.mp4", payload, "video/mp4")}, data={"counts": '{"people":2}'} )
    assert result.status_code == 201
    record = result.json()
    assert client.get("/api/v1/results").json() == []
    assert client.get(record["download_url"]).status_code == 404
    assert client.post(f"/api/v1/results/{record['id']}/publish").status_code == 200
    restarted = TestClient(create_app(tmp_path))
    assert restarted.get("/api/v1/results").json()[0]["id"] == record["id"]
    assert restarted.get(record["download_url"]).content == payload
    assert len(list(tmp_path.glob("*.mp4"))) == 1
    assert not list(tmp_path.glob("*.partial"))


@pytest.mark.parametrize("payload,content_type", [(b"", "video/mp4"), (b"not an mp4 file", "video/mp4"), (b"image", "image/png")])
def test_storage_rejects_invalid_results(tmp_path, payload, content_type):
    client = TestClient(create_app(tmp_path))
    assert client.post("/api/v1/results", files={"video": ("x.mp4", payload, content_type)}).status_code in (415, 422)
    assert client.get("/api/v1/results").json() == []
    assert not list(tmp_path.glob("*.partial"))


def test_adapter_framing_handles_tcp_fragmentation():
    async def run():
        reader = asyncio.StreamReader()
        for part in [b"\x03", b"\x00\x00", b"\x00a", b"bc"]:
            reader.feed_data(part)
        assert await read_packet(reader) == b"abc"
        reader.feed_data(struct.pack("<I", MAX_MESSAGE + 1))
        with pytest.raises(ValueError):
            await read_packet(reader)
    asyncio.run(run())


def test_adapter_disconnect_during_accept_does_not_keep_party_busy():
    state = SimpleNamespace(party_id=0, job_service=SimpleNamespace(get=lambda _: {"status": "PROCESSING"}))
    websocket = SimpleNamespace(
        headers={"origin": "http://localhost:8080"}, app=SimpleNamespace(state=state),
        accept=AsyncMock(side_effect=WebSocketDisconnect()), close=AsyncMock(side_effect=WebSocketDisconnect()),
    )
    asyncio.run(external_io(websocket, uuid4()))
    assert state.browser_connected is False
