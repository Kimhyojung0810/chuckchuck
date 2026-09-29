/**
 * qa/tidy — 리포트·리빌이 「판정하지 않은 개념」 을 정직하게 그리는지 (app.js · f11_reveal.html 순수 함수 스모크).
 *
 *   node tests/js/report_tidy.smoke.mjs
 *
 * 1. 리빌(f11_reveal.html) — 녹음이 다른 발표면(speech_match unrelated · basis skipped) 개념을 「안 나왔어요」 로 칠하지 않는다.
 *    판정 안 함(na)이고 판정 5색이 아닌 중립 회색이다. 설명 비중·연결 수를 0 으로 세우지 않는다.
 * 2. AI 판정이 비어 짐작한 개념(decided_by fallback · basis fallback)은 리포트 탭들과 리빌이 똑같이 「판정 안 함」 으로 — 짐작의 재료였던
 *    이름 언급 횟수는 사실로 적는다. 코드가 까닭을 대고 정한 판정(decided_by code)은 그대로 판정이다.
 * 「여기부터 보세요」 근거 한 줄(plainEvidence)은 report_hint.smoke.mjs 가 본다.
 *
 * app.js 는 최상위에서 route() 가 돌아 통째로 못 올린다 — report_faults.smoke.mjs 처럼 **이름으로 원본 함수를 잘라** 올린다.
 * 리빌은 HTML 안의 <script> 에서 같은 방법으로 자른다. 못 찾으면 던진다. 마지막 케이스들은 하네스가 진짜로 회귀를 잡는지 스스로 본다.
 * 재료는 튜닝·held-out·벤치 덱이 아니다 — 동네 수영장 발표.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const APP_SRC = readFileSync(path.join(ROOT, 'demo/YEHS_demo/js/app.js'), 'utf8');
const DATA_SRC = readFileSync(path.join(ROOT, 'demo/YEHS_demo/js/data.js'), 'utf8');
const REVEAL_SRC = readFileSync(path.join(ROOT, 'demo/YEHS_demo/f11_reveal.html'), 'utf8');

function extractFunction(src, name) {
  const m = new RegExp(`\\n(?:async\\s+)?function\\s+${name}\\s*\\(`).exec(src);
  if (!m) throw new Error(`${name} 을 못 찾았어요. 원본이 바뀌었으면 하네스도 같이 고쳐야 해요.`);
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
function extractBlockConst(src, name) {
  const m = new RegExp(`\\nconst ${name} = ([\\[{])`).exec(src);
  if (!m) throw new Error(`${name} 상수를 못 찾았어요.`);
  let depth = 0;
  for (let j = m.index + m[0].length - 1; j < src.length; j += 1) {
    if ('[{'.includes(src[j])) depth += 1;
    else if (']}'.includes(src[j]) && --depth === 0) return src.slice(m.index + 1, j + 2);
  }
  throw new Error(`${name} 상수가 안 닫혀요.`);
}

const escapeHtml = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const APP_NAMES = ['recordingUnrelated', 'conceptUnjudgedWhy', 'realJudgeTree', 'judgeSplitHtml',
  'judgeLegendHtml', 'noEvidenceNote', 'fmtMarkSec', 'judgeSlideOf', 'qaBuildCandidates'];
function loadApp(src = APP_SRC) {
  const ctx = vm.createContext({ escapeHtml, __out: null, nf: null });
  vm.runInContext([
    extractConst(DATA_SRC, 'STATUS'), extractBlockConst(src, 'STATUS_FROM_VERDICT'), extractBlockConst(src, 'JUDGE_SPLIT'),
    'function reportOut() { return globalThis.__out; }',
    ...APP_NAMES.map((n) => extractFunction(src, n)),
    `;globalThis.__api = { ${APP_NAMES.join(', ')} };`,
  ].join('\n'), ctx);
  ctx.__api.setOut = (out) => { ctx.__out = out; ctx.nf = { pipelineOut: out }; };
  return ctx.__api;
}

const REVEAL_NAMES = ['alignUnjudged', 'revealVerdict', 'revealMode', 'revealCounts', 'revealCaptions', 'verdictRowsShown'];
function loadReveal(src = REVEAL_SRC) {
  const ctx = vm.createContext({});
  vm.runInContext([
    extractBlockConst(src, 'CAPTIONS'), extractConst(src, 'CAPTION_VERDICT'), extractConst(src, 'CAPTION_DONE'),
    extractBlockConst(src, 'VERDICT_FROM_API'),
    ...REVEAL_NAMES.map((n) => extractFunction(src, n)),
    `;globalThis.__api = { ${REVEAL_NAMES.join(', ')} };`,
  ].join('\n'), ctx);
  return ctx.__api;
}

const A = loadApp();
const R = loadReveal();
const cases = [];
const test = (name, fn) => cases.push({ name, fn });
function eq(actual, expected, what) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) throw new Error(`${what}: ${e} 를 기대했는데 ${a} 였어요`);
}
function ok(cond, what) { if (!cond) throw new Error(what); }

/* ── 재료 — 동네 수영장 발표 ─────────────────────────────────────────────────────────────── */
const GRAPH = { nodes: [
  { id: 'water', label: '수질 관리', slide_nos: [1], weight: 1 }, { id: 'chlorine', label: '잔류 염소', slide_nos: [3], weight: 0.9 },
  { id: 'filter', label: '여과기', slide_nos: [2], weight: 0.7 }, { id: 'shower', label: '샤워 규칙', slide_nos: [4], weight: 0.5 },
] };
const basis = (mentions) => ({ mention_count: mentions, first_mention_sec: mentions ? 12 : null });
/** AI 판정이 두 번 다 비어 전부 짐작(basis fallback) — 코드가 정한 것 둘(말한 문장을 찾음 · 자료와 어긋난 수치)만 판정이다 */
const GUESS_ALIGN = { speech_match: 'matched', basis: 'fallback', speech_overlap: 0.41, items: [
  { node_id: 'water', verdict: 'aligned', decided_by: 'code', evidence: '수질은 매일 아침 재요.', speech_basis: basis(3) },
  { node_id: 'chlorine', verdict: 'contradiction', decided_by: 'code', evidence: '염소는 0.2로 맞춰요.',
    deck_quote: '잔류 염소를 0.6ppm 으로 맞춥니다', deck_slide_no: 3, speech_basis: basis(2) },
  { node_id: 'filter', verdict: 'missing', decided_by: 'fallback', evidence: '', note: '여과기를 잘 설명했어요', speech_basis: basis(1) },
  { node_id: 'shower', verdict: 'aligned', decided_by: 'fallback', evidence: '', note: '', speech_basis: basis(4) },
] };
const UNRELATED_ALIGN = { speech_match: 'unrelated', basis: 'skipped', speech_overlap: 0.047, items: GRAPH.nodes.map((n) => ({
  node_id: n.id, verdict: 'missing', decided_by: 'fallback', evidence: '', note: '녹음이 이 자료의 발표가 아니라서 판정하지 않았어요' })) };
const LLM_ALIGN = { speech_match: 'matched', basis: 'llm', items: [
  { node_id: 'water', verdict: 'aligned', decided_by: 'llm', evidence: '수질은 매일 재요.' },
  { node_id: 'chlorine', verdict: 'missing', decided_by: 'llm' },
  { node_id: 'filter', verdict: 'justified_skip', decided_by: 'llm' },
  { node_id: 'shower', verdict: 'missing', decided_by: 'fallback' },          // LLM 이 빠뜨린 개념 하나 — 짐작
] };

/* ═══ 1·2. 리빌 ═══════════════════════════════════════════════════════════════════════════ */
test('리빌 — 다른 발표 녹음이면 개념은 전부 판정 안 함(na)이고, 판정 줄은 「판정하지 않았어요」 하나', () => {
  eq(R.revealMode(UNRELATED_ALIGN), 'unrelated', '모드');
  eq(UNRELATED_ALIGN.items.map((it) => R.revealVerdict(it, true)), ['na', 'na', 'na', 'na'], '판정');
  const counts = R.revealCounts(UNRELATED_ALIGN);
  eq(counts, { aligned: 0, partial: 0, missing: 0, contra: 0, skip: 0, na: 4 }, '개수');
  eq(R.verdictRowsShown(counts), ['vr6'], '판정 다섯을 0 으로 늘어놓지 않는다');
  const caps = R.revealCaptions('unrelated', counts, 0.047);
  eq(caps.verdict.h, '녹음이 이 자료의 발표가 아니에요', '판정 씬 제목');
  ok(caps.verdict.p.startsWith('녹음 낱말 가운데 이 자료에도 있는 말이 5%예요.'), `겹침 비중 — 리포트와 같은 반올림: ${caps.verdict.p}`);
  ok(!/설명|맞춰 봤/.test(caps.done.p), `요약 캡션이 맞춰 봤다고 하지 않는다: ${caps.done.p}`);
  ok(/판정하지 않았어요/.test(caps.verdict.p), '판정하지 않았다');
});

test('리빌 — 짐작(decided_by fallback)은 판정 안 함, 코드가 정한 판정은 그대로', () => {
  eq(R.revealMode(GUESS_ALIGN), 'guess', '모드');
  eq(GUESS_ALIGN.items.map((it) => R.revealVerdict(it, false)), ['aligned', 'contra', 'na', 'na'], '판정');
  const counts = R.revealCounts(GUESS_ALIGN);
  eq([counts.aligned, counts.contra, counts.missing, counts.na], [1, 1, 0, 2], '개수 — 짐작한 「안 나옴」 을 세지 않는다');
  eq(R.verdictRowsShown(counts), ['vr1', 'vr2', 'vr3', 'vr4', 'vr5', 'vr6'], '판정 다섯 뒤에 판정 안 함');
  const caps = R.revealCaptions('guess', counts, 0.41);
  ok(caps.verdict.p.includes('회색 점선 2개는 AI 판정이 비어서 판정하지 않은 개념이에요'), caps.verdict.p);
  eq(R.revealVerdict(undefined, false), 'na', '항목이 없는 개념도 「안 나옴」 이 아니다');
  const allGuess = { basis: 'fallback', items: [{ verdict: 'missing', decided_by: 'fallback' }, { verdict: 'aligned', decided_by: 'fallback' }] };
  const c2 = R.revealCounts(allGuess);
  eq(R.verdictRowsShown(c2), ['vr6'], '전부 짐작이면 한 줄');
  eq(R.revealCaptions('guess', c2, null).verdict.h, '개념 판정이 비었어요', '전부 짐작 — 판정 씬 제목');
});

test('리빌 — 판정 그대로인 발표는 예전과 같다 (LLM 이 빠뜨린 개념 하나만 판정 안 함)', () => {
  eq(R.revealMode(LLM_ALIGN), '', '모드');
  eq(LLM_ALIGN.items.map((it) => R.revealVerdict(it, false)), ['aligned', 'missing', 'skip', 'na'], '판정');
  const caps = R.revealCaptions('', { aligned: 1, partial: 0, missing: 1, contra: 0, skip: 1, na: 0 }, 0.6);
  eq([caps.verdict.h, caps.done.p], ['개념마다 판정을 내렸어요', '자료와 발표를 개념 단위로 맞춰 봤어요'], '캡션 그대로');
});

test('리빌 — 판정 안 함은 판정 5색이 아닌 중립 회색(--na)이다', () => {
  const node = /\.node\.v-na circle\.body \{([^}]*)\}/.exec(REVEAL_SRC);
  ok(node && /stroke: var\(--na\)/.test(node[1]) && /fill: var\(--na-bg\)/.test(node[1]), `노드 스타일: ${node && node[1]}`);
  for (const verdictColour of ['--good', '--bad', '--dim', '--faint', '#C88A2E']) {
    ok(!node[1].includes(verdictColour), `판정 색 ${verdictColour} 을 쓰면 안 돼요`);
  }
  ok(/na:\s*\{ t: "판정 안 했어요",\s*c: "var\(--na\)" \}/.test(REVEAL_SRC), '개념 목록의 판정 칸');
  ok(/skip: "var\(--faint\)", contra: "var\(--bad\)", na: "var\(--na\)"/.test(REVEAL_SRC), '미니 산점도의 점');
  const light = /--na: (#[0-9a-f]{6}); --na-bg: (#[0-9a-f]{6});/i.exec(REVEAL_SRC);
  eq(light && [light[1].toLowerCase(), light[2].toLowerCase()], ['#71717a', '#f4f4f5'], '앱 .st-na 와 같은 회색 (app.css --text-3 · --fill)');
});

/* ═══ 2. 리포트 — 짐작은 「판정 안 함」, 이름 언급 횟수는 사실로 ════════════════════════════════════ */
test('리포트 — 짐작한 개념은 판정 안 함이고 까닭(guess)·이름 언급 횟수를 들고 간다, 버려진 LLM 까닭은 판정 이유가 아니다', () => {
  A.setOut({ graph: GRAPH, alignment: GUESS_ALIGN, score: { score: 61, faults: [{ kind: 'align_fallback' }] } });
  const tree = A.realJudgeTree();
  eq(tree.map((t) => [t.id, t.status, t.naWhy]), [['water', 'ok', ''], ['chlorine', 'ct', ''], ['filter', 'na', 'guess'],
    ['shower', 'na', 'guess']], '상태');
  const filter = tree.find((t) => t.id === 'filter');
  eq([filter.mentions, filter.why], [1, ''], '언급 횟수는 들고 가고, 「여과기를 잘 설명했어요」(버려진 판정의 까닭)는 안 싣는다');
  eq(A.noEvidenceNote('na', 'guess', 0),
    'AI 판정이 비어서 이 개념은 판정하지 않았어요. 발표에서 이 개념 이름 그대로는 나오지 않았어요. 다른 말로 설명했을 수 있어요.', '0번');
  eq(A.noEvidenceNote('na', 'guess', 4), 'AI 판정이 비어서 이 개념은 판정하지 않았어요. 발표에서 이 개념 이름은 4번 나왔어요.', '4번');
  ok(A.noEvidenceNote('na').includes('찾아보지 않았어요'), '다른 발표 녹음 문구는 그대로');
});

test('리포트 — 판정 안 한 개념이 섞이면 분모는 판정한 개념이고, 범례에 판정 안 함이 붙는다', () => {
  A.setOut({ graph: GRAPH, alignment: GUESS_ALIGN, score: { score: 61, faults: [] } });
  const tree = A.realJudgeTree();
  const split = A.judgeSplitHtml(tree);
  ok(/판정한 개념 <b class="num">2<\/b>개 중 <b class="num jsplit-ok">1<\/b>개를 설명했어요/.test(split), split);
  ok(split.includes('다시 볼 곳 1개') && split.includes('판정 안 함 2개는 AI 판정이 비어서'), split);
  ok(!/안 나옴/.test(split), `짐작을 「안 나옴」 으로 세지 않는다: ${split}`);
  eq((A.judgeLegendHtml(tree).match(/<span>/g) || []).length, 6, '범례 다섯 + 판정 안 함');
  // 전부 짐작이면 한 줄로
  const allGuess = { ...GUESS_ALIGN, items: GUESS_ALIGN.items.map((it) => ({ ...it, decided_by: 'fallback' })) };
  A.setOut({ graph: GRAPH, alignment: allGuess, score: { score: 61, faults: [] } });
  const all = A.judgeSplitHtml(A.realJudgeTree());
  ok(all.includes('AI 판정이 비어서 개념 <b class="num">4</b>개를 판정하지 않았어요') && !all.includes('녹음이 이 자료'), all);
  // 판정 그대로인 발표는 예전 헤드 그대로
  A.setOut({ graph: GRAPH, alignment: { ...LLM_ALIGN, items: LLM_ALIGN.items.slice(0, 3) }, score: { score: 70, faults: [] } });
  ok(/^\s*개념 <b class="num">3<\/b>개 중/.test(A.judgeSplitHtml(A.realJudgeTree()).split('jsplit-head">')[1]), '판정 그대로');
});

test('질문 준비 화면의 후보 — 다른 발표 녹음이면 없고, 짐작한 「안 나옴」 은 후보가 아니다', () => {
  A.setOut({ graph: GRAPH, alignment: UNRELATED_ALIGN, score: { faults: [{ kind: 'unrelated_speech' }] } });
  eq(A.qaBuildCandidates(), [], '다른 발표 녹음');
  A.setOut({ graph: GRAPH, alignment: GUESS_ALIGN, score: { faults: [] } });
  eq(A.qaBuildCandidates().map((c) => [c.label, c.verdict]), [['잔류 염소', 'contradiction']], '코드가 확인한 모순만');
  A.setOut({ graph: GRAPH, alignment: LLM_ALIGN, score: { faults: [] } });
  eq(A.qaBuildCandidates().map((c) => c.label), ['잔류 염소'], 'LLM 판정의 누락은 후보, 빠뜨린 개념의 짐작은 아니다');
});

/* ═══ 하네스 자기 검사 ═══════════════════════════════════════════════════════════════════════ */
test('하네스가 회귀를 잡는다 (짐작한 개념을 「안 나옴」 으로 그리는 app.js 를 넣으면 실패)', () => {
  const broken = APP_SRC.replace("return item && item.decided_by === 'fallback' ? 'guess' : '';", "return '';");
  ok(broken !== APP_SRC, '망가뜨릴 줄을 못 찾았어요 — 원본이 바뀌었으면 이 케이스도 같이 고쳐요');
  const B = loadApp(broken);
  B.setOut({ graph: GRAPH, alignment: GUESS_ALIGN, score: { faults: [] } });
  eq(B.realJudgeTree().map((t) => t.status), ['ok', 'ct', 'no', 'ok'], '망가진 원본은 짐작을 판정으로 그린다');
});

test('하네스가 회귀를 잡는다 (다른 발표 녹음의 개념을 「안 나왔어요」 로 칠하는 리빌을 넣으면 실패)', () => {
  const broken = REVEAL_SRC.replace('if (unrelated || !item || item.decided_by === "fallback") return "na";', '');
  ok(broken !== REVEAL_SRC, '망가뜨릴 줄을 못 찾았어요 — 원본이 바뀌었으면 이 케이스도 같이 고쳐요');
  const B = loadReveal(broken);
  eq(UNRELATED_ALIGN.items.map((it) => B.revealVerdict(it, true)), ['missing', 'missing', 'missing', 'missing'], '망가진 원본');
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
