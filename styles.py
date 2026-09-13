# Styles for Anki Card Maker

from paths import resource_path

# QSS의 url()은 정방향 슬래시만 받는다
_CHECKMARK_PATH = resource_path("checkmark.svg").replace("\\", "/")

def get_colors(children_mode: bool = False) -> dict:
    """
    팔레트를 코드에서도 쓸 수 있게 꺼낸다.
    QSS 안의 색은 파이썬에서 읽을 수 없는데, 본문 하이라이트처럼
    HTML을 직접 만들어야 하는 곳에서는 같은 색이 필요하다.
    """
    if children_mode:
        primary, hover, pressed = "#5B8FA8", "#7AAFC8", "#4A7A90"
    else:
        primary, hover, pressed = "#8A9A5B", "#A9BA7D", "#74824A"

    return {
        "PRIMARY": primary,
        "PRIMARY_HOVER": hover,
        "PRIMARY_PRESSED": pressed,
        "BG": "#1C201A",
        "SURFACE": "#262B22",
        "TEXT": "#E1E8D8",
        "TEXT_DIM": "#94A18E",
        "BORDER": "#3E4738",
    }


def get_styles(children_mode: bool = False) -> str:
    c = get_colors(children_mode)
    COLOR_PRIMARY = c["PRIMARY"]
    COLOR_PRIMARY_HOVER = c["PRIMARY_HOVER"]
    COLOR_PRIMARY_PRESSED = c["PRIMARY_PRESSED"]
    COLOR_BG = c["BG"]
    COLOR_SURFACE = c["SURFACE"]
    COLOR_TEXT = c["TEXT"]
    COLOR_TEXT_DIM = c["TEXT_DIM"]
    COLOR_BORDER = c["BORDER"]

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

/* 지금 어떤 단어의 이미지를 고르는 중인지 바로 보이게 */
QWidget#wordBanner {{
    background-color: {COLOR_SURFACE};
    border-left: 4px solid {COLOR_PRIMARY};
    border-radius: 0;
}}

QLabel#wordText {{
    font-size: 26px;
    font-weight: bold;
    color: {COLOR_TEXT};
}}

QLabel#picturePreview {{
    background-color: {COLOR_SURFACE};
    border: 2px dashed {COLOR_BORDER};
    border-radius: 8px;
    color: {COLOR_TEXT_DIM};
    font-size: 12px;
}}

QLabel#fieldLabel {{
    color: {COLOR_PRIMARY};
    font-weight: bold;
    font-size: 14px;
}}

QComboBox {{
    background-color: {COLOR_SURFACE};
    border: 2px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 14px;
    color: {COLOR_TEXT};
}}

QComboBox:hover {{
    border: 2px solid {COLOR_PRIMARY};
}}

QComboBox:disabled {{
    color: #6B7568;
    border-color: #333B2E;
}}

QComboBox QAbstractItemView {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 6px;
    color: {COLOR_TEXT};
    selection-background-color: {COLOR_PRIMARY};
    selection-color: {COLOR_BG};
    outline: none;
    padding: 4px;
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

/* 스크롤 안쪽 위젯은 기본 팔레트(흰색)를 쓴다.
   글자색이 밝은 색이라 그대로 두면 흰 바탕에 흰 글씨가 된다. */
QScrollArea > QWidget > QWidget {{
    background-color: {COLOR_BG};
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
