/**
 * 리포트 2.0 「질문은 이렇게 골랐어요」 — 네 모델 Q&A 후보 판 (4단계, 2026-10-17).
 * 네 국내 모델(Solar · A.X · Mi:dm · EXAONE)이 개념 그래프의 자리(슬롯)마다 질문 후보를 쓰고 → 코드 거르기 → 서로 평가 → 고른 과정을 보여 준다.
 * 판정이 아니라 「과정 보여 주기」다 — 판정 색(맞음 · 틀림)을 쓰지 않는다. 주인공은 「그래프의 어디를 물었나」.
 * 데이터: docs/qa-ensemble/CONTRACT.md §1 + main/server/qa_board.py (graph · paths · rounds · tracks)
 *
 * window.ReportQaBoard = { model(board, qa) → 뷰모델 | null, screens(ctx) → { board, slot, round, entry, link } }
 * report_v2.js 가 스택 화면(board · slot:<id> · round:<n>)으로 밀어 넣는다.
 */
(function () {
  const MODELS = {
    solar4: { name: 'Solar Pro4', short: 'Solar', org: 'Upstage', logo: 'assets/logo-solar.svg', mark: true },
    solar: { name: 'Solar Pro3', short: 'Solar3', org: 'Upstage', logo: 'assets/logo-solar.svg', mark: true },
    ax: { name: 'A.X', short: 'A.X', org: 'SK텔레콤', logo: 'assets/logo-ax.png', mark: false },
    midm: { name: 'Mi:dm', short: 'Mi:dm', org: 'KT', logo: 'assets/logo-midm.png', mark: false },
    exaone: { name: 'EXAONE', short: 'EXAONE', org: 'LG AI연구원', logo: 'assets/logo-exaone.png', mark: true },
  };
  const modelOf = (m) => MODELS[m] || { name: m || '모델', org: '', logo: '', mark: true };
  const PATTERN = {
    P1: '핵심 주장', P2: '근거 충분성', P3: '빈 고리', P4: '결론을 좌우하는 조건', P5: '주장 잇기', P6: '방법 선택',
    P7: '한계 · 반례', P8: '개념의 역할', P9: '함정', P10: '옮겨 쓰기', voice: '발표를 듣고',
  };
  const SIGNAL = { skipped_reason: '결론만 말하고 이유를 건너뛴 곳', vague: '짧게 지나간 곳', misexplained: '자료와 어긋나게 설명한 곳', weak_answer: '앞 답에서 약했던 곳' };
  /** 버림 까닭 — [칩, 문장]. 이름은 _ens_slots.check_candidate 의 reasons 그대로 */
  const REASON = {
    micro: ['숫자 · 용어만 확인', '숫자나 용어 하나만 확인하는 질문이라 뺐어요'],
    generic: ['어느 발표에나 쓸 질문', '이 자료만의 낱말이 없어 다른 발표에도 쓸 수 있는 질문이라 뺐어요'],
    vague_deixis: ['가리키는 말이 모호', '「이 조건」처럼 무엇을 가리키는지 모를 말을 써서 뺐어요'],
    off_slot: ['맡은 자리를 안 물음', '그래프에서 맡은 자리를 묻지 않아서 뺐어요'],
    multi_ask: ['한 번에 둘 이상', '한 번에 둘 이상을 물어서 뺐어요'],
    impolite: ['말투', '말투가 맞지 않아서 뺐어요'],
    too_long: ['너무 긺', '질문이 너무 길어서 뺐어요'],
    not_korean: ['한국어 아님', '한국어로 쓰지 않아서 뺐어요'],
    line_id_leak: ['줄 번호 노출', '자료 줄 번호를 그대로 드러내서 뺐어요'],
    false_premise: ['틀린 전제', '자료와 다른 전제를 깔고 물어서 뺐어요'],
    number_not_in_deck: ['자료에 없는 숫자', '자료에 없는 숫자를 써서 뺐어요'],
    off_deck_terms: ['자료 밖 낱말', '자료에 없는 말을 많이 써서 뺐어요'],
    bad_line_ref: ['근거 줄 어긋남', '근거로 댄 자료 줄이 질문과 맞지 않아서 뺐어요'],
    answer_len: ['모범답 길이', '모범답이 너무 짧거나 길어서 뺐어요'],
    answer_fragment: ['모범답이 조각', '모범답이 문장이 아니어서 뺐어요'],
    answer_messy: ['모범답이 어수선', '모범답이 어수선해서 뺐어요'],
    answer_number_not_in_deck: ['모범답에 없는 숫자', '모범답에 자료에 없는 숫자가 있어서 뺐어요'],
    answer_off_deck: ['모범답이 자료 밖', '모범답이 자료 밖 지식으로 살을 붙여서 뺐어요'],
    answer_mismatch: ['모범답이 질문과 어긋남', '모범답이 질문에 맞는 답이 아니어서 뺐어요'],
    trap_premise_missing: ['함정 전제 빠짐', '함정 질문인데 틀린 전제를 담지 않아서 뺐어요'],
    duplicate: ['다른 모델과 겹침', '다른 모델과 거의 같은 질문이라 하나만 남겼어요'],
    repeats_asked: ['이미 물은 것과 겹침', '이미 물은 질문과 겹쳐서 뺐어요'],
    skipped: ['모델이 건너뜀', '모델이 「자료가 답을 담고 있지 않다」며 쓰지 않았어요'],
  };
  const reasonChip = (r) => (REASON[r] || [r])[0];
  const reasonLine = (r) => (REASON[r] || [null, r])[1];
  const WEIGHTS = { core: 0.4, grounded: 0.2, specific: 0.25, clear: 0.15 };
  /** 한 심사의 가중 점수 0~100 (f08_ensemble.peer_score 와 같은 무게) */
  const scoreOf = (s) => Math.round(100 * Object.keys(WEIGHTS).reduce((a, k) => a + WEIGHTS[k] * ((Number(s[k]) || 1) - 1) / 4, 0));
  /** 자료 줄의 표 구분자(| --- |)를 걷는다 — report_v2.js plainDeck 과 같은 규칙 */
  const plain = (t) => String(t || '').replace(/\|\s*-{3,}\s*/g, ' ').replace(/^\s*\|\s*|\s*\|\s*$/g, '').replace(/\s*\|\s*/g, ' · ').replace(/(?:·\s*){2,}/g, '· ').replace(/\s{2,}/g, ' ').trim();
  const norm = (t) => String(t || '').replace(/\s+/g, '').replace(/[?？.!。]+$/, '');
  const sum = (xs) => xs.reduce((a, b) => a + b, 0);

  /* ─── 순수: 판 → 뷰모델 (etc/tests/js/report_qaboard.smoke.mjs) ─────────────────────────── */
  function model(board, qa) {
    if (!board || !Array.isArray(board.candidates) || !board.candidates.length) return null;
    const slots = board.slots || [];
    const slotOf = Object.fromEntries(slots.map((s) => [s.id, s]));
    const cands = board.candidates;
    const dropped = board.dropped || [];
    const rounds = (board.rounds || []).slice().sort((a, b) => a.n - b.n);
    const byUid = Object.fromEntries(cands.map((c) => [c.uid, c]));
    const byText = new Map(cands.map((c) => [norm(c.question), c]));
    const roundByText = new Map(rounds.map((r) => [norm(r.question), r]));
    const item = (n, c, r) => (r ? { n, kind: 'voice', round: r, uid: r.uid, by: r.by, question: r.question, node_id: r.node_id, slot: r.slot || (byUid[r.uid] || {}).slot || '' }
      : { n, kind: 'pool', cand: c, uid: c.uid, by: c.model, question: c.question, node_id: c.node_id, slot: c.slot });
    // 실제로 받은 질문 순서 — Q&A 기록과 글자로 맞춘다. 하나도 안 맞으면(샘플 · 기록 없음) 판이 고른 순서
    const asked = [];
    const results = (qa && Array.isArray(qa.results) ? qa.results : []).map((r) => r.question);
    let hit = 0;
    results.forEach((t, k) => {
      const r = roundByText.get(norm(t)); const c = byText.get(norm(t));
      if (r || c) { hit += 1; asked.push({ ...item(k + 1, c, r), qid: (qa.results[k] || {}).id || '' }); }
      else asked.push({ n: k + 1, kind: 'other', question: t, qid: (qa.results[k] || {}).id || '' });
    });
    const fromQa = hit > 0;
    if (!fromQa) {
      asked.length = 0;
      const picked = (board.picked || []).map((u) => byUid[u]).filter(Boolean);
      // 3번+ 기록은 샘플 판에서만 순서대로 늘어놓는다 — 내 판인데 Q&A 기록과 하나도 안 맞으면 그 기록은 내 것이 아닐 수 있다(같은 파일 = 같은 세션)
      const own = board.source ? rounds : [];
      const head = own.length ? picked.slice(0, 2) : picked;
      head.forEach((c, k) => asked.push(item(k + 1, c, null)));
      own.forEach((r) => asked.push(item(r.n || asked.length + 1, null, r)));
    }
    const askedBySlot = {}; const askedByNode = {};
    asked.forEach((a) => {
      if (a.kind === 'pool' && a.slot) (askedBySlot[a.slot] = askedBySlot[a.slot] || []).push(a.n);
      if (a.node_id) (askedByNode[a.node_id] = askedByNode[a.node_id] || []).push(a.n);
    });
    const slotView = slots.map((s) => {
      const kept = cands.filter((c) => c.slot === s.id);
      const top = kept.reduce((m, c) => (!m || c.peer > m.peer ? c : m), null);
      return { ...s, kept, dropped: dropped.filter((d) => d.slot === s.id), top, asked: askedBySlot[s.id] || [], path: (board.paths || {})[s.id] || [s.label] };
    });
    const voiceAll = rounds.flatMap((r) => r.candidates || []);
    const voiceDrop = rounds.flatMap((r) => r.dropped || []);
    const askedModel = (a) => (a.kind === 'voice' ? a.by : a.kind === 'pool' ? a.cand.model : '');
    const models = (board.models || []).map((m) => ({
      key: m, ...modelOf(m),
      written: cands.filter((c) => c.model === m).length + dropped.filter((d) => d.model === m).length,
      passed: cands.filter((c) => c.model === m).length,
      asked: asked.filter((a) => askedModel(a) === m).length,
      reviews: sum(cands.map((c) => (c.peer_scores || []).filter((p) => p.reviewer === m && !p.self).length)),
      voice: voiceAll.filter((c) => c.model === m).length + voiceDrop.filter((d) => d.model === m).length,
      dead: ((board.timings || {}).dead_models || []).includes(m),
    }));
    const tally = {};
    [...dropped, ...voiceDrop].forEach((d) => (d.reasons || []).forEach((r) => { tally[r] = (tally[r] || 0) + 1; }));
    const calls = (board.calls || []).length + sum(rounds.map((r) => (r.calls || []).length));
    const picker = ((rounds.flatMap((r) => r.calls || []).find((c) => c.role === 'pick') || {}).model) || '';
    return {
      slots: slotView, slotOf, asked, fromQa, rounds, byUid, models, picker,
      reasons: Object.entries(tally).sort((a, b) => b[1] - a[1]),
      totals: {
        written: cands.length + dropped.length, passed: cands.length,
        reviews: sum(cands.map((c) => (c.peer_scores || []).filter((p) => !p.self).length)),
        asked: asked.filter((a) => a.kind !== 'other').length, voice: voiceAll.length + voiceDrop.length,
        sec: (board.timings || {}).total_sec || 0, calls,
      },
      graph: (board.graph && board.graph.nodes) || [],
      source: board.source || null,
    };
  }

  /* ─── 미니맵 — 그래프를 층(핵심 주장 · 주장 · 개념)으로 눕히고 물은 노드에 번호 ─────────── */
  function layout(nodes) {
    // 층은 노드 종류로 — 핵심 주장(thesis) · 주장(claim) · 개념(그 밖). 그래프 깊이는 덱마다 들쭉날쭉해서(개념 아래 주장도 있다) 종류가 「어디」를 더 잘 말한다
    const by = Object.fromEntries(nodes.map((n) => [n.id, n]));
    const rowOf = (n) => (n.kind === 'thesis' ? 0 : n.kind === 'claim' ? 1 : 2);
    const rows = [[], [], []];
    nodes.forEach((n) => rows[rowOf(n)].push(n));
    if (!rows[0].length && rows[1].length) rows[0].push(rows[1].shift());
    const W = 360; const X0 = 66; const GAP = 74;
    const present = rows.map((r, k) => (r.length ? k : -1)).filter((k) => k >= 0);
    const Y = {}; present.forEach((k, i) => { Y[k] = 30 + i * GAP; });
    const pos = {};
    const anc = (n) => { let cur = n; const seen = new Set(); while (cur && cur.parent_id && by[cur.parent_id] && !seen.has(cur.id)) { seen.add(cur.id); cur = by[cur.parent_id]; if (pos[cur.id]) return pos[cur.id].x; } return 0; };
    rows.forEach((row, k) => {
      if (!row.length) return;
      const ordered = row.map((n, i) => [n, anc(n), -(Number(n.weight) || 0), i]).sort((a, b) => a[1] - b[1] || a[2] - b[2] || a[3] - b[3]).map((x) => x[0]);
      ordered.forEach((n, i) => { pos[n.id] = { x: X0 + (W - X0 - 14) * (ordered.length === 1 ? 0.5 : (i + 0.5) / ordered.length), y: Y[k], d: k }; });
    });
    return { pos, by, rows, Y, W, H: 30 + (present.length - 1) * GAP + 40 };
  }

  /* ─── 화면 ─────────────────────────────────────────────────────────── */
  function screens(ctx) {
    const { esc, I, asset } = ctx;
    const logo = (m, cls = '') => {
      const x = modelOf(m);
      return `<span class="qb-m ${x.mark ? '' : 'is-word'} ${cls}">${x.logo ? `<img src="${esc(asset(x.logo))}" alt="${x.mark ? '' : esc(x.name)}">` : ''}${x.mark || !x.logo ? `<b>${esc(x.name)}</b>` : ''}</span>`;
    };
    /** 표 머리용 작은 표시 — 그림 위 · 짧은 이름 아래 (낱말 로고는 그림만) */
    const mini = (m) => { const x = modelOf(m); return `<span class="qb-mini${x.mark ? '' : ' is-word'}" title="${esc(x.name)}">${x.logo ? `<img src="${esc(asset(x.logo))}" alt="${esc(x.name)}">` : ''}${x.mark || !x.logo ? `<small>${esc(x.short || x.name)}</small>` : ''}</span>`; };
    const logos = (ms) => `<span class="qb-logos">${ms.map((m) => `<img src="${esc(asset(modelOf(m).logo))}" alt="">`).join('')}</span>`;
    const chip = (t, cls = '') => `<span class="qb-chip ${cls}">${esc(t)}</span>`;
    const pathChips = (labels) => {
      const p = (labels || []).slice().reverse();
      return `<ol class="qb-path">${p.map((l, k) => `<li class="${k === p.length - 1 ? 'is-here' : ''}"><span>${esc(k === 0 ? '핵심 주장' : k === p.length - 1 ? '물은 곳' : '이어지는 주장')}</span><b>${esc(l)}</b></li>`).join('')}</ol>`;
    };
    /** 이 질문이 무엇을 물었나 — 음성 신호가 있으면 그 신호, 없으면(묶음에서 올라온 3번+) 자리의 묻는 방식 */
    const whatOf = (a, Q) => (a.kind === 'voice' ? (SIGNAL[a.round.signal_kind] || PATTERN[(Q.slotOf[a.slot] || {}).pattern] || '앞 답까지 듣고 다시 고름')
      : a.kind === 'pool' ? PATTERN[(Q.slotOf[a.slot] || {}).pattern] || '' : '준비해 둔 질문');
    const routeOf = (a) => (a.kind === 'voice' ? `round:${a.n}` : a.kind === 'pool' ? `slot:${a.slot}` : '');
    const askLine = (a, Q) => {
      if (a.kind === 'voice') return `${whatOf(a, Q)} · ${modelOf(a.by).name}${a.round.signal_kind ? '' : ' · 미리 만든 후보'}`;
      if (a.kind === 'pool') { const s = Q.slotOf[a.slot] || {}; return `${PATTERN[s.pattern] || ''} · ${modelOf(a.by).name} · 서로 평가 ${Math.round((a.cand.peer || 0) * 100)}점`; }
      return '준비해 둔 질문';
    };

    function minimap(Q) {
      if (!Q.graph.length) return '';
      const L = layout(Q.graph);
      const askedNodes = {};
      Q.asked.forEach((a) => { if (a.node_id && L.pos[a.node_id]) (askedNodes[a.node_id] = askedNodes[a.node_id] || []).push(a); });
      const slotNodes = new Set(Q.slots.map((s) => s.node_id));
      // 물은 노드 → 루트까지의 줄은 강조 (그래프의 「어디」)
      const hot = new Set();
      Object.keys(askedNodes).forEach((id) => { let cur = L.by[id]; const seen = new Set(); while (cur && cur.parent_id && L.by[cur.parent_id] && !seen.has(cur.id)) { seen.add(cur.id); hot.add(cur.id); cur = L.by[cur.parent_id]; } });
      const edges = Q.graph.filter((n) => n.parent_id && L.pos[n.parent_id] && L.pos[n.id]).map((n) => {
        const a = L.pos[n.parent_id]; const b = L.pos[n.id]; const my = (a.y + b.y) / 2;
        // 같은 줄끼리(개념 아래 개념)는 줄 아래로 휘게 — 곧게 그으면 점들을 덮는다
        const d = a.y === b.y ? `M${a.x.toFixed(1)} ${a.y} Q${((a.x + b.x) / 2).toFixed(1)} ${a.y + 14 + Math.min(14, Math.abs(a.x - b.x) / 8)} ${b.x.toFixed(1)} ${b.y}`
          : `M${a.x.toFixed(1)} ${a.y} C${a.x.toFixed(1)} ${my} ${b.x.toFixed(1)} ${my} ${b.x.toFixed(1)} ${b.y}`;
        return `<path class="${hot.has(n.id) ? 'is-hot' : ''}" d="${d}"/>`;
      }).join('');
      const dense = L.rows[2].length > 18;
      const dots = Q.graph.filter((n) => L.pos[n.id]).map((n) => {
        const p = L.pos[n.id]; const as = askedNodes[n.id];
        if (as) {
          const first = as[0]; const label = as.map((a) => a.n).join('·');
          const r = label.length > 2 ? 15 : 12.5;
          return `<g class="qb-hit" data-push="${esc(routeOf(first))}" style="--k:${first.n}"><circle class="qb-asked" cx="${p.x.toFixed(1)}" cy="${p.y}" r="${r}"/><text x="${p.x.toFixed(1)}" y="${p.y + 4.2}" class="qb-num">${esc(label)}</text></g>`;
        }
        const r = n.kind === 'thesis' ? 8 : p.d === 1 ? 5.5 : dense ? 2.6 : 3.4;
        return `<circle class="qb-n k-${esc(n.kind || 'concept')}${slotNodes.has(n.id) ? ' is-slot' : ''}" cx="${p.x.toFixed(1)}" cy="${p.y}" r="${slotNodes.has(n.id) ? r + 1.5 : r}"/>`;
      }).join('');
      const rowLabel = ['핵심 주장', '주장', '개념'].map((t, k) => (L.rows[k].length ? `<text x="4" y="${L.Y[k] + 4}" class="qb-rowlab">${t}</text>` : '')).join('');
      const thesis = L.rows[0][0];
      return `<div class="qb-map">
        <svg viewBox="0 0 ${L.W} ${L.H}" role="img" aria-label="개념 그래프에서 물은 곳 ${Object.keys(askedNodes).length}군데">${rowLabel}<g class="qb-edges">${edges}</g>${dots}</svg>
        <ol class="qb-legend">${Object.entries(askedNodes).sort((x, y) => x[1][0].n - y[1][0].n).map(([id, as]) => `<li><button type="button" data-push="${esc(routeOf(as[0]))}"><span class="qb-n1">${esc(as.map((a) => a.n).join('·'))}</span><span><b>${esc((L.by[id] || {}).label || '')}</b><small>${esc(as.map((a) => whatOf(a, Q)).join(' · '))}</small></span></button></li>`).join('')}</ol>
        ${thesis ? `<p class="qb-mapcap">맨 위가 발표의 핵심 주장 「${esc(thesis.label)}」이에요. 번호가 물은 곳, 빈 고리는 후보만 만든 곳이에요.</p>` : ''}
      </div>`;
    }

    /** 후보 카드 — 모델이 쓴 질문 하나. 뽑힌 것 · 이 자리 1등 · 버린 것 */
    function card(c, { askedN = 0, top = false, drop = null, fromPool = false } = {}) {
      const pct = Math.round((c.peer || 0) * 100);
      const tag = askedN ? chip(`${askedN}번으로 물었어요`, 'is-picked') : drop ? chip('뺐어요', 'is-out') : top ? chip('이 자리 1등', 'is-top') : fromPool ? chip('미리 만든 후보', '') : '';
      return `<article class="qb-card${askedN ? ' is-picked' : ''}${drop ? ' is-out' : ''}">
        <header>${logo(c.model)}${tag}</header>
        <p class="qb-q">${esc(c.question || '(질문을 쓰지 않았어요)')}</p>
        ${drop ? `<div class="qb-why">${(drop.reasons || []).map((r) => `<p>${esc(reasonLine(r))}</p>`).join('')}</div>`
          : `${c.why ? `<p class="qb-cap"><b>이렇게 물은 까닭</b> ${esc(c.why)}</p>` : ''}
          ${c.peer_scores && c.peer_scores.length ? `<div class="qb-meter"><span>서로 평가</span><i style="--w:${pct}%"></i><b>${pct}</b></div>` : ''}
          ${(c.twins || []).length ? `<p class="qb-cap">${esc(c.twins.map((m) => modelOf(m).name).join(' · '))}도 거의 같은 질문을 써서 하나로 합쳤어요</p>` : ''}`}
      </article>`;
    }

    /** 서로 평가 표 — 줄 = 후보(쓴 모델), 칸 = 평가한 모델. 자기 것은 빼고 평균 */
    function matrix(kept, models) {
      const rated = kept.filter((c) => (c.peer_scores || []).length);
      if (!rated.length) return '<p class="nv-empty">이 자리는 서로 평가를 하지 못했어요.</p>';
      const head = models.map((m) => `<th scope="col">${mini(m)}</th>`).join('');
      const rows = rated.map((c) => {
        const cells = models.map((m) => {
          const s = (c.peer_scores || []).find((p) => p.reviewer === m);
          if (!s) return '<td class="is-none">–</td>';
          if (s.self) return `<td class="is-self" title="자기 후보라 점수에서 뺐어요">자기<br>것</td>`;
          return `<td><b>${scoreOf(s)}</b>${s.answer_ok === false ? '<small>모범답 의심</small>' : ''}</td>`;
        }).join('');
        return `<tr><th scope="row">${mini(c.model)}</th>${cells}<td class="is-avg"><b>${Math.round((c.peer || 0) * 100)}</b></td></tr>`;
      }).join('');
      return `<div class="qb-table"><table><thead><tr><th scope="col"><span class="qb-th">쓴 ↓ 평가 →</span></th>${head}<th scope="col">평균</th></tr></thead><tbody>${rows}</tbody></table></div>
        <p class="nv-note">누가 썼는지 가리고 순서를 섞어 매겼어요. 핵심을 묻는가 40% · 이 자료만의 질문인가 25% · 자료에 근거하나 20% · 분명한가 15%로 100점을 만들고, 자기 후보에 준 점수는 평균에서 뺐어요.</p>`;
    }

    function board() {
      const Q = ctx.Q();
      if (!Q) return { title: '질문은 이렇게 골랐어요', short: '고른 과정', html: '<p class="nv-empty">이 리포트엔 네 모델이 고른 기록이 없어요.</p>' };
      const T = Q.totals;
      const step = (n, cap, k) => `<li style="--k:${k}"><b>${n}</b><span>${cap}</span></li>`;
      return {
        title: '질문은 이렇게 골랐어요', short: '고른 과정', eyebrow: `네 국내 AI 모델 · ${T.sec ? `${Math.round(T.sec)}초` : ''}`,
        html: `
        ${Q.source && Q.source.note ? `<div class="nv-callout nv-samplenote"><b>샘플이에요</b><p>${esc(Q.source.note)}</p></div>` : ''}
        <section class="qb-hero">
          <p class="qb-hero-lead">네 모델이 개념 그래프의 자리마다 질문을 쓰고, 서로 평가한 뒤 골랐어요.</p>
          <ol class="qb-funnel">${step(T.written, '모델이 쓴 후보', 0)}${step(T.passed, '거르기 통과', 1)}${step(T.reviews, '서로 평가', 2)}${step(T.asked, Q.fromQa ? '내가 받은 질문' : '고른 질문', 3)}</ol>
          <div class="qb-hero-foot">${logos(Q.models.map((m) => m.key))}<span>${T.calls ? `AI 호출 ${T.calls}번` : ''}${T.voice ? ` · 발표를 듣고 쓴 후보 ${T.voice}개` : ''}${Q.models.some((m) => m.dead) ? ` · ${Q.models.filter((m) => m.dead).map((m) => m.name).join(' · ')}는 이번에 후보 응답이 깨져 평가에서 빠졌어요` : ''}</span></div>
        </section>
        <h3 class="nv-sec">그래프의 어디를 물었나</h3>
        <div class="nv-card qb-mapcard">${minimap(Q)}</div>
        <h3 class="nv-sec">${Q.fromQa ? '받은 질문' : '고른 질문'}</h3>
        <div class="nv-group">${Q.asked.map((a) => {
          const r = routeOf(a);
          return `<${r ? `button type="button" data-push="${esc(r)}"` : 'div'} class="nv-row${r ? '' : ' is-static'}"><span class="qb-n1">${a.n}</span><span class="nv-row-main"><b>${esc(a.question)}</b><small>${esc(askLine(a, Q))}</small></span>${r ? `<i class="nv-chev">${I.chev}</i>` : ''}</${r ? 'button' : 'div'}>`;
        }).join('')}</div>
        ${Q.fromQa ? '' : '<p class="nv-note">Q&A 기록과 맞춰 볼 질문이 없어서, 판이 고른 순서로 보여 줘요.</p>'}
        <h3 class="nv-sec">모델마다 맡은 일</h3>
        <div class="nv-group">${Q.models.map((m) => `<div class="nv-row is-static qb-mrow"><div class="qb-mhead">${logo(m.key, 'is-lg')}<small>${esc(m.org)}</small>${m.asked ? `<span class="nv-val">질문 ${m.asked}개</span>` : ''}</div><span class="qb-roles">${[
          m.dead ? '후보 응답이 깨져 이번엔 빠졌어요' : m.written ? `후보 ${m.written}개 · 통과 ${m.passed}개` : '',
          m.reviews ? `서로 평가 ${m.reviews}건` : '',
          m.voice ? `발표 듣고 후보 ${m.voice}개` : '',
          Q.picker === m.key ? '3번부터 최종 선택' : '',
        ].filter(Boolean).map((t) => chip(t)).join('')}</span></div>`).join('')}</div>
        <p class="nv-note">자리(그래프의 노드 × 묻는 방식)는 코드가 정하고, 패턴마다 잘 쓰는 두 모델에게 맡겨요. 평가는 넷이 다 해요.</p>
        ${Q.reasons.length ? `<h3 class="nv-sec">거르기에서 뺀 후보</h3>
        <div class="nv-card"><div class="qb-chips">${Q.reasons.map(([r, n]) => `<span class="qb-chip is-count">${esc(reasonChip(r))}<b>${n}</b></span>`).join('')}</div>
          <p class="nv-note" style="margin:12px 0 0">숫자 하나 · 용어 하나를 확인하는 질문은 빼요. 이 자료의 핵심을 이해했는지 묻는 질문만 남겨요.</p></div>` : ''}
        <h3 class="nv-sec">자리마다 보기</h3>
        <div class="nv-group">${Q.slots.map((s) => `<button type="button" class="nv-row" data-push="slot:${esc(s.id)}"><span class="qb-pat">${esc((s.pattern || '').replace('P', ''))}</span><span class="nv-row-main"><b>${esc(s.label)}</b><small>${esc(PATTERN[s.pattern] || s.pattern)} · 후보 ${s.kept.length + s.dropped.length}개${s.asked.length ? ` · ${s.asked.join('·')}번으로 물음` : ''}</small></span><i class="nv-chev">${I.chev}</i></button>`).join('')}</div>`,
      };
    }

    function slot(id) {
      const Q = ctx.Q();
      const s = Q && Q.slots.find((x) => x.id === id);
      if (!s) return { title: '자리', html: '<p class="nv-empty">이 자리의 기록이 없어요.</p>' };
      const askedN = s.asked[0] || 0;
      const desc = String(s.pattern_desc || '').split(' — ')[1] || s.pattern_desc || '';
      const ordered = s.kept.slice().sort((a, b) => (Q.asked.some((x) => x.uid === b.uid) - Q.asked.some((x) => x.uid === a.uid)) || (b.peer - a.peer));
      const pick = ordered.find((c) => Q.asked.some((x) => x.uid === c.uid)) || null;
      const reviewers = Q.models.map((m) => m.key);
      return {
        title: s.label, short: PATTERN[s.pattern] || '자리', eyebrow: `${askedN ? `${askedN}번 질문` : '묻지 않은 자리'} · ${PATTERN[s.pattern] || s.pattern}`,
        html: `
        <div class="nv-card qb-where"><p class="qb-k">이 자리에서 묻는 것</p><p class="qb-ask">${esc(desc)}</p>${pathChips(s.path)}
          ${(s.slides || []).length ? `<p class="nv-cap">근거 ${esc(s.slides.join(' · '))}장${s.partner_label ? ` · 이어지는 주장 「${esc(s.partner_label)}」` : ''}</p>` : ''}</div>
        <h3 class="nv-sec">모델마다 쓴 후보 <small>${s.kept.length + s.dropped.length}개</small></h3>
        <div class="nv-pager qb-pager">${ordered.map((c) => card(c, { askedN: (Q.asked.find((x) => x.uid === c.uid) || {}).n || 0, top: c === s.top && !pick })).join('')}${s.dropped.map((d) => card(d, { drop: d })).join('')}</div>
        <p class="nv-note">옆으로 넘겨 보세요. 거르기를 통과한 후보만 서로 평가를 받아요.</p>
        <h3 class="nv-sec">서로 평가</h3>
        ${matrix(s.kept, reviewers)}
        <h3 class="nv-sec">왜 이 질문이었나</h3>
        <div class="nv-card">${pick ? `<p class="nv-body">${askedN <= 2
          ? '1 · 2번은 발표가 끝나자마자 나와야 해서 AI 를 다시 부르지 않고 골랐어요. 그래프에서 무게가 큰 자리(핵심 주장일수록 커요)이면서 서로 평가가 높은 후보예요.'
          : '음성 후보가 늦거나 없을 때를 대비해 미리 만든 묶음의 순서대로 냈어요.'}</p>
          <p class="qb-stats">${chip(`자리 무게 ${Number(s.score || 0).toFixed(2)}`)}${chip(`서로 평가 ${Math.round((pick.peer || 0) * 100)}점`)}${chip(`${modelOf(pick.model).name} 작성`)}</p>`
          : `<p class="nv-body">이 자리는 이번엔 묻지 않았어요. 같은 노드를 이미 물었거나 질문 수가 찼어요.${s.top ? ` 이 자리 1등은 ${esc(modelOf(s.top.model).name)} 후보(서로 평가 ${Math.round(s.top.peer * 100)}점)였어요.` : ''}</p>`}</div>
        ${(pick || s.top) && (pick || s.top).answer ? `<h3 class="nv-sec">자료가 기대한 답</h3><div class="nv-card"><p class="nv-body">${esc((pick || s.top).answer)}</p>${(pick || s.top).quote ? `<p class="qb-quote"><span>${esc((pick || s.top).slide_no || '')}장</span>${esc(plain((pick || s.top).quote))}</p>` : ''}</div>` : ''}`,
      };
    }

    function round(nArg) {
      const Q = ctx.Q();
      const n = Number(nArg) || 0;
      const a = Q && Q.asked.find((x) => x.kind === 'voice' && x.n === n);
      const r = a ? a.round : Q && Q.rounds.find((x) => x.n === n);
      if (!r) return { title: `${n}번 질문`, html: '<p class="nv-empty">이 질문을 고른 기록이 없어요.</p>' };
      const used = (r.signals || []).find((s) => s.id === r.signal) || null;
      const pickedFromPool = !String(r.uid || '').includes(':v') && Q.byUid[r.uid];
      const vc = (r.candidates || []).slice().sort((x, y) => (y.uid === r.uid) - (x.uid === r.uid));
      const pathL = r.path || [];
      return {
        title: `${n}번 질문`, short: `${n}번 질문`, eyebrow: r.signal_kind ? '발표와 앞 답을 듣고 골랐어요' : '앞 답까지 듣고 다시 골랐어요',
        html: `
        <div class="nv-card"><p class="qb-k">물은 질문 ${chip(`${modelOf(r.by).name} 작성`)}</p><p class="qb-ask">${esc(r.question)}</p></div>
        <h3 class="nv-sec">AI 가 들은 신호</h3>
        ${(r.signals || []).length ? `<div class="qb-sigs">${r.signals.slice().sort((x, y) => (used && y.id === used.id) - (used && x.id === used.id)).map((s) => `<div class="nv-card qb-sig${used && s.id === used.id ? ' is-used' : ''}">
            <p class="qb-k">${esc(SIGNAL[s.kind] || s.kind)}${used && s.id === used.id ? chip('이 질문의 재료', 'is-picked') : ''}</p>
            <p class="qb-ask">${esc(s.label)}</p>
            ${s.speech_quote ? `<p class="qb-said"><span>발표에서 한 말</span>«${esc(s.speech_quote)}»</p>` : ''}
            ${s.deck_text ? `<p class="qb-quote"><span>${esc(s.slide_no || '')}장</span>${esc(plain(s.deck_text))}</p>` : ''}
            ${s.note ? `<p class="nv-cap">${esc(s.note)}</p>` : ''}</div>`).join('')}</div>`
          : '<p class="nv-empty">이번엔 발표에서 따로 짚을 신호가 없어서 미리 만든 묶음에서 골랐어요.</p>'}
        <h3 class="nv-sec">모델마다 쓴 후보 <small>${(r.candidates || []).length + (r.dropped || []).length}개</small></h3>
        <div class="nv-pager qb-pager">${pickedFromPool ? card(pickedFromPool, { askedN: n, fromPool: true }) : ''}${vc.map((c) => card(c, { askedN: c.uid === r.uid ? n : 0 })).join('')}${(r.dropped || []).map((d) => card(d, { drop: d })).join('')}</div>
        <h3 class="nv-sec">${r.substituted ? '이렇게 냈어요' : `${esc(modelOf(Q.picker || 'solar4').name)}가 고른 이유`}</h3>
        <div class="nv-card qb-reason">${logo(r.substituted ? r.by : (Q.picker || 'solar4'))}<blockquote>${esc(r.pick_reason || (r.substituted ? '음성 후보가 제때 오지 않아 미리 만든 묶음에서 냈어요.' : ''))}</blockquote>
          <p class="nv-cap">${r.substituted ? '기다리지 않게 묶음의 남은 1등을 바로 냈어요.' : '음성 후보와 미리 만든 묶음의 남은 상위 후보를, 쓴 모델을 가리고 섞어서 하나 골랐어요.'}${r.voice_sec ? ` 음성 후보 ${r.voice_sec.toFixed(1)}초` : ''}${r.pick_sec ? ` · 고르기 ${Number(r.pick_sec).toFixed(1)}초` : ''}</p></div>
        ${pathL.length ? `<h3 class="nv-sec">그래프 위치</h3><div class="nv-card">${pathChips(pathL)}</div>` : ''}
        ${r.answer ? `<h3 class="nv-sec">자료가 기대한 답</h3><div class="nv-card"><p class="nv-body">${esc(r.answer)}</p>${r.quote ? `<p class="qb-quote"><span>${esc(r.slide_no || '')}장</span>${esc(plain(r.quote))}</p>` : ''}</div>` : ''}`,
      };
    }

    /** 진입 줄 — Q&A 목록 위. 판이 없으면 그 까닭을 한 줄로(누를 곳 없음) */
    function entry(state) {
      const Q = ctx.Q();
      if (Q) {
        return `<button type="button" class="nv-row qb-entry" data-push="board"><span class="nv-ico i-green">${I.chart}</span><span class="nv-row-main"><b>질문은 이렇게 골랐어요</b><small>네 모델 · 후보 ${Q.totals.written}개 → 질문 ${Q.totals.asked}개</small></span>${logos(Q.models.map((m) => m.key))}<i class="nv-chev">${I.chev}</i></button>`;
      }
      const line = { loading: '네 모델이 고른 과정을 불러오고 있어요', single: '이번 질문은 한 모델이 골랐어요', missing: '네 모델이 고른 기록은 리포트를 처음 연 탭에서 볼 수 있어요' }[state];
      return line ? `<div class="nv-row is-static qb-entry is-off"><span class="nv-ico i-gray">${I.chart}</span><span class="nv-row-main"><b>질문은 이렇게 골랐어요</b><small>${esc(line)}</small></span></div>` : '';
    }

    /** Q&A 한 질문 화면 아래 — 이 질문을 고른 과정으로 */
    function link(questionText) {
      const Q = ctx.Q();
      if (!Q) return '';
      const a = Q.asked.find((x) => norm(x.question) === norm(questionText));
      const r = a ? routeOf(a) : '';
      if (!r) return '';
      return `<div class="nv-group" style="margin-top:24px"><button type="button" class="nv-row" data-push="${esc(r)}"><span class="nv-ico i-green">${I.chart}</span><span class="nv-row-main"><b>이 질문은 이렇게 골랐어요</b><small>${esc(askLine(a, Q))}</small></span><i class="nv-chev">${I.chev}</i></button></div>`;
    }

    return { board, slot, round, entry, link };
  }

  const api = { model, screens, layout, scoreOf, REASON, PATTERN, SIGNAL, MODELS };
  if (typeof window !== 'undefined') window.ReportQaBoard = api;
})();
