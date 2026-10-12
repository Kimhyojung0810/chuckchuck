/*
 * /hi/stage 시안 A 「들어오자마자 채점당한다」 — 무대 (2026-10-13). intro.js(팀 · 시트 · 퍼널 · 떠오르기) 다음에 돈다.
 *
 * 이 파일이 맡는 것
 *   (1) 사람 그래프 재생 — data/hi_stage/pose.json(8초 · 15fps 고리, 미리 계산)을 프레임 사이 보간해 2D 캔버스에 그린다.
 *       그리기는 부스 화면과 같은 js/booth_scan_draw.js(person · pulses)를 색만 랜딩 토큰으로 바꿔 쓴다.
 *       ⚠️ 이 움직임은 녹화가 아니다 — 퍼블릭 도메인 그림 한 장의 실제 랜드마크 위에 호흡 · 고개 · 손짓을 계산해 입혔다
 *       (etc/labs/hi_stage/make_pose.mjs). 화면은 그래프를 「녹화」라고 부르지 않는다.
 *   (2) 첫 연출 시간표 — 0.3초 점 · 0.8초 선 · 1.6초부터 칩 · 3.0초 레이저. 시계는 performance.now()(페이지 열린 때부터)라
 *       스크립트가 늦게 와도 연출이 밀리지 않는다. 탭 · 「연출 건너뛰기」 면 끝 상태로.
 *   (3) 근거 펼치기 — 사람(또는 칩)을 누르면 그 장면의 자료 몇 장 · 어느 문장. 값은 녹화 투어(data/tour/delivery-rating.json)에서 읽는다.
 *   (4) 스크롤하면 무대가 밝아지기(--lift) · 주 버튼 띠 색 · theme-color — 스크롤은 붙잡지 않는다(passive).
 *   (5) 시트가 열리면 무대 · main · dock 에 inert (intro.js 는 그대로 두고 #inapp 의 hidden 만 지켜본다).
 * 지킬 것 — 감정 추정 없음. 시선을 자리로 나누지 않음(시선 무리는 아예 빛내지 않는다). 데이터는 textContent 로만.
 */
(() => {
  'use strict';

  const POSE_URL = '/data/hi_stage/pose.json';
  const TOUR_URL = '/data/tour/delivery-rating.json';
  const T_DOTS = 300, T_LINES = 800, T_CHIPS = [1600, 2000, 2400], T_LASER = 2800, T_DONE = 3400;
  const DPR_MAX = 2;
  const LIFT_MAX = 0.55;
  /** 칩 ↔ 그래프 무리 · 기준점 (pose.json anchors) — 시선(gaze) 무리는 쓰지 않는다 */
  const MOMENT = {
    pace: { group: 'voice', anchor: 'voice' },
    claim: { group: 'hand', anchor: 'hand' },
    qa: { group: 'head', anchor: 'head' },
  };
  const COL = { tint: [206, 250, 220], vivid: [12, 175, 104], iris: [236, 255, 247], laser: [232, 92, 74] };

  const $ = (id) => document.getElementById(id);
  const root = document.documentElement;
  const stage = $('stage');
  const fig = $('stage-fig');
  const canvas = $('fig-canvas');
  const hit = $('fig-hit');
  const skipBtn = $('stage-skip');
  if (!stage || !fig || !canvas || !hit) return;
  const reduce = !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
  const chips = Array.from(document.querySelectorAll('.vchip'));
  const chipOf = (m) => chips.find((c) => c.dataset.m === m);

  // ── 근거 문구 — 투어 녹화값이 오기 전엔 HTML 에 적힌 값(같은 값)으로 ──
  let grounds = {
    pace: { k: '말 빠르기 · 발표 전체 2분 20초', main: '1분에 253자예요', sub: '권장(300~350자/분)보다 느려요' },
    claim: { k: '자료 3장 · 핵심 주장', main: '「4.7은 품질이 아니라 리뷰 수집 방식의 결과다」', sub: '자료에 있는 이 문장을 발표에서 말하지 않은 것으로 봤어요' },
    qa: { k: '교수님 질문 · 자료 3장', main: '「4.5점 이상 구간에 82%가 몰려 있다.」', sub: '질문 「4.7이라는 수치가 리뷰 수집 방식의 결과라는 주장의 근거는 무엇인가요?」에 이 문장을 들어 답해 좋아요를 받았어요' },
  };
  const minSec = (s) => { const m = Math.floor(s / 60), r = Math.round(s % 60); return m ? `${m}분${r ? ` ${r}초` : ''}` : `${r}초`; };
  const lastSentence = (q) => { const parts = String(q || '').split(/(?<=\.)\s+/).filter(Boolean); return parts[parts.length - 1] || ''; };

  /** 녹화 투어 → 칩 숫자 · 근거 문장. 모양이 다르면 HTML 값을 그대로 둔다(거짓 값을 지어내지 않는다) */
  function applyTour(t) {
    try {
      const pace = t.analysis.pace;
      const root2 = t.analysis.claim_graph.nodes.find((n) => n.id === t.analysis.claim_graph.root);
      const q = t.qa.questions[0];
      const g = q.answers.good.grounds[0];
      const cpm = Math.round(pace.cpm);
      if (!(cpm > 0) || !root2 || !g) return;
      document.querySelectorAll('[data-f="cpm"]').forEach((n) => { n.textContent = String(cpm); });
      document.querySelectorAll('[data-f="claim-slide"]').forEach((n) => { n.textContent = String(root2.slide_no); });
      document.querySelectorAll('[data-f="deck-title"]').forEach((n) => { n.textContent = t.deck.title; });
      grounds = {
        pace: { k: `말 빠르기 · 발표 전체 ${minSec(t.present.duration_sec)}`, main: `1분에 ${cpm}자예요`, sub: pace.note },
        claim: { k: `자료 ${root2.slide_no}장 · 핵심 주장`, main: `「${root2.label}」`, sub: '자료에 있는 이 문장을 발표에서 말하지 않은 것으로 봤어요' },
        qa: { k: `${t.qa.asker} 질문 · 자료 ${g.slide_no}장`, main: `「${lastSentence(g.quote)}」`,
          sub: `질문 「${q.question}」에 이 문장을 들어 답해 좋아요를 받았어요` },
      };
      if (openM) showGround(openM, null);
    } catch (_) { /* 모양이 다르면 HTML 값 그대로 */ }
  }

  // ── 근거 카드 ──
  const ground = $('ground');
  let openM = null;
  let opener = null;
  function showGround(m, from) {
    const g = grounds[m];
    if (!g || !ground) return;
    $('ground-k').textContent = g.k;
    $('ground-main').textContent = g.main;
    $('ground-sub').textContent = g.sub;
    openM = m;
    if (from) opener = from;
    ground.hidden = false;
    hit.setAttribute('aria-expanded', 'true');
    chips.forEach((c) => c.setAttribute('aria-expanded', String(c.dataset.m === m)));
    if (from) $('ground-close').focus({ preventScroll: true });
  }
  function hideGround() {
    if (!ground || ground.hidden) return;
    ground.hidden = true;
    openM = null;
    hit.setAttribute('aria-expanded', 'false');
    chips.forEach((c) => c.setAttribute('aria-expanded', 'false'));
    if (opener) opener.focus({ preventScroll: true });
  }
  chips.forEach((c) => c.setAttribute('aria-expanded', 'false'));

  // ── 재생 상태 ──
  const playing = root.classList.contains('stage-play') && !reduce;
  let skipAt = playing ? null : -Infinity;          // 건너뛴 시각 — 이후로는 끝 상태
  const elapsed = () => (skipAt != null && performance.now() >= skipAt ? Infinity : performance.now());
  function skip() {
    if (skipAt != null && skipAt <= performance.now()) return;
    skipAt = performance.now();
    root.classList.add('stage-done');
    root.classList.remove('stage-play');
    if (skipBtn) skipBtn.hidden = true;   // 건너뛴 뒤엔 바로 숨긴다
  }
  // 「연출 건너뛰기」 는 CSS 가 보였다가 숨긴다(html.stage-play) — 여기는 누르기만
  if (skipBtn) skipBtn.addEventListener('click', skip);
  hit.addEventListener('click', () => {
    if (elapsed() < T_DONE) { skip(); return; }
    if (openM) { hideGround(); return; }
    showGround(curMoment, hit);
  });
  chips.forEach((c) => c.addEventListener('click', () => {
    if (elapsed() < T_DONE) skip();
    if (openM === c.dataset.m) hideGround(); else showGround(c.dataset.m, c);
  }));
  if (ground) $('ground-close').addEventListener('click', hideGround);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && openM) hideGround(); });

  // ── 그래프 그리기 ──
  const D = window.BoothScanDraw;
  let pose = null;
  let curMoment = 'pace';
  let W = 0, H = 0, u = 1;
  const ctx = canvas.getContext && canvas.getContext('2d');
  if (D && D.COLORS) {   // 부스 화면(어두운 면 · 시안 · 민트)과 같은 그리기, 색만 랜딩 토큰으로 — 이 페이지에는 부스 화면이 없다
    D.COLORS.edge = COL.tint; D.COLORS.node = COL.vivid; D.COLORS.brand = COL.tint; D.COLORS.iris = COL.iris;
  }

  function size() {
    const r = fig.getBoundingClientRect();
    u = Math.min(DPR_MAX, window.devicePixelRatio || 1);
    W = Math.round(r.width * u); H = Math.round(r.height * u);
    canvas.width = W; canvas.height = H;
  }
  /** pose 상자 → 캔버스 픽셀. SVG(viewBox · xMidYMax meet)와 같은 식이라 정지 그림과 겹친다 */
  function fit() {
    const [bw, bh] = pose.box;
    const s = Math.min(W / bw, H / bh);
    return { s, x0: (W - bw * s) / 2, y0: H - bh * s };
  }
  const smooth = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };

  /** 고리 시간 — 연출 끝(3.0초)에 정지 그림(still_t)과 같은 자세가 되게 맞춘다 */
  function loopT(ms) {
    const L = pose.frames.length / pose.fps;
    const t = (ms === Infinity ? T_LASER : ms) / 1000 + pose.still_t - T_LASER / 1000;
    return ((t % L) + L) % L;
  }
  function positions(tSec, f) {
    const n = pose.nodes.length;
    const fr = tSec * pose.fps;
    const i0 = Math.floor(fr) % pose.frames.length;
    const i1 = (i0 + 1) % pose.frames.length;
    const k = fr - Math.floor(fr);
    const a = pose.frames[i0], b = pose.frames[i1];
    const out = new Array(n);
    for (let i = 0; i < n; i += 1) {
      out[i] = [f.x0 + (a[2 * i] + (b[2 * i] - a[2 * i]) * k) * f.s, f.y0 + (a[2 * i + 1] + (b[2 * i + 1] - a[2 * i + 1]) * k) * f.s];
    }
    return out;
  }
  function momentAt(tSec) {
    const m = pose.moments.find(([a, b]) => tSec >= a && tSec < b);
    return m ? m[2] : 'pace';
  }

  let graph = null;
  let order = null;   // 점이 찍히는 순서 — 위(머리)부터 아래(손)로
  const pulses = [];
  let lastPulse = 0;

  function frame(now) {
    const ms = elapsed();
    const live = ms === Infinity ? Infinity : ms;
    const f = fit();
    const t = loopT(live);
    const pos = positions(t, f);
    const n = pos.length;
    const alpha = new Array(n), link = new Array(n);
    for (let r = 0; r < n; r += 1) {
      const i = order[r];
      alpha[i] = smooth(T_DOTS + r * 5, T_DOTS + r * 5 + 160, live);
      link[i] = smooth(T_LINES + r * 6, T_LINES + r * 6 + 300, live);
    }
    const shown = T_CHIPS.map((c) => live >= c + 120);
    const m = live >= T_DONE ? momentAt(t) : null;
    if (m !== curMoment && m) {
      curMoment = m;
      chips.forEach((c) => c.classList.toggle('is-now', c.dataset.m === m));
    }
    const glow = {};
    if (m) glow[MOMENT[m].group] = 1;

    D.clear(ctx, W, H);
    leaderLines(pos, shown, f);
    D.person(ctx, graph, { pos, alpha, link, scale: Math.max(0.8, (f.s / u) * 2.6) }, glow, u);
    // 지금 장면 무리의 선을 따라 빛이 흐른다 — 「지금 읽는 중」
    if (m && !reduce && now - lastPulse > 260) {
      lastPulse = now;
      const hot = graph.edges.map((e, k) => k).filter((k) => graph.nodes[graph.edges[k][0]].group === MOMENT[m].group || graph.nodes[graph.edges[k][1]].group === MOMENT[m].group);
      if (hot.length) pulses.push({ edge: hot[Math.floor(Math.random() * hot.length)], t0: now, dur: 700, rev: Math.random() < 0.5 });
    }
    for (let k = pulses.length - 1; k >= 0; k -= 1) if (now - pulses[k].t0 > pulses[k].dur) pulses.splice(k, 1);
    if (pulses.length) D.pulses(ctx, graph, { pos, alpha, link, scale: Math.max(0.8, (f.s / u) * 2.6) }, pulses, now, u);
    laser(live);
    if (!root.classList.contains('fig-live-done')) { fig.classList.add('fig-live'); root.classList.add('fig-live-done'); }
  }

  const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
  /** 칩 왼쪽 가운데(캔버스 픽셀) */
  function chipPoint(c) {
    const fr = fig.getBoundingClientRect(), r = c.getBoundingClientRect();
    return [(r.left - fr.left) * u, (r.top + r.height / 2 - fr.top) * u];
  }
  function leaderLines(pos, shown) {
    ctx.save();
    ctx.setLineDash([3 * u, 4 * u]);
    ctx.lineWidth = 1.2 * u;
    ['claim', 'qa', 'pace'].forEach((m, k) => {
      if (!shown[k]) return;
      const c = chipOf(m);
      const a = pos[pose.anchors[MOMENT[m].anchor]];
      if (!c || !a) return;
      const p = chipPoint(c);
      const now = m === curMoment;
      ctx.strokeStyle = rgba(COL.tint, now ? 0.85 : 0.35);
      ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(p[0] - 4 * u, p[1]); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = rgba(COL.tint, now ? 1 : 0.6);
      ctx.beginPath(); ctx.arc(a[0], a[1], (now ? 4 : 3) * u, 0, Math.PI * 2); ctx.fill();
      ctx.setLineDash([3 * u, 4 * u]);
    });
    ctx.restore();
  }
  /** 삐약이 봉 끝 → 「말 빠르기」 칩의 숫자. 3.0초부터 계속 켜 둔다 */
  function laser(live) {
    if (live < T_LASER) return;
    const tip = document.querySelector('.judge-face .w-tip circle:nth-child(3)');
    const c = chipOf('pace');
    if (!tip || !c) return;
    const fr = fig.getBoundingClientRect(), tr = tip.getBoundingClientRect();
    const num = c.querySelector('.v-num') || c;
    const nr = num.getBoundingClientRect();
    const a = [(tr.left + tr.width / 2 - fr.left) * u, (tr.top + tr.height / 2 - fr.top) * u];
    const b = [(nr.left + nr.width * 0.5 - fr.left) * u, (nr.bottom + 2 - fr.top) * u];
    const k = smooth(T_LASER, T_LASER + 240, live);
    const e = [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k];
    ctx.save();
    ctx.strokeStyle = rgba(COL.laser, 0.75);
    ctx.lineWidth = 1.6 * u;
    ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(e[0], e[1]); ctx.stroke();
    const pulse = reduce ? 0.5 : 0.5 + 0.5 * Math.sin(performance.now() / 260);
    ctx.fillStyle = rgba(COL.laser, 0.25 + 0.2 * pulse);
    ctx.beginPath(); ctx.arc(e[0], e[1], (6 + 3 * pulse) * u, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = rgba(COL.laser, 1);
    ctx.beginPath(); ctx.arc(e[0], e[1], 2.6 * u, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
  }

  // ── 돌리기 · 멈추기 — 화면 밖이거나 탭이 숨으면 쉰다 ──
  let raf = 0;
  let onScreen = true;
  const loop = (now) => { raf = 0; frame(now); if (!reduce && onScreen && !document.hidden) raf = requestAnimationFrame(loop); };
  const kick = () => { if (!raf && pose) raf = requestAnimationFrame(loop); };

  async function start() {
    if (!ctx || !D) return;   // 그리기를 못 하면 정지 그림(SVG)이 그대로 남는다
    try {
      const res = await fetch(POSE_URL);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const p = await res.json();
      if (!p || p.schema !== 'chuckchuck.hi-stage-pose' || !Array.isArray(p.frames) || !p.frames.length) throw new Error('pose.json 모양이 달라요');
      pose = p;
    } catch (_) { return; /* 정지 그림이 남는다 */ }
    graph = { nodes: pose.nodes.map(([group, iris]) => ({ group, kind: iris ? 'iris' : 'node' })), edges: pose.edges };
    const still = pose.still;
    order = pose.nodes.map((_, i) => i).sort((a, b) => still[2 * a + 1] - still[2 * b + 1]);
    size();
    if ('ResizeObserver' in window) new ResizeObserver(() => { size(); kick(); }).observe(fig);
    if ('IntersectionObserver' in window) {
      new IntersectionObserver((es) => { onScreen = es.some((e) => e.isIntersecting); kick(); }).observe(fig);
    }
    document.addEventListener('visibilitychange', kick);
    if (reduce) { skipAt = -Infinity; requestAnimationFrame(frame); return; }
    kick();
  }

  // ── 스크롤하면 밝아지기 · 주 버튼 띠 · theme-color ──
  const theme = document.querySelector('meta[name="theme-color"]');
  let sQueued = false;
  function onScroll() {
    if (sQueued) return;
    sQueued = true;
    requestAnimationFrame(() => {
      sQueued = false;
      const h = stage.offsetHeight || 1;
      const p = Math.min(1, Math.max(0, (scrollY - h * 0.25) / (h * 0.6)));   // 무대 4분의 1을 지난 뒤부터 밝아진다
      stage.style.setProperty('--lift', (reduce ? 0 : p * LIFT_MAX).toFixed(3));
      const past = scrollY > h - 120;
      root.classList.toggle('past-stage', past);
      if (theme) theme.setAttribute('content', past ? '#FFFFFF' : '#066339');
    });
  }
  addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  // ── 시트가 열리면 뒤를 inert — 스크린리더 · 탭 키가 시트 밖으로 새지 않게 ──
  const sheet = $('inapp');
  if (sheet && 'MutationObserver' in window) {
    const behind = [stage, document.querySelector('main'), document.querySelector('.dock')].filter(Boolean);
    const sync = () => behind.forEach((n) => n.toggleAttribute('inert', !sheet.hidden));
    new MutationObserver(sync).observe(sheet, { attributes: true, attributeFilter: ['hidden'] });
  }

  start();
  // 근거 문장은 녹화 투어 파일에서 — 첫 그림이 끝난 뒤 받는다(투어로 넘어가면 같은 파일을 캐시로 쓴다)
  const loadTour = () => fetch(TOUR_URL).then((r) => (r.ok ? r.json() : null)).then((t) => { if (t) applyTour(t); }).catch(() => { /* HTML 값 그대로 */ });
  if ('requestIdleCallback' in window) requestIdleCallback(loadTour, { timeout: 2500 }); else setTimeout(loadTour, 1200);
})();
