"""Aplicación FastAPI compartida por mock-party-0, mock-party-1 y mock-party-2."""

import os
from pathlib import Path

from fastapi import FastAPI

from party_receiver.api.shares import router as shares_router
from party_receiver.services.share_service import ShareService
from party_receiver.storage.local_storage import LocalStorage


def _party_id_from_environment() -> int:
    raw_party_id = os.getenv("PARTY_ID", "0")
    try:
        party_id = int(raw_party_id)
    except ValueError as exc:
        raise RuntimeError("PARTY_ID debe ser un entero entre 0 y 2.") from exc

    if party_id not in (0, 1, 2):
        raise RuntimeError("PARTY_ID debe ser 0, 1 o 2.")
    return party_id


def create_app() -> FastAPI:
    party_id = _party_id_from_environment()
    storage_directory = Path(
        os.getenv("PARTY_STORAGE_DIR", f"data/parties/party-{party_id}")
    )
    coordinator_url = os.getenv(
        "COORDINATOR_INTERNAL_URL", "http://coordinator-api:8000"
    ).strip()
    if not coordinator_url:
        raise RuntimeError("COORDINATOR_INTERNAL_URL no puede estar vacío.")

    application = FastAPI(
        title=f"Proyecto Delta - Mock Party {party_id}",
        version="0.1.0",
    )
    application.state.party_id = party_id
    application.state.share_service = ShareService(
        party_id=party_id,
        storage=LocalStorage(storage_directory),
        coordinator_url=coordinator_url,
    )
    application.include_router(shares_router)

    @application.get("/health", tags=["health"])
    async def health() -> dict[str, int | str]:
        return {"status": "ok", "party_id": party_id}

    return application


app = create_app()
