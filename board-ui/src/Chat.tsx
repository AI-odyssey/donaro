// 도나로 대화 화면. 서버의 /api/task(작업 접수)·/api/history·/api/tasks를 그대로 쓴다. 서버 로직은 바꾸지 않는다.
import { useCallback, useEffect, useRef, useState } from "react"
import { ArrowUp, Bell, Headphones, Mic, Paperclip, Plus, Volume2, VolumeX, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select"
import { cn } from "@/lib/utils"
import { IOS, SR, chimeDown, chimeUp, getSpeakOn, pushSupported, saveSpeakTasks, setSpeakOn, speak, speakTasks, startPresence, subscribePush, unlockAudio } from "./voice"

/* eslint-disable @typescript-eslint/no-explicit-any */
type Any = any
const D: Any = (window as Any).__BOARD__ || {}
const APPS: [string, string][] = [["claude", "Claude Code"], ["codex", "Codex"], ["gemini", "Gemini"], ["copilot", "GitHub Copilot"], ["grok", "Grok"]]
const STATE_KO: Record<string, string> = { ready: "사용 가능", unknown: "미확인", quota: "한도 소진", rate_limit: "속도 제한", unavailable: "장애", auth: "인증 필요" }
const kfmt = (n: number) => (n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n || 0))
// 앱 하나의 상태: 모델 중 하나라도 사용 가능하면 사용 가능, 전부 막히면 가장 심한 상태
function appState(models: Any[], app: string) {
  const st = models.filter(m => m.app === app).map(m => m.state)
  return st.includes("ready") ? "ready" : st.find(x => ["quota", "unavailable", "auth", "rate_limit"].includes(x)) || "unknown"
}
const DOT: Record<string, string> = { ready: "bg-ok", unknown: "bg-muted-foreground/40", rate_limit: "bg-warn" }

const esc = (s: string) => s.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!)
// 글을 먼저 이스케이프한 뒤 최소한의 마크다운만 바꾼다(스크립트가 끼어들 수 없다)
function md(s: string) {
  return esc(s).split(/```/).map((b, i) => i % 2 ? `<pre>${b.replace(/^\w*\n/, "")}</pre>` :
    b.split(/\n{2,}/).map(p => {
      p = p.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>").replace(/^#{1,6} (.+)$/gm, "<b>$1</b>")
      if (/^\s*[-*] /m.test(p) && p.split("\n").every(l => /^\s*([-*] |\s)/.test(l) || !l.trim()))
        return "<ul>" + p.split("\n").filter(l => l.trim()).map(l => "<li>" + l.replace(/^\s*[-*] /, "") + "</li>").join("") + "</ul>"
      if (/^\d+\. /.test(p)) return "<ol>" + p.split("\n").filter(l => l.trim()).map(l => "<li>" + l.replace(/^\s*\d+\. /, "") + "</li>").join("") + "</ol>"
      return "<p>" + p.replace(/\n/g, "<br>") + "</p>"
    }).join("")).join("")
}
const isImg = (n: string) => /\.(jpe?g|png|gif|webp|heic)$/i.test(n)
const uid = () => (crypto.randomUUID ? crypto.randomUUID() : Date.now() + "-" + Math.random().toString(36).slice(2))
const dur = (s: number) => (s >= 60 ? `${Math.floor(s / 60)}분 ${s % 60}초` : `${s}초`)
const day = (ts: number) => new Date(ts * 1000).toLocaleString("ko-KR", { month: "long", day: "numeric", weekday: "short", hour: "numeric", minute: "2-digit" })

async function api(path: string, init?: RequestInit) {
  const r = await fetch(path, init)
  if (!r.ok) throw new Error((await r.text().catch(() => "")) || String(r.status))
  return r.json()
}

function Bubble({ m }: { m: Any }) {
  const me = m.role === "user"
  const files: string[] = m.files || [], images: string[] = m.images || []
  return <div className={cn("flex flex-col gap-1", me ? "items-end" : "items-start")}>
    {images.map(n => isImg(n)
      ? <img key={n} src={`/files/${encodeURIComponent(n)}`} alt="보낸 사진" className="max-h-60 max-w-[75%] rounded-lg border object-cover" />
      : <span key={n} className="rounded-lg border px-3 py-1.5 text-[13px]">📎 {n}</span>)}
    {m.text && (me
      ? <div className="max-w-[85%] rounded-2xl bg-primary px-3.5 py-2 text-[14px] leading-relaxed whitespace-pre-wrap text-primary-foreground">{m.text}</div>
      : <div className="chat-md max-w-[92%] rounded-2xl bg-muted px-3.5 py-2 text-[14px] leading-relaxed" dangerouslySetInnerHTML={{ __html: md(m.text) }} />)}
    {files.map(u => <a key={u} href={u} download className="rounded-lg border px-3 py-1.5 text-[13px] underline underline-offset-2">📎 {decodeURIComponent(u.split("/").pop() || "")}</a>)}
  </div>
}

export default function Chat({ onBoard }: { onBoard?: () => void }) {
  const [msgs, setMsgs] = useState<Any[]>([]), [tasks, setTasks] = useState<Any[]>([])
  const [text, setText] = useState(""), [imgs, setImgs] = useState<string[]>([]), [uploading, setUploading] = useState(0)
  const [sending, setSending] = useState(false), [note, setNote] = useState<[string, boolean] | null>(null)
  const [target, setTarget] = useState(() => { try { return localStorage.getItem("donaro_target") || "auto" } catch { return "auto" } }), [parent, setParent] = useState("")
  const [usage, setUsage] = useState<Any>(null), [local, setLocal] = useState<Any[]>([]), [live, setLive] = useState(false)
  const liveRef = useRef(false), micRef = useRef<Any>(null)
  const [thread, setThread] = useState(() => { try { return localStorage.getItem("donaro_thread") !== "0" } catch { return true } }) // 이전 대화를 모든 AI가 이어 받는다(기본 켬)
  liveRef.current = live
  const box = useRef<HTMLDivElement>(null), area = useRef<HTMLTextAreaElement>(null), file = useRef<HTMLInputElement>(null)
  const [speakOn, setSpeakOnState] = useState(getSpeakOn), [listening, setListening] = useState(false), [cd, setCd] = useState(0)
  const [tap, setTap] = useState(false), [pushAsk, setPushAsk] = useState(false)
  const textRef = useRef(""), rec = useRef<Any>(null), timer = useRef<Any>(null), heard = useRef(false), cdRef = useRef<Any>(null), sendRef = useRef<Any>(null)
  textRef.current = text
  const stick = useRef(true), req = useRef<{ sig: string; id: string } | null>(null), lastLen = useRef(-1)

  const load = useCallback(async () => {
    try {
      const [h, t] = await Promise.all([api("/api/history"), api("/api/tasks")])
      setMsgs(h); setTasks(t)
      for (const m of h) if (m.role === "jarvis" && m.task_id && speakTasks.has(m.task_id)) { // 음성으로 맡긴 작업의 결과는 도착하면 한 번 읽는다
        speakTasks.delete(m.task_id); saveSpeakTasks(); speak(m.body || String(m.text).replace(/^\*\*작업 #\d+[^\n]*\n\n/, "")).then(() => { if (liveRef.current && !rec.current) setTimeout(() => micRef.current?.(), 400) })
      }
    } catch { /* 연결이 잠시 끊겨도 다음 주기에 다시 받는다 */ }
  }, [])
  const active = tasks.filter(t => ["running", "queued", "waiting"].includes(t.status))
  const decide = tasks.filter(t => (t as any).source !== "harness" && ["needs_reconciliation", "needs_input"].includes(t.status) && Date.now() / 1000 - ((t as any).since || 0) < 3 * 86400).length
  useEffect(() => { load() }, [load])
  useEffect(() => { // AI별 상태·오늘 사용량: 20초마다 새로 받는다
    const f = () => { if (!document.hidden) api("/api/usage").then(setUsage).catch(() => {}) }
    f(); const id = setInterval(f, 20000); return () => clearInterval(id)
  }, [])
  useEffect(() => {
    const stop = startPresence()
    if (pushSupported()) { if (Notification.permission === "granted") subscribePush().catch(() => {}); else if (Notification.permission === "default") setPushAsk(true) }
    if (new URLSearchParams(location.search).get("voice") === "1") { history.replaceState(null, "", location.pathname); if (SR) setTap(true) } // 단축어로 열면 탭 한 번으로 듣기 시작(사파리는 터치로만 마이크를 켠다)
    return stop
  }, [])
  useEffect(() => {
    const ms = active.length ? 2500 : 8000
    const id = setInterval(() => { if (!document.hidden) load() }, ms)
    const vis = () => { if (!document.hidden) load() }
    document.addEventListener("visibilitychange", vis)
    return () => { clearInterval(id); document.removeEventListener("visibilitychange", vis) }
  }, [load, active.length])
  useEffect(() => { // 읽던 자리가 튀지 않게: 맨 아래 근처일 때만 따라 내려간다
    const n = msgs.length + local.length
    if (n !== lastLen.current && (stick.current || lastLen.current < 0)) box.current?.scrollTo({ top: box.current.scrollHeight })
    lastLen.current = n
  }, [msgs, local])

  function grow() { const a = area.current; if (a) { a.style.height = "auto"; a.style.height = Math.min(a.scrollHeight, 160) + "px" } }
  async function attach(files: FileList | null) {
    if (!files?.length) return
    setUploading(n => n + files.length)
    for (const f of Array.from(files)) {
      try { const fd = new FormData(); fd.append("file", f, f.name); const j = await api("/api/upload", { method: "POST", body: fd }); setImgs(x => [...x, j.name]) }
      catch (e: Any) { setNote([`올리지 못했습니다: ${f.name}`, false]) }
      setUploading(n => n - 1)
    }
    if (file.current) file.current.value = ""
  }
  async function send(o: { spoken?: boolean; text?: string } = {}) {
    const t = (o.text ?? text).trim()
    if ((!t && !imgs.length) || sending || uploading) return
    if (!imgs.length && /^(\/board|\/보드|보드)$/.test(t)) { textRef.current = ""; setText(""); requestAnimationFrame(grow); onBoard?.(); return }  // 보드는 작업으로 보내지 않고 화면만 바꾼다
    if (!imgs.length && /^\/(usage|model|new|help)(\s|$)/.test(t) && await slash(t)) return
    const direct = target !== "auto" && target !== "economy"  // 모델 id를 고르면 그 AI 한 곳에서 처리
    const body = { text: t, images: imgs, provider: direct ? "auto" : target, ...(direct ? { target } : {}), parent_id: Number(parent) || null, thread: thread && !Number(parent) }
    const sig = JSON.stringify(body)
    if (!req.current || req.current.sig !== sig) req.current = { sig, id: uid() }  // 같은 내용을 다시 보내도 중복 접수되지 않게
    setSending(true); setNote(["접수 중…", true])
    try {
      const j = await api("/api/task", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...body, request_id: req.current.id }) })
      if (o.spoken && !j.duplicate) { speakTasks.add(j.id); saveSpeakTasks() }
      req.current = null; textRef.current = ""; setText(""); setImgs([]); setParent(""); requestAnimationFrame(grow)
      setNote([`✓ 작업 #${j.id} 접수 · ${j.routing_reason || ""}`, true]); stick.current = true
      await load()
    } catch (e: Any) { setNote([`접수 확인 실패: ${e.message}. 같은 내용으로 다시 보내면 중복 접수를 막습니다.`, false]) }
    setSending(false)
  }
  // Claude Code의 슬래시 명령 중 이 화면에서 쓸 수 있는 것: /usage /model /new /help (서버로 보내지 않고 바로 답한다)
  async function slash(t: string) {
    const [cmd, ...rest] = t.split(/\s+/), arg = rest.join(" ").trim().toLowerCase()
    textRef.current = ""; setText(""); requestAnimationFrame(grow); stick.current = true
    const say = (reply: string) => setLocal(l => [...l, { role: "user", text: t }, { role: "jarvis", text: reply }])
    const models: Any[] = usage?.models || D.models || []
    if (cmd === "/new") { await reset(); return true }
    if (cmd === "/help") { say("**쓸 수 있는 명령**\n- /usage: AI별 오늘 사용량과 상태\n- /model: 지금 보낼 AI·모델 보기\n- /model 이름: 바꾸기(예: /model opus, /model gemini, /model 자동)\n- /new: 새 대화\n- /board: 보드로 이동\n\n마이크 🎤는 한 번 말하기, 🎧 대화 모드는 말하고 듣기를 이어서 합니다."); return true }
    if (cmd === "/model") {
      if (!arg) {
        const cur = target === "auto" ? "자동 배정" : target === "economy" ? "빠른 텍스트 응답" : (models.find(m => m.id === target)?.label || target)
        say(`**지금 보낼 곳:** ${cur}\n\n` + APPS.map(([a, n]) => `- ${n}: ` + models.filter(m => m.app === a).map(m => `${m.label}(\`${m.id}\`)`).join(", ")).join("\n") + "\n\n바꾸려면 `/model 모델id` 또는 `/model 자동`")
        return true
      }
      const hit = /^(auto|자동)/.test(arg) ? "auto" : /^(economy|빠른)/.test(arg) ? "economy"
        : models.find(m => m.id === arg || m.label.toLowerCase() === arg)?.id || models.find(m => (m.id + " " + m.label + " " + m.app).toLowerCase().includes(arg))?.id
      if (!hit) { say(`'${arg}'에 맞는 모델이 없습니다. /model 로 목록을 확인해 주세요.`); return true }
      pickTarget(hit); say(`보낼 곳을 **${hit === "auto" ? "자동 배정" : hit === "economy" ? "빠른 텍스트 응답" : models.find(m => m.id === hit)?.label}**(으)로 바꿨습니다.`); return true
    }
    try {
      const u = await api("/api/usage"); setUsage(u)
      const rows = (u.today as Any[]).map(r => `- ${r.label}: 호출 ${r.calls}${r.errors ? `(실패 ${r.errors})` : ""} · 입력 ${kfmt(r.input)} · 출력 ${kfmt(r.output)}`)
      say(`**오늘 사용량**\n${rows.join("\n") || "- 아직 호출이 없습니다."}\n\n**최근 7일 합계:** 입력 ${kfmt(u.week.input)} · 출력 ${kfmt(u.week.output)} · 진행 중 ${u.active}건\n\n**상태**\n` +
        APPS.map(([a, n]) => `- ${n}: ${STATE_KO[appState(u.models, a)]}`).join("\n") + "\n\n요금제 한도(%)는 서버에서 확인할 수 없어 표시하지 않습니다. 한도가 소진되면 위 상태가 '한도 소진'으로 바뀝니다.")
    } catch (e: Any) { say(`사용량을 불러오지 못했습니다: ${e.message}`) }
    return true
  }
  function pickTarget(v: string) { setTarget(v); try { localStorage.setItem("donaro_target", v) } catch { /* 저장 못 해도 이번 화면에서는 적용된다 */ } }
  function toggleLive() { // 대화 모드: 듣기 → 보내기 → 결과를 소리로 읽기 → 다시 듣기를 이어서 한다
    if (!SR) return setNote(["이 브라우저는 음성 인식을 지원하지 않습니다.", false])
    const v = !live; setLive(v); liveRef.current = v
    if (v) { unlockAudio(); setSpeakOnState(true); setSpeakOn(true); if (!rec.current) toggleMic() } else rec.current?.stop()
  }
  sendRef.current = send
  // 말로 입력: 말이 멈추면 1.5초 뒤 자동 전송, 덜 끝난 말(그리고·근데·~는데 등)이면 4초까지 기다린다. 아이폰은 3초 취소 창을 둔다
  const unfinished = (t: string) => /(\.\.\.|…|,)\s*$/.test(t) || /(^|\s)(그리고|근데|그런데|그래서|그러니까|그러면|아니면|왜냐면|또|그|어|음|저|좀)\s*$/.test(t) || /(고|는데|은데|면|면서|니까|지만|거든|며)\s*$/.test(t)
  const arm = () => { clearTimeout(timer.current); timer.current = setTimeout(() => rec.current?.stop(), unfinished(textRef.current.trim()) ? 4000 : 1500) }
  function stopCd() { clearInterval(cdRef.current); cdRef.current = null; setCd(0) }
  function countdown(t: string) {
    stopCd(); let n = 3; setCd(n)
    cdRef.current = setInterval(() => { n--; if (n <= 0) { stopCd(); sendRef.current({ spoken: true, text: t }) } else setCd(n) }, 1000)
  }
  function toggleMic() {
    stopCd()
    if (rec.current) { rec.current.stop(); return }
    if (sending) return
    unlockAudio()
    const r = new SR(); r.lang = "ko-KR"; r.interimResults = true; r.continuous = !IOS; heard.current = false; rec.current = r
    const base = textRef.current ? textRef.current + " " : ""
    r.onerror = (ev: Any) => {
      if (ev.error === "not-allowed" || ev.error === "service-not-allowed") { liveRef.current = false; setLive(false); setTap(true) }
      else if (ev.error !== "aborted" && ev.error !== "no-speech") setNote([`음성 인식 오류: ${ev.error}`, false])
    }
    r.onresult = (ev: Any) => { heard.current = true; const v = base + Array.from(ev.results).map((x: Any) => x[0].transcript).join(""); textRef.current = v; setText(v); requestAnimationFrame(grow); arm() }
    r.onend = () => {
      clearTimeout(timer.current); rec.current = null; setListening(false); if (!IOS) chimeDown()
      const v = textRef.current.trim()
      if (heard.current && v) { if (IOS) countdown(v); else sendRef.current({ spoken: true, text: v }) }
      else if (liveRef.current) setTimeout(() => { if (liveRef.current && !rec.current) micRef.current?.() }, 700) // 대화 모드: 말이 없었으면 계속 듣는다
    }
    r.start(); if (!IOS) chimeUp(); setListening(true)
  }
  micRef.current = toggleMic
  function toggleSpeak() { const v = !speakOn; setSpeakOnState(v); setSpeakOn(v); if (v) { unlockAudio(); if ("speechSynthesis" in window) speechSynthesis.speak(new SpeechSynthesisUtterance("")) } }
  async function askPush() {
    if (await Notification.requestPermission() !== "granted") return setPushAsk(false)
    try { await subscribePush(); setPushAsk(false) } catch (e: Any) { setNote([`알림 설정 실패: ${e.message || e}`, false]) }
  }
  async function cancel(id: number) { try { await api(`/api/tasks/${id}/cancel`, { method: "POST" }); await load() } catch { setNote(["취소하지 못했습니다.", false]) } }
  async function reset() {
    if (!confirm("대화 기록을 지울까요? (사본은 서버에 남습니다)")) return
    try { await api("/api/new", { method: "POST" }); setMsgs([]); setLocal([]); setNote(null) } catch { setNote(["지우지 못했습니다.", false]) }
  }

  const done = tasks.filter(t => t.status === "done").slice(-15).reverse()
  let lastTs = 0
  const ms: Any[] = usage?.models || D.models || []
  const tokToday = (usage?.today || []).reduce((a: number, r: Any) => a + r.input + r.output, 0)
  return <div className="flex h-full min-h-0 flex-col">
    <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b px-4 py-1.5 text-xs text-muted-foreground" aria-label="AI 상태">
      {APPS.map(([a, n]) => { const st = appState(ms, a); return <span key={a} className="inline-flex items-center gap-1.5" title={STATE_KO[st]}><i className={cn("inline-block size-1.5 rounded-full", DOT[st] || "bg-bad")} />{n.split(" ")[0]}{st !== "ready" && st !== "unknown" ? ` ${STATE_KO[st]}` : ""}</span> })}
      <span className="ml-auto tabular-nums">오늘 {kfmt(tokToday)} 토큰{usage?.active ? ` · 진행 ${usage.active}` : ""} · <button className="underline underline-offset-2" onClick={() => { setText("/usage"); textRef.current = "/usage"; setTimeout(() => sendRef.current(), 0) }}>자세히</button></span>
    </div>
    {tap && <button className="fixed inset-0 z-50 bg-black/60 text-3xl text-white" onClick={() => { setTap(false); if (!rec.current) toggleMic() }}>🎙 탭하면 듣기</button>}
    <div ref={box} onScroll={e => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 140 }} className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
      <div className="mx-auto flex max-w-2xl flex-col gap-2.5">
        {!msgs.length && !local.length && <p className="py-16 text-center text-[13px] text-muted-foreground">일을 말씀해 주세요. 사진과 파일도 붙일 수 있습니다.</p>}
        {msgs.map((m, i) => {
          const gap = m.ts && m.ts - lastTs > 900; if (m.ts) lastTs = m.ts
          return <div key={i} className="flex flex-col gap-2.5">{gap && <div className="py-1 text-center text-[11px] text-muted-foreground">{day(m.ts)}</div>}<Bubble m={m} /></div>
        })}
        {local.map((m, i) => <Bubble key={"l" + i} m={m} />)}
      </div>
    </div>
    <div className="border-t bg-background px-4 pt-2 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
      <div className="mx-auto max-w-2xl">
        {active.map(t => <div key={t.id} className="mb-1.5 flex items-center gap-2 text-xs text-muted-foreground">
          <i className="inline-block size-1.5 shrink-0 animate-pulse rounded-full bg-warn" />
          <span className="min-w-0 flex-1 truncate">#{t.id} {t.status === "queued" ? "대기" : t.status === "waiting" ? "한도 대기(자동 재개)" : "진행"} · {t.step || t.routing_reason} · {dur(t.elapsed)}</span>
          <button className="underline underline-offset-2" onClick={() => cancel(t.id)}>취소</button>
        </div>)}
        {decide > 0 && <div className="mb-1.5 text-xs font-medium text-warn">확인이 필요한 작업 {decide}건 · 업무보드에서 보실 수 있습니다</div>}
        {listening && <div className="mb-1.5 flex items-center gap-2 text-xs"><i className="inline-block size-1.5 animate-pulse rounded-full bg-bad" />듣고 있습니다</div>}
        {cd > 0 && <div className="mb-1.5 flex items-center gap-3 text-xs text-muted-foreground">{cd}초 뒤 보냅니다<button className="underline underline-offset-2" onClick={stopCd}>취소</button></div>}
        {note && <div className={cn("mb-1.5 text-xs", note[1] ? "text-muted-foreground" : "text-bad")} aria-live="polite">{note[0]}</div>}
        {(imgs.length > 0 || uploading > 0) && <div className="mb-1.5 flex flex-wrap gap-1.5">
          {imgs.map(n => <span key={n} className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs">{isImg(n) ? "🖼" : "📎"} {n.slice(-14)}<button aria-label="빼기" onClick={() => setImgs(x => x.filter(y => y !== n))}><X className="size-3" /></button></span>)}
          {uploading > 0 && <span className="text-xs text-muted-foreground">올리는 중…</span>}
        </div>}
        <div className="mb-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <label className="flex items-center gap-1.5">보낼 곳
            <NativeSelect size="sm" className="h-7 max-w-52 text-xs" value={target} onChange={e => pickTarget(e.target.value)}>
              <NativeSelectOption value="auto">자동 · Claude/Codex 기획</NativeSelectOption><NativeSelectOption value="economy">빠른 텍스트 응답</NativeSelectOption>
              {APPS.map(([a, n]) => <optgroup key={a} label={n}>{ms.filter(m => m.app === a).map(m => <NativeSelectOption key={m.id} value={m.id}>{m.label}{["ready", "unknown"].includes(m.state) ? "" : " · " + STATE_KO[m.state]}</NativeSelectOption>)}</optgroup>)}
            </NativeSelect></label>
          <button className={cn("underline underline-offset-2", thread && "font-semibold text-foreground")} aria-pressed={thread} onClick={() => { const v = !thread; setThread(v); try { localStorage.setItem("donaro_thread", v ? "1" : "0") } catch { /* 이번 화면에서는 적용됨 */ } }} title="켜면 직전 대화 10개를 어느 AI에게 보내든 함께 넘겨 이어서 답하게 합니다">대화 이어가기 {thread ? "켬" : "끔"}</button>
          <label className="flex items-center gap-1.5">이어갈 작업
            <NativeSelect size="sm" className="h-7 max-w-44 text-xs" value={parent} onChange={e => setParent(e.target.value)}>
              <NativeSelectOption value="">새 작업</NativeSelectOption>{done.map(t => <NativeSelectOption key={t.id} value={String(t.id)}>#{t.id} {String(t.req).slice(0, 18)}</NativeSelectOption>)}</NativeSelect></label>
          <span className="ml-auto flex items-center gap-3">
            {pushAsk && <button className="flex items-center gap-1 underline underline-offset-2" onClick={askPush}><Bell className="size-3" />알림 켜기</button>}
            {SR && <button className={cn("flex items-center gap-1 underline underline-offset-2", live && "font-semibold text-foreground")} aria-pressed={live} onClick={toggleLive}><Headphones className="size-3" />대화 모드 {live ? "켬" : "끔"}</button>}
            <button className="flex items-center gap-1 underline underline-offset-2" aria-pressed={speakOn} onClick={toggleSpeak} aria-label="음성으로 보낸 일의 결과를 소리로 듣기">{speakOn ? <Volume2 className="size-3" /> : <VolumeX className="size-3" />}읽어 주기 {speakOn ? "켬" : "끔"}</button>
            <button className="underline underline-offset-2" onClick={reset}>새 대화</button>
          </span>
        </div>
        <div className="flex items-end gap-2">
          <input ref={file} type="file" multiple hidden onChange={e => attach(e.target.files)} />
          <Button type="button" variant="outline" size="icon" aria-label="파일 붙이기" onClick={() => file.current?.click()}><Paperclip /></Button>
          <textarea ref={area} rows={1} value={text} placeholder="도나로에게 메시지" aria-label="메시지"
            onChange={e => { setText(e.target.value); grow() }}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && matchMedia("(pointer:fine)").matches) { e.preventDefault(); send() } }}
            className="max-h-40 min-h-9 flex-1 resize-none rounded-md border bg-background px-3 py-1.5 text-[15px] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50" />
          {SR && <Button type="button" variant={listening ? "default" : "outline"} size="icon" aria-label="말로 입력" aria-pressed={listening} onClick={toggleMic}><Mic /></Button>}
          <Button type="button" size="icon" aria-label="보내기" disabled={sending || uploading > 0 || (!text.trim() && !imgs.length)} onClick={() => send()}>{sending ? <Plus className="animate-spin" /> : <ArrowUp />}</Button>
        </div>
      </div>
    </div>
  </div>
}
