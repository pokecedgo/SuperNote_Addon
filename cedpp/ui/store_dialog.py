"""'Store page' dialog: name the page and choose a notebook/folder for it."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

from ..library import Library
from . import theme
from .folder_tree import FolderTree
from .workers import gray_to_qimage


class StoreDialog(QDialog):
    def __init__(self, library: Library, page: np.ndarray, default_title: str,
                 comment_count: int, last_folder: Optional[Path] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.library = library
        self.setWindowTitle("Store page")
        self.setModal(True)
        self.resize(760, 560)
        self.chosen_folder: Optional[Path] = None

        root = QHBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(22)

        preview = QLabel()
        pix = QPixmap.fromImage(gray_to_qimage(page)).scaledToHeight(
            470, Qt.SmoothTransformation)
        preview.setPixmap(pix)
        preview.setStyleSheet(f"border: 1.5px solid {theme.INK}; border-radius: 10px; "
                              f"background: {theme.PAPER};")
        root.addWidget(preview, 0, Qt.AlignTop)

        side = QVBoxLayout()
        side.setSpacing(10)
        title = QLabel("Store this page")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        side.addWidget(title)
        sub = QLabel(f"Saved with its {comment_count} Ced++ comment"
                     f"{'' if comment_count == 1 else 's'}." if comment_count else
                     "Saved as a snapshot of the current page.")
        sub.setObjectName("Muted")
        side.addWidget(sub)

        side.addWidget(self._section("PAGE NAME"))
        self.name = QLineEdit(default_title)
        self.name.selectAll()
        side.addWidget(self.name)

        side.addWidget(self._section("SAVE TO"))
        self.tree = FolderTree(library)
        self.tree.folder_selected.connect(self._on_folder)
        side.addWidget(self.tree, 1)

        row = QHBoxLayout()
        nb = QPushButton("+ Notebook")
        nb.clicked.connect(self.tree.new_notebook)
        folder = QPushButton("+ Folder")
        folder.clicked.connect(self.tree.new_folder)
        row.addWidget(nb)
        row.addWidget(folder)
        row.addStretch(1)
        side.addLayout(row)

        self.where = QLabel("")
        self.where.setObjectName("Small")
        self.where.setWordWrap(True)
        side.addWidget(self.where)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.save_btn = QPushButton("Store page")
        self.save_btn.setDefault(True)
        self.save_btn.setStyleSheet(f"background: {theme.INK}; color: {theme.PAPER};")
        self.save_btn.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(self.save_btn)
        side.addLayout(buttons)
        root.addLayout(side, 1)

        self.tree.reload(select=last_folder)
        if not library.notebooks():
            # First time: ask for the notebook name straight away.
            QTimer.singleShot(0, self._first_notebook)

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    def _first_notebook(self) -> None:
        self.where.setText("Create your first notebook to store pages in.")
        self.tree.new_notebook()

    def _on_folder(self, folder: Optional[Path]) -> None:
        self.save_btn.setEnabled(folder is not None)
        self.where.setText(f"Will be stored in  {self.library.relative(folder)}"
                           if folder else "Create a notebook to store this page.")

    def _save(self) -> None:
        folder = self.tree.current_folder()
        if folder is None:
            return
        self.chosen_folder = folder
        self.accept()

    @property
    def title(self) -> str:
        return self.name.text().strip()
