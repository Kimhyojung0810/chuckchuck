// window.ChuckVoice — 바닐라 앱 화면(비전 리허설 · 글라스 화상판)에 음성 시각화를 꽂는 입구. 빌드: ../js/voice-viz.js
//
//   const h = ChuckVoice.mount(el, { kind: 'bars', read: () => rms | null, tone: 'light' })   // 발표 하단 — 내 목소리
//   const h = ChuckVoice.mount(el, { kind: 'wave', read })  // 발표 하단 — 흐르는 파형(10-13 사용자: Bars 대신 녹음하는 느낌)
//   const h = ChuckVoice.mount(el, { kind: 'qa' })                             // Q&A — 삐약이 구 / 내 Bars
//   h.update({ thinking, micOn, speakText })   // speakText: 삐약이가 새로 한 말(그 길이만큼 말하는 중)
//   h.destroy()
//
// 신호 고르기: 앱이 이미 재고 있는 음량(read) > 재기 전용 마이크(iOS 는 열지 않음) > 흉내(진짜 신호가 없을 때만).
// AI 목소리: ChuckVoice.outputFrom(<audio>) 로 TTS 를 이으면 그 소리 크기, 없으면 speechSynthesis 말하기 여부, 그것도 없으면 글 길이만큼 흉내.
import { createRoot } from 'react-dom/client'
import { VoiceViz } from './VoiceViz.jsx'
import { Waveform } from './Waveform.jsx'
import { createMicMeter, createOutputMeter } from './meter.js'
import { qaVoiceState, viewFor, speakMsFor, rmsToVolume, pickVolume } from './signal.js'

const FRAME_MS = 33 // 신호는 30fps 면 충분하다 — 그리기(rAF)는 각 테마가 한다

function createSignalAdapter() {
  const listeners = new Set()
  let last = { state: 'idle', inputVolume: 0, outputVolume: 0 }
  return {
    subscribe(fn) { listeners.add(fn); fn(last); return () => listeners.delete(fn) },
    emit(sig) { last = sig; listeners.forEach((fn) => fn(sig)) },
  }
}

let output = null // 지금 이어진 TTS 출력 재기

function outputFrom(mediaEl) {
  try { output = mediaEl ? createOutputMeter(mediaEl) : null } catch (_) { output = null }
  return !!output
}

function ttsSpeaking() {
  if (output && output.playing()) return true
  return typeof window.speechSynthesis !== 'undefined' && window.speechSynthesis.speaking
}

/** 흐르는 파형 — 앱이 재는 음량(read) 우선, 없으면 재기 전용 마이크(iOS 는 안 염), 그것도 없으면 흉내(Waveform 안) */
function mountWave(el, { read = null, tone = 'dark', label, height = 32 } = {}) {
  const root = createRoot(el)
  const meter = createMicMeter()
  const level = () => {
    const ext = typeof read === 'function' ? read() : null
    if (ext !== null && ext !== undefined) return rmsToVolume(ext)
    meter.open()
    const own = meter.read()
    return own === null ? null : rmsToVolume(own)
  }
  root.render(<Waveform active read={level} height={height} barColor={tone === 'light' ? '#0e8850' : '#3fd599'} label={label || '마이크 파형'} />)
  let dead = false
  const destroy = () => { if (dead) return; dead = true; clearInterval(watch); meter.close(); root.unmount() }
  const watch = setInterval(() => { if (!el.isConnected) destroy() }, 1000)   // 앱이 자리를 다시 그리면 스스로 정리
  return { update() {}, destroy }
}

function mount(el, opts = {}) {
  if (opts.kind === 'wave') return mountWave(el, opts)
  return mountOrb(el, opts)
}

function mountOrb(el, { kind = 'bars', read = null, barsSize = 40, orbSize = 64, tone = 'dark', label } = {}) {
  const adapter = createSignalAdapter()
  const root = createRoot(el)
  const meter = createMicMeter()
  const want = { thinking: false, micOn: kind === 'bars', speakUntil: 0 }
  let shown
  let timer = 0
  let dead = false

  const stateNow = (now) => (kind === 'bars'
    ? (want.micOn ? 'listening' : 'idle')
    : qaVoiceState({ thinking: want.thinking, micOn: want.micOn, speaking: now < want.speakUntil || ttsSpeaking() }))

  function readInput() {
    const ext = typeof read === 'function' ? read() : null
    if (ext !== null && ext !== undefined) return rmsToVolume(ext)
    const own = meter.read()
    return own === null ? null : rmsToVolume(own)
  }

  function readOutput() {
    if (!output || !output.playing()) return null
    const r = output.read()
    return r === null ? null : rmsToVolume(r)
  }

  function tick() {
    timer = 0
    if (dead) return
    // 앱이 화면을 통째로 다시 그리면(innerHTML) 자리가 떨어져 나간다 — 그때 스스로 정리한다(마이크 · 타이머 · WebGL)
    if (!el.isConnected) { handle.destroy(); return }
    const now = performance.now()
    const state = stateNow(Date.now())
    // 자리가 감춰져 있으면(display:none — 폰 하단 독 등) 그리지 않는다
    const view = el.getClientRects().length ? viewFor(kind, state) : null
    if (view !== shown) {
      shown = view
      el.dataset.voice = view || ''
      root.render(<VoiceViz view={view} adapter={adapter} barsSize={barsSize} orbSize={orbSize} tone={tone} label={label} />)
    }
    // 내가 말할 때만 재기 전용 마이크를 연다 — 앱이 이미 재고 있으면(read) 열지 않는다
    const needOwn = state === 'listening' && !(typeof read === 'function' && read() !== null)
    if (needOwn) meter.open(); else meter.close()
    if (state === 'listening') {
      const { volume } = pickVolume(readInput(), state, now)
      adapter.emit({ state, inputVolume: volume, outputVolume: 0 })
    } else if (state === 'speaking') {
      const { volume } = pickVolume(readOutput(), state, now)
      adapter.emit({ state, inputVolume: 0, outputVolume: volume })
    } else {
      adapter.emit({ state, inputVolume: 0, outputVolume: 0 })
    }
    // 아무것도 안 그리면 쉰다 — update() 가 다시 깨운다. 말하기 흉내는 끝나는 시각에 한 번 깬다
    if (view && !document.hidden) timer = setTimeout(tick, FRAME_MS)
    else if (viewFor(kind, state) && !document.hidden) timer = setTimeout(tick, 500) // 감춰진 자리 — 다시 보이는지만 가끔 본다
    else if (want.speakUntil > Date.now()) timer = setTimeout(tick, want.speakUntil - Date.now() + 10)
  }

  const wake = () => { if (!timer && !dead) timer = setTimeout(tick, 0) }
  const onVis = () => { if (!document.hidden) wake() }
  document.addEventListener('visibilitychange', onVis)
  wake()

  const handle = {
    update({ thinking, micOn, speakText } = {}) {
      if (thinking !== undefined) want.thinking = !!thinking
      if (micOn !== undefined) want.micOn = !!micOn
      if (speakText) want.speakUntil = Date.now() + speakMsFor(speakText)
      wake()
    },
    destroy() {
      if (dead) return
      dead = true
      clearTimeout(timer)
      meter.close()
      document.removeEventListener('visibilitychange', onVis)
      root.unmount()
    },
  }
  return handle
}

window.ChuckVoice = { mount, outputFrom }
