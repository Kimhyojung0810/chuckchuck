/* 가상 발표 스튜디오 — React Three Fiber. design/SPACE.md v3 (Horizon OS 방식: 시점 고정, 창이 곡선 위를 미끄러진다)
   10-13: 창 안은 지금 앱의 리허설 흐름 그대로(§6) — 앱의 주소가 정거장을 정하고, 스튜디오는 곡선을 미끄러뜨린다 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Canvas } from '@react-three/fiber'
import { STATIONS, FOV, FOV_PHONE, EYE } from './config.js'
import { rig } from './rig.js'
import { Hall } from './scene/Hall.jsx'
import { Lights } from './scene/Lights.jsx'
import { CameraRig } from './scene/CameraRig.jsx'
import { GlassPass } from './scene/Glass.jsx'
import { Station } from './scene/Station.jsx'
import { useMicLevel } from './media.js'
import { AppFrame, CoverCard } from './ui/Frame.jsx'
import { PresentDock } from './ui/PresentDock.jsx'
import { Companion } from './piyak/Companion.jsx'
import { rmsToVolume } from './voice/signal.js'
import { stationLayout, appRect } from './layout.js'
import { ST, isReport } from './ui/keys.js'
import { useAppMirror, pressApp, SlideOverlay, Listener } from './ui/AppMirror.jsx'
import { ScoreBoard } from './ui/ScoreBoard.jsx'

function useViewport() {
  const read = () => ({ w: innerWidth, h: innerHeight, phone: innerWidth < 720 })
  const [vp, setVp] = useState(read)
  useEffect(() => { const on = () => setVp(read()); addEventListener('resize', on); return () => removeEventListener('resize', on) }, [])
  return vp
}

// 자라는 삐약이의 단계 — 정거장 다섯(분석이 늘었다)에 그림 넷: ① 알 · ② ③ 금 간 알 · ④ 깨고 나옴 · ⑤ 모자
const COMPANION_STAGE = [0, 1, 1, 2, 3, 3, 3, 3, 3]

export default function App() {
  const vp = useViewport()
  const [at, setAt] = useState(0)
  const mic = useMicLevel()
  const live = useRef(null)
  const htmlLayer = useRef(null)   // drei Html 이 붙을 고정 층 — 첫 Html 이 붙을 자리를 못 찾고 사라지던 것을 막는다
  const frameApi = useRef(null)
  const [fitH, setFitH] = useState(null)        // ① 업로드 창 = 내용 높이 (Frame onFit)
  const [bigSlide, setBigSlide] = useState(false) // ② PPT 창 크게
  const onFit = useCallback((v) => setFitH((h) => (h === v || (h && v && Math.abs(h - v) < 6) ? h : v)), [])

  /** 앱이 그 단계 화면으로 넘어갔다 → 곡선이 미끄러진다 (시점은 그대로) */
  const holdTimer = useRef(0)
  const go = useCallback((to) => {
    to = Math.max(0, Math.min(STATIONS.length - 1, to))
    rig.drag = 0
    if (to === rig.at) return
    // ③ 발표 채점 연출이 도는 중이면 질의응답으로 가는 것을 끝날 때까지(최대 10초) 미룬다 — 앱은 질문이 준비되면 0.9초 뒤 넘어간다
    if (rig.at === 2 && to === 3 && rig.hold) {
      if (!holdTimer.current) holdTimer.current = Date.now()
      if (Date.now() - holdTimer.current < 10000) return
    }
    holdTimer.current = 0
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

  // ── 정거장마다 정면 배치 (layout.js) — 앱 창 자리는 지금 정거장 것. 3D 창도 같은 자리라 멈추면 정확히 겹친다 ──
  const Ls = STATIONS.map((_, k) => stationLayout(k, vp, { fitH, bigSlide }))
  const rect = appRect(Ls[at], vp)
  const W = Ls[0].app.w, H = Ls[0].app.h
  // ② · ③ 은 앱 안의 자료 · 반응 삐약이 · 진행 삐약이를 무대로 꺼낸다 (ui/AppMirror.jsx)
  // ④ 질의응답은 비추지 않는다 — 삐약이 · 질문 · 자료는 앱 안 무대(js/qa_stage.js 띠 · 틀 · 레일)가 맡는다 (10-13)
  const mirror = useAppMirror(frameApi, at === 2 ? 'wait' : vp.phone ? null : at === 1 ? 'present' : null)
  const slideNav = (d) => pressApp(frameApi, `#vrCall .vr-dock [data-slide-nav="${d}"]`)
  // 채점판은 앱이 기다림 층을 걷어도(질의응답으로 넘어가도) 마지막 결과를 붙든다 — 연출을 끝까지 보여 주려고
  const lastWait = useRef(null)
  if (at === 2 && mirror) lastWait.current = mirror
  if (at === 1 || at === 0) lastWait.current = null
  const scoreData = at === 2 ? (mirror || lastWait.current) : null

  /** ② 발표 음량 — 비전 리허설이 이미 재는 값 (PresentDock 과 같다 · 마이크를 더 열지 않는다) */
  const readAppLevel = useCallback(() => {
    const f = frameApi.current?.win()?.visionReadLevel
    const r = typeof f === 'function' ? f() : null
    return r === null || r === undefined ? 0 : rmsToVolume(r)
  }, [])

  const stations = STATIONS.map((s, k) => {
    const L = Ls[k]
    const panels = [{ id: 'w', x: L.app.x, y: L.app.y, w: L.app.w, h: L.app.h, children: <CoverCard no={k + 1} name={s.name} line={s.line} /> }]
    if (L.listener) panels.push({ id: 'listener', ...L.listener, glass: false, bare: true,
      children: <Listener bird={k === at && mirror ? mirror.bird : null} size={L.seat} onEar={() => pressApp(frameApi, '#vrEar')} /> })
    // ③ 발표 채점 — 개념 그래프 채점판이 주인공 (앱의 실제 그래프 · 판정만)
    if (L.graph) panels.push({ id: 'graph', ...L.graph, radius: 28,
      children: <ScoreBoard data={k === at ? scoreData : null} w={L.graph.w} h={L.graph.h} k={k} /> })
    // 흐름을 따라 자라는 삐약이 (알 → 금 간 알 → 깨고 나옴 → 모자 · 닭, piyak/Companion.jsx) — 정거장마다 비어 있는 자리에
    // ② 발표는 웹캠 · 앞줄 관중이 주인공이라 자라는 삐약이는 쉰다(v3 — 메인 콘텐츠와 경쟁하지 않게). ④ 질의응답도 — 웹캠이 화면을 채운다
    if (!vp.phone && k !== 1 && k !== 3) {
      const at2 = k === 2 ? { x: L.app.x, y: L.app.y + L.app.h / 2 + 120 }                                       // 발표 채점 — 진행 창 아래
        : { x: L.app.x - (L.app.w / 2 + 130), y: L.app.y + L.app.h / 2 - 150 }
      // 화면 밖으로 잘리지 않게 (리포트처럼 창이 넓으면 옆 자리가 좁다)
      const px = Math.max(-vp.w / 2 + 112, Math.min(vp.w / 2 - 112, at2.x))
      panels.push({ id: 'piyak', x: Math.round(px), y: Math.round(at2.y), w: 210, h: 300, glass: false, bare: true,
        children: <Companion k={COMPANION_STAGE[k]} active={k === at} mic={mic} readAppLevel={readAppLevel} /> })
    }
    return panels
  })

  return (
    <div className="sx-root ds-root" onPointerMove={onPointerMove} onPointerDown={onPointerDown} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}>
      <Canvas className="sx-canvas" dpr={[1, 1.5]} gl={{ antialias: true, powerPreference: 'high-performance', toneMappingExposure: 1.0 }}
        camera={{ fov: vp.phone ? FOV_PHONE : FOV, near: 0.05, far: 60, position: [0, EYE, 0] }}>
        <color attach="background" args={['#EEEAE4']} />
        <Scene stations={stations} at={at} readLevel={readAppLevel} portal={htmlLayer} W={W} H={H} Ls={Ls} />
      </Canvas>
      <div className="sx-html" ref={htmlLayer} />
      <AppFrame rect={rect} onStation={go} api={frameApi} onFit={onFit} />
      {at === 1 && Ls[1].overlay && mirror && mirror.slide && (
        <SlideOverlay slide={mirror.slide} onNav={slideNav} big={bigSlide} onToggle={() => setBigSlide((b) => !b)}
          box={{ left: rect.left + Ls[1].overlay.left, top: rect.top + Ls[1].overlay.top, w: Ls[1].overlay.w, h: Ls[1].overlay.h }} />
      )}
      <PresentDock api={frameApi} box={Ls[1].dock || { left: rect.left, width: rect.width, top: rect.top + rect.height + 14 }} on={at === 1 && !vp.phone} />

      <header className="hud">
        <span className="hud__brand"><img src="assets/chuckchuck-app-icon-64.png" alt="" /><span>척척발표</span></span>
        <ol className="hud__steps" aria-label="리허설 단계">
          {STATIONS.map((s, i) => (
            <li key={s.key} className={i === ST.report ? 'hud__report-start' : undefined}>
              {/* 리포트 정거장(05~09)은 언제든 눌러서 간다 — 발표 전이면 미리 돌린 샘플 리포트로(Frame api.tab). 앞 단계(01~04)는 앱 흐름이 정한다 */}
              {isReport(i)
                ? <button type="button" className="ds-step" aria-current={i === at ? 'step' : undefined} onClick={() => frameApi.current?.tab(i - ST.report)}>
                    <span className="ds-mono">0{i + 1}</span><span className="hud__step-name">{s.name}</span></button>
                : <span className="ds-step" aria-current={i === at ? 'step' : undefined}>
                    <span className="ds-mono">0{i + 1}</span><span className="hud__step-name">{s.name}</span></span>}</li>
          ))}
        </ol>
        <span className="hud__end"><a className="hud__exit" href="/">나가기</a></span>
      </header>
      {at === 0 && <p className="hud__note ds-mono">→ · Enter 다음 · ← 이전 · 빈 곳을 좌우로 끌면 둘러봐요</p>}
      {isReport(at) && <p className="hud__note ds-mono">← → 리포트 화면 옮기기 · 위 단계를 눌러도 돼요</p>}
      <p className="ds-sr" ref={live} aria-live="polite" />
    </div>
  )
}

function Scene({ stations, at, readLevel, portal, W, H, Ls }) {
  const coveRef = useRef([])
  return (
    <>
      <CameraRig />
      <Lights coveRef={coveRef} />
      <Hall readLevel={readLevel} />
      <GlassPass />
      {stations.map((panels, k) => (
        <Station key={k} k={k} active={k === at} panels={panels} portal={portal} W={Ls[k].app.w} H={Ls[k].app.h} L={Ls[k]} />
      ))}
    </>
  )
}
