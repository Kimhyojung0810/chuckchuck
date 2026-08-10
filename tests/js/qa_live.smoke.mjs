/**
 * 질문 코칭(Q&A) 프론트 순수 함수 스모크.
 *
 *   node tests/js/qa_live.smoke.mjs
 *
 * 왜 있나 — `tests/` 가 전부 파이썬이라 **프론트 JS 는 자동 커버리지가 0이었다.**
 * 2026-08 스프린트에서 고친 여섯 자리(마이크 폴백·세션 초기화·「처음부터」·말풍선
 * 중복·힌트 분모·입력 카드)가 전부 사람 손으로만 확인됐고, 같은 자리가 계속 깨졌다.
 *
 * 브라우저를 띄우지 않는다. `qa_live.js` 는 최상위에 부작용이 없어서(선언뿐)
 * `vm` 컨텍스트에 통째로 올릴 수 있다. `app.js` 는 최상위에서 `route()` 가 돌기
 * 때문에 통째로 못 올린다 — 필요한 함수 하나만 이름으로 잘라 쓴다.
 *
 * **하네스가 흉내 내는 전역이 곧 시험 범위다.** `hasRealSlideImage`·`qaDocKey` 는
 * 원본이 `typeof … === 'function'` 으로 감싸고 있어서, 안 심으면 그 가지가 통째로
 * 죽은 코드가 된다 — 심어야 비로소 시험이 된다.
 *
 * 이 파일은 pytest 가 수집하지 않는다 (`test_*.py` 만 모은다).
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const JS_DIR = path.join(ROOT, 'demo/YEHS_demo/js');

const QA_LIVE_SRC = readFileSync(path.join(JS_DIR, 'qa_live.js'), 'utf8');
const APP_SRC = readFileSync(path.join(JS_DIR, 'app.js'), 'utf8');

/* 최상위 `const`/`let` 은 컨텍스트의 전역 객체에 안 올라간다. 함수 선언만 올라간다.
   그래서 이름을 한 줄로 모아 내보낸다 — 같은 스크립트 스코프라 전부 잡힌다.
   컨텍스트를 뒤져서 꺼내지 않는다. 없는 이름을 뒤지면 오류가 아니라 undefined 라
   조용히 통과해 버린다. */
const EXPORT_LINE = `
;globalThis.__api = {
  qaLiveActive, newLiveState, liveStalled, hintSlideNos,
  liveHints, liveQuestionHints, openNextHint, liveArtifacts, HINT_SLIDE_SHOW_MAX,
  liveScoredAnswers,
};`;

/**
 * 이름으로 함수 하나를 잘라낸다. `app.js` 를 통째로 올릴 수 없어서 쓴다.
 * **못 찾으면 던진다.** 손으로 베낀 사본으로 물러나면 그때부터 원본이 아니라
 * 사본을 시험하게 되고, 원본이 바뀌어도 초록으로 남는다.
 */
function extractFunction(src, name) {
  const head = new RegExp(`\\n(?:async\\s+)?function\\s+${name}\\s*\\(`);
  const m = head.exec(src);
  if (!m) throw new Error(`app.js 에서 ${name} 을 못 찾았어요. 원본이 바뀌었으면 하네스도 같이 고쳐야 해요.`);
  const start = m.index + 1;
  let depth = 0;
  let seen = false;
  for (let i = start; i < src.length; i += 1) {
    if (src[i] === '{') { depth += 1; seen = true; }
    else if (src[i] === '}') {
      depth -= 1;
      if (seen && depth === 0) {
        const slice = src.slice(start, i + 1);
        new vm.Script(slice);   // 중괄호 세기가 어긋났으면 여기서 터진다
        return slice;
      }
    }
  }
  throw new Error(`${name} 의 본문이 안 닫혀요.`);
}

const QA_DOC_KEY_SRC = extractFunction(APP_SRC, 'qaDocKey');

/**
 * 시험용 컨텍스트 한 벌. `pushTurn` 은 빈 함수가 아니라 **기록기**다 —
 * 힌트 분모("힌트 2/4")는 `liveHints()` 의 반환 길이가 아니라 말풍선에 실린
 * `total` 이라, 그걸 봐야 진짜로 본 숫자를 보는 것이다.
 */
function newContext({ nf = null, hasRealSlideImage = () => true } = {}) {
  const turns = [];
  const sandbox = {
    console,
    qa: { live: null },
    nf,
    pushTurn: (t) => turns.push(t),
    saveSession: () => {},
    loadSession: () => null,
    escapeHtml: (s) => String(s),
    hasRealSlideImage,
  };
  const ctx = vm.createContext(sandbox);
  vm.runInContext(QA_DOC_KEY_SRC, ctx);          // qa_live 가 qaDocKey 를 lazy 로 부른다
  vm.runInContext(QA_LIVE_SRC + EXPORT_LINE, ctx);
  return { ctx, api: ctx.__api, turns };
}

/** `newLiveState` 위에 필요한 칸만 덮어 새 상태를 만든다 (원본을 안 건드린다). */
function liveState(api, questions, overrides = {}) {
  return { ...api.newLiveState('s1', questions, ''), ...overrides };
}

/* ── 아주 작은 시험 틀 ─────────────────────────────────────────────────────── */
const cases = [];
const test = (name, fn) => cases.push({ name, fn });

function eq(actual, expected, what) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) throw new Error(`${what}: ${e} 를 기대했는데 ${a} 였어요`);
}

/* ── qaDocKey — 자료의 지문 (app.js) ───────────────────────────────────────── */

test('자료가 없으면 지문은 빈 문자열이다', () => {
  const { ctx } = newContext({ nf: null });
  eq(ctx.qaDocKey(), '', '지문');
});

test('지문은 자료 이름과 장수를 같이 본다', () => {
  const { ctx } = newContext({ nf: { slideDocMeta: { file_name: '수면.pptx', total_slides: 33 } } });
  eq(ctx.qaDocKey(), '수면.pptx|33', '지문');
});

test('같은 이름이라도 장수가 다르면 다른 지문이다', () => {
  const a = newContext({ nf: { slideDocMeta: { file_name: '수면.pptx', total_slides: 33 } } });
  const b = newContext({ nf: { slideDocMeta: { file_name: '수면.pptx', total_slides: 8 } } });
  if (a.ctx.qaDocKey() === b.ctx.qaDocKey()) throw new Error('장수가 달라도 지문이 같아요');
});

/* ── qaLiveActive — 새 발표면 지난 코칭을 안 보여준다 ───────────────────────── */

test('질문이 없으면 진행 중이 아니다', () => {
  const { ctx, api } = newContext();
  ctx.qa.live = null;
  eq(api.qaLiveActive(), false, '질문 없는 상태');
});

test('자료가 바뀌면 지난 질문을 버린다', () => {
  const { ctx, api } = newContext({ nf: { slideDocMeta: { file_name: '집중.pptx', total_slides: 8 } } });
  ctx.qa.live = liveState(api, [{ question: 'q' }], { docKey: '수면.pptx|33' });
  eq(api.qaLiveActive(), false, '자료가 바뀐 상태');
});

test('같은 자료면 진행 중인 코칭이 살아 있다', () => {
  const { ctx, api } = newContext({ nf: { slideDocMeta: { file_name: '수면.pptx', total_slides: 33 } } });
  ctx.qa.live = liveState(api, [{ question: 'q' }], { docKey: '수면.pptx|33' });
  eq(api.qaLiveActive(), true, '같은 자료');
});

test('옛 세션(지문 없음)은 새로고침에 안 날린다', () => {
  const { ctx, api } = newContext({ nf: { slideDocMeta: { file_name: '수면.pptx', total_slides: 33 } } });
  ctx.qa.live = liveState(api, [{ question: 'q' }], { docKey: '' });
  eq(api.qaLiveActive(), true, '지문 없는 옛 세션');
});

test('지금 자료를 아직 못 읽으면 낡음으로 치지 않는다', () => {
  // 새로고침 직후 nf 가 안 찬 순간. 여기서 지우면 진행 중인 코칭이 사라진다.
  const { ctx, api } = newContext({ nf: null });
  ctx.qa.live = liveState(api, [{ question: 'q' }], { docKey: '수면.pptx|33' });
  eq(api.qaLiveActive(), true, 'nf 가 아직 빈 순간');
});

/* ── liveStalled — 막힌 사람에게 열어 주는 출구 ────────────────────────────── */

test('판정이 실패하면 2턴을 못 채웠어도 출구를 연다', () => {
  // 순서가 핵심이다. judgeFailed 검사가 turns.length 검사보다 뒤로 가면
  // 첫 턴에 판정이 죽은 사람은 코칭 전체를 끝내는 것 말고 길이 없다.
  const { ctx, api } = newContext();
  ctx.qa.live = liveState(api, [{ hints: ['a', 'b'] }], { judgeFailed: true, turns: [] });
  eq(api.liveStalled(), true, '판정 실패');
});

test('답을 보고 다시 말하는 중에는 출구를 또 열지 않는다', () => {
  const { ctx, api } = newContext();
  ctx.qa.live = liveState(api, [{ hints: ['a', 'b'] }], {
    retell: { gist: 'g' }, turns: [{ score: 40 }, { score: 40 }], hintLevel: 2,
  });
  eq(api.liveStalled(), false, '되말하기 중');
});

test('턴이 하나뿐이면 아직 안 연다', () => {
  const { ctx, api } = newContext();
  ctx.qa.live = liveState(api, [{ hints: ['a', 'b'] }], { turns: [{ score: 40 }] });
  eq(api.liveStalled(), false, '첫 턴');
});

test('힌트 사다리를 다 썼으면 연다', () => {
  const { ctx, api } = newContext();
  ctx.qa.live = liveState(api, [{ hints: ['a', 'b'] }], {
    hintLevel: 2, turns: [{ score: 40 }, { score: 70 }],
  });
  eq(api.liveStalled(), true, '사다리 소진');
});

test('점수가 오르는 중이면 안 연다', () => {
  const { ctx, api } = newContext();
  ctx.qa.live = liveState(api, [{ hints: ['a', 'b'] }], {
    hintLevel: 0, turns: [{ score: 40 }, { score: 70 }],
  });
  eq(api.liveStalled(), false, '점수 상승');
});

test('점수가 제자리면 연다', () => {
  // 같은 점수도 정체다. 좁혀서 `<` 로 만들면 정작 막힌 사람이 출구를 잃는다.
  const { ctx, api } = newContext();
  ctx.qa.live = liveState(api, [{ hints: ['a', 'b'] }], {
    hintLevel: 0, turns: [{ score: 70 }, { score: 70 }],
  });
  eq(api.liveStalled(), true, '점수 정체');
});

/* ── hintSlideNos — 힌트가 가리키는 장 ─────────────────────────────────────── */

test('장 번호가 없으면 그림을 안 붙인다', () => {
  const { api } = newContext();
  eq(api.hintSlideNos('회복 시간을 떠올려 보세요'), [], '번호 없는 힌트');
});

test('여러 장을 한꺼번에 읽는다', () => {
  const { api } = newContext();
  eq(api.hintSlideNos('3, 5, 7장을 떠올려 보세요'), [3, 5, 7], '여러 장');
});

test('진짜 렌더가 있는 장만 남긴다', () => {
  // 이 가지는 hasRealSlideImage 를 안 심으면 통째로 건너뛴다 — 심어야 시험이 된다.
  const { api } = newContext({ hasRealSlideImage: (n) => n !== 5 });
  eq(api.hintSlideNos('3, 5, 7장을 떠올려 보세요'), [3, 7], '렌더 없는 장 제외');
});

test('장 그림은 최대 세 개까지만 붙인다', () => {
  const { api } = newContext();
  eq(api.hintSlideNos('1, 2, 3, 4, 5장을 떠올려 보세요').length, api.HINT_SLIDE_SHOW_MAX, '장 개수 상한');
});

/* ── 힌트 분모 — "힌트 2/4" 다음에 "힌트 3/3" 이 뜨던 자리 ──────────────────── */

/** 판정이 짧은 사다리를 들고 와도 분모가 안 줄어야 한다. 아래 회귀 시험의 본체. */
function assertHintDenominatorHolds(ctx, api, turns) {
  ctx.qa.live = liveState(api, [{ hints: ['b1', 'b2', 'b3'] }], {
    hintList: ['j1', 'j2', 'j3', 'j4'],              // 앞선 판정이 준 4단 (이미 4를 봤다)
    lastJudgement: { hints: ['k1', 'k2', 'k3'] },    // 이번 판정은 3단으로 짧아졌다
  });
  api.openNextHint();
  eq(turns[0].total, 4, '말풍선에 실린 분모');
}

test('판정 사다리가 짧아져도 힌트 분모가 안 줄어든다', () => {
  const { ctx, api, turns } = newContext();
  assertHintDenominatorHolds(ctx, api, turns);
});

test('힌트를 두 번 열어도 분모가 그대로다', () => {
  const { ctx, api, turns } = newContext();
  ctx.qa.live = liveState(api, [{ hints: ['b1', 'b2', 'b3'] }], {
    hintList: ['j1', 'j2', 'j3', 'j4'],
    lastJudgement: { hints: ['k1', 'k2', 'k3'] },
  });
  api.openNextHint();
  api.openNextHint();
  eq([turns[0].total, turns[1].total], [4, 4], '두 번 연 분모');
  if (turns[1].level <= turns[0].level) throw new Error('힌트 칸이 안 올라갔어요');
});

test('옛 저장 세션(hintList 없음)은 질문이 들고 온 사다리로 떨어진다', () => {
  const { ctx, api, turns } = newContext();
  ctx.qa.live = liveState(api, [{ hints: ['b1', 'b2', 'b3'] }], { hintList: undefined });
  api.openNextHint();
  eq(turns[0].total, 3, '폴백 분모');
});

/* ── 세션 아티팩트 계약 — 발표 A 의 근거가 발표 B 로 새지 않게 하는 자리 ────── */

/* 데모의 서버 세션 키는 'flat' 하나뿐이라 새 발표도 같은 칸에 쓴다. 그래서
   `put_artifacts` 는 **명시적 null 을 지우기로** 계약했다 (session_store.py) —
   프론트가 "이번 발표엔 flow 가 없다" 를 null 로 말해 줘야 지난 발표의 flow 가
   판정 근거로 안 섞인다. 그 계약은 **프론트가 다섯 키를 전부 보낼 때만** 성립한다.
   키가 하나 늘고 프론트가 안 따라오면 누수는 조용히 돌아온다. 여기서 잠근다. */
const ARTIFACT_KEYS = (() => {
  const py = readFileSync(path.join(ROOT, 'demo/session_store.py'), 'utf8');
  const m = py.match(/^ARTIFACT_KEYS\s*=\s*\(([^)]*)\)/m);
  if (!m) throw new Error('demo/session_store.py 에서 ARTIFACT_KEYS 를 못 찾았어요.');
  return m[1].split(',').map((s) => s.trim().replace(/^['"]|['"]$/g, '')).filter(Boolean);
})();

test('프론트가 서버 아티팩트 키를 하나도 빠뜨리지 않는다', () => {
  const { api } = newContext({ nf: { pipelineOut: { graph: { nodes: [] } } } });
  const sent = api.liveArtifacts();
  if (!sent) throw new Error('그래프가 있는데 아티팩트를 안 보냈어요');
  const missing = ARTIFACT_KEYS.filter((k) => !(k in sent));
  if (missing.length) {
    throw new Error(`서버가 보관하는 키인데 프론트가 안 보내요: ${missing.join(', ')}. `
      + '안 보낸 키는 지난 발표 값이 그대로 남아 판정 근거로 섞여요.');
  }
});

test('없는 값은 빼지 않고 null 로 보낸다', () => {
  // 키를 빼면 서버는 "안 보냈다" 로 읽고 지난 발표 값을 남긴다. null 이어야 지운다.
  const { api } = newContext({ nf: { pipelineOut: { graph: { nodes: [] } } } });
  const sent = api.liveArtifacts();
  eq([sent.alignment, sent.flow, sent.transcript], [null, null, null], '빈 값의 표현');
});

test('그래프가 아직 없으면 아무것도 안 보낸다', () => {
  // 절반만 올리면 나머지 칸에 지난 발표가 남는다. 그럴 바엔 안 올리는 게 맞다.
  const { api } = newContext({ nf: { pipelineOut: {} } });
  eq(api.liveArtifacts(), null, '그래프 없는 상태');
});

/* ── 하네스가 진짜로 회귀를 잡는지 ─────────────────────────────────────────── */

/* 회귀 시험이 회귀를 못 잡으면 초록은 거짓말이다. 고치기 **전** 코드를 만들어
   같은 시험을 돌려서, 반드시 깨지는 것까지 확인한다. */
const NEW_KEPT_LINE = 'const kept = (L && L.hintList) || [];';
const OLD_KEPT_LINE = 'const kept = (L.lastJudgement && L.lastJudgement.hints) || [];';

test('고치기 전 코드로 돌리면 힌트 분모 시험이 깨진다', () => {
  if (!QA_LIVE_SRC.includes(NEW_KEPT_LINE)) {
    throw new Error(`liveHints() 가 바뀌었어요. 이 자기검사도 같이 고쳐야 해요: ${NEW_KEPT_LINE}`);
  }
  const broken = QA_LIVE_SRC.replace(NEW_KEPT_LINE, OLD_KEPT_LINE);
  const turns = [];
  const ctx = vm.createContext({
    console, qa: { live: null }, nf: null,
    pushTurn: (t) => turns.push(t), saveSession: () => {},
    escapeHtml: (s) => String(s), hasRealSlideImage: () => true,
  });
  vm.runInContext(broken + EXPORT_LINE, ctx);

  let threw = false;
  try {
    assertHintDenominatorHolds(ctx, ctx.__api, turns);
  } catch {
    threw = true;
  }
  if (!threw) throw new Error('고치기 전 코드도 통과했어요 — 이 시험은 회귀를 못 잡아요');
});

/* ── liveScoredAnswers — 라운드를 세는 분모 ────────────────────────────────────
   서버(f09 `_round_no`)가 이 배열의 길이로 되묻기 라운드를 센다. 채점 안 된 턴이
   섞이면 ① 라운드가 이유 없이 올라 되묻기가 좁아지고 ② 누적 답변 블록에 그 말이
   답으로 실린다. ─────────────────────────────────────────────────────────── */

function withTurns(api, ctx, turns) {
  ctx.qa.live = liveState(api, [{ id: 'q1', node_id: 'c1', question: '왜요?' }], { turns });
  return api.liveScoredAnswers();
}

test('채점된 답만 라운드에 센다', () => {
  const { ctx, api } = newContext();
  eq(withTurns(api, ctx, [{ answer: '첫 답' }, { answer: '둘째 답' }]),
     ['첫 답', '둘째 답'], '채점된 답');
});

test('포기 자리표시자는 답이 아니라 뺀다', () => {
  const { ctx, api } = newContext();
  eq(withTurns(api, ctx, [{ answer: '첫 답' }, { answer: '(모르겠어요)', gaveUp: true }]),
     ['첫 답'], '포기를 뺀 답');
});

test('되물음 턴은 라운드를 태우지 않는다', () => {
  const { ctx, api } = newContext();
  eq(withTurns(api, ctx, [
    { answer: '질문이 무슨 뜻인가요?', clarify: true },
    { answer: '깊은 수면이요' },
  ]), ['깊은 수면이요'], '되물음을 뺀 답');
});

test('옛 세션(clarify 없음)은 예전 그대로 센다', () => {
  const { ctx, api } = newContext();
  eq(withTurns(api, ctx, [{ answer: '첫 답' }, { answer: '둘째 답', gaveUp: false }]),
     ['첫 답', '둘째 답'], '옛 세션의 답');
});

test('턴이 없으면 1라운드다 (빈 배열)', () => {
  const { ctx, api } = newContext();
  eq(withTurns(api, ctx, []), [], '빈 턴');
});

/* ── 실행 ──────────────────────────────────────────────────────────────────── */
let failed = 0;
for (const c of cases) {
  try {
    c.fn();
    console.log(`  ok   ${c.name}`);
  } catch (err) {
    failed += 1;
    console.log(`  FAIL ${c.name}\n       ${err.message}`);
  }
}
console.log(`\n${cases.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
