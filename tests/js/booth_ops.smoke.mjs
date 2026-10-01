/**
 * 부스 운영 장치(booth_ops.js) 스모크 — 브라우저 없이.
 *
 *   node tests/js/booth_ops.smoke.mjs
 *
 * 왜 있나 — 2026-10-01 화상판(/booth/call)에서 마지막 질문을 닫으면 탭이 멈췄다. 끝 카드 초읽기(bqArmAutoEnd)가 같은 글이어도
 * textContent 를 다시 써서 답 칸 감시(MutationObserver)를 깨우고, 그 감시가 다시 bqArmAutoEnd 를 불렀다. 실험실이 그 길(질문 3개를
 * 끝까지 닫기)을 안 밟아 놓쳤다. 감시 고리는 브라우저에서만 돌지만, 「같은 글은 다시 쓰지 않는다」 는 여기서 지킬 수 있다.
 * booth_ops.js 는 클래식 스크립트라 vm 에 원본 그대로 올린다 — 사본이 아니다.
 *
 * 마지막 케이스는 하네스가 진짜로 회귀를 잡는지 스스로 검사한다 (booth.smoke.mjs 와 같은 규율).
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const SRC = readFileSync(path.join(ROOT, 'demo/YEHS_demo/js/booth_ops.js'), 'utf8');

/** 글 쓰기 수를 세는 끝 카드 초읽기 칸 */
function fakeNote() {
  let text = '';
  const el = { writes: 0 };
  Object.defineProperty(el, 'textContent', {
    get: () => text,
    set: (v) => { el.writes += 1; text = String(v); },
  });
  return el;
}

function load(src, { qa, note = fakeNote() } = {}) {
  const timers = [];
  const ctx = {
    console,
    qa,
    bq: { screen: 'qa' },
    document: { querySelector: (sel) => (sel.includes('qa-end-note') ? note : null), getElementById: () => null },
    setInterval: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    clearInterval: () => {},
    setTimeout: () => 0,
    clearTimeout: () => {},
    sessionStorage: { getItem: () => null, setItem: () => {} },
    location: { reload: () => {} },
    qaLiveEnd: () => { ctx.ended = (ctx.ended || 0) + 1; },
    bqIsFollowUp: (t) => !String(t.meta || '').startsWith('예상 질문'),   // booth_qa.js 와 같은 규칙
  };
  vm.createContext(ctx);
  vm.runInContext(src, ctx, { filename: 'booth_ops.js' });
  return { ctx, note, timers };
}

const cases = [];
const test = (name, fn) => cases.push({ name, fn });
const eq = (a, b, msg) => { if (a !== b) throw new Error(`${msg}: ${JSON.stringify(a)} !== ${JSON.stringify(b)}`); };

const endQa = () => ({ live: { awaitEnd: true, questions: [{}, {}, {}], qi: 3 }, turns: [] });

test('P0 끝 카드 초읽기 — 같은 글은 다시 쓰지 않는다 (감시가 다시 깨지 않게)', () => {
  const { ctx, note } = load(SRC, { qa: endQa() });
  ctx.bqArmAutoEnd();
  eq(note.writes, 1, '처음 한 번');
  for (let i = 0; i < 50; i += 1) ctx.bqArmAutoEnd();   // 감시가 몇 번을 불러도
  eq(note.writes, 1, '같은 초에는 다시 안 쓴다');
  eq(note.textContent, '12초 뒤 결과를 보여 줘요', '글');
});

test('P0 초읽기 타이머는 하나만 — 매초 한 번 쓰고, 0초에 결과로 간다', () => {
  const { ctx, note, timers } = load(SRC, { qa: endQa() });
  ctx.bqArmAutoEnd();
  ctx.bqArmAutoEnd();
  eq(timers.length, 1, '타이머 하나');
  for (let i = 0; i < 11; i += 1) timers[0].fn();
  eq(note.textContent, '1초 뒤 결과를 보여 줘요', '1초 남음');
  eq(note.writes, 12, '매초 한 번씩');
  timers[0].fn();
  eq(ctx.ended, 1, '결과로 간다');
});

test('질문이 남았으면 초읽기를 안 건다', () => {
  const { ctx, note, timers } = load(SRC, { qa: { live: { awaitEnd: false, questions: [{}], qi: 0 }, turns: [] } });
  ctx.bqArmAutoEnd();
  eq(timers.length, 0, '타이머 없음');
  eq(note.writes, 0, '안 씀');
});

const askQa = (q, turns = []) => ({
  live: { awaitEnd: false, questions: [q], qi: 0 },
  turns: [{ who: 'ai', kind: 'question', meta: '예상 질문 1/1 · 보통이에요' }, ...turns],
});

test('P2-1 자료 창 — 질문이 근거로 든 장(evidence_slide_no)이 먼저', () => {
  const { ctx } = load(SRC, { qa: askQa({ slide_nos: [2, 4, 8], evidence_slide_no: 4 }) });
  const f = ctx.bqFocusSlide();
  eq(f.no, 4, '근거 장');
  eq(f.why, '질문이 가리키는', '까닭');
});

test('근거 장이 없으면 표지(1장)보다 다른 장', () => {
  eq(load(SRC, { qa: askQa({ slide_nos: [1, 3] }) }).ctx.bqFocusSlide().no, 3, '비표지');
  eq(load(SRC, { qa: askQa({ slide_nos: [1] }) }).ctx.bqFocusSlide().no, 1, '표지뿐');
});

test('판정 근거가 장을 가리키면 그 장이 질문 장보다 먼저', () => {
  const { ctx } = load(SRC, { qa: askQa({ slide_nos: [2], evidence_slide_no: 2 }, [{ who: 'me', kind: 'say' }, { who: 'ai', kind: 'react', groundSlides: [6] }]) });
  const f = ctx.bqFocusSlide();
  eq(f.no, 6, '판정 장');
  eq(f.why, '판정이 가리키는', '까닭');
});

/* 자기검사 — 「바뀔 때만 쓴다」 를 빼면 첫 시험이 깨져야 한다 */
const GUARD_LINE = 'if (el && el.textContent !== text) el.textContent = text;';
test('「바뀔 때만 쓴다」 를 빼면 P0 시험이 깨진다', () => {
  if (!SRC.includes(GUARD_LINE)) throw new Error(`bqEndNote 가 바뀌었어요. 이 자기검사도 같이 고쳐야 해요: ${GUARD_LINE}`);
  const { ctx, note } = load(SRC.replace(GUARD_LINE, 'if (el) el.textContent = text;'), { qa: endQa() });
  ctx.bqArmAutoEnd();
  ctx.bqArmAutoEnd();
  if (note.writes < 2) throw new Error('깨진 코드도 한 번만 썼어요 — 시험이 아무것도 안 지킨다');
});

/* ── 실행 ──────────────────────────────────────────────────────────────────── */
let failed = 0;
for (const c of cases) {
  try {
    await c.fn();
    console.log(`  ✓ ${c.name}`);
  } catch (err) {
    failed += 1;
    console.log(`  ✗ ${c.name}\n    ${String(err && err.message || err).replace(/\n/g, '\n    ')}`);
  }
}
console.log(`\n${cases.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
