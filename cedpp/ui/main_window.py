"""Main window: top bar, mirrored page, comment margin."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QMessageBox, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from ..comments import CommentStore, Status
from ..config import APP_NAME, AppConfig
from ..ink import InkEvent
from ..mirror import DemoNotebookSource, FrameSource, MirrorSource
from ..library import Library, LibraryError
from ..tutor import NoteTutor, StudyAssistant, TutorRequest
from ..tutor.base import zone_crop
from . import theme
from .ask_popup import AskPopup
from .comments_panel import CommentsPanel
from .connect_dialog import DEMO, ConnectDialog
from ..audio import AudioError, fmt_time
from .lecture_audio import ClipPlayer, LectureAudio
from .lecture_digest import LectureDigestDialog
from .library_view import LibraryView
from .neat_service import NeatService
from .page_view import Anchor, PageView
from .store_dialog import StoreDialog
from .workers import MirrorThread, TutorThread

log = logging.getLogger(__name__)


class SearchBox(QLineEdit):
    """Compact until focused (or holding a query), then widens for typing."""

    COMPACT, WIDE = 108, 240

    def __init__(self) -> None:
        super().__init__()
        self.setFixedWidth(self.COMPACT)
        self.textChanged.connect(lambda _t: self._fit())

    def _fit(self) -> None:
        self.setFixedWidth(self.WIDE if self.hasFocus() or self.text() else self.COMPACT)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self._fit()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self._fit()


class Logo(QLabel):
    def __init__(self) -> None:
        super().__init__("S")
        self.setFixedSize(30, 30)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(f"background: {theme.INK}; color: {theme.PAPER}; border-radius: 9px; "
                           "font-weight: 800; font-size: 16px;")


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig, tutor: NoteTutor, study: StudyAssistant,
                 source_factory: Callable[[str], FrameSource],
                 autoconnect: Optional[str] = None,
                 lecture: Optional[LectureAudio] = None) -> None:
        super().__init__()
        self.lecture = lecture
        self.clips = ClipPlayer()
        self._session_folder: Optional[Path] = None
        self._digest_open = False
        if lecture is not None:
            lecture.transcript_updated.connect(lambda _n: self._tick())
            lecture.digest_ready.connect(self._show_digest)
            lecture.digest_failed.connect(
                lambda msg: self._set_status(f"Lecture side notes unavailable: {msg}"))
        self.cfg = config
        self.tutor = tutor
        self.study = study
        self.library = Library(config.library_dir)
        self.neat = NeatService(self.library, study)
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
        self.resize(1320, 900)
        self.setMinimumSize(1120, 700)
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
        b.setSpacing(8)
        b.addWidget(Logo())
        title = QLabel(APP_NAME)
        title.setObjectName("AppTitle")
        title.setMinimumWidth(title.sizeHint().width() + 4)
        b.addWidget(title)
        b.addSpacing(14)
        seg = QFrame()
        seg.setObjectName("Segment")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        for i, label in enumerate(("Live", "Notebooks")):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setChecked(i == 0)
            self.mode_group.addButton(btn, i)
            sl.addWidget(btn)
        self.mode_group.idClicked.connect(self._set_mode)
        b.addWidget(seg)
        seg.setMinimumWidth(seg.sizeHint().width())
        b.addSpacing(10)
        b.addStretch(1)
        self.search_box = SearchBox()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("⌕  Search")
        self.search_box.setClearButtonEnabled(True)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(280)
        self._search_timer.timeout.connect(self._run_search)
        self.search_box.textChanged.connect(lambda _t: self._search_timer.start())
        self.search_box.returnPressed.connect(self._run_search)
        b.addWidget(self.search_box)
        self.conn_pill = QLabel("Not connected")
        self.conn_pill.setMaximumWidth(170)
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
        self.ask_btn = QPushButton("◌  Ask")
        self.ask_btn.setCheckable(True)
        self.ask_btn.setEnabled(False)
        self.ask_btn.setCursor(Qt.PointingHandCursor)
        self.ask_btn.setToolTip("While recording: draw a loop around anything on the page and "
                                "Ced++ explains it (A)")
        self.ask_btn.toggled.connect(self._toggle_lasso)
        b.addWidget(self.ask_btn)
        self.store_btn = QPushButton("⤓  Store")
        self.store_btn.setEnabled(False)
        self.store_btn.setCursor(Qt.PointingHandCursor)
        self.store_btn.setToolTip("Save a snapshot of this page (and its comments) to a notebook (S)")
        self.store_btn.clicked.connect(self._store_page)
        b.addWidget(self.store_btn)
        outer.addWidget(bar)

        self.stack = QStackedWidget()
        live = QWidget()
        body = QHBoxLayout(live)
        body.setContentsMargins(24, 0, 12, 0)
        body.setSpacing(18)
        body.addStretch(1)
        self.page_view = PageView()
        self.page_view.anchor_clicked.connect(self._select)
        self.page_view.background_clicked.connect(lambda: self._select(None))
        self.page_view.layout_changed.connect(self._relayout)
        self.page_view.zone_drawn.connect(self._on_zone_drawn)
        self.ask_popup = AskPopup(self.page_view)
        self.ask_popup.submitted.connect(self._ask_about_zone)
        self.ask_popup.cancelled.connect(self._cancel_zone)
        body.addWidget(self.page_view)
        self.panel = CommentsPanel()
        self.panel.card_clicked.connect(self._select)
        self.panel.resolve_requested.connect(self._resolve)
        self.panel.retry_requested.connect(self._retry)
        self.panel.play_requested.connect(self._play_comment)
        body.addWidget(self.panel)
        body.addStretch(1)
        self.stack.addWidget(live)
        self.library_view = LibraryView(self.library, self.study, self.neat)
        self.stack.addWidget(self.library_view)
        outer.addWidget(self.stack, 1)

        foot = QHBoxLayout()
        foot.setContentsMargins(24, 4, 24, 8)
        self.status = QLabel("Connect your Supernote to begin.")
        self.status.setObjectName("Small")
        foot.addWidget(self.status)
        foot.addStretch(1)
        self.mic_label = QLabel("")
        self.mic_label.setObjectName("Small")
        foot.addWidget(self.mic_label)
        foot.addSpacing(16)
        self.tutor_label = QLabel(f"Tutor: {self.tutor.name}")
        self.tutor_label.setObjectName("Small")
        foot.addWidget(self.tutor_label)
        outer.addLayout(foot)

        QShortcut(QKeySequence("R"), self, activated=self.record_btn.click)
        QShortcut(QKeySequence("S"), self, activated=self.store_btn.click)
        QShortcut(QKeySequence("A"), self, activated=self.ask_btn.click)
        QShortcut(QKeySequence.Find, self, activated=lambda: (self.search_box.setFocus(),
                                                              self.search_box.selectAll()))
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self._escape)

    def _set_status(self, text: str) -> None:
        self.status.setText(text)

    def _set_pill(self, text: str, on: bool) -> None:
        self.conn_pill.setToolTip(text)
        metrics = self.conn_pill.fontMetrics()
        self.conn_pill.setText(metrics.elidedText(text, Qt.ElideRight, 160))
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
        self.store_btn.setEnabled(True)
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

    # ------------------------------------------------------------------ notebooks
    def _set_mode(self, index: int) -> None:
        self.mode_group.button(index).setChecked(True)
        self.stack.setCurrentIndex(index)
        live = index == 0
        for widget in (self.ask_btn, self.store_btn):
            widget.setVisible(live)          # live-only tools
        if index == 1:
            # Keep the open folder; the first time, open where you last stored a page.
            last = self.settings.value("last_folder", "")
            self.library_view.refresh(
                select=self.library_view.folder or (Path(last) if last else None))
        else:
            QTimer.singleShot(0, self._fit_page_width)
            QTimer.singleShot(0, self._relayout)

    def _run_search(self) -> None:
        self._search_timer.stop()
        query = self.search_box.text()
        if query.strip():
            if self.stack.currentIndex() != 1:
                self._set_mode(1)
            self.library_view.show_search(query)
        else:
            self.library_view.close_search()

    def _store_page(self) -> None:
        frame = self.mirror.latest_frame() if self.mirror else None
        if frame is None:
            self._set_status("Connect your Supernote first - there's no page to store yet.")
            return
        comments = [c.to_dict() for c in self.store.for_page(self.page_index)
                    if c.status == Status.READY]
        last = self.settings.value("last_folder", "")
        dialog = StoreDialog(self.library, frame,
                             f"Page {self.page_index + 1} · {time.strftime('%b %d')}",
                             len(comments), Path(last) if last else None, self)
        if not dialog.exec() or dialog.chosen_folder is None:
            return
        try:
            page = self.library.add_page(dialog.chosen_folder, frame, dialog.title, comments)
        except LibraryError as exc:
            QMessageBox.warning(self, "Couldn't store page", str(exc))
            return
        self.settings.setValue("last_folder", str(dialog.chosen_folder))
        self.neat.request(page)      # neat copy + searchable transcript, in the background
        self._set_status(f"Stored “{page.title}” in {self.library.relative(page.folder)}. "
                         "Writing its neat copy in the background…")

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
        self.ask_btn.setEnabled(True)
        self._session_folder = self.cfg.sessions_dir / time.strftime("%Y-%m-%d_%H-%M-%S")
        audio_note = ""
        if self.lecture is not None and self.cfg.audio.enabled:
            try:
                self.lecture.start(context_hint=self._notes_context())
                audio_note = " Listening to the lecture too."
            except AudioError as exc:
                audio_note = f" (No lecture audio: {exc})"
        self._tick()
        self._update_page_label()
        self._set_status("Recording — Ced++ comments whenever you pause writing." + audio_note)

    def _stop_recording(self) -> None:
        self.recording = False
        self.ask_btn.setChecked(False)
        self.ask_btn.setEnabled(False)
        self.record_btn.setChecked(False)
        self.record_btn.setText("●  Record")
        self.page_view.set_recording(False)
        if self.mirror is not None:
            self.mirror.stop_recording()
            frame = self.mirror.latest_frame()
            if frame is not None:
                self.page_snapshots[self.page_index] = frame
        self._save_session()
        if self.lecture is not None and self.lecture.active and self._session_folder:
            self.lecture.stop(self._session_folder, self._notes_context())
            self._set_status("Recording stopped. Finishing the lecture transcript and "
                             "looking for important side notes…")
            self.mic_label.setText("🎙 finishing transcript…")

    def _save_session(self) -> None:
        if not any(c.status != Status.SKIPPED for c in self.store.comments.values()):
            self._set_status("Recording stopped.")
            return
        try:
            folder = self.store.save_session(self.cfg.sessions_dir, self.page_snapshots,
                                             self._session_folder)
            self._set_status(f"Recording stopped. Comments saved to {folder.relative_to(folder.parents[1])}/")
        except OSError as exc:
            self._set_status(f"Recording stopped, but saving failed: {exc}")

    def _tick(self) -> None:
        if self.recording:
            s = int(time.monotonic() - self.record_started)
            self.record_btn.setText(f"■  Stop  {s // 60:02d}:{s % 60:02d}")
            lecture = self.lecture
            if lecture is not None and lecture.active and lecture.recorder is not None:
                lines = len(lecture.live.transcript.segments) if lecture.live else 0
                level = "▮" * min(5, int(lecture.recorder.level * 60)) or "▯"
                extra = f"{lines} lines transcribed" if lecture.live else lecture.note
                self.mic_label.setText(f"🎙 {level}  {fmt_time(lecture.now() or 0)} · {extra}")

    # ------------------------------------------------------------------ lecture audio
    def _notes_context(self) -> str:
        titles = [f"{c.tip.title}: {c.tip.recognized}" for c in self.store.comments.values()
                  if c.tip and not c.tip.skip]
        return "\n".join(titles[-30:])

    def _play_comment(self, cid: int) -> None:
        c = self.store.get(cid)
        if c is None or c.audio_t is None:
            return
        start = c.audio_t - self.cfg.audio.replay_before_s
        self._play_at(start)

    def _play_at(self, start: float) -> None:
        lecture = self.lecture
        saved = lecture.saved_audio if lecture else None
        if lecture is not None and lecture.recorder is not None and saved is None:
            self._set_status(self.clips.play(lecture.recorder, start))
        elif saved is not None and Path(saved).exists():
            self._set_status(self.clips.play_file(Path(saved), start))

    def _show_digest(self, result, folder) -> None:
        self.mic_label.setText("")
        if result is None:
            self._set_status("Recording stopped. No speech was transcribed, so there are no "
                             "lecture side notes.")
            return
        n = len(result.get("items", []))
        self._set_status(f"Lecture side notes ready: {n} item{'s' if n != 1 else ''}. "
                         f"Saved in {folder.name}/.")
        dialog = LectureDigestDialog(result, folder, self._play_at, self)
        self._digest_open = True
        dialog.finished.connect(lambda _r: (setattr(self, "_digest_open", False), self.clips.stop()))
        dialog.open()

    def _update_page_label(self) -> None:
        self.page_view.set_page_number(self.page_index + 1)

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
            comment.audio_t = self.lecture.now() if self.lecture and self.lecture.active else None
            if ev.page_index == self.page_index:
                self.panel.upsert(comment)
            self._queue.append(comment.id)
        self._refresh_anchors()
        self._relayout()
        self._pump()

    # ------------------------------------------------------------------ ask about area
    def _escape(self) -> None:
        if self.ask_btn.isChecked():
            self.ask_btn.setChecked(False)
        else:
            self._select(None)

    def _toggle_lasso(self, on: bool) -> None:
        if on and self.stack.currentIndex() != 0:
            self._set_mode(0)
        self.page_view.set_lasso(on)
        if on:
            self._select(None)
            self._set_status("Draw a loop around what you want help with. Esc to cancel.")
        else:
            self._cancel_zone()

    def _on_zone_drawn(self, zone) -> None:
        self._draft_zone = zone
        self.ask_popup.open_at(self.page_view.zone_bottom_left(zone).toPoint())

    def _cancel_zone(self) -> None:
        self._draft_zone = None
        self.ask_popup.hide()
        self.page_view.set_draft(None)

    def _ask_about_zone(self, question: str) -> None:
        zone = getattr(self, "_draft_zone", None)
        frame = self.mirror.latest_frame() if self.mirror else None
        self.page_view.set_draft(None)
        self._draft_zone = None
        self.ask_btn.setChecked(False)
        if zone is None or frame is None:
            return
        crop, bbox = zone_crop(frame, zone)
        comment = self.store.add(self.page_index, bbox, crop, frame, zone=zone, question=question)
        comment.audio_t = self.lecture.now() if self.lecture and self.lecture.active else None
        self.page_snapshots[self.page_index] = frame
        self.panel.upsert(comment)
        self._queue.insert(0, comment.id)          # your questions jump the queue
        self._refresh_anchors()
        self._select(comment.id)
        self._pump()
        self._set_status("Ced++ is looking at the area you circled…")

    def _pump(self) -> None:
        while self._queue and len(self._tutor_threads) < self.cfg.tutor.max_parallel:
            cid = self._queue.pop(0)
            c = self.store.get(cid)
            if c is None or c.status != Status.PENDING:
                continue
            request = TutorRequest(c.crop, c.page, c.bbox,
                                   self.store.history(c.page_index, self.cfg.tutor.history_items),
                                   requested=c.requested, question=c.question,
                                   lecture_context=self.lecture.context(c.audio_t)
                                   if self.lecture else "")
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
        c.status = Status.SKIPPED if tip.skip and not c.requested else Status.READY
        if c.requested:
            self._set_status(f"Ced++ answered about the area you circled (comment {c.number}).")
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
                                   heads_up=bool(c.tip and c.tip.heads_up), zone=c.zone)
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
        self.library_view.detail.wait_for_threads()
        self.neat.wait()
        if self.lecture is not None:
            self.lecture.wait()
        super().closeEvent(event)


def default_source_factory(config: AppConfig) -> Callable[[str], FrameSource]:
    def make(address: str) -> FrameSource:
        if address == DEMO:
            return DemoNotebookSource()
        return MirrorSource(address, config.mirror.connect_timeout_s)
    return make
