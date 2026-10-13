/**
 * Q&A 무대 「띠 · 틀 · 레일」 순간 계산 스모크 — 원본 main/web/js/qa_stage.js (클래식 스크립트, 최상위는 선언 · 이벤트 등록뿐).
 *
 *   node etc/tests/js/qa_stage.smoke.mjs
 *
 * 왜 있나 — 화면 전체가 qsScene 하나만 읽는다(한 순간에 주된 행동 하나). 순간이 틀리면 버튼이 엉뚱하게 뜬다.
 * ① 끝 > 주제 바꾸는 중 > 판정 기다림 > 곧 보내요 > 막힘(도움 열림) > 묻기(읽는 시간 안 · 아직 말 안 함) > 답하기
 * ② 도움은 이 물음 뒤 힌트 · 펼친 답(내가 다시 답하면 끝), 또는 이 물음을 부른 막힘 사다리 응답
 * ③ 이 물음을 부른 반응은 판정 반응만(코칭 응답은 반응이 아니라 도움). 마지막 케이스는 하네스 자가 검사.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const SRC = readFileSync(path.join(ROOT, 'main/web/js/qa_stage.js'), 'utf8');

const ctx = vm.createContext({ window: { addEventListener() {} }, console });
vm.runInContext(`${SRC}\n;globalThis.__s = { qsScene, qsPlain, qsReadMs, qsHelp };`, ctx);
const S = ctx.__s;

let failed = 0;
function check(name, ok) {
  if (ok) console.log(`  ok  ${name}`);
  else { failed++; console.log(`  FAIL ${name}`); }
}

const L = { qi: 1, questions: [{}, {}, {}], busy: false };
const q1 = { who: 'ai', kind: 'question', text: '첫 질문이에요?' };
const me1 = { who: 'me', text: '음… 한 플랫폼 데이터만 &amp; 썼어요' };
const react = { who: 'ai', kind: 'react', verdict: 'partial', text: '요지는 잡았어요.' };
const q2 = { who: 'ai', kind: 'question', text: '분석 대상은 <a href="#">어떻게</a> 정의했나요?' };
const turns = [q1, me1, react, q2];
const now = 100000;
const fresh = { now, askAt: now - 500 };
const late = { now, askAt: now - 60000 };

check('글자 풀기 — 태그 · 엔티티', S.qsPlain(q2.text) === '분석 대상은 어떻게 정의했나요?' && S.qsPlain(me1.text) === '음… 한 플랫폼 데이터만 & 썼어요');
check('읽는 시간 1.6~7초', S.qsReadMs('짧') === 1600 && S.qsReadMs('가'.repeat(200)) === 7000);
let sc = S.qsScene(L, turns, fresh);
check('막 뜬 꼬리질문 = 묻기', sc.phase === 'asking' && sc.question === '분석 대상은 어떻게 정의했나요?');
check('이 물음을 부른 판정 반응', sc.react && sc.react.verdict === 'partial' && sc.react.text === '요지는 잡았어요.');
check('말하기 시작하면 = 답하기', S.qsScene(L, turns, { ...fresh, text: '분석은' }).phase === 'listening');
check('읽는 시간이 지나면 = 답하기', S.qsScene(L, turns, late).phase === 'listening');
check('곧 보내요', S.qsScene(L, turns, { ...late, text: 'x', sending: true }).phase === 'sending');
check('판정 기다림 = 생각', S.qsScene({ ...L, busy: true }, [...turns, { who: 'me', text: '보낸 답' }], late).phase === 'thinking');
check('생각 중엔 보낸 답을 보여 준다', S.qsScene({ ...L, busy: true }, [...turns, { who: 'me', text: '보낸 답' }], late).answer === '보낸 답');
check('주제 바꾸는 중', S.qsScene({ ...L, switching: '다른 개념을 찾고 있어요' }, turns, late).phase === 'switching');
check('끝 — 다 마침', S.qsScene({ ...L, awaitEnd: true }, turns, late).phase === 'done' && S.qsScene({ ...L, qi: 3 }, turns, late).phase === 'done');

const hint = { who: 'ai', kind: 'hint', level: 1, total: 3, text: '자료 2장 표', slides: ['2'] };
sc = S.qsScene(L, [...turns, hint], fresh);
check('힌트를 열면 = 막힘(격려)', sc.phase === 'encouraging' && sc.help.tag === '힌트 1/3' && sc.help.slide === 2);
check('다시 답하면 힌트는 닫힌다', S.qsHelp([...turns, hint, { who: 'me', text: '다시' }], 3) === null);
const coach = { who: 'ai', kind: 'react', coach: 'narrow', text: '같이 찾아봐요', quoteSlide: 4 };
const q3 = { who: 'ai', kind: 'question', text: '좁힌 질문' };
sc = S.qsScene(L, [q1, { who: 'me', text: '모르겠어요' }, coach, q3], fresh);
check('막힘 사다리가 부른 질문 = 막힘, 판정 반응 아님', sc.phase === 'encouraging' && sc.react === null && sc.help.tag.startsWith('막힘 1/3') && sc.help.slide === 4);
const gist = { who: 'ai', kind: 'gist', mid: true, text: '이렇게 말하면 돼요' };
sc = S.qsScene(L, [q1, me1, react, gist, q2], fresh);
check('절반 펼친 답 뒤 꼬리질문 = 막힘(완성 문장)', sc.phase === 'encouraging' && sc.help.tag === '이렇게 말하면 완성이에요' && sc.react.verdict === 'partial');
check('끝난 질문 앞 도움은 새 질문에 안 넘어온다', S.qsHelp([q1, hint, me1, { who: 'sys', kind: 'done' }, q2], 4) === null);
check('질문이 없으면 null', S.qsScene(null, [], fresh) === null);

// 하네스 자가 검사 — 「내 답 앞에서 멈추지 않는」 잘못된 도움 규칙을 잡아내는가
const broken = (ts) => ts.slice().reverse().find((t) => t.kind === 'hint') || null;
const after = [q1, hint, me1, { who: 'sys', kind: 'done' }, q2];
check('하네스가 회귀를 잡는다', broken(after) !== null && S.qsHelp(after, 4) === null);

if (failed) { console.log(`\n${failed} failed`); process.exit(1); }
console.log('\nqa_stage: all ok');
