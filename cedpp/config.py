"""All tunables for SuperNote(Ced++) in one place."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

APP_NAME = "SuperNote(Ced++)"
APP_VERSION = "0.1.0"
ASSISTANT_NAME = "Ced++"


@dataclass(frozen=True)
class MirrorConfig:
    port: int = 8080
    path: str = "/screencast.mjpeg"
    connect_timeout_s: float = 5.0
    reconnect_delay_s: float = 2.0
    # Frames taller than this are halved before ink tracking (display stays full-res).
    track_max_height: int = 2000


@dataclass(frozen=True)
class InkConfig:
    # A pixel counts as new ink when it got this much darker than the baseline...
    darken_threshold: int = 55
    # ...and is now at least this dark.
    ink_max_value: int = 160
    # Pixels are pooled into square cells; a cell with this many ink pixels is "inked".
    cell_px: int = 12
    cell_min_pixels: int = 3
    # Comment once the pen has rested this long...
    pause_s: float = 2.5
    # ...or, during non-stop writing, after this long (at the next short gap).
    max_batch_s: float = 12.0
    min_gap_s: float = 0.8
    # Ignore specks smaller than this many cells.
    min_cluster_cells: int = 4
    # Cells this far apart still belong to the same piece of writing.
    cluster_gap_cells: int = 3
    # If more than this fraction of the page changes at once, it's a page turn.
    page_change_fraction: float = 0.18
    page_settle_s: float = 0.8
    crop_padding_px: int = 28
    # Fractions of the frame to ignore (e.g. a status bar in the mirror).
    ignore_top: float = 0.0
    ignore_bottom: float = 0.0


@dataclass(frozen=True)
class TutorConfig:
    model: str = "claude-opus-5"
    effort: str = "low"          # fast, short tips; raise to "medium" for deeper ones
    study_effort: str = "medium" # Summarize / Exam takeaways (not time-critical)
    max_tokens: int = 4000
    history_items: int = 8       # recent comments sent as context to avoid repeats
    max_parallel: int = 3


@dataclass(frozen=True)
class AppConfig:
    mirror: MirrorConfig = field(default_factory=MirrorConfig)
    ink: InkConfig = field(default_factory=InkConfig)
    tutor: TutorConfig = field(default_factory=TutorConfig)
    sessions_dir: Path = PROJECT_ROOT / "sessions"
    library_dir: Path = PROJECT_ROOT / "library"
