/**
 * 비전 리허설 반응 규칙.
 *
 *   node tests/js/vision_cue.smoke.mjs
 *
 * 카메라·마이크는 이 서버에서 못 연다. 그래서 "빠르면 우웅, 느리면 하품,
 * 작으면 귀 기울임, 크면 귀 막음"을 vision_cue.js 로 빼 두고 여기서 잡는다.
 * 파일은 window.VisionCue 에 붙는 클래식 스크립트라 vm 으로 올린다.
 */
import { readFileSync } from 'node:fs';
import { createContext, runInContext } from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const SRC_PATH = path.join(ROOT, 'demo/YEHS_demo/js/vision_cue.js');

function load(src = readFileSync(SRC_PATH, 'utf8')) {
  const sandbox = { window: {}, console };
  runInContext(src, createContext(sandbox), { filename: 'vision_cue.js' });
  if (!sandbox.window.VisionCue) throw new Error('VisionCue 가 안 붙었어요');
  return sandbox.window.VisionCue;
}

const V = load();
const cases = [];
function test(name, fn) { cases.push({ name, fn }); }
function eq(a, b, msg = '') {
  const A = JSON.stringify(a), B = JSON.stringify(b);
  if (A !== B) throw new Error(`${msg}\n  expected ${B}\n  got      ${A}`);
}

function series(mod, { step, dChars, level, until, cfg }) {
  const use = cfg || mod.VISION;
  const events = [];
  let chars = 0;
  for (let t = 0; t <= until; t += step) {
    chars += dChars;
    const e = { t, chars };
    if (level !== undefined) e.level = level;
    events.push(e);
  }
  return mod.desiredCue(events, until, use);
}

test('글자만 센다 — 쉼표·물음표는 빠르기에 안 들어간다', () => {
  eq(V.countSpeechChars('어, 음... 안녕?'), 4);
});

test('말이 없고 방이 조용하면 잘 안 들려가 아니다', () => {
  const events = [0, 250, 500, 750].map((t) => ({ t, level: 0.004 }));
  eq(V.desiredCue(events, 750), 'idle');
});

test('말은 느는데 목소리가 작으면 잘 안 들려', () => {
  const events = [];
  for (let i = 0; i < 5; i++) events.push({ t: i * 200, chars: i * 4, level: 0.008 });
  eq(V.desiredCue(events, 800), 'quiet');
});

test('목소리가 크면 귀를 막는다 — 글자가 없어도', () => {
  const events = [0, 300, 600].map((t) => ({ t, level: 0.4 }));
  eq(V.desiredCue(events, 600), 'loud');
});

test('권장보다 많이 빠르면 우웅', () => {
  eq(series(V, { step: 250, dChars: 25, until: 2500 }), 'fast');
});

test('권장보다 많이 느리면 하품', () => {
  eq(series(V, { step: 300, dChars: 1, until: 4200 }), 'slow');
});

test('권장 안쪽 속도이고 목소리도 보통이면 듣기만 한다', () => {
  eq(series(V, { step: 250, dChars: 1.35, level: 0.08, until: 4000 }), 'listen');
});

test('빠르면서 크면 귀 막기가 이긴다', () => {
  eq(series(V, { step: 250, dChars: 25, level: 0.4, until: 2500 }), 'loud');
});

test('느리고 작으면 잘 안 들려가 이긴다', () => {
  const quiet = [];
  for (let i = 0; i <= 10; i++) quiet.push({ t: i * 400, chars: i, level: 0.008 });
  quiet.push({ t: 4200, chars: 12, level: 0.008 });
  quiet.push({ t: 4400, chars: 14, level: 0.008 });
  quiet.push({ t: 4600, chars: 16, level: 0.008 });
  eq(V.desiredCue(quiet, 4600), 'quiet');
  const audible = quiet.map((e) => ({ t: e.t, chars: e.chars, level: 0.08 }));
  eq(V.desiredCue(audible, 4600), 'slow');
});

test('큰 소리 한 점은 귀를 막지 않는다', () => {
  eq(V.desiredCue([{ t: 0, level: 0.9 }], 0), 'idle');
});

function wave(every, low, high, until) {
  const step = 80;
  const events = [];
  for (let t = 0, i = 0; t <= until; t += step, i += 1) {
    events.push({ t, level: i % every === 0 ? high : low });
  }
  return V.desiredCue(events, until);
}

test('받아쓰기 없이 말이 빠르면 우웅', () => {
  eq(wave(2, 0.05, 0.12, 1600), 'fast');
});

test('받아쓰기 없이 말이 느리면 하품', () => {
  eq(wave(10, 0.05, 0.12, 3200), 'slow');
});

test('작게 오르내리면 잘 안 들려', () => {
  eq(wave(2, 0.004, 0.018, 1600), 'quiet');
});

test('반응은 잠깐 유지된다 — 우웅 직후 재료가 사라져도 바로 풀리지 않는다', () => {
  const cfg = { ...V.VISION, holdMs: 800 };
  const meter = {
    ...V.createVisionMeter(0),
    cue: 'fast', cueAt: 1000, pending: 'idle', pendingAt: 1000, events: [],
  };
  const mid = V.observeVision(meter, { now: 1200 }, cfg);
  eq(mid.cue, 'fast');
  const later = V.observeVision(mid.meter, { now: 1800 }, cfg);
  eq(later.cue, 'idle');
});

test('문구는 네 반응에 우웅·하암·안 들려·귀가 있다', () => {
  eq(V.CUE_COPY.fast, '우웅?');
  eq(V.CUE_COPY.slow, '하암~');
  eq(V.CUE_COPY.quiet, '잘 안 들려');
  eq(V.CUE_COPY.loud, '귀가 아파');
});

const LOUD_LINE = "if (vol !== null && vol >= cfg.loudLevel) return 'loud';";
test('큰 소리 줄을 빼면 빠르면서 큰 소리가 우웅으로 떨어진다', () => {
  const src = readFileSync(SRC_PATH, 'utf8');
  if (!src.includes(LOUD_LINE)) throw new Error('큰 소리 판정이 바뀌었어요. 이 자기검사도 같이 고쳐요');
  const broken = load(src.replace(LOUD_LINE, ''));
  const events = [];
  let chars = 0;
  for (let t = 0; t <= 2500; t += 250) {
    chars += 25;
    events.push({ t, chars, level: 0.4 });
  }
  if (broken.desiredCue(events, 2500) === 'loud') {
    throw new Error('깨진 규칙이 여전히 귀를 막아요 — 시험이 아무것도 안 지킨다');
  }
});

let failed = 0;
for (const c of cases) {
  try {
    await c.fn();
    console.log(`  ✓ ${c.name}`);
  } catch (err) {
    failed += 1;
    console.error(`  ✗ ${c.name}`);
    console.error(err && err.stack || err);
  }
}
console.log(failed ? `${failed} failed` : `${cases.length} passed`);
process.exit(failed ? 1 : 0);
