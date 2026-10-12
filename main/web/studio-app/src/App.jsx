/* 가상 발표 스튜디오 — React Three Fiber. design/SPACE.md v3 (Horizon OS 방식: 시점 고정, 창이 곡선 위를 미끄러진다)
   10-13: 창 안은 지금 앱의 리허설 흐름 그대로(§6) — 앱의 주소가 정거장을 정하고, 스튜디오는 곡선을 미끄러뜨린다 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Canvas } from '@react-three/fiber'
import { STATIONS, FOV, FOV_PHONE, EYE } from './config.js'
import { rig } from './rig.js'
import { Room } from './scene/Room.jsx'
import { Lights } from './scene/Lights.jsx'
import { CameraRig } from './scene/CameraRig.jsx'
import { GlassPass } from './scene/Glass.jsx'
import { Station } from './scene/Station.jsx'
import { useMicLevel } from './media.js'
import { AppFrame, CoverCard } from './ui/Frame.jsx'
import { PresentDock } from './ui/PresentDock.jsx'
import { PiyakStage } from './piyak/PiyakStage.jsx'

function useViewport() {
  const read = () => ({ w: innerWidth, h: innerHeight, phone: innerWidth < 720 })
  const [vp, setVp] = useState(read)
  useEffect(() => { const on = () => setVp(read()); addEventListener('resize', on); return () => removeEventListener('resize', on) }, [])
  return vp
}

export default function App() {
  const vp = useViewport()
  const [at, setAt] = useState(0)
  const mic = useMicLevel()
  const live = useRef(null)
  const quality = useRef(1)
  const htmlLayer = useRef(null)   // drei Html 이 붙을 고정 층 — 첫 Html 이 붙을 자리를 못 찾고 사라지던 것을 막는다
  const frameApi = useRef(null)

  /** 앱이 그 단계 화면으로 넘어갔다 → 곡선이 미끄러진다 (시점은 그대로) */
  const go = useCallback((to) => {
    to = Math.max(0, Math.min(STATIONS.length - 1, to))
    rig.drag = 0
    if (to === rig.at) return
    rig.at = to
    setAt(to)
    document.title = `척척발표 — ${STATIONS[to].name}`
    if (live.current) live.current.textContent = `${to + 1}단계 ${STATIONS[to].name}(으)로 왔어요`
  }, [])
  // 실험실 · 헤드리스용 — 상태를 읽고, 전환 중간 자세로 멈춰 찍는다
  useEffect(() => { window.studioDebug = { rig, go, frame: frameApi } }, [go])

  // 키보드 — → · Enter 주 버튼, ← 이전 화면 (SPACE §7). iframe 안에서 누른 키는 Frame 이 같은 규칙으로 받는다
  useEffect(() => {
    const onKey = (e) => frameApi.current?.key(e)
    addEventListener('keydown', onKey)
    return () => removeEventListener('keydown', onKey)
  }, [])

  // ── 끌기: 둘러보기만 — 곡선이 손가락을 따라왔다가 놓으면 지금 창으로 돌아온다(실제 화면은 앱이 정한다) ──
  const drag = useRef(null)
  const onPointerMove = (e) => {
    const d = drag.current
    if (!d) return
    const slot = vp.w * 0.62                                  // 창 한 칸 = 화면 폭의 62% 를 끌면
    rig.drag = Math.max(-rig.at - 0.35, Math.min(STATIONS.length - 1 - rig.at + 0.35, -(e.clientX - d.x) / slot))
  }
  const onPointerDown = (e) => {
    if (e.target.tagName !== 'CANVAS') return          // 창 위는 창 안 조작이 먼저
    drag.current = { x: e.clientX }
    rig.dragging = true
    e.currentTarget.setPointerCapture?.(e.pointerId)
  }
  const onPointerUp = () => {
    if (!drag.current) return
    drag.current = null
    rig.dragging = false
    rig.drag = 0
  }

  // ── 정면 창 = 실제 앱 자리 (CSS px). 3D 창도 같은 크기라 멈추면 정확히 겹친다 ──
  // 양옆 · 아래에 세트와 삐약이가 설 자리를 남긴다 (데스크톱 폭 66% · 높이 74%)
  const W = Math.round(Math.min(1120, vp.w * (vp.phone ? 0.94 : 0.66)))
  const H = Math.round(Math.min(760, vp.h * (vp.phone ? 0.8 : 0.74)))
  const rect = { left: Math.round((vp.w - W) / 2), top: Math.round((vp.h - H) / 2), width: W, height: H }

  const stations = STATIONS.map((s, k) => {
    const panels = [{ id: 'w', x: 0, y: 0, w: W, h: H, children: <CoverCard no={k + 1} name={s.name} line={s.line} /> }]
    // ① 작업실의 삐약이(쏠라) — 창 왼쪽에 서서 맞이한다. 누르면 반기고, 마이크를 켜면 말에 따라 움직인다
    if (k === 0 && !vp.phone) panels.push({ id: 'piyak', x: -(W / 2 + 118), y: H / 2 - 140, w: 210, h: 300, glass: false, bare: true,
      children: <PiyakStage mic={mic} className="sx-piyak" /> })
    return panels
  })

  return (
    <div className="sx-root ds-root" onPointerMove={onPointerMove} onPointerDown={onPointerDown} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}>
      <Canvas className="sx-canvas" dpr={[1, 1.5]} gl={{ antialias: true, powerPreference: 'high-performance', toneMappingExposure: 1.45 }}
        camera={{ fov: vp.phone ? FOV_PHONE : FOV, near: 0.05, far: 60, position: [0, EYE, 0] }}>
        <color attach="background" args={['#040605']} />
        <Scene stations={stations} at={at} quality={quality.current} portal={htmlLayer} W={W} H={H} />
      </Canvas>
      <div className="sx-html" ref={htmlLayer} />
      <AppFrame rect={rect} onStation={go} api={frameApi} />
      <PresentDock api={frameApi} rect={rect} on={at === 1 && !vp.phone} />

      <header className="hud">
        <span className="hud__brand"><img src="assets/chuckchuck-app-icon-64.png" alt="" /><span>척척발표</span></span>
        <ol className="hud__steps" aria-label="리허설 단계">
          {STATIONS.map((s, i) => (
            <li key={s.key}><span className="ds-step" aria-current={i === at ? 'step' : undefined}>
              <span className="ds-mono">0{i + 1}</span><span className="hud__step-name">{s.name}</span></span></li>
          ))}
        </ol>
        <span className="hud__end"><a className="hud__exit" href="/">나가기</a></span>
      </header>
      <p className="hud__note ds-mono">→ · Enter 다음 · ← 이전 · 빈 곳을 좌우로 끌면 둘러봐요</p>
      <p className="ds-sr" ref={live} aria-live="polite" />
    </div>
  )
}

function Scene({ stations, at, quality, portal, W, H }) {
  const coveRef = useRef([])
  return (
    <>
      <CameraRig />
      <Lights coveRef={coveRef} />
      <Room coveRef={coveRef} quality={quality} />
      <GlassPass />
      {stations.map((panels, k) => (
        <Station key={k} k={k} active={k === at} panels={panels} portal={portal} W={W} H={H} />
      ))}
    </>
  )
}
