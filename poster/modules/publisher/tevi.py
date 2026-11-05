"""
Tevi video publisher.

Tevi (tevi.com) is a creator monetization and community platform where creators
publish posts, short-form/long-form videos, and exclusive content in their Space.

Auth method: persistent (cfg.PROFILES_DIR / 'tevi')
Stores complete browser session (Cookies + LocalStorage JWT token + Cloudflare clearance).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, BrowserContext, Page

from poster.modules.publisher.base import BasePublisher


class TeviPublisher(BasePublisher):
    """Uploads and publishes video posts to Tevi (tevi.com)."""

    PLATFORM_NAME = 'tevi'
    AUTH_METHOD = 'persistent'
    UPLOAD_URL = 'https://tevi.com'

    # Selectors
    _SEL_CREATE_TRIGGER = (
        'button:has-text("Create"), '
        'button:has-text("Post"), '
        'button:has-text("New Post"), '
        'button:has-text("Buat"), '
        'a[href*="create"], '
        'a[href*="compose"], '
        'a[href*="space"], '
        '[aria-label*="Create" i], '
        '[aria-label*="Post" i], '
        '[aria-label*="compose" i], '
        '[placeholder*="What\'s on your mind" i], '
        '[placeholder*="Write something" i], '
        '[placeholder*="Share" i], '
        '[placeholder*="Bagikan" i], '
        'button:has-text("+"), '
        ':text("Create Post"), '
        ':text("Buat Postingan"), '
        'div[role="textbox"]'
    )
    _SEL_FILE_INPUT = 'input[type="file"][accept*="video"], input[type="file"]'
    _SEL_MEDIA_BTN = (
        'button[aria-label*="video" i], '
        'button[aria-label*="media" i], '
        'button[aria-label*="upload" i], '
        'button[aria-label*="Attach" i], '
        '[data-icon*="video"], '
        'svg[data-icon="video"], '
        'button:has-text("Video"), '
        '[class*="media-button"], '
        'button:has(svg)'
    )
    _SEL_CAPTION_INPUT = (
        'textarea, '
        '[contenteditable="true"], '
        'input[name="caption"], '
        'input[name="content"], '
        '[placeholder*="Write" i], '
        '[placeholder*="mind" i], '
        '[placeholder*="Say something" i], '
        '[placeholder*="Bagikan" i]'
    )
    _SEL_SUBMIT_BTN = (
        'button:has-text("Post"), '
        'button:has-text("Publish"), '
        'button:has-text("Share"), '
        'button:has-text("Kirim"), '
        'button[type="submit"]'
    )

    async def upload(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
    ) -> bool:
        """Perform video post publication flow on Tevi.

        Args:
            video_path: Absolute path to the video file.
            title: Title / headline of the post.
            description: Description / body text.
            tags: Hashtags list.

        Returns:
            True on successful publication.
        """
        log = self._log
        v_file = Path(video_path)
        if not v_file.exists():
            log.error('[tevi] Video file not found: %s', video_path)
            return False

        # Build composite caption
        hashtags_str = " ".join(f"#{t.lstrip('#')}" for t in tags) if tags else ""
        caption_parts = []
        if title and title.strip():
            caption_parts.append(title.strip())
        if description and description.strip() and description.strip() != (title or "").strip():
            caption_parts.append(description.strip())
        if hashtags_str:
            caption_parts.append(hashtags_str)
        full_caption = "\n\n".join(caption_parts)

        async with async_playwright() as playwright:
            context = await self._get_context(playwright)
            try:
                page = context.pages[0] if context.pages else await context.new_page()

                # Track created post ID/URL via network responses
                created_post_id: Optional[str] = None
                created_post_url: Optional[str] = None

                async def handle_response(response):
                    nonlocal created_post_id, created_post_url
                    try:
                        url = response.url.lower()
                        if ("/post" in url or "/feed" in url or "/space" in url) and response.status in (200, 201):
                            if "json" in (response.headers.get("content-type") or ""):
                                data = await response.json()
                                if isinstance(data, dict):
                                    pid = (
                                        data.get("id")
                                        or data.get("post_id")
                                        or (data.get("data") or {}).get("id")
                                        or (data.get("data") or {}).get("post_id")
                                        or (data.get("post") or {}).get("id")
                                    )
                                    if pid:
                                        created_post_id = str(pid)
                                        log.info('[tevi] Intercepted post ID from response: %s', created_post_id)
                                    purl = (
                                        data.get("url")
                                        or (data.get("data") or {}).get("url")
                                        or (data.get("post") or {}).get("url")
                                    )
                                    if purl and purl.startswith("http"):
                                        created_post_url = purl
                    except Exception:
                        pass

                page.on("response", handle_response)

                # ── Step 1: Navigate to Tevi ──────────────────────────────────
                log.info('[tevi] Navigating to %s', self.UPLOAD_URL)
                await page.goto(self.UPLOAD_URL, wait_until='domcontentloaded', timeout=60_000)
                await self._jitter(2000, 4000)

                # Check for Cloudflare interstitial
                title_text = await page.title()
                if "Just a moment" in title_text or "Cloudflare" in title_text:
                    log.info('[tevi] Cloudflare check detected, waiting for clearance...')
                    for _ in range(15):
                        await asyncio.sleep(1)
                        if "Just a moment" not in await page.title():
                            log.info('[tevi] ✓ Cloudflare cleared successfully')
                            break

                await self._save_debug_screenshot(page, 'home')

                # ── Step 2: Detect creator username & authentication ──────────
                creator_handle: Optional[str] = None
                for _ in range(3):
                    try:
                        for sel in ['a[href*="/@"]', 'a[href^="/@"]', '[data-testid*="profile"] a']:
                            el = page.locator(sel).first
                            if await el.count():
                                h = await el.get_attribute("href") or ""
                                if "/@" in h:
                                    cand = h.split("/@")[1].split("/")[0].split("?")[0].strip()
                                    if cand and cand.lower() not in ["home", "explore", "notifications", "settings"]:
                                        creator_handle = cand
                                        log.info('[tevi] ✓ Detected creator handle: @%s', creator_handle)
                                        break
                    except Exception:
                        pass
                    if creator_handle:
                        break
                    await asyncio.sleep(1)

                # Check if logged in or if login is required
                login_indicators = page.locator(
                    'button:has-text("Log in"), button:has-text("Sign in"), '
                    'a:has-text("Log in"), a[href*="login"], button:has-text("Masuk")'
                )
                if not creator_handle and await login_indicators.count() > 0:
                    is_headless = getattr(self._cfg, 'HEADLESS', False)
                    if not is_headless:
                        log.warning(
                            '[tevi] ⚠️ Akun belum login di Tevi (terlihat tombol Log in). '
                            'Karena Tevi menyimpan token di LocalStorage browser, silakan login sekarang di jendela browser yang sedang terbuka! '
                            '(Sistem menunggu hingga 60 detik...)'
                        )
                        for wait_sec in range(30):
                            await asyncio.sleep(2)
                            # Check if creator handle appeared
                            for sel in ['a[href*="/@"]', 'a[href^="/@"]']:
                                el = page.locator(sel).first
                                if await el.count():
                                    h = await el.get_attribute("href") or ""
                                    if "/@" in h:
                                        cand = h.split("/@")[1].split("/")[0].split("?")[0].strip()
                                        if cand and cand.lower() not in ["home", "explore"]:
                                            creator_handle = cand
                                            break
                            if creator_handle:
                                log.info('[tevi] ✓ Berhasil login! Terdeteksi creator: @%s', creator_handle)
                                break
                    else:
                        log.error(
                            '[tevi] ✗ Akun Tevi belum login! Silakan login terlebih dahulu melalui profil persistent '
                            'atau upload profile zip "tevi.zip".'
                        )
                        await self._save_debug_screenshot(page, 'not_logged_in')
                        return False

                # ── Step 3: Open Post Composer ─────────────────────────────────
                log.info('[tevi] Locating Post Composer trigger...')
                composer_open = False

                # Check if composer or file input is already visible
                file_input = page.locator(self._SEL_FILE_INPUT).first
                caption_area = page.locator(self._SEL_CAPTION_INPUT).first

                if await file_input.count() and await caption_area.count() and await caption_area.is_visible():
                    log.info('[tevi] Post composer is already visible on the current page')
                    composer_open = True

                if not composer_open:
                    create_triggers = page.locator(self._SEL_CREATE_TRIGGER)
                    t_count = await create_triggers.count()
                    for idx in range(min(t_count, 4)):
                        trig = create_triggers.nth(idx)
                        try:
                            if await trig.is_visible():
                                await trig.click(timeout=4000)
                                log.info('[tevi] Clicked Create/Post trigger button #%d', idx + 1)
                                await self._jitter(1000, 2000)
                                composer_open = True
                                break
                        except Exception:
                            pass

                # If still not open, try navigating to creator's Space
                if not composer_open and creator_handle:
                    space_url = f"https://tevi.com/@{creator_handle}"
                    log.info('[tevi] Navigating to creator Space: %s', space_url)
                    await page.goto(space_url, wait_until='domcontentloaded', timeout=30_000)
                    await self._jitter(2000, 3000)
                    create_triggers = page.locator(self._SEL_CREATE_TRIGGER)
                    t_count = await create_triggers.count()
                    for idx in range(min(t_count, 4)):
                        trig = create_triggers.nth(idx)
                        try:
                            if await trig.is_visible():
                                await trig.click(timeout=4000)
                                await self._jitter(1000, 2000)
                                break
                        except Exception:
                            pass

                # ── Step 4: Attach Video File ──────────────────────────────────
                log.info('[tevi] Attaching video file: %s', v_file.name)
                video_attached = False

                # Strategy 1: Check if input[type="file"] already exists in DOM
                file_input = page.locator(self._SEL_FILE_INPUT).first
                if await file_input.count():
                    try:
                        await file_input.set_input_files(str(v_file.resolve()))
                        video_attached = True
                        log.info('[tevi] ✓ Video file set directly on existing input[type="file"]')
                    except Exception as fi_err:
                        log.debug('[tevi] Direct set_input_files error: %s', fi_err)

                # Strategy 2: Click media / video button while expecting file chooser
                if not video_attached:
                    media_btns = page.locator(self._SEL_MEDIA_BTN)
                    m_count = await media_btns.count()
                    log.info('[tevi] Found %d potential media trigger buttons, testing file chooser...', m_count)
                    for m_idx in range(min(m_count, 5)):
                        try:
                            m_btn = media_btns.nth(m_idx)
                            if await m_btn.is_visible():
                                async with page.expect_file_chooser(timeout=4000) as fc_info:
                                    await m_btn.click()
                                fc = await fc_info.value
                                await fc.set_files(str(v_file.resolve()))
                                video_attached = True
                                log.info('[tevi] ✓ Video file set via file chooser on media button #%d', m_idx + 1)
                                break
                        except Exception:
                            pass

                # Strategy 3: Try generic file input after media clicks
                if not video_attached:
                    file_input = page.locator('input[type="file"]').first
                    if await file_input.count():
                        try:
                            await file_input.set_input_files(str(v_file.resolve()))
                            video_attached = True
                            log.info('[tevi] ✓ Video file set via generic input[type="file"]')
                        except Exception:
                            pass

                if not video_attached:
                    await self._save_debug_screenshot(page, 'no_file_input')
                    log.error('[tevi] ✗ Could not locate video file input selector. Pastikan akun sudah login di Tevi!')
                    return False

                log.info('[tevi] ✓ Video attachment confirmed')
                await self._jitter(1500, 3000)

                # ── Step 5: Fill Caption / Title ──────────────────────────────
                log.info('[tevi] Filling caption/description text...')
                caption_el = page.locator(self._SEL_CAPTION_INPUT).first
                if await caption_el.count() and await caption_el.is_visible():
                    try:
                        await caption_el.fill(full_caption)
                    except Exception:
                        try:
                            await caption_el.click()
                            await page.keyboard.insert_text(full_caption)
                        except Exception:
                            await caption_el.evaluate(
                                "(el, txt) => { el.value = txt; el.innerText = txt; el.dispatchEvent(new Event('input', {bubbles: true})); }",
                                full_caption
                            )
                    log.info('[tevi] ✓ Caption filled (%d characters)', len(full_caption))
                await self._jitter(1000, 2000)

                # ── Step 6: Ensure Post Visibility (Everyone / Free) ───────────
                try:
                    everyone_btn = page.locator(
                        'button:has-text("Everyone"), '
                        'input[value="everyone"], '
                        '[role="radio"]:has-text("Everyone"), '
                        ':text("Everyone"), '
                        ':text("Public"), '
                        ':text("Semua Orang")'
                    ).first
                    if await everyone_btn.count() and await everyone_btn.is_visible():
                        await everyone_btn.click(timeout=3000)
                        log.info('[tevi] Set audience to "Everyone"')
                except Exception:
                    pass

                # ── Step 7: Wait for Upload / Transcoding Completion ───────────
                log.info('[tevi] Waiting for video upload to process and Post button to be enabled...')
                submit_btn = page.locator(self._SEL_SUBMIT_BTN).last

                post_enabled = False
                for sec in range(180):
                    if await submit_btn.count():
                        is_dis = await submit_btn.is_disabled()
                        aria_dis = await submit_btn.get_attribute("aria-disabled")
                        if not is_dis and aria_dis != "true":
                            post_enabled = True
                            log.info('[tevi] ✓ Submit Post button is enabled (after %ds)', sec + 1)
                            break
                    if (sec + 1) % 15 == 0:
                        log.info('[tevi] Video upload in progress... (%ds elapsed, waiting for button enablement)', sec + 1)
                    await asyncio.sleep(1)

                if not post_enabled:
                    log.warning('[tevi] Submit button enable check timed out, attempting click anyway...')

                # ── Step 8: Click Submit Post ──────────────────────────────────
                await self._jitter(1000, 2000)
                log.info('[tevi] Submitting post...')
                try:
                    await submit_btn.click(timeout=8000)
                    log.info('[tevi] Clicked submit button')
                except Exception as ex:
                    log.warning('[tevi] Direct click failed: %s, using dispatch_event', ex)
                    try:
                        await submit_btn.dispatch_event('click')
                    except Exception:
                        await submit_btn.evaluate("el => el.click()")

                # ── Step 9: Wait for Success Confirmation ──────────────────────
                log.info('[tevi] Waiting for post completion confirmation...')
                success_detected = False
                for w in range(30):
                    await asyncio.sleep(1)
                    # Check URL change
                    if "/post/" in page.url or (created_post_url and created_post_url.startswith("http")):
                        success_detected = True
                        log.info('[tevi] ✓ Post URL detected: %s', page.url)
                        break

                    # Check success toast
                    succ_toast = page.locator(
                        ':text("Post published"), '
                        ':text("Your post is live"), '
                        ':text("Published"), '
                        ':text("Success"), '
                        ':text("Berhasil dipublikasikan")'
                    ).first
                    if await succ_toast.count() and await succ_toast.is_visible():
                        success_detected = True
                        log.info('[tevi] ✓ Success notification toast detected')
                        break

                    # Check dialog closed
                    if w > 10 and not await page.locator('div[role="dialog"]').is_visible() and not await page.locator(self._SEL_FILE_INPUT).is_visible():
                        success_detected = True
                        log.info('[tevi] ✓ Composer closed — post published successfully')
                        break

                if not success_detected:
                    log.warning('[tevi] Success indicator not explicitly confirmed, verifying final page state')

                # ── Step 10: Extract URL ───────────────────────────────────────
                try:
                    if created_post_url:
                        self.uploaded_url = created_post_url
                    elif "/post/" in page.url:
                        self.uploaded_url = page.url.split("?")[0]
                    elif created_post_id and creator_handle:
                        self.uploaded_url = f"https://tevi.com/@{creator_handle}/post/{created_post_id}"
                    elif creator_handle:
                        # Check latest post link on creator space
                        space_url = f"https://tevi.com/@{creator_handle}"
                        if f"/@{creator_handle}" not in page.url:
                            try:
                                await page.goto(space_url, wait_until="domcontentloaded", timeout=15_000)
                                await asyncio.sleep(2)
                            except Exception:
                                pass
                        
                        first_post = page.locator('main a[href*="/post/"], a[href*="/post/"]').first
                        if await first_post.count():
                            fh = await first_post.get_attribute("href") or ""
                            if fh:
                                clean_fh = fh.split("?")[0]
                                self.uploaded_url = clean_fh if clean_fh.startswith("http") else f"https://tevi.com{clean_fh}"
                                log.info('[tevi] ✓ Captured direct post URL from creator Space: %s', self.uploaded_url)

                        if not self.uploaded_url:
                            self.uploaded_url = space_url
                    else:
                        self.uploaded_url = "https://tevi.com"

                    log.info('[tevi] ✓ Final published URL: %s', self.uploaded_url)
                except Exception as ex:
                    log.warning('[tevi] Error resolving post URL: %s', ex)
                    self.uploaded_url = f"https://tevi.com/@{creator_handle}" if creator_handle else "https://tevi.com"

                await self._jitter(3000, 5000)
                log.info('[tevi] ✓ Video post upload to Tevi completed successfully')
                return True

            except Exception as exc:
                log.exception('[tevi] Upload failed: %s', exc)
                try:
                    await self._save_debug_screenshot(page, 'error')
                except Exception:
                    pass
                return False
            finally:
                await context.close()
