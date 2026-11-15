// 통합 자비스 업무보드. 서버가 끼워 준 데이터(window.__BOARD__)만 그린다.
// data-* 속성은 261104_실시간음성비서/harness_board.py가 데이터와 전수 대조하는 기준이라 지우지 않는다.
import { useEffect, useMemo, useRef, useState } from "react"
import { Background, BackgroundVariant, Controls, getBezierPath, getSmoothStepPath, Handle, Position, ReactFlow, type EdgeProps, type NodeProps } from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import { ArrowRight, CornerDownRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { cn } from "@/lib/utils"
import Chat from "./Chat"

/* eslint-disable @typescript-eslint/no-explicit-any */
type Any = any
const D: Any = (window as Any).__BOARD__ || {}
// 2안(노선도)이 기본(11/13 대표님 결정). 1안은 /board?v=1. 같은 데이터·같은 data-* 속성을 다른 조형으로 그린다. AI 앱 하나가 노선 하나다.
const V2 = new URLSearchParams(location.search).get("v") !== "1"
const LINE: Record<string, string> = { claude: "#D9623B", codex: "var(--foreground)", gemini: "#2F6BFF", copilot: "#7A4DE8", grok: "#0E9F6E", local: "#8A8A8A" }
const lineOf = (app?: string) => LINE[app || ""] || "var(--muted-foreground)"

const ENGINE: Record<string, string> = { auto: "자동(기존 규칙)", claude: "Claude Code", codex: "Codex · OmniRoute", codex_native: "Codex 고성능", economy: "경량 API", local: "로컬 코드", codex_artifact: "경량 API 파일 작성", blocked: "실행 불가", orchestrator: "오케스트레이터", api: "OmniRoute API" }
const APPS: [string, string][] = [["claude", "Claude Code"], ["codex", "Codex"], ["gemini", "Gemini"], ["copilot", "GitHub Copilot"], ["grok", "Grok"], ["local", "로컬 코드"]]
const KIND: Record<string, string> = { plan: "계획", text: "짧은 답", draft: "긴 글", research: "자료 확인", deep_research: "심층 확인", analysis: "분석", code: "코드", review: "검수", synthesize: "종합", sub: "실행", repair: "수정", recheck: "재검수" }
const STATE: Record<string, [string, Tone]> = { ready: ["사용 가능", "ok"], unknown: ["미확인", "idle"], quota: ["한도 소진", "bad"], rate_limit: ["속도 제한", "warn"], unavailable: ["장애", "bad"], auth: ["인증 필요", "bad"] }
// 부서 목록 묶음(성격별)과 묶음 점 색. 노선도의 AI 앱 색과 겹치지 않는 톤을 쓴다
const DEPT_GROUPS: [string, string[], string][] = [["사업", ["10", "30"], "#BA7517"], ["연구·학습", ["20", "70"], "#D4537E"], ["협조 부서", ["40", "50", "60"], "#1D9E75"], ["운영·개인", ["01", "80"], "#888780"], ["기타", [], "#B4B2A9"]]
const STATUS: Record<string, string> = { done: "완료", running: "진행", queued: "대기", waiting: "한도 대기", error: "실패", needs_input: "확인 필요", needs_reconciliation: "변경 확인", cancelled: "취소", failed: "실패", pending: "대기" }
type Tone = "ok" | "warn" | "bad" | "idle"

const k = (n: number) => (n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n || 0))
const hm = (t: number) => new Date(t * 1000).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false })
const ago = (t: number) => { const s = Math.max(0, (D.server_time || Date.now() / 1000) - t); return s < 60 ? "방금" : s < 3600 ? Math.floor(s / 60) + "분 전" : s < 86400 ? Math.floor(s / 3600) + "시간 전" : Math.floor(s / 86400) + "일 전" }
const executionSteps = (o: Any): Any[] => o?.mode === "delegated" ? (o.executor ? [o.executor] : []) : (o?.subtasks || [])
const steps = (o: Any): Any[] => (o ? [o.planner, ...executionSteps(o), o.synthesis, o.review, o.repair, o.recheck].filter(Boolean) : [])
// 실행한 AI 앱. 오케스트레이션 작업은 단계마다 실제로 실행한 앱에 붙는다(구조=화면의 기준).
const appOf = (r: Any) => { const m = String(r.model || "").toLowerCase(); return m.includes("gemini") ? "gemini" : m.includes("grok") ? "grok" : m.includes("github") || m.includes("mai-") ? "copilot" : r.engine === "claude" ? "claude" : r.engine === "local" ? "local" : "codex" }
const runTone = (r: Any): Tone => (r.status === "done" ? "ok" : ["running", "queued", "waiting"].includes(r.status) ? "warn" : ["error", "needs_input", "needs_reconciliation"].includes(r.status) ? "bad" : "idle")
const stepTone = (s: string): Tone => (s === "done" ? "ok" : s === "running" ? "warn" : ["failed", "needs_input"].includes(s) ? "bad" : "idle")
const DOT: Record<Tone, string> = { ok: "bg-ok", warn: "bg-warn", bad: "bg-bad", idle: "bg-muted-foreground/40" }

function Dot({ tone, className }: { tone: Tone; className?: string }) { return <i aria-hidden className={cn("inline-block size-1.5 shrink-0 rounded-full", DOT[tone], className)} /> }
function Status({ tone, children, className }: { tone: Tone; children: React.ReactNode; className?: string }) {
  return <span className={cn("badge inline-flex shrink-0 items-center gap-1.5 text-xs whitespace-nowrap text-muted-foreground", className)}><Dot tone={tone} />{children}</span>
}
function Logo({ app, className }: { app: string; className?: string }) {
  const l = (D.service_logos || {})[app]
  return l ? <img alt="" src={l.uri} className={cn("size-4 shrink-0 object-contain", app === "codex" && "rounded-[3px] bg-neutral-900 p-px", className)} /> : <span aria-hidden className={cn("grid size-4 shrink-0 place-items-center rounded-[3px] border text-[11px] leading-none font-semibold", className)}>{"{}"}</span>
}
function Section({ title, aside, children, className, ...rest }: { title: string; aside?: React.ReactNode; children: React.ReactNode; className?: string } & React.ComponentProps<"section">) {
  return <section className={cn("min-w-0", className)} {...rest}>
    <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1"><h2 className="text-[13px] font-semibold">{title}</h2>{aside && <div className="text-xs text-muted-foreground">{aside}</div>}</div>
    {children}
  </section>
}

async function post(body: Any) {
  const r = await fetch("/api/board", { method: "POST", headers: { "Content-Type": "text/plain;charset=UTF-8" }, body: JSON.stringify({ ...body, token: D.board_token }) })
  const j = await r.json().catch(() => ({ error: "응답을 읽지 못했습니다." }))
  if (!r.ok || j.error) throw new Error(j.error || r.status)
  return j
}

function useNarrow() {
  const q = "(max-width: 760px)"
  const [narrow, set] = useState(() => matchMedia(q).matches)
  useEffect(() => { const m = matchMedia(q), f = () => set(m.matches); m.addEventListener("change", f); return () => m.removeEventListener("change", f) }, [])
  return narrow
}

// ---------- 실행 그래프 ----------
const NODE_W = 156, NODE_H = 96
const STEP_STATE: Record<string, string> = { done: "완료", running: "진행", failed: "실패", needs_input: "확인 필요", pending: "대기", cancelled: "취소" }
function StepNode({ data }: NodeProps) {
  const { s, run, lane, vertical } = data as Any
  const st = s.status || "pending", tries = s.tries || [], deliver = s.id === "deliver"
  const [open, setOpen] = useState(false)
  return <div data-step={`${run.id}:${s.id}`} data-status={st} data-model={s.model || ""} data-lane={lane} data-open={open ? "1" : "0"} style={{ width: NODE_W }} onClick={() => setOpen(o => !o)}
    className={cn("cursor-pointer rounded-md border bg-card px-2.5 py-2 text-card-foreground", st === "running" && "border-warn", ["failed", "needs_input"].includes(st) && "border-bad")}>
    <Handle type="target" position={vertical ? Position.Top : Position.Left} />
    <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground"><span>{deliver ? "" : lane === "repair" ? "수정" : KIND[s.kind] || KIND[lane] || ""}</span><Dot tone={stepTone(st)} /></div>
    <div className="mt-0.5 line-clamp-2 text-[12.5px] leading-snug font-medium">{deliver ? "결과물" : s.title || s.id}</div>
    {deliver
      ? <div className="mt-1 text-[11px] break-all text-muted-foreground">{(run.files || []).length ? run.files.map((f: string) => f.split("/").pop()).join(", ") : "대기 중"}</div>
      : !open ? <div data-step-state className="mt-1 text-[11px] text-muted-foreground">{STEP_STATE[st] || st}</div> : <>
        <div className="mt-1.5 flex items-center gap-1.5 text-xs">{s.app && <Logo app={s.app} className="size-3.5" />}<span className="min-w-0">{s.label || (s.chain ? "배정 대기" : "—")}</span></div>
        <div className="mt-1 text-[11px] text-muted-foreground tabular-nums">{s.usage ? `${k(s.usage.input)} → ${k(s.usage.output)} 토큰` : "토큰 —"}{s.finished && s.started ? ` · ${Math.round(s.finished - s.started)}초` : ""}</div>
        {tries.length > 0 && <div className="mt-1 text-[11px] text-foreground" title={tries.map((t: Any) => t.model + ": " + t.error).join("\n")}>대체 {tries.length}회 ({tries.map((t: Any) => t.model + (t.quota ? " 한도" : " 장애")).join(", ")})</div>}
        {s.verdict && <div className="mt-1 text-[11px] text-muted-foreground">{s.verdict.pass ? "통과" : `보완 ${s.verdict.issues.length}건`}</div>}
      </>}
    <Handle type="source" position={vertical ? Position.Bottom : Position.Right} />
  </div>
}
function DepEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition }: EdgeProps) {
  const [d] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })
  return <path data-edge={id} d={d} fill="none" strokeWidth={1.25} className="stroke-muted-foreground/45" />
}
function StationNode({ data }: NodeProps) {
  const { s, run, lane, vertical } = data as Any
  const st = s.status || "pending", deliver = s.id === "deliver", bad = ["failed", "needs_input"].includes(st)
  const color = deliver ? "var(--foreground)" : st === "pending" ? "var(--border)" : lineOf(s.app)
  const dot = <span className={cn("station-dot", deliver && "is-terminal", st === "running" && "is-running")} style={{ borderColor: bad ? "var(--bad)" : color }} />
  const kind = deliver ? "" : lane === "repair" ? "수정" : KIND[s.kind] || KIND[lane] || ""
  const title = deliver ? "결과물" : s.title || s.id
  let meta = deliver ? ((run.files || []).length ? run.files.map((f: string) => f.split("/").pop()).join(", ") : "대기 중")
    : `${s.usage ? `${k(s.usage.input)} → ${k(s.usage.output)}` : "토큰 —"}${s.finished && s.started ? ` · ${Math.round(s.finished - s.started)}초` : ""}${(s.tries || []).length ? ` · 대체 ${s.tries.length}` : ""}${s.verdict ? (s.verdict.pass ? " · 통과" : ` · 보완 ${s.verdict.issues.length}`) : ""}`
  // 기본은 단계 이름과 상태만. 엔진·토큰·시간은 눌렀을 때만(11/16 대표님 확인)
  const [open, setOpen] = useState(false)
  const stText = <span data-step-state className="text-xs text-muted-foreground">{STEP_STATE[st] || st}</span>
  const model = !deliver && (open ? <span className="inline-flex max-w-full items-center gap-1 text-xs font-medium">{s.app && <Logo app={s.app} className="size-3.5" />}<span className="truncate">{s.label || (s.chain ? "배정 대기" : "—")}</span></span> : stText)
  if (!deliver && !open) meta = ""
  const attrs = { "data-step": `${run.id}:${s.id}`, "data-status": st, "data-model": s.model || "", "data-lane": lane, "data-open": open ? "1" : "0", style: { width: NODE_W, height: NODE_H },
    role: deliver ? undefined : "button", title: deliver ? undefined : open ? "눌러서 접기" : "눌러서 담당 AI·토큰 보기", onClick: deliver ? undefined : () => setOpen(o => !o) }
  if (vertical) return <div {...attrs} className={cn("relative flex flex-col justify-center pl-9", !deliver && "cursor-pointer")}>
    <Handle type="target" position={Position.Top} style={{ left: 14 }} />
    <span className="absolute inset-y-0 left-[11px] w-1.5" style={{ background: color }} /><span className="absolute top-1/2 left-[5px] -translate-y-1/2">{dot}</span>
    <span className="text-[11px] text-muted-foreground">{kind}</span><span className="line-clamp-1 text-[13px] leading-snug font-bold">{title}</span>{model}<span className="truncate text-[11px] text-muted-foreground tabular-nums">{meta}</span>
    <Handle type="source" position={Position.Bottom} style={{ left: 14 }} />
  </div>
  return <div {...attrs} className={cn("relative flex flex-col text-center", !deliver && "cursor-pointer")}>
    <Handle type="target" position={Position.Left} />
    <div className="flex h-[41px] flex-col justify-end px-1 pb-1.5"><span className="text-[11px] text-muted-foreground">{kind}</span><span className="line-clamp-1 text-[13px] leading-snug font-bold">{title}</span></div>
    <div className="relative h-[14px]"><span className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2" style={{ background: color }} /><span className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2">{dot}</span></div>
    <div className="flex h-[41px] flex-col items-center px-1 pt-1.5">{model}<span className="max-w-full truncate text-[11px] text-muted-foreground tabular-nums">{meta}</span></div>
    <Handle type="source" position={Position.Right} />
  </div>
}
function LineEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data }: EdgeProps) {
  const [d] = getSmoothStepPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, borderRadius: 18 })
  const { color, pending } = (data || {}) as Any
  return <path data-edge={id} d={d} fill="none" stroke={pending ? "var(--border)" : color} strokeWidth={6} strokeLinecap="round" pathLength={1} className="line-edge" />
}
const nodeTypes = { step: V2 ? StationNode : StepNode }, edgeTypes = { dep: V2 ? LineEdge : DepEdge }

function buildGraph(r: Any, vertical: boolean) {
  const o = r.orchestration, subs: Any[] = executionSteps(o)
  const waves: Any[][] = [], done = new Set<string>(); let left = [...subs]
  while (left.length) { const w = left.filter(s => (s.depends_on || []).every((d: string) => done.has(d))); if (!w.length) break; waves.push(w); w.forEach(s => done.add(s.id)); left = left.filter(s => !done.has(s.id)) }
  const lanes: [Any[], string][] = []
  waves.forEach(w => lanes.push([w, "sub"]))
  if (o.synthesis) lanes.push([[o.synthesis], "synthesize"])
  if (o.review) lanes.push([[o.review], "review"])
  if (o.repair) lanes.push([[o.repair], "repair"])
  if (o.recheck) lanes.push([[o.recheck], "recheck"])
  lanes.push([[{ id: "deliver", status: r.status === "done" ? "done" : "pending" }], "deliver"])
  const gx = vertical ? 10 : 24, gy = vertical ? 30 : V2 ? 34 : 12
  const nodes = lanes.flatMap(([ss, lane], i) => ss.map((s, j) => {
    const off = j - (ss.length - 1) / 2
    return { id: s.id, type: "step", data: { s, run: r, lane, vertical }, position: vertical ? { x: off * (NODE_W + gx), y: i * (NODE_H + gy) } : { x: i * (NODE_W + gx), y: off * (NODE_H + gy) } }
  }))
  // 의존 관계를 그대로 선으로 잇는다. 서브 업무는 depends_on, 그 외는 앞 단계 전체 → 다음 단계.
  const subIds = new Set(subs.map(s => s.id)), ids = lanes.map(([ss]) => ss.map(s => s.id)), pairs: [string, string][] = []
  lanes.forEach(([ss], i) => ss.forEach(s => {
    if (subIds.has(s.id) && (s.depends_on || []).length) s.depends_on.forEach((d: string) => pairs.push([d, s.id]))
    else if (i > 0) ids[i - 1].filter(p => !subIds.has(p) || !subs.some(x => (x.depends_on || []).includes(p)) || !subIds.has(s.id)).forEach(p => pairs.push([p, s.id]))
  }))
  const seen = new Set<string>(), byId: Record<string, Any> = Object.fromEntries(lanes.flatMap(([ss]) => ss).map(s => [s.id, s]))
  const edges = pairs.filter(([a, b]) => !seen.has(a + ">" + b) && seen.add(a + ">" + b)).map(([a, b]) => ({ id: `${a}>${b}`, source: a, target: b, type: "dep", data: { color: lineOf(byId[a]?.app), pending: (byId[b]?.status || "pending") === "pending" } }))
  const tall = Math.max(...lanes.map(([ss]) => ss.length))
  return { nodes, edges, height: vertical ? lanes.length * (NODE_H + gy) + 24 : tall * (NODE_H + gy) + 40 }
}

function Graph({ run, narrow }: { run: Any; narrow: boolean }) {
  const g = useMemo(() => buildGraph(run, narrow), [run, narrow])
  return <div style={{ height: g.height }} className="w-full">
    <ReactFlow key={`${run.id}-${narrow}`} nodes={g.nodes} edges={g.edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} colorMode="system" proOptions={{ hideAttribution: true }} onNodeClick={() => { /* 노드가 눌리게(펼치기는 노드가 처리) */ }} fitView fitViewOptions={{ padding: 0.04 }} minZoom={0.5} maxZoom={1}
      nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} panOnDrag={!narrow} zoomOnScroll={false} zoomOnPinch={!narrow} zoomOnDoubleClick={false} preventScrolling={false}>
      {V2 && <Background variant={BackgroundVariant.Dots} gap={18} size={1.2} color="var(--border)" />}
      {!narrow && <Controls showInteractive={false} position="bottom-right" />}
    </ReactFlow>
  </div>
}

// ---------- 제어 ----------
// 되돌리기 어려운 동작은 한 번 더 묻는다. 보드는 sandbox라 window.confirm을 못 쓰므로 버튼 자리에서 확인한다
function Confirm({ label, ask, run, attr }: { label: string; ask: string; run: () => Promise<string | void>; attr: Record<string, string> }) {
  const [stage, setStage] = useState<"idle" | "ask" | "busy">("idle"), [msg, setMsg] = useState("")
  const go = async () => { setStage("busy"); try { setMsg((await run()) || "") } catch (err: Any) { setMsg("실패: " + err.message) } setStage("idle") }
  return <span className="inline-flex shrink-0 items-center gap-1.5 text-xs">
    {stage === "ask" ? <><span className="text-muted-foreground">{ask}</span><Button size="sm" variant="destructive" className="h-6 px-2 text-xs" data-confirm-yes onClick={go}>예</Button><Button size="sm" variant="ghost" className="h-6 px-2 text-xs" onClick={() => setStage("idle")}>아니오</Button></>
      : <Button {...attr} size="sm" variant="outline" className="h-6 px-2 text-xs" disabled={stage === "busy"} onClick={() => { setMsg(""); setStage("ask") }}>{stage === "busy" ? "처리 중…" : label}</Button>}
    {msg && <span className="text-muted-foreground" aria-live="polite">{msg}</span>}
  </span>
}
const SCHED_NAME: Record<string, string> = { HQ_git_backup: "GitHub 백업", HQ_guideline_notion_sync: "노션 지침 사본", SkillWatch: "스킬 점검", PP_English_Quiz: "영어 퀴즈" }
// 처리 칸: 라우터 이름 대신 지금 상태를 말로(진행 중이면 '검수 중'처럼 단계 이름)
const procText = (r: Any) => {
  if (ACTIVE_S.includes(r.status)) { const st = r.orchestration ? steps(r.orchestration).find(x => x.status === "running") : null
    return st ? `${KIND[st.kind] || "작업"} 중` : r.status === "waiting" ? "한도 대기" : "진행 중" }
  return STATUS[r.status] || r.status
}
const ACTIVE_S = ["running", "queued", "waiting"]
const sec = (n: number) => (n < 60 ? `${n}초` : n < 3600 ? `${Math.floor(n / 60)}분 ${n % 60}초` : `${Math.floor(n / 3600)}시간 ${Math.floor((n % 3600) / 60)}분`)
const ACTIVE = ["running", "queued", "waiting"], RETRYABLE = ["error", "cancelled", "needs_input", "needs_reconciliation", "failed"]

// ---------- 담당 편집 ----------
function RoleBox({ a, role, onSaved }: { a: Any; role: string; onSaved: (x: Any) => void }) {
  const [note, setNote] = useState<[string, boolean] | null>(null), [busy, setBusy] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  async function save() { // 보드는 sandbox(allow-forms 없음)로 열려 form 제출이 막힌다. 버튼 클릭으로 직접 읽는다
    const q = (n: string) => box.current!.querySelector<HTMLInputElement | HTMLSelectElement>(`[name=${n}]`)!
    const engine = q("engine").value, model = q("model").value || null, active = (q("state") as HTMLInputElement).checked
    if (model && engine !== "claude") return setNote(["모델은 Claude Code를 고를 때만 정할 수 있습니다.", false])
    setBusy(true); setNote(["저장 중…", true])
    try {
      const j = await post({ op: "assignment", id: a.id, engine, model, state: active ? "active" : "proposed" })
      onSaved(j.assignment)
      setNote(["저장됨 · " + (role === "execute" ? (j.assignment.state === "active" ? "다음 요청부터 라우터가 따릅니다." : "제안 상태라 라우터는 기존 규칙을 씁니다.") : "검수 기록에 반영했습니다."), true])
    } catch (err: Any) { setNote(["저장 실패: " + err.message, false]) }
    setBusy(false)
  }
  const engines = Object.entries(ENGINE).filter(([x]) => !["codex_artifact", "blocked", "orchestrator", "api"].includes(x))
  return <div ref={box} className="role min-w-0 flex-1 basis-64" data-asg={a.id} key={`${a.id}-${a.updated_at}`}>
    <div className="flex items-center gap-2"><h3 className="text-[13px] font-semibold">{role === "execute" ? "진행 담당" : "검수 담당"}</h3><Status tone={a.state === "active" ? "ok" : "idle"}>{a.state === "active" ? "확정" : "배정 대기"}</Status></div>
    <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{a.responsibility ? a.responsibility + ". " : ""}{role === "execute" ? "확정하면 라우터와 오케스트레이터가 이 담당을 맨 앞 순서에 둡니다." : "복합 업무 검수는 가능하면 만든 쪽과 다른 AI가 맡고, 이 칸은 부서 QC 기록입니다."}</p>
    <div className="mt-2.5 flex flex-wrap items-center gap-2">
      <NativeSelect name="engine" size="sm" defaultValue={a.engine} aria-label="담당">{engines.map(([x, v]) => <NativeSelectOption key={x} value={x}>{v}</NativeSelectOption>)}</NativeSelect>
      <NativeSelect name="model" size="sm" defaultValue={a.model || ""} aria-label="모델"><NativeSelectOption value="">기본 모델</NativeSelectOption><NativeSelectOption value="sonnet">sonnet</NativeSelectOption><NativeSelectOption value="opus">opus</NativeSelectOption></NativeSelect>
      <label className="flex items-center gap-1.5 text-[13px]"><input type="checkbox" name="state" defaultChecked={a.state === "active"} className="size-4 accent-primary" />확정</label>
      <Button type="button" size="sm" data-save disabled={busy} onClick={save}>저장</Button>
    </div>
    <div className={cn("note mt-1.5 min-h-4 text-xs", note && !note[1] ? "text-bad" : "text-muted-foreground")} aria-live="polite">{note?.[0]}</div>
  </div>
}

// ---------- 화면 ----------
function Board() {
  const narrow = useNarrow()
  const [asg, setAsg] = useState<Any[]>(D.assignments || [])
  const [runsAll, setRuns] = useState<Any[]>(() => (D.runs || []).slice().reverse())
  const runs = runsAll.filter(r => r.source !== "harness"), harnessRuns = runsAll.filter(r => r.source === "harness")  // 자동 시험 작업은 운영 상세에서만
  const [act, setAct] = useState<Any>(D.activity || { sessions: D.sessions || [], services: [], scheduled: [] })
  const [usageDays, setUsageDays] = useState<Any[]>(D.usage_days || [])
  const [, setTick] = useState(0)
  const depts: Any[] = D.departments || [], sessions: Any[] = act.sessions || [], models: Any[] = D.models || []
  const modelById = useMemo(() => Object.fromEntries(models.map(m => [m.id, m])), [models])
  const allOrchRuns = runs.filter(r => r.orchestration)
  const [selDept, setSelDept] = useState<string | null>(null), [selApp, setSelApp] = useState("claude"), [more, setMore] = useState<Record<string, boolean>>({})
  const [selRun, setSelRun] = useState<number | undefined>(() => (allOrchRuns.find(r => ["running", "queued"].includes(r.status)) || allOrchRuns[0] || {}).id)
  const [pv, setPv] = useState(""), [pvOut, setPvOut] = useState<Any>(null)
  const graphRef = useRef<HTMLDivElement>(null)
  async function refresh() {  // 실행 기록·외부 활동·사용량을 새로 받는다(보드 토큰 경로라 /board·/app 공통)
    const j = await post({ op: "live" })
    D.server_time = j.server_time
    setRuns(j.runs.slice().reverse()); setAct(j.activity); setUsageDays(j.usage); setTick(x => x + 1)
  }
  useEffect(() => {  // 5초마다 새로 받는다. 화면이 가려져 있으면 쉰다
    const id = setInterval(() => { if (!document.hidden) refresh().catch(() => { /* 다음 주기에 다시 받는다 */ }) }, 5000)
    refresh().catch(() => {})
    return () => clearInterval(id)
  }, [])
  const liveRow = (r: Any) => <li key={r.id} data-live-run={r.id} data-status={r.status} className="flex flex-wrap items-start gap-x-3 gap-y-1 py-2">
    <span className="w-10 shrink-0 text-muted-foreground tabular-nums">#{r.id}</span>
    <div className="min-w-0 flex-1 basis-60">
      <div className="truncate font-medium">{r.request}</div>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground"><Status tone={runTone(r)}>{STATUS[r.status] || r.status}</Status>{ACTIVE.includes(r.status) && <span data-live-step>{r.step || "단계 준비 중"}</span>}<span data-live-elapsed className="tabular-nums">{sec(r.elapsed || 0)}{ACTIVE.includes(r.status) ? " 경과" : " 걸림"}</span></div>
      {r.last_output && <p data-live-output className="mt-1 line-clamp-2 text-xs text-muted-foreground">{r.last_output}</p>}
    </div>
    {ACTIVE.includes(r.status) ? <Confirm key={"c" + r.id} label="취소" ask={`#${r.id}을 취소할까요?`} run={() => cancelRun(r.id)} attr={{ "data-cancel": String(r.id) }} />
      : RETRYABLE.includes(r.status) && <Confirm key={"r" + r.id} label="재시도" ask="다시 실행할까요?" run={() => retryRun(r.id)} attr={{ "data-retry": String(r.id) }} />}
  </li>
  const cancelRun = async (id: number) => { await post({ op: "cancel", run_id: id }); await refresh(); return "취소했습니다." }
  const retryRun = async (id: number) => { const j = await post({ op: "retry", run_id: id }); await refresh(); return j.duplicate ? `이미 #${j.task_id}로 접수됨` : `#${j.task_id}로 다시 접수` }
  const restart = async (svc: string) => { const j = await post({ op: "restart", service: svc }); setTimeout(() => refresh().catch(() => {}), 3000); return j.message }

  const deptName = (id: string | null) => (id === "00" ? "비서실" : (depts.find(d => d.id === id) || {}).name || "미분류")
  const inDept = (x: Any) => !selDept || x.department_id === selDept
  const scopedRuns = runs.filter(inDept), orchRuns = allOrchRuns.filter(inDept)
  const asgOf = (d: string, role: string) => asg.find(a => a.department_id === d && a.role_id === role) || {}
  const engineText = (a: Any) => (a.engine ? ENGINE[a.engine] + (a.model ? " · " + a.model : "") : "없음")
  const placements = runs.flatMap(r => r.orchestration ? steps(r.orchestration).filter(s => s.app).map(s => ({ run: r, step: s, app: s.app })) : r.engine === "orchestrator" ? [] : [{ run: r, step: null as Any, app: appOf(r) }])

  // 상단 수치
  const count = (s: string) => scopedRuns.filter(r => r.status === s).length
  const today = new Date((D.server_time || 0) * 1000).toDateString()
  const tok = scopedRuns.filter(r => new Date(r.started * 1000).toDateString() === today).reduce((a, r) => a + (r.usage?.input_tokens || 0) + (r.usage?.output_tokens || 0), 0)
  const nowT = D.server_time || Date.now() / 1000
  const recent = (r: Any) => nowT - r.started <= 3 * 86400 // 3일 지난 확인 필요는 집계에서 뺀다
  const doneAt = (r: Any) => new Date((r.finished || r.started) * 1000).toDateString()
  const mine = scopedRuns
  const needs = mine.filter(r => ["needs_input", "needs_reconciliation"].includes(r.status) && recent(r))  // 상단과 숫자줄이 같은 기준
  const attn: [string, Any[], Tone][] = [
    ["확인 필요", needs, "bad"],
    ["오늘 완료", mine.filter(r => r.status === "done" && doneAt(r) === today), "ok"],
    ["막힘", mine.filter(r => ["error", "waiting"].includes(r.status)), "warn"]]
  const stats: [string, string | number, Tone | null][] = [["진행", count("running") + count("queued") + count("waiting"), "warn"], ["완료", count("done"), "ok"], ["확인 필요", needs.length, "bad"]]
  const live = asg.filter(a => a.role_id === "execute" && a.state === "active").length
  const fb = orchRuns.reduce((a, r) => a + steps(r.orchestration).filter(s => (s.tries || []).length).length, 0)
  const flow: [string, string, string][] = [["요청", "웹·음성·Siri 공통 입구", `${runs.length}건 기록`], ["부서 분류", "단어 규칙, 보드 수정", `${runs.filter(r => r.department_id).length}건 분류 · 확정 담당 ${live}/9`],
    ["계획", "최상위 모델이 업무 분해", `${orchRuns.filter(r => r.orchestration.planner).length}건 계획`], ["서브 업무 실행", "종류별 대체 순서", `대체 ${fb}회`],
    ["종합·독립 검수", "만든 AI와 다른 AI", `${orchRuns.filter(r => r.orchestration.review?.status === "done").length}건 검수`], ["레드팀", "대외 문서만 건별 구성", "상시 조직 아님"], ["전달", "휴대폰·PC 결과 파일", `${count("done")}건 완료`]]

  const run = orchRuns.find(r => r.id === selRun) || orchRuns.find(r => ["running", "queued"].includes(r.status)) || orchRuns[0]
  const o = run?.orchestration
  const out = steps(o).reduce((a, s) => a + (s.usage?.output || 0), 0)
  const pick = (id: number) => { setSelRun(id); graphRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }) }

  async function preview() {
    const text = pv.trim()
    if (!text) return setPvOut({ msg: "문장을 넣어 주세요." })
    setPvOut({ msg: "확인 중…" })
    try { setPvOut(await post({ op: "preview", text })) } catch (err: Any) { setPvOut({ msg: "실패: " + err.message }) }
  }
  async function setRunDept(r: Any, department_id: string) {
    try { const j = await post({ op: "run_department", run_id: r.id, department_id: department_id || null }); setRuns(rs => rs.map(x => (x.id === r.id ? { ...x, ...j.run } : x))) }
    catch (err: Any) { setPvOut({ msg: "부서 저장 실패: " + err.message }) }
  }

  const logAll = runs.filter(inDept), logRows = logAll.slice(0, more.log ? 99 : 12)
  const appSessions = (a: string) => sessions.filter(s => s.app === a && inDept(s) && s.origin !== "donaro")
  const appWork = (a: string) => placements.filter(p => p.app === a && inDept(p.run))
  const ss = appSessions(selApp), pl = appWork(selApp)
  const okModel = (id: string) => ["ready", "unknown"].includes((modelById[id] || {}).state)
  const dept = depts.find(d => d.id === selDept)

  return <div className={cn("@container mx-auto max-w-[1280px] px-4 pb-16 sm:px-6", V2 && "v2")}>
    <header className={cn("flex flex-wrap gap-x-6 gap-y-3", V2 ? "items-end border-b-4 border-foreground pt-8 pb-4" : "items-center border-b py-3")}>
      <div className="min-w-0">
        {V2 ? <h1 className="text-[34px] leading-none font-black tracking-tight sm:text-5xl">통합 자비스<span className="font-light text-muted-foreground"> 업무보드</span></h1>
          : <h1 className="text-[15px] font-semibold">통합 자비스 업무보드</h1>}
        <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground"><Dot tone="ok" />서버 동작 중 · {new Date((D.server_time || 0) * 1000).toLocaleString("ko-KR", { hour12: false })}</p>
        {V2 && <p className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs">{APPS.filter(([id]) => id !== "local").map(([id, name]) => <span key={id} className="inline-flex items-center gap-1.5"><i className="block h-1.5 w-5 rounded-full" style={{ background: lineOf(id) }} />{name}</span>)}</p>}
      </div>

    </header>



    <section data-attention aria-label="대표님이 볼 것" className="grid grid-cols-1 gap-x-8 gap-y-3 border-b py-3 sm:grid-cols-3">
      {attn.map(([n, rs, tone]) => <div key={n} data-attn={n} className="min-w-0">
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground"><Dot tone={tone} />{n}<span className="ml-1 text-base font-bold text-foreground tabular-nums">{rs.length}</span></div>
        <ul className="mt-1 space-y-0.5 text-[13px]">{rs.slice(0, 2).map(r => <li key={r.id}><button data-attn-pick={r.id} onClick={() => pick(r.id)} className="block w-full truncate text-left hover:underline"><span className="mr-1.5 text-muted-foreground tabular-nums">#{r.id}</span>{String(r.request || "").slice(0, 30)}</button></li>)}
          {!rs.length && <li className="text-xs text-muted-foreground">없음</li>}</ul>
      </div>)}
    </section>

    <section data-live aria-label="지금 진행" className="border-b py-3">
      <h2 className="text-[13px] font-semibold">지금 진행 <span className="font-normal text-muted-foreground">· 5초마다 갱신</span></h2>
      {(() => { const live = runs.filter(r => ACTIVE.includes(r.status))
        return live.length ? <ul className="mt-1.5 divide-y text-[13px]">{live.map(liveRow)}</ul> : <p className="mt-1 text-xs text-muted-foreground">진행 중인 도나로 작업이 없습니다.</p> })()}
    </section>

    <section data-external aria-label="외부 활동" className="grid grid-cols-1 gap-x-8 gap-y-4 border-b py-3 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <div className="min-w-0">
        <h2 className="text-[13px] font-semibold">외부 활동 <span className="font-normal text-muted-foreground">· 다른 곳에서 한 AI 작업 (최근 7일)</span></h2>
        <ul className="mt-1.5 divide-y text-[13px]">{sessions.filter(s => s.origin === "user").slice(0, more.ext ? 40 : 8).map(s => <li key={s.app + s.id} data-ext-session={`${s.app}:${s.id}`} data-active={s.active ? "1" : "0"} data-gr={s.gr ? "1" : "0"} className="flex items-center gap-2.5 py-1.5">
          <Logo app={s.app} /><span className={cn("min-w-0 flex-1 truncate", s.gr && "text-muted-foreground")}>{s.title || "제목 없음"}</span>
          <span className="hidden shrink-0 text-xs text-muted-foreground sm:inline">{s.department_id ? deptName(s.department_id) : "기타"} · {ago(s.updated)}</span>
          <Status tone={s.active ? "warn" : "idle"} className="w-[4.5rem] justify-end">{s.active ? "진행 중" : "대기"}</Status></li>)}</ul>
        {sessions.filter(s => s.origin === "user").length > 8 && !more.ext && <Button variant="ghost" size="sm" className="mt-1" onClick={() => setMore(m => ({ ...m, ext: true }))}>세션 더 보기</Button>}
      </div>
      <div className="min-w-0 space-y-4">
        <div>
          <h3 className="text-[13px] font-semibold">항상 켜 두는 도우미</h3>
          <ul className="mt-1 divide-y text-[13px]">{(act.services || []).map((v: Any) => <li key={v.id} data-service={v.id} data-running={v.running ? "1" : "0"} className="flex items-center gap-2.5 py-1.5">
            <span className="min-w-0 flex-1">{v.label}</span><Status tone={v.running ? "ok" : "bad"}>{v.running ? `실행 중 · ${ago(v.since)} 시작` : "꺼짐"}</Status>
            {v.restartable && <Confirm label={v.running ? "재시작" : "켜기"} ask={v.running ? "끄고 다시 켤까요?" : "켤까요?"} run={() => restart(v.id)} attr={{ "data-restart": v.id }} />}</li>)}</ul>
        </div>
        <div>
          <h3 className="text-[13px] font-semibold">예약 작업 <span className="font-normal text-muted-foreground">· 마지막 실행</span></h3>
          <ul className="mt-1 divide-y text-[13px]">{(act.scheduled || []).map((t: Any, i: number) => <li key={i} data-sched={t.name} data-ok={t.ok ? "1" : "0"} className="py-1.5">
            <div className="flex items-center gap-2.5"><span className="min-w-0 flex-1 truncate">{SCHED_NAME[t.name] || t.name}</span><span className="shrink-0 text-xs text-muted-foreground">{t.last ? ago(t.last) : "실행 전"}</span><Status tone={t.ok ? "ok" : "bad"}>{t.result}</Status></div>
            {t.log && <div className="truncate text-xs text-muted-foreground">{t.log.replace("푸시 완료", "백업 완료")}</div>}</li>)}
            {!(act.scheduled || []).length && <li className="py-1.5 text-xs text-muted-foreground">불러오는 중…</li>}</ul>
        </div>
      </div>
    </section>

    <div data-board-primary className="grid grid-cols-[minmax(0,1fr)] gap-x-8 gap-y-5 pt-5 lg:grid-cols-[264px_minmax(0,1fr)]">
      <Section title="부서" aside={selDept ? <button className="underline underline-offset-2" onClick={() => setSelDept(null)}>전체 보기</button> : "선택한 부서의 업무를 봅니다"}>
        <div className="-mx-1 flex gap-3 overflow-x-auto pb-1 lg:block lg:overflow-visible lg:pb-0">
          {DEPT_GROUPS.map(([g, ids, color]) => {
            const members = depts.filter(d => (ids.length ? ids.includes(d.id) : !DEPT_GROUPS.some(x => x[1].includes(d.id))))
            if (!members.length) return null
            return <div key={g} className="flex shrink-0 items-start gap-1 lg:block lg:[&+&]:mt-3">
              <div className="shrink-0 self-center px-1 text-[11px] text-muted-foreground lg:mb-0.5 lg:self-auto">{g}</div>
              {members.map(d => {
                const ex = asgOf(d.id, "execute"), nS = sessions.filter(s => s.department_id === d.id).length, nR = runs.filter(r => r.department_id === d.id).length
                const nRun = runs.filter(r => r.department_id === d.id && runTone(r) === "warn").length
                const busy = nS + nR > 0
                return <button key={d.id} className={cn("dept block w-40 shrink-0 rounded-md px-2 py-1.5 text-left lg:w-full", selDept === d.id ? "bg-accent" : "hover:bg-accent/60")} data-d={d.id} data-exec={ex.engine} data-exec-state={ex.state} aria-pressed={selDept === d.id} onClick={() => setSelDept(selDept === d.id ? null : d.id)}>
                  <span className="flex items-center gap-2"><i aria-hidden className="block size-2 shrink-0 rounded-full" style={{ background: color }} />
                    <span className={cn("text-[13px]", busy ? "font-semibold" : "text-muted-foreground")}>{d.name}</span>
                    {nRun ? <Status tone="warn" className="ml-auto">진행 {nRun}</Status> : <Status tone={ex.state === "active" ? "ok" : "idle"} className="ml-auto">{ex.state === "active" ? "확정" : "배정 대기"}</Status>}</span>
                </button>
              })}
            </div>
          })}
        </div>

      </Section>
      <div className="min-w-0">
    <Section title="진행 흐름" className="scroll-mt-4" ref={graphRef as Any} aria-label="실행 그래프"
      aside={<span className="picks flex flex-wrap items-center gap-1">{orchRuns.slice(0, 6).map(r => <button key={r.id} data-pick={r.id} aria-pressed={r.id === run?.id} onClick={() => pick(r.id)}
        className={cn("rounded-md border px-2 py-0.5 text-xs tabular-nums", r.id === run?.id ? "border-foreground bg-foreground text-background" : "text-foreground hover:bg-accent")}>#{r.id}</button>)}</span>}>
      {!o ? <p className="rounded-md border border-dashed px-4 py-8 text-center text-[13px] text-muted-foreground">{selDept ? `${deptName(selDept)}에는 아직 실행이 없습니다.` : "표시할 실행이 없습니다. 부서를 선택하거나 새 작업을 보내세요."}</p> : <div className="rounded-lg border">
        <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-2 border-b px-4 py-3">
          <div className="max-w-3xl min-w-0">
            <p className="line-clamp-2 text-[13px] font-medium"><span className="mr-1.5 text-muted-foreground tabular-nums">#{run.id}</span>{run.request}</p>
            <details className="mt-1 text-xs leading-relaxed text-muted-foreground"><summary className="cursor-pointer">작업 계획 보기</summary><p className="mt-1">{o.approach || "계획 중"}</p></details>
          </div>
          <div className="flex shrink-0 items-center gap-4 text-xs text-muted-foreground">
            <Status tone={runTone(run)}>{STATUS[run.status] || run.status}</Status>
            {ACTIVE.includes(run.status) ? <Confirm key={"c" + run.id} label="취소" ask="취소할까요?" run={() => cancelRun(run.id)} attr={{ "data-cancel": String(run.id) }} />
              : RETRYABLE.includes(run.status) && <Confirm key={"r" + run.id} label="재시도" ask="같은 요청으로 다시 실행할까요?" run={() => retryRun(run.id)} attr={{ "data-retry": String(run.id) }} />}
          </div>
        </div>
        {(run.review_note || run.error_detail) && <div className="space-y-1 border-b px-4 py-2 text-xs text-muted-foreground">
          {run.review_note && <details data-review-note><summary className="cursor-pointer">검수 메모</summary><p className="mt-1 whitespace-pre-wrap leading-relaxed">{run.review_note}</p></details>}
          {run.error_detail && <details data-error-detail><summary className="cursor-pointer">오류 원문</summary><p className="mt-1 whitespace-pre-wrap leading-relaxed">{run.error_detail}</p></details>}
        </div>}
        <Graph run={run} narrow={narrow} />
      </div>}
    </Section>
      </div>
    </div>

    <div className={cn("grid grid-cols-5 divide-x border-b @2xl:flex @2xl:divide-x-0", V2 ? "py-3 @2xl:gap-10" : "py-3 @2xl:gap-10")}>
      {stats.map(([n, v, tone]) => <div key={n} data-stat={n} className="min-w-0 px-1 first:pl-0 @2xl:px-0">
        <div className={cn("leading-tight tabular-nums", V2 ? "text-base font-bold tracking-tight @2xl:text-2xl @4xl:text-3xl" : "text-xl font-semibold @2xl:text-2xl")}>{v}</div>
        <div className="mt-0.5 flex items-center gap-1 text-[11px] whitespace-nowrap text-muted-foreground @2xl:gap-1.5 @2xl:text-xs">{tone && <Dot tone={tone} />}{n}</div>
      </div>)}
    </div>


    <div className="mt-8">


      <div className="min-w-0 space-y-6">
        {dept && <Section title={`${dept.name} 담당`} aside={`${dept.session_policy || ""} · ${dept.note || dept.tagline || ""}`} aria-label="부서 상세">
          <div className="flex flex-wrap gap-x-8 gap-y-5 rounded-lg border p-4"><RoleBox a={asgOf(dept.id, "execute")} role="execute" onSaved={x => setAsg(as => as.map(a => (a.id === x.id ? { ...a, ...x } : a)))} /><RoleBox a={asgOf(dept.id, "review")} role="review" onSaved={x => setAsg(as => as.map(a => (a.id === x.id ? { ...a, ...x } : a)))} /></div>
        </Section>}

        <Tabs defaultValue="log">
          <TabsList><TabsTrigger value="log">실행 기록</TabsTrigger><TabsTrigger value="tree">AI 앱·세션</TabsTrigger><TabsTrigger value="models">AI 배정 순서</TabsTrigger><TabsTrigger value="usage">사용량</TabsTrigger></TabsList>

          <TabsContent value="log" forceMount className="data-[state=inactive]:hidden">
            <Table className="text-[13px]">
              <TableHeader><TableRow><TableHead className="hidden w-14 sm:table-cell">시각</TableHead><TableHead>#</TableHead><TableHead>요청</TableHead><TableHead className="hidden md:table-cell">처리</TableHead><TableHead>상태</TableHead><TableHead>부서</TableHead></TableRow></TableHeader>
              <TableBody>
                {logRows.map(r => <TableRow key={r.id} data-run-row={r.id} data-state={r.id === selRun ? "selected" : undefined}>
                  <TableCell className="hidden text-muted-foreground tabular-nums sm:table-cell">{hm(r.started)}</TableCell>
                  <TableCell className="tabular-nums">{r.orchestration ? <button data-pick={r.id} onClick={() => pick(r.id)} className="underline underline-offset-2">#{r.id}</button> : <span className="text-muted-foreground">#{r.id}</span>}</TableCell>
                  <TableCell className="w-full max-w-0 whitespace-normal"><span className="line-clamp-2 sm:line-clamp-1" title={r.routing_reason || ""}>{r.request}</span></TableCell>
                  <TableCell className="hidden text-muted-foreground md:table-cell">{V2 && <span className="mr-2 inline-flex items-center align-middle">{(r.orchestration ? steps(r.orchestration).filter(s => s.app).map(s => s.app) : [appOf(r)]).map((a: string, i: number) => <i key={i} className="block h-1.5 w-3 first:rounded-l-full last:rounded-r-full" style={{ background: lineOf(a) }} />)}</span>}{procText(r)}</TableCell>
                  <TableCell><span className="flex flex-wrap items-center gap-1.5"><Status tone={runTone(r)}>{STATUS[r.status] || r.status}</Status>
                    {RETRYABLE.includes(r.status) && <Confirm label="재시도" ask="다시 실행?" run={() => retryRun(r.id)} attr={{ "data-retry": String(r.id) }} />}</span></TableCell>
                  <TableCell><NativeSelect size="sm" className="h-7 w-24 text-xs sm:w-28" data-run={r.id} aria-label={`#${r.id} 부서`} value={r.department_id || ""} onChange={e => setRunDept(r, e.target.value)}><NativeSelectOption value="">미분류</NativeSelectOption>{depts.map(d => <NativeSelectOption key={d.id} value={d.id}>{d.name}</NativeSelectOption>)}</NativeSelect></TableCell>
                </TableRow>)}
                {!logRows.length && <TableRow><TableCell colSpan={6} className="py-8 text-center text-muted-foreground">이 부서로 분류된 실행 기록이 없습니다.</TableCell></TableRow>}
              </TableBody>
            </Table>
            {logAll.length > logRows.length && <Button variant="ghost" size="sm" className="mt-2" onClick={() => setMore(m => ({ ...m, log: true }))}>기록 {logAll.length - logRows.length}건 더 보기</Button>}
          </TabsContent>

          <TabsContent value="tree" forceMount className="data-[state=inactive]:hidden">
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="AI 앱">
              {APPS.map(([id, name]) => <button key={id} data-a={id} data-sessions={appSessions(id).length} data-work={appWork(id).length} aria-pressed={selApp === id} onClick={() => setSelApp(id)}
                className={cn("flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-[13px]", selApp === id ? "border-foreground" : "hover:bg-accent")}><Logo app={id} /><span className="font-medium">{name}</span><span className="text-xs text-muted-foreground tabular-nums">세션 {appSessions(id).length} · 작업 {appWork(id).length}</span></button>)}
            </div>
            <p className="mt-3 text-xs text-muted-foreground">통합 자비스 → {(APPS.find(a => a[0] === selApp) || [])[1]} → 세션 → 하위 작업{selDept ? ` · ${deptName(selDept)}만` : ""}</p>
            {pl.length > 0 && <div className="mt-3">
              <h3 className="text-xs font-medium text-muted-foreground">통합 자비스가 이 AI에 맡긴 단계 {pl.length}</h3>
              <ul className="mt-1 divide-y border-y text-[13px]">{pl.slice(0, more[selApp + "r"] ? 99 : 8).map((p, i) => <li key={i} data-place={p.step ? `${p.run.id}:${p.step.id}` : p.run.id} className="flex items-center gap-3 py-1.5">
                <span className="w-9 shrink-0 text-muted-foreground tabular-nums">#{p.run.id}</span><span className="min-w-0 flex-1 truncate">{p.step ? p.step.title : p.run.request}</span>
                <span className="hidden shrink-0 text-xs text-muted-foreground sm:inline">{p.step ? p.step.label : ENGINE[p.run.engine] || p.run.engine}</span>
                <Status tone={p.step ? stepTone(p.step.status) : runTone(p.run)}>{STATUS[p.step ? p.step.status : p.run.status] || "대기"}</Status></li>)}</ul>
              {pl.length > 8 && !more[selApp + "r"] && <Button variant="ghost" size="sm" className="mt-1" onClick={() => setMore(m => ({ ...m, [selApp + "r"]: true }))}>{pl.length - 8}개 더 보기</Button>}
            </div>}
            {ss.length > 0 && <div className="mt-5">
              <h3 className="text-xs font-medium text-muted-foreground">세션 {ss.length} (최근 7일)</h3>
              <ul className="mt-1 divide-y border-y text-[13px]">{ss.slice(0, more[selApp] ? 99 : 6).map(s => <li key={s.id} data-session={`${s.app}:${s.id}`} className="py-2">
                <div className="flex items-baseline gap-3"><span className="shrink-0 text-xs text-muted-foreground tabular-nums">{s.id}</span><span className="min-w-0 flex-1 truncate">{s.title || "제목 없음"}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">{s.department_id ? deptName(s.department_id) : "기타"} · {ago(s.updated)}</span></div>
                {s.subtask_total > 0 && <ul className="mt-1 space-y-0.5 pl-12 text-xs text-muted-foreground">{s.subtasks.map((t: Any, i: number) => <li key={i} className="flex items-center gap-1.5"><CornerDownRight className="size-3 shrink-0" /><span className="truncate">{t.title}</span><Dot tone={t.done ? "ok" : "warn"} /></li>)}
                  {s.subtask_total > s.subtasks.length && <li className="pl-[18px]">외 {s.subtask_total - s.subtasks.length}개</li>}</ul>}
              </li>)}</ul>
              {ss.length > 6 && !more[selApp] && <Button variant="ghost" size="sm" className="mt-1" onClick={() => setMore(m => ({ ...m, [selApp]: true }))}>세션 {ss.length - 6}개 더 보기</Button>}
            </div>}
            {!ss.length && <p className="mt-4 text-[13px] text-muted-foreground">{["gemini", "grok", "copilot"].includes(selApp) ? "직접 연 세션은 없습니다. OmniRoute로 호출되며, 맡은 단계만 위에 붙습니다." : pl.length ? "" : "이 범위에 세션과 작업이 없습니다."}</p>}
          </TabsContent>

          <TabsContent value="usage" forceMount className="data-[state=inactive]:hidden">
            <Table className="text-[13px]" data-usage>
              <TableHeader><TableRow><TableHead>날짜</TableHead><TableHead className="text-right">Claude 토큰</TableHead><TableHead className="text-right">Codex 토큰</TableHead><TableHead className="hidden text-right sm:table-cell">기타 토큰</TableHead><TableHead className="hidden text-right sm:table-cell">모델 호출</TableHead><TableHead className="text-right">Jev 호출</TableHead></TableRow></TableHeader>
              <TableBody>{usageDays.map(u => <TableRow key={u.date} data-usage-row={u.date} data-claude={u.claude} data-codex={u.codex} data-jev={u.jev}>
                <TableCell className="tabular-nums">{u.date.slice(5).replace("-", "/")}</TableCell><TableCell className="text-right tabular-nums">{k(u.claude)}</TableCell><TableCell className="text-right tabular-nums">{k(u.codex)}</TableCell>
                <TableCell className="hidden text-right text-muted-foreground tabular-nums sm:table-cell">{k(u.other)}</TableCell><TableCell className="hidden text-right text-muted-foreground tabular-nums sm:table-cell">{u.calls}</TableCell><TableCell className="text-right tabular-nums">{u.jev}</TableCell></TableRow>)}</TableBody>
            </Table>
            <p className="mt-2 text-xs text-muted-foreground">도나로가 맡긴 작업의 기록(입력+출력)입니다. 도나로 밖 세션과 요금제 한도(%)는 서버에서 알 수 없어 빠집니다. Jev 호출은 11/16 이후 기록분입니다.</p>
          </TabsContent>

          <TabsContent value="models" forceMount className="data-[state=inactive]:hidden">
            <Table className="text-[13px]">
              <TableHeader><TableRow><TableHead>모델 {models.length}</TableHead><TableHead className="hidden sm:table-cell">경로</TableHead><TableHead className="hidden sm:table-cell">등급</TableHead><TableHead className="hidden sm:table-cell">기능</TableHead><TableHead className="w-24">상태</TableHead></TableRow></TableHeader>
              <TableBody>{APPS.flatMap(([a]) => models.filter(m => m.app === a)).map(m => { const [t, tone] = STATE[m.state] || [m.state, "idle" as Tone]
                return <TableRow key={m.id} data-model-row={m.id} data-state={m.state}>
                  <TableCell><span className="flex items-center gap-2"><Logo app={m.app} />{m.label}</span></TableCell>
                  <TableCell className="hidden text-muted-foreground sm:table-cell">{m.route === "api" ? "OmniRoute" : ENGINE[m.route] || m.route}</TableCell>
                  <TableCell className="hidden text-muted-foreground tabular-nums sm:table-cell">{m.tier}/3</TableCell>
                  <TableCell className="hidden text-muted-foreground sm:table-cell">{m.tools ? "도구" : "글"}{m.write ? ", 쓰기" : ""}</TableCell>
                  <TableCell><Status tone={tone}>{t}</Status></TableCell></TableRow> })}</TableBody>
            </Table>
            <h3 className="mt-6 text-[13px] font-semibold">작업 종류별 대체 순서</h3>
            <p className="mt-0.5 text-xs text-muted-foreground">앞 모델이 한도나 장애로 실패하면 다음 모델로 넘어갑니다. 줄 그은 모델은 지금 건너뜁니다.</p>
            <div className="mt-2 divide-y border-y text-[13px]">{Object.entries(D.chains || {}).map(([kind, ids]) => <div key={kind} data-chain={kind} className="flex flex-wrap items-center gap-x-1.5 gap-y-1 py-1.5">
              <span className="w-20 shrink-0 font-medium">{KIND[kind] || kind}</span>
              {(ids as string[]).map((id, i) => <span key={id} className="flex items-center gap-1.5">{i > 0 && <ArrowRight className="size-3 text-muted-foreground" />}<span className={cn(!okModel(id) && "text-muted-foreground line-through")}>{(modelById[id] || {}).label || id}</span></span>)}</div>)}</div>
          </TabsContent>
        </Tabs>
      </div>
    </div>
    <details className="mt-8 rounded-lg border p-4" data-board-operations>
      <summary className="cursor-pointer text-[13px] font-medium">운영 상세</summary>
      <p className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">정책 {D.policy_version || ""} · 오늘 토큰 {k(tok)} · 모델 가용 {models.filter(m => m.state === "ready").length}/{models.length}
        <span className="inline-flex shrink-0 overflow-hidden rounded-md border whitespace-nowrap">{[["1", "1안"], ["2", "2안"]].map(([v, n]) => <a key={v} href={`?v=${v}`} aria-current={(V2 ? "2" : "1") === v} className={cn("px-2 py-0.5", (V2 ? "2" : "1") === v ? "bg-foreground text-background" : "text-foreground hover:bg-accent")}>{n}</a>)}</span></p>
      <div data-harness-runs className="mt-4"><h3 className="text-[13px] font-semibold">자동 시험 작업 <span className="font-normal text-muted-foreground">· 하네스가 보낸 작업, 대표님 화면 집계에서 뺌</span></h3>
        {harnessRuns.length ? <ul className="mt-1 divide-y text-[13px]">{harnessRuns.slice(0, 10).map(liveRow)}</ul> : <p className="mt-1 text-xs text-muted-foreground">없음</p>}</div>
        <div className="mt-4 space-y-1.5 border-t pt-3 text-xs leading-relaxed text-muted-foreground lg:block">{(D.review_layers || []).map((l: Any) => <p key={l.id}><span className="font-medium text-foreground">{l.label}</span> {l.owner}. {l.policy}</p>)}</div>
      <div className="mt-4">
      <div className="ml-auto flex w-full max-w-md items-center gap-2 sm:w-auto sm:min-w-[400px]">
        <Input id="pv" value={pv} onChange={e => setPv(e.target.value)} onKeyDown={e => { if (e.key === "Enter") preview() }} maxLength={500} placeholder="문장을 넣으면 어느 부서·담당으로 가는지 봅니다" aria-label="라우터 시험 문장" className="h-8 text-[13px]" />
        <Button id="pvBtn" type="button" variant="outline" size="sm" onClick={preview}>라우터 시험</Button>
      </div>
      </div>
    <div id="pvOut" hidden={!pvOut} className="border-b bg-muted/50 px-3 py-2.5 text-[13px]" aria-live="polite">
      {pvOut?.msg ? pvOut.msg : pvOut && <dl className="grid grid-cols-[3rem_1fr] gap-x-3 gap-y-1">
        <dt className="text-muted-foreground">부서</dt><dd>{deptName(pvOut.department_id)}</dd>
        <dt className="text-muted-foreground">담당</dt><dd>{ENGINE[pvOut.engine] || pvOut.engine} · {pvOut.model}</dd>
        <dt className="text-muted-foreground">배정</dt><dd>{pvOut.assignment_id || "적용 안 함(기존 규칙)"}</dd>
        <dt className="text-muted-foreground">이유</dt><dd>{pvOut.reason}</dd>
      </dl>}
      <p className="mt-1.5 text-xs text-muted-foreground">실행하지 않고 경로만 확인합니다.</p>
    </div>

    {V2 ? <nav className="flow relative grid gap-y-3 border-b py-5 lg:grid-cols-7" aria-label="업무 흐름">
      <span aria-hidden className="absolute top-7 bottom-7 left-[7px] w-1 bg-foreground lg:top-[27px] lg:right-[calc(100%/7-18px)] lg:bottom-auto lg:left-2 lg:h-1 lg:w-auto" />
      {flow.map(([a, v, n], i) => <div key={a} className="step relative flex min-w-0 gap-3 pr-3 lg:block">
        <span className={cn("relative z-10 mt-0.5 block size-[18px] shrink-0 rounded-full border-4 bg-background lg:mt-0", i === 5 ? "border-muted-foreground/50" : "border-foreground")} />
        <div className="min-w-0 lg:mt-2"><div className="text-[13px] font-bold">{a}</div><div className="text-xs">{v}</div><div className="text-xs text-muted-foreground">{n}</div></div>
      </div>)}
    </nav> : <nav className="flow grid grid-cols-2 border-b sm:grid-cols-4 lg:grid-cols-7" aria-label="업무 흐름">
      {flow.map(([a, v, n], i) => <div key={a} className="step min-w-0 py-2.5 pr-3">
        <div className="flex items-center gap-1 text-xs text-muted-foreground"><span className="tabular-nums">{i + 1}</span>{a}</div>
        <div className="mt-0.5 text-[13px] font-medium">{v}</div>
        <div className="text-xs text-muted-foreground">{n}</div>
      </div>)}
    </nav>}

    </details>
  </div>
}

// /app 에서는 대화와 보드를 한 앱으로 보여 준다. 대화·보드 따로, 또는 넓은 화면에서 함께(왼쪽 대화·오른쪽 보드). /board 는 기존처럼 보드만(하네스 기준)
const VIEWS = [["chat", "대화"], ["board", "보드"], ["both", "함께"]]
const savedView = () => {
  const h = location.hash.slice(1)
  if (VIEWS.some(([v]) => v === h)) return h
  try { return localStorage.getItem("donaroView") || "chat" } catch { return "chat" }
}
export default function App() {
  const [view, setView] = useState(savedView)
  if (!D.chat) return <Board />
  const go = (v: string) => {
    setView(v); history.replaceState(null, "", v === "chat" ? location.pathname + location.search : "#" + v)
    try { localStorage.setItem("donaroView", v) } catch { /* 저장 못 해도 화면은 바뀐다 */ }
  }
  const both = view === "both"
  return <div className="flex h-dvh flex-col">
    <nav className="flex shrink-0 items-center gap-1 border-b px-3 py-1.5" aria-label="화면">
      <span className="mr-2 text-[15px] font-black tracking-tight">도나로</span>
      {VIEWS.map(([v, n]) => <button key={v} aria-pressed={view === v} onClick={() => go(v)}
        className={cn("rounded-md px-3 py-1 text-[13px] font-medium", v === "both" && "hidden md:inline-block", view === v || (both && v === "chat") ? "bg-foreground text-background" : "text-foreground hover:bg-accent", both && v === "chat" && "md:bg-transparent md:text-foreground md:hover:bg-accent")}>{n}</button>)}
      <a href="/old" className="ml-auto text-xs text-muted-foreground underline underline-offset-2">이전 화면</a>
    </nav>
    {/* 함께 보기는 넓은 화면에서만 둘로 나눈다. 좁은 화면에서는 대화만 보인다 */}
    <div className={cn("min-h-0 flex-1", both && "md:grid md:grid-cols-[minmax(340px,2fr)_3fr] md:grid-rows-[minmax(0,1fr)]")}>
      <div className={cn("h-full min-w-0", both && "md:border-r", view === "board" && "hidden")}><Chat onBoard={() => go(both && matchMedia("(min-width: 768px)").matches ? "both" : "board")} /></div>
      <div className={cn("h-full min-w-0 overflow-y-auto", view === "chat" && "hidden", both && "hidden md:block")}><Board /></div>
    </div>
  </div>
}
