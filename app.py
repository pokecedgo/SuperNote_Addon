#!/usr/bin/env python3
"""SuperNote(Ced++) - live study comments on your Supernote's mirrored screen.

Usage:
  python app.py                    open the app, then click Connect
  python app.py --ip 192.168.1.42  connect straight to your Supernote's mirror
  python app.py --demo             simulated notebook (no Supernote needed)
  python app.py --demo --offline   simulated notebook + canned tips (no API key needed)
"""
from __future__ import annotations

import argparse
import importlib
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REQUIRED = [("PySide6", "PySide6"), ("numpy", "numpy"), ("PIL", "Pillow"),
            ("anthropic", "anthropic")]


def check_dependencies() -> None:
    if sys.version_info < (3, 10):
        sys.exit("SuperNote(Ced++) needs Python 3.10 or newer. See README → Install.")
    missing = []
    for module, package in REQUIRED:
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(package)
    if missing:
        sys.exit("Missing packages: " + ", ".join(missing) +
                 "\nActivate the virtual environment and run:  pip install -r requirements.txt")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SuperNote(Ced++)")
    p.add_argument("--ip", help="Supernote mirror address, e.g. 192.168.1.42")
    p.add_argument("--demo", action="store_true", help="use the simulated demo notebook")
    p.add_argument("--offline", action="store_true",
                   help="canned demo tips instead of Claude (no API key needed)")
    p.add_argument("--debug", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    check_dependencies()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from PySide6.QtWidgets import QApplication

    from cedpp.config import APP_NAME, AppConfig
    from cedpp.mirror import normalize_address
    from cedpp.tutor import ClaudeTutor, OfflineTutor
    from cedpp.ui.connect_dialog import DEMO
    from cedpp.ui.main_window import MainWindow, default_source_factory
    from cedpp.ui.theme import STYLESHEET, apply_palette

    config = AppConfig()
    if args.offline:
        tutor = OfflineTutor()
    else:
        tutor = ClaudeTutor(config.tutor)
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            print("Note: ANTHROPIC_API_KEY isn't set. If you haven't run `ant auth login`, "
                  "comments will show a sign-in error. Use --offline for canned demo tips.")

    autoconnect = None
    if args.demo:
        autoconnect = DEMO
    elif args.ip:
        try:
            autoconnect = normalize_address(args.ip, config.mirror.port, config.mirror.path)
        except ValueError as exc:
            sys.exit(str(exc))

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    apply_palette(app)
    app.setStyleSheet(STYLESHEET)
    window = MainWindow(config, tutor, default_source_factory(config), autoconnect)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
