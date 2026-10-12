/* 매 프레임 읽고 쓰는 값 — React 상태가 아니라 한 객체(다시 그리기 없이). SPACE v3: 시점 고정, 곡선 위치 f 만 움직인다 */
export const rig = {
  at: 0,            // 목표 단계 (0..3)
  f: 0,             // 곡선의 지금 위치(소수) — at 을 스프링으로 따라간다
  drag: 0,          // 끌기 중 덧붙이는 칸 수(소수)
  dragging: false,
  motion: 0,        // 움직이는 정도 0..1 — 이동 중 줌 아웃 · 멈추면 집중 (10-13 사용자)
  reduced: typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches,
}
