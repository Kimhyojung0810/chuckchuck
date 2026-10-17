/* 정거장마다 무대 세트와 삐약이 (SPACE §2-2, 10-13 사용자). 창과 함께 곡선을 미끄러진다 — 정거장 묶음(Station) 안에 놓인다.
   좌표: 창 가운데 원점, x 오른쪽 · y 위 (px → world 로 바꿔 놓는다), z 는 m (앞 +). 창(앱 화면) 자리는 비워 둔다 — 소품은 창 밖에만. */
import { useEffect, useMemo, useState } from 'react'
import * as THREE from 'three'

/* 삐약이 그림(SVG)을 큰 캔버스에 한 번 그려 텍스처로 — 3D 안에서도 선명하게. 같은 그림은 한 번만 */
const texCache = new Map()
function chickTexture(name, mood) {
  const key = `${name}-${mood}`
  if (texCache.has(key)) return texCache.get(key)
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = 512
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
  const img = new Image()
  img.onload = () => { canvas.getContext('2d').drawImage(img, 0, 0, 512, 512); tex.needsUpdate = true }
  img.src = `assets/chick-${name}-${mood}.svg`
  texCache.set(key, tex)
  return tex
}

/** 삐약이 한 마리 — at: [x px, y px(발 위치), z m], h: 키(px). 살짝 숨쉰다 */
function Chick({ name, mood = 'neutral', at, h = 110, world, flip = false, tilt = 0 }) {
  const tex = useMemo(() => chickTexture(name, mood), [name, mood])
  const s = h * world
  return (
    <mesh position={[at[0] * world, at[1] * world + s / 2, at[2] ?? 0.1]} rotation={[0, 0, tilt]} scale={[flip ? -s : s, s, 1]}>
      <planeGeometry args={[1, 1]} />
      <meshBasicMaterial map={tex} transparent alphaTest={0.02} toneMapped={false} depthWrite={false} />
    </mesh>
  )
}

/* 10-17 사진 환경(scene/Environment.jsx)으로 바꾸며 회색 방에 맞춰 지은 소품(창틀 · 막 · 선반 · 책상)은 걷었다 —
   실사 극장 · 들판 앞에서 판지처럼 보였다. 삐약이만 남는다 (객석 · 심사위원 · 리포트의 엑사원) */

/* ② 무대(넓은 화면) — 앞줄 관중 삐약이 셋. 뒤로는 극장 객석 사진이 이어진다 */
function StageWide({ L, world }) {
  const u = world
  // 앞줄 관중 — 큰 반응 삐약이(왼쪽) 와 자라는 삐약이(오른쪽) 사이에 셋
  const from = L.listener.x + L.listener.w / 2 + 30
  const to = L.app.x + L.app.w / 2 - 230
  const feet = L.dockTop - 8
  const h = Math.round(L.seat * 0.62)
  const seats = [0, 1, 2].map((i) => from + ((to - from) * (i + 0.5)) / 3)
  const who = [['ax', 'neutral'], ['midm', 'excited'], ['exaone', 'happy']]
  return (
    <group>
      {seats.map((x, i) => (
        <Chick key={i} name={who[i][0]} mood={who[i][1]} at={[x, -feet, 0.12]} h={h - (i % 2) * 10} world={u} flip={i === 2} tilt={(i - 1) * 0.04} />
      ))}
    </group>
  )
}

/* ② 무대(좁은 화면) — 창 아래 양쪽 객석 */
function Stage({ W, H, world }) {
  const u = world
  return (
    <group>
      <Chick name="ax" mood="neutral" at={[-(W / 2 + 62), -(H / 2 + 20), 0.12]} h={104} world={u} />
      <Chick name="midm" mood="excited" at={[-(W / 2 + 152), -(H / 2 + 34), 0.14]} h={92} world={u} tilt={0.05} />
      <Chick name="exaone" mood="happy" at={[W / 2 + 62, -(H / 2 + 20), 0.12]} h={104} world={u} flip />
      <Chick name="solar" mood="excited" at={[W / 2 + 152, -(H / 2 + 34), 0.14]} h={92} world={u} flip tilt={-0.05} />
    </group>
  )
}

/* ⑤ 리포트 — 엑사원이 기뻐한다 */
function Study({ W, H, world }) {
  return <Chick name="exaone" mood="happy" at={[W / 2 + 130, -(H / 2 - 60) + 110 + 2, -0.3]} h={96} world={world} flip />
}

/* ③ 발표 채점 — 세트 없음: 개념 그래프 채점판(ui/ScoreBoard)이 주인공이라 방은 조용히 */
const Scoring = () => null

// ④ 질의응답은 웹캠 창이 화면 90% 라 양 끝 심사위원 넷이 화면 밖에서 반쯤 잘려 보였다 — 객석 삐약이(Audience)가 맡는다
const SETS = [null, Stage, Scoring, null, Study]

/** 정거장 k 의 세트 — W·H 는 창 크기(px), world 는 1px 의 m */
export function StationSet({ k, W, H, L, world }) {
  // 텍스처가 늦게 들어와도 다시 그리게 한 번 깨운다
  const [, kick] = useState(0)
  useEffect(() => { const id = setTimeout(() => kick(1), 400); return () => clearTimeout(id) }, [])
  if (k === 1 && L && L.overlay) return <StageWide L={L} world={world} />
  const C = SETS[k]
  return C ? <C W={W} H={H} world={world} /> : null
}
