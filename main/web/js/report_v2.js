/**
 * Report 2.0 시제품 화면 — docs/report-v2/PRODUCT_SPEC.md · UX_PROTOTYPES.md. 데이터는 js/report_graph.js 의 뷰모델만 읽는다.
 * 기존 리포트(#/report)는 그대로다 — 이 화면은 /report-v2 (report_v2.html) 에서만 뜬다.
 * 생김새는 Apple 결(etc/design-ref/apple/README.md §5, 10-16) — 칩 대신 색 점 한 줄, 주 버튼 하나 + 글자 링크 ›.
 *
 * 데이터: window.__RV2_DATA(묶어 낸 사본) → ?src=last(이 브라우저의 마지막 리포트) → data/report_v2_rec.json(실측 묶음, 팀 전용)
 * 주소: #/{reveal|audience|replay|coach|practice}?i={insightId}&t={시작초}-{끝초} — 화면을 바꿔도 i · t 를 넘긴다 (EVIDENCE_GRAPH §9)
 */
(function () {
  const SCREENS = [['reveal', '결과'], ['audience', '청중석'], ['replay', '리플레이'], ['coach', '코칭'], ['practice', '다시 연습']];
  const ST_WORD = { supported: '근거 있음', conflicting: '근거끼리 어긋나요', unsupported: '근거 없음', inferred: '추정으로 이었어요', missing: '근거 없음' };
  const EV_WORD = { high: '발언과 시각까지 확인', mid: '장까지 확인', low: '채점 글만 있음', none: '근거 없음' };
  const CRIT = { all: '전체', content: '개념 전달', time: '시간', logic: '흐름', delivery: '말하기' };
  const UI_WORD = { ok: '설명함', no: '안 나옴', ct: '자료와 모순', om: '정당한 생략', na: '판정 안 함' };
  const EMBED = !!window.__RV2_EMBED;
  const asset = (p) => (window.__RV2_ASSET ? window.__RV2_ASSET(p) : p);

  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = (sec) => { if (sec == null || !isFinite(sec)) return '–'; const s = Math.max(0, Math.round(sec)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
  const st = (status, word) => `<span class="rv-st st-${esc(status)}"><i></i>${esc(word || ST_WORD[status] || status)}</span>`;
  const dot = (x) => (x.status === 'conflicting' ? 'conflict' : x.polarity);
  /** 등급 — 기존 app.js scoreGrade 와 같은 규칙 (A+≥90 · A≥80 · B+≥70 · B≥60 · C+≥50 · C≥40 · D) */
  const grade = (v) => (v >= 90 ? 'A+' : v >= 80 ? 'A' : v >= 70 ? 'B+' : v >= 60 ? 'B' : v >= 50 ? 'C+' : v >= 40 ? 'C' : 'D');
  /** 자료 원문의 표 기호(| --- |)를 걷어 읽을 글로 */
  const plainDeck = (t) => String(t).replace(/\|\s*-{3,}\s*/g, ' ').replace(/\s*\|\s*/g, ' · ').replace(/(?:·\s*){2,}/g, '· ').replace(/\s{2,}/g, ' ').trim();

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
    window.scrollTo(0, 0);
  }
  const insight = (id) => (id ? [...V.issues, ...V.strengths, ...V.unknown].find((x) => x.id === id) || null : null);
  const timeOf = (ins) => {
    const p = (ins && ins.proofs || []).find((x) => x.anchor && x.anchor.start_sec != null && x.status === 'supported');
    return p ? [p.anchor.start_sec, p.anchor.end_sec] : null;
  };
  const bindGo = (root) => {
    root.querySelectorAll('[data-proof]').forEach((b) => b.addEventListener('click', () => go('replay', { i: b.dataset.proof })));
    root.querySelectorAll('[data-fix]').forEach((b) => b.addEventListener('click', () => go('coach', { i: b.dataset.fix })));
    root.querySelectorAll('[data-practice]').forEach((b) => b.addEventListener('click', () => go('practice', { i: b.dataset.practice })));
  };
  const ctxLine = () => {
    const cur = insight(S.i);
    return cur ? `<p class="rv-ctx">선택한 진단 <b>${esc(cur.title)}</b><button type="button" data-clear>선택 풀기</button></p>` : '';
  };
  const foot = () => `<footer class="rv-foot">${Object.values(D.provenance || {}).map((t) => `<p>${esc(t)}</p>`).join('')}</footer>`;

  /* ─── 위 줄 ───────────────────────────────────────────────────────── */
  function renderTop() {
    const top = document.getElementById('rvTop');
    top.innerHTML = `
      <div class="rv-brand"><img src="${esc(asset('assets/chuckchuck-app-icon-64.png'))}" alt="" width="22" height="22">척척발표 리포트 <span>시제품</span></div>
      <nav class="rv-nav" aria-label="리포트 화면">${SCREENS.map(([k, name]) => `<button type="button" data-go="${k}" ${S.screen === k ? 'aria-current="page"' : ''}>${name}</button>`).join('')}</nav>`;
    top.querySelectorAll('[data-go]').forEach((b) => b.addEventListener('click', () => go(b.dataset.go)));
  }

  /* ─── 01 결과 ─────────────────────────────────────────────────────── */
  function issueItem(ins, n) {
    return `<article class="rv-card rr-item"><span class="rr-no rv-num">${n}</span><div>
      <h3>${esc(ins.title)}</h3>
      ${ins.why ? `<p>${esc(ins.why)}</p>` : ''}
      <div class="rr-meta">${st(ins.evidence === 'none' ? 'missing' : 'supported', EV_WORD[ins.evidence])}
        ${ins.status === 'conflicting' ? st('conflicting', ins.conflict || '판정이 흔들려요') : ''}</div>
      <div class="rv-acts"><button type="button" class="rv-btn" data-fix="${esc(ins.id)}">고쳐 보기</button>
        <button type="button" class="rv-link" data-proof="${esc(ins.id)}" ${ins.proofs.length ? '' : 'disabled'}>근거 보기</button></div>
    </div></article>`;
  }
  function renderReveal(main) {
    const top3 = V.issues.slice(0, 3);
    const best = V.strengths[0];
    const next = top3[0] && top3[0].actions.find((a) => a.text);
    const sc = V.score;
    const bestSaid = best && (best.proofs.find((p) => p.kind === 'said') || {}).text;
    main.innerHTML = `<section class="rv-screen">
      <header class="rr-hero">
        <div><p class="rv-eyebrow">${esc(V.title)}</p>
          <h1 class="rr-title">${esc(V.headline || (top3[0] ? top3[0].title : '진단할 내용이 없어요'))}</h1></div>
        ${sc ? `<div class="rr-grade"><b class="rv-num">${esc(grade(sc.value))}</b><span class="rv-num">발표 완성도 ${esc(sc.value)}점</span></div>` : ''}
      </header>
      <section class="rr-sec"><h2>먼저 고칠 것.</h2>
        <div class="rr-list">${top3.map((x, k) => issueItem(x, k + 1)).join('') || '<p class="rv-note">고칠 것을 찾지 못했어요.</p>'}</div>
        ${top3.length < 3 ? `<p class="rr-unknown">근거가 있는 문제는 ${top3.length}개예요. 개수를 채우려고 지어내지 않았어요.</p>` : ''}
        ${V.unknown.length ? `<p class="rr-unknown">${st('missing', `판정하지 못한 것 ${V.unknown.length}개`)} — ${V.unknown.map((u) => esc(u.title.replace(/ 는 판정하지 못했어요$/, ''))).join(', ')}. 분석이 대체값으로 끝나 말했는지 확인하지 못했어요.</p>` : ''}
      </section>
      <section class="rr-sec rr-two">
        ${best ? `<div class="rv-card"><p class="rv-eyebrow">가장 잘한 점</p><h3>${esc(best.title)}</h3>
          ${bestSaid ? `<p class="rr-quote">“${esc(bestSaid)}”</p>` : ''}
          <div class="rv-acts"><button type="button" class="rv-link" data-proof="${esc(best.id)}">들어 보기</button></div></div>` : ''}
        ${next ? `<div class="rv-card rv-dark"><p class="rv-eyebrow">다음 행동</p><h3>${esc(next.text)}</h3>
          <p class="rv-note" style="margin-top:10px">${esc(next.basis)}</p>
          <div class="rv-acts"><button type="button" class="rv-btn" data-practice="${esc(top3[0].id)}">${esc((next.practice && next.practice.label) || '다시 연습')}</button></div></div>` : ''}
      </section>
      ${sc ? `<section class="rr-sec"><h2>기준별 점수.</h2><div class="rv-card"><div class="rr-crit">${sc.criteria.map((k) => `<div><span>${esc(k.name)}</span>
          <span class="rr-bar"><i style="width:${k.scored ? Math.round(k.average) : 0}%"></i></span><em class="rv-num">${k.scored ? Math.round(k.average) : '못 잼'}</em></div>`).join('')}</div>
          <p class="rv-note" style="margin-top:20px">${esc(sc.situation)} 기준 · 기존 채점(39항목 → 7묶음) 그대로예요.</p></div></section>` : ''}
      ${foot()}</section>`;
    bindGo(main);
  }

  /* ─── 02 청중석 ───────────────────────────────────────────────────── */
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
    if (!evs.length) { main.innerHTML = `<section class="rv-screen"><p class="rv-note">청중석 기록이 없어요. 청중은 리포트를 열 때 따로 불러요.</p>${foot()}</section>`; return; }
    if (!S.who || !evs.some((e) => e.key === S.who)) S.who = (evs.find((e) => !e.absent) || evs[0]).key;
    const me = evs.find((e) => e.key === S.who);
    const real = me.remarks.filter((r) => !r.filler);
    main.innerHTML = `<section class="rv-screen">${ctxLine()}
      <div class="ra-stage rv-dark">
        <h1>삐약이 청중석</h1>
        <p>점수를 매기는 심사위원이 아니에요. 넷이 저마다 맡은 것만 보고 한마디씩 해요.</p>
        <div class="ra-seats" ${S.entered ? '' : 'data-enter'}>${evs.map((e) => `<button type="button" class="ra-seat" data-who="${esc(e.key)}" aria-pressed="${e.key === S.who}" ${e.absent ? 'data-absent' : ''}>
          <img src="${esc(asset(`assets/chick-${e.key}-${e.absent ? 'neutral' : MOOD[(e.remarks.find((r) => !r.filler) || {}).mood] || 'neutral'}.svg`))}" alt="">
          <b>${esc(e.name)}</b><small>${esc(e.lane)}</small><small>${e.absent ? '이번엔 못 왔어요' : `${e.remarks.filter((r) => !r.filler).length}마디`}</small></button>`).join('')}</div>
      </div>
      <section class="ra-who"><p class="rv-eyebrow">${esc(me.model)} · ${esc(me.lane)}</p><h2>${esc(me.name)}의 반응.</h2>
        ${me.absent ? `<p class="ra-diff">${esc(me.name)}은 이번에 객석에 오지 못했어요(모델 응답 실패). 대신 나온 대사는 근거로 쓰지 않아요.</p>` : ''}
        <div class="ra-list">${real.map((r) => {
          const eng = r.concepts.map((c) => ({ c, e: engineView(c.id) })).filter((x) => x.e);
          return `<article class="rv-card"><p class="ra-text">“${esc(r.text)}”</p>${st(r.status)}${r.why && !eng.length ? `<p class="rv-note" style="margin-top:8px">${esc(r.why)}</p>` : ''}
            ${eng.length ? `<div class="ra-engine">${eng.map(({ c, e }) => `<span>분석 엔진은 「${esc(c.label)}」을 <b class="${e.cls}">${esc(e.word)}</b>으로 봤어요${e.said ? ` — “${esc(e.said)}”` : ''}</span>`).join('')}</div>` : ''}
            <div class="rv-acts">${r.concepts.map((c) => `<button type="button" class="rv-link" data-jump="${esc(c.id)}">「${esc(c.label)}」 근거 듣기</button>`).join('')}</div></article>`;
        }).join('')}</div>
        ${real.some((r) => r.status === 'conflicting') ? '<p class="ra-diff">의견이 갈리는 곳이 있어요. 청중은 그 낱말이 나왔는지를, 분석 엔진은 뜻이 자료와 맞는지를 봐요. 두 근거를 같이 보고 판단해요 — 억지로 맞추지 않았어요.</p>' : ''}
      </section>${foot()}</section>`;
    S.entered = true;
    main.querySelectorAll('[data-who]').forEach((b) => b.addEventListener('click', () => { S.who = b.dataset.who; render(); }));
    main.querySelectorAll('[data-jump]').forEach((b) => b.addEventListener('click', () => go('replay', conceptJump(b.dataset.jump))));
  }

  /* ─── 03 리플레이 ─────────────────────────────────────────────────── */
  function renderReplay(main) {
    const dur = V.duration_sec || 0;
    const ins = insight(S.i);
    const t = S.t || timeOf(ins);
    const pct = (x) => `${(100 * x / (dur || 1)).toFixed(3)}%`;
    const all = [...V.issues, ...V.strengths].filter((x) => S.filter === 'all' || x.criterion === S.filter);
    const marks = all.flatMap((x) => x.proofs.filter((p) => p.anchor.start_sec != null && p.status === 'supported' && p.kind !== 'time').map((p) => ({ x, p })));
    // 진단이 있으면 그 말한 구절의 발화, 없이 구간만 왔으면(청중석에서 개념으로) 그 구간과 겹치는 발화
    const hitUtts = new Set(ins ? ins.proofs.flatMap((p) => (p.kind === 'said' && p.anchor.utt_ids) || [])
      : t ? V.utterances.filter((u) => u.end > t[0] && u.start < t[1]).map((u) => u.id) : []);
    const at = t ? t[0] : null;
    const slideNow = (at != null && (V.slides.find((s) => s.spans.some((sp) => at >= sp.start && at < sp.end)) || {}).no) || (ins && ins.anchor.slide_no) || 1;
    const img = (D.deck.slide_images || [])[slideNow - 1];
    const estimated = D.transcript && D.transcript.marks_estimated;
    main.innerHTML = `<section class="rv-screen">${ctxLine()}<div class="rp">
      <div class="rp-main">
        <figure class="rp-slide">${img ? `<img src="${esc(img)}" alt="${esc(slideNow)}장">` : ''}</figure>
        <div class="rv-card rp-bar">
          <div class="rp-time"><span class="rp-cap">${esc(slideNow)}장 · ${esc(((V.slides.find((s) => s.no === slideNow)) || {}).title || '')}</span>
            <span class="rv-num" id="rpClock">0:00 / ${fmt(dur)}</span>
            <button type="button" class="rv-btn" id="rpPlay" ${D.deck.audio_url ? '' : 'disabled'}>${t ? `${fmt(t[0])}–${fmt(t[1])} 듣기` : '처음부터 듣기'}</button></div>
          <div class="rp-track" id="rpTrack" role="slider" aria-label="발표 시간축" aria-valuemin="0" aria-valuemax="${Math.round(dur)}" aria-valuenow="0" tabindex="0">
            ${V.slides.flatMap((s) => s.spans.map((sp) => `<div class="rp-band" ${s.no === slideNow ? 'data-on' : ''} style="left:${pct(sp.start)};width:${pct(sp.end - sp.start)}">${s.no}장</div>`)).join('')}
            ${V.utterances.map((u) => `<div class="rp-utt" style="left:${pct(u.start)};width:${pct(u.end - u.start)}"></div>`).join('')}
            ${marks.map(({ x, p }) => `<button type="button" class="rp-mark ${dot(x)}" ${ins && x.id === ins.id ? 'data-on' : ''} data-i="${esc(x.id)}"
              style="left:${pct(p.anchor.start_sec)};width:${pct(Math.max(0.6, p.anchor.end_sec - p.anchor.start_sec))}" title="${esc(x.title)} ${fmt(p.anchor.start_sec)}" aria-label="${esc(x.title)}"></button>`).join('')}
            <div class="rp-head" id="rpHead" style="left:0"></div>
          </div>
          <div class="rp-filters" role="group" aria-label="진단 거르기">${Object.entries(CRIT).map(([k, w]) => `<button type="button" data-f="${k}" aria-pressed="${S.filter === k}">${w}</button>`).join('')}</div>
          <p class="rv-note" style="margin-top:14px">${D.deck.audio_url ? '실제 발표 녹음이에요.' : '녹음이 저장되지 않아 들을 수 없어요 — 글로만 봐요.'}${estimated ? ' 장 경계는 녹음 내용으로 추정해서 대략 위치예요.' : ''}</p>
        </div>
        <div class="rv-card rp-lines" id="rpLines">${V.utterances.map((u) => `<button type="button" class="rp-line" data-u="${esc(u.id)}" data-s="${u.start}" ${hitUtts.has(u.id) ? 'data-hit' : ''}>
          <time class="rv-num">${fmt(u.start)}</time><span>${esc(u.text)}</span></button>`).join('')}</div>
      </div>
      <aside class="rp-side">${ins ? replayCard(ins) : '<div class="rv-card"><p class="rv-note">시간축의 표시나 아래 목록에서 진단을 고르면, 그 순간의 근거가 여기 나와요.</p></div>'}
        <div class="rv-card"><p class="rv-eyebrow">이 발표의 진단</p><div class="rp-list" style="margin-top:8px">${all.map((x) => `<button type="button" data-i="${esc(x.id)}" aria-current="${!!ins && x.id === ins.id}"><i class="dot-${dot(x)}"></i>${esc(x.title)}</button>`).join('')}</div></div>
      </aside></div>${foot()}</section>`;
    wireReplay(main, t, dur);
  }
  function replayCard(ins) {
    return `<div class="rv-card"><p class="rv-eyebrow">${ins.polarity === 'strength' ? '잘한 점' : ins.polarity === 'unknown' ? '판정 못 함' : '고칠 것'} · ${esc(CRIT[ins.criterion] || ins.criterion)}</p>
      <h2>${esc(ins.title)}</h2>${ins.why ? `<p>${esc(ins.why)}</p>` : ''}
      ${ins.conflict ? `<p class="rp-warn">${esc(ins.conflict)}</p>` : ''}
      ${ins.proofs.map((p) => `<div class="rp-proof">${st(p.status, `${p.kind === 'said' ? '말한 구절' : p.kind === 'deck' ? '자료 원문' : p.kind === 'rubric' ? '채점 항목' : '구간'}${p.anchor.start_sec != null ? ` · ${fmt(p.anchor.start_sec)}–${fmt(p.anchor.end_sec)}` : ''}${p.anchor.slide_no ? ` · ${p.anchor.slide_no}장` : ''}`)}
        ${p.kind === 'said' ? `<q>${esc(p.text)}</q>` : `<span>${esc(p.text)}</span>`}
        ${p.anchor.start_sec != null ? `<button type="button" class="rv-link" data-seek="${p.anchor.start_sec}" data-end="${p.anchor.end_sec}">여기 듣기</button>` : ''}</div>`).join('')}
      ${ins.polarity !== 'strength' ? `<div class="rv-acts"><button type="button" class="rv-btn" data-fix="${esc(ins.id)}">이 구간 고쳐 보기</button></div>` : ''}</div>`;
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
    main.querySelectorAll('[data-i]').forEach((b) => b.addEventListener('click', () => go('replay', { i: b.dataset.i })));
    main.querySelectorAll('[data-f]').forEach((b) => b.addEventListener('click', () => { S.filter = b.dataset.f; render(); }));
    main.querySelectorAll('[data-seek]').forEach((b) => b.addEventListener('click', () => play(+b.dataset.seek, +b.dataset.end)));
    main.querySelectorAll('.rp-line').forEach((b) => b.addEventListener('click', () => play(+b.dataset.s)));
    bindGo(main);
    const hit = main.querySelector('.rp-line[data-hit]');
    if (hit) { const box = main.querySelector('#rpLines'); box.scrollTop = hit.offsetTop - box.clientHeight / 2; }
  }

  /* ─── 04 코칭 ─────────────────────────────────────────────────────── */
  function renderCoach(main) {
    const list = [...V.issues, ...V.unknown];
    const picked = insight(S.i);
    const ins = picked && picked.polarity !== 'strength' ? picked : list[0];
    if (!ins) { main.innerHTML = `<section class="rv-screen"><p class="rv-note">고칠 것이 없어요.</p>${foot()}</section>`; return; }
    const said = ins.proofs.find((p) => p.kind === 'said' && p.status === 'supported');
    const times = ins.proofs.filter((p) => p.kind === 'time');
    const acts = ins.actions.filter((a) => a.text);
    const act = acts[0] || ins.actions[0];
    const slide = (act && act.anchor && act.anchor.slide_no) || ins.anchor.slide_no;
    const deck = (D.deck.slides || []).find((s) => s.slide_no === slide);
    const img = slide ? (D.deck.slide_images || [])[slide - 1] : '';
    main.innerHTML = `<section class="rv-screen">
      <p class="rv-eyebrow">코칭 · ${esc(CRIT[ins.criterion] || ins.criterion)}</p><h1 class="rc-title">${esc(ins.title)}</h1>
      <div class="rc-flow">
        <div class="rv-card rc-col before"><p class="rv-eyebrow">원래 발표</p>
          ${said ? `<blockquote>“${esc(said.text)}”</blockquote><p class="rc-basis rv-num">${fmt(said.anchor.start_sec)}–${fmt(said.anchor.end_sec)} · 받아쓰기 원문</p>`
            : times.length ? times.map((p) => `<blockquote class="rv-num">${esc(p.text)}</blockquote>`).join('') : '<blockquote>이 부분을 말한 구절을 찾지 못했어요.</blockquote>'}</div>
        <div class="rv-card rc-col"><p class="rv-eyebrow">진단한 까닭</p><blockquote>${esc(ins.why || '분석이 까닭 글을 남기지 않았어요.')}</blockquote>
          ${ins.conflict ? st('conflicting', ins.conflict) : ''}</div>
        <div class="rv-card rc-col rv-dark"><p class="rv-eyebrow">이렇게 바꿔 말해요</p>
          ${acts.length ? acts.slice(0, 3).map((a) => `<blockquote>${esc(a.text)}</blockquote>`).join('') : '<blockquote>제안 문장이 아직 없어요. 아래 자료 원문을 보며 다시 설명해 봐요.</blockquote>'}
          <p class="rc-basis">근거 · ${esc((act && act.basis) || '없음')}</p></div>
      </div>
      <div class="rv-acts" style="margin-top:28px"><button type="button" class="rv-btn" data-practice="${esc(ins.id)}">이 부분 다시 연습</button>
        ${ins.proofs.some((p) => p.anchor.start_sec != null) ? `<button type="button" class="rv-link" data-proof="${esc(ins.id)}">근거 구간 다시 듣기</button>` : ''}</div>
      <p class="rc-why"><b>왜 이 제안인가요?</b> 새로 지은 문장이 아니에요. ${esc((act && act.basis) || '')}에서 가져왔어요. 개념 전달 판정은 말한 내용을 자료와 대조해서 내려요(F-11). 자료가 말하는 핵심을 말로 옮기면 대조할 거리가 생겨요.</p>
      ${deck ? `<div class="rv-card rc-deck">${img ? `<img src="${esc(img)}" alt="${esc(slide)}장">` : ''}<div><p class="rv-eyebrow">자료 ${esc(slide)}장 원문</p><p>${esc(plainDeck(deck.raw_text || deck.title || '').slice(0, 420))}</p></div></div>` : ''}
      <section class="rc-pick"><h2>다른 진단.</h2><div class="rp-list">${list.map((x) => `<button type="button" data-pick="${esc(x.id)}" aria-current="${x.id === ins.id}"><i class="dot-${dot(x)}"></i>${esc(x.title)}</button>`).join('')}</div></section>
      ${foot()}</section>`;
    main.querySelectorAll('[data-pick]').forEach((b) => b.addEventListener('click', () => go('coach', { i: b.dataset.pick })));
    bindGo(main);
  }

  /* ─── 05 다시 연습 ────────────────────────────────────────────────── */
  function renderPractice(main) {
    const ins = insight(S.i) || V.issues[0];
    const targets = [];
    (ins ? ins.actions : []).forEach((a) => { if (a.practice && !targets.some((x) => x.label === a.practice.label)) targets.push(a.practice); });
    targets.push({ label: '처음부터 다시 발표하기', route: '#/rehearsal', kind: 'full', available: true });
    const href = (r) => (EMBED ? null : `index.html${r}`);
    const why = (p) => (p.kind === 'qa' ? '이 개념 질문을 Q&A 에서 다시 받아요' : p.kind === 'slide' ? '리허설에서 그 장부터 다시 말해요' : '리허설을 새로 시작해요');
    main.innerHTML = `<section class="rv-screen">${ctxLine()}
      <p class="rv-eyebrow">다시 연습</p><h1 class="rq-title">고칠 곳만 골라서 다시 해 봐요.</h1>
      <div class="rq-grid">
        <div class="rv-card rq-go">${targets.map((p) => href(p.route)
          ? `<a href="${esc(href(p.route))}"><b>${esc(p.label)}</b><span>${why(p)}</span></a>`
          : `<a aria-disabled="true"><b>${esc(p.label)}</b><span>${why(p)} — 앱에서 열려요</span></a>`).join('')}
          <p class="rv-note">다시 연습한 결과는 아직 이 진단에 이어지지 않아요. 그래서 나아졌는지는 보여 주지 않아요.</p>
        </div>
        <div class="rq-chain"><p class="rv-eyebrow" style="margin-bottom:4px">Q&A — 내 답의 어느 말에서 다음 질문이 나왔나</p>
          ${V.qa.length ? V.qa.map(qaCard).join('') : '<div class="rv-card"><p class="rv-note">이 리포트엔 Q&A 기록이 없어요.</p></div>'}
        </div>
      </div>${foot()}</section>`;
  }
  function qaCard(q) {
    const r = q.result || {};
    const state = r.setAside === 'concept' ? '다른 개념으로 넘김' : r.setAside === 'skip' ? '건너뜀' : r.setAside === 'perspective' ? '관점 바꿈' : r.verdict === 'good' ? '스스로 설명함' : r.verdict || '안 물음';
    return `<article class="rv-card rq-q"><p class="rv-eyebrow">${esc(q.label)} · ${esc(state)}</p><h3>${esc(q.text)}</h3>
      ${q.steps.length ? q.steps.map((s) => `
        <div class="rq-step"><i></i><div>${s.answer ? highlight(s.answer, s.claim) : s.claim ? `<mark>${esc(s.claim)}</mark>` : ''}
          ${s.claim ? `<p class="rv-note">AI 가 주목한 내 말 「${esc(s.claim)}」</p>` : ''}</div></div>
        ${s.followup ? `<div class="rq-step ai"><i></i><div><b>꼬리질문</b> ${esc(s.followup)}</div></div>` : ''}`).join('')
        : '<p class="rv-note" style="margin-top:14px">답하지 않았어요.</p>'}</article>`;
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
    const clr = main.querySelector('[data-clear]');
    if (clr) clr.addEventListener('click', () => go(S.screen, { i: '', t: null }));
    main.focus({ preventScroll: true });
  }

  async function start() {
    const main = document.getElementById('rvMain');
    try {
      D = await loadData();
    } catch (err) {
      main.innerHTML = `<section class="rv-screen"><h1 class="rr-title" style="font-size:32px">리포트를 열지 못했어요</h1><p>${esc(err.message)}</p></section>`;
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
