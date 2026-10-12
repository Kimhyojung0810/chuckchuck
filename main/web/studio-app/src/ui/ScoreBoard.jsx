/* 발표 채점판 — 개념 그래프 위에서 채점이 진행되는 모습 (10-13 사용자: 「발표 채점」 · 「기가 막히게 채점하는 걸 · 개념 그래프」).
   정직하게: 보이는 것은 앱의 실제 결과뿐이다.
   1) 그래프가 오면 → 뿌리에서 바깥으로 개념이 차례로 펼쳐진다
   2) 판정이 아직이면 → 「내 말에서 이 개념을 찾는 중」 스캔이 너비 우선으로 돈다(일을 하고 있다는 표시 — 결과처럼 보이지 않게 색 없음)
   3) 판정(alignment)이 오면 → 개념마다 판정 도장이 하나씩 찍히고(다룸 · 빠뜨림 · 어긋남 · 넘어가도 됨 · 판정 안 함),
      셈과 실제 커버리지(summary.coverage)가 올라간다. 숫자는 만들지 않는다 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { rig } from '../rig.js'
import { pickNodes, rootOf, bfsOrder, radialLayout, verdictOf, tally, phaseLine, shortLabel, VERDICT_WORD } from './scoreModel.js'

const SCAN_MS = 420
const STAMP_MS = 260   // 도장 하나에 인용 한 줄을 읽을 틈
const MARK = { ok: '✓', no: '✕', ct: '!', om: '–', na: '?' }

function useReduced() {
  return useMemo(() => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches, [])
}

/** 실제 커버리지로 세어 올라가는 숫자 */
/** 둥근 게이지 — 판정 중에는 판정한 비율(중성), 끝나면 실제 커버리지(에메랄드)로 차오른다 */
function Gauge({ value, final }) {
  const R = 30, C = 2 * Math.PI * R
  const v = Math.max(0, Math.min(100, value || 0))
  return (
    <svg className={`sx-gauge${final ? ' is-final' : ''}`} width="76" height="76" viewBox="0 0 76 76" aria-hidden="true">
      <circle cx="38" cy="38" r={R} className="sx-gauge__track" />
      <circle cx="38" cy="38" r={R} className="sx-gauge__fill" strokeDasharray={C} strokeDashoffset={C * (1 - v / 100)} transform="rotate(-90 38 38)" />
    </svg>
  )
}

function CountUp({ to, run }) {
  const [v, setV] = useState(0)
  useEffect(() => {
    if (!run || to == null) { setV(0); return undefined }
    let raf = 0
    const t0 = performance.now(), dur = 1400
    const tick = (now) => {
      const p = Math.min(1, (now - t0) / dur)
      setV(Math.round(to * (1 - Math.pow(1 - p, 3))))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [to, run])
  return <>{v}</>
}

export function ScoreBoard({ data, w, h }) {
  const reduced = useReduced()
  const graph = data && data.graph
  const alignment = data && data.alignment
  const steps = (data && data.steps) || {}
  const picked = useMemo(() => pickNodes(graph), [graph])
  const root = useMemo(() => rootOf(picked, graph && graph.thesis), [picked, graph])
  const order = useMemo(() => bfsOrder(picked, root), [picked, root])
  const gw = w - 48, gh = h - 168
  const pos = useMemo(() => radialLayout(picked, root, gw, gh), [picked, root, gw, gh])
  const byId = useMemo(() => new Map(picked.map((n) => [n.id, n])), [picked])

  // 1) 펼치기 — 그래프가 바뀌면 처음부터
  const [shown, setShown] = useState(0)
  const shownRef = useRef(0)
  shownRef.current = shown
  useEffect(() => {
    if (!order.length) { setShown(0); return undefined }
    if (reduced) { setShown(order.length); return undefined }
    setShown(0)
    let i = 0
    const id = setInterval(() => { i += 1; setShown(i); if (i >= order.length) clearInterval(id) }, 90)
    return () => clearInterval(id)
  }, [order, reduced])

  // 2) 스캔 — 판정 전, 펼친 뒤에만
  const [scan, setScan] = useState(-1)
  const scanning = !!graph && !alignment && shown >= order.length && order.length > 0
  useEffect(() => {
    if (!scanning || reduced) { setScan(-1); return undefined }
    let i = 0
    setScan(0)
    const id = setInterval(() => { i = (i + 1) % order.length; setScan(i) }, SCAN_MS)
    return () => clearInterval(id)
  }, [scanning, order, reduced])

  // 3) 도장 — 판정이 오면 너비 우선으로 하나씩
  const [stamped, setStamped] = useState(0)
  useEffect(() => {
    if (!alignment || !order.length) { setStamped(0); return undefined }
    if (reduced) { setStamped(order.length); return undefined }
    setStamped(0)
    let i = 0
    let iv = 0
    // 도장 전체를 ~5초 안에(개념이 많으면 빠르게, 하나에 140~260ms). 펼치기가 남았으면 그만큼 기다린다
    const step = Math.max(140, Math.min(STAMP_MS, Math.round(5000 / order.length)))
    const start = setTimeout(() => {
      iv = setInterval(() => { i += 1; setStamped(i); if (i >= order.length) clearInterval(iv) }, step)
    }, 90 * Math.max(0, order.length - shownRef.current) + 300)
    return () => { clearTimeout(start); clearInterval(iv) }
  }, [alignment, order, reduced])

  const verdicts = useMemo(() => new Map(order.map((id) => [id, verdictOf(alignment, id)])), [order, alignment])
  // 판정 근거 — aligned 는 내가 실제로 한 말(evidence), 그 밖은 판정 메모(note). 없으면 비운다(만들지 않는다)
  const items = useMemo(() => new Map(((alignment && alignment.items) || []).map((it) => [it.node_id, it])), [alignment])
  const stampedIds = order.slice(0, stamped)
  const t = tally(stampedIds.map((id) => verdicts.get(id)))
  const done = alignment && stamped >= order.length
  const coverage = alignment && alignment.summary && typeof alignment.summary.coverage === 'number' ? Math.round(alignment.summary.coverage * 100) : null
  // 끝나면 가장 무거운 「다룸」 개념과 내가 한 말로 마무리한다(있을 때만) — 마지막 도장이 「판정 안 함」 이면 맥이 빠졌다
  const featured = useMemo(() => {
    if (!alignment) return null
    const ok = order.filter((id) => verdicts.get(id) === 'ok' && items.get(id) && items.get(id).evidence)
    ok.sort((a, b) => ((byId.get(b) || {}).weight || 0) - ((byId.get(a) || {}).weight || 0))
    return ok[0] || null
  }, [alignment, order, verdicts, items, byId])
  const nowId = alignment ? (done && featured ? featured : stampedIds[stampedIds.length - 1]) : scan >= 0 ? order[scan] : null
  // 판정이 온 뒤 도장 · 게이지가 다 돌 때까지 스튜디오가 다음 정거장(질의응답)으로 미끄러지지 않게 붙잡는다
  useEffect(() => {
    if (!alignment || !order.length) { rig.hold = false; return undefined }
    if (!done) { rig.hold = true; return undefined }
    const id = setTimeout(() => { rig.hold = false }, 1800)   // 게이지가 차오르고 요약을 읽을 틈
    return () => clearTimeout(id)
  }, [alignment, order, done])
  useEffect(() => () => { rig.hold = false }, [])
  const nowNode = nowId ? byId.get(nowId) : null
  // 도장이 다 찍힌 뒤에 「채점했어요」 · 커버리지가 올라간다 — 숫자가 도장보다 먼저 뜨지 않게
  const line = alignment && !done ? '개념마다 판정을 매기고 있어요' : phaseLine({ phase: data && data.phase, steps, hasGraph: !!graph, hasAlign: !!alignment })
  const unrelated = alignment && (alignment.speech_match === 'unrelated' || alignment.basis === 'skipped')
  const flowIssues = data && data.flow && Array.isArray(data.flow.issues) ? data.flow.issues : null

  const cx = gw / 2, cy = gh / 2
  const P = (id) => { const p = pos.get(id) || { x: 0, y: 0 }; return { x: cx + p.x, y: cy + p.y } }
  const rOf = (n) => (n.id === root ? 22 : 8 + 10 * Math.max(0, Math.min(1, n.weight || 0)))

  return (
    <div className="sx-score" data-done={done ? '1' : ''}>
      <header className="sx-score__head">
        <div>
          <span className="sx-score__eyebrow">발표 채점</span>
          <h2 className="sx-score__title" aria-live="polite">{line}</h2>
        </div>
        <div className="sx-score__meter" aria-label="개념 커버리지">
          <Gauge value={coverage != null && done ? coverage : alignment ? (stamped / Math.max(1, order.length)) * 100 : 0} final={!!done} />
          {coverage != null
            ? done
              ? <><strong><CountUp to={coverage} run={done} /><small>%</small></strong><span>개념 커버리지{unrelated ? ' · 판정 안 함' : ''}</span></>
              : <><strong className="is-wait">{Math.round((stamped / Math.max(1, order.length)) * 100)}<small>%</small></strong><span>판정한 개념</span></>
            : <><strong className="is-wait">—</strong><span>채점이 끝나면 보여요</span></>}
        </div>
      </header>

      <div className="sx-score__stage">
        {!graph && (
          <div className="sx-score__empty"><span className="sx-score__spin" aria-hidden="true" />자료의 개념 지도를 그리고 있어요</div>
        )}
        {graph && (
          <svg className="sx-score__svg" viewBox={`0 0 ${gw} ${gh}`} width={gw} height={gh} role="img" aria-label="개념 지도와 채점">
            <defs>
              <radialGradient id="sxCore" cx="50%" cy="50%" r="50%">
                <stop offset="0%" stopColor="rgba(111,181,154,.22)" /><stop offset="100%" stopColor="rgba(111,181,154,0)" />
              </radialGradient>
            </defs>
            <circle cx={cx} cy={cy} r={Math.min(gw, gh) * 0.3} fill="url(#sxCore)" />
            {order.slice(0, shown).map((id) => {
              const n = byId.get(id)
              if (!n || !n.parent || !pos.has(n.parent)) return null
              const a = P(n.parent), b = P(id)
              const va = verdicts.get(n.parent), vb = verdicts.get(id)
              const lit = alignment && stampedIds.includes(id) && va === 'ok' && vb === 'ok'
              return <line key={`e-${id}`} className={`sx-score__edge${lit ? ' is-lit' : ''}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} />
            })}
            {!alignment && scan >= 0 && order[scan] && order[scan] !== root && (() => {
              const a = P(root), b = P(order[scan])
              return <line key={`beam-${scan}`} className="sx-score__beam" x1={a.x} y1={a.y} x2={b.x} y2={b.y} />
            })()}
            {order.slice(0, shown).map((id, i) => {
              const n = byId.get(id)
              const p = P(id)
              const r = rOf(n)
              const v = stampedIds.includes(id) ? verdicts.get(id) : null
              const isScan = !alignment && scan >= 0 && order[scan] === id
              return (
                <g key={id} className={`sx-node${v ? ` is-${v} is-stamped` : ''}${isScan ? ' is-scan' : ''}${id === nowId ? ' is-now' : ''}${id === root ? ' is-root' : ''}`}
                  transform={`translate(${p.x} ${p.y})`} style={{ '--i': i }}>
                  <title>{`${n.label}${v ? ` — ${VERDICT_WORD[v]}` : ''}`}</title>
                  {isScan && <circle className="sx-node__ping" r={r + 10} />}
                  {v && <circle className="sx-node__burst" r={r + 4} />}
                  <circle className="sx-node__dot" r={r} />
                </g>
              )
            })}
          </svg>
        )}
        {graph && (
          <div className="sx-score__labels" style={{ width: gw, height: gh }} aria-hidden="true">
            {order.slice(0, shown).map((id) => {
              const n = byId.get(id)
              const p = P(id)
              const r = rOf(n)
              const v = stampedIds.includes(id) ? verdicts.get(id) : null
              const isNow = id === nowId
              const label = id === root || r >= 14 || isNow
              return (
                <span key={id} className={`sx-tag${id === root ? ' is-root' : ''}${isNow ? ' is-now' : ''}`} style={{ left: p.x, top: p.y, '--r': `${r}px` }}>
                  {v && <i className={`sx-tag__mark is-${v}`}>{MARK[v]}</i>}
                  {v === 'ok' && <b className="sx-tag__spark" aria-hidden="true">{[0, 1, 2, 3, 4, 5].map((k) => <s key={k} style={{ '--a': `${k * 60}deg` }} />)}</b>}
                  {label && <em className="sx-tag__label">{shortLabel(n.label, id === root ? 22 : 14)}</em>}
                </span>
              )
            })}
          </div>
        )}
      </div>

      <footer className="sx-score__foot">
        <div className="sx-score__now" key={nowId || 'none'}>
          {nowNode ? (
            <>
              <span className={`sx-score__verdict${alignment && verdicts.get(nowId) ? ` is-${verdicts.get(nowId)}` : ''}`}>
                {alignment ? (VERDICT_WORD[verdicts.get(nowId)] || '') : '찾는 중'}
              </span>
              <b className="sx-score__concept">{nowNode.label}</b>
              {alignment && (() => {
                const it = items.get(nowId)
                const v = verdicts.get(nowId)
                if (v === 'ok' && it && it.evidence) return <span className="sx-score__said"><small>내 말</small><q className="sx-score__quote">{it.evidence}</q></span>
                if (v === 'na') return <q className="sx-score__quote is-dim">이 개념은 판정하지 않았어요</q>
                if (it && it.note) return <q className="sx-score__quote is-dim">{it.note}</q>
                return null
              })()}
            </>
          ) : <span className="sx-score__concept is-dim">{graph ? '\u00a0' : '자료를 읽고 있어요'}</span>}
        </div>
        <ul className="sx-score__tally" aria-label="판정 셈">
          {['ok', 'no', 'ct', 'om', 'na'].map((k) => (alignment && (t[k] || k === 'ok' || k === 'no')) ? (
            <li key={k} className={`is-${k}`}><i aria-hidden="true">{MARK[k]}</i>{VERDICT_WORD[k]} <b key={t[k]} className="sx-bump">{t[k]}</b></li>
          ) : null)}
          {!alignment && graph && <li className="is-wait">개념 {order.length}개를 내 말과 맞춰 봐요</li>}
        </ul>
        {done && (
          <p className="sx-score__sum">
            개념 {order.length}개 중 <b>{t.ok}개</b>를 내 말로 다뤘어요{t.no ? ` · ${t.no}개를 빠뜨렸어요` : ''}{t.ct ? ` · ${t.ct}개가 자료와 어긋났어요` : ''}{t.na ? ` · ${t.na}개는 판정하지 않았어요` : ''}
            {flowIssues ? ` · 흐름: 빠진 연결 ${flowIssues.filter((x) => x.kind === 'missing_link').length} · 순서 뒤바뀜 ${flowIssues.filter((x) => x.kind === 'order_jump').length}` : ''}
          </p>
        )}
      </footer>
    </div>
  )
}
