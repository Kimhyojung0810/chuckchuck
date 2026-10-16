/**
 * Report 2.0 화면 — iOS 내비게이션 스택 + 토스식 큰 숫자 (10-16 사용자 「iOS + 토스 · 리포트 하나로 만들지 마라 · 화면 전환 여러 개 ·
 * 기능은 죽이지 말고 강약 조절 · 대회 와우 포인트는 살리면서 디테일까지」).
 * 홈(요약)에서 진단 · 근거 · 코칭 · 다시 보기 · 청중석 · Q&A · 연습 · 점수를 저마다 한 화면으로 밀어 넣는다(push). 뒤로는 ‹ 단추 · 왼쪽 가장자리 밀기.
 * 데이터는 js/report_graph.js 의 뷰모델만 읽는다 — 새 판정 없음. 설계: docs/report-v2/ (PRODUCT_SPEC · UX_PROTOTYPES · DECISIONS D-011)
 *
 * 쓰는 법: ReportV2.mount(root, data, { mode: 'page' | 'app', slideImage(n), onLegacy() }) → { update(patch), destroy() }
 *  - page: 단독 페이지(/report-v2). 스택이 주소(#/home/issue:…)에 남아 뒤로 가기 · 새로고침이 된다
 *  - app : 앱 안(/VRShow 리포트 단계). 앱 주소를 건드리지 않고 스택은 sessionStorage 에만
 */
(function () {
  /* ─── 순수: 앱 상태 → 입력 묶음 (etc/tests/js/report_v2.smoke.mjs) ─────────────────────────── */
  function inputFromApp(raw) {
    const po = (raw && raw.pipelineOut) || {};
    const t = po.transcript ? { ...po.transcript } : null;
    if (t && (!t.words || !t.words.length) && raw.words && raw.words.length) t.words = raw.words;
    if (t && (!t.marks || !t.marks.length) && raw.marks && raw.marks.length) t.marks = raw.marks;
    const deck = raw.deck || {};
    const hasWords = !!(t && t.words && t.words.length);
    return {
      schema: 'report-v2-live',
      provenance: {
        presentation: raw.saved ? `이 브라우저에 저장한 리포트예요${raw.saved}.` : '방금 한 발표의 분석이에요.',
        ...(hasWords ? {} : { words: '단어 시각이 없어서 발언 위치는 장 단위로만 보여요.' }),
        ...(deck.audio_url ? {} : { audio: '녹음이 이 탭에 없어서 다시 들을 수 없어요.' }),
      },
      deck: { title: deck.title || (po.graph && po.graph.file_name) || '', slides: deck.slides || [], slide_images: deck.slide_images || [], audio_url: deck.audio_url || '' },
      transcript: t, graph: po.graph || null, alignment: po.alignment || null, flow: po.flow || null, score: po.score || null,
      pace: po.pace || null, habits: po.habits || null, report: po.report || null,
      chatter: raw.chatter || null, questions: null,
      qa: raw.qa && Array.isArray(raw.qa.results) && raw.qa.results.length ? { questions: raw.qa.questions || [], results: raw.qa.results } : null,
    };
  }

  /* ─── 공통 ─────────────────────────────────────────────────────────── */
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = (sec) => { if (sec == null || !isFinite(sec)) return '–'; const s = Math.max(0, Math.round(sec)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
  /** 등급 — 기존 app.js scoreGrade 와 같은 규칙 */
  const grade = (v) => (v >= 90 ? 'A+' : v >= 80 ? 'A' : v >= 70 ? 'B+' : v >= 60 ? 'B' : v >= 50 ? 'C+' : v >= 40 ? 'C' : 'D');
  const plainDeck = (t) => String(t).replace(/\|\s*-{3,}\s*/g, ' ').replace(/\s*\|\s*/g, ' · ').replace(/(?:·\s*){2,}/g, '· ').replace(/\s{2,}/g, ' ').trim();
  const asset = (p) => (typeof window !== 'undefined' && window.__RV2_ASSET ? window.__RV2_ASSET(p) : p);
  const ST = { supported: '근거 있음', conflicting: '근거끼리 어긋나요', unsupported: '근거 없음', inferred: '추정으로 이었어요', missing: '근거 없음' };
  const EV = { high: '발언과 시각까지 확인했어요', mid: '장까지 확인했어요', low: '채점 글만 있어요', none: '근거가 없어요' };
  const CRIT = { content: '개념 전달', time: '시간', logic: '흐름', delivery: '말하기', visual: '시각자료', clarity: '명료성', audience: '청중 적합성' };
  const UI_WORD = { ok: '설명함', no: '안 나옴', ct: '자료와 모순', om: '정당한 생략', na: '판정 안 함' };
  const MOOD = { happy: 'happy', curious: 'curious', excited: 'excited', grumpy: 'neutral', neutral: 'neutral' };
  const tone = (x) => (x.status === 'conflicting' ? 'ct' : x.polarity === 'strength' ? 'ok' : x.polarity === 'unknown' ? 'na' : 'mid');

  /* 아이콘 — SF Symbols 는 웹에 못 실어서 같은 결의 선 아이콘(둥근 끝)을 직접 */
  const I = {
    chev: '<svg viewBox="0 0 8 14" aria-hidden="true"><path d="M1.5 1.5 6.5 7l-5 5.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    back: '<svg viewBox="0 0 12 20" aria-hidden="true"><path d="M10 2 2 10l8 8" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    play: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 2.8v10.4c0 .6.7 1 1.2.6l8-5.2a.7.7 0 0 0 0-1.2l-8-5.2c-.5-.4-1.2 0-1.2.6Z" fill="currentColor"/></svg>',
    pause: '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3.5" y="2.5" width="3" height="11" rx="1" fill="currentColor"/><rect x="9.5" y="2.5" width="3" height="11" rx="1" fill="currentColor"/></svg>',
    wave: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 9v2M6.5 6v8M10 3v14M13.5 6v8M17 9v2" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>',
    chat: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 4.5h12a1.5 1.5 0 0 1 1.5 1.5v7a1.5 1.5 0 0 1-1.5 1.5H9l-4 3v-3H4A1.5 1.5 0 0 1 2.5 13V6A1.5 1.5 0 0 1 4 4.5Z" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/></svg>',
    chart: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 16V9M10 16V4M16 16v-5" stroke="currentColor" stroke-width="2.3" stroke-linecap="round"/></svg>',
    people: '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="7" cy="7" r="2.8" fill="none" stroke="currentColor" stroke-width="1.9"/><circle cx="14" cy="8" r="2.2" fill="none" stroke="currentColor" stroke-width="1.9"/><path d="M2.5 16c.6-2.6 2.4-4 4.5-4s3.9 1.4 4.5 4M12 12.3c2.2-.4 4.2.9 4.9 3.7" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>',
    redo: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M15.5 7.5A6 6 0 1 0 16 12" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/><path d="M16 3.5v4.2h-4.2" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    check: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3.5 8.3 3 3 6-6.6" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    q: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5.8 5.9a2.3 2.3 0 1 1 3.3 2.1c-.7.3-1.1.9-1.1 1.6v.4M8 12.2v.1" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"/></svg>',
    bang: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3.5v5.3M8 11.9v.1" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round"/></svg>',
    doc: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M6 2.8h5.5L15.5 7v9.2A1.3 1.3 0 0 1 14.2 17.5H6a1.3 1.3 0 0 1-1.3-1.3V4.1A1.3 1.3 0 0 1 6 2.8Z" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/><path d="M11 3v4.5h4.5" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/></svg>',
  };
  const badge = (x) => `<span class="nv-badge t-${tone(x)}">${tone(x) === 'ok' ? I.check : tone(x) === 'na' ? I.q : I.bang}</span>`;

  /* ═══ 마운트 ═══════════════════════════════════════════════════════════ */
  function mount(root, data, opts = {}) {
    const MODE = opts.mode || 'page';
    const EMBED = !!window.__RV2_EMBED;
    /* 탭 모드(스튜디오 /VRShow) — 뿌리 화면 다섯이 스튜디오 정거장 다섯(05 결과 · 06 다시 보기 · 07 청중석 · 08 코칭 · 09 연습)이다.
       그 다섯으로 가는 push 는 뿌리를 바꾸고(opts.onRoot 로 알린다 → 스튜디오 창이 곡선을 따라 미끄러진다), 그 아래 깊은 화면만 창 안에서 밀어 넣는다 */
    const TABS = Array.isArray(opts.tabs) && opts.tabs.length ? opts.tabs : null;
    let D = data; let G = null; let V = null;
    let audio = null; let stopAt = null; let playingKey = '';
    const stack = [];      // [{ route, el, short, onTime }]
    const imgCache = {};
    const STATE_KEY = 'cheokcheok:rv2-stack';
    root.classList.add('rv2');
    root.innerHTML = '<div class="nv" aria-roledescription="리포트"></div>';
    const NV = root.querySelector('.nv');

    /* ── 데이터 ── */
    function build() {
      G = window.ReportGraph.buildGraph({ ...D, reportId: D.schema || 'report' });
      V = window.ReportGraph.buildViewModel(G, D);
      if (MODE === 'page') window.__RV2 = { D, G, V, validate: () => window.ReportGraph.validate(G) };
    }
    const all = () => [...V.issues, ...V.unknown, ...V.strengths];
    const insight = (id) => (id ? all().find((x) => x.id === id) || null : null);
    const timeOf = (ins) => {
      const p = (ins && ins.proofs || []).find((x) => x.anchor && x.anchor.start_sec != null && x.status === 'supported');
      return p ? [p.anchor.start_sec, p.anchor.end_sec] : null;
    };
    const slideImg = (n) => (D.deck.slide_images || [])[n - 1] || imgCache[n] || '';
    function slideTag(n, cls = 'nv-slide') {
      if (!slideImg(n) && typeof opts.slideImage === 'function') {
        Promise.resolve(opts.slideImage(n)).then((url) => {
          if (!url) return;
          imgCache[n] = url;
          NV.querySelectorAll(`img[data-slide="${n}"]`).forEach((el) => { el.src = url; el.hidden = false; });
        }).catch(() => {});
      }
      const u = slideImg(n);
      return `<div class="${cls}"><img data-slide="${n}" src="${esc(u)}" alt="${esc(n)}장" ${u ? '' : 'hidden'}><span>${esc(n)}장</span></div>`;
    }

    /* ── 소리 — 구간 재생(끝나면 멈춤). 같은 단추를 다시 누르면 멈춘다 ── */
    function setAudio() {
      if (audio) { try { audio.pause(); } catch (_) { /* 멈춤 */ } }
      audio = null;
      if (D.deck && D.deck.audio_url) {
        audio = new Audio(); audio.preload = 'metadata'; audio.src = D.deck.audio_url;
        audio.addEventListener('timeupdate', onTime);
        audio.addEventListener('pause', paintPlay); audio.addEventListener('play', paintPlay);
      }
    }
    function play(a, b, key = '') {
      if (!audio) return;
      if (playingKey === key && !audio.paused) { audio.pause(); return; }
      playingKey = key;
      audio.currentTime = Math.max(0, a); stopAt = b != null && isFinite(b) ? b + 0.3 : null;
      audio.play().catch(() => {});
    }
    function onTime() {
      if (stopAt != null && audio.currentTime >= stopAt) { audio.pause(); stopAt = null; }
      const top = stack[stack.length - 1];
      if (top && top.onTime) top.onTime(audio.currentTime);
    }
    function paintPlay() {
      NV.querySelectorAll('[data-play]').forEach((b) => {
        const on = !!audio && !audio.paused && b.dataset.play === playingKey;
        b.classList.toggle('is-on', on);
        const ic = b.querySelector('.nv-pi'); if (ic) ic.innerHTML = on ? I.pause : I.play;
      });
    }
    const playBtn = (key, a, b, label) => `<button type="button" class="nv-play" data-play="${esc(key)}" data-a="${a}" data-b="${b == null ? '' : b}" ${audio ? '' : 'disabled'}><span class="nv-pi">${I.play}</span><span>${esc(label)}</span></button>`;

    /* ── 스택 ── */
    const ROUTES = { home, issue, replay, coach, audience, chick, practice, qa, scores };
    const parse = (r) => { const k = r.indexOf(':'); return k < 0 ? [r, ''] : [r.slice(0, k), r.slice(k + 1)]; };
    function renderScreen(route) {
      const [name, arg] = parse(route);
      const sc = (ROUTES[name] || home)(arg);
      const el = document.createElement('section');
      el.className = `nv-screen nv-${ROUTES[name] ? name : 'home'}`;
      el.setAttribute('aria-label', sc.title);
      const prev = stack[stack.length - 1];
      const backWord = prev ? prev.short : '';
      el.innerHTML = `
        <header class="nv-bar">
          ${backWord ? `<button type="button" class="nv-back" data-back>${I.back}<span>${esc(backWord)}</span></button>`
            : (typeof opts.onLegacy === 'function' && name === 'home' ? '<button type="button" class="nv-legacy" data-legacy>이전 리포트</button>' : '<span></span>')}
          <h2 class="nv-small">${esc(sc.short || sc.title)}</h2><span class="nv-bar-end"></span>
        </header>
        <div class="nv-scroll">
          ${sc.top || ''}
          ${sc.eyebrow ? `<p class="nv-eyebrow">${esc(sc.eyebrow)}</p>` : ''}
          <h1 class="nv-large" tabindex="-1">${esc(sc.title)}</h1>
          ${sc.html}
          <footer class="nv-foot">${Object.values(D.provenance || {}).map((t) => `<p>${esc(t)}</p>`).join('')}</footer>
        </div>
        ${sc.cta ? `<div class="nv-cta"><button type="button" class="nv-pill" ${sc.cta.attr}>${sc.cta.icon || ''}<span>${esc(sc.cta.label)}</span></button></div>` : ''}`;
      const scroller = el.querySelector('.nv-scroll');
      const bar = el.querySelector('.nv-bar');
      scroller.addEventListener('scroll', () => bar.classList.toggle('is-compact', scroller.scrollTop > 40), { passive: true });
      wire(el);
      if (sc.wire) sc.wire(el);
      return { route, el, short: sc.short || sc.title, onTime: sc.onTime || null };
    }
    function wire(el) {
      el.querySelectorAll('[data-push]').forEach((b) => b.addEventListener('click', (e) => { e.stopPropagation(); push(b.dataset.push); }));
      el.querySelectorAll('[data-back]').forEach((b) => b.addEventListener('click', () => back()));
      el.querySelectorAll('[data-legacy]').forEach((b) => b.addEventListener('click', () => opts.onLegacy()));
      el.querySelectorAll('[data-play]').forEach((b) => b.addEventListener('click', (e) => { e.stopPropagation(); play(+b.dataset.a, b.dataset.b === '' ? null : +b.dataset.b, b.dataset.play); }));
      el.querySelectorAll('[data-href]').forEach((b) => b.addEventListener('click', () => { if (!EMBED) location.href = b.dataset.href; }));
    }
    const reduced = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const EASE = 'cubic-bezier(0.32, 0.72, 0, 1)';   // iOS 밀기 곡선 — 빠르게 출발해 부드럽게 멈춘다
    function animate(el, from, to, ms) {
      return new Promise((done) => {
        if (reduced() || !el.animate) { el.style.transform = to; done(); return; }
        const a = el.animate([{ transform: from }, { transform: to }], { duration: ms, easing: EASE, fill: 'forwards' });
        a.onfinish = () => { el.style.transform = to; a.cancel(); done(); };
      });
    }
    let busy = false;
    function goRoot(route) {
      if (stack.length === 1 && stack[0].route === route) return;
      if (audio) audio.pause();
      rebuild([route]);
      saveStack();
    }
    const notifyRoot = () => { if (typeof opts.onRoot === 'function' && stack[0]) opts.onRoot(parse(stack[0].route)[0]); };
    async function push(route) {
      if (TABS && TABS.includes(route)) { goRoot(route); return; }
      if (busy) return;
      busy = true;
      const prev = stack[stack.length - 1];
      const next = renderScreen(route);
      NV.appendChild(next.el);
      stack.push(next);
      if (prev) { prev.el.setAttribute('inert', ''); prev.el.setAttribute('aria-hidden', 'true'); }
      NV.classList.add('is-moving');
      await Promise.all([animate(next.el, 'translateX(100%)', 'translateX(0)', 500), prev ? animate(prev.el, 'translateX(0)', 'translateX(-28%)', 500) : null]);
      NV.classList.remove('is-moving');
      if (prev) prev.el.classList.add('is-under');
      const h = next.el.querySelector('.nv-large'); if (h) h.focus({ preventScroll: true });
      if (MODE === 'page') history.pushState({ rv2: stack.map((s) => s.route) }, '', hashOf());
      saveStack();
      busy = false;
    }
    async function back({ fromHistory = false } = {}) {
      if (busy || stack.length < 2) return;
      if (MODE === 'page' && !fromHistory) { history.back(); return; }   // popstate 가 다시 부른다
      busy = true;
      const top = stack.pop();
      const under = stack[stack.length - 1];
      under.el.classList.remove('is-under');
      under.el.removeAttribute('inert'); under.el.removeAttribute('aria-hidden');
      NV.classList.add('is-moving');
      const fromX = top.el.style.transform || 'translateX(0)';
      const underFrom = under.el.style.transform || 'translateX(-28%)';
      await Promise.all([animate(top.el, fromX, 'translateX(100%)', 420), animate(under.el, underFrom, 'translateX(0)', 420)]);
      NV.classList.remove('is-moving');
      top.el.remove();
      saveStack();
      busy = false;
    }
    function hashOf() { return EMBED ? '#r' : `#/${stack.map((s) => encodeURIComponent(s.route).replace(/%3A/g, ':')).join('/')}`; }
    function saveStack() {
      if (MODE !== 'app') return;
      try { sessionStorage.setItem(STATE_KEY, JSON.stringify({ key: D.deck.title, routes: stack.map((s) => s.route) })); } catch (_) { /* 처음부터 */ }
    }
    function routesFromHash() {
      const h = location.hash.replace(/^#\/?/, '');
      if (!h || h === 'r') return null;
      return h.split('/').filter(Boolean).map((p) => decodeURIComponent(p));
    }
    function rebuild(routes) {
      stack.splice(0).forEach((s) => s.el.remove());
      const list = routes && routes.length ? routes.slice() : ['home'];
      if (list[0] !== 'home' && !(TABS && TABS.includes(list[0]))) list.unshift('home');
      list.forEach((r, k) => {
        if (k > 0) { const p = stack[stack.length - 1]; p.el.style.transform = 'translateX(-28%)'; p.el.classList.add('is-under'); p.el.setAttribute('inert', ''); p.el.setAttribute('aria-hidden', 'true'); }
        const s = renderScreen(r);
        NV.appendChild(s.el);
        stack.push(s);
      });
      notifyRoot();
    }

    /* ── 왼쪽 가장자리 밀기 — 손가락을 1:1 로 따라오고, 놓을 때의 속도 · 거리로 정한다(중간에 되돌릴 수 있다) ── */
    let drag = null;
    NV.addEventListener('pointerdown', (e) => {
      if (stack.length < 2 || busy) return;
      const r = NV.getBoundingClientRect();
      if (e.clientX - r.left > 22) return;
      drag = { x0: e.clientX, w: r.width, t0: performance.now(), x: e.clientX, v: 0, id: e.pointerId };
      NV.setPointerCapture(e.pointerId);
    });
    NV.addEventListener('pointermove', (e) => {
      if (!drag || e.pointerId !== drag.id) return;
      const now = performance.now();
      drag.v = (e.clientX - drag.x) / Math.max(1, now - drag.t0); drag.x = e.clientX; drag.t0 = now;
      const dx = Math.max(0, e.clientX - drag.x0);
      stack[stack.length - 1].el.style.transform = `translateX(${dx}px)`;
      stack[stack.length - 2].el.style.transform = `translateX(${-28 + 28 * (dx / drag.w)}%)`;
    });
    const endDrag = async (e) => {
      if (!drag || e.pointerId !== drag.id) return;
      const dx = Math.max(0, drag.x - drag.x0); const w = drag.w; const go = drag.v > 0.45 || dx > w * 0.4;
      drag = null;
      if (go) { if (MODE === 'page') history.back(); else back({ fromHistory: true }); return; }
      const top = stack[stack.length - 1].el; const under = stack[stack.length - 2].el;
      await Promise.all([animate(top, `translateX(${dx}px)`, 'translateX(0)', 300), animate(under, `translateX(${-28 + 28 * (dx / w)}%)`, 'translateX(-28%)', 300)]);
    };
    NV.addEventListener('pointerup', endDrag); NV.addEventListener('pointercancel', endDrag);

    /* ═══ 화면들 ═══════════════════════════════════════════════════════ */

    /* 홈 — 토스식 큰 숫자 하나 + iOS 묶음 목록. 고칠 것이 주인공, 나머지는 입구 */
    function home() {
      const sc = V.score;
      const val = sc ? sc.value : null;
      const C = 2 * Math.PI * 46;
      const top = V.issues.slice(0, 3);
      const real = V.evaluators.filter((e) => !e.absent);
      const remarks = V.evaluators.reduce((n, e) => n + e.remarks.filter((r) => !r.filler).length, 0);
      const row = (x, k) => `<button type="button" class="nv-row" data-push="issue:${esc(x.id)}">
          <span class="nv-num t-${tone(x)}">${k + 1}</span><span class="nv-row-main"><b>${esc(x.title)}</b><small>${esc(EV[x.evidence])}${x.status === 'conflicting' ? ' · 판정이 흔들려요' : ''}</small></span><i class="nv-chev">${I.chev}</i></button>`;
      return {
        title: '리포트', short: '리포트', eyebrow: `${D.sample ? '샘플 · ' : ''}${D.deck.title}`,
        html: `
        ${D.sample ? '<div class="nv-callout nv-samplenote"><b>샘플 리포트예요</b><p>미리 돌려 둔 부스 시연 발표의 실제 분석이에요. 직접 발표를 마치면 이 자리에 내 리포트가 떠요.</p></div>' : ''}
        <section class="nv-hero">
          ${val != null ? `<div class="nv-score">
            <svg class="nv-ring" viewBox="0 0 108 108" aria-hidden="true"><circle cx="54" cy="54" r="46" class="bg"/><circle cx="54" cy="54" r="46" class="fg" style="--c:${C.toFixed(1)};--off:${(C * (1 - Math.max(0, Math.min(100, val)) / 100)).toFixed(1)}"/></svg>
            <div class="nv-score-in"><b>${esc(grade(val))}</b><span>${esc(val)}점</span></div></div>` : ''}
          <div class="nv-hero-txt"><p class="nv-cap">발표 완성도${sc && sc.situation ? ` · ${esc(sc.situation)}` : ''}</p>
            <p class="nv-headline">${esc(V.headline || (top[0] ? top[0].title : '분석 결과를 정리했어요'))}</p>
            ${V.duration_sec ? `<p class="nv-meta">${fmt(V.duration_sec)} 발표 · ${(V.slides || []).length}장</p>` : ''}</div>
        </section>
        <h3 class="nv-sec">먼저 고칠 것</h3>
        <div class="nv-group">${top.map(row).join('') || '<p class="nv-empty">근거가 있는 문제를 찾지 못했어요.</p>'}</div>
        ${top.length && top.length < 3 ? `<p class="nv-note">근거가 있는 문제는 ${top.length}개예요. 개수를 채우려고 지어내지 않았어요.</p>` : ''}
        ${V.unknown.length ? `<div class="nv-group">${V.unknown.map((u) => `<button type="button" class="nv-row" data-push="issue:${esc(u.id)}">${badge(u)}<span class="nv-row-main"><b>${esc(u.title)}</b><small>분석이 대체값으로 끝났어요</small></span><i class="nv-chev">${I.chev}</i></button>`).join('')}</div>` : ''}
        ${V.strengths.length ? `<h3 class="nv-sec">잘한 점</h3><div class="nv-group">${V.strengths.slice(0, 4).map((x) => `<button type="button" class="nv-row" data-push="issue:${esc(x.id)}">${badge(x)}<span class="nv-row-main"><b>${esc(x.title)}</b></span><i class="nv-chev">${I.chev}</i></button>`).join('')}</div>` : ''}
        <h3 class="nv-sec">더 살펴보기</h3>
        <div class="nv-group">
          <button type="button" class="nv-row" data-push="replay"><span class="nv-ico i-blue">${I.wave}</span><span class="nv-row-main"><b>발표 다시 보기</b><small>${D.deck.audio_url ? '실제 녹음 · 받아쓰기 · 장 그림을 같이' : '받아쓰기 · 장 그림을 같이'}</small></span><span class="nv-val">${fmt(V.duration_sec)}</span><i class="nv-chev">${I.chev}</i></button>
          <button type="button" class="nv-row" data-push="audience"><span class="nv-ico i-orange">${I.people}</span><span class="nv-row-main"><b>삐약이 청중석</b><small>${real.length ? `${real.length}마리가 ${remarks}마디 했어요` : V.evaluators.length ? '이번엔 다 못 왔어요' : '청중 반응을 불러오고 있어요'}</small></span>
            <span class="nv-faces">${V.evaluators.map((e) => `<img src="${esc(asset(`assets/chick-${e.key}-neutral.svg`))}" alt="" class="${e.absent ? 'off' : ''}">`).join('')}</span><i class="nv-chev">${I.chev}</i></button>
          <button type="button" class="nv-row" data-push="practice"><span class="nv-ico i-green">${I.chat}</span><span class="nv-row-main"><b>Q&A 돌아보기</b><small>${V.qa.length ? `질문 ${V.qa.length}개 · 내 어느 말에서 꼬리질문이 나왔나` : 'Q&A 기록이 없어요'}</small></span><i class="nv-chev">${I.chev}</i></button>
          ${sc ? `<button type="button" class="nv-row" data-push="scores"><span class="nv-ico i-gray">${I.chart}</span><span class="nv-row-main"><b>기준별 점수</b><small>39개 항목을 7개 기준으로</small></span><span class="nv-val">${esc(val)}점</span><i class="nv-chev">${I.chev}</i></button>` : ''}
        </div>`,
        cta: { label: '다시 연습하기', attr: 'data-push="practice"', icon: I.redo },
      };
    }

    /* 진단 하나 — 무엇이 · 왜 · 근거(실제 음성으로) · 청중 반응, 아래 「고쳐 보기」 */
    function issue(id) {
      const x = insight(id) || V.issues[0] || all()[0];
      if (!x) return { title: '진단', html: '<p class="nv-empty">진단이 없어요.</p>' };
      const t = timeOf(x);
      const cards = []; const rows = [];
      x.proofs.forEach((p, k) => {
        if (p.kind === 'said') cards.push(`<div class="nv-card nv-quote"><p class="nv-cap">말한 구절${p.anchor.start_sec != null ? ` · ${fmt(p.anchor.start_sec)}` : ''}${p.anchor.slide_no ? ` · ${p.anchor.slide_no}장` : ''}</p>
          <blockquote>${esc(p.text)}</blockquote><div class="nv-acts">${p.anchor.start_sec != null ? playBtn(`q${k}`, p.anchor.start_sec, p.anchor.end_sec, '실제 목소리로 듣기') : ''}
          <button type="button" class="nv-link" data-push="replay:${esc(x.id)}">발표에서 보기</button></div></div>`);
        else if (p.kind === 'deck') cards.push(`<div class="nv-card nv-deckq">${p.anchor.slide_no ? slideTag(p.anchor.slide_no, 'nv-thumb') : ''}<div><p class="nv-cap">자료 ${esc(p.anchor.slide_no || '')}장 원문</p><p class="nv-body">${esc(plainDeck(p.text))}</p></div></div>`);
        else if (p.kind === 'time') rows.push(`<div class="nv-row is-static"><span class="nv-ico i-gray">${I.wave}</span><span class="nv-row-main"><b>${esc(p.text)}</b><small>${fmt(p.anchor.start_sec)}–${fmt(p.anchor.end_sec)}</small></span>${p.anchor.start_sec != null ? playBtn(`t${k}`, p.anchor.start_sec, p.anchor.end_sec, '듣기') : ''}</div>`);
        else rows.push(`<div class="nv-row is-static"><span class="nv-ico i-gray">${I.doc}</span><span class="nv-row-main"><b>${esc(p.text)}</b></span></div>`);
      });
      return {
        title: x.title, short: '진단', eyebrow: `${x.polarity === 'strength' ? '잘한 점' : x.polarity === 'unknown' ? '판정 못 함' : '고칠 것'} · ${CRIT[x.criterion] || '종합'}`,
        html: `
        <div class="nv-status">${badge(x)}<span>${esc(EV[x.evidence])}</span></div>
        ${x.conflict ? `<div class="nv-callout t-ct"><b>판정이 흔들려요</b><p>${esc(x.conflict)}</p></div>` : ''}
        ${x.why ? `<h3 class="nv-sec">왜 이렇게 봤나요</h3><div class="nv-card"><p class="nv-body">${esc(x.why)}</p></div>` : ''}
        ${cards.length || rows.length ? `<h3 class="nv-sec">근거</h3>${cards.join('')}${rows.length ? `<div class="nv-group">${rows.join('')}</div>` : ''}`
          : '<div class="nv-callout"><b>근거가 없어요</b><p>분석이 이 판정의 근거를 남기지 않았어요. 믿기 어려운 판정이라 순위에서 뒤로 뺐어요.</p></div>'}
        ${x.remarks.length ? `<h3 class="nv-sec">청중 반응</h3><div class="nv-group">${x.remarks.map((r) => `<button type="button" class="nv-row" data-push="chick:${esc(r.speaker)}"><img class="nv-face" src="${esc(asset(`assets/chick-${r.speaker}-neutral.svg`))}" alt=""><span class="nv-row-main"><b>${esc(r.text)}</b><small>${esc(ST[r.status] || '')}</small></span><i class="nv-chev">${I.chev}</i></button>`).join('')}</div>` : ''}`,
        cta: x.polarity === 'strength' ? (t && audio ? { label: '이 부분 다시 듣기', attr: `data-play="cta" data-a="${t[0]}" data-b="${t[1]}"`, icon: I.play } : null) : { label: '고쳐 보기', attr: `data-push="coach:${esc(x.id)}"` },
      };
    }

    /* 코칭 — 원래 → 까닭 → 바꿔 말하기 를 옆으로 넘기는 카드 */
    function coach(id) {
      const x = insight(id) || V.issues[0];
      if (!x) return { title: '코칭', html: '<p class="nv-empty">고칠 것이 없어요.</p>' };
      const said = x.proofs.find((p) => p.kind === 'said' && p.status === 'supported');
      const times = x.proofs.filter((p) => p.kind === 'time');
      const acts = x.actions.filter((a) => a.text);
      const act = acts[0] || x.actions[0];
      const slide = (act && act.anchor && act.anchor.slide_no) || x.anchor.slide_no;
      const deck = (D.deck.slides || []).find((s) => s.slide_no === slide);
      const pages = [
        { k: '원래 발표', body: said ? `<blockquote>${esc(said.text)}</blockquote><p class="nv-cap">${fmt(said.anchor.start_sec)}–${fmt(said.anchor.end_sec)} · 받아쓰기 원문</p><div class="nv-acts">${playBtn('c0', said.anchor.start_sec, said.anchor.end_sec, '들어 보기')}</div>`
          : times.length ? times.map((p) => `<blockquote>${esc(p.text)}</blockquote>`).join('') : '<blockquote>이 부분을 말한 구절을 찾지 못했어요.</blockquote>' },
        { k: '진단한 까닭', body: `<blockquote>${esc(x.why || '분석이 까닭을 남기지 않았어요.')}</blockquote>${x.conflict ? `<p class="nv-cap t-ct-text">${esc(x.conflict)}</p>` : ''}` },
        { k: '이렇게 바꿔 말해요', accent: true, body: `${acts.length ? acts.slice(0, 3).map((a) => `<blockquote>${esc(a.text)}</blockquote>`).join('') : '<blockquote>제안 문장이 아직 없어요. 자료 원문을 보며 다시 설명해 봐요.</blockquote>'}<p class="nv-cap">근거 · ${esc((act && act.basis) || '없음')}</p>` },
      ];
      return {
        title: '이렇게 고쳐요', short: '코칭', eyebrow: x.title,
        html: `
        <div class="nv-pager" tabindex="0" aria-label="코칭 카드 세 장 — 옆으로 넘겨요">${pages.map((p, k) => `<article class="nv-page${p.accent ? ' is-accent' : ''}"><p class="nv-step">${k + 1} / ${pages.length} · ${esc(p.k)}</p>${p.body}</article>`).join('')}</div>
        <div class="nv-dots" aria-hidden="true">${pages.map((_, k) => `<i${k === 0 ? ' class="on"' : ''}></i>`).join('')}</div>
        <p class="nv-note">새로 지은 문장이 아니에요. ${esc((act && act.basis) || '')}에서 가져왔어요. 개념 전달 판정은 말한 내용을 자료와 대조해서 내리니, 자료의 핵심을 말로 옮기면 대조할 거리가 생겨요.</p>
        ${deck ? `<h3 class="nv-sec">자료 ${esc(slide)}장</h3><div class="nv-card nv-deckq">${slideTag(slide, 'nv-thumb')}<p class="nv-body">${esc(plainDeck(deck.raw_text || deck.title || '').slice(0, 360))}</p></div>` : ''}`,
        cta: { label: '이 부분 연습하기', attr: `data-push="practice:${esc(x.id)}"`, icon: I.redo },
        wire(el) {
          const pg = el.querySelector('.nv-pager'); const dots = [...el.querySelectorAll('.nv-dots i')];
          pg.addEventListener('scroll', () => { const w = pg.firstElementChild ? pg.firstElementChild.getBoundingClientRect().width : pg.clientWidth; const k = Math.round(pg.scrollLeft / Math.max(1, w)); dots.forEach((d, j) => d.classList.toggle('on', j === Math.min(dots.length - 1, k))); }, { passive: true });
        },
      };
    }

    /* 발표 다시 보기 — 장 그림 · 재생 · 시간축 · 받아쓰기. 시간축 표시를 누르면 아래에서 진단 시트가 올라온다 */
    function replay(arg) {
      const focus = insight(arg);
      const t = timeOf(focus);
      const dur = V.duration_sec || 0;
      const pct = (s) => `${(100 * s / (dur || 1)).toFixed(3)}%`;
      const marks = [...V.issues, ...V.strengths].flatMap((x) => x.proofs.filter((p) => p.anchor.start_sec != null && p.status === 'supported' && p.kind !== 'time').map((p) => ({ x, p })));
      const hit = new Set(focus ? focus.proofs.flatMap((p) => (p.kind === 'said' && p.anchor.utt_ids) || []) : []);
      const slideAt = (s) => (V.slides.find((sl) => sl.spans.some((sp) => s >= sp.start && s < sp.end)) || {}).no || 1;
      const s0 = t ? slideAt(t[0]) : (focus && focus.anchor.slide_no) || 1;
      return {
        title: '발표 다시 보기', short: '다시 보기', eyebrow: focus ? focus.title : `${D.sample ? '샘플 · ' : ''}${D.deck.title}`,
        html: `
        <div class="nv-stage">${slideTag(s0, 'nv-slide')}</div>
        <div class="nv-card nv-player">
          <div class="nv-player-row">
            <button type="button" class="nv-bigplay" data-play="${t ? 'focus' : 'all'}" data-a="${t ? t[0] : 0}" data-b="${t ? t[1] : ''}" ${audio ? '' : 'disabled'} aria-label="${t ? '이 구간 듣기' : '처음부터 듣기'}"><span class="nv-pi">${I.play}</span></button>
            <div class="nv-player-txt"><b>${t ? `${fmt(t[0])}–${fmt(t[1])} 구간` : '처음부터 듣기'}</b><small class="nv-clock">0:00 / ${fmt(dur)}</small></div>
          </div>
          <div class="nv-track" role="slider" tabindex="0" aria-label="발표 시간축" aria-valuemin="0" aria-valuemax="${Math.round(dur)}">
            ${V.slides.flatMap((s) => s.spans.map((sp) => `<span class="nv-band" style="left:${pct(sp.start)};width:${pct(sp.end - sp.start)}"><em>${s.no}장</em></span>`)).join('')}
            ${marks.map(({ x, p }) => `<button type="button" class="nv-mark t-${tone(x)}${focus && x.id === focus.id ? ' is-on' : ''}" data-sheet="${esc(x.id)}" style="left:${pct(p.anchor.start_sec)}" aria-label="${esc(x.title)}"></button>`).join('')}
            <i class="nv-head"></i>
          </div>
          <div class="nv-legend"><span><i class="t-mid"></i>고칠 것</span><span><i class="t-ct"></i>판정이 흔들림</span><span><i class="t-ok"></i>잘한 점</span></div>
          ${D.transcript && D.transcript.marks_estimated ? '<p class="nv-cap">장 경계는 녹음 내용으로 추정한 대략 위치예요.</p>' : ''}
          ${audio ? '' : '<p class="nv-cap">녹음이 저장되지 않아 들을 수 없어요. 글로만 봐요.</p>'}
        </div>
        <h3 class="nv-sec">받아쓰기</h3>
        <div class="nv-group nv-lines">${V.utterances.map((u) => `<button type="button" class="nv-line${hit.has(u.id) ? ' is-hit' : ''}" data-u="${esc(u.id)}" data-s="${u.start}"><time>${fmt(u.start)}</time><span>${esc(u.text)}</span></button>`).join('') || '<p class="nv-empty">받아쓰기가 없어요.</p>'}</div>
        <div class="nv-sheet" hidden><div class="nv-sheet-card" role="dialog" aria-label="진단"><i class="nv-grab"></i><div class="nv-sheet-body"></div></div></div>`,
        onTime(now) {
          const el = stack[stack.length - 1].el;
          const head = el.querySelector('.nv-head'); if (head) head.style.left = pct(now);
          const clk = el.querySelector('.nv-clock'); if (clk) clk.textContent = `${fmt(now)} / ${fmt(dur)}`;
          const u = V.utterances.find((x) => x.start <= now && x.end >= now);
          el.querySelectorAll('.nv-line.is-now').forEach((l) => l.classList.remove('is-now'));
          if (u) { const l = el.querySelector(`.nv-line[data-u="${u.id}"]`); if (l) l.classList.add('is-now'); }
          const sl = slideAt(now); const img = el.querySelector('.nv-stage img');
          if (img && img.dataset.slide !== String(sl)) el.querySelector('.nv-stage').innerHTML = slideTag(sl, 'nv-slide');
        },
        wire(el) {
          el.querySelectorAll('.nv-line').forEach((b) => b.addEventListener('click', () => play(+b.dataset.s, null, `u${b.dataset.u}`)));
          const tr = el.querySelector('.nv-track');
          tr.addEventListener('click', (e) => { if (e.target.closest('.nv-mark')) return; const r = tr.getBoundingClientRect(); play(((e.clientX - r.left) / r.width) * dur, null, 'scrub'); });
          tr.addEventListener('keydown', (e) => { if (!audio) return; if (e.key === 'ArrowRight') audio.currentTime += 5; if (e.key === 'ArrowLeft') audio.currentTime -= 5; });
          const sheet = el.querySelector('.nv-sheet'); const body = el.querySelector('.nv-sheet-body'); const card = el.querySelector('.nv-sheet-card');
          const close = () => { sheet.classList.remove('is-open'); setTimeout(() => { sheet.hidden = true; }, 320); };
          const openSheet = (id) => {
            const x = insight(id); if (!x) return;
            const tt = timeOf(x);
            body.innerHTML = `<p class="nv-eyebrow">${x.polarity === 'strength' ? '잘한 점' : x.status === 'conflicting' ? '판정이 흔들려요' : '고칠 것'}</p><h3 class="nv-sheet-title">${esc(x.title)}</h3>
              ${x.why ? `<p class="nv-body">${esc(x.why)}</p>` : ''}
              <div class="nv-acts">${tt ? playBtn('sheet', tt[0], tt[1], `${fmt(tt[0])} 듣기`) : ''}<button type="button" class="nv-link" data-push="issue:${esc(x.id)}">자세히 보기</button></div>`;
            wire(body);
            sheet.hidden = false;
            requestAnimationFrame(() => sheet.classList.add('is-open'));
          };
          el.querySelectorAll('[data-sheet]').forEach((m) => m.addEventListener('click', (e) => { e.stopPropagation(); openSheet(m.dataset.sheet); }));
          sheet.addEventListener('click', (e) => { if (e.target === sheet) close(); });
          // 시트 손잡이를 아래로 끌어 닫기 — 손을 1:1 로 따라온다
          let sd = null;
          card.addEventListener('pointerdown', (e) => { if (!e.target.closest('.nv-grab')) return; sd = { y0: e.clientY, id: e.pointerId }; card.setPointerCapture(e.pointerId); card.style.transition = 'none'; });
          card.addEventListener('pointermove', (e) => { if (!sd || e.pointerId !== sd.id) return; card.style.transform = `translateY(${Math.max(0, e.clientY - sd.y0)}px)`; });
          const up = (e) => { if (!sd || e.pointerId !== sd.id) return; const dy = e.clientY - sd.y0; sd = null; card.style.transition = ''; card.style.transform = ''; if (dy > 90) close(); };
          card.addEventListener('pointerup', up); card.addEventListener('pointercancel', up);
          const h = el.querySelector('.nv-line.is-hit');
          if (h) setTimeout(() => { const sc = el.querySelector('.nv-scroll'); sc.scrollTo({ top: h.offsetTop - sc.clientHeight / 2, behavior: reduced() ? 'auto' : 'smooth' }); }, 540);
        },
      };
    }

    /* 삐약이 청중석 — 와우 포인트: 조명이 켜지는 어두운 무대 한 칸. 고르면 그 삐약이 화면으로 */
    function audience() {
      const evs = V.evaluators;
      return {
        title: '삐약이 청중석', short: '청중석',
        html: `<div class="nv-theater"><i class="nv-spot"></i>
          <p>점수를 매기는 심사위원이 아니에요.<br>넷이 저마다 맡은 것만 보고 한마디씩 해요.</p>
          <div class="nv-seats">${evs.length ? evs.map((e, k) => `<button type="button" class="nv-seat${e.absent ? ' is-off' : ''}" data-push="chick:${esc(e.key)}" style="--k:${k}">
            <img src="${esc(asset(`assets/chick-${e.key}-${e.absent ? 'neutral' : MOOD[(e.remarks.find((r) => !r.filler) || {}).mood] || 'neutral'}.svg`))}" alt="">
            <b>${esc(e.name)}</b><small>${e.absent ? '이번엔 못 왔어요' : `${e.remarks.filter((r) => !r.filler).length}마디`}</small></button>`).join('')
            : '<p class="nv-empty">청중 반응을 불러오고 있어요.</p>'}</div></div>
        <h3 class="nv-sec">맡은 것</h3>
        <div class="nv-group">${evs.map((e) => `<button type="button" class="nv-row" data-push="chick:${esc(e.key)}"><img class="nv-face" src="${esc(asset(`assets/chick-${e.key}-neutral.svg`))}" alt=""><span class="nv-row-main"><b>${esc(e.name)}</b><small>${esc(e.lane)} · ${esc(e.model)}</small></span><span class="nv-val">${e.absent ? '결석' : `${e.remarks.filter((r) => !r.filler).length}마디`}</span><i class="nv-chev">${I.chev}</i></button>`).join('')}</div>
        <p class="nv-note">말마다 분석 근거와 맞는지 같이 보여 드려요. 근거가 없는 말은 근거처럼 보이지 않게 표시해요.</p>`,
      };
    }
    function chick(key) {
      const e = V.evaluators.find((x) => x.key === key);
      if (!e) return { title: '청중', html: '<p class="nv-empty">이 삐약이의 기록이 없어요.</p>' };
      const real = e.remarks.filter((r) => !r.filler);
      const engine = (cid) => { const a = G.nodes.get(`A:align:${cid.slice(2)}`); const v = G.nodes.get(`V:said:${cid.slice(2)}`);
        return a ? { word: UI_WORD[a.ui_status] || a.ui_status, cls: `v-${a.ui_status}`, said: v && v.status === 'supported' ? v.text : '' } : null; };
      const jump = (cid) => { const hit = all().find((x) => x.concepts.some((c) => c.id === cid)); return hit ? `issue:${hit.id}` : 'replay'; };
      const stTone = (s) => (s === 'supported' ? 'ok' : s === 'conflicting' ? 'ct' : s === 'unsupported' ? 'no' : 'na');
      return {
        title: e.name, short: e.name, eyebrow: `${e.model} · ${e.lane}`,
        top: `<div class="nv-chickhero"><img src="${esc(asset(`assets/chick-${e.key}-${e.absent ? 'neutral' : MOOD[(real[0] || {}).mood] || 'neutral'}.svg`))}" alt=""></div>`,
        html: `
        ${e.absent ? '<div class="nv-callout"><b>이번엔 객석에 못 왔어요</b><p>모델 응답이 실패했어요. 대신 나온 대사는 근거로 쓰지 않아요.</p></div>' : ''}
        ${real.map((r) => { const eng = r.concepts.map((c) => ({ c, x: engine(c.id) })).filter((y) => y.x);
          return `<div class="nv-card nv-remark"><p class="nv-bubble">${esc(r.text)}</p>
            <div class="nv-status"><span class="nv-dot t-${stTone(r.status)}"></span><span>${esc(ST[r.status] || '')}</span></div>
            ${r.why && !eng.length ? `<p class="nv-cap">${esc(r.why)}</p>` : ''}
            ${eng.map(({ c, x }) => `<p class="nv-cap">분석 엔진은 「${esc(c.label)}」을 <b class="${x.cls}">${esc(x.word)}</b>으로 봤어요${x.said ? ` — “${esc(x.said)}”` : ''}</p>`).join('')}
            ${r.concepts.length ? `<div class="nv-acts">${r.concepts.map((c) => `<button type="button" class="nv-link" data-push="${esc(jump(c.id))}">「${esc(c.label)}」 근거 보기</button>`).join('')}</div>` : ''}</div>`; }).join('')}
        ${real.some((r) => r.status === 'conflicting') ? '<p class="nv-note">의견이 갈리는 곳이 있어요. 청중은 그 낱말이 나왔는지를, 분석 엔진은 뜻이 자료와 맞는지를 봐요. 억지로 맞추지 않았어요.</p>' : ''}`,
      };
    }

    /* 다시 연습 — 갈 곳 + Q&A 전환점 목록(누르면 그 질문 화면) */
    function practice(id) {
      const x = insight(id) || V.issues[0];
      const targets = [];
      (x ? x.actions : []).forEach((a) => { if (a.practice && !targets.some((p) => p.label === a.practice.label)) targets.push(a.practice); });
      targets.push({ label: '처음부터 다시 발표하기', route: '#/rehearsal', kind: 'full' });
      const why = (p) => (p.kind === 'qa' ? '이 개념 질문을 Q&A 에서 다시 받아요' : p.kind === 'slide' ? '리허설에서 그 장부터 다시 말해요' : '리허설을 새로 시작해요');
      const state = (r) => (r.setAside === 'concept' ? '다른 개념으로 넘김' : r.setAside === 'skip' ? '건너뜀' : r.setAside === 'perspective' ? '관점 바꿈' : r.verdict === 'good' ? '스스로 설명함' : r.verdict ? '도움 받아 설명함' : '안 물음');
      return {
        title: '다시 연습', short: '연습', eyebrow: x ? x.title : '',
        html: `
        <h3 class="nv-sec">어디부터 할까요</h3>
        <div class="nv-group">${targets.map((p) => `<button type="button" class="nv-row" data-href="index.html${esc(p.route)}"><span class="nv-ico i-green">${I.redo}</span><span class="nv-row-main"><b>${esc(p.label)}</b><small>${why(p)}${EMBED ? ' — 앱에서 열려요' : ''}</small></span><i class="nv-chev">${I.chev}</i></button>`).join('')}</div>
        <p class="nv-note">다시 연습한 결과는 아직 이 진단에 이어지지 않아요. 그래서 나아졌는지는 보여 주지 않아요.</p>
        <h3 class="nv-sec">Q&A 돌아보기</h3>
        <div class="nv-group">${V.qa.length ? V.qa.map((q) => `<button type="button" class="nv-row" data-push="qa:${esc(q.id)}"><span class="nv-ico i-${q.result && q.result.verdict === 'good' ? 'green' : q.result && q.result.setAside ? 'gray' : 'orange'}">${I.chat}</span><span class="nv-row-main"><b>${esc(q.text)}</b><small>${esc(state(q.result || {}))}${q.steps.length > 1 ? ` · 꼬리질문 ${q.steps.length - 1}번` : ''}</small></span><i class="nv-chev">${I.chev}</i></button>`).join('') : '<p class="nv-empty">이 리포트엔 Q&A 기록이 없어요.</p>'}</div>`,
      };
    }
    /* Q&A 한 질문 — 메신저처럼 다 늘어놓지 않고 전환점만: 내 답 → AI 가 주목한 말 → 꼬리질문 */
    function qa(qid) {
      const q = V.qa.find((x) => x.id === qid);
      if (!q) return { title: 'Q&A', html: '<p class="nv-empty">이 질문의 기록이 없어요.</p>' };
      const hl = (text, claim) => { const k = claim ? text.indexOf(claim) : -1; return k < 0 ? esc(text) : `${esc(text.slice(0, k))}<mark>${esc(claim)}</mark>${esc(text.slice(k + claim.length))}`; };
      return {
        title: q.text, short: '질문', eyebrow: q.label,
        html: `
        <div class="nv-chat">${q.steps.length ? q.steps.map((s) => `
          <div class="nv-msg me"><p>${s.answer ? hl(s.answer, s.claim) : s.claim ? `<mark>${esc(s.claim)}</mark>` : ''}</p></div>
          ${s.claim ? `<p class="nv-why">AI 가 주목한 내 말 「${esc(s.claim)}」</p>` : ''}
          ${s.followup ? `<div class="nv-msg ai"><img src="${esc(asset('assets/chick-solar-curious.svg'))}" alt=""><p>${esc(s.followup)}</p></div>` : ''}`).join('') : '<p class="nv-empty">답하지 않았어요.</p>'}</div>
        ${q.gist ? `<h3 class="nv-sec">자료가 기대한 답</h3><div class="nv-card"><p class="nv-body">${esc(q.gist)}</p></div>` : ''}
        ${D.provenance && D.provenance.qa ? `<p class="nv-note">${esc(D.provenance.qa)}</p>` : ''}`,
      };
    }
    function scores() {
      const sc = V.score;
      return {
        title: '기준별 점수', short: '점수', eyebrow: sc ? `${sc.situation} 기준` : '',
        html: sc ? `<div class="nv-group">${sc.criteria.map((k) => `<div class="nv-row is-static nv-crit"><span class="nv-row-main"><b>${esc(k.name)}</b><span class="nv-meter"><i style="--w:${k.scored ? Math.round(k.average) : 0}%"></i></span></span><span class="nv-val">${k.scored ? Math.round(k.average) : '못 잼'}</span></div>`).join('')}</div>
          <p class="nv-note">기존 채점(39개 항목 → 7개 기준) 그대로예요. 리포트 2.0 은 점수를 새로 매기지 않아요.</p>` : '<p class="nv-empty">점수가 없어요.</p>',
      };
    }

    /* ── 시작 ── */
    build();
    setAudio();
    if (MODE === 'page') {
      rebuild(routesFromHash());
      history.replaceState({ rv2: stack.map((s) => s.route) }, '', hashOf());
      window.addEventListener('popstate', (e) => {
        const want = (e.state && e.state.rv2) || routesFromHash() || ['home'];
        if (want.length === stack.length - 1 && want.every((r, k) => r === stack[k].route)) back({ fromHistory: true });
        else rebuild(want);
      });
    } else {
      let saved = null;
      try { saved = JSON.parse(sessionStorage.getItem(STATE_KEY) || 'null'); } catch (_) { saved = null; }
      rebuild(saved && saved.key === D.deck.title ? saved.routes : null);
    }
    return {
      /** 늦게 온 재료(청중석 등)를 얹고 지금 스택 그대로 다시 그린다 */
      update(patch) { D = { ...D, ...patch }; build(); rebuild(stack.map((s) => s.route)); },
      /** 탭 i 로 (스튜디오 정거장 · ← → 키) */
      tab(i) { if (TABS && TABS[i]) goRoot(TABS[i]); },
      destroy() { if (audio) audio.pause(); root.classList.remove('rv2'); root.innerHTML = ''; },
    };
  }

  /* ═══ 단독 페이지 ═══════════════════════════════════════════════════════ */
  async function loadPageData() {
    if (window.__RV2_DATA) return window.__RV2_DATA;
    const qs = new URLSearchParams(location.search);
    if (qs.get('src') === 'last') {
      let last = null;
      try { last = JSON.parse(localStorage.getItem('cheokcheok:last-report') || 'null'); } catch (_) { last = null; }
      if (!last || !last.pipelineOut) throw new Error('이 브라우저에 저장한 리포트가 없어요. 발표를 한 번 분석하면 생겨요.');
      return inputFromApp({ pipelineOut: last.pipelineOut, deck: { title: last.fileName || '', slides: (last.slideTitles || []).map((t, k) => ({ slide_no: k + 1, title: t })),
        audio_url: last.deckAudio ? `/api/v1/dev/decks/file?deck=${encodeURIComponent(last.deckAudio)}&kind=audio` : '' }, qa: last.qa, saved: '' });
    }
    const res = await fetch('data/report_v2_rec.json', { credentials: 'same-origin' });
    if (!res.ok) throw new Error(res.status === 404 ? '실측 묶음은 팀 브라우저에서만 열려요. /auth 에서 팀 코드를 넣은 뒤 다시 열어요.' : `데이터를 불러오지 못했어요 (${res.status}).`);
    return res.json();
  }
  async function bootPage(el) {
    try {
      mount(el, await loadPageData(), { mode: 'page' });
    } catch (err) {
      el.classList.add('rv2');
      el.innerHTML = `<div class="nv"><section class="nv-screen"><div class="nv-scroll"><h1 class="nv-large">리포트를 열지 못했어요</h1><p class="nv-lead">${esc(err.message || err)}</p></div></section></div>`;
    }
  }

  if (typeof window !== 'undefined') {
    window.ReportV2 = { mount, inputFromApp, bootPage };
    const pageRoot = typeof document !== 'undefined' && document.getElementById && document.getElementById('rv2Page');
    if (pageRoot) bootPage(pageRoot);
  }
})();
