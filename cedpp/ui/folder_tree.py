"""Notebook / folder tree shared by the Store dialog and Notebooks mode."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import (QInputDialog, QMessageBox, QStyle, QStyledItemDelegate,
                               QTreeWidget, QTreeWidgetItem, QWidget)

from ..library import Library, LibraryError
from . import theme

PATH_ROLE = Qt.UserRole


def ask_name(parent: QWidget, title: str, label: str, default: str = "") -> Optional[str]:
    name, ok = QInputDialog.getText(parent, title, label, text=default)
    return name.strip() if ok and name.strip() else None


class FolderDelegate(QStyledItemDelegate):
    def paint(self, p: QPainter, option, index) -> None:
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        r = QRectF(option.rect).adjusted(0, 2, -2, -2)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        if selected or hovered:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.INK if selected else theme.PAPER_2))
            p.drawRoundedRect(r, 9, 9)
        p.setFont(index.data(Qt.FontRole) or option.font)
        p.setPen(QColor(theme.PAPER if selected else theme.INK))
        text = p.fontMetrics().elidedText(index.data(Qt.DisplayRole) or "", Qt.ElideRight,
                                          int(r.width()) - 16)
        p.drawText(r.adjusted(8, 0, -8, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
        p.restore()


class FolderTree(QTreeWidget):
    folder_selected = Signal(object)   # Path or None

    def __init__(self, library: Library, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.library = library
        self.setHeaderHidden(True)
        self.setIndentation(18)
        self.setAnimated(True)
        self.setRootIsDecorated(True)
        self.setStyleSheet(f"""
            QTreeWidget {{ background: {theme.PAPER}; border: 1.2px solid {theme.RULE};
                           border-radius: 14px; padding: 6px; font-size: 14px;
                           show-decoration-selected: 0; }}
            QTreeWidget::item {{ padding: 6px 4px; }}
        """)
        # Selection is painted by FolderDelegate (a black pill on the name only).
        pal = self.palette()
        pal.setColor(QPalette.Highlight, QColor(0, 0, 0, 0))
        pal.setColor(QPalette.HighlightedText, QColor(theme.PAPER))
        self.setPalette(pal)
        self.setItemDelegate(FolderDelegate(self))
        self.currentItemChanged.connect(
            lambda cur, _prev: self.folder_selected.emit(self._path(cur)))

    def drawBranches(self, painter: QPainter, rect, index) -> None:
        """Our own chevrons (and no selection fill in the indent area)."""
        item = self.itemFromIndex(index)
        if item is None or item.childCount() == 0:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(theme.INK), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        cx, cy = rect.right() - 9, rect.center().y() + 0.5
        if item.isExpanded():   # ⌄
            pts = [QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2)]
        else:                   # ›
            pts = [QPointF(cx - 2, cy - 4), QPointF(cx + 2, cy), QPointF(cx - 2, cy + 4)]
        painter.drawPolyline(pts)
        painter.restore()

    @staticmethod
    def _path(item: Optional[QTreeWidgetItem]) -> Optional[Path]:
        return item.data(0, PATH_ROLE) if item is not None else None

    def current_folder(self) -> Optional[Path]:
        return self._path(self.currentItem())

    def reload(self, select: Optional[Path] = None) -> None:
        select = select or self.current_folder()
        expanded = {self._path(it) for it in self._all_items() if it.isExpanded()}
        self.blockSignals(True)
        self.clear()
        target = None

        def add(parent_item, folder: Path, notebook: bool) -> None:
            nonlocal target
            count = self.library.page_count(folder)
            item = QTreeWidgetItem([folder.name + (f"   ·  {count}" if count else "")])
            if notebook:
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)
            item.setData(0, PATH_ROLE, folder)
            if parent_item is None:
                self.addTopLevelItem(item)
            else:
                parent_item.addChild(item)
            for sub in self.library.subfolders(folder):
                add(item, sub, False)
            if folder in expanded or notebook:
                item.setExpanded(True)
            if select is not None and folder.resolve() == Path(select).resolve():
                target = item

        for nb in self.library.notebooks():
            add(None, nb, True)
        self.blockSignals(False)
        if target is None and self.topLevelItemCount():
            target = self.topLevelItem(0)
        if target is not None:
            self.setCurrentItem(target)
            target.setExpanded(True)
            parent = target.parent()
            while parent is not None:
                parent.setExpanded(True)
                parent = parent.parent()
        self.folder_selected.emit(self.current_folder())

    def _all_items(self):
        stack = [self.topLevelItem(i) for i in range(self.topLevelItemCount())]
        while stack:
            item = stack.pop()
            yield item
            stack.extend(item.child(i) for i in range(item.childCount()))

    # ------------------------------------------------------------------ actions
    def new_notebook(self) -> Optional[Path]:
        name = ask_name(self, "New notebook", "Notebook name (e.g. Calc III):")
        return self._create(None, name)

    def new_folder(self) -> Optional[Path]:
        parent = self.current_folder()
        if parent is None:
            QMessageBox.information(self, "New folder", "Create or select a notebook first.")
            return None
        name = ask_name(self, "New folder",
                        f"New folder inside “{self.library.relative(parent)}”:")
        return self._create(parent, name)

    def _create(self, parent: Optional[Path], name: Optional[str]) -> Optional[Path]:
        if not name:
            return None
        try:
            folder = self.library.create_folder(parent, name)
        except LibraryError as exc:
            QMessageBox.warning(self, "Couldn't create", str(exc))
            return None
        self.reload(select=folder)
        return folder
