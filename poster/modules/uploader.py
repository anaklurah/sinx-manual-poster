"""
Core Multi-Platform Uploader for Sin'X Manual Poster.
Executes the upload of a manual video to all selected social media platforms.
"""
from __future__ import annotations

import asyncio
import json
import random
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from poster.config import get_config
from poster.db.queue import (
    check_and_finalize_post,
    get_post_by_id,
    update_platform_post_status,
    update_post_status,
)
from poster.modules.publisher import get_publisher_class
from poster.modules.telegram_notifier import notify_post_results
from poster.utils.logger import get_logger

logger = get_logger("poster.uploader")


async def publish_manual_post(
    post_id: int,
    db_path: Optional[str] = None,
    author_name: str = "",
) -> Dict[str, Any]:
    """Publish a manual post to all its pending target platforms."""
    cfg = get_config()
    db = db_path or cfg.DB_PATH

    post = get_post_by_id(post_id, db)
    if not post:
        logger.error("[Uploader] Post #%d not found in database.", post_id)
        return {"success": False, "error": f"Post #{post_id} not found"}

    update_post_status(post_id, "uploading", db)

    video_path = Path(post["video_path"])
    if not video_path.exists():
        err_msg = f"File video tidak ditemukan di server: {video_path}"
        logger.error("[Uploader] Post #%d: %s", post_id, err_msg)
        update_post_status(post_id, "failed", db)
        return {"success": False, "error": err_msg}

    title = post.get("title", "")
    description = post.get("description", "")
    tags_raw = post.get("tags", "[]")
    try:
        tags = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
    except Exception:
        tags = []

    account_id = post.get("account_id") or 1
    platforms_map = post.get("platforms", {})
    target_keys = list(platforms_map.keys())

    # Fallback to target_platforms if post_platforms was empty
    if not target_keys and post.get("target_platforms"):
        try:
            target_keys = json.loads(post["target_platforms"])
        except Exception:
            target_keys = []

    if not target_keys:
        logger.warning("[Uploader] Post #%d has no target platforms selected.", post_id)
        update_post_status(post_id, "failed", db)
        return {"success": False, "error": "Tidak ada platform tujuan yang dipilih"}

    success_links: Dict[str, str] = {}
    failed_platforms: List[str] = []

    logger.info("=" * 60)
    logger.info("🚀 [Uploader] Starting publish for Post #%d: '%s'", post_id, title[:50])
    logger.info("🎯 Targets: %s | Account: #%d", ", ".join(target_keys), account_id)
    logger.info("=" * 60)

    for idx, t_key in enumerate(target_keys):
        p_info = platforms_map.get(t_key, {})
        # If already done, skip
        if p_info.get("status") == "done":
            logger.info("[Uploader] Target '%s' already completed. Skipping.", t_key)
            if p_info.get("upload_url"):
                success_links[t_key] = p_info["upload_url"]
            continue

        base_platform = t_key.split("_")[0] if "_" in t_key else t_key
        publisher_cls = get_publisher_class(t_key) or get_publisher_class(base_platform)

        if not publisher_cls:
            err = f"Publisher class for '{t_key}' ({base_platform}) not found or supported."
            logger.error("[Uploader] %s", err)
            update_platform_post_status(post_id, t_key, "failed", error_msg=err, db_path=db)
            failed_platforms.append(t_key)
            continue

        # Inter-platform jitter delay (not for first platform)
        if idx > 0:
            delay = max(10, cfg.DELAY_BETWEEN_PLATFORMS_SEC + random.randint(-5, 10))
            logger.info("[Uploader] Waiting %ds before publishing to next platform (%s)...", delay, t_key)
            await asyncio.sleep(delay)

        update_platform_post_status(post_id, t_key, "uploading", db_path=db)
        logger.info("[Uploader] 🌐 Publishing Post #%d to %s...", post_id, t_key)

        try:
            publisher = publisher_cls(account_id=account_id, target_key=t_key)
            # Ensure upload method is invoked with full arguments
            success = await publisher.upload(
                video_path=str(video_path.resolve()),
                title=title,
                description=description,
                tags=tags,
            )

            if success:
                pub_url = getattr(publisher, "uploaded_url", None) or ""
                update_platform_post_status(post_id, t_key, "done", upload_url=pub_url, db_path=db)
                success_links[t_key] = pub_url
                logger.info("✅ [Uploader] Post #%d successfully published to %s! URL: %s", post_id, t_key, pub_url or "(Pending link)")
            else:
                err = getattr(publisher, "last_error", None) or "Publisher returned failure status (check live logs for details)"
                update_platform_post_status(post_id, t_key, "failed", error_msg=err[:500], db_path=db)
                failed_platforms.append(t_key)
                logger.error("❌ [Uploader] Post #%d failed on %s: %s", post_id, t_key, err)

        except Exception as exc:
            err = f"{type(exc).__name__}: {str(exc)}"
            tb = traceback.format_exc()
            logger.error("❌ [Uploader] Exception while publishing to %s:\n%s", t_key, tb)
            update_platform_post_status(post_id, t_key, "failed", error_msg=err[:500], db_path=db)
            failed_platforms.append(t_key)

    final_status = check_and_finalize_post(post_id, db)
    logger.info("=" * 60)
    logger.info("🏁 [Uploader] Finished Post #%d with final status: [%s]", post_id, final_status.upper())
    logger.info("=" * 60)

    # Send Telegram notification
    try:
        await notify_post_results(
            post_id=post_id,
            title=title,
            success_links=success_links,
            failed_platforms=failed_platforms if failed_platforms else None,
            account_id=account_id,
            author_name=author_name,
        )
    except Exception as tg_err:
        logger.warning("[Uploader] Telegram notification failed: %s", tg_err)

    return {
        "success": final_status in ("done", "partial"),
        "final_status": final_status,
        "success_links": success_links,
        "failed_platforms": failed_platforms,
    }
