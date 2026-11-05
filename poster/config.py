"""
Configuration module for Sin'X Manual Poster.
Loads settings from environment variables and config.yaml.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # Server & Port
    HOST: str = "0.0.0.0"
    PORT: int = 8090

    # Paths
    DB_PATH: str = "./data/manual_poster.db"
    UPLOADS_DIR: Path = field(default_factory=lambda: Path("./uploads"))
    PROFILES_DIR: Path = field(default_factory=lambda: Path("./assets/profiles"))
    ASSETS_DIR: Path = field(default_factory=lambda: Path("./assets"))
    DOWNLOAD_DIR: Path = field(default_factory=lambda: Path("./data/downloads"))

    # Browser
    HEADLESS: bool = False
    BROWSER_ENGINE: str = "chromium"
    BROWSER_LOCALE: str = "id-ID"
    BROWSER_TIMEZONE: str = "Asia/Jakarta"

    # Publishing Rate limits & delays
    DELAY_BETWEEN_PLATFORMS_SEC: int = 25
    SCHEDULER_POLL_INTERVAL_SEC: int = 15

    # Proxy
    PROXY_URL: Optional[str] = None

    # Telegram
    TELEGRAM_ENABLED: bool = False
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    def ensure_directories(self) -> None:
        """Create necessary directories if they do not exist."""
        for d in [self.UPLOADS_DIR, self.PROFILES_DIR, self.ASSETS_DIR, self.DOWNLOAD_DIR, Path(self.DB_PATH).parent]:
            d.mkdir(parents=True, exist_ok=True)


_CONFIG_INSTANCE: Optional[Config] = None


def get_config(config_path: str | Path = "config.yaml") -> Config:
    """Return singleton Config instance."""
    global _CONFIG_INSTANCE
    if _CONFIG_INSTANCE is not None:
        return _CONFIG_INSTANCE

    cfg = Config()

    # Load YAML if present
    p = Path(config_path)
    yaml_data: dict[str, Any] = {}
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f) or {}
        except Exception:
            yaml_data = {}

    server_data = yaml_data.get("server", {})
    cfg.HOST = os.environ.get("HOST", server_data.get("host", cfg.HOST))
    cfg.PORT = int(os.environ.get("HOST_PORT") or os.environ.get("PORT") or server_data.get("port", cfg.PORT))

    cfg.DB_PATH = os.environ.get("POSTER_DB_PATH") or os.environ.get("DB_PATH", cfg.DB_PATH)
    cfg.UPLOADS_DIR = Path(os.environ.get("UPLOADS_DIR", "./uploads"))
    cfg.PROFILES_DIR = Path(os.environ.get("PROFILES_DIR", "./assets/profiles"))
    cfg.ASSETS_DIR = Path(os.environ.get("ASSETS_DIR", "./assets"))

    browser_data = yaml_data.get("browser", {})
    cfg.HEADLESS = (
        os.environ.get("HEADLESS", "").lower() in ("1", "true", "yes")
        if "HEADLESS" in os.environ
        else bool(browser_data.get("headless", True))
    )
    cfg.BROWSER_ENGINE = os.environ.get("BROWSER_ENGINE", browser_data.get("engine", "camoufox"))
    cfg.BROWSER_LOCALE = os.environ.get("BROWSER_LOCALE", browser_data.get("locale", "id-ID"))
    cfg.BROWSER_TIMEZONE = os.environ.get("TIMEZONE", browser_data.get("timezone", "Asia/Jakarta"))

    rate_data = yaml_data.get("rate_limits", {})
    cfg.DELAY_BETWEEN_PLATFORMS_SEC = int(
        os.environ.get("DELAY_BETWEEN_PLATFORMS_SEC", rate_data.get("delay_between_platforms_sec", 25))
    )

    sched_data = yaml_data.get("scheduler", {})
    cfg.SCHEDULER_POLL_INTERVAL_SEC = int(
        os.environ.get("SCHEDULER_POLL_INTERVAL_SEC", sched_data.get("poll_interval_sec", 15))
    )

    cfg.PROXY_URL = os.environ.get("PROXY_URL") or yaml_data.get("proxy", {}).get("url") or None

    tg_data = yaml_data.get("telegram", {})
    cfg.TELEGRAM_ENABLED = (
        os.environ.get("TELEGRAM_ENABLED", "").lower() in ("1", "true", "yes")
        if "TELEGRAM_ENABLED" in os.environ
        else bool(tg_data.get("enabled", False))
    )
    cfg.TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", tg_data.get("bot_token", ""))
    cfg.TELEGRAM_CHAT_ID = str(os.environ.get("TELEGRAM_CHAT_ID", tg_data.get("chat_id", "")))

    cfg.ensure_directories()
    _CONFIG_INSTANCE = cfg
    return cfg


def reload_config() -> Config:
    """Clear singleton and re-read config."""
    global _CONFIG_INSTANCE
    _CONFIG_INSTANCE = None
    return get_config()
