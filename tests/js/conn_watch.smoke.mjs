/**
 * 연결 감시(js/conn_watch.js) 배너 스모크 — 브라우저 없이 문서 한 조각만 흉내 낸다.
 *
 *   node tests/js/conn_watch.smoke.mjs
 *
 * 왜 있나 — 부스 투어(#/tour/*)는 서버가 필요 없는 녹화 재생인데, 폰 망이 끊기면 개발자 말 배너
 * 「포트 연결(VS Code Ports·SSH 터널)을 다시 이으면…」 이 진행 막대를 가렸다 (10-12 2차 perf-security-copy-r2-4).
 * 투어에서는 배너를 띄우지 않고, 공개 방문객에게는 「인터넷 연결」 말로, 개발 안내는 팀 브라우저에만.
 * 마지막 케이스는 하네스가 진짜로 회귀를 잡는지 스스로 검사한다.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const SRC = readFileSync(path.join(ROOT, 'demo/YEHS_demo/js/conn_watch.js'), 'utf8');

/** 문서 한 조각 — getElementById · createElement · body.appendChild 만. 배너 글은 innerHTML 로 본다 */
function load(src, { hash = '', team = false } = {}) {
  const nodes = new Map();
  const mk = () => {
    const el = {
      id: '', className: '', innerHTML: '', attrs: {}, removed: false,
      setAttribute(k, v) { this.attrs[k] = v; },
      querySelector() { return { addEventListener() {} }; },
      remove() { this.removed = true; nodes.delete(this.id); },
      classList: { contains: () => false },
    };
    return el;
  };
  const document = {
    hidden: false, readyState: 'complete',
    getElementById: (id) => nodes.get(id) || null,
    createElement: () => mk(),
    body: { appendChild: (el) => { nodes.set(el.id, el); } },
    addEventListener() {},
  };
  const window = { addEventListener() {}, dispatchEvent() {}, ChuckchuckBridge: { qaApiBase: () => '' } };
  const sandbox = {
    window, document, location: { hash }, console: { warn() {}, info() {} },
    setTimeout: () => 0, clearTimeout() {}, CustomEvent: function CustomEvent() {}, AbortController, fetch: async () => ({ ok: false }),
  };
  if (team) sandbox.ccTeam = true;
  vm.runInNewContext(src + ';globalThis.__c = { connMarkDown, connState };', sandbox, { filename: 'conn_watch.js' });
  return { api: sandbox.__c, banner: () => nodes.get('connBanner') || null };
}

const cases = [];
const test = (name, fn) => cases.push({ name, fn });
const ok = (v, msg) => { if (!v) throw new Error(msg); };

function suite(src) {
  const out = [];
  const t = (name, fn) => out.push({ name, fn: () => fn(src) });
  t('투어(#/tour/*)에서는 끊겨도 배너를 띄우지 않는다 — 녹화 재생은 서버 없이 돈다', (s) => {
    for (const hash of ['#/tour', '#/tour/analysis', '#/tour/qa/2']) {
      const w = load(s, { hash });
      w.api.connMarkDown();
      ok(!w.banner(), `${hash}: 배너가 떴어요`);
    }
  });
  t('공개 방문객에게는 「인터넷 연결」 말 — VS Code · SSH 안내는 안 보인다', (s) => {
    const w = load(s, { hash: '#/rehearsal' });
    w.api.connMarkDown();
    ok(w.banner(), '투어 밖에서는 배너가 떠야 해요');
    ok(/인터넷 연결/.test(w.banner().innerHTML), `공개 문구가 아니에요: ${w.banner().innerHTML}`);
    ok(!/VS Code|SSH/.test(w.banner().innerHTML), '공개 방문객에게 개발 안내가 보여요');
  });
  t('팀 브라우저에는 포트 연결 안내를 그대로', (s) => {
    const w = load(s, { hash: '#/qa', team: true });
    w.api.connMarkDown();
    ok(/VS Code/.test(w.banner().innerHTML), '팀에게는 포트 연결 안내가 보여야 해요');
  });
  return out;
}

suite(SRC).forEach((c) => test(c.name, c.fn));

test('하네스 자기 검사 — 투어 막이를 지운 파일을 넣으면 잡는다', () => {
  const broken = SRC.replace(/if \(connOnTour\(\)\)[^\n]*\n/g, '');
  ok(broken !== SRC, '고장 낼 줄(connOnTour)을 못 찾았어요 — 막이 이름이 바뀌었으면 여기도 고친다');
  const failed = suite(broken).filter((c) => { try { c.fn(); return false; } catch (_) { return true; } });
  ok(failed.length > 0, '고장 낸 conn_watch 가 스모크를 통과했어요');
});

let pass = 0, fail = 0;
for (const c of cases) {
  try { c.fn(); pass += 1; console.log(`  ✓ ${c.name}`); }
  catch (e) { fail += 1; console.log(`  ✗ ${c.name}\n    ${String(e.message).split('\n').join('\n    ')}`); }
}
console.log(`\n${pass}/${pass + fail} 통과`);
process.exit(fail ? 1 : 0);
