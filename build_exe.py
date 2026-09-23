import PyInstaller.__main__
import os
import sys

def build_exe():
    # 메인 실행 파일 설정
    entry_point = "anki_gui.py"
    
    # 앱 이름 설정
    app_name = "AnkiCardMaker"
    
    # 추가할 데이터나 파일이 있다면 여기에 작성 (예: 아이콘)
    # .env는 일부러 넣지 않는다. 사용자가 exe 옆에 두고 고쳐 쓰는 설정 파일이다.
    datas = [
        # (source, destination)
    ]
    
    # PyInstaller 옵션 구성
    opts = [
        entry_point,
        "--name=%s" % app_name,
        "--onefile",        # 단일 파일로 생성
        "--windowed",       # 실행 시 터미널 창 안 뜨게 설정
        "--clean",          # 빌드 전 캐시 삭제
        "--noconfirm",      # 덮어쓰기 확인 생략
        # "--icon=icon.ico", # 아이콘이 있다면 주석 해제 후 경로 지정
        
        # PySide6 관련 최적화 (필요시)
        "--collect-submodules=PySide6",
        
        # .py 모듈은 PyInstaller가 자동으로 번들하므로 --add-data가 필요 없다.
        # 반면 checkmark.svg는 코드가 경로로 여는 자원이라 명시해야 한다.
        # (빠뜨리면 체크박스 체크 표시가 조용히 사라진다)
        "--add-data=checkmark.svg;.",
    ]
    
    # .env(선택)는 빌드된 exe와 같은 폴더에서 읽는다
    print("="*50)
    print(f"🚀 {app_name} EXE 빌드를 시작합니다...")
    print("="*50)
    
    PyInstaller.__main__.run(opts)
    
    print("\n" + "="*50)
    print("✅ 빌드가 완료되었습니다!")
    print(f"📁 생성된 파일 위치: {os.path.join(os.getcwd(), 'dist', app_name + '.exe')}")
    print("\n⚠️  주의사항:")
    print("1. 카드 생성에는 agy(Antigravity CLI) 설치와 로그인이 필요합니다. (없으면 Claude CLI로 넘어갑니다)")
    print("2. 모델을 바꾸려면 exe와 같은 폴더의 '.env'에 AGY_MODEL=... 를 적습니다. (선택)")
    print("3. Anki가 실행 중이고 AnkiConnect가 설치되어 있어야 정상 작동합니다.")
    print("="*50)

if __name__ == "__main__":
    build_exe()
