/**
 * Report 2.0 — Evidence Graph (docs/report-v2/EVIDENCE_GRAPH.md). 순수 함수만 — 화면 · 저장 · 네트워크 없음.
 * 기존 분석 결과(파이프라인 응답 그대로)를 타입 있는 노드 · 엣지로 잇고, 인사이트마다 실제 근거로 가는 길이 있는지 검사한다.
 *
 * 원칙 (명세 §3):
 *  - 새 판정을 만들지 않는다. 판정 · 점수 · 문장은 원래 산출물에서 온다. 여기선 잇고 · 고르고 · 검사만 한다.
 *  - 인용은 받아쓰기 원문에서 **그대로 찾을 때만** 발화에 잇는다. 못 찾으면 `inferred`, 비면 `missing`.
 *  - 신뢰도 숫자를 지어내지 않는다 — 상태(supported · inferred · missing · conflicting · unsupported)와 등급(높음 · 보통 · 낮음)만.
 *
 * 브라우저: window.ReportGraph · 시험: etc/tests/js/report_graph.smoke.mjs (vm 으로 읽는다)
 */
(function (root) {
  const SCHEMA = 'reg/1';
  const VERDICT_STATUS = { aligned: 'ok', missing: 'no', contradiction: 'ct', justified_skip: 'om' };   // app.js STATUS_FROM_VERDICT 와 같다
  const SENT_END = /[.?!]$|(?:니다|어요|아요|에요|예요|해요|거든요|죠|네요|군요)[.?!]?$/;
  const UTT_GAP = 0.6;       // 이 초보다 길게 쉬면 발화를 끊는다 (실측 rec_weave: 0.6초 넘는 쉼 8번)
  const UTT_MAX = 12;        // 발화 하나가 이 초를 넘지 않게
  const TIER = { high: 3, mid: 2, low: 1, none: 0 };

  const norm = (s) => String(s || '').replace(/[\s"'“”‘’.,?!…·]/g, '');
  const sid = (n) => `S${n}`;

  /* ─── 발화 — words 를 문장 끝 · 쉼 · 길이로 묶는다 (서버엔 발화 id 가 없다, AUDIT §2-1) ─────────── */
  function segmentUtterances(transcript) {
    const words = (transcript && transcript.words) || [];
    const marks = (transcript && (transcript.marks || transcript.by_slide)) || [];
    const slideAt = (t) => {
      const m = marks.find((x) => t >= x.start_sec && t < x.end_sec) || marks[marks.length - 1];
      return m ? m.slide_no : null;
    };
    const utts = [];
    let cur = null;
    words.forEach((w, i) => {
      if (!cur) cur = { from: i, start: w.start_sec, texts: [] };
      cur.texts.push(w.text);
      const next = words[i + 1];
      const gap = next ? next.start_sec - w.end_sec : Infinity;
      if (SENT_END.test(w.text) || gap > UTT_GAP || w.end_sec - cur.start > UTT_MAX || !next) {
        utts.push({ id: `U${utts.length + 1}`, from: cur.from, to: i, start_sec: cur.start, end_sec: w.end_sec,
          text: cur.texts.join(' '), slide_no: slideAt(cur.start) });
        cur = null;
      }
    });
    return utts;
  }

  /** 인용을 받아쓰기에서 찾는다 — 공백 · 문장부호를 빼고 글자 단위로 맞춘다. 찾으면 단어 범위 · 시각 · 발화 id */
  function locateQuote(transcript, utts, quote) {
    const q = norm(quote);
    const words = (transcript && transcript.words) || [];
    if (!q) return { status: 'missing' };
    if (!words.length) return { status: 'inferred', why: 'no_words' };
    let flat = '';
    const owner = [];
    words.forEach((w, i) => { const t = norm(w.text); flat += t; for (let k = 0; k < t.length; k += 1) owner.push(i); });
    const at = flat.indexOf(q);
    if (at < 0) return { status: 'inferred', why: 'not_verbatim' };
    const a = owner[at];
    const b = owner[at + q.length - 1];
    const ids = utts.filter((u) => u.to >= a && u.from <= b).map((u) => u.id);
    return { status: 'supported', word_from: a, word_to: b, start_sec: words[a].start_sec, end_sec: words[b].end_sec, utt_ids: ids };
  }

  /* ─── 그래프 ───────────────────────────────────────────────────────────── */
  function makeGraph(reportId) {
    const nodes = new Map();
    const edges = [];
    const g = {
      reportId, schema: SCHEMA, nodes, edges,
      add(id, type, source, extra = {}) {
        if (nodes.has(id)) return nodes.get(id);
        const n = { id, type, reportId, schema: SCHEMA, source, status: 'supported', anchor: {}, ...extra };
        nodes.set(id, n);
        return n;
      },
      link(type, from, to, source, status = 'supported') {
        const id = `${type}:${from}>${to}`;
        if (!edges.some((e) => e.id === id)) edges.push({ id, type, from, to, source, status });
      },
      out(id, type) { return edges.filter((e) => e.from === id && (!type || e.type === type)).map((e) => nodes.get(e.to)).filter(Boolean); },
      in(id, type) { return edges.filter((e) => e.to === id && (!type || e.type === type)).map((e) => nodes.get(e.from)).filter(Boolean); },
    };
    return g;
  }

  /** 근거 노드 하나 — 인용을 찾아 발화 · 구간 · 장에 잇는다 */
  function addEvidence(g, ctx, id, { kind, quote, slide_no, start_sec, end_sec, source, text }) {
    const loc = quote ? locateQuote(ctx.transcript, ctx.utts, quote) : { status: start_sec != null ? 'supported' : (slide_no ? 'supported' : 'missing') };
    const anchor = {};
    if (slide_no) anchor.slide_no = slide_no;
    if (quote) anchor.quote = quote;
    const s = loc.start_sec != null ? loc.start_sec : start_sec;
    const e = loc.end_sec != null ? loc.end_sec : end_sec;
    if (s != null) { anchor.start_sec = s; anchor.end_sec = e != null ? e : s; }
    if (loc.utt_ids) anchor.utt_ids = loc.utt_ids;
    const v = g.add(id, 'Evidence', source, { kind, anchor, status: loc.status, text: text || quote || '', why: loc.why || '' });
    (loc.utt_ids || []).forEach((u) => g.link('POINTS_TO', id, u, source, loc.status));
    if (slide_no && g.nodes.has(sid(slide_no))) g.link('POINTS_TO', id, sid(slide_no), source);
    if (anchor.start_sec != null && !loc.utt_ids) {
      ctx.utts.filter((u) => u.end_sec > anchor.start_sec && u.start_sec < anchor.end_sec).forEach((u) => g.link('POINTS_TO', id, u.id, source, 'inferred'));
    }
    return v;
  }

  function buildGraph(input) {
    const reportId = (input && input.reportId) || 'report';
    const g = makeGraph(reportId);
    const t = input.transcript || null;
    const utts = segmentUtterances(t);
    const ctx = { transcript: t, utts };
    const graph = input.graph || { nodes: [], edges: [] };
    const align = input.alignment || { items: [] };
    const totalSlides = graph.total_slides || ((input.deck && input.deck.slides) || []).length || 0;
    const unrelated = align.speech_match === 'unrelated' || align.basis === 'skipped';

    g.add('P', 'Presentation', { type: 'session', id: reportId }, { title: (input.deck && input.deck.title) || graph.file_name || '',
      duration_sec: (t && t.duration_sec) || null, total_slides: totalSlides });

    // 장 · 장 구간 (marks — 라이브면 넘긴 시각, 올린 녹음이면 추정 · AUDIT §2-1)
    const marks = (t && (t.marks || t.by_slide)) || [];
    for (let n = 1; n <= totalSlides; n += 1) {
      const s = ((input.deck && input.deck.slides) || []).find((x) => x.slide_no === n) || {};
      g.add(sid(n), 'Slide', { type: 'slide_doc', id: String(n) }, { slide_no: n, title: s.title || '', anchor: { slide_no: n } });
      g.link('CONTAINS', 'P', sid(n), { type: 'slide_doc', id: String(n) });
    }
    marks.forEach((m) => {
      const id = `T${m.slide_no}.${m.visit || 1}`;
      g.add(id, 'TimeSpan', { type: 'transcript.marks', id }, { anchor: { slide_no: m.slide_no, start_sec: m.start_sec, end_sec: m.end_sec },
        status: t && t.marks_estimated ? 'inferred' : 'supported', estimated: !!(t && t.marks_estimated) });
      if (g.nodes.has(sid(m.slide_no))) g.link('SPANS', id, sid(m.slide_no), { type: 'transcript.marks', id });
    });
    utts.forEach((u) => {
      g.add(u.id, 'Utterance', { type: 'transcript.words', id: `${u.from}-${u.to}` }, { text: u.text,
        anchor: { start_sec: u.start_sec, end_sec: u.end_sec, slide_no: u.slide_no } });
      const span = marks.find((m) => u.start_sec >= m.start_sec && u.start_sec < m.end_sec);
      if (span) g.link('OCCURS_IN', u.id, `T${span.slide_no}.${span.visit || 1}`, { type: 'transcript.marks', id: '' }, t.marks_estimated ? 'inferred' : 'supported');
    });

    // 개념 (F-07)
    (graph.nodes || []).forEach((c) => {
      g.add(`C:${c.id}`, 'Concept', { type: 'concept_graph', id: c.id }, { label: c.label, kind: c.kind, weight: c.weight, summary: c.summary || '',
        slide_nos: c.slide_nos || [], anchor: { slide_no: (c.slide_nos || [])[0] } });
      (c.slide_nos || []).forEach((n) => { if (g.nodes.has(sid(n))) g.link('CONTAINS', sid(n), `C:${c.id}`, { type: 'concept_graph', id: c.id }); });
    });

    // 기준 · 채점 (F-14) — 평가자는 「분석 엔진」, 청중 삐약이와 따로
    const score = input.score || null;
    g.add('E:engine', 'Evaluator', { type: 'pipeline', id: 'f11-f14-f17-f18' }, { name: '척척발표 분석', role: 'engine' });
    ((score && score.clusters) || []).forEach((k) => {
      g.add(`K:${k.key}`, 'Criterion', { type: 'rubric_score.clusters', id: k.key }, { name: k.name, weight: k.weight, average: k.average,
        scored: k.status === 'scored', status: k.status === 'scored' ? 'supported' : 'missing' });
    });
    ((score && score.items) || []).forEach((it) => {
      const id = `A:rubric:${it.no}`;
      g.add(id, 'Assessment', { type: 'rubric_score.items', id: String(it.no) }, { name: it.name, score: it.score, status_raw: it.status,
        method: it.source, text: it.evidence || it.note || '', status: it.status === 'scored' ? 'supported' : 'missing' });
      if (g.nodes.has(`K:${it.cluster}`)) g.link('SCORES', id, `K:${it.cluster}`, { type: 'rubric_score.items', id: String(it.no) });
      g.link('PRODUCED_BY', id, 'E:engine', { type: 'rubric_score.items', id: String(it.no) });
    });

    // 개념 전달 판정 (F-11) — 대체값 · 무관 녹음은 판정 안 함(na), 판정과 근거 글이 어긋나면 conflicting
    (align.items || []).forEach((it) => {
      const id = `A:align:${it.node_id}`;
      const na = unrelated || it.decided_by === 'fallback';
      const conflicting = it.verdict === 'missing' && !!it.evidence && /설명했|말했|다뤘/.test(it.note || '');
      g.add(id, 'Assessment', { type: 'alignment_doc.items', id: it.node_id }, { verdict: it.verdict, ui_status: na ? 'na' : VERDICT_STATUS[it.verdict],
        decided_by: it.decided_by, note: it.note || '', status: na ? 'missing' : (conflicting ? 'conflicting' : 'supported') });
      g.link('PRODUCED_BY', id, 'E:engine', { type: 'alignment_doc.items', id: it.node_id });
      if (g.nodes.has(`C:${it.node_id}`)) g.link('ASSESSES', id, `C:${it.node_id}`, { type: 'alignment_doc.items', id: it.node_id });
      if (it.evidence) {
        const v = addEvidence(g, ctx, `V:said:${it.node_id}`, { kind: 'said', quote: it.evidence, source: { type: 'alignment_doc.items.evidence', id: it.node_id } });
        g.link('SUPPORTED_BY', id, v.id, v.source, v.status);
      }
      if (it.deck_quote) {
        const n = it.deck_slide_no || ((graph.nodes || []).find((c) => c.id === it.node_id) || { slide_nos: [] }).slide_nos[0];
        const v = addEvidence(g, ctx, `V:deck:${it.node_id}`, { kind: 'deck', slide_no: n, text: it.deck_quote, source: { type: 'alignment_doc.items.deck_quote', id: it.node_id } });
        g.link('SUPPORTED_BY', id, v.id, v.source);
      }
    });

    addAudience(g, ctx, input.chatter, align, graph);
    addQa(g, ctx, input.qa, input.questions);
    deriveInsights(g, ctx, input);
    return g;
  }

  /* ─── 청중석 (F-12) — 평가위원이 아니라 청중이다(AUDIT §3). 대사마다 근거를 검사한다 ─────────────────── */
  const SPEAKERS = { midm: '믿:음', solar: '쏠라', exaone: '엑사원', ax: '엑씨' };
  const LANE = { midm: '자료와 말이 어긋난 곳', solar: '발표 구조 · 순서', exaone: '잘한 점', ax: '들은 것 · 안 나온 개념' };
  function addAudience(g, ctx, chatter, align, graph) {
    if (!chatter) return;
    const absent = new Set(chatter.absent || []);
    Object.keys(SPEAKERS).forEach((k) => g.add(`E:${k}`, 'Evaluator', { type: 'chatter_doc', id: k },
      { name: (chatter.speaker_names || {})[k] || SPEAKERS[k], model: (chatter.speaker_models || {})[k] || '', lane: LANE[k], role: 'audience',
        status: absent.has(k) ? 'missing' : 'supported', absent: absent.has(k) }));
    const labels = new Map((graph.nodes || []).map((c) => [norm(c.label), c.id]));
    const verdictOf = new Map((align.items || []).map((i) => [i.node_id, i.verdict]));
    const said = norm((ctx.transcript && ctx.transcript.full_text) || '');
    (chatter.turns || []).forEach((turn, i) => {
      const id = `R${i + 1}`;
      if (absent.has(turn.speaker) && !(turn.refs || []).length) {
        g.add(id, 'Remark', { type: 'chatter_doc.turns', id: String(i) }, { speaker: turn.speaker, text: turn.text, mood: turn.mood, filler: true, status: 'missing' });
        g.link('PRODUCED_BY', id, `E:${turn.speaker}`, { type: 'chatter_doc.turns', id: String(i) });
        return;
      }
      // 대사 속 '…' 로 부른 이름 — 그래프에 있는 개념인가, 받아쓰기에 있는 말인가
      const named = [...String(turn.text).matchAll(/['‘“"]([^'’”"]{2,40})['’”"]/g)].map((m) => m[1]);
      const known = named.filter((w) => labels.has(norm(w)) || said.includes(norm(w)));
      const ghost = named.filter((w) => !labels.has(norm(w)) && !said.includes(norm(w)));
      const refs = (turn.refs || []).map((r) => r.node_id).filter((n) => g.nodes.has(`C:${n}`));
      // 「안 나왔다」 고 한 개념이 정합에선 aligned 면 상충 (낱말은 안 나왔어도 뜻으로 설명 — 둘 다 근거가 있다)
      const saysAbsent = /안 나(?:왔|와|옴)|언급이 (?:전혀 )?없|빠(?:졌|져)|안 했/.test(turn.text);
      const clash = saysAbsent && named.some((w) => verdictOf.get(labels.get(norm(w))) === 'aligned');
      const status = ghost.length ? 'unsupported' : clash ? 'conflicting' : (refs.length || known.length) ? 'supported' : 'inferred';
      g.add(id, 'Remark', { type: 'chatter_doc.turns', id: String(i) }, { speaker: turn.speaker, text: turn.text, mood: turn.mood,
        named, ghost, status, why: ghost.length ? `그래프 · 받아쓰기에 없는 말: ${ghost.join(', ')}` : clash ? '분석 엔진은 「설명함」으로 판정했는데 다르게 말했어요' : '' });
      g.link('PRODUCED_BY', id, `E:${turn.speaker}`, { type: 'chatter_doc.turns', id: String(i) });
      refs.forEach((n) => g.link('REFERENCES', id, `C:${n}`, { type: 'chatter_doc.turns.refs', id: n }));
      named.forEach((w) => { const n = labels.get(norm(w)); if (n && !refs.includes(n)) g.link('REFERENCES', id, `C:${n}`, { type: 'chatter_doc.turns.text', id: n }, 'inferred'); });
    });
  }

  /* ─── Q&A — 질문 · 답 · 꼬리질문 (claim 은 답 원문 구절일 때만 GROUNDED_IN) ─────────────────────────── */
  function addQa(g, ctx, qa, questionDoc) {
    const qs = (qa && qa.questions && qa.questions.length ? qa.questions : (questionDoc && questionDoc.questions)) || [];
    const results = (qa && qa.results) || [];
    qs.forEach((q) => {
      const id = `Q:${q.id}`;
      g.add(id, 'Question', { type: 'question_doc', id: q.id }, { text: q.question, label: q.label, gist: q.answer_gist || '', anchor: { slide_no: q.evidence_slide_no || (q.slide_nos || [])[0] } });
      if (q.node_id && g.nodes.has(`C:${q.node_id}`)) g.link('REFERENCES', id, `C:${q.node_id}`, { type: 'question_doc', id: q.id });
      (q.slide_nos || []).forEach((n) => { if (g.nodes.has(sid(n))) g.link('REFERENCES', id, sid(n), { type: 'question_doc', id: q.id }); });
    });
    results.forEach((r) => {
      if (!g.nodes.has(`Q:${r.id}`)) return;
      const trail = r.trail || [];
      trail.forEach((step, k) => {
        const ans = `A:qa:${r.id}:${k + 1}`;
        const grounded = !!step.claim && (k < trail.length - 1 ? true : norm(r.answer).includes(norm(step.claim)));
        g.add(ans, 'Answer', { type: 'qa.results.trail', id: `${r.id}#${k}` }, { claim: step.claim || '', text: k === trail.length - 1 ? r.answer : '',
          verdict: k === trail.length - 1 ? r.verdict : '', status: step.claim ? (grounded ? 'supported' : 'inferred') : 'missing' });
        if (k === 0) g.link('RESPONDS_TO', ans, `Q:${r.id}`, { type: 'qa.results', id: r.id });
        const next = trail[k + 1];
        if (next) {
          const fu = `F:${r.id}:${k + 1}`;
          g.add(fu, 'FollowUp', { type: 'qa.results.trail', id: `${r.id}#${k + 1}` }, { text: next.q });
          g.link('GROUNDED_IN', fu, ans, { type: 'qa.results.trail', id: `${r.id}#${k + 1}` }, step.claim ? 'supported' : 'missing');
          g.link('RESPONDS_TO', `A:qa:${r.id}:${k + 2}`, fu, { type: 'qa.results.trail', id: `${r.id}#${k + 1}` });
        }
      });
      g.nodes.get(`Q:${r.id}`).result = { verdict: r.verdict, setAside: r.setAside || '', passed: !!r.passed, turns: r.turns || 0, hintUsed: r.hintUsed || 0 };
    });
  }

  /* ─── 인사이트 — 원래 산출물에서만 고른다. 순위는 등급 피처(영향 · 근거 · 실행 가능성) ─────────────────── */
  function deriveInsights(g, ctx, input) {
    const graph = input.graph || { nodes: [] };
    const conceptW = new Map((graph.nodes || []).map((c) => [c.id, c]));
    const qByNode = new Map((((input.qa && input.qa.questions) || (input.questions && input.questions.questions)) || []).map((q) => [q.node_id, q]));
    const list = [];
    const add = (id, data, evidenceIds, targets, actions) => {
      const n = g.add(id, 'Insight', data.source, { ...data, anchor: data.anchor || {} });
      evidenceIds.filter((e) => g.nodes.has(e)).forEach((e) => g.link('SUPPORTED_BY', id, e, data.source, g.nodes.get(e).status));
      targets.filter((x) => g.nodes.has(x)).forEach((x) => g.link('TARGETS', id, x, data.source));
      (actions || []).forEach((a, k) => {
        const cid = `CA:${id.slice(2)}:${k + 1}`;
        g.add(cid, 'CoachingAction', a.source, { kind: a.kind, text: a.text, basis: a.basis || '', practice: a.practice || null,
          status: a.status || 'supported', anchor: a.anchor || {} });
        g.link('ADDRESSES', cid, id, a.source, a.status || 'supported');
        if (a.practice) {
          const pid = `PR:${a.practice.kind}:${a.practice.target}`;
          g.add(pid, 'PracticeTarget', { type: 'route', id: a.practice.route }, { kind: a.practice.kind, route: a.practice.route, label: a.practice.label,
            status: a.practice.available ? 'supported' : 'missing' });
          g.link('REHEARSES', pid, cid, { type: 'route', id: a.practice.route }, a.practice.available ? 'supported' : 'missing');
        }
      });
      list.push(n);
      return n;
    };

    // 1) 개념 전달 — 빠뜨림 · 모순 (대체값은 「판정 못 함」 으로 따로)
    ((input.alignment && input.alignment.items) || []).forEach((it) => {
      const a = g.nodes.get(`A:align:${it.node_id}`);
      const c = conceptW.get(it.node_id) || {};
      if (!a) return;
      const slide = it.deck_slide_no || (c.slide_nos || [])[0];
      const q = qByNode.get(it.node_id);
      const practice = q ? { kind: 'qa', target: q.id, route: '#/rehearsal/qa', label: '이 개념 질문 다시 받기', available: true }
        : { kind: 'slide', target: slide, route: '#/rehearsal', label: `${slide}장 다시 설명하기`, available: true };
      const deckLine = g.nodes.get(`V:deck:${it.node_id}`);
      const actions = [];
      if (q && q.answer_gist) actions.push({ kind: 'explain', text: q.answer_gist, basis: `질문 생성(F-08)의 기대 답 · ${q.evidence_slide_no || slide}장`, practice,
        source: { type: 'question_doc.answer_gist', id: q.id }, anchor: { slide_no: q.evidence_slide_no || slide } });
      else if (deckLine) actions.push({ kind: 'explain', text: deckLine.text, basis: `자료 ${slide}장 원문`, practice, source: deckLine.source, anchor: { slide_no: slide } });
      else actions.push({ kind: 'explain', text: '', basis: '제안 문장 없음 — 자료 장을 보며 다시 설명', practice, status: 'missing', source: { type: 'none', id: it.node_id } });
      if (a.ui_status === 'na') {
        add(`I:unjudged:${it.node_id}`, { title: `「${c.label || it.node_id}」 는 판정하지 못했어요`, polarity: 'unknown', criterion: 'content',
          impact: c.kind === 'thesis' ? 'high' : 'low', why: '분석이 대체값으로 끝나 말했는지 확인 못 함 (decided_by: fallback)', anchor: { slide_no: slide },
          source: { type: 'alignment_doc.items', id: it.node_id } }, [], [`C:${it.node_id}`, sid(slide)], actions);
      } else if (it.verdict === 'missing' || it.verdict === 'contradiction') {
        add(`I:concept:${it.node_id}`, { title: it.verdict === 'missing' ? `「${c.label}」 를 말로 전하지 못했어요` : `「${c.label}」 를 자료와 다르게 말했어요`,
          polarity: 'issue', criterion: 'content', impact: (c.kind === 'thesis' || (c.weight || 0) >= 0.85) ? 'high' : (c.weight || 0) >= 0.6 ? 'mid' : 'low',
          why: it.note || '', conflict: a.status === 'conflicting' ? '판정은 「빠뜨림」인데 근거 글은 설명했다고 해요 — 판정을 그대로 믿기 어려워요' : '',
          anchor: { slide_no: slide }, source: { type: 'alignment_doc.items', id: it.node_id } },
        [`V:said:${it.node_id}`, `V:deck:${it.node_id}`], [`C:${it.node_id}`, sid(slide), 'K:content'], actions);
      }
    });

    // 2) 잘한 개념 — 무게 큰 aligned 중 말한 구절을 원문에서 찾은 것 1~2개
    ((input.alignment && input.alignment.items) || [])
      .filter((it) => it.verdict === 'aligned' && g.nodes.get(`V:said:${it.node_id}`) && g.nodes.get(`V:said:${it.node_id}`).status === 'supported')
      .sort((a, b) => ((conceptW.get(b.node_id) || {}).weight || 0) - ((conceptW.get(a.node_id) || {}).weight || 0))
      .slice(0, 2)
      .forEach((it) => {
        const c = conceptW.get(it.node_id) || {};
        add(`I:good:${it.node_id}`, { title: `「${c.label}」 를 자료대로 전했어요`, polarity: 'strength', criterion: 'content', impact: 'mid', why: it.note || '',
          anchor: { slide_no: (c.slide_nos || [])[0] }, source: { type: 'alignment_doc.items', id: it.node_id } }, [`V:said:${it.node_id}`], [`C:${it.node_id}`]);
      });

    // 3) 시간 배분 (F-17) — 장별 상태 · 구간. 같은 쪽(모두 짧음 · 모두 김)이 둘 이상이면 하나로 묶는다 — 상위 셋이 같은 말로 차지 않게
    const pace = input.pace || null;
    const off = ((pace && pace.slides) || []).filter((s) => s.status && s.status !== 'ok' && s.status !== 'fit');
    const paceEv = (s) => addEvidence(g, ctx, `V:pace:${s.slide_no}`, { kind: 'time', slide_no: s.slide_no,
      start_sec: (marksOf(ctx, s.slide_no) || {}).start_sec, end_sec: (marksOf(ctx, s.slide_no) || {}).end_sec,
      text: `${s.slide_no}장 실제 ${Math.round(s.actual_sec)}초 · 권장 ${Math.round(s.recommended_sec)}초`, source: { type: 'pace_doc.slides', id: String(s.slide_no) } });
    const paceAct = (s) => ({ kind: 'time', text: `${s.slide_no}장을 약 ${Math.round(s.recommended_sec)}초로 맞춰 다시 말해 봐요`, basis: '말하기 분석(F-17) 권장 시간',
      practice: { kind: 'slide', target: s.slide_no, route: '#/rehearsal', label: `${s.slide_no}장 다시 연습`, available: true }, source: { type: 'pace_doc.slides', id: String(s.slide_no) } });
    const groups = [off.filter((s) => s.delta_sec < 0), off.filter((s) => s.delta_sec >= 0)];
    groups.forEach((grp, gi) => {
      if (!grp.length) return;
      const short = gi === 0;
      if (grp.length === 1) {
        const s = grp[0];
        const v = paceEv(s);
        add(`I:pace:${s.slide_no}`, { title: `${s.slide_no}장에 시간을 ${short ? '너무 짧게' : '너무 길게'} 썼어요`, polarity: 'issue', criterion: 'time',
          impact: s.importance === 'core' ? 'high' : 'mid', why: s.note || '', anchor: { slide_no: s.slide_no, start_sec: v.anchor.start_sec, end_sec: v.anchor.end_sec },
          source: { type: 'pace_doc.slides', id: String(s.slide_no) } }, [v.id], [sid(s.slide_no), 'K:time'], [paceAct(s)]);
        return;
      }
      const ev = grp.map(paceEv);
      const target = pace.target_sec ? `목표 ${Math.round(pace.target_sec / 60)}분` : '권장 시간';
      add(`I:pace:${short ? 'short' : 'long'}`, { title: `${grp.length}개 장 모두 ${target}보다 ${short ? '짧게' : '길게'} 말했어요`, polarity: 'issue', criterion: 'time',
        impact: grp.some((s) => s.importance === 'core') ? 'high' : 'mid',
        why: pace.target_sec ? `전체 ${Math.round(pace.actual_sec)}초 · ${target}(${Math.round(pace.target_sec)}초) — 목표 시간은 발표 상황 설정에서 왔어요` : '',
        anchor: { slide_no: grp[0].slide_no }, source: { type: 'pace_doc', id: 'slides' } },
      ev.map((v) => v.id), [...grp.map((s) => sid(s.slide_no)), 'K:time'], grp.map(paceAct));
    });

    // 4) 흐름 (F-11 flow) — 순서 · 고리
    ((input.flow && input.flow.issues) || []).forEach((iss, k) => {
      const good = iss.kind === 'good_link';
      const v = addEvidence(g, ctx, `V:flow:${k}`, { kind: 'said', quote: iss.cue || '', slide_no: (iss.slide_nos || [])[0], text: iss.cue || iss.note,
        source: { type: 'flow_diff.issues', id: String(k) } });
      add(`I:flow:${k}`, { title: good ? '개념 둘을 말로 잘 이었어요' : iss.kind === 'order_jump' ? '설명 순서가 자료와 달라요' : '개념 사이 고리가 빠졌어요',
        polarity: good ? 'strength' : 'issue', criterion: 'logic', impact: good ? 'mid' : 'mid', why: iss.note || '', anchor: { slide_no: (iss.slide_nos || [])[0] },
        source: { type: 'flow_diff.issues', id: String(k) } }, [v.id], [...(iss.node_ids || []).map((n) => `C:${n}`), 'K:logic']);
    });

    // 5) 채점 결함 (F-14 faults)
    (((input.score && input.score.faults) || [])).forEach((f, k) => {
      add(`I:fault:${k}`, { title: f.text, polarity: 'issue', criterion: f.kind || '', impact: 'high', why: '채점 상한을 거는 결함', anchor: { slide_no: f.slide_no },
        source: { type: 'rubric_score.faults', id: String(k) } }, [], f.slide_no ? [sid(f.slide_no)] : []);
    });

    // 6) 말버릇 (F-18) — 구간이 있을 때만
    const spans = ((input.habits && input.habits.spans) || []);
    if (spans.length) {
      const ids = spans.map((s, k) => addEvidence(g, ctx, `V:habit:${k}`, { kind: 'time', slide_no: s.slide_no, start_sec: s.start_sec, end_sec: s.end_sec,
        text: s.text, source: { type: 'habit_doc.spans', id: String(k) } }).id);
      const many = spans.length >= 4;
      add('I:habit', { title: many ? '같은 말버릇이 여러 번 나왔어요' : `말버릇은 ${spans.length}번뿐이에요`, polarity: many ? 'issue' : 'strength',
        criterion: 'delivery', impact: many ? 'mid' : 'low', why: (input.report && input.report.habit_summary) || '', source: { type: 'habit_doc', id: 'spans' } }, ids, ['K:delivery']);
    }

    // 7) 약한 채점 묶음 (F-14) — 70점 아래. 시간은 3)이 다루니 거기에 잇기만 한다. 근거 = 그 묶음의 낮은 항목 글(앵커 없음)
    ((input.score && input.score.clusters) || []).filter((k) => k.status === 'scored' && k.average < 70).forEach((k) => {
      const low = ((input.score.items) || []).filter((it) => it.cluster === k.key && it.status === 'scored' && it.score < 70);
      if (k.key === 'time' && list.some((n) => n.criterion === 'time')) return;
      add(`I:cluster:${k.key}`, { title: `「${k.name}」 점수가 낮아요 (${Math.round(k.average)}점)`, polarity: 'issue', criterion: k.key,
        impact: k.weight >= 15 ? 'high' : 'mid', why: low.map((it) => `${it.name}: ${it.evidence || it.note || ''}`).join(' · ').slice(0, 280),
        source: { type: 'rubric_score.clusters', id: k.key } }, low.map((it) => `A:rubric:${it.no}`), [`K:${k.key}`]);
    });

    // 순위 — 이슈만, 등급으로 (impact → 근거 → 실행) · 가짜 소수점 없음
    list.forEach((n) => {
      const ev = g.out(n.id, 'SUPPORTED_BY');
      const anchored = ev.some((e) => e.status === 'supported' && e.anchor && (e.anchor.utt_ids || e.anchor.start_sec != null));
      const slideOnly = ev.some((e) => e.status === 'supported' && e.anchor && e.anchor.slide_no);
      n.evidence = anchored ? 'high' : slideOnly ? 'mid' : ev.length ? 'low' : 'none';
      const acts = g.in(n.id, 'ADDRESSES');
      n.actionability = acts.some((a) => a.text && a.practice) ? 'high' : acts.length ? 'mid' : 'low';
      if (n.evidence === 'none') n.status = 'missing';
      else if (ev.some((e) => e.status === 'conflicting') || n.conflict) n.status = 'conflicting';
      n.rank = [TIER[n.impact] || 0, TIER[n.evidence] || 0, TIER[n.actionability] || 0];
    });
  }

  function marksOf(ctx, slideNo) {
    const marks = (ctx.transcript && (ctx.transcript.marks || ctx.transcript.by_slide)) || [];
    return marks.find((m) => m.slide_no === slideNo) || null;
  }

  /* ─── 검증 (명세 §3-5) ─────────────────────────────────────────────────── */
  function validate(g) {
    const issues = [];
    const dur = (g.nodes.get('P') || {}).duration_sec;
    const total = (g.nodes.get('P') || {}).total_slides || 0;
    const ids = new Set();
    g.edges.forEach((e) => {
      if (!g.nodes.has(e.from)) issues.push({ kind: 'dangling', id: e.id, end: e.from });
      if (!g.nodes.has(e.to)) issues.push({ kind: 'dangling', id: e.id, end: e.to });
      if (ids.has(e.id)) issues.push({ kind: 'duplicate_edge', id: e.id });
      ids.add(e.id);
      if (!e.source || !e.source.type) issues.push({ kind: 'edge_no_source', id: e.id });
    });
    g.nodes.forEach((n) => {
      if (!n.source || !n.source.type) issues.push({ kind: 'node_no_source', id: n.id });
      const a = n.anchor || {};
      if (a.slide_no != null && total && (a.slide_no < 1 || a.slide_no > total)) issues.push({ kind: 'slide_out_of_range', id: n.id, slide_no: a.slide_no });
      if (a.start_sec != null && dur && (a.start_sec < 0 || a.end_sec > dur + 0.5 || a.end_sec < a.start_sec)) issues.push({ kind: 'time_out_of_range', id: n.id });
      if (n.type === 'Evidence' && n.kind === 'said' && n.anchor.quote && n.status !== 'supported') issues.push({ kind: 'quote_not_verbatim', id: n.id });
      if (n.type === 'Insight' && n.status === 'missing') issues.push({ kind: 'insight_without_evidence', id: n.id });
      if (n.type === 'Remark' && n.status === 'unsupported') issues.push({ kind: 'unsupported_remark', id: n.id, why: n.why });
    });
    const insights = [...g.nodes.values()].filter((n) => n.type === 'Insight');
    const withPath = insights.filter((n) => evidencePath(g, n.id).length);
    const anchored = insights.filter((n) => n.evidence === 'high');
    return {
      issues,
      metrics: {
        nodes: g.nodes.size, edges: g.edges.length, insights: insights.length,
        evidencePathRate: insights.length ? withPath.length / insights.length : 0,
        anchoredRate: insights.length ? anchored.length / insights.length : 0,
      },
    };
  }

  /** Insight → Evidence → Utterance/Slide/TimeSpan 경로 (명세 §3-5 탐색 예) */
  function evidencePath(g, insightId) {
    const paths = [];
    g.out(insightId, 'SUPPORTED_BY').forEach((v) => {
      const to = g.out(v.id, 'POINTS_TO');
      if (to.length) to.forEach((x) => paths.push([insightId, v.id, x.id]));
      else if (v.anchor && (v.anchor.slide_no || v.anchor.start_sec != null)) paths.push([insightId, v.id]);
    });
    return paths;
  }

  /* ─── 화면 모형 (ReportViewModel) — 화면은 그래프가 아니라 이것만 읽는다 ─────────────────────────────── */
  function buildViewModel(g, input) {
    const all = [...g.nodes.values()];
    const insights = all.filter((n) => n.type === 'Insight');
    const byRank = (a, b) => (b.rank[0] - a.rank[0]) || (b.rank[1] - a.rank[1]) || (b.rank[2] - a.rank[2]);
    const issues = insights.filter((n) => n.polarity === 'issue').sort(byRank);
    const strengths = insights.filter((n) => n.polarity === 'strength').sort(byRank);
    const unknown = insights.filter((n) => n.polarity === 'unknown');
    const view = (n) => ({
      id: n.id, title: n.title, polarity: n.polarity, status: n.status, why: n.why || '', conflict: n.conflict || '', criterion: n.criterion,
      impact: n.impact, evidence: n.evidence, actionability: n.actionability, anchor: n.anchor || {},
      proofs: g.out(n.id, 'SUPPORTED_BY').map((v) => ({ id: v.id, kind: v.type === 'Assessment' ? 'rubric' : v.kind, text: v.type === 'Assessment' ? `${v.name} ${v.score}점 — ${v.text}` : v.text, status: v.status, anchor: v.anchor || {} })),
      actions: g.in(n.id, 'ADDRESSES').map((a) => ({ id: a.id, kind: a.kind, text: a.text, basis: a.basis, status: a.status, practice: a.practice, anchor: a.anchor })),
      concepts: g.out(n.id, 'TARGETS').filter((x) => x.type === 'Concept').map((c) => ({ id: c.id, label: c.label })),
      remarks: g.out(n.id, 'TARGETS').filter((x) => x.type === 'Concept').flatMap((c) => g.in(c.id, 'REFERENCES').filter((r) => r.type === 'Remark'))
        .map((r) => ({ id: r.id, speaker: r.speaker, text: r.text, status: r.status })),
    });
    const score = input.score || {};
    const report = input.report || {};
    return {
      reportId: g.reportId,
      title: (g.nodes.get('P') || {}).title || '',
      duration_sec: (g.nodes.get('P') || {}).duration_sec,
      score: score.score != null ? { value: score.score, situation: score.situation_label || '', criteria: (score.clusters || []).map((k) => ({ key: k.key, name: k.name, average: k.average, scored: k.status === 'scored' })) } : null,
      headline: report.one_liner || '',
      issues: issues.map(view), strengths: strengths.map(view), unknown: unknown.map(view),
      evaluators: all.filter((n) => n.type === 'Evaluator' && n.role === 'audience').map((e) => ({
        id: e.id, key: e.id.slice(2), name: e.name, model: e.model, lane: e.lane, absent: !!e.absent,
        remarks: g.in(e.id, 'PRODUCED_BY').filter((r) => r.type === 'Remark').map((r) => ({ id: r.id, text: r.text, mood: r.mood, status: r.status, why: r.why || '',
          filler: !!r.filler, concepts: g.out(r.id, 'REFERENCES').map((c) => ({ id: c.id, label: c.label, slide_no: (c.slide_nos || [])[0] })) })),
      })),
      slides: all.filter((n) => n.type === 'Slide').map((s) => ({ no: s.slide_no, title: s.title,
        spans: all.filter((t) => t.type === 'TimeSpan' && t.anchor.slide_no === s.slide_no).map((t) => ({ start: t.anchor.start_sec, end: t.anchor.end_sec, estimated: !!t.estimated })) })),
      utterances: all.filter((n) => n.type === 'Utterance').map((u) => ({ id: u.id, text: u.text, start: u.anchor.start_sec, end: u.anchor.end_sec, slide_no: u.anchor.slide_no })),
      qa: all.filter((n) => n.type === 'Question').map((q) => ({ id: q.id, text: q.text, label: q.label, gist: q.gist, result: q.result || null,
        steps: chainOf(g, q.id) })),
    };
  }

  /** 질문 하나의 전환점 — 질문 → 답(claim) → 꼬리질문 → 답 … */
  function chainOf(g, qid) {
    const steps = [];
    let ans = g.in(qid, 'RESPONDS_TO').find((n) => n.type === 'Answer');
    let guard = 0;
    while (ans && guard < 8) {
      guard += 1;
      const fu = g.in(ans.id, 'GROUNDED_IN').find((n) => n.type === 'FollowUp');
      steps.push({ claim: ans.claim, answer: ans.text, verdict: ans.verdict, status: ans.status, followup: fu ? fu.text : '' });
      ans = fu ? g.in(fu.id, 'RESPONDS_TO').find((n) => n.type === 'Answer') : null;
    }
    return steps;
  }

  const api = { SCHEMA, segmentUtterances, locateQuote, buildGraph, validate, evidencePath, buildViewModel };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.ReportGraph = api;
})(typeof window !== 'undefined' ? window : globalThis);
