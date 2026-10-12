/**
 * 가상 발표 스튜디오 — 1차 시제품 (design/SPACE.md)
 *
 * 카메라는 .studio-world 의 변환 하나다. 매 프레임 바꾸는 것은 --yaw · --dolly 와 조명 변수뿐이고,
 * 창 · 벽은 처음에 한 번 놓은 뒤 건드리지 않는다.
 * 다음 단계는 언제나 오른쪽 +90° — 각도를 누적해서 리포트 → 새 리허설도 거꾸로 돌지 않는다.
 */
(function () {
  'use strict';

  const STATIONS = [
    { key: 'upload',  name: '자료 올리기' },
    { key: 'present', name: '발표' },
    { key: 'qa',      name: '질의응답' },
    { key: 'report',  name: '리포트' },
  ];

  /* 정거장별 조명 (SPACE §3). light 는 RGB 셋 */
  const LIGHT = [
    { light: [232, 228, 220], lum: .55, cove: 1.0, pool: .55, spot: 1.0 },   // ① 아침 작업실
    { light: [201, 169, 110], lum: .22, cove: .12, pool: 1.0, spot: .62 },   // ② 무대 스포트
    { light: [217, 185, 138], lum: .38, cove: .45, pool: .75, spot: .85 },   // ③ 마주 앉은 대화
    { light: [242, 237, 228], lum: .72, cove: 1.0, pool: .5,  spot: 1.15 },  // ④ 읽는 방
  ];

  const root = document.documentElement;
  const studio = document.getElementById('studio');
  const world = document.getElementById('world');
  const live = document.getElementById('live');
  const stations = [...document.querySelectorAll('.station')];
  const walls = [...document.querySelectorAll('.room-wall')];
  const pools = [...document.querySelectorAll('.room-pool')];
  const steps = [...document.querySelectorAll('.hud .ds-step')];
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');

  const state = { at: 0, yaw: 0, busy: false };

  /* ── 시야 밖 감추기 ────────────────────────────────────────────────────
     카메라 뒤로 넘어간 면은 원근 계산에서 뒤집혀 화면을 덮는다 (10-12 헤드리스 확인). 등 뒤 벽 · 빛 웅덩이는 뺀다.
     바닥 · 천장은 css 에서 카메라를 따라 돌며 언제나 앞쪽에만 있다 — 둥근 무늬라 따라 돌아도 겉모습이 같다. */
  /* 조각마다 보이는 방향의 양 끝(from · to, 도). 두 끝이 모두 지금 방향에서 90° 안쪽이면 전부 카메라 앞이다 */
  const slices = [];
  walls.forEach((el) => {
    const c = Number(el.dataset.at) * 90;
    const left = el.classList.contains('room-wall--l');
    slices.push({ el, a: left ? c - 45 : c, b: left ? c : c + 45, limit: 89.9 });
  });
  pools.forEach((el) => { const c = Number(el.dataset.at) * 90; slices.push({ el, a: c - 32, b: c + 32, limit: 89.9 }); });
  stations.forEach((el) => { const c = Number(el.style.getPropertyValue('--at')) * 90; slices.push({ el, a: c - 24, b: c + 24, limit: 89.9 }); });

  const angleGap = (a, b) => Math.abs(((a - b) % 360 + 540) % 360 - 180);
  function cull(yaw) {
    slices.forEach((sl) => {
      const off = Math.max(angleGap(sl.a, yaw), angleGap(sl.b, yaw)) >= sl.limit;
      if (sl.off !== off) { sl.off = off; sl.el.style.visibility = off ? 'hidden' : ''; }
    });
  }

  const mod4 = (n) => ((n % 4) + 4) % 4;
  const lerp = (a, b, t) => a + (b - a) * t;
  /* cubic-bezier(.65, 0, .35, 1) 과 같은 곡선 (easeInOutCubic) */
  const ease = (t) => (t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
  const smooth = (a, b, t) => { const x = Math.min(1, Math.max(0, (t - a) / (b - a))); return x * x * (3 - 2 * x); };

  /* ── 크기 — 창은 원근 거리(P)에 놓여 멈추면 1:1 ───────────────────────── */
  function layout() {
    const vw = window.innerWidth, vh = window.innerHeight;
    const phone = vw < 720;
    const P = phone ? 760 : Math.round(Math.min(1400, Math.max(1000, vw * .85)));
    const winW = Math.round(Math.min(1080, vw * (phone ? .92 : .78)));
    const winH = Math.round(Math.min(680, vh * (phone ? .76 : .72)));
    const R = Math.round(P * 1.9);
    root.style.setProperty('--P', P + 'px');
    root.style.setProperty('--R', R + 'px');
    /* 벽 높이 — 멈춰 있을 때 바닥선 · 천장선이 화면 위아래 15~20% 자리에 보이게 (방으로 읽히게) */
    root.style.setProperty('--H', Math.round(R * (phone ? .62 : .56)) + 'px');
    root.style.setProperty('--win-w', winW + 'px');
    root.style.setProperty('--win-h', winH + 'px');
    state.P = P;
    state.phone = phone;
  }

  /* ── 한 프레임 그리기 ─────────────────────────────────────────────────── */
  function paintCamera(yaw, dolly) {
    cull(yaw);
    root.style.setProperty('--yaw', yaw.toFixed(3) + 'deg');
    root.style.setProperty('--dolly', dolly.toFixed(2) + 'px');
  }

  function paintLight(from, to, t) {
    const a = LIGHT[from], b = LIGHT[to];
    const rgb = a.light.map((v, i) => Math.round(lerp(v, b.light[i], t)));
    root.style.setProperty('--light', rgb.join(' '));
    root.style.setProperty('--lum', lerp(a.lum, b.lum, t).toFixed(3));
    root.style.setProperty('--cove', lerp(a.cove, b.cove, t).toFixed(3));
    root.style.setProperty('--pool', lerp(a.pool, b.pool, t).toFixed(3));
    root.style.setProperty('--spot', lerp(a.spot, b.spot, t).toFixed(3));
    /* 정면 벽 · 빛 웅덩이만 밝힌다 — 떠나는 쪽은 꺼지고 오는 쪽이 켜진다 */
    [walls, pools].forEach((list) => list.forEach((el) => {
      const i = Number(el.dataset.at);
      const f = i === to ? t : (i === from ? 1 - t : 0);
      el.style.setProperty('--focus', (from === to ? (i === to ? 1 : 0) : f).toFixed(3));
    }));
  }

  function paintWindows(from, to, t) {
    stations.forEach((el, i) => {
      let show = 0;
      if (from === to) show = i === to ? 1 : 0;
      else if (i === from) show = 1 - smooth(.1, .6, t);   // 두 창이 잠깐 같이 보여야 공간에서 돈다는 게 읽힌다
      else if (i === to) show = smooth(.4, .9, t);
      el.style.setProperty('--show', show.toFixed(3));
      el.classList.toggle('is-visible', show > 0.001);
    });
  }

  /* ── 도착 처리 — 접근성 · 기록 ─────────────────────────────────────────── */
  function settle(to, { push = true, focus = true } = {}) {
    state.at = to;
    state.busy = false;
    studio.classList.remove('is-moving');
    stations.forEach((el, i) => {
      const here = i === to;
      el.toggleAttribute('inert', !here);
      el.setAttribute('aria-hidden', here ? 'false' : 'true');
    });
    steps.forEach((b, i) => {
      if (i === to) b.setAttribute('aria-current', 'step'); else b.removeAttribute('aria-current');
    });
    const name = STATIONS[to].name;
    document.title = `척척발표 — ${name} (시제품)`;
    if (push && location.hash.slice(1) !== STATIONS[to].key) history.pushState({ at: to }, '', '#' + STATIONS[to].key);
    if (focus) {
      const h = stations[to].querySelector('[id^="t-"]');
      if (h) h.focus({ preventScroll: true });
      live.textContent = `${to + 1}단계 ${name}(으)로 왔어요`;
    }
  }

  /* ── 이동 ──────────────────────────────────────────────────────────────── */
  /** to 정거장으로. dir: +1(오른쪽) · -1(왼쪽) · 0(최단). 두 칸이면 오른쪽으로 180° */
  function go(to, { dir = 0, push = true } = {}) {
    to = mod4(to);
    if (state.busy || to === state.at) return;
    const from = state.at;
    let turns = dir || mod4(to - from);
    if (!dir) turns = turns === 3 ? -1 : turns;       // 1 → +90 · 2 → +180 · 3 → −90
    const y0 = state.yaw, y1 = state.yaw + turns * 90;
    state.yaw = y1;

    if (reduce.matches) {          // 움직임 줄이기 — 회전 없이 0.2s 겹쳐 바뀌기
      state.busy = true;
      paintCamera(y1, 0);
      paintLight(to, to, 1);
      crossfade(from, to, 200, () => settle(to, { push }));
      return;
    }

    state.busy = true;
    studio.classList.add('is-moving');
    const dur = (state.phone ? 900 : 1100) * (Math.abs(turns) === 2 ? 1.35 : 1);
    const back = state.P * .16 * (Math.abs(turns) === 2 ? 1.25 : 1);   // 한 걸음 물러섬
    const t0 = performance.now();
    function frame(now) {
      const t = Math.min(1, (now - t0) / dur);
      const e = ease(t);
      paintCamera(lerp(y0, y1, e), Math.sin(Math.PI * t) * back);
      paintLight(from, to, e);
      paintWindows(from, to, t);
      if (t < 1) requestAnimationFrame(frame);
      else { paintCamera(y1, 0); paintWindows(to, to, 1); paintLight(to, to, 1); settle(to, { push }); }
    }
    requestAnimationFrame(frame);
  }

  function crossfade(from, to, ms, done) {
    const t0 = performance.now();
    function frame(now) {
      const t = Math.min(1, (now - t0) / ms);
      stations.forEach((el, i) => {
        const show = i === to ? t : (i === from ? 1 - t : 0);
        el.style.setProperty('--show', show.toFixed(3));
        el.classList.toggle('is-visible', show > 0.001);
      });
      if (t < 1) requestAnimationFrame(frame); else done();
    }
    requestAnimationFrame(frame);
  }

  /* ── 연결 ──────────────────────────────────────────────────────────────── */
  document.addEventListener('click', (e) => {
    const next = e.target.closest('[data-next]');
    if (next) { go(state.at + 1, { dir: +1 }); return; }
    const step = e.target.closest('[data-go]');
    if (step) go(Number(step.dataset.go));
  });
  window.addEventListener('popstate', (e) => {
    const at = e.state && Number.isInteger(e.state.at) ? e.state.at : indexOfHash();
    go(at, { push: false });
  });
  window.addEventListener('resize', layout);

  function indexOfHash() {
    const i = STATIONS.findIndex((s) => s.key === location.hash.slice(1));
    return i < 0 ? 0 : i;
  }

  /* 실험실 · 헤드리스용 — 전환 중간을 멈춰 찍는다 (?freeze=0.5 처럼) */
  window.studioDebug = {
    go,
    pose(from, to, t, turns = 1) {
      const y0 = from * 90;
      paintCamera(lerp(y0, y0 + turns * 90, ease(t)), Math.sin(Math.PI * t) * state.P * .16);
      paintLight(from, mod4(to), ease(t));
      paintWindows(from, mod4(to), t);
    },
    get state() { return { ...state }; },
  };

  /* ── 시작 ──────────────────────────────────────────────────────────────── */
  layout();
  const first = indexOfHash();
  state.at = first;
  state.yaw = first * 90;
  paintCamera(state.yaw, 0);
  paintLight(first, first, 1);
  paintWindows(first, first, 1);
  history.replaceState({ at: first }, '', '#' + STATIONS[first].key);
  settle(first, { push: false, focus: false });
})();
