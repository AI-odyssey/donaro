"""GR 판정 하네스: 고객 용어·신호어·첨부 본문·부서 규칙 순서 우회를 단언한다. 고객사명은 출력하지 않는다."""
import json, sys, tempfile, zipfile
from pathlib import Path
import orchestrator as orch

terms = orch.gr_terms()
assert len(terms) >= 10, "GR 용어 목록이 비었다(비공개 용어 파일 확인)"
sample = next(t for t in terms if t.isascii() and len(t) > 4)
assert orch.is_gr(None, f"{sample.upper()} 미팅 메모 정리"), "고객 용어(대문자) 미탐지"
assert orch.is_gr("40", "GR 모니터링 자동화 코드 고쳐줘"), "부서 규칙(40 우선) 우회"
assert orch.is_gr(None, "국회 법안 동향"), "GR 신호어 미탐지"
assert not orch.is_gr("40", "도나로 서버 재시작"), "개발 요청 오탐"
assert not orch.is_gr(None, "오늘 저녁 메뉴 추천"), "일상 요청 오탐"
for kind in ("plan", "text", "review", "synthesize"):
    chain = orch.chain_for(kind, lambda h: True, gr=True)
    assert chain and all(e["app"] == "claude" for e in chain), f"GR {kind} 사슬에 Claude 외 모델"
# 첨부 본문 검사(server.attachment_text와 같은 규칙)
src = Path("server.py").read_text(encoding="utf-8")
ns = {}
exec("import re\nfrom pathlib import Path\nUPLOADS=Path('.')\n" + src[src.index("def attachment_text"):src.index("# ---------- 목소리 ----------")], ns)
with tempfile.TemporaryDirectory() as d:
    txt = Path(d) / "memo.txt"; txt.write_text(f"내일 {sample} 콜 준비", encoding="utf-8")
    docx = Path(d) / "a.docx"
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml", f"<w:t>{sample}</w:t>")
    assert orch.is_gr(None, "이 파일 요약해줘", str(txt), ns["attachment_text"](str(txt))), "첨부 txt 본문 미탐지"
    assert orch.is_gr(None, "요약", str(docx), ns["attachment_text"](str(docx))), "첨부 docx 본문 미탐지"
print("PASS: GR 용어·신호어·부서 우회·첨부 본문·Claude 전용 사슬")
