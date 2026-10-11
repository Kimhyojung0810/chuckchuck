/**
 * 부스 퍼널 신호(js/funnel.js) 스모크 — 브라우저 없이 window·fetch·sessionStorage 를 흉내 내 올린다.
 *
 *   node tests/js/funnel.smoke.mjs
 *
 * 잡는 것: 허용 목록 밖 단계·덱은 안 보낸다 · 같은 단계는 탭에서 한 번 · 본문은 {step, t, deck?} 뿐 ·
 * sessionStorage 가 던져도(사파리 사생활 보호·인앱) 화면이 안 죽는다 · fetch 가 실패해도 조용하다.
 * 마지막 케이스는 하네스가 진짜로 회귀를 잡는지 스스로 검사한다 (qa_live.smoke.mjs 와 같은 규율).
 * 이 파일은 pytest 가 수집하지 않는다.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const SRC = readFileSync(path.join(ROOT, 'demo/YEHS_demo/js/funnel.js'), 'utf8');

function memoryStorage() {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), _m: m };
}

function load({ storage = memoryStorage(), fetchImpl, now = () => 1_000_000 } = {}) {
  const calls = [];
  const window = {};
  Object.defineProperty(window, 'sessionStorage', {
    get() { if (storage === 'throw') throw new Error('SecurityError'); return storage; },
  });
  const ctx = {
    window,
    fetch: fetchImpl || ((url, init) => { calls.push({ url, init, body: JSON.parse(init.body) }); return Promise.resolve({ ok: true }); }),
    Date: { now },
    JSON, Math, Number, String, Promise,
  };
  vm.createContext(ctx);
  vm.runInContext(SRC, ctx);
  return { f: window.ccFunnel, calls, storage };
}

let failed = 0;
function check(name, fn) {
  try { fn(); console.log(`ok   ${name}`); } catch (e) { failed++; console.log(`FAIL ${name}\n     ${e.message}`); }
}
function eq(a, b, msg) {
  if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${msg || ''} ${JSON.stringify(a)} !== ${JSON.stringify(b)}`);
}

check('허용 단계만 보내고 본문은 step·t·deck 뿐', () => {
  const { f, calls } = load();
  eq(f('admin'), false, '모르는 단계');
  eq(f('tour_deck', { deck: '../x' }), true, '덱이 틀리면 덱만 뺀다');
  eq(calls.length, 1);
  eq(calls[0].url, '/api/v1/tour/event');
  eq(calls[0].init.method, 'POST');
  eq(calls[0].init.keepalive, true);
  eq(calls[0].init.headers['Content-Type'], 'application/json');
  eq(Object.keys(calls[0].body).sort(), ['step', 't']);
});

check('같은 단계는 한 번 — 덱이 다르면 따로', () => {
  const { f, calls } = load();
  f('hi'); f('hi'); f('tour_deck', { deck: 'sleep' }); f('tour_deck', { deck: 'sleep' }); f('tour_deck', { deck: 'battery-fastcharge' });
  eq(calls.map((c) => c.body.step + ':' + (c.body.deck || '')), ['hi:', 'tour_deck:sleep', 'tour_deck:battery-fastcharge']);
});

check('t 는 처음 신호부터 지난 초 — 페이지가 바뀌어도(같은 저장소) 이어진다', () => {
  const storage = memoryStorage();
  let t = 1_000_000;
  const a = load({ storage, now: () => t });
  a.f('hi');
  t += 42_400;
  const b = load({ storage, now: () => t });   // intro.html → index.html#/tour/deck
  b.f('tour_deck', { deck: 'sleep' });
  eq(a.calls[0].body.t, 0);
  eq(b.calls[0].body.t, 42);
  b.f('hi');
  eq(b.calls.length, 1, '앞 페이지에서 보낸 hi 는 다시 안 보낸다');
});

check('sessionStorage 가 던져도 죽지 않고 페이지 안에서는 한 번', () => {
  const { f, calls } = load({ storage: 'throw' });
  eq(f('team'), true); eq(f('team'), false);
  eq(calls.length, 1);
});

check('fetch 가 거절돼도 · 아예 던져도 조용하다', () => {
  load({ fetchImpl: () => Promise.reject(new Error('offline')) }).f('hi');
  load({ fetchImpl: () => { throw new Error('no fetch'); } }).f('hi');
});

check('단계 목록이 서버(demo/tour_events.py STEPS)와 같다', () => {
  const py = readFileSync(path.join(ROOT, 'demo/tour_events.py'), 'utf8');
  const block = py.slice(py.indexOf('STEPS: tuple'), py.indexOf('STEP_SET'));
  const server = [...block.matchAll(/^\s+"([a-z_]+)",/gm)].map((m) => m[1]);
  const { f } = load();
  eq(f.STEPS, server);
});

// 하네스 자기 검사 — 한 번만 보내는 규칙을 깨뜨린 사본은 잡혀야 한다
check('하네스가 회귀를 잡는다 (중복 보내기 사본)', () => {
  const broken = SRC.replace('if (alreadySent(key)) return false;', '');
  const calls = [];
  const window = { sessionStorage: memoryStorage() };
  const ctx = { window, fetch: (u, i) => { calls.push(i); return Promise.resolve(); }, Date, JSON, Math, Number, String, Promise };
  vm.createContext(ctx); vm.runInContext(broken, ctx);
  window.ccFunnel('hi'); window.ccFunnel('hi');
  if (calls.length !== 2) throw new Error('사본이 원본처럼 동작한다 — 하네스가 아무것도 못 잡는다');
});

if (failed) { console.log(`\n${failed} 실패`); process.exit(1); }
console.log('\nfunnel.smoke 통과');
