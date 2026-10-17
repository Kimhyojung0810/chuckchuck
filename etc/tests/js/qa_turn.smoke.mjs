/**
 * Q&A 턴 시각 · 말 끝 판단(js/qa_turn.js) 순수 함수 스모크 (2026-10-17 tune).
 *
 *   node etc/tests/js/qa_turn.smoke.mjs
 *
 * 말 끝 판단은 이 서버에서 손으로 말해 볼 수 없다(마이크 없음). 그래서 「어떤 말끝에서 얼마나 기다리나」 · 「주소로 켜는 설정」 ·
 * 「턴 시각 요약」 을 여기서 잡는다. 마지막 케이스는 하네스가 진짜로 회귀를 잡는지 스스로 검사한다.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const SRC = readFileSync(path.join(ROOT, 'main/web/js/qa_turn.js'), 'utf8');

function load(src = SRC, search = '') {
  const logs = [];
  const box = { console: { info: (...a) => logs.push(a.join(' ')) }, location: { search }, performance: { now: () => box.__t }, __t: 0, URLSearchParams };
  box.window = box;
  vm.runInNewContext(src, box);
  return { Q: box.QaTurn, box, logs };
}

const cases = [];
function test(name, fn) { cases.push({ name, fn }); }
function eq(a, b, msg = '') {
  const A = JSON.stringify(a), B = JSON.stringify(b);
  if (A !== B) throw new Error(`${msg}\n  expected ${B}\n  got      ${A}`);
}

test('종결어미는 final · 잇는 말은 cont · 이어 말하기 잦은 해요체는 soft', () => {
  const { Q } = load();
  for (const t of ['수집 방식의 결과라서 그래요.', '표본이 얇다고 봐요', '결론은 현상 수준까지입니다', '그렇게 볼 수 있죠?', '왜 그럴까요', '차이가 작다'])
    eq(Q.endKind(t), 'final', t);
  for (const t of ['리뷰 이벤트가 있었고', '표본이 네 개인데', '조건을 묶어서', '그래서', '음...', '그러니까 결국', '첫째로,', '온도를 올리면'])
    eq(Q.endKind(t), 'cont', t);
  for (const t of ['표본이 좀 적은데요', '그게 핵심이거든요', '조건을 묶었고요']) eq(Q.endKind(t), 'soft', t);
  eq(Q.endKind(''), 'none');
});

test('기본은 예전 그대로 — 일괄 2.2초 · 초읽기 3초 · 미리 판정은 초읽기 때', () => {
  const { Q } = load();
  const c = Q.cfg();
  eq([c.eot, c.silenceMs, c.sendMs, c.spec], ['fixed', 2200, 3000, 'quiet']);
  eq(Q.silenceFor('그래서', c), 2200);
  eq(Q.silenceFor('그래요.', c), 2200);
});

test('?qa_turn=fast 는 어미로 기다리고 초읽기 1.2초 · 문장 확정 때 미리 판정', () => {
  const { Q } = load(SRC, '?qa_turn=fast');
  const c = Q.cfg();
  eq([c.eot, c.sendMs, c.spec], ['ending', 1200, 'final']);
  eq(Q.silenceFor('그래요.', c), 900);
  eq(Q.silenceFor('표본이 적은데요', c), 1800);
  eq(Q.silenceFor('조건을 묶어서', c), 3200);
  eq(Q.silenceFor('A.X', c), 2200, '모르는 끝은 일괄 값');
});

test('주소 값은 범위 안만 — 300~8000ms', () => {
  const { Q } = load();
  eq(Q.config('?qa_silence_ms=100&qa_send_ms=9000&qa_eot=ending&qa_spec=off&qa_final_ms=700'),
    { eot: 'ending', silenceMs: 2200, sendMs: 3000, spec: 'off', finalMs: 700, softMs: 1800, contMs: 3200 });
  eq(Q.config('?qa_eot=zzz').eot, 'fixed');
});

test('턴 시각 — 말 끝(마지막 eos)에서 각 지점까지, 한 번만 찍는 칸 · 덮어쓰는 칸', () => {
  const { Q, box, logs } = load();
  const at = (ms) => { box.__t = ms; };
  at(0); Q.begin('0|0|0|0');
  at(500); Q.mark('speech_on');
  at(2500); Q.mark('speech_off'); Q.mark('final');
  at(3000); Q.mark('speech_on');            // 더 말함 — speech_on 은 첫 번째 그대로
  at(5000); Q.mark('speech_off');
  at(5050); Q.mark('final');
  at(6000); Q.mark('quiet', { eotKind: 'final' }); Q.mark('spec');
  at(7200); Q.mark('send'); Q.mark('ack');
  at(8000); Q.mark('judged', { specHit: 1.9 });
  at(8020); Q.mark('next');
  const t = Q.finish('judged');
  eq(t.t.speech_on, 500);
  eq(t.sum.eot_to_final, 50);
  eq([t.sum.eot_to_quiet, t.sum.eot_to_send, t.sum.eot_to_ack, t.sum.eot_to_next], [1000, 2200, 2200, 3020]);
  eq([t.sum.judge_wait, t.sum.spec_hit, t.sum.finals, t.sum.eot_kind], [800, 1.9, 2, 'final']);
  eq(box.__qaTurns.length, 1);
  if (!logs.some((l) => l.startsWith('[qa-turn]'))) throw new Error('콘솔 한 줄이 없어요');
  Q.begin('0|1|0|1'); at(9000); Q.finish('replaced');
  eq(logs.length, 1, '보내지 않은 턴은 콘솔에 안 남긴다');
});

test('하네스 자체 검사 — 어미 판단을 망가뜨리면 위 케이스가 깨진다', () => {
  const broken = SRC.replace("if (SOFT_END_RE.test(t)) return 'soft';", '');
  const { Q } = load(broken);
  if (Q.endKind('표본이 좀 적은데요') === 'soft') throw new Error('고장 낸 판이 통과했어요 — 하네스가 회귀를 못 잡아요');
});

let fail = 0;
for (const { name, fn } of cases) {
  try { fn(); console.log(`✓ ${name}`); } catch (e) { fail += 1; console.log(`✗ ${name}\n${e.message}`); }
}
console.log(`\n${cases.length - fail}/${cases.length} 통과`);
process.exit(fail ? 1 : 0);
