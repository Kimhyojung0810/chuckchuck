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
import { predsFromRows } from './lab_rows.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const [src, dst, webArg] = process.argv.slice(2);
const RUNS = '/data/models/_runs/behavior-cv/lab/runs';
const web = webArg || path.resolve(HERE, '../../../main/web');
const ctx = { console };
vm.createContext(ctx);
vm.runInContext(readFileSync(path.join(web, 'js/behavior_cv_logic.js'), 'utf8'), ctx);
const L = ctx.BehaviorCvLogic;
// 문턱 바꿔 보기: LOGIC_CFG='{"gestThr":0.03}' node replay_logic.mjs …  (CFG 객체를 그 자리에서 고친다 — 함수 기본값이 같은 객체를 본다)
if (process.env.LOGIC_CFG) Object.assign(L.CFG, JSON.parse(process.env.LOGIC_CFG));

// preds 아래 갈래(browser · 노드 엔진의 p0/p67/p133 …)를 다 다시 돌린다
for (const label of readdirSync(path.join(RUNS, src, 'preds'))) {
  const inDir = path.join(RUNS, src, 'preds', label);
  const outDir = path.join(RUNS, dst, 'preds', label);
  mkdirSync(outDir, { recursive: true });
  for (const f of readdirSync(inDir).filter((x) => x.endsWith('.json'))) {
    const d = JSON.parse(readFileSync(path.join(inDir, f), 'utf8'));
    const rows = d.engine_rows;
    if (!rows) { console.log('engine_rows 없음 —', f); continue; }
    const gt = JSON.parse(readFileSync(path.join('/data/models/_runs/behavior-cv/lab/clips', f.replace('.json', '.gt.json')), 'utf8'));
    const { rows: out, summary } = predsFromRows(L, rows, gt.fps);
    writeFileSync(path.join(outDir, f), JSON.stringify({ ...d, rows: out, summary, adapter_note: `replay ${src}` }));
  }
  console.log('→', outDir);
}
const meta = path.join(RUNS, src, 'meta.json');
if (existsSync(meta)) copyFileSync(meta, path.join(RUNS, dst, 'meta.json'));
