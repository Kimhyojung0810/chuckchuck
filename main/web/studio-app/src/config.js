/* 공간 값 — main/web/design/SPACE.md §1 · §3. 단위는 미터 */
export const ROOM = 6          // 방 반폭 (벽까지)
export const CEIL = 4.2        // 천장 높이
export const EYE = 1.6         // 눈높이
export const DIST = 3.2        // 창 · 카메라 화면까지
export const FOV = 50          // 세로 시야각 (폰 62)
export const FOV_PHONE = 62

export const STATIONS = [
  { key: 'upload',  name: '자료 올리기' },
  { key: 'present', name: '발표' },
  { key: 'qa',      name: '질의응답' },
  { key: 'report',  name: '리포트' },
]

/* 정거장별 조명 (SPACE §3). spot: 지금 벽 스포트 세기(cd) · 각(rad), cove: 천장 띠 밝기, amb: 방 전체, fog: 안개 끝(m) */
export const LIGHT = [
  { color: '#E8E4DC', spot: 260, angle: .62, cove: 1.0, amb: 1.6, fog: 24 },
  { color: '#C9A96E', spot: 420, angle: .5, cove: .12, amb: .6, fog: 14 },
  { color: '#D9B98A', spot: 300, angle: .5, cove: .5, amb: 1.1, fog: 18 },
  { color: '#F2EDE4', spot: 300, angle: .78, cove: 1.0, amb: 2.1, fog: 28 },
]

/* SPACE v3 — 시점은 고정, 창이 곡선 위를 미끄러진다 (Horizon OS 방식) */
export const SPACING = 64       // 곡선 위 창 간격(°) — 이웃 창이 화면 가장자리에 살짝 비친다
export const SLIDE = .2         // 미끄러짐 스프링 반응 시간(s) — .6~.7초에 자리 잡는다, 튕김 없음
export const HIDE_DOM = 60      // 정면에서 이만큼(°) 비켜나면 DOM 을 감춘다 (CSS 3D 뒤집힘 방지)

export const deg = (d) => d * Math.PI / 180
export const mod4 = (n) => ((n % 4) + 4) % 4
/** 정거장 k 의 방향(°) — 오른쪽(시계)으로 90° 씩 */
export const stationAngle = (k) => k * 90
/** 방향 θ(°) 로 거리 r 만큼 간 점 (카메라 원점 기준, y 는 따로) */
export const toward = (theta, r) => [Math.sin(deg(theta)) * r, -Math.cos(deg(theta)) * r]
