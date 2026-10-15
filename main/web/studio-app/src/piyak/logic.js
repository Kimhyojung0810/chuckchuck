/* 삐약이 — 그림과 떨어진 계산 (브라우저 없이 node 로 확인할 수 있게). 단위는 삐약이 viewBox(100) */

/** 눈이 움직이는 한계 — 눈동자가 얼굴 밖으로 나가지 않는 만큼 */
export const GAZE_X = 4.2      // 10-13 사용자: 눈 움직임을 더 크게 (2.6 → 4.2)
export const GAZE_Y = 3.1

/**
 * 커서를 보는 방향 — 삐약이 가운데(cx, cy)에서 커서(px, py)까지. 가까우면 덜, 멀면 끝까지 본다.
 * reach: 이만큼(px) 떨어지면 한계의 ~70% 까지 돌아간다 (삐약이 크기에 맞춘다)
 */
export function gaze(px, py, cx, cy, reach = 240) {
  const dx = px - cx
  const dy = py - cy
  const d = Math.hypot(dx, dy)
  if (!Number.isFinite(d) || d < 1) return { x: 0, y: 0 }
  const pull = d / (d + reach)                  // 0 → 1 로 부드럽게 (멀어도 한계를 넘지 않는다)
  return { x: (dx / d) * pull * GAZE_X, y: (dy / d) * pull * GAZE_Y }
}

/** 마이크 RMS(0..~.3) → 움직임 세기 0..1 — 음성 구(VoiceOrb)와 같은 눈금 (×7) */
export function voiceK(rms) {
  if (!Number.isFinite(rms) || rms <= 0) return 0
  return Math.min(1, rms * 7)
}

/** 소리가 조용할 때 바닥 흔들림을 떼어 낸다 — 방 소음에 삐약이가 떨지 않게 */
export const VOICE_FLOOR = 0.06
export function voiceLift(k) {
  return k <= VOICE_FLOOR ? 0 : (k - VOICE_FLOOR) / (1 - VOICE_FLOOR)
}

export const MOODS = ['neutral', 'happy', 'curious', 'excited', 'grumpy']

/**
 * 지금 표정 — 정해 준 표정(fixed)이 있으면 그것, 아니면 상황에서 고른다.
 * 쓰다듬은 직후 > 크게 말함 > 듣는 중 · 커서가 위에 있음 > 평소
 */
export function pickMood({ fixed, poked, loud, listening, hovered }) {
  if (fixed && MOODS.includes(fixed)) return fixed
  if (poked) return 'happy'
  if (loud) return 'excited'
  if (listening || hovered) return 'curious'
  return 'neutral'
}
