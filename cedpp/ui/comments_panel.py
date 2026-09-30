"""Right-hand margin: cards float beside their anchor, like Google Docs comments."""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ..comments import Comment
from . import theme
from .comment_card import CARD_WIDTH, CommentCard

GAP = 10


class CommentsPanel(QFrame):
    card_clicked = Signal(int)
    resolve_requested = Signal(int)
    retry_requested = Signal(int)
    play_requested = Signal(int)

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
        self.title = title
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
            card.play_requested.connect(self.play_requested)
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
    def set_page(self, page_number: int) -> None:
        self.title.setText(f"COMMENTS · PAGE {page_number}")
        self.empty.setText("No comments on this page yet.\n\nPress Record and start writing, "
                           "or use Ask to circle something.")

    def relayout(self, desired: Optional[Dict[int, float]] = None, animate: bool = True) -> None:
        """Stack the cards newest first (comment ids increase over time)."""
        self.empty.setVisible(not self.cards)
        n = len(self.cards)
        self.count_label.setText(f"{n} comment{'s' if n != 1 else ''}" if n else "")
        y, bottom = 8, 0
        for cid in sorted(self.cards, reverse=True):
            card = self.cards[cid]
            card.fit_height()
            x = 4 if cid == self.selected else 14     # selected card nudges left
            target = QPoint(x, y)
            y += card.height() + GAP
            bottom = y
            if not animate or not card.isVisible() or card.pos() == QPoint(0, 0):
                card.move(target)
                continue
            anim = self._anims.get(cid)
            if anim is None:
                anim = QPropertyAnimation(card, b"pos", self)
                anim.setDuration(200)
                anim.setEasingCurve(QEasingCurve.OutCubic)
                self._anims[cid] = anim
            anim.stop()
            anim.setEndValue(target)
            anim.start()
        self.canvas.setFixedHeight(max(self.scroll.viewport().height(), bottom + 30))

    def scroll_to_top(self) -> None:
        self.scroll.verticalScrollBar().setValue(0)

    def scroll_to(self, comment_id: int) -> None:
        card = self.cards.get(comment_id)
        if card:
            self.scroll.ensureWidgetVisible(card, 0, 40)
