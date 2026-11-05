"""
Telegram Notification Module for Sin'X Manual Poster.
Sends real-time post summaries and published links to Telegram.
"""
from __future__ import annotations

import asyncio
import datetime
import html
from typing import Dict, List, Optional, Tuple

import requests

from poster.config import get_config
from poster.utils.logger import get_logger

logger = get_logger("poster.telegram")


def send_telegram_message_sync(
    text: str,
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = False,
    timeout: int = 15,
) -> bool:
    cfg = get_config()
    token = token or getattr(cfg, "TELEGRAM_BOT_TOKEN", None)
    chat_id = chat_id or getattr(cfg, "TELEGRAM_CHAT_ID", None)

    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        data = resp.json()
        if resp.status_code == 200 and data.get("ok"):
            logger.info("[Telegram] Message sent successfully to chat %s", chat_id)
            return True
        else:
            err_desc = data.get("description", resp.text)
            logger.error("[Telegram] API error (%d): %s", resp.status_code, err_desc)
            # If HTML parsing failed, retry once sending plain text stripped of HTML tags
            if parse_mode and ("parse" in err_desc.lower() or "entity" in err_desc.lower()):
                import re
                clean_text = re.sub(r'<[^>]+>', '', text)
                retry_payload = {
                    "chat_id": chat_id,
                    "text": clean_text,
                    "disable_web_page_preview": disable_web_page_preview,
                }
                retry_resp = requests.post(url, json=retry_payload, timeout=timeout)
                if retry_resp.status_code == 200 and retry_resp.json().get("ok"):
                    logger.info("[Telegram] Sent successfully via plain-text fallback")
                    return True
            return False
    except Exception as exc:
        logger.exception("[Telegram] Failed to send message: %s", exc)
        return False


async def send_telegram_message(
    text: str,
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = False,
) -> bool:
    return await asyncio.to_thread(
        send_telegram_message_sync,
        text=text,
        token=token,
        chat_id=chat_id,
        parse_mode=parse_mode,
        disable_web_page_preview=disable_web_page_preview,
    )


def test_telegram_connection(bot_token: str, chat_id: str) -> Tuple[bool, str]:
    if not bot_token or not chat_id:
        return False, "Bot Token dan Chat ID wajib diisi."

    try:
        me_url = f"https://api.telegram.org/bot{bot_token}/getMe"
        resp = requests.get(me_url, timeout=10)
        me_data = resp.json()
        if not (resp.status_code == 200 and me_data.get("ok")):
            return False, f"Bot Token tidak valid: {me_data.get('description', 'Unknown error')}"

        bot_username = me_data.get("result", {}).get("username", "Bot")
        test_msg = (
            f"🤖 <b>Tes Koneksi Sin'X Manual Poster</b>\n\n"
            f"✅ Bot: <b>@{bot_username}</b>\n"
            f"📅 Waktu: <code>{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n\n"
            f"Notifikasi posting manual berhasil tersambung!"
        )
        ok = send_telegram_message_sync(test_msg, token=bot_token, chat_id=chat_id)
        if ok:
            return True, f"Koneksi berhasil! Pesan tes terkirim ke Telegram via @{bot_username}"
        return False, "Token valid, namun pesan gagal dikirim ke Chat ID. Pastikan Anda sudah klik /start pada bot!"
    except Exception as exc:
        return False, f"Gagal menghubungi server Telegram: {exc}"


async def notify_post_results(
    post_id: int,
    title: str,
    success_links: Dict[str, str],
    failed_platforms: Optional[List[str]] = None,
    account_id: Optional[int] = None,
    author_name: str = "",
) -> None:
    cfg = get_config()
    bot_token = cfg.TELEGRAM_BOT_TOKEN
    chat_id = cfg.TELEGRAM_CHAT_ID

    if account_id:
        try:
            from poster.db.queue import get_account_settings
            acc_s = get_account_settings(account_id, cfg.DB_PATH)
            if acc_s.get("telegram_enabled") and acc_s.get("telegram_bot_token") and acc_s.get("telegram_chat_id"):
                bot_token = acc_s["telegram_bot_token"].strip()
                chat_id = str(acc_s["telegram_chat_id"]).strip()
        except Exception:
            pass

    if not bot_token or not chat_id:
        return

    now_str = datetime.datetime.now().strftime("%d-%m-%Y %H:%M WIB")
    author_tag = f" 👤 <i>Oleh: {html.escape(author_name)}</i>" if author_name else ""

    lines = [
        "🚀 <b>Sin'X Manual Poster — Laporan Publikasi</b>",
        f"📅 <code>{now_str}</code>{author_tag}",
        "───────────────────────────────",
        f"📌 <b>Judul:</b> {html.escape(title[:100])}",
        f"🆔 <b>Post ID:</b> #{post_id}",
        "───────────────────────────────",
    ]

    if success_links:
        lines.append("✅ <b>Berhasil Dipublikasikan:</b>")
        for plat, raw_link in success_links.items():
            p_display = plat.replace("_", " ").title()
            link = (raw_link or "").strip()
            if link and link.startswith("http"):
                escaped_link = html.escape(link)
                lines.append(f"  • <b>{p_display}</b>:\n    🔗 <a href=\"{escaped_link}\">{escaped_link}</a>")
            else:
                lines.append(f"  • <b>{p_display}</b>: Berhasil terupload")

    if failed_platforms:
        lines.append("")
        lines.append("❌ <b>Gagal Upload:</b>")
        for plat in failed_platforms:
            lines.append(f"  • {plat.replace('_', ' ').title()}")

    lines.append("───────────────────────────────")
    text = "\n".join(lines)
    await send_telegram_message(text, token=bot_token, chat_id=chat_id, disable_web_page_preview=False)
