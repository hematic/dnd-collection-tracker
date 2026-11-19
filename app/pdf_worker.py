"""Docker entry point for the standalone PDF indexing worker."""
from __future__ import annotations

import logging
import signal
import threading

from . import db, pdf_indexer


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    db.init_db()
    stop_event = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    pdf_indexer.run_worker(stop_event)


if __name__ == "__main__":
    main()
