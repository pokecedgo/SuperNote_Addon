"""Supernote look: black ink on warm paper, thin black strokes, soft rounded corners."""
from __future__ import annotations

DESK = "#E9E3D6"        # app background (warm beige desk)
PAPER = "#FBF9F4"       # cards, page, buttons
PAPER_2 = "#F3EFE6"     # hover / subtle fills
INK = "#161616"         # text, borders, active fills
INK_SOFT = "#3A3835"
MUTED = "#7A756B"
RULE = "#D5CDBD"        # hairlines
HIGHLIGHT = (22, 22, 22, 18)   # anchor fill on the page (RGBA)

FONT_FAMILY = "Avenir Next"

STYLESHEET = f"""
* {{
    font-family: "{FONT_FAMILY}", "Helvetica Neue", "Helvetica";
    color: {INK};
    font-size: 13px;
}}
QMainWindow, QDialog, #Root {{ background: {DESK}; }}
QLabel {{ background: transparent; }}

#TopBar {{
    background: {PAPER};
    border-bottom: 1.5px solid {INK};
}}
#AppTitle {{ font-size: 18px; font-weight: 700; letter-spacing: 0.2px; }}
#Muted {{ color: {MUTED}; }}
#Small {{ color: {MUTED}; font-size: 11px; }}
#SectionTitle {{ font-size: 11px; font-weight: 700; letter-spacing: 1.6px; color: {INK_SOFT}; }}

/* Supernote-style buttons: paper fill, black outline, inverted when active */
QPushButton {{
    background: {PAPER};
    border: 1.5px solid {INK};
    border-radius: 12px;
    padding: 7px 16px;
    font-weight: 600;
}}
QPushButton:hover {{ background: {PAPER_2}; }}
QPushButton:pressed, QPushButton:checked {{ background: {INK}; color: {PAPER}; }}
QPushButton:disabled {{ color: #A9A398; border-color: #B9B2A4; background: {PAPER}; }}
#RecordButton {{ padding: 8px 16px; font-size: 14px; border-radius: 14px; min-width: 112px; }}
#Ghost {{ border: none; background: transparent; padding: 4px 8px; }}
#Ghost:hover {{ background: {PAPER_2}; }}
#IconButton {{
    border: 1.2px solid {RULE}; border-radius: 12px; padding: 0; min-width: 24px;
    max-width: 24px; min-height: 24px; max-height: 24px; font-size: 12px;
}}
#IconButton:hover {{ border-color: {INK}; background: {PAPER}; }}

#Segment {{ background: {PAPER_2}; border: 1.5px solid {INK}; border-radius: 14px; }}
#Segment QPushButton {{
    border: none; border-radius: 11px; padding: 5px 16px; background: transparent;
}}
#Segment QPushButton:hover {{ background: {PAPER}; }}
#Segment QPushButton:checked {{ background: {INK}; color: {PAPER}; }}
QTreeWidget, QInputDialog QLineEdit {{ font-size: 14px; }}

#Pill {{
    background: {PAPER};
    border: 1.2px solid {INK};
    border-radius: 13px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 600;
}}
#PillOff {{
    background: transparent;
    border: 1.2px dashed {MUTED};
    border-radius: 13px;
    padding: 4px 12px;
    font-size: 12px;
    color: {MUTED};
}}

QLineEdit {{
    background: {PAPER};
    border: 1.5px solid {INK};
    border-radius: 12px;
    padding: 8px 12px;
    font-size: 15px;
    selection-background-color: {INK};
    selection-color: {PAPER};
}}
#SearchBox {{ padding: 6px 12px; font-size: 13px; border-radius: 14px; }}
QListWidget {{
    background: {PAPER}; border: 1.2px solid {RULE}; border-radius: 12px; padding: 4px;
}}
QListWidget::item {{ padding: 6px 8px; border-radius: 8px; }}
QListWidget::item:selected {{ background: {INK}; color: {PAPER}; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ width: 6px; background: transparent; }}
QScrollBar::handle:vertical {{ background: {RULE}; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: {PAPER}; color: {INK}; border: 1px solid {INK}; padding: 4px; }}
"""


def apply_palette(app) -> None:
    from PySide6.QtGui import QColor, QPalette

    pal = QPalette()
    for role, color in [(QPalette.Window, DESK), (QPalette.Base, PAPER),
                        (QPalette.Button, PAPER), (QPalette.Text, INK),
                        (QPalette.WindowText, INK), (QPalette.ButtonText, INK),
                        (QPalette.Highlight, INK), (QPalette.HighlightedText, PAPER),
                        (QPalette.ToolTipBase, PAPER), (QPalette.ToolTipText, INK),
                        (QPalette.PlaceholderText, MUTED)]:
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
