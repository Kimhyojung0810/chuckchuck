/* 앱 안의 것을 무대로 꺼낸다 (10-13 사용자 「배경을 적극적으로 · 크다 작다 하는 삐약이는 관중으로 · 질의응답도 비슷하게」).
   ② 발표: 앱의 자료 창(#vrSlide)은 화면 밖에 크게 두고(그래야 장 그림이 선명하게 그려진다) 무대 스크린이 그 장을 비춘다.
          앱의 반응 삐약이(#vrBird)는 숨기고 앞줄 큰 관중 삐약이가 같은 반응(빨라요 · 느려요 · 작아요 · 커요)을 말한다.
   ③ 질의응답: 앱의 진행 삐약이 카드(#bcHost)를 숨기고 왼쪽 앞 큰 심사위원 삐약이가 역할 · 몇 번째 질문 · 하는 말 · 목소리(구 · 막대)를 보인다.
   읽기만 한다 — 넘기기 · 다시 듣기 · 보내지 않기는 숨긴 앱 단추를 누른다. 카메라 · 녹음 · 받아쓰기 코드는 그대로. */
import { useEffect, useRef, useState } from 'react'
import { VoiceViz } from '../voice/VoiceViz.jsx'
import { rig } from '../rig.js'
import { createMicMeter } from '../voice/meter.js'
import { qaVoiceState, viewFor, speakMsFor, rmsToVolume, pickVolume } from '../voice/signal.js'

const MIRROR_CSS = `
  html.sx-stage #vrCall #vrSlide { position: fixed !important; left: -10000px !important; top: 0 !important; width: 1100px !important; height: 720px !important; }
  html.sx-stage #vrCall #vrBird { display: none !important; }
  html.sx-judge #bcHost { display: none !important; }
`

const text = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '')

function readPresent(doc) {
  const call = doc.getElementById('vrCall')
  if (!call) return null
  const img = call.querySelector('#vrSlide #slideImage')
  const card = call.querySelector('#vrSlide #slideCardWrap')
  const canvas = call.querySelector('#vrSlide canvas')
  const bar = call.querySelector('#vrSlide .vr-prog i')
  const bird = call.querySelector('#vrBird')
  const line = call.querySelector('#vrLine')
  return {
    slide: {
      src: img ? img.getAttribute('src') : canvas && canvas.width ? canvas.toDataURL('image/webp', 0.9) : '',
      html: !img && card ? card.innerHTML : '',
      no: text(call.querySelector('#slideNo')),
      title: text(call.querySelector('#slideTitle')),
      caption: text(call.querySelector('#vrCaption')),
      prog: bar ? bar.style.width : '',
    },
    bird: {
      cue: bird ? bird.dataset.cue || 'idle' : 'idle',
      line: line && !line.hidden ? text(line) : '',
      status: text(call.querySelector('#vrStatus')),
    },
  }
}

function readJudge(doc) {
  const host = doc.getElementById('bcHost')
  if (!host) return null
  const cancel = doc.getElementById('bcSendCancel')
  const bird = host.querySelector('.bq-bird')
  return {
    role: text(host.querySelector('.bc-host-text b')),
    count: text(doc.getElementById('bcCount')),
    say: text(doc.getElementById('bqJudgeSay')),
    mood: bird ? bird.dataset.mood || 'neutral' : 'neutral',
    mic: host.dataset.mic === 'on',
    thinking: !!doc.getElementById('coachThinking'),
    cancel: !!(cancel && !cancel.hidden),
  }
}

/** 분석 기다림 — 실제 파이프라인 단계(rec · stt · align · flow · questions)의 상태만 (rehearsal.js RH_WAIT_STEPS) */
const WAIT_PEEK = `(()=>{ try {
  const o = (typeof nf !== 'undefined' && nf && nf.pipelineOut) || {};
  const pre = (typeof precompute !== 'undefined' && precompute && precompute.state && precompute.state.graph) || null;
  return { graph: o.graph || pre || null, alignment: o.alignment || null, flow: o.flow || null, phase: (typeof nf !== 'undefined' && nf && nf.pipelinePhase) || '' };
} catch (e) { return null } })()`

function readWait(doc) {
  const stage = doc.querySelector('#bqStage[data-screen="wait"]')
  if (!stage) return null
  const steps = {}
  stage.querySelectorAll('.rh-wait-steps li[data-step]').forEach((li) => { steps[li.dataset.step] = li.dataset.state || 'wait' })
  // 개념 그래프 · 판정 · 흐름은 앱 전역(nf.pipelineOut · precompute)에 있다 — 같은 출처라 iframe 안에서 읽는다(쓰지 않는다)
  let peek = null
  try { peek = doc.defaultView.eval(WAIT_PEEK) } catch (_) { peek = null }
  return { steps, title: text(doc.getElementById('rhWaitTitle')), ...(peek || {}) }
}

/* 큰 객체(그래프 · 판정)는 문자열로 비교하지 않는다 — 참조가 바뀌면 바뀐 것(앱은 갱신마다 새 객체를 만든다) */
const refIds = new WeakMap()
let refSeq = 0
const refKey = (o) => { if (!o || typeof o !== 'object') return '-'; if (!refIds.has(o)) refIds.set(o, ++refSeq); return refIds.get(o) }
const stateKey = (mode, s) => (mode === 'wait' && s
  ? JSON.stringify([s.steps, s.title, s.phase, refKey(s.graph), refKey(s.alignment), refKey(s.flow)])
  : JSON.stringify(s))

/** 앱을 6번/초 읽는다 — 바뀌었을 때만 다시 그린다. mode: 'present' | 'qa' | null */
export function useAppMirror(api, mode) {
  const [state, setState] = useState(null)
  useEffect(() => {
    let last = ''
    let styled = null
    const tick = () => {
      const doc = api.current?.doc()
      if (!doc || !doc.documentElement) return
      if (doc !== styled) { const st = doc.createElement('style'); st.textContent = MIRROR_CSS; doc.head.appendChild(st); styled = doc }
      const s = mode === 'present' ? readPresent(doc) : mode === 'qa' ? readJudge(doc) : mode === 'wait' ? readWait(doc) : null
      doc.documentElement.classList.toggle('sx-stage', mode === 'present' && !!s)
      doc.documentElement.classList.toggle('sx-judge', mode === 'qa' && !!s)
      const key = stateKey(mode, s)
      if (key !== last) { last = key; setState(s) }
    }
    tick()
    const id = setInterval(tick, 160)
    return () => {
      clearInterval(id)
      const doc = api.current?.doc()
      if (doc && doc.documentElement) doc.documentElement.classList.remove('sx-stage', 'sx-judge')
    }
  }, [api, mode])
  return state
}

/** 숨긴 앱 단추 누르기 */
export const pressApp = (api, sel) => { const el = api.current?.doc()?.querySelector(sel); if (el && !el.disabled) el.click() }

/* ── ② 웹캠 위 PPT — 작은 떠 있는 창(PiP), 「크게」 로 넓힌다 (10-13 사용자: 「발표 자료를 사람 카메라에 overlay」 · 리뉴얼 「웹캠이 가장 크고 PPT 는 PiP」).
   앱의 자료 창과 같은 밝은 유리 판. iframe(카메라) 위 고정 층이라 곡선이 멈췄을 때만 보인다 ── */
export function SlideOverlay({ slide, box, onNav, big, onToggle }) {
  const ref = useRef(null)
  useEffect(() => {
    let raf = 0, was = null
    const t = () => {
      const s = rig.settled && !rig.dragging
      if (s !== was && ref.current) { was = s; ref.current.classList.toggle('is-shown', s) }
      raf = requestAnimationFrame(t)
    }
    raf = requestAnimationFrame(t)
    return () => cancelAnimationFrame(raf)
  }, [])
  return (
    <div ref={ref} className="sx-screen" style={{ left: box.left, top: box.top, width: box.w }} aria-label="발표 자료">
      <div className="sx-screen__stage">
        {slide && slide.src ? <img className="sx-screen__img" src={slide.src} alt={slide.title || '지금 장'} draggable="false" />
          : slide && slide.html ? <div className="sx-screen__doc" dangerouslySetInnerHTML={{ __html: slide.html }} />
          : <p className="sx-screen__empty">자료를 불러오고 있어요</p>}
        <button type="button" className="sx-screen__side is-prev" onClick={() => onNav(-1)} aria-label="이전 장">‹</button>
        <button type="button" className="sx-screen__side is-next" onClick={() => onNav(1)} aria-label="다음 장">›</button>
      </div>
      <div className="sx-screen__cap">
        <strong>{slide ? slide.title : ''}</strong>
        <span className="sx-screen__no">{slide ? slide.no : ''}</span>
        <span className="sx-screen__prog" aria-hidden="true"><i style={{ width: (slide && slide.prog) || '0%' }} /></span>
        <button type="button" className="sx-screen__size" onClick={onToggle} aria-pressed={!!big}>{big ? '작게' : '크게'}</button>
      </div>
      {slide && slide.caption && <p className="sx-screen__sub">{slide.caption}</p>}
    </div>
  )
}

const CUE_MOOD = { idle: 'neutral', listen: 'happy', fast: 'excited', loud: 'excited', slow: 'curious', quiet: 'curious' }

/** 앞줄 큰 관중 삐약이 — 내 말 빠르기 · 크기에 반응한다 */
export function Listener({ bird, size, onEar }) {
  const cue = bird ? bird.cue : 'idle'
  const mood = CUE_MOOD[cue] || 'neutral'
  const said = bird && bird.line
  return (
    <div className="sx-listener" data-cue={cue} style={{ '--seat': `${size}px` }}>
      <img key={cue} className="sx-listener__chick" src={`assets/chick-solar-${mood}.svg`} alt="" draggable="false" />
      <div className="sx-listener__talk">
        <p className={`sx-bubble${said ? ' is-said' : ''}`} aria-live="polite">{said || (bird && bird.status) || '말하면 반응해요'}</p>
        <span className="sx-listener__name">앞줄 삐약이 · 내 말 빠르기와 크기를 들어요</span>
        <button type="button" className="sx-listener__ear" onClick={onEar}>다시 듣기</button>
      </div>
    </div>
  )
}

/* ── ③ 심사위원 — 목소리 신호는 앱의 상태(생각 · 마이크 · 새 말)를 따른다 ── */
function useJudgeVoice(judge) {
  const listeners = useRef(new Set())
  const adapter = useRef({ subscribe: (fn) => { listeners.current.add(fn); return () => listeners.current.delete(fn) } }).current
  const meter = useRef(null)
  const speakUntil = useRef(0)
  const lastSay = useRef('')
  const [view, setView] = useState(null)
  const want = useRef({ thinking: false, mic: false })
  if (judge) {
    want.current = { thinking: judge.thinking, mic: judge.mic }
    if (judge.say && judge.say !== lastSay.current) { lastSay.current = judge.say; speakUntil.current = Date.now() + speakMsFor(judge.say) }
  }
  useEffect(() => {
    meter.current = createMicMeter()
    let raf = 0, t = 0, shown = null
    const tick = (now) => {
      raf = requestAnimationFrame(tick)
      if (now - t < 33) return
      t = now
      const state = qaVoiceState({ thinking: want.current.thinking, micOn: want.current.mic, speaking: Date.now() < speakUntil.current })
      const v = viewFor('qa', state)
      if (v !== shown) { shown = v; setView(v) }
      if (state === 'listening') meter.current.open(); else meter.current.close()
      const own = meter.current.read()
      const real = state === 'listening' && own !== null ? rmsToVolume(own) : null
      const { volume } = pickVolume(real, state, now)
      const sig = { state, inputVolume: state === 'listening' ? volume : 0, outputVolume: state === 'speaking' ? volume : 0 }
      listeners.current.forEach((fn) => fn(sig))
    }
    raf = requestAnimationFrame(tick)
    return () => { cancelAnimationFrame(raf); meter.current.close() }
  }, [])
  return { adapter, view }
}

export function Judge({ judge, size, onCancel }) {
  const { adapter, view } = useJudgeVoice(judge)
  const mood = judge ? (judge.mood === 'grumpy' ? 'curious' : judge.mood) : 'neutral'
  return (
    <div className="sx-judge" style={{ '--seat': `${size}px` }}>
      <div className="sx-judge__talk">
        {judge && judge.count && <span className="sx-judge__count">{judge.count}</span>}
        <p className="sx-bubble is-said sx-bubble--down" aria-live="polite">{(judge && judge.say) || '곧 질문할게요'}</p>
        {judge && judge.cancel && <button type="button" className="sx-judge__cancel" onClick={onCancel}>보내지 않기</button>}
      </div>
      <div className="sx-judge__seat">
        <img className="sx-judge__chick" src={`assets/chick-exaone-${['happy', 'curious', 'excited', 'neutral'].includes(mood) ? mood : 'neutral'}.svg`} alt="" draggable="false" />
        <span className="sx-judge__voice" data-voice={view || ''}>
          <VoiceViz view={view} adapter={adapter} barsSize={60} orbSize={86} label="심사위원 목소리" />
        </span>
      </div>
      <span className="sx-judge__name"><b>{(judge && judge.role) || '심사위원'}</b> 역할을 맡은 삐약이</span>
    </div>
  )
}
