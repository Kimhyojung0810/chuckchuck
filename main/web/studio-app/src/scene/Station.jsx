/* 정거장 — 벽 앞에 떠 있는 유리 창들 (SPACE §4 · §5). 창 하나 = 유리 판(WebGL) + 그 위 DOM(drei Html).
   멈췄을 때 CSS 1px = 화면 1px 이 되게 크기를 맞춘다 — 글자가 흐려지지 않는다. */
import { useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import { DIST, EYE, deg, stationAngle, toward } from '../config.js'
import { rig } from '../rig.js'
import { GlassPanel } from './Glass.jsx'

/** 화면 1px 이 창 거리(DIST)에서 몇 m 인가 */
export function useWorldPerPx() {
  const camera = useThree((s) => s.camera)
  const h = useThree((s) => s.size.height)
  return (2 * DIST * Math.tan(deg(camera.fov) / 2)) / h
}

const angleGap = (a, b) => Math.abs(((a - b) % 360 + 540) % 360 - 180)
const smoothstep = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t) }

/**
 * panels: [{ id, x, y, w, h, radius, paper, children }] — x·y 는 창 가운데에서의 CSS px (오른쪽 · 아래로 +)
 * behind: 창들 뒤에 놓을 3D 물건(카메라 화면 등)
 */
export function Station({ k, active, onEnter, panels, behind = null, portal }) {
  const theta = stationAngle(k)
  const [x, z] = toward(theta, DIST)
  const world = useWorldPerPx()
  const op = useRef(active ? 1 : 0.35)
  const htmlRefs = useRef([])

  useFrame(() => {
    // 시선에서 멀어지면 DOM 은 감춘다 — CSS 3D 는 카메라 옆 · 뒤로 넘어간 면을 뒤집어 그린다 (SPACE §9)
    const gap = angleGap(rig.yaw, theta)
    const near = 1 - smoothstep(34, 54, gap)
    const target = (active ? 1 : 0.35) * near
    op.current += (target - op.current) * 0.18
    htmlRefs.current.forEach((el) => {
      if (!el) return
      el.style.opacity = op.current.toFixed(3)
      el.style.visibility = op.current < 0.02 ? 'hidden' : 'visible'
    })
  })

  return (
    <group position={[x, EYE, z]} rotation={[0, -deg(theta), 0]}>
      {behind}
      {panels.map((p, i) => (
        <group key={p.id} position={[p.x * world, -p.y * world, i * 0.002]}>
          <GlassPanel widthPx={p.w} heightPx={p.h} radius={p.radius ?? 24} world={world} paper={p.paper} tint={p.tint} opacityRef={op} />
          <Html transform portal={portal} distanceFactor={400 * world} zIndexRange={[20, 0]} style={{ pointerEvents: 'auto' }}>
            <div ref={(el) => { htmlRefs.current[i] = el }}
              className={`sx-panel${p.paper ? ' sx-panel--paper' : ''}${active ? '' : ' is-away'}`}
              style={{ width: p.w, height: p.h, borderRadius: p.radius ?? 24 }}
              inert={!active}
              onClickCapture={active ? undefined : (e) => { e.preventDefault(); e.stopPropagation(); onEnter(k) }}>
              {p.children}
            </div>
          </Html>
        </group>
      ))}
    </group>
  )
}
