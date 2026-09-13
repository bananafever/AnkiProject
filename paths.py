"""
경로 해석 헬퍼

앱이 쓰는 경로는 성격이 두 가지이고, 패키징(PyInstaller)하면 서로 다른 곳을 봐야 한다.

- resource_path : 앱에 동봉되는 읽기 전용 자원 (checkmark.svg 등)
                  → frozen이면 PyInstaller가 압축을 푼 임시 폴더(_MEIPASS)
- user_data_path: 사용자가 직접 두고 쓰는 파일 (.env, api_usage.json)
                  → frozen이면 exe가 놓인 폴더

둘을 섞어 쓰면 exe에서 조용히 파일을 못 찾는다.
"""

import os
import sys


def _script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(name: str) -> str:
    """앱에 동봉된 자원의 절대 경로"""
    base = getattr(sys, "_MEIPASS", None) or _script_dir()
    return os.path.join(base, name)


def user_data_path(name: str) -> str:
    """사용자가 exe 옆에 두고 쓰는 파일의 절대 경로"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = _script_dir()
    return os.path.join(base, name)
