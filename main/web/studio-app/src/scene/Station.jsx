/* 정거장 — 벽 앞에 떠 있는 유리 창들 (SPACE §4 · §5). 창 하나 = 유리 판(WebGL) + 그 위 DOM(drei Html).
   멈췄을 때 CSS 1px = 화면 1px 이 되게 크기를 맞춘다 — 글자가 흐려지지 않는다. */
import { useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import { DIST, EYE, SPACING, HIDE_DOM, deg, toward } from '../config.js'
import { rig } from '../rig.js'
import { GlassPanel } from './Glass.jsx'

/** 화면 1px 이 창 거리(DIST)에서 몇 m 인가 */
export function useWorldPerPx() {
  const camera = useThree((s) => s.camera)
  const h = useThree((s) => s.size.height)
  return (2 * DIST * Math.tan(deg(camera.fov) / 2)) / h
}

const smoothstep = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t) }

/**
 * 곡선 위의 창 하나 (SPACE v3 §2). 매 프레임 (k − f) 로 각도 · 크기 · 흐림을 정한다 — 시점은 그대로, 창이 미끄러진다.
 * panels: [{ id, x, y, w, h, radius, paper, tint, glass, children }] — x·y 는 창 가운데에서의 CSS px (오른쪽 · 아래로 +)
 */
export function Station({ k, active, onEnter, panels, portal }) {
  const world = useWorldPerPx()
  const group = useRef()
  const op = useRef(active ? 1 : 0.45)
  const htmlRefs = useRef([])

  useFrame(() => {
    const rel = k - rig.f
    const ang = rel * SPACING
    // 이동 중에는 곡선 전체가 뒤로 물러나고 작아진다(줌 아웃), 멈추면 지금 창이 정면 1:1 로 다가온다(집중)
    const m = rig.motion
    const [x, z] = toward(ang, DIST + 1.1 * m)
    const g = group.current
    if (g) {
      g.position.set(x, EYE + 0.06 * m, z)
      g.rotation.set(0, -deg(ang), 0)
      g.scale.setScalar((1 - 0.1 * Math.min(1, Math.abs(rel))) * (1 - 0.06 * m))
    }
    const off = Math.abs(ang)
    op.current = (1 - 0.55 * Math.min(1, Math.abs(rel))) * (1 - smoothstep(HIDE_DOM - 22, HIDE_DOM, off))
    htmlRefs.current.forEach((el) => {
      if (!el) return
      el.style.opacity = op.current.toFixed(3)
      el.style.visibility = op.current < 0.02 ? 'hidden' : 'visible'
    })
  })

  return (
    <group ref={group}>
      {panels.map((p, i) => (
        <group key={p.id} position={[p.x * world, -p.y * world, i * 0.002]}>
          {p.glass !== false && <GlassPanel widthPx={p.w} heightPx={p.h} radius={p.radius ?? 24} world={world} paper={p.paper} tint={p.tint} opacityRef={op} />}
          <Html transform portal={portal} distanceFactor={400 * world} zIndexRange={[20, 0]} style={{ pointerEvents: 'auto' }}>
            <div ref={(el) => { htmlRefs.current[i] = el }}
              className={`sx-panel${p.paper ? ' sx-panel--paper' : ''}${p.glass === false ? ' sx-panel--solid' : ''}${active ? '' : ' is-away'}`}
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
