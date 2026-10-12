/* 알 껍데기 — 알(Egg.jsx) · 껍데기 바지 · 껍데기 모자(Piyak shell prop)가 같은 알 모양 · 같은 깨진 줄을 쓴다. 단위는 삐약이 viewBox(100) */

export const EGG = 'M50 14C32 14 19 40 19 59c0 18 13 29 31 29s31-11 31-29C81 40 68 14 50 14z'
/** 알을 가로로 가르는 깨진 줄 (y 52 ~ 58 사이를 지그재그) */
export const ZIG = 'M15 52l7 5 6-6 6 6 6-6 6 6 6-6 6 6 6-6 6 6 6-5 6 4'
// 깨진 줄은 x 20 에서 끝난다 — 그 왼쪽은 수평으로 0 까지 이어야 알 왼쪽 끝이 세로로 잘리지 않는다
const TOP = 'M0 -20H100V52l-7 4-6-4-6 6-6-6-6 6-6-6-6 6-6-6-6 6-6-6-6 6-7-5H0z'
const BOTTOM = 'M0 120H100V56l-7-4-6 4-6-6-6 6-6-6-6 6-6-6-6 6-6-6-6 6-6-6-7 5H0z'
/** 알 껍데기의 얼룩 — 깨진 조각에도 남는다 */
const SPOTS = [[36, 40, 2.4], [62, 34, 1.8], [66, 68, 2.6], [33, 72, 1.8], [54, 78, 1.4]]

/** 알 모양 클립 · 위 · 아래 조각 클립 — id 는 쓰는 쪽마다 따로 (한 페이지에 여럿) */
export function ShellDefs({ id }) {
  return (
    <>
      <clipPath id={`${id}-egg`}><path d={EGG} /></clipPath>
      <clipPath id={`${id}-top`}><path d={TOP} /></clipPath>
      <clipPath id={`${id}-bot`}><path d={BOTTOM} /></clipPath>
    </>
  )
}

/** 껍데기 조각 하나 — part: whole(통알) · top(위 조각) · bottom(아래 조각) */
export function ShellPiece({ id, part = 'whole', crack = false }) {
  const body = (
    <>
      <path className="px-egg" d={EGG} />
      <g clipPath={`url(#${id}-egg)`}>
        {SPOTS.map(([x, y, r]) => <ellipse key={`${x}-${y}`} className="px-egg-spot" cx={x} cy={y} rx={r} ry={r * 0.8} />)}
      </g>
      {crack && <path className="px-crack" d="M27 46l5 4 4-4 5 5 4-4" />}
    </>
  )
  if (part === 'whole') return <g>{body}</g>
  return (
    <g>
      <g clipPath={`url(#${id}-${part === 'top' ? 'top' : 'bot'})`}>{body}</g>
      <path className="px-zig" d={ZIG} clipPath={`url(#${id}-egg)`} />
    </g>
  )
}

/** 갓 깬 병아리가 입은 아래 껍데기 — 몸보다 넓게 · 낮게 눌러 배 아래만 덮는다 */
export function ShellPants({ id }) {
  return <g transform="translate(-15 28) scale(1.3 .72)"><ShellPiece id={id} part="bottom" /></g>
}
/** 머리에 얹은 위 껍데기 — 새싹을 덮고 살짝 기울었다 */
export function ShellCap({ id }) {
  return <g transform="translate(7 -12) rotate(12 50 40) scale(.82)"><ShellPiece id={id} part="top" /></g>
}
