"""
Authentication and Session Management for Sin'X Manual Poster.
"""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from poster.db.models import db_session, get_conn
from poster.utils.logger import get_logger

_log = get_logger(__name__)
TOKEN_EXPIRY_DAYS = 30


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    if not password or not hashed:
        return False
    # Direct match (in case user enters the hash string itself or plaintext match)
    if secrets.compare_digest(password, hashed):
        return True
    # Bcrypt support
    if hashed.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            import bcrypt
            if bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8")):
                return True
        except Exception as e:
            _log.warning(f"Bcrypt verification error: {e}")
    # Standard SHA-256 fallback
    computed = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return secrets.compare_digest(computed, hashed)


def generate_token() -> str:
    return secrets.token_hex(32)


def token_expiry() -> str:
    return (datetime.utcnow() + timedelta(days=TOKEN_EXPIRY_DAYS)).isoformat()


def create_user(
    db_path: str | Path,
    username: str,
    password: str,
    account_id: int = 1,
    is_admin: bool = False,
) -> dict:
    pw_hash = hash_password(password)
    with db_session(db_path) as conn:
        try:
            conn.execute(
                "INSERT INTO users (account_id, username, password_hash, is_admin) VALUES (?, ?, ?, ?)",
                (account_id, username.strip(), pw_hash, 1 if is_admin else 0),
            )
        except sqlite3.IntegrityError as e:
            raise ValueError(f"Username '{username}' sudah ada: {e}")

        row = conn.execute(
            "SELECT id, account_id, username, is_admin, created_at FROM users WHERE username = ? COLLATE NOCASE",
            (username.strip(),),
        ).fetchone()
        return dict(row)


def get_user_by_username(db_path: str | Path, username: str) -> Optional[dict]:
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT id, account_id, username, password_hash, is_admin FROM users WHERE username = ? COLLATE NOCASE",
            (username.strip(),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_users(db_path: str | Path) -> list[dict]:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            """
            SELECT u.id, u.account_id, u.username, u.is_admin, u.created_at, a.name as account_name
            FROM users u
            JOIN accounts a ON u.account_id = a.id
            ORDER BY u.id ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_user(db_path: str | Path, user_id: int) -> bool:
    with db_session(db_path) as conn:
        user_row = conn.execute("SELECT account_id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user_row:
            return False
        account_id = user_row["account_id"]

        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

        if account_id and account_id != 1:
            conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            conn.execute("DELETE FROM account_settings WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM posts WHERE account_id = ?", (account_id,))

        return True


def update_user_password(db_path: str | Path, user_id: int, new_password: str) -> bool:
    pw_hash = hash_password(new_password)
    with db_session(db_path) as conn:
        cur = conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pw_hash, user_id))
        return cur.rowcount > 0


def create_session(db_path: str | Path, user_id: int, account_id: int) -> str:
    token = generate_token()
    expires = token_expiry()
    with db_session(db_path) as conn:
        conn.execute(
            "INSERT INTO sessions (user_id, account_id, token, expires_at) VALUES (?, ?, ?, ?)",
            (user_id, account_id, token, expires),
        )
    return token


def validate_token(db_path: str | Path, token: str) -> Optional[dict]:
    if not token:
        return None
    conn = get_conn(db_path)
    try:
        now = datetime.utcnow().isoformat()
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        conn.commit()

        row = conn.execute(
            """
            SELECT s.user_id, s.user_id AS id, s.account_id, u.username, u.is_admin
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.token = ? AND s.expires_at > ?
            """,
            (token, now),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def revoke_token(db_path: str | Path, token: str) -> None:
    with db_session(db_path) as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def ensure_default_admin(
    db_path: str | Path,
    default_username: str = "adminkd",
    default_password_hash: str = "$2a$10$XDWXg3CgGcwSyIiHP6AS7uJJZhuhIy3LtyV1XnEjiwAwfS68r8wwK",
) -> None:
    conn = get_conn(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()

    if count == 0:
        try:
            with db_session(db_path) as conn:
                conn.execute(
                    "INSERT INTO users (account_id, username, password_hash, is_admin) VALUES (?, ?, ?, 1)",
                    (1, default_username, default_password_hash),
                )
            _log.info(f"Default admin user created: username='{default_username}'")
        except Exception as e:
            _log.error(f"Failed to create default admin: {e}")


def log_audit_event(
    db_path: str | Path,
    action: str,
    details: str = "",
    user_id: int | None = None,
    username: str = "",
    account_id: int | None = None,
    ip_address: str = "",
) -> None:
    try:
        with db_session(db_path) as conn:
            conn.execute(
                """
                INSERT INTO audit_logs (user_id, username, account_id, action, details, ip_address)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, username, account_id, action, details, ip_address),
            )
    except Exception as e:
        _log.debug("Audit log recording error: %s", e)


def get_audit_logs(
    db_path: str | Path,
    limit: int = 100,
    offset: int = 0,
    account_id: int | None = None,
) -> list[dict[str, Any]]:
    with db_session(db_path) as conn:
        if account_id is not None:
            rows = conn.execute(
                """
                SELECT * FROM audit_logs
                WHERE account_id = ?
                ORDER BY id DESC LIMIT ? OFFSET ?
                """,
                (account_id, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]
