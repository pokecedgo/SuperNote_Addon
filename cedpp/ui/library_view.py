"""Notebooks mode: browse stored pages, reorder, delete, and study them."""
from __future__ import annotations

import html
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

from ..library import Library, LibraryError, StoredPage
from ..tutor import StudyAssistant, TutorError
from . import theme
from .folder_tree import FolderTree
from .neat_service import NeatService
from .page_shelf import PageShelf
from .search_view import SearchView
from .workers import TaskThread



def _card(title: str) -> tuple:
    frame = QFrame()
    frame.setStyleSheet(f"QFrame#StudyCard {{ background: {theme.PAPER}; border: 1.2px solid "
                        f"{theme.RULE}; border-radius: 16px; }}")
    frame.setObjectName("StudyCard")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(18, 14, 18, 16)
    lay.setSpacing(8)
    head = QLabel(title)
    head.setObjectName("SectionTitle")
    lay.addWidget(head)
    return frame, lay


def _rich(text: str) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.RichText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    label.setStyleSheet("font-size: 13.5px;")
    return label


def _esc(s: str) -> str:
    return html.escape(str(s))


class PageDetail(QWidget):
    back_requested = Signal()
    deleted = Signal()

    def __init__(self, library: Library, study: StudyAssistant) -> None:
        super().__init__()
        self.library = library
        self.study = study
        self.page: Optional[StoredPage] = None
        self._threads: List[TaskThread] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        head = QHBoxLayout()
        self.back = QPushButton("←  Back")
        self.back.setObjectName("Ghost")
        self.back.setCursor(Qt.PointingHandCursor)
        self.back.clicked.connect(self.back_requested)
        head.addWidget(self.back)
        self.crumb = QLabel("")
        self.crumb.setObjectName("Muted")
        head.addWidget(self.crumb)
        head.addStretch(1)
        self.prev_btn = QPushButton("‹ Move earlier")
        self.next_btn = QPushButton("Move later ›")
        for b, step in ((self.prev_btn, -1), (self.next_btn, 1)):
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, s=step: self._move(s))
            head.addWidget(b)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(22)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.image.setStyleSheet(f"border: 1.5px solid {theme.INK}; border-radius: 12px; "
                                 f"background: {theme.PAPER};")
        body.addWidget(self.image, 0, Qt.AlignTop)

        side = QVBoxLayout()
        side.setSpacing(10)
        self.title = QLabel("")
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-size: 22px; font-weight: 700;")
        side.addWidget(self.title)
        self.meta = QLabel("")
        self.meta.setObjectName("Muted")
        side.addWidget(self.meta)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.summarize_btn = QPushButton("Summarize Page")
        self.exam_btn = QPushButton("Important Takeaways for Exam")
        self.delete_btn = QPushButton("Delete")
        for b in (self.summarize_btn, self.exam_btn, self.delete_btn):
            b.setCursor(Qt.PointingHandCursor)
            actions.addWidget(b)
        actions.addStretch(1)
        self.summarize_btn.clicked.connect(lambda: self._run("summary"))
        self.exam_btn.clicked.connect(lambda: self._run("takeaways"))
        self.delete_btn.clicked.connect(self._delete)
        side.addLayout(actions)

        self.results = QVBoxLayout()
        self.results.setSpacing(12)
        holder = QWidget()
        holder.setLayout(self.results)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        side.addWidget(scroll, 1)
        body.addLayout(side, 1)
        root.addLayout(body, 1)

        self.reorder: Callable[[StoredPage, int], None] = lambda page, step: None

    # ------------------------------------------------------------------ show
    def show_page(self, page: StoredPage, position: int, total: int) -> None:
        self.page = page
        self._position = (position, total)
        self.crumb.setText(f"{self.library.relative(page.folder)}   ·   page {position + 1} of {total}")
        self._refresh_move_buttons()
        pix = QPixmap(str(page.image_path))
        if not pix.isNull():
            height = max(420, min(760, self.height() - 60 if self.height() > 200 else 700))
            self.image.setPixmap(pix.scaledToHeight(height, Qt.SmoothTransformation))
        self.title.setText(page.title)
        self.meta.setText(page.created_at.strftime("Stored %A, %b %d %Y at %-I:%M %p"))
        self._render_results()

    def _clear_results(self) -> None:
        while self.results.count():
            item = self.results.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _render_results(self, busy: Optional[str] = None, error: str = "") -> None:
        self._clear_results()
        meta = self.page.meta if self.page else {}
        if busy:
            frame, lay = _card("CED++ IS READING THIS PAGE")
            lay.addWidget(_rich(f"<span style='color:{theme.MUTED}'>{_esc(busy)}…</span>"))
            self.results.addWidget(frame)
        if error:
            frame, lay = _card("SOMETHING WENT WRONG")
            lay.addWidget(_rich(_esc(error)))
            self.results.addWidget(frame)
        if meta.get("takeaways"):
            self.results.addWidget(self._takeaways_card(meta["takeaways"]))
        if meta.get("summary"):
            self.results.addWidget(self._summary_card(meta["summary"]))
        comments = [c for c in meta.get("comments", []) if c.get("tip")]
        if comments:
            frame, lay = _card(f"CED++ COMMENTS FROM CLASS  ·  {len(comments)}")
            for c in comments:
                t = c["tip"]
                flag = (f"<b style='background:{theme.INK};color:{theme.PAPER}'>&nbsp;HEADS UP&nbsp;</b> "
                        if t.get("heads_up") else "")
                lay.addWidget(_rich(f"{flag}<b>{_esc(t.get('title', ''))}</b> "
                                    f"<span style='color:{theme.MUTED}'>— {_esc(t.get('recognized', ''))}"
                                    f"</span><br>{_esc(t.get('comment', ''))}"))
            self.results.addWidget(frame)
        if not (busy or error or meta.get("summary") or meta.get("takeaways") or comments):
            hint = _rich(f"<span style='color:{theme.MUTED}'>Use <b>Summarize Page</b> or "
                         "<b>Important Takeaways for Exam</b> to study this page. Results are "
                         "saved with the page.</span>")
            self.results.addWidget(hint)
        self.results.addStretch(1)
        has = bool(meta.get("summary")), bool(meta.get("takeaways"))
        self.summarize_btn.setText("Summarize again" if has[0] else "Summarize Page")
        self.exam_btn.setText("Exam takeaways again" if has[1] else "Important Takeaways for Exam")

    @staticmethod
    def _summary_card(s: dict) -> QFrame:
        frame, lay = _card("SUMMARY")
        lay.addWidget(_rich(f"<b style='font-size:15px'>{_esc(s.get('topic', ''))}</b>"))
        lay.addWidget(_rich(_esc(s.get("summary", ""))))
        points = "".join(f"<li>{_esc(p)}</li>" for p in s.get("key_points", []))
        if points:
            lay.addWidget(_rich(f"<b>Key points</b><ul style='margin-left:-20px'>{points}</ul>"))
        return frame

    @staticmethod
    def _takeaways_card(t: dict) -> QFrame:
        frame, lay = _card("IMPORTANT TAKEAWAYS FOR EXAM")
        items = "".join(f"<li><b>{_esc(x.get('point', ''))}</b><br>"
                        f"<span style='color:{theme.INK_SOFT}'>{_esc(x.get('why', ''))}</span></li>"
                        for x in t.get("takeaways", []))
        lay.addWidget(_rich(f"<ol style='margin-left:-20px'>{items}</ol>"))
        if t.get("watch_out"):
            watch = "".join(f"<li>{_esc(w)}</li>" for w in t["watch_out"])
            lay.addWidget(_rich(f"<b>Watch out</b><ul style='margin-left:-20px'>{watch}</ul>"))
        if t.get("practice_questions"):
            qs = "".join(f"<li>{_esc(q)}</li>" for q in t["practice_questions"])
            lay.addWidget(_rich(f"<b>Practice questions</b><ol style='margin-left:-20px'>{qs}</ol>"))
        return frame

    # ------------------------------------------------------------------ actions
    def _set_busy(self, busy: bool) -> None:
        for b in (self.summarize_btn, self.exam_btn, self.delete_btn, self.prev_btn,
                  self.next_btn, self.back):
            b.setEnabled(not busy)

    def _run(self, kind: str) -> None:
        page = self.page
        if page is None:
            return
        from PIL import Image
        image = np.array(Image.open(page.image_path).convert("L"))
        fn = self.study.summarize if kind == "summary" else self.study.takeaways
        label = "Summarizing" if kind == "summary" else "Finding the exam takeaways"

        def work():
            try:
                return ("ok", fn(image, page.comments))
            except TutorError as exc:
                return ("error", str(exc))

        thread = TaskThread(work)
        thread.succeeded.connect(lambda res, p=page, k=kind: self._done(p, k, res))
        thread.finished.connect(lambda t=thread: self._threads.remove(t) if t in self._threads else None)
        self._threads.append(thread)
        self._set_busy(True)
        self._render_results(busy=label)
        thread.start()

    def _done(self, page: StoredPage, kind: str, result) -> None:
        self._set_busy(False)
        if result is None:
            result = ("error", "Something went wrong. Try again.")
        status, payload = result
        if status == "ok":
            try:
                self.library.update_meta(page, kind, payload)
            except OSError as exc:
                payload, status = f"Couldn't save the result: {exc}", "error"
        if self.page is page:
            self._render_results(error=payload if status == "error" else "")
            self._refresh_move_buttons()

    def _refresh_move_buttons(self) -> None:
        position, total = getattr(self, "_position", (0, 1))
        self.prev_btn.setEnabled(position > 0)
        self.next_btn.setEnabled(position < total - 1)

    def _move(self, step: int) -> None:
        if self.page is not None:
            self.reorder(self.page, step)

    def _delete(self) -> None:
        page = self.page
        if page is None:
            return
        answer = QMessageBox.question(self, "Delete page?",
                                      f"Delete “{page.title}”? This can't be undone.")
        if answer != QMessageBox.Yes:
            return
        self.library.delete_page(page)
        self.page = None
        self.deleted.emit()

    def wait_for_threads(self) -> None:
        for t in list(self._threads):
            t.wait(10000)


class LibraryView(QWidget):
    GRID, DETAIL, SEARCH = 0, 1, 2

    def __init__(self, library: Library, study: StudyAssistant, neat: NeatService) -> None:
        super().__init__()
        self.library = library
        self.neat = neat
        self._detail_return = self.GRID
        neat.started.connect(self._neat_changed)
        neat.ready.connect(self._neat_changed)
        neat.failed.connect(lambda pid, _msg: self._neat_changed(pid))
        self.folder: Optional[Path] = None
        self.pages: List[StoredPage] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 12)
        root.setSpacing(20)

        # --- left: notebooks & folders
        left = QVBoxLayout()
        left.setSpacing(10)
        title = QLabel("NOTEBOOKS")
        title.setObjectName("SectionTitle")
        left.addWidget(title)
        self.tree = FolderTree(library)
        self.tree.setFixedWidth(260)
        self.tree.folder_selected.connect(self._open_folder)
        left.addWidget(self.tree, 1)
        row = QHBoxLayout()
        nb = QPushButton("+ Notebook")
        nb.clicked.connect(self.tree.new_notebook)
        sub = QPushButton("+ Folder")
        sub.clicked.connect(self.tree.new_folder)
        row.addWidget(nb)
        row.addWidget(sub)
        left.addLayout(row)
        self.delete_folder_btn = QPushButton("Delete folder")
        self.delete_folder_btn.clicked.connect(self._delete_folder)
        left.addWidget(self.delete_folder_btn)
        root.addLayout(left)

        # --- right: grid or page detail
        self.stack = QStackedWidget()
        grid_page = QWidget()
        g = QVBoxLayout(grid_page)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(6)
        head = QHBoxLayout()
        self.folder_title = QLabel("")
        self.folder_title.setStyleSheet("font-size: 22px; font-weight: 700;")
        head.addWidget(self.folder_title)
        head.addStretch(1)
        self.count = QLabel("")
        self.count.setObjectName("Muted")
        head.addWidget(self.count)
        g.addLayout(head)
        self.hint = QLabel("")
        self.hint.setObjectName("Small")
        g.addWidget(self.hint)
        self.grid = PageShelf()
        self.grid.neat_lookup = self._neat_state
        self.grid.order_changed.connect(self._save_order)
        self.grid.open_requested.connect(self._open_page_obj)
        self.grid.reveal_requested.connect(lambda page: self.neat.request(page))
        self.grid.retry_neat.connect(lambda page: self.neat.request(page, force=True))
        g.addWidget(self.grid, 1)
        self.empty = QLabel("")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setStyleSheet(f"color: {theme.MUTED}; border: 1.2px dashed {theme.RULE}; "
                                 "border-radius: 16px; padding: 40px; font-size: 14px;")
        g.addWidget(self.empty)
        self.stack.addWidget(grid_page)

        self.detail = PageDetail(library, study)
        self.detail.back_requested.connect(self._back_to_grid)
        self.detail.deleted.connect(self._after_delete)
        self.detail.reorder = self._step_page
        self.stack.addWidget(self.detail)

        self.search = SearchView(library)
        self.search.open_page.connect(self._open_search_hit)
        self.search.transcribe_requested.connect(self._transcribe_all)
        self.stack.addWidget(self.search)
        root.addWidget(self.stack, 1)

    # ------------------------------------------------------------------ data
    def refresh(self, select: Optional[Path] = None) -> None:
        self.tree.reload(select=select)

    def _open_folder(self, folder: Optional[Path]) -> None:
        self.folder = folder
        self.stack.setCurrentIndex(0)
        self.delete_folder_btn.setEnabled(folder is not None)
        if folder is None or not folder.exists():
            self.pages = []
            self.folder_title.setText("No notebooks yet")
            self.count.setText("")
            self.hint.setText("")
            self.grid.set_pages([])
            self.grid.hide()
            self.empty.setText("Click  + Notebook  to create one, or use  Store Page  in Live "
                               "mode after you finish a page.")
            self.empty.show()
            return
        self.pages = self.library.pages(folder)
        self.folder_title.setText(self.library.relative(folder))
        n = len(self.pages)
        self.count.setText(f"{n} page{'s' if n != 1 else ''}")
        self.hint.setText("Click a page to see its neat copy · double-click to open"
                          + (" · drag to reorder" if n > 1 else "") if n else "")
        self.grid.set_pages(self.pages)
        self.grid.setVisible(bool(self.pages))
        self.empty.setVisible(not self.pages)
        subs = self.library.subfolders(folder)
        self.empty.setText("No pages here yet. Store a page from Live mode"
                           + (f", or open one of its {len(subs)} folders on the left." if subs else "."))

    def _save_order(self, ids: List[str]) -> None:
        if self.folder is not None:
            self.library.reorder(self.folder, ids)
            self.pages = self.library.pages(self.folder)

    def _open_page(self, row: int) -> None:
        if 0 <= row < len(self.pages):
            self._detail_return = self.GRID
            self.stack.setCurrentIndex(self.DETAIL)
            self.detail.show_page(self.pages[row], row, len(self.pages))

    def _open_page_obj(self, page: StoredPage) -> None:
        ids = [p.id for p in self.pages]
        if page.id in ids:
            self._open_page(ids.index(page.id))

    # ------------------------------------------------------------------ neat copies
    def _neat_state(self, page: StoredPage) -> tuple:
        status = self.neat.status(page)
        if status == "missing" and page.neat:
            status = "ready"
        pix = self.neat.pixmap(page) if status == "ready" else None
        return status, pix, self.neat.errors.get(page.id, "")

    def _neat_changed(self, page_id: str) -> None:
        # the transcript lives in the page json; reload so search/detail see it
        for i, p in enumerate(self.pages):
            if p.id == page_id:
                fresh = [x for x in self.library.pages(p.folder) if x.id == page_id]
                if fresh:
                    self.pages[i] = fresh[0]
                    for tile in self.grid.canvas.tiles:
                        if tile.page.id == page_id:
                            tile.page = fresh[0]
        self.grid.refresh_neat(page_id)
        if self.stack.currentIndex() == self.SEARCH and self.search.query:
            self.search.run(self.search.query, busy=self.neat.busy)

    def _transcribe_all(self, pages: List[StoredPage]) -> None:
        for page in pages:
            self.neat.request(page)
        self.search.run(self.search.query, busy=self.neat.busy)

    # ------------------------------------------------------------------ search
    def show_search(self, query: str) -> None:
        if not query.strip():
            self.close_search()
            return
        self.stack.setCurrentIndex(self.SEARCH)
        self.search.run(query, busy=self.neat.busy)

    def close_search(self) -> None:
        if self.stack.currentIndex() == self.SEARCH or self._detail_return == self.SEARCH:
            self._detail_return = self.GRID
            self._open_folder(self.folder)

    def _open_search_hit(self, page: StoredPage) -> None:
        pages = self.library.pages(page.folder)
        ids = [p.id for p in pages]
        if page.id not in ids:
            return
        self._detail_return = self.SEARCH
        i = ids.index(page.id)
        self.stack.setCurrentIndex(self.DETAIL)
        self.detail.show_page(pages[i], i, len(pages))

    def _step_page(self, page: StoredPage, step: int) -> None:
        ids = [p.id for p in self.pages]
        i = ids.index(page.id)
        j = i + step
        if not 0 <= j < len(ids):
            return
        ids[i], ids[j] = ids[j], ids[i]
        self.library.reorder(page.folder, ids)
        self.pages = self.library.pages(page.folder)
        self.grid.set_pages(self.pages)
        self.detail.show_page(self.pages[j], j, len(self.pages))

    def _back_to_grid(self) -> None:
        if self._detail_return == self.SEARCH and self.search.query:
            self.show_search(self.search.query)
        else:
            self._open_folder(self.folder)

    def _after_delete(self) -> None:
        if self._detail_return == self.SEARCH and self.search.query:
            self.tree.reload(select=self.folder)
            self.show_search(self.search.query)
        else:
            self.tree.reload(select=self.folder)

    def _delete_folder(self) -> None:
        folder = self.tree.current_folder()
        if folder is None:
            return
        n = self.library.page_count(folder)
        what = "notebook" if folder.parent.resolve() == self.library.root.resolve() else "folder"
        answer = QMessageBox.question(
            self, f"Delete {what}?",
            f"Delete “{folder.name}”" + (f" and its {n} stored page{'s' if n != 1 else ''}" if n else "")
            + "? This can't be undone.")
        if answer != QMessageBox.Yes:
            return
        try:
            self.library.delete_folder(folder)
        except (LibraryError, OSError) as exc:
            QMessageBox.warning(self, "Couldn't delete", str(exc))
            return
        self.tree.reload(select=folder.parent)
