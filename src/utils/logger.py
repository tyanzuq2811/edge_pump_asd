import logging
import os
import sys
from typing import Optional


class FlushFileHandler(logging.FileHandler):
    """FileHandler that flushes after every emit, ideal for nohup/tmux monitoring."""
    def emit(self, record):
        super().emit(record)
        self.flush()


class FlushStreamHandler(logging.StreamHandler):
    """StreamHandler that flushes stdout after every emit."""
    def emit(self, record):
        super().emit(record)
        self.flush()


def setup_logger(
    name: str = "PumpAnomalyDetection",
    log_file: Optional[str] = None,
    level: int = logging.INFO
) -> logging.Logger:
    """
    Sets up a logger with both console and optional file handlers.
    Flushes buffer immediately to support real-time log monitoring (e.g., tail -f).
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid adding duplicate handlers if logger was already initialized
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console Handler (stdout)
    console_handler = FlushStreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    logger.addHandler(console_handler)

    # File Handler
    if log_file:
        log_dir = os.path.dirname(os.path.abspath(log_file))
        os.makedirs(log_dir, exist_ok=True)
        file_handler = FlushFileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        logger.addHandler(file_handler)

    return logger
