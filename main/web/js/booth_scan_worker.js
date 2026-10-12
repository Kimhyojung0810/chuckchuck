/**
 * 부스 「사람 그래프」 스캔 화면(/booth/scan) 추론 워커 (모듈 워커) — MediaPipe Tasks Vision 의 FaceLandmarker · PoseLandmarker(lite).
 * lab/eval-1008 의 eval_lab_worker.js 를 이 화면에 맞게 줄였다: 손 모델 없음(무겁다) · 표정 계수 · 변환 행렬 없음 · 여러 사람(최대 3).
 *
 * 왜 워커인가 — detectForVideo 는 부르는 스레드를 막는다. 메인 스레드는 그리기(화면 주사율)만 맡는다.
 * 프레임은 이 워커 밖으로 나가지 않는다 — 서버로도 안 간다. 고른 점의 좌표 숫자만 메인으로 돌려준다(478점 전체도 안 보낸다).
 *
 * 받는 곳: 우리 정적 경로(js/vendor/mediapipe/, etc/scripts/get_mediapipe.sh)를 먼저, 없으면 jsDelivr · Google 모델 저장소.
 * 위임: GPU 먼저, 만들다 실패하면 CPU.
 *
 * 메시지: init {base, pickFace, pickPose, people, delegate} → ready {delegate, src, ms} | failed {message}
 *         frame {bitmap, t, seq} → result {t, seq, faces:[Float32Array x,y…], poses:[Float32Array x,y,vis…], ms}
 */
const VER = '1.0.1';
const CDN = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VER}`;
const MODEL_CDN = {
  face: 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task',
  pose: 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task',
};

let V = null;
let tasks = { face: null, pose: null };
let state = { delegate: '', src: '', lastT: 0, opts: null, pickFace: [], pickPose: [] };

async function exists(url) {
  try {
    const r = await fetch(url, { method: 'HEAD' });
    return r.ok;
  } catch (_) {
    return false;
  }
}

async function loadLib(base) {
  try {
    if (!(await exists(`${base}vision_bundle.mjs`))) throw new Error('local missing');
    V = await import(`${base}vision_bundle.mjs`);
    return { src: 'local', wasm: `${base}wasm` };
  } catch (_) {
    V = await import(`${CDN}/vision_bundle.mjs`);
    return { src: 'cdn', wasm: `${CDN}/wasm` };
  }
}

async function modelPaths(base, src) {
  if (src !== 'local') return MODEL_CDN;
  const local = { face: `${base}face_landmarker.task`, pose: `${base}pose_landmarker_lite.task` };
  const out = {};
  for (const k of Object.keys(local)) out[k] = (await exists(local[k])) ? local[k] : MODEL_CDN[k];
  return out;
}

function closeAll() {
  for (const k of Object.keys(tasks)) {
    try { if (tasks[k]) tasks[k].close(); } catch (_) { /* 이미 닫힘 */ }
    tasks[k] = null;
  }
}

/**
 * 모듈 워커에서는 ES 모듈이 한 번만 실행된다. MediaPipe 는 과제 하나를 만들고 나면 self.ModuleFactory 를 비워서
 * 두 번째 과제(Pose)가 「ModuleFactory not set.」 으로 죽는다 (eval-lab 10-08 실측). 로더의 팩토리를 잡아 두고 매번 다시 꽂는다.
 */
let factory = null;
async function create(Task, fileset, opts) {
  if (factory) self.ModuleFactory = factory;
  return Task.createFromOptions(fileset, opts);
}

async function build(fileset, paths, delegate, people) {
  const base = (p) => ({ modelAssetPath: p, delegate });
  if (!factory) factory = (await import(fileset.wasmLoaderPath)).default;
  tasks.face = await create(V.FaceLandmarker, fileset, {
    baseOptions: base(paths.face), runningMode: 'VIDEO', numFaces: people,
    outputFaceBlendshapes: false, outputFacialTransformationMatrixes: false,
  });
  tasks.pose = await create(V.PoseLandmarker, fileset, {
    baseOptions: base(paths.pose), runningMode: 'VIDEO', numPoses: people,
  });
}

async function init(msg) {
  const t0 = performance.now();
  state.opts = msg;
  state.pickFace = Array.isArray(msg.pickFace) ? msg.pickFace : [];
  state.pickPose = Array.isArray(msg.pickPose) ? msg.pickPose : [];
  const people = Math.max(1, Math.min(3, msg.people | 0 || 3));
  try {
    const lib = await loadLib(msg.base);
    state.src = lib.src;
    const fileset = await V.FilesetResolver.forVisionTasks(lib.wasm, true);
    const paths = await modelPaths(msg.base, lib.src);
    const order = msg.delegate === 'CPU' ? ['CPU'] : ['GPU', 'CPU'];
    let lastErr = null;
    for (const d of order) {
      try {
        closeAll();
        await build(fileset, paths, d, people);
        state.delegate = d;
        lastErr = null;
        break;
      } catch (e) {
        lastErr = e;
        console.warn(`[booth-scan worker] ${d} 위임 실패:`, (e && e.message) || e);
      }
    }
    if (lastErr) throw lastErr;
    self.postMessage({ type: 'ready', delegate: state.delegate, src: state.src, ms: Math.round(performance.now() - t0) });
  } catch (e) {
    closeAll();
    self.postMessage({ type: 'failed', message: String((e && e.message) || e) });
  }
}

/** 478점 중 고른 번호만 [x,y,x,y…] 로 — 나머지는 버린다 */
function pickXY(lm, pick) {
  const out = new Float32Array(pick.length * 2);
  pick.forEach((idx, k) => {
    const p = lm[idx];
    out[2 * k] = p ? p.x : NaN;
    out[2 * k + 1] = p ? p.y : NaN;
  });
  return out;
}
function pickXYV(lm, pick) {
  const out = new Float32Array(pick.length * 3);
  pick.forEach((idx, k) => {
    const p = lm[idx];
    out[3 * k] = p ? p.x : NaN;
    out[3 * k + 1] = p ? p.y : NaN;
    out[3 * k + 2] = p && p.visibility != null ? p.visibility : 0;
  });
  return out;
}

function run(msg) {
  const img = msg.bitmap;
  // VIDEO 모드는 시각이 늘 커져야 한다 — 같은 값이 오면 1ms 밀어 준다
  const t = Math.max(msg.t, state.lastT + 1);
  state.lastT = t;
  const ms = {};
  const out = { type: 'result', t: msg.t, seq: msg.seq, faces: [], poses: [], ms };
  const transfer = [];
  try {
    let s = performance.now();
    const f = tasks.face.detectForVideo(img, t);
    ms.face = performance.now() - s;
    (f.faceLandmarks || []).forEach((lm) => { const a = pickXY(lm, state.pickFace); out.faces.push(a); transfer.push(a.buffer); });
    s = performance.now();
    const p = tasks.pose.detectForVideo(img, t);
    ms.pose = performance.now() - s;
    (p.landmarks || []).forEach((lm) => { const a = pickXYV(lm, state.pickPose); out.poses.push(a); transfer.push(a.buffer); });
  } catch (e) {
    out.error = String((e && e.message) || e);
  } finally {
    if (img && img.close) img.close();
  }
  self.postMessage(out, transfer);
}

self.onmessage = (e) => {
  const m = e.data || {};
  if (m.type === 'init') init(m);
  else if (m.type === 'reinit') init({ ...state.opts, delegate: m.delegate || 'CPU' });
  else if (m.type === 'frame') {
    if (!tasks.face || !tasks.pose) {
      if (m.bitmap && m.bitmap.close) m.bitmap.close();
      self.postMessage({ type: 'result', t: m.t, seq: m.seq, skipped: true });
      return;
    }
    run(m);
  } else if (m.type === 'close') closeAll();
};
