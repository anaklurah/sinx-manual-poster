"""
FastAPI Backend Server for Sin'X Manual Poster.
Provides RESTful APIs for Manual Content Ingestion, Multi-Platform Publishing,
Scheduling, Multi-Tenant Cookie Management, and Real-time SSE Logs.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import poster.auth as auth_module
from poster.config import get_config
from poster.db.models import init_db
from poster.db.queue import (
    create_account,
    create_platform_target,
    create_post,
    delete_platform_target,
    delete_post,
    get_account_settings,
    get_platform_target,
    get_post_by_id,
    get_stats,
    list_accounts,
    list_platform_targets,
    list_posts,
    update_account_settings,
    update_platform_target,
    update_post_status,
)
from poster.modules.publisher.cookie_loader import export_netscape_cookies, load_cookies
from poster.modules.scheduler import PostScheduler
from poster.modules.uploader import publish_manual_post
from poster.utils.hardware import get_system_info
from poster.utils.logger import get_logger

logger = get_logger("poster.web")

# ---------------------------------------------------------------------------
# SSE Log Streamer
# ---------------------------------------------------------------------------

class SSELogHandler(logging.Handler):
    """Broadcasts logs to connected SSE clients in real-time."""

    def __init__(self, max_backlog: int = 200):
        super().__init__()
        self.queues: list[asyncio.Queue] = []
        self.backlog: list[dict] = []
        self.max_backlog = max_backlog

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            entry = {
                "time": datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
                "level": record.levelname,
                "name": record.name,
                "msg": msg,
            }
            self.backlog.append(entry)
            if len(self.backlog) > self.max_backlog:
                self.backlog.pop(0)

            for q in list(self.queues):
                try:
                    q.put_nowait(entry)
                except asyncio.QueueFull:
                    pass
        except Exception:
            self.handleError(record)


sse_log_handler = SSELogHandler()
sse_log_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(sse_log_handler)

# Background scheduler instance
scheduler = PostScheduler()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_config()
    cfg.ensure_directories()
    init_db(cfg.DB_PATH)
    auth_module.ensure_default_admin(cfg.DB_PATH)

    # Start background scheduler for scheduled posts
    scheduler.start()
    logger.info("✨ Sin'X Manual Poster server ready on http://%s:%d", cfg.HOST, cfg.PORT)

    yield

    scheduler.stop()


app = FastAPI(
    title="Sin'X Manual Poster",
    description="Dedicated Social Media Publishing for Manually-Edited Videos",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Auth Dependency Helpers
# ---------------------------------------------------------------------------

def _resolve_token(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    x_tok = request.headers.get("X-Auth-Token", "").strip()
    if x_tok:
        return x_tok
    q_tok = request.query_params.get("token", "").strip()
    return q_tok or None


def require_auth(request: Request) -> dict:
    token = _resolve_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Autentikasi dibutuhkan. Silakan login.")
    cfg = get_config()
    user = auth_module.validate_token(cfg.DB_PATH, token)
    if not user:
        raise HTTPException(status_code=401, detail="Sesi login kedaluwarsa. Silakan login ulang.")
    return user


def require_admin(request: Request) -> dict:
    user = require_auth(request)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Akses ditolak: Hanya Admin yang diizinkan.")
    return user


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class AdminCreateUserRequest(BaseModel):
    username: str
    password: str
    account_name: Optional[str] = None
    is_admin: bool = False


class CreatePostRequest(BaseModel):
    title: str
    description: str = ""
    tags: List[str] = Field(default_factory=list)
    video_path: str
    video_filename: str
    video_size_bytes: int = 0
    target_platforms: List[str] = Field(default_factory=list)
    scheduled_at: Optional[str] = None  # e.g. "2026-10-30 15:30:00"
    post_now: bool = False


class UserSettingsRequest(BaseModel):
    timezone: Optional[str] = None
    delay_between_platforms_sec: Optional[int] = None
    telegram_enabled: Optional[bool] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    proxy_url: Optional[str] = None


class TelegramTestRequest(BaseModel):
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None


class TargetUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    name: Optional[str] = None


class CreateTargetRequest(BaseModel):
    target_key: str
    platform: str
    name: str


# ---------------------------------------------------------------------------
# Auth Routes
# ---------------------------------------------------------------------------

@app.post("/api/auth/login")
async def login(req: LoginRequest):
    cfg = get_config()
    user = auth_module.get_user_by_username(cfg.DB_PATH, req.username)
    if not user or not auth_module.verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Username atau password salah.")
    token = auth_module.create_session(cfg.DB_PATH, user["id"], user["account_id"])
    logger.info("User '%s' logged in (account_id=%d)", user["username"], user["account_id"])
    return {
        "success": True,
        "token": token,
        "username": user["username"],
        "account_id": user["account_id"],
        "is_admin": bool(user["is_admin"]),
        "message": f"Selamat datang, {user['username']}!",
    }


@app.post("/api/auth/logout")
async def logout(request: Request):
    token = _resolve_token(request)
    if token:
        auth_module.revoke_token(get_config().DB_PATH, token)
    return {"success": True, "message": "Berhasil logout."}


@app.get("/api/auth/me")
async def get_current_user_info(current_user: dict = Depends(require_auth)):
    return {
        "username": current_user["username"],
        "account_id": current_user["account_id"],
        "is_admin": bool(current_user.get("is_admin", False)),
    }


@app.post("/api/auth/change-password")
async def change_password(req: ChangePasswordRequest, current_user: dict = Depends(require_auth)):
    cfg = get_config()
    user = auth_module.get_user_by_username(cfg.DB_PATH, current_user["username"])
    if not user or not auth_module.verify_password(req.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="Password lama tidak sesuai.")
    auth_module.update_user_password(cfg.DB_PATH, user["id"], req.new_password)
    return {"success": True, "message": "Password berhasil diperbarui."}


# ---------------------------------------------------------------------------
# Admin Routes
# ---------------------------------------------------------------------------

@app.get("/api/admin/users")
async def list_users_admin(current_user: dict = Depends(require_admin)):
    cfg = get_config()
    users = auth_module.list_users(cfg.DB_PATH)
    return {"users": users}


@app.post("/api/admin/users")
async def create_user_admin(req: AdminCreateUserRequest, current_user: dict = Depends(require_admin)):
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password minimal 6 karakter.")
    cfg = get_config()
    acc_name = (req.account_name or req.username).strip()
    existing_accs = {a["name"].lower(): a for a in list_accounts(cfg.DB_PATH)}
    if acc_name.lower() in existing_accs:
        acc_id = existing_accs[acc_name.lower()]["id"]
    else:
        new_acc = create_account(acc_name, cfg.DB_PATH)
        acc_id = new_acc["id"]

    try:
        user = auth_module.create_user(cfg.DB_PATH, req.username, req.password, acc_id, req.is_admin)
        return {"success": True, "user": user, "message": f"Akun karyawan '{req.username}' berhasil dibuat!"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/admin/users/{user_id}")
async def delete_user_admin(user_id: int, current_user: dict = Depends(require_admin)):
    cfg = get_config()
    if current_user.get("id") == user_id:
        raise HTTPException(status_code=400, detail="Tidak dapat menghapus akun Anda sendiri.")
    success = auth_module.delete_user(cfg.DB_PATH, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="User tidak ditemukan.")
    return {"success": True, "message": "User berhasil dihapus."}


@app.get("/api/admin/audit-logs")
async def list_audit_logs(current_user: dict = Depends(require_admin)):
    cfg = get_config()
    logs = auth_module.get_audit_logs(cfg.DB_PATH, limit=100)
    return {"logs": logs}


# ---------------------------------------------------------------------------
# Video Upload & Post CRUD Routes
# ---------------------------------------------------------------------------

@app.post("/api/posts/upload-video")
async def upload_video_file(file: UploadFile = File(...), current_user: dict = Depends(require_auth)):
    """Accepts a manual video file (.mp4, .mov, etc.) and streams it to uploads/ directory."""
    cfg = get_config()
    cfg.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    original_name = file.filename or "video.mp4"
    ext = Path(original_name).suffix.lower() or ".mp4"
    if ext not in (".mp4", ".mov", ".mkv", ".webm", ".avi"):
        raise HTTPException(status_code=400, detail="Format file tidak didukung. Harap upload video (.mp4, .mov, .webm)")

    unique_name = f"{uuid.uuid4().hex[:12]}_{original_name.replace(' ', '_')}"
    save_path = cfg.UPLOADS_DIR / unique_name

    total_bytes = 0
    chunk_size = 1024 * 1024  # 1MB
    async with aiofiles.open(save_path, "wb") as out_file:
        while content := await file.read(chunk_size):
            await out_file.write(content)
            total_bytes += len(content)

    logger.info("Uploaded manual video file '%s' (%d bytes) by user '%s'", unique_name, total_bytes, current_user["username"])
    return {
        "success": True,
        "video_path": str(save_path.resolve()),
        "video_filename": unique_name,
        "original_filename": original_name,
        "video_size_bytes": total_bytes,
        "video_url": f"/uploads/{unique_name}",
    }


@app.post("/api/posts")
async def create_new_post(req: CreatePostRequest, current_user: dict = Depends(require_auth)):
    """Create a manual post entry. If post_now is True, immediate multi-platform publishing is fired."""
    cfg = get_config()
    acc_id = current_user.get("account_id") or 1

    if not req.title.strip():
        raise HTTPException(status_code=400, detail="Judul video wajib diisi.")
    if not req.video_path or not Path(req.video_path).exists():
        raise HTTPException(status_code=400, detail="File video belum diunggah atau tidak ditemukan di server.")
    if not req.target_platforms:
        raise HTTPException(status_code=400, detail="Pilih minimal 1 platform tujuan publikasi.")

    post = create_post(
        title=req.title,
        video_path=req.video_path,
        video_filename=req.video_filename,
        target_platforms=req.target_platforms,
        description=req.description,
        tags=req.tags,
        scheduled_at=req.scheduled_at if not req.post_now else None,
        account_id=acc_id,
        video_size_bytes=req.video_size_bytes,
        db_path=cfg.DB_PATH,
    )

    auth_module.log_audit_event(
        cfg.DB_PATH,
        action="CREATE_POST",
        details=f"Post #{post['id']}: '{req.title[:40]}' -> {', '.join(req.target_platforms)} (Post Now: {req.post_now})",
        user_id=current_user.get("id"),
        username=current_user.get("username", ""),
        account_id=acc_id,
    )

    # If post_now is requested, trigger background publish task immediately
    if req.post_now:
        asyncio.create_task(
            publish_manual_post(post["id"], cfg.DB_PATH, author_name=current_user.get("username", ""))
        )
        msg = f"Post #{post['id']} berhasil dibuat dan proses publikasi ke {len(req.target_platforms)} platform dimulai!"
    else:
        msg = f"Post #{post['id']} berhasil dijadwalkan untuk {req.scheduled_at}!"

    return {"success": True, "post": post, "message": msg}


@app.get("/api/posts")
async def list_posts_endpoint(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    current_user: dict = Depends(require_auth),
):
    cfg = get_config()
    offset = (page - 1) * limit
    acc_filter = None if current_user.get("is_admin") else current_user["account_id"]
    posts, total = list_posts(account_id=acc_filter, status=status, limit=limit, offset=offset, db_path=cfg.DB_PATH)
    return {
        "posts": posts,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit if total > 0 else 1,
    }


@app.get("/api/posts/{post_id}")
async def get_post_detail(post_id: int, current_user: dict = Depends(require_auth)):
    cfg = get_config()
    post = get_post_by_id(post_id, cfg.DB_PATH)
    if not post:
        raise HTTPException(status_code=404, detail="Postingan tidak ditemukan.")
    if not current_user.get("is_admin") and post.get("account_id") != current_user["account_id"]:
        raise HTTPException(status_code=403, detail="Akses ditolak.")
    return {"post": post}


@app.post("/api/posts/{post_id}/publish")
async def trigger_post_now(post_id: int, current_user: dict = Depends(require_auth)):
    cfg = get_config()
    post = get_post_by_id(post_id, cfg.DB_PATH)
    if not post:
        raise HTTPException(status_code=404, detail="Postingan tidak ditemukan.")
    if not current_user.get("is_admin") and post.get("account_id") != current_user["account_id"]:
        raise HTTPException(status_code=403, detail="Akses ditolak.")

    asyncio.create_task(
        publish_manual_post(post_id, cfg.DB_PATH, author_name=current_user.get("username", ""))
    )
    auth_module.log_audit_event(
        cfg.DB_PATH,
        action="TRIGGER_PUBLISH",
        details=f"Manual trigger publish for Post #{post_id}",
        user_id=current_user.get("id"),
        username=current_user.get("username", ""),
        account_id=current_user["account_id"],
    )
    return {"success": True, "message": f"Proses upload untuk Post #{post_id} telah dimulai! Pantau status di Live Logs."}


@app.delete("/api/posts/{post_id}")
async def delete_post_endpoint(post_id: int, current_user: dict = Depends(require_auth)):
    cfg = get_config()
    post = get_post_by_id(post_id, cfg.DB_PATH)
    if not post:
        raise HTTPException(status_code=404, detail="Postingan tidak ditemukan.")
    if not current_user.get("is_admin") and post.get("account_id") != current_user["account_id"]:
        raise HTTPException(status_code=403, detail="Akses ditolak.")

    delete_post(post_id, clean_file=True, db_path=cfg.DB_PATH)
    return {"success": True, "message": f"Post #{post_id} dan berkas videonya berhasil dihapus."}


# ---------------------------------------------------------------------------
# Platform Targets & Cookies
# ---------------------------------------------------------------------------

@app.get("/api/platforms")
async def get_platforms(current_user: dict = Depends(require_auth)):
    cfg = get_config()
    targets = list_platform_targets(cfg.DB_PATH)
    acc_id = current_user.get("account_id")
    is_employee = bool(acc_id and acc_id > 1)
    target_profiles_dir = (cfg.PROFILES_DIR / f"account_{acc_id}") if is_employee else cfg.PROFILES_DIR

    for t in targets:
        t_key = t["target_key"]
        p_name = t["platform"]

        candidate_files = [
            target_profiles_dir / f"{t_key}_storage.json",
            target_profiles_dir / f"{t_key}_cookies.json",
            target_profiles_dir / f"{t_key}_cookies.txt",
            target_profiles_dir / f"{p_name}_storage.json",
            target_profiles_dir / f"{p_name}_cookies.txt",
            target_profiles_dir / t_key,
        ]
        if not is_employee:
            candidate_files.extend([
                cfg.PROFILES_DIR / f"{t_key}_storage.json",
                cfg.PROFILES_DIR / f"{t_key}_cookies.txt",
                cfg.PROFILES_DIR / t_key,
            ])

        has_auth = False
        for cf in candidate_files:
            if cf.is_dir() and any(cf.iterdir()):
                has_auth = True
                break
            elif cf.is_file() and cf.stat().st_size > 0:
                has_auth = True
                break
        t["auth_configured"] = has_auth

    return {"targets": targets}


@app.patch("/api/platforms/{target_key}")
async def update_platform_endpoint(
    target_key: str,
    req: TargetUpdateRequest,
    current_user: dict = Depends(require_auth),
):
    cfg = get_config()
    target = update_platform_target(target_key, enabled=req.enabled, name=req.name, db_path=cfg.DB_PATH)
    if not target:
        raise HTTPException(status_code=404, detail="Platform target tidak ditemukan.")
    return {"success": True, "target": target}


@app.post("/api/platforms")
async def create_platform_endpoint(req: CreateTargetRequest, current_user: dict = Depends(require_admin)):
    cfg = get_config()
    key = req.target_key.strip().lower().replace(" ", "_")
    try:
        t = create_platform_target(key, req.platform, req.name, db_path=cfg.DB_PATH)
        return {"success": True, "target": t}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Gagal membuat kartu target: {e}")


@app.delete("/api/platforms/{target_key}")
async def delete_platform_endpoint(target_key: str, current_user: dict = Depends(require_admin)):
    cfg = get_config()
    success = delete_platform_target(target_key, cfg.DB_PATH)
    if not success:
        raise HTTPException(status_code=400, detail="Hanya kartu kustom yang dapat dihapus.")
    return {"success": True, "message": f"Target '{target_key}' berhasil dihapus."}


@app.post("/api/platforms/{target_key}/upload-cookies")
async def upload_cookies_endpoint(
    target_key: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(require_auth),
):
    cfg = get_config()
    acc_id = current_user.get("account_id")
    is_employee = bool(acc_id and acc_id > 1)
    target_dir = (cfg.PROFILES_DIR / f"account_{acc_id}") if is_employee else cfg.PROFILES_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="File cookie kosong!")

    filename = (file.filename or "").lower()
    is_json = filename.endswith(".json") or contents.strip().startswith((b"{", b"["))

    if is_json:
        save_path = target_dir / f"{target_key}_storage.json"
        with open(save_path, "wb") as f:
            f.write(contents)
        try:
            parsed = load_cookies(save_path)
            with open(save_path, "w", encoding="utf-8") as sf:
                json.dump({"cookies": parsed, "origins": []}, sf, indent=2)
        except Exception:
            parsed = []
    else:
        save_path = target_dir / f"{target_key}_cookies.txt"
        with open(save_path, "wb") as f:
            f.write(contents)
        try:
            parsed = load_cookies(save_path)
            # generate storage_state.json alongside
            storage_path = target_dir / f"{target_key}_storage.json"
            with open(storage_path, "w", encoding="utf-8") as sf:
                json.dump({"cookies": parsed, "origins": []}, sf, indent=2)
        except Exception:
            parsed = []

    count = len(parsed)
    logger.info("Uploaded %d cookies for target '%s' by user '%s'", count, target_key, current_user["username"])
    return {
        "success": True,
        "target_key": target_key,
        "cookies_count": count,
        "message": f"{count} cookies berhasil diunggah untuk {target_key}!",
    }


@app.post("/api/platforms/{target_key}/upload-profile")
async def upload_profile_endpoint(
    target_key: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(require_auth),
):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Hanya file arsip .zip yang diperbolehkan.")

    cfg = get_config()
    acc_id = current_user.get("account_id")
    is_employee = bool(acc_id and acc_id > 1)
    target_dir = (cfg.PROFILES_DIR / f"account_{acc_id}" / target_key) if is_employee else (cfg.PROFILES_DIR / target_key)
    target_dir.mkdir(parents=True, exist_ok=True)

    contents = await file.read()
    import zipfile
    extracted = 0
    try:
        with zipfile.ZipFile(io.BytesIO(contents)) as zf:
            for member in zf.infolist():
                if member.filename.startswith("/") or ".." in member.filename:
                    continue
                parts = Path(member.filename).parts
                rel_path = Path(*parts[1:]) if len(parts) > 1 and parts[0].lower() == target_key.lower() else Path(*parts)
                if not str(rel_path) or str(rel_path) == ".":
                    continue
                dest = target_dir / rel_path
                if member.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with open(dest, "wb") as dst:
                        dst.write(zf.read(member))
                    extracted += 1
        return {"success": True, "extracted_files": extracted, "message": f"Berhasil mengekstrak {extracted} file profil {target_key}!"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Gagal mengekstrak profil zip: {e}")


# ---------------------------------------------------------------------------
# Dashboard & Settings Routes
# ---------------------------------------------------------------------------

@app.get("/api/status")
async def get_dashboard_status(current_user: dict = Depends(require_auth)):
    cfg = get_config()
    acc_filter = None if current_user.get("is_admin") else current_user["account_id"]
    stats = get_stats(account_id=acc_filter, db_path=cfg.DB_PATH)
    hw = get_system_info()
    return {
        "stats": stats,
        "scheduler_running": scheduler.is_running(),
        "hardware": hw,
        "current_user": {
            "username": current_user["username"],
            "account_id": current_user["account_id"],
            "is_admin": bool(current_user.get("is_admin", False)),
        },
    }


@app.get("/api/user/settings")
async def get_my_settings(current_user: dict = Depends(require_auth)):
    cfg = get_config()
    settings = get_account_settings(current_user["account_id"], cfg.DB_PATH)
    return {"settings": settings}


@app.post("/api/user/settings")
async def save_my_settings(req: UserSettingsRequest, current_user: dict = Depends(require_auth)):
    cfg = get_config()
    d = req.dict(exclude_unset=True)
    updated = update_account_settings(current_user["account_id"], d, cfg.DB_PATH)
    return {"success": True, "settings": updated, "message": "Pengaturan akun berhasil disimpan!"}


@app.post("/api/user/telegram/test")
async def test_telegram_api(req: TelegramTestRequest, current_user: dict = Depends(require_auth)):
    cfg = get_config()
    acc_s = get_account_settings(current_user["account_id"], cfg.DB_PATH)
    token = (req.bot_token or acc_s.get("telegram_bot_token") or "").strip()
    chat_id = str(req.chat_id or acc_s.get("telegram_chat_id") or "").strip()

    if not token or not chat_id:
        raise HTTPException(status_code=400, detail="Bot Token dan Chat ID wajib diisi!")

    from poster.modules.telegram_notifier import test_telegram_connection
    ok, msg = test_telegram_connection(token, chat_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


# ---------------------------------------------------------------------------
# Live SSE Logs
# ---------------------------------------------------------------------------

@app.get("/api/logs/recent")
async def get_recent_logs(current_user: dict = Depends(require_auth)):
    return {"logs": sse_log_handler.backlog[-50:]}


@app.post("/api/logs/clear")
async def clear_logs_endpoint(current_user: dict = Depends(require_auth)):
    sse_log_handler.backlog.clear()
    return {"success": True, "message": "Log backlog berhasil dibersihkan."}


@app.get("/api/logs/stream")
async def stream_live_logs(request: Request):
    token = _resolve_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Auth token required")
    cfg = get_config()
    user = auth_module.validate_token(cfg.DB_PATH, token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")

    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    for entry in sse_log_handler.backlog[-30:]:
        q.put_nowait(entry)
    sse_log_handler.queues.append(q)

    async def _generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    entry = await asyncio.wait_for(q.get(), timeout=20.0)
                    yield f"data: {json.dumps(entry)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            if q in sse_log_handler.queues:
                sse_log_handler.queues.remove(q)

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Static Files & Dashboard SPA
# ---------------------------------------------------------------------------

cfg = get_config()
app.mount("/static", StaticFiles(directory="web/static"), name="static")
app.mount("/uploads", StaticFiles(directory=str(cfg.UPLOADS_DIR)), name="uploads")


@app.get("/")
async def serve_index():
    index_file = Path("web/static/index.html")
    if not index_file.exists():
        return JSONResponse({"status": "ready", "app": "Sin'X Manual Poster"})
    return FileResponse(index_file)
