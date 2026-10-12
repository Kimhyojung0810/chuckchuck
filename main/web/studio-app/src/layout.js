/* 정거장마다 정면에 무엇을 어디에 — 순수 계산 (CSS px, 화면 가운데가 원점, x 오른쪽 · y 아래로 +). SPACE §2-3
   10-13 사용자: 「발표할 때 PPT 너무 작다 · 배경을 적극적으로 · 내 말 듣고 크다 작다 하는 삐약이는 관중으로 · 질의응답도 비슷하게」
   ① ④  앱 창 하나(가운데)
   ②    카메라(앱 창)를 위에 넓게 + 그 위에 겹친 큰 자료 창 · 아래 앞줄에 큰 관중 삐약이(말 빠르기 · 크기 반응) · 맨 아래 조작줄
   ③    앱 창(질문 · 답 · 카메라)을 오른쪽으로 · 왼쪽 앞에 큰 심사위원 삐약이(질문하고 생각하고 말한다) */

const HUD = 56          // 위 HUD 높이
const DOCK = 64         // ② 조작줄 높이 (css .sx-dock)
const EDGE = 16         // 화면 가장자리 여백

/** 가운데 창 하나 (① ④ · 폰은 모든 정거장) */
function single(vp) {
  const w = Math.round(Math.min(1120, vp.w * (vp.phone ? 0.94 : 0.66)))
  const h = Math.round(Math.min(760, vp.h * (vp.phone ? 0.8 : 0.74)))
  return { app: { x: 0, y: 0, w, h } }
}

/** ② 발표 — 카메라(앱 창)를 위에 가로로 넓게, 발표 자료는 그 카메라 위에 겹친다(왼쪽 큰 유리 창). 아래는 관중석 · 조작줄.
 *  10-13 사용자: 「발표 자료를 사람 카메라에 overlay 해야 해」 (나란히 둔 무대 스크린은 되돌렸다) · 「PPT 너무 작다」 */
function present(vp) {
  const dockTop = vp.h / 2 - EDGE - DOCK
  const top = -vp.h / 2 + HUD + 14
  const seat = Math.round(Math.max(130, Math.min(200, vp.h * 0.2)))
  const floor = dockTop - seat - 18                      // 카메라 아래 끝 — 그 아래가 앞줄 관중
  const hc = Math.round(floor - top)
  const wc = Math.round(Math.min(vp.w * 0.92, hc * 2.4))
  const app = { x: 0, y: Math.round(top + hc / 2), w: wc, h: hc }
  // 카메라 위 자료 창 — 카메라 폭의 44%(얼굴은 가운데라 왼쪽에), 16:9 + 제목 띠, 세로 가운데
  const cap = 40
  let ow = Math.round(wc * 0.44)
  let oh = Math.round(ow * 9 / 16) + cap
  if (oh > hc - 36) { oh = hc - 36; ow = Math.round((oh - cap) * 16 / 9) }
  const overlay = { left: 18, top: Math.round((hc - oh) / 2), w: ow, h: oh }   // 카메라 창 안 좌표
  const left = -wc / 2
  const listener = { x: Math.round(left + seat * 1.3), y: Math.round(dockTop - 10 - seat / 2), w: Math.round(seat * 2.6), h: seat }
  return {
    app, overlay, listener, total: wc, floor, seat, top, dockTop,
    dock: { left: Math.round(vp.w / 2 + left), width: Math.round(wc), top: Math.round(vp.h / 2 + dockTop) },
  }
}

/** ③ 질의응답 — 앱 창을 오른쪽으로, 왼쪽 앞에 심사위원 */
function qa(vp) {
  const w = Math.round(Math.min(1080, vp.w * 0.6))
  const h = Math.round(Math.min(760, vp.h * 0.76))
  const room = vp.w / 2 - w / 2                          // 창 양옆 남는 폭(가운데일 때)
  const shift = Math.round(Math.min(room - EDGE, vp.w * 0.11))
  const app = { x: shift, y: 0, w, h }
  const seat = Math.round(Math.min(260, vp.h * 0.3))
  const jh = Math.round(seat * 1.9)
  // 아래 끝을 화면 아래 여백에 맞춘다 — 이름 줄이 화면 밖으로 잘렸다
  const judge = { x: Math.round(-vp.w / 2 + EDGE + seat * 0.75), y: Math.round(vp.h / 2 - EDGE - 12 - jh / 2), w: Math.round(seat * 1.5), h: jh }
  return { app, judge, seat }
}

export function stationLayout(k, vp) {
  if (vp.phone) return single(vp)
  if (k === 1) return present(vp)
  if (k === 2) return qa(vp)
  return single(vp)
}

/** 화면 좌표의 앱 창 자리 (iframe 이 멈췄을 때 정확히 겹칠 자리) */
export function appRect(L, vp) {
  const a = L.app
  return { left: Math.round(vp.w / 2 + a.x - a.w / 2), top: Math.round(vp.h / 2 + a.y - a.h / 2), width: a.w, height: a.h }
}
