/* 카메라 리그가 매 프레임 읽고 쓰는 값 — React 상태가 아니라 한 객체(다시 그리기 없이) */
export const rig = {
  yawTarget: 0,     // 누적 목표 각도(°) — 다음 단계는 +90
  yaw: 0,           // 지금 각도(°)
  peek: 0,          // 끌어서 둘러보기(°)
  lookX: 0, lookY: 0,   // 마우스 시선 (-1..1)
  at: 0,            // 지금(목표) 정거장
  reduced: typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches,
}
