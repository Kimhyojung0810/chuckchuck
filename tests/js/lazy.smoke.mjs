/**
 * 나중에 받는 파일(js/lazy.js · index.html 의 #lazyAssets) 스모크.
 *
 *   node tests/js/lazy.smoke.mjs
 *
 * 왜 있나 — 첫 화면을 가볍게 하려고 베타 화면(통화·비전·부스)·랜딩·모션·pdf.js 를 처음 부르는 목록에서 뺐다.
 * 그 대가로 생길 수 있는 사고를 브라우저 없이 잡는다.
 *  ① 템플릿에 적은 파일이 실제로 있는가 (오타면 그 화면이 「불러오지 못했어요」로 끝난다)
 *  ② 같은 파일을 처음부터 부르기도 하는가 (두 번 실행되면 const 중복 선언으로 그 파일이 통째로 죽는다)
 *  ③ app.js 의 LAZY_FLOW_FLAGS 가 각 흐름 파일의 sessionStorage 키와 같은가
 *     (다르면 흐름을 켠 채 새로 고친 #/new·#/qa 가 통화·비전 배치를 잃는다)
 *  ④ 번들 파일끼리 적은 순서가 원래 순서와 같은가 (booth_cv → booth_qa · vision_cue → vision_rehearsal)
 *  ⑤ lazy.js 를 가짜 DOM 에 올려 load() 가 순서·중복·실패 재시도를 지키는가
 *
 * 마지막 케이스는 하네스가 진짜로 회귀를 잡는지 스스로 검사한다 (booth.smoke.mjs 와 같은 규율).
 */
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const WEB = path.join(ROOT, 'demo/YEHS_demo');
const read = (rel) => readFileSync(path.join(WEB, rel), 'utf8');

const cases = [];
const test = (name, fn) => cases.push({ name, fn });
const eq = (a, b, msg) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${msg}: ${JSON.stringify(a)} !== ${JSON.stringify(b)}`); };
const ok = (v, msg) => { if (!v) throw new Error(msg); };

/** index.html → { lazy: [{bundle, url}], eager: [url] } */
function parseIndex(html) {
  const m = html.match(/<template id="lazyAssets">([\s\S]*?)<\/template>/);
  ok(m, '#lazyAssets 템플릿이 없어요');
  const tpl = m[1];
  const rest = html.replace(m[0], '');
  const refs = (s) => [...s.matchAll(/<(?:script|link)\b[^>]*?\b(?:src|href)="([^"]+)"[^>]*>/g)].map((x) => x[0]);
  const lazy = refs(tpl).map((tag) => ({
    bundle: (tag.match(/data-bundle="([^"]+)"/) || [])[1],
    url: tag.match(/\b(?:src|href)="([^"]+)"/)[1],
  }));
  const eager = refs(rest).map((tag) => tag.match(/\b(?:src|href)="([^"]+)"/)[1]);
  return { lazy, eager };
}
const bare = (u) => u.split('?')[0];

function flagsInApp(appJs) {
  const m = appJs.match(/const LAZY_FLOW_FLAGS = \[([^\]]*)\]/);
  ok(m, 'app.js 에 LAZY_FLOW_FLAGS 가 없어요');
  return [...m[1].matchAll(/'([^']+)'/g)].map((x) => x[1]).sort();
}
function flagsInFlows() {
  const pick = (file, name) => read(file).match(new RegExp(`const ${name} = '([^']+)'`))[1];
  return [pick('js/call_flow.js', 'CALL_FLOW_KEY'), pick('js/vision_rehearsal.js', 'VISION_FLOW_KEY'),
    pick('js/booth_qa.js', 'BOOTH_QA_KEY'), pick('js/rehearsal.js', 'REHEARSAL_FLOW_KEY')].sort();
}

function checkIndex(html) {
  const { lazy, eager } = parseIndex(html);
  const problems = [];
  lazy.forEach(({ bundle, url }) => {
    if (!bundle) problems.push(`${url}: data-bundle 없음`);
    if (!/^https?:/.test(url) && !existsSync(path.join(WEB, bare(url)))) problems.push(`${url}: 파일 없음`);
    if (eager.some((e) => bare(e) === bare(url))) problems.push(`${url}: 처음부터도 부름 (두 번 실행)`);
  });
  return problems;
}

const HTML = read('index.html');

test('① ② 템플릿의 파일은 다 있고, 처음부터 부르는 목록과 겹치지 않는다', () => {
  eq(checkIndex(HTML), [], '문제');
});

test('lazy.js 가 app.js 보다 먼저 온다 (route() 가 ccLazy 를 본다)', () => {
  const { eager } = parseIndex(HTML);
  const i = eager.findIndex((u) => bare(u) === 'js/lazy.js');
  const j = eager.findIndex((u) => bare(u) === 'js/app.js');
  ok(i >= 0 && j >= 0 && i < j, `lazy.js ${i} · app.js ${j}`);
});

test('③ app.js LAZY_FLOW_FLAGS == 흐름 파일들의 sessionStorage 키', () => {
  eq(flagsInApp(read('js/app.js')), flagsInFlows(), '키');
});

test('④ 번들 안의 순서 — 먼저 있어야 하는 파일이 먼저', () => {
  const beta = parseIndex(HTML).lazy.filter((x) => x.bundle === 'beta').map((x) => bare(x.url));
  const before = (a, b) => ok(beta.indexOf(a) >= 0 && beta.indexOf(a) < beta.indexOf(b), `${a} 가 ${b} 앞에 없어요`);
  before('js/booth_cv.js', 'js/booth_qa.js');
  before('js/vision_cue.js', 'js/vision_rehearsal.js');
});

test('app.js 가 부르는 베타 화면이 모두 LAZY_ROUTE_BUNDLES 에 있다', () => {
  const app = read('js/app.js');
  const m = app.match(/const LAZY_ROUTE_BUNDLES = \{([^}]*)\}/);
  ok(m, 'LAZY_ROUTE_BUNDLES 없음');
  ['temp', 'vision', 'booth', 'landing'].forEach((k) => ok(new RegExp(`\\b${k}:`).test(m[1]), `${k} 빠짐`));
});

/* ── ⑤ lazy.js 를 가짜 DOM 에 올린다 ─────────────────────────────────────── */

function fakeDom(tplNodes, { fail = new Set() } = {}) {
  const appended = [];
  const mk = (tag) => {
    const el = { tagName: tag.toUpperCase(), attrs: {}, removed: false,
      setAttribute(k, v) { this.attrs[k] = v; }, remove() { this.removed = true; } };
    return el;
  };
  const parent = {
    appendChild(el) {
      appended.push(el);
      const url = el.src || el.href;
      queueMicrotask(() => (fail.has(url) ? el.onerror() : el.onload()));
    },
  };
  const tpl = {
    content: {
      querySelectorAll(sel) {
        const want = sel.match(/data-bundle="([^"]+)"/)[1];
        return tplNodes.filter((n) => n.bundle === want).map((n) => ({
          tagName: n.tag, getAttribute: (k) => (k === 'data-bundle' ? n.bundle : n[k] || null),
        }));
      },
    },
  };
  const document = { head: parent, body: parent, readyState: 'complete', createElement: mk,
    getElementById: (id) => (id === 'lazyAssets' ? tpl : null) };
  const win = { document, console: { warn() {} }, setTimeout, queueMicrotask, addEventListener() {} };
  win.window = win;
  return { win, appended };
}
function loadLazy(dom) {
  vm.createContext(dom.win);
  vm.runInContext(read('js/lazy.js'), dom.win, { filename: 'lazy.js' });
  return dom.win.ccLazy;
}
const NODES = [
  { tag: 'LINK', bundle: 'beta', href: 'css/a.css?v=1' },
  { tag: 'SCRIPT', bundle: 'beta', src: 'js/a.js?v=1' },
  { tag: 'SCRIPT', bundle: 'beta', src: 'js/b.js?v=1' },
  { tag: 'SCRIPT', bundle: 'pdf', src: 'https://cdn/pdf.js', 'data-worker': 'https://cdn/w.js' },
];

test('⑤ load() — 적은 순서대로 붙이고 스크립트는 async=false, 두 번 불러도 한 번', async () => {
  const dom = fakeDom(NODES);
  const L = loadLazy(dom);
  const [a, b] = await Promise.all([L.load('beta'), L.load('beta')]);
  ok(a && b && L.loaded('beta'), '받았다고 해야 한다');
  eq(dom.appended.map((e) => e.src || e.href), ['css/a.css?v=1', 'js/a.js?v=1', 'js/b.js?v=1'], '붙인 순서');
  ok(dom.appended.filter((e) => e.tagName === 'SCRIPT').every((e) => e.async === false), 'async=false');
  await L.load('beta');
  eq(dom.appended.length, 3, '다시 불러도 안 붙인다');
});

test('⑤ 하나라도 못 받으면 false, 다시 부르면 못 받은 것만 다시 붙인다', async () => {
  const fail = new Set(['js/b.js?v=1']);
  const dom = fakeDom(NODES, { fail });
  const L = loadLazy(dom);
  eq(await L.load('beta'), false, '첫 시도');
  ok(!L.loaded('beta'), 'loaded 가 아니어야 한다');
  fail.clear();
  eq(await L.load('beta'), true, '두 번째 시도');
  eq(dom.appended.map((e) => e.src || e.href), ['css/a.css?v=1', 'js/a.js?v=1', 'js/b.js?v=1', 'js/b.js?v=1'],
    '성공한 a.js 는 다시 실행하지 않는다');
});

test('⑤ pdf 번들을 받으면 worker 주소를 붙인다', async () => {
  const dom = fakeDom(NODES);
  const L = loadLazy(dom);
  dom.win.pdfjsLib = { GlobalWorkerOptions: {} };
  await L.load('pdf');
  eq(dom.win.pdfjsLib.GlobalWorkerOptions.workerSrc, 'https://cdn/w.js', 'workerSrc');
});

test('하네스 자기 검사 — 처음부터도 부르는 파일·없는 파일을 넣으면 잡는다', () => {
  const broken = HTML
    .replace('<script src="js/config.js', '<script src="js/booth_qa.js?v=x"></script>\n<script src="js/config.js')
    .replace('</template>', '  <script src="js/nope.js?v=1" data-bundle="beta"></script>\n</template>');
  const p = checkIndex(broken);
  ok(p.some((x) => x.includes('booth_qa.js') && x.includes('두 번')), `중복을 못 잡음: ${p}`);
  ok(p.some((x) => x.includes('nope.js') && x.includes('없음')), `없는 파일을 못 잡음: ${p}`);
});

let failed = 0;
for (const c of cases) {
  try {
    await c.fn();
    console.log(`  ✓ ${c.name}`);
  } catch (e) {
    failed += 1;
    console.log(`  ✗ ${c.name}\n      ${e.message}`);
  }
}
console.log(failed ? `\n${failed}/${cases.length} 실패` : `\n${cases.length}개 통과`);
process.exit(failed ? 1 : 0);
