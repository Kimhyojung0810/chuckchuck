// 음성 시각화 신호 — 순수 함수만 (DOM · 오디오 없음). etc/tests/js/voice_signal.smoke.mjs 가 브라우저 없이 검사한다.
// 쓰는 곳: ./driver.js (window.ChuckVoice) — 발표 하단 Bars · Q&A 삐약이 구(GradientOrb)/Bars

/** 마이크 RMS 를 0~1 음량으로 — 말소리 범위(-58 ~ -14 dBFS)를 펼친다. 조용한 방의 잡음은 0 에 붙는다 */
export const FLOOR_DB = -58
export const CEIL_DB = -14

export function clamp01(x) {
  return x < 0 ? 0 : x > 1 ? 1 : x
}

export function rmsToVolume(rms) {
  if (!(rms > 0)) return 0
  const db = 20 * Math.log10(rms)
  return clamp01((db - FLOOR_DB) / (CEIL_DB - FLOOR_DB))
}

/**
 * Q&A 에서 지금 보일 상태. 생각(질문 만들기 · 답 판정) > 내가 말하기 > 삐약이가 말하기 > 쉼.
 * 내가 말하기 시작하면 삐약이의 말하기 연출은 접는다 — 말을 끊는 쪽이 이긴다.
 */
export function qaVoiceState({ thinking = false, micOn = false, speaking = false } = {}) {
  if (thinking) return 'thinking'
  if (micOn) return 'listening'
  if (speaking) return 'speaking'
  return 'idle'
}

/** 상태별 그림 — Bars(내 목소리) · 구(삐약이의 생각 · 말 — GradientOrb) · 없음(그리지 않는다 — WebGL 을 쉬게) */
export function viewFor(kind, state) {
  if (kind === 'bars') return state === 'idle' ? null : 'bars'
  if (state === 'listening') return 'bars'
  if (state === 'thinking' || state === 'speaking') return 'orb'
  return null
}

/** 삐약이가 한 말을 소리 내 읽는 데 걸리는 시간(ms) — 한국어 낭독 ~7자/초, 1.6~7초 */
export function speakMsFor(text) {
  const n = String(text || '').replace(/\s+/g, '').length
  return Math.round(Math.min(7000, Math.max(1600, (n / 7) * 1000)))
}

/**
 * 실제 음성 신호가 없을 때만 쓰는 흉내 음량 — 음절처럼 오르내린다(정해진 시각이면 같은 값).
 * listening 은 낮게, speaking 은 높게. 그 밖의 상태는 0.
 */
export function simulatedVolume(state, tMs) {
  if (state !== 'listening' && state !== 'speaking') return 0
  const t = tMs / 1000
  const syllable = 0.5 + 0.5 * Math.sin(t * 2 * Math.PI * 3.1)
  const phrase = 0.5 + 0.5 * Math.sin(t * 2 * Math.PI * 0.37 + 1.3)
  const flutter = 0.5 + 0.5 * Math.sin(t * 2 * Math.PI * 7.3 + 0.4)
  const v = 0.55 * syllable * (0.4 + 0.6 * phrase) + 0.15 * flutter
  return state === 'speaking' ? clamp01(0.25 + v * 0.75) : clamp01(0.12 + v * 0.4)
}

/** 신호 고르기 — 진짜 값(null 아님)이 있으면 그것, 없을 때만 흉내 */
export function pickVolume(real, state, tMs) {
  if (real !== null && real !== undefined && Number.isFinite(real)) return { volume: clamp01(real), simulated: false }
  return { volume: simulatedVolume(state, tMs), simulated: true }
}
