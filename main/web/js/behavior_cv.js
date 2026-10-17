/**
 * 발표 태도(베타) 카메라 기록 — 리허설(#/rehearsal)의 비전 리허설(발표)과 글라스 화상판(Q&A)이 이미 연 카메라를 조용히 본다.
 *
 *  화면 → 320px 로 줄인 한 장 → 워커(js/behavior_cv_worker.js, 고전 OpenCV) → 숫자 한 줄 → 여기서 장면 표시(장 · 질문 · 말하는 중)를 붙여 쌓는다
 *  기록을 닫으면 → js/behavior_cv_logic.js analyze() → nf.behavior.present | .qa (화면용) · summary(서버용, 숫자만)
 *
 * 카메라 권한을 묻는 때 · 녹음 · 부스 정면 알약(js/booth_cv.js)은 건드리지 않는다 — 열린 video 를 읽기만 한다.
 * 영상은 탭 밖으로 나가지 않는다. 워커를 못 띄우거나 도구를 못 받으면 조용히 빠지고 리포트에 「카메라 분석 없음」 과 까닭만 남는다.
 */
(function (root) {
  'use strict';

  if (!root.document) return;

  // ⚠️ 워커 · 워커가 다시 읽는 특징 파일의 ?v= 는 여기서 손으로 올린다 — etc/scripts/chk bump 는 index.html 만 본다 (CLAUDE.md §2)
  const WORKER_SRC = 'js/behavior_cv_worker.js?v=bc1';
  const FEATURES_SRC = 'js/behavior_cv_features.js?v=bc1';
  const CDN_CV = 'https://cdn.jsdelivr.net/npm/@techstark/opencv-js@4.10.0-release.1/dist/opencv.js';
  const CDN_XML = 'https://cdn.jsdelivr.net/gh/opencv/opencv@4.10.0/data/haarcascades/';
  const OPENCV_SRCS = ['js/vendor/opencv.js', CDN_CV];
  const CASCADES = {
    frontal: ['js/vendor/cv/haarcascade_frontalface_default.xml', `${CDN_XML}haarcascade_frontalface_default.xml`],
    profile: ['js/vendor/cv/haarcascade_profileface.xml', `${CDN_XML}haarcascade_profileface.xml`],
    eye: ['js/vendor/cv/haarcascade_eye.xml', `${CDN_XML}haarcascade_eye.xml`],
  };
  const FRAME_W = 320;          // 특징 뽑기 폭 — booth_cv 와 같다. 노트북 카메라 1m 거리 얼굴이 40~70px
  const TICK_MS = 200;          // 5fps 목표 (계획 §2)
  const SLOW_TICK_MS = 333;     // 느리면 3fps — 워커 한 장이 SLOW_COST_MS 를 넘거나 탭을 숨겼을 때
  const SLOW_COST_MS = 120;     // 한 장 처리(워커 안)가 이보다 오래면 느린 기기로 본다 — 3fps 에서도 받아쓰기 · 녹음과 같이 돌게
  const FAST_COST_MS = 70;      // 이 아래로 열 장 이어지면 다시 5fps
  const STALL_MS = 3000;
  const LOAD_TIMEOUT_MS = 45000;
  const MAX_ROWS = 20000;       // 5fps × 66분. 넘으면 하나 걸러 버린다(메모리 상한) — 평활 · 구간은 시간으로 재므로 깨지지 않는다
  const SPEAK_LEVEL = 0.015;    // 마이크 RMS 가 이 위면 말소리 — vision_cue.js quietLevel(0.03) 의 반 (작게 말해도 말하는 중, 설계값)
  const SPEAK_HOLD_MS = 700;    // 음절 사이 숨은 말하는 중으로 친다 (설계값)
  const abs = (u) => new URL(u, root.location.href).href;

  const rt = {
    status: 'idle',            // idle | loading | ready | failed
    error: '',
    info: null,
    loading: null,
    worker: null,
    busy: false, sentAt: 0, sentMeta: null, seq: 0,
    timer: 0, tickMs: TICK_MS, fastRun: 0,
    canvas: null,
    cap: null,                 // { phase, video(), seg(), speaking(), rows, t0, capMs[], skipped }
    lastLoudAt: -Infinity,
  };

  const L = () => root.BehaviorCvLogic;

  function load() {
    if (rt.status === 'ready') return Promise.resolve(true);
    if (rt.loading) return rt.loading;
    if (typeof root.Worker !== 'function') { rt.status = 'failed'; rt.error = '이 브라우저는 카메라 분석을 따로 돌리지 못해요'; return Promise.resolve(false); }
    rt.status = 'loading';
    const work = new Promise((resolve, reject) => {
      const w = new Worker(WORKER_SRC);
      rt.worker = w;
      w.addEventListener('message', (e) => {
        const msg = e.data || {};
        if (msg.type === 'ready') { rt.info = msg.info || null; resolve(true); }
        else if (msg.type === 'failed') reject(new Error(msg.error));
        else if (msg.type === 'row') onRow(msg);
      });
      w.addEventListener('error', (e) => reject(new Error(e.message || '카메라 분석 워커가 멈췄어요')));
      w.postMessage({
        type: 'init',
        opencv: OPENCV_SRCS.map(abs),
        cascades: Object.fromEntries(Object.entries(CASCADES).map(([k, v]) => [k, v.map(abs)])),
        features: abs(FEATURES_SRC),
      });
    });
    const timeout = new Promise((_, reject) => setTimeout(() => reject(new Error('카메라 분석 도구를 받는 데 너무 오래 걸려요')), LOAD_TIMEOUT_MS));
    rt.loading = Promise.race([work, timeout]).then(() => {
      rt.status = 'ready'; rt.error = '';
      return true;
    }).catch((err) => {
      rt.status = 'failed';
      rt.error = String((err && err.message) || err);
      if (rt.worker) { rt.worker.terminate(); rt.worker = null; }
      console.warn('[chuckchuck] behavior cv', rt.error);
      return false;
    }).finally(() => {
      rt.loading = null;
      if (rt.status === 'ready' && rt.cap) { rt.worker.postMessage({ type: 'reset' }); schedule(0); }
    });
    return rt.loading;
  }

  function onRow(msg) {
    rt.busy = false;
    const cap = rt.cap;
    const meta = rt.sentMeta;
    rt.sentMeta = null;
    if (!cap || !meta || meta.id !== msg.id || meta.cap !== cap) return;   // 지난 기록의 답 — 버린다
    if (msg.error || !msg.row) { cap.errors += 1; return; }
    const row = msg.row;
    row.seg = meta.seg;
    if (meta.sp !== undefined) row.sp = meta.sp;
    row.cap = meta.capMs;
    cap.rows.push(row);
    if (cap.rows.length > MAX_ROWS) cap.rows = cap.rows.filter((_, i) => i % 2 === 0);
    // 느린 기기면 3fps 로 — 워커 한 장 처리 시간으로 정한다 (탭이 숨으면 tick 이 따로 늦춘다)
    if (row.ms > SLOW_COST_MS) { rt.tickMs = SLOW_TICK_MS; rt.fastRun = 0; }
    else if (row.ms < FAST_COST_MS && rt.tickMs !== TICK_MS && ++rt.fastRun >= 10) { rt.tickMs = TICK_MS; rt.fastRun = 0; }
  }

  function speakingNow(cap) {
    if (typeof cap.level !== 'function') return undefined;
    const lv = cap.level();
    if (lv === null || lv === undefined || !Number.isFinite(lv)) return undefined;
    const now = performance.now();
    if (lv > SPEAK_LEVEL) rt.lastLoudAt = now;
    return now - rt.lastLoudAt < SPEAK_HOLD_MS ? 1 : 0;
  }

  function sendFrame() {
    const cap = rt.cap;
    const v = cap && cap.video();
    if (!v || !rt.worker || rt.busy || v.readyState < 2 || !v.videoWidth) return;
    const c0 = performance.now();
    const h = Math.round(FRAME_W * (v.videoHeight / v.videoWidth)) || 240;
    if (!rt.canvas) rt.canvas = document.createElement('canvas');
    const c = rt.canvas;
    if (c.width !== FRAME_W || c.height !== h) { c.width = FRAME_W; c.height = h; }
    const ctx = c.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(v, 0, 0, FRAME_W, h);
    const img = ctx.getImageData(0, 0, FRAME_W, h);
    rt.seq += 1;
    rt.busy = true;
    rt.sentAt = Date.now();
    rt.sentMeta = { id: rt.seq, cap, seg: String(cap.seg() || ''), sp: speakingNow(cap), capMs: Math.round(performance.now() - c0) };
    rt.worker.postMessage({ type: 'frame', w: FRAME_W, h, data: img.data.buffer, t: Math.round(performance.now() - cap.t0), id: rt.seq }, [img.data.buffer]);
  }

  function tick() {
    rt.timer = 0;
    const cap = rt.cap;
    if (!cap || rt.status !== 'ready') return;
    if (rt.busy && Date.now() - rt.sentAt > STALL_MS) { rt.busy = false; rt.sentMeta = null; cap.stalls += 1; }
    if (!document.hidden && (!cap.active || cap.active())) {
      try { sendFrame(); } catch (err) { rt.busy = false; cap.errors += 1; console.warn('[chuckchuck] behavior cv frame', err); }
    }
    schedule(document.hidden ? Math.max(1000, rt.tickMs) : rt.tickMs);
  }

  function schedule(ms) {
    if (rt.timer) clearTimeout(rt.timer);
    rt.timer = setTimeout(tick, ms);
  }

  /**
   * 기록을 시작한다. 같은 phase 가 이미 돌고 있으면 그대로 둔다(화면을 다시 그려도 이어 쓴다).
   * o: { video(): HTMLVideoElement|null, seg(): 's3' | 'q1' | '', level(): 마이크 RMS|null, active(): 지금 재도 되나 }
   */
  function start(phase, o = {}) {
    if (rt.cap && rt.cap.phase === phase) { Object.assign(rt.cap, pick(o)); return; }
    if (rt.cap) finish(rt.cap.phase);
    rt.cap = { phase, rows: [], t0: performance.now(), errors: 0, stalls: 0, startedAt: Date.now(), ...pick(o) };
    rt.tickMs = TICK_MS;
    rt.lastLoudAt = -Infinity;
    if (rt.status === 'ready') { rt.worker.postMessage({ type: 'reset' }); schedule(0); } else load();
  }

  function pick(o) {
    const out = {};
    ['video', 'seg', 'level', 'active'].forEach((k) => { if (typeof o[k] === 'function') out[k] = o[k]; });
    if (!out.video) out.video = () => null;
    if (!out.seg) out.seg = () => '';
    return out;
  }

  /** 지금 기록 중인 phase (없으면 '') */
  function running() { return rt.cap ? rt.cap.phase : ''; }

  /** 왜 기록이 없나 — 사용자가 고칠 수 있는 말로 */
  function whyNone(extra) {
    if (extra) return extra;
    if (rt.status === 'failed') return '카메라 분석 도구를 받지 못해서 이번엔 건너뛰었어요';
    if (rt.status === 'loading') return '카메라 분석 도구를 받는 사이에 끝났어요';
    return '카메라 화면을 읽지 못했어요';
  }

  /**
   * 기록을 닫고 분석한다. 돌려주는 것: 화면용 묶음(analyze 결과 + summary · device). 기록이 없으면 none(까닭).
   * 워커는 내리지 않는다 — 발표 다음 Q&A 가 곧 다시 쓴다. 다 끝나면 dispose().
   */
  function finish(phase, { why = '' } = {}) {
    const cap = rt.cap;
    if (!cap || (phase && cap.phase !== phase)) return null;
    rt.cap = null;
    if (rt.timer) { clearTimeout(rt.timer); rt.timer = 0; }
    rt.busy = false; rt.sentMeta = null;
    const logic = L();
    if (!logic) return null;
    let res;
    try {
      res = cap.rows.length ? logic.analyze(cap.rows, { phase: cap.phase }) : logic.none(whyNone(why), cap.phase);
    } catch (err) {
      console.warn('[chuckchuck] behavior cv analyze', err);
      res = logic.none('카메라 기록을 정리하다 멈췄어요', cap.phase);
    }
    const caps = cap.rows.map((r) => r.cap).filter(Number.isFinite);
    const view = { ...res, raw: undefined };
    view.summary = logic.summaryOf(res);
    view.device = { opencv: rt.info ? rt.info.opencv : '', tickMs: rt.tickMs, errors: cap.errors, stalls: cap.stalls,
      capP50: caps.length ? caps.slice().sort((a, b) => a - b)[caps.length >> 1] : null };
    return view;
  }

  /** 기록을 버린다 (녹음 파일로 대신함 · 다시 발표). 까닭이 있으면 none 묶음을 돌려준다 */
  function discard(phase, why) {
    if (rt.cap && (!phase || rt.cap.phase === phase)) {
      rt.cap = null;
      if (rt.timer) { clearTimeout(rt.timer); rt.timer = 0; }
      rt.busy = false; rt.sentMeta = null;
    }
    return why && L() ? L().none(why, phase || 'present') : null;
  }

  /** 워커(OpenCV ≈ 60MB)를 내린다 — 리허설을 떠날 때. 다음 load() 가 다시 띄운다(캐시에서 ≈1초) */
  function dispose() {
    if (rt.loading) { rt.loading.then(() => { if (!rt.cap) dispose(); }); return; }
    if (rt.cap) return;
    if (rt.timer) { clearTimeout(rt.timer); rt.timer = 0; }
    if (rt.worker) { rt.worker.terminate(); rt.worker = null; }
    rt.canvas = null;
    rt.busy = false;
    if (rt.status === 'ready') rt.status = 'idle';
  }

  /** 실험실 · 점검용 — 지금 기록의 줄 수 · 속도 */
  function snapshot() {
    const cap = rt.cap;
    const rows = cap ? cap.rows : [];
    const last = rows[rows.length - 1] || null;
    return { status: rt.status, error: rt.error, phase: cap ? cap.phase : '', rows: rows.length, tickMs: rt.tickMs, last, info: rt.info };
  }

  root.BehaviorCV = { load, start, finish, discard, dispose, running, snapshot, status: () => rt.status };
})(typeof window !== 'undefined' ? window : globalThis);
