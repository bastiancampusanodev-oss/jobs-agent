from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    job_url TEXT,
    job_title TEXT,
    company TEXT,
    decision TEXT NOT NULL,
    match_score INTEGER NOT NULL,
    cv_id TEXT,
    payload_json TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_job_runs_url
ON job_runs(job_url)
WHERE job_url IS NOT NULL AND job_url <> '';
"""


class StateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def has_job_url(self, url: str) -> bool:
        if not url:
            return False
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM job_runs WHERE job_url = ? LIMIT 1", (url,)).fetchone()
            return row is not None

    def save_job_result(self, payload: dict[str, Any], *, source: str) -> int:
        job = payload.get("job", {})
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO job_runs(
                    created_at, source, job_url, job_title, company,
                    decision, match_score, cv_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(UTC).isoformat(),
                    source,
                    job.get("url"),
                    job.get("title"),
                    job.get("company"),
                    payload["decision"],
                    payload["match_score"],
                    payload.get("cv_id"),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            return int(cur.lastrowid)

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM job_runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]
