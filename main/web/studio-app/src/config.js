/* 공간 값 — main/web/design/SPACE.md §1 · §3. 단위는 미터 */
export const ROOM = 6          // 방 반폭 (벽까지)
export const CEIL = 4.2        // 천장 높이
export const EYE = 1.6         // 눈높이
export const DIST = 3.2        // 창 · 카메라 화면까지
export const FOV = 50          // 세로 시야각 (폰 62)
export const FOV_PHONE = 62

/* 네 정거장 — 지금 앱의 리허설 흐름(#/rehearsal …)이 그대로 돈다. line · chick 은 다른 정거장에 비치는 「표지」 (SPACE §6) */
export const STATIONS = [
  { key: 'upload',  name: '자료 올리기', line: '발표 자료를 올리고, 어떤 발표인지 골라요' },
  { key: 'present', name: '발표',       line: '카메라 앞에서 발표해요 — 삐약이들이 들어요' },
  { key: 'analysis', name: '발표 채점',  line: '내 말을 자료의 개념과 맞춰 채점해요' },
  { key: 'qa',      name: '질의응답',    line: '심사위원 삐약이들의 질문에 답해요' },
  { key: 'report',  name: '결과',        line: '이번 발표의 진단과 고칠 것 셋' },
  { key: 'replay',  name: '다시 보기',   line: '실제 녹음으로 근거 구간을 다시 들어요' },
  { key: 'audience', name: '청중석',     line: '삐약이 넷의 반응과 그 근거' },
  { key: 'coach',   name: '코칭',        line: '원래 말 → 까닭 → 이렇게 바꿔 말해요' },
  { key: 'practice', name: '연습',       line: '고칠 곳만 다시 · Q&A 전환점 돌아보기' },
]

/* 정거장별 조명 (SPACE §3 · DESIGN_SYSTEM v3-3) — 따뜻한 중성 빛만(10-13 리뉴얼: 초록 빛 없음, 조용한 스튜디오).
   spot: 정면 스포트(cd) · 각(rad), cove: 빛 띠 밝기, amb: 방 전체, fog: 안개 끝(m) */
export const LIGHT = [
  { color: '#FFFFFF', spot: 160, angle: .7, cove: .8, amb: 2.6, fog: 30 },
  { color: '#FFFFFF', spot: 180, angle: .55, cove: .35, amb: 2.3, fog: 28 },
  { color: '#FFFFFF', spot: 150, angle: .75, cove: .7, amb: 2.5, fog: 30 },
  { color: '#FFFFFF', spot: 170, angle: .6, cove: .5, amb: 2.4, fog: 28 },
  { color: '#FFFFFF', spot: 170, angle: .8, cove: .9, amb: 2.8, fog: 32 },
  { color: '#FFFFFF', spot: 170, angle: .8, cove: .9, amb: 2.8, fog: 32 },
  { color: '#FFFFFF', spot: 150, angle: .8, cove: .7, amb: 2.4, fog: 30 },
  { color: '#FFFFFF', spot: 170, angle: .8, cove: .9, amb: 2.8, fog: 32 },
  { color: '#FFFFFF', spot: 170, angle: .8, cove: .9, amb: 2.8, fog: 32 },
]

/* SPACE v3 — 시점은 고정, 창이 곡선 위를 미끄러진다 (Horizon OS 방식) */
export const SPACING = 64       // 곡선 위 창 간격(°) — 이웃 창이 화면 가장자리에 살짝 비친다
/* 미끄러짐 = easeInOutSine 곡선 (10-13 사용자: 「너무 빠르다, 스무스하게」 — 스프링은 출발이 갑작스러웠다).
   걸리는 시간 = 한 칸까지 SLIDE_MIN + SLIDE_ONE × 칸, 한 칸 넘으면 칸마다 + SLIDE_MORE. 한 칸 = 1.5초 */
export const SLIDE_MIN = .5
export const SLIDE_ONE = 1.0
export const SLIDE_MORE = .35
export const slideSeconds = (cells) => {
  const d = Math.abs(cells)
  return SLIDE_MIN + SLIDE_ONE * Math.min(1, d) + SLIDE_MORE * Math.max(0, d - 1)
}
export const easeInOutSine = (p) => -(Math.cos(Math.PI * p) - 1) / 2
export const HIDE_DOM = 60      // 정면에서 이만큼(°) 비켜나면 DOM 을 감춘다 (CSS 3D 뒤집힘 방지)

export const deg = (d) => d * Math.PI / 180
export const mod4 = (n) => ((n % 4) + 4) % 4
/** 정거장 k 의 방향(°) — 오른쪽(시계)으로 90° 씩 */
export const stationAngle = (k) => k * 90
/** 방향 θ(°) 로 거리 r 만큼 간 점 (카메라 원점 기준, y 는 따로) */
export const toward = (theta, r) => [Math.sin(deg(theta)) * r, -Math.cos(deg(theta)) * r]
