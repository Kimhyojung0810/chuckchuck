/**
 * logic 만 바꿨을 때 브라우저 없이 다시 채점 — 브라우저 실행(run.py browser)이 남긴 preds 의 engine_rows(엔진 줄)를
 * 지금의 main/web/js/behavior_cv_logic.js 로 다시 돌려 어댑터와 같은 모양의 예측을 새 실행 폴더에 쓴다. 그다음 run.py score.
 *
 *   node etc/labs/behavior_cv/replay_logic.mjs <원래 run> <새 run> [main/web 경로]
 *   PYTHONPATH=/data/models/_runs/behavior-cv/pylib .venv/bin/python etc/labs/behavior_cv/run.py score --run <새 run>
 *
 * 특징 뽑기(워커)를 바꿨으면 이걸로는 안 된다 — 브라우저로 다시 돌린다. 줄 모양은 web/adapter_default.js stop() 과 같게 유지할 것.
 */
import { readFileSync, writeFileSync, mkdirSync, readdirSync, copyFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const [src, dst, webArg] = process.argv.slice(2);
const RUNS = '/data/models/_runs/behavior-cv/lab/runs';
const web = webArg || path.resolve(HERE, '../../../main/web');
const ctx = { console };
vm.createContext(ctx);
vm.runInContext(readFileSync(path.join(web, 'js/behavior_cv_logic.js'), 'utf8'), ctx);
const L = ctx.BehaviorCvLogic;

const inDir = path.join(RUNS, src, 'preds', 'browser');
const outDir = path.join(RUNS, dst, 'preds', 'browser');
mkdirSync(outDir, { recursive: true });
for (const f of readdirSync(inDir).filter((x) => x.endsWith('.json'))) {
  const d = JSON.parse(readFileSync(path.join(inDir, f), 'utf8'));
  const rows = d.engine_rows;
  if (!rows) { console.log('engine_rows 없음 —', f); continue; }
  const gt = JSON.parse(readFileSync(path.join('/data/models/_runs/behavior-cv/lab/clips', f.replace('.json', '.gt.json')), 'utf8'));
  const fps = gt.fps;
  const seq = L.states(rows);
  const gflags = L.gestureFlags(seq);
  const sw = L.swayWindows(seq);
  const out = seq.map((x, i) => {
    const inOn = sw.filter((w) => w.on && x.t >= w.start && x.t < w.end);
    const any = sw.filter((w) => x.t >= w.start && x.t < w.end);
    return {
      frame: x.row._frame, orient: x.state, orient_raw: x.raw, present: x.present,
      sway: { active: inOn.length > 0, amp_fw: any.length ? Math.max(...any.map((w) => w.amp)) : null, freq: (inOn[0] || any[0] || {}).freq ?? null },
      gesture: gflags[i] === true, motion: Number.isFinite(x.row.meb) ? x.row.meb : (Number.isFinite(x.row.body) ? x.row.body : null), ms: x.row.ms,
      raw: { src: x.row.src, box: x.row.box },
    };
  });
  const t2f = (t) => { let best = seq[0]; for (const x of seq) { if (x.t <= t) best = x; else break; } return best ? best.row._frame : 0; };
  const m = L.measure(seq);
  const lookaways = m.look.map((r) => ({ t0: t2f(r.start) / fps, t1: (t2f(r.start) / fps) + r.dur / 1000 }));
  const view = L.analyze(rows);
  const slides = (view.segs || []).map((s) => ({
    i: Number(String(s.seg).slice(1)) - 1, presence_ratio: s.present, front_ratio: s.gaze,
    down_sec: s.down !== null && s.down !== undefined ? s.down * s.present * s.dur / 1000 : null, gesture_ratio: s.gesture, lookaway_n: s.lookaway,
  }));
  writeFileSync(path.join(outDir, f), JSON.stringify({ ...d, rows: out, summary: { slides, lookaways }, adapter_note: `replay ${src}` }));
}
const meta = path.join(RUNS, src, 'meta.json');
if (existsSync(meta)) copyFileSync(meta, path.join(RUNS, dst, 'meta.json'));
console.log('→', outDir);
