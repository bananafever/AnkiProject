"""
Gemini API 일일 사용량 카운터
- 기준: KST 오후 5시마다 리셋
- 데이터 저장: api_usage.json
"""

import json
import os
from datetime import datetime, timezone, timedelta

import sys

KST = timezone(timedelta(hours=9))
RESET_HOUR = 17       # KST 오후 5시
DAILY_LIMIT = 20

def _get_base_dir() -> str:
    """exe로 실행 시엔 exe 위치 폴더, py로 실행 시엔 소스 폴더 반환"""
    if getattr(sys, "frozen", False):
        # PyInstaller로 패키징된 exe 실행 중
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

COUNTER_FILE = os.path.join(_get_base_dir(), "api_usage.json")


def _get_current_period_start() -> datetime:
    """현재 카운팅 기간의 시작 시각 반환 (가장 최근 KST 오후 5시)"""
    now_kst = datetime.now(KST)
    today_reset = now_kst.replace(hour=RESET_HOUR, minute=0, second=0, microsecond=0)
    if now_kst >= today_reset:
        return today_reset
    else:
        return today_reset - timedelta(days=1)


def load_usage() -> dict:
    """저장된 사용량 불러오기 (기간이 지났으면 자동 초기화)"""
    period_start_str = _get_current_period_start().isoformat()

    if os.path.exists(COUNTER_FILE):
        try:
            with open(COUNTER_FILE, "r") as f:
                data = json.load(f)
            if data.get("period_start") == period_start_str:
                return data
        except Exception:
            pass

    # 새 기간 시작 또는 파일 없음 → 초기화
    return {"count": 0, "period_start": period_start_str}


def _save_usage(data: dict):
    with open(COUNTER_FILE, "w") as f:
        json.dump(data, f)


def increment() -> int:
    """API 호출 1회 증가 후 현재 누적 횟수 반환"""
    data = load_usage()
    data["count"] += 1
    _save_usage(data)
    return data["count"]


def get_count() -> int:
    """현재 누적 횟수 반환"""
    return load_usage()["count"]


def get_next_reset_str() -> str:
    """다음 리셋 시각 문자열 반환 (예: 03월 09일 오후 5:00)"""
    next_reset = _get_current_period_start() + timedelta(days=1)
    return next_reset.strftime("%m월 %d일 오후 5:00")
