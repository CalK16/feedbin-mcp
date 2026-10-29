from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_CACHE_PATH = Path.home() / ".cache" / "feedbin-mcp" / "entries.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    feed_id INTEGER,
    title TEXT,
    url TEXT,
    published TEXT,
    created_at TEXT,
    json TEXT NOT NULL,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def default_cache_path() -> Path:
    env = os.environ.get("FEEDBIN_CACHE_PATH")
    if env:
        return Path(env).expanduser()
    return DEFAULT_CACHE_PATH


class EntryCache:
    """SQLite store for full Feedbin entry JSON."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def upsert(self, entry: dict[str, Any]) -> None:
        self.upsert_many([entry])

    def upsert_many(self, entries: list[Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        rows: list[tuple[Any, ...]] = []
        for item in entries:
            if not isinstance(item, dict) or item.get("id") is None:
                continue
            rows.append(
                (
                    int(item["id"]),
                    item.get("feed_id"),
                    item.get("title"),
                    item.get("url"),
                    item.get("published"),
                    item.get("created_at"),
                    json.dumps(item, ensure_ascii=False),
                    now,
                )
            )
        if not rows:
            return
        with self._lock:
            self._conn.executemany(
                """
                INSERT OR REPLACE INTO entries
                    (id, feed_id, title, url, published, created_at, json, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            self._conn.commit()

    def get(self, entry_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT json FROM entries WHERE id = ?",
                (entry_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def get_many(self, ids: list[int]) -> dict[int, dict[str, Any]]:
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT id, json FROM entries WHERE id IN ({placeholders})",
                tuple(ids),
            ).fetchall()
        return {int(entry_id): json.loads(payload) for entry_id, payload in rows}

    def missing_ids(self, ids: list[int]) -> list[int]:
        present = self.get_many(ids)
        return [entry_id for entry_id in ids if entry_id not in present]

    def list_entries(
        self,
        *,
        feed_id: int | None = None,
        limit: int = 50,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT json FROM entries WHERE 1=1"
        params: list[Any] = []
        if feed_id is not None:
            sql += " AND feed_id = ?"
            params.append(feed_id)
        if search:
            sql += " AND title LIKE ? COLLATE NOCASE"
            params.append(f"%{search}%")
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [json.loads(row[0]) for row in rows]

    def set_last_poll_at(self, when: str | None = None) -> None:
        value = when if when is not None else datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_poll_at', ?)",
                (value,),
            )
            self._conn.commit()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = 'last_poll_at'"
            ).fetchone()
        return {
            "count": int(count),
            "path": str(self.path),
            "last_poll_at": row[0] if row else None,
        }
