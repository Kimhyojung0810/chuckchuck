/**
 * 리허설 한 줄 흐름(js/rehearsal.js · #/rehearsal) 순수 함수 스모크 — 브라우저 없이.
 *
 *   node tests/js/rehearsal.smoke.mjs
 *
 * 왜 있나 — 리허설은 비전 리허설 · 분석 · 부스 화상판 · 리포트를 sessionStorage 표시 하나로 잇는다. 표시가 남으면 다음 #/new · #/qa 가
 * 리허설 배치로 뜨고(흐름 밖으로 새는 것), 분석 기다림의 줄 상태가 산출물과 어긋나면 「멈췄어요」 가 거짓말이 된다.
 * rehearsal.js 는 클래식 스크립트라 vm 에 원본 그대로 올린다 — 사본이 아니다.
 *
 * 마지막 케이스는 하네스가 진짜로 회귀를 잡는지 스스로 검사한다 (booth.smoke.mjs 와 같은 규율).
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const SRC = readFileSync(path.join(ROOT, 'demo/YEHS_demo/js/rehearsal.js'), 'utf8');
const APP = readFileSync(path.join(ROOT, 'demo/YEHS_demo/js/app.js'), 'utf8');
/** app.js 의 리허설 주소 함수 묶음(RH_SCREENS ~ rhFlagSet) — app.js 는 통째로 못 올려서 그 토막만 원본에서 잘라 온다 */
function appRouteSrc(app = APP) {
  const from = app.indexOf('const RH_SCREENS');
  const to = app.indexOf('function dismissF11Reveal');
  if (from < 0 || to < from) throw new Error('app.js 에서 리허설 주소 함수를 못 찾았어요');
  return app.slice(from, to);
}

function load(src) {
  const store = new Map();
  const ctx = {
    console,
    sessionStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) },
  };
  vm.createContext(ctx);
  vm.runInContext(src, ctx, { filename: 'rehearsal.js' });
  return { ctx, store };
}

const cases = [];
const test = (name, fn) => cases.push({ name, fn });
const eq = (a, b, msg) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${msg}: ${JSON.stringify(a)} !== ${JSON.stringify(b)}`); };

const { ctx: R, store } = load(SRC);

test('흐름 안 주소는 #/rehearsal 아래 전부 — 그 밖(일반 #/new · #/qa · #/report · 홈 · 부스 · 비전 · 통화)은 벗어난 것 (10-03 사용자)', () => {
  ['#/rehearsal', '#/rehearsal/', '#/rehearsal/occ', '#/rehearsal/new', '#/rehearsal/qa', '#/rehearsal/report', '#rehearsal/qa']
    .forEach((h) => eq(R.rehearsalLeaves(h), false, h));
  ['', '#/', '#/new', '#/qa', '#/report', '#/booth/qa', '#/booth/call', '#/vision', '#/temp', '#/test/qa', '#/rehearsals', '#/new/rehearsal']
    .forEach((h) => eq(R.rehearsalLeaves(h), true, h || '(빈 주소)'));
});

test('흐름 안 화면 주소 — rhHash 는 늘 #/rehearsal 아래', () => {
  eq(R.rhHash(), '#/rehearsal', '고르기');
  eq(['new', 'qa', 'report', 'occ'].map((s) => R.rhHash(s)), ['#/rehearsal/new', '#/rehearsal/qa', '#/rehearsal/report', '#/rehearsal/occ'], '화면');
});

test('app.js routeParts — #/rehearsal/<화면> 은 그 화면을 그리고, 나머지 주소는 예전 그대로', () => {
  const store = new Map();
  const A = { location: { hash: '' }, sessionStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null) } };
  vm.createContext(A);
  vm.runInContext(`${appRouteSrc()}\nfunction rhFlowOn() { return false; }`, A, { filename: 'app.js(리허설 주소)' });
  eq(A.routeParts('#/rehearsal/new'), ['new'], 'new');
  eq(A.routeParts('#/rehearsal/qa'), ['qa'], 'qa');
  eq(A.routeParts('#/rehearsal/report'), ['report'], 'report');
  eq(A.routeParts('#/rehearsal'), ['rehearsal'], '고르기');
  eq(A.routeParts('#/rehearsal/occ'), ['rehearsal', 'occ'], '어떤 발표인가요는 리허설 제 화면');
  eq(A.routeParts('#/report/last'), ['report', 'last'], '일반 리포트 하위 주소');
  eq(A.routeParts('#/new/reset'), ['new', 'reset'], '일반 초기화');
  eq(A.routeParts('#/booth/qa'), ['booth', 'qa'], '부스는 그대로');
  // 화면을 옮기는 주소 — 리허설 표시가 켜져 있을 때만 /rehearsal 아래
  eq(['new', 'qa', 'report'].map((s) => A.screenHash(s)), ['#/new', '#/qa', '#/report'], '흐름 밖');
  store.set('cheokcheok:rehearsal-flow', '1');
  eq(['new', 'qa', 'report'].map((s) => A.screenHash(s)), ['#/rehearsal/new', '#/rehearsal/qa', '#/rehearsal/report'], '흐름 안');
  A.location.hash = '#/rehearsal/new';
  eq([A.onScreen('new'), A.onScreen('qa')], [true, false], '지금 화면');
  A.location.hash = '#/new/';
  eq(A.onScreen('new'), true, '#/new/ 도 같은 화면');
});

test('app.js 와 rehearsal.js 가 같은 리허설 표시 키를 쓴다', () => {
  const key = (APP.match(/const RH_FLOW_FLAG = '([^']+)'/) || [])[1];
  eq(key, R.REHEARSAL_FLOW_KEY || SRC.match(/const REHEARSAL_FLOW_KEY = '([^']+)'/)[1], '키');
});

test('켜짐 표시 — 켜고 끄면 키가 남지 않는다 (app.js LAZY_FLOW_FLAGS 가 「1」 로 읽는다)', () => {
  R.rehearsalFlowSet(true);
  eq(store.get('cheokcheok:rehearsal-flow'), '1', '켜짐');
  eq(R.rehearsalFlowOn(), true, '읽기');
  R.rehearsalFlowSet(false);
  eq(store.has('cheokcheok:rehearsal-flow'), false, '꺼지면 키가 없다');
  eq(R.rehearsalFlowOn(), false, '꺼짐');
});

test('분석 기다림 — 막 시작(queued)은 첫 줄만 도는 중', () => {
  eq(R.rehearsalWaitStates({ phase: 'queued' }), { rec: 'run', stt: 'wait', align: 'wait', flow: 'wait', questions: 'wait' }, '줄');
});

test('받아쓰기 중 → 앞줄은 끝, 받아쓰기만 도는 중', () => {
  eq(R.rehearsalWaitStates({ phase: 'stt' }), { rec: 'done', stt: 'run', align: 'wait', flow: 'wait', questions: 'wait' }, '줄');
});

test('개념 · 그래프 · 정합 단계는 한 줄(자료와 내 말을 맞춰 봐요)이 돈다', () => {
  ['concepts', 'graph_done', 'align'].forEach((p) => eq(R.rehearsalWaitStates({ phase: p, out: { transcript: { by_slide: [] } } }).align, 'run', p));
});

test('질문 재료가 모이면(qaReady) 분석 넷은 끝 · 질문 줄이 돈다 → 질문이 살아 있으면 끝', () => {
  const s = R.rehearsalWaitStates({ phase: 'flow_done', qaReady: true });
  eq([s.rec, s.stt, s.align, s.flow, s.questions], ['done', 'done', 'done', 'done', 'run'], '만드는 중');
  eq(R.rehearsalWaitStates({ phase: 'done', qaReady: true, questionsReady: true }).questions, 'done', '질문 준비');
});

test('분석이 실패하면 아직 안 끝난 첫 줄이 실패 — 받은 받아쓰기는 끝으로 남는다', () => {
  const s = R.rehearsalWaitStates({ phase: 'error', out: { transcript: { by_slide: [] } } });
  eq([s.rec, s.stt, s.align, s.flow], ['done', 'done', 'fail', 'wait'], '줄');
});

test('받아쓰기에서 멈추면 받아쓰기 줄이 실패 — 녹음이 있으면 녹음 정리 줄은 끝 (10-03 F5)', () => {
  const s = R.rehearsalWaitStates({ phase: 'error', hasTake: true, lastPhase: 'stt' });
  eq([s.rec, s.stt, s.align, s.flow], ['done', 'fail', 'wait', 'wait'], '줄');
});

test('받아쓰기 중 새로고침(실패 직전 단계를 모름)도 녹음이 있으면 받아쓰기 줄이 실패', () => {
  const s = R.rehearsalWaitStates({ phase: 'error', hasTake: true });
  eq([s.rec, s.stt], ['done', 'fail'], '줄');
});

test('녹음 정리(encoding)에서 멈췄으면 첫 줄이 실패 — 녹음이 있어도', () => {
  const s = R.rehearsalWaitStates({ phase: 'error', hasTake: true, lastPhase: 'encoding' });
  eq([s.rec, s.stt], ['fail', 'wait'], '줄');
});

test('정합에서 멈추면 정합 줄이 실패', () => {
  const s = R.rehearsalWaitStates({ phase: 'error', hasTake: true, lastPhase: 'align', out: { transcript: { by_slide: [] } } });
  eq([s.rec, s.stt, s.align, s.flow], ['done', 'done', 'fail', 'wait'], '줄');
});

test('질문 재료가 모인 뒤 실패(error 지만 qaReady)는 분석 실패가 아니다', () => {
  const s = R.rehearsalWaitStates({ phase: 'error', qaReady: true });
  eq(Object.values(s).includes('fail'), false, '실패 없음');
});

test('질문 생성 실패 — 만드는 중이면 아직 실패가 아니다', () => {
  eq(R.rehearsalWaitStates({ phase: 'done', qaReady: true, buildFailed: true, building: false }).questions, 'fail', '실패');
  eq(R.rehearsalWaitStates({ phase: 'done', qaReady: true, buildFailed: true, building: true }).questions, 'run', '다시 만드는 중');
});

test('한 단계만 죽고 닫힌 분석(partial)도 질문 재료가 모자라면 멈춘 것 — 개념 · 그래프 · 정합이면 맞춰 보기 줄, 흐름이면 흐름 줄 (F1)', () => {
  const a = R.rehearsalWaitStates({ phase: 'partial', out: { transcript: { by_slide: [] } } });
  eq([a.rec, a.stt, a.align, a.flow], ['done', 'done', 'fail', 'wait'], '정합 전');
  const f = R.rehearsalWaitStates({ phase: 'partial', out: { transcript: {}, graph: {}, alignment: {} } });
  eq([f.rec, f.stt, f.align, f.flow], ['done', 'done', 'done', 'fail'], '흐름');
});

test('partial 이어도 질문 재료가 다 모였으면(리포트 축만 실패) 멈춘 게 아니다', () => {
  const s = R.rehearsalWaitStates({ phase: 'partial', qaReady: true });
  eq(Object.values(s).includes('fail'), false, '실패 없음');
});

test('새로고침으로 단계가 멈춘 세션도 산출물로 판단한다 (phase 가 비어도 정합이 있으면 끝)', () => {
  const s = R.rehearsalWaitStates({ phase: '', out: { transcript: {}, alignment: {}, flow: {} } });
  eq([s.rec, s.stt, s.align, s.flow], ['done', 'done', 'done', 'done'], '줄');
});

test('#/rehearsal/qa 를 되살릴 수 없으면 — 자료가 있으면 #/rehearsal/new, 없으면 발표 고르기. 질문이 살아 있으면 그대로', () => {
  eq(R.rehearsalQaFallback({ live: true }), null, '살아 있음');
  eq(R.rehearsalQaFallback({ ended: true }), null, '끝난 기록');
  eq(R.rehearsalQaFallback({ hasDeck: true }), '#/rehearsal/new', '자료 있음');
  eq(R.rehearsalQaFallback({}), '#/rehearsal', '빈 탭');
});

test('하네스 자가 검사 — 벗어남 판단이 예전(화면 이름)으로 돌아가면 첫 케이스가 잡는다', () => {
  const at = SRC.indexOf('function rehearsalLeaves(hash) {');
  if (at < 0) throw new Error('rehearsalLeaves 를 못 찾았어요');
  const broken = load(SRC.replace(/function rehearsalLeaves\(hash\) \{[^}]*\}/, "function rehearsalLeaves(hash) { return !/^#\\/?(rehearsal|new|qa)(\\/|$)/.test(String(hash || '')); }")).ctx;
  let caught = false;
  try { eq(broken.rehearsalLeaves('#/qa'), true, '#/qa'); } catch (_) { caught = true; }
  if (!caught) throw new Error('망가뜨린 원본을 못 잡았어요 — 하네스가 원본을 안 읽고 있어요');
});

let failed = 0;
for (const { name, fn } of cases) {
  try { fn(); console.log(`ok   ${name}`); } catch (err) { failed += 1; console.log(`FAIL ${name}\n     ${err.message}`); }
}
console.log(`\n${cases.length - failed}/${cases.length} 통과`);
process.exit(failed ? 1 : 0);
