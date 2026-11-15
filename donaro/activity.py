"""도나로 밖 AI 활동 수집(읽기 전용, 메타데이터만)과 상주 프로그램 재시작.

- 예약 작업: Windows 작업 스케줄러에서 python으로 도는 본사 스크립트의 마지막 실행 결과
- 상주 프로그램: 텔레그램 봇·실시간 음성 비서 실행 여부(psutil), 재시작(vbs 실행기)
- 일자별 사용량: 작업 attempts의 토큰을 앱별로 묶고 Jev 호출 수(jev_usage.json)를 붙인다
판단은 전부 코드 규칙이다(3단 구조 1층). 외부 서비스로 아무것도 보내지 않는다.
"""
import json
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import re

import psutil

import orchestrator as orch

DEV = Path(__file__).resolve().parent.parent
GR_MASK = "[GR 업무]"
# is_gr에 더해 모니터링(고객 모니터링 자동화)도 GR로 본다. 고객 약칭(예: 두 글자 코드)은 용어 파일에 없어 이름만으론 못 잡는다
MONITOR = re.compile(r"monitor|모니터링", re.I)


def is_gr(department_id, *texts):
    return orch.is_gr(department_id, *texts) or any(MONITOR.search(str(t)) for t in texts if t)
SERVICES = {  # 이름 → (보드 표시, 프로세스 판별 문자열, 실행기 vbs)
    "telegram": ("텔레그램 봇", "bot.py", DEV / "261005_텔레그램자비스" / "start_bot.vbs"),
    "voice": ("실시간 음성 비서", "voice_agent.py", DEV / "261104_실시간음성비서" / "start_voice_agent.vbs"),
}
TASK_LOGS = {"HQ_git_backup": DEV / "261025_깃헙백업" / "backup.log"}
RESULT_TEXT = {0: "성공", 267009: "실행 중", 267011: "아직 실행 전", 267014: "중지됨"}
PS_TASKS = r"""[Console]::OutputEncoding=[Text.Encoding]::UTF8
Get-ScheduledTask | ? { $_.TaskPath -notlike '\Microsoft\*' -and (($_.Actions | % { "$($_.Execute)" }) -match 'python') } | % {
 $i = $_ | Get-ScheduledTaskInfo
 [pscustomobject]@{name=$_.TaskName; state=[string]$_.State; last=$(if($i.LastRunTime){$i.LastRunTime.ToString('o')}); result=$i.LastTaskResult;
  next=$(if($i.NextRunTime){$i.NextRunTime.ToString('o')}); action=(($_.Actions | % { "$($_.Execute) $($_.Arguments) $($_.WorkingDirectory)" }) -join ';')} } | ConvertTo-Json -Compress
"""
_cache = {"tasks": (0.0, [])}
_lock = threading.Lock()


def _ts(iso):
    try:
        t = datetime.fromisoformat(iso).timestamp()
        return t if t > 946684800 else None  # 2000년 이전 값은 '실행한 적 없음' 표시값
    except (TypeError, ValueError):
        return None


def last_log_line(path):
    try:
        lines = [l.strip() for l in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-30:] if l.strip()]
        return lines[-1][:160] if lines else ""
    except OSError:
        return ""


def parse_tasks(raw):
    """PowerShell JSON → 보드 행. 이름·명령에 GR 신호가 있으면 이름을 가리고 로그도 내지 않는다."""
    items = json.loads(raw) if raw.strip() else []
    items = [items] if isinstance(items, dict) else items
    out = []
    for x in items:
        gr = is_gr(None, x.get("name"), x.get("action"))
        code = x.get("result")
        out.append({"name": GR_MASK if gr else x.get("name"), "state": x.get("state"), "last": _ts(x.get("last")), "next": _ts(x.get("next")),
                    "result": RESULT_TEXT.get(code, f"실패(0x{(code or 0) & 0xFFFFFFFF:X})"), "ok": code in (0, 267009, 267011),
                    "log": "" if gr else last_log_line(TASK_LOGS[x["name"]]) if x.get("name") in TASK_LOGS else ""})
    return sorted(out, key=lambda r: -(r["last"] or 0))


def scheduled_tasks(ttl=60):
    """예약 작업 목록(60초 캐시). PowerShell 호출이 2~3초라 서버는 실행기 스레드에서 부른다."""
    with _lock:
        at, rows = _cache["tasks"]
        if time.time() - at < ttl:
            return rows
        try:
            p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", PS_TASKS], capture_output=True,
                               timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            rows = parse_tasks(p.stdout.decode("utf-8", "replace"))
        except (OSError, subprocess.TimeoutExpired, ValueError):
            rows = rows or []
        _cache["tasks"] = (time.time(), rows)
        return rows


def _procs(marker):
    found = []
    for p in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
        try:
            # 인자 하나가 그 파일로 끝날 때만(다른 명령의 문자열 속 'bot.py'를 잘못 끄지 않게)
            if any(a.replace("\\", "/").split("/")[-1] == marker for a in p.info["cmdline"] or []) and (p.info["name"] or "").lower().startswith(("python", "wscript")):
                found.append(p)
        except (psutil.Error, TypeError):
            continue
    return found


def services():
    out = []
    for key, (label, marker, vbs) in SERVICES.items():
        py = [p for p in _procs(marker) if (p.info["name"] or "").lower().startswith("python")]
        out.append({"id": key, "label": label, "running": bool(py), "since": min((p.info["create_time"] for p in py), default=None),
                    "restartable": vbs.exists()})
    return out


def restart(key):
    """상주 프로그램을 끄고 실행기로 다시 켠다. 음성 비서 실행기는 비정상 종료 시 되살리는 반복문이라 실행기도 함께 끈다."""
    label, marker, vbs = SERVICES[key]
    for p in _procs(vbs.name) + _procs(marker):
        try:
            p.kill()
        except psutil.Error:
            pass
    time.sleep(1)
    subprocess.Popen(["wscript.exe", str(vbs)], cwd=str(vbs.parent), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return label


def app_of_model(model):
    m = next((x for x in orch.MODELS if x["model"] == model), None)
    if m:
        return m["app"]
    s = str(model or "").lower()
    return "claude" if any(w in s for w in ("claude", "opus", "sonnet", "haiku")) else "codex" if any(w in s for w in ("codex", "gpt")) else "other"


def daily_usage(tasks, jev_counts, days=7, now=None):
    """일자별 Claude·Codex·기타 토큰(입력+출력)과 호출 수, Jev 호출 수. 최근 날짜가 위."""
    now = now or time.time()
    day0 = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    keys = [datetime.fromtimestamp(day0 - i * 86400).strftime("%Y-%m-%d") for i in range(days)]
    rows = {k: {"date": k, "claude": 0, "codex": 0, "other": 0, "calls": 0, "jev": int(jev_counts.get(k, 0))} for k in keys}
    for t in tasks:
        for a in t.get("attempts", []):
            k = datetime.fromtimestamp(a.get("started") or 0).strftime("%Y-%m-%d")
            if k not in rows:
                continue
            u = a.get("usage") or {}
            tok = int(u.get("input_tokens", 0) or 0) + int(u.get("output_tokens", 0) or 0)
            app = app_of_model(a.get("model"))
            rows[k][app if app in ("claude", "codex") else "other"] += tok  # Gemini·Copilot·Grok 등은 기타
            rows[k]["calls"] += 1
    return [rows[k] for k in keys]


def first_request(head):
    """세션 기록 앞부분(jsonl 문자열)에서 대표님의 첫 요청 문장. Claude Code·Codex 두 형식을 읽는다.
    시스템이 넣은 지침·환경 블록('<'·'#'로 시작)과 메타 줄은 건너뛴다."""
    for line in head.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        if d.get("type") == "user" and not d.get("isMeta"):  # Claude Code
            c = (d.get("message") or {}).get("content")
            parts = [c] if isinstance(c, str) else [x.get("text", "") for x in c or [] if isinstance(x, dict) and x.get("type") == "text"]
        elif d.get("type") == "response_item" and (d.get("payload") or {}).get("role") == "user":  # Codex
            parts = [x.get("text", "") for x in d["payload"].get("content") or [] if isinstance(x, dict)]
        else:
            continue
        for t in parts:
            t = " ".join(str(t).split())
            m = re.match(r'<scheduled-task name="([^"]+)"', t)
            if m:  # 예약 실행 세션은 사람 요청이 없어 작업 이름을 제목으로
                return "예약 실행: " + m[1]
            if t and not t.startswith(("<", "#", "Caveat:", "The following is the Codex")):
                return t
    return ""


_titles = {}  # 파일 경로 → (다 읽은 위치, 마지막 customTitle). 세션 기록은 뒤에 붙기만 해서 새로 붙은 부분만 읽는다
CUSTOM_TITLE = re.compile(rb'"type":"custom-title","customTitle":"((?:[^"\\]|\\.)*)"')


def custom_title(path):
    """Claude 데스크톱 사이드바에 보이는 세션 제목(jsonl의 custom-title 줄, 마지막 값). 없으면 ''."""
    key = str(path)
    pos, title = _titles.get(key, (0, ""))
    try:
        size = Path(path).stat().st_size
        if size < pos:  # 파일이 줄었으면(새로 쓰였으면) 처음부터
            pos, title = 0, ""
        with open(path, "rb") as f:
            f.seek(pos)
            chunk = f.read(size - pos)
    except OSError:
        return title
    cut = chunk.rfind(b"\n") + 1  # 덜 쓴 마지막 줄은 다음에 다시 읽는다
    found = CUSTOM_TITLE.findall(chunk[:cut])
    if found:
        try:
            title = json.loads(b'"' + found[-1] + b'"')
        except ValueError:
            pass
    _titles[key] = (pos + cut, title)
    return title


def session_title(title, head):
    """제목이 비었거나 2자 이하면 첫 요청 앞 40자로 대신한다."""
    title = (title or "").strip()
    return title if len(title) > 2 else (first_request(head)[:40] or title)


def mask_session(s, texts):
    """세션 제목·폴더·사용자 입력 중 하나라도 GR이면 제목을 가린다(본문은 화면에 내지 않는다)."""
    if is_gr(s.get("department_id"), s.get("title"), s.get("cwd"), *texts):
        s = dict(s, title=GR_MASK, gr=True, subtasks=[{**x, "title": GR_MASK} for x in s.get("subtasks", [])])
    return s


if __name__ == "__main__":  # 자체 점검(네트워크 없음)
    sample = json.dumps([{"name": "HQ_git_backup", "state": "Ready", "last": "2026-11-15T23:40:01+09:00", "result": 0, "next": None, "action": "python backup.py"},
                         {"name": "X_job", "state": "Ready", "last": "1999-11-30T00:00:00+09:00", "result": 1, "next": None, "action": "python 국회 법안.py"}])
    rows = parse_tasks(sample)
    assert parse_tasks(json.dumps([{"name": "XX_Monitoring_Daily", "result": 0, "action": "python monitor_xx.py"}]))[0]["name"] == GR_MASK
    assert rows[0]["name"] == "HQ_git_backup" and rows[0]["ok"] and rows[0]["result"] == "성공"
    assert rows[1]["name"] == GR_MASK and not rows[1]["ok"] and rows[1]["last"] is None and rows[1]["log"] == ""
    assert parse_tasks("") == [] and parse_tasks(json.dumps(sample and json.loads(sample)[0]))[0]["name"] == "HQ_git_backup"
    t0 = datetime(2026, 11, 16, 12).timestamp()
    tasks = [{"attempts": [{"model": "claude-opus", "started": t0, "usage": {"input_tokens": 10, "output_tokens": 5}},
                           {"model": "codex/gpt-6.1-sol", "started": t0 - 86400, "usage": {"input_tokens": 7, "output_tokens": 3}},
                           {"model": next(m["model"] for m in orch.MODELS if m["app"] not in ("claude", "codex")), "started": t0, "usage": {"input_tokens": 2}}]}]
    u = daily_usage(tasks, {"2026-11-16": 4}, days=3, now=t0)
    assert [r["date"] for r in u] == ["2026-11-16", "2026-11-15", "2026-11-14"]
    assert u[0]["claude"] == 15 and u[0]["other"] == 2 and u[0]["jev"] == 4 and u[1]["codex"] == 10 and u[2]["calls"] == 0
    assert mask_session({"title": "국회 법안 정리", "cwd": "x"}, [])["title"] == GR_MASK
    assert mask_session({"title": "서버 재시작", "cwd": "x", "department_id": "40"}, ["도나로 보드"])["title"] == "서버 재시작"
    assert set(SERVICES) == {"telegram", "voice"}
    head = "\n".join(json.dumps(x, ensure_ascii=False) for x in [
        {"type": "user", "isMeta": True, "message": {"content": "meta"}},
        {"type": "user", "message": {"content": "<command-name>/clear</command-name>"}},
        {"type": "user", "message": {"content": [{"type": "text", "text": "도나로 보드에 사용량 표를   붙여 줘. 그리고 하네스도 돌려 줘 길게 길게 길게"}]}}])
    assert session_title("ㄱㄱ", head) == "도나로 보드에 사용량 표를 붙여 줘. 그리고 하네스도 돌려 줘 길게 길게 길게"[:40]
    assert session_title("다음 단계 진행", head) == "다음 단계 진행"
    codex = json.dumps({"type": "response_item", "payload": {"role": "user", "content": [{"type": "input_text", "text": "# AGENTS.md instructions"}, {"type": "input_text", "text": "온톨로지 정리"}]}}, ensure_ascii=False)
    assert first_request(json.dumps({"type": "user", "message": {"content": '<scheduled-task name="nightly-x" file="a">run'}})) == "예약 실행: nightly-x"
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "s.jsonl"
        f.write_text('{"type":"custom-title","customTitle":"첫 제목","sessionId":"x"}\n{"type":"user"}\n', encoding="utf-8")
        assert custom_title(f) == "첫 제목"
        with open(f, "a", encoding="utf-8") as fh:
            fh.write('{"type":"custom-title","customTitle":"도나로 \\"4단계\\"","sessionId":"x"}\n{"type":"custom-title","customTitle":"덜 쓴')
        assert custom_title(f) == '도나로 "4단계"'  # 마지막 완성 줄의 값, 덜 쓴 줄은 무시
        assert custom_title(Path(d) / "없음.jsonl") == ""
    assert first_request(codex) == "온톨로지 정리" and session_title("", "not json") == ""
    print("activity self-check PASS")
