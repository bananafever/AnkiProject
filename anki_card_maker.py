"""
Anki 카드 자동 생성기
- Gemini API로 카드 내용 생성
- AnkiConnect로 Anki에 카드 추가
- 노트 유형 "01_EN_Voca_New" 1개로 Card 1(빈칸채우기) + Card 2(단어카드) 자동 생성

사용법:
  python anki_card_maker.py

사전 준비:
  1. pip install google-genai requests python-dotenv
  2. Anki 실행 + AnkiConnect 애드온 설치 (코드: 2055492159)
  3. .env 파일에 GEMINI_API_KEY 입력

"""

import requests
import json
from google import genai
from google.genai import errors as genai_errors
from config import GEMINI_API_KEY, ANKI_DECK_NAME, ANKI_MODEL_NAME
import api_counter

# ── Gemini 설정 ────────────────────────────────────────────────
client = genai.Client(api_key=GEMINI_API_KEY)
MODEL_ID = "gemini-2.5-flash"  # 최신 모델로 업데이트


# ── 1. Gemini로 카드 내용 생성 ──────────────────────────────────

def generate_card(topic: str) -> dict:
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
    prompt = f"""
아래 단어/표현으로 Anki 플래시카드 내용을 만들어주세요.

단어/표현: {topic}

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
    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt
        )
        text = response.text.strip()
        api_counter.increment()  # 성공 시 카운터 증가
    except Exception as e:
        # google-genai는 다양한 예외를 던질 수 있음.
        # 한도 초과(429) 또는 기타 오류 처리
        if "429" in str(e) or "quota" in str(e).lower():
            raise RuntimeError("Gemini API 사용 한도(Quota)를 초과했습니다. 잠시 후 다시 시도하거나, API 설정을 확인해주세요.")
        raise e

    # 마크다운 코드블록 제거 (```json ... ``` 형태 대응)
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1])

    return json.loads(text)


def generate_cards_batch(topics: list) -> list:
    """
    여러 단어/표현을 한 번의 API 호출로 카드 내용 생성 (RPD 절약)
    Returns: list of card dicts
    """
    topics_str = "\n".join(f"- {t}" for t in topics)

    prompt = f"""
아래 단어/표현 목록 각각에 대해 Anki 플래시카드 내용을 만들어주세요.

단어/표현 목록:
{topics_str}

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
    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt
        )
        text = response.text.strip()
        api_counter.increment()  # 성공 시 카운터 증가
    except Exception as e:
        if "429" in str(e) or "quota" in str(e).lower():
            raise RuntimeError("Gemini API 사용 한도(Quota)를 초과했습니다. 잠시 후 다시 시도하거나, API 설정을 확인해주세요.")
        raise e

    # 마크다운 코드블록 제거
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1])

    return json.loads(text)


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
    except ConnectionError as e:
        print(f"\n❌ {e}")
        return

    # 덱 준비
    ensure_deck_exists(ANKI_DECK_NAME)

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
