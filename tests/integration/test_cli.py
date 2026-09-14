"""Pruebas del flujo y los códigos de salida de la CLI sin servicios externos."""

from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pytest

from client import cli
from client.networking import (
    CoordinatorClientError,
    PartyClientError,
    PartyEndpoint,
    VideoRegistration,
    VideoState,
)
from client.preprocessing import PreprocessedVideo, VideoMetadata


def _registration(video_id: str) -> VideoRegistration:
    return VideoRegistration(
        id=video_id,
        status="WAITING_FOR_SHARES",
        parties=(
            PartyEndpoint(0, "http://party-0"),
            PartyEndpoint(1, "http://party-1"),
            PartyEndpoint(2, "http://party-2"),
        ),
    )


@dataclass
class StubCoordinator:
    video_id: str = field(default_factory=lambda: str(uuid4()))
    final_status: str = "READY_FOR_MPC"
    register_error: Exception | None = None
    registrations: list[tuple[str, str]] = field(default_factory=list)
    status_queries: list[str] = field(default_factory=list)

    def register_video(self, filename: str, video_format: str) -> VideoRegistration:
        self.registrations.append((filename, video_format))
        if self.register_error is not None:
            raise self.register_error
        return _registration(self.video_id)

    def get_video(self, video_id: str) -> VideoState:
        self.status_queries.append(video_id)
        return VideoState(
            id=video_id,
            status=self.final_status,
            parties={"0": "RECEIVED", "1": "RECEIVED", "2": "RECEIVED"},
        )


@dataclass
class StubPreprocessor:
    error: Exception | None = None
    paths: list[Path] = field(default_factory=list)

    def process(self, path: Path) -> PreprocessedVideo:
        self.paths.append(path)
        if self.error is not None:
            raise self.error
        return PreprocessedVideo(
            payload=b"secret-payload",
            metadata=VideoMetadata(
                frame_count=2,
                height=12,
                width=16,
                channels=3,
                fps=5.0,
                dtype="uint8",
            ),
        )


@dataclass
class StubGenerator:
    payloads: list[bytes] = field(default_factory=list)

    def generate(self, payload: bytes) -> tuple[bytes, bytes, bytes]:
        self.payloads.append(payload)
        return b"share-0", b"share-1", b"share-2"


@dataclass
class StubPartyClient:
    fail_party: int | None = None
    sends: list[tuple[int, str, str, bytes]] = field(default_factory=list)

    def send_share(
        self,
        party_id: int,
        party_url: str,
        video_id: str,
        share: bytes,
    ) -> None:
        self.sends.append((party_id, party_url, video_id, share))
        if party_id == self.fail_party:
            raise PartyClientError(f"Party {party_id} no respondió.")


def _patch_cli_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    coordinator: StubCoordinator,
    party_client: StubPartyClient,
    preprocessor: StubPreprocessor,
    generator: StubGenerator,
) -> None:
    monkeypatch.setattr(cli, "CoordinatorClient", lambda url: coordinator)
    monkeypatch.setattr(cli, "PartyClient", lambda: party_client)
    monkeypatch.setattr(cli, "VideoPreprocessor", lambda: preprocessor)
    monkeypatch.setattr(cli, "create_share_generator", lambda: generator)


def _existing_mp4(tmp_path: Path) -> Path:
    path = tmp_path / "entrada.mp4"
    path.write_bytes(b"contenido reemplazado por el preprocessor stub")
    return path


def test_success_returns_zero_and_distributes_each_share_to_its_party(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _existing_mp4(tmp_path)
    coordinator = StubCoordinator()
    party_client = StubPartyClient()
    preprocessor = StubPreprocessor()
    generator = StubGenerator()
    _patch_cli_dependencies(monkeypatch, coordinator, party_client, preprocessor, generator)

    exit_code = cli.main(["upload", str(path)])

    output = capsys.readouterr()
    assert exit_code == 0
    assert coordinator.registrations == [("entrada.mp4", "mp4")]
    assert preprocessor.paths == [path]
    assert generator.payloads == [b"secret-payload"]
    assert party_client.sends == [
        (0, "http://party-0", coordinator.video_id, b"share-0"),
        (1, "http://party-1", coordinator.video_id, b"share-1"),
        (2, "http://party-2", coordinator.video_id, b"share-2"),
    ]
    assert coordinator.status_queries == [coordinator.video_id]
    assert "Estado: READY_FOR_MPC" in output.out
    assert "Party 0" in output.out
    assert "Party 1" in output.out
    assert "Party 2" in output.out
    assert "[OK] Video registrado" in output.out
    # La CLI debe funcionar también en la consola cp1252 habitual de Windows.
    output.out.encode("cp1252")
    assert output.err == ""


def test_nonexistent_file_returns_nonzero_without_registering_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    coordinator = StubCoordinator()
    preprocessor = StubPreprocessor()
    party_client = StubPartyClient()
    generator = StubGenerator()
    _patch_cli_dependencies(monkeypatch, coordinator, party_client, preprocessor, generator)

    exit_code = cli.main(["upload", str(tmp_path / "no-existe.mp4")])

    output = capsys.readouterr()
    assert exit_code != 0
    assert "El archivo no existe" in output.err
    assert "Traceback" not in output.err
    assert coordinator.registrations == []
    assert preprocessor.paths == []
    assert party_client.sends == []


@pytest.mark.parametrize("suffix", [".avi", ".mov", ".mkv", ".txt"])
def test_invalid_extension_returns_nonzero_without_registering_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    suffix: str,
) -> None:
    path = tmp_path / f"entrada{suffix}"
    path.write_bytes(b"no importa")
    coordinator = StubCoordinator()
    preprocessor = StubPreprocessor()
    party_client = StubPartyClient()
    generator = StubGenerator()
    _patch_cli_dependencies(monkeypatch, coordinator, party_client, preprocessor, generator)

    exit_code = cli.main(["upload", str(path)])

    output = capsys.readouterr()
    assert exit_code != 0
    assert "solamente admite archivos con extensión .mp4" in output.err
    assert "Traceback" not in output.err
    assert coordinator.registrations == []
    assert preprocessor.paths == []
    assert party_client.sends == []


def test_coordinator_failure_returns_nonzero_and_stops_before_preprocessing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _existing_mp4(tmp_path)
    coordinator = StubCoordinator(
        register_error=CoordinatorClientError("No se pudo conectar con el Coordinator.")
    )
    preprocessor = StubPreprocessor()
    party_client = StubPartyClient()
    generator = StubGenerator()
    _patch_cli_dependencies(monkeypatch, coordinator, party_client, preprocessor, generator)

    exit_code = cli.main(["upload", str(path)])

    output = capsys.readouterr()
    assert exit_code != 0
    assert "No se pudo conectar con el Coordinator" in output.err
    assert "Traceback" not in output.err
    assert coordinator.registrations == [("entrada.mp4", "mp4")]
    assert preprocessor.paths == []
    assert generator.payloads == []
    assert party_client.sends == []


def test_party_failure_identifies_party_and_does_not_report_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _existing_mp4(tmp_path)
    coordinator = StubCoordinator()
    preprocessor = StubPreprocessor()
    party_client = StubPartyClient(fail_party=2)
    generator = StubGenerator()
    _patch_cli_dependencies(monkeypatch, coordinator, party_client, preprocessor, generator)

    exit_code = cli.main(["upload", str(path)])

    output = capsys.readouterr()
    assert exit_code != 0
    assert "Party 2 no respondió" in output.err
    assert "Traceback" not in output.err
    assert [send[0] for send in party_client.sends] == [0, 1, 2]
    assert "Party 0 recibió share" in output.out
    assert "Party 1 recibió share" in output.out
    assert "Party 2 recibió share" not in output.out
    assert "READY_FOR_MPC" not in output.out
    assert coordinator.status_queries == []


def test_waiting_final_state_returns_nonzero_with_explanation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _existing_mp4(tmp_path)
    coordinator = StubCoordinator(final_status="WAITING_FOR_SHARES")
    party_client = StubPartyClient()
    preprocessor = StubPreprocessor()
    generator = StubGenerator()
    _patch_cli_dependencies(monkeypatch, coordinator, party_client, preprocessor, generator)

    exit_code = cli.main(["upload", str(path)])

    output = capsys.readouterr()
    assert exit_code != 0
    assert "Estado: WAITING_FOR_SHARES" in output.out
    assert "todavía no recibió las tres confirmaciones" in output.err
    assert "READY_FOR_MPC" not in output.out


def test_cli_help_exits_successfully(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])

    output = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "upload" in output.out
    assert output.err == ""
