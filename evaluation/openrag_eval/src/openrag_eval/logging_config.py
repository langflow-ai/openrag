"""Shared logging configuration for openrag_eval."""

import logging


class ShortNameFormatter(logging.Formatter):
    """Custom formatter that shows only the last part of the logger name."""

    def format(self, record: logging.LogRecord) -> str:
        # Extract just the module name (last part after the last dot)
        if "." in record.name:
            record.name = record.name.split(".")[-1]
        return super().format(record)


def init_logger() -> None:
    """Initialize logging configuration with custom format."""
    handler = logging.StreamHandler()
    handler.setFormatter(
        ShortNameFormatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler],
    )

