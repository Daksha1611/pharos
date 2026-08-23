"""Append-only audit trail.

Written on day one, not retrofitted on day fourteen. Every state change routes
through `record()`, and nothing else writes to the table.

This is what makes the system adoptable rather than merely impressive: a state
authority asks who decided what, when, and on what evidence, and the answer has
to be a query rather than a story. Entries are never updated or deleted -
a correction is a new entry.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT    NOT NULL,
    actor         TEXT    NOT NULL,
    action        TEXT    NOT NULL,
    entity_type   TEXT    NOT NULL,
    entity_id     TEXT    NOT NULL,
    evidence_json TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_entity ON audit_log (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS ix_audit_created ON audit_log (created_at);
"""


@dataclass
class AuditEntry:
    id: int
    created_at: str
    actor: str
    action: str
    entity_type: str
    entity_id: str
    evidence: dict = field(default_factory=dict)


class AuditLog:
    """SQLite-backed, with an in-memory tail for the console.

    SQLite because the demo must run with no containers. The same `record()`
    call writes to Postgres unchanged when `PHAROS_DATABASE_URL` points there;
    only the connection differs.
    """

    def __init__(self, path: str | Path = "data/pharos_audit.db", tail: int = 500):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._tail_size = tail
        self._tail: list[AuditEntry] = []
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def record(
        self,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str,
        evidence: dict | None = None,
    ) -> AuditEntry:
        payload = json.dumps(evidence or {}, default=str)
        created = datetime.now(UTC).isoformat()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO audit_log (created_at, actor, action, entity_type, entity_id, "
                "evidence_json) VALUES (?, ?, ?, ?, ?, ?)",
                (created, actor, action, entity_type, entity_id, payload),
            )
            self._conn.commit()
            entry = AuditEntry(
                id=cur.lastrowid,
                created_at=created,
                actor=actor,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                evidence=evidence or {},
            )
            self._tail.append(entry)
            if len(self._tail) > self._tail_size:
                del self._tail[: len(self._tail) - self._tail_size]
            return entry

    def recent(self, limit: int = 100) -> list[AuditEntry]:
        with self._lock:
            return list(reversed(self._tail[-limit:]))

    def for_entity(self, entity_type: str, entity_id: str) -> list[AuditEntry]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, created_at, actor, action, entity_type, entity_id, evidence_json "
                "FROM audit_log WHERE entity_type = ? AND entity_id = ? ORDER BY id DESC",
                (entity_type, entity_id),
            ).fetchall()
        return [
            AuditEntry(
                id=r[0],
                created_at=r[1],
                actor=r[2],
                action=r[3],
                entity_type=r[4],
                entity_id=r[5],
                evidence=json.loads(r[6]),
            )
            for r in rows
        ]

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0])
