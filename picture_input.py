"""
이미지 입력 기능 (붙여넣기 / 드래그앤드롭 / 파일 선택 / 구글 이미지 검색)

카드 미리보기 창과 기존 카드 채우기 창이 같은 코드를 쓰도록 믹스인으로 분리했다.
QWidget 계열에 섞어 쓰며, 호스트는 두 가지만 하면 된다.

  1. __init__ 에서 self._init_picture() 호출
  2. _build_picture_section() 이 돌려준 레이아웃을 원하는 위치에 넣기

_current_word() 는 훅이다. 구글 이미지 검색에 쓸 단어를 각 창이 알려준다.
"""

import base64
import os
import re
from urllib.parse import quote_plus, parse_qs, urlparse, unquote_to_bytes

from PySide6.QtCore import Qt, QBuffer, QByteArray, QUrl
from PySide6.QtGui import (
    QGuiApplication, QImage, QPixmap, QKeySequence, QShortcut, QDesktopServices
)
from PySide6.QtWidgets import (
    QApplication, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTextEdit, QLineEdit, QMessageBox, QFileDialog
)

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


# 구글 이미지 검색 유형. 단어에 따라 사진보다 일러스트가 나을 때가 있다.
# (표시 이름, tbs 파라미터)
IMAGE_SEARCH_KINDS = [
    ("전체",      ""),
    ("사진",      "itp:photo"),
    ("일러스트",  "itp:clipart"),
    ("선화",      "itp:lineart"),
    ("투명 배경", "itp:clipart,ic:trans"),
    ("GIF",       "itp:animated"),
]

# 카드마다 다시 고르지 않도록 세션 동안 마지막 선택을 기억한다
_last_search_kind = 0


class PictureInputMixin:
    """이미지 붙여넣기/드롭/파일 선택을 제공하는 믹스인"""

    def _init_picture(self):
        # 이미지는 self.edits 같은 텍스트 위젯 dict에 넣지 않는다 —
        # .toPlainText()를 도는 쪽에서 터진다.
        self.picture_data = None   # bytes
        self.picture_ext = "jpg"

        self.setAcceptDrops(True)

        # 창 어디에 포커스가 있든 Ctrl+V로 이미지를 붙일 수 있게 한다.
        # (텍스트 편집 중이면 그쪽 붙여넣기가 우선)
        QShortcut(QKeySequence.Paste, self, activated=self.paste_picture)

    def _current_word(self) -> str:
        """구글 이미지 검색에 쓸 단어. 호스트가 재정의한다."""
        return ""

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

        btn_search = QPushButton("🔍 구글 이미지")
        btn_search.setObjectName("secondaryButton")
        btn_search.clicked.connect(self.open_image_search)
        row.addWidget(btn_search)

        # 단어에 따라 사진보다 일러스트가 나을 때가 있다
        self.search_kind_combo = QComboBox()
        for name, tbs in IMAGE_SEARCH_KINDS:
            self.search_kind_combo.addItem(name, tbs)
        self.search_kind_combo.setCurrentIndex(_last_search_kind)
        self.search_kind_combo.currentIndexChanged.connect(self._remember_search_kind)
        self.search_kind_combo.setToolTip("구글 이미지 검색에 적용할 유형")
        row.addWidget(self.search_kind_combo)

        for text, slot in (
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

    def _remember_search_kind(self, index: int):
        """카드마다 다시 고르지 않도록 세션 동안 유지"""
        global _last_search_kind
        _last_search_kind = index

    def open_image_search(self):
        word = self._current_word()
        if not word:
            QMessageBox.information(self, "검색", "검색할 단어가 없습니다.")
            return

        # udm=2 가 지금 구글의 이미지 탭 파라미터다.
        # 예전 tbm=isch 로 보내면 구글이 udm=2 로 리다이렉트하면서
        # tbs(유형 필터)를 떨어뜨려 사진/일러스트 선택이 먹히지 않는다.
        url = f"https://www.google.com/search?udm=2&q={quote_plus(word)}"
        tbs = self.search_kind_combo.currentData()
        if tbs:
            url += f"&tbs={quote_plus(tbs, safe=':,')}"
        QDesktopServices.openUrl(QUrl(url))

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
