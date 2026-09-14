"""CLI del entorno confiable para registrar y distribuir un MP4."""

import argparse
import os
from pathlib import Path
import sys
from typing import Sequence

from client.networking import (
    CoordinatorClient,
    CoordinatorClientError,
    PartyClient,
    PartyClientError,
)
from client.preprocessing import VideoPreprocessingError, VideoPreprocessor
from client.sharing import (
    ShareGenerationError,
    ShareGenerator,
    create_share_generator,
)


class ClientInputError(ValueError):
    """La entrada local de la CLI no cumple los requisitos de T09."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m client",
        description="Cliente confiable de Proyecto Delta.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    upload = commands.add_parser(
        "upload",
        help="Preprocesa un MP4 y distribuye sus shares.",
    )
    upload.add_argument("video", type=Path, help="Ruta local al archivo .mp4")
    return parser


def _validated_video_path(path: Path) -> Path:
    if not path.exists():
        raise ClientInputError(f"El archivo no existe: {path}")
    if not path.is_file():
        raise ClientInputError(f"La ruta no corresponde a un archivo: {path}")
    if path.suffix.lower() != ".mp4":
        raise ClientInputError("T09 solamente admite archivos con extensión .mp4.")
    return path


def upload_video(
    video_path: Path,
    coordinator: CoordinatorClient,
    party_client: PartyClient,
    preprocessor: VideoPreprocessor,
    share_generator: ShareGenerator,
) -> int:
    path = _validated_video_path(video_path)
    print("Proyecto Delta")
    print(f"\nVideo: {path.name}")

    registration = coordinator.register_video(path.name, "mp4")
    print(f"ID: {registration.id}\n")
    print("[OK] Video registrado")

    processed = preprocessor.process(path)
    print(
        "[OK] Preprocesamiento completado "
        f"({processed.metadata.frame_count} frames, "
        f"{processed.metadata.width}x{processed.metadata.height})"
    )

    shares = share_generator.generate(processed.payload)
    print("[OK] Shares generados")

    for endpoint, share in zip(registration.parties, shares):
        party_client.send_share(endpoint.id, endpoint.url, registration.id, share)
        print(f"[OK] Party {endpoint.id} recibió share")

    final_state = coordinator.get_video(registration.id)
    print(f"\nEstado: {final_state.status}")
    if final_state.status != "READY_FOR_MPC":
        print(
            "El Coordinator todavía no recibió las tres confirmaciones.",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "upload":
        return 2

    coordinator_url = os.getenv("COORDINATOR_URL", "http://localhost:8000")
    try:
        return upload_video(
            video_path=args.video,
            coordinator=CoordinatorClient(coordinator_url),
            party_client=PartyClient(),
            preprocessor=VideoPreprocessor(),
            share_generator=create_share_generator(),
        )
    except (
        ClientInputError,
        CoordinatorClientError,
        PartyClientError,
        VideoPreprocessingError,
        ShareGenerationError,
        ValueError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nOperación cancelada.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
