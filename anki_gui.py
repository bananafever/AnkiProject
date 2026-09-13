import base64
import os
import re
import sys
from urllib.parse import quote_plus, parse_qs, urlparse, unquote_to_bytes

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QTextEdit, QMessageBox, QDialog,
    QScrollArea, QCheckBox, QComboBox, QFileDialog
)
import anki_card_maker
import api_counter
from PySide6.QtCore import Qt, QThread, Signal, QBuffer, QByteArray, QUrl
from PySide6.QtGui import QGuiApplication, QImage, QPixmap, QKeySequence, QShortcut, QDesktopServices
from PySide6.QtWidgets import QProgressBar
from styles import get_styles

RECOMMENDED_MAX_TOPICS = 10

# 화면에는 200px 높이로만 나오므로 원본을 그대로 담을 이유가 없다
MAX_PICTURE_EDGE = 800
PICTURE_PREVIEW_HEIGHT = 120
# 드롭된 URL에서 내려받을 때의 상한
PICTURE_DOWNLOAD_TIMEOUT = 10
MAX_PICTURE_BYTES = 10 * 1024 * 1024

# 기본 python-requests UA는 이미지 호스트가 자주 막는다
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


def _short_url(url: str, limit: int = 45) -> str:
    """오류 메시지에 넣을 짧은 URL 표기"""
    return url if len(url) <= limit else url[:limit - 3] + "..."

class ResultWindow(QDialog):
    def __init__(self, card_data, profile_name=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generation Result")
        self.resize(600, 700)
        self.card_data = card_data
        self.profile_name = profile_name

        # 이미지는 self.edits에 넣지 않는다 — add_to_anki의 루프가
        # .toPlainText()를 부르므로 QTextEdit이 아닌 것이 섞이면 터진다.
        self.picture_data = None   # bytes
        self.picture_ext = "jpg"

        self.setAcceptDrops(True)
        self.init_ui()

        # 창 어디에 포커스가 있든 Ctrl+V로 이미지를 붙일 수 있게 한다.
        # (텍스트 편집 중이면 그쪽 붙여넣기가 우선)
        QShortcut(QKeySequence.Paste, self, activated=self.paste_picture)

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

        layout.addLayout(self._build_picture_section())

        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("Anki에 추가")
        self.btn_add.clicked.connect(self.add_to_anki)

        self.btn_cancel = QPushButton("취소")
        self.btn_cancel.setObjectName("secondaryButton")
        self.btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_add)
        layout.addLayout(btn_layout)

    # ── 이미지 ──────────────────────────────────────────────────

    def _build_picture_section(self):
        section = QVBoxLayout()
        section.setSpacing(8)

        label = QLabel("Picture (선택)")
        label.setObjectName("fieldLabel")
        section.addWidget(label)

        self.picture_preview = QLabel()
        self.picture_preview.setObjectName("picturePreview")
        self.picture_preview.setAlignment(Qt.AlignCenter)
        self.picture_preview.setFixedHeight(PICTURE_PREVIEW_HEIGHT)
        section.addWidget(self.picture_preview)

        row = QHBoxLayout()
        for text, slot in (
            ("🔍 구글 이미지", self.open_image_search),
            ("📋 붙여넣기", self.paste_picture),
            ("파일...", self.choose_picture_file),
            ("제거", self.clear_picture),
        ):
            btn = QPushButton(text)
            btn.setObjectName("secondaryButton")
            btn.clicked.connect(slot)
            row.addWidget(btn)
        section.addLayout(row)

        self._refresh_picture_preview()
        return section

    def _current_word(self) -> str:
        edit = self.edits.get("Word/Phrase")
        if edit is not None:
            return edit.toPlainText().strip()
        return str(self.card_data.get("Word/Phrase", "")).strip()

    def _refresh_picture_preview(self):
        if not self.picture_data:
            self.picture_preview.setPixmap(QPixmap())
            self.picture_preview.setText(
                "이미지 없음 — Ctrl+V로 붙여넣거나 여기로 끌어다 놓으세요"
            )
            return

        pixmap = QPixmap()
        if pixmap.loadFromData(QByteArray(self.picture_data)):
            self.picture_preview.setText("")
            self.picture_preview.setPixmap(pixmap.scaled(
                self.picture_preview.width(), PICTURE_PREVIEW_HEIGHT - 8,
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            ))
        else:
            self.picture_preview.setText("이미지를 표시할 수 없습니다")

    def _set_picture(self, data: bytes, ext: str):
        self.picture_data = data
        self.picture_ext = ext
        self._refresh_picture_preview()

    def _set_picture_from_image(self, image: QImage):
        """QImage를 JPEG(투명도가 있으면 PNG)로 인코딩해 보관"""
        if image.isNull():
            raise ValueError("이미지를 읽을 수 없습니다.")

        if max(image.width(), image.height()) > MAX_PICTURE_EDGE:
            image = image.scaled(MAX_PICTURE_EDGE, MAX_PICTURE_EDGE,
                                 Qt.KeepAspectRatio, Qt.SmoothTransformation)

        fmt, ext = ("PNG", "png") if image.hasAlphaChannel() else ("JPG", "jpg")
        buffer = QBuffer()
        buffer.open(QBuffer.WriteOnly)
        if not image.save(buffer, fmt, 85):
            raise ValueError("이미지를 변환하지 못했습니다.")
        self._set_picture(bytes(buffer.data()), ext)

    def _picture_candidates(self, mime) -> list:
        """
        드롭/클립보드 데이터에서 시도해볼 이미지 출처를 우선순위대로 모은다.

        브라우저에서 끌면 uri-list / text-html / 이미지 데이터가 함께 오고,
        구글 이미지는 uri-list에 이미지 주소가 아니라 결과 페이지 링크
        (imgres?imgurl=...)를 넣는다. 하나만 보고 포기하면 안 된다.

        반환: [(라벨, 실행 함수), ...]
        """
        if mime is None:
            return []

        candidates = []

        # 1) 이미지 데이터가 실려 있으면 네트워크가 필요 없다
        if mime.hasImage():
            candidates.append(
                ("클립보드 이미지",
                 lambda: self._set_picture_from_image(QImage(mime.imageData())))
            )

        direct_urls = []
        for url in mime.urls():
            # 2) 로컬 파일
            if url.isLocalFile():
                path = url.toLocalFile()
                candidates.append((f"파일 {os.path.basename(path)}",
                                   lambda p=path: self._load_picture_file(p)))
                continue

            text = url.toString()

            # 3) data:image/...;base64,....
            if url.scheme() == "data":
                candidates.append(("data: URL",
                                   lambda t=text: self._set_picture_from_data_url(t)))
                continue

            if url.scheme() not in ("http", "https"):
                continue

            query = parse_qs(urlparse(text).query)
            # 4) 구글 이미지 결과 링크 -> imgurl 에 원본 주소가 들어 있다 (해상도 최상)
            real = (query.get("imgurl") or query.get("mediaurl") or [None])[0]
            if real:
                referer = (query.get("imgrefurl") or [None])[0]
                candidates.append((f"원본 {_short_url(real)}",
                                   lambda u=real, r=referer: self._download_picture(u, r)))
            else:
                direct_urls.append(text)

        # 5) 평범한 이미지 링크
        for text in direct_urls:
            candidates.append((f"링크 {_short_url(text)}",
                               lambda u=text: self._download_picture(u)))

        # 6) text/html 조각의 <img src> — 구글이 서빙하는 썸네일.
        #    원본이 핫링크 차단이면 이쪽에서 건진다.
        if mime.hasHtml():
            found = re.search(r"""<img[^>]+src=["']([^"']+)["']""", mime.html(), re.I)
            if found:
                thumb = found.group(1)
                if thumb.startswith("data:"):
                    candidates.append(("HTML 조각의 data: 이미지",
                                       lambda t=thumb: self._set_picture_from_data_url(t)))
                elif not any(thumb in label for label, _ in candidates):
                    candidates.append((f"썸네일 {_short_url(thumb)}",
                                       lambda u=thumb: self._download_picture(u)))

        return candidates

    def _set_picture_from_mime(self, mime) -> bool:
        """
        후보를 순서대로 시도한다. 하나라도 성공하면 True.
        전부 실패하면 무엇을 왜 못 했는지 모아서 알린다.
        """
        candidates = self._picture_candidates(mime)
        if not candidates:
            return False

        failures = []
        for label, attempt in candidates:
            try:
                attempt()
                return True
            except Exception as e:
                failures.append(f"  · {label}: {e}")

        raise ValueError(
            "이미지를 가져오지 못했습니다. 시도한 출처:\n" + "\n".join(failures)
        )

    def _set_picture_from_data_url(self, text: str):
        header, _, payload = text.partition(",")
        if not payload:
            raise ValueError("data: URL 형식이 아닙니다.")
        if "base64" in header:
            data = base64.b64decode(payload)
        else:
            data = unquote_to_bytes(payload)
        if "image/gif" in header:
            self._set_picture(data, "gif")
            return
        self._set_picture_from_image(QImage.fromData(QByteArray(data)))

    def _load_picture_file(self, path: str):
        ext = os.path.splitext(path)[1].lstrip(".").lower()
        if ext == "gif":
            # GIF는 QImage로 다시 인코딩하면 애니메이션이 죽으므로 원본 그대로
            with open(path, "rb") as f:
                self._set_picture(f.read(), "gif")
            return
        self._set_picture_from_image(QImage(path))

    def _download_picture(self, url: str, referer: str = None):
        """
        브라우저에서 이미지를 끌어다 놓으면 URL로 온다.
        기본 python-requests UA는 이미지 호스트가 자주 막으므로 브라우저처럼 요청한다.
        """
        import requests

        headers = dict(BROWSER_HEADERS)
        # 핫링크 차단을 통과하려면 Referer가 필요한 경우가 많다
        headers["Referer"] = referer or f"{urlparse(url).scheme}://{urlparse(url).netloc}/"

        res = requests.get(url, headers=headers, timeout=PICTURE_DOWNLOAD_TIMEOUT, stream=True)
        res.raise_for_status()

        content_type = res.headers.get("Content-Type", "").split(";")[0].strip()
        if not content_type.startswith("image/"):
            raise ValueError(f"이미지가 아님 (Content-Type: {content_type or '알 수 없음'})")

        data = b""
        for chunk in res.iter_content(64 * 1024):
            data += chunk
            if len(data) > MAX_PICTURE_BYTES:
                raise ValueError(
                    f"이미지가 너무 큼 ({MAX_PICTURE_BYTES // (1024 * 1024)}MB 초과)"
                )

        if content_type == "image/gif":
            self._set_picture(data, "gif")
            return
        self._set_picture_from_image(QImage.fromData(QByteArray(data)))

    def _picture_error(self, e: Exception):
        QMessageBox.warning(self, "이미지를 넣지 못했습니다", str(e))

    # 버튼 / 단축키 / 드래그앤드롭

    def paste_picture(self):
        mime = QGuiApplication.clipboard().mimeData()

        # 클립보드에 이미지가 있을 때만 가져간다. 그렇지 않으면
        # 텍스트 편집 중의 평범한 Ctrl+V를 방해하지 않도록 넘겨준다.
        if mime is not None and mime.hasImage():
            try:
                self._set_picture_from_mime(mime)
            except Exception as e:
                self._picture_error(e)
            return

        focused = QApplication.focusWidget()
        if isinstance(focused, (QTextEdit, QLineEdit)):
            focused.paste()
        else:
            QMessageBox.information(
                self, "붙여넣기",
                "클립보드에 이미지가 없습니다.\n"
                "브라우저에서 이미지를 우클릭 → '이미지 복사' 후 다시 시도하세요."
            )

    def choose_picture_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "이미지 선택", "",
            "이미지 (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;모든 파일 (*)"
        )
        if not path:
            return
        try:
            self._load_picture_file(path)
        except Exception as e:
            self._picture_error(e)

    def clear_picture(self):
        self.picture_data = None
        self.picture_ext = "jpg"
        self._refresh_picture_preview()

    def open_image_search(self):
        word = self._current_word()
        if not word:
            QMessageBox.information(self, "검색", "Word/Phrase가 비어 있습니다.")
            return
        QDesktopServices.openUrl(
            QUrl(f"https://www.google.com/search?tbm=isch&q={quote_plus(word)}")
        )

    def _set_picture_hint(self, text: str):
        """다운로드 중처럼 잠깐 다른 안내를 띄울 때. 이미지가 있으면 건드리지 않는다."""
        if not self.picture_data:
            self.picture_preview.setText(text)
            QApplication.processEvents()

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasImage() or mime.hasUrls() or mime.hasHtml():
            self._set_picture_hint("여기에 놓으세요")
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._refresh_picture_preview()

    def dropEvent(self, event):
        # 내려받는 데 몇 초 걸릴 수 있어 아무 반응이 없으면 멈춘 것처럼 보인다
        self._set_picture_hint("이미지를 가져오는 중...")
        try:
            if self._set_picture_from_mime(event.mimeData()):
                event.acceptProposedAction()
            else:
                self._refresh_picture_preview()
        except Exception as e:
            self._refresh_picture_preview()
            self._picture_error(e)

    # ── Anki 추가 ───────────────────────────────────────────────

    def add_to_anki(self):
        try:
            # Update card_data from edits
            updated_fields = {}
            for key, edit in self.edits.items():
                updated_fields[key] = edit.toPlainText()

            # 취소한 카드의 이미지가 미디어 폴더에 남지 않도록,
            # 붙여넣는 시점이 아니라 추가하는 시점에 올린다.
            if self.picture_data:
                filename = anki_card_maker.store_media_image(
                    self.picture_data, self.picture_ext
                )
                updated_fields["Picture"] = anki_card_maker.picture_html(filename)

            anki_fields = anki_card_maker.build_anki_fields(updated_fields)

            # Ensure deck / note type exist
            anki_card_maker.ensure_deck_exists(anki_card_maker.ANKI_DECK_NAME)
            anki_card_maker.ensure_model_exists(anki_card_maker.ANKI_MODEL_NAME)

            word = updated_fields["Word/Phrase"].strip()
            try:
                note_id = anki_card_maker.add_note(anki_fields)
            except anki_card_maker.AnkiDuplicateError:
                # 중복이라고 창을 붙잡아 두면 건너뛸 방법이 없다. 선택지를 준다.
                answer = QMessageBox.question(
                    self, "이미 있는 단어",
                    f"'{word}' 노트가 이미 있습니다.\n\n"
                    "(덱 위치와 무관하게 같은 노트 유형 전체에서 검사합니다)\n\n"
                    "그래도 추가할까요?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer != QMessageBox.Yes:
                    self.reject()   # 건너뛰고 다음 카드로
                    return
                note_id = anki_card_maker.add_note(anki_fields, allow_duplicate=True)

            target = self.profile_name or anki_card_maker.get_active_profile()
            QMessageBox.information(
                self, "Success",
                f"성공적으로 추가되었습니다!\n"
                f"대상: '{target}' › '{anki_card_maker.ANKI_DECK_NAME}'\n"
                f"노트 ID: {note_id}"
            )
            self.accept()
        except anki_card_maker.CardMakerError as e:
            QMessageBox.critical(self, "Anki 추가 실패", str(e))
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
        # DAILY_LIMIT = 0 은 무제한을 뜻한다 (api_counter 참조)
        quota = f"{count} / {limit}" if limit else f"{count}회 (한도 없음)"
        self.counter_label.setText(f"오늘 Gemini 사용: {quota}  (리셋: {next_reset} KST)")

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

        # 권장치를 넘으면 확인만 받는다 (막지는 않는다)
        if len(topics) > RECOMMENDED_MAX_TOPICS:
            answer = QMessageBox.question(
                self, "단어가 많습니다",
                f"{len(topics)}개를 한 번에 생성하려고 합니다.\n"
                f"권장은 {RECOMMENDED_MAX_TOPICS}개까지입니다. 시간이 오래 걸리고 "
                "사용량도 많이 듭니다.\n\n계속할까요?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
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

    def handle_results(self, cards_data, failures=None):
        self.progress_bar.setVisible(False)
        self.status_label.setVisible(False)

        failures = failures or []
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

            # 실패한 배치가 있으면 성공/실패를 함께 알린다
            summary = f"{added_count}개의 카드가 Anki에 추가되었습니다."
            if failures:
                detail = "\n".join(f"  · {words}: {reason}" for words, reason in failures)
                QMessageBox.warning(self, "일부 실패",
                                    f"{summary}\n\n생성에 실패한 단어:\n{detail}")
            elif added_count > 0:
                QMessageBox.information(self, "완료", summary)
        except Exception as e:
            # 슬롯 밖으로 예외가 나가면 패키징된 exe가 조용히 죽는다
            QMessageBox.critical(self, "Error", f"카드 검토 중 오류가 발생했습니다: {e}")
        finally:
            self.finalize_generation()

    def handle_error(self, error):
        self.progress_bar.setVisible(False)
        self.status_label.setVisible(False)

        acm = anki_card_maker
        message = str(error)

        # 한국어 부분 문자열 대신 예외 타입으로 분기한다.
        # 문구를 바꿔도 분기가 깨지지 않는다.
        if isinstance(error, acm.GeminiQuotaError):
            QMessageBox.warning(self, "Gemini 사용 한도 초과",
                                f"{message}\n\n"
                                "→ 잠시 후 다시 시도하거나,\n"
                                "→ '생성 모델'을 'Gemini API → Claude CLI' 또는 'Claude CLI만'으로 바꿔주세요.")
        elif isinstance(error, acm.AnkiConnectionError):
            QMessageBox.critical(self, "Anki 연결 오류", message)
        elif isinstance(error, acm.AnkiError):
            QMessageBox.critical(self, "Anki 오류", message)
        elif isinstance(error, acm.GenerationError):
            QMessageBox.critical(self, "카드 생성 실패", message)
        elif isinstance(error, acm.CardMakerError):
            QMessageBox.critical(self, "오류", message)
        else:
            QMessageBox.critical(self, "Error", f"예상치 못한 오류가 발생했습니다:\n\n{message}")

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
    finished = Signal(list, list)  # (생성된 카드, 실패한 [(단어, 사유)])
    error = Signal(object)  # 예외 객체 (타입으로 분기하기 위해)

    def __init__(self, topics, children_mode: bool = False, backend: str = None):
        super().__init__()
        self.topics = topics
        self.children_mode = children_mode
        self.backend = backend or anki_card_maker.BACKEND_AUTO

    def run(self):
        try:
            # Check Anki connection first
            anki_card_maker.anki_request("version")

            anki_card_maker.backend = self.backend
            # Gemini 실패 시 Claude CLI 폴백 사실을 UI로 전달
            anki_card_maker.on_fallback = self.fallback.emit

            all_cards = []
            failures = []
            first_error = None
            # Split into batches of 3 for better progress feedback
            batch_size = 3
            total_count = len(self.topics)

            for i in range(0, total_count, batch_size):
                batch = self.topics[i:i + batch_size]
                current_count = len(all_cards)

                status_text = f"생성 중... ({current_count}/{total_count})"
                self.progress.emit(current_count, total_count, status_text)

                # 배치 하나가 실패해도 이미 생성한 카드는 지키고 다음 배치를 계속한다
                try:
                    if len(batch) == 1:
                        card = anki_card_maker.generate_card(batch[0], children_mode=self.children_mode)
                        all_cards.append(card)
                    else:
                        cards = anki_card_maker.generate_cards_batch(batch, children_mode=self.children_mode)
                        all_cards.extend(cards)
                except Exception as e:
                    failures.append((", ".join(batch), str(e)))
                    first_error = first_error or e

            if not all_cards:
                # 하나도 못 만들었으면 첫 예외를 그대로 올려 타입 분기를 유지한다
                raise first_error or anki_card_maker.GenerationError(
                    "AI가 카드를 하나도 생성하지 못했습니다."
                )

            self.progress.emit(total_count, total_count, "생성 완료!")
            self.finished.emit(all_cards, failures)

        except Exception as e:
            self.error.emit(e)
        finally:
            anki_card_maker.on_fallback = None
            anki_card_maker.backend = anki_card_maker.BACKEND_AUTO

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(get_styles())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
