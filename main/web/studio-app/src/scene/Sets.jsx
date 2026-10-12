/* 정거장마다 무대 세트와 삐약이 (SPACE §2-2, 10-13 사용자). 창과 함께 곡선을 미끄러진다 — 정거장 묶음(Station) 안에 놓인다.
   좌표: 창 가운데 원점, x 오른쪽 · y 위 (px → world 로 바꿔 놓는다), z 는 m (앞 +). 창(앱 화면) 자리는 비워 둔다 — 소품은 창 밖에만. */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
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

/* 주름진 막(커튼) — 세로 주름을 sin 으로 */
function curtainGeometry(w, h) {
  const g = new THREE.PlaneGeometry(w, h, 48, 1)
  const p = g.attributes.position
  for (let i = 0; i < p.count; i++) p.setZ(i, Math.sin((p.getX(i) / w) * Math.PI * 14) * Math.min(w * 0.035, 0.03))
  g.computeVertexNormals()
  return g
}

function Box({ at, size, color, rough = 0.85, emissive, emissiveIntensity = 0 }) {
  return (
    <mesh position={at}>
      <boxGeometry args={size} />
      <meshStandardMaterial color={color} roughness={rough} emissive={emissive || '#000000'} emissiveIntensity={emissiveIntensity} />
    </mesh>
  )
}

/* ① 작업실 — 벽에 비친 아침 빛 창 둘 */
function Workshop({ W, H, world }) {
  const u = world
  const win = (side) => {
    const x = side * (W / 2 + 300) * u, y = 60 * u, w = 140 * u, h = 480 * u   // 창 뒤에서 멀리 — 유리에 줄무늬로 비치지 않게
    return (
      <group key={side} position={[x, y, -1.1]}>
        <mesh><planeGeometry args={[w, h]} /><meshBasicMaterial color="#F2EEE4" transparent opacity={0.22} toneMapped={false} /></mesh>
        <Box at={[0, 0, 0.01]} size={[6 * u, h, 0.02]} color="#1a221e" />
        <Box at={[0, h * 0.12, 0.01]} size={[w, 6 * u, 0.02]} color="#1a221e" />
        {/* 바닥으로 떨어지는 빛 — 옅은 사다리꼴 */}
        <mesh position={[side * -40 * u, -h / 2 - 90 * u, 0.4]} rotation={[-1.2, 0, 0]}>
          <planeGeometry args={[w * 1.3, 260 * u]} />
          <meshBasicMaterial color="#F2EEE4" transparent opacity={0.06} depthWrite={false} toneMapped={false} />
        </mesh>
      </group>
    )
  }
  return <group>{win(-1)}{win(1)}</group>
}

/* ② 무대 — 양옆 초록 막 · 위 막 · 무대 바닥 끝선 · 위에서 떨어지는 빛 기둥, 객석 삐약이 넷 */
function StageWide({ L, world }) {
  const u = world
  const top = L.top, floor = L.floor, half = L.total / 2
  const ch = (floor - top + 420) * u
  const geo = useMemo(() => curtainGeometry(200 * u, ch), [u, ch])
  const val = useMemo(() => curtainGeometry((L.total + 520) * u, 80 * u), [L.total, u])
  // 앞줄 관중 — 큰 반응 삐약이(왼쪽) 와 자라는 삐약이(오른쪽) 사이에 셋
  const from = L.listener.x + L.listener.w / 2 + 30
  const to = L.app.x + L.app.w / 2 - 230
  const feet = L.dockTop - 8
  const h = Math.round(L.seat * 0.62)
  const seats = [0, 1, 2].map((i) => from + ((to - from) * (i + 0.5)) / 3)
  const who = [['ax', 'neutral'], ['midm', 'excited'], ['exaone', 'happy']]
  return (
    <group>
      {[-1, 1].map((side) => (
        <mesh key={side} geometry={geo} position={[side * (half + 90) * u, -((top + floor) / 2) * u, -0.35]}>
          <meshStandardMaterial color="#2B3A33" roughness={0.78} side={THREE.DoubleSide} />
        </mesh>
      ))}
      <mesh geometry={val} position={[0, -(top - 40) * u, -0.3]}>
        <meshStandardMaterial color="#26332D" roughness={0.8} side={THREE.DoubleSide} />
      </mesh>
      <Box at={[0, -(floor + 10) * u, 0.05]} size={[(L.total + 160) * u, 2 * u, 0.02]} color="#2A2E2B" emissive="#EEE9DF" emissiveIntensity={0.06} />
      {seats.map((x, i) => (
        <Chick key={i} name={who[i][0]} mood={who[i][1]} at={[x, -feet, 0.12]} h={h - (i % 2) * 10} world={u} flip={i === 2} tilt={(i - 1) * 0.04} />
      ))}
    </group>
  )
}

function Stage({ W, H, world }) {
  const u = world
  const cw = 200 * u, ch = (H + 380) * u
  const geo = useMemo(() => curtainGeometry(cw, ch), [cw, ch])
  const val = useMemo(() => curtainGeometry((W + 520) * u, 90 * u), [W, u])
  return (
    <group>
      {[-1, 1].map((side) => (
        <mesh key={side} geometry={geo} position={[side * (W / 2 + 120) * u, 40 * u, -0.35]}>
          <meshStandardMaterial color="#2B3A33" roughness={0.78} side={THREE.DoubleSide} />
        </mesh>
      ))}
      <mesh geometry={val} position={[0, (H / 2 + 90) * u, -0.3]}>
        <meshStandardMaterial color="#26332D" roughness={0.8} side={THREE.DoubleSide} />
      </mesh>
      {/* 무대 바닥 끝선 */}
      <Box at={[0, -(H / 2 + 30) * u, 0.05]} size={[(W + 420) * u, 2 * u, 0.02]} color="#2A2E2B" emissive="#EEE9DF" emissiveIntensity={0.06} />
      {/* 객석 — 창 아래 양쪽 */}
      <Chick name="ax" mood="neutral" at={[-(W / 2 + 62), -(H / 2 + 20), 0.12]} h={104} world={u} />
      <Chick name="midm" mood="excited" at={[-(W / 2 + 152), -(H / 2 + 34), 0.14]} h={92} world={u} tilt={0.05} />
      <Chick name="exaone" mood="happy" at={[W / 2 + 62, -(H / 2 + 20), 0.12]} h={104} world={u} flip />
      <Chick name="solar" mood="excited" at={[W / 2 + 152, -(H / 2 + 34), 0.14]} h={92} world={u} flip tilt={-0.05} />
    </group>
  )
}

/* ③ 심사석(넓은 화면) — 앱 창 아래 긴 책상. 심사위원은 왼쪽 앞 큰 삐약이(ui/AppMirror Judge)가 맡는다 */
function JudgesWide({ L, world }) {
  const u = world
  const top = L.app.y + L.app.h / 2 + 10
  return (
    <group>
      <Box at={[L.app.x * u, -(top + 36) * u, 0.2]} size={[(L.app.w + 120) * u, 72 * u, 0.12]} color="#0c1210" rough={0.7} />
      <Box at={[L.app.x * u, -top * u, 0.2]} size={[(L.app.w + 130) * u, 3 * u, 0.06]} color="#0e1512" rough={0.8} />
    </group>
  )
}

/* ③ 심사석 — 긴 책상, 양 끝에 심사위원 삐약이 넷(궁금한 얼굴) */
function JudgesDesk({ W, H, world }) {
  const u = world
  const top = -(H / 2 + 10)
  return (
    <group>
      <Box at={[0, (top - 36) * u, 0.2]} size={[(W + 420) * u, 72 * u, 0.12]} color="#0c1210" rough={0.7} />
      <Box at={[0, top * u, 0.2]} size={[(W + 430) * u, 3 * u, 0.14]} color="#1d211e" rough={0.6} />
      <Chick name="solar" mood="curious" at={[-(W / 2 + 62), top - 6, 0.1]} h={100} world={u} />
      <Chick name="midm" mood="curious" at={[-(W / 2 + 150), top - 6, 0.1]} h={92} world={u} />
      <Chick name="ax" mood="curious" at={[W / 2 + 62, top - 6, 0.1]} h={100} world={u} flip />
      <Chick name="exaone" mood="curious" at={[W / 2 + 150, top - 6, 0.1]} h={92} world={u} flip />
    </group>
  )
}

/* ④ 서재 — 낮은 선반 둘, 엑사원이 기뻐한다 */
function Shelf({ side, W, H, world }) {
  const u = world
  const w = 190 * u, h = 220 * u, x = side * (W / 2 + 130) * u, y = -(H / 2 - 60) * u
  return (
    <group position={[x, 0, -0.4]}>
      <Box at={[0, y, -0.05]} size={[w, h, 0.02]} color="#161A17" rough={0.95} />
      {[0, 1, 2].map((r) => <Box key={r} at={[0, y - h / 2 + r * (h / 2), 0.02]} size={[w, 4 * u, 0.12]} color="#2A2E2B" rough={0.9} />)}
    </group>
  )
}
function Study({ W, H, world }) {
  const u = world
  return (
    <group>
      <Shelf side={-1} W={W} H={H} world={u} />
      <Shelf side={1} W={W} H={H} world={u} />
      <Chick name="exaone" mood="happy" at={[W / 2 + 130, -(H / 2 - 60) + 110 + 2, -0.3]} h={96} world={u} flip />
    </group>
  )
}

/* ③ 분석 — 창 둘레에 분석 요소 넷이 떠 있다. 앱의 실제 단계 상태(rec · stt · align · flow · questions)로만 켜진다 — 숫자 진행률은 만들지 않는다 */
const ANALYSIS_CARDS = [
  { key: 'voice', label: '목소리', sub: '녹음을 정리하고 받아써요', steps: ['rec', 'stt'], at: [-1, -1] },
  { key: 'align', label: '자료와 내 말', sub: '장마다 한 말을 맞춰 봐요', steps: ['align'], at: [1, -1] },
  { key: 'flow', label: '발표 흐름', sub: '자료의 흐름과 비교해요', steps: ['flow'], at: [-1, 1] },
  { key: 'ask', label: '질문', sub: '빠뜨린 개념으로 질문 3개', steps: ['questions'], at: [1, 1] },
]
const STATE_WORD = { wait: '기다려요', run: '하고 있어요', done: '마쳤어요', fail: '멈췄어요' }

function cardState(steps, keys) {
  if (!steps) return 'wait'
  const st = keys.map((k) => steps[k] || 'wait')
  if (st.includes('fail')) return 'fail'
  if (st.every((x) => x === 'done')) return 'done'
  if (st.some((x) => x === 'run' || x === 'done')) return 'run'
  return 'wait'
}

/** 카드 그림 — 캔버스에 그려 텍스처로 (상태가 바뀔 때만 다시 그린다) */
function useCardTexture(card, state) {
  const tex = useMemo(() => {
    const c = document.createElement('canvas'); c.width = 520; c.height = 300
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4
    return t
  }, [])
  useEffect(() => {
    const c = tex.image, g = c.getContext('2d')
    g.clearRect(0, 0, c.width, c.height)
    const r = 36
    g.beginPath(); g.roundRect ? g.roundRect(4, 4, c.width - 8, c.height - 8, r) : g.rect(4, 4, c.width - 8, c.height - 8)
    g.fillStyle = state === 'run' ? 'rgba(52, 74, 64, .92)' : 'rgba(34, 39, 36, .86)'; g.fill()
    g.lineWidth = 3; g.strokeStyle = state === 'run' ? 'rgba(111, 181, 154, .75)' : state === 'done' ? 'rgba(111, 181, 154, .35)' : 'rgba(240, 240, 233, .14)'; g.stroke()
    const font = '"Pretendard Variable", Pretendard, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif'
    g.fillStyle = state === 'wait' ? '#8A938C' : '#F0F0E9'; g.font = `600 46px ${font}`; g.fillText(card.label, 40, 104)
    g.fillStyle = '#A4ADA6'; g.font = `400 28px ${font}`; g.fillText(card.sub, 40, 156)
    g.beginPath(); g.arc(52, 232, 10, 0, Math.PI * 2)
    g.fillStyle = state === 'fail' ? '#E5484D' : state === 'wait' ? 'rgba(240, 240, 233, .25)' : '#6FB59A'; g.fill()
    g.fillStyle = state === 'wait' ? '#8A938C' : '#F0F0E9'; g.font = `500 30px ${font}`; g.fillText(STATE_WORD[state], 76, 243)
    tex.needsUpdate = true
  }, [tex, card, state])
  return tex
}

function AnalysisCard({ card, state, W, H, world, phase }) {
  const tex = useCardTexture(card, state)
  const ref = useRef()
  const u = world
  const w = 260, h = 150
  const x = card.at[0] * (W / 2 + 30 + w / 2), y = -card.at[1] * (H / 2 - h / 2 - 10)
  useFrame((st) => {
    if (!ref.current) return
    const t = st.clock.elapsedTime
    // 떠 있는 물건 — 아주 느리게 오르내린다(멈춘 화면이 아니라 공간). 하고 있는 카드는 조금 앞으로
    ref.current.position.y = (y + Math.sin(t * 0.6 + phase) * 5) * u
    const z = state === 'run' ? 0.18 : 0.06
    ref.current.position.z += (z - ref.current.position.z) * 0.06
  })
  return (
    <mesh ref={ref} position={[x * u, y * u, 0.06]} rotation={[0, -card.at[0] * 0.12, 0]}>
      <planeGeometry args={[w * u, h * u]} />
      <meshBasicMaterial map={tex} transparent toneMapped={false} depthWrite={false} />
    </mesh>
  )
}

function Analysis({ W, H, world, info }) {
  const steps = info && info.steps
  return (
    <group>
      {ANALYSIS_CARDS.map((card, i) => (
        <AnalysisCard key={card.key} card={card} state={cardState(steps, card.steps)} W={W} H={H} world={world} phase={i * 1.7} />
      ))}
    </group>
  )
}

const SETS = [Workshop, Stage, Analysis, JudgesDesk, Study]

/** 정거장 k 의 세트 — W·H 는 창 크기(px), world 는 1px 의 m */
export function StationSet({ k, W, H, L, info, world }) {
  // 텍스처가 늦게 들어와도 다시 그리게 한 번 깨운다
  const [, kick] = useState(0)
  useEffect(() => { const id = setTimeout(() => kick(1), 400); return () => clearTimeout(id) }, [])
  if (k === 1 && L && L.overlay) return <StageWide L={L} world={world} />
  if (k === 3 && L && L.judge) return <JudgesWide L={L} world={world} />
  const C = SETS[k]
  return C ? <C W={W} H={H} world={world} info={info} /> : null
}
