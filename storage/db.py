"""SQLite job/report metadata store."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite

_DB_PATH = os.getenv("DB_PATH", "./competitool.db")


class JobStore:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or _DB_PATH

    async def init(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    session_count INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    report_id TEXT,
                    error TEXT
                )
            """)
            await db.commit()

    async def create(self, job_id: str, url: str, session_count: int = 1) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO jobs (id, url, session_count, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
                (job_id, url, session_count, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()

    async def update_status(
        self,
        job_id: str,
        status: str,
        report_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        completed_at = datetime.now(timezone.utc).isoformat() if status in ("complete", "failed") else None
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """UPDATE jobs
                   SET status = ?, completed_at = ?, report_id = ?, error = ?
                   WHERE id = ?""",
                (status, completed_at, report_id, error, job_id),
            )
            await db.commit()

    async def get(self, job_id: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
