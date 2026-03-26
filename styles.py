# Styles for Anki Card Maker

import os

_CHECKMARK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checkmark.svg").replace("\\", "/")

def get_styles(children_mode: bool = False) -> str:
    if children_mode:
        COLOR_PRIMARY = "#5B8FA8"
        COLOR_PRIMARY_HOVER = "#7AAFC8"
        COLOR_PRIMARY_PRESSED = "#4A7A90"
    else:
        COLOR_PRIMARY = "#8A9A5B"
        COLOR_PRIMARY_HOVER = "#A9BA7D"
        COLOR_PRIMARY_PRESSED = "#74824A"

    COLOR_BG = "#1C201A"
    COLOR_SURFACE = "#262B22"
    COLOR_TEXT = "#E1E8D8"
    COLOR_TEXT_DIM = "#94A18E"
    COLOR_BORDER = "#3E4738"

    return f"""
QMainWindow, QDialog {{
    background-color: {COLOR_BG};
}}

QWidget {{
    font-family: 'Segoe UI', 'Malgun Gothic', sans-serif;
    color: {COLOR_TEXT};
}}

QLineEdit, QTextEdit {{
    background-color: {COLOR_SURFACE};
    border: 2px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 10px;
    font-size: 15px;
    color: {COLOR_TEXT};
}}

QLineEdit:focus, QTextEdit:focus {{
    border: 2px solid {COLOR_PRIMARY};
    background-color: #2D3328;
}}

QPushButton {{
    background-color: {COLOR_PRIMARY};
    color: {COLOR_BG};
    border: none;
    border-radius: 8px;
    padding: 12px 24px;
    font-weight: bold;
    font-size: 14px;
}}

QPushButton:hover {{
    background-color: {COLOR_PRIMARY_HOVER};
}}

QPushButton:pressed {{
    background-color: {COLOR_PRIMARY_PRESSED};
}}

QPushButton:disabled {{
    background-color: #3E4738;
    color: #6B7568;
}}

QPushButton#secondaryButton {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER};
}}

QPushButton#secondaryButton:hover {{
    background-color: #31382C;
}}

QLabel#titleLabel {{
    font-size: 24px;
    font-weight: bold;
    color: {COLOR_PRIMARY};
    margin-bottom: 10px;
}}

QLabel#infoLabel {{
    color: {COLOR_TEXT_DIM};
    font-size: 13px;
}}

QLabel#fieldLabel {{
    color: {COLOR_PRIMARY};
    font-weight: bold;
    font-size: 14px;
}}

QCheckBox {{
    color: {COLOR_TEXT};
    font-size: 13px;
    spacing: 6px;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 2px solid {COLOR_BORDER};
    border-radius: 4px;
    background-color: {COLOR_SURFACE};
}}

QCheckBox::indicator:checked {{
    background-color: {COLOR_PRIMARY};
    border-color: {COLOR_PRIMARY};
    image: url({_CHECKMARK_PATH});
}}

QScrollArea {{
    border: none;
    background-color: transparent;
}}

QScrollBar:vertical {{
    border: none;
    background: {COLOR_BG};
    width: 10px;
    margin: 0px;
}}

QScrollBar::handle:vertical {{
    background: {COLOR_BORDER};
    min-height: 20px;
    border-radius: 5px;
}}

QScrollBar::handle:vertical:hover {{
    background: {COLOR_TEXT_DIM};
}}

QProgressBar {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    height: 8px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {COLOR_PRIMARY};
    border-radius: 4px;
}}

QMessageBox {{
    background-color: {COLOR_SURFACE};
}}

QMessageBox QLabel {{
    color: {COLOR_TEXT};
}}
"""

STYLES = get_styles()
