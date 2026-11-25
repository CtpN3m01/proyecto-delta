"""El Node Agent aporta el share de su party al programa delta_video_offline."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from threading import Lock, Thread
from typing import Callable
from uuid import UUID

from mpc.offline_protocol import (
    ExternalIoSession,
    chunk_count,
    keystream,
    padded_words,
    rechunk,
)
from party_receiver.services.upload_store import UploadStore

logger = logging.getLogger(__name__)


@dataclass
class FeedState:
    status: str = "RUNNING"
    chunks: int = 0
    total_chunks: int = 0
    error: str | None = None
    thread: Thread | None = field(default=None, repr=False)


def feed_party_share(
    party_id: int,
    video_id: UUID,
    store: UploadStore,
    session: ExternalIoSession,
    progress: Callable[[int], None] = lambda _: None,
) -> None:
    metadata = store.metadata(video_id)
    frame_size = metadata["width"] * metadata["height"]
    payload_size = frame_size * metadata["frame_count"]
    with session:
        session.handshake(payload_size, chunk_count(payload_size))
        if party_id == 0:
            masks = rechunk(store.mask_frames(video_id))
            for index, share in enumerate(rechunk(store.share_frames(video_id))):
                mask = next(masks)
                if len(mask) != len(share):
                    raise RuntimeError("Máscara y share desalineados")
                session.send_words(padded_words(mask))
                session.input_private(padded_words(share))
                progress(index + 1)
        else:
            key = store.key(video_id)
            frames = (keystream(key, f, frame_size) for f in range(metadata["frame_count"]))
            for index, share in enumerate(rechunk(frames)):
                session.input_private(padded_words(share))
                progress(index + 1)


class ShareFeeder:
    """Un hilo por job; el estado se consulta desde el coordinator."""

    def __init__(self, party_id: int, store: UploadStore,
                 session_factory: Callable[[int], ExternalIoSession] = ExternalIoSession) -> None:
        self.party_id = party_id
        self.store = store
        self.session_factory = session_factory
        self._jobs: dict[UUID, FeedState] = {}
        self._lock = Lock()

    def start(self, video_id: UUID) -> FeedState:
        with self._lock:
            current = self._jobs.get(video_id)
            if current is not None and current.status == "RUNNING":
                return current
            metadata = self.store.metadata(video_id)
            payload = metadata["width"] * metadata["height"] * metadata["frame_count"]
            state = FeedState(total_chunks=chunk_count(payload))
            self._jobs[video_id] = state

        def run() -> None:
            try:
                feed_party_share(
                    self.party_id, video_id, self.store, self.session_factory(self.party_id),
                    progress=lambda n: setattr(state, "chunks", n),
                )
                state.status = "DONE"
            except Exception as exc:  # el detalle va al log, nunca bytes de shares
                logger.exception("Falló el aporte de la party %s", self.party_id)
                state.status = "FAILED"
                state.error = type(exc).__name__

        state.thread = Thread(target=run, name=f"feed-{video_id}", daemon=True)
        state.thread.start()
        return state

    def get(self, video_id: UUID) -> FeedState | None:
        with self._lock:
            return self._jobs.get(video_id)

    def forget(self, video_id: UUID) -> None:
        with self._lock:
            self._jobs.pop(video_id, None)
