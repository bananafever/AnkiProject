import PyInstaller.__main__
import os
import sys

def build_exe():
    # 메인 실행 파일 설정
    entry_point = "anki_gui.py"
    
    # 앱 이름 설정
    app_name = "AnkiCardMaker"
    
    # 추가할 데이터나 파일이 있다면 여기에 작성 (예: 아이콘)
    # 현재는 특별한 이미지 에셋이 없으므로 비워둡니다.
    datas = [
        # (source, destination)
        # (".env", "."), # .env를 포함하고 싶다면 주석 해제 (단, 보안 주의)
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
        
        # 프로젝트 관련 모듈들 (자동으로 추적되지만 명시적으로 추가 가능)
        "--add-data=styles.py;.",
        "--add-data=config.py;.", 
        "--add-data=anki_card_maker.py;.",
    ]
    
    # .env 파일은 빌드된 exe와 같은 폴더에 있어야 작동함
    print("="*50)
    print(f"🚀 {app_name} EXE 빌드를 시작합니다...")
    print("="*50)
    
    PyInstaller.__main__.run(opts)
    
    print("\n" + "="*50)
    print("✅ 빌드가 완료되었습니다!")
    print(f"📁 생성된 파일 위치: {os.path.join(os.getcwd(), 'dist', app_name + '.exe')}")
    print("\n⚠️  주의사항:")
    print("1. 실행 파일(.exe)과 같은 폴더에 '.env' 파일이 있어야 API 키를 인식합니다.")
    print("2. Anki가 실행 중이고 AnkiConnect가 설치되어 있어야 정상 작동합니다.")
    print("="*50)

if __name__ == "__main__":
    build_exe()
