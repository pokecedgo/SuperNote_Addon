"""Search results across every notebook."""
from __future__ import annotations

import html
import re
from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from ..library import Library, SearchHit
from . import theme


def highlight(text: str, terms: List[str]) -> str:
    """HTML-escape text and bold every search term (case-insensitive)."""
    out = html.escape(text)
    for term in sorted(set(terms), key=len, reverse=True):
        pattern = re.compile(re.escape(html.escape(term)), re.IGNORECASE)
        out = pattern.sub(lambda m: f"<b style='background:{theme.PAPER_2}'>{m.group(0)}</b>", out)
    return out


class ResultRow(QFrame):
    clicked = Signal(object)    # StoredPage

    def __init__(self, hit: SearchHit, library: Library) -> None:
        super().__init__()
        self.page = hit.page
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("ResultRow")
        self.setStyleSheet(f"""
            #ResultRow {{ background: {theme.PAPER}; border: 1.2px solid {theme.RULE};
                          border-radius: 16px; }}
            #ResultRow:hover {{ border: 1.6px solid {theme.INK}; }}
        """)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 12, 16, 12)
        row.setSpacing(16)
        thumb = QLabel()
        pix = QPixmap(str(hit.page.image_path))
        if not pix.isNull():
            thumb.setPixmap(pix.scaled(66, 88, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        thumb.setFixedSize(66, 88)
        thumb.setStyleSheet(f"border: 1.2px solid {theme.INK}; border-radius: 6px; "
                            f"background: {theme.PAPER};")
        row.addWidget(thumb, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(3)
        title = QLabel(highlight(hit.page.title, hit.terms))
        title.setTextFormat(Qt.RichText)
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        col.addWidget(title)
        where = QLabel(f"{html.escape(library.relative(hit.page.folder))}  ·  "
                       f"{hit.page.created_at:%b %d, %Y}"
                       + (f"  ·  found in {hit.where}" if hit.where else ""))
        where.setObjectName("Small")
        col.addWidget(where)
        if hit.snippet and hit.where != "Title":
            snippet = QLabel(highlight(hit.snippet, hit.terms))
            snippet.setTextFormat(Qt.RichText)
            snippet.setWordWrap(True)
            snippet.setStyleSheet(f"color: {theme.INK_SOFT}; font-size: 13px;")
            col.addWidget(snippet)
        col.addStretch(1)
        row.addLayout(col, 1)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.page)


class SearchView(QWidget):
    open_page = Signal(object)          # StoredPage
    transcribe_requested = Signal(list)  # pages without a transcript

    def __init__(self, library: Library) -> None:
        super().__init__()
        self.library = library
        self.query = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        self.title = QLabel("")
        self.title.setStyleSheet("font-size: 22px; font-weight: 700;")
        root.addWidget(self.title)

        self.banner = QFrame()
        self.banner.setStyleSheet(f"background: {theme.PAPER_2}; border-radius: 12px;")
        b = QHBoxLayout(self.banner)
        b.setContentsMargins(14, 8, 8, 8)
        self.banner_text = QLabel("")
        self.banner_text.setWordWrap(True)
        b.addWidget(self.banner_text, 1)
        self.transcribe_btn = QPushButton("Make neat copies")
        self.transcribe_btn.setCursor(Qt.PointingHandCursor)
        self.transcribe_btn.clicked.connect(
            lambda: self.transcribe_requested.emit(self.library.untranscribed()))
        b.addWidget(self.transcribe_btn)
        root.addWidget(self.banner)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.list_holder = QWidget()
        self.list = QVBoxLayout(self.list_holder)
        self.list.setContentsMargins(0, 4, 8, 4)
        self.list.setSpacing(10)
        self.scroll.setWidget(self.list_holder)
        root.addWidget(self.scroll, 1)

    def run(self, query: str, busy: int = 0) -> None:
        self.query = query
        hits = self.library.search(query)
        self.title.setText(f"{len(hits)} note{'s' if len(hits) != 1 else ''} matching "
                           f"“{query.strip()}”")
        while self.list.count():
            item = self.list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for hit in hits:
            row = ResultRow(hit, self.library)
            row.clicked.connect(self.open_page)
            self.list.addWidget(row)
        if not hits:
            empty = QLabel("No matches. Try a shorter word, or a formula symbol like ∇.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"color: {theme.MUTED}; border: 1.2px dashed {theme.RULE}; "
                                "border-radius: 16px; padding: 30px;")
            self.list.addWidget(empty)
        self.list.addStretch(1)

        missing = len(self.library.untranscribed())
        self.banner.setVisible(missing > 0)
        if busy:
            self.banner_text.setText(f"Making neat copies… {busy} page{'s' if busy != 1 else ''} "
                                     "left. Results update as they finish.")
            self.transcribe_btn.hide()
        else:
            self.banner_text.setText(
                f"{missing} stored page{'s' if missing != 1 else ''} can only be found by title "
                "and comments, because they don't have a neat copy (text transcript) yet.")
            self.transcribe_btn.show()
