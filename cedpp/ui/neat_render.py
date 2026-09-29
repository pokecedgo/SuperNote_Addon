"""Draws a Neat Copy page: the transcription in tidy handwriting on clean paper."""
from __future__ import annotations

from typing import List, Tuple

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPen

PAGE_W, PAGE_H = 1404, 1872          # same canvas as a Supernote page
MARGIN_X, TOP, BOTTOM = 110, 150, 110
INK = QColor(22, 22, 22)
LINE_GAP = 1.35

_STYLE = {                      # kind -> (size factor, bold, indent, spacing before)
    "heading": (1.35, True, 0, 1.2),
    "text": (1.0, False, 0, 0.5),
    "bullet": (1.0, False, 46, 0.3),
    "math": (1.12, False, 70, 0.6),
    "note": (0.86, False, 0, 0.5),
}


def _family() -> str:
    families = set(QFontDatabase.families())
    for name in ("Noteworthy", "Bradley Hand", "Chalkboard SE"):
        if name in families:
            return name
    return "Helvetica Neue"


def _layout(p: QPainter, blocks: List[dict], base: int) -> Tuple[bool, list]:
    """Measure every block at this base size; return (fits, placements)."""
    family = _family()
    width = PAGE_W - 2 * MARGIN_X
    y = TOP
    placed = []
    for block in blocks:
        kind = block.get("kind", "text")
        size_f, bold, indent, before = _STYLE.get(kind, _STYLE["text"])
        font = QFont(family)
        font.setPixelSize(int(base * size_f))
        font.setBold(bold)
        font.setItalic(kind == "note")
        p.setFont(font)
        text = block.get("text", "")
        if kind == "bullet":
            text = text.lstrip("•-* ").strip()
        y += int(base * before)
        rect = QRectF(MARGIN_X + indent, y, width - indent, 10_000)
        bound = p.boundingRect(rect, Qt.TextWordWrap | Qt.AlignLeft, text)
        h = bound.height() * (LINE_GAP if bound.height() < base * 2 else 1.08)
        placed.append((kind, text, font, QRectF(rect.x(), y, rect.width(), h)))
        y += h
    return y <= PAGE_H - BOTTOM, placed


def render_neat(blocks: List[dict]) -> QImage:
    image = QImage(PAGE_W, PAGE_H, QImage.Format_RGB32)
    image.fill(QColor("#ffffff"))
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)

    # Shrink the writing until the whole page fits.
    base = 50
    fits, placed = _layout(p, blocks, base)
    while not fits and base > 22:
        base -= 3
        fits, placed = _layout(p, blocks, base)

    for kind, text, font, rect in placed:
        p.setFont(font)
        p.setPen(INK)
        if kind == "bullet":
            p.drawText(QRectF(rect.x() - 34, rect.y(), 30, rect.height()),
                       Qt.AlignLeft | Qt.AlignTop, "•")
        p.drawText(rect, Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, text)
        if kind == "heading":
            p.setPen(QPen(INK, 2.4, Qt.SolidLine, Qt.RoundCap))
            w = min(rect.width(), p.fontMetrics().horizontalAdvance(text) + 8)
            underline_y = rect.y() + p.fontMetrics().height() + 4
            p.drawLine(int(rect.x()), int(underline_y), int(rect.x() + w), int(underline_y))
    p.end()
    return image
