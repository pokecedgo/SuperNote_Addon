"""Main window: top bar, mirrored page, comment margin."""
from __future__ import annotations

import logging
import time
from typing import Callable, Dict, List, Optional

import numpy as np
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QVBoxLayout, QWidget)

from ..comments import CommentStore, Status
from ..config import APP_NAME, AppConfig
from ..ink import InkEvent
from ..mirror import DemoNotebookSource, FrameSource, MirrorSource
from ..tutor import NoteTutor, TutorRequest
from . import theme
from .comments_panel import CommentsPanel
from .connect_dialog import DEMO, ConnectDialog
from .page_view import Anchor, PageView
from .workers import MirrorThread, TutorThread

log = logging.getLogger(__name__)


class Logo(QLabel):
    def __init__(self) -> None:
        super().__init__("S")
        self.setFixedSize(30, 30)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(f"background: {theme.INK}; color: {theme.PAPER}; border-radius: 9px; "
                           "font-weight: 800; font-size: 16px;")


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, tutor: NoteTutor,
                 source_factory: Callable[[str], FrameSource],
                 autoconnect: Optional[str] = None) -> None:
        super().__init__()
        self.cfg = config
        self.tutor = tutor
        self.source_factory = source_factory
        self.settings = QSettings("CedPP", "SuperNoteCedPP")
        self.store = CommentStore()
        self.mirror: Optional[MirrorThread] = None
        self.address: Optional[str] = None
        self.recording = False
        self.record_started = 0.0
        self.page_index = 0
        self.selected: Optional[int] = None
        self.page_snapshots: Dict[int, np.ndarray] = {}
        self._tutor_threads: Dict[int, TutorThread] = {}
        self._queue: List[int] = []

        self.setWindowTitle(APP_NAME)
        self.resize(1280, 900)
        self.setMinimumSize(980, 700)
        self._build()

        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick)
        self._clock.start(1000)
        if autoconnect:
            QTimer.singleShot(0, lambda: self._connect_to(autoconnect))

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(62)
        b = QHBoxLayout(bar)
        b.setContentsMargins(20, 10, 20, 10)
        b.setSpacing(12)
        b.addWidget(Logo())
        title = QLabel(APP_NAME)
        title.setObjectName("AppTitle")
        b.addWidget(title)
        b.addSpacing(10)
        self.page_label = QLabel("")
        self.page_label.setObjectName("Muted")
        b.addWidget(self.page_label)
        b.addStretch(1)
        self.conn_pill = QLabel("Not connected")
        self.conn_pill.setObjectName("PillOff")
        b.addWidget(self.conn_pill)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setCursor(Qt.PointingHandCursor)
        self.connect_btn.clicked.connect(self._open_connect)
        b.addWidget(self.connect_btn)
        self.record_btn = QPushButton("●  Record")
        self.record_btn.setObjectName("RecordButton")
        self.record_btn.setCheckable(True)
        self.record_btn.setEnabled(False)
        self.record_btn.setCursor(Qt.PointingHandCursor)
        self.record_btn.setToolTip("Start commenting on everything you write from now on (R)")
        self.record_btn.clicked.connect(self._toggle_record)
        b.addWidget(self.record_btn)
        outer.addWidget(bar)

        body = QHBoxLayout()
        body.setContentsMargins(24, 0, 12, 0)
        body.setSpacing(18)
        body.addStretch(1)
        self.page_view = PageView()
        self.page_view.anchor_clicked.connect(self._select)
        self.page_view.background_clicked.connect(lambda: self._select(None))
        self.page_view.layout_changed.connect(self._relayout)
        body.addWidget(self.page_view)
        self.panel = CommentsPanel()
        self.panel.card_clicked.connect(self._select)
        self.panel.resolve_requested.connect(self._resolve)
        self.panel.retry_requested.connect(self._retry)
        body.addWidget(self.panel)
        body.addStretch(1)
        outer.addLayout(body, 1)

        foot = QHBoxLayout()
        foot.setContentsMargins(24, 4, 24, 8)
        self.status = QLabel("Connect your Supernote to begin.")
        self.status.setObjectName("Small")
        foot.addWidget(self.status)
        foot.addStretch(1)
        self.tutor_label = QLabel(f"Tutor: {self.tutor.name}")
        self.tutor_label.setObjectName("Small")
        foot.addWidget(self.tutor_label)
        outer.addLayout(foot)

        QShortcut(QKeySequence("R"), self, activated=self.record_btn.click)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=lambda: self._select(None))

    def _set_status(self, text: str) -> None:
        self.status.setText(text)

    def _set_pill(self, text: str, on: bool) -> None:
        self.conn_pill.setText(text)
        self.conn_pill.setObjectName("Pill" if on else "PillOff")
        self.conn_pill.style().unpolish(self.conn_pill)
        self.conn_pill.style().polish(self.conn_pill)

    # ------------------------------------------------------------------ connection
    def _open_connect(self) -> None:
        dialog = ConnectDialog(self.settings.value("last_address", ""), self.cfg.mirror.port, self)
        if dialog.exec() and dialog.result_address:
            if dialog.result_address != DEMO:
                self.settings.setValue("last_address", dialog.address.text().strip())
            self._connect_to(dialog.result_address)

    def _connect_to(self, address: str) -> None:
        self._disconnect()
        self.address = address
        source = self.source_factory(address)
        self.mirror = MirrorThread(source, self.cfg.mirror, self.cfg.ink)
        self.mirror.frame_ready.connect(self._on_frame)
        self.mirror.connected.connect(self._on_connected)
        self.mirror.disconnected.connect(self._on_disconnected)
        self.mirror.ink_events.connect(self._on_ink_events)
        self.mirror.pending_changed.connect(self.page_view.set_pending)
        self.mirror.page_changed.connect(self._on_page_changed)
        label = "demo notebook" if address == DEMO else address.split("//")[-1].split("/")[0]
        self._set_pill(f"Connecting to {label}…", False)
        self.page_view.set_message("Connecting…")
        self.mirror.start()

    def _disconnect(self) -> None:
        if self.recording:
            self._stop_recording()
        if self.mirror is not None:
            self.mirror.stop()
            self.mirror = None

    def _on_connected(self) -> None:
        label = ("Demo notebook" if self.address == DEMO
                 else "Mirroring " + self.address.split("//")[-1].split(":")[0])
        self._set_pill("●  " + label, True)
        self.record_btn.setEnabled(True)
        self.connect_btn.setText("Change")
        if not self.recording:
            self._set_status("Connected. Press Record (or R) when you're ready to write.")

    def _on_disconnected(self, reason: str) -> None:
        self._set_pill("Reconnecting…", False)
        self._set_status(f"{reason} Retrying… Keep Screen Mirroring on and stay on the same Wi-Fi.")

    def _on_frame(self, image) -> None:
        resized = image.size() != self.page_view.image_size()
        self.page_view.set_frame(image)
        if resized:
            self._fit_page_width()

    # ------------------------------------------------------------------ recording
    def _toggle_record(self) -> None:
        if self.record_btn.isChecked():
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self) -> None:
        if self.mirror is None:
            self.record_btn.setChecked(False)
            return
        self.recording = True
        self.record_started = time.monotonic()
        self.mirror.start_recording()
        self.page_view.set_recording(True)
        self._tick()
        self._update_page_label()
        self._set_status("Recording — Ced++ comments whenever you pause writing.")

    def _stop_recording(self) -> None:
        self.recording = False
        self.record_btn.setChecked(False)
        self.record_btn.setText("●  Record")
        self.page_view.set_recording(False)
        if self.mirror is not None:
            self.mirror.stop_recording()
            frame = self.mirror.latest_frame()
            if frame is not None:
                self.page_snapshots[self.page_index] = frame
        self._save_session()

    def _save_session(self) -> None:
        if not any(c.status != Status.SKIPPED for c in self.store.comments.values()):
            self._set_status("Recording stopped.")
            return
        try:
            folder = self.store.save_session(self.cfg.sessions_dir, self.page_snapshots)
            self._set_status(f"Recording stopped. Comments saved to {folder.relative_to(folder.parents[1])}/")
        except OSError as exc:
            self._set_status(f"Recording stopped, but saving failed: {exc}")

    def _tick(self) -> None:
        if self.recording:
            s = int(time.monotonic() - self.record_started)
            self.record_btn.setText(f"■  Stop  {s // 60:02d}:{s % 60:02d}")

    def _update_page_label(self) -> None:
        self.page_label.setText(f"Page {self.page_index + 1}")

    def _on_page_changed(self, index: int, first_frame) -> None:
        self.page_index = index
        self.page_snapshots[index] = first_frame
        self._select(None)
        self._update_page_label()
        self._refresh_page_comments()
        self._set_status(f"New page detected — now on page {index + 1}.")

    # ------------------------------------------------------------------ comments
    def _on_ink_events(self, events: List[InkEvent]) -> None:
        for ev in events:
            self.page_snapshots[ev.page_index] = ev.page
            comment = self.store.add(ev.page_index, ev.bbox, ev.crop, ev.page)
            if ev.page_index == self.page_index:
                self.panel.upsert(comment)
            self._queue.append(comment.id)
        self._refresh_anchors()
        self._relayout()
        self._pump()

    def _pump(self) -> None:
        while self._queue and len(self._tutor_threads) < self.cfg.tutor.max_parallel:
            cid = self._queue.pop(0)
            c = self.store.get(cid)
            if c is None or c.status != Status.PENDING:
                continue
            request = TutorRequest(c.crop, c.page, c.bbox,
                                   self.store.history(c.page_index, self.cfg.tutor.history_items))
            thread = TutorThread(self.tutor, cid, request)
            thread.done.connect(self._on_tip)
            thread.failed.connect(self._on_tip_failed)
            thread.finished.connect(lambda cid=cid: self._thread_finished(cid))
            self._tutor_threads[cid] = thread
            thread.start()

    def _thread_finished(self, cid: int) -> None:
        thread = self._tutor_threads.pop(cid, None)
        if thread is not None:
            thread.deleteLater()
        self._pump()

    def _on_tip(self, cid: int, tip) -> None:
        c = self.store.get(cid)
        if c is None or c.status == Status.RESOLVED:
            return
        c.tip = tip
        c.status = Status.SKIPPED if tip.skip else Status.READY
        if tip.skip:
            self.panel.remove(cid)
        elif c.page_index == self.page_index:
            self.panel.upsert(c)
        self._refresh_anchors()
        QTimer.singleShot(0, self._relayout)   # after the card has its final size

    def _on_tip_failed(self, cid: int, message: str) -> None:
        c = self.store.get(cid)
        if c is None:
            return
        c.status, c.error = Status.ERROR, message
        if c.page_index == self.page_index:
            self.panel.upsert(c)
        self._refresh_anchors()
        QTimer.singleShot(0, self._relayout)

    def _retry(self, cid: int) -> None:
        c = self.store.get(cid)
        if c is None:
            return
        c.status, c.error = Status.PENDING, ""
        self.panel.upsert(c)
        self._refresh_anchors()
        self._queue.append(cid)
        self._pump()
        QTimer.singleShot(0, self._relayout)

    def _resolve(self, cid: int) -> None:
        c = self.store.get(cid)
        if c is None:
            return
        c.status = Status.RESOLVED
        self.panel.remove(cid)
        if self.selected == cid:
            self._select(None)
        self._refresh_anchors()
        self._relayout()

    def _select(self, cid: Optional[int]) -> None:
        self.selected = cid
        self.page_view.set_selected(cid)
        self.panel.set_selected(cid)
        self._relayout()
        if cid is not None:
            self.panel.scroll_to(cid)

    def _refresh_page_comments(self) -> None:
        self.panel.show_only(self.store.for_page(self.page_index))
        self._refresh_anchors()
        QTimer.singleShot(0, self._relayout)

    def _refresh_anchors(self) -> None:
        anchors = {}
        for c in self.store.for_page(self.page_index):
            anchors[c.id] = Anchor(c.number, c.bbox, pending=c.status == Status.PENDING,
                                   error=c.status == Status.ERROR,
                                   heads_up=bool(c.tip and c.tip.heads_up))
        self.page_view.set_anchors(anchors)

    def _relayout(self) -> None:
        desired = {}
        for cid in self.panel.cards:
            c = self.store.get(cid)
            if c is None:
                continue
            rect = self.page_view.map_bbox(c.bbox)
            global_y = self.page_view.mapToGlobal(rect.topLeft().toPoint()).y()
            desired[cid] = self.panel.canvas_y_for(global_y) - 6
        self.panel.relayout(desired)

    def _fit_page_width(self) -> None:
        """Size the page to the window height so the comment margin hugs it."""
        width = self.page_view.width_for_height(self.page_view.height())
        room = self.width() - self.panel.width() - 80
        self.page_view.setFixedWidth(max(360, min(width, room)))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._fit_page_width)
        QTimer.singleShot(0, self._relayout)

    # ------------------------------------------------------------------ close
    def closeEvent(self, event) -> None:
        if self.recording:
            self._stop_recording()
        self._disconnect()
        for thread in list(self._tutor_threads.values()):
            thread.wait(3000)
        super().closeEvent(event)


def default_source_factory(config: AppConfig) -> Callable[[str], FrameSource]:
    def make(address: str) -> FrameSource:
        if address == DEMO:
            return DemoNotebookSource()
        return MirrorSource(address, config.mirror.connect_timeout_s)
    return make
