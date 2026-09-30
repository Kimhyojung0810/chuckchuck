/**
 * 부스 Q&A 무대(#/booth/qa)의 카메라 판단(booth_cv.js BoothCvLogic) 순수 함수 스모크.
 *
 *   node tests/js/booth_qa.smoke.mjs
 *
 * 왜 있나 — 이 서버엔 웹캠이 없어서 「사람이 다가오면 인사」·「가운데로 와 주세요」·「정면 비율」이
 * 화면에서 어떻게 켜지고 꺼지는지 손으로 못 본다. 판단은 프레임 표본만 받는 순수 함수라 여기서 잡는다.
 * booth_cv.js 는 클래식 스크립트(window.BoothCvLogic)라 vm 에 원본 그대로 올린다 — 사본이 아니다.
 *
 * 마지막 케이스는 하네스가 진짜로 회귀를 잡는지 스스로 검사한다 (booth.smoke.mjs 와 같은 규율).
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const CV_PATH = path.join(ROOT, 'demo/YEHS_demo/js/booth_cv.js');

function loadLogic(src) {
  const ctx = { console };
  vm.createContext(ctx);
  vm.runInContext(src, ctx, { filename: 'booth_cv.js' });
  return ctx.BoothCvLogic;
}
const SRC = readFileSync(CV_PATH, 'utf8');
const L = loadLogic(SRC);

const cases = [];
const test = (name, fn) => cases.push({ name, fn });
const eq = (a, b, msg) => { if (a !== b) throw new Error(`${msg}: ${JSON.stringify(a)} !== ${JSON.stringify(b)}`); };

const FACE_MID = { cx: 0.5, cy: 0.45, w: 0.22, h: 0.3 };

/** 표본을 fps 간격으로 흘려 마지막 상태와 지나간 상태들을 돌려준다 */
function run(samples, { start = 0, stepMs = 180, state = L.createCvState(start) } = {}) {
  let s = state;
  let t = start;
  const seen = [];
  samples.forEach((sample) => {
    t += stepMs;
    s = L.stepCvState(s, sample, t);
    seen.push(s);
  });
  return { s, t, seen };
}
const repeat = (n, sample) => Array.from({ length: n }, () => sample);

test('빈 방에서는 앞에 섰다고 하지 않는다', () => {
  const { s } = run(repeat(20, { face: null, motion: 0 }));
  eq(s.present, false, 'present');
  eq(s.hint, '', 'hint');
});

test('얼굴이 한 번 잡히면 곧바로 「앞에 섰다」 — arrived 는 그 한 걸음만 참', () => {
  const { seen } = run([{ face: null, motion: 0 }, { face: FACE_MID, motion: 0 }, { face: FACE_MID, motion: 0 }]);
  eq(seen[1].present, true, 'present');
  eq(seen[1].arrived, true, 'arrived 첫 걸음');
  eq(seen[2].arrived, false, 'arrived 는 한 번만');
});

test('조명이 한 프레임 번쩍한 것은 사람이 아니다 — 움직임은 이어져야 한다', () => {
  const { s } = run([{ face: null, motion: 0.3 }, { face: null, motion: 0 }, { face: null, motion: 0 }]);
  eq(s.present, false, 'present');
});

test('얼굴은 옆을 봐도 계속 움직이면 앞에 있는 것이다', () => {
  const { s } = run(repeat(6, { face: null, motion: 0.05 }));
  eq(s.present, true, 'present');
});

test('떠난 뒤 absentMs 가 지나야 「떠났다」 — 잠깐 고개 돌린 것으로는 안 떠난다', () => {
  const first = run(repeat(3, { face: FACE_MID, motion: 0 }));
  const brief = run(repeat(10, { face: null, motion: 0 }), { start: first.t, state: first.s });   // 1.8초
  eq(brief.s.present, true, '1.8초 뒤');
  const long = run(repeat(30, { face: null, motion: 0 }), { start: first.t, state: first.s });   // 5.4초
  eq(long.s.present, false, '5.4초 뒤');
  eq(long.seen.filter((x) => x.left).length, 1, 'left 는 한 번만');
});

test('가장자리에 선 얼굴은 hintHoldMs 뒤에야 「가운데로」 — 스쳐 지나가면 말하지 않는다', () => {
  const edge = { cx: 0.12, cy: 0.5, w: 0.2, h: 0.28 };
  const quick = run(repeat(3, { face: edge, motion: 0 }));    // 0.54초
  eq(quick.s.hint, '', '스쳐 지나감');
  const stay = run(repeat(8, { face: edge, motion: 0 }));     // 1.44초
  eq(stay.s.hint, L.HINT_COPY.center, '머무름');
});

test('Haar 가 한두 프레임 놓쳐도 하던 안내를 그대로 둔다 (깜빡임 방지)', () => {
  const edge = { cx: 0.12, cy: 0.5, w: 0.2, h: 0.28 };
  const a = run(repeat(8, { face: edge, motion: 0 }));
  const b = run([{ face: null, motion: 0 }, { face: null, motion: 0 }], { start: a.t, state: a.s });
  eq(b.s.hint, L.HINT_COPY.center, '놓친 동안');
});

test('얼굴이 lostMs 넘게 안 보이면 「화면 밖」', () => {
  const a = run(repeat(3, { face: FACE_MID, motion: 0 }));
  const b = run(repeat(14, { face: null, motion: 0.03 }), { start: a.t, state: a.s });   // 움직임으로 present 유지
  eq(b.s.present, true, 'present');
  eq(b.s.hint, L.HINT_COPY.lost, 'lost');
});

test('구도 종류 — 작으면 가까이, 크면 뒤로, 알맞으면 없음', () => {
  eq(L.framingKind({ cx: 0.5, cy: 0.5, w: 0.08, h: 0.1 }), 'near', 'near');
  eq(L.framingKind({ cx: 0.5, cy: 0.5, w: 0.7, h: 0.9 }), 'far', 'far');
  eq(L.framingKind(FACE_MID), '', 'ok');
  eq(L.framingKind(null), 'lost', 'lost');
});

test('stepCvState 는 넘겨받은 상태를 고치지 않는다', () => {
  const s0 = L.createCvState(0);
  const snap = JSON.stringify(s0);
  L.stepCvState(s0, { face: FACE_MID, motion: 0.5 }, 1000);
  eq(JSON.stringify(s0), snap, 'prev 불변');
});

test('정면 비율은 충분히 쟀을 때만 숫자가 된다', () => {
  let g = L.createGazeStats();
  for (let i = 0; i < 5; i += 1) g = L.addGazeSample(g, true);
  eq(L.gazePercent(g), null, '5프레임');
  for (let i = 0; i < 15; i += 1) g = L.addGazeSample(g, i % 3 !== 0);
  eq(L.gazePercent(g), 75, '20프레임 중 15');
});

test('여러 얼굴 중 가장 큰 얼굴을 비율로 바꾼다', () => {
  const f = L.pickLargestFace([{ x: 10, y: 10, width: 20, height: 20 }, { x: 100, y: 40, width: 64, height: 64 }], 320, 180);
  eq(f.w, 0.2, 'w');
  eq(Math.round(f.cx * 1000), Math.round((132 / 320) * 1000), 'cx');
  eq(L.pickLargestFace([], 320, 180), null, '없음');
});

/* 자기검사 — 움직임 지속 조건을 빼면 「조명 번쩍」 시험이 깨져야 한다 */
const SUSTAIN_LINE = 'const moving = motionSince >= 0 && now - motionSince >= cfg.motionSustainMs;';
test('움직임 지속 조건을 빼면 「조명 번쩍」 시험이 깨진다', () => {
  if (!SRC.includes(SUSTAIN_LINE)) throw new Error(`stepCvState 가 바뀌었어요. 이 자기검사도 같이 고쳐야 해요: ${SUSTAIN_LINE}`);
  const B = loadLogic(SRC.replace(SUSTAIN_LINE, 'const moving = motionSince >= 0;'));
  let s = B.createCvState(0);
  s = B.stepCvState(s, { face: null, motion: 0.3 }, 180);
  if (!s.present) throw new Error('깨진 규칙도 번쩍임을 걸렀어요 — 시험이 아무것도 안 지킨다');
});

/* ── 실행 ──────────────────────────────────────────────────────────────────── */
let failed = 0;
for (const c of cases) {
  try {
    await c.fn();
    console.log(`  ✓ ${c.name}`);
  } catch (err) {
    failed += 1;
    console.log(`  ✗ ${c.name}\n    ${String(err && err.message || err).replace(/\n/g, '\n    ')}`);
  }
}
console.log(`\n${cases.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
