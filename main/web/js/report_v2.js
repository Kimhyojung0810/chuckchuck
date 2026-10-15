/**
 * Report 2.0 프로토타입 화면 — docs/report-v2/PRODUCT_SPEC.md · UX_PROTOTYPES.md. 데이터는 js/report_graph.js 의 뷰모델만 읽는다.
 * 기존 리포트(#/report)는 그대로다 — 이 화면은 /report-v2 (report_v2.html) 에서만 뜬다.
 *
 * 데이터: window.__RV2_DATA(묶어 낸 사본) → ?src=last(이 브라우저의 마지막 리포트) → data/report_v2_rec.json(실측 묶음, 팀 전용)
 * 주소: #/{reveal|audience|replay|coach|practice}?i={insightId}&t={시작초}-{끝초} — 화면을 바꿔도 i · t 를 넘긴다 (EVIDENCE_GRAPH §9)
 */
(function () {
  const SCREENS = [
    ['reveal', '결과 공개'], ['audience', '삐약이 청중석'], ['replay', '발표 리플레이'], ['coach', '코칭 스튜디오'], ['practice', '다시 연습'],
  ];
  const DARK = new Set(['audience', 'replay']);
  const ST_WORD = { supported: '근거 있음', conflicting: '근거끼리 어긋남', unsupported: '근거 없음', inferred: '추정으로 이음', missing: '근거 없음' };
  const EV_WORD = { high: '발언 · 시각까지', mid: '장까지', low: '글만', none: '근거 없음' };
  const CRIT = { all: '전체', content: '개념 전달', time: '시간', logic: '흐름', delivery: '말하기' };
  const UI_WORD = { ok: '설명함', no: '안 나옴', ct: '자료와 모순', om: '정당한 생략', na: '판정 안 함' };
  const EMBED = !!window.__RV2_EMBED;

  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = (sec) => { if (sec == null || !isFinite(sec)) return '–'; const s = Math.max(0, Math.round(sec)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
  const chip = (status, word) => `<span class="rv-chip st-${esc(status)}">${esc(word || ST_WORD[status] || status)}</span>`;
  /** 등급 — 기존 app.js scoreGrade 와 같은 규칙 (A+≥90 · A≥80 · B+≥70 · B≥60 · C+≥50 · C≥40 · D) */
  const grade = (v) => (v >= 90 ? 'A+' : v >= 80 ? 'A' : v >= 70 ? 'B+' : v >= 60 ? 'B' : v >= 50 ? 'C+' : v >= 40 ? 'C' : 'D');

  const S = { screen: 'reveal', i: '', t: null, filter: 'all', who: '', entered: false };
  let D = null; let G = null; let V = null; let audio = null;

  /* ─── 데이터 ─────────────────────────────────────────────────────────── */
  async function loadData() {
    if (window.__RV2_DATA) return window.__RV2_DATA;
    const qs = new URLSearchParams(location.search);
    if (qs.get('src') === 'last') {
      let last = null;
      try { last = JSON.parse(localStorage.getItem('cheokcheok:last-report') || 'null'); } catch (_) { last = null; }
      if (!last || !last.pipelineOut) throw new Error('이 브라우저에 저장한 리포트가 없어요. 발표를 한 번 분석하면 생겨요.');
      const po = last.pipelineOut;
      return { schema: 'report-v2-last', provenance: { presentation: '이 브라우저의 마지막 리포트 (단어 시각 · Q&A 꼬리질문은 저장본에 없어요)' },
        deck: { title: last.fileName || '', slides: (last.slideTitles || []).map((t, k) => ({ slide_no: k + 1, title: t })), slide_images: [] },
        transcript: po.transcript || null, graph: po.graph, alignment: po.alignment, flow: po.flow, score: po.score, pace: po.pace, habits: po.habits, report: po.report,
        chatter: null, questions: null, qa: null };
    }
    const res = await fetch('data/report_v2_rec.json', { credentials: 'same-origin' });
    if (!res.ok) throw new Error(res.status === 404 ? '실측 묶음은 팀 브라우저에서만 열려요. /auth 에서 팀 코드를 넣은 뒤 다시 열어요.' : `데이터를 불러오지 못했어요 (${res.status}).`);
    return res.json();
  }

  /* ─── 주소 ─────────────────────────────────────────────────────────── */
  function readHash() {
    const h = location.hash.replace(/^#\/?/, '');
    const [screen, query] = h.split('?');
    if (SCREENS.some(([k]) => k === screen)) S.screen = screen;
    const q = new URLSearchParams(query || '');
    S.i = q.get('i') || '';
    const t = (q.get('t') || '').split('-').map(Number);
    S.t = t.length === 2 && t.every(isFinite) ? t : null;
  }
  function go(screen, patch = {}) {
    // 인사이트를 바꾸면서 구간을 안 주면 그 인사이트의 구간으로 — 앞 화면의 구간이 따라오지 않게
    if ('i' in patch && !('t' in patch)) patch = { ...patch, t: timeOf(insight(patch.i)) };
    Object.assign(S, patch, { screen });
    const q = new URLSearchParams();
    if (S.i) q.set('i', S.i);
    if (S.t) q.set('t', `${S.t[0].toFixed(1)}-${S.t[1].toFixed(1)}`);
    const next = EMBED ? `#${screen}` : `#/${screen}${q.toString() ? `?${q}` : ''}`;
    if (location.hash !== next) history.pushState(null, '', next);
    render();
    window.scrollTo({ top: 0, behavior: 'instant' in window ? 'instant' : 'auto' });
  }
  const insight = (id) => [...V.issues, ...V.strengths, ...V.unknown].find((x) => x.id === id) || null;
  const current = () => insight(S.i) || V.issues[0] || V.unknown[0] || V.strengths[0] || null;
  const timeOf = (ins) => {
    const p = (ins && ins.proofs || []).find((x) => x.anchor && x.anchor.start_sec != null && x.status === 'supported');
    return p ? [p.anchor.start_sec, p.anchor.end_sec] : null;
  };

  /* ─── 머리 ─────────────────────────────────────────────────────────── */
  function renderTop() {
    const top = document.getElementById('rvTop');
    top.toggleAttribute('data-dark', DARK.has(S.screen));
    document.body.classList.toggle('rv-dark', DARK.has(S.screen));
    const cur = insight(S.i);
    top.innerHTML = `
      <div class="rv-brand"><img src="assets/chuckchuck-app-icon-64.png" alt="" width="22" height="22">척척발표 <small>리포트 2.0 · 시제품</small></div>
      <nav class="rv-nav" aria-label="리포트 화면">${SCREENS.map(([k, name], n) => `<button type="button" data-go="${k}" ${S.screen === k ? 'aria-current="page"' : ''}><b>0${n + 1}</b>${name}</button>`).join('')}</nav>
      <div class="rv-ctx" ${cur ? '' : 'hidden'}><span title="${esc(cur ? cur.title : '')}">선택: ${esc(cur ? cur.title : '')}</span><button type="button" class="rv-btn ghost" data-clear aria-label="선택 풀기" style="padding:0 6px;border:0">×</button></div>
      <p class="rv-src" title="${esc(Object.values(D.provenance || {}).join(' / '))}">${esc((D.provenance && D.provenance.presentation) || '')}</p>`;
    top.querySelectorAll('[data-go]').forEach((b) => b.addEventListener('click', () => go(b.dataset.go)));
    const clr = top.querySelector('[data-clear]');
    if (clr) clr.addEventListener('click', () => go(S.screen, { i: '', t: null }));
  }

  /* ─── 01 결과 공개 ─────────────────────────────────────────────────── */
  function issueItem(ins) {
    const unc = ins.status === 'conflicting' ? chip('conflicting', '판정이 흔들려요') : ins.status === 'missing' ? chip('missing', '근거 없음') : '';
    return `<article class="rr-item"><div>
      <h3>${esc(ins.title)}</h3>
      ${ins.why ? `<p>${esc(ins.why)}</p>` : ''}
      ${ins.conflict ? `<p class="v-ct">${esc(ins.conflict)}</p>` : ''}
      <div class="rr-meta">${chip(ins.evidence === 'none' ? 'missing' : 'supported', `근거 위치: ${EV_WORD[ins.evidence]}`)} ${unc}
        <span class="rv-chip st-inferred">영향 ${ins.impact === 'high' ? '큼' : ins.impact === 'mid' ? '보통' : '작음'}</span></div>
      <div class="rr-acts">
        <button type="button" class="rv-btn" data-proof="${esc(ins.id)}" ${ins.proofs.length ? '' : 'disabled'}>근거 보기</button>
        <button type="button" class="rv-btn primary" data-fix="${esc(ins.id)}">개선하기</button>
      </div></div></article>`;
  }
  function renderReveal(main) {
    const top3 = V.issues.slice(0, 3);
    const best = V.strengths[0];
    const next = top3[0] && top3[0].actions.find((a) => a.text);
    const sc = V.score;
    main.innerHTML = `<section class="rv-screen">
      <header class="rr-head">
        <div><p class="rv-eyebrow">이번 발표의 진단 · ${esc(V.title)}</p>
          <h1 class="rr-title">${esc(V.headline || (top3[0] ? top3[0].title : '진단할 내용이 없어요'))}</h1></div>
        ${sc ? `<div class="rr-score"><b class="rv-num">${esc(grade(sc.value))}</b><span class="rv-num">발표 완성도 ${esc(sc.value)}점 · ${esc(sc.situation)}</span></div>` : ''}
      </header>
      <div class="rr-grid">
        <div>
          <p class="rv-eyebrow">먼저 고칠 것 ${top3.length}가지 — 영향 · 근거 · 고칠 수 있는 정도 순</p>
          <div class="rr-list">${top3.map(issueItem).join('') || '<p class="rv-note">고칠 것을 찾지 못했어요.</p>'}</div>
          ${top3.length < 3 ? `<p class="rv-note">분석 결과에서 근거가 있는 문제는 ${top3.length}개예요. 개수를 채우려고 지어내지 않았어요.</p>` : ''}
          ${V.unknown.length ? `<div class="rr-unknown"><b>판정하지 못한 것 ${V.unknown.length}개</b> — ${V.unknown.map((u) => esc(u.title)).join(' · ')}. 분석이 대체값으로 끝나 말했는지 확인하지 못했어요.</div>` : ''}
        </div>
        <aside class="rr-side">
          ${best ? `<div class="rr-box"><p class="rv-eyebrow">가장 잘한 점</p><h4>${esc(best.title)}</h4>
            ${(best.proofs.find((p) => p.kind === 'said') || {}).text ? `<p class="rr-quote">"${esc(best.proofs.find((p) => p.kind === 'said').text)}"</p>` : ''}
            <button type="button" class="rv-btn ghost" data-proof="${esc(best.id)}" style="margin-top:10px">들어 보기</button></div>` : ''}
          ${next ? `<div class="rr-box next"><p class="rv-eyebrow">다음 행동</p><h4>${esc(next.text)}</h4><p class="rv-note" style="color:rgba(243,241,234,.7)">${esc(next.basis)}</p>
            <button type="button" class="rv-btn" data-practice="${esc(top3[0].id)}">${esc((next.practice && next.practice.label) || '다시 연습')}</button></div>` : ''}
          ${sc ? `<details class="rr-more"><summary>기준별 점수 보기</summary><div class="rr-crit">${sc.criteria.map((k) => `<div><span>${esc(k.name)}</span>
            <span class="rr-bar"><i style="width:${k.scored ? Math.round(k.average) : 0}%"></i></span><span class="rv-num">${k.scored ? Math.round(k.average) : '못 잼'}</span></div>`).join('')}</div>
            <p class="rv-note">점수는 기존 채점(39항목 → 7묶음) 그대로예요.</p></details>` : ''}
        </aside>
      </div></section>`;
    main.querySelectorAll('[data-proof]').forEach((b) => b.addEventListener('click', () => { const ins = insight(b.dataset.proof); go('replay', { i: b.dataset.proof, t: timeOf(ins) }); }));
    main.querySelectorAll('[data-fix]').forEach((b) => b.addEventListener('click', () => go('coach', { i: b.dataset.fix })));
    main.querySelectorAll('[data-practice]').forEach((b) => b.addEventListener('click', () => go('practice', { i: b.dataset.practice })));
  }

  /* ─── 02 삐약이 청중석 ─────────────────────────────────────────────── */
  const MOOD = { happy: 'happy', curious: 'curious', excited: 'excited', grumpy: 'neutral', neutral: 'neutral' };
  function conceptJump(cid) {
    const hit = [...V.issues, ...V.strengths, ...V.unknown].find((x) => x.concepts.some((c) => c.id === cid));
    if (hit) return { i: hit.id, t: timeOf(hit) };
    const said = G.nodes.get(`V:said:${cid.slice(2)}`);
    return { i: '', t: said && said.anchor.start_sec != null ? [said.anchor.start_sec, said.anchor.end_sec] : null };
  }
  function engineView(cid) {
    const a = G.nodes.get(`A:align:${cid.slice(2)}`);
    const v = G.nodes.get(`V:said:${cid.slice(2)}`);
    return a ? { word: UI_WORD[a.ui_status] || a.ui_status, cls: `v-${a.ui_status}`, said: v && v.status === 'supported' ? v.text : '' } : null;
  }
  function renderAudience(main) {
    const evs = V.evaluators;
    if (!evs.length) { main.innerHTML = '<section class="rv-screen"><p class="rv-note">청중석 기록이 없어요. 청중은 리포트를 열 때 따로 불러요(/api/v1/chatter).</p></section>'; return; }
    if (!S.who || !evs.some((e) => e.key === S.who)) S.who = (evs.find((e) => !e.absent) || evs[0]).key;
    const me = evs.find((e) => e.key === S.who);
    const real = me.remarks.filter((r) => !r.filler);
    main.innerHTML = `<section class="rv-screen">
      <div class="ra-stage"><div class="ra-light" aria-hidden="true"></div>
        <p class="rv-eyebrow">삐약이 청중석 — 점수를 내는 심사위원이 아니라, 저마다 맡은 것을 보는 청중이에요</p>
        <h2>누구의 반응을 볼까요?</h2>
        <div class="ra-seats" ${S.entered ? '' : 'data-enter'}>${evs.map((e) => `<button type="button" class="ra-seat" data-who="${esc(e.key)}" aria-pressed="${e.key === S.who}" ${e.absent ? 'data-absent' : ''}>
          <img src="assets/chick-${esc(e.key)}-${e.absent ? 'neutral' : MOOD[(e.remarks.find((r) => !r.filler) || {}).mood] || 'neutral'}.svg" alt="">
          <b>${esc(e.name)}</b><small>${esc(e.lane)}</small><small>${e.absent ? '결석 — 응답을 받지 못했어요' : `대사 ${e.remarks.filter((r) => !r.filler).length}개`}</small></button>`).join('')}</div>
      </div>
      <div class="ra-panel">
        <p class="rv-note">${esc(me.name)} · ${esc(me.model)} · 맡은 것: ${esc(me.lane)}</p>
        ${me.absent ? `<div class="ra-diff">${esc(me.name)}은 이번에 객석에 오지 못했어요 (모델 응답 실패). 대체 대사는 근거로 쓰지 않아요.</div>` : ''}
        ${real.map((r) => {
          const eng = r.concepts.map((c) => ({ c, e: engineView(c.id) })).filter((x) => x.e);
          return `<article class="ra-remark"><p>${esc(r.text)}</p>${chip(r.status)}
            ${r.why ? `<p class="ra-why">${esc(r.why)}</p>` : ''}
            ${eng.map(({ c, e }) => `<p class="ra-why">분석 엔진은 「${esc(c.label)}」 을(를) <b class="${e.cls}">${esc(e.word)}</b>으로 봤어요${e.said ? ` — 근거 발언 "${esc(e.said)}"` : ''}.</p>`).join('')}
            <div class="rr-acts">${r.concepts.map((c) => `<button type="button" class="rv-btn" data-jump="${esc(c.id)}">「${esc(c.label)}」 근거로 가기</button>`).join('')}</div></article>`;
        }).join('')}
        ${real.some((r) => r.status === 'conflicting') ? `<div class="ra-diff">의견이 갈려요. 청중은 낱말이 나왔는지를, 분석 엔진은 뜻을 자료와 대조해요. 두 근거를 같이 보고 판단해요 — 억지로 맞추지 않았어요.</div>` : ''}
      </div></section>`;
    S.entered = true;
    main.querySelectorAll('[data-who]').forEach((b) => b.addEventListener('click', () => { S.who = b.dataset.who; render(); }));
    main.querySelectorAll('[data-jump]').forEach((b) => b.addEventListener('click', () => go('replay', conceptJump(b.dataset.jump))));
  }

  /* ─── 03 발표 리플레이 ─────────────────────────────────────────────── */
  function renderReplay(main) {
    const dur = V.duration_sec || 0;
    const ins = insight(S.i);
    const t = S.t || timeOf(ins);
    const pct = (x) => `${(100 * x / (dur || 1)).toFixed(3)}%`;
    const all = [...V.issues, ...V.strengths].filter((x) => S.filter === 'all' || x.criterion === S.filter);
    const marks = all.flatMap((x) => x.proofs.filter((p) => p.anchor.start_sec != null && p.status === 'supported' && p.kind !== 'time')
      .map((p) => ({ x, p })));
    const hitUtts = new Set((ins ? ins.proofs : []).flatMap((p) => (p.kind === 'said' && p.anchor.utt_ids) || []));
    const at = t ? t[0] : null;
    const slideNow = (at != null && (V.slides.find((s) => s.spans.some((sp) => at >= sp.start && at < sp.end)) || {}).no) || (ins && ins.anchor.slide_no) || 1;
    const img = (D.deck.slide_images || [])[(slideNow || 1) - 1];
    const estimated = D.transcript && D.transcript.marks_estimated;
    main.innerHTML = `<section class="rv-screen"><div class="rp">
      <div class="rp-media">
        <figure class="rp-slide" style="margin:0">${img ? `<img src="${esc(img)}" alt="${esc(slideNow)}장">` : ''}<figcaption id="rpCap">${esc(slideNow || '–')}장 · ${esc(((V.slides.find((s) => s.no === slideNow)) || {}).title || '')}</figcaption></figure>
        <div class="rp-time"><button type="button" class="rv-btn" id="rpPlay" ${D.deck.audio_url ? '' : 'disabled'}>${t ? `이 구간 듣기 ${fmt(t[0])}–${fmt(t[1])}` : '처음부터 듣기'}</button>
          <span class="rv-num" id="rpClock">0:00 / ${fmt(dur)}</span>
          <span>${D.deck.audio_url ? '실제 발표 녹음' : '녹음이 저장되지 않아 들을 수 없어요 — 글로만 봐요'}</span></div>
        <div class="rp-track" id="rpTrack" role="slider" aria-label="발표 시간축" aria-valuemin="0" aria-valuemax="${Math.round(dur)}" aria-valuenow="0" tabindex="0">
          ${V.slides.flatMap((s) => s.spans.map((sp) => `<div class="rp-band" ${s.no === slideNow ? 'data-on' : ''} style="left:${pct(sp.start)};width:${pct(sp.end - sp.start)}">${s.no}장</div>`)).join('')}
          ${V.utterances.map((u) => `<div class="rp-utt" style="left:${pct(u.start)};width:${pct(u.end - u.start)}"></div>`).join('')}
          ${marks.map(({ x, p }) => `<button type="button" class="rp-mark ${x.status === 'conflicting' ? 'conflict' : x.polarity}" ${ins && x.id === ins.id ? 'data-on' : ''} data-i="${esc(x.id)}"
            style="left:${pct(p.anchor.start_sec)};width:${pct(Math.max(0.6, p.anchor.end_sec - p.anchor.start_sec))}" title="${esc(x.title)} ${fmt(p.anchor.start_sec)}" aria-label="${esc(x.title)}"></button>`).join('')}
          <div class="rp-head" id="rpHead" style="left:0"></div>
        </div>
        <div class="rp-filters" role="group" aria-label="인사이트 거르기">${Object.entries(CRIT).map(([k, w]) => `<button type="button" data-f="${k}" aria-pressed="${S.filter === k}">${w}</button>`).join('')}</div>
        ${estimated ? '<p class="rv-note">장 경계는 녹음 내용으로 추정했어요(발표 중 넘긴 기록이 아님). 장 띠는 대략 위치예요.</p>' : ''}
        <div class="rp-lines" id="rpLines">${V.utterances.map((u) => `<button type="button" class="rp-line" data-u="${esc(u.id)}" data-s="${u.start}" ${hitUtts.has(u.id) ? 'data-hit' : ''}>
          <time class="rv-num">${fmt(u.start)}</time><span>${hitUtts.has(u.id) ? markQuote(u.text, ins) : esc(u.text)}</span></button>`).join('')}</div>
      </div>
      <aside class="rp-side">${ins ? replayCard(ins) : '<div class="rp-card"><p>왼쪽 시간축의 표시를 누르면 그 순간의 진단과 근거가 여기 나와요.</p></div>'}
        <div class="rp-card"><p class="rv-eyebrow">이 발표의 진단 (${all.length})</p><div class="rp-list">${all.map((x) => `<button type="button" data-i="${esc(x.id)}" aria-current="${ins && x.id === ins.id}">${x.polarity === 'strength' ? '잘함' : x.status === 'conflicting' ? '흔들림' : '고칠 것'} · ${esc(x.title)}</button>`).join('')}</div></div>
      </aside></div></section>`;
    wireReplay(main, t, dur);
  }
  function markQuote(text, ins) {
    const said = (ins.proofs.find((p) => p.kind === 'said') || {}).text || '';
    const k = said ? text.replace(/\s/g, '').indexOf(said.replace(/\s/g, '').slice(0, 6)) : -1;
    return k < 0 ? esc(text) : `<mark>${esc(text)}</mark>`;
  }
  function replayCard(ins) {
    return `<div class="rp-card"><p class="rv-eyebrow">${ins.polarity === 'strength' ? '잘한 점' : ins.polarity === 'unknown' ? '판정 못 함' : '고칠 것'} · ${esc(CRIT[ins.criterion] || ins.criterion)}</p>
      <h3>${esc(ins.title)}</h3>${ins.why ? `<p>${esc(ins.why)}</p>` : ''}
      ${ins.conflict ? `<p class="rp-warn">${esc(ins.conflict)}</p>` : ''}
      ${ins.proofs.map((p) => `<div class="rp-proof"><span>${chip(p.status)} ${esc(p.kind === 'said' ? '말한 구절' : p.kind === 'deck' ? '자료 원문' : p.kind === 'rubric' ? '채점 항목' : '구간')}
        ${p.anchor.start_sec != null ? `<span class="rv-num"> ${fmt(p.anchor.start_sec)}–${fmt(p.anchor.end_sec)}</span>` : ''}${p.anchor.slide_no ? ` · ${p.anchor.slide_no}장` : ''}</span>
        <span>${esc(p.text)}</span>${p.anchor.start_sec != null ? `<button type="button" class="rv-btn" data-seek="${p.anchor.start_sec}" data-end="${p.anchor.end_sec}">여기 듣기</button>` : ''}</div>`).join('')}
      ${ins.polarity !== 'strength' ? `<button type="button" class="rv-btn primary" data-fix="${esc(ins.id)}" style="margin-top:8px">이 구간 개선하기</button>` : ''}</div>`;
  }
  function wireReplay(main, t, dur) {
    const head = main.querySelector('#rpHead'); const clock = main.querySelector('#rpClock'); const track = main.querySelector('#rpTrack');
    let stopAt = null;
    const paint = () => {
      const now = audio ? audio.currentTime : 0;
      head.style.left = `${(100 * now / (dur || 1)).toFixed(3)}%`;
      clock.textContent = `${fmt(now)} / ${fmt(dur)}`;
      track.setAttribute('aria-valuenow', String(Math.round(now)));
      const u = V.utterances.find((x) => x.start <= now && x.end >= now);
      main.querySelectorAll('.rp-line[data-now]').forEach((el) => el.removeAttribute('data-now'));
      if (u) { const el = main.querySelector(`.rp-line[data-u="${u.id}"]`); if (el) el.setAttribute('data-now', ''); }
      if (stopAt != null && now >= stopAt) { audio.pause(); stopAt = null; }
    };
    const play = (a, b) => {
      if (!audio) return;
      audio.currentTime = a; stopAt = b != null ? b + 0.3 : null;
      audio.play().catch(() => { clock.textContent = '재생을 시작하지 못했어요. 한 번 더 눌러요.'; });
    };
    if (audio) { audio.ontimeupdate = paint; paint(); }
    main.querySelector('#rpPlay').addEventListener('click', () => (t ? play(t[0], t[1]) : play(0)));
    track.addEventListener('click', (e) => { if (e.target.closest('.rp-mark')) return; const r = track.getBoundingClientRect(); play(((e.clientX - r.left) / r.width) * dur); });
    track.addEventListener('keydown', (e) => { if (!audio) return; if (e.key === 'ArrowRight') audio.currentTime += 5; if (e.key === 'ArrowLeft') audio.currentTime -= 5; paint(); });
    main.querySelectorAll('[data-i]').forEach((b) => b.addEventListener('click', () => { const x = insight(b.dataset.i); go('replay', { i: b.dataset.i, t: timeOf(x) }); }));
    main.querySelectorAll('[data-f]').forEach((b) => b.addEventListener('click', () => { S.filter = b.dataset.f; render(); }));
    main.querySelectorAll('[data-seek]').forEach((b) => b.addEventListener('click', () => play(+b.dataset.seek, +b.dataset.end)));
    main.querySelectorAll('.rp-line').forEach((b) => b.addEventListener('click', () => play(+b.dataset.s)));
    main.querySelectorAll('[data-fix]').forEach((b) => b.addEventListener('click', () => go('coach', { i: b.dataset.fix })));
    const hit = main.querySelector('.rp-line[data-hit]');
    if (hit) hit.scrollIntoView({ block: 'center' });
  }

  /* ─── 04 코칭 스튜디오 ─────────────────────────────────────────────── */
  function renderCoach(main) {
    const list = [...V.issues, ...V.unknown];
    const ins = (insight(S.i) && insight(S.i).polarity !== 'strength') ? insight(S.i) : list[0];
    if (!ins) { main.innerHTML = '<section class="rv-screen"><p class="rv-note">고칠 것이 없어요.</p></section>'; return; }
    const said = ins.proofs.find((p) => p.kind === 'said' && p.status === 'supported');
    const times = ins.proofs.filter((p) => p.kind === 'time');
    const act = ins.actions.find((a) => a.text) || ins.actions[0];
    const slide = (act && act.anchor && act.anchor.slide_no) || ins.anchor.slide_no;
    const deck = (D.deck.slides || []).find((s) => s.slide_no === slide);
    const img = slide ? (D.deck.slide_images || [])[slide - 1] : '';
    main.innerHTML = `<section class="rv-screen">
      <div class="rc-head"><p class="rv-eyebrow">코칭 스튜디오 · ${esc(CRIT[ins.criterion] || ins.criterion)}</p><h2>${esc(ins.title)}</h2></div>
      <div class="rc-flow">
        <div class="rc-col before"><p class="rv-eyebrow">원래 발표</p>
          ${said ? `<blockquote>"${esc(said.text)}"</blockquote><p class="rc-basis rv-num">${fmt(said.anchor.start_sec)}–${fmt(said.anchor.end_sec)} · 받아쓰기 원문</p>`
            : times.length ? times.map((p) => `<blockquote class="rv-num">${esc(p.text)}</blockquote>`).join('') : '<blockquote>이 부분을 말한 구절을 찾지 못했어요.</blockquote>'}</div>
        <div class="rc-col"><p class="rv-eyebrow">진단한 까닭</p><blockquote>${esc(ins.why || '분석이 까닭 글을 남기지 않았어요.')}</blockquote>
          ${ins.conflict ? `<p class="v-ct" style="font-size:14px">${esc(ins.conflict)}</p>` : ''}${chip(ins.status)}</div>
        <div class="rc-col after"><p class="rv-eyebrow">이렇게 바꿔 말해요</p>
          ${act && act.text ? ins.actions.filter((a) => a.text).slice(0, 3).map((a) => `<blockquote>${esc(a.text)}</blockquote>`).join('') : '<blockquote>제안 문장이 아직 없어요. 아래 자료 원문을 보며 다시 설명해 봐요.</blockquote>'}
          <p class="rc-basis">근거: ${esc((act && act.basis) || '없음')}</p></div>
      </div>
      <p class="rc-why"><b>왜 이 제안인가요?</b> 새로 지은 문장이 아니에요. ${esc((act && act.basis) || '')}에서 가져왔어요. 개념 전달 판정은 말한 내용을 자료와 대조해서 내리므로(F-11), 자료가 말하는 핵심을 말로 옮기면 대조할 거리가 생겨요.</p>
      ${deck ? `<div class="rc-deck">${img ? `<img src="${esc(img)}" alt="${esc(slide)}장">` : ''}<div><p class="rv-eyebrow">자료 ${esc(slide)}장 원문</p><p>${esc(plainDeck(deck.raw_text || deck.title || '').slice(0, 420))}</p></div></div>` : ''}
      <div class="rr-acts" style="margin-top:20px">
        <button type="button" class="rv-btn primary" data-practice="${esc(ins.id)}">해당 부분 다시 연습</button>
        ${ins.proofs.some((p) => p.anchor.start_sec != null) ? `<button type="button" class="rv-btn" data-proof="${esc(ins.id)}">근거 구간 다시 듣기</button>` : ''}</div>
      <div class="rc-pick" role="group" aria-label="다른 진단">${list.map((x) => `<button type="button" data-pick="${esc(x.id)}" aria-current="${x.id === ins.id}">${esc(x.title)}</button>`).join('')}</div>
    </section>`;
    main.querySelectorAll('[data-pick]').forEach((b) => b.addEventListener('click', () => go('coach', { i: b.dataset.pick, t: null })));
    main.querySelectorAll('[data-practice]').forEach((b) => b.addEventListener('click', () => go('practice', { i: b.dataset.practice })));
    main.querySelectorAll('[data-proof]').forEach((b) => b.addEventListener('click', () => go('replay', { i: b.dataset.proof, t: timeOf(insight(b.dataset.proof)) })));
  }

  /** 자료 원문의 표 기호(| --- |)를 걷어 읽을 글로 */
  const plainDeck = (t) => String(t).replace(/\|\s*-{3,}\s*/g, ' ').replace(/\s*\|\s*/g, ' · ').replace(/(?:·\s*){2,}/g, '· ').replace(/\s{2,}/g, ' ').trim();

  /* ─── 05 다시 연습 ─────────────────────────────────────────────────── */
  function renderPractice(main) {
    const ins = insight(S.i) || V.issues[0];
    const targets = [];
    (ins ? ins.actions : []).forEach((a) => { if (a.practice && !targets.some((x) => x.label === a.practice.label)) targets.push(a.practice); });
    targets.push({ label: '처음부터 다시 발표하기', route: '#/rehearsal', kind: 'full', available: true });
    const href = (r) => (EMBED ? null : `index.html${r}`);
    main.innerHTML = `<section class="rv-screen">
      <p class="rv-eyebrow">다시 연습${ins ? ` · ${esc(ins.title)}` : ''}</p>
      <h2 style="margin:6px 0 0;font-size:clamp(22px,3vw,30px)">고칠 곳만 골라서 다시 해 봐요</h2>
      <div class="rq-grid">
        <div class="rq-go">${targets.map((p) => href(p.route)
          ? `<a href="${esc(href(p.route))}"><b>${esc(p.label)}</b><span>${p.kind === 'qa' ? '이 개념 질문을 Q&A 에서 다시 받아요' : p.kind === 'slide' ? '리허설에서 그 장부터 다시 말해요' : '리허설을 새로 시작해요'}</span></a>`
          : `<a aria-disabled="true"><b>${esc(p.label)}</b><span>앱에서 열려요 (이 미리보기에선 이동하지 않아요)</span></a>`).join('')}
          <p class="rq-empty">다시 연습한 결과는 아직 이 진단에 이어지지 않아요. 그래서 나아졌는지는 보여 주지 않아요 — 연습 기록을 잇는 건 다음 단계에서 만들어요.</p>
        </div>
        <div class="rq-chain"><p class="rv-eyebrow">Q&A 전환점 — 내 답의 어느 말에서 다음 질문이 나왔나</p>
          ${V.qa.length ? V.qa.map(qaCard).join('') : '<p class="rq-empty">이 리포트엔 Q&A 기록이 없어요.</p>'}
          ${D.provenance && D.provenance.qa ? `<p class="rv-note">${esc(D.provenance.qa)}</p>` : ''}
        </div>
      </div></section>`;
  }
  function qaCard(q) {
    const r = q.result || {};
    const state = r.setAside === 'concept' ? '다른 개념으로 넘김' : r.setAside === 'skip' ? '건너뜀' : r.setAside === 'perspective' ? '관점 바꿈' : r.verdict === 'good' ? '스스로 설명함' : r.verdict || '안 물음';
    return `<article class="rq-q"><p class="rv-eyebrow">${esc(q.label)} · ${esc(state)}</p><b>${esc(q.text)}</b>
      ${q.steps.length ? q.steps.map((s) => `
        <div class="rq-step"><i></i><div>${s.answer ? highlight(s.answer, s.claim) : s.claim ? `<mark>${esc(s.claim)}</mark>` : ''}
          ${s.claim ? `<p class="rv-note" style="margin:4px 0 0">AI 가 주목한 내 말: 「${esc(s.claim)}」 ${chip(s.status)}</p>` : ''}</div></div>
        ${s.followup ? `<div class="rq-step ai"><i></i><div><b>꼬리질문</b> ${esc(s.followup)}</div></div>` : ''}`).join('')
        : '<p class="rv-note" style="margin-top:10px">답하지 않았어요.</p>'}</article>`;
  }
  function highlight(text, claim) {
    const k = claim ? text.indexOf(claim) : -1;
    return k < 0 ? esc(text) : `${esc(text.slice(0, k))}<mark>${esc(claim)}</mark>${esc(text.slice(k + claim.length))}`;
  }

  /* ─── 그리기 ───────────────────────────────────────────────────────── */
  function render() {
    renderTop();
    const main = document.getElementById('rvMain');
    ({ reveal: renderReveal, audience: renderAudience, replay: renderReplay, coach: renderCoach, practice: renderPractice }[S.screen] || renderReveal)(main);
    main.focus({ preventScroll: true });
  }

  async function start() {
    const main = document.getElementById('rvMain');
    try {
      D = await loadData();
    } catch (err) {
      main.innerHTML = `<section class="rv-screen"><h1 class="rr-title" style="font-size:24px">리포트를 열지 못했어요</h1><p>${esc(err.message)}</p></section>`;
      return;
    }
    G = window.ReportGraph.buildGraph({ ...D, reportId: D.schema || 'report' });
    V = window.ReportGraph.buildViewModel(G, D);
    window.__RV2 = { D, G, V, validate: () => window.ReportGraph.validate(G) };   // 확인용 (콘솔)
    if (D.deck && D.deck.audio_url) { audio = new Audio(); audio.preload = 'metadata'; audio.src = D.deck.audio_url; }
    readHash();
    window.addEventListener('popstate', () => { readHash(); render(); });
    render();
  }
  start();
})();
