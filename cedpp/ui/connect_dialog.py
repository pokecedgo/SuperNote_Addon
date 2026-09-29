"""'Connect to Supernote' dialog: type the mirror address, scan, or use the demo."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QPushButton, QVBoxLayout, QWidget)

from ..mirror import normalize_address
from ..mirror.discovery import scan
from .workers import TaskThread

DEMO = "demo"


class ConnectDialog(QDialog):
    def __init__(self, last_address: str = "", port: int = 8080,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Connect to Supernote")
        self.setModal(True)
        self.setFixedWidth(460)
        self.port = port
        self.result_address: Optional[str] = None   # stream URL or DEMO
        self._scan_thread: Optional[TaskThread] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 22)
        root.setSpacing(12)

        title = QLabel("Connect to Supernote")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        root.addWidget(title)
        steps = QLabel(
            "1.  On your Supernote, swipe down from the top and tap "
            "<b>Screen Mirroring</b>.<br>"
            "2.  Type the address it shows (for example <b>192.168.1.42</b>).<br>"
            "3.  Keep this Mac and the Supernote on the same Wi-Fi, with no VPN.")
        steps.setWordWrap(True)
        steps.setTextFormat(Qt.RichText)
        steps.setObjectName("Muted")
        root.addWidget(steps)

        self.address = QLineEdit(last_address)
        self.address.setPlaceholderText("192.168.1.42")
        self.address.returnPressed.connect(self._connect)
        root.addWidget(self.address)

        self.error = QLabel("")
        self.error.setObjectName("Small")
        self.error.setWordWrap(True)
        root.addWidget(self.error)

        self.found = QListWidget()
        self.found.setFixedHeight(90)
        self.found.hide()
        self.found.itemClicked.connect(lambda item: self.address.setText(item.text()))
        self.found.itemDoubleClicked.connect(lambda _item: self._connect())
        root.addWidget(self.found)

        buttons = QHBoxLayout()
        self.scan_btn = QPushButton("Scan Wi-Fi")
        self.scan_btn.setCursor(Qt.PointingHandCursor)
        self.scan_btn.clicked.connect(self._scan)
        demo = QPushButton("Try demo notebook")
        demo.setCursor(Qt.PointingHandCursor)
        demo.clicked.connect(self._demo)
        connect = QPushButton("Connect")
        connect.setDefault(True)
        connect.setCursor(Qt.PointingHandCursor)
        connect.setStyleSheet("background: #161616; color: #FBF9F4;")
        connect.clicked.connect(self._connect)
        buttons.addWidget(self.scan_btn)
        buttons.addWidget(demo)
        buttons.addStretch(1)
        buttons.addWidget(connect)
        root.addLayout(buttons)

    def _connect(self) -> None:
        try:
            self.result_address = normalize_address(self.address.text(), self.port)
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()

    def _demo(self) -> None:
        self.result_address = DEMO
        self.accept()

    def _scan(self) -> None:
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("Scanning…")
        self.error.setText("Looking for a mirroring Supernote on this network (≈5 s)…")
        self._scan_thread = TaskThread(lambda: scan(self.port))
        self._scan_thread.succeeded.connect(self._scan_done)
        self._scan_thread.start()

    def _scan_done(self, hosts) -> None:
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("Scan Wi-Fi")
        hosts = hosts or []
        self.found.clear()
        if hosts:
            self.found.addItems(hosts)
            self.found.show()
            self.address.setText(hosts[0])
            self.error.setText(f"Found {len(hosts)} device{'s' if len(hosts) > 1 else ''}.")
        else:
            self.found.hide()
            self.error.setText("No mirror found. Make sure Screen Mirroring is on and both "
                               "devices share the same Wi-Fi (school networks sometimes "
                               "block this - a phone hotspot works).")

    def done(self, result: int) -> None:
        if self._scan_thread is not None and self._scan_thread.isRunning():
            self._scan_thread.wait(8000)
        super().done(result)
