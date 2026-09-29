"""Creates Neat Copies in the background and caches the rendered images."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QPixmap

from ..library import Library, StoredPage
from ..tutor import StudyAssistant, TutorError
from .neat_render import render_neat
from .workers import TaskThread

log = logging.getLogger(__name__)

MAX_PARALLEL = 2


class NeatService(QObject):
    started = Signal(str)          # page id
    ready = Signal(str)            # page id
    failed = Signal(str, str)      # page id, message

    def __init__(self, library: Library, study: StudyAssistant) -> None:
        super().__init__()
        self.library = library
        self.study = study
        self._threads: Dict[str, TaskThread] = {}      # running jobs
        self._finishing: List[TaskThread] = []          # done, waiting for thread exit
        self._queue: List[StoredPage] = []
        self.errors: Dict[str, str] = {}
        self._pixmaps: Dict[str, QPixmap] = {}

    # ------------------------------------------------------------------ state
    def status(self, page: StoredPage) -> str:
        if page.id in self._threads or any(p.id == page.id for p in self._queue):
            return "working"
        if page.id in self.errors:
            return "error"
        return "ready" if page.neat else "missing"

    def pixmap(self, page: StoredPage) -> Optional[QPixmap]:
        if page.id in self._pixmaps:
            return self._pixmaps[page.id]
        if not page.neat:
            return None
        if not page.neat_path.exists():          # transcript saved, image missing
            try:
                render_neat(page.neat.get("blocks", [])).save(str(page.neat_path))
            except OSError:
                return None
        pix = QPixmap(str(page.neat_path))
        if pix.isNull():
            return None
        self._pixmaps[page.id] = pix
        return pix

    @property
    def busy(self) -> int:
        return len(self._threads) + len(self._queue)

    # ------------------------------------------------------------------ jobs
    def request(self, page: StoredPage, force: bool = False) -> None:
        if self.status(page) == "working" or (page.neat and not force):
            return
        self.errors.pop(page.id, None)
        self._pixmaps.pop(page.id, None)
        self._queue.append(page)
        self.started.emit(page.id)
        self._pump()

    def _pump(self) -> None:
        while self._queue and len(self._threads) < MAX_PARALLEL:
            page = self._queue.pop(0)
            thread = TaskThread(lambda p=page: self._work(p))
            thread.succeeded.connect(lambda res, p=page: self._done(p, res))
            thread.finished.connect(lambda t=thread: self._finished(t))
            self._threads[page.id] = thread
            thread.start()

    def _work(self, page: StoredPage):
        """Runs in a worker thread: transcribe, save, render the image."""
        from PIL import Image
        try:
            image = np.array(Image.open(page.image_path).convert("L"))
            neat = self.study.neat_copy(image)
            self.library.update_meta(page, "neat", neat)
            render_neat(neat["blocks"]).save(str(page.neat_path))
            return ("ok", None)
        except TutorError as exc:
            return ("error", str(exc))
        except OSError as exc:
            return ("error", f"Couldn't save the neat copy: {exc}")

    def _done(self, page: StoredPage, result) -> None:
        # Leave the "running" set *before* announcing, so listeners see the new status.
        thread = self._threads.pop(page.id, None)
        if thread is not None:
            self._finishing.append(thread)
        status, message = result or ("error", "Something went wrong.")
        if status == "ok":
            self._pixmaps.pop(page.id, None)
            self.ready.emit(page.id)
        else:
            self.errors[page.id] = message
            self.failed.emit(page.id, message)

    def _finished(self, thread: TaskThread) -> None:
        if thread in self._finishing:
            self._finishing.remove(thread)
        for pid, t in list(self._threads.items()):
            if t is thread:
                del self._threads[pid]
        thread.deleteLater()
        self._pump()

    def wait(self) -> None:
        self._queue.clear()
        for thread in list(self._threads.values()) + list(self._finishing):
            thread.wait(15000)
