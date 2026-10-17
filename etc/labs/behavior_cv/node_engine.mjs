/**
 * 브라우저 없이 엔진 특징(behavior_cv_features.js)까지 돌리기 — 노드에서 opencv.js(main/web/js/vendor) + 같은 캐스케이드로
 * y4m 영상을 「브라우저가 보는 것처럼」 줄여(320px) 처리 속도(5fps · 3fps …)대로 뽑아 넣는다. 결과는 run.py score 가 읽는 preds.
 *
 *   node etc/labs/behavior_cv/node_engine.mjs --run node_x [--clips d0_clean,s08_gesture] [--proc-fps 5] [--in-fps 15] [--jobs 6] [--web main/web]
 *   PYTHONPATH=/data/models/_runs/behavior-cv/pylib .venv/bin/python etc/labs/behavior_cv/run.py score --run node_x
 *
 * 브라우저 실행(run.py browser, 실시간 25분)과 다른 점: 처리 간격이 고르다(브라우저는 setTimeout 떨림 · 워커가 늦으면 건너뜀) ·
 * 줄이기가 cv.resize(INTER_AREA) 다(크롬 drawImage 와 화소가 조금 다르다). 그래서 기법 비교 · 저fps · 입력 fps 실험용이고,
 * 고친 것을 싣기 전에는 브라우저 실행(labrun.sh)으로 다시 잰다.
 *   --in-fps 15 : 30fps 영상(d8)을 15fps 로 솎아 「같은 영상 15 vs 30fps 입력」 을 견준다 (가짜 카메라가 15fps 로 내주는 셈)
 *   --proc-fps 3: 느린 기기(엔진이 3fps 로 내려감)를 흉내 낸다
 *   --phase-ms 67 : 카메라 장과 처리 시계의 어긋남 (세 위상 평균을 보려고)
 *   --fx '{"gestFlow":0.5}' : 특징 문턱을 바꿔 보기 · --debug : 손짓 중간값(gd)을 줄에 남김
 */
import { readFileSync, writeFileSync, mkdirSync, openSync, readSync, statSync, existsSync, readdirSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { predsFromRows } from './lab_rows.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CLIPS = '/data/models/_runs/behavior-cv/lab/clips';
const RUNS = '/data/models/_runs/behavior-cv/lab/runs';
const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => {
  if (a.startsWith('--')) acc.push([a.slice(2), all[i + 1] && !all[i + 1].startsWith('--') ? all[i + 1] : '1']);
  return acc;
}, []));
const web = path.resolve(args.web || path.join(HERE, '../../../main/web'));
const run = args.run || 'node_tmp';
const procFps = Number(args['proc-fps'] || 5);
// 5fps 처리는 15fps 영상의 3장마다 한 장 — 어느 장부터 뽑느냐(위상)에 손짓 값이 꽤 흔들린다. --phase-ms 0/67/133 세 번 돌려 평균을 본다
const phaseMs = Number(args['phase-ms'] || 0);
const label = args.label || 'browser';
const outDir = path.join(RUNS, run, 'preds', label);
let clips = (args.clips ? args.clips.split(',') : readdirSync(CLIPS).filter((f) => f.endsWith('.y4m')).map((f) => f.replace('.y4m', '')))
  .filter((c) => args.clips || !c.startsWith('d8_'));   // HD 영상(d8_*)은 따로 (--clips)

/* ── 여러 갈래로 나눠 돌리기 (자식 프로세스) ── */
const jobs = Number(args.jobs || 1);
if (jobs > 1 && !args.child) {
  const parts = Array.from({ length: jobs }, (_, j) => clips.filter((_, k) => k % jobs === j)).filter((p) => p.length);
  const pass = process.argv.slice(2).filter((a, i, all) => !(a === '--jobs' || all[i - 1] === '--jobs' || a === '--clips' || all[i - 1] === '--clips'));
  await Promise.all(parts.map((p) => new Promise((res) => {
    const ch = spawn(process.execPath, [fileURLToPath(import.meta.url), ...pass, '--clips', p.join(','), '--child', '1'], { stdio: 'inherit' });
    ch.on('exit', res);
  })));
  writeMeta();
  process.exit(0);
}

const require = createRequire(import.meta.url);
let cv = require(path.join(web, 'js/vendor/opencv.js'));
if (cv instanceof Promise) cv = await cv;
if (!cv.Mat) await new Promise((r) => { cv.onRuntimeInitialized = r; });
try { delete cv.then; } catch (_) { /* */ }
const files = {};
for (const [k, f] of Object.entries({ frontal: 'haarcascade_frontalface_alt2.xml', profile: 'haarcascade_profileface.xml', eye: 'haarcascade_eye.xml' })) {
  const name = `bcv_${k}.xml`;
  cv.FS_createDataFile('/', name, readFileSync(path.join(web, 'js/vendor/cv', f)), true, false, false);
  files[k] = name;
}
const F = require(path.join(web, 'js/behavior_cv_features.js'));
const ctx = { console };
vm.createContext(ctx);
vm.runInContext(readFileSync(path.join(web, 'js/behavior_cv_logic.js'), 'utf8'), ctx);
const L = ctx.BehaviorCvLogic;

function y4m(p) {
  const fd = openSync(p, 'r');
  const head = Buffer.alloc(200); readSync(fd, head, 0, 200, 0);
  const line = head.toString('latin1').split('\n')[0];
  const hdr = line.length + 1;
  const tok = (c) => line.split(' ').find((x) => x[0] === c).slice(1);
  const w = Number(tok('W')); const h = Number(tok('H'));
  const [a, b] = tok('F').split(':').map(Number);
  const fsize = (w * h * 3) / 2; const stride = 6 + fsize;
  const n = Math.floor((statSync(p).size - hdr) / stride);
  const buf = Buffer.alloc(fsize);
  return { w, h, fps: a / b, n, read(i) { readSync(fd, buf, 0, fsize, hdr + i * stride + 6); return buf; } };
}

mkdirSync(outDir, { recursive: true });
for (const clip of clips) {
  const gt = JSON.parse(readFileSync(path.join(CLIPS, `${clip}.gt.json`), 'utf8'));
  const v = y4m(path.join(CLIPS, `${clip}.y4m`));
  const inFps = Number(args['in-fps'] || v.fps);
  const ex = F.createExtractor(cv, files, { ...(args.fx ? JSON.parse(args.fx) : {}), ...(args.debug ? { debug: true } : {}) });
  const yuv = new cv.Mat(v.h * 1.5, v.w, cv.CV_8UC1);
  const rgba = new cv.Mat(); const small = new cv.Mat();
  const W = 320; const H = Math.round((W * v.h) / v.w);
  const rows = [];
  const dur = (v.n / v.fps) * 1000;
  const period = 1000 / procFps;
  const slideOf = (f) => { const t = f / gt.fps; let k = 0; gt.slides.forEach((s, i) => { if (t >= s.t0) k = i; }); return k; };
  const t0 = Date.now();
  for (let k = 0; ; k += 1) {
    const t = k * period + ((k * 37) % 11) - 5;                 // 고른 간격 + 작은 떨림(±5ms, 결정적)
    if (t >= dur) break;
    const fIn = Math.floor(((Math.max(0, t) + phaseMs) / 1000) * inFps);   // 그 순간 카메라가 내주는 장(입력 fps 기준) — phaseMs: 카메라와 처리 시계의 어긋남
    const f = Math.min(v.n - 1, Math.round((fIn / inFps) * v.fps));
    yuv.data.set(v.read(f));
    cv.cvtColor(yuv, rgba, cv.COLOR_YUV2RGBA_I420);
    cv.resize(rgba, small, new cv.Size(W, H), 0, 0, args.interp === 'area' ? cv.INTER_AREA : cv.INTER_LINEAR);
    const row = ex.process({ data: new Uint8ClampedArray(small.data), w: W, h: H, t: Math.max(0, t) });
    row.seg = 's' + (slideOf(f) + 1);
    row._frame = f;
    rows.push(row);
  }
  ex.dispose(); yuv.delete(); rgba.delete(); small.delete();
  const pred = predsFromRows(L, rows, gt.fps);
  writeFileSync(path.join(outDir, `${clip}.json`), JSON.stringify({ ...pred, engine_rows: rows, engine: 'node', clip, adapter_note: `node ${procFps}fps in ${inFps}fps phase ${phaseMs}ms` }));
  console.log(`  ${clip.padEnd(18)} 줄 ${String(rows.length).padStart(4)}  ${((Date.now() - t0) / 1000).toFixed(1)}s`);
}
if (!args.child) writeMeta();

function writeMeta() {
  const meta = path.join(RUNS, run, 'meta.json');
  const prev = existsSync(meta) ? JSON.parse(readFileSync(meta, 'utf8')) : {};
  writeFileSync(meta, JSON.stringify({ ...prev, engine: 'node', web, yaw_convention: 'subject', proc_fps: procFps, in_fps: args['in-fps'] || null,
    variants: [...new Set([...(prev.variants || []), label])], created: new Date().toISOString().slice(0, 19) }, null, 1));
}
