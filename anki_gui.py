import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QTextEdit, QMessageBox, QDialog,
    QScrollArea
)
from PySide6.QtCore import Qt

import anki_card_maker
from styles import STYLES

class ResultWindow(QDialog):
    def __init__(self, card_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generation Result")
        self.resize(600, 700)
        self.card_data = card_data
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        title = QLabel("카드 생성 미리보기")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        # Scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        fields = [
            ("Word/Phrase", "Word/Phrase"),
            ("Outline", "Outline"),
            ("KR Definition", "KR_Definition"),
            ("EN Definition", "EN_Definition"),
            ("Full Sentence", "FullSentence"),
            ("Blank Sentence", "BlankSentence")
        ]

        self.edits = {}
        for label_text, key in fields:
            label = QLabel(label_text)
            label.setObjectName("fieldLabel")
            scroll_layout.addWidget(label)

            edit = QTextEdit()
            edit.setPlainText(str(self.card_data.get(key, "")))
            edit.setMinimumHeight(100)
            scroll_layout.addWidget(edit)
            self.edits[key] = edit

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("Anki에 추가")
        self.btn_add.clicked.connect(self.add_to_anki)

        self.btn_cancel = QPushButton("취소")
        self.btn_cancel.setObjectName("secondaryButton")
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_add)
        layout.addLayout(btn_layout)

    def add_to_anki(self):
        try:
            # Update card_data from edits
            updated_fields = {}
            for key, edit in self.edits.items():
                updated_fields[key] = edit.toPlainText()

            # Prepare fields for Anki (HTML conversion)
            def to_html(text: str) -> str:
                return text.replace("\n", "<br>")

            anki_fields = {
                "Word/Phrase":   updated_fields["Word/Phrase"],
                "BlankSentence": updated_fields["BlankSentence"],
                "FullSentence":  updated_fields["FullSentence"],
                "KR_Definition": to_html(updated_fields["KR_Definition"]),
                "EN_Definition": to_html(updated_fields["EN_Definition"]),
                "Outline":       to_html(updated_fields["Outline"]),
                "Picture":       "",
                "Audio":         "",
            }

            # Ensure deck exists
            anki_card_maker.ensure_deck_exists(anki_card_maker.ANKI_DECK_NAME)

            note_id = anki_card_maker.add_note(anki_fields)
            QMessageBox.information(self, "Success", f"성공적으로 추가되었습니다!\n노트 ID: {note_id}")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Anki 추가 중 오류 발생: {e}")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Anki Card Maker")
        self.resize(500, 250)
        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)

        title = QLabel("Anki Card Maker")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Gemini AI를 이용한 영어 단어장 자동 생성\n여러 단어는 쉼표로 구분하세요 (예: apple, run away, on purpose)\n안정적인 생성을 위해 한 번에 최대 10개를 권장합니다.")
        subtitle.setObjectName("infoLabel")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("단어나 표현 입력 (쉼표로 구분 가능: apple, banana, cherry)")
        self.input_field.returnPressed.connect(self.generate)
        layout.addWidget(self.input_field)

        self.btn_generate = QPushButton("카드 생성하기")
        self.btn_generate.clicked.connect(self.generate)
        self.btn_generate.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.btn_generate)

        layout.addStretch()

    def generate(self):
        raw_input = self.input_field.text().strip()
        if not raw_input:
            QMessageBox.warning(self, "Warning", "단어를 입력해주세요.")
            return

        # 쉼표로 구분된 단어 목록 파싱
        topics = [t.strip() for t in raw_input.split(",") if t.strip()]
        if not topics:
            QMessageBox.warning(self, "Warning", "단어를 입력해주세요.")
            return

        self.btn_generate.setEnabled(False)
        count = len(topics)
        self.btn_generate.setText(f"생성 중... (0/{count})")
        QApplication.processEvents()

        try:
            # Anki 연결 확인
            anki_card_maker.anki_request("version")

            # 단어 수에 따라 단일/배치 생성 분기
            if count == 1:
                cards_data = [anki_card_maker.generate_card(topics[0])]
            else:
                self.btn_generate.setText(f"생성 중... (API 호출 1회로 {count}개 처리)")
                QApplication.processEvents()
                cards_data = anki_card_maker.generate_cards_batch(topics)

            # 각 카드를 순서대로 미리보기 창에 표시
            added_count = 0
            for i, card_data in enumerate(cards_data):
                self.btn_generate.setText(f"검토 중... ({i + 1}/{count})")
                QApplication.processEvents()

                res_win = ResultWindow(card_data, self)
                res_win.setStyleSheet(STYLES)
                if res_win.exec():
                    added_count += 1

            if added_count > 0:
                self.input_field.clear()
                QMessageBox.information(self, "완료", f"{added_count}개의 카드가 Anki에 추가되었습니다.")

        except ConnectionError as e:
            QMessageBox.critical(self, "Anki Connection Error", str(e))
        except Exception as e:
            error_msg = str(e)
            if "Gemini API 사용 한도" in error_msg:
                QMessageBox.warning(self, "Gemini 사용 한도 초과",
                                  "Gemini API의 무료 티어 사용량 제한(Rate Limit)에 도달했습니다.\n"
                                  "잠시(약 1분) 후 다시 시도해주세요.")
            else:
                QMessageBox.critical(self, "Error", f"오류가 발생했습니다: {e}")
        finally:
            self.btn_generate.setEnabled(True)
            self.btn_generate.setText("카드 생성하기")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLES)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
