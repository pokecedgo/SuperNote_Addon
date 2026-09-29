"""The mirrored Supernote page with comment anchors drawn on top."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPolygonF
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
    zone: Optional[List[Tuple[int, int]]] = None   # freehand loop (page pixels)


class PageView(QWidget):
    anchor_clicked = Signal(int)          # comment id
    background_clicked = Signal()
    layout_changed = Signal()             # page rect moved/resized -> re-align cards
    zone_drawn = Signal(object)           # list of (x, y) page pixels

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
        self._page_number = 0
        self._message = ("Turn on Screen Mirroring on your Supernote\n"
                         "(swipe down → Screen Mirroring), then click Connect.")
        self._last_rect = QRectF()
        # "Ask about area" lasso
        self._lasso = False
        self._stroke: List[QPointF] = []            # widget coords while dragging
        self._draft: Optional[List[Tuple[int, int]]] = None   # finished, awaiting question

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

    def set_lasso(self, on: bool) -> None:
        self._lasso = on
        self._stroke = []
        self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)
        self.update()

    @property
    def lasso(self) -> bool:
        return self._lasso

    def set_draft(self, zone: Optional[List[Tuple[int, int]]]) -> None:
        self._draft = zone
        self.update()

    def _to_page(self, pos: QPointF) -> Tuple[int, int]:
        page = self.page_rect()
        size = self.image_size()
        x = (min(max(pos.x(), page.left()), page.right()) - page.left()) * size.width() / page.width()
        y = (min(max(pos.y(), page.top()), page.bottom()) - page.top()) * size.height() / page.height()
        return int(x), int(y)

    def map_point(self, pt: Tuple[int, int]) -> QPointF:
        page = self.page_rect()
        size = self.image_size()
        return QPointF(page.x() + pt[0] * page.width() / size.width(),
                       page.y() + pt[1] * page.height() / size.height())

    def zone_bottom_left(self, zone: List[Tuple[int, int]]) -> QPointF:
        xs = [p[0] for p in zone]
        ys = [p[1] for p in zone]
        return self.map_point((min(xs), max(ys)))

    def set_page_number(self, n: int) -> None:
        self._page_number = n
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
            if a.zone and self._zone_path(a.zone).contains(pos):
                return cid
            if self.map_bbox(a.bbox).adjusted(-6, -6, 6, 6).contains(pos):
                return cid
        return None

    def mouseMoveEvent(self, event) -> None:
        if self._lasso:
            if self._stroke:
                pos = event.position()
                last = self._stroke[-1]
                if abs(pos.x() - last.x()) + abs(pos.y() - last.y()) > 2:
                    self._stroke.append(pos)
                    self.update()
            return
        hovered = self._anchor_at(event.position())
        if hovered != self._hovered:
            self._hovered = hovered
            self.setCursor(Qt.PointingHandCursor if hovered else Qt.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if not (self._lasso and self._stroke):
            return
        stroke, self._stroke = self._stroke, []
        zone = [self._to_page(pt) for pt in stroke]
        xs, ys = [p[0] for p in zone], [p[1] for p in zone]
        if len(zone) >= 6 and (max(xs) - min(xs)) * (max(ys) - min(ys)) >= 60 * 60:
            self._draft = zone
            self.zone_drawn.emit(zone)
        self.update()

    def mousePressEvent(self, event) -> None:
        if self._lasso:
            if event.button() == Qt.LeftButton and self._image is not None \
                    and self.page_rect().contains(event.position()):
                self._draft = None
                self._stroke = [event.position()]
                self.update()
            return
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
            self._paint_lasso(p)
            p.restore()

        if self._recording:
            self._paint_rec(p, page)
        if self._page_number and self._image is not None:
            f = QFont(self.font())
            f.setPointSize(11)
            f.setBold(True)
            p.setFont(f)
            label = f"Page {self._page_number}"
            tw = p.fontMetrics().horizontalAdvance(label) + 24
            pill = QRectF(page.right() - tw - 14, page.bottom() - 40, tw, 26)
            p.setPen(QPen(QColor(theme.INK), 1.2))
            p.setBrush(QColor(theme.PAPER))
            p.drawRoundedRect(pill, 13, 13)
            p.setPen(QColor(theme.INK))
            p.drawText(pill, Qt.AlignCenter, label)

    def _paint_pending(self, p: QPainter) -> None:
        if self._pending is None:
            return
        r = self.map_bbox(self._pending).adjusted(-4, -4, 4, 4)
        pen = QPen(QColor(theme.MUTED), 1.4, Qt.DashLine)
        pen.setDashPattern([3, 4])
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 10, 10)

    def _zone_path(self, zone: List[Tuple[int, int]]) -> QPainterPath:
        path = QPainterPath()
        path.addPolygon(QPolygonF([self.map_point(pt) for pt in zone]))
        path.closeSubpath()
        return path

    def _paint_lasso(self, p: QPainter) -> None:
        if self._stroke:
            p.setPen(QPen(QColor(theme.INK), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPolyline(QPolygonF(self._stroke))
        elif self._draft:
            path = self._zone_path(self._draft)
            p.fillPath(path, QColor(22, 22, 22, 26))
            pen = QPen(QColor(theme.INK), 2.0, Qt.DashLine, Qt.RoundCap, Qt.RoundJoin)
            pen.setDashPattern([4, 3])
            p.setPen(pen)
            p.drawPath(path)
        if self._lasso and not self._stroke and not self._draft:
            f = QFont(self.font())
            f.setPointSize(12)
            p.setFont(f)
            page = self.page_rect()
            text = "Draw a loop around what you want help with"
            tw = p.fontMetrics().horizontalAdvance(text) + 28
            pill = QRectF(page.center().x() - tw / 2, page.top() + 14, tw, 30)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.INK))
            p.drawRoundedRect(pill, 15, 15)
            p.setPen(QColor(theme.PAPER))
            p.drawText(pill, Qt.AlignCenter, text)

    def _paint_anchor(self, p: QPainter, cid: int, a: Anchor) -> None:
        if a.zone:
            self._paint_zone_anchor(p, cid, a)
            return
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

        self._paint_tab(p, r, a, active)

    def _paint_zone_anchor(self, p: QPainter, cid: int, a: Anchor) -> None:
        active = cid in (self._selected, self._hovered)
        path = self._zone_path(a.zone)
        fill = QColor(*theme.HIGHLIGHT)
        fill.setAlpha(34 if active else 20)
        p.fillPath(path, fill)
        if a.pending:
            pen = QPen(QColor(theme.INK), 1.6, Qt.DashLine, Qt.RoundCap, Qt.RoundJoin)
            pen.setDashPattern([2, 3])
        else:
            pen = QPen(QColor(theme.INK), 2.6 if active else 1.5, Qt.SolidLine, Qt.RoundCap,
                       Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        self._paint_tab(p, path.boundingRect(), a, active, asked=True)

    def _paint_tab(self, p: QPainter, r: QRectF, a: Anchor, active: bool,
                   asked: bool = False) -> None:
        # Numbered tab: top-right for auto comments, top-left for circled areas.
        page = self.page_rect()
        x = r.left() - 12 if asked else r.right() - 12
        x = min(max(x, page.left() + 4), page.right() - 28)      # keep it on the page
        tab = QRectF(x, max(r.top() - 11, page.top() + 4), 24, 22)
        p.setPen(QPen(QColor(theme.INK), 1.3))
        p.setBrush(QColor(theme.INK) if active or a.heads_up else QColor(theme.PAPER))
        p.drawRoundedRect(tab, 11, 11)
        f = QFont(self.font())
        f.setPointSize(11)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.PAPER) if active or a.heads_up else QColor(theme.INK))
        label = "!" if a.heads_up and not active else ("?" if asked and a.pending else str(a.number))
        p.drawText(tab, Qt.AlignCenter, label)

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
