"""Popup after a recording: important things said outside the lecture topic."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from ..tutor.side_notes import ANNOUNCEMENT_KINDS
from . import theme

KIND_LABEL = {"exam": "EXAM", "deadline": "DEADLINE", "assignment": "HOMEWORK",
              "event": "EVENT", "logistics": "CLASS INFO", "advice": "TIP",
              "analogy": "ANALOGY", "story": "STORY", "other": "ASIDE"}


def _parse_time(stamp: str) -> Optional[float]:
    parts = stamp.strip("[] ").split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    secs = 0
    for n in nums:
        secs = secs * 60 + n
    return float(secs)


class DigestItem(QFrame):
    def __init__(self, item: dict, play: Optional[Callable[[float], None]]) -> None:
        super().__init__()
        high = item.get("importance") == "high"
        self.setObjectName("DigestItem")
        self.setStyleSheet(f"""
            #DigestItem {{ background: {theme.PAPER};
                           border: {'2px solid ' + theme.INK if high else '1.2px solid ' + theme.RULE};
                           border-radius: 16px; }}
        """)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 12, 12, 12)
        row.setSpacing(12)
        col = QVBoxLayout()
        col.setSpacing(5)
        head = QHBoxLayout()
        head.setSpacing(8)
        chip = QLabel(KIND_LABEL.get(item.get("kind", ""), "NOTE"))
        chip.setStyleSheet(
            f"background: {theme.INK if high else theme.PAPER}; color: {theme.PAPER if high else theme.INK};"
            f" border: 1.2px solid {theme.INK}; border-radius: 9px; padding: 1px 8px;"
            " font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        head.addWidget(chip)
        if item.get("cue"):
            cue = QLabel(f"heard: “{item['cue']}”")
            cue.setTextFormat(Qt.PlainText)
            cue.setObjectName("Small")
            head.addWidget(cue)
        head.addStretch(1)
        col.addLayout(head)
        summary = QLabel(item.get("summary", ""))
        summary.setTextFormat(Qt.PlainText)
        summary.setWordWrap(True)
        summary.setStyleSheet("font-size: 15px; font-weight: 700;" if high else "font-size: 14px;")
        col.addWidget(summary)
        if item.get("quote"):
            quote = QLabel(f"“{item['quote']}”")
            quote.setTextFormat(Qt.PlainText)
            quote.setWordWrap(True)
            quote.setStyleSheet(f"color: {theme.MUTED}; font-style: italic; font-size: 12.5px;")
            col.addWidget(quote)
        row.addLayout(col, 1)
        at = _parse_time(item.get("start", ""))
        if play is not None and at is not None:
            btn = QPushButton(f"▶  {item.get('start', '')}")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip("Hear this moment")
            btn.clicked.connect(lambda: play(max(0.0, at - 3)))
            row.addWidget(btn, 0, Qt.AlignTop)


class LectureDigestDialog(QDialog):
    def __init__(self, result: dict, folder: Path, play: Optional[Callable[[float], None]],
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("From today's lecture")
        self.resize(640, 680)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 18)
        root.setSpacing(10)

        title = QLabel("Heads-up from today's lecture")
        title.setStyleSheet("font-size: 21px; font-weight: 700;")
        root.addWidget(title)
        topic = result.get("lecture_topic") or ""
        sub = QLabel((f"Lecture: {topic}. " if topic else "")
                     + "Things the teacher mentioned outside the topic, most important first.")
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        root.addWidget(sub)

        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 6, 6, 6)
        lay.setSpacing(10)
        items = result.get("items", [])
        announcements = [i for i in items if i.get("kind") in ANNOUNCEMENT_KINDS]
        asides = [i for i in items if i.get("kind") not in ANNOUNCEMENT_KINDS]
        for label, group in (("IMPORTANT — NOT PART OF THE LECTURE", announcements),
                             ("ASIDES, TIPS & ANALOGIES", asides)):
            if not group:
                continue
            section = QLabel(label)
            section.setObjectName("SectionTitle")
            lay.addWidget(section)
            for item in group:
                lay.addWidget(DigestItem(item, play))
        if not items:
            empty = QLabel("Nothing outside the lecture topic was mentioned.")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"color: {theme.MUTED}; border: 1.2px dashed {theme.RULE};"
                                " border-radius: 16px; padding: 30px;")
            lay.addWidget(empty)
        lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        foot = QHBoxLayout()
        saved = QLabel(f"Saved with the transcript and audio in "
                       f"{folder.parent.name}/{folder.name}/")
        saved.setObjectName("Small")
        foot.addWidget(saved, 1)
        close = QPushButton("Got it")
        close.setDefault(True)
        close.setStyleSheet(f"background: {theme.INK}; color: {theme.PAPER};")
        close.clicked.connect(self.accept)
        foot.addWidget(close)
        root.addLayout(foot)
