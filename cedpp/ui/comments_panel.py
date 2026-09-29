"""Right-hand margin: cards float beside their anchor, like Google Docs comments."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ..comments import Comment
from . import theme
from .comment_card import CARD_WIDTH, CommentCard

GAP = 10


def layout_cards(items: List[Tuple[int, float, int]], selected: Optional[int],
                 top: float = 0.0, gap: float = GAP) -> Dict[int, float]:
    """Place cards as close to their anchors as possible without overlapping.

    items: (id, desired_y, height). The selected card sits exactly beside its
    anchor and the others make room around it (the Google Docs behaviour).
    """
    items = sorted(items, key=lambda it: (it[1], it[0]))
    ys: Dict[int, float] = {}
    idx = next((i for i, it in enumerate(items) if it[0] == selected), None)
    if idx is None:
        cursor = top
        for cid, desired, h in items:
            ys[cid] = max(desired, cursor)
            cursor = ys[cid] + h + gap
        return ys
    cid, desired, h = items[idx]
    ys[cid] = max(desired, top)
    cursor = ys[cid] + h + gap
    for cid, desired, h in items[idx + 1:]:
        ys[cid] = max(desired, cursor)
        cursor = ys[cid] + h + gap
    ceiling = ys[items[idx][0]]
    for cid, desired, h in reversed(items[:idx]):
        ys[cid] = min(desired, ceiling - gap - h)
        ceiling = ys[cid]
    if items and ys[items[0][0]] < top:     # ran off the top: fall back to stacking
        return layout_cards(items, None, top, gap)
    return ys


class CommentsPanel(QFrame):
    card_clicked = Signal(int)
    resolve_requested = Signal(int)
    retry_requested = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(CARD_WIDTH + 36)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(18, 18, 18, 6)
        title = QLabel("COMMENTS")
        title.setObjectName("SectionTitle")
        self.count_label = QLabel("")
        self.count_label.setObjectName("Small")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.count_label)
        outer.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.canvas = QWidget()
        self.canvas.setFixedWidth(CARD_WIDTH + 30)
        self.scroll.setWidget(self.canvas)
        outer.addWidget(self.scroll, 1)

        self.empty = QLabel(
            "Ced++ leaves comments here as you write.\n\n"
            "Connect your Supernote, press Record,\nand start writing.")
        self.empty.setParent(self.canvas)
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setFixedWidth(CARD_WIDTH)
        self.empty.setStyleSheet(f"color: {theme.MUTED}; border: 1.2px dashed {theme.RULE}; "
                                 "border-radius: 16px; padding: 22px;")
        self.empty.move(12, 8)

        self.cards: Dict[int, CommentCard] = {}
        self._anims: Dict[int, QPropertyAnimation] = {}
        self.selected: Optional[int] = None

    # ------------------------------------------------------------------ cards
    def upsert(self, comment: Comment) -> CommentCard:
        card = self.cards.get(comment.id)
        if card is None:
            card = CommentCard(comment, self.canvas)
            card.clicked.connect(self.card_clicked)
            card.resolve_requested.connect(self.resolve_requested)
            card.retry_requested.connect(self.retry_requested)
            self.cards[comment.id] = card
            card.show()
        else:
            card.update_from(comment)
        return card

    def remove(self, comment_id: int) -> None:
        card = self.cards.pop(comment_id, None)
        if card is not None:
            anim = self._anims.pop(comment_id, None)
            if anim:
                anim.stop()
            card.deleteLater()

    def show_only(self, comments: List[Comment]) -> None:
        """Keep exactly these comments (e.g. after a page turn)."""
        keep = {c.id for c in comments}
        for cid in list(self.cards):
            if cid not in keep:
                self.remove(cid)
        for c in comments:
            self.upsert(c)

    def set_selected(self, comment_id: Optional[int]) -> None:
        self.selected = comment_id
        for cid, card in self.cards.items():
            card.set_selected(cid == comment_id)

    # ------------------------------------------------------------------ layout
    def relayout(self, desired: Dict[int, float], animate: bool = True) -> None:
        """desired: comment id -> y (in canvas coordinates) of its anchor."""
        self.empty.setVisible(not self.cards)
        n = len(self.cards)
        self.count_label.setText(f"{n} on this page" if n else "")
        items = []
        for cid, card in self.cards.items():
            card.fit_height()
            items.append((cid, desired.get(cid, 0.0), card.height()))
        ys = layout_cards(items, self.selected, top=8)
        bottom = 0
        for cid, y in ys.items():
            card = self.cards[cid]
            x = 4 if cid == self.selected else 14     # selected card nudges left
            target = QPoint(x, int(y))
            bottom = max(bottom, int(y) + card.height())
            if not animate or not card.isVisible() or card.pos() == QPoint(0, 0):
                card.move(target)
                continue
            anim = self._anims.get(cid)
            if anim is None:
                anim = QPropertyAnimation(card, b"pos", self)
                anim.setDuration(180)
                anim.setEasingCurve(QEasingCurve.OutCubic)
                self._anims[cid] = anim
            anim.stop()
            anim.setEndValue(target)
            anim.start()
        self.canvas.setFixedHeight(max(self.scroll.viewport().height(), bottom + 40))

    def canvas_y_for(self, global_y: int) -> float:
        return float(self.canvas.mapFromGlobal(QPoint(0, global_y)).y())

    def scroll_to(self, comment_id: int) -> None:
        card = self.cards.get(comment_id)
        if card:
            self.scroll.ensureWidgetVisible(card, 0, 40)
