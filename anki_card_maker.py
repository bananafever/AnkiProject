"""
Anki 카드 자동 생성기
- Gemini API로 카드 내용 생성 (실패 시 Claude CLI로 자동 폴백)
- AnkiConnect로 Anki에 카드 추가
- 노트 유형 "01_EN_Voca_SYS" 1개로 Card 1(빈칸채우기) + Card 2(단어카드) 자동 생성

사용법:
  python anki_card_maker.py

사전 준비:
  1. pip install google-genai requests python-dotenv
  2. Anki 실행 + AnkiConnect 애드온 설치 (코드: 2055492159)
  3. .env 파일에 GEMINI_API_KEY 입력
  4. (선택) Claude CLI 폴백을 쓰려면 claude 로그인
     npm install -g @anthropic-ai/claude-code

"""

import requests
import base64
import hashlib
import json
import re
import shutil
import subprocess
import time
from google import genai
from config import GEMINI_API_KEY, ANKI_DECK_NAME, ANKI_MODEL_NAME, ENV_PATH
import api_counter

# ── 예외 타입 ──────────────────────────────────────────────────
# GUI가 한국어 문구를 부분 문자열로 비교해 분기하던 것을 타입으로 대체한다.
# 문구를 손볼 때마다 분기가 조용히 깨지는 걸 막는다.

class CardMakerError(Exception):
    """사용자에게 그대로 보여줘도 되는 오류"""


class AnkiError(CardMakerError):
    """AnkiConnect 요청 실패"""


class AnkiConnectionError(AnkiError):
    """Anki에 닿지 못함 (미실행, 애드온 없음, 응답 없음)"""


class AnkiDuplicateError(AnkiError):
    """같은 노트가 이미 있음"""


class GenerationError(CardMakerError):
    """AI가 쓸 수 있는 카드를 만들지 못함"""


class GeminiQuotaError(CardMakerError):
    """Gemini 사용 한도 초과"""


# ── Gemini 설정 ────────────────────────────────────────────────
MODEL_ID = "gemini-2.5-flash-lite"  # Flash-Lite 모델 적용

_client = None


def _get_client():
    """
    Gemini 클라이언트를 처음 쓸 때 만든다.
    import 시점에 만들면 .env를 못 찾았을 때 창이 뜨기도 전에 죽고,
    패키징된 exe(console=False)에서는 아무 메시지도 남지 않는다.
    Claude CLI만 쓰는 경우에는 키가 없어도 앱이 동작해야 한다.
    """
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY를 찾을 수 없습니다.\n"
                f"→ {ENV_PATH} 파일에 GEMINI_API_KEY=... 를 넣어주세요.\n"
                "→ 또는 '생성 모델'을 'Claude CLI만'으로 바꿔주세요."
            )
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client

# ── 생성 경로(백엔드) 설정 ──────────────────────────────────────
BACKEND_AUTO = "auto"      # Gemini API → 실패 시 Claude CLI (기본)
BACKEND_GEMINI = "gemini"  # Gemini API만 (폴백 없음)
BACKEND_CLAUDE = "claude"  # Claude CLI만

# UI 표시 순서 = 이 순서. 첫 항목이 기본값이다.
BACKENDS = [
    (BACKEND_AUTO,   "Gemini API → Claude CLI (기본)"),
    (BACKEND_GEMINI, "Gemini API만"),
    (BACKEND_CLAUDE, "Claude CLI만"),
]

backend = BACKEND_AUTO  # 현재 선택된 생성 경로

# ── Claude CLI 설정 ────────────────────────────────────────────
CLAUDE_CLI_TIMEOUT = 180  # 초. CLI는 API보다 느리므로 넉넉하게

# 폴백이 일어날 때 호출되는 콜백 (GUI에서 상태 표시용). 인자: 사유 문자열
on_fallback = None

# 한도 초과가 확인된 카운터 기간. 여기 값이 현재 기간과 같으면 Gemini를 건너뛴다.
# (한 번 한도가 차면 매 호출마다 429를 다시 맞을 이유가 없다)
_gemini_blocked_period = None


# ── 0. LLM 호출 (Gemini → Claude CLI 폴백) ──────────────────────

def _notify_fallback(reason: str):
    """폴백 발생을 UI에 알린다. 콜백이 없거나 실패해도 생성은 계속한다."""
    if on_fallback:
        try:
            on_fallback(reason)
        except Exception:
            pass


def _blocked_reason(response) -> str:
    """Gemini가 응답을 내주지 않았을 때 사유를 최대한 뽑아낸다"""
    reason = None
    try:
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            reason = getattr(candidates[0], "finish_reason", None)
        if reason is None:
            feedback = getattr(response, "prompt_feedback", None)
            reason = getattr(feedback, "block_reason", None)
    except Exception:
        pass

    detail = f" (사유: {reason})" if reason else ""
    return (f"Gemini가 응답을 생성하지 않았습니다{detail}. "
            "안전 필터에 걸렸을 수 있습니다.")


def _call_gemini(prompt: str) -> str:
    """Gemini API 호출. 429/503은 1초, 2초 간격으로 최대 3회 시도."""
    limit = api_counter.DAILY_LIMIT
    if limit and api_counter.get_count() >= limit:
        # 표시만 하고 막지 않으면 카운터가 아무 의미가 없다.
        # DAILY_LIMIT = 0 으로 두면 무제한.
        raise GeminiQuotaError(
            f"오늘 Gemini 사용 한도({limit}회)를 모두 썼습니다."
        )

    last_error = None
    for attempt in range(3):
        try:
            response = _get_client().models.generate_content(
                model=MODEL_ID,
                contents=prompt
            )
            # 안전 필터 등으로 차단되면 .text가 None이다.
            # 카운터는 실제로 텍스트를 받은 뒤에만 올린다.
            text = getattr(response, "text", None)
            if text is None:
                raise RuntimeError(_blocked_reason(response))
            api_counter.increment()  # 성공 시 카운터 증가
            return text.strip()
        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            is_retryable = ("503" in error_str or "unavailable" in error_str
                            or "429" in error_str)
            if is_retryable and attempt < 2:
                time.sleep(2 ** attempt)  # 1초, 2초 후 재시도
                continue
            break
    raise last_error


def _call_claude_cli(prompt: str) -> str:
    """
    Claude CLI(`claude -p`)로 생성.
    - 프롬프트가 길고 개행/따옴표가 많으므로 argv 대신 stdin으로 전달
    - `--tools ""`로 도구를 모두 끄고 `--strict-mcp-config`로 MCP를 건너뛴다
      (텍스트 생성만 필요하고, 파일/명령 실행 부작용이 없어야 하며, 시작도 빠르다)
    """
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError(
            "claude CLI를 찾을 수 없습니다.\n"
            "→ 설치: npm install -g @anthropic-ai/claude-code"
        )

    try:
        proc = subprocess.run(
            [exe, "-p", "--tools", "", "--strict-mcp-config"],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CLAUDE_CLI_TIMEOUT,
            # 패키징된 GUI(.exe)에서 콘솔 창이 깜빡이지 않도록
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Claude CLI가 {CLAUDE_CLI_TIMEOUT}초 안에 응답하지 않았습니다.")

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:300]
        raise RuntimeError(f"Claude CLI 오류 (종료 코드 {proc.returncode}): {detail}")

    text = (proc.stdout or "").strip()
    if not text:
        raise RuntimeError("Claude CLI가 빈 응답을 반환했습니다. (로그인 상태를 확인하세요)")
    return text


def _is_quota_error(error_str: str) -> bool:
    return ("429" in error_str or "quota" in error_str
            or "resource_exhausted" in error_str
            or "사용 한도" in error_str)


def _gemini_error_message(e: Exception) -> str:
    """폴백 없이 Gemini만 쓸 때 사용자에게 보여줄 메시지"""
    error_str = str(e).lower()
    if _is_quota_error(error_str):
        return ("Gemini API 사용 한도(Quota)를 초과했습니다. "
                "잠시 후 다시 시도하거나, 생성 모델을 'Claude CLI'로 바꿔주세요.")
    if "503" in error_str or "unavailable" in error_str:
        return ("현재 Gemini API 서버에 트래픽이 몰려 일시적으로 사용할 수 없거나 "
                "지연되고 있습니다 (503 Unavailable). 잠시 후 다시 시도해주세요.")
    return str(e)


def _gemini_is_blocked() -> bool:
    """
    Gemini 한도 초과 상태인지 확인.
    카운터의 일일 리셋(KST 17시)이 지나면 자동으로 해제된다.
    """
    if _gemini_blocked_period is None:
        return False
    return _gemini_blocked_period == api_counter.load_usage()["period_start"]


def _generate_text(prompt: str) -> str:
    """선택된 백엔드로 생성. BACKEND_AUTO면 Gemini 실패 시 Claude CLI로 폴백."""
    global _gemini_blocked_period

    if backend == BACKEND_CLAUDE:
        return _call_claude_cli(prompt)

    gemini_error = None

    if backend == BACKEND_AUTO and _gemini_is_blocked():
        # 이미 한도가 찬 것이 확인됨 → Gemini를 건너뛰고 바로 폴백
        reason = "Gemini 사용 한도 초과 (리셋 전까지 Claude CLI 사용)"
    else:
        try:
            return _call_gemini(prompt)
        except Exception as e:
            gemini_error = e
            error_str = str(e).lower()
            if _is_quota_error(error_str):
                # 이번 기간 내내 폴백을 쓰도록 기록
                _gemini_blocked_period = api_counter.load_usage()["period_start"]
                reason = "Gemini 사용 한도 초과"
            elif "503" in error_str or "unavailable" in error_str:
                # 일시적 장애이므로 다음 호출에서는 다시 Gemini를 시도한다
                reason = "Gemini 서버 일시 장애"
            elif "응답을 생성하지 않았습니다" in str(e):
                # 안전 필터 차단. 재시도해도 같으므로 폴백이 유일한 길이다
                reason = "Gemini 응답 차단(안전 필터)"
            else:
                reason = f"Gemini 오류 ({type(e).__name__})"

            if backend == BACKEND_GEMINI:
                # 폴백 없이 Gemini만 쓰도록 선택한 경우
                message = _gemini_error_message(e)
                if _is_quota_error(error_str) or isinstance(e, GeminiQuotaError):
                    raise GeminiQuotaError(message) from e
                raise GenerationError(message) from e

    _notify_fallback(reason)
    try:
        return _call_claude_cli(prompt)
    except Exception as cli_error:
        detail = f"→ Gemini: {gemini_error}\n" if gemini_error is not None else ""
        raise GenerationError(
            f"Claude CLI 폴백도 실패했습니다. (폴백 사유: {reason})\n"
            f"{detail}→ Claude CLI: {cli_error}"
        ) from cli_error


# 카드 1장이 반드시 가져야 하는 키 (Picture/Audio는 코드에서 ""로 채운다)
REQUIRED_CARD_KEYS = ("Word/Phrase", "Outline", "KR_Definition",
                      "EN_Definition", "FullSentence", "BlankSentence")


def _coerce_card(raw, topic_hint: str) -> dict:
    """
    LLM이 돌려준 카드 1장을 검증하고 문자열 필드로 정규화.
    형식이 어긋나면 여기서 걸러야 GUI에서 엉뚱한 타입으로 터지지 않는다.
    """
    if not isinstance(raw, dict):
        raise ValueError(
            f"AI 응답 형식이 올바르지 않습니다 ('{topic_hint}'): "
            f"카드가 객체가 아님 ({type(raw).__name__})"
        )

    missing = [k for k in REQUIRED_CARD_KEYS if k not in raw]
    if missing:
        raise ValueError(
            f"AI 응답에 필드가 빠졌습니다 ('{topic_hint}'): {', '.join(missing)}"
        )

    card = {}
    for key in REQUIRED_CARD_KEYS:
        value = raw[key]
        card[key] = "" if value is None else (
            value if isinstance(value, str) else str(value)
        )
    return card


def _extract_json(text: str) -> str:
    """
    LLM 응답에서 JSON 본문만 추출.
    CLI는 코드블록으로 감싸거나 앞뒤에 설명을 덧붙일 수 있다.
    """
    text = text.strip()

    # ```json ... ``` 코드블록이 있으면 그 안의 내용을 우선 사용
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    # 앞뒤 설명이 붙은 경우 첫 여는 괄호 ~ 마지막 닫는 괄호만 남김
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    ends = [i for i in (text.rfind("}"), text.rfind("]")) if i != -1]
    if starts and ends and max(ends) > min(starts):
        text = text[min(starts):max(ends) + 1]

    return text


def _generate_json(prompt: str, parse):
    """
    생성 후 JSON 파싱까지. 형식이 틀리면 한 번 더 생성한다.
    LLM이 예문 HTML에 큰따옴표를 섞어 JSON을 깨뜨리는 일이 잦은데,
    전송 오류가 아니라서 _call_gemini의 재시도 루프로는 잡히지 않는다.
    """
    last_error = None
    for attempt in range(2):
        text = _generate_text(prompt)
        try:
            return parse(json.loads(_extract_json(text)))
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            if attempt == 0:
                _notify_fallback("AI 응답 형식 오류 → 다시 생성 중")

    raise GenerationError(
        f"AI가 두 번 모두 올바른 형식으로 응답하지 않았습니다: {last_error}"
    )


# ── 1. 카드 내용 생성 ───────────────────────────────────────────

CHILDREN_RULE = """
[어린이 모드 규칙]
- 모든 정의, 설명, 예문에서 성적 표현, 외설적 내용, 욕설을 완전히 제거한다.
- 예문은 어린이에게 적합한 일상적/교육적 상황으로만 구성한다.
- 성인 주제(음주, 도박, 폭력, 성인 관계 등)를 다루는 예문은 중립적 상황으로 대체한다.
- 어린이 모드임을 언급하거나 특정 내용을 제외했음을 설명하는 문구를 절대 포함하지 않는다.
  (예: "어린이 모드에서는 ~", "성적인 의미를 제외하고 ~" 등의 표현 금지)
"""


def _build_prompt(topics: list, children_mode: bool) -> str:
    """
    카드 생성 프롬프트를 만든다.

    단어가 1개든 여러 개든 같은 규칙을 쓴다. 예전에는 단일용/배치용 프롬프트가
    따로 있었고 내용이 갈려서, 입력 개수에 따라 지시가 달라졌다.
    (배치 쪽에만 '기계적인 사전 순서가 아닌'이 있었다)

    필드 매핑:
      Outline        ← 개요
      KR_Definition  ← 영한사전 뜻
      EN_Definition  ← 영영사전 뜻
      FullSentence   ← 예문 (HTML)
      BlankSentence  ← 빈칸 예문 (HTML)
    """
    topics_str = "\n".join(f"- {t}" for t in topics)
    children_rule = CHILDREN_RULE if children_mode else ""

    return f"""
아래 단어/표현 목록 각각에 대해 Anki 플래시카드 내용을 만들어주세요.

단어/표현 목록:
{topics_str}
{children_rule}
[작성 규칙]
- HTML style 속성은 반드시 작은따옴표(')를 사용하세요. (JSON 파싱 오류 방지)
- Outline에는 각 단어별로 '사용 빈도', '사용시 유의 사항', '뉘앙스', '문맥 및 배경' 4가지를 모두 반드시 포함하여 작성하세요.
- 뜻(KR_Definition, EN_Definition)을 작성할 때는 반드시 기계적인 사전 순서가 아닌, 실제 사용 빈도가 가장 높은 뜻을 1번에 배치하고 순서대로 나열하세요.
- ★중요★ 품사 작성 시 단어가 동사라면 단순히 '[동사]'라고 쓰지 말고, 반드시 '[자동사]' 또는 '[타동사]' (영어는 vi. 또는 vt.)로 완벽하게 구분해서 기재하세요.
- 각 단어의 FullSentence와 BlankSentence는 동일한 문장을 사용하며,
  BlankSentence는 해당 단어/표현 부분만 _____로 교체합니다.
- 반드시 아래 JSON 배열 형식으로만 답하세요. 다른 말 없이 JSON 배열만 출력하세요.

[
  {{
    "Word/Phrase": "단어",
    "Outline": "① 사용 빈도: (높음/중간/낮음 및 한 줄 설명)\\n② 사용시 유의 사항: (문법적 특징, 자주 헷갈리는 뜻 등)\\n③ 뉘앙스: (격식체/비격식, 긍정/부정 등)\\n④ 문맥 및 배경: (주로 쓰이는 상황)",
    "KR_Definition": "① [타동사] 뜻 1 (동사면 반드시 자/타 구분)\\n② [명사] 뜻 2\\n③ [형용사] 뜻 3",
    "EN_Definition": "① (vt.) Definition 1\\n② (n.) Definition 2\\n③ (adj.) Definition 3",
    "FullSentence": "<div style='line-height:1.6;'>예문1 <span style='color:#FFD54F'>단어</span> 예문1 계속<br><span style='color:#A0A0A0;'>→ 한국어 번역 1</span><br><br>예문2 <span style='color:#FFD54F'>단어</span> 예문2 계속<br><span style='color:#A0A0A0;'>→ 한국어 번역 2</span></div>",
    "BlankSentence": "<div style='line-height:1.6;'>예문1 _____ 예문1 계속<br><span style='color:#A0A0A0;'>→ 한국어 번역 1</span><br><br>예문2 _____ 예문2 계속<br><span style='color:#A0A0A0;'>→ 한국어 번역 2</span></div>"
  }},
  ...
]

총 {len(topics)}개의 카드를 위 형식의 JSON 배열로 반환하세요.
"""


def generate_cards_batch(topics: list, children_mode: bool = False) -> list:
    """여러 단어/표현을 한 번의 호출로 생성 (API 사용량 절약). Returns: list of card dicts"""
    prompt = _build_prompt(topics, children_mode)

    def parse(data):
        # 배열 대신 객체 1개로 답하는 경우가 있다.
        # 검증 없이 넘기면 호출부의 list.extend()가 dict의 '키'를 담아버린다.
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            raise ValueError(
                f"AI 응답 형식이 올바르지 않습니다: JSON 배열이 아님 ({type(data).__name__})"
            )
        if not data:
            raise ValueError("AI가 카드를 하나도 생성하지 못했습니다.")

        return [
            _coerce_card(card, topics[i] if i < len(topics) else f"#{i + 1}")
            for i, card in enumerate(data)
        ]

    return _generate_json(prompt, parse)


def generate_card(topic: str, children_mode: bool = False) -> dict:
    """단어/표현 1개로 카드 생성"""
    cards = generate_cards_batch([topic], children_mode=children_mode)
    return cards[0]


# ── 2. AnkiConnect로 카드 추가 ─────────────────────────────────
ANKI_URL = "http://localhost:8765"
# addNote는 중복 검사로 노트 유형 전체를 훑고, 동기화 중에는 Anki가 멈춰 있다.
ANKI_TIMEOUT = 15


def anki_request(action: str, **params):
    """AnkiConnect API를 호출하는 공통 함수"""
    payload = {"action": action, "version": 6, "params": params}

    try:
        res = requests.post(ANKI_URL, json=payload, timeout=ANKI_TIMEOUT)
        res.raise_for_status()
        result = res.json()
    except requests.exceptions.ConnectionError:
        raise AnkiConnectionError(
            "Anki에 연결할 수 없습니다.\n"
            "→ Anki가 실행 중인지, AnkiConnect 애드온이 설치되어 있는지 확인하세요."
        )
    except requests.exceptions.Timeout:
        # 동기화·데이터베이스 확인·모달 창이 떠 있으면 Anki가 응답을 미룬다.
        # ReadTimeout은 ConnectionError를 상속하지 않아 따로 잡아야 한다.
        raise AnkiConnectionError(
            f"Anki가 {ANKI_TIMEOUT}초 안에 응답하지 않았습니다.\n"
            "→ 동기화나 데이터베이스 확인이 끝난 뒤, 또는 Anki에 열린 창을 닫고 다시 시도하세요."
        )
    except requests.exceptions.RequestException as e:
        raise AnkiConnectionError(f"Anki 요청이 실패했습니다: {e}")
    except ValueError:
        raise AnkiError(
            "Anki의 응답을 해석할 수 없습니다.\n"
            f"→ {ANKI_URL} 를 다른 프로그램이 쓰고 있는지 확인하세요."
        )

    if not isinstance(result, dict):
        raise AnkiError(f"Anki가 예상과 다른 형식으로 응답했습니다: {type(result).__name__}")

    error = result.get("error")
    if error:
        lowered = str(error).lower()
        if "duplicate" in lowered:
            raise AnkiDuplicateError("이미 같은 단어의 노트가 있습니다.")
        if "empty" in lowered:
            raise AnkiError("첫 번째 필드(Word/Phrase)가 비어 있어 추가할 수 없습니다.")
        raise AnkiError(f"AnkiConnect 오류: {error}")

    return result.get("result")


def ensure_deck_exists(deck_name: str):
    """덱이 없으면 자동으로 생성"""
    decks = anki_request("deckNames")
    if deck_name not in decks:
        anki_request("createDeck", deck=deck_name)
        print(f"  ✅ 덱 생성됨: '{deck_name}'")


def get_active_profile() -> str:
    """현재 Anki에 열려 있는 프로필 이름을 반환"""
    return anki_request("getActiveProfile")


def ensure_model_exists(model_name: str):
    """노트 유형이 없으면 사용 가능한 목록과 함께 명확한 오류를 발생"""
    models = anki_request("modelNames")
    if model_name not in models:
        raise AnkiError(
            f"노트 유형 '{model_name}'을(를) 찾을 수 없습니다.\n"
            f"현재 프로필: {get_active_profile()}\n"
            f"사용 가능한 노트 유형: {', '.join(models)}"
        )


def to_html(text: str) -> str:
    """줄바꿈을 <br>로. Anki 필드는 HTML이라 개행이 그대로 죽는다."""
    return text.replace("\n", "<br>")


def build_anki_fields(card: dict) -> dict:
    """
    카드 dict를 노트 유형의 8개 필드로 변환.
    CLI와 GUI가 각자 들고 있던 것을 한 곳으로 모았다.

    Picture는 미리보기 창에서 붙여넣은 <img> 태그가 들어온다 (없으면 빈 값).
    Audio는 아직 Anki에서 직접 채운다.
    """
    return {
        "Word/Phrase":   card.get("Word/Phrase", ""),
        "BlankSentence": card.get("BlankSentence", ""),
        "FullSentence":  card.get("FullSentence", ""),
        "KR_Definition": to_html(card.get("KR_Definition", "")),
        "EN_Definition": to_html(card.get("EN_Definition", "")),
        "Outline":       to_html(card.get("Outline", "")),
        "Picture":       card.get("Picture", ""),
        "Audio":         "",
    }


def store_media_image(data: bytes, ext: str = "jpg") -> str:
    """
    이미지를 Anki 미디어 폴더에 저장하고 실제 저장된 파일명을 반환.

    내용 해시를 파일명으로 써서 같은 이미지를 여러 카드에 붙여도 파일이 늘지 않는다.
    (기존 노트의 paste-<sha1>.jpg 명명과 같은 결)
    """
    filename = f"paste-{hashlib.sha1(data).hexdigest()}.{ext}"
    encoded = base64.b64encode(data).decode("ascii")

    try:
        stored = anki_request("storeMediaFile", filename=filename, data=encoded)
    except AnkiError as e:
        # anki_request는 오류 문구에 duplicate/empty가 있으면 노트 관련 예외로
        # 바꾼다. 여기서는 이미지 저장 실패이므로 오해가 없도록 다시 감싼다.
        raise AnkiError(f"이미지를 Anki에 저장하지 못했습니다: {e}") from e

    # AnkiConnect가 이름을 바꿔 저장할 수 있으므로 돌려준 값을 쓴다
    return stored or filename


def find_notes(query: str) -> list:
    """Anki 검색식으로 노트 ID 목록을 가져온다"""
    return anki_request("findNotes", query=query) or []


def notes_info(note_ids: list) -> list:
    """노트 ID 목록의 필드 내용을 가져온다"""
    if not note_ids:
        return []
    return anki_request("notesInfo", notes=list(note_ids)) or []


def update_note_fields(note_id: int, fields: dict):
    """기존 노트의 필드를 수정한다"""
    try:
        anki_request("updateNoteFields", note={"id": note_id, "fields": fields})
    except AnkiError as e:
        # anki_request는 오류 문구에 duplicate/empty가 있으면 노트 '추가' 관련
        # 예외로 바꾼다. 여기서는 수정 실패이므로 오해가 없도록 다시 감싼다.
        raise AnkiError(f"노트(id={note_id})를 수정하지 못했습니다: {e}") from e


def picture_html(filename: str) -> str:
    """
    Picture 필드에 넣을 HTML.
    크기는 노트 유형 CSS(.card img)가 max-height 200px로 잡으므로 지정하지 않는다.
    """
    return f'<img src="{filename}">'


def add_note(fields: dict, allow_duplicate: bool = False) -> int:
    """
    노트를 Anki에 추가하고 노트 ID를 반환 (Card 1 + Card 2 자동 생성).
    중복이면 AnkiDuplicateError가 난다. 사용자가 그래도 추가하겠다고 하면
    allow_duplicate=True로 다시 호출한다.
    """
    note = {
        "deckName": ANKI_DECK_NAME,
        "modelName": ANKI_MODEL_NAME,
        "fields": fields,
        "options": {"allowDuplicate": allow_duplicate},
        "tags": ["auto-generated"],
    }
    return anki_request("addNote", note=note)


# ── 3. 메인 실행 ───────────────────────────────────────────────

def main():
    print("=" * 50)
    print("  📚 Anki 카드 자동 생성기")
    print(f"  덱: {ANKI_DECK_NAME}  |  노트 유형: {ANKI_MODEL_NAME}")
    print("=" * 50)

    # Anki 연결 확인
    print("\n🔌 Anki 연결 확인 중...")
    try:
        version = anki_request("version")
        print(f"  ✅ AnkiConnect 버전: {version}")
        print(f"  📥 추가 대상: '{get_active_profile()}' 프로필 › '{ANKI_DECK_NAME}' 덱")
    except ConnectionError as e:
        print(f"\n❌ {e}")
        return

    # 덱 / 노트 유형 준비
    ensure_deck_exists(ANKI_DECK_NAME)
    try:
        ensure_model_exists(ANKI_MODEL_NAME)
    except CardMakerError as e:
        print(f"\n❌ {e}")
        return

    print("\n단어/표현을 입력하면 카드를 생성합니다. 종료하려면 'q' 입력.\n")

    while True:
        topic = input("단어/표현 입력 > ").strip()

        if topic.lower() == "q":
            print("\n👋 종료합니다.")
            break

        if not topic:
            print("  ⚠️  단어/표현을 입력해주세요.\n")
            continue

        print("  ⏳ Gemini로 카드 생성 중...")
        try:
            card = generate_card(topic)

            print(f"  📝 단어:      {card['Word/Phrase']}")
            print(f"  📝 개요:\n{card['Outline']}")
            print(f"  📝 한국어뜻:\n{card['KR_Definition']}")
            print(f"  📝 영어뜻:\n{card['EN_Definition']}")

            note_id = add_note(build_anki_fields(card))
            print(f"  ✅ 노트 추가 완료! Card 1 + Card 2 자동 생성됨 (ID: {note_id})\n")

        except CardMakerError as e:
            print(f"  ❌ {e}\n")
        except Exception as e:
            print(f"  ❌ 오류 발생: {e}\n")


if __name__ == "__main__":
    main()
