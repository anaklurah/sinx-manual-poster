"""
Publisher Registry for Sin'X Manual Poster.
Maps platform names to their respective Playwright automation classes.
"""
from __future__ import annotations

import importlib
from typing import Optional, Type

from poster.modules.publisher.base import BasePublisher
from poster.utils.logger import get_logger

logger = get_logger(__name__)

PUBLISHER_REGISTRY: dict[str, type[BasePublisher]] = {}

_PLATFORM_MAP = [
    ("youtube", "poster.modules.publisher.youtube", "YouTubePublisher"),
    ("facebook", "poster.modules.publisher.facebook", "FacebookPublisher"),
    ("instagram", "poster.modules.publisher.instagram", "InstagramPublisher"),
    ("twitter", "poster.modules.publisher.twitter", "TwitterPublisher"),
    ("twitter_nsfw", "poster.modules.publisher.twitter_nsfw", "TwitterNSFWPublisher"),
    ("tiktok", "poster.modules.publisher.tiktok", "TikTokPublisher"),
    ("upscrolled", "poster.modules.publisher.upscrolled", "UpscrolledPublisher"),
    ("febspot", "poster.modules.publisher.febspot", "FebspotPublisher"),
    ("tevi", "poster.modules.publisher.tevi", "TeviPublisher"),
]


def load_publishers() -> dict[str, type[BasePublisher]]:
    """Lazy-load publisher classes to avoid startup delays."""
    global PUBLISHER_REGISTRY
    if PUBLISHER_REGISTRY:
        return PUBLISHER_REGISTRY

    for platform, mod_path, cls_name in _PLATFORM_MAP:
        try:
            mod = importlib.import_module(mod_path)
            PUBLISHER_REGISTRY[platform] = getattr(mod, cls_name)
        except Exception as e:
            logger.warning("Could not load publisher for '%s': %s", platform, e)

    return PUBLISHER_REGISTRY


def get_publisher_class(platform_name: str) -> Optional[type[BasePublisher]]:
    """Retrieve publisher class by platform name (e.g. 'youtube', 'tiktok')."""
    registry = load_publishers()
    base_name = platform_name.split("_")[0] if "_" in platform_name and platform_name not in registry else platform_name
    return registry.get(platform_name) or registry.get(base_name)
