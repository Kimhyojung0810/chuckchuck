/**
 * 발표 중 자세 알림의 순수 함수 스모크 — js/behavior_cue.js (BehaviorCue.conditions · decide) 위에 js/behavior_cv_logic.js.
 *
 *   node etc/tests/js/behavior_cue.smoke.mjs
 *
 * 왜 있나 — 이 서버엔 웹캠이 없다. 엔진 줄 모양(behavior_cv_logic.js 머리말)대로 장면을 지어 화면 층과 같은 박자(0.5초마다)로
 * 흘려 무엇이 언제 알려지는지 잡는다: 드물게(20초 간격 · 같은 자세 한 번) · 목소리 반응과 안 겹치게 · 측정 문제는 한 번 · 손짓은 안 알림.
 * 원본 파일을 vm 에 그대로 올린다. 마지막 케이스는 하네스가 진짜로 회귀를 잡는지 스스로 검사한다.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const LOGIC = readFileSync(path.join(ROOT, 'main/web/js/behavior_cv_logic.js'), 'utf8');
const SRC = readFileSync(path.join(ROOT, 'main/web/js/behavior_cue.js'), 'utf8');

function load(src) {
  const ctx = { console };
  vm.createContext(ctx);
  vm.runInContext(LOGIC, ctx, { filename: 'behavior_cv_logic.js' });
  vm.runInContext(src, ctx, { filename: 'behavior_cue.js' });
  return { L: ctx.BehaviorCvLogic, C: ctx.BehaviorCue };
}
const { L, C } = load(SRC);

const cases = [];
const test = (name, fn) => cases.push({ name, fn });
const eq = (a, b, msg) => { if (a !== b) throw new Error(`${msg}: ${JSON.stringify(a)} !== ${JSON.stringify(b)}`); };
const ok = (c, msg) => { if (!c) throw new Error(msg); };

/* ── 줄 짓기 ── 5fps · 얼굴 폭 0.18 · 또렷 · 밝게 (behavior_cv.smoke.mjs 와 같은 모양) */
const STEP = 200;
const FW = 0.18;
const front = (t, o = {}) => ({ t, src: 'F', side: 0, box: [0.41, 0.2, FW, 0.24], eyes: 2, ey: 0.39, ex: 0, br: 150, fb: 140, bl: 300, mv: 0.05, body: 0.05, meb: 0.02, gs: 0, ms: 15, ...o });
const side = (t, o = {}) => ({ ...front(t), src: 'P', side: 1, eyes: 0, ...o });
const down = (t, o = {}) => ({ ...front(t), box: [0.41, 0.2 + 0.4 * 0.24, FW, 0.24], eyes: 2, ey: 0.55, ...o });
const lost = (t, o = {}) => ({ t, src: '', side: 0, box: null, eyes: 0, br: 150, bl: null, mv: 0.02, ms: 30, ...o });
const swayAt = (f, a) => (t) => { const x = 0.41 + a * FW * Math.sin(2 * Math.PI * f * (t / 1000)); return front(t, { box: [x, 0.2, FW, 0.24] }); };

/** 구간 대본 [[초, 줄 짓는 함수]] → 줄들. 장은 10초마다 넘긴다 */
function script(parts) {
  const rows = [];
  let t = 0;
  parts.forEach(([secs, make]) => {
    const n = Math.round((secs * 1000) / STEP);
    for (let k = 0; k < n; k += 1) { const r = make(t, k); rows.push({ ...r, seg: `s${1 + Math.floor(t / 10000)}` }); t += STEP; }
  });
  return rows;
}

/** 화면 층처럼 0.5초마다 판단 — voice(t) 가 참이면 목소리 반응이 떠 있다 */
function play(rows, { enabled = true, voice = () => false, api = C } = {}) {
  let meter = api.createMeter();
  const buf = []; const out = [];
  let next = 0;
  for (const r of rows) {
    buf.push(r);
    while (buf[0].t < r.t - api.CUE.bufMs) buf.shift();
    if (r.t < next) continue;
    next = r.t + 500;
    const d = api.decide(meter, api.conditions(buf, L), { enabled, voiceBusy: voice(r.t), t0: rows[0].t });
    meter = d.meter;
    if (d.cue) out.push({ type: d.cue.type, s: Math.round(d.cue.t / 100) / 10 });
  }
  return out;
}
const types = (cues) => cues.map((c) => c.type).join(',');

test('정면으로 가만히 60초 — 알림이 하나도 없다', () => {
  eq(types(play(script([[60, front]]))), '', '정면');
});

test('옆을 5초 — 「화면 쪽으로 돌아와요」 한 번, 옆을 본 지 4초 남짓에', () => {
  const cues = play(script([[8, front], [5, side], [10, front]]));
  eq(types(cues), 'away', '옆 5초');
  ok(cues[0].s >= 12 && cues[0].s <= 13, `알린 때 ${cues[0].s}초 (옆은 8초부터)`);
  eq(C.COPY.away, '화면 쪽으로 돌아와요', '문구');
});

test('옆을 3초 — 짧은 이탈은 알리지 않는다', () => {
  eq(types(play(script([[8, front], [3, side], [10, front]]))), '', '옆 3초');
});

test('자료 보기(아래) 6초는 「다른 곳」 이 아니고 아직 짧다 — 알림 없음', () => {
  eq(types(play(script([[8, front], [6, down], [10, front]]))), '', '아래 6초');
});

test('아래를 9초 — 「고개를 들고 말해 봐요」', () => {
  const cues = play(script([[8, front], [9, down], [6, front]]));
  eq(types(cues), 'down', '아래 9초');
  ok(cues[0].s >= 16 && cues[0].s <= 17, `알린 때 ${cues[0].s}초 (아래는 8초부터)`);
});

test('20초 간격 — 10초 사이 두 번 옆을 보면 첫 번째만, 25초 뒤 세 번째는 다시', () => {
  const cues = play(script([[6, front], [5, side], [5, front], [5, side], [20, front], [5, side], [5, front]]));
  eq(types(cues), 'away,away', '첫째 · 셋째');
  ok(cues[1].s - cues[0].s >= C.CUE.gapMs / 1000, `간격 ${cues[1].s - cues[0].s}초`);
});

test('같은 자세가 30초 이어져도 한 번만 — 끝나야 다시 알릴 수 있다', () => {
  eq(types(play(script([[6, front], [30, side], [4, front]]))), 'away', '긴 이탈');
});

test('목소리 반응이 떠 있으면 미룬다 — 걷히고 자세가 이어지면 그때 알린다', () => {
  const rows = script([[6, front], [12, side], [4, front]]);
  const cues = play(rows, { voice: (t) => t >= 9000 && t < 14000 });
  eq(types(cues), 'away', '미룬 뒤');
  ok(cues[0].s >= 14, `목소리가 걷힌 14초 뒤에 (${cues[0].s}초)`);
  eq(types(play(script([[6, front], [5, side], [6, front]]), { voice: () => true })), '', '목소리가 계속이면 안 알림');
});

test('끄면 아무것도 안 알린다', () => {
  eq(types(play(script([[6, front], [9, side], [12, down], [6, lost]]), { enabled: false })), '', '꺼짐');
});

test('처음 4초는 조용 — 시작부터 옆을 봐도 기록 시작 4초 전엔 안 알림', () => {
  const cues = play(script([[8, side], [4, front]]));
  eq(types(cues), 'away', '한 번');
  ok(cues[0].s >= C.CUE.warmMs / 1000, `${cues[0].s}초`);
});

test('화면 밖 — 「화면 안으로 들어와요」 는 한 테이크에 한 번', () => {
  const cues = play(script([[6, front], [6, lost], [20, front], [6, lost], [6, front]]));
  eq(types(cues), 'frame', '두 번째 자리 비움은 조용');
  eq(C.COPY.frame, '화면 안으로 들어와요', '문구');
});

test('너무 멂 · 역광 — 측정 문제는 한 번씩', () => {
  const small = (t) => front(t, { box: [0.47, 0.3, 0.06, 0.08] });
  eq(types(play(script([[40, small]]))), 'far', '작은 얼굴');
  const dark = (t) => front(t, { fb: 50, br: 160 });
  eq(types(play(script([[40, dark]]))), 'backlit', '역광');
});

test('몸을 0.6Hz 로 16초 흔들면 흔들림 알림 — 흔들리는 동안에', () => {
  const cues = play(script([[6, front], [16, swayAt(0.6, 0.3)], [10, front]]));
  eq(types(cues), 'sway', '흔들림');
  ok(cues[0].s > 6 && cues[0].s <= 22, `흔들리는 6~22초 사이 (${cues[0].s}초)`);
});

test('4초 흔들림은 알리지 않고, 7초 흔들림도 멎은 뒤에는 알리지 않는다 (8초 창의 늦은 알림 막기)', () => {
  eq(types(play(script([[6, front], [4, swayAt(0.6, 0.3)], [14, front]]))), '', '4초 흔들림');
  const late = play(script([[6, front], [7, swayAt(0.6, 0.3)], [14, front]])).filter((c) => c.s > 13.5);
  eq(types(late), '', '멎은(13초) 뒤 알림');
});

test('손짓은 알리지 않는다 — 손이 계속 움직여도', () => {
  const hands = (t, k) => front(t, { gs: 0.2, hl: 0.3, hr: 0.3, mea: 0.1, meb: 0.2 + 0.1 * (k % 2) });
  eq(types(play(script([[40, hands]]))), '', '손짓');
  ok(!('gesture' in C.COPY), '손짓 문구가 없다');
});

test('decide 는 meter 를 고치지 않는다 · 기록에 남는다', () => {
  const m = C.createMeter();
  const rows = script([[6, front], [5, side]]);
  const d = C.decide(m, C.conditions(rows, L), { enabled: true, voiceBusy: false, t0: 0 });
  eq(d.cue && d.cue.type, 'away', '알림');
  eq(m.log.length, 0, '옛 meter 그대로');
  eq(d.meter.log.length, 1, '새 meter 에 기록');
});

test('문구 — 해요체 · 짧게 · 감정 · 평가 낱말 없음 · 우선순위', () => {
  Object.entries(C.COPY).forEach(([k, v]) => {
    ok(/요$/.test(v), `${k} 해요체: ${v}`);
    ok(v.length <= 16, `${k} 짧게: ${v}`);
    ok(!/긴장|불안|자신감|초조|산만|나빠|틀렸|잘못|하세요|십시오|주세요/.test(v), `${k} 낱말: ${v}`);
  });
  eq(C.ORDER.join(','), 'frame,far,backlit,away,down,sway', '측정 문제가 먼저');
});

/* 자기검사 — 간격 규칙을 빼면 「20초 간격」 시험이 깨져야 한다 */
const GAP_LINE = 'if (c.t - m.lastAt < cfg.gapMs) return { meter: m, cue: null };';
test('간격 규칙을 빼면 20초 간격 시험이 깨진다', () => {
  if (!SRC.includes(GAP_LINE)) throw new Error(`decide 의 간격 줄이 바뀌었어요. 이 자기검사도 같이 고쳐야 해요: ${GAP_LINE}`);
  const B = load(SRC.replace(GAP_LINE, '')).C;
  const cues = play(script([[6, front], [5, side], [5, front], [5, side], [20, front], [5, side], [5, front]]), { api: B });
  if (cues.length <= 2) throw new Error('깨진 규칙도 두 번만 알렸어요 — 시험이 간격을 안 지킨다');
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
