import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure(log_path: str, level=logging.INFO):
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    file_handler = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=5)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    root.addHandler(console_handler)
