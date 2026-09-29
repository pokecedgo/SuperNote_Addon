"""A single Google-Docs-style comment card, drawn in the Supernote style."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from ..comments import Comment, Status
from ..config import ASSISTANT_NAME
from . import theme

CARD_WIDTH = 318


class Avatar(QWidget):
    def __init__(self, text: str = "C++", size: int = 30) -> None:
        super().__init__()
        self.text = text
        self.setFixedSize(size, size)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.INK))
        p.drawEllipse(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1))
        f = QFont(self.font())
        f.setPointSize(9)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.PAPER))
        p.drawText(self.rect(), Qt.AlignCenter, self.text)


class NumberChip(QWidget):
    def __init__(self, number: int) -> None:
        super().__init__()
        self.number = number
        self.inverted = False
        self.setFixedSize(24, 22)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(theme.INK), 1.2))
        p.setBrush(QColor(theme.INK if self.inverted else theme.PAPER))
        p.drawRoundedRect(QRectF(0.6, 0.6, 22.8, 20.8), 10.4, 10.4)
        f = QFont(self.font())
        f.setPointSize(10)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.PAPER if self.inverted else theme.INK))
        p.drawText(self.rect(), Qt.AlignCenter, str(self.number))


class CommentCard(QFrame):
    clicked = Signal(int)
    resolve_requested = Signal(int)
    retry_requested = Signal(int)
    play_requested = Signal(int)

    def __init__(self, comment: Comment, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.comment_id = comment.id
        self.selected = False
        self.setFixedWidth(CARD_WIDTH)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)
        self.setCursor(Qt.PointingHandCursor)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(16, 14, 14, 14)
        self._root.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(Avatar(), 0, Qt.AlignTop)
        who = QVBoxLayout()
        who.setSpacing(0)
        name = QLabel(ASSISTANT_NAME)
        name.setStyleSheet("font-weight: 700; font-size: 13px;")
        self.time_label = QLabel(comment.created_at.strftime("%-I:%M %p · Page ") +
                                 str(comment.page_index + 1))
        self.time_label.setObjectName("Small")
        who.addWidget(name)
        who.addWidget(self.time_label)
        who.addStretch(1)
        head.addLayout(who, 1)
        self.chip = NumberChip(comment.number)
        head.addWidget(self.chip, 0, Qt.AlignTop)
        if comment.audio_t is not None:
            m, s = divmod(int(comment.audio_t), 60)
            play = QPushButton(f"▶ {m:02d}:{s:02d}")
            play.setObjectName("Ghost")
            play.setCursor(Qt.PointingHandCursor)
            play.setToolTip("Hear what the teacher was saying at this moment")
            play.setStyleSheet("font-size: 11px; padding: 2px 6px;")
            play.clicked.connect(lambda: self.play_requested.emit(self.comment_id))
            head.addWidget(play, 0, Qt.AlignTop)
        self.resolve_btn = QPushButton("✓")
        self.resolve_btn.setObjectName("IconButton")
        self.resolve_btn.setToolTip("Resolve (hide this comment)")
        self.resolve_btn.setCursor(Qt.PointingHandCursor)
        self.resolve_btn.clicked.connect(lambda: self.resolve_requested.emit(self.comment_id))
        head.addWidget(self.resolve_btn, 0, Qt.AlignTop)
        self._root.addLayout(head)

        self._body = QVBoxLayout()
        self._body.setSpacing(6)
        self._root.addLayout(self._body)

        self._dots = 0
        self._dot_timer = QTimer(self)
        self._dot_timer.timeout.connect(self._tick)
        self.update_from(comment)
        self._apply_style()

    # ------------------------------------------------------------------ content
    def _clear_body(self) -> None:
        while self._body.count():
            item = self._body.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                lay = item.layout()
                while lay.count():
                    sub = lay.takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()

    @staticmethod
    def _text(text: str, style: str = "", obj: str = "") -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if obj:
            label.setObjectName(obj)
        if style:
            label.setStyleSheet(style)
        return label

    def update_from(self, c: Comment) -> None:
        self._clear_body()
        self._dot_timer.stop()
        if c.requested:
            asked = f"You asked: “{c.question}”" if c.question else "You circled this area"
            self._body.addWidget(self._text(
                asked, f"background: {theme.INK}; color: {theme.PAPER}; border-radius: 10px; "
                       "padding: 6px 10px; font-size: 12.5px; font-weight: 600;"))
        if c.status == Status.PENDING:
            self._pending_label = self._text("Reading your handwriting", f"color: {theme.MUTED};")
            self._body.addWidget(self._pending_label)
            self._dot_timer.start(400)
        elif c.status == Status.ERROR:
            self._body.addWidget(self._text(c.error, f"color: {theme.INK_SOFT};"))
            retry = QPushButton("Try again")
            retry.setCursor(Qt.PointingHandCursor)
            retry.clicked.connect(lambda: self.retry_requested.emit(self.comment_id))
            row = QHBoxLayout()
            row.addWidget(retry)
            row.addStretch(1)
            self._body.addLayout(row)
        elif c.tip is not None:
            t = c.tip
            title_row = QHBoxLayout()
            title_row.setSpacing(8)
            if t.heads_up:
                tag = QLabel("HEADS UP")
                tag.setStyleSheet(f"background: {theme.INK}; color: {theme.PAPER}; "
                                  "border-radius: 8px; padding: 2px 7px; font-size: 10px; "
                                  "font-weight: 700; letter-spacing: 1px;")
                title_row.addWidget(tag, 0, Qt.AlignVCenter)
            title_row.addWidget(self._text(t.title, "font-weight: 700; font-size: 14px;"), 1)
            self._body.addLayout(title_row)
            if t.recognized:
                self._body.addWidget(self._text(
                    t.recognized,
                    f"font-family: 'Menlo'; font-size: 12px; color: {theme.INK_SOFT}; "
                    f"background: {theme.PAPER_2}; border-left: 3px solid {theme.INK}; "
                    "border-radius: 4px; padding: 6px 8px;"))
            self._body.addWidget(self._text(t.comment, "font-size: 13px; line-height: 140%;"))
            if t.extras:
                self._body.addWidget(self._text("You could also note:",
                                                f"color: {theme.MUTED}; font-size: 11px; "
                                                "font-weight: 700; letter-spacing: 0.5px;"))
                for extra in t.extras:
                    self._body.addWidget(self._text(f"•  {extra}", "font-size: 12.5px;"))
        self.chip.number = c.number
        self.fit_height()

    def fit_height(self) -> None:
        """Wrapped labels need heightForWidth; plain adjustSize() over-allocates."""
        self._root.activate()
        self.setFixedHeight(self._root.totalHeightForWidth(CARD_WIDTH))

    def _tick(self) -> None:
        self._dots = (self._dots + 1) % 4
        self._pending_label.setText("Reading your handwriting" + "." * self._dots)

    # ------------------------------------------------------------------ style
    def set_selected(self, selected: bool) -> None:
        if selected != self.selected:
            self.selected = selected
            self._apply_style()

    def _apply_style(self) -> None:
        border = f"2px solid {theme.INK}" if self.selected else f"1.2px solid {theme.RULE}"
        self.setStyleSheet(f"CommentCard {{ background: {theme.PAPER}; border: {border}; "
                           "border-radius: 16px; }")
        self.chip.inverted = self.selected
        self.chip.update()

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self.comment_id)
        super().mousePressEvent(event)
