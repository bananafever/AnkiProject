import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QTextEdit, QMessageBox, QDialog,
    QScrollArea, QCheckBox, QComboBox
)
import anki_card_maker
import api_counter
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QProgressBar
from styles import get_styles

class ResultWindow(QDialog):
    def __init__(self, card_data, profile_name=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generation Result")
        self.resize(600, 700)
        self.card_data = card_data
        self.profile_name = profile_name
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        title = QLabel("카드 생성 미리보기")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        if self.profile_name:
            target = QLabel(f"📥 '{self.profile_name}' 프로필의 '{anki_card_maker.ANKI_DECK_NAME}' 덱에 추가됩니다")
            target.setObjectName("infoLabel")
            layout.addWidget(target)

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

            # Ensure deck / note type exist
            anki_card_maker.ensure_deck_exists(anki_card_maker.ANKI_DECK_NAME)
            anki_card_maker.ensure_model_exists(anki_card_maker.ANKI_MODEL_NAME)

            note_id = anki_card_maker.add_note(anki_fields)
            target = self.profile_name or anki_card_maker.get_active_profile()
            QMessageBox.information(
                self, "Success",
                f"성공적으로 추가되었습니다!\n"
                f"대상: '{target}' › '{anki_card_maker.ANKI_DECK_NAME}'\n"
                f"노트 ID: {note_id}"
            )
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

        subtitle = QLabel("AI로 영어 단어장 자동 생성\n여러 단어는 쉼표로 구분하세요 (예: apple, run away, on purpose)\n안정적인 생성을 위해 한 번에 최대 10개를 권장합니다.")
        subtitle.setObjectName("infoLabel")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        self.counter_label = QLabel()
        self.counter_label.setObjectName("infoLabel")
        self.counter_label.setAlignment(Qt.AlignCenter)
        self._update_counter_label()
        layout.addWidget(self.counter_label)

        self.profile_label = QLabel()
        self.profile_label.setObjectName("infoLabel")
        self.profile_label.setAlignment(Qt.AlignCenter)
        self._update_profile_label()
        layout.addWidget(self.profile_label)

        backend_row = QHBoxLayout()
        backend_label = QLabel("생성 모델")
        backend_label.setObjectName("fieldLabel")
        backend_row.addWidget(backend_label)

        self.backend_combo = QComboBox()
        for key, label in anki_card_maker.BACKENDS:
            self.backend_combo.addItem(label, key)
        self.backend_combo.setToolTip(
            "Gemini API → Claude CLI: Gemini를 먼저 쓰고, 한도 초과 등으로 실패하면 Claude CLI로 자동 전환합니다."
        )
        backend_row.addWidget(self.backend_combo, 1)
        layout.addLayout(backend_row)

        self.children_mode_checkbox = QCheckBox("어린이용 모드")
        self.children_mode_checkbox.setToolTip("외설/성적 표현/욕설 관련 내용을 제거합니다.")
        self.children_mode_checkbox.stateChanged.connect(self._on_mode_changed)
        layout.addWidget(self.children_mode_checkbox)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("단어나 표현 입력 (쉼표로 구분 가능: apple, banana, cherry)")
        self.input_field.returnPressed.connect(self.start_generation)
        layout.addWidget(self.input_field)

        self.btn_generate = QPushButton("카드 생성하기")
        self.btn_generate.clicked.connect(self.start_generation)
        self.btn_generate.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.btn_generate)

        # Progress Section
        self.status_label = QLabel("")
        self.status_label.setObjectName("infoLabel")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        layout.addStretch()

    def _on_mode_changed(self):
        QApplication.instance().setStyleSheet(get_styles(self.children_mode_checkbox.isChecked()))

    def _update_counter_label(self):
        count = api_counter.get_count()
        limit = api_counter.DAILY_LIMIT
        next_reset = api_counter.get_next_reset_str()
        self.counter_label.setText(f"오늘 Gemini 사용: {count} / {limit}  (리셋: {next_reset} KST)")

    def _update_profile_label(self):
        try:
            self.active_profile = anki_card_maker.get_active_profile()
            self.profile_label.setText(
                f"📥 추가 대상: '{self.active_profile}' 프로필 › "
                f"'{anki_card_maker.ANKI_DECK_NAME}' 덱"
            )
        except Exception:
            self.active_profile = None
            self.profile_label.setText("⚠️ Anki에 연결되지 않음 (Anki 실행 후 카드를 생성하세요)")

    def start_generation(self):
        self._update_profile_label()
        raw_input = self.input_field.text().strip()
        if not raw_input:
            QMessageBox.warning(self, "Warning", "단어를 입력해주세요.")
            return

        topics = [t.strip() for t in raw_input.split(",") if t.strip()]
        if not topics:
            QMessageBox.warning(self, "Warning", "단어를 입력해주세요.")
            return

        # UI State - Generation Start
        self.btn_generate.setEnabled(False)
        self.input_field.setEnabled(False)
        self.backend_combo.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(topics))
        self.progress_bar.setValue(0)
        self.status_label.setVisible(True)
        self.status_label.setText(f"준비 중... (0/{len(topics)})")

        # Worker Thread
        self.worker = GenerationWorker(
            topics,
            children_mode=self.children_mode_checkbox.isChecked(),
            backend=self.backend_combo.currentData(),
        )
        self.worker.progress.connect(self.update_progress)
        self.worker.fallback.connect(self.handle_fallback)
        self.worker.finished.connect(self.handle_results)
        self.worker.error.connect(self.handle_error)
        self.worker.start()

    def update_progress(self, current, total, text):
        # 폴백 중 불확정 상태로 바뀌었을 수 있으므로 범위를 복구
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)
        self.status_label.setText(text)

    def handle_fallback(self, reason):
        # Gemini가 막혔을 때. CLI는 느리므로 진행 표시를 불확정 상태로 바꾼다.
        self.progress_bar.setRange(0, 0)
        self.status_label.setText(f"⚠️ {reason} → Claude CLI로 생성 중... (수십 초 걸릴 수 있습니다)")

    def handle_results(self, cards_data):
        self.progress_bar.setVisible(False)
        self.status_label.setVisible(False)
        
        count = len(cards_data)
        added_count = 0

        try:
            profile_name = anki_card_maker.get_active_profile()
        except Exception:
            profile_name = None

        try:
            for i, card_data in enumerate(cards_data):
                self.btn_generate.setText(f"검토 중... ({i + 1}/{count})")
                res_win = ResultWindow(card_data, profile_name, self)
                res_win.setStyleSheet(get_styles(self.children_mode_checkbox.isChecked()))
                if res_win.exec():
                    added_count += 1
            
            if added_count > 0:
                self.input_field.clear()
                QMessageBox.information(self, "완료", f"{added_count}개의 카드가 Anki에 추가되었습니다.")
        finally:
            self.finalize_generation()

    def handle_error(self, error_msg):
        self.progress_bar.setVisible(False)
        self.status_label.setVisible(False)
        
        if "Claude CLI 폴백도 실패" in error_msg:
            QMessageBox.critical(self, "생성 실패 (Gemini + Claude CLI)",
                              "Gemini와 Claude CLI 폴백이 모두 실패했습니다.\n\n"
                              f"{error_msg}\n\n"
                              "→ Gemini 한도라면 잠시(약 1분) 후 재시도,\n"
                              "→ Claude CLI는 터미널에서 `claude` 로그인 상태를 확인하세요.")
        elif "Gemini API 사용 한도" in error_msg:
            QMessageBox.warning(self, "Gemini 사용 한도 초과",
                              "Gemini API의 무료 티어 사용량 제한(Rate Limit)에 도달했습니다.\n\n"
                              "→ 잠시(약 1분) 후 다시 시도하거나,\n"
                              "→ '생성 모델'을 'Gemini API → Claude CLI' 또는 'Claude CLI만'으로 바꿔주세요.")
        elif "Anki" in error_msg:
            QMessageBox.critical(self, "Anki Connection Error", error_msg)
        else:
            QMessageBox.critical(self, "Error", f"오류가 발생했습니다: {error_msg}")
        
        self.finalize_generation()

    def finalize_generation(self):
        self.btn_generate.setEnabled(True)
        self.btn_generate.setText("카드 생성하기")
        self.input_field.setEnabled(True)
        self.backend_combo.setEnabled(True)
        self._update_counter_label()
        self._update_profile_label()

class GenerationWorker(QThread):
    progress = Signal(int, int, str)
    fallback = Signal(str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, topics, children_mode: bool = False, backend: str = None):
        super().__init__()
        self.topics = topics
        self.children_mode = children_mode
        self.backend = backend or anki_card_maker.BACKEND_AUTO

    def run(self):
        try:
            # Check Anki connection first
            import anki_card_maker
            anki_card_maker.anki_request("version")

            anki_card_maker.backend = self.backend
            # Gemini 실패 시 Claude CLI 폴백 사실을 UI로 전달
            anki_card_maker.on_fallback = self.fallback.emit

            all_cards = []
            # Split into batches of 3 for better progress feedback
            batch_size = 3
            total_count = len(self.topics)
            
            for i in range(0, total_count, batch_size):
                batch = self.topics[i:i + batch_size]
                current_count = len(all_cards)
                
                status_text = f"생성 중... ({current_count}/{total_count})"
                self.progress.emit(current_count, total_count, status_text)
                
                if len(batch) == 1:
                    card = anki_card_maker.generate_card(batch[0], children_mode=self.children_mode)
                    all_cards.append(card)
                else:
                    cards = anki_card_maker.generate_cards_batch(batch, children_mode=self.children_mode)
                    all_cards.extend(cards)
            
            self.progress.emit(total_count, total_count, "생성 완료!")
            self.finished.emit(all_cards)

        except Exception as e:
            self.error.emit(str(e))
        finally:
            import anki_card_maker
            anki_card_maker.on_fallback = None

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(get_styles())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
