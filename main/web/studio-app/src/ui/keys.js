/* 스튜디오 ↔ 앱 흐름 — 순수 함수 (etc/tests/js/studio_flow.smoke.mjs 가 브라우저 없이 검사한다). SPACE §6 · §7 */

/** 앱 주소 → 정거장 (0 자료 올리기 · 1 발표 · 2 질의응답 · 3 리포트). 흐름 밖(#/home · #/)이면 -1 */
export function stationOfHash(hash) {
  const h = String(hash || '').replace(/^#\/?/, '')
  if (/^rehearsal\/(new|wait)(\/|$)/.test(h)) return 1
  if (/^rehearsal\/qa(\/|$)/.test(h)) return 2
  if (/^(rehearsal\/)?report(\/|$)/.test(h)) return 3
  if (/^rehearsal(\/|$)/.test(h)) return 0
  return -1
}

/**
 * 키 하나를 스튜디오가 맡을지. 'next' = 지금 화면의 주 버튼, 'back' = 앱의 이전 화면, null = 앱(또는 브라우저)에 맡긴다.
 * - 글 입력 중이면 그 칸의 것
 * - ② 발표 화면은 ← → 가 슬라이드 넘김(클리커) — 앱 안 초점이면 앱이, 바깥 초점이면 스튜디오가 앱의 넘김 단추를 누른다. Enter 는 맡기지 않는다
 * - Enter 는 버튼 · 링크에 초점이 있으면 그것을 누르게 둔다
 * - 조합키(⌘ · Ctrl · Alt · Shift)는 브라우저 것
 */
export function keyAction({ key, station, typing = false, onControl = false, mod = false, inApp = false }) {
  if (mod || typing) return null
  // ② 발표: 앱 안에 초점이 있으면 앱이 직접 넘긴다(클리커 · 키보드). 스튜디오(바깥)에 초점이 있으면 넘김을 앱에 건넨다 —
  // 10-13 사용자 「발표 시작하면 넘길 수 있게」: 바깥 조작줄을 누른 뒤엔 방향키가 앱에 닿지 않았다
  if (station === 1) {
    if (inApp) return null
    if (key === 'ArrowRight' || key === 'PageDown') return 'slideNext'
    if (key === 'ArrowLeft' || key === 'PageUp') return 'slidePrev'
    return null
  }
  if (key === 'ArrowRight') return 'next'
  if (key === 'Enter') return onControl ? null : 'next'
  if (key === 'ArrowLeft') return 'back'
  return null
}

/** 앱 안 이동 기록 — 앞으로 가면 쌓고, 바로 앞 주소로 돌아오면 덜어낸다(브라우저 뒤로 가기와 같다). ← 는 둘 이상일 때만 */
export function trackHash(stack, hash) {
  if (stack.length && stack[stack.length - 1] === hash) return stack
  if (stack.length > 1 && stack[stack.length - 2] === hash) return stack.slice(0, -1)
  return [...stack, hash]
}
