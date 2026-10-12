/* 발표 채점판 — 순수 계산 (etc/tests/js/score_model.smoke.mjs). 데이터는 앱의 실제 결과만:
   ConceptGraph(nodes · edges · thesis) · AlignmentDoc(items[].verdict · summary.coverage) — main/pipeline/contracts.py
   판정 색은 앱과 같은 규칙(app.js STATUS_FROM_VERDICT · conceptUnjudgedWhy): aligned→ok · missing→no · contradiction→ct · justified_skip→om,
   녹음이 자료와 맞지 않거나(speech_match unrelated · basis skipped) 판정이 대체값(decided_by fallback)이면 na(판정 안 함) */

export const MAX_NODES = 24

export const VERDICT = { aligned: 'ok', missing: 'no', contradiction: 'ct', justified_skip: 'om' }
export const VERDICT_WORD = { ok: '다룸', no: '빠뜨림', ct: '어긋남', om: '넘어가도 됨', na: '판정 안 함' }

/** 무게 큰 개념부터 max 개 — 고른 개념의 조상은 같이 넣어 나무가 끊기지 않게 */
export function pickNodes(graph, max = MAX_NODES) {
  const nodes = (graph && graph.nodes) || []
  if (!nodes.length) return []
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const parentOf = new Map()
  ;(graph.edges || []).forEach((e) => { if (e.kind !== 'relates' && byId.has(e.from) && byId.has(e.to)) parentOf.set(e.to, e.from) })
  nodes.forEach((n) => { if (n.parent_id && !parentOf.has(n.id) && byId.has(n.parent_id)) parentOf.set(n.id, n.parent_id) })
  const keep = new Set()
  const sorted = [...nodes].sort((a, b) => (b.weight || 0) - (a.weight || 0))
  if (graph.thesis && byId.has(graph.thesis)) keep.add(graph.thesis)
  for (const n of sorted) {
    if (keep.size >= max) break
    const chain = []
    for (let id = n.id; id && !keep.has(id); id = parentOf.get(id)) chain.push(id)
    if (keep.size + chain.length > max && keep.size) continue
    chain.forEach((id) => keep.add(id))
  }
  return nodes.filter((n) => keep.has(n.id)).map((n) => ({ ...n, parent: keep.has(parentOf.get(n.id)) ? parentOf.get(n.id) : null }))
}

/** 뿌리 — thesis, 없으면 부모 없는 것 중 가장 무거운 것 */
export function rootOf(picked, thesis) {
  if (thesis && picked.some((n) => n.id === thesis)) return thesis
  const roots = picked.filter((n) => !n.parent).sort((a, b) => (b.weight || 0) - (a.weight || 0))
  return roots.length ? roots[0].id : null
}

/** 너비 우선 순서 — 스캔 · 도장이 뿌리에서 바깥으로 퍼진다. 부모 없는 다른 나무도 뒤에 잇는다 */
export function bfsOrder(picked, root) {
  const kids = new Map(picked.map((n) => [n.id, []]))
  picked.forEach((n) => { if (n.parent && kids.has(n.parent)) kids.get(n.parent).push(n.id) })
  kids.forEach((arr) => arr.sort((a, b) => weightOf(picked, b) - weightOf(picked, a)))
  const order = []
  const seen = new Set()
  const starts = [root, ...picked.filter((n) => !n.parent && n.id !== root).map((n) => n.id)].filter(Boolean)
  for (const s of starts) {
    const q = [s]
    while (q.length) {
      const id = q.shift()
      if (seen.has(id)) continue
      seen.add(id); order.push(id)
      ;(kids.get(id) || []).forEach((c) => q.push(c))
    }
  }
  return order
}
const weightOf = (picked, id) => (picked.find((n) => n.id === id) || {}).weight || 0

/**
 * 방사형 나무 — 뿌리가 가운데, 깊이마다 바깥 고리. 잎 수만큼 각을 나눠 갖는다.
 * 반환: Map(id → { x, y, depth }) — 가운데 원점, 반지름은 r(0..1) × min(W,H)/2 비율
 */
export function radialLayout(picked, root, W, H) {
  const pos = new Map()
  if (!picked.length) return pos
  const kids = new Map(picked.map((n) => [n.id, []]))
  picked.forEach((n) => { if (n.parent && kids.has(n.parent)) kids.get(n.parent).push(n.id) })
  const tops = [root, ...picked.filter((n) => !n.parent && n.id !== root).map((n) => n.id)].filter(Boolean)
  const leaves = (id) => { const k = kids.get(id) || []; return k.length ? k.reduce((s, c) => s + leaves(c), 0) : 1 }
  const depthOf = new Map()
  const walkDepth = (id, d) => { depthOf.set(id, d); (kids.get(id) || []).forEach((c) => walkDepth(c, d + 1)) }
  tops.forEach((t) => walkDepth(t, t === root ? 0 : 1))
  const maxD = Math.max(1, ...depthOf.values())
  const R = Math.min((W * 0.47) / 1.25, (H * 0.47) / 0.92)   // 가로 1.25 · 세로 .92 로 늘린 뒤 판에 꽉 차게
  const ring = (d) => (d === 0 ? 0 : R * (0.28 + 0.72 * (d / maxD)))
  const place = (id, a0, a1) => {
    const d = depthOf.get(id) || 0
    const a = (a0 + a1) / 2
    // 가로로 조금 넓게(화면이 가로로 길다)
    pos.set(id, { x: Math.cos(a) * ring(d) * 1.25, y: Math.sin(a) * ring(d) * 0.92, depth: d })
    const k = kids.get(id) || []
    const total = k.reduce((s, c) => s + leaves(c), 0)
    let at = a0
    k.forEach((c) => { const span = (a1 - a0) * (leaves(c) / total); place(c, at, at + span); at += span })
  }
  const all = tops.reduce((s, t) => s + leaves(t), 0)
  let at = -Math.PI / 2
  tops.forEach((t) => {
    const span = Math.PI * 2 * (leaves(t) / all)
    if (t === root) place(t, at, at + span)
    else place(t, at, at + span)
    at += span
  })
  pos.set(root, { x: 0, y: 0, depth: 0 })
  return pos
}

/** 노드 하나의 판정 (ok · no · ct · om · na) — 결과가 없으면 null */
export function verdictOf(alignment, id) {
  if (!alignment || !Array.isArray(alignment.items)) return null
  const it = alignment.items.find((x) => x.node_id === id)
  if (!it) return null
  if (alignment.speech_match === 'unrelated' || alignment.basis === 'skipped' || it.decided_by === 'fallback') return 'na'
  return VERDICT[it.verdict] || 'na'
}

/** 도장 찍힌 노드들의 셈 */
export function tally(verdicts) {
  const t = { ok: 0, no: 0, ct: 0, om: 0, na: 0 }
  verdicts.forEach((v) => { if (v && t[v] !== undefined) t[v] += 1 })
  return t
}

/** 단계 문구 — 앱의 실제 진행(pipelinePhase · 기다림 단계 상태)만 말한다 */
export function phaseLine({ phase = '', steps = {}, hasGraph = false, hasAlign = false }) {
  if (hasAlign) return '채점했어요 — 개념마다 내 말과 맞춰 봤어요'
  if (steps.rec === 'run' || /^(queued|encoding)/.test(phase)) return '발표 녹음을 정리하고 있어요'
  if (steps.stt === 'run' || /^stt/.test(phase)) return '내가 한 말을 받아쓰고 있어요'
  if (!hasGraph) return '자료에서 개념 지도를 그리고 있어요'
  return '내 말에서 개념을 하나씩 찾고 있어요'
}

/** 긴 개념 이름 줄이기 */
export function shortLabel(s, n = 14) {
  const t = String(s || '').replace(/\s+/g, ' ').trim()
  return t.length > n ? `${t.slice(0, n - 1)}…` : t
}
