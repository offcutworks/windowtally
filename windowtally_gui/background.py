"""Work the window runs off its own thread — a pass reads every source and can take a minute — handed back to the
window's thread for its result: a Qt widget belongs to that thread alone, so no job touches one, and the window's
clock calls ``poll``, which hands each finished job's result, or its failure, to the window there.

One job runs at a time: a second is refused while one runs, and the window keeps the buttons that would start one
enabled and says so, rather than queueing passes behind each other. A job's end always reaches ``poll`` — its result
or the exception it raised — and the job is over before either is handed on, so a handler that fails in its turn
cannot leave a job running for ever.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable

log = logging.getLogger(__name__)


class Background:
    def __init__(self) -> None:
        self._done: queue.Queue = queue.Queue()
        self._running: str | None = None

    @property
    def running(self) -> str | None:
        """The name of the job running, or None."""
        return self._running

    def start(self, name: str, job: Callable[[], Any], deliver: Callable[[Any], None],
              failed: Callable[[BaseException], None]) -> bool:
        """Runs ``job`` on a thread of its own; ``poll`` later calls ``deliver(result)``, or ``failed(error)`` should
        the job raise, on the window's thread. False, and nothing started, while another job runs."""
        if self._running is not None:
            return False
        self._running = name

        def work() -> None:
            try:
                handed = (deliver, job())
            except BaseException as exc:  # a job's failure reaches the window, never vanishes with its thread
                log.exception("%s failed", name)
                handed = (failed, exc)
            self._done.put(handed)

        threading.Thread(target=work, name=f"window-{name}", daemon=True).start()
        return True

    def poll(self) -> None:
        """Hands on every finished job's end; call it on the window's thread."""
        while True:
            try:
                handler, value = self._done.get_nowait()
            except queue.Empty:
                return
            self._running = None
            handler(value)
