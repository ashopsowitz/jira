"""SQLite storage layer for Jira watchlist app."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from jira_client import JiraIssueData


class WatchlistStore:
    def __init__(self, db_path: str = "watchlist.db"):
        self.db_path = Path(db_path)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watchlist (
                    issue_key TEXT PRIMARY KEY,
                    issue_url TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_synced_at TEXT,
                    summary TEXT,
                    status TEXT,
                    sprint TEXT,
                    latest_comment_text TEXT,
                    latest_comment_author TEXT,
                    latest_comment_timestamp TEXT,
                    error_message TEXT
                )
                """
            )

    def add_issue(self, issue_key: str, issue_url: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO watchlist(issue_key, issue_url, created_at)
                VALUES (?, ?, ?)
                """,
                (issue_key, issue_url, now),
            )
            return cur.rowcount > 0

    def remove_issues(self, issue_keys: list[str]) -> int:
        if not issue_keys:
            return 0
        placeholders = ",".join("?" for _ in issue_keys)
        with self._connect() as conn:
            cur = conn.execute(
                f"DELETE FROM watchlist WHERE issue_key IN ({placeholders})",
                issue_keys,
            )
            return cur.rowcount

    def list_issues(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT issue_key, issue_url, summary, status, sprint,
                       latest_comment_text, latest_comment_author,
                       latest_comment_timestamp, created_at, last_synced_at,
                       error_message
                FROM watchlist
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def get_issue_urls(self, issue_keys: list[str]) -> dict[str, str]:
        if not issue_keys:
            return {}
        placeholders = ",".join("?" for _ in issue_keys)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT issue_key, issue_url FROM watchlist WHERE issue_key IN ({placeholders})",
                issue_keys,
            ).fetchall()
        return {r["issue_key"]: r["issue_url"] for r in rows}

    def save_sync_result(self, issue_key: str, issue: JiraIssueData | None, error_message: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            if issue is None:
                conn.execute(
                    """
                    UPDATE watchlist
                    SET last_synced_at = ?, error_message = ?
                    WHERE issue_key = ?
                    """,
                    (now, error_message, issue_key),
                )
                return

            data = asdict(issue)
            conn.execute(
                """
                UPDATE watchlist
                SET summary = ?, status = ?, sprint = ?,
                    latest_comment_text = ?, latest_comment_author = ?, latest_comment_timestamp = ?,
                    last_synced_at = ?, error_message = NULL
                WHERE issue_key = ?
                """,
                (
                    data["summary"],
                    data["status"],
                    data["sprint"],
                    data["latest_comment_text"],
                    data["latest_comment_author"],
                    data["latest_comment_timestamp"],
                    now,
                    issue_key,
                ),
            )

    def seed_demo_data(self) -> None:
        """Insert a tiny local-only sample dataset for UI testing."""
        samples = [
            ("DEMO-1", "https://example.atlassian.net/browse/DEMO-1"),
            ("DEMO-2", "https://example.atlassian.net/browse/DEMO-2"),
        ]
        for issue_key, issue_url in samples:
            self.add_issue(issue_key, issue_url)
