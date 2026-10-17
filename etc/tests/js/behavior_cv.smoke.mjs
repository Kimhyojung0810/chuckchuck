/**
 * 발표 태도(베타) 카메라 판단의 순수 함수 스모크 — js/behavior_cv_logic.js (BehaviorCvLogic).
 *
 *   node etc/tests/js/behavior_cv.smoke.mjs
 *
 * 왜 있나 — 이 서버엔 웹캠이 없다. 특징 줄(얼굴 상자 · 눈 · 흐름)을 지어서 흘려 평활 · 구간 · 흔들림 대역 · 품질 게이트 ·
 * 근거 카드 · 서버 요약이 어떻게 나오는지 잡는다. 원본 파일을 vm 에 그대로 올린다 — 사본이 아니다.
 * 마지막 케이스는 하네스가 진짜로 회귀를 잡는지 스스로 검사한다 (booth_qa.smoke.mjs 와 같은 규율).
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const SRC = readFileSync(path.join(ROOT, 'main/web/js/behavior_cv_logic.js'), 'utf8');

function loadLogic(src) {
  const ctx = { console };
  vm.createContext(ctx);
  vm.runInContext(src, ctx, { filename: 'behavior_cv_logic.js' });
  return ctx.BehaviorCvLogic;
}
const L = loadLogic(SRC);

const cases = [];
const test = (name, fn) => cases.push({ name, fn });
const eq = (a, b, msg) => { if (a !== b) throw new Error(`${msg}: ${JSON.stringify(a)} !== ${JSON.stringify(b)}`); };
const ok = (c, msg) => { if (!c) throw new Error(msg); };

/* ── 줄 짓기 ── 5fps · 얼굴 폭 0.18 · 또렷 · 밝게 · 몸 영역 있음 */
const STEP = 200;
const front = (t, o = {}) => ({ t, src: 'F', side: 0, box: [0.41, 0.2, 0.18, 0.24], eyes: 2, ey: 0.39, ex: 0, br: 150, bl: 300, mv: 0.05, body: 0.05, hl: 0.01, hr: 0.01, hf: 0.01, ms: 15, ...o });
const lost = (t, o = {}) => ({ t, src: '', side: 0, box: null, eyes: 0, br: 150, bl: null, mv: 0.02, ms: 30, ...o });
/** 구간 대본 [[초, 줄 짓는 함수, 장]] → 줄들 */
function script(parts) {
  const rows = [];
  let t = 0;
  parts.forEach(([secs, make, slide]) => {
    const n = Math.round((secs * 1000) / STEP);
    for (let k = 0; k < n; k += 1) { rows.push({ ...make(t, k), seg: `s${slide || 1}` }); t += STEP; }
  });
  return rows;
}

test('날 방향 — 옆얼굴 · 눈 위치 · 이어 붙임 · 없음 (발표자 기준 왼쪽 · 오른쪽)', () => {
  eq(L.rawDir({ src: 'P', side: 1 }), 'right', '코가 화면 왼쪽 = 발표자 오른쪽');
  eq(L.rawDir({ src: 'P', side: -1 }), 'left', '뒤집어 찾은 옆얼굴');
  // 정면 Haar 는 20~35° 돌림까지 잡는다 — 눈 비낌으로 옆을 나누지 않는다(실험실 권고 4). 아래는 states() 가 얼굴 하강으로 본다
  eq(L.rawDir(front(0, { ex: 0.15 })), 'front', '눈 가운데가 비껴도 정면');
  eq(L.rawDir(front(0, { ey: 0.55 })), 'front', '눈 높이만으로는 아래가 아니다');
  eq(L.rawDir(front(0, { eyes: 0 })), 'front', '눈을 못 찾은 정면');
  eq(L.rawDir({ src: 'T' }), 'unknown', '이어 붙임');
  eq(L.rawDir(lost(0)), 'none', '없음');
});

test('Haar 가 정면을 몇 장 놓쳐도 청중 쪽으로 센다 (메우기)', () => {
  const rows = script([[30, (t, k) => (k % 7 === 3 ? lost(t) : front(t))]]);
  const r = L.analyze(rows);
  eq(r.metrics.gaze.ok, true, '잴 수 있음');
  ok(r.metrics.gaze.value > 0.97, `청중 쪽 비율 ${r.metrics.gaze.value}`);
  eq(r.metrics.lookaway.n, 0, '눈 뗀 구간 없음');
});

test('한 장짜리 옆얼굴 헛잡음은 방향을 바꾸지 않는다 (히스테리시스)', () => {
  const rows = script([[30, (t, k) => (k % 10 === 5 ? { ...front(t), src: 'P', side: 1, eyes: 0 } : front(t))]]);
  const seq = L.states(rows);
  eq(seq.filter((x) => x.state !== 'front').length, 0, '바뀐 줄');
});

test('4초 넘게 옆을 본 구간 → 장 · 초가 붙은 근거 카드 · 가장 먼저 고칠 한 가지', () => {
  const side = (t) => ({ ...front(t), src: 'P', side: -1, eyes: 0 });
  const rows = script([[10, front, 1], [4.4, side, 2], [8, front, 2], [4.4, side, 3], [8, front, 3], [4.4, side, 3], [20, front, 4]]);
  const r = L.analyze(rows);
  eq(r.metrics.lookaway.n, 3, '구간 수');
  eq(r.metrics.lookaway.word, '잦아요', '1분에 3번 넘게');
  const c = r.cards.filter((x) => x.kind === 'lookaway');
  ok(c.length >= 2, '카드');
  ok(/다른 곳/.test(c[0].observation) && !/왼쪽|오른쪽/.test(c[0].observation), `방향은 「다른 곳」 하나로: ${c[0].observation}`);
  ok(c[0].scene.where.endsWith('장') && c[0].scene.sec >= 9, `장면 ${JSON.stringify(c[0].scene)}`);
  ok(['관찰', 'observation'].some((k) => k in c[0]) && c[0].basis && c[0].conf && c[0].tip, '카드 여섯 칸');
  eq(r.first.kind, 'lookaway', '먼저 고칠 것');
  ok(r.first.slide === 2 || r.first.slide === 3, `장 ${r.first.slide}`);
  eq(r.areas.find((a) => a.key === 'gaze').level >= 1, true, '시선 갈래가 짚는다');
});

test('얼굴이 아래로 내려가며 사라지면 그 뒤는 「아래를 봄」 (자리 비움 아님)', () => {
  const drop = (t, k) => front(t, { box: [0.41, 0.2 + 0.03 * k, 0.18, 0.24], eyes: 0 });
  const rows = script([[10, front], [0.8, drop], [3, lost], [10, front]]);
  const r = L.analyze(rows);
  ok(r.metrics.down.value > 0.08, `아래 비율 ${r.metrics.down.value}`);
  ok(r.raw.downs.length === 1, '아래 구간 하나');
  eq(r.quality.presence, 1, '자리 비움으로 안 셌다');
});

test('정면으로 잡힌 채 얼굴이 기준선보다 내려가면 「아래를 봄」 — 눈을 못 찾아도', () => {
  const low = (t) => front(t, { box: [0.41, 0.28, 0.18, 0.24], eyes: 0 });
  const r = L.analyze(script([[15, front], [5, low], [15, front]]));
  ok(r.metrics.down.value > 0.1, `아래 비율 ${r.metrics.down.value}`);
  eq(r.raw.downs.length, 1, '아래 구간');
});

test('움직임 양은 프레임 차분(MEA) 몸 영역 — 3fps 로 느려져도 같은 낱말', () => {
  const at = (fps, meb) => {
    const rows = []; const step = 1000 / fps;
    for (let t = 0; t < 40000; t += step) rows.push({ ...front(Math.round(t)), meb: meb * (step / 200), seg: 's1' });
    return L.analyze(rows).metrics.movement;
  };
  eq(at(5, 0.02).word, '적어요', '가만히 5fps');
  eq(at(3, 0.02).word, '적어요', '가만히 3fps');
  eq(at(5, 0.25).word, '많아요', '많이 5fps');
  eq(at(3, 0.25).word, '많아요', '많이 3fps');
  eq(at(5, 0.25).look, false, '움직임 양은 연습 표시를 안 한다');
});

test('캐스케이드 없는 예비 모드 — 방향 지표는 까닭과 함께 빠지고 흔들림 · 움직임은 잰다', () => {
  const noc = (t) => ({ ...front(t, { box: [0.41 + 0.07 * Math.sin((2 * Math.PI * 0.6 * t) / 1000), 0.2, 0.18, 0.24], meb: 0.03 }), src: 'C', mode: 'noc', eyes: 0 });
  const r = L.analyze(script([[60, noc]]));
  ['gaze', 'lookaway', 'down'].forEach((k) => ok(!r.metrics[k].ok && /예비 모드/.test(r.metrics[k].why), `${k}: ${r.metrics[k].why}`));
  ok(r.metrics.sway.ok && r.metrics.movement.ok, '흔들림 · 움직임');
  eq(r.cards.filter((c) => c.kind === 'lookaway').length, 0, '눈 뗀 카드 없음');
  eq(L.summaryOf(r).events.filter((e) => e.k === 'lookaway').length, 0, '눈 뗀 장면 없음');
});

test('얼굴도 움직임도 오래 없으면 자리 비움 — 있는 시간이 모자라면 시선은 「잴 수 없었어요」', () => {
  const rows = script([[15, front], [40, lost]]);
  const r = L.analyze(rows);
  ok(r.quality.presence < 0.6, `있음 ${r.quality.presence}`);
  eq(r.metrics.gaze.ok, false, '게이트');
  eq(r.metrics.gaze.word, L.UNMEASURED, '낱말');
  ok(/짧았어요/.test(r.metrics.gaze.why), r.metrics.gaze.why);
});

test('어둡거나 흐리거나 짧으면 숫자 대신 까닭', () => {
  eq(L.analyze(script([[30, (t) => front(t, { br: 20 })]])).metrics.gaze.why.includes('어두'), true, '어두움');
  eq(L.analyze(script([[30, (t) => front(t, { bl: 4 })]])).metrics.gaze.why.includes('흐렸'), true, '흐림');
  eq(L.analyze(script([[12, front]])).status, 'unmeasured', '12초');
  eq(L.analyze(script([[30, (t) => front(t, { box: [0.45, 0.3, 0.06, 0.08] })]])).metrics.gaze.why.includes('멀어요'), true, '작은 얼굴 → 너무 멀어요');
  eq(L.analyze([]).status, 'none', '빈 기록');
});

test('흔들림 — 0.6Hz 좌우 반복은 잡고, 가만히 · 천천히 자리 옮김은 안 잡는다', () => {
  const sway = (t) => front(t, { box: [0.41 + 0.07 * Math.sin((2 * Math.PI * 0.6 * t) / 1000), 0.2, 0.18, 0.24] });
  const drift = (t) => front(t, { box: [0.2 + 0.4 * (t / 60000), 0.2, 0.18, 0.24] });
  const a = L.analyze(script([[60, sway]]));
  const b = L.analyze(script([[60, front]]));
  const c = L.analyze(script([[60, drift]]));
  ok(a.metrics.sway.ok && a.metrics.sway.value > 0.8, `흔들림 ${a.metrics.sway.value}`);
  ok(Math.abs(a.metrics.sway.amp - 0.07 / 0.18) < 0.08, `진폭 ${a.metrics.sway.amp}`);
  eq(b.metrics.sway.value, 0, '가만히');
  eq(c.metrics.sway.value, 0, '천천히 옮김');
});

test('역광(얼굴이 화면보다 많이 어두움)이면 방향 지표는 까닭과 함께 빠진다', () => {
  const r = L.analyze(script([[30, (t) => front(t, { br: 170, fb: 60 })]]));
  ok(!r.metrics.gaze.ok && /역광/.test(r.metrics.gaze.why), r.metrics.gaze.why);
});

test('고개를 돌리는 동안의 얼굴 자리 움직임은 흔들림으로 세지 않는다', () => {
  // 3초마다 옆으로 돌렸다 오기 — 옆얼굴 상자는 머리 가운데에서 비낀다
  const turn = (t, k) => (Math.floor(k / 8) % 2 ? { ...front(t, { box: [0.48, 0.2, 0.18, 0.24] }), src: 'P', side: 1, eyes: 0 } : front(t));
  const r = L.analyze(script([[60, turn]]));
  eq(r.raw.sway.filter((w) => w.on).length, 0, '켜진 흔들림 창');
  const a = L.analyze(script([[60, (t) => front(t, { box: [0.41 + 0.07 * Math.sin((2 * Math.PI * 0.6 * t) / 1000), 0.2, 0.18, 0.24] })]]));
  ok(Math.abs(a.raw.sway.find((w) => w.on).freq - 0.6) <= 0.05, `주파수 ${a.raw.sway.find((w) => w.on).freq}`);
});

test('손짓(gs) — 3장 중 2장 · 장 넘김 앞뒤 1초 · 화면 전체가 바뀐 장은 뺀다', () => {
  const rows = script([[10, (t, k) => front(t, { gs: k % 3 === 0 ? 0.08 : 0.0 }), 1], [10, (t) => front(t, { gs: 0.08 }), 2]]);
  const seq = L.states(rows);
  const f = L.gestureFlags(seq);
  const at = (sec) => f[seq.findIndex((x) => x.t >= sec * 1000)];
  eq(at(5), false, '3장 중 1장만 켜진 앞쪽');
  eq(at(10), null, '장 넘김 바로 뒤');
  eq(at(15), true, '뒤쪽');
  const spike = L.states(script([[10, (t) => front(t, { gs: 0.08, mea: 0.6 })]]));
  ok(L.gestureFlags(spike).every((v) => v === null), '화면 전체가 바뀐 장');
});

test('손짓 · 말소리 — 말할 때만 손이 움직이면 그렇게 쓴다 (많을수록 좋다고 안 쓴다)', () => {
  const rows = script([[60, (t, k) => {
    const speak = Math.floor(k / 25) % 2 === 0;
    return front(t, { sp: speak ? 1 : 0, hr: speak && k % 25 < 18 ? 0.12 : 0.005 });
  }]]);
  const r = L.analyze(rows);
  const g = r.metrics.gesture;
  ok(g.ok && g.speak > 0.5 && g.silent < 0.1, JSON.stringify(g));
  eq(g.look, false, '손짓은 연습 표시를 안 한다');
  const card = r.cards.find((x) => x.kind === 'gesture_speech');
  ok(card && /말하는 동안/.test(card.observation), '카드');
  ok(/많을수록 좋다는 뜻이 아니에요/.test(L.BASIS.gesture), '비교 기준 문구');
});

test('장별 집계 · 서버 요약은 숫자만, 크기 상한 안', () => {
  const rows = script(Array.from({ length: 80 }, (_, i) => [3, i % 4 === 0 ? (t) => ({ ...front(t), src: 'P', side: 1, eyes: 0 }) : front, i + 1]));
  const r = L.analyze(rows);
  ok(r.segs.length === 80, `장 ${r.segs.length}`);
  const s = L.summaryOf(r);
  const text = JSON.stringify(s);
  ok(text.length <= L.CFG.maxBytes, `크기 ${text.length}`);
  ok(s.segs.length <= L.CFG.maxSegs && s.events.length <= L.CFG.maxEvents, '목록 상한');
  ok(!('raw' in s) && !('cards' in s), '화면용 덩어리는 안 보낸다');
  eq(s.areas.length, 4, '갈래 넷');
  ok(L.METRIC_KEYS.every((k) => k in s.metrics), '지표 일곱');
});

test('화면 문구에 감정 · 성격 낱말이 없다', () => {
  const BAD = /불안|긴장|자신감|초조|감정|성격|당황|떨림|짜증|행복|슬픔|화가/;
  const texts = [];
  Object.values(L.WORDS).forEach((w) => texts.push(w.label, w.tip, ...w.words));
  Object.values(L.BASIS).forEach((b) => texts.push(b));
  const side = (t) => ({ ...front(t), src: 'P', side: 1, eyes: 0 });
  const r = L.analyze(script([[10, front, 1], [5, side, 2], [20, front, 3]]));
  r.cards.forEach((c) => texts.push(c.observation, c.value, c.basis, c.tip));
  texts.filter(Boolean).forEach((t) => ok(!BAD.test(t), `감정 낱말: ${t}`));
});

/* ── 리포트 카드 (js/behavior_report.js) ── */
const RSRC = readFileSync(path.join(ROOT, 'main/web/js/behavior_report.js'), 'utf8');
const R = (() => { const ctx = { console }; vm.createContext(ctx); vm.runInContext(RSRC, ctx, { filename: 'behavior_report.js' }); return ctx.BehaviorReport; })();

test('리포트 카드 — 베타 표시 · 먼저 살펴볼 한 가지 · 숫자는 자세히 보기 안 · 감정 낱말 없음', () => {
  const side = (t) => ({ ...front(t), src: 'P', side: -1, eyes: 0 });
  const res = L.analyze(script([[10, front, 1], [4.4, side, 2], [8, front, 2], [4.4, side, 3], [8, front, 3], [4.4, side, 3], [20, front, 4]]));
  const view = { ...res, raw: undefined, summary: L.summaryOf(res) };
  const html = R.html({ present: view, qa: null }, { titles: ['표지', '문제', '해법', '정리'] });
  ok(html.includes('베타 · 총점에 안 들어가요'), '베타 표시');
  ok(html.includes('먼저 살펴볼 한 가지') && /[23]장 · (문제|해법)/.test(html), '먼저 살펴볼 한 가지 + 장 제목');
  const [top, fold] = html.split('<details class="bh-fold">');
  ok(fold && /\d+%/.test(fold), '숫자는 자세히 보기 안에');
  ok(!/\d+%/.test(top.replace(/<details class="bh-more">[\s\S]*?<\/details>/g, '')), `화면 위쪽에 퍼센트가 없다`);
  ok(!/불안|긴장|자신감|초조|감정 상태/.test(html), '감정 낱말');
  const h = R.headline({ present: view });
  eq(h.status, 'ok', 'headline'); ok(h.first && h.first.slide, '첫 줄의 장'); ok(h.topEvidence.length >= 1, '근거 위 셋');
  // 숫자만 있는 요약(서버 보관본)도 그린다 — 근거 카드 없이
  ok(R.html({ present: view.summary }).includes('bh-areas'), '요약만으로도');
});

test('리포트 카드 — 카메라 분석 없음이면 까닭 한 줄, 리포트 2.0 입구 줄', () => {
  const none = L.none('카메라를 꺼 두고 발표해서 카메라 분석은 없어요');
  const html = R.html({ present: none, qa: null });
  ok(html.includes('카메라 분석 없음') && html.includes('카메라를 꺼 두고'), html);
  eq(R.headline({ present: none }).word, '카메라 분석 없음', '첫 줄 낱말');
  ok(R.rv2Row({ present: none }).includes('data-push="attitude"'), '입구 줄');
  eq(R.html(null), '', '기록 자체가 없으면 그리지 않는다');
});

/* 자기검사 — 히스테리시스를 빼면 「한 장짜리 헛잡음」 시험이 깨져야 한다 */
const DWELL_LINE = 'if (seq[i].t - seq[candStart].t + seq[i].dt >= cfg.minDwellMs) {';
test('히스테리시스를 빼면 한 장짜리 헛잡음 시험이 깨진다', () => {
  if (!SRC.includes(DWELL_LINE)) throw new Error(`hysteresis 가 바뀌었어요. 이 자기검사도 같이 고쳐야 해요: ${DWELL_LINE}`);
  const B = loadLogic(SRC.replace(DWELL_LINE, 'if (true) {'));
  const rows = script([[30, (t, k) => (k % 10 === 5 ? { ...front(t), src: 'P', side: 1, eyes: 0 } : front(t))]]);
  if (B.states(rows).filter((x) => x.state !== 'front').length === 0) throw new Error('깨진 규칙도 헛잡음을 걸렀어요 — 시험이 아무것도 안 지킨다');
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
