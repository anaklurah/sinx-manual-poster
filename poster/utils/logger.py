"""
Structured Logging Setup for Sin'X Manual Poster.
"""
from __future__ import annotations

import logging
from pathlib import Path
try:
    from rich.console import Console
    from rich.logging import RichHandler
    console: Console = Console(stderr=True)
    HAS_RICH = True
except ImportError:
    console = None
    HAS_RICH = False

_LOG_FORMAT: str = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: str | int = "INFO",
    log_file: str | Path | None = None,
) -> logging.Logger:
    root_logger = logging.getLogger()

    numeric_level: int = (
        level if isinstance(level, int) else getattr(logging, str(level).upper(), logging.INFO)
    )
    root_logger.setLevel(numeric_level)

    custom_handlers = [h for h in root_logger.handlers if "SSE" in h.__class__.__name__]
    root_logger.handlers.clear()
    for h in custom_handlers:
        root_logger.addHandler(h)

    if HAS_RICH and console is not None:
        rich_handler = RichHandler(
            console=console,
            level=numeric_level,
            show_time=True,
            show_level=True,
            show_path=False,
            rich_tracebacks=True,
        )
        root_logger.addHandler(rich_handler)
    else:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(numeric_level)
        stream_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
        root_logger.addHandler(stream_handler)

    if log_file is not None:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_path), mode="a", encoding="utf-8")
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
        root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
