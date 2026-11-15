"""Jev(TypeSafe System One) 빠른 판단층. 3단 구조의 1층: 판단은 Jev, 결정은 코드.

지금 쓰는 곳: 단어 규칙으로 부서를 못 정한 요청의 부서 추정.
GR 문장은 외부로 보내지 않는다(orchestrator.is_gr). 키가 없거나 실패하면 None을 돌려 기존 동작(미분류)을 그대로 둔다.
"""
import json
import os
import threading
import time
import urllib.request
from pathlib import Path

import orchestrator as orch

API = "https://api.typesafe.ai/v1/systemone"
# GR사업부(10)는 후보에서 뺀다: GR 문장은 애초에 Jev로 보내지 않는다
DEPARTMENTS = {
    "01": "일정·할 일, 재무·가계부, 투자, 계약·행정, 비전·전략",
    "20": "석사논문, 정치철학, 유학·박사 지원, 리딩노트, Writing Sample",
    "30": "Substack 글, 극본, 영상·숏폼, 개인 브랜딩",
    "40": "개발, 봇·자동화, 스크립트, 서버·앱 고치기",
    "50": "글을 다듬거나 문체를 고치는 일",
    "60": "웹·장표·카드뉴스·썸네일 등 시각 디자인",
    "70": "AI·업무 강의 정리, 뉴스 리서치, 업무 영어 공부",
    "80": "영화·음악 등 개인 취향 기록",
}
MIN_PROB, MIN_FIT = 0.6, 0.3  # 이 아래면 미분류. 적합 0.3: 실측(11/16) 윤문 요청 0.41, 인사 0.06
_cache = {}


def key():
    k = os.environ.get("TYPESAFE_API_KEY")
    if not k:
        env = Path(__file__).with_name(".env")
        for line in env.read_text(encoding="utf-8").splitlines() if env.exists() else []:
            if line.startswith("TYPESAFE_API_KEY="):
                k = line.split("=", 1)[1].strip()
    return k or None


USAGE = Path(__file__).with_name("jev_usage.json")  # 날짜 → 호출 수(보드 사용량 표). gitignore 대상
_usage_lock = threading.Lock()


def calls():
    try:
        return json.loads(USAGE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def count_call():
    with _usage_lock:
        d = calls()
        day = time.strftime("%Y-%m-%d")
        d[day] = d.get(day, 0) + 1
        USAGE.write_text(json.dumps(dict(sorted(d.items())[-60:])), encoding="utf-8")


def ask(state, questions, timeout=2.5):
    """Jev에 한 번 묻는다. 답(answers dict) 또는 None."""
    k = key()
    if not k:
        return None
    body = json.dumps({"state": state, "model": "jev-latest", "questions": questions}).encode()
    req = urllib.request.Request(API, body, {"Authorization": f"Bearer {k}", "Content-Type": "application/json"})
    count_call()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())["answers"]
    except Exception:
        return None


def decide_department(answers):
    """Jev 답 -> 부서 id 또는 None. 결정 규칙은 여기(코드)에 둔다."""
    if not answers:
        return None
    c, fit = answers["department"], answers["fits"]["noul"]
    prob = c["probabilities"].get(c["choice"], 0)
    return c["choice"] if prob >= MIN_PROB and fit >= MIN_FIT else None


def department(req):
    """단어 규칙이 못 정한 요청의 부서. GR이면 묻지 않는다."""
    req = req.strip()[:2000]
    if not req or orch.is_gr(None, req):
        return None
    if req not in _cache:  # shortcut: 메모리 캐시라 재시작 시 비움, 요청이 많아지면 크기 제한 추가
        _cache[req] = decide_department(ask(req, {
            "department": {"type": "choice", "instructions": "이 요청을 맡을 부서", "criteria": DEPARTMENTS},
            "fits": {"type": "noul", "instructions": "이 요청은 위 부서 중 하나가 맡을 구체적인 업무다(인사·잡담이 아니다)"},
        }))
    return _cache[req]


if __name__ == "__main__":  # 자체 점검(네트워크 없이 결정 규칙만)
    ok = {"department": {"choice": "40", "probabilities": {"40": 0.8}}, "fits": {"noul": 0.9}}
    assert decide_department(ok) == "40"
    assert decide_department({**ok, "fits": {"noul": 0.2}}) is None
    assert decide_department({"department": {"choice": "30", "probabilities": {"30": 0.4}}, "fits": {"noul": 0.9}}) is None
    assert decide_department(None) is None
    assert department("국회 법안 동향 정리해줘") is None  # GR은 외부로 안 보냄
    print("jev self-check PASS", "(키 있음)" if key() else "(키 없음: 실제 호출은 건너뜀)")
