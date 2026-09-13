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
import json
import re
import shutil
import subprocess
import time
from google import genai
from google.genai import errors as genai_errors
from config import GEMINI_API_KEY, ANKI_DECK_NAME, ANKI_MODEL_NAME
import api_counter

# ── Gemini 설정 ────────────────────────────────────────────────
client = genai.Client(api_key=GEMINI_API_KEY)
MODEL_ID = "gemini-2.5-flash-lite"  # Flash-Lite 모델 적용

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


def _call_gemini(prompt: str) -> str:
    """Gemini API 호출. 429/503은 1초, 2초 간격으로 최대 3회 시도."""
    last_error = None
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=prompt
            )
            api_counter.increment()  # 성공 시 카운터 증가
            return response.text.strip()
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
            or "resource_exhausted" in error_str)


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
            else:
                reason = f"Gemini 오류 ({type(e).__name__})"

            if backend == BACKEND_GEMINI:
                # 폴백 없이 Gemini만 쓰도록 선택한 경우
                raise RuntimeError(_gemini_error_message(e)) from e

    _notify_fallback(reason)
    try:
        return _call_claude_cli(prompt)
    except Exception as cli_error:
        detail = f"→ Gemini: {gemini_error}\n" if gemini_error is not None else ""
        raise RuntimeError(
            f"Claude CLI 폴백도 실패했습니다. (폴백 사유: {reason})\n"
            f"{detail}→ Claude CLI: {cli_error}"
        ) from cli_error


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


# ── 1. Gemini로 카드 내용 생성 ──────────────────────────────────

def generate_card(topic: str, children_mode: bool = False) -> dict:
    """
    단어/표현 1개로 노트에 필요한 모든 필드 생성
    Gem 지침과 동일한 포맷으로 생성 (섹션 3, 7 제외)

    필드 매핑:
      Outline        ← 섹션 1. 개요
      KR_Definition  ← 섹션 2. 영한사전 뜻
      EN_Definition  ← 섹션 4. 영영사전 뜻
      FullSentence   ← 섹션 5. 예문 (HTML)
      BlankSentence  ← 섹션 6. 빈칸 예문 (HTML)
    """
    children_rule = """
[어린이 모드 규칙]
- 모든 정의, 설명, 예문에서 성적 표현, 외설적 내용, 욕설을 완전히 제거한다.
- 예문은 어린이에게 적합한 일상적/교육적 상황으로만 구성한다.
- 성인 주제(음주, 도박, 폭력, 성인 관계 등)를 다루는 예문은 중립적 상황으로 대체한다.
- 어린이 모드임을 언급하거나 특정 내용을 제외했음을 설명하는 문구를 절대 포함하지 않는다.
  (예: "어린이 모드에서는 ~", "성적인 의미를 제외하고 ~" 등의 표현 금지)
""" if children_mode else ""

    prompt = f"""
아래 단어/표현으로 Anki 플래시카드 내용을 만들어주세요.

단어/표현: {topic}
{children_rule}
[작성 규칙]
- HTML style 속성은 반드시 작은따옴표(')를 사용하세요. (JSON 파싱 오류 방지)
- Outline에는 '사용 빈도', '사용시 유의 사항', '뉘앙스', '문맥 및 배경' 4가지를 모두 반드시 포함하여 작성하세요.
- 뜻(KR_Definition, EN_Definition)을 작성할 때는 반드시 실제 사용 빈도가 가장 높은 뜻을 1번에 배치하고, 그 다음으로 자주 쓰이는 순서대로 나열하세요.
- ★중요★ 품사 작성 시 단어가 동사라면 단순히 '[동사]'라고 쓰지 말고, 반드시 '[자동사]' 또는 '[타동사]' (영어는 vi. 또는 vt.)로 완벽하게 구분해서 기재하세요.
- FullSentence와 BlankSentence는 동일한 문장을 사용하며,
  BlankSentence는 {topic} 부분만 _____로 교체합니다.
- 반드시 아래 JSON 형식으로만 답하세요. 다른 말 없이 JSON만 출력하세요.

{{
  "Word/Phrase": "{topic}",

  "Outline": "① 사용 빈도: (높음/중간/낮음 및 한 줄 설명)\\n② 사용시 유의 사항: (문법적 특징, 자주 헷갈리는 뜻 등)\\n③ 뉘앙스: (격식체/비격식, 긍정/부정 등)\\n④ 문맥 및 배경: (주로 쓰이는 상황)",

  "KR_Definition": "① [타동사] 뜻 1 (동사면 반드시 자/타 구분)\\n② [명사] 뜻 2\\n③ [형용사] 뜻 3",

  "EN_Definition": "① (vt.) Definition 1\\n② (n.) Definition 2\\n③ (adj.) Definition 3",

  "FullSentence": "<div style='line-height:1.6;'>예문1 <span style='color:#FFD54F'>{topic}</span> 예문1 계속<br><span style='color:#A0A0A0;'>→ 한국어 번역 1</span><br><br>예문2 <span style='color:#FFD54F'>{topic}</span> 예문2 계속<br><span style='color:#A0A0A0;'>→ 한국어 번역 2</span></div>",

  "BlankSentence": "<div style='line-height:1.6;'>예문1 _____ 예문1 계속<br><span style='color:#A0A0A0;'>→ 한국어 번역 1</span><br><br>예문2 _____ 예문2 계속<br><span style='color:#A0A0A0;'>→ 한국어 번역 2</span></div>"
}}
"""
    text = _generate_text(prompt)
    return json.loads(_extract_json(text))


def generate_cards_batch(topics: list, children_mode: bool = False) -> list:
    """
    여러 단어/표현을 한 번의 API 호출로 카드 내용 생성 (RPD 절약)
    Returns: list of card dicts
    """
    topics_str = "\n".join(f"- {t}" for t in topics)

    children_rule = """
[어린이 모드 규칙]
- 모든 정의, 설명, 예문에서 성적 표현, 외설적 내용, 욕설을 완전히 제거한다.
- 예문은 어린이에게 적합한 일상적/교육적 상황으로만 구성한다.
- 성인 주제(음주, 도박, 폭력, 성인 관계 등)를 다루는 예문은 중립적 상황으로 대체한다.
- 어린이 모드임을 언급하거나 특정 내용을 제외했음을 설명하는 문구를 절대 포함하지 않는다.
  (예: "어린이 모드에서는 ~", "성적인 의미를 제외하고 ~" 등의 표현 금지)
""" if children_mode else ""

    prompt = f"""
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
    text = _generate_text(prompt)
    return json.loads(_extract_json(text))


# ── 2. AnkiConnect로 카드 추가 ─────────────────────────────────
ANKI_URL = "http://localhost:8765"


def anki_request(action: str, **params):
    """AnkiConnect API를 호출하는 공통 함수"""
    payload = {"action": action, "version": 6, "params": params}
    try:
        res = requests.post(ANKI_URL, json=payload, timeout=5)
        res.raise_for_status()
        result = res.json()
        if result.get("error"):
            raise RuntimeError(f"AnkiConnect 오류: {result['error']}")
        return result["result"]
    except requests.exceptions.ConnectionError:
        raise ConnectionError(
            "Anki에 연결할 수 없습니다.\n"
            "→ Anki가 실행 중인지, AnkiConnect 애드온이 설치되어 있는지 확인하세요."
        )


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
        raise RuntimeError(
            f"노트 유형 '{model_name}'을(를) 찾을 수 없습니다.\n"
            f"현재 프로필: {get_active_profile()}\n"
            f"사용 가능한 노트 유형: {', '.join(models)}"
        )


def add_note(fields: dict) -> int:
    """노트를 Anki에 추가하고 노트 ID를 반환 (Card 1 + Card 2 자동 생성)"""
    note = {
        "deckName": ANKI_DECK_NAME,
        "modelName": ANKI_MODEL_NAME,
        "fields": fields,
        "options": {"allowDuplicate": False},
        "tags": ["auto-generated"],
    }
    note_id = anki_request("addNote", note=note)
    return note_id


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
    except RuntimeError as e:
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

            # Anki는 HTML 렌더링이므로 \n → <br> 변환 필요
            def to_html(text: str) -> str:
                return text.replace("\n", "<br>")

            fields = {
                "Word/Phrase":   card["Word/Phrase"],
                "BlankSentence": card["BlankSentence"],
                "FullSentence":  card["FullSentence"],
                "KR_Definition": to_html(card["KR_Definition"]),
                "EN_Definition": to_html(card["EN_Definition"]),
                "Outline":       to_html(card.get("Outline", "")),
                "Picture":       "",   # 직접 추가 필요
                "Audio":         "",   # 직접 추가 필요
            }

            note_id = add_note(fields)
            print(f"  ✅ 노트 추가 완료! Card 1 + Card 2 자동 생성됨 (ID: {note_id})\n")

        except json.JSONDecodeError:
            print("  ❌ Gemini 응답을 파싱하지 못했습니다. 다시 시도해주세요.\n")
        except RuntimeError as e:
            print(f"  ❌ {e}\n")
        except Exception as e:
            print(f"  ❌ 오류 발생: {e}\n")


if __name__ == "__main__":
    main()
