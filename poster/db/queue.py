"""
Database query and queue operations for Sin'X Manual Poster.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from poster.config import get_config
from poster.db.models import db_session, get_conn


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# Posts CRUD & Management
# ---------------------------------------------------------------------------

def create_post(
    title: str,
    video_path: str,
    video_filename: str,
    target_platforms: list[str],
    description: str = "",
    tags: list[str] | None = None,
    scheduled_at: Optional[str] = None,
    account_id: int = 1,
    video_size_bytes: int = 0,
    db_path: str | Path | None = None,
) -> dict:
    """Create a new manual post record and associated post_platforms entries."""
    cfg = get_config()
    db = db_path or cfg.DB_PATH
    tags_json = json.dumps(tags or [])
    platforms_json = json.dumps(target_platforms)
    status = "scheduled" if scheduled_at else "pending"

    with db_session(db) as conn:
        cursor = conn.execute(
            """
            INSERT INTO posts (
                account_id, title, description, tags, video_path, video_filename,
                video_size_bytes, status, target_platforms, scheduled_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                title.strip(),
                description.strip(),
                tags_json,
                video_path,
                video_filename,
                video_size_bytes,
                status,
                platforms_json,
                scheduled_at,
            ),
        )
        post_id = cursor.lastrowid

        # Insert platform target rows
        for t_key in target_platforms:
            # Determine platform type from target_key
            platform_type = t_key.split("_")[0] if "_" in t_key else t_key
            conn.execute(
                """
                INSERT OR IGNORE INTO post_platforms (post_id, account_id, target_key, platform, status)
                VALUES (?, ?, ?, ?, 'pending')
                """,
                (post_id, account_id, t_key, platform_type),
            )

        row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        return _row_to_dict(row)


def get_post_by_id(post_id: int, db_path: str | Path | None = None) -> Optional[dict]:
    cfg = get_config()
    db = db_path or cfg.DB_PATH
    conn = get_conn(db)
    try:
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not row:
            return None
        post = dict(row)
        # Fetch platform statuses
        pu_rows = conn.execute(
            "SELECT * FROM post_platforms WHERE post_id = ? ORDER BY id ASC",
            (post_id,),
        ).fetchall()
        post["platforms"] = {r["target_key"]: dict(r) for r in pu_rows}
        return post
    finally:
        conn.close()


def list_posts(
    account_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db_path: str | Path | None = None,
) -> tuple[list[dict], int]:
    cfg = get_config()
    db = db_path or cfg.DB_PATH
    conn = get_conn(db)
    try:
        where = []
        params: list[Any] = []

        if account_id is not None:
            where.append("p.account_id = ?")
            params.append(account_id)
        if status:
            where.append("p.status = ?")
            params.append(status)

        where_clause = f"WHERE {' AND '.join(where)}" if where else ""

        count_sql = f"SELECT COUNT(*) FROM posts p {where_clause}"
        total = conn.execute(count_sql, params).fetchone()[0]

        query_sql = f"""
            SELECT p.*, a.name as account_name
            FROM posts p
            LEFT JOIN accounts a ON p.account_id = a.id
            {where_clause}
            ORDER BY p.id DESC
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(query_sql, params + [limit, offset]).fetchall()
        posts = [dict(r) for r in rows]

        if posts:
            p_ids = [p["id"] for p in posts]
            placeholders = ",".join("?" for _ in p_ids)
            pu_rows = conn.execute(
                f"SELECT * FROM post_platforms WHERE post_id IN ({placeholders})",
                p_ids,
            ).fetchall()
            pu_by_pid: dict[int, dict[str, Any]] = {pid: {} for pid in p_ids}
            for pu in pu_rows:
                pu_dict = dict(pu)
                pu_by_pid[pu_dict["post_id"]][pu_dict["target_key"]] = pu_dict

            for p in posts:
                p["platforms"] = pu_by_pid.get(p["id"], {})

        return posts, total
    finally:
        conn.close()


def update_post_status(post_id: int, status: str, db_path: str | Path | None = None) -> None:
    cfg = get_config()
    db = db_path or cfg.DB_PATH
    now = datetime.utcnow().isoformat()
    with db_session(db) as conn:
        if status == "done":
            conn.execute(
                "UPDATE posts SET status = ?, published_at = ?, updated_at = ? WHERE id = ?",
                (status, now, now, post_id),
            )
        else:
            conn.execute(
                "UPDATE posts SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, post_id),
            )


def update_platform_post_status(
    post_id: int,
    target_key: str,
    status: str,
    upload_url: Optional[str] = None,
    error_msg: Optional[str] = None,
    db_path: str | Path | None = None,
) -> None:
    cfg = get_config()
    db = db_path or cfg.DB_PATH
    now = datetime.utcnow().isoformat()
    with db_session(db) as conn:
        conn.execute(
            """
            UPDATE post_platforms
            SET status = ?, upload_url = COALESCE(?, upload_url),
                error_msg = ?, updated_at = ?, attempts = attempts + 1
            WHERE post_id = ? AND target_key = ?
            """,
            (status, upload_url, error_msg, now, post_id, target_key),
        )


def check_and_finalize_post(post_id: int, db_path: str | Path | None = None) -> str:
    """Check all post_platforms and update parent post status."""
    cfg = get_config()
    db = db_path or cfg.DB_PATH
    with db_session(db) as conn:
        rows = conn.execute(
            "SELECT status FROM post_platforms WHERE post_id = ?",
            (post_id,),
        ).fetchall()
        statuses = [r["status"] for r in rows]

        if not statuses:
            final_status = "failed"
        elif all(s == "done" for s in statuses):
            final_status = "done"
        elif any(s == "done" for s in statuses):
            final_status = "partial"
        elif any(s in ("pending", "uploading") for s in statuses):
            final_status = "uploading"
        else:
            final_status = "failed"

        now = datetime.utcnow().isoformat()
        if final_status in ("done", "partial"):
            conn.execute(
                "UPDATE posts SET status = ?, published_at = ?, updated_at = ? WHERE id = ?",
                (final_status, now, now, post_id),
            )
        else:
            conn.execute(
                "UPDATE posts SET status = ?, updated_at = ? WHERE id = ?",
                (final_status, now, post_id),
            )
        return final_status


def delete_post(post_id: int, clean_file: bool = True, db_path: str | Path | None = None) -> bool:
    cfg = get_config()
    db = db_path or cfg.DB_PATH
    with db_session(db) as conn:
        row = conn.execute("SELECT video_path FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not row:
            return False

        if clean_file and row["video_path"]:
            try:
                p = Path(row["video_path"])
                if p.exists() and p.is_file():
                    p.unlink()
            except Exception:
                pass

        conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        return True


def get_due_scheduled_posts(db_path: str | Path | None = None) -> list[dict]:
    """Find scheduled posts whose scheduled_at is <= current local time."""
    cfg = get_config()
    db = db_path or cfg.DB_PATH
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    now_iso = datetime.utcnow().isoformat()

    conn = get_conn(db)
    try:
        # Match against either local time format or ISO format
        rows = conn.execute(
            """
            SELECT * FROM posts
            WHERE status = 'scheduled'
              AND scheduled_at IS NOT NULL
              AND (scheduled_at <= ? OR scheduled_at <= ?)
            ORDER BY scheduled_at ASC
            LIMIT 5
            """,
            (now_str, now_iso),
        ).fetchall()
        posts = [dict(r) for r in rows]
        for p in posts:
            pu_rows = conn.execute(
                "SELECT * FROM post_platforms WHERE post_id = ?",
                (p["id"],),
            ).fetchall()
            p["platforms"] = {r["target_key"]: dict(r) for r in pu_rows}
        return posts
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Platform Targets
# ---------------------------------------------------------------------------

def list_platform_targets(db_path: str | Path | None = None) -> list[dict]:
    cfg = get_config()
    db = db_path or cfg.DB_PATH
    conn = get_conn(db)
    try:
        rows = conn.execute("SELECT * FROM platform_targets ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_platform_target(target_key: str, db_path: str | Path | None = None) -> Optional[dict]:
    cfg = get_config()
    db = db_path or cfg.DB_PATH
    conn = get_conn(db)
    try:
        row = conn.execute("SELECT * FROM platform_targets WHERE target_key = ?", (target_key,)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def update_platform_target(
    target_key: str,
    enabled: Optional[bool] = None,
    name: Optional[str] = None,
    db_path: str | Path | None = None,
) -> Optional[dict]:
    cfg = get_config()
    db = db_path or cfg.DB_PATH
    with db_session(db) as conn:
        updates = []
        params = []
        if enabled is not None:
            updates.append("enabled = ?")
            params.append(1 if enabled else 0)
        if name is not None:
            updates.append("name = ?")
            params.append(name.strip())

        if updates:
            params.append(target_key)
            conn.execute(
                f"UPDATE platform_targets SET {', '.join(updates)} WHERE target_key = ?",
                params,
            )
        row = conn.execute("SELECT * FROM platform_targets WHERE target_key = ?", (target_key,)).fetchone()
        return _row_to_dict(row)


def create_platform_target(
    target_key: str,
    platform: str,
    name: str,
    db_path: str | Path | None = None,
) -> dict:
    cfg = get_config()
    db = db_path or cfg.DB_PATH
    with db_session(db) as conn:
        conn.execute(
            """
            INSERT INTO platform_targets (target_key, platform, name, enabled, is_custom)
            VALUES (?, ?, ?, 1, 1)
            """,
            (target_key.strip(), platform.strip(), name.strip()),
        )
        row = conn.execute("SELECT * FROM platform_targets WHERE target_key = ?", (target_key,)).fetchone()
        return dict(row)


def delete_platform_target(target_key: str, db_path: str | Path | None = None) -> bool:
    cfg = get_config()
    db = db_path or cfg.DB_PATH
    with db_session(db) as conn:
        cur = conn.execute("DELETE FROM platform_targets WHERE target_key = ? AND is_custom = 1", (target_key,))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Account & Settings
# ---------------------------------------------------------------------------

def list_accounts(db_path: str | Path | None = None) -> list[dict]:
    cfg = get_config()
    db = db_path or cfg.DB_PATH
    conn = get_conn(db)
    try:
        rows = conn.execute("SELECT * FROM accounts ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_account(name: str, db_path: str | Path | None = None) -> dict:
    cfg = get_config()
    db = db_path or cfg.DB_PATH
    with db_session(db) as conn:
        cur = conn.execute("INSERT INTO accounts (name, is_active) VALUES (?, 1)", (name.strip(),))
        acc_id = cur.lastrowid
        return {"id": acc_id, "name": name.strip(), "is_active": 1}


def get_account_settings(account_id: int, db_path: str | Path | None = None) -> dict:
    cfg = get_config()
    db = db_path or cfg.DB_PATH
    with db_session(db) as conn:
        row = conn.execute("SELECT * FROM account_settings WHERE account_id = ?", (account_id,)).fetchone()
        if not row:
            conn.execute(
                """
                INSERT OR IGNORE INTO account_settings (
                    account_id, timezone, delay_between_platforms_sec,
                    telegram_enabled, telegram_bot_token, telegram_chat_id, proxy_url
                ) VALUES (?, 'Asia/Jakarta', 25, 0, '', '', '')
                """,
                (account_id,),
            )
            row = conn.execute("SELECT * FROM account_settings WHERE account_id = ?", (account_id,)).fetchone()
        return dict(row) if row else {}


def update_account_settings(account_id: int, settings: dict, db_path: str | Path | None = None) -> dict:
    cfg = get_config()
    db = db_path or cfg.DB_PATH
    get_account_settings(account_id, db)  # ensure exists
    allowed = {
        "timezone", "delay_between_platforms_sec",
        "telegram_enabled", "telegram_bot_token", "telegram_chat_id", "proxy_url"
    }
    updates = []
    params = []
    for k, v in settings.items():
        if k in allowed:
            updates.append(f"{k} = ?")
            if k == "telegram_enabled":
                params.append(1 if v else 0)
            else:
                params.append(v)

    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(account_id)
        with db_session(db) as conn:
            conn.execute(
                f"UPDATE account_settings SET {', '.join(updates)} WHERE account_id = ?",
                params,
            )
    return get_account_settings(account_id, db)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def get_stats(account_id: Optional[int] = None, db_path: str | Path | None = None) -> dict:
    cfg = get_config()
    db = db_path or cfg.DB_PATH
    conn = get_conn(db)
    try:
        acc_filter = "WHERE account_id = ?" if account_id is not None else ""
        params = (account_id,) if account_id is not None else ()

        total = conn.execute(f"SELECT COUNT(*) FROM posts {acc_filter}", params).fetchone()[0]
        scheduled = conn.execute(f"SELECT COUNT(*) FROM posts WHERE status = 'scheduled' {'AND account_id = ?' if account_id is not None else ''}", params).fetchone()[0]
        uploading = conn.execute(f"SELECT COUNT(*) FROM posts WHERE status = 'uploading' {'AND account_id = ?' if account_id is not None else ''}", params).fetchone()[0]
        done = conn.execute(f"SELECT COUNT(*) FROM posts WHERE status = 'done' {'AND account_id = ?' if account_id is not None else ''}", params).fetchone()[0]
        failed = conn.execute(f"SELECT COUNT(*) FROM posts WHERE status = 'failed' {'AND account_id = ?' if account_id is not None else ''}", params).fetchone()[0]

        return {
            "total_posts": total,
            "scheduled": scheduled,
            "uploading": uploading,
            "done": done,
            "failed": failed,
        }
    finally:
        conn.close()
