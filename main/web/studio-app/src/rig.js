/* 매 프레임 읽고 쓰는 값 — React 상태가 아니라 한 객체(다시 그리기 없이). SPACE v3: 시점 고정, 곡선 위치 f 만 움직인다 */
export const rig = {
  at: 0,            // 목표 단계 (0..3)
  f: 0,             // 곡선의 지금 위치(소수) — at 을 easeInOutSine 으로 따라간다 (CameraRig)
  tween: null,      // { from, to, t0, dur } — 끌기를 놓았을 때 짧게 돌아오기
  fade: null,       // { from, to, t0, p } — 단계 전환: 제자리 겹쳐 바꾸기 (CameraRig, 10-17 멀미)
  shown: null,      // 마지막으로 전환을 시작한 단계
  settled: true,
  hold: false,      // ③ 발표 채점 연출 중 — 앱이 질의응답으로 넘어가도 끝날 때까지(최대 8초) 기다린다 (ui/ScoreBoard)    // 멈춰 있나 — 멈췄을 때만 실제 앱(iframe)을 정면 창에 띄운다
  drag: 0,          // 끌기 중 덧붙이는 칸 수(소수)
  dragging: false,
  motion: 0,        // 움직이는 정도 0..1 — 이동 중 줌 아웃 · 멈추면 집중 (10-13 사용자)
  reduced: typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches,
}
