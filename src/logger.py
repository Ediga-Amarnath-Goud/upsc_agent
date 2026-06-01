import logging
import logging.handlers
from pathlib import Path


def setup_logging(log_level: str = "INFO", log_dir: str = "./logs") -> logging.Logger:
    """
    Configure application-wide logging.
    
    - Console: INFO+ (colored, concise)
    - File: DEBUG+ (verbose, rotating)
    - File rotation: 5MB per file, 5 backups
    """
    Path(log_dir).mkdir(exist_ok=True)

    logger = logging.getLogger("upsc_agent")
    logger.setLevel(getattr(logging, log_level.upper()))

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        "%(asctime)s │ %(levelname)-8s │ %(name)-20s │ %(message)s",
        datefmt="%H:%M:%S"
    ))

    # File handler (rotating)
    file_handler = logging.handlers.RotatingFileHandler(
        Path(log_dir) / "upsc_agent.log",
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s │ %(levelname)-8s │ %(name)-25s │ %(funcName)-20s │ %(message)s"
    ))

    logger.addHandler(console)
    logger.addHandler(file_handler)

    return logger
