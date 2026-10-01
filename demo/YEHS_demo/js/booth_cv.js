/**
 * 부스 Q&A 무대(#/booth/qa · 주소창 /booth/qa)의 카메라 판단 — OpenCV.js 에서 두 가지만 빌려 쓴다.
 *
 *  1. 얼굴 찾기 — Haar 정면 얼굴 분류기(CascadeClassifier). 정면에 가까운 얼굴만 잡히는 성질을
 *     그대로 쓴다: 「정면으로 잡힌 시간」은 이 분류기가 얼굴을 찾은 프레임의 비율이라 지어낸 값이 아니다.
 *  2. 움직임 — 작게 줄인 흑백 프레임 둘의 차이(absdiff → threshold → countNonZero).
 *     얼굴이 옆을 봐도 사람이 앞에 서 있는지는 이것으로 안다.
 *
 * 쓰는 곳: 시작 화면에서 사람이 다가오면 인사하기 · 질문 무대에서 구도 안내 한 줄과 얼굴 테두리 ·
 * 마무리 카드의 「정면으로 잡힌 시간」. 판단은 이 컴퓨터 브라우저 안에서만 한다 — 프레임을 서버로 보내지 않는다.
 *
 * OpenCV.js(약 10MB)는 이 화면에 처음 들어올 때만, **워커(booth_cv_worker.js) 안에서** 받는다 — 메인 스레드에서
 * 올리면 화면이 2분 넘게 얼었다. 못 받으면 카메라 판단 없이 그대로 돈다 —
 * 체험의 주인공은 질문이고, 카메라 판단은 얹는 층이다 (CLAUDE.md §3-4).
 *
 * 위쪽 절반(BoothCvLogic)은 순수 함수라 노드 스모크(tests/js/booth_qa.smoke.mjs)가 시험한다.
 */
(function (root) {
  'use strict';

  const CV_CFG = {
    presentHoldMs: 1500,     // 얼굴을 마지막으로 본 뒤 이만큼은 「앞에 있다」로 친다
    absentMs: 4000,          // 얼굴도 움직임도 이만큼 없으면 「떠났다」
    motionOn: 0.02,          // 줄인 프레임에서 바뀐 화소 비율 — 사람이 걸어 들어오면 넘는다
    motionSustainMs: 600,    // 움직임이 이만큼 이어져야 사람으로 친다 (조명 깜빡임은 한 프레임이다)
    hintHoldMs: 900,         // 구도 안내는 이만큼 같은 말이 이어질 때만 띄운다 — 깜빡이면 거슬린다
    lostMs: 1200,            // 얼굴을 이만큼 못 찾아야 「화면 밖」이라고 말한다
    edge: 0.24,              // 얼굴 가운데가 화면 가장자리 이 비율 안이면 「가운데로」
    small: 0.13,             // 얼굴 폭이 화면 폭의 이 비율보다 작으면 「가까이」
    big: 0.55,               // 이보다 크면 「뒤로」
    minGazeSamples: 20,      // 정면 비율은 약 4초 이상 쟀을 때만 보여 준다
  };

  const HINT_COPY = {
    lost: '얼굴이 화면 밖에 있어요',
    center: '화면 가운데로 조금 와 주세요',
    near: '조금 더 가까이 와 주세요',
    far: '조금만 뒤로 가 주세요',
  };

  /* ─── 순수 판단 ─────────────────────────────────────────────────────────── */

  function createCvState(now = 0) {
    return {
      present: false,
      faceAt: -Infinity,       // 마지막으로 얼굴을 본 시각
      motionSince: -1,         // 움직임이 문턱을 넘기 시작한 시각 (-1 이면 지금 조용하다)
      activeAt: -Infinity,     // 마지막으로 사람 기척(얼굴 또는 이어진 움직임)이 있던 시각
      face: null,
      hint: '',
      pendingHint: '',
      pendingAt: now,
      arrived: false,          // 이번 걸음에서 막 「앞에 섰다」가 됐는가 (한 번만 참)
      left: false,             // 이번 걸음에서 막 「떠났다」가 됐는가
    };
  }

  /** 얼굴 하나를 보고 구도 안내 종류를 고른다. 얼굴이 없으면 lost — 이어진 시간은 호출자가 본다 */
  function framingKind(face, cfg = CV_CFG) {
    if (!face) return 'lost';
    if (face.cx < cfg.edge || face.cx > 1 - cfg.edge) return 'center';
    if (face.w < cfg.small) return 'near';
    if (face.w > cfg.big) return 'far';
    return '';
  }

  /**
   * 한 프레임을 반영한 **새** 상태를 돌려준다 (넘겨받은 상태는 고치지 않는다).
   * sample: { face: {cx, cy, w, h} (0~1, 화면 비율) | null, motion: 0~1 }
   */
  function stepCvState(prev, sample, now, cfg = CV_CFG) {
    const face = (sample && sample.face) || null;
    const motion = Number(sample && sample.motion) || 0;
    const faceAt = face ? now : prev.faceAt;
    const motionSince = motion >= cfg.motionOn ? (prev.motionSince >= 0 ? prev.motionSince : now) : -1;
    const moving = motionSince >= 0 && now - motionSince >= cfg.motionSustainMs;
    const recentFace = now - faceAt <= cfg.presentHoldMs;
    // 기척 시각은 **지금** 얼굴이나 이어진 움직임이 있을 때만 민다 — recentFace 로 밀면 떠난 뒤에도 presentHoldMs 만큼 더 머문 것으로 센다
    const activeAt = face || moving ? now : prev.activeAt;
    const present = prev.present ? now - activeAt < cfg.absentMs : (recentFace || moving);

    /* Haar 는 멀쩡한 얼굴도 몇 프레임씩 놓친다. 잠깐 놓친 동안은 하던 판단을 그대로 들고 간다 —
       안 그러면 「가운데로 와 주세요」 가 한 프레임마다 켜졌다 꺼진다 */
    let kind;
    if (!present) kind = '';
    else if (!face) kind = now - faceAt >= cfg.lostMs ? 'lost' : prev.pendingHint;
    else kind = framingKind(face, cfg);
    const same = kind === prev.pendingHint;
    const pendingHint = kind;
    const pendingAt = same ? prev.pendingAt : now;
    const hint = !kind ? '' : (now - pendingAt >= cfg.hintHoldMs ? HINT_COPY[kind] : (same ? prev.hint : ''));

    return {
      present, faceAt, motionSince, activeAt,
      face, hint, pendingHint, pendingAt,
      arrived: present && !prev.present,
      left: !present && prev.present,
    };
  }

  function createGazeStats() {
    return { samples: 0, frontal: 0 };
  }

  function addGazeSample(stats, hasFace) {
    return { samples: stats.samples + 1, frontal: stats.frontal + (hasFace ? 1 : 0) };
  }

  /** 정면으로 잡힌 비율(0~100). 잰 시간이 짧으면 null — 두 프레임으로 퍼센트를 말하지 않는다 */
  function gazePercent(stats, cfg = CV_CFG) {
    if (!stats || stats.samples < cfg.minGazeSamples) return null;
    return Math.round((stats.frontal / stats.samples) * 100);
  }

  /** 여러 얼굴 중 가장 큰 것 (부스 뒤로 지나가는 사람보다 앞에 선 사람) */
  function pickLargestFace(rects, frameW, frameH) {
    let best = null;
    (rects || []).forEach((r) => {
      if (!best || r.width * r.height > best.width * best.height) best = r;
    });
    if (!best || !frameW || !frameH) return null;
    return {
      cx: (best.x + best.width / 2) / frameW,
      cy: (best.y + best.height / 2) / frameH,
      w: best.width / frameW,
      h: best.height / frameH,
    };
  }

  root.BoothCvLogic = {
    CV_CFG, HINT_COPY,
    createCvState, stepCvState, framingKind,
    createGazeStats, addGazeSample, gazePercent, pickLargestFace,
  };

  /* ─── 브라우저 런타임 ───────────────────────────────────────────────────── */

  // 워커(booth_cv_worker.js)가 importScripts 로 이 파일을 다시 읽는다 — 거기엔 document 가 없어 여기서 멈춘다
  if (!root.document) return;

  /* OpenCV 는 워커에서 돈다 (booth_cv_worker.js 머리말). 여기서는 video 를 320px 로 줄여 보내고 결과만 받는다.
     로컬 사본이 있으면 먼저 쓴다 — 부스 인터넷이 느릴 때를 대비해 js/vendor/ 에 받아 둘 수 있다(git 에는 안 올린다).
     없으면 CDN. index.html 이 pdf.js 를 받는 곳과 같은 jsdelivr 다. */
  // ⚠️ 워커와 워커가 다시 읽는 이 파일의 ?v= 는 여기서 손으로 올린다 — scripts/chk bump 는 index.html 만 본다 (CLAUDE.md §2 캐시 함정)
  const WORKER_SRC = 'js/booth_cv_worker.js?v=bq1';
  const LOGIC_SRC = 'js/booth_cv.js?v=bq1';
  const OPENCV_SRCS = [
    'js/vendor/opencv.js',
    'https://cdn.jsdelivr.net/npm/@techstark/opencv-js@4.10.0-release.1/dist/opencv.js',
  ];
  const CASCADE_SRCS = [
    'js/vendor/haarcascade_frontalface_default.xml',
    'https://cdn.jsdelivr.net/gh/opencv/opencv@4.10.0/data/haarcascades/haarcascade_frontalface_default.xml',
  ];
  const LOAD_TIMEOUT_MS = 45000;
  const FRAME_W = 320;          // 얼굴 찾기용 축소 폭. 부스 거리(1~2m)의 얼굴은 이 폭에서 40px 안팎이다
  const TICK_MS = 180;          // 약 5.5fps — 받아쓰기·판정과 같이 돌아도 통화가 안 끊기는 선
  const SLOW_TICK_MS = 400;     // 한 프레임이 오래 걸리는 노트북에서는 느리게
  const STALL_MS = 3000;        // 워커가 이만큼 답이 없으면 그 장은 버린다
  const STALL_RESTART = 3;      // 연달아 이만큼 멈추면 워커를 새로 띄운다 (하루 종일 도는 부스 — 조용히 멈추지 않게)
  const RETRY_AFTER_MS = 60000; // 불러오기에 실패하면 이만큼 지나야 다시 받는다 (방문객마다 10MB 를 다시 받지 않게)
  const abs = (u) => new URL(u, root.location.href).href;

  const rt = {
    status: 'idle',             // idle | loading | ready | failed
    error: '',
    loading: null,
    worker: null,
    busy: false,                // 워커가 프레임 하나를 보는 중 — 끝나야 다음 것을 보낸다
    video: null,
    timer: 0,
    listeners: new Set(),
    state: createCvState(0),
    gaze: null,                 // 재는 중이면 { samples, frontal }
    canvas: null,
    lastCostMs: 0,
    tickMs: TICK_MS,            // 화면마다 다르다 — 사람이 오는지만 보는 화면은 느리게 (watch 의 tickMs)
    sentAt: 0,
    stalls: 0,
    failedAt: 0,
  };

  function onWorkerMessage(e) {
    const msg = e.data || {};
    if (msg.type === 'result') {
      rt.busy = false;
      rt.stalls = 0;
      rt.lastCostMs = Number(msg.ms) || 0;
      if (msg.error) console.warn('[chuckchuck] booth cv frame', msg.error);
      if (!rt.video) return;
      rt.state = stepCvState(rt.state, { face: msg.face, motion: msg.motion }, Date.now());
      if (rt.gaze) rt.gaze = addGazeSample(rt.gaze, !!msg.face);
      emit();
    }
  }

  function load() {
    if (rt.status === 'ready') return Promise.resolve(true);
    if (rt.loading) return rt.loading;
    if (rt.status === 'failed' && Date.now() - rt.failedAt < RETRY_AFTER_MS) return Promise.resolve(false);
    if (typeof root.Worker !== 'function') {
      rt.status = 'failed';
      rt.error = '이 브라우저는 카메라 판단을 따로 돌리지 못해요';
      emit();
      return Promise.resolve(false);
    }
    rt.status = 'loading';
    emit();
    const work = new Promise((resolve, reject) => {
      const w = new Worker(WORKER_SRC);
      rt.worker = w;
      const first = (e) => {
        const msg = e.data || {};
        if (msg.type === 'ready') { w.removeEventListener('message', first); resolve(true); }
        if (msg.type === 'failed') { w.removeEventListener('message', first); reject(new Error(msg.error)); }
      };
      w.addEventListener('message', first);
      w.addEventListener('message', onWorkerMessage);
      w.addEventListener('error', (e) => reject(new Error(e.message || '카메라 판단 워커가 멈췄어요')));
      w.postMessage({ type: 'init', opencv: OPENCV_SRCS.map(abs), cascade: CASCADE_SRCS.map(abs), logic: abs(LOGIC_SRC) });
    });
    const timeout = new Promise((_, reject) => setTimeout(() => reject(new Error('카메라 판단 도구를 받는 데 너무 오래 걸려요')), LOAD_TIMEOUT_MS));
    rt.loading = Promise.race([work, timeout]).then(() => {
      rt.status = 'ready';
      rt.error = '';
      return true;
    }).catch((err) => {
      rt.status = 'failed';
      rt.failedAt = Date.now();
      rt.error = String((err && err.message) || err);
      if (rt.worker) { rt.worker.terminate(); rt.worker = null; }
      console.warn('[chuckchuck] booth cv', rt.error);
      return false;
    }).finally(() => {
      rt.loading = null;
      emit();
      if (rt.status === 'ready' && rt.video) schedule(0);
    });
    return rt.loading;
  }

  /** video 한 장을 줄여 워커로 보낸다. 워커가 앞 장을 보는 중이면 이번 장은 건너뛴다 */
  function sendFrame() {
    const v = rt.video;
    if (!v || !rt.worker || rt.busy || v.readyState < 2 || !v.videoWidth) return;
    const h = Math.round(FRAME_W * (v.videoHeight / v.videoWidth)) || 180;
    if (!rt.canvas) rt.canvas = document.createElement('canvas');
    const c = rt.canvas;
    if (c.width !== FRAME_W || c.height !== h) { c.width = FRAME_W; c.height = h; }
    const ctx = c.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(v, 0, 0, FRAME_W, h);
    const img = ctx.getImageData(0, 0, FRAME_W, h);
    rt.busy = true;
    rt.sentAt = Date.now();
    rt.worker.postMessage({ type: 'frame', w: FRAME_W, h, data: img.data.buffer }, [img.data.buffer]);
  }

  /** 워커가 답을 안 하면 busy 가 영원히 남아 판단이 조용히 멈춘다 — 그 장은 버리고, 거듭되면 워커를 새로 띄운다 */
  function checkStall() {
    if (!rt.busy || Date.now() - rt.sentAt < STALL_MS) return false;
    rt.busy = false;
    rt.stalls += 1;
    if (rt.stalls < STALL_RESTART) return false;
    console.warn('[chuckchuck] booth cv worker stalled — restarting');
    if (rt.worker) rt.worker.terminate();
    rt.worker = null;
    rt.stalls = 0;
    rt.status = 'idle';
    load();
    return true;
  }

  function tick() {
    rt.timer = 0;
    if (!rt.video || rt.status !== 'ready') return;
    if (checkStall()) return;
    if (!document.hidden) {
      try { sendFrame(); } catch (err) { rt.busy = false; console.warn('[chuckchuck] booth cv frame', err); }
    }
    schedule(document.hidden || rt.lastCostMs > 90 ? Math.max(SLOW_TICK_MS, rt.tickMs) : rt.tickMs);
  }

  function schedule(ms) {
    if (rt.timer) clearTimeout(rt.timer);
    rt.timer = setTimeout(tick, ms);
  }

  function emit() {
    const snap = snapshot();
    rt.listeners.forEach((fn) => { try { fn(snap); } catch (err) { console.warn('[chuckchuck] booth cv listener', err); } });
  }

  function snapshot() {
    return {
      status: rt.status,
      error: rt.error,
      present: rt.state.present,
      arrived: rt.state.arrived,
      left: rt.state.left,
      face: rt.state.face,
      hint: rt.state.hint,
      gaze: rt.gaze ? { ...rt.gaze } : null,
      costMs: rt.lastCostMs,
    };
  }

  /**
   * 이 video 를 보기 시작한다. 같은 video 면 속도만 바꾼다.
   * tickMs — 사람이 오는지만 보는 화면(시작·고르기)은 느리게, 구도 안내·정면 비율을 재는 질문 화면은 기본.
   */
  function watch(video, { tickMs = TICK_MS } = {}) {
    rt.tickMs = Math.max(TICK_MS, Number(tickMs) || TICK_MS);
    if (rt.video === video) return;
    rt.video = video || null;
    rt.state = createCvState(Date.now());
    if (rt.video && rt.status === 'ready') schedule(0);
    if (!rt.video && rt.timer) { clearTimeout(rt.timer); rt.timer = 0; }
  }

  function unwatch() { watch(null); }

  function subscribe(fn) {
    rt.listeners.add(fn);
    fn(snapshot());
    return () => rt.listeners.delete(fn);
  }

  function startGaze() { rt.gaze = createGazeStats(); }
  function readGaze() { return rt.gaze ? { ...rt.gaze } : null; }
  function stopGaze() { const g = readGaze(); rt.gaze = null; return g; }

  root.BoothCV = {
    load, watch, unwatch, subscribe,
    startGaze, readGaze, stopGaze,
    status: () => rt.status,
    snapshot,
  };
})(typeof window !== 'undefined' ? window : globalThis);
