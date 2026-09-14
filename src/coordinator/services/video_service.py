"""In-memory coordination and status-transition logic."""

from dataclasses import dataclass
import os
from threading import RLock
from typing import Dict, Iterable, Tuple
from urllib.parse import urlparse
from uuid import UUID, uuid4

from coordinator.models.video import (
    PartyEndpoint,
    PartyShareStatus,
    VideoRegistrationResponse,
    VideoStateResponse,
    VideoStatus,
)


DEFAULT_PARTY_URLS = (
    "http://localhost:8100",
    "http://localhost:8101",
    "http://localhost:8102",
)
SUPPORTED_FORMAT = "mp4"


class VideoNotFoundError(LookupError):
    """Raised when a video identifier is not registered."""


class UnsupportedVideoFormatError(ValueError):
    """Raised when the client tries to register a non-MP4 video."""


@dataclass
class _VideoJob:
    id: UUID
    filename: str
    format: str
    status: VideoStatus
    parties: Dict[int, PartyShareStatus]


def load_party_urls(raw_value: str | None = None) -> Tuple[str, str, str]:
    """Load and validate the three public party URLs.

    ``PARTY_URLS`` is a comma-separated list because these addresses are
    returned to the CLI running outside Docker.
    """

    configured = raw_value if raw_value is not None else os.getenv("PARTY_URLS")
    values = DEFAULT_PARTY_URLS if configured is None else tuple(
        item.strip().rstrip("/") for item in configured.split(",") if item.strip()
    )

    if len(values) != 3:
        raise RuntimeError("PARTY_URLS must contain exactly three comma-separated URLs")

    for value in values:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError(f"Invalid public party URL in PARTY_URLS: {value!r}")

    return values[0], values[1], values[2]


class VideoService:
    """Register jobs and track share receipts without handling secret data."""

    def __init__(self, party_urls: Iterable[str]) -> None:
        urls = tuple(party_urls)
        if len(urls) != 3:
            raise ValueError("The T09 protocol requires exactly three parties")

        self._party_endpoints = tuple(
            PartyEndpoint(id=party_id, url=url)
            for party_id, url in enumerate(urls)
        )
        self._jobs: Dict[UUID, _VideoJob] = {}
        self._lock = RLock()

    def register_video(self, filename: str, video_format: str) -> VideoRegistrationResponse:
        """Register video metadata and return direct party destinations."""

        normalized_filename = filename.strip()
        normalized_format = video_format.strip().lower().lstrip(".")
        if not normalized_filename:
            raise ValueError("filename must not be blank")
        if normalized_format != SUPPORTED_FORMAT:
            raise UnsupportedVideoFormatError("Only MP4 videos are supported")

        job = _VideoJob(
            id=uuid4(),
            filename=normalized_filename,
            format=normalized_format,
            status=VideoStatus.WAITING_FOR_SHARES,
            parties={
                endpoint.id: PartyShareStatus.PENDING
                for endpoint in self._party_endpoints
            },
        )
        with self._lock:
            self._jobs[job.id] = job

        return VideoRegistrationResponse(
            id=job.id,
            status=job.status,
            parties=list(self._party_endpoints),
        )

    def get_video(self, video_id: UUID) -> VideoStateResponse:
        """Return a snapshot of one registered job."""

        with self._lock:
            job = self._find_job(video_id)
            return self._state_response(job)

    def confirm_share(self, video_id: UUID, party_id: int) -> VideoStateResponse:
        """Mark one party as received and recalculate the aggregate state."""

        with self._lock:
            job = self._find_job(video_id)
            if type(party_id) is not int or party_id not in job.parties:
                raise ValueError(f"Unknown party_id: {party_id}")

            # Confirmations are idempotent so a party can safely retry its callback.
            job.parties[party_id] = PartyShareStatus.RECEIVED
            if all(status is PartyShareStatus.RECEIVED for status in job.parties.values()):
                job.status = VideoStatus.READY_FOR_MPC

            return self._state_response(job)

    def _find_job(self, video_id: UUID) -> _VideoJob:
        try:
            return self._jobs[video_id]
        except KeyError as exc:
            raise VideoNotFoundError(f"Video {video_id} was not found") from exc

    @staticmethod
    def _state_response(job: _VideoJob) -> VideoStateResponse:
        return VideoStateResponse(
            id=job.id,
            status=job.status,
            parties={str(party_id): status for party_id, status in job.parties.items()},
        )
