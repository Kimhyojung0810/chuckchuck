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
    const x = side * (W / 2 + 190) * u, y = 40 * u, w = 150 * u, h = 520 * u
    return (
      <group key={side} position={[x, y, -1.1]}>
        <mesh><planeGeometry args={[w, h]} /><meshBasicMaterial color="#EAF7EF" transparent opacity={0.55} toneMapped={false} /></mesh>
        <Box at={[0, 0, 0.01]} size={[6 * u, h, 0.02]} color="#1a221e" />
        <Box at={[0, h * 0.12, 0.01]} size={[w, 6 * u, 0.02]} color="#1a221e" />
        {/* 바닥으로 떨어지는 빛 — 옅은 사다리꼴 */}
        <mesh position={[side * -40 * u, -h / 2 - 90 * u, 0.4]} rotation={[-1.2, 0, 0]}>
          <planeGeometry args={[w * 1.3, 260 * u]} />
          <meshBasicMaterial color="#DDF5E6" transparent opacity={0.08} depthWrite={false} toneMapped={false} />
        </mesh>
      </group>
    )
  }
  return <group>{win(-1)}{win(1)}</group>
}

/* ② 무대 — 양옆 초록 막 · 위 막 · 무대 바닥 끝선 · 위에서 떨어지는 빛 기둥, 객석 삐약이 넷 */
function Stage({ W, H, world }) {
  const u = world
  const cw = 200 * u, ch = (H + 380) * u
  const geo = useMemo(() => curtainGeometry(cw, ch), [cw, ch])
  const val = useMemo(() => curtainGeometry((W + 520) * u, 90 * u), [W, u])
  return (
    <group>
      {[-1, 1].map((side) => (
        <mesh key={side} geometry={geo} position={[side * (W / 2 + 120) * u, 40 * u, -0.35]}>
          <meshStandardMaterial color="#0B5A3C" roughness={0.78} side={THREE.DoubleSide} />
        </mesh>
      ))}
      <mesh geometry={val} position={[0, (H / 2 + 90) * u, -0.3]}>
        <meshStandardMaterial color="#09503A" roughness={0.8} side={THREE.DoubleSide} />
      </mesh>
      {/* 무대 바닥 끝선 */}
      <Box at={[0, -(H / 2 + 30) * u, 0.05]} size={[(W + 420) * u, 3 * u, 0.03]} color="#0f1a15" emissive="#3fd599" emissiveIntensity={0.6} />
      {/* 객석 — 창 아래 양쪽 */}
      <Chick name="ax" mood="neutral" at={[-(W / 2 + 62), -(H / 2 + 20), 0.12]} h={104} world={u} />
      <Chick name="midm" mood="excited" at={[-(W / 2 + 152), -(H / 2 + 34), 0.14]} h={92} world={u} tilt={0.05} />
      <Chick name="exaone" mood="happy" at={[W / 2 + 62, -(H / 2 + 20), 0.12]} h={104} world={u} flip />
      <Chick name="solar" mood="excited" at={[W / 2 + 152, -(H / 2 + 34), 0.14]} h={92} world={u} flip tilt={-0.05} />
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
      <Box at={[0, top * u, 0.2]} size={[(W + 430) * u, 3 * u, 0.14]} color="#1b2621" rough={0.5} emissive="#3fd599" emissiveIntensity={0.08} />
      <Chick name="solar" mood="curious" at={[-(W / 2 + 62), top - 6, 0.1]} h={100} world={u} />
      <Chick name="midm" mood="curious" at={[-(W / 2 + 150), top - 6, 0.1]} h={92} world={u} />
      <Chick name="ax" mood="curious" at={[W / 2 + 62, top - 6, 0.1]} h={100} world={u} flip />
      <Chick name="exaone" mood="curious" at={[W / 2 + 150, top - 6, 0.1]} h={92} world={u} flip />
    </group>
  )
}

/* ④ 서재 — 낮은 선반 둘, 엑사원이 기뻐한다 */
const BOOKS = ['#0E8850', '#E7FBF0', '#064E3B', '#aeefd5', '#3fd599', '#F1F4EF']
function Shelf({ side, W, H, world }) {
  const u = world
  const w = 190 * u, h = 300 * u, x = side * (W / 2 + 118) * u, y = -(H / 2) * u   // 선반 가운데 = 창 아래 끝
  const books = []
  for (let r = 0; r < 2; r++) for (let i = 0; i < 5; i++) {
    const bw = (22 + ((i * 7 + r * 3) % 4) * 6) * u, bh = (80 + ((i * 5 + r) % 3) * 16) * u
    books.push(<Box key={`${r}-${i}`} at={[-w / 2 + 16 * u + i * 28 * u + bw / 2, y - h / 2 + 12 * u + r * 145 * u + bh / 2, -0.02]} size={[bw, bh, 0.22]} color={BOOKS[(i + r * 2) % BOOKS.length]} rough={0.7} />)
  }
  return (
    <group position={[x, 0, -0.25]}>
      <Box at={[0, y, -0.15]} size={[w, h, 0.05]} color="#16201b" />
      {[0, 1, 2].map((r) => <Box key={r} at={[0, y - h / 2 + r * 145 * u, 0]} size={[w, 10 * u, 0.32]} color="#24302a" />)}
      {books}
    </group>
  )
}
function Study({ W, H, world }) {
  const u = world
  return (
    <group>
      <Shelf side={-1} W={W} H={H} world={u} />
      <Shelf side={1} W={W} H={H} world={u} />
      <Chick name="exaone" mood="happy" at={[W / 2 + 118, -(H / 2) + 150 + 5, 0.05]} h={110} world={u} flip />
    </group>
  )
}

const SETS = [Workshop, Stage, JudgesDesk, Study]

/** 정거장 k 의 세트 — W·H 는 창 크기(px), world 는 1px 의 m */
export function StationSet({ k, W, H, world }) {
  const C = SETS[k]
  // 텍스처가 늦게 들어와도 다시 그리게 한 번 깨운다
  const [, kick] = useState(0)
  useEffect(() => { const id = setTimeout(() => kick(1), 400); return () => clearTimeout(id) }, [])
  return C ? <C W={W} H={H} world={world} /> : null
}
