/**
 * 리포트 판정 헤드의 「먼저 짚을 것」 (09-30 WP-S2) — app.js 순수 함수 스모크.
 *
 *   node tests/js/report_faults.smoke.mjs
 *
 * 왜 있나 — 채점표(F-14)가 자료와 다르게 말한 수치·말로 건너뛴 핵심 장·다른 발표 녹음으로 등급에 상한을 걸어도, 화면이
 * 까닭을 안 보여 주거나 「핵심은 잘 전달했어요」 를 그 옆에 세우면 리포트가 스스로 거짓말을 한다. 이 서버엔 브라우저가 없어
 * 손으로 매번 못 눌러 보니, 행을 만드는 함수·헤드 한 줄·HTML 을 여기서 본다.
 *
 * `app.js` 는 최상위에서 `route()` 가 돌아 통째로 못 올린다 — qa_live.smoke.mjs 처럼 **이름으로 원본 함수를 잘라** 올린다.
 * 못 찾으면 던진다(사본으로 물러나면 원본이 바뀌어도 초록이 된다). 마지막 케이스는 하네스가 진짜로 회귀를 잡는지 스스로 본다.
 * 이 파일은 pytest 가 수집하지 않는다.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const APP_SRC = readFileSync(path.join(ROOT, 'demo/YEHS_demo/js/app.js'), 'utf8');

function extractFunction(src, name) {
  const head = new RegExp(`\\n(?:async\\s+)?function\\s+${name}\\s*\\(`);
  const m = head.exec(src);
  if (!m) throw new Error(`app.js 에서 ${name} 을 못 찾았어요. 원본이 바뀌었으면 하네스도 같이 고쳐야 해요.`);
  const start = m.index + 1;
  let i = m.index + m[0].length;
  for (let paren = 1; paren > 0; i += 1) {          // 매개변수 기본값(`max = …`)을 건너뛴다
    if (src[i] === '(') paren += 1;
    else if (src[i] === ')') paren -= 1;
  }
  const bodyAt = src.indexOf('{', i);
  let depth = 0;
  for (let j = bodyAt; j < src.length; j += 1) {
    if (src[j] === '{') depth += 1;
    else if (src[j] === '}' && --depth === 0) {
      const slice = src.slice(start, j + 1);
      new vm.Script(slice);
      return slice;
    }
  }
  throw new Error(`${name} 의 본문이 안 닫혀요.`);
}
function extractConst(src, name) {
  const m = new RegExp(`\\nconst ${name} = [^\\n]*;`).exec(src);
  if (!m) throw new Error(`${name} 상수를 못 찾았어요.`);
  return m[0].trim();
}

const NAMES = ['faultClip', 'reportFaultRows', 'reportFaultHeadline', 'reportFaultsHtml', 'scoreGrade'];
function load(src = APP_SRC) {
  const ctx = vm.createContext({
    escapeHtml: (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
  });
  vm.runInContext([
    extractConst(src, 'REPORT_FAULT_ORDER'), extractConst(src, 'REPORT_FAULT_QUOTE_MAX'),
    ...NAMES.map((n) => extractFunction(src, n)),
    `;globalThis.__api = { ${NAMES.join(', ')} };`,
  ].join('\n'), ctx);
  return ctx.__api;
}
const A = load();

const cases = [];
const test = (name, fn) => cases.push({ name, fn });
function eq(actual, expected, what) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) throw new Error(`${what}: ${e} 를 기대했는데 ${a} 였어요`);
}
function ok(cond, what) { if (!cond) throw new Error(what); }

/* ── 재료 — 공원 산책로 발표(튜닝 덱이 아니다): 4장 수치를 다르게 말함 · 2장은 말로 건너뜀 ───────────── */
const GRAPH = { nodes: [
  { id: 'root', label: '산책로 연결' }, { id: 'len', label: '산책로 길이' }, { id: 'cross', label: '교차로 수' },
  { id: 'use', label: '이용자 증가' },
] };
const ALIGN = {
  speech_match: 'matched', basis: 'llm', speech_overlap: 0.38,
  items: [
    { node_id: 'use', verdict: 'contradiction', decided_by: 'code', evidence: '산책로를 잇고 나서 이용자가 두 배로 늘었어요',
      deck_quote: '연결 뒤 주말 이용자가 1.4배 늘었습니다', deck_slide_no: 4, note: '발표에서는 2배라고 했는데 자료 4장은 1.4배예요' },
    { node_id: 'len', verdict: 'missing', decided_by: 'code', evidence: '', deck_quote: '', deck_slide_no: null },
    { node_id: 'cross', verdict: 'missing', decided_by: 'code', evidence: '', deck_quote: '', deck_slide_no: null },
  ],
  skipped_slides: [{ slide_no: 2, cue: '이 지도는 시간 관계상 그냥 넘어갈게요.', node_ids: ['len', 'cross'] }],
};
const SCORE = {
  score: 59, cap: 59,
  faults: [
    { kind: 'skipped_slide', text: '핵심 2장을 「이 지도는 시간 관계상 그냥 넘어갈게요.」라고 하고 건너뛰었어요', slide_no: 2 },
    { kind: 'contradiction', text: '발표에서는 2배라고 했는데 자료 4장은 1.4배예요', slide_no: 4 },
  ],
};

test('모순과 건너뛴 장 — 모순이 먼저, 두 인용·장 번호·건너뛴 말·빠진 개념이 붙는다', () => {
  const rows = A.reportFaultRows(SCORE, ALIGN, GRAPH);
  eq(rows.map((r) => r.kind), ['contradiction', 'skipped_slide'], '순서');
  eq([rows[0].title, rows[0].slide, rows[0].said, rows[0].deck],
    ['발표에서는 2배라고 했는데 자료 4장은 1.4배예요', 4, '산책로를 잇고 나서 이용자가 두 배로 늘었어요', '연결 뒤 주말 이용자가 1.4배 늘었습니다'],
    '모순 행');
  eq([rows[1].title, rows[1].cue, rows[1].concepts],
    ['핵심 2장을 말로 건너뛰었어요', '이 지도는 시간 관계상 그냥 넘어갈게요.', ['산책로 길이', '교차로 수']], '건너뛴 장 행');
});

test('결함이 있으면 헤드 한 줄은 그 사실이다 — 등급 구간 문장(「핵심은 잘 전달했어요」)을 쓰지 않는다', () => {
  eq(A.reportFaultHeadline(A.reportFaultRows(SCORE, ALIGN, GRAPH)), '자료와 다르게 말한 곳과 말로 건너뛴 핵심 장이 있어요', '둘 다');
  const onlyContra = { faults: [SCORE.faults[1]] };
  eq(A.reportFaultHeadline(A.reportFaultRows(onlyContra, ALIGN, GRAPH)), '자료와 다르게 말한 곳이 있어요', '모순 하나');
  const onlySkip = { faults: [SCORE.faults[0]] };
  eq(A.reportFaultHeadline(A.reportFaultRows(onlySkip, ALIGN, GRAPH)), '핵심 2장을 말로 건너뛰었어요', '건너뜀 하나');
  for (const kind of ['contradiction', 'skipped_slide', 'unrelated_speech', 'align_fallback']) {
    const line = A.reportFaultHeadline(A.reportFaultRows({ faults: [{ kind, text: '', slide_no: 3 }] }, {}, GRAPH));
    ok(line && !/잘 전달했어요|핵심은 전했고/.test(line), `${kind} 헤드가 비었거나 칭찬이에요: ${line}`);
  }
});

test('HTML — 「먼저 짚을 것 2가지」 · 발표/자료 쌍 · 상한 등급 한 줄', () => {
  const html = A.reportFaultsHtml(A.reportFaultRows(SCORE, ALIGN, GRAPH), SCORE.cap);
  ok(html.includes('먼저 짚을 것 2가지'), '머리 칩');
  ok(html.includes('<span>발표</span>“산책로를 잇고 나서 이용자가 두 배로 늘었어요”'), '발표 인용');
  ok(html.includes('<span>자료 4장</span>“연결 뒤 주말 이용자가 1.4배 늘었습니다”'), '자료 인용');
  ok(html.includes('설명하지 않은 개념 · 산책로 길이 · 교차로 수'), '빠진 개념');
  ok(html.includes('이 2가지 때문에 등급은 C+까지만 매겼어요.'), `상한 줄: ${html}`);
});

test('다른 발표 녹음 — 헤드는 약속한 문장, 행은 그렇게 본 까닭(겹침)과 할 일, 등급은 상한 그대로', () => {
  const sc = { score: 39, cap: 39, faults: [{ kind: 'unrelated_speech', text: '녹음이 이 발표 자료와 다른 발표예요 (4%)', slide_no: null }] };
  const rows = A.reportFaultRows(sc, { speech_match: 'unrelated', speech_overlap: 0.039, items: [] }, GRAPH);
  eq(A.reportFaultHeadline(rows), '녹음이 이 자료와 다른 발표라서 말 분석은 하지 않았어요', '헤드');
  eq(rows[0].title, '녹음 낱말 가운데 이 자료에도 있는 말이 4%예요', '행 제목 — 헤드를 되풀이하지 않는다');
  const html = A.reportFaultsHtml(rows, sc.cap);
  ok(html.includes('아래 개념 판정은 참고만 하고, 이 자료로 발표한 녹음을 올리면 같이 볼게요.'), '할 일 · 아래 판정의 단서');
  ok(html.includes('이 자료의 발표가 아니라서 등급은 D까지만 매겼어요.'), '상한 줄');
  eq(A.reportFaultRows(sc, { speech_match: 'unrelated', items: [] }, GRAPH)[0].title, '녹음과 이 자료가 다루는 내용이 달라요', '겹침을 모르면');
});

test('채점표에 결함 칸이 없어도(옛 방식 폴백) 정합이 다른 발표라면 그 한 줄은 세운다', () => {
  const rows = A.reportFaultRows({ score: 12 }, { speech_match: 'unrelated', items: [] }, GRAPH);
  eq(rows.map((r) => r.kind), ['unrelated_speech'], '행');
  eq(A.reportFaultsHtml(rows, null).includes('등급은'), false, '상한이 없으면 상한 줄도 없다');
});

test('결함이 없으면 행도 헤드도 HTML 도 없다', () => {
  const rows = A.reportFaultRows({ score: 82, faults: [] }, { speech_match: 'matched', items: [] }, GRAPH);
  eq([rows, A.reportFaultHeadline(rows), A.reportFaultsHtml(rows, null)], [[], '', ''], '빈 결과');
  eq(A.reportFaultRows(null, null, null), [], '재료가 없어도 던지지 않는다');
});

test('판정이 비어 짐작뿐 — 상한 없이 개념 전달을 빼고 봤다고만 말한다', () => {
  const rows = A.reportFaultRows({ faults: [{ kind: 'align_fallback', text: '발표와 자료를 대조하지 못했어요', slide_no: null }] }, {}, GRAPH);
  eq(A.reportFaultHeadline(rows), '개념 전달은 빼고 매긴 등급이에요', '헤드');
  eq(rows[0].title, '발표와 자료를 대조하지 못해 개념 전달은 채점하지 않았어요', '행');
  eq(A.reportFaultsHtml(rows, null).includes('등급은'), false, '상한 줄 없음');
});

test('인용은 escape 되고 길면 낱말 경계에서 자른다', () => {
  const al = { items: [{ node_id: 'x', verdict: 'contradiction', deck_slide_no: 1, note: 'n',
    evidence: '<b>굵게</b> 말했어요', deck_quote: '가나다 '.repeat(40) }] };
  const rows = A.reportFaultRows({ faults: [{ kind: 'contradiction', text: 'n', slide_no: 1 }] }, al, GRAPH);
  ok(rows[0].deck.endsWith('…') && rows[0].deck.length <= 91, `자르기: ${rows[0].deck.length}`);
  const html = A.reportFaultsHtml(rows, 69);
  ok(html.includes('&lt;b&gt;굵게&lt;/b&gt;') && !html.includes('<b>굵게'), 'escape');
});

/* ── 하네스 자기 검사 — 헤드가 결함을 무시하도록 원본을 망가뜨리면 위 케이스가 떨어져야 한다 ─────────── */
test('하네스가 회귀를 잡는다 (헤드가 결함을 무시하는 app.js 를 넣으면 실패)', () => {
  const broken = APP_SRC.replace("if (count('unrelated_speech')) return '녹음이 이 자료와 다른 발표라서 말 분석은 하지 않았어요';",
    "if (count('unrelated_speech')) return '';");
  ok(broken !== APP_SRC, '망가뜨릴 줄을 못 찾았어요 — 원본이 바뀌었으면 이 케이스도 같이 고쳐요');
  const B = load(broken);
  const rows = B.reportFaultRows({ faults: [{ kind: 'unrelated_speech', text: '', slide_no: null }] }, {}, GRAPH);
  eq(B.reportFaultHeadline(rows), '', '망가진 원본은 빈 헤드를 낸다');
});

let failed = 0;
for (const c of cases) {
  try {
    c.fn();
    console.log(`  ✓ ${c.name}`);
  } catch (e) {
    failed += 1;
    console.log(`  ✗ ${c.name}\n    ${e.message}`);
  }
}
console.log(`\n${cases.length - failed}/${cases.length} 통과`);
if (failed) process.exit(1);
