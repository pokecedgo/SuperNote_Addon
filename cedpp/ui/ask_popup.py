"""Small floating box shown after you circle an area: optional question + Ask."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QPushButton, QWidget

from . import theme


class _QuestionEdit(QLineEdit):
    escape = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.escape.emit()
            return
        super().keyPressEvent(event)


class AskPopup(QFrame):
    submitted = Signal(str)
    cancelled = Signal()

    WIDTH = 440

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("AskPopup")
        self.setStyleSheet(f"""
            #AskPopup {{ background: {theme.PAPER}; border: 1.5px solid {theme.INK};
                         border-radius: 16px; }}
            #AskPopup QLineEdit {{ border: none; background: transparent; font-size: 14px;
                                   padding: 6px 4px; }}
        """)
        self.setFixedWidth(self.WIDTH)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 6, 6)
        row.setSpacing(6)
        self.edit = _QuestionEdit()
        self.edit.setPlaceholderText("Ask something specific (optional)…")
        self.edit.returnPressed.connect(self._submit)
        self.edit.escape.connect(self._cancel)
        row.addWidget(self.edit, 1)
        ask = QPushButton("Ask Ced++")
        ask.setCursor(Qt.PointingHandCursor)
        ask.setStyleSheet(f"background: {theme.INK}; color: {theme.PAPER};")
        ask.clicked.connect(self._submit)
        row.addWidget(ask)
        close = QPushButton("✕")
        close.setObjectName("IconButton")
        close.setCursor(Qt.PointingHandCursor)
        close.setToolTip("Cancel (Esc)")
        close.clicked.connect(self._cancel)
        row.addWidget(close)
        self.hide()

    def open_at(self, anchor: QPoint) -> None:
        """Show just below the circled area, kept inside the parent."""
        self.edit.clear()
        self.adjustSize()
        parent = self.parentWidget()
        x = min(max(8, anchor.x()), parent.width() - self.width() - 8)
        y = anchor.y() + 12
        if y + self.height() > parent.height() - 8:
            y = anchor.y() - self.height() - 12
        self.move(x, max(8, y))
        self.show()
        self.raise_()
        self.edit.setFocus()

    def _submit(self) -> None:
        text = self.edit.text().strip()
        self.hide()
        self.submitted.emit(text)

    def _cancel(self) -> None:
        self.hide()
        self.cancelled.emit()
