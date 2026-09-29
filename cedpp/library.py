"""The notebook library: stored page snapshots organised in nested folders.

On disk (under library/):

    library/
      Calc III/                     <- a notebook (top-level folder)
        folder.json                 <- {"order": [page ids]}
        Midterm 1/                  <- folders can nest
          folder.json
          p_20260929_104512.png     <- page image
          p_20260929_104512.json    <- title, date, comments, summary, takeaways

Plain files on purpose: easy to back up, open in Finder, or sync.
"""
from __future__ import annotations

import json
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

FOLDER_META = "folder.json"
_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _is_page_image(path: Path) -> bool:
    return not path.stem.endswith("_neat")


class LibraryError(Exception):
    """Message is safe to show to the user."""


def clean_name(name: str) -> str:
    name = _BAD_CHARS.sub("-", name).strip().strip(".")
    if not name:
        raise LibraryError("Please enter a name.")
    if len(name) > 80:
        name = name[:80].rstrip()
    return name


@dataclass
class StoredPage:
    id: str
    folder: Path
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def image_path(self) -> Path:
        return self.folder / f"{self.id}.png"

    @property
    def meta_path(self) -> Path:
        return self.folder / f"{self.id}.json"

    @property
    def neat_path(self) -> Path:
        """Rendered neat copy (regenerated from meta['neat'] when missing)."""
        return self.folder / f"{self.id}_neat.png"

    @property
    def neat(self) -> Optional[dict]:
        return self.meta.get("neat")

    @property
    def transcript(self) -> str:
        return str((self.neat or {}).get("transcript", ""))

    @property
    def title(self) -> str:
        return str(self.meta.get("title") or "Untitled page")

    @property
    def created_at(self) -> datetime:
        try:
            return datetime.fromisoformat(self.meta["created_at"])
        except (KeyError, ValueError):
            return datetime.fromtimestamp(self.image_path.stat().st_mtime)

    @property
    def comments(self) -> List[dict]:
        return list(self.meta.get("comments") or [])


class Library:
    def __init__(self, root: Path) -> None:
        self.root = root

    # ------------------------------------------------------------------ paths
    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _inside(self, path: Path) -> Path:
        path = path.resolve()
        root = self.root.resolve()
        if path != root and root not in path.parents:
            raise LibraryError("That folder is outside the library.")
        return path

    def relative(self, folder: Path) -> str:
        """'Calc III / Midterm 1' style label."""
        rel = self._inside(folder).relative_to(self.root.resolve())
        return " / ".join(rel.parts)

    # ------------------------------------------------------------------ folders
    def notebooks(self) -> List[Path]:
        self.ensure()
        return self.subfolders(self.root)

    def subfolders(self, folder: Path) -> List[Path]:
        folder = self._inside(folder)
        if not folder.is_dir():
            return []
        return sorted((p for p in folder.iterdir() if p.is_dir() and not p.name.startswith(".")),
                      key=lambda p: p.name.lower())

    def create_folder(self, parent: Optional[Path], name: str) -> Path:
        """parent=None creates a notebook."""
        self.ensure()
        parent = self._inside(parent or self.root)
        target = parent / clean_name(name)
        if target.exists():
            raise LibraryError(f"'{target.name}' already exists here.")
        target.mkdir(parents=True)
        return target

    def delete_folder(self, folder: Path) -> None:
        folder = self._inside(folder)
        if folder == self.root.resolve():
            raise LibraryError("Can't delete the whole library.")
        shutil.rmtree(folder)

    def page_count(self, folder: Path) -> int:
        """Pages in this folder and everything below it."""
        folder = self._inside(folder)
        return sum(1 for p in folder.rglob("p_*.png") if _is_page_image(p)) if folder.is_dir() else 0

    # ------------------------------------------------------------------ order
    def _order_path(self, folder: Path) -> Path:
        return folder / FOLDER_META

    def _read_order(self, folder: Path) -> List[str]:
        try:
            return list(json.loads(self._order_path(folder).read_text()).get("order", []))
        except (OSError, json.JSONDecodeError):
            return []

    def _write_order(self, folder: Path, ids: List[str]) -> None:
        self._order_path(folder).write_text(json.dumps({"order": ids}, indent=2))

    def reorder(self, folder: Path, ids: List[str]) -> None:
        folder = self._inside(folder)
        existing = {p.id for p in self.pages(folder)}
        ordered = [i for i in ids if i in existing]
        ordered += [i for i in existing if i not in ordered]
        self._write_order(folder, ordered)

    # ------------------------------------------------------------------ pages
    def pages(self, folder: Path) -> List[StoredPage]:
        """Pages in this folder, in the user's order (new ones at the end)."""
        folder = self._inside(folder)
        if not folder.is_dir():
            return []
        found: Dict[str, StoredPage] = {}
        for img in folder.glob("p_*.png"):
            if not _is_page_image(img):
                continue
            page = StoredPage(img.stem, folder)
            try:
                page.meta = json.loads(page.meta_path.read_text())
            except (OSError, json.JSONDecodeError):
                page.meta = {}
            found[page.id] = page
        order = [i for i in self._read_order(folder) if i in found]
        rest = sorted((i for i in found if i not in order),
                      key=lambda i: found[i].created_at)
        return [found[i] for i in order + rest]

    def add_page(self, folder: Path, image: np.ndarray, title: str,
                 comments: Optional[List[dict]] = None) -> StoredPage:
        from PIL import Image

        folder = self._inside(folder)
        if not folder.is_dir():
            raise LibraryError("That folder no longer exists.")
        now = datetime.now()
        base = f"p_{now:%Y%m%d_%H%M%S}"
        pid, n = base, 2
        while (folder / f"{pid}.png").exists():
            pid, n = f"{base}_{n}", n + 1
        page = StoredPage(pid, folder, {
            "title": title.strip() or f"Page · {now:%b %d, %Y %H:%M}",
            "created_at": now.isoformat(timespec="seconds"),
            "comments": comments or [],
        })
        try:
            Image.fromarray(image).save(page.image_path)
            self.save(page)
        except OSError as exc:
            page.image_path.unlink(missing_ok=True)
            raise LibraryError(f"Couldn't save the page: {exc}") from exc
        self._write_order(folder, [p.id for p in self.pages(folder)])
        return page

    def save(self, page: StoredPage) -> None:
        page.meta_path.write_text(json.dumps(page.meta, indent=2, ensure_ascii=False))

    def update_meta(self, page: StoredPage, key: str, value: Any) -> None:
        """Set one field, merging with what's on disk so parallel jobs (neat copy,
        summary, takeaways) never overwrite each other's results."""
        try:
            current = json.loads(page.meta_path.read_text())
        except (OSError, json.JSONDecodeError):
            current = dict(page.meta)
        current[key] = value
        page.meta = current
        self.save(page)

    def delete_page(self, page: StoredPage) -> None:
        for path in (page.image_path, page.meta_path, page.neat_path):
            path.unlink(missing_ok=True)
        self._write_order(page.folder, [p.id for p in self.pages(page.folder)])

    # ------------------------------------------------------------------ search
    def all_pages(self) -> List[StoredPage]:
        self.ensure()
        out: List[StoredPage] = []
        stack = [self.root]
        while stack:
            folder = stack.pop()
            out += self.pages(folder)
            stack += self.subfolders(folder)
        return out

    def untranscribed(self) -> List[StoredPage]:
        return [p for p in self.all_pages() if not p.transcript]

    def search(self, query: str, limit: int = 60) -> List["SearchHit"]:
        terms = [t for t in _fold(query).split() if t]
        if not terms:
            return []
        phrase = " ".join(terms)
        hits: List[SearchHit] = []
        for page in self.all_pages():
            fields = _search_fields(page)
            folded = {name: _fold(text) for name, text in fields.items()}
            everything = " ".join(folded.values())
            if not all(t in everything for t in terms):
                continue
            score = 0.0
            for name, text in folded.items():
                weight = FIELD_WEIGHTS.get(name, 1.0)
                score += weight * sum(text.count(t) for t in terms)
                if len(terms) > 1 and phrase in text:
                    score += 3 * weight
            where, snippet = _snippet(fields, folded, terms)
            hits.append(SearchHit(page, score, where, snippet, terms))
        hits.sort(key=lambda h: (-h.score, -h.page.created_at.timestamp()))
        return hits[:limit]


FIELD_WEIGHTS = {"title": 5.0, "transcript": 2.0, "summary": 1.5, "takeaways": 1.2,
                 "comments": 1.0}
FIELD_LABELS = {"title": "Title", "transcript": "Notes", "summary": "Summary",
                "takeaways": "Exam takeaways", "comments": "Ced++ comments"}


@dataclass
class SearchHit:
    page: StoredPage
    score: float
    where: str          # which field the snippet came from ("Notes", "Summary"...)
    snippet: str        # original-case text around the first match
    terms: List[str]


def _fold(text: str) -> str:
    """Case- and accent-insensitive form used for matching."""
    decomposed = unicodedata.normalize("NFKD", str(text))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _search_fields(page: StoredPage) -> Dict[str, str]:
    meta = page.meta
    comments = " \n".join(
        " ".join(str((c.get("tip") or {}).get(k, "")) for k in ("title", "recognized", "comment"))
        + (" " + c["question"] if c.get("question") else "")
        for c in page.comments)
    summary = meta.get("summary") or {}
    takeaways = meta.get("takeaways") or {}
    return {
        "title": page.title,
        "transcript": page.transcript,
        "summary": " ".join([str(summary.get("topic", "")), str(summary.get("summary", ""))]
                            + [str(x) for x in summary.get("key_points", [])]),
        "takeaways": " ".join([f"{t.get('point', '')} {t.get('why', '')}"
                               for t in takeaways.get("takeaways", [])]
                              + [str(x) for x in takeaways.get("practice_questions", [])]),
        "comments": comments,
    }


def _snippet(fields: Dict[str, str], folded: Dict[str, str], terms: List[str],
             radius: int = 70) -> tuple:
    for name in ("transcript", "comments", "summary", "takeaways", "title"):
        text, low = fields[name], folded[name]
        positions = [low.find(t) for t in terms if low.find(t) >= 0]
        if not positions or len(low) != len(text):
            if positions and name == "title":
                return FIELD_LABELS[name], text
            continue
        i = min(positions)
        start, end = max(0, i - radius), min(len(text), i + radius)
        snippet = " ".join(text[start:end].split())
        return FIELD_LABELS[name], ("…" if start else "") + snippet + ("…" if end < len(text) else "")
    return "", ""
