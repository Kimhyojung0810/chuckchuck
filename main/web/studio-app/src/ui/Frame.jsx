/* 실제 앱 — 지금 앱의 리허설 흐름(#/rehearsal …)을 iframe 하나로 정면 창 자리에 띄운다 (SPACE §6, 10-13 사용자).
   앱 코드 · 카메라 코드는 한 줄도 안 바뀐다. iframe 은 하나다 — 3D 창 안으로 옮기면 다시 불러 흐름이 날아가서,
   3D 위 고정 2D 층에 두고, 곡선이 멈췄을 때만 정면 창 자리에 정확히 겹쳐 보인다(창이 1:1 이라). 움직이는 동안은 3D 표지가 보인다. */
import { useEffect, useRef } from 'react'
import { rig } from '../rig.js'
import { stationOfHash, keyAction, trackHash } from './keys.js'

export const APP_START = '/index.html#/rehearsal'

// 스튜디오 HUD 가 단계를 보인다 — 앱 위 띠의 이름표 · 단계 · 옆 메뉴는 감춘다(카메라 · 나가기 단추는 그대로)
const FRAME_CSS = `
  :root { --nav-w: 0px !important; }
  .sidenav, .topbar { display: none !important; }
  body { padding-left: 0 !important; }
  .bq-top .bq-brand, .bq-top .bq-steps-top, .vr-top .vr-pill { display: none !important; }
`
const PRIMARY = '.bq-cta, .btn-primary'

function visible(el) {
  if (!el || el.disabled || el.closest('[inert], [hidden], [aria-hidden="true"]')) return false
  const r = el.getBoundingClientRect()
  return r.width > 0 && r.height > 0
}

function typingIn(el) {
  if (!el) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable
}

/**
 * @param rect   { left, top, width, height } — 정면 창 자리(CSS px)
 * @param onStation (k) => void — 앱이 다른 정거장의 화면으로 넘어갔다
 * @param api    ref — { next(), back() } 를 바깥 키 처리에 내준다
 */
export function AppFrame({ rect, onStation, api }) {
  const frame = useRef(null)
  const wrap = useRef(null)
  const stack = useRef([])
  const station = useRef(0)

  // 앱 주소가 정거장을 정한다
  const sync = () => {
    const win = frame.current?.contentWindow
    if (!win) return
    let path
    try { path = win.location.pathname } catch (_) { return }
    // 처음 빈 문서(about:blank)의 load 는 건너뛴다 — 거기서 상대 주소('#/rehearsal')로 바꾸면 부모 주소(/studio)로 풀려
    // 스튜디오가 iframe 안에 또 떴다 (10-13 사용자 「화면이 겹쳐 보인다」)
    if (win.location.href === 'about:blank') return
    const onApp = /^\/(index\.html)?$/.test(path)
    if (!onApp) { win.location.replace(new URL(APP_START, location.origin).href); return }   // 앱이 아닌 문서가 실렸으면 앱으로
    const hash = win.location.hash
    const k = stationOfHash(hash)
    if (k < 0) {   // 앱의 「나가기」 · 홈 → 스튜디오는 처음 정거장(앱도 리허설 첫 화면으로) — 늘 절대 주소로
      win.location.replace(new URL(APP_START, location.origin).href)
      return
    }
    stack.current = trackHash(stack.current, hash)
    station.current = k
    onStation(k)
  }

  const act = (what) => {
    const win = frame.current?.contentWindow
    const doc = frame.current?.contentDocument
    if (!win || !doc) return false
    if (what === 'next') {
      const btn = [...doc.querySelectorAll(PRIMARY)].find(visible)
      if (!btn) return false
      btn.click()
      return true
    }
    if (what === 'back' && stack.current.length > 1) { win.history.back(); return true }
    return false
  }

  /** 키 하나 — 바깥(스튜디오)과 iframe 안이 같은 규칙 (SPACE §7) */
  const onKey = (e, active) => {
    if (e.defaultPrevented) return
    const what = keyAction({
      key: e.key,
      station: station.current,
      typing: typingIn(active),
      onControl: !!active && /^(BUTTON|A|SUMMARY)$/.test(active.tagName),
      mod: e.metaKey || e.ctrlKey || e.altKey || e.shiftKey,
    })
    if (what && rig.settled && act(what)) e.preventDefault()
  }

  useEffect(() => {
    if (api) api.current = {
      next: () => act('next'), back: () => act('back'), key: (e) => onKey(e, document.activeElement),
      doc: () => frame.current?.contentDocument || null, win: () => frame.current?.contentWindow || null,
    }
  })

  const onLoad = () => {
    const win = frame.current?.contentWindow
    const doc = frame.current?.contentDocument
    if (!win || !doc || win.location.href === 'about:blank') return
    const st = doc.createElement('style')
    st.textContent = FRAME_CSS
    doc.head.appendChild(st)
    // 1336×1024 판을 창 크기에 맞춘다 — 폭에 맞추고, 판 높이도 틀 높이에 맞춰 위아래가 잘리지 않게(안쪽 스크롤)
    const fit = doc.createElement('style')
    const refit = () => {
      const k = Math.min(1, win.innerWidth / 1336)
      fit.textContent = `:root { --artboard-scale: ${k.toFixed(3)} !important; --artboard-h: ${Math.round(win.innerHeight / k)}px !important; }`
    }
    refit()
    doc.head.appendChild(fit)
    win.addEventListener('resize', refit)
    win.addEventListener('hashchange', sync)
    doc.addEventListener('keydown', (e) => onKey(e, doc.activeElement))
    stack.current = []
    sync()
  }

  // 멈췄을 때만 보인다 — 움직이는 동안은 숨고(.2s) 3D 표지가 보인다. 숨겨도 iframe 은 그대로 돈다(카메라 · 녹음이 끊기지 않게 opacity 만)
  useEffect(() => {
    let raf = 0
    let shown = null
    const tick = () => {
      const show = rig.settled && !rig.dragging
      if (show !== shown && wrap.current) {
        shown = show
        wrap.current.classList.toggle('is-shown', show)
        wrap.current.inert = !show
        if (show) frame.current?.focus({ preventScroll: true })
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])

  return (
    <div ref={wrap} className="sx-app" style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }}>
      <iframe ref={frame} className="sx-app__frame" src={APP_START} title="척척발표 리허설"
        allow="camera; microphone; autoplay; fullscreen; screen-wake-lock" onLoad={onLoad} />
    </div>
  )
}

/** 다른 정거장의 3D 창 — 그 단계의 표지 (번호 · 이름 · 한 줄). 지금 정거장은 멈추면 실제 앱이 위를 덮는다 */
export function CoverCard({ no, name, line }) {
  return (
    <div className="ds-window sx-fill sx-cover">
      <div className="sx-cover__body">
        <span className="ds-window__no">{String(no).padStart(2, '0')}</span>
        <h2 className="sx-cover__name">{name}</h2>
        <p className="sx-cover__line">{line}</p>
      </div>
    </div>
  )
}
