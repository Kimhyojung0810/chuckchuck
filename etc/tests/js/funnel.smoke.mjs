/**
 * 부스 퍼널 신호(js/funnel.js) 스모크 — 브라우저 없이 window·fetch·sessionStorage 를 흉내 내 올린다.
 *
 *   node etc/tests/js/funnel.smoke.mjs
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

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const SRC = readFileSync(path.join(ROOT, 'main/web/js/funnel.js'), 'utf8');

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

check('단계 목록이 서버(main/server/tour_events.py STEPS)와 같다', () => {
  const py = readFileSync(path.join(ROOT, 'main/server/tour_events.py'), 'utf8');
  const block = py.slice(py.indexOf('STEPS: tuple'), py.indexOf('STEP_SET'));
  const server = [...block.matchAll(/^\s+"([a-z_]+)",/gm)].map((m) => m[1]);
  const { f } = load();
  eq(f.STEPS, server);
});

// perf-security-copy-r1-1 — 응답 전에 markSent 를 해서 429 로 떨어진 단계를 그 탭에서 다시 안 보냈다
const asyncChecks = [];
function checkAsync(name, fn) { asyncChecks.push([name, fn]); }
const tick = () => new Promise((r) => setImmediate(r));

function loadWith(responses) {
  const calls = [];
  const timers = [];
  const window = {};
  Object.defineProperty(window, 'sessionStorage', { get() { return storage; } });
  const storage = memoryStorage();
  const ctx = {
    window, JSON, Math, Number, String, Promise, Date: { now: () => 1_000_000 },
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    fetch: (url, init) => {
      calls.push(JSON.parse(init.body));
      const r = responses.shift() || { ok: true, status: 204 };
      return r === 'reject' ? Promise.reject(new Error('offline')) : Promise.resolve(r);
    },
  };
  vm.createContext(ctx);
  vm.runInContext(SRC, ctx);
  return { f: window.ccFunnel, calls, timers };
}
const res429 = (sec) => ({ ok: false, status: 429, headers: { get: (k) => (k.toLowerCase() === 'retry-after' ? String(sec) : null) } });

checkAsync('429 면 Retry-After 뒤에 한 번 더 보낸다', async () => {
  const { f, calls, timers } = loadWith([res429(3)]);
  f('hi');
  await tick();
  eq(timers.map((t) => t.ms), [3000], 'Retry-After 초만큼 기다린다');
  timers[0].fn();
  await tick();
  eq(calls.map((c) => c.step), ['hi', 'hi']);
  eq(f('hi'), false, '두 번째가 닿았으니 다시 안 보낸다');
});

checkAsync('다시 보내도 429 거나 망이 끊기면 보낸 표시를 지운다 — 다음에 그 단계를 부르면 다시 간다', async () => {
  const a = loadWith([res429(2), res429(2)]);
  a.f('team');
  await tick(); a.timers[0].fn(); await tick();
  eq(a.timers.length, 1, '다시 보내기는 한 번뿐');
  eq(a.f('team'), true);
  const b = loadWith(['reject']);
  b.f('intro');
  await tick();
  eq(b.f('intro'), true, '망 실패 뒤에는 다시 보낸다');
  const c = loadWith([{ ok: false, status: 400 }]);
  c.f('intro');
  await tick();
  eq(c.f('intro'), false, '400(본문이 틀림)은 다시 보내도 같으니 지우지 않는다');
});

checkAsync('Retry-After 가 너무 길면(60초 넘게) 기다리지 않고 표시만 지운다', async () => {
  const { f, timers } = loadWith([res429(300)]);
  f('hi');
  await tick();
  eq(timers.length, 0);
  eq(f('hi'), true);
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

for (const [name, fn] of asyncChecks) {
  try { await fn(); console.log(`ok   ${name}`); } catch (e) { failed++; console.log(`FAIL ${name}\n     ${e.message}`); }
}

if (failed) { console.log(`\n${failed} 실패`); process.exit(1); }
console.log('\nfunnel.smoke 통과');
