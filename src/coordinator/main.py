"""FastAPI application for Proyecto Delta's control plane."""

from fastapi import FastAPI

from coordinator.api.videos import router as videos_router


app = FastAPI(
    title="Proyecto Delta Coordinator",
    description="Registers video metadata and coordinates T09 share receipt states.",
    version="0.1.0",
)
app.include_router(videos_router)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Lightweight service health endpoint."""

    return {"status": "ok"}

