/**
 * Q&A 「생각 엮기」 순수 함수 스모크 — 원본 main/web/js/qa_weave.js (클래식 스크립트, 최상위는 선언 · 이벤트 등록뿐).
 *
 *   node etc/tests/js/qa_weave.smoke.mjs
 *
 * 왜 있나 — 흔적 · 내 발언 칩은 qa.live 를 그대로 읽어야 한다(브리프 「가짜 이해 완료 금지」). 특히
 * ① 내 발언은 서버가 확인한 claim 만 — 비면 칩이 없다 ② 꼬리질문 출처는 마지막 채점 답 → 그 판정의 followup 뿐(코칭 되물음 · 다시 말하기는 잇지 않는다)
 * ③ 같은 개념이면 실이 이어지고(관점 바꾸기) 바뀌면 끊긴다. 마지막 케이스는 하네스 자가 검사.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const SRC = readFileSync(path.join(ROOT, 'main/web/js/qa_weave.js'), 'utf8');

const ctx = vm.createContext({ window: { addEventListener() {} }, console, liveBucket: (r) => (r && r.mastered ? 'self' : 'skipped') });
vm.runInContext(`${SRC}\n;globalThis.__w = { qwModel, qwTopicText, qwAskMeta, qwClaimLinked };`, ctx);
const W = ctx.__w;

let failed = 0;
function check(name, ok) {
  if (ok) console.log(`  ok  ${name}`);
  else { failed++; console.log(`  FAIL ${name}`); }
}

const qs = [
  { id: 'q1', node_id: 'a', label: '실험 설계', question: '통제는?' },
  { id: 'q1~counter', node_id: 'a', label: '실험 설계', question: '반례는?', perspectiveName: '반례' },
  { id: 'q2', node_id: 'b', label: '결과 해석', question: '왜?' },
];
const L = {
  qi: 1, questions: qs,
  results: [{ id: 'q1', setAside: 'perspective', trail: [{ q: '통제는?', claim: '나머지는 묶었다' }, { q: '꼬리', claim: '' }] }],
  turns: [{ question: '반례는?', answer: '...', claim: '로트가 같다', verdict: 'partial' }],
  lastJudgement: { followup: '로트가 다르면요?', claim: '로트가 같다' },
};
const m = W.qwModel(L);
check('지난 질문 + 지금 질문 마디', m.knots.length === 2 && m.knots[1].now && !m.knots[0].now);
check('내려놓은 질문은 aside', m.knots[0].state === 'aside');
check('지난 마디는 비지 않은 발언만', JSON.stringify(m.knots[0].claims) === '["나머지는 묶었다"]');
check('같은 개념이면 실이 이어진다', m.knots[1].joined === true);
check('꼬리질문 출처 = 마지막 채점 답의 발언', m.claim && m.claim.text === '로트가 같다' && m.claim.round === 1);
check('이름표 — 개념 · 관점 · 꼬리질문', W.qwAskMeta(m, L) === '실험 설계 · 반례 관점 · 꼬리질문 1');
check('관점 바꾼 질문의 주제 이름', W.qwTopicText(L) === '같은 주제 · 반례 관점');

// 10-13 실측 — 판정기의 고정 문구 꼬리질문은 발언을 붙잡지 않는다. 그때는 「내 말에서」 를 달지 않는다
const canned = '「2C 충전은 500 사이클에서 용량의 4분의 1을 깎았다」에 대한 질문이에요. 자료 3장을 다시 보고, 그 장이 하는 말을 한 문장으로 말해 볼래요?';
check('발언을 안 붙잡은 꼬리질문엔 잇지 않는다', W.qwModel({ ...L, turns: [{ ...L.turns[0], claim: '온도를 25도로 맞췄을 때' }], lastJudgement: { followup: canned } }).claim === null);
check('발언 낱말을 쓴 꼬리질문은 잇는다', W.qwClaimLinked('온도를 25도로 맞췄을 때', '25도라는 조건을 바꾸면 결과가 그대로일까요?') === true);
check('어미만 겹치면 이어진 게 아니다', W.qwClaimLinked('상황마다 다를 것 같아요', '자료 3장은 무엇을 말하나요? 같아요') === false);
check('발언이 비면 칩이 없다', W.qwModel({ ...L, turns: [{ ...L.turns[0], claim: '' }] }).claim === null);
check('코칭 되물음은 발언에서 나온 꼬리질문이 아니다', W.qwModel({ ...L, lastJudgement: { followup: 'x', coach_stage: 'narrow' } }).claim === null);
check('다시 말하기 중이면 잇지 않는다', W.qwModel({ ...L, retell: { model: 'm' } }).claim === null);
check('포기 · 되물음 턴은 발언으로 안 센다', W.qwModel({ ...L, turns: [{ claim: '로트', gaveUp: true }] }).claim === null);
const next = W.qwModel({ ...L, qi: 2, results: [...L.results, { id: 'q1~counter', mastered: true, trail: [] }], turns: [] });
check('개념이 바뀌면 실이 끊긴다', next.knots[2].joined === false && next.knots[1].state === 'self');
check('다음 개념 주제 이름', W.qwTopicText({ ...L, qi: 2, results: [...L.results, {}] }) === '다음 개념 · 결과 해석');
check('다른 개념으로 간 주제 이름', W.qwTopicText({ ...L, qi: 2, results: [...L.results, { setAside: 'concept' }] }) === '다른 개념 · 결과 해석');
check('다 마쳤으면 지금 마디가 없다', W.qwModel({ ...L, awaitEnd: true }).knots.every((k) => !k.now));
check('질문이 없으면 null', W.qwModel(null) === null);

// 하네스 자가 검사 — 코칭 되물음까지 발언에 잇는 잘못된 규칙을 잡아내는가
const broken = (x) => { const t = x.turns[x.turns.length - 1]; return t && t.claim && x.lastJudgement.followup ? t.claim : null; };
const coached = { ...L, lastJudgement: { followup: 'x', coach_stage: 'narrow' } };
check('하네스가 회귀를 잡는다', broken(coached) !== null && W.qwModel(coached).claim === null);

if (failed) { console.log(`\n${failed} failed`); process.exit(1); }
console.log('\nqa_weave: all ok');
