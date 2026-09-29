"""Comment model + session store (saved as JSON and Markdown when you stop)."""
from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from .ink import BBox
from .tutor import Tip


class Status(str, Enum):
    PENDING = "pending"      # Ced++ is reading it
    READY = "ready"
    ERROR = "error"
    SKIPPED = "skipped"      # nothing worth saying - not shown
    RESOLVED = "resolved"    # dismissed by the user


@dataclass
class Comment:
    id: int
    page_index: int
    bbox: BBox
    created_at: datetime
    status: Status = Status.PENDING
    tip: Optional[Tip] = None
    error: str = ""
    number: int = 0                       # 1, 2, 3... per page, shown on the anchor
    crop: Optional[np.ndarray] = field(default=None, repr=False)
    page: Optional[np.ndarray] = field(default=None, repr=False)
    zone: Optional[List[Tuple[int, int]]] = None   # freehand loop drawn by the user
    question: str = ""
    audio_t: Optional[float] = None       # seconds into the lecture recording

    @property
    def requested(self) -> bool:
        return self.zone is not None

    @property
    def visible(self) -> bool:
        return self.status in (Status.PENDING, Status.READY, Status.ERROR)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "page": self.page_index + 1, "number": self.number,
            "bbox": list(self.bbox), "created_at": self.created_at.isoformat(timespec="seconds"),
            "status": self.status.value, "tip": self.tip.to_dict() if self.tip else None,
            "error": self.error or None,
            "requested": self.requested, "question": self.question or None,
            "zone": [list(p) for p in self.zone] if self.zone else None,
            "audio_t": round(self.audio_t, 1) if self.audio_t is not None else None,
        }


class CommentStore:
    def __init__(self) -> None:
        self._ids = itertools.count(1)
        self.comments: Dict[int, Comment] = {}
        self._page_numbers: Dict[int, itertools.count] = {}

    def add(self, page_index: int, bbox: BBox, crop=None, page=None,
            zone=None, question: str = "") -> Comment:
        counter = self._page_numbers.setdefault(page_index, itertools.count(1))
        c = Comment(next(self._ids), page_index, bbox, datetime.now(), crop=crop, page=page,
                    number=next(counter), zone=zone, question=question)
        self.comments[c.id] = c
        return c

    def get(self, comment_id: int) -> Optional[Comment]:
        return self.comments.get(comment_id)

    def for_page(self, page_index: int) -> List[Comment]:
        return [c for c in self.comments.values() if c.page_index == page_index and c.visible]

    def history(self, page_index: int, limit: int) -> List[str]:
        done = [c for c in self.comments.values()
                if c.page_index == page_index and c.tip and c.status in (Status.READY, Status.RESOLVED)]
        return [f"{c.tip.title}: {c.tip.recognized}" for c in done][-limit:]

    def to_markdown(self, title: str) -> str:
        lines = [f"# {title}", ""]
        pages = sorted({c.page_index for c in self.comments.values()})
        for p in pages:
            items = [c for c in self.comments.values()
                     if c.page_index == p and c.tip and c.status in (Status.READY, Status.RESOLVED)]
            if not items:
                continue
            lines += [f"## Page {p + 1}", ""]
            for c in items:
                t = c.tip
                flag = " ⚠️" if t.heads_up else ""
                if c.question:
                    lines.append(f"> You asked: {c.question}  ")
                lines.append(f"**{c.number}. {t.title}**{flag} — `{t.recognized}`  ")
                lines.append(t.comment)
                lines += [f"- {e}" for e in t.extras]
                lines.append("")
        return "\n".join(lines)

    def save_session(self, directory: Path, pages: Dict[int, np.ndarray],
                     folder: Optional[Path] = None) -> Path:
        """Write comments.json, notes.md and page PNGs into a timestamped folder."""
        from PIL import Image

        folder = folder or directory / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        folder.mkdir(parents=True, exist_ok=True)
        data = [c.to_dict() for c in self.comments.values() if c.status != Status.SKIPPED]
        (folder / "comments.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
        (folder / "notes.md").write_text(
            self.to_markdown(f"Ced++ comments · {datetime.now():%b %d, %Y %H:%M}"))
        for index, page in pages.items():
            Image.fromarray(page).save(folder / f"page_{index + 1}.png")
        return folder
