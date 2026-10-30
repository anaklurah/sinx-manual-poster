"""
Background Scheduler for Sin'X Manual Poster.
Monitors the database for scheduled posts and triggers publishing when due.
"""
from __future__ import annotations

import asyncio
from typing import Optional, Set

from poster.config import get_config
from poster.db.queue import get_due_scheduled_posts, update_post_status
from poster.modules.uploader import publish_manual_post
from poster.utils.logger import get_logger

logger = get_logger("poster.scheduler")


class PostScheduler:
    """Async background worker that automatically triggers scheduled posts when due."""

    def __init__(self, db_path: Optional[str] = None):
        self.cfg = get_config()
        self.db_path = db_path or self.cfg.DB_PATH
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._active_post_ids: Set[int] = set()

    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.is_running():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("⏱️  [Scheduler] Background post scheduler started (polling every %ds)...", self.cfg.SCHEDULER_POLL_INTERVAL_SEC)

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("🛑 [Scheduler] Background post scheduler stopped.")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                due_posts = get_due_scheduled_posts(self.db_path)
                for post in due_posts:
                    pid = post["id"]
                    if pid in self._active_post_ids:
                        continue

                    self._active_post_ids.add(pid)
                    # Mark post as uploading immediately to prevent duplicate pick up
                    update_post_status(pid, "uploading", self.db_path)
                    logger.info("⏰ [Scheduler] Scheduled post #%d ('%s') is DUE! Launching upload task...", pid, post.get("title", "")[:40])

                    asyncio.create_task(self._process_post(pid))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[Scheduler] Error in poll loop: %s", e)

            await asyncio.sleep(self.cfg.SCHEDULER_POLL_INTERVAL_SEC)

    async def _process_post(self, post_id: int) -> None:
        try:
            await publish_manual_post(post_id, self.db_path, author_name="Automated Scheduler")
        except Exception as e:
            logger.error("[Scheduler] Exception processing post #%d: %s", post_id, e)
        finally:
            self._active_post_ids.discard(post_id)
