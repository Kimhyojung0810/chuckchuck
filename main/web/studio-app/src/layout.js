/* 정거장마다 정면에 무엇을 어디에 — 순수 계산 (CSS px, 화면 가운데가 원점, x 오른쪽 · y 아래로 +). SPACE §2-3 · DESIGN_SYSTEM v3-5
   10-13 리뉴얼: 「업로드 창은 내용 크기 — 배경이 둘레로 드러나게」 「발표는 웹캠이 가장 크고 PPT 는 작은 PiP」
   「Q&A 는 웹캠 중심 + 떠 있는 목소리」 「분석은 독립 장면」 「리포트는 읽기 우선」
   0 자료 올리기  내용 크기 창(가운데)
   1 발표        웹캠(앱 창)을 위에 넓게 · 그 위 작은 PPT 창(PiP) · 아래 앞줄 관중 · 맨 아래 조작줄
   2 발표 채점    오른쪽 크게 개념 그래프 채점판(ui/ScoreBoard) · 왼쪽 작은 창에 앱의 실제 진행 단계
   3 질의응답     웹캠(앱 창)이 화면의 약 80% — 삐약이 · 질문 · 생각의 흔적은 앱 안 한 겹(10-13 생각 엮기)
   4 리포트      크게 — 읽기 우선 */

const HUD = 56          // 위 HUD 높이
const DOCK = 64         // ② 조작줄 높이 (css .sx-dock)
const EDGE = 16         // 화면 가장자리 여백

const clamp = (v, a, b) => Math.max(a, Math.min(b, v))

/** 가운데 창 하나 */
function single(vp, fw, fh, maxW, maxH) {
  const w = Math.round(Math.min(maxW, vp.w * (vp.phone ? 0.94 : fw)))
  const h = Math.round(Math.min(maxH, vp.h * (vp.phone ? 0.8 : fh)))
  return { app: { x: 0, y: 0, w, h } }
}

/** ① 자료 올리기 — 내용 높이(fitH)에 맞춘다. 모르면 기본 크기 */
function upload(vp, fitH) {
  const w = Math.round(Math.min(860, vp.w * (vp.phone ? 0.94 : 0.58)))
  const maxH = vp.h * (vp.phone ? 0.8 : 0.78)
  const h = Math.round(fitH ? clamp(fitH, 280, maxH) : Math.min(560, maxH))
  return { app: { x: 0, y: Math.round(HUD / 4), w, h } }
}

/** ② 발표 — 웹캠이 가장 크다. PPT 는 그 위 작은 떠 있는 창(PiP, 「크게」 로 넓힌다). 아래 앞줄 관중 · 조작줄 */
function present(vp, big = false) {
  const dockTop = vp.h / 2 - EDGE - DOCK
  const top = -vp.h / 2 + HUD + 12
  const seat = Math.round(clamp(vp.h * 0.15, 110, 150))
  const floor = dockTop - seat - 14                      // 웹캠 아래 끝 — 그 아래가 앞줄 관중
  const hc = Math.round(floor - top)
  const wc = Math.round(Math.min(vp.w * 0.92, hc * 2.2))
  const app = { x: 0, y: Math.round(top + hc / 2), w: wc, h: hc }
  const cap = 38
  let ow = Math.round(wc * (big ? 0.46 : 0.3))
  let oh = Math.round(ow * 9 / 16) + cap
  if (oh > hc - 40) { oh = hc - 40; ow = Math.round((oh - cap) * 16 / 9) }
  const overlay = { left: 20, top: 20, w: ow, h: oh }   // 웹캠 창 안 좌표 — 왼쪽 위(얼굴은 가운데)
  const left = -wc / 2
  const listener = { x: Math.round(left + seat * 1.3), y: Math.round(dockTop - 10 - seat / 2), w: Math.round(seat * 2.6), h: seat }
  return {
    app, overlay, listener, total: wc, floor, seat, top, dockTop,
    dock: { left: Math.round(vp.w / 2 + left), width: Math.round(wc), top: Math.round(vp.h / 2 + dockTop) },
  }
}

/** ③ 발표 채점 — 개념 그래프가 주인공(오른쪽 크게, ui/ScoreBoard), 앱의 실제 진행 단계는 왼쪽 작은 창 */
function analysis(vp) {
  const w = Math.round(Math.min(400, vp.w * 0.28))
  const h = Math.round(Math.min(560, vp.h * 0.64))
  const left = -vp.w / 2 + EDGE + 32
  const app = { x: Math.round(left + w / 2), y: Math.round(HUD / 4 - 20), w, h }
  const gx0 = left + w + 28, gx1 = vp.w / 2 - EDGE - 32
  const gy0 = -vp.h / 2 + HUD + 16, gy1 = vp.h / 2 - EDGE - 24
  const graph = { x: Math.round((gx0 + gx1) / 2), y: Math.round((gy0 + gy1) / 2), w: Math.round(gx1 - gx0), h: Math.round(gy1 - gy0) }
  return { app, graph }
}

/**
 * ④ 질의응답 — 웹캠이 무대 (10-13 Q&A 「생각 엮기」 브리프: 화면의 75~85%, 질문이 바뀌어도 크기 그대로).
 * 삐약이 · 목소리 구 · 질문 · 흔적 · 「다른 주제로」 는 앱 안 한 겹(js/qa_weave.js)이 맡는다 — 바깥 심사위원 자리는 없다.
 */
function qa(vp) {
  const w = Math.round(vp.w * 0.9)
  const h = Math.round(Math.min(vp.h * 0.88, vp.h - HUD - 8 - EDGE))
  const app = { x: 0, y: Math.round(-vp.h / 2 + HUD + 8 + h / 2), w, h }
  return { app }
}

/**
 * @param k   정거장 (keys.js ST)
 * @param vp  { w, h, phone }
 * @param opt { fitH: 업로드 내용 높이, bigSlide: PPT 창 크게 }
 */
export function stationLayout(k, vp, opt = {}) {
  if (k === 0) return upload(vp, opt.fitH)
  if (vp.phone) return single(vp, 0.94, 0.8, 1120, 760)
  if (k === 1) return present(vp, opt.bigSlide)
  if (k === 2) return analysis(vp)
  if (k === 3) return qa(vp)
  return single(vp, 0.72, 0.8, 1240, 860)
}

/** 화면 좌표의 앱 창 자리 (iframe 이 멈췄을 때 정확히 겹칠 자리) */
export function appRect(L, vp) {
  const a = L.app
  return { left: Math.round(vp.w / 2 + a.x - a.w / 2), top: Math.round(vp.h / 2 + a.y - a.h / 2), width: a.w, height: a.h }
}
