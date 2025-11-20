"""Central logging configuration using loguru."""

from __future__ import annotations

from pathlib import Path
from loguru import logger

from mate.config import MateSettings

_LOGGER_CONFIGURED = False


def configure_logging(settings: MateSettings, level: str = "INFO") -> None:
    """Route logs to stderr and rotating file only once."""

    global _LOGGER_CONFIGURED
    if _LOGGER_CONFIGURED:
        return

    log_dir: Path = settings.paths.logs_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(
        sink=lambda msg: print(msg, end=""),
        level=level,
        colorize=True,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    )
    logger.add(
        log_dir / "mate.log",
        level="DEBUG",
        rotation="1 week",
        retention=4,
        compression="zip",
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )

    _LOGGER_CONFIGURED = True


def get_logger(name: str | None = None):
    return logger.bind(context=name or "mate")
