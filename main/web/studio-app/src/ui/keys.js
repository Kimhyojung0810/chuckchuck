/* 스튜디오 ↔ 앱 흐름 — 순수 함수 (etc/tests/js/studio_flow.smoke.mjs 가 브라우저 없이 검사한다). SPACE §6 · §7 */

/** 정거장 번호 — 0 자료 올리기 · 1 발표 · 2 분석 · 3 질의응답 · 4~8 리포트(결과 · 다시 보기 · 청중석 · 코칭 · 연습) (config.STATIONS 와 같은 순서)
 *  10-16 사용자 「리포트 탭을 하나만 만드는 게 아니라 여러 개로 분리」 — 리포트 2.0(js/report_v2.js)의 뿌리 화면 하나 = 정거장 하나 */
export const ST = { upload: 0, present: 1, analysis: 2, qa: 3, report: 4, replay: 5, audience: 6, coach: 7, practice: 8 }
/** 리포트 정거장 ↔ 리포트 2.0 뿌리 화면 (report_v2.js tabs 와 같은 순서) */
export const REPORT_TABS = ['home', 'replay', 'audience', 'coach', 'practice']
export const isReport = (k) => k >= ST.report

/** 앱 주소 → 정거장. 흐름 밖(#/home · #/)이면 -1. 분석 기다림은 발표와 같은 주소(#/rehearsal/new)라 stationOf 가 화면으로 가른다 */
export function stationOfHash(hash) {
  const h = String(hash || '').replace(/^#\/?/, '')
  if (/^rehearsal\/(new|wait)(\/|$)/.test(h)) return ST.present
  if (/^rehearsal\/qa(\/|$)/.test(h)) return ST.qa
  if (/^(rehearsal\/)?report(\/|$)/.test(h)) return ST.report
  if (/^rehearsal(\/|$)/.test(h)) return ST.upload
  return -1
}

/** 주소 + 지금 떠 있는 층 → 정거장. wait: 분석 기다림 층(#bqStage[data-screen=wait])이 떠 있나 · rv2Root: 리포트 2.0 이 지금 보이는 뿌리 화면 */
export function stationOf({ hash, wait = false, rv2Root = '' }) {
  const k = stationOfHash(hash)
  if (k === ST.present && wait) return ST.analysis
  if (k === ST.report) { const i = REPORT_TABS.indexOf(rv2Root); return i > 0 ? ST.report + i : ST.report }
  return k
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
  if (station === ST.present) {
    if (inApp) return null
    if (key === 'ArrowRight' || key === 'PageDown') return 'slideNext'
    if (key === 'ArrowLeft' || key === 'PageUp') return 'slidePrev'
    return null
  }
  // 리포트 정거장끼리는 → ← 가 옆 탭(결과 ↔ 다시 보기 ↔ 청중석 ↔ 코칭 ↔ 연습). 리포트 안엔 「다음」 주 버튼이 없다
  if (isReport(station)) {
    if (key === 'ArrowRight') return station < ST.report + REPORT_TABS.length - 1 ? 'tabNext' : null
    if (key === 'ArrowLeft') return station > ST.report ? 'tabPrev' : null
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
