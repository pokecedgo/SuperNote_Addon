"""Tutor interface: look at new handwriting, return one short comment."""
from __future__ import annotations

import io
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


class TutorError(Exception):
    """Message is safe to show in a comment card."""


@dataclass
class Tip:
    skip: bool                       # nothing worth commenting on (stray marks, UI...)
    recognized: str = ""             # what Ced++ read, e.g. "∇f = ⟨∂f/∂x, ∂f/∂y⟩"
    title: str = ""                  # short name, e.g. "Gradient formula"
    comment: str = ""                # 1-2 friendly sentences
    extras: List[str] = field(default_factory=list)  # related things worth writing down
    heads_up: bool = False           # True when pointing out a likely mistake

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TutorRequest:
    crop: np.ndarray                 # gray image of the new writing
    page: np.ndarray                 # whole page for context
    bbox: Tuple[int, int, int, int]
    history: List[str] = field(default_factory=list)  # recent comment titles on this page
    requested: bool = False          # the student circled this area and asked for help
    question: str = ""               # optional question typed with the request


class NoteTutor(ABC):
    name = "tutor"

    @abstractmethod
    def analyze(self, request: TutorRequest) -> Tip:
        """Blocking call - run it off the UI thread. Raise TutorError on failure."""


def zone_crop(page: np.ndarray, polygon: List[Tuple[int, int]], pad: int = 24) -> Tuple[
        np.ndarray, Tuple[int, int, int, int]]:
    """Crop to a freehand zone; everything outside the loop is whited out."""
    pts = np.asarray(polygon, dtype=np.int32)
    h, w = page.shape[:2]
    x1, y1 = max(0, int(pts[:, 0].min()) - pad), max(0, int(pts[:, 1].min()) - pad)
    x2, y2 = min(w, int(pts[:, 0].max()) + pad), min(h, int(pts[:, 1].max()) + pad)
    mask = Image.new("L", (x2 - x1, y2 - y1), 0)
    ImageDraw.Draw(mask).polygon([(int(x) - x1, int(y) - y1) for x, y in pts], fill=255)
    inside = np.array(mask.filter(ImageFilter.MaxFilter(9))) > 0   # small margin around the loop
    crop = page[y1:y2, x1:x2].copy()
    crop[~inside] = 255
    return crop, (x1, y1, x2, y2)


def png_bytes(gray: np.ndarray, max_side: int = 1400,
              box: Optional[Tuple[int, int, int, int]] = None) -> bytes:
    """Encode a gray image as PNG, downscaled, optionally with a box drawn on it."""
    img = Image.fromarray(gray).convert("L")
    scale = min(1.0, max_side / float(max(img.size)))
    if box is not None:
        img = img.convert("RGB")
        ImageDraw.Draw(img).rectangle(box, outline=(220, 40, 40), width=6)
    if scale < 1.0:
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
