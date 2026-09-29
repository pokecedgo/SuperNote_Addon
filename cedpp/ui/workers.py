"""Background threads: the mirror stream (+ ink tracking) and tutor requests."""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from ..config import InkConfig, MirrorConfig
from ..ink import InkTracker, pad_bbox
from ..mirror import FrameSource
from ..tutor import NoteTutor, TutorError, TutorRequest

log = logging.getLogger(__name__)


def gray_to_qimage(gray: np.ndarray) -> QImage:
    h, w = gray.shape
    return QImage(gray.data, w, h, w, QImage.Format_Grayscale8).copy()


class MirrorThread(QThread):
    """Reads frames, keeps reconnecting, and runs the ink tracker while recording."""

    frame_ready = Signal(object)        # QImage
    connected = Signal()
    disconnected = Signal(str)          # reason
    ink_events = Signal(object)         # List[InkEvent]
    pending_changed = Signal(object)    # bbox or None
    page_changed = Signal(int, object)  # new page index, first frame of that page

    def __init__(self, source: FrameSource, mirror_cfg: MirrorConfig, ink_cfg: InkConfig) -> None:
        super().__init__()
        self.source = source
        self.cfg = mirror_cfg
        self.tracker = InkTracker(ink_cfg)
        self._running = True
        self._lock = threading.Lock()
        self._want_start = False
        self._want_stop = False
        self._latest: Optional[np.ndarray] = None
        self._last_pending = None

    # --- called from the UI thread -------------------------------------------
    def start_recording(self) -> None:
        with self._lock:
            self._want_start, self._want_stop = True, False

    def stop_recording(self) -> None:
        with self._lock:
            self._want_stop, self._want_start = True, False

    def latest_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            return None if self._latest is None else self._latest.copy()

    def stop(self) -> None:
        self._running = False
        self.source.close()
        self.wait(4000)

    # --- thread body -----------------------------------------------------------
    def _track(self, full: np.ndarray) -> None:
        with self._lock:
            want_start, want_stop = self._want_start, self._want_stop
            self._want_start = self._want_stop = False
        # Very large mirrors are tracked at half size; boxes are scaled back up.
        scale = 2 if full.shape[0] > self.cfg.track_max_height else 1
        frame = full[::scale, ::scale] if scale > 1 else full
        if want_stop:
            self.tracker.stop()
        if want_start:
            self.tracker.start(frame)
        if not self.tracker.active:
            return
        update = self.tracker.update(frame, time.monotonic())
        if update.page_changed:
            self.page_changed.emit(update.page_index, full.copy())
        pending = update.pending_bbox
        if pending is not None and scale > 1:
            pending = tuple(v * scale for v in pending)
        if pending != self._last_pending:
            self._last_pending = pending
            self.pending_changed.emit(pending)
        if update.events:
            if scale > 1:
                for ev in update.events:
                    ev.bbox = tuple(v * scale for v in ev.bbox)
                    x1, y1, x2, y2 = pad_bbox(ev.bbox, self.tracker.cfg.crop_padding_px,
                                              full.shape)
                    ev.crop, ev.page = full[y1:y2, x1:x2].copy(), full.copy()
            self.ink_events.emit(update.events)

    def run(self) -> None:
        while self._running:
            was_connected = False
            try:
                for frame in self.source.frames():
                    if not self._running:
                        break
                    if not was_connected:
                        was_connected = True
                        self.connected.emit()
                    with self._lock:
                        self._latest = frame
                    self.frame_ready.emit(gray_to_qimage(frame))
                    self._track(frame)
                reason = "The mirror stream ended."
            except OSError as exc:
                reason = f"Can't reach the Supernote ({exc.__class__.__name__})."
            except Exception as exc:  # keep the app alive on unexpected stream data
                log.exception("Mirror thread error")
                reason = f"Mirror error: {exc}"
            if not self._running:
                break
            self.disconnected.emit(reason)
            deadline = time.monotonic() + self.cfg.reconnect_delay_s
            while self._running and time.monotonic() < deadline:
                time.sleep(0.1)


class TutorThread(QThread):
    """One tutor request."""

    done = Signal(int, object)     # comment id, Tip
    failed = Signal(int, str)      # comment id, message

    def __init__(self, tutor: NoteTutor, comment_id: int, request: TutorRequest) -> None:
        super().__init__()
        self.tutor = tutor
        self.comment_id = comment_id
        self.request = request

    def run(self) -> None:
        try:
            self.done.emit(self.comment_id, self.tutor.analyze(self.request))
        except TutorError as exc:
            self.failed.emit(self.comment_id, str(exc))
        except Exception as exc:
            log.exception("Tutor failed")
            self.failed.emit(self.comment_id, f"Something went wrong: {exc}")


class TaskThread(QThread):
    succeeded = Signal(object)

    def __init__(self, fn: Callable[[], object]) -> None:
        super().__init__()
        self.fn = fn

    def run(self) -> None:
        try:
            self.succeeded.emit(self.fn())
        except Exception:
            log.exception("Background task failed")
            self.succeeded.emit(None)
