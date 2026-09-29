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
  liveScoredAnswers, stuckLabelFor, coachMeta, coachReactText,
  paperHref, attachQuestionPapers, linkCitedText, questionPapersHtml,
  questionOriginLine, questionOriginHtml,
  liveHistory, liveForcedClose, liveWonCount, liveCoachAsk,
  liveBucket, liveHintsUsed, liveWholeSentences, liveDegradedLines, liveQuestionWhy, liveJudgeFailure,
  liveResultRow, liveResultSummary, liveRetryWaitText, closeLiveQuestion, finishLiveQaEarly, presentLiveQuestion,
  liveHintsShown,
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
 * 매개변수에 기본값 객체(`{ a = 1 } = {}`)가 있는 함수도 잘라낸다 — 괄호 깊이로 매개변수를 건너뛴 뒤 본문 중괄호를 센다.
 * chuckchuck_bridge.js 는 ES 모듈(import·window 전역)이라 통째로 못 올려서, 순수 함수만 이름으로 꺼낸다.
 */
function extractFunctionWithParams(src, name) {
  const head = new RegExp(`\\n(?:async\\s+)?function\\s+${name}\\s*\\(`);
  const m = head.exec(src);
  if (!m) throw new Error(`${name} 을 못 찾았어요. 원본이 바뀌었으면 하네스도 같이 고쳐야 해요.`);
  const start = m.index + 1;
  let i = m.index + m[0].length;
  for (let paren = 1; paren > 0; i += 1) {
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
/** 한 줄 상수(`const NAME = …;`)를 꺼낸다 — 잘라낸 함수가 기대는 값 */
function extractConst(src, name) {
  const m = new RegExp(`\\nconst ${name} = [^\\n]*;`).exec(src);
  if (!m) throw new Error(`${name} 상수를 못 찾았어요.`);
  return m[0].trim();
}
const BRIDGE_SRC = readFileSync(path.join(JS_DIR, 'chuckchuck_bridge.js'), 'utf8');
const BRIDGE = (() => {
  const ctx = vm.createContext({});
  vm.runInContext([
    extractConst(BRIDGE_SRC, 'JUDGE_RATE_RETRIES'), extractConst(BRIDGE_SRC, 'ANSWER_STT_SENDS_SESSION'),
    extractFunctionWithParams(BRIDGE_SRC, 'judgeRetryPlan'), extractFunctionWithParams(BRIDGE_SRC, 'answerSttBody'),
    ';globalThis.__b = { judgeRetryPlan, answerSttBody, ANSWER_STT_SENDS_SESSION };',
  ].join('\n'), ctx);
  return ctx.__b;
})();

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

/* C-09 자기검사 — 「도움 받아 닫힘」 규칙을 빼면(예전처럼 good·partial 이면 다 지킨 것) 결과 묶음 시험이 깨져야 한다 */
const HELPED_LINE = "if (liveForcedClose(r) || (r.hintLevel || 0) >= LIVE_HINT_HELP || r.viaCoach) return 'helped';";
test('도움 받아 닫힘 규칙을 빼면 C-09 결과 묶음 시험이 깨진다', () => {
  if (!QA_LIVE_SRC.includes(HELPED_LINE)) throw new Error(`liveBucket 이 바뀌었어요. 이 자기검사도 같이 고쳐야 해요: ${HELPED_LINE}`);
  const ctx = vm.createContext({ console, qa: { live: null }, nf: null, pushTurn: () => {}, saveSession: () => {}, escapeHtml: (x) => String(x) });
  vm.runInContext(QA_LIVE_SRC.replace(HELPED_LINE, '') + EXPORT_LINE, ctx);
  const broken = [R.forced, R.hint3, R.chip].map((r) => ctx.__api.liveBucket(r));
  if (broken.every((b) => b === 'helped')) throw new Error('규칙을 빼도 도움 받은 질문이 helped 로 남았어요 — 시험이 아무것도 안 지킨다');
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
/* ── 「모르겠어요」 사다리 3단 (2026-09-10) ── */
test('「모르겠어요」 라벨은 포기 횟수를 따라 3단이다', () => {
  const { api } = newContext();
  eq(api.stuckLabelFor(0), '모르겠어요', '0회');
  eq(api.stuckLabelFor(1), '그래도 모르겠어요 · 빈칸으로', '1회');
  eq(api.stuckLabelFor(2), '그래도 모르겠어요 · 답 보기', '2회');
  eq(api.stuckLabelFor(5), '그래도 모르겠어요 · 답 보기', '그 이상');
});
test('코치 머리말은 단계마다 몇 단째인지 말한다', () => {
  const { api } = newContext();
  eq(api.coachMeta('narrow').startsWith('막힘 1/3'), true, 'narrow');
  eq(api.coachMeta('scaffold').startsWith('막힘 2/3'), true, 'scaffold');
  eq(api.coachMeta('explain').startsWith('막힘 3/3'), true, 'explain');
  eq(api.coachMeta('없는단계'), '더 쉬운 걸로 바꿔 물을게요', '모르는 단계는 예전 문구');
});
test('react 에 붙어 온 자료 인용은 카드로 그리니 본문에서 뗀다', () => {
  const { api } = newContext();
  const react = '괜찮아요, 같이 볼게요. 자료 3장은 이렇게 말해요: «손실은 돌아오는 과정에서 커진다»';
  eq(api.coachReactText(react, '손실은 돌아오는 과정에서 커진다'), '괜찮아요, 같이 볼게요.', '인용 제거');
  eq(api.coachReactText(react, ''), react, '인용이 없으면 그대로');
  eq(api.coachReactText('그냥 한 마디', '인용'), '그냥 한 마디', '« 가 없으면 그대로');
});

test('논문 근거 질문은 그 논문으로 가는 링크를 단다', () => {
  const { api } = newContext();
  const papers = [
    { id: 's04', cite_key: 'Paulsrud et al. (2026)', title: 'Sleep measures', url: 'https://doi.org/10.1016/j.sleep.2026.108965' },
    { id: 's05', cite_key: 'Bad et al. (2020)', url: 'javascript:alert(1)', doi: '10.1234/abc' },
    { id: 's06', cite_key: 'None et al. (2020)', url: 'javascript:alert(1)', doi: '' },
  ];
  const qs = api.attachQuestionPapers([
    { id: 'q1', question: 'Paulsrud et al. (2026)는 그렇게 봤는데 맞나요?', paper_ids: ['s04', 'zz'] },
    { id: 'q2', question: '자료만 묻는다', paper_ids: [] },
    { id: 'q3', question: 'x', paper_ids: ['s05', 's06'] },
  ], papers);
  eq(qs[0].papers.length, 1, '없는 id 는 버린다');
  eq(qs[0].papers[0].href, 'https://doi.org/10.1016/j.sleep.2026.108965', 'url 그대로');
  eq(qs[1].papers, undefined, '인용 없는 질문은 그대로');
  eq(qs[2].papers.map((r) => r.href).join(','), 'https://doi.org/10.1234/abc', 'http 아닌 url 은 DOI 로, 둘 다 없으면 뺀다');
  const html = api.linkCitedText(qs[0].question, qs[0].papers);
  eq(html.includes('<a class="msg-paper-link" href="https://doi.org/10.1016/j.sleep.2026.108965"'), true, '문장 속 인용에 링크');
  eq(html.includes('rel="noopener noreferrer"'), true, '새 창은 opener 를 끊는다');
  eq(api.questionPapersHtml([]), '', '문헌 없으면 줄도 없다');
  eq(api.questionPapersHtml(qs[0].papers).includes('Sleep measures'), true, '아래 줄에 제목');
  eq(api.attachQuestionPapers([{ id: 'q', paper_ids: ['s04'] }], undefined)[0].papers, undefined, 'papers 가 없는 옛 응답');
});

test('「이 질문의 근거」 는 자리·근거를 사람 말로 옮기고 영문 id 를 안 보인다', () => {
  const { api } = newContext();
  const probe = { kind: 'tension', node_ids: ['quality', 'time'],
    evidence: [{ slide_no: 4, quote: '수면의 질 = 시간 × 연속성 × 규칙성' }, { slide_no: 1, quote: '수면 시간보다 중요한 수면의 질' }] };
  const basis = { source: 'tension', slot: 'theme', rank: 1, probe, evidence: probe.evidence, checks: ['probe_template'] };
  eq(api.questionOriginLine(basis), '발표 주제 · 자료 1·4장에서 서로 부딪히는 표현', '장 번호는 정렬해서 한 번씩');
  eq(api.questionOriginLine({ source: 'core_weight', slot: '' }), '자료가 크게 다룬 개념', '배합 밖이면 근거만');
  eq(api.questionOriginLine({ source: 'missing', slot: 'weak' }), '더 짚어 볼 곳 · 자료에 있는데 발표에서 말하지 않은 개념', '탐침 아닌 약점');
  eq(api.questionOriginLine(null), '', '옛 세션 질문은 basis 가 없다');
  const html = api.questionOriginHtml({ basis });
  eq(html.startsWith('<details class="msg-origin"><summary>이 질문의 근거</summary>'), true, '접혀서 시작한다');
  eq(/tension|theme|probe_template/.test(html), false, '영문 id 가 화면에 안 나온다');
  eq(api.questionOriginHtml({}), '', 'basis 없으면 칸도 없다');
});

test('C-03 「이 질문의 근거」 는 장 번호만 — 자료 인용(함정이면 정답 줄)을 싣지 않는다', () => {
  const { api } = newContext();
  const fact = '대출 권수보다 더 중요한 것은 독서 경험입니다';
  // 함정: 근거 인용이 곧 바로잡은 사실 줄이다
  const trap = { trap: true, basis: { source: 'core_weight', slot: 'part', evidence: [{ slide_no: 1, quote: fact }, { slide_no: 1, quote: '같은 장' }] } };
  const t = api.questionOriginHtml(trap);
  eq(t.includes(fact), false, '함정의 사실 줄이 안 보인다');
  eq(t.includes('근거 자료 1장'), true, '어디를 보면 되는지는 말한다');
  // 함정이 아닌 질문도 답하기 전에는 인용을 안 싣는다
  const probe = { kind: 'tension', evidence: [{ slide_no: 4, quote: '수면의 질 = 시간 × 연속성 × 규칙성' }] };
  const p = api.questionOriginHtml({ basis: { source: 'tension', slot: 'theme', probe, evidence: probe.evidence } });
  eq(p.includes('수면의 질 = 시간'), false, '인용 없음');
  eq((p.match(/4장/g) || []).length, 1, '탐침 줄이 이미 장을 말하면 장 번호 줄을 또 달지 않는다');
});

test('B-01·H-07 함정 질문은 다른 질문과 같은 말풍선 — claim(주황)·함정 이유 줄이 없다', () => {
  const { ctx, api, turns } = newContext();
  const trapWhy = '「단백질 먼저」에 대해 질문이 말한 내용이 자료와 같은지 먼저 따져 보는 연습이에요.';
  ctx.qa.live = liveState(api, [{ id: 'q1', trap: true, question: '20%라고 했는데?', why: trapWhy, slide_nos: [6], label: '단백질 먼저' }]);
  api.presentLiveQuestion();
  const q = turns.find((t) => t.who === 'ai');
  eq(q.kind, 'question', '함정도 question');
  eq(q.basis.includes('따져'), false, '함정 이유 줄을 안 싣는다');
  eq(q.basis, '자료 6장을 근거로 설명할 수 있는지 보려고 물어요.', '장만 가리키는 중립 이유');
  eq(api.liveQuestionWhy({ why: ' 보통 이유 ' }), '보통 이유', '보통 질문은 서버 이유 그대로');
});

test('질문 묶음의 폴백 표시는 첫 질문 앞에 한 번 — 서버 질문을 못 찾은 것은 화면에 안 싣는다', () => {
  const { ctx, api, turns } = newContext();
  ctx.qa.live = liveState(api, [{ id: 'q1', question: 'a' }, { id: 'q2', question: 'b' }], { notes: ['문헌 검색이 늦어져 자료가 인용한 문헌만으로 질문을 만들었어요.'] });
  api.presentLiveQuestion();
  eq(turns[0].kind, 'note', '첫 질문 앞 안내 한 줄');
  eq(api.liveDegradedLines({ degraded: ['question_unverified', 'papers_timeout'], degraded_notes: ['개발용', '문헌 늦음'], grounded_on_server: false }), ['문헌 늦음']);
  eq(api.liveDegradedLines({ degraded: [], degraded_notes: [], grounded_on_deck: false }), ['자료 본문 없이 판정했어요.']);
  eq(api.liveDegradedLines(null), []);
});

/* ── 09-30 대화 감사 §10 — 판정에 보내는 대화 · 라운드 출구 ── */
test('판정 대화에는 지금 질문의 턴만 싣는다', () => {
  const { ctx, api } = newContext();
  ctx.qa.live = liveState(api, [{ id: 'q1', question: '왜요?' }, { id: 'q2', question: '어떻게요?' }], {
    qi: 1,
    results: [{ id: 'q1', question: '왜요?', answer: '끝난 답', verdict: 'good' }],
    turns: [{ question: '어떻게요?', questionId: 'q2', answer: '지금 답', verdict: 'partial' }],
  });
  const h = api.liveHistory();
  eq(h.map((t) => t.답변), ['지금 답'], '지금 질문의 답만');
  eq(h[0].question_id, 'q2', '조인 키');
});

test('세 번째 답에서 닫힌 질문은 설득한 수에서 뺀다', () => {
  const { api } = newContext();
  const rs = [
    { verdict: 'good', mastered: true, closeReason: 'good' },
    { verdict: 'partial', mastered: true, closeReason: 'rounds' },
    { verdict: 'partial', mastered: true, closeReason: 'guard' },
    { verdict: 'partial', mastered: true },               // 옛 세션 — partial 로 닫힌 건 라운드 출구다
    { verdict: 'partial', mastered: false, revealed: true },
  ];
  eq(rs.map((r) => api.liveForcedClose(r)), [false, true, true, true, false], '라운드 출구');
  eq(api.liveWonCount(rs), 1, '설득한 수');
});

test('코칭이 방금 되물었으면 그 되물음을 판정에 같이 싣는다', () => {
  const { ctx, api } = newContext();
  ctx.qa.live = liveState(api, [{ id: 'q1', question: '왜요?' }], {
    lastJudgement: { coach_stage: 'narrow', followup: "'가' 쪽인가요, '나' 쪽인가요?" },
  });
  eq(api.liveCoachAsk(), ["되물음: '가' 쪽인가요, '나' 쪽인가요?"], '코칭 되물음');
  ctx.qa.live.lastJudgement = { verdict: 'partial', followup: '더 말해 볼래요?' };
  eq(api.liveCoachAsk(), [], '판정 되물음은 싣지 않는다');
});

/* ── 09-30 held-out C-09 — 결과 네 묶음 · 헤드라인은 스스로 설명만 ── */
const R = {
  self: { verdict: 'good', mastered: true, closeReason: 'good', turns: 1, hintLevel: 0 },
  selfHint: { verdict: 'good', mastered: true, closeReason: 'good', turns: 2, hintLevel: 2, hintUsed: 1 },
  forced: { verdict: 'partial', mastered: true, closeReason: 'rounds', turns: 3 },
  guard: { verdict: 'partial', mastered: true, closeReason: 'guard', turns: 3 },
  hint3: { verdict: 'good', mastered: true, closeReason: 'good', turns: 1, hintLevel: 3, hintUsed: 3 },
  chip: { verdict: 'good', mastered: true, closeReason: 'good', turns: 2, viaCoach: true },
  retold: { verdict: 'partial', mastered: false, revealed: true, retold: true, answer: '다시 말한 답' },
  looked: { verdict: 'partial', mastered: false, revealed: true },
  coachedRetell: { verdict: 'unknown', mastered: false, gaveUp: true, revealed: true, coached: true, retold: true },
  skipped: { verdict: 'skipped', mastered: false, skipped: true },
  unasked: { verdict: 'skipped', mastered: false, unasked: true },
  stopped: { verdict: 'partial', mastered: false, stopped: true, answers: 2, answer: '두 번째 답' },
  labSkip: { verdict: 'skipped', mastered: false, answer: '(lab skip)' },
};
test('C-09 결과 묶음: 스스로·도움·답 보고 다시 말함·넘김 — 강제 닫힘·힌트 셋째 칸·보기는 「스스로」 가 아니다', () => {
  const { api } = newContext();
  const b = Object.fromEntries(Object.entries(R).map(([k, r]) => [k, api.liveBucket(r)]));
  eq(b, { self: 'self', selfHint: 'self', forced: 'helped', guard: 'helped', hint3: 'helped', chip: 'helped', retold: 'retold', looked: 'skipped',
    coachedRetell: 'retold', skipped: 'skipped', unasked: 'skipped', stopped: 'skipped', labSkip: 'skipped' }, '묶음');
  eq(api.liveWonCount(Object.values(R)), 2, '퀘스트 막대·헤드라인은 스스로 설명만');
  eq(api.liveBucket({ verdict: 'good', passed: true }), 'self', '옛 세션(mastered 없음)은 passed 로');
});
test('C-09 헤드라인 숫자는 스스로 설명한 것만 — 안 물은 질문은 분모에서도 뺀다', () => {
  const { api } = newContext();
  const mixed = api.liveResultSummary([R.self, R.forced, R.retold, R.unasked], { speech: false });
  eq([mixed.asked, mixed.self], [3, 1]);
  eq(mixed.head.includes('질문 3개 중') && mixed.head.includes('>1</b>개를 스스로 설명했어요'), true, mixed.head);
  eq(mixed.stats.map((x) => [x.key, x.n]), [['self', 1], ['helped', 1], ['retold', 1], ['skipped', 1]]);
  eq(mixed.sub.includes('근거 발화'), false, '자료만 쓴 세션에 「근거 발화와 함께」 를 약속하지 않는다');
  eq(api.liveResultSummary([R.self, R.forced], { speech: true }).sub.includes('근거 발화'), true);
  const all = api.liveResultSummary([R.self, R.selfHint], {});
  eq([all.allSelf, all.stats.length], [true, 0]);
  eq(all.head.includes('모두 스스로 설명했어요'), true);
  eq(all.sub.startsWith('힌트를 본 질문이 1개'), true, '누른 힌트만 센다');
  const none = api.liveResultSummary([R.forced, R.skipped], {});
  eq(/0\s*<\/b>개를|>0</.test(none.head), false, '0 을 앞세우지 않는다');
  eq(none.head.includes('다음엔 스스로 설명해 볼 질문'), true, none.head);
  eq(api.liveResultSummary([R.unasked], {}).head, '질문에 답하면 여기에 결과가 쌓여요');
});
test('C-09 결과·리포트 한 줄은 스스로 모순되지 않는다 — 「N번 만에」 는 스스로 설명에만', () => {
  const { api } = newContext();
  const row = (r) => api.liveResultRow(r);
  eq(row(R.self), { bucket: 'self', chip: '스스로 설명', cls: 'st-ok', meta: '첫 답에 설명했어요' });
  eq(row(R.selfHint).meta, '2번 만에 설명했어요 · 힌트 1번 봤어요');
  eq(row(R.forced).meta, '세 번째 답에서 닫혔어요');
  eq(row(R.guard).meta, '자료와 다시 맞춰 볼 곳이 남았어요');
  eq(row(R.chip).meta, '보기·빈칸 도움으로 닫았어요');
  eq(row(R.retold), { bucket: 'retold', chip: '답 보고 다시 말함', cls: 'st-om', meta: '답을 보고 내 말로 다시 말했어요' });
  eq(row(R.stopped).meta, '답 2번 하고 멈췄어요');
  eq([row(R.unasked).chip, row(R.looked).chip, row(R.skipped).chip], ['안 물음', '답만 봄', '넘김']);
  for (const r of Object.values(R)) {
    const x = row(r);
    if (x.bucket !== 'self' && /만에/.test(x.meta)) throw new Error(`스스로가 아닌 줄에 「만에」: ${JSON.stringify(x)}`);
  }
  eq(api.liveResultRow({ closeReason: 'guard' }, 'helped').meta, '자료와 다시 맞춰 볼 곳이 남았어요', '리포트는 저장한 묶음을 넘긴다');
});
test('B-09 판정에 보내는 힌트는 연 칸의 글 그대로 — 사다리가 갈아 끼워져도 본 적 없는 글이 안 간다', () => {
  const { ctx, api } = newContext();
  ctx.qa.live = liveState(api, [{ id: 'q1', hints: ['방향', '범위', '인용', '조각'] }]);
  api.openNextHint();
  ctx.qa.live.hintList = ['방향', '범위', '인용', '아직 안 나온 것: X'];   // 판정이 넷째 칸을 바꿔 끼웠다
  ctx.qa.live.lastJudgement = { coach_stage: 'narrow', followup: "'가' 쪽인가요?" };
  eq(api.liveHintsShown(), ['방향', "되물음: '가' 쪽인가요?"]);
  ctx.qa.live.hintsSeen = undefined;   // 옛 저장 세션
  eq(api.liveHintsShown(), ['방향', "되물음: '가' 쪽인가요?"], '옛 세션은 연 칸만큼 자른다');
});
test('L-05 저절로 열린 힌트는 「힌트 N번」 으로 안 센다', () => {
  const { ctx, api } = newContext();
  ctx.qa.live = liveState(api, [{ id: 'q1', hints: ['a', 'b', 'c'] }, { id: 'q2' }]);
  api.openNextHint({ auto: true });
  api.openNextHint();
  api.closeLiveQuestion({ id: 'q1', verdict: 'good', mastered: true, closeReason: 'good' });
  const r = ctx.qa.live.results[0];
  eq([r.hintLevel, r.hintUsed, api.liveHintsUsed(r)], [2, 1, 1]);
  eq(ctx.qa.live.hintAuto, 0, '다음 질문은 새로 센다');
  eq(api.liveHintsUsed({ hintLevel: 2 }), 2, '옛 결과는 hintLevel');
});
test('M-11 「여기까지 하고 저장」 — 답한 질문은 시도를 남기고(멈춤), 띄우지 않은 질문은 「안 물음」', () => {
  const { ctx, api, turns } = newContext();
  ctx.qaLiveEnd = () => {};
  ctx.qa.live = liveState(api, [{ id: 'q1', label: 'A', question: 'a?' }, { id: 'q2', label: 'B', question: 'b?' }, { id: 'q3', label: 'C', question: 'c?' }], {
    turn: 2,
    turns: [{ answer: '첫 답', verdict: 'wrong', score: 30 }, { answer: '(모르겠어요)', verdict: 'unknown', gaveUp: true }, { answer: '둘째 답', verdict: 'partial', score: 65 }],
  });
  api.finishLiveQaEarly();
  const rs = ctx.qa.live.results;
  eq([rs[0].stopped, rs[0].answer, rs[0].answers, rs[0].viaCoach, rs[0].verdict], [true, '둘째 답', 2, true, 'partial'], '지금 질문');
  eq([rs[1].unasked, rs[2].unasked], [true, true], '남은 질문');
  eq(rs.map((r) => api.liveBucket(r)), ['skipped', 'skipped', 'skipped']);
  eq(turns.filter((t) => t.kind === 'lost').map((t) => t.text), ['A — 답 2번 하고 멈췄어요. 한 답을 리포트에 남겨둘게요', '남은 질문 2개는 묻지 않고 마쳤어요']);
});
test('M-11 답이 없으면 넘김, 답을 보고 다시 말하던 중이면 「답만 봄」 으로 닫는다', () => {
  const { ctx, api } = newContext();
  ctx.qaLiveEnd = () => {};
  ctx.qa.live = liveState(api, [{ id: 'q1', label: 'A' }]);
  api.finishLiveQaEarly();
  eq([ctx.qa.live.results[0].skipped, ctx.qa.live.results[0].answer], [true, '']);
  const b = newContext();
  b.ctx.qaLiveEnd = () => {};
  b.ctx.qa.live = liveState(b.api, [{ id: 'q1', label: 'A' }], { retell: { model: 'm', record: { id: 'q1', label: 'A', revealed: true, verdict: 'wrong', answer: '틀린 답' } } });
  b.api.finishLiveQaEarly();
  eq(b.api.liveBucket(b.ctx.qa.live.results[0]), 'skipped');
  eq(b.api.liveResultRow(b.ctx.qa.live.results[0]).chip, '답만 봄');
});
test('문장 한가운데서 끊긴 모범답은 마지막 온전한 문장까지', () => {
  const { api } = newContext();
  eq(api.liveWholeSentences('A 해요. B 를 진행…'), 'A 해요.');
  eq(api.liveWholeSentences('3.5% 예요. 계속…'), '3.5% 예요.');
  eq(api.liveWholeSentences('안 잘린 글이에요.'), '안 잘린 글이에요.');
  eq(api.liveWholeSentences('끝이 없는 잘린…'), '끝이 없는 잘린…');
});

/* ── 09-30 held-out H-15 — 요청 제한은 판정 실패가 아니다 ── */
test('H-15 요청 제한(429)은 기다렸다 두 번까지 다시, AI 지연(503 upstream)은 한 번, 그 밖은 안 다시', () => {
  const rate = { code: 'rate_limited', status: 429, rateLimited: true, retryAfter: 45 };
  eq(BRIDGE.judgeRetryPlan(rate, 0), { retry: true, waitSec: 45, reason: 'rate' });
  eq(BRIDGE.judgeRetryPlan(rate, 1).retry, true);
  eq(BRIDGE.judgeRetryPlan(rate, 2), { retry: false, waitSec: 0, reason: 'rate' });
  eq(BRIDGE.judgeRetryPlan({ status: 429 }, 0).waitSec, 5, 'retry_after 가 없으면 5초');
  eq(BRIDGE.judgeRetryPlan({ status: 429, retryAfter: 600 }, 0).waitSec, 60, '60초로 자른다');
  eq(BRIDGE.judgeRetryPlan({ code: 'upstream_timeout', status: 503, retryAfter: 10 }, 0), { retry: true, waitSec: 10, reason: 'upstream' });
  eq(BRIDGE.judgeRetryPlan({ code: 'upstream_unavailable', status: 503 }, 1).retry, false, '한 번만');
  for (const e of [{ code: 'session_missing', status: 409 }, { code: 'server_unreachable' }, { code: 'upstream_failed', status: 502 }, null]) {
    eq(BRIDGE.judgeRetryPlan(e, 0).retry, false, JSON.stringify(e));
  }
});
test('H-15 끝내 막힌 요청 제한은 출구(답 보기)를 열지 않고 「넘긴 질문」 으로 안 남긴다 — 서버가 죽은 것과 다르다', () => {
  const { ctx, api } = newContext();
  const f = api.liveJudgeFailure({ code: 'rate_limited', status: 429, rateLimited: true, message: '요청이 너무 잦아요.' });
  eq([f.judgeFailed, f.restore, f.retryOnReconnect], [false, true, null]);
  ctx.qa.live = liveState(api, [{ id: 'q1', hints: ['a'] }], { judgeFailed: f.judgeFailed, turns: [{ score: 40 }] });
  eq(api.liveStalled(), false, '요청 제한 한 번으로 답 보기 출구가 열리지 않는다');
  eq(api.liveJudgeFailure({ code: 'server_unreachable' }).judgeFailed, true, '서버가 끊긴 것은 출구를 연다');
  eq(api.liveJudgeFailure({ code: 'server_unreachable' }, true).retryOnReconnect, { giveUp: true });
  eq(api.liveJudgeFailure({ code: 'cancelled' }).text, '', '화면을 떠나 취소된 것은 말하지 않는다');
  eq(api.liveJudgeFailure({ code: 'rate_limited' }, true).restore, false, '포기 자리표시자는 되살리지 않는다');
  eq(api.liveRetryWaitText(9.1), '요청이 몰려서 잠깐 기다렸다 다시 보낼게요 · 10초');
});
test('답변 받아쓰기 본문 — 세션 id 를 맨 앞에 싣는다 (브리지가 purpose=qa_answer 는 보관하지 않는다, 09-30)', () => {
  eq(BRIDGE.ANSWER_STT_SENDS_SESSION, true, '켬 — 요청 제한을 세션마다 세게 한다 (H-15)');
  const def = BRIDGE.answerSttBody({ sessionId: '20260930T015107Z_abcdef12', audioBase64: 'AAA', ext: '.webm' });
  eq(Object.keys(def)[0], 'session_id');
  eq([def.purpose, def.marks, def.audio_base64, def.ext], ['qa_answer', [], 'AAA', '.webm']);
  const off = BRIDGE.answerSttBody({ sessionId: '20260930T015107Z_abcdef12', audioBase64: 'AAA', ext: '.webm', sendSession: false });
  eq('session_id' in off, false);
  const on = BRIDGE.answerSttBody({ sessionId: '20260930T015107Z_abcdef12', audioBase64: 'AAA', ext: '.webm', sendSession: true });
  eq(Object.keys(on)[0], 'session_id', '켜면 맨 앞 — 큰 본문에서 정규식이 바로 찾는다');
  eq('session_id' in BRIDGE.answerSttBody({ sessionId: null, sendSession: true }), false, '세션이 없으면 안 싣는다');
});

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
