"""
Google Antigravity CLI(`agy`)를 비대화식으로 부른다.

Gemini를 API 키 대신 **구독(Google AI Pro 등)**으로 쓰는 길이다.
CPProject의 app/utils/agy_cli.py를 옮겨 왔다.

### 부르는 꼴이 까다로운 두 가지
1. **평문 stdin은 읽지 않는다.** `--input-format stream-json`으로 한 줄짜리
   NDJSON을 넣는다. 이 입력은 `--output-format stream-json`을 요구한다
   — 끝의 `result` 이벤트를 읽는다.
2. **코딩 에이전트라 도구부터 쓰려 든다.** 비대화식에서는 승인이 필요한 도구가
   거절되고, 그러면 `status: SUCCESS`인데 `response`가 빈 채 끝난다.
   프롬프트 맨 앞에 `NO_TOOLS` 머리말을 붙이면 도구 없이 곧바로 답한다.
   `--dangerously-skip-permissions`는 쓰지 않는다.

### 대화 기록
agy에는 세션을 남기지 않는 옵션이 없다. 부를 때마다
`~/.gemini/antigravity-cli/conversations/<id>.db`와 `brain/<id>/`가 생긴다.
답을 받으면 **그 id의 것만** 지운다(`_forget`).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional


class AgyCLIError(Exception):
    pass


class AgyUnavailable(AgyCLIError):
    """agy 실행 파일을 찾지 못함"""


class AgyQuotaExceeded(AgyCLIError):
    """한도 초과. 다시 해 봐야 같은 답이 온다."""


# Flash가 Pro보다 구독 한도를 덜 쓴다. `.env`의 AGY_MODEL로 바꾼다
# (`agy models`가 고를 수 있는 이름을 보여 준다).
DEFAULT_MODEL = "gemini-3.8-flash-medium"

NO_TOOLS = ("[중요] 이것은 순수 텍스트 질의다. 도구·명령·파일·브라우저를 절대 쓰지 말고, "
            "아래 글만 읽고 곧바로 최종 답을 내라.\n\n")

_CANDIDATES = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe",
    Path.home() / ".local" / "bin" / "agy",
)

_STATE = Path.home() / ".gemini" / "antigravity-cli"

_QUOTA_WORDS = ("quota", "rate limit", "resource_exhausted", "429", "exhausted")


def find_cli() -> Optional[str]:
    """agy 실행 파일 경로. 못 찾으면 None."""
    override = os.environ.get("AGY_CLI_PATH", "").strip()
    if override:
        return override if Path(override).is_file() else None

    found = shutil.which("agy")
    if found:
        return found
    for p in _CANDIDATES:
        try:
            if p and p.is_file():
                return str(p)
        except OSError:
            continue
    return None


def unavailable_reason() -> str:
    return ("Antigravity CLI(agy)를 찾을 수 없습니다.\n"
            "→ PowerShell에서 `irm https://antigravity.google/cli/install.ps1 | iex`로 설치하고 "
            "`agy`를 한 번 실행해 로그인해 주세요.\n"
            "→ 다른 곳에 있다면 .env의 AGY_CLI_PATH에 경로를 지정합니다.")


def model_name() -> str:
    return os.environ.get("AGY_MODEL", "").strip() or DEFAULT_MODEL


def _result_event(stdout: str) -> Optional[dict]:
    """stream-json 출력에서 마지막 `result` 이벤트의 본체."""
    got = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("event") == "result":
            got = ev.get("result") or {}
    return got


def _forget(conversation_id: str) -> None:
    """이번 호출이 남긴 대화 기록을 지운다. 실패해도 답은 돌려준다."""
    cid = (conversation_id or "").strip()
    # id는 uuid다. 경로 조각이 섞여 있으면 아무것도 지우지 않는다.
    if not cid or any(c in cid for c in "/\\.:") or len(cid) < 16:
        return
    conv = _STATE / "conversations"
    for p in (conv / (cid + ".db"), conv / (cid + ".db-wal"), conv / (cid + ".db-shm")):
        try:
            p.unlink()
        except OSError:
            pass
    shutil.rmtree(_STATE / "brain" / cid, ignore_errors=True)


def run_text(prompt: str, timeout: int = 180, model: Optional[str] = None) -> str:
    """프롬프트를 넣고 답 글을 돌려준다. `model`을 안 주면 `model_name()`."""
    exe = find_cli()
    if not exe:
        raise AgyUnavailable(unavailable_reason())

    # 빈 폴더를 cwd로 — 앱 폴더나 저장소의 CLAUDE.md를 읽히지 않는다.
    tmp = tempfile.mkdtemp(prefix="agy_")
    cmd = [exe, "--input-format", "stream-json", "--output-format", "stream-json",
           "--model", model or model_name()]
    line = json.dumps({"event": "user", "message": {"content": NO_TOOLS + prompt}},
                      ensure_ascii=False) + "\n"

    creationflags = 0
    if sys.platform == "win32":
        # 패키징된 GUI(.exe)에서 콘솔 창이 깜빡이지 않도록
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        proc = subprocess.run(
            cmd, input=line.encode("utf-8"), cwd=tmp,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, creationflags=creationflags)
    except subprocess.TimeoutExpired:
        raise AgyCLIError(f"agy가 {timeout}초 안에 끝나지 않았습니다.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    res = _result_event(out)
    if res is None:
        tail = (err or out)[-800:]
        if any(w in tail.lower() for w in _QUOTA_WORDS):
            raise AgyQuotaExceeded(f"agy 한도 초과입니다.\n{tail}")
        raise AgyCLIError(f"agy가 답을 내지 못했습니다 (코드 {proc.returncode}).\n{tail}")
    _forget(res.get("conversation_id", ""))

    text = (res.get("response") or "").strip()
    if res.get("status") != "SUCCESS" or not text:
        why = str(res.get("error") or "")
        if any(w in (why + err).lower() for w in _QUOTA_WORDS):
            raise AgyQuotaExceeded(f"agy 한도 초과입니다.\n{why or err[-800:]}")
        if res.get("denied_actions"):
            why = why or ("도구 사용이 거절되어 답이 비었습니다 (%s)"
                          % ", ".join(str(a.get("display_name") or a.get("action"))
                                      for a in res["denied_actions"]))
        raise AgyCLIError(f"agy가 빈 답을 냈습니다 ({res.get('status')}).\n{why or err[-800:]}")
    return text
