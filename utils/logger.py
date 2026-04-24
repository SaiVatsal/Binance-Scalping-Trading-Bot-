"""
Structured logging with rotation and color output.
"""

import os
import sys
import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone

from config import settings


# ──────────────────────────────────────────────
# Custom log levels
# ──────────────────────────────────────────────
TRADE = 25
SIGNAL = 23
RISK = 22

logging.addLevelName(TRADE, "TRADE")
logging.addLevelName(SIGNAL, "SIGNAL")
logging.addLevelName(RISK, "RISK")


class ColorFormatter(logging.Formatter):
    """Console formatter with ANSI colors."""

    COLORS = {
        "DEBUG": "\033[90m",      # Gray
        "INFO": "\033[36m",       # Cyan
        "SIGNAL": "\033[35m",     # Magenta
        "RISK": "\033[33m",       # Yellow
        "TRADE": "\033[32m",      # Green
        "WARNING": "\033[33m",    # Yellow
        "ERROR": "\033[31m",      # Red
        "CRITICAL": "\033[41m",   # Red background
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelname, "")
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        msg = f"{color}{timestamp} [{record.levelname:<7}] {record.name}: {record.getMessage()}{self.RESET}"
        if record.exc_info:
            msg += f"\n{self.formatException(record.exc_info)}"
        return msg


class JSONFormatter(logging.Formatter):
    """File formatter outputting structured JSON lines."""

    def format(self, record):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if hasattr(record, "trade_data"):
            entry["trade"] = record.trade_data
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def get_logger(name: str) -> logging.Logger:
    """Create a logger with console + rotating file handlers."""

    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG)
    console.setFormatter(ColorFormatter())
    logger.addHandler(console)

    # File handler
    os.makedirs(settings.LOG_DIR, exist_ok=True)
    log_path = os.path.join(settings.LOG_DIR, f"{name}.jsonl")
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=settings.LOG_MAX_BYTES,
        backupCount=settings.LOG_BACKUP_COUNT,
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JSONFormatter())
    logger.addHandler(file_handler)

    # Convenience methods
    def trade(msg, *args, **kwargs):
        trade_data = kwargs.pop("trade_data", None)
        if trade_data:
            extra = kwargs.get("extra", {})
            extra["trade_data"] = trade_data
            kwargs["extra"] = extra
        logger.log(TRADE, msg, *args, **kwargs)

    def signal(msg, *args, **kwargs):
        logger.log(SIGNAL, msg, *args, **kwargs)

    def risk(msg, *args, **kwargs):
        logger.log(RISK, msg, *args, **kwargs)

    logger.trade = trade
    logger.signal = signal
    logger.risk = risk

    return logger
