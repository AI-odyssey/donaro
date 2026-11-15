"""도나로 맥락 카드(11/4 레드팀 1번): 터미널 자비스가 아는 것(메모리·진행 중 업무·Top 3·최근 대화)을 글 한 덩어리로 만든다.
Haiku 즉답 창구와 오퍼스 자비스 둘 다 띄울 때 시스템 프롬프트에 붙인다. 노션 조회는 10분 캐시.
"""
import json
import sys
import time
from pathlib import Path

HOME = Path.home()
HQ = HOME / "본사"
MEMORY = HOME / ".claude" / "projects" / "C--Users------" / "memory" / "MEMORY.md"
PRIORITY = HQ / "00_수신함" / "업무보드" / "priority.json"
CACHE = Path(__file__).with_name("context_cache.json")
NOTION_DB = ""  # 공개본: 노션 DB ID는 비공개 설정에 둔다  # 3. AI 공동 업무·대화 기록
HIDE = {"경영지원실"}  # 개인 영역(가계부 등)은 휴대폰 화면에 안 띄운다(업무보드 규칙과 같음)


def _text(prop):
    if not prop:
        return ""
    t = prop.get("type")
    if t in ("title", "rich_text"):
        return "".join(x.get("plain_text", "") for x in prop[t])
    if t in ("select", "status"):
        return (prop[t] or {}).get("name", "")
    return ""


def notion_tasks():
    try:
        c = json.loads(CACHE.read_text(encoding="utf-8"))
        if time.time() - c["ts"] < 600:
            return c["rows"]
    except (OSError, ValueError, KeyError):
        pass
    sys.path.insert(0, str(HOME / ".claude" / "hooks"))
    from notion_sync import _req
    body = {"filter": {"and": [{"property": "상태", "select": {"equals": "진행 중"}},
                               {"property": "부서", "select": {"is_not_empty": True}}]}, "page_size": 50}
    try:
        res = _req("POST", f"/databases/{NOTION_DB}/query", body).get("results", [])
    except Exception:
        return []
    rows = []
    for p in res:
        pr = p["properties"]
        rows.append({"제목": _text(pr.get("제목")), "부서": _text(pr.get("부서")),
                     "주체": _text(pr.get("액션 주체")), "남은 일": _text(pr.get("남은 일"))[:160]})
    CACHE.write_text(json.dumps({"ts": time.time(), "rows": rows}, ensure_ascii=False), encoding="utf-8")
    return rows


def build(history=None, n_hist=8, memory=True):
    out = [f"[오늘 {time.strftime('%Y-%m-%d (%a) %H:%M')}]"]
    try:
        pr = json.loads(PRIORITY.read_text(encoding="utf-8"))
        out.append("[이번 주 Top 3] " + ", ".join(pr["top"]) + " / 중요: " + ", ".join(pr["high"]))
    except (OSError, ValueError, KeyError):
        pass
    out.append("[업무 기록은 현재 요청과 관련된 항목만 필요한 때 조회한다.]")
    if memory and MEMORY.exists():
        out.append("[대표님 메모리 목록(제목 — 요지). 자세한 건 같은 폴더의 파일]")
        out += [l for l in MEMORY.read_text(encoding="utf-8").splitlines() if l.startswith("- [")]
    if history:
        out.append("[최근 대화]")
        out += [f"{'대표님' if m['role'] == 'user' else '자비스'}: {m['text'][:200]}" for m in history[-n_hist:]]
    return "\n".join(out)


if __name__ == "__main__":
    card = build()
    assert "[오늘" in card and "Top 3" in card, card[:200]
    print(card[:1500], f"\n... ({len(card)}자)")
