/* 정거장 — 벽 앞에 떠 있는 유리 창들 (SPACE §4 · §5). 창 하나 = 유리 판(WebGL) + 그 위 DOM(drei Html).
   멈췄을 때 CSS 1px = 화면 1px 이 되게 크기를 맞춘다 — 글자가 흐려지지 않는다. */
import { useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import { DIST, EYE, SPACING, HIDE_DOM, deg, toward, easeInOutSine } from '../config.js'
import { rig } from '../rig.js'
import { GlassPanel } from './Glass.jsx'
import { StationSet } from './Sets.jsx'

/** 화면 1px 이 창 거리(DIST)에서 몇 m 인가 */
export function useWorldPerPx() {
  const camera = useThree((s) => s.camera)
  const h = useThree((s) => s.size.height)
  return (2 * DIST * Math.tan(deg(camera.fov) / 2)) / h
}

const smoothstep = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t) }

/**
 * 곡선 위의 창 하나 (SPACE v3 §2). 매 프레임 (k − f) 로 각도 · 크기 · 흐림을 정한다 — 시점은 그대로, 창이 미끄러진다.
 * panels: [{ id, x, y, w, h, radius, paper, tint, glass, bare, children }] — x·y 는 창 가운데에서의 CSS px (오른쪽 · 아래로 +)
 * 다른 정거장의 창은 표지라 누를 것이 없다(inert) — 실제 화면은 앱이 정한다 (SPACE §6). W·H 는 세트를 놓을 창 크기
 */
export function Station({ k, active, panels, portal, W, H, L }) {
  const world = useWorldPerPx()
  const group = useRef()
  const op = useRef(active ? 1 : 0.45)
  const htmlRefs = useRef([])
  const setRef = useRef()

  useFrame(() => {
    let rel = k - rig.f
    // 단계 전환(제자리 페이드, CameraRig) — 떠나는 창은 정면에서 살짝 물러나며 흐려지고, 오는 창은 살짝 앞에서 자리로 내려앉는다
    let fade = 1, push = 0
    const fd = rig.fade
    if (fd) {
      const out = easeInOutSine(Math.min(1, fd.p / 0.6))
      const inn = easeInOutSine(Math.max(0, (fd.p - 0.3) / 0.7))
      if (k === fd.from) { rel = 0; fade = 1 - out; push = -0.12 * out }
      else if (k === fd.to) { fade = inn; push = 0.06 * (1 - inn) }
      else fade = inn
    }
    const ang = rel * SPACING
    const m = rig.motion
    const [x, z] = toward(ang, DIST + 0.5 * m - push)
    const g = group.current
    if (g) {
      g.position.set(x, EYE, z)
      g.rotation.set(0, -deg(ang), 0)
      g.scale.setScalar((1 - 0.1 * Math.min(1, Math.abs(rel))) * (1 - 0.03 * m))
    }
    // 세트는 제 창이 정면 가까이 올 때만 — 이웃 정거장의 소품 · 삐약이가 화면 가장자리에 몰려 어수선했다
    if (setRef.current) setRef.current.visible = Math.abs(rel) < 0.7 && fade > 0.5
    const off = Math.abs(ang)
    op.current = fade * (1 - 0.55 * Math.min(1, Math.abs(rel))) * (1 - smoothstep(HIDE_DOM - 22, HIDE_DOM, off))
    // 지금 정거장의 표지는 실제 앱이 덮는 동안 감춘다 — v3 앱 문서는 바탕이 투명이라 표지 글자가 비쳤다
    const live = active && rig.settled && !rig.dragging
    htmlRefs.current.forEach((el, i) => {
      if (!el) return
      el.style.opacity = op.current.toFixed(3)
      el.style.visibility = op.current < 0.02 ? 'hidden' : 'visible'
      if (panels[i] && panels[i].id === 'w') el.classList.toggle('is-live-cover', live)
    })
  })

  return (
    <group ref={group}>
      <group ref={setRef}><StationSet k={k} W={W} H={H} L={L} world={world} /></group>
      {panels.map((p, i) => (
        <group key={p.id} position={[p.x * world, -p.y * world, i * 0.002]}>
          {p.glass !== false && <GlassPanel widthPx={p.w} heightPx={p.h} radius={p.radius ?? 24} world={world} paper={p.paper} tint={p.tint} opacityRef={op} />}
          <Html transform portal={portal} distanceFactor={400 * world} zIndexRange={[20, 0]} style={{ pointerEvents: 'auto' }}>
            <div ref={(el) => { htmlRefs.current[i] = el }}
              className={`sx-panel${p.paper ? ' sx-panel--paper' : ''}${p.glass === false ? ' sx-panel--solid' : ''}${p.bare ? ' sx-panel--bare' : ''}${active ? '' : ' is-away'}`}
              style={{ width: p.w, height: p.h, borderRadius: p.radius ?? 24 }}
              inert={!active}>
              {p.children}
            </div>
          </Html>
        </group>
      ))}
    </group>
  )
}
