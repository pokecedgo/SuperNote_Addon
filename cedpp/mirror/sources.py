"""Frame sources. Each yields grayscale page frames (numpy uint8, H x W)."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator, List, Optional

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

from .mjpeg import iter_jpegs, open_stream


def qimage_to_gray(image: QImage) -> np.ndarray:
    gray = image.convertToFormat(QImage.Format_Grayscale8)
    h, w = gray.height(), gray.width()
    arr = np.frombuffer(gray.constBits(), np.uint8, count=gray.bytesPerLine() * h)
    return arr.reshape(h, gray.bytesPerLine())[:, :w].copy()


class FrameSource(ABC):
    label = "source"

    @abstractmethod
    def frames(self) -> Iterator[np.ndarray]:
        """Yield frames until the source ends or raises (OSError = connection lost)."""

    def close(self) -> None:
        pass


class MirrorSource(FrameSource):
    """The Supernote's built-in Screen Mirroring stream."""

    label = "supernote"

    def __init__(self, url: str, timeout: float = 5.0) -> None:
        self.url = url
        self.timeout = timeout
        self._stream = None

    def frames(self) -> Iterator[np.ndarray]:
        self._stream = open_stream(self.url, self.timeout)
        try:
            for jpeg in iter_jpegs(self._stream):
                image = QImage.fromData(jpeg, "JPG")
                if not image.isNull():
                    yield qimage_to_gray(image)
        finally:
            self.close()

    def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass


@dataclass
class DemoLine:
    x: int
    y: int
    text: str
    size: int = 46


DEMO_SCRIPT: List[DemoLine] = [
    DemoLine(90, 150, "Calc III  -  Lecture 7", 58),
    DemoLine(90, 330, "Gradient:  ∇f = ⟨ ∂f/∂x , ∂f/∂y ⟩"),
    DemoLine(90, 520, "ex.  f(x,y) = x²y + 3y"),
    DemoLine(90, 640, "∇f = ⟨ 2xy , x² + 2 ⟩"),
    DemoLine(90, 860, "Chain rule:  dz/dt = fx·x'(t) + fy·y'(t)"),
]


class DemoNotebookSource(FrameSource):
    """A simulated Supernote page that 'writes' DEMO_SCRIPT with realistic pauses.

    Lets you try the whole app without a device (python app.py --demo).
    """

    label = "demo"
    size = (1404, 1872)  # Supernote A5 X portrait resolution

    def __init__(self, fps: float = 8.0, chars_per_s: float = 9.0, pause_s: float = 4.5,
                 start_delay_s: float = 2.0, script: Optional[List[DemoLine]] = None) -> None:
        self.fps = fps
        self.chars_per_s = chars_per_s
        self.pause_s = pause_s
        self.start_delay_s = start_delay_s
        self.script = script or DEMO_SCRIPT
        self._closed = False

    def _page(self) -> QImage:
        w, h = self.size
        page = QImage(w, h, QImage.Format_Grayscale8)
        page.fill(QColor("#ffffff"))
        p = QPainter(page)
        p.setPen(QPen(QColor(222, 222, 222), 2))
        for y in range(240, h - 80, 110):          # faint ruled lines
            p.drawLine(70, y + 40, w - 70, y + 40)
        p.end()
        return page

    def _render(self, progress: List[float]) -> np.ndarray:
        page = self._page()
        p = QPainter(page)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setPen(QColor(18, 18, 18))
        for line, frac in zip(self.script, progress):
            if frac <= 0:
                continue
            font = QFont("Bradley Hand", line.size)
            font.setBold(True)
            p.setFont(font)
            width = p.fontMetrics().horizontalAdvance(line.text) + 20
            p.save()
            p.setClipRect(QRectF(line.x, line.y - line.size * 1.4, width * frac, line.size * 2.2))
            p.drawText(line.x, line.y, line.text)
            p.restore()
        p.end()
        return qimage_to_gray(page)

    def frames(self) -> Iterator[np.ndarray]:
        self._closed = False
        durations = [max(1.0, len(line.text) / self.chars_per_s) for line in self.script]
        t0 = time.monotonic() + self.start_delay_s
        while not self._closed:
            t = time.monotonic() - t0
            progress = []
            cursor = 0.0
            for d in durations:
                progress.append(min(1.0, max(0.0, (t - cursor) / d)))
                cursor += d + self.pause_s
            yield self._render(progress)
            time.sleep(1.0 / self.fps)

    def close(self) -> None:
        self._closed = True
