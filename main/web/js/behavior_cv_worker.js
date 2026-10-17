/**
 * 발표 태도(베타) 카메라 워커 — js/behavior_cv.js 가 띄운다. OpenCV.js 와 캐스케이드 셋(정면 · 옆얼굴 · 눈)을 여기서만 올린다.
 * 메인 스레드에서 올리면 화면이 2분 넘게 얼었다 (booth_cv_worker.js 머리말, 2026-09-30 실험실) — 발표 화면이 얼면 안 된다.
 *
 * 받는 것: { type: 'init', opencv: [url…], cascades: { frontal: [url…], profile: [url…], eye: [url…] }, features: url, mode: 'cascade'|'nocascade' }
 *          { type: 'frame', w, h, data: ArrayBuffer(RGBA), t, id }   — 메인이 320px 로 줄여 보낸 한 장
 *          { type: 'reset' }                                           — 새 기록(발표 · Q&A)을 시작한다: 템플릿 · 앞 장을 버린다
 * 보내는 것: { type: 'ready', info } · { type: 'failed', error } · { type: 'row', id, row } · { type: 'row', id, error }
 * 프레임은 이 워커 밖으로 나가지 않는다 — 돌려주는 것은 숫자 한 줄뿐이다 (서버로도 숫자 요약만 간다).
 */
/* global cv, BehaviorCvFeatures */
'use strict';

let ex = null;

function post(msg) { self.postMessage(msg); }

/* 이 빌드의 Module 은 then 을 가진 thenable 이다 — Module 자체를 resolve 하면 끝없이 돈다 (booth_cv_worker.js 와 같은 함정) */
function cvReady(mod) {
  if (!mod) return Promise.reject(new Error('OpenCV 가 전역에 없어요'));
  return new Promise((resolve) => {
    if (mod.Mat) resolve();
    else mod.onRuntimeInitialized = () => resolve();
  }).then(() => { try { delete mod.then; } catch (_) { /* 값을 안 넘기니 괜찮다 */ } });
}

function importFirst(urls) {
  let last = null;
  for (const url of urls || []) {
    try { importScripts(url); return url; } catch (err) { last = err; }
  }
  throw last || new Error('불러올 곳이 없어요');
}

async function fetchFirst(urls) {
  let last = null;
  for (const url of urls || []) {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return new Uint8Array(await res.arrayBuffer());
    } catch (err) { last = err; }
  }
  throw last || new Error('불러올 곳이 없어요');
}

async function init(msg) {
  try {
    importScripts(msg.features);
    const from = importFirst(msg.opencv);
    await cvReady(self.cv);
    const names = {};
    const noc = msg.mode === 'nocascade';
    // 정면은 꼭 있어야 하고, 옆얼굴 · 눈은 못 받으면 그 지표만 빠진다 (logic 이 「잴 수 없었어요」 로 말한다).
    // 예비 모드(nocascade)는 캐스케이드를 아예 받지 않는다 — 가운데 시작 CamShift + 차분만
    for (const kind of noc ? [] : ['frontal', 'profile', 'eye']) {
      try {
        const bytes = await fetchFirst((msg.cascades || {})[kind]);
        const file = `bcv_${kind}.xml`;
        cv.FS_createDataFile('/', file, bytes, true, false, false);
        names[kind] = file;
      } catch (err) {
        if (kind === 'frontal') throw err;
      }
    }
    ex = BehaviorCvFeatures.createExtractor(cv, names, { mode: noc ? 'nocascade' : 'cascade' });
    post({ type: 'ready', info: { ...ex.info, opencv: /vendor/.test(from) ? 'local' : 'cdn' } });
  } catch (err) {
    post({ type: 'failed', error: String((err && err.message) || err) });
  }
}

self.onmessage = (e) => {
  const msg = e.data || {};
  if (msg.type === 'init') { init(msg); return; }
  if (msg.type === 'reset') { if (ex) ex.reset(); return; }
  if (msg.type === 'frame') {
    if (!ex) { post({ type: 'row', id: msg.id, error: 'not ready' }); return; }
    try {
      post({ type: 'row', id: msg.id, row: ex.process({ data: msg.data, w: msg.w, h: msg.h, t: msg.t }) });
    } catch (err) {
      post({ type: 'row', id: msg.id, error: String((err && err.message) || err) });
    }
  }
};
