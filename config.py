import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# Gemini API 키
# .env 파일에서 정보를 가져옵니다. 없을 경우 직접 입력한 값을 사용할 수도 있습니다.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Anki 덱 이름 (없으면 자동 생성됩니다)
ANKI_DECK_NAME = "EN_Voca"

# Anki 노트 유형 이름
ANKI_MODEL_NAME = "01_EN_Voca_New"

