"""Page tiles for a folder. Click a page and its Neat Copy slides out from behind it.

- one click: reveal the neat copy (only one page open at a time)
- click again / click another page: hide it
- double-click (or "Open ›"): open the page with its study tools
- drag a page: reorder
"""
from __future__ import annotations

from typing import Callable, List, Optional

from PySide6.QtCore import (QEasingCurve, QMimeData, QPoint, QRect, QRectF, QSize, Qt,
                            QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QDrag, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QLayout, QPushButton, QScrollArea, QSizePolicy, QWidget

from ..library import StoredPage
from . import theme

W, H = 150, 200          # one sheet
GAP = 16                 # between original and neat copy when revealed
PAD_X, PAD_Y = 10, 8
TEXT_H = 50
MIME = "application/x-cedpp-page"


class FlowLayout(QLayout):
    """Left-to-right wrapping layout whose items may change width (animations)."""

    def __init__(self, parent: QWidget, spacing: int = 14) -> None:
        super().__init__(parent)
        self._items = []
        self._spacing = spacing

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        height = self._do_layout(rect, apply=True)
        parent = self.parentWidget()
        if parent is not None and parent.minimumHeight() != height:
            parent.setMinimumHeight(height)

    def _do_layout(self, rect: QRect, apply: bool) -> int:
        x, y, row_h = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() and row_h > 0:
                x, y = rect.x(), y + row_h + self._spacing
                row_h = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            row_h = max(row_h, hint.height())
        return y + row_h - rect.y() + 8


def _sheet_path(r: QRectF) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(r, 8, 8)
    return path


class PageTile(QWidget):
    clicked = Signal(object)          # self
    open_requested = Signal(object)   # StoredPage
    retry_neat = Signal(object)       # StoredPage

    def __init__(self, page: StoredPage, number: int, original: Optional[QPixmap]) -> None:
        super().__init__()
        self.page = page
        self.number = number
        self.original = original
        self.neat: Optional[QPixmap] = None
        self.neat_status = "missing"      # missing | working | ready | error
        self.neat_error = ""
        self.revealed = False
        self._reveal = 0.0
        self._press: Optional[QPoint] = None
        self._dots = 0
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(340)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set_reveal)
        self._anim.finished.connect(self._sync_open_button)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._animate_dots)

        self.open_btn = QPushButton("Open ›", self)
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.setStyleSheet("padding: 3px 12px; border-radius: 10px; font-size: 12px;")
        self.open_btn.clicked.connect(lambda: self.open_requested.emit(self.page))
        self.open_btn.hide()

    # ------------------------------------------------------------------ geometry
    def sizeHint(self) -> QSize:
        return QSize(int(2 * PAD_X + W + self._reveal * (W + GAP)), 2 * PAD_Y + H + TEXT_H)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _set_reveal(self, value) -> None:
        self._reveal = float(value)
        self.updateGeometry()
        self.update()

    def set_revealed(self, on: bool, animate: bool = True) -> None:
        if on == self.revealed:
            return
        self.revealed = on
        self.open_btn.hide()
        self._anim.stop()
        if animate:
            self._anim.setStartValue(self._reveal)
            self._anim.setEndValue(1.0 if on else 0.0)
            self._anim.start()
        else:
            self._set_reveal(1.0 if on else 0.0)
            self._sync_open_button()

    def _sync_open_button(self) -> None:
        if self.revealed and self._reveal >= 0.99:
            self.open_btn.adjustSize()
            x = PAD_X + W + GAP + W - self.open_btn.width()
            self.open_btn.move(int(x), PAD_Y + H + 18)
            self.open_btn.show()
        else:
            self.open_btn.hide()

    def set_neat(self, status: str, pixmap: Optional[QPixmap] = None, error: str = "") -> None:
        self.neat_status = status
        self.neat = pixmap if status == "ready" else None
        self.neat_error = error
        if status == "working":
            self._tick.start(420)
        else:
            self._tick.stop()
        self.update()

    def _animate_dots(self) -> None:
        self._dots = (self._dots + 1) % 4
        self.update()

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press = event.position().toPoint()

    def mouseMoveEvent(self, event) -> None:
        if self._press is None or not (event.buttons() & Qt.LeftButton):
            return
        if (event.position().toPoint() - self._press).manhattanLength() < 10:
            return
        self._press = None
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME, self.page.id.encode())
        drag.setMimeData(mime)
        if self.original is not None:
            drag.setPixmap(self.original.scaled(W // 2, H // 2, Qt.KeepAspectRatio,
                                                Qt.SmoothTransformation))
        drag.exec(Qt.MoveAction)

    def mouseReleaseEvent(self, event) -> None:
        if self._press is not None and event.button() == Qt.LeftButton:
            self._press = None
            neat_rect = QRectF(PAD_X + self._reveal * (W + GAP), PAD_Y, W, H)
            if self.revealed and self.neat_status == "error" and \
                    neat_rect.contains(event.position()):
                self.retry_neat.emit(self.page)
                return
            self.clicked.emit(self)

    def mouseDoubleClickEvent(self, event) -> None:
        self._press = None
        self.open_requested.emit(self.page)

    # ------------------------------------------------------------------ paint
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        f = QFont(self.font())

        orig = QRectF(PAD_X, PAD_Y, W, H)
        # --- neat copy: behind the original, sliding out to the right
        if self._reveal > 0.001:
            neat = QRectF(PAD_X + self._reveal * (W + GAP), PAD_Y + 4 * (1 - self._reveal), W, H)
            path = _sheet_path(neat)
            p.fillPath(path, QColor(theme.PAPER))
            p.save()
            p.setClipPath(path)
            if self.neat is not None:
                p.drawPixmap(neat, self.neat, QRectF(self.neat.rect()))
            else:
                f.setPointSize(11)
                p.setFont(f)
                p.setPen(QColor(theme.MUTED))
                msg = {"working": "Writing neat copy" + "." * self._dots,
                       "error": (self.neat_error or "Couldn't make a neat copy")
                                + "\n\nClick to try again",
                       "missing": "No neat copy yet"}.get(self.neat_status, "")
                p.drawText(neat.adjusted(12, 0, -12, 0), Qt.AlignCenter | Qt.TextWordWrap, msg)
            p.restore()
            pen = QPen(QColor(theme.INK), 1.2)
            pen.setStyle(Qt.SolidLine if self.neat is not None else Qt.DashLine)
            p.setPen(pen)
            p.drawPath(path)
            # label under the neat copy
            p.setOpacity(self._reveal)
            f.setPointSize(11)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(theme.INK))
            p.drawText(QRectF(neat.left(), neat.bottom() + 6, W, 18), Qt.AlignLeft, "Neat copy")
            p.setOpacity(1.0)

        # --- original on top
        path = _sheet_path(orig)
        p.fillPath(path, QColor(theme.PAPER))
        if self.original is not None:
            p.save()
            p.setClipPath(path)
            p.drawPixmap(orig, self.original, QRectF(self.original.rect()))
            p.restore()
        p.setPen(QPen(QColor(theme.INK), 2.4 if self.revealed else 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        num = QRectF(orig.right() - 30, orig.bottom() - 28, 24, 22)
        p.setPen(QPen(QColor(theme.INK), 1.1))
        p.setBrush(QColor(theme.INK if self.revealed else theme.PAPER))
        p.drawRoundedRect(num, 10, 10)
        f.setPointSize(10)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.PAPER if self.revealed else theme.INK))
        p.drawText(num, Qt.AlignCenter, str(self.number))

        text = QRectF(orig.left(), orig.bottom() + 6, W, 20)
        f.setPointSize(12)
        p.setFont(f)
        p.setPen(QColor(theme.INK))
        p.drawText(text, Qt.AlignLeft | Qt.AlignTop,
                   p.fontMetrics().elidedText(self.page.title, Qt.ElideRight, W))
        f.setBold(False)
        f.setPointSize(10)
        p.setFont(f)
        p.setPen(QColor(theme.MUTED))
        p.drawText(text.translated(0, 19), Qt.AlignLeft | Qt.AlignTop,
                   self.page.created_at.strftime("%b %d · %-I:%M %p"))


class _ShelfCanvas(QWidget):
    """Holds the tiles; handles drag-and-drop reordering."""

    dropped = Signal(str, int)     # page id, new index

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.layout_ = FlowLayout(self)
        self.tiles: List[PageTile] = []
        self._drop_index: Optional[int] = None

    def _index_at(self, pos: QPoint) -> int:
        for i, tile in enumerate(self.tiles):
            g = tile.geometry()
            if pos.y() < g.top():
                return i
            if g.top() <= pos.y() <= g.bottom() and pos.x() < g.left() + PAD_X + W / 2:
                return i
        return len(self.tiles)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME):
            self._drop_index = self._index_at(event.position().toPoint())
            event.acceptProposedAction()
            self.update()

    def dragLeaveEvent(self, _event) -> None:
        self._drop_index = None
        self.update()

    def dropEvent(self, event) -> None:
        index = self._index_at(event.position().toPoint())
        self._drop_index = None
        self.update()
        page_id = bytes(event.mimeData().data(MIME)).decode()
        event.acceptProposedAction()
        self.dropped.emit(page_id, index)

    def paintEvent(self, _event) -> None:
        if self._drop_index is None or not self.tiles:
            return
        p = QPainter(self)
        p.setPen(QPen(QColor(theme.INK), 3, Qt.SolidLine, Qt.RoundCap))
        if self._drop_index < len(self.tiles):
            g = self.tiles[self._drop_index].geometry()
            x = g.left() + 2
        else:
            g = self.tiles[-1].geometry()
            x = g.right() - 2
        p.drawLine(x, g.top() + PAD_Y, x, g.top() + PAD_Y + H)


class PageShelf(QScrollArea):
    open_requested = Signal(object)        # StoredPage
    reveal_requested = Signal(object)      # StoredPage - make sure it has a neat copy
    retry_neat = Signal(object)            # StoredPage
    order_changed = Signal(list)           # page ids

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.canvas = _ShelfCanvas()
        self.canvas.dropped.connect(self._on_drop)
        self.setWidget(self.canvas)
        self._thumbs = {}
        self.neat_lookup: Callable[[StoredPage], tuple] = lambda page: ("missing", None, "")

    def set_pages(self, pages: List[StoredPage]) -> None:
        layout = self.canvas.layout_
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.canvas.tiles = []
        for i, page in enumerate(pages):
            key = (page.id, str(page.folder))
            if key not in self._thumbs:
                pix = QPixmap(str(page.image_path))
                self._thumbs[key] = None if pix.isNull() else pix.scaled(
                    W * 2, H * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            tile = PageTile(page, i + 1, self._thumbs[key])
            tile.clicked.connect(self._on_click)
            tile.open_requested.connect(self.open_requested)
            tile.retry_neat.connect(self.retry_neat)
            self.canvas.tiles.append(tile)
            layout.addWidget(tile)
            self.refresh_neat(page.id)

    def refresh_neat(self, page_id: str) -> None:
        for tile in self.canvas.tiles:
            if tile.page.id == page_id:
                status, pix, error = self.neat_lookup(tile.page)
                tile.set_neat(status, pix, error)

    def _on_click(self, tile: PageTile) -> None:
        if tile.revealed:
            tile.set_revealed(False)
            return
        for other in self.canvas.tiles:
            if other is not tile:
                other.set_revealed(False)
        tile.set_revealed(True)
        self.reveal_requested.emit(tile.page)
        QTimer.singleShot(360, lambda: self.ensureWidgetVisible(tile, 20, 20)
                          if tile in self.canvas.tiles else None)

    def hide_all(self) -> None:
        for tile in self.canvas.tiles:
            tile.set_revealed(False, animate=False)

    def _on_drop(self, page_id: str, index: int) -> None:
        ids = [t.page.id for t in self.canvas.tiles]
        if page_id not in ids:
            return
        old = ids.index(page_id)
        ids.pop(old)
        if index > old:
            index -= 1
        ids.insert(index, page_id)
        if ids != [t.page.id for t in self.canvas.tiles]:
            self.order_changed.emit(ids)
