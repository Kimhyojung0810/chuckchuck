/* 가상 발표 스튜디오 — React Three Fiber. design/SPACE.md v3 (Horizon OS 방식: 시점 고정, 창이 곡선 위를 미끄러진다) */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Canvas } from '@react-three/fiber'
import { STATIONS, FOV, FOV_PHONE, EYE } from './config.js'
import { rig } from './rig.js'
import { Room } from './scene/Room.jsx'
import { Lights } from './scene/Lights.jsx'
import { CameraRig } from './scene/CameraRig.jsx'
import { GlassPass } from './scene/Glass.jsx'
import { Station } from './scene/Station.jsx'
import { useCamera, useMicLevel } from './media.js'
import { UploadWindow, CameraStage, ReportWindow } from './ui/Panels.jsx'

const indexOfHash = () => Math.max(0, STATIONS.findIndex((s) => s.key === location.hash.slice(1)))

function useViewport() {
  const read = () => ({ w: innerWidth, h: innerHeight, phone: innerWidth < 720 })
  const [vp, setVp] = useState(read)
  useEffect(() => { const on = () => setVp(read()); addEventListener('resize', on); return () => removeEventListener('resize', on) }, [])
  return vp
}

export default function App() {
  const vp = useViewport()
  const [at, setAt] = useState(() => { const i = indexOfHash(); rig.at = i; rig.f = i; return i })
  const cam = useCamera()
  const mic = useMicLevel()
  const live = useRef(null)
  const quality = useRef(1)
  const [reportSeen, setReportSeen] = useState(false)   // 리포트 iframe 은 처음 갈 때 불러온다 (지금 앱 전체를 싣는다)
  const htmlLayer = useRef(null)   // drei Html 이 붙을 고정 층 — 첫 Html 이 붙을 자리를 못 찾고 사라지던 것을 막는다

  /** 그 단계로 — 곡선이 미끄러진다 (시점은 그대로) */
  const go = useCallback((to, { push = true } = {}) => {
    to = Math.max(0, Math.min(STATIONS.length - 1, to))
    rig.drag = 0
    if (to === rig.at) return
    rig.at = to
    setAt(to)
    if (to === 3) setReportSeen(true)
    if (push) history.pushState({ at: to }, '', '#' + STATIONS[to].key)
    document.title = `척척발표 — ${STATIONS[to].name} (시제품)`
    if (live.current) live.current.textContent = `${to + 1}단계 ${STATIONS[to].name}(으)로 왔어요`
    setTimeout(() => document.getElementById(`t-${STATIONS[to].key}`)?.focus({ preventScroll: true }), rig.reduced ? 0 : 700)
  }, [])
  const next = useCallback(() => go(rig.at === STATIONS.length - 1 ? 0 : rig.at + 1), [go])
  // 실험실 · 헤드리스용 — 상태를 읽고, 전환 중간 자세로 멈춰 찍는다
  useEffect(() => { window.studioDebug = { rig, go } }, [go])

  useEffect(() => {
    history.replaceState({ at: rig.at }, '', '#' + STATIONS[rig.at].key)
    const onPop = (e) => go(e.state && Number.isInteger(e.state.at) ? e.state.at : indexOfHash(), { push: false })
    addEventListener('popstate', onPop)
    return () => removeEventListener('popstate', onPop)
  }, [go])

  // ── 끌기: 곡선이 손가락을 그대로 따른다 (SPACE v3 §7) — 시점은 움직이지 않는다 ──
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
    const to = Math.round(rig.at + rig.drag)
    if (to !== rig.at) go(to)
    else rig.drag = 0
  }

  // ── 창 크기 (CSS px) ──
  const winW = Math.round(Math.min(1080, vp.w * (vp.phone ? 0.92 : 0.74)))
  const winH = Math.round(Math.min(660, vp.h * (vp.phone ? 0.74 : 0.7)))
  const camH = Math.round(vp.h * (vp.phone ? 0.66 : 0.82))
  const camW = Math.round(Math.min(camH * 16 / 9, vp.w * (vp.phone ? 0.94 : 0.9)))
  const camHh = Math.round(Math.min(camH, camW * 9 / 16) + (vp.phone ? 120 : 0))
  const repW = Math.round(Math.min(1280, vp.w * (vp.phone ? 0.94 : 0.84))), repH = Math.round(Math.min(840, vp.h * 0.8))
  const camPanel = (mode) => ({ id: 'cam', x: 0, y: 0, w: camW, h: camHh, radius: 28, glass: false,
    children: <CameraStage mode={mode} cam={cam} mic={mic} onNext={next} /> })

  const stations = [
    [{ id: 'w', x: 0, y: 0, w: winW, h: winH, children: <UploadWindow onNext={next} /> }],
    [camPanel('present')],
    [camPanel('qa')],
    [{ id: 'w', x: 0, y: 0, w: repW, h: repH, paper: true, children: <ReportWindow onNext={next} load={reportSeen || at === 3} /> }],
  ]

  return (
    <div className="sx-root ds-root" onPointerMove={onPointerMove} onPointerDown={onPointerDown} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}>
      <Canvas className="sx-canvas" dpr={[1, 1.5]} gl={{ antialias: true, powerPreference: 'high-performance', toneMappingExposure: 1.45 }}
        camera={{ fov: vp.phone ? FOV_PHONE : FOV, near: 0.05, far: 60, position: [0, EYE, 0] }}>
        <color attach="background" args={['#050504']} />
        <Scene stations={stations} at={at} go={go} quality={quality.current} portal={htmlLayer} />
      </Canvas>
      <div className="sx-html" ref={htmlLayer} />

      <header className="hud">
        <span className="hud__brand"><img src="assets/chuckchuck-app-icon-64.png" alt="" /><span>척척발표</span></span>
        <ol className="hud__steps" aria-label="단계">
          {STATIONS.map((s, i) => (
            <li key={s.key}><button className="ds-step" type="button" aria-current={i === at ? 'step' : undefined} onClick={() => go(i)}>
              <span className="ds-mono">0{i + 1}</span><span className="hud__step-name">{s.name}</span></button></li>
          ))}
        </ol>
        <span className="hud__end">
          {cam.state === 'on' && <button className="hud__exit" type="button" onClick={cam.stop}>카메라 끄기</button>}
          <a className="hud__exit" href="/#/home">나가기</a>
        </span>
      </header>
      <p className="hud__note ds-mono">시제품 — 빈 곳을 좌우로 끌면 창을 넘길 수 있어요. 분석은 연결하지 않았어요.</p>
      <p className="ds-sr" ref={live} aria-live="polite" />
    </div>
  )
}

function Scene({ stations, at, go, quality, portal }) {
  const coveRef = useRef([])
  return (
    <>
      <CameraRig />
      <Lights coveRef={coveRef} />
      <Room coveRef={coveRef} quality={quality} />
      <GlassPass />
      {stations.map((panels, k) => (
        <Station key={k} k={k} active={k === at} onEnter={go} panels={panels} portal={portal} />
      ))}
    </>
  )
}
