"""Recognises which page is on screen, so each page keeps its own comments.

Every frame is reduced to a small grid of "does this cell contain ink" (a page
fingerprint). When the fingerprint changes a lot and then holds still, a new
screen is showing: it's matched against pages seen before (so going back to
page 2 brings page 2's comments back), otherwise it becomes a new page.
Menus and the file browser count as screens too - their comments, if any,
never mix with your notes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np

CELL = 16            # px per fingerprint cell (1404x1872 -> 87x117 grid)
INK = 150            # a cell holds ink if its darkest pixel is below this


def fingerprint(frame: np.ndarray, cell: int = CELL) -> np.ndarray:
    h, w = frame.shape[:2]
    gh, gw = h // cell, w // cell
    pooled = frame[:gh * cell, :gw * cell].reshape(gh, cell, gw, cell).min(axis=(1, 3))
    return pooled < INK


def difference(a: np.ndarray, b: np.ndarray) -> float:
    """0 = same ink layout, 1 = nothing in common (share of differing ink cells)."""
    if a.shape != b.shape:
        return 1.0
    union = np.count_nonzero(a | b)
    if union < 12:                     # both (nearly) blank: can't tell them apart
        return 0.0
    return np.count_nonzero(a ^ b) / union


@dataclass
class PageSwitch:
    index: int
    is_new: bool


class PageIdentifier:
    def __init__(self, switch_threshold: float = 0.45, match_threshold: float = 0.35,
                 settle_s: float = 0.8, min_switch_cells: int = 120) -> None:
        self.switch_threshold = switch_threshold   # this different -> a page switch
        # ...and at least this many cells changed. On a nearly empty page a single
        # word is a large *share* of the ink, but only a few dozen cells.
        self.min_switch_cells = min_switch_cells
        self.match_threshold = match_threshold     # at most this different -> same page
        self.settle_s = settle_s
        self.pages: List[np.ndarray] = []          # latest fingerprint of each page
        self.current: Optional[int] = None
        self._candidate: Optional[np.ndarray] = None
        self._candidate_since = 0.0

    def update(self, frame: np.ndarray, now: float) -> Optional[PageSwitch]:
        fp = fingerprint(frame)
        if self.current is None:                   # first frame ever
            self.pages.append(fp)
            self.current = 0
            return PageSwitch(0, True)

        current = self.pages[self.current]
        changed = np.count_nonzero(fp ^ current) if fp.shape == current.shape else fp.size
        if difference(fp, current) < self.switch_threshold or changed < self.min_switch_cells:
            self.pages[self.current] = fp          # same page (maybe with new writing)
            self._candidate = None
            return None

        # Something else is on screen; wait until it stops changing.
        if self._candidate is None or difference(fp, self._candidate) > 0.08:
            self._candidate, self._candidate_since = fp, now
            return None
        if now - self._candidate_since < self.settle_s:
            return None
        self._candidate = None
        return self._switch_to(fp)

    def _switch_to(self, fp: np.ndarray) -> PageSwitch:
        scores = [(difference(fp, known), i) for i, known in enumerate(self.pages)
                  if i != self.current]
        best = min(scores, default=(1.0, -1))
        if best[0] <= self.match_threshold:
            self.current = best[1]
            self.pages[self.current] = fp
            return PageSwitch(self.current, False)
        self.pages.append(fp)
        self.current = len(self.pages) - 1
        return PageSwitch(self.current, True)
