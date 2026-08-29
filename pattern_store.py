"""
pattern_store.py — persistent storage layer for resume-agent.

Provides a clean abstract interface (StorageBackend) so the backend can be
swapped from SQLite to Firestore without touching any calling code.

Usage:
    from pattern_store import get_storage_backend
    store = get_storage_backend()
    store.save_checkpoint(...)
    store.get_stats()
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import cfg


# ─────────────────────────────────────────────────────────────────────────────
# Data types
# ─────────────────────────────────────────────────────────────────────────────

VALID_TASK_TYPES = {"debugging", "new-feature", "review-response", "refactor", "unclear"}


# ─────────────────────────────────────────────────────────────────────────────
# Abstract interface
# ─────────────────────────────────────────────────────────────────────────────

class StorageBackend(ABC):
    """Abstract storage interface. Implement this to add a new backend."""

    @abstractmethod
    def save_checkpoint(
        self,
        summary: str,
        task_type: str,
        confidence: float,
        next_likely_step: str,
        raw_diff: str = "",
        elapsed_seconds: float | None = None,
    ) -> str:
        """
        Persist a checkpoint and return its unique ID.

        Args:
            summary:           2-3 sentence narrative of what was happening.
            task_type:         One of VALID_TASK_TYPES.
            confidence:        Agent's confidence score 0.0–1.0.
            next_likely_step:  What the developer would likely do next.
            raw_diff:          The git diff that was used to generate the summary.
            elapsed_seconds:   How many seconds elapsed since the last checkpoint.

        Returns:
            Unique checkpoint ID string.
        """

    @abstractmethod
    def get_latest_checkpoint(self) -> dict[str, Any] | None:
        """Return the most recent checkpoint dict, or None if none exist."""

    @abstractmethod
    def get_checkpoint_by_id(self, checkpoint_id: str) -> dict[str, Any] | None:
        """Return a checkpoint by its ID, or None if not found."""

    @abstractmethod
    def get_previous_checkpoint_time(self) -> float | None:
        """
        Return the Unix timestamp (float) of the checkpoint saved *before*
        the most recent one, or None if fewer than 2 checkpoints exist.

        Used to compute elapsed_seconds across separate CLI invocations,
        since in-memory state doesn't persist between `python cli.py` runs.
        """

    @abstractmethod
    def get_stats(self) -> dict[str, dict[str, Any]]:
        """
        Return interruption statistics per task_type.

        Returns:
            {
                "debugging": {
                    "count": 5,
                    "avg_time_before_interrupt": 142.3,   # seconds
                    "recommended_interval": 71,            # seconds
                },
                ...
            }
        """

    @abstractmethod
    def update_interval(self, task_type: str, elapsed_seconds: float) -> None:
        """
        Record that an interruption happened for `task_type` after
        `elapsed_seconds` of work. Used to drive adaptive checkpointing.
        """

    @abstractmethod
    def save_feedback(self, checkpoint_id: str, corrected_type: str) -> None:
        """
        Store user feedback that corrects the inferred task_type.

        Args:
            checkpoint_id:  ID of the checkpoint being corrected.
            corrected_type: The correct task_type the user provided.
        """

    @abstractmethod
    def get_recent_feedback(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        Return the most recent feedback records (newest first).
        Used to inject correction context into future agent calls.
        """

    @abstractmethod
    def get_recent_checkpoints(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        Return the most recent checkpoints (newest first), for browsing history.

        Args:
            limit: Maximum number of checkpoints to return.
        """


# ─────────────────────────────────────────────────────────────────────────────
# SQLite backend
# ─────────────────────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS checkpoints (
    id                    TEXT PRIMARY KEY,
    timestamp             TEXT NOT NULL,
    summary               TEXT NOT NULL,
    task_type             TEXT NOT NULL,
    confidence            REAL NOT NULL,
    next_likely_step      TEXT NOT NULL,
    raw_diff              TEXT DEFAULT '',
    elapsed_seconds       REAL,
    feedback_corrected_type TEXT
);

CREATE TABLE IF NOT EXISTS interruption_stats (
    task_type             TEXT PRIMARY KEY,
    count                 INTEGER NOT NULL DEFAULT 0,
    total_elapsed_seconds REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS feedback_log (
    id             TEXT PRIMARY KEY,
    checkpoint_id  TEXT NOT NULL,
    corrected_type TEXT NOT NULL,
    timestamp      TEXT NOT NULL,
    FOREIGN KEY (checkpoint_id) REFERENCES checkpoints(id)
);
"""


class SQLiteBackend(StorageBackend):
    """SQLite-backed storage. Data lives in `data/checkpoints.db`."""

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or cfg.sqlite_db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA_SQL)

    # ── StorageBackend implementation ─────────────────────────────────────────

    def save_checkpoint(
        self,
        summary: str,
        task_type: str,
        confidence: float,
        next_likely_step: str,
        raw_diff: str = "",
        elapsed_seconds: float | None = None,
    ) -> str:
        checkpoint_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO checkpoints
                    (id, timestamp, summary, task_type, confidence,
                     next_likely_step, raw_diff, elapsed_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint_id,
                    now,
                    summary,
                    task_type,
                    confidence,
                    next_likely_step,
                    raw_diff,
                    elapsed_seconds,
                ),
            )
        return checkpoint_id

    def get_latest_checkpoint(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM checkpoints ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def get_checkpoint_by_id(self, checkpoint_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM checkpoints WHERE id = ?", (checkpoint_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_previous_checkpoint_time(self) -> float | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT timestamp FROM checkpoints ORDER BY timestamp DESC LIMIT 1 OFFSET 1"
            ).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row["timestamp"]).timestamp()

    def get_stats(self) -> dict[str, dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM interruption_stats").fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            d = dict(row)
            count = d["count"]
            total = d["total_elapsed_seconds"]
            avg = total / count if count > 0 else 0.0
            # Recommended interval = half the average time before interruption,
            # clamped to [min_interval, max_interval].
            recommended = int(avg / 2) if avg > 0 else cfg.checkpoint_interval
            recommended = max(cfg.min_checkpoint_interval, min(recommended, cfg.max_checkpoint_interval))
            result[d["task_type"]] = {
                "count": count,
                "avg_time_before_interrupt": round(avg, 1),
                "recommended_interval": recommended,
            }
        return result

    def update_interval(self, task_type: str, elapsed_seconds: float) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO interruption_stats (task_type, count, total_elapsed_seconds)
                VALUES (?, 1, ?)
                ON CONFLICT(task_type) DO UPDATE SET
                    count = count + 1,
                    total_elapsed_seconds = total_elapsed_seconds + excluded.total_elapsed_seconds
                """,
                (task_type, elapsed_seconds),
            )

    def save_feedback(self, checkpoint_id: str, corrected_type: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        feedback_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO feedback_log (id, checkpoint_id, corrected_type, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (feedback_id, checkpoint_id, corrected_type, now),
            )
            # Also update the checkpoint row itself
            conn.execute(
                "UPDATE checkpoints SET feedback_corrected_type = ? WHERE id = ?",
                (corrected_type, checkpoint_id),
            )

    def get_recent_feedback(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT f.corrected_type, f.timestamp,
                       c.summary, c.task_type AS inferred_type
                FROM feedback_log f
                JOIN checkpoints c ON f.checkpoint_id = c.id
                ORDER BY f.timestamp DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_recent_checkpoints(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM checkpoints ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Firestore backend (activate once GCP billing is ready)
# ─────────────────────────────────────────────────────────────────────────────

class FirestoreBackend(StorageBackend):
    """
    Google Cloud Firestore backend.

    Activate by setting STORAGE_BACKEND=firestore in your .env.
    Requires: pip install google-cloud-firestore
              GCP_PROJECT_ID set in .env
              Application Default Credentials configured
                  (run `gcloud auth application-default login`)
    """

    def __init__(self) -> None:
        try:
            from google.cloud import firestore  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "Firestore backend requires `google-cloud-firestore`. "
                "Run: pip install google-cloud-firestore"
            ) from exc
        project = cfg.gcp_project_id or None
        self._db = firestore.Client(project=project)
        self._checkpoints = self._db.collection("checkpoints")
        self._stats = self._db.collection("interruption_stats")
        self._feedback = self._db.collection("feedback_log")

    def save_checkpoint(
        self,
        summary: str,
        task_type: str,
        confidence: float,
        next_likely_step: str,
        raw_diff: str = "",
        elapsed_seconds: float | None = None,
    ) -> str:
        checkpoint_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self._checkpoints.document(checkpoint_id).set(
            {
                "id": checkpoint_id,
                "timestamp": now,
                "summary": summary,
                "task_type": task_type,
                "confidence": confidence,
                "next_likely_step": next_likely_step,
                "raw_diff": raw_diff,
                "elapsed_seconds": elapsed_seconds,
                "feedback_corrected_type": None,
            }
        )
        return checkpoint_id

    def get_latest_checkpoint(self) -> dict[str, Any] | None:
        docs = (
            self._checkpoints.order_by("timestamp", direction="DESCENDING")
            .limit(1)
            .stream()
        )
        for doc in docs:
            return doc.to_dict()
        return None

    def get_checkpoint_by_id(self, checkpoint_id: str) -> dict[str, Any] | None:
        doc = self._checkpoints.document(checkpoint_id).get()
        return doc.to_dict() if doc.exists else None

    def get_previous_checkpoint_time(self) -> float | None:
        docs = list(
            self._checkpoints.order_by("timestamp", direction="DESCENDING")
            .limit(2)
            .stream()
        )
        if len(docs) < 2:
            return None
        return datetime.fromisoformat(docs[1].to_dict()["timestamp"]).timestamp()

    def get_stats(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for doc in self._stats.stream():
            d = doc.to_dict()
            task_type = d.get("task_type", doc.id)
            count = d.get("count", 0)
            total = d.get("total_elapsed_seconds", 0.0)
            avg = total / count if count > 0 else 0.0
            recommended = int(avg / 2) if avg > 0 else cfg.checkpoint_interval
            recommended = max(cfg.min_checkpoint_interval, min(recommended, cfg.max_checkpoint_interval))
            result[task_type] = {
                "count": count,
                "avg_time_before_interrupt": round(avg, 1),
                "recommended_interval": recommended,
            }
        return result

    def update_interval(self, task_type: str, elapsed_seconds: float) -> None:
        from google.cloud import firestore as _fs  # type: ignore

        ref = self._stats.document(task_type)
        ref.set(
            {
                "task_type": task_type,
                "count": _fs.Increment(1),
                "total_elapsed_seconds": _fs.Increment(elapsed_seconds),
            },
            merge=True,
        )

    def save_feedback(self, checkpoint_id: str, corrected_type: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        feedback_id = str(uuid.uuid4())
        self._feedback.document(feedback_id).set(
            {
                "id": feedback_id,
                "checkpoint_id": checkpoint_id,
                "corrected_type": corrected_type,
                "timestamp": now,
            }
        )
        self._checkpoints.document(checkpoint_id).update(
            {"feedback_corrected_type": corrected_type}
        )

    def get_recent_feedback(self, limit: int = 10) -> list[dict[str, Any]]:
        docs = (
            self._feedback.order_by("timestamp", direction="DESCENDING")
            .limit(limit)
            .stream()
        )
        records = []
        for doc in docs:
            d = doc.to_dict()
            # Enrich with checkpoint info
            cp = self.get_checkpoint_by_id(d.get("checkpoint_id", ""))
            if cp:
                d["summary"] = cp.get("summary", "")
                d["inferred_type"] = cp.get("task_type", "")
            records.append(d)
        return records

    def get_recent_checkpoints(self, limit: int = 10) -> list[dict[str, Any]]:
        docs = (
            self._checkpoints.order_by("timestamp", direction="DESCENDING")
            .limit(limit)
            .stream()
        )
        return [doc.to_dict() for doc in docs]


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────

def get_storage_backend() -> StorageBackend:
    """
    Return the configured storage backend.

    Reads STORAGE_BACKEND from config (sqlite | firestore).
    Defaults to SQLite if unrecognised.
    """
    backend = cfg.storage_backend
    if backend == "firestore":
        return FirestoreBackend()
    return SQLiteBackend()