/* 실제 앱 — 지금 앱의 리허설 흐름(#/rehearsal …)을 iframe 하나로 정면 창 자리에 띄운다 (SPACE §6, 10-13 사용자).
   앱 코드 · 카메라 코드는 한 줄도 안 바뀐다. iframe 은 하나다 — 3D 창 안으로 옮기면 다시 불러 흐름이 날아가서,
   3D 위 고정 2D 층에 두고, 곡선이 멈췄을 때만 정면 창 자리에 정확히 겹쳐 보인다(창이 1:1 이라). 움직이는 동안은 3D 표지가 보인다. */
import { useEffect, useRef } from 'react'
import { rig } from '../rig.js'
import { stationOf, keyAction, trackHash, ST } from './keys.js'

export const APP_START = '/index.html#/rehearsal'

// 스튜디오 HUD 가 단계를 보인다 — 앱 위 띠의 이름표 · 단계 · 옆 메뉴는 감춘다(카메라 · 나가기 단추는 그대로)
const FRAME_CSS = `
  :root { --nav-w: 0px !important; }
  .sidenav, .topbar { display: none !important; }
  body { padding-left: 0 !important; }
  .bq-top .bq-brand, .bq-top .bq-steps-top, .vr-top .vr-pill { display: none !important; }
`
const PRIMARY = '.bq-cta, .btn-primary'
// 스튜디오 안에서만 앱에 입히는 옷 (css/studio-skin.css — 바탕 투명 · 초록 5% · 중성 면)
const SKIN_HREF = '/css/studio-skin.css?v=sk13'
const FIT_PAD = 72   // 업로드 장면 창 = 내용(.bq-pick) 높이 + 위아래 여백(studio-skin .bq-body 36px ×2)

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
 * @param onFit  (h | null) => void — 업로드 장면이면 내용 높이(창을 내용에 맞춘다), 아니면 null
 */
export function AppFrame({ rect, onStation, api, onFit }) {
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
    const doc = win.document
    // 분석 기다림은 발표와 같은 주소라 떠 있는 층으로 가른다 (#bqStage[data-screen=wait])
    // 리포트는 리포트 2.0 이 #app[data-rv2-root] 에 지금 뿌리 화면(결과 · 다시 보기 · 청중석 · 코칭 · 연습)을 적는다 — 정거장 다섯으로 가른다
    const app = doc.getElementById('app')
    const k = stationOf({ hash, wait: !!doc.querySelector('#bqStage[data-screen="wait"]'), rv2Root: (app && app.dataset.rv2Root) || '' })
    if (k < 0) {   // 앱의 「나가기」 · 홈 → 스튜디오는 처음 정거장(앱도 리허설 첫 화면으로) — 늘 절대 주소로
      win.location.replace(new URL(APP_START, location.origin).href)
      return
    }
    stack.current = trackHash(stack.current, hash)
    station.current = k
    onStation(k)
    // 업로드 장면은 창을 내용 크기에 맞춘다 (v3 — 큰 창이 공간을 가리지 않게)
    if (onFit) {
      const pick = k === ST.upload ? doc.querySelector('#bqStage[data-flow="rehearsal"] .bq-pick') : null
      onFit(pick ? Math.ceil(pick.getBoundingClientRect().height + FIT_PAD) : null)
    }
  }

  // 층(분석 기다림) · 내용 높이는 주소 없이 바뀐다 — 3번/초 다시 본다
  useEffect(() => {
    const id = setInterval(() => { try { if (frame.current?.contentWindow?.location.href !== 'about:blank') sync() } catch (_) { /* 다른 문서 */ } }, 330)
    return () => clearInterval(id)
  })

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
    if (what === 'tabNext' || what === 'tabPrev') {
      if (typeof win.__rv2Tab !== 'function') return false
      win.__rv2Tab(station.current - ST.report + (what === 'tabNext' ? 1 : -1))
      return true
    }
    if (what === 'slideNext' || what === 'slidePrev') {
      const b = doc.querySelector(`#vrCall .vr-dock [data-slide-nav="${what === 'slideNext' ? 1 : -1}"]`)
      if (!b || b.disabled) return false
      b.click()
      return true
    }
    return false
  }

  /** 키 하나 — 바깥(스튜디오)과 iframe 안이 같은 규칙 (SPACE §7) */
  const onKey = (e, active, inApp = false) => {
    if (e.defaultPrevented) return
    const what = keyAction({
      inApp,
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
      /** 리포트 탭 i(0 결과 · 1 다시 보기 · 2 청중석 · 3 코칭 · 4 연습)로 — 리포트 2.0 이 뿌리 화면을 바꾸면 sync 가 정거장을 옮긴다 */
      // 리포트에 와 있으면 그 리포트의 탭을, 아니면(발표를 아직 안 했으면) 미리 돌린 샘플 리포트의 그 탭을 연다 (10-16 사용자 「샘플 자료로 왔다 갔다」)
      tab: (i) => {
        const w = frame.current?.contentWindow
        if (!w) return
        const onReport = station.current >= ST.report && w.document.getElementById('app')?.classList.contains('rv2')
        if (onReport && typeof w.__rv2Tab === 'function') { w.__rv2Tab(i); return }
        w.__rv2WantTab = i
        w.location.hash = '#/rehearsal/report/demo'
      },
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
    doc.documentElement.classList.add('sx-studio')
    const skin = doc.createElement('link')
    skin.rel = 'stylesheet'
    skin.href = SKIN_HREF
    doc.head.appendChild(skin)
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
    doc.addEventListener('keydown', (e) => onKey(e, doc.activeElement, true))
    stack.current = []
    sync()
  }

  // 멈췄을 때만 보인다 — 움직이는 동안은 숨고(.2s) 3D 표지가 보인다. 숨겨도 iframe 은 그대로 돈다(카메라 · 녹음이 끊기지 않게 opacity 만)
  useEffect(() => {
    let raf = 0
    let shown = null
    const tick = () => {
      const show = rig.settled && !rig.dragging && !(rig.hold && station.current === 3)   // 채점 연출을 붙잡는 동안 질의응답 화면은 숨긴다
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
