from __future__ import annotations

import threading
import time

from . import db
from .config import INDEXER_INTERVAL_S, PROJECTS_DIR


def _loop() -> None:
    while True:
        try:
            db.index_all(PROJECTS_DIR)
        except Exception as e:
            print(f"Indexer error: {e}")
        time.sleep(INDEXER_INTERVAL_S)


def start() -> threading.Thread:
    t = threading.Thread(target=_loop, daemon=True, name="claude-dash-indexer")
    t.start()
    return t
