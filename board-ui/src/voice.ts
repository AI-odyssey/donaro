// 도나로 음성·알림 보조. 이전 화면(static/index.html)의 동작을 그대로 옮겼다: 서버 TTS(/api/tts)로 읽어 주기, 효과음, 푸시 알림, 화면 보는 중 신호.
/* eslint-disable @typescript-eslint/no-explicit-any */
const W = window as any

export const SR = W.SpeechRecognition || W.webkitSpeechRecognition
export const IOS = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)

// 아이폰은 터치 때 한 번 재생해 둔 플레이어만 나중에 소리를 낼 수 있다
const player = new Audio()
const SILENT = (() => {
  const b = new Uint8Array(46), v = new DataView(b.buffer), s = (o: number, t: string) => [...t].forEach((c, i) => (b[o + i] = c.charCodeAt(0)))
  s(0, "RIFF"); v.setUint32(4, 38, true); s(8, "WAVEfmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true)
  v.setUint32(24, 8000, true); v.setUint32(28, 16000, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); s(36, "data"); v.setUint32(40, 2, true)
  return URL.createObjectURL(new Blob([b], { type: "audio/wav" }))
})()
export function unlockAudio() { if (player.dataset.ok) return; player.src = SILENT; player.play().then(() => (player.dataset.ok = "1")).catch(() => {}) }

function speakBrowser(text: string) {
  if (!("speechSynthesis" in window)) return
  const m = text.match(/\[결론\]\s*(.+)/), line = (m ? m[1] : text.split("\n")[0]).replace(/[`*_#>|[\]]/g, "").slice(0, 220)
  const u = new SpeechSynthesisUtterance(line); u.lang = "ko-KR"; speechSynthesis.cancel(); speechSynthesis.speak(u)
}
async function speakOne(text: string) {
  try {
    const r = await fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) })
    if (!r.ok) throw new Error()
    const old = player.src; player.src = URL.createObjectURL(await r.blob())
    if (old.startsWith("blob:") && old !== SILENT) URL.revokeObjectURL(old)
    await player.play()
    const cap = Math.min(120000, (player.duration > 0 && isFinite(player.duration) ? player.duration : 60) * 1000 + 4000)
    await new Promise<void>(res => { player.onended = player.onerror = player.onpause = player.onabort = player.onemptied = () => res(); setTimeout(res, cap) })
    return
  } catch { /* 서버 목소리가 안 되면 브라우저 기본 음성 */ }
  speakBrowser(text)
}
let chain: Promise<unknown> = Promise.resolve()
export function speak(text: string) { chain = chain.then(() => speakOne(text)).catch(() => {}); return chain } // 여러 건이 한꺼번에 끝나도 차례로 읽는다

// 효과음: 듣기 시작(올라가는 음) / 끝(내려가는 음)
let ac: AudioContext | null = null
function tone(freqs: number[], step = 0.09, vol = 0.12) {
  try {
    ac = ac || new (W.AudioContext || W.webkitAudioContext)(); if (ac!.state === "suspended") ac!.resume()
    const a = ac!, t0 = a.currentTime
    freqs.forEach((f, i) => {
      const o = a.createOscillator(), g = a.createGain(), t = t0 + i * step
      o.type = "sine"; o.frequency.value = f
      g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(vol, t + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t + step * 1.6)
      o.connect(g).connect(a.destination); o.start(t); o.stop(t + step * 1.7)
    })
  } catch { /* 소리가 안 나도 동작은 계속한다 */ }
}
export const chimeUp = () => tone([660, 880]), chimeDown = () => tone([880, 660])

// 작업 결과를 소리로 읽을 목록(음성으로 맡긴 작업만). 새로고침해도 남도록 저장
const KEY = "speakTasks"
export const speakTasks = (() => { try { return new Set<number>(JSON.parse(localStorage.getItem(KEY) || "[]")) } catch { return new Set<number>() } })()
export const saveSpeakTasks = () => { try { localStorage.setItem(KEY, JSON.stringify([...speakTasks].slice(-30))) } catch { /* 저장 못 해도 무방 */ } }
export const getSpeakOn = () => { try { return localStorage.getItem("speak2") === "1" } catch { return false } }
export const setSpeakOn = (v: boolean) => { try { localStorage.setItem("speak2", v ? "1" : "0") } catch { /* */ } }

// 앱을 보고 있는지 서버에 알린다: 안 보고 있을 때 답이 끝나면 서버가 푸시 알림을 보낸다
const CID = (() => { try { let c = localStorage.getItem("cid"); if (!c) { c = Math.random().toString(36).slice(2) + Date.now().toString(36); localStorage.setItem("cid", c) } return c } catch { return "anon" } })()
const tellVisible = (v: boolean) => fetch("/api/visible", { method: "POST", keepalive: true, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ v, cid: CID }) }).catch(() => {})
export function startPresence() {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {})
  const vis = () => tellVisible(!document.hidden), hide = () => tellVisible(false)
  document.addEventListener("visibilitychange", vis); addEventListener("pagehide", hide); vis()
  const id = setInterval(() => { if (!document.hidden) tellVisible(true) }, 20000) // 신호가 끊기면 서버가 45초 뒤 안 보는 것으로 본다
  return () => { document.removeEventListener("visibilitychange", vis); removeEventListener("pagehide", hide); clearInterval(id) }
}

// 푸시 알림: 아이폰은 홈 화면에 추가한 앱에서, 버튼을 눌러 허락해야 켜진다
export async function subscribePush() {
  const reg = await navigator.serviceWorker.ready
  const { key } = await (await fetch("/api/push/key")).json()
  const raw = Uint8Array.from(atob(key.replace(/-/g, "+").replace(/_/g, "/") + "==".slice(0, (4 - (key.length % 4)) % 4)), (c: string) => c.charCodeAt(0))
  const sub = (await reg.pushManager.getSubscription()) || (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: raw }))
  await fetch("/api/push/sub", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...sub.toJSON(), cid: CID }) })
}
export const pushSupported = () => "PushManager" in window && "Notification" in window && "serviceWorker" in navigator
