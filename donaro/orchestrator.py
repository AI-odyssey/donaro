"""통합 자비스 멀티에이전트 오케스트레이션 정책(11/12).
판단(업무 분해·접근법)은 최상위 모델이 한다. 배정·대체·예산 집행은 이 파일의 코드가 한다.
실행은 server.py의 run_orchestrated가 이 정책을 읽어 한다.
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

# 모델 등록부. route는 실제 실행 방식, health는 Router 상태 키다.
# 실호출 확인(11/12): claude native, codex native, OmniRoute codex/gemini/github/grok. gemini-3.1-pro는 한도 초과 상태였다.
MODELS = [
    {"id": "claude-opus", "app": "claude", "label": "Claude Opus", "route": "claude", "model": "opus", "tier": 3, "tools": True, "write": True, "health": "claude_native"},
    {"id": "claude-sonnet", "app": "claude", "label": "Claude Sonnet", "route": "claude", "model": "sonnet", "tier": 2, "tools": True, "write": True, "health": "claude_native"},
    {"id": "codex-sol", "app": "codex", "label": "Codex gpt-6.1-sol", "route": "codex_native", "model": "gpt-6.1-sol", "tier": 3, "tools": True, "write": False, "health": "codex_native"},
    {"id": "codex-sol-api", "app": "codex", "label": "gpt-6.1-sol API", "route": "api", "model": "codex/gpt-6.1-sol", "tier": 3, "tools": False, "write": False, "health": "api:codex/gpt-6.1-sol"},
    {"id": "codex-luna", "app": "codex", "label": "gpt-6-luna API", "route": "api", "model": "codex/gpt-6-luna", "tier": 1, "tools": False, "write": False, "health": "api:codex/gpt-6-luna"},
    {"id": "codex-cli", "app": "codex", "label": "Codex CLI · OmniRoute", "route": "codex", "model": "auto-fallback", "tier": 2, "tools": True, "write": False, "health": "codex"},
    {"id": "gemini-pro", "app": "gemini", "label": "Gemini 3.1 Pro", "route": "api", "model": "gemini/gemini-3.1-pro-preview", "tier": 3, "tools": False, "write": False, "health": "api:gemini/gemini-3.1-pro-preview"},
    {"id": "gemini-flash", "app": "gemini", "label": "Gemini 3 Flash", "route": "api", "model": "gemini/gemini-3-flash-preview", "tier": 2, "tools": False, "write": False, "health": "api:gemini/gemini-3-flash-preview"},
    {"id": "gemini-lite", "app": "gemini", "label": "Gemini 3.1 Flash Lite", "route": "api", "model": "gemini/gemini-3.1-flash-lite", "tier": 1, "tools": False, "write": False, "health": "api:gemini/gemini-3.1-flash-lite"},
    {"id": "copilot-auto", "app": "copilot", "label": "GitHub Copilot Auto", "route": "api", "model": "github/auto", "tier": 1, "tools": False, "write": False, "health": "api:github/auto"},
    {"id": "grok", "app": "grok", "label": "Grok 4.7", "route": "api", "model": "grok-cli/grok-4.7", "tier": 2, "tools": False, "write": False, "health": "api:grok-cli/grok-4.7"},
]
BY_ID = {m["id"]: m for m in MODELS}

# 서브 업무 종류별 대체 사슬(앞에서부터). 한도·장애로 막히면 다음 모델로 넘어간다.
# 기본은 Claude·Codex 상위 모델. 뒤쪽 모델은 앞 경로 한도·장애 때만 실행한다.
CHAINS = {
    "plan": ["claude-opus", "codex-sol-api"],
    "patch": ["claude-opus", "codex-sol-api"],
    "text": ["claude-opus", "codex-sol-api", "claude-sonnet", "codex-luna"],
    "draft": ["claude-opus", "codex-sol-api", "claude-sonnet", "codex-luna"],
    "research": ["codex-sol", "claude-opus", "codex-cli"],
    "deep_research": ["codex-sol", "claude-opus", "codex-cli"],
    "analysis": ["claude-opus", "codex-sol-api", "claude-sonnet"],
    "code": ["codex-sol", "claude-opus", "codex-sol-api", "claude-sonnet"],
    "review": ["claude-opus", "codex-sol-api", "claude-sonnet"],
    "synthesize": ["claude-opus", "codex-sol-api", "claude-sonnet"],
}
KINDS = ("text", "draft", "research", "analysis", "code")
# 서브 업무 종류별 출력 토큰 상한(배분 기본값). 계획이 정한 비중으로 전체 예산 안에서 나눈다.
DEFAULT_TOKENS = {"text": 800, "draft": 2500, "research": 3000, "deep_research": 4000, "analysis": 4000, "code": 3000}
TOTAL_BUDGET = 24000  # 오케스트레이션 1건의 출력 토큰 상한(계획·검수 포함). shortcut: 고정값, 실제 사용량이 쌓이면 종류별로 보정

PLAN_NOTE = (
    "너는 통합 자비스의 계획 담당이다. 요청을 가장 효율적으로 끝낼 접근법을 정하고 서브 업무로 나눈다. "
    "각 서브 업무는 kind 하나를 고른다: text(짧은 답·정리), draft(긴 글 초안), research(파일·웹 등 도구로 자료 확인), "
    "analysis(깊은 추론·비교·설계), code(코드 작성·검토). "
    "서로 독립인 업무는 depends_on을 비워 병렬로 돌게 하고, 앞 결과가 필요할 때만 의존을 건다. "
    "업무는 2~5개, 쪼갤 필요가 없으면 1개로 한다. weight는 그 업무가 쓸 토큰 비중(1~5)이다. "
    "너는 기획자이며 실제 도구 실행·파일 변경은 하지 않는다. "
    "코드 원본 변경 요청이면 code_workspace에 repository(본사 Git 저장소의 절대 루트 경로), paths(수정 가능한 저장소 상대 경로 배열), "
    "checks(셸 없이 실행할 검증 명령 argv 배열의 배열), directory(검증 실행 디렉터리의 저장소 상대 경로 또는 null)를 반드시 적는다. "
    "검증은 python -m unittest/pytest, 범위 안의 harness_/test_ 스크립트, npm run build/test/lint/check만 가능하다. 문서·조회는 code_workspace:null. "
    "코드 변경은 workspace에 작업별 worktree·기준 커밋 확인·변경 범위·검증·통합 방법을 적고, 문서·조회는 작업 폴더를 쓴다. "
    "제공된 공통·부서 지침을 적용하고 필요한 스킬을 설치 목록의 정확한 이름으로 skills에 고른다(최대 8개). "
    "각 goal에는 구체적인 입력·범위·산출물과 근거 요구를 적고 acceptance에는 검증 가능한 완료 조건을 적는다. "
    "자료 확인은 반드시 research로 분리한다. 실행자는 요청·맥락·지침 본문·선택 스킬을 함께 받는다. "
    "외부 발송·결제·파일 삭제는 업무로 만들지 않는다. "
    'JSON만 출력한다: {"approach":"한두 문장","workspace":"작업 공간과 검증·통합 방식","code_workspace":null,"skills":["필요한 설치 스킬 이름"],"subtasks":[{"id":"s1","title":"짧은 이름","kind":"text","goal":"이 업무가 낼 결과","depends_on":[],"weight":2}],"acceptance":["완료 기준"]}'
)


def needs_plan(text, kind, images=(), parent=False):
    """자동 작업은 기획자가 브리프를 만든다. 등록된 로컬 함수는 호출부에서 제외한다."""
    return True


def parse_plan(raw):
    """모델이 낸 계획을 검사한다. 틀리면 ValueError."""
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError("계획 JSON이 없음")
    plan = json.loads(m[0])
    subs = plan.get("subtasks")
    if not isinstance(plan.get("approach"), str) or not isinstance(subs, list) or not 1 <= len(subs) <= 5:
        raise ValueError("계획 형식 오류")
    seen = set()
    for i, s in enumerate(subs):
        if not isinstance(s, dict):
            raise ValueError("서브 업무 형식 오류")
        s["id"] = str(s.get("id") or f"s{i + 1}")[:12]
        s["kind"] = s.get("kind") if s.get("kind") in KINDS else "text"
        s["title"] = str(s.get("title") or s["id"])[:60]
        s["goal"] = str(s.get("goal") or s["title"])[:600]
        deps = s.get("depends_on") or []
        if not isinstance(deps, list) or any(d not in seen for d in deps):
            raise ValueError("의존 관계는 앞 업무만 가리킬 수 있음")  # 앞 업무만 허용 → 순환 불가
        s["depends_on"] = [str(d) for d in deps]
        w = s.get("weight")
        s["weight"] = w if isinstance(w, int) and 1 <= w <= 5 else 2
        if s["id"] in seen:
            raise ValueError("서브 업무 id 중복")
        seen.add(s["id"])
    plan["acceptance"] = [str(x)[:200] for x in plan.get("acceptance", [])][:6] if isinstance(plan.get("acceptance"), list) else []
    plan["workspace"] = str(plan.get("workspace") or "문서·조회: 작업 폴더. 코드 변경: 원본 상태 확인 후 작업별 worktree에서 검증.")[:1200]
    plan["approach"] = plan["approach"][:400]
    return plan


def allocate(subtasks, total=TOTAL_BUDGET, reserve=5000):
    """계획·종합·검수 몫(reserve)을 빼고 서브 업무에 비중대로 출력 토큰을 나눈다."""
    pool = max(total - reserve, 1000)
    weight = sum(s["weight"] for s in subtasks) or 1
    for s in subtasks:
        s["max_tokens"] = max(400, min(DEFAULT_TOKENS[s["kind"]] * 2, pool * s["weight"] // weight))
    return subtasks


_GR_TERMS = []


def gr_terms():
    """GR 고객 용어(소문자). 기본 목록 + private_terms.py + gr_terms_private.txt + ~/.claude/hooks/client_terms.json(모두 깃 제외).
    하나라도 읽지 못하면 캐시하지 않고 다음 호출에 다시 읽는다(조용히 빈 목록으로 굳지 않게)."""
    if _GR_TERMS:
        return _GR_TERMS
    terms, ok, here = set(), True, Path(__file__).resolve().parent
    try:
        spec = importlib.util.spec_from_file_location("_gr_private_terms", here.parent / "261104_실시간음성비서" / "private_terms.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        terms |= set(mod.TERMS) | set(mod.FIX) | set(mod.FIX.values())
    except Exception as exc:
        ok = False
        print("GR 용어(private_terms) 읽기 실패:", exc, file=sys.stderr)
    try:
        terms |= {l.strip() for l in (here / "gr_terms_private.txt").read_text(encoding="utf-8").splitlines() if l.strip()}
        terms |= {t for v in json.loads((Path.home() / ".claude" / "hooks" / "client_terms.json").read_text(encoding="utf-8")).values() for t in v}
    except (OSError, ValueError) as exc:
        ok = False
        print("GR 용어 파일 읽기 실패:", exc, file=sys.stderr)
    found = [t.casefold() for t in terms if len(t) >= 3]  # 두 글자 약어(TP 등)는 일반 단어와 겹쳐 뺀다
    if ok:
        _GR_TERMS.extend(found)
    return found


GR_HINT = re.compile(r"(?<![a-z])gr(?![a-z])|입법|법안|국회|고객사|국감|클라이언트|제안서|프로포절|의견서|서면질의|정책 ?(?:모니터링|동향|브리핑)|규제")


def is_gr(department_id, *texts):
    """GR 작업 판정: 부서가 10이거나, 요청·첨부(이름과 본문)·맥락에 GR 신호어나 고객 용어가 있으면 True.
    부서 규칙은 개발(40)이 GR보다 먼저라 'GR 모니터링 코드' 같은 요청도 여기서 다시 잡는다."""
    low = "\n".join(str(x) for x in texts if x).casefold()
    terms = gr_terms()
    if len(terms) < 10:  # 비공개 용어 파일을 못 읽은 상태면 판정할 수 없으니 GR로 본다(외부 모델 차단)
        return True
    return department_id == "10" or bool(GR_HINT.search(low)) or any(t in low for t in terms)


def gr_plan(plan, claude_ok=True, worktree=False):
    """GR 작업은 claude(local 제외) 외 실행기로 못 간다. Claude를 못 쓰거나 worktree 변경안이면 blocked."""
    if plan["engine"] in ("claude", "local"):
        return plan
    blocked = worktree or not claude_ok
    return dict(plan, engine="blocked" if blocked else "claude", model="none" if blocked else "opus", assignment_id=None,
                reason="GR 작업은 Claude만 사용(외부 API·Codex 제외); 기존 판단: " + plan["engine"])


def chain_for(kind, available, assigned=None, avoid_app=None, gr=False):
    """사용 가능한 모델만 남긴 대체 사슬. 확정된 부서 진행 담당이 있으면 맨 앞에 둔다(권한 맞을 때만).
    avoid_app: 검수는 만든 쪽과 다른 AI가 보게 한다(가능할 때)."""
    ids = list(CHAINS[kind])
    if assigned and kind not in ("plan", "review", "synthesize"):
        head = {"claude": "claude-opus", "codex_native": "codex-sol", "codex": "codex-cli", "economy": "codex-luna"}.get(assigned)
        if head and BY_ID[head]["tier"] == 3 and (kind not in ("research", "deep_research") or BY_ID[head]["tools"]):
            ids = [head] + [i for i in ids if i != head]
    if kind in ("research", "deep_research"):
        ids = [i for i in ids if BY_ID[i]["tools"]]
    ids = [i for i in ids if BY_ID[i]["tier"] == 3] + [i for i in ids if BY_ID[i]["tier"] != 3]
    chain = [BY_ID[i] for i in ids if available(BY_ID[i]["health"])]
    if avoid_app:
        chain = sorted(chain, key=lambda m: (m["tier"] != 3, m["app"] == avoid_app))
    return [m for m in chain if m["app"] == "claude"] if gr else chain


def is_quota(error):
    text = str(error).lower()
    return any(x in text for x in ("429", "quota", "rate limit", "usage limit", "weekly limit", "5-hour limit", "daily limit", "too many requests", "402", "exhausted"))


def order(subtasks):
    """의존을 지키는 실행 묶음. 같은 묶음 안은 병렬로 돈다."""
    done, waves, left = set(), [], list(subtasks)
    while left:
        wave = [s for s in left if all(d in done for d in s["depends_on"])]
        waves.append(wave)
        done |= {s["id"] for s in wave}
        left = [s for s in left if s["id"] not in done]
    return waves


def _selfcheck():
    assert needs_plan("3 더하기 4", "text")
    assert needs_plan("오늘 회의 요약해 줘", "text")
    assert needs_plan("1. 경쟁사 조사\n2. 비교표 작성\n3. 추천안", "text")
    assert needs_plan("A안과 B안을 비교해서 추천해 줘", "text")
    assert needs_plan("긴 비교 요청" * 100, "write")
    p = parse_plan('설명 {"approach":"a","subtasks":[{"id":"s1","kind":"research"},{"id":"s2","kind":"x","depends_on":["s1"],"weight":9}]}')
    assert p["subtasks"][1]["kind"] == "text" and p["subtasks"][1]["weight"] == 2
    try:
        parse_plan('{"approach":"a","subtasks":[{"id":"s1","depends_on":["s2"]},{"id":"s2"}]}')
        raise AssertionError("순환 허용됨")
    except ValueError:
        pass
    assert [len(w) for w in order(p["subtasks"])] == [1, 1]
    allocate(p["subtasks"])
    assert all(s["max_tokens"] >= 400 for s in p["subtasks"])
    up = lambda h: h != "claude_native"
    assert chain_for("plan", up)[0]["id"] == "codex-sol-api"  # Claude 한도 소진이면 다음 최상위 모델이 계획
    assert chain_for("review", lambda h: True, avoid_app="gemini")[0]["app"] != "gemini"
    assert all(m["tools"] for m in chain_for("research", lambda h: True, assigned="economy"))
    assert chain_for("analysis", lambda h: True, assigned="claude")[0]["id"] == "claude-opus"
    assert is_quota("HTTP 429 Too Many Requests") and not is_quota("timeout")
    assert {m["app"] for m in MODELS} == {"claude", "codex", "gemini", "copilot", "grok"}
    return True


if __name__ == "__main__":
    print("selfcheck", _selfcheck())
