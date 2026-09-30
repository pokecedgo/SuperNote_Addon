"""Detects what you *newly* wrote on the mirrored page.

Pure numpy (no Qt) so it's fast to test. Feed it every frame with `update()`:

* baseline      - the page as it was when Record was pressed (or last committed)
* new ink       - pixels that got clearly darker than the baseline
* erasing       - pixels that got lighter are folded into the baseline, so you
                  can rewrite in the same spot
* pause         - once the ink stops changing for `pause_s`, the new writing is
                  grouped into clusters and returned as `InkEvent`s, then committed
* page turn     - a large change is ignored; PageIdentifier picks the page and
                  calls reset()
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from ..config import InkConfig

BBox = Tuple[int, int, int, int]  # x1, y1, x2, y2 (page pixels)


@dataclass
class InkEvent:
    bbox: BBox                  # tight box around the new ink (the comment anchor)
    crop: np.ndarray            # padded gray crop of the new writing
    page: np.ndarray            # full page snapshot for context
    page_index: int


@dataclass
class TrackerUpdate:
    events: List[InkEvent] = field(default_factory=list)
    page_index: int = 0
    pending_bbox: Optional[BBox] = None   # writing in progress (not yet commented)


def pad_bbox(bbox: BBox, pad: int, shape) -> BBox:
    h, w = shape[:2]
    x1, y1, x2, y2 = bbox
    return max(0, x1 - pad), max(0, y1 - pad), min(w, x2 + pad), min(h, y2 + pad)


def _dilate(mask: np.ndarray, r: int) -> np.ndarray:
    """Square binary dilation by r cells using shifted ORs (no scipy needed)."""
    out = mask.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx == 0 and dy == 0:
                continue
            shifted = np.zeros_like(mask)
            ys = slice(max(0, dy), mask.shape[0] + min(0, dy))
            yd = slice(max(0, -dy), mask.shape[0] + min(0, -dy))
            xs = slice(max(0, dx), mask.shape[1] + min(0, dx))
            xd = slice(max(0, -dx), mask.shape[1] + min(0, -dx))
            shifted[ys, xs] = mask[yd, xd]
            out |= shifted
    return out


def _components(mask: np.ndarray) -> List[np.ndarray]:
    """4-connected components of a small boolean grid, as arrays of (y, x)."""
    seen = np.zeros_like(mask, dtype=bool)
    comps = []
    h, w = mask.shape
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        stack = deque([(y0, x0)])
        seen[y0, x0] = True
        cells = []
        while stack:
            y, x = stack.pop()
            cells.append((y, x))
            for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        comps.append(np.array(cells))
    return comps


class InkTracker:
    def __init__(self, config: InkConfig = InkConfig()) -> None:
        self.cfg = config
        self.page_index = 0
        self.baseline: Optional[np.ndarray] = None
        self._prev_cells: Optional[np.ndarray] = None
        self._last_change = 0.0
        self._first_ink: Optional[float] = None

    # ------------------------------------------------------------------ control
    def start(self, frame: np.ndarray) -> None:
        """Begin tracking: everything already on the page is ignored."""
        self.baseline = frame.copy()
        self._reset_pending()

    def stop(self) -> None:
        self.baseline = None
        self._reset_pending()

    def reset(self, frame: np.ndarray, page_index: int) -> None:
        """A different page is showing: only writing added from now on is new."""
        self.page_index = page_index
        if self.baseline is not None:
            self.start(frame)

    @property
    def active(self) -> bool:
        return self.baseline is not None

    def _reset_pending(self) -> None:
        self._prev_cells = None
        self._first_ink = None
        self._last_change = 0.0

    # ------------------------------------------------------------------ helpers
    def _valid_region(self, shape) -> Tuple[int, int]:
        h = shape[0]
        return int(h * self.cfg.ignore_top), h - int(h * self.cfg.ignore_bottom)

    def _ink_cells(self, frame: np.ndarray) -> np.ndarray:
        c = self.cfg
        darker = self.baseline.astype(np.int16) - frame.astype(np.int16)
        ink = (darker > c.darken_threshold) & (frame < c.ink_max_value)
        top, bottom = self._valid_region(frame.shape)
        ink[:top] = False
        ink[bottom:] = False
        h, w = ink.shape
        ch, cw = h // c.cell_px, w // c.cell_px
        pooled = ink[:ch * c.cell_px, :cw * c.cell_px].reshape(ch, c.cell_px, cw, c.cell_px)
        return pooled.sum(axis=(1, 3)) >= c.cell_min_pixels

    def _cells_to_bbox(self, cells: np.ndarray, shape, pad: int = 0) -> BBox:
        c = self.cfg.cell_px
        y1, x1 = cells.min(axis=0)
        y2, x2 = cells.max(axis=0) + 1
        h, w = shape[:2]
        return (max(0, int(x1 * c) - pad), max(0, int(y1 * c) - pad),
                min(w, int(x2 * c) + pad), min(h, int(y2 * c) + pad))

    def _clusters(self, cells: np.ndarray, shape) -> List[BBox]:
        grouped = _dilate(cells, self.cfg.cluster_gap_cells)
        boxes = []
        for comp in _components(grouped):
            real = comp[cells[comp[:, 0], comp[:, 1]]]
            if len(real) >= self.cfg.min_cluster_cells:
                boxes.append(self._cells_to_bbox(real, shape))
        if len(boxes) > 3:  # scattered writing - one comment for the lot
            xs1, ys1, xs2, ys2 = zip(*boxes)
            boxes = [(min(xs1), min(ys1), max(xs2), max(ys2))]
        return sorted(boxes, key=lambda b: (b[1], b[0]))

    # ------------------------------------------------------------------ main
    def update(self, frame: np.ndarray, now: float) -> TrackerUpdate:
        result = TrackerUpdate(page_index=self.page_index)
        if self.baseline is None:
            return result
        if frame.shape != self.baseline.shape:  # orientation/resolution change
            self.start(frame)
            return result
        c = self.cfg

        # Most of the screen changed (page turn, menu): not handwriting. The
        # PageIdentifier decides which page this is and calls reset().
        changed = np.abs(frame.astype(np.int16) - self.baseline.astype(np.int16)) > c.darken_threshold
        if changed.mean() > c.page_change_fraction:
            self._reset_pending()
            return result

        # Erasing: accept lighter pixels into the baseline.
        lighter = frame.astype(np.int16) - self.baseline.astype(np.int16) > c.darken_threshold
        if lighter.any():
            self.baseline[lighter] = frame[lighter]

        cells = self._ink_cells(frame)
        if not cells.any():
            self._reset_pending()
            return result

        if self._prev_cells is None or (cells ^ self._prev_cells).any():
            self._last_change = now
        if self._first_ink is None:
            self._first_ink = now
        self._prev_cells = cells

        ys, xs = np.nonzero(cells)
        result.pending_bbox = self._cells_to_bbox(np.stack([ys, xs], axis=1), frame.shape)

        idle = now - self._last_change
        long_batch = now - self._first_ink >= c.max_batch_s and idle >= c.min_gap_s
        if idle >= c.pause_s or long_batch:
            for bbox in self._clusters(cells, frame.shape):
                x1, y1, x2, y2 = pad_bbox(bbox, c.crop_padding_px, frame.shape)
                result.events.append(InkEvent(bbox, frame[y1:y2, x1:x2].copy(),
                                              frame.copy(), self.page_index))
            self.baseline = frame.copy()   # commit: this writing is handled
            self._reset_pending()
            result.pending_bbox = None
        return result
