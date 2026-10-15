/* 발표 채점판 — 순수 계산 (etc/tests/js/score_model.smoke.mjs). 데이터는 앱의 실제 결과만:
   ConceptGraph(nodes · edges · thesis) · AlignmentDoc(items[].verdict · summary.coverage) — main/pipeline/contracts.py
   판정 색은 앱과 같은 규칙(app.js STATUS_FROM_VERDICT · conceptUnjudgedWhy): aligned→ok · missing→no · contradiction→ct · justified_skip→om,
   녹음이 자료와 맞지 않거나(speech_match unrelated · basis skipped) 판정이 대체값(decided_by fallback)이면 na(판정 안 함) */

export const MAX_NODES = 60   // InfraNodus 처럼 네트워크가 보이게 — 무게 큰 개념부터 60개 + 조상

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

/** 시드 고정 난수 — 같은 그래프면 늘 같은 배치 */
function rng(seed) {
  let x = 2166136261
  for (let i = 0; i < seed.length; i++) { x ^= seed.charCodeAt(i); x = Math.imul(x, 16777619) }
  return () => { x ^= x << 13; x ^= x >>> 17; x ^= x << 5; return ((x >>> 0) % 100000) / 100000 }
}

/** 같은 장에 함께 나온 개념끼리 — 실제 자료에서 나온 관계(옅은 점선). 장마다 무게 큰 셋끼리만 잇는다(털뭉치가 되지 않게) */
export function cooccurEdges(picked) {
  const bySlide = new Map()
  picked.forEach((n) => (n.slide_nos || []).forEach((s) => { if (!bySlide.has(s)) bySlide.set(s, []); bySlide.get(s).push(n) }))
  const seen = new Set()
  const out = []
  bySlide.forEach((ns) => {
    const top = [...ns].sort((a, b) => (b.weight || 0) - (a.weight || 0)).slice(0, 4)
    for (let i = 0; i < top.length; i++) for (let j = i + 1; j < top.length; j++) {
      const a = top[i].id, b = top[j].id
      const key = a < b ? `${a}|${b}` : `${b}|${a}`
      if (seen.has(key) || top[i].parent === b || top[j].parent === a) continue
      seen.add(key); out.push({ from: a, to: b, kind: 'slide' })
    }
  })
  return out
}

/**
 * 힘 기반 배치(InfraNodus 처럼 유기적인 네트워크) — 밀어내기 · 연결 당기기 · 가운데로 모으기. 뿌리는 가운데 고정.
 * groupOf: Map(id → 섹션 번호) — 주면 같은 섹션 개념이 제 자리(둘레의 몫)로 살짝 모인다(InfraNodus 의 주제 덩어리)
 * 반환: Map(id → { x, y, depth }) — 가운데 원점. depth 는 뿌리에서 부모를 따라 센 깊이(깊이 층 시차에 쓴다)
 */
export function forceLayout(picked, root, links, W, H, groupOf = null) {
  const pos = new Map()
  if (!picked.length) return pos
  const rand = rng(picked.map((n) => n.id).join('|'))
  const idx = new Map(picked.map((n, i) => [n.id, i]))
  const N = picked.length
  const px = new Float64Array(N), py = new Float64Array(N)
  const rx = W * 0.46, ry = H * 0.44
  picked.forEach((n, i) => { const a = rand() * Math.PI * 2, r = 0.3 + rand() * 0.6; px[i] = Math.cos(a) * rx * r; py[i] = Math.sin(a) * ry * r })
  const L = links.map((e) => [idx.get(e.from), idx.get(e.to), e.kind === 'parent' ? 1 : 0.35]).filter(([a, b]) => a !== undefined && b !== undefined)
  const k = Math.sqrt((rx * ry * 3.2) / N)
  const ri = root ? idx.get(root) : -1
  const nG = groupOf ? Math.max(0, ...groupOf.values()) + 1 : 0
  const ax = new Float64Array(N), ay = new Float64Array(N), hasA = new Uint8Array(N)
  if (nG > 1) picked.forEach((n, i) => {
    const g = groupOf.get(n.id)
    if (g === undefined) return
    const a = -Math.PI / 2 + (Math.PI * 2 * (g + 0.5)) / nG
    ax[i] = Math.cos(a) * rx * 0.6; ay[i] = Math.sin(a) * ry * 0.6; hasA[i] = 1
    px[i] = ax[i] + (rand() - 0.5) * rx * 0.3; py[i] = ay[i] + (rand() - 0.5) * ry * 0.3   // 처음부터 제 몫 근처에서
  })
  for (let it = 0; it < 320; it++) {
    const t = 1 - it / 320
    const fx = new Float64Array(N), fy = new Float64Array(N)
    for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
      let dx = px[i] - px[j], dy = py[i] - py[j]
      let d2 = dx * dx + dy * dy + 0.01
      const f = (k * k) / d2
      fx[i] += dx * f; fy[i] += dy * f; fx[j] -= dx * f; fy[j] -= dy * f
    }
    for (const [a, b, w] of L) {
      const dx = px[a] - px[b], dy = py[a] - py[b]
      const d = Math.sqrt(dx * dx + dy * dy) + 0.01
      const f = (d / k) * w
      fx[a] -= dx * f; fy[a] -= dy * f; fx[b] += dx * f; fy[b] += dy * f
    }
    for (let i = 0; i < N; i++) {
      fx[i] -= px[i] * 0.04; fy[i] -= py[i] * 0.06          // 가운데로(세로를 조금 더 — 판이 가로로 길다)
      if (hasA[i]) { fx[i] += (ax[i] - px[i]) * 0.09; fy[i] += (ay[i] - py[i]) * 0.09 }   // 같은 섹션끼리 제 몫으로
      const m = Math.sqrt(fx[i] * fx[i] + fy[i] * fy[i]) + 1e-6
      const step = Math.min(m, 24 * t + 1)
      px[i] += (fx[i] / m) * step; py[i] += (fy[i] / m) * step
      const e = (px[i] / rx) ** 2 + (py[i] / ry) ** 2       // 판 밖으로 나가지 않게(타원 안)
      if (e > 1) { const s = 1 / Math.sqrt(e); px[i] *= s; py[i] *= s }
    }
    if (ri >= 0) { px[ri] = 0; py[ri] = 0 }
  }
  const depthOf = new Map()
  const byId = new Map(picked.map((n) => [n.id, n]))
  const dep = (id, guard = 0) => {
    if (depthOf.has(id)) return depthOf.get(id)
    const n = byId.get(id)
    const d = !n || !n.parent || guard > 40 ? 0 : dep(n.parent, guard + 1) + 1
    depthOf.set(id, d); return d
  }
  picked.forEach((n, i) => pos.set(n.id, { x: px[i], y: py[i], depth: dep(n.id) }))
  return pos
}

/** 자료의 섹션(graph.sections) — 개념은 처음 나온 장이 든 섹션에 속한다 */
export function sectionsOf(graph, picked) {
  const secs = ((graph && graph.sections) || []).map((s) => ({ name: s.name, slides: new Set(s.slide_nos || []), ids: [] }))
  if (!secs.length) return []
  picked.forEach((n) => {
    const first = Math.min(...(n.slide_nos && n.slide_nos.length ? n.slide_nos : [Infinity]))
    const sec = secs.find((s) => s.slides.has(first))
    if (sec) sec.ids.push(n.id)
  })
  return secs.filter((s) => s.ids.length)
}

/** 섹션 하나의 채점 — 판정한 개념(판정 안 함 제외) 가운데 다룸 비율. 판정한 게 없으면 pct null */
export function sectionStat(ids, verdicts, stampedSet) {
  let judged = 0, ok = 0, done = 0
  ids.forEach((id) => {
    if (!stampedSet.has(id)) return
    done += 1
    const v = verdicts.get(id)
    if (v && v !== 'na') { judged += 1; if (v === 'ok') ok += 1 }
  })
  return { total: ids.length, done, judged, ok, pct: judged ? Math.round((ok / judged) * 100) : null }
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
