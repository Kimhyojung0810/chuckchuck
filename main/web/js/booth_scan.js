/**
 * 부스 「사람 그래프」 스캔 화면(/booth/scan) — 카메라 · 워커 · 마이크 크기 · 그리기 고리 (2026-10-12).
 *
 * 결선 부스(11/3~5) 노트북·모니터에 띄워 두는 연출 화면. 지나가는 사람이 자기 얼굴·어깨가 점과 선으로 읽히는 것을 본다.
 * 점수·리포트·발표·Q&A 흐름에는 아무것도 넘기지 않는다. 판단은 js/booth_scan_logic.js, 칠하기는 js/booth_scan_draw.js.
 *
 * 영상 프레임은 워커(js/booth_scan_worker.js)로만 가고 고른 점의 좌표만 돌아온다. 소리는 크기(RMS) 하나만 쓴다. 녹화·녹음 없음,
 * 서버로 보내는 것 없음. 마이크를 막으면 「목소리·쉼」 만 흐리게 남고, 카메라·모델이 안 되면 차분한 안내 + 떠다니는 점은 그대로.
 * 팀 모드에서만 열린다 — 브리지가 /booth/scan 을 팀 쿠키(또는 DEMO_DEV_ROUTES)일 때만 준다.
 */
(function () {
  'use strict';
  const L = window.BoothScanLogic, D = window.BoothScanDraw;
  if (!L || !D) return;

  const GRAPH = L.buildGraph();
  /** 추론 간격 하한(ms) — ~14fps. 그리기는 화면 주사율로 따로 돈다 */
  const INFER_MIN_MS = 70;
  /** 워커에 넘기는 프레임 폭 — 정규 좌표라 줄여도 점 자리는 같고, 약한 노트북에서 추론이 빨라진다 */
  const INFER_W = 640;
  const PARTICLES = 84;
  const WORKER_URL = '/js/booth_scan_worker.js?v=bs1';
  const VENDOR_BASE = '/js/vendor/mediapipe/';
  const RETRY_CAM_MS = 8000, RETRY_MODEL_MS = 20000, STUCK_MS = 4000;

  const $ = (id) => document.getElementById(id);
  const el = { video: $('bsVideo'), canvas: $('bsCanvas'), prompt: $('bsPrompt'), hint: $('bsHint'), list: $('bsSignals') };
  const ctx = el.canvas.getContext('2d');
  const rng = L.rng32(20261012);
  const query = new URLSearchParams(location.search);

  const S = {
    cam: 'boot', model: 'boot', W: 0, H: 0, dpr: 1, shift: 0,
    tracks: [], nextId: 1,
    particles: L.makeParticles(PARTICLES, rng), idleAlpha: 1,
    signals: L.makeSignals(), sig: null,
    audio: null, rms: null,
    worker: null, busy: false, sentAt: 0, seq: 0, src: '', delegate: '',
    inferMs: 0, inferFps: 0, lastResult: 0, lastFrame: 0,
  };
  const items = {};

  // ── 「읽는 것」 다섯 줄 ─────────────────────────────────────────────────────────────────
  function renderSignals() {
    el.list.innerHTML = '';
    L.SIGNALS.forEach((s) => {
      const li = document.createElement('li');
      li.className = 'bs-sig';
      li.dataset.sig = s.id;
      li.innerHTML = `<i class="bs-dot" aria-hidden="true"></i><span class="bs-sig-text"><b></b><small></small></span>`;
      li.querySelector('b').textContent = s.label;
      li.querySelector('small').textContent = s.sub;
      el.list.appendChild(li);
      items[s.id] = { li, on: false, lv: -1 };
    });
  }
  function paintSignals(sig) {
    L.SIGNALS.forEach(({ id }) => {
      const it = items[id], s = sig[id];
      const lv = Math.round(s.level * 20) / 20;
      if (lv !== it.lv) { it.li.style.setProperty('--lv', String(lv)); it.lv = lv; }
      if (s.on !== it.on) { it.li.toggleAttribute('data-on', s.on); it.on = s.on; }
      if (s.fired) { it.li.classList.remove('bs-fire'); void it.li.offsetWidth; it.li.classList.add('bs-fire'); }
    });
    items.voice.li.toggleAttribute('data-mic-off', !sig.voice.mic);
  }

  // ── 가운데 안내 ─────────────────────────────────────────────────────────────────────────
  const MESSAGES = {
    loading: ['읽을 준비를 하고 있어요', '처음 한 번은 조금 걸려요'],
    idle: ['앞에 서 보세요', '카메라 앞에 서면 얼굴과 어깨를 점과 선으로 읽어요'],
    camDenied: ['카메라를 켜면 시작해요', '주소창 왼쪽에서 카메라를 허용해 주세요'],
    camMissing: ['카메라를 찾고 있어요', '카메라를 연결하면 바로 시작해요'],
    model: ['사람을 읽는 모델을 다시 불러오고 있어요', '인터넷이 이어지면 저절로 시작해요'],
  };
  let shownMsg = '';
  function message() {
    // 흩어지는 점이 다 사라진 뒤에 「앞에 서 보세요」 — 흩어지는 그래프 위에 글자가 겹치지 않게
    const live = S.tracks.length > 0;
    let key = '';
    if (S.cam === 'denied') key = 'camDenied';
    else if (S.cam === 'missing') key = 'camMissing';
    else if (S.model === 'failed') key = 'model';
    else if (S.cam !== 'on' || S.model !== 'ready') key = 'loading';
    else if (!live) key = 'idle';
    if (key === shownMsg) return;
    shownMsg = key;
    document.body.dataset.msg = key || 'none';
    if (key) { el.prompt.textContent = MESSAGES[key][0]; el.hint.textContent = MESSAGES[key][1]; }
  }

  // ── 카메라 · 마이크 ─────────────────────────────────────────────────────────────────────
  async function startCamera() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' }, audio: false,
      });
      el.video.srcObject = stream;
      await el.video.play().catch(() => {});
      S.cam = 'on';
      stream.getVideoTracks().forEach((tr) => tr.addEventListener('ended', () => { S.cam = 'missing'; setTimeout(startCamera, 1000); }));
    } catch (e) {
      const name = (e && e.name) || '';
      S.cam = name === 'NotAllowedError' || name === 'SecurityError' ? 'denied' : 'missing';
      // 막힌 것은 사람이 허용해야 풀린다 — 그래도 가끔 다시 묻는다(권한을 바꾼 뒤 새로 고치지 않아도 되게). 없는 카메라는 꽂히길 기다린다
      setTimeout(startCamera, S.cam === 'denied' ? RETRY_CAM_MS * 2 : RETRY_CAM_MS);
    }
  }

  /** 마이크는 크기 하나만 — AnalyserNode 의 파형에서 RMS. 녹음·전송 없음. 막히면 null 로 남는다 */
  async function startMic() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false }, video: false,
      });
      const ac = new (window.AudioContext || window.webkitAudioContext)();
      const an = ac.createAnalyser();
      an.fftSize = 1024;
      ac.createMediaStreamSource(stream).connect(an);
      S.audio = { ac, an, buf: new Float32Array(an.fftSize) };
      const wake = () => { if (ac.state === 'suspended') ac.resume().catch(() => {}); };
      wake();
      ['pointerdown', 'keydown'].forEach((ev) => window.addEventListener(ev, wake, { passive: true }));
    } catch (_) {
      S.audio = null;  // 「목소리·쉼」 만 흐리게 — 나머지는 그대로
    }
  }
  function readRms() {
    const a = S.audio;
    if (!a || a.ac.state !== 'running') return null;
    a.an.getFloatTimeDomainData(a.buf);
    let sum = 0;
    for (let i = 0; i < a.buf.length; i += 1) sum += a.buf[i] * a.buf[i];
    return Math.sqrt(sum / a.buf.length);
  }

  // ── 워커 ───────────────────────────────────────────────────────────────────────────────
  function startWorker() {
    try {
      S.worker = new Worker(WORKER_URL, { type: 'module' });
    } catch (_) {
      return modelFailed();
    }
    S.model = 'loading';
    S.busy = false;
    S.worker.onmessage = (e) => onWorker(e.data || {});
    S.worker.onerror = () => modelFailed();
    S.worker.postMessage({
      type: 'init', base: VENDOR_BASE, pickFace: L.PICK_FACE, pickPose: L.PICK_POSE,
      people: L.MAX_PEOPLE, delegate: query.has('cpu') ? 'CPU' : '',
    });
  }
  function modelFailed() {
    S.model = 'failed';
    try { if (S.worker) S.worker.terminate(); } catch (_) { /* 이미 끝남 */ }
    S.worker = null;
    setTimeout(startWorker, RETRY_MODEL_MS);
  }
  function onWorker(m) {
    if (m.type === 'ready') { S.model = 'ready'; S.src = m.src; S.delegate = m.delegate; return; }
    if (m.type === 'failed') return modelFailed();
    if (m.type !== 'result') return;
    S.busy = false;
    if (m.skipped || m.error) return;
    const now = performance.now();
    if (S.lastResult) S.inferFps += ((1000 / Math.max(1, now - S.lastResult)) - S.inferFps) * 0.2;
    S.lastResult = now;
    S.inferMs = (m.ms.face || 0) + (m.ms.pose || 0);
    onPeople(m.faces || [], m.poses || [], now);
  }
  async function sendFrame(now) {
    const v = el.video;
    if (!S.worker || S.model !== 'ready' || S.cam !== 'on' || v.readyState < 2 || !v.videoWidth) return;
    if (S.busy && now - S.sentAt < STUCK_MS) return;
    if (now - S.sentAt < INFER_MIN_MS) return;
    S.busy = true;
    S.sentAt = now;
    try {
      const h = Math.round(INFER_W * v.videoHeight / v.videoWidth);
      const bitmap = await createImageBitmap(v, { resizeWidth: INFER_W, resizeHeight: h, resizeQuality: 'low' });
      S.seq += 1;
      S.worker.postMessage({ type: 'frame', bitmap, t: now, seq: S.seq }, [bitmap]);
    } catch (_) {
      S.busy = false;
    }
  }

  // ── 사람 따라가기 ───────────────────────────────────────────────────────────────────────
  const aspect = () => (el.video.videoWidth && el.video.videoHeight ? el.video.videoWidth / el.video.videoHeight : 16 / 9);

  function newTrack(person, now) {
    const n = GRAPH.nodes.length;
    // 모일 때 출발점 — 지금 떠다니는 점들. 노드마다 다른 점에서 날아온다
    const offset = Math.floor(rng() * PARTICLES);
    const start = GRAPH.nodes.map((_, i) => {
      const p = S.particles[(offset + i * 7) % PARTICLES];
      return [p.x * S.W, p.y * S.H];
    });
    return {
      id: S.nextId++, born: now, lastSeen: now, missed: 0, lostAt: null, center: person.center, size: person.size,
      filters: GRAPH.nodes.map(() => [L.makeOneEuro(), L.makeOneEuro()]),
      target: new Array(n).fill(null), want: new Array(n).fill(0),
      disp: new Array(n).fill(null), alpha: new Array(n).fill(0), start,
      scatterFrom: null, scatterVel: null, prevPose: null, prevT: 0,
      sig: { gaze: null, head: null, tilt: null, hand: null }, pulses: [],
    };
  }
  function feedTrack(tr, person, now) {
    const raw = L.nodeTargets(GRAPH, person);
    raw.forEach((p, i) => {
      if (p && isFinite(p[0]) && isFinite(p[1])) {
        tr.target[i] = [tr.filters[i][0].filter(p[0], now), tr.filters[i][1].filter(p[1], now)];
        tr.want[i] = 1;
      } else {
        tr.want[i] = 0;  // 안 보이는 팔 — 자리는 두고 옅어진다
        tr.filters[i][0].reset(); tr.filters[i][1].reset();
      }
    });
    const dt = tr.prevT ? (now - tr.prevT) / 1000 : 0;
    tr.sig = {
      gaze: L.gazeDir(person.face), head: L.headPose(person.face),
      tilt: person.pose ? L.shoulderTilt(person.pose, aspect()) : null,
      hand: L.handSpeed(tr.prevPose, person.pose, dt, aspect()),
    };
    tr.prevPose = person.pose;
    tr.prevT = now;
    tr.center = person.center;
    tr.size = person.size;
    tr.lastSeen = now;
    tr.missed = 0;
  }
  function onPeople(faces, poses, now) {
    const people = L.pairPeople(faces, poses, aspect());
    const live = S.tracks.filter((t) => t.lostAt == null);
    const m = L.matchTracks(live, people, aspect());
    m.matched.forEach(([ti, pj]) => feedTrack(live[ti], people[pj], now));
    m.missing.forEach((ti) => { live[ti].missed += 1; });
    m.fresh.forEach((pj) => {
      if (live.length >= L.MAX_PEOPLE) return;
      const tr = newTrack(people[pj], now);
      feedTrack(tr, people[pj], now);
      S.tracks.push(tr);
    });
  }

  // ── 그리기 고리 ─────────────────────────────────────────────────────────────────────────
  /**
   * 무대(캠) 가운데를 오른쪽 「읽는 것」 기둥 왼쪽 빈 곳의 가운데로 민다 (CSS px, 0 이하). 화면 가운데에 깔면 1280 노트북에서
   * 오른쪽에 선 사람의 얼굴 그래프가 판 밑에 통째로 가렸다 (10-12 알려진 문제). 민 만큼 왼쪽 끝이 잘리고 오른쪽 끝은 기둥 밑으로 간다 —
   * 가리는 폭이 양쪽으로 반씩 나뉘어 가운데 선 사람은 늘 빈 곳 가운데에 온다. 세로 화면 · 기둥이 안 보이면 0.
   */
  function stageShift() {
    const side = document.querySelector('.bs-side');
    if (!side || window.innerWidth <= window.innerHeight) return 0;
    const left = side.getBoundingClientRect().left;
    if (!(left > 0 && left < window.innerWidth)) return 0;
    return Math.min(0, Math.round(left / 2 - window.innerWidth / 2));
  }

  function resize() {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const W = Math.round(window.innerWidth * dpr), H = Math.round(window.innerHeight * dpr);
    const shift = stageShift();
    if (shift !== S.shift) { S.shift = shift; document.body.style.setProperty('--stage-x', shift + 'px'); }
    if (W === S.W && H === S.H) return;
    el.canvas.width = W; el.canvas.height = H;
    S.W = W; S.H = H; S.dpr = dpr;
  }

  /** 노드 하나의 이번 프레임 자리 · 진하기 (단계별) */
  function placeTrack(tr, phase, map, now, dt) {
    const n = GRAPH.nodes.length;
    const pos = new Array(n).fill(null), alpha = new Array(n).fill(0), link = new Array(n).fill(1);
    if (phase === 'lost' && tr.lostAt == null) {
      tr.lostAt = now;
      tr.scatterFrom = tr.disp.map((p) => (p ? p.slice() : null));
      tr.scatterVel = L.scatterVelocities(tr.scatterFrom, rng).map((v) => [v[0] * S.dpr, v[1] * S.dpr]);
    }
    for (let i = 0; i < n; i += 1) {
      if (tr.lostAt != null) {
        if (!tr.scatterFrom[i]) continue;
        const sc = L.scatterAt(tr.scatterFrom[i], tr.scatterVel[i], now - tr.lostAt);
        pos[i] = sc.pos; alpha[i] = sc.alpha * tr.alpha[i];
        link[i] = sc.alpha * sc.alpha;  // 선이 먼저 끊어지고 점이 흩어진다
        continue;
      }
      const t = tr.target[i];
      if (t) {
        const X = map.x(t[0]), Y = map.y(t[1]);
        tr.disp[i] = tr.disp[i] ? [L.follow(tr.disp[i][0], X, dt, 22), L.follow(tr.disp[i][1], Y, dt, 22)] : [X, Y];
      }
      tr.alpha[i] = L.follow(tr.alpha[i], tr.want[i], dt, 7);
      if (!tr.disp[i]) continue;
      if (phase === 'assemble') {
        const p = L.assembleProgress(now - tr.born, i, n);
        pos[i] = L.lerp2(tr.start[i], tr.disp[i], p);
        alpha[i] = Math.min(1, 0.35 + p) * Math.max(tr.alpha[i], tr.want[i] ? 1 : 0);
        link[i] = p * p * p;
      } else {
        pos[i] = tr.disp[i];
        alpha[i] = tr.alpha[i];
      }
    }
    // 얼굴 폭(화면 CSS px) 240 을 1 로 — 멀리 선 사람은 점도 작게, 가까이 오면 크게
    const facePx = (tr.size * map.dh) / S.dpr;
    return { pos, alpha, link, scale: Math.max(0.8, Math.min(1.35, facePx / 240)) };
  }

  function groupGlow(sig) {
    return { gaze: sig.gaze.level, head: sig.head.level, shoulder: sig.shoulder.level, hand: sig.hand.level, voice: sig.voice.level };
  }

  function frame(tMs) {
    const now = performance.now();
    const dt = S.lastFrame ? Math.min(0.1, (now - S.lastFrame) / 1000) : 0;
    S.lastFrame = now;
    resize();
    sendFrame(now);
    const v = el.video;
    const map = L.coverMap(v.videoWidth || 16, v.videoHeight || 9, S.W, S.H, true, S.shift * S.dpr);
    S.particles = L.driftParticles(S.particles, dt, now / 1000);
    // 카메라가 빠지면 결과가 더 안 온다 — 남은 그래프를 놓친 것으로 돌려 흩어 보낸다
    if (S.cam !== 'on') S.tracks.forEach((tr) => { tr.missed = L.MISS_MAX; });
    S.tracks.forEach((tr) => { tr.phase = L.phaseOf(tr, now); });
    S.tracks = S.tracks.filter((tr) => tr.phase !== 'gone');
    const live = S.tracks.filter((tr) => tr.lostAt == null && tr.phase !== 'lost').sort((a, b) => b.size - a.size);
    S.sig = S.signals.update(live.map((tr) => tr.sig), readRms(), now);
    paintSignals(S.sig);
    const glow = groupGlow(S.sig);
    const on = { gaze: S.sig.gaze.on, head: S.sig.head.on, shoulder: S.sig.shoulder.on, hand: S.sig.hand.on, voice: S.sig.voice.on };
    S.idleAlpha = L.follow(S.idleAlpha, live.length ? 0.1 : 1, dt, live.length ? 6 : 1.6);
    D.clear(ctx, S.W, S.H);
    D.idle(ctx, S.particles, S.W, S.H, S.idleAlpha, S.dpr);
    S.tracks.forEach((tr) => {
      const view = placeTrack(tr, tr.phase, map, now, dt);
      if (tr.lostAt == null && tr.phase === 'track') tr.pulses = tr.pulses.concat(L.spawnPulses(GRAPH, on, dt, now, rng, 8));
      tr.pulses = L.livePulses(tr.pulses, now);
      D.person(ctx, GRAPH, view, glow, S.dpr);
      D.pulses(ctx, GRAPH, view, tr.pulses, now, S.dpr);
      tr.view = view;
    });
    message();
    document.body.dataset.people = String(live.length);
    requestAnimationFrame(frame);
  }

  // ── 부스 노트북 편의 — 화면 꺼짐 막기 · 전체 화면(f · 두 번 누르기) · 가만히 있으면 커서 숨김 ─────────────
  let wakeLock = null;
  async function keepAwake() {
    try { if ('wakeLock' in navigator && document.visibilityState === 'visible') wakeLock = await navigator.wakeLock.request('screen'); } catch (_) { /* 안 되면 그만 */ }
  }
  function toggleFullscreen() {
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else document.documentElement.requestFullscreen().catch(() => {});
  }
  let cursorTimer = 0;
  function wakeCursor() {
    document.body.classList.remove('bs-nocursor');
    clearTimeout(cursorTimer);
    cursorTimer = setTimeout(() => document.body.classList.add('bs-nocursor'), 3000);
  }

  /** 헤드리스 실험실(etc/labs/booth_scan/run.py)이 읽는 상태 — 숫자는 화면에 내지 않는다, 여기서만 */
  window.__boothScan = () => ({
    cam: S.cam, model: S.model, src: S.src, delegate: S.delegate, msg: shownMsg,
    people: S.tracks.filter((t) => t.lostAt == null).length,
    phases: S.tracks.map((t) => t.phase), inferFps: Math.round(S.inferFps * 10) / 10, inferMs: Math.round(S.inferMs),
    signals: S.sig ? Object.fromEntries(Object.entries(S.sig).map(([k, v]) => [k, { on: v.on, level: Math.round(v.level * 100) / 100 }])) : null,
    nodes: S.tracks[0] && S.tracks[0].view ? S.tracks[0].view.pos.filter(Boolean).length : 0,
    face: S.tracks[0] && S.tracks[0].view ? box(S.tracks[0].view.pos.slice(0, 18)) : null,
  });
  function box(pts) {
    const p = pts.filter(Boolean);
    if (!p.length) return null;
    const xs = p.map((q) => q[0] / S.dpr), ys = p.map((q) => q[1] / S.dpr);
    return { x0: Math.round(Math.min(...xs)), y0: Math.round(Math.min(...ys)), x1: Math.round(Math.max(...xs)), y1: Math.round(Math.max(...ys)) };
  }

  function boot() {
    renderSignals();
    resize();
    message();
    window.addEventListener('resize', resize);
    window.addEventListener('keydown', (e) => { if (e.key === 'f' || e.key === 'F') toggleFullscreen(); });
    window.addEventListener('dblclick', toggleFullscreen);
    window.addEventListener('pointermove', wakeCursor, { passive: true });
    document.addEventListener('visibilitychange', keepAwake);
    keepAwake();
    wakeCursor();
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) S.cam = 'denied';
    else startCamera().then(startMic);
    startWorker();
    requestAnimationFrame(frame);
  }
  boot();
})();
