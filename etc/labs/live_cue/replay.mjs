/**
 * 발표 중 자세 알림(js/behavior_cue.js)을 브라우저 없이 — 정답 실험실이 남긴 엔진 줄(engine_rows)을 도착 순서대로 흘려
 * 화면 층과 같은 박자(0.5초마다 판단)로 decide 를 부르고, 알림이 뜬 시각을 영상 시각 · 정답 구간과 나란히 적는다.
 *
 *   node etc/labs/live_cue/replay.mjs [run 이름=engine_r3a] [클립,클립…]
 *
 * 엔진 줄은 /data/models/_runs/behavior-cv/lab/runs/<run>/preds/browser/<클립>.json 의 engine_rows (row._frame = 영상 프레임).
 * 목소리 반응은 없다고 본다(voiceBusy=false). 브라우저 검증은 etc/labs/live_cue/run.py.
 */
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const LAB = '/data/models/_runs/behavior-cv/lab';
const ctx = { console };
vm.createContext(ctx);
vm.runInContext(readFileSync(path.join(ROOT, 'main/web/js/behavior_cv_logic.js'), 'utf8'), ctx);
vm.runInContext(readFileSync(path.join(ROOT, 'main/web/js/behavior_cue.js'), 'utf8'), ctx);
const L = ctx.BehaviorCvLogic;
const C = ctx.BehaviorCue;

const run = process.argv[2] || 'engine_r3a';
const clips = (process.argv[3] || 's01_front_steady,s03_lookaway,s04_down_reading,s05_sway_freq,s06_sway_amp,s09_leave,d5_backlit,d7_small,d0_clean').split(',');

export function replay(rows, { evalMs = 500, enabled = true } = {}) {
  let meter = C.createMeter();
  const buf = [];
  const out = [];
  let nextEval = rows.length ? rows[0].t : 0;
  const t0 = rows.length ? rows[0].t : 0;
  for (const r of rows) {
    buf.push(r);
    while (buf.length && buf[0].t < r.t - C.CUE.bufMs) buf.shift();
    if (r.t < nextEval) continue;
    nextEval = r.t + evalMs;
    const c = C.conditions(buf, L);
    const d = C.decide(meter, c, { enabled, voiceBusy: false, t0 });
    meter = d.meter;
    if (d.cue) out.push({ ...d.cue, frame: r._frame, cond: c });
  }
  return out;
}

if (process.argv[1] && process.argv[1].endsWith('replay.mjs')) {
  for (const clip of clips) {
    const f = path.join(LAB, 'runs', run, 'preds/browser', `${clip}.json`);
    if (!existsSync(f)) { console.log(`${clip}: 엔진 줄 없음`); continue; }
    const d = JSON.parse(readFileSync(f, 'utf8'));
    const gt = JSON.parse(readFileSync(path.join(LAB, 'clips', `${clip}.gt.json`), 'utf8'));
    const rows = (d.engine_rows || []).slice().sort((a, b) => a.t - b.t);
    const cues = replay(rows);
    const seg = gt.segments;
    const fmt = (xs) => xs.map((s) => `${s.t0.toFixed(1)}–${s.t1.toFixed(1)}${s.dir ? s.dir[0] : ''}`).join(' ') || '-';
    console.log(`\n${clip}  (${gt.duration}s · 줄 ${rows.length})`);
    console.log(`  정답 이탈 ${fmt(seg.lookaway)} | 아래 ${fmt(seg.down)} | 흔들림 ${fmt(seg.sway)} | 비움 ${fmt(seg.absent)}`);
    if (!cues.length) console.log('  알림 없음');
    cues.forEach((c) => console.log(`  ▶ ${(c.frame / gt.fps).toFixed(1)}s  ${c.type.padEnd(7)} ${c.text}   (away ${c.cond.away} down ${c.cond.down} none ${c.cond.none} sway ${c.cond.sway} far ${c.cond.far} backlit ${c.cond.backlit})`));
  }
}
