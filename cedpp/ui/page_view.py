"""The mirrored Supernote page with comment anchors drawn on top."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import theme

BBox = Tuple[int, int, int, int]
PAGE_ASPECT = 1404 / 1872   # used before the first frame arrives


@dataclass
class Anchor:
    number: int
    bbox: BBox
    pending: bool = False
    error: bool = False
    heads_up: bool = False


class PageView(QWidget):
    anchor_clicked = Signal(int)          # comment id
    background_clicked = Signal()
    layout_changed = Signal()             # page rect moved/resized -> re-align cards

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(360, 480)
        self.setMouseTracking(True)
        self._image: Optional[QImage] = None
        self._anchors: Dict[int, Anchor] = {}
        self._selected: Optional[int] = None
        self._hovered: Optional[int] = None
        self._pending: Optional[BBox] = None
        self._recording = False
        self._message = ("Turn on Screen Mirroring on your Supernote\n"
                         "(swipe down → Screen Mirroring), then click Connect.")
        self._last_rect = QRectF()

    # ------------------------------------------------------------------ state
    def set_frame(self, image: QImage) -> None:
        size_changed = self._image is None or self._image.size() != image.size()
        self._image = image
        self._message = None
        self.update()
        if size_changed:
            self._emit_if_moved()

    def clear_frame(self, message: str) -> None:
        self._image = None
        self._message = message
        self.update()

    def set_message(self, message: Optional[str]) -> None:
        self._message = message
        self.update()

    def set_recording(self, on: bool) -> None:
        self._recording = on
        if not on:
            self._pending = None
        self.update()

    def set_pending(self, bbox: Optional[BBox]) -> None:
        self._pending = bbox
        self.update()

    def set_anchors(self, anchors: Dict[int, Anchor]) -> None:
        self._anchors = dict(anchors)
        self.update()

    def set_selected(self, comment_id: Optional[int]) -> None:
        self._selected = comment_id
        self.update()

    # ------------------------------------------------------------------ geometry
    def image_size(self) -> QSize:
        if self._image is not None:
            return self._image.size()
        return QSize(1404, 1872)

    def width_for_height(self, height: int) -> int:
        size = self.image_size()
        return int((height - 32) * size.width() / size.height()) + 16

    def page_rect(self) -> QRectF:
        """Where the page is drawn inside this widget (aspect-fit, with margins)."""
        bounds = QRectF(self.rect()).adjusted(8, 16, -8, -16)
        size = self.image_size()
        scale = min(bounds.width() / size.width(), bounds.height() / size.height())
        w, h = size.width() * scale, size.height() * scale
        return QRectF(bounds.center().x() - w / 2, bounds.top(), w, h)

    def map_bbox(self, bbox: BBox) -> QRectF:
        page = self.page_rect()
        size = self.image_size()
        sx, sy = page.width() / size.width(), page.height() / size.height()
        x1, y1, x2, y2 = bbox
        return QRectF(page.x() + x1 * sx, page.y() + y1 * sy, (x2 - x1) * sx, (y2 - y1) * sy)

    def _emit_if_moved(self) -> None:
        rect = self.page_rect()
        if rect != self._last_rect:
            self._last_rect = rect
            self.layout_changed.emit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._emit_if_moved()

    # ------------------------------------------------------------------ mouse
    def _anchor_at(self, pos: QPointF) -> Optional[int]:
        for cid, a in sorted(self._anchors.items(), key=lambda kv: kv[0], reverse=True):
            if self.map_bbox(a.bbox).adjusted(-6, -6, 6, 6).contains(pos):
                return cid
        return None

    def mouseMoveEvent(self, event) -> None:
        hovered = self._anchor_at(event.position())
        if hovered != self._hovered:
            self._hovered = hovered
            self.setCursor(Qt.PointingHandCursor if hovered else Qt.ArrowCursor)
            self.update()

    def mousePressEvent(self, event) -> None:
        cid = self._anchor_at(event.position())
        if cid is not None:
            self.anchor_clicked.emit(cid)
        else:
            self.background_clicked.emit()

    # ------------------------------------------------------------------ painting
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        page = self.page_rect()

        # Paper sheet with a crisp ink border, like the Supernote frame.
        path = QPainterPath()
        path.addRoundedRect(page, 14, 14)
        p.fillPath(path, QColor(theme.PAPER))
        p.save()
        p.setClipPath(path)
        if self._image is not None:
            p.drawImage(page, self._image, QRectF(self._image.rect()))
        p.restore()
        p.setPen(QPen(QColor(theme.INK), 1.5))
        p.drawPath(path)

        if self._message:
            f = QFont(self.font())
            f.setPointSize(15)
            p.setFont(f)
            p.setPen(QColor(theme.MUTED))
            p.drawText(page.adjusted(40, 0, -40, 0), Qt.AlignCenter | Qt.TextWordWrap,
                       self._message)

        if self._image is not None:
            p.save()
            p.setClipPath(path)
            self._paint_pending(p)
            for cid, anchor in self._anchors.items():
                self._paint_anchor(p, cid, anchor)
            p.restore()

        if self._recording:
            self._paint_rec(p, page)

    def _paint_pending(self, p: QPainter) -> None:
        if self._pending is None:
            return
        r = self.map_bbox(self._pending).adjusted(-4, -4, 4, 4)
        pen = QPen(QColor(theme.MUTED), 1.4, Qt.DashLine)
        pen.setDashPattern([3, 4])
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 10, 10)

    def _paint_anchor(self, p: QPainter, cid: int, a: Anchor) -> None:
        r = self.map_bbox(a.bbox).adjusted(-7, -6, 7, 6)
        active = cid in (self._selected, self._hovered)
        fill = QColor(*theme.HIGHLIGHT)
        if active:
            fill.setAlpha(34)
        p.setBrush(fill)
        if a.pending:
            pen = QPen(QColor(theme.INK), 1.4, Qt.DashLine)
            pen.setDashPattern([2, 3])
        else:
            pen = QPen(QColor(theme.INK), 2.4 if active else 1.3)
        p.setPen(pen)
        p.drawRoundedRect(r, 10, 10)

        # Numbered tab on the top-right corner (inverted when active).
        tab = QRectF(r.right() - 12, r.top() - 11, 24, 22)
        p.setPen(QPen(QColor(theme.INK), 1.3))
        p.setBrush(QColor(theme.INK) if active or a.heads_up else QColor(theme.PAPER))
        p.drawRoundedRect(tab, 11, 11)
        f = QFont(self.font())
        f.setPointSize(11)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.PAPER) if active or a.heads_up else QColor(theme.INK))
        p.drawText(tab, Qt.AlignCenter, "!" if a.heads_up and not active else str(a.number))

    def _paint_rec(self, p: QPainter, page: QRectF) -> None:
        pill = QRectF(page.left() + 14, page.bottom() - 40, 74, 26)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.INK))
        p.drawRoundedRect(pill, 13, 13)
        p.setBrush(QColor(theme.PAPER))
        p.drawEllipse(QRectF(pill.left() + 11, pill.center().y() - 4, 8, 8))
        f = QFont(self.font())
        f.setPointSize(11)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.PAPER))
        p.drawText(pill.adjusted(26, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, "REC")
