/**
 * 발표를 들으며 3번+ 질문 준비(js/qa_listen.js) 순수 함수 스모크 — 브라우저 없이.
 *
 *   node etc/tests/js/qa_listen.smoke.mjs
 *
 * 왜 있나 — 받아쓰기 확정문은 누적으로 온다. 늘어난 부분만 지금 보던 장에 붙이지 않으면 앞 장의 말이 뒷장에 다시 붙고,
 * 장을 떠날 때 보내지 않으면 서버가 「다 들었다」 를 몰라 여러 장에 걸친 주장의 신호를 영영 못 본다.
 * qa_listen.js 는 클래식 스크립트라 vm 에 원본 그대로 올린다. 마지막 케이스는 하네스가 진짜로 회귀를 잡는지 스스로 검사한다.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const SRC = readFileSync(path.join(ROOT, 'main/web/js/qa_listen.js'), 'utf8');

function load(src) {
  const ctx = { console, window: {}, module: { exports: {} } };
  vm.createContext(ctx);
  vm.runInContext(src, ctx, { filename: 'qa_listen.js' });
  return ctx.module.exports;
}

const cases = [];
const test = (name, fn) => cases.push({ name, fn });
const eq = (a, b, msg) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${msg}: ${JSON.stringify(a)} !== ${JSON.stringify(b)}`); };

function run(L, events) {
  let st = null;
  const sent = [];
  for (const ev of events) {
    const r = L.qaListenReduce(st, ev);
    st = r.state;
    sent.push(...r.send);
  }
  return { st, sent };
}

test('늘어난 확정문만 지금 장에 붙는다 · 장을 떠나면 그 장 전체를 닫아서 보낸다', () => {
  const L = load(SRC);
  const { st, sent } = run(L, [
    { type: 'text', final: '첫 장 말이에요.', slide: 1 },
    { type: 'text', final: '첫 장 말이에요. 둘째 문장.', slide: 1 },
    { type: 'turn', from: 1, to: 2 },
    { type: 'text', final: '첫 장 말이에요. 둘째 문장. 2장 말이에요.', slide: 2 },
    { type: 'end' },
  ]);
  eq(st.slides[1], '첫 장 말이에요. 둘째 문장.', '1장');
  eq(st.slides[2], '2장 말이에요.', '2장 — 앞 장 말이 다시 붙지 않는다');
  eq(sent.map((x) => [x.slide_no, x.closed, !!x.final]), [[1, true, false], [2, true, true]], '보낸 것');
});

test('받아쓰기를 다시 열어 확정문이 처음부터 오면 전부 새 말로 센다', () => {
  const L = load(SRC);
  eq(L.qaListenDelta('긴 앞 말이에요.', '새로 연 말'), '새로 연 말', '줄어든 확정문');
  eq(L.qaListenDelta('', ''), '', '빈 것');
});

test('말이 없던 장도 떠나면 닫힘을 보낸다 (여러 장에 걸친 주장)', () => {
  const L = load(SRC);
  const { sent } = run(L, [{ type: 'text', final: '', slide: 1 }, { type: 'turn', from: 1, to: 2 }]);
  eq(sent, [{ slide_no: 1, text: '', closed: true }], '빈 장 닫힘');
});

test('하네스 자기 검사 — 늘어난 부분 대신 전체를 붙이면 잡는다', () => {
  const broken = SRC.replace('if (f.startsWith(p)) return f.slice(p.length).trim();', 'if (f.startsWith(p)) return f.trim();');
  if (broken === SRC) throw new Error('자기 검사 대상 줄을 못 찾았어요');
  const { st } = run(load(broken), [
    { type: 'text', final: '첫 장.', slide: 1 }, { type: 'turn', from: 1, to: 2 }, { type: 'text', final: '첫 장. 2장.', slide: 2 },
  ]);
  if (st.slides[2] === '2장.') throw new Error('망가진 원본을 못 잡았어요');
});

let failed = 0;
for (const c of cases) {
  try { c.fn(); console.log(`ok  ${c.name}`); } catch (e) { failed += 1; console.error(`FAIL ${c.name}\n  ${e.message}`); }
}
if (failed) { console.error(`${failed}개 실패`); process.exit(1); }
console.log(`qa_listen smoke ${cases.length}개 통과`);
