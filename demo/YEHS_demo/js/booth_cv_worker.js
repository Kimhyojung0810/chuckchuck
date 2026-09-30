/**
 * 부스 Q&A 무대의 카메라 판단 워커 — js/booth_cv.js 가 띄운다.
 *
 * OpenCV.js(약 10MB)를 메인 스레드에서 올리면 헤드리스 크롬이 2분 넘게 멈췄다 (2026-09-30 실험실).
 * 같은 파일을 워커에서 올리면 0.7초다. 부스 화면(질문·판정·받아쓰기)이 얼면 안 되므로 판단은 전부 여기서 한다.
 *
 * 받는 것: { type: 'init', opencv: [url…], cascade: [url…], logic: url }
 *          { type: 'frame', w, h, data: ArrayBuffer(RGBA) }  — 메인이 320px 로 줄여 보낸 한 장
 * 보내는 것: { type: 'ready' } · { type: 'failed', error } · { type: 'result', face, motion, ms }
 * 프레임은 이 워커 밖으로 나가지 않는다 (서버로도 안 간다).
 */
/* global cv, BoothCvLogic */
'use strict';

let clf = null;
let mats = null;
let matsKey = '';
const MOTION_W = 80;

function post(msg) { self.postMessage(msg); }

/* 이 빌드의 Module 은 then 을 가진 thenable 이다. Promise 에 **Module 자체를 resolve 하면** 그 then 을 불러
   Module 을 또 resolve 하고 … 끝없이 돈다 (Emscripten 의 알려진 함정 — 실험실에서 45초 제한에 걸렸다).
   그래서 준비 신호만 기다리고 값은 넘기지 않는다. 다 뜬 뒤엔 then 을 떼어 이후 await 에도 안 걸리게 한다 */
function cvReady(mod) {
  if (!mod) return Promise.reject(new Error('OpenCV 가 전역에 없어요'));
  return new Promise((resolve) => {
    if (mod.Mat) resolve();
    else mod.onRuntimeInitialized = () => resolve();
  }).then(() => { try { delete mod.then; } catch (_) { /* 못 떼도 값을 안 넘기니 괜찮다 */ } });
}

function importFirst(urls) {
  let last = null;
  for (const url of urls) {
    try { importScripts(url); return; } catch (err) { last = err; }
  }
  throw last || new Error('불러올 곳이 없어요');
}

async function fetchFirst(urls) {
  let last = null;
  for (const url of urls) {
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
    importScripts(msg.logic);          // BoothCvLogic.pickLargestFace — 메인과 같은 함수를 쓴다
    importFirst(msg.opencv);
    await cvReady(self.cv);
    const bytes = await fetchFirst(msg.cascade);
    cv.FS_createDataFile('/', 'bq_face.xml', bytes, true, false, false);
    clf = new cv.CascadeClassifier();
    if (!clf.load('bq_face.xml')) throw new Error('얼굴 분류기를 읽지 못했어요');
    post({ type: 'ready' });
  } catch (err) {
    post({ type: 'failed', error: String((err && err.message) || err) });
  }
}

/* Mat 은 가비지 수거가 안 된다 — 한 벌을 만들어 돌려 쓴다 */
function ensureMats(w, h) {
  const key = `${w}x${h}`;
  if (mats && matsKey === key) return mats;
  if (mats) Object.values(mats).forEach((m) => { try { m.delete(); } catch (_) { /* 이미 지웠다 */ } });
  matsKey = key;
  mats = {
    gray: new cv.Mat(), small: new cv.Mat(), prev: new cv.Mat(), diff: new cv.Mat(), faces: new cv.RectVector(),
  };
  return mats;
}

function frame(msg) {
  if (!clf) return;
  const t0 = Date.now();
  const { w, h } = msg;
  const m = ensureMats(w, h);
  const rgba = cv.matFromImageData({ data: new Uint8ClampedArray(msg.data), width: w, height: h });
  try {
    cv.cvtColor(rgba, m.gray, cv.COLOR_RGBA2GRAY);
  } finally {
    rgba.delete();
  }
  cv.equalizeHist(m.gray, m.gray);
  clf.detectMultiScale(m.gray, m.faces, 1.1, 4, 0, new cv.Size(28, 28), new cv.Size(0, 0));
  const rects = [];
  for (let i = 0; i < m.faces.size(); i += 1) {
    const r = m.faces.get(i);
    rects.push({ x: r.x, y: r.y, width: r.width, height: r.height });
  }
  const face = BoothCvLogic.pickLargestFace(rects, w, h);

  // 움직임 — 80px 로 더 줄인 흑백 두 장의 차이. 조명 잡음은 흐림 + 문턱 25 로 거른다
  cv.resize(m.gray, m.small, new cv.Size(MOTION_W, Math.max(1, Math.round((MOTION_W * h) / w))), 0, 0, cv.INTER_AREA);
  cv.GaussianBlur(m.small, m.small, new cv.Size(3, 3), 0);
  let motion = 0;
  if (!m.prev.empty() && m.prev.rows === m.small.rows && m.prev.cols === m.small.cols) {
    cv.absdiff(m.small, m.prev, m.diff);
    cv.threshold(m.diff, m.diff, 25, 255, cv.THRESH_BINARY);
    motion = cv.countNonZero(m.diff) / (m.diff.rows * m.diff.cols);
  }
  m.small.copyTo(m.prev);
  post({ type: 'result', face, motion, ms: Date.now() - t0 });
}

self.onmessage = (e) => {
  const msg = e.data || {};
  if (msg.type === 'init') { init(msg); return; }
  if (msg.type === 'frame') {
    try { frame(msg); } catch (err) { post({ type: 'result', face: null, motion: 0, ms: 0, error: String((err && err.message) || err) }); }
  }
};
