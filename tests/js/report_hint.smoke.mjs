/**
 * qa/tidy — 「여기부터 보세요」 근거 한 줄이 마크다운 표·칸째 나가지 않는지 (app.js 순수 함수 스모크).
 *
 *   node tests/js/report_hint.smoke.mjs
 *
 * 왜 — 채점표(F-14)의 LLM 근거는 자료 인용이면 표를 마크다운째, 대개 한 줄로 눌러 싣는다(09-30 교실 공기 R1: 「측정 결과 | 조건 |
 * 평균 농도 | … | --- | --- | … | 수업 중 5분을 더 열자 평균 농도가 40% 낮아졌습니다.」). 기둥의 「여기부터 보세요」 가 그걸 그대로
 * 그려 카드가 파이프·대시로 찼다. plainEvidence 가 표 칸·빈 칸·꾸밈을 걷고 짧게 자른다 — 숫자는 고치지 않는다.
 *
 * app.js 는 최상위에서 route() 가 돌아 통째로 못 올린다 — report_faults.smoke.mjs 처럼 **이름으로 원본 함수를 잘라** 올린다.
 * 마지막 케이스는 하네스가 진짜로 회귀를 잡는지 스스로 본다. 재료는 튜닝·held-out·벤치 덱이 아니다 — 동네 수영장 발표.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const APP_SRC = readFileSync(path.join(ROOT, 'demo/YEHS_demo/js/app.js'), 'utf8');

function extractFunction(src, name) {
  const m = new RegExp(`\\n(?:async\\s+)?function\\s+${name}\\s*\\(`).exec(src);
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

const NAMES = ['faultClip', 'stripMarkdownLine', 'plainEvidence', 'clusterReason'];
function load(src = APP_SRC) {
  const ctx = vm.createContext({ __score: null });
  vm.runInContext([
    extractConst(src, 'REPORT_FAULT_QUOTE_MAX'), extractConst(src, 'HINT_MAX'), extractConst(src, 'MD_SEP_CELL_RE'),
    extractConst(src, 'MD_EMPTY_FIELD_RE'),
    'function reportScore() { return globalThis.__score; }',
    ...NAMES.map((n) => extractFunction(src, n)),
    `;globalThis.__api = { ${NAMES.join(', ')} };`,
  ].join('\n'), ctx);
  ctx.__api.setScore = (score) => { ctx.__score = score; };
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

test('한 줄로 눌린 마크다운 표는 표 밖의 글만 — 숫자는 그대로', () => {
  const table = '수질 기록 | 요일 | 잔류 염소 | 탁도 | | --- | --- | --- | | 월 | 0.6ppm | 0.3NTU | | 화 | 0.5ppm | 0.4NTU | 주말에는 잔류 염소를 두 번 쟀습니다.';
  eq(A.plainEvidence(table), '수질 기록 · 주말에는 잔류 염소를 두 번 쟀습니다.', '표');
  eq(A.plainEvidence('| --- | --- |'), '', '표 칸뿐이면 빈 글 — 호출자가 다음 재료로 물러난다');
});

test('표가 아닌 칸 나열은 값 있는 칸만, 여러 줄 표는 표 행을 버린다', () => {
  eq(A.plainEvidence('제목: - | 시각요소: - | 본문: 여과기는 영업 시간 내내 돌립니다'), '본문: 여과기는 영업 시간 내내 돌립니다', '빈 칸');
  eq(A.plainEvidence('기록\n| 요일 | 염소 |\n| --- | --- |\n| 월 | 0.6 |\n주말 기록이 빠졌어요'), '기록 주말 기록이 빠졌어요', '여러 줄 표');
});

test('마크다운 꾸밈을 걷는다 — 굵게·코드·링크·글머리표', () => {
  eq(A.plainEvidence('**평균 139자/분**으로 권장 구간(300~350)보다 161자/분 느려요'),
    '평균 139자/분으로 권장 구간(300~350)보다 161자/분 느려요', '굵게');
  eq(A.plainEvidence('- `수질 일지`는 [게시판](http://x)에 붙였어요'), '수질 일지는 게시판에 붙였어요', '코드·링크·글머리표');
});

test('길면 짧게 — 문장 끝(없으면 낱말 경계)에서 자른다', () => {
  const long = '샤워를 하고 들어가야 수질이 오래 유지됩니다. ' + '샤워 규칙을 입구에 붙였지만 지키는 회원이 절반뿐이었습니다. '.repeat(3);
  const cut = A.plainEvidence(long);
  ok(cut.length <= 90 && (cut.endsWith('다.') || cut.endsWith('…')), `자르기: ${cut.length} «${cut}»`);
  const words = '수질 '.repeat(60);
  const cut2 = A.plainEvidence(words);
  ok(cut2.length <= 91 && cut2.endsWith('…') && !cut2.endsWith(' …'), `낱말 경계: «${cut2}»`);
});

test('축에서 제일 낮은 항목의 근거가 표면 글로, 글이 안 남으면 까닭(note)으로', () => {
  A.setScore({ items: [
    { cluster: 'visual', status: 'scored', score: 0, evidence: '| 요일 | 염소 | | --- | --- | | 월 | 0.6 |', note: '표를 말로 풀지 않았어요' },
    { cluster: 'visual', status: 'scored', score: 40, evidence: '슬라이드 글자가 많아요', note: '' },
  ] });
  eq(A.clusterReason('visual'), '표를 말로 풀지 않았어요', '표뿐인 근거');
  A.setScore({ items: [{ cluster: 'visual', status: 'scored', score: 10,
    evidence: '수질 기록 | 요일 | 염소 | | --- | --- | | 월 | 0.6 | 월요일은 0.6ppm 이었습니다.', note: 'x' }] });
  eq(A.clusterReason('visual'), '수질 기록 · 월요일은 0.6ppm 이었습니다.', '표 밖의 글');
  eq(A.clusterReason('time'), '', '근거가 없으면 빈 글 — DIM_HINT 질문으로 떨어진다');
});

test('하네스가 회귀를 잡는다 (근거 한 줄에서 표를 안 걷는 app.js 를 넣으면 실패)', () => {
  const broken = APP_SRC.replace('const hasTable = /\\|\\s*:?-{3,}:?\\s*\\|/.test(raw);', 'const hasTable = false;');
  ok(broken !== APP_SRC, '망가뜨릴 줄을 못 찾았어요 — 원본이 바뀌었으면 이 케이스도 같이 고쳐요');
  const B = load(broken);
  ok(B.plainEvidence('기록 | 요일 | | --- | | 월 | 끝') !== '기록 · 끝', '망가진 원본은 표 칸을 남긴다');
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
