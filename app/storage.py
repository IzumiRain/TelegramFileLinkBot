"""On-disk file storage with a small SQLite index.

Layout:
    <storage_dir>/
        files.db          index (token -> metadata)
        files/<token>/<filename>

The token is a random, unguessable id (secrets.token_urlsafe). Knowing a
file's name is never enough to download it — you need its token.
"""
from __future__ import annotations

import secrets
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class StoredFile:
    token: str
    filename: str
    size: int
    mime_type: str | None
    owner_id: int | None
    created_at: float


class FileStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.files_dir = self.root / "files"
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "files.db")
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                token      TEXT PRIMARY KEY,
                filename   TEXT NOT NULL,
                size       INTEGER NOT NULL,
                mime_type  TEXT,
                owner_id   INTEGER,
                created_at REAL NOT NULL
            )
            """
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS allowed_users (
                user_id    INTEGER PRIMARY KEY,
                added_by   INTEGER,
                created_at REAL NOT NULL
            )
            """
        )
        self.db.commit()

    # -- allow-list (managed from the /admin menu) ------------------------
    def seed_allowed_users(self, user_ids, added_by: int | None = None) -> None:
        """Insert ids (e.g. from ALLOWED_USER_IDS env) that are not in the
        table yet. Existing rows are never removed by seeding."""
        for uid in user_ids:
            self.db.execute(
                "INSERT OR IGNORE INTO allowed_users (user_id, added_by, created_at) "
                "VALUES (?, ?, ?)",
                (int(uid), added_by, time.time()),
            )
        self.db.commit()

    def allowed_user_ids(self) -> set[int]:
        rows = self.db.execute("SELECT user_id FROM allowed_users").fetchall()
        return {int(r[0]) for r in rows}

    def is_allowed_user(self, user_id: int) -> bool:
        row = self.db.execute(
            "SELECT 1 FROM allowed_users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row is not None

    def add_allowed_user(self, user_id: int, added_by: int | None = None) -> bool:
        """Add a user. Returns True if newly added, False if already there."""
        cur = self.db.execute(
            "INSERT OR IGNORE INTO allowed_users (user_id, added_by, created_at) "
            "VALUES (?, ?, ?)",
            (int(user_id), added_by, time.time()),
        )
        self.db.commit()
        return cur.rowcount > 0

    def remove_allowed_user(self, user_id: int) -> bool:
        """Remove a user. Returns True if the user was present."""
        cur = self.db.execute(
            "DELETE FROM allowed_users WHERE user_id = ?", (int(user_id),)
        )
        self.db.commit()
        return cur.rowcount > 0

    # -- writing ---------------------------------------------------------
    def new_token(self) -> str:
        return secrets.token_urlsafe(12)

    def path_for(self, token: str, filename: str) -> Path:
        """Where a brand-new file with this token/filename should be saved."""
        directory = self.files_dir / token
        directory.mkdir(parents=True, exist_ok=True)
        return directory / filename

    def register(
        self,
        token: str,
        filename: str,
        size: int,
        mime_type: str | None,
        owner_id: int | None,
    ) -> StoredFile:
        created = time.time()
        self.db.execute(
            "INSERT OR REPLACE INTO files "
            "(token, filename, size, mime_type, owner_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (token, filename, size, mime_type, owner_id, created),
        )
        self.db.commit()
        return StoredFile(token, filename, size, mime_type, owner_id, created)

    # -- reading ---------------------------------------------------------
    def get(self, token: str) -> StoredFile | None:
        row = self.db.execute(
            "SELECT * FROM files WHERE token = ?", (token,)
        ).fetchone()
        return StoredFile(**dict(row)) if row else None

    def absolute_path(self, record: StoredFile) -> Path:
        """Resolve a stored file's path, guaranteeing it stays inside the
        storage directory (defence in depth against path traversal)."""
        path = (self.files_dir / record.token / record.filename).resolve()
        if self.files_dir.resolve() not in path.parents:
            raise ValueError("stored path escapes the storage directory")
        return path

    def list_for_owner(self, owner_id: int, limit: int = 10) -> list[StoredFile]:
        rows = self.db.execute(
            "SELECT * FROM files WHERE owner_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (owner_id, limit),
        ).fetchall()
        return [StoredFile(**dict(r)) for r in rows]

    # -- maintenance -----------------------------------------------------
    def delete(self, record: StoredFile) -> None:
        shutil.rmtree(self.files_dir / record.token, ignore_errors=True)
        self.db.execute("DELETE FROM files WHERE token = ?", (record.token,))
        self.db.commit()

    def delete_expired(self, ttl_hours: int) -> int:
        """Delete files older than ttl_hours. Returns how many were removed."""
        if ttl_hours <= 0:
            return 0
        cutoff = time.time() - ttl_hours * 3600
        rows = self.db.execute(
            "SELECT * FROM files WHERE created_at < ?", (cutoff,)
        ).fetchall()
        for row in rows:
            self.delete(StoredFile(**dict(row)))
        return len(rows)
