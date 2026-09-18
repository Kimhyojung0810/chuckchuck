/**
 * 부스 체험(booth.html) 프론트 순수 함수 스모크.
 *
 *   node tests/js/booth.smoke.mjs
 *
 * 왜 있나 — 카메라·마이크·읽어 주기는 이 서버에 브라우저가 없어 손으로 못 눌러 본다.
 * 그래서 "브라우저에서만 틀리는 판단"(어느 담기 버튼을 보일지 · 받아쓰기가 사용자 타이핑을
 * 지우지 않는지 · 코치가 화면에 없는 말을 읽지 않는지)을 booth_logic.js 로 빼 두고 여기서 잡는다.
 * booth.js 자체는 최상위에서 버튼을 배선하므로 올리지 않는다.
 *
 * 마지막 케이스는 하네스가 진짜로 회귀를 잡는지 스스로 검사한다 (qa_live.smoke.mjs 와 같은 규율).
 * 이 파일은 pytest 가 수집하지 않는다.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const LOGIC_PATH = path.join(ROOT, 'demo/YEHS_demo/js/booth_logic.js');

/* .js 는 node 가 CommonJS 로 읽어 `export` 에서 죽는다. 브라우저용 폴더에 package.json 을 심는
   대신 소스를 data: URL 로 올린다 — 원본 파일 그대로를 시험한다 (사본이 아니다). */
async function importSource(src) {
  return import(`data:text/javascript;base64,${Buffer.from(src).toString('base64')}`);
}
const L = await importSource(readFileSync(LOGIC_PATH, 'utf8'));

const cases = [];
function test(name, fn) { cases.push({ name, fn }); }
function eq(a, b, msg = '') {
  const A = JSON.stringify(a), B = JSON.stringify(b);
  if (A !== B) throw new Error(`${msg}\n  expected ${B}\n  got      ${A}`);
}

/* ── 담기 경로 ─────────────────────────────────────────────────────────────── */
test('http 로 들어온 폰: 카메라는 기기 앱(file), 공유 없음, 카메라가 주인공', () => {
  eq(L.captureRoutes({ secure: false, hasUserMedia: true, hasDisplayMedia: false, coarse: true }),
    { camera: 'file', share: false, primary: 'camera' });
});
test('https 폰: 카메라 미리보기(live), 화면 공유는 폰에서 숨긴다', () => {
  eq(L.captureRoutes({ secure: true, hasUserMedia: true, hasDisplayMedia: true, coarse: true }),
    { camera: 'live', share: false, primary: 'camera' });
});
test('부스 노트북(127.0.0.1 크롬): 둘 다 되고 화면 공유가 주인공', () => {
  eq(L.captureRoutes({ secure: true, hasUserMedia: true, hasDisplayMedia: true, coarse: false }),
    { camera: 'live', share: true, primary: 'share' });
});
test('공유가 안 되는 데스크톱 브라우저: 카메라가 주인공', () => {
  eq(L.captureRoutes({ secure: true, hasUserMedia: true, hasDisplayMedia: false, coarse: false }).primary, 'camera');
});
test('인자를 안 주면 가장 보수적인 길(file · 공유 없음)', () => {
  eq(L.captureRoutes(), { camera: 'file', share: false, primary: 'camera' });
});

/* ── 사진 크기·이름·안내 ───────────────────────────────────────────────────── */
test('12MP 폰 사진은 긴 변 1600 으로 줄이고, 작은 그림은 키우지 않는다', () => {
  eq(Math.round(4032 * L.fitScale(4032, 3024)), 1600);
  eq(L.fitScale(800, 600), 1);
  eq(L.fitScale(0, 0), 1, '크기를 모르면 그대로');
});
test('장면 이름은 형식을 따른다 — 서버는 내용으로 판별하지만 이름도 맞춘다', () => {
  eq(L.shotFileName(0, 'image/jpeg'), '장면-1.jpg');
  eq(L.shotFileName(2, 'image/png'), '장면-3.png');
  eq(L.shotFileName(1, ''), '장면-2.png');
});
test('담은 장면 수 안내 — 0·1장은 더 담으라 하고, 상한에서는 상한을 말한다', () => {
  if (!L.shotsAdvice(0).includes('2~4장')) throw new Error(L.shotsAdvice(0));
  if (!L.shotsAdvice(1).includes('한 장 더')) throw new Error(L.shotsAdvice(1));
  if (!L.shotsAdvice(3).startsWith('3장')) throw new Error(L.shotsAdvice(3));
  if (!L.shotsAdvice(L.MAX_SHOTS).includes(`${L.MAX_SHOTS}장`)) throw new Error(L.shotsAdvice(L.MAX_SHOTS));
});
test('카메라 오류는 다음 행동이 보이는 말로 — 코드를 그대로 보여 주지 않는다', () => {
  for (const name of ['NotAllowedError', 'NotFoundError', 'NotReadableError', 'WeirdError', undefined]) {
    const t = L.cameraErrorText(name ? { name } : null);
    if (/Error/.test(t) || !/(사진을 찍어 올리|다시 누르)/.test(t)) throw new Error(`${name}: ${t}`);
  }
});

/* ── 받아쓰기 붓 ───────────────────────────────────────────────────────────── */
test('받아쓰기: 이미 쳐 놓은 글 뒤에 말이 붙고, 중간 결과는 통째로 다시 그린다', () => {
  let pen = L.newPen('  첫째로 ');
  let r = L.paintDictation(pen, '첫째로', '데이터를');
  eq(r.value, '첫째로 데이터를');
  r = L.paintDictation(r.pen, r.value, '데이터를 모았고');
  eq(r.value, '첫째로 데이터를 모았고');
});
test('받아쓰기: 말하는 도중 사용자가 친 글자는 지우지 않는다 (새 기준선)', () => {
  let r = L.paintDictation(L.newPen(''), '', '안녕');
  eq(r.value, '안녕');
  // 사용자가 입력창을 손댔다 — painted 와 다르다
  r = L.paintDictation(r.pen, '안녕하세요 (수정)', '안녕 저는');
  eq(r.value, '안녕하세요 (수정) 안녕 저는');
});
test('받아쓰기: 붓은 바꾸지 않는다 (새 붓을 돌려준다)', () => {
  const pen = L.newPen('a');
  L.paintDictation(pen, 'a', 'b');
  eq(pen, { base: 'a', painted: null });
});
test('서버 STT 결과는 기존 글 뒤에 잇고, 빈 결과는 아무것도 안 바꾼다', () => {
  eq(L.appendTranscript('앞', '뒤'), '앞 뒤');
  eq(L.appendTranscript('', ' 뒤 '), '뒤');
  eq(L.appendTranscript('앞', ''), '앞');
});
test('마이크 이름은 앱(qa_live.js MIC_STATE)과 같은 말', () => {
  const src = readFileSync(path.join(ROOT, 'demo/YEHS_demo/js/qa_live.js'), 'utf8');
  for (const label of Object.values(L.MIC_LABEL)) {
    if (!src.includes(`'${label}'`)) throw new Error(`qa_live.js 에 없는 마이크 이름: ${label}`);
  }
});

/* ── 판정 · 읽어 주기 ──────────────────────────────────────────────────────── */
test('힌트 사다리: hints[] 가 있으면 그것, 없으면 옛 hint 한 칸, 둘 다 없으면 빈 사다리', () => {
  eq(L.hintLadder({ hints: ['a', ' ', 'b'], hint: 'x' }), ['a', 'b']);
  eq(L.hintLadder({ hint: 'x' }), ['x']);
  eq(L.hintLadder({ hints: [], hint: '' }), []);
  eq(L.hintLadder(null), []);
});
test('마지막 화면: 질문마다 마지막 판정이 결과, 판정이 없으면 unknown', () => {
  const rows = L.tally([{ id: 'q1', label: 'A' }, { id: 'q2' }], { q1: { verdicts: ['wrong', 'good'] } });
  eq(rows.map((r) => [r.no, r.label, r.verdict]), [[1, 'A', 'good'], [2, '질문', 'unknown']]);
  eq(rows[0].word, L.VERDICT_WORD.good);
});
test('읽어 주기: 화면에 있는 말만 — 되묻기는 평소에, 정답 요지는 포기했을 때만', () => {
  const j = { react: '좋아요.', summary_sentence: '핵심을 짚었어요.', followup: '그럼 왜죠?', explanation: '정답은 X.' };
  eq(L.speakableJudgement(j), '좋아요. 핵심을 짚었어요. 그럼 왜죠?');
  eq(L.speakableJudgement(j, { giveUp: true }), '좋아요. 핵심을 짚었어요. 정답은 X.');
  eq(L.speakableJudgement({ coach_stage: 'explain', summary_sentence: 's' }, { answerGist: '요지' }), 's 요지');
  eq(L.speakableJudgement({ react: 42, followup: '   ' }), '', '문자열이 아니거나 빈 것은 읽지 않는다');
  eq(L.speakableJudgement(null), '');
});

/* ── 통화 모드 ─────────────────────────────────────────────────────────────── */
test('상대 기분은 chatter.css 가 아는 이름만 — 묻는 중 curious, 잘 답하면 happy, 어긋나면 grumpy', () => {
  eq(L.partnerMood('asking'), 'curious');
  eq(L.partnerMood('listening'), 'neutral');
  eq(L.partnerMood('judged', 'good'), 'happy');
  eq(L.partnerMood('judged', 'wrong'), 'grumpy');
  eq(L.partnerMood('judged', 'partial'), 'curious');
  const css = readFileSync(path.join(ROOT, 'demo/YEHS_demo/css/chatter.css'), 'utf8');
  for (const m of ['curious', 'happy', 'grumpy']) if (!css.includes(`data-mood="${m}"`)) throw new Error(`chatter.css 에 없는 기분: ${m}`);
});
test('침묵 판정: 말한 게 있고 2.5초 조용하면 끝, 아무 말 없으면 영원히 끝이 아니다', () => {
  eq(L.speechSettled({ lastChangeAt: 1000, now: 3600, text: '답' }), true);
  eq(L.speechSettled({ lastChangeAt: 1000, now: 3000, text: '답' }), false);
  eq(L.speechSettled({ lastChangeAt: 1000, now: 99999, text: '  ' }), false);
  eq(L.speechSettled({ lastChangeAt: NaN, now: 5000, text: '답' }), false);
});
test('카운트다운 문구는 고칠 길을 말한다', () => {
  if (!L.countdownText(2.2).startsWith('3초')) throw new Error(L.countdownText(2.2));
  if (!L.countdownText(3).includes('고치려면')) throw new Error(L.countdownText(3));
  eq(L.countdownText(0), '보내는 중이에요.');
});
test('판정 말풍선: 반응+요약 → 빠진 것 → 되묻기(평소) 또는 정답 요지(포기)', () => {
  const j = { verdict: 'partial', react: '음,', summary_sentence: '반은 맞아요.', missing_points: ['근거', ''], followup: '그럼요?', explanation: '정답 X' };
  eq(L.judgementBubbles(j).map((b) => b.kind), ['verdict', 'missing', 'followup']);
  eq(L.judgementBubbles(j)[0], { kind: 'verdict', verdict: 'partial', text: '음, 반은 맞아요.' });
  eq(L.judgementBubbles(j)[1].items, ['근거']);
  eq(L.judgementBubbles(j, { giveUp: true }).map((b) => b.kind), ['verdict', 'missing', 'explain']);
  eq(L.judgementBubbles({ verdict: 'good', react: '좋아요' }).length, 1);
  eq(L.judgementBubbles(null), []);
});

/* ── 하네스가 진짜로 회귀를 잡는지 ─────────────────────────────────────────── */
/* 고치기 전 붓(기준선을 한 번만 잡던 것)으로 같은 시험을 돌려서 반드시 깨지는지 본다.
   안 깨지면 위의 「사용자가 친 글자」 시험은 아무것도 지키고 있지 않은 것이다. */
const GUARD_LINE = "if (pen.painted !== null && current !== pen.painted) base = (current || '').trim();";
test('고치기 전 붓으로 돌리면 「사용자가 친 글자」 시험이 깨진다', async () => {
  const src = readFileSync(LOGIC_PATH, 'utf8');
  if (!src.includes(GUARD_LINE)) throw new Error(`paintDictation 이 바뀌었어요. 이 자기검사도 같이 고쳐야 해요: ${GUARD_LINE}`);
  const broken = src.replace(GUARD_LINE, '');
  const B = await importSource(broken);
  let r = B.paintDictation(B.newPen(''), '', '안녕');
  r = B.paintDictation(r.pen, '안녕하세요 (수정)', '안녕 저는');
  if (r.value === '안녕하세요 (수정) 안녕 저는') throw new Error('깨진 붓이 통과했어요 — 시험이 아무것도 안 지킨다');
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
