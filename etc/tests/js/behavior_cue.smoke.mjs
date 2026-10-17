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

test('숙인 동안 얼굴을 잠깐 놓쳐도(머리 추적이 6초에 끊김) 아래로 이어 센다 — 실험실 c01 모양', () => {
  const cues = play(script([[8, front], [6.5, down], [0.8, (t) => lost(t)], [1, lost], [3, down], [6, front]]));
  eq(types(cues), 'down', '아래 6.5 · 놓침 1.8 · 아래 3');
  // 자리를 뜨는 사람은 옆으로 걸어 나간다 — 놓치기 직전 얼굴이 옆으로 움직였으면 엔진은 「아래」 를 들지 않는다(lostDownLateral).
  // 옆 이동 없이 숙인 채 사라지는 것은 오래 대본을 읽는 것과 엔진이 가를 수 없어 「아래」 로 든다(lostDownHoldMs 8초, 바퀴 5)
  let x0 = null;
  const walkOut = (t) => { if (x0 === null) x0 = t; return down(t, { box: [0.41 + 0.6 * FW * ((t - x0) / 800), 0.2 + 0.4 * 0.24, FW, 0.24] }); };
  eq(types(play(script([[8, front], [4, down], [0.8, walkOut], [8, lost], [6, front]]))), 'frame', '숙였다가 옆으로 걸어 나가면 아래가 아니라 화면 밖');
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

test('목소리 말풍선 — 새로 뜨거나 바뀌면 3초 미루고, 같은 말풍선이 오래 떠 있으면 막지 않는다', () => {
  let g = { text: '', at: -Infinity };
  const at = (text, now) => { const r = C.voiceGate(g, text, now); g = r.g; return r; };
  const a = at('하암~', 1000);
  ok(a.busy && a.fresh, '막 떴다 — 미루고 떠 있던 자세 알림은 걷는다');
  ok(at('하암~', 3500).busy && !at('하암~', 3600).fresh, '3초 안 — 아직 미룸 · 새로 뜬 건 아님');
  ok(!at('하암~', 4200).busy, '3초 지나 같은 말풍선 — 막지 않는다');
  const b = at('잘 안 들려', 9000);
  ok(b.busy && b.fresh, '다른 반응으로 바뀜 — 다시 미룸');
  ok(at('', 12500).busy, '사라진 직후 1.5초 — 미룸');
  ok(!at('', 14100).busy, '사라지고 1.5초 지나면 — 됨');
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
/* ── 알림 뒤 돌아오기 (리포트 「발표 중 알림」, 바퀴 6) ── play 로 알림 시각을 얻고, 그 뒤 줄로 backAfter */
function backOf(rows, type, opts = {}) {
  const cue = play(rows).find((c) => c.type === type);
  ok(cue, `${type} 알림이 안 떴다`);
  return { cue, back: C.backAfter(L.states(rows), cue.s * 1000, type, L, opts) };
}

test('옆 6초 → 알림 뒤 정면으로 돌아오기까지 ≈ (옆 끝 − 알림 시각)', () => {
  const { cue, back } = backOf(script([[8, front], [6, side], [10, front]]), 'away');
  ok(typeof back === 'number', `숫자가 아니다: ${back}`);
  const want = 14000 - cue.s * 1000;
  ok(Math.abs(back - want) <= 600, `돌아오기 ${back}ms (기대 ≈ ${want})`);
});

test('아래 11초 → 고개를 들기까지 ≈ (아래 끝 − 알림 시각) · 한두 장 정면 깜박임은 돌아온 것이 아님', () => {
  const rows = script([[8, front], [11, (t, k) => (k === 45 ? front(t) : down(t))], [10, front]]);
  const { cue, back } = backOf(rows, 'down');
  const want = 19000 - cue.s * 1000;
  ok(typeof back === 'number' && Math.abs(back - want) <= 800, `고개 들기 ${back}ms (기대 ≈ ${want}, 알림 ${cue.s}초)`);
});

test('알림 뒤 15초 넘게 옆이면 late · 그 전에 기록이 끝나면 final 에서 end, 아니면 아직 모름(null)', () => {
  const longRows = script([[8, front], [25, side], [5, front]]);
  eq(backOf(longRows, 'away').back, 'late', '25초 옆');
  const cut = script([[8, front], [9, side]]);
  eq(backOf(cut, 'away').back, null, '끝나지 않은 기록');
  eq(backOf(cut, 'away', { final: true }).back, 'end', '기록 끝');
});

test('흔들림 → 멎기까지(4초 창 기준, ±1초) · 역광 · 멂은 재지 않음(na)', () => {
  const rows = script([[6, front], [16, swayAt(0.6, 0.3)], [12, front]]);
  const { cue, back } = backOf(rows, 'sway');
  const want = 22000 - cue.s * 1000;
  ok(typeof back === 'number' && Math.abs(back - want) <= 2000, `멎기 ${back}ms (기대 ≈ ${want}, 알림 ${cue.s}초)`);
  eq(C.backAfter(L.states(rows), 5000, 'far', L), 'na', '멂');
  eq(C.backAfter(L.states(rows), 5000, 'backlit', L), 'na', '역광');
});

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
