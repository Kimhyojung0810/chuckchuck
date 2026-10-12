/* ② 발표 — 앱의 하단 조작줄을 창 밖(정면 창 아래)으로 꺼낸다 (10-13 사용자 「버튼들은 아예 밖으로 빼도 괜찮지 않나」).
   앱의 조작줄(.vr-dock)은 숨기고 그 단추들을 그대로 비춘다 — 누르면 숨긴 앱 단추를 누른다(녹음 · 장 넘기기 · 마치기는 앱이 한다).
   위계: 「이전 · 다음」 이 장 넘기기의 주인공(양 끝, 크게), 가운데는 녹음 시계(밀리초) · 흐르는 파형 · 마치기.
   자료 위 ‹ › 는 앱 CSS 가 마우스를 올렸을 때만 작게 보인다. */
import { useEffect, useRef, useState } from 'react'
import { rig } from '../rig.js'
import { Waveform } from '../voice/Waveform.jsx'
import { rmsToVolume } from '../voice/signal.js'

const DOCK_OUT = 'sx-dock-out'
const DOCK_CSS = `html.${DOCK_OUT} #vrCall .vr-dock { display: none !important; }`

function shown(el, stop) {
  for (let n = el; n && n !== stop; n = n.parentElement) {
    if (n.hidden || getComputedStyle(n).display === 'none') return false
  }
  return true
}

/** 앱 조작줄의 단추들 — 숨긴 조작줄 안에서도 각자 보일 것만 */
function readDock(doc) {
  const dock = doc.querySelector('#vrCall .vr-dock')
  if (!dock) return null
  const items = [...dock.querySelectorAll('button')].filter((b) => shown(b, dock)).map((b) => {
    const nav = b.getAttribute('data-slide-nav')
    const kind = nav === '-1' ? 'prev' : nav === '1' ? 'next' : b.classList.contains('btn-primary') ? 'primary' : 'secondary'
    return { el: b, kind, label: b.textContent.trim().replace(/\s+/g, ' '), disabled: b.disabled }
  })
  const panel = doc.getElementById('recPanel')
  const clock = doc.getElementById('clock')
  return {
    items,
    live: !!(panel && panel.classList.contains('is-live')),
    sec: clock ? clock.textContent.split(':').reduce((a, v) => a * 60 + Number(v), 0) : 0,
    note: (dock.querySelector('.rec-copy span') || {}).textContent || '',
  }
}

const sig = (d) => d ? `${d.live}|${d.note}|${d.items.map((i) => `${i.kind}:${i.label}:${i.disabled}`).join(',')}` : ''

function fmtMs(ms) {
  const t = Math.max(0, ms)
  const m = Math.floor(t / 60000), s = Math.floor(t / 1000) % 60, r = Math.floor(t % 1000)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(r).padStart(3, '0')}`
}

/** 녹음 시계 — 앱 시계(초)에 맞춰 두고 그 사이를 밀리초로 잇는다 */
function Clock({ live, sec }) {
  const el = useRef(null)
  const t0 = useRef(0)
  useEffect(() => {
    const now = performance.now()
    if (!live) { t0.current = 0; return }
    if (!t0.current) t0.current = now - sec * 1000
    else if (Math.abs((now - t0.current) / 1000 - sec) > 0.95) t0.current = now - sec * 1000   // 앱 시계와 1초 넘게 어긋나면 다시 맞춘다
  }, [live, sec])
  useEffect(() => {
    if (!live) { if (el.current) el.current.textContent = fmtMs(0); return undefined }
    let raf = 0
    const tick = () => { if (el.current && t0.current) el.current.textContent = fmtMs(performance.now() - t0.current); raf = requestAnimationFrame(tick) }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [live])
  return <strong ref={el} className="sx-dock__clock" aria-label="발표 시간">{fmtMs(0)}</strong>
}

/**
 * @param api   AppFrame 이 내준 { doc(), win() }
 * @param rect  정면 창 자리 — 조작줄은 그 바로 아래
 * @param on    지금 ② 발표 정거장인가
 */
export function PresentDock({ api, rect, on }) {
  const [dock, setDock] = useState(null)
  const items = useRef([])
  const wrap = useRef(null)

  // 앱 조작줄을 4번/초 읽는다 — 바뀌었을 때만 다시 그린다
  useEffect(() => {
    let last = ''
    let styled = null
    const tick = () => {
      const doc = on ? api.current?.doc() : null
      const d = doc ? readDock(doc) : null
      if (doc && doc !== styled) {
        const st = doc.createElement('style'); st.textContent = DOCK_CSS; doc.head.appendChild(st); styled = doc
      }
      if (doc) doc.documentElement.classList.toggle(DOCK_OUT, !!d)
      items.current = d ? d.items : []
      const s = sig(d) + (d && d.live ? `|${d.sec}` : '')
      if (s !== last) { last = s; setDock(d) }
    }
    tick()
    const id = setInterval(tick, 250)
    return () => {
      clearInterval(id)
      const doc = api.current?.doc()
      if (doc) doc.documentElement.classList.remove(DOCK_OUT)
    }
  }, [on, api])

  // 곡선이 멈췄을 때만 (실제 앱 창과 같이)
  useEffect(() => {
    let raf = 0, was = null
    const t = () => {
      const s = rig.settled && !rig.dragging
      if (s !== was && wrap.current) { was = s; wrap.current.classList.toggle('is-shown', s) }
      raf = requestAnimationFrame(t)
    }
    raf = requestAnimationFrame(t)
    return () => cancelAnimationFrame(raf)
  }, [])

  if (!on || !dock) return null
  const press = (i) => () => { const it = items.current[i]; if (it && !it.el.disabled) it.el.click() }
  const read = () => {
    const f = api.current?.win()?.visionReadLevel   // 비전 리허설이 이미 재는 음량 — 마이크를 더 열지 않는다
    const r = typeof f === 'function' ? f() : null
    return r === null || r === undefined ? null : rmsToVolume(r)
  }
  const prev = dock.items.findIndex((i) => i.kind === 'prev')
  const next = dock.items.findIndex((i) => i.kind === 'next')
  const mids = dock.items.map((it, i) => ({ ...it, i })).filter((it) => it.kind !== 'prev' && it.kind !== 'next')
    .sort((a, b) => (a.kind === 'primary' ? -1 : 0) - (b.kind === 'primary' ? -1 : 0))

  return (
    <div ref={wrap} className="sx-dock" role="toolbar" aria-label="발표 조작"
      style={{ left: rect.left, width: rect.width, top: rect.top + rect.height + 14 }}>
      {prev >= 0 && <button type="button" className="sx-dock__nav" onClick={press(prev)} disabled={dock.items[prev].disabled}>
        <span aria-hidden="true">‹</span> 이전</button>}
      <div className="sx-dock__mid">
        {dock.live
          ? <span className="sx-dock__rec"><i aria-hidden="true" /> 발표 중 <Clock live={dock.live} sec={dock.sec} /></span>
          : dock.note && <span className="sx-dock__note">{dock.note}</span>}
        <Waveform active={dock.live} read={read} height={30} className="sx-dock__wave" label="마이크 파형" />
        {mids.map((it) => (
          <button key={it.i} type="button" className={`sx-dock__btn${it.kind === 'primary' ? ' is-primary' : ''}`}
            onClick={press(it.i)} disabled={it.disabled}>{it.label}</button>
        ))}
      </div>
      {next >= 0 && <button type="button" className="sx-dock__nav is-next" onClick={press(next)} disabled={dock.items[next].disabled}>
        다음 <span aria-hidden="true">›</span></button>}
    </div>
  )
}
