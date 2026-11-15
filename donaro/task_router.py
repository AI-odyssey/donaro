"""Shared routing policy. Eligibility and permissions are enforced before preferences."""
import re
import time

VERSION = "2026.11.13-planner"
HEALTH_KEY = {"claude": "claude_native", "codex": "codex", "codex_native": "codex_native", "economy": "api:codex/gpt-6-luna"}
STATUS_NOTE = "마지막 줄에 [작업상태: 완료], 자료가 없으면 [작업상태: 확인필요], 실패하면 [작업상태: 실패]를 쓴다."


def local_answer(text):
    expression = re.fullmatch(r"\s*(?:지금\s*)?(-?\d{1,9})\s*(더하기|빼기|곱하기|나누기|[+*/-])\s*(-?\d{1,9})\s*(?:은|는|이|가)?\s*(?:얼마|몇|계산해\s*줘)?[요야?!.\s]*", text)
    if expression:
        left, op, right = expression.groups()
        a, b = int(left), int(right)
        if op in ("/", "나누기") and b == 0:
            return "0으로 나눌 수 없습니다.\n[작업상태: 확인필요]"
        value = a + b if op in ("+", "더하기") else a - b if op in ("-", "빼기") else a * b if op in ("*", "곱하기") else a / b
        return f"계산 결과는 {value}입니다.\n[작업상태: 완료]"
    if re.fullmatch(r"\s*(?:오늘|지금|현재)\s*(?:날짜|며칠|몇\s*일)(?:가|이|는|야|예요|알려\s*줘|인가요|뭐야|\s|[?!.])*", text):
        from datetime import datetime, timezone, timedelta
        return datetime.now(timezone(timedelta(hours=9))).strftime("오늘은 %Y년 %m월 %d일입니다.") + "\n[작업상태: 완료]"
    return None


class Router:
    def __init__(self, store):
        self.store = store

    def health(self, route):
        return self.store.get_state("health:" + route, {"state": "unknown"})

    def available(self, route):
        # A timer permits a recovery probe; it never declares a quota recovered.
        return self.health(route)["state"] not in ("quota", "auth", "rate_limit", "unavailable")

    def failure(self, route, error, model=None, observed_at=None):
        message = str(error)
        text = message.lower()
        kind = ("auth" if any(x in text for x in ("401", "unauthorized", "authentication")) else
                "quota" if any(x in text for x in ("weekly limit", "usage limit", "5-hour limit", "daily limit", "quota_exhausted")) else
                "rate_limit" if any(x in text for x in ("429", "rate limit")) else "unavailable")
        delay = {"quota": 3600, "rate_limit": 120, "unavailable": 300, "auth": 86400}[kind]
        now = time.time() if observed_at is None else observed_at
        hint = None
        match = re.search(r"resets\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)", message, re.I)
        if kind == "quota" and "Asia/Seoul" in message and match:
            hour, minute = int(match[1]), int(match[2] or 0)
            if 1 <= hour <= 12 and minute < 60:
                from datetime import datetime, timezone, timedelta
                local = datetime.fromtimestamp(now, timezone(timedelta(hours=9)))
                target = local.replace(hour=hour % 12 + (12 if match[3].lower() == "pm" else 0), minute=minute, second=0, microsecond=0)
                if target.timestamp() <= now:
                    target += timedelta(days=1)
                delay = max(60, target.timestamp() - now)
                hint = "제공자 시각 힌트 이전에는 복구 호출하지 않음; 날짜는 미확정"
        self.store.set_state("health:" + route, {"state": kind, "observed_at": now,
                             "next_probe_at": now + delay, "reason": message[:500], "model": model, "reset_hint": hint})

    def success(self, route):
        self.store.set_state("health:" + route, {"state": "ready", "observed_at": time.time()})

    def seed(self, tasks):
        prior = self.health("claude_native")
        if prior["state"] == "quota" and "reset_hint" not in prior:
            self.failure("claude_native", prior.get("reason", "weekly limit"), prior.get("model"), prior.get("observed_at"))
        if prior["state"] != "unknown":
            return
        for task in reversed(list(tasks.values())):
            if task.get("provider") != "claude" or task.get("route", "native") != "native":
                continue
            if any(x in task.get("result", "").lower() for x in ("weekly limit", "usage limit")):
                self.failure("claude_native", task["result"], task.get("model"))
                return

    def assignment_block(self, engine, kind, images, parent):
        """부서 진행 담당을 쓸 수 없는 이유. 쓸 수 있으면 None. 권한·가용 조건이 배정보다 먼저다."""
        if engine not in HEALTH_KEY:
            return "라우터가 실행할 수 없는 담당"
        if kind == "write" and engine != "claude":
            return "쓰기 작업인데 읽기 전용 실행기"
        if engine == "economy" and (kind != "text" or images or parent):
            return "도구 없는 경량 경로라 도구·첨부 작업 불가"
        if not self.available(HEALTH_KEY[engine]):
            return "실행기 사용 불가: " + self.health(HEALTH_KEY[engine])["state"]
        return None

    def select(self, text, images=(), requested="auto", checks=None, parent=False, assigned=None):
        lower = text.lower()
        transform = bool(re.search(r"^.{0,35}(번역|교정|맞춤법|요약).{0,20}[:：\n]", text)) and not images
        nouns = r"파일|폴더|코드|설정|캘린더|메일|서버|앱|프로젝트|문서"
        verbs = r"수정|삭제|이동|저장|등록|업로드|전송|발송|배포|게시|설치|연결|만들"
        write = bool(re.search(nouns, lower) and re.search(verbs, lower)) and not transform
        descriptive = bool(re.search(r"설명|요약|분석|검토|여부|방식|원리", lower))
        change_command = bool(re.search(r"(?:수정|삭제|이동|저장|등록|업로드|전송|발송|배포|게시|설치|연결)(?:해|하라|하세요|하고|하기)|만들어|바꿔|고쳐", lower))
        if descriptive and not change_command:
            write = False
        tools = bool(re.search(r"(?:최근|진행|현재|요즘|지난|오늘).{0,20}(?:업무|작업|할\s*일)|(?:업무|작업).{0,20}(?:브리핑|현황|진척|진행\s*상황)", lower) or images or parent or re.search(r"https?://|파일|첨부|폴더|검색|조사|최신|오늘.{0,10}(뉴스|기사|주가|날씨)|현재.{0,10}(상태|계정|접속)|노션|zotero|overleaf|도구", lower)) and not transform
        deep = bool(re.search(r"전략|설계|심층|논문|복잡|아키텍처|다단계|코드.*분석", lower)) or len(text) > 5000
        kind = "write" if write else "analysis" if deep else "read" if tools else "text"
        contract = {"kind": kind, "checks": checks or {}, "required_reads": list(images),
                    "max_attempts": 2, "deadline_seconds": 120 if kind == "text" else 600,
                    "estimated_seconds": [5, 30] if kind == "text" else [30, 600],
                    "soft_token_budget": 150000, "token_budget_kind": "between-attempts only"}
        reason = []
        if requested in ("auto", "economy") and not images and not parent and local_answer(text):
            engine = "local"
            reason.append("등록된 계산·날짜 함수로 처리; 모델 호출 없음")
        elif write:
            simple_file = bool(re.search(r"\.(?:txt|md|csv|json)\b|텍스트\s*파일", lower)) and not deep
            engine = "codex_artifact" if requested == "codex" or (requested in ("auto", "economy") and simple_file) else "claude" if self.available("claude_native") else "codex_artifact"
            reason.append("간단한 텍스트 파일·Claude 대체는 경량 API 작성 후 서버 검증·저장" if engine == "codex_artifact" else "도구 실행이 필요한 변경 작업")
        elif requested == "claude" and self.available("claude_native"):
            engine = "claude"
            reason.append("사용자 선호와 계정 가용 조건 충족")
        elif deep:
            engine = "codex_native" if self.available("codex_native") else "claude" if self.available("claude_native") else "blocked"
            reason.append("깊은 분석은 인증된 Codex 고성능 경로")
        elif re.search(r"노션|notion|zotero|overleaf|조테로|오버리프", lower):
            engine = "codex_native" if self.available("codex_native") else "blocked"
            reason.append("연결 앱은 기존 MCP 설정을 사용하는 native Codex 경로")
        elif requested == "codex" or tools:
            engine = "codex_native" if self.available("codex_native") else "codex" if self.available("codex") else "blocked"
            reason.append("읽기 도구가 필요한 작업")
        else:
            engine = "economy"
            reason.append("단순 텍스트는 전체 CLI 문맥 없이 직접 API")
        model = {"local": "code", "economy": "codex/gpt-6-luna", "codex": "auto-fallback",
                 "codex_native": "gpt-6.1-sol", "codex_artifact": "codex/gpt-6-luna", "claude": "opus", "blocked": "none"}[engine]
        assignment_id = None
        # 보드에서 확정한 부서 진행 담당. 사용자가 담당을 직접 고른 요청과 코드 처리(local)에는 쓰지 않는다.
        if assigned and requested == "auto" and engine != "local" and assigned.get("engine") not in (None, "auto"):
            blocked = self.assignment_block(assigned["engine"], kind, images, parent)
            if blocked:
                reason.insert(0, f"부서 진행 담당({assigned['id']}) 미적용: {blocked}")
            else:
                reason = [f"기존 규칙이었다면 {engine}"]
                engine, assignment_id = assigned["engine"], assigned["id"]
                fixed = {"economy": "codex/gpt-6-luna", "codex": "auto-fallback", "codex_native": "gpt-6.1-sol"}
                model = assigned.get("model") or "opus" if engine == "claude" else fixed[engine]
                reason.insert(0, f"부서 진행 담당 배정({assigned['id']}) 적용")
        if not self.available("claude_native"):
            reason.append("Claude native 제외: " + self.health("claude_native")["state"])
        return {"engine": engine, "model": model, "assignment_id": assignment_id,
                "reason": "; ".join(reason), "policy_version": VERSION, "contract": contract}


def validate_result(text, contract, evidence):
    """Deterministic contract checks; these do not certify factual correctness."""
    errors = []
    if not text.strip():
        errors.append("결과 본문이 비어 있음")
    if len(text) > 100000:
        errors.append("결과 크기 상한 초과")
    checks = contract.get("checks", {})
    for term in checks.get("contains", []):
        if term.casefold() not in text.casefold():
            errors.append("필수 내용 누락: " + term)
    if checks.get("format") == "json":
        import json
        try:
            json.loads(text)
        except ValueError:
            errors.append("유효한 JSON이 아님")
    if len(text) < checks.get("min_chars", 1):
        errors.append("본문 길이 조건 미달")
    required = contract.get("required_reads", [])
    for name in required:
        if name not in evidence.get("read_files", []):
            errors.append("첨부 읽기 근거 없음: " + name)
    if evidence.get("failed_tools") and not evidence.get("successful_tools"):
        errors.append("도구 실행이 모두 실패함")
    return errors
