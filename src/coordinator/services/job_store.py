"""Historial y cola persistentes de los videos de cada usuario (SQLite).

Solo guarda metadata pública: dueño, nombre original, estado y perfil del
video. Los shares viven en las parties; el resultado, en result-storage.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from threading import RLock
import time
from typing import Any
from uuid import UUID, uuid4

UPLOADING = "UPLOADING"      # el navegador todavía detecta y sube shares
QUEUED = "QUEUED"            # shares completos; esperando turno MPC
PROCESSING = "PROCESSING"    # MP-SPDZ procesa el video
COMPLETED = "COMPLETED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"
TERMINAL = {COMPLETED, FAILED, CANCELLED}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class JobStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.getenv("DELTA_COORDINATOR_DB", "data/coordinator/jobs.sqlite3"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS jobs ("
                " id TEXT PRIMARY KEY, owner TEXT NOT NULL, filename TEXT NOT NULL,"
                " status TEXT NOT NULL, metadata TEXT NOT NULL, counts TEXT NOT NULL DEFAULT '{}',"
                " result_id TEXT, error TEXT, touched REAL NOT NULL, queued_at TEXT,"
                " created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner, created_at)")
            db.execute("CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, created_at)")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["metadata"] = json.loads(item["metadata"])
        item["counts"] = json.loads(item["counts"])
        return item

    def create(self, owner: str, filename: str, metadata: dict[str, Any]) -> dict[str, Any]:
        job_id, now = str(uuid4()), now_iso()
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO jobs(id,owner,filename,status,metadata,touched,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (job_id, owner, filename, UPLOADING, json.dumps(metadata), time.time(), now, now),
            )
        return self.get(job_id)  # type: ignore[return-value]

    def get(self, job_id: UUID | str) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            return self._row(db.execute("SELECT * FROM jobs WHERE id=?", (str(job_id),)).fetchone())

    def list_for(self, owner: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT * FROM jobs WHERE owner=? ORDER BY created_at DESC LIMIT 200", (owner,)
            ).fetchall()
        return [self._row(row) for row in rows]  # type: ignore[misc]

    def update(self, job_id: UUID | str, **fields: Any) -> dict[str, Any] | None:
        if "counts" in fields:
            fields["counts"] = json.dumps(fields["counts"])
        fields["updated_at"] = now_iso()
        columns = ", ".join(f"{name}=?" for name in fields)
        with self._lock, self._connect() as db:
            db.execute(f"UPDATE jobs SET {columns} WHERE id=?", (*fields.values(), str(job_id)))
        return self.get(job_id)

    def transition(self, job_id: UUID | str, expected: set[str], status: str, **fields: Any) -> bool:
        """Cambia de estado solo si el actual está en ``expected`` (atómico)."""

        with self._lock:
            job = self.get(job_id)
            if job is None or job["status"] not in expected:
                return False
            self.update(job_id, status=status, **fields)
            return True

    def touch(self, job_id: UUID | str) -> None:
        with self._lock, self._connect() as db:
            db.execute("UPDATE jobs SET touched=? WHERE id=?", (time.time(), str(job_id)))

    def next_queued(self) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            return self._row(db.execute(
                "SELECT * FROM jobs WHERE status=? ORDER BY queued_at, created_at LIMIT 1", (QUEUED,)
            ).fetchone())

    def queue_position(self, job: dict[str, Any]) -> int:
        if job["status"] != QUEUED:
            return 0
        with self._lock, self._connect() as db:
            (ahead,) = db.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN (?,?) AND (queued_at < ? OR (queued_at = ? AND created_at < ?))",
                (QUEUED, PROCESSING, job["queued_at"], job["queued_at"], job["created_at"]),
            ).fetchone()
        return int(ahead) + 1

    def stale_uploads(self, lease_seconds: float) -> list[dict[str, Any]]:
        limit = time.time() - lease_seconds
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT * FROM jobs WHERE status=? AND touched<?", (UPLOADING, limit)).fetchall()
        return [self._row(row) for row in rows]  # type: ignore[misc]

    def recover(self) -> None:
        """Tras reiniciar: un MPC interrumpido vuelve al frente de la cola (sus
        shares siguen en las parties; conserva queued_at)."""

        with self._lock, self._connect() as db:
            db.execute("UPDATE jobs SET status=?, updated_at=? WHERE status=?", (QUEUED, now_iso(), PROCESSING))
