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

/* 오버레이 상태(booth_overlay_state.js)는 booth_logic 을 './booth_logic.js?v=…' 로 import 한다.
   data: URL 에서는 상대 경로가 안 풀리므로 그 한 줄만 booth_logic 의 data: URL 로 바꿔 올린다 (나머지는 원본 그대로) */
const OVERLAY_PATH = path.join(ROOT, 'demo/YEHS_demo/js/booth_overlay_state.js');
const LOGIC_URL = `data:text/javascript;base64,${Buffer.from(readFileSync(LOGIC_PATH, 'utf8')).toString('base64')}`;
const overlaySrc = readFileSync(OVERLAY_PATH, 'utf8');
if (!/from '\.\/booth_logic\.js(\?v=[^']*)?'/.test(overlaySrc)) throw new Error('booth_overlay_state.js 의 booth_logic import 가 바뀌었어요 — 스모크의 치환도 같이 고쳐요');
const O = await importSource(overlaySrc.replace(/from '\.\/booth_logic\.js(\?v=[^']*)?'/, `from '${LOGIC_URL}'`));

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
/* 토스 오류 문구 시스템 — 무슨 일 · 왜 · 이제 뭘. 가지마다 원인 한 마디와 다음 행동 한 마디가 있어야 한다 */
const CAMERA_ERRORS = ['NotAllowedError', 'SecurityError', 'NotFoundError', 'OverconstrainedError', 'NotReadableError', 'AbortError', 'WeirdError', undefined];
function threeParts(t, label) {
  const sentences = t.split(/(?<=요\.)\s*/).filter(Boolean);
  if (sentences.length < 2 || !sentences.every((x) => /요\.$/.test(x))) throw new Error(`${label}: 해요체 문장으로 끝나야 해요 — ${t}`);
  if (!/(권한|다른 앱|찾을 수|지원)/.test(t)) throw new Error(`${label}: 원인(왜)이 없어요 — ${t}`);
  if (!/(올리면|누르면|눌러요)/.test(t)) throw new Error(`${label}: 다음 행동(이제 뭘)이 없어요 — ${t}`);
  if (/(주세요|세요\.)/.test(t)) throw new Error(`${label}: 과한 경어 — ${t}`);
}
test('카메라 오류 문구는 가지마다 무슨 일·왜·이제 뭘 세 가지를 다 말한다', () => {
  for (const name of CAMERA_ERRORS) threeParts(L.cameraErrorText(name ? { name } : null), `담기 ${name}`);
});
test('통화 중 내 모습 오류는 「카메라 켜기」로 가는 길과 목소리로 이어지는 통화를 말한다', () => {
  for (const name of CAMERA_ERRORS) {
    const t = L.selfViewErrorText(name ? { name } : null);
    if (!/「카메라 켜기」를 (한 번 더 )?눌러요/.test(t) || !t.includes('목소리로 통화해요') || /Error|주세요/.test(t)) throw new Error(`${name}: ${t}`);
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
test('마지막 화면(옛 기록 모양): 마지막 판정이 good 이면 닫힌 것, 판정이 없으면 「안 물었어요」 (H-13)', () => {
  const rows = L.tally([{ id: 'q1', label: 'A' }, { id: 'q2' }], { q1: { verdicts: ['wrong', 'good'] } });
  eq(rows.map((r) => [r.no, r.label, r.verdict]), [[1, 'A', 'good'], [2, '질문', 'unasked']]);
  eq(rows[0].word, L.VERDICT_WORD.good);
  eq(rows[1].word, '안 물었어요', '「아직 모르겠어요」 가 아니다 — 사용자는 모른다고 한 적이 없다');
});
test('마지막 화면: 띄웠는데 답이 없으면 「답하기 전에 마쳤어요」, 코칭·해설·힌트 셋째 칸 뒤에 닫히면 「도움 받아 답했어요」 (H-12)', () => {
  const qs = ['a', 'b', 'c', 'd', 'e', 'f', 'g'].map((id) => ({ id, label: id }));
  const rows = L.tally(qs, {
    a: { asked: true, verdicts: [] },
    b: { verdicts: ['good'], closed: true, closeReason: 'good' },
    c: { verdicts: ['unknown', 'good'], closed: true, closeReason: 'good', coached: true },
    d: { verdicts: ['partial', 'partial', 'partial'], closed: true, closeReason: 'rounds' },
    e: { verdicts: ['good'], closed: true, closeReason: 'good', hintLevel: 3 },
    f: { verdicts: ['unknown', 'unknown', 'unknown'], closed: false, explained: true },
    g: { verdicts: ['partial'], closed: false },
  });
  eq(rows.map((r) => r.word), ['답하기 전에 마쳤어요', '잘 답했어요', '도움 받아 답했어요', '요지는 통과했어요', '도움 받아 답했어요', '답을 같이 풀었어요', '반쯤 왔어요']);
  eq(rows.map((r) => r.verdict), ['unasked', 'good', 'partial', 'partial', 'partial', 'unknown', 'partial'], '판정 색은 네 가지 + 회색만');
  eq(L.tally([{ id: 'x' }], { x: { verdicts: ['partial'], closed: true, closeReason: 'guard' } })[0].word, '자료와 다시 맞춰 봐요');
});
test('읽어 주기: 화면에 있는 말만 — 총평은 닫혔을 때만, 되묻기는 안 닫혔을 때, 해설은 해설 단계에서', () => {
  const j = { react: '좋아요.', summary_sentence: '핵심을 짚었어요.', followup: '그럼 왜죠?', explanation: '정답은 X.' };
  eq(L.speakableJudgement({ ...j, verdict: 'partial', mastered: false }), '좋아요. 그럼 왜죠?', '안 닫힌 판정에 총평(모범답)을 읽지 않는다 (H-11)');
  eq(L.speakableJudgement({ ...j, verdict: 'good', mastered: true, close_reason: 'good' }), '좋아요. 핵심을 짚었어요.', '닫혔으면 되묻지 않는다 (H-12)');
  eq(L.speakableJudgement({ ...j, verdict: 'unknown', coach_stage: 'explain' }), '좋아요. 핵심을 짚었어요. 정답은 X.');
  eq(L.speakableJudgement({ coach_stage: 'explain', summary_sentence: 's' }, { answerGist: '요지' }), 's 요지', '해설이 비면 골자로');
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
  if (L.countdownText(3) !== '3초 뒤에 보낼게요. 고치려면 자막을 눌러요.') throw new Error(L.countdownText(3));
  eq(L.countdownText(0), '보내는 중이에요.');
});
test('판정 말풍선: 반응 → 빠진 것 → 되묻기. 안 닫힌 판정에는 총평을 안 붙인다 (H-11)', () => {
  const j = { verdict: 'partial', react: '음,', summary_sentence: '반은 맞아요.', missing_points: ['근거', ''], followup: '그럼요?', explanation: '정답 X' };
  eq(L.judgementBubbles(j).map((b) => b.kind), ['verdict', 'missing', 'followup']);
  eq(L.judgementBubbles(j)[0], { kind: 'verdict', verdict: 'partial', text: '음,' });
  eq(L.judgementBubbles(j)[1].items, ['근거']);
  eq(L.judgementBubbles(j, { giveUp: true }).map((b) => b.kind), ['verdict', 'missing', 'explain'], '옛 브리지(단계 없는 포기)는 해설이 있을 때만 해설');
  eq(L.judgementBubbles({ verdict: 'good', react: '좋아요' }).length, 1);
  eq(L.judgementBubbles(null), []);
});
test('판정 한 풍선(9/23): 조각을 잃지 않고 하나로 — pill 낱말·빠진 것·되묻기가 들어간다', () => {
  const j = { verdict: 'partial', react: '음,', summary_sentence: '반은 맞아요.', missing_points: ['근거'], followup: '그럼요?', explanation: '정답 X' };
  eq(L.judgementBubble(j), { verdict: 'partial', word: '반쯤 왔어요', text: '음,', missing: ['근거'], missingHead: '빠진 것', tail: { kind: 'followup', text: '그럼요?', choices: [] }, closed: false, stage: '' });
  eq(L.judgementBubble(j, { giveUp: true }).tail, { kind: 'explain', text: '정답 X', choices: [] });
  eq(L.judgementBubble({ verdict: 'good', react: '좋아요', mastered: true, close_reason: 'good' }),
    { verdict: 'good', word: '잘 답했어요', text: '좋아요', missing: [], missingHead: '다시 볼 것', tail: null, closed: true, stage: '' });
  eq(L.judgementBubble(null), null);
});
/* ── 09-30 held-out 부스 감사 H-10~H-14 ─────────────────────────────────── */
const GIST = '현재 프로토타입/MVP를 보유 중이며, 발표자료에 명시된 대로 PoC 단계에서 아이디어 및 개념 검증을 진행…';
test('H-10 「모르겠어요」 첫 번째(narrow): 되물음 + 보기 칩, 골자는 안 보인다, 답칸은 열린다', () => {
  const j = { verdict: 'unknown', score: 0, coach_stage: 'narrow', react: '같이 볼게요.', summary_sentence: '단계 — 막힌 지점을 같이 짚었어요.',
    followup: "'PoC' 쪽인가요, 'MVP' 쪽인가요?", choices: ['PoC', ' MVP ', ''], mastered: false };
  const b = L.judgementBubble(j, { giveUp: true, answerGist: GIST });
  eq(b.tail, { kind: 'followup', text: "'PoC' 쪽인가요, 'MVP' 쪽인가요?", choices: ['PoC', 'MVP'] });
  eq(b.closed, false, '다시 답할 수 있다');
  eq([b.verdict, b.word], ['unknown', L.COACH_WORD.narrow], '판정이 아니라 코치가 하는 일');
  eq(JSON.stringify(b).includes('프로토타입/MVP를 보유'), false, '골자(모범답)를 흘리지 않는다');
  eq(b.text, '같이 볼게요.', '코칭 단계에는 총평을 안 붙인다');
});
test('H-10 scaffold 는 빈칸 되물음, explain 은 해설 — 해설이 비었을 때만 골자, 잘린 골자는 문장 끝에서', () => {
  const sc = L.judgementBubble({ coach_stage: 'scaffold', react: 'r', followup: '빈칸: 개념 ___ 을 해요.' }, { giveUp: true, answerGist: GIST });
  eq(sc.tail.kind, 'followup');
  const ex = L.judgementBubble({ coach_stage: 'explain', react: 'r', explanation: '' }, { giveUp: true, answerGist: '첫 문장이에요. 둘째 문장은 여기서 끊…' });
  eq(ex.tail, { kind: 'explain', text: '첫 문장이에요.', choices: [] });
  eq(L.judgementBubble({ coach_stage: 'explain', explanation: '' }, { giveUp: true, answerGist: '함정의 사실 줄이에요.', trap: true }).tail, null, '함정의 골자는 바로잡은 사실 그 자체라 대신 쓰지 않는다');
});
test('문장 한가운데서 끊긴 글은 마지막 온전한 문장까지 — 안 잘린 글·온전한 문장이 없는 글은 그대로', () => {
  eq(L.wholeSentences('A 해요. B 를 진행…'), 'A 해요.');
  eq(L.wholeSentences('수치는 3.5%예요. 그리고 계속…'), '수치는 3.5%예요.', '소수점은 문장 끝이 아니다');
  eq(L.wholeSentences('«인용이에요.» 다음…'), '«인용이에요.»');
  eq(L.wholeSentences('끝까지 다 온 글이에요.'), '끝까지 다 온 글이에요.');
  eq(L.wholeSentences('한 문장도 안 끝난 채 잘린…'), '한 문장도 안 끝난 채 잘린…');
  eq(L.wholeSentences(null), '');
});
test('H-11 오답·절반 풍선에 총평(모범답)이 없다 — 닫힌 good 에만', () => {
  const summary = 'B2C/B2B 병행 시 가격 정책은 두 가지 과금 구조로 설계되어야 해요.';
  const wrong = L.judgementBubble({ verdict: 'wrong', score: 0, react: '질문과 다른 이야기예요.', summary_sentence: summary, followup: 'f', mastered: false });
  eq(wrong.text.includes(summary), false);
  const good = L.judgementBubble({ verdict: 'good', score: 85, react: '좋아요.', summary_sentence: summary, mastered: true, close_reason: 'good' });
  eq(good.text.includes(summary), true);
});
test('70~79 통과(passed)인데 안 닫힌 판정은 「반쯤 왔어요」 가 아니라 「요지는 맞아요」 — 되묻기는 이어 간다 (앱 칩과 같다)', () => {
  const b = L.judgementBubble({ verdict: 'partial', score: 75, passed: true, mastered: false, react: 'r', followup: '한 가지만 더요?' });
  eq([b.word, b.verdict, b.tail.kind], [L.PASSED_WORD, 'good', 'followup']);
  eq(L.judgementBubble({ verdict: 'partial', score: 65, passed: false, mastered: false, react: 'r' }).word, L.VERDICT_WORD.partial);
});
test('H-11 가드 사유 표기는 「빠진 것」 이 아니다', () => {
  eq(L.cleanMissing(['질문이 묻는 것: B2C/B2B 병행', '자료 4장과 어긋난 곳: 맞다·아니다 쪽', '개인 사용자 구독형', ' ', 3]), ['개인 사용자 구독형']);
});
test('H-12 서버가 닫았으면(mastered) 되묻지 않는다 — followup 이 와도, 3라운드 출구는 pill 이 그렇다고 말한다', () => {
  const j = { verdict: 'partial', score: 75, mastered: true, close_reason: 'rounds', react: '요지는 맞아요.', summary_sentence: '총평.', followup: '한 가지만 더 짚어 주세요.', missing_points: [] };
  const b = L.judgementBubble(j);
  eq([b.closed, b.tail, b.word, b.verdict], [true, null, L.CLOSE_WORD.rounds, 'partial']);
  eq(L.judgementClosed({ verdict: 'good' }), true, '옛 브리지(mastered 없음)는 good 만 닫는다 (B-10)');
  eq(L.judgementClosed({ verdict: 'partial', score: 75 }), false);
  eq(L.judgementClosed({ verdict: 'unknown', coach_stage: 'narrow', mastered: true }), false, '코칭 응답은 닫지 않는다');
});
test('H-14 판정에 보내는 힌트는 연 칸만 — 판정이 준 사다리는 사다리에만 (+ 코칭 되물음)', () => {
  eq(L.hintsForJudge(['h1'], { verdict: 'partial', hints: ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'] }), ['h1']);
  eq(L.hintsForJudge([], { coach_stage: 'narrow', followup: "'가' 쪽인가요, '나' 쪽인가요?" }), ["되물음: '가' 쪽인가요, '나' 쪽인가요?"]);
  eq(L.hintsForJudge(['h1', ' '], { coach_stage: 'explain', followup: 'x' }), ['h1'], '해설 단계는 되물음이 아니다');
  eq(L.mergeLadder(['a', 'b', 'c'], ['A', 'B', 'C', 'D']), ['A', 'B', 'C', 'D'], '긴 사다리로 갈아탄다');
  eq(L.mergeLadder(['a', 'b', 'c', 'd'], ['A', 'B']), ['a', 'b', 'c', 'd'], '짧아지면 안 버린다 (분모가 안 준다)');
  eq(L.mergeLadder(['a', 'b'], ['A', 'B']), ['A', 'B'], '같은 길이는 갈아탄다 (넷째 칸이 바뀐다)');
  eq(L.mergeLadder(['a'], undefined), ['a']);
});
test('B-10·M-08 판정에는 이 질문의 대화만, 채점된 답만 — 포기·되물음 턴은 라운드를 태우지 않는다', () => {
  const hist = [{ question_id: 'q1', 답변: '끝난 답' }, { question_id: 'q2', 답변: '지금 답' }];
  eq(L.questionHistory(hist, 'q2').map((t) => t.답변), ['지금 답']);
  eq(L.scoredAnswers([{ answer: '첫 답' }, { answer: '', giveUp: true }, { answer: '무슨 뜻이에요?', clarify: true }, { answer: ' 둘째 답 ' }]), ['첫 답', '둘째 답']);
});
test('L-01 「모르겠어요」 버튼·말풍선 — 서버 사다리를 따라 이름이 바뀌고, 자리표시자는 안 보인다', () => {
  eq([0, 1, 2, 5].map(L.giveupLabel), ['모르겠어요', '그래도 모르겠어요 · 빈칸으로', '그래도 모르겠어요 · 답 보기', '그래도 모르겠어요 · 답 보기']);
  eq(L.giveupSaid(''), '모르겠어요');
  eq(L.giveupSaid(' 음 PoC 는 지났는데 '), '음 PoC 는 지났는데');
});
test('폴백 표시: 사람이 할 일이 있는 것만 화면에 — 서버 질문을 못 찾은 것은 개발 로그로만', () => {
  const j = { degraded: ['question_unverified', 'slide_doc_missing'], degraded_notes: ['서버 질문 못 찾음', '자료 본문을 찾지 못해 자료와 대조하지 않고 진행했어요.'], grounded_on_deck: false, grounded_on_server: false };
  eq(L.degradedLines(j), ['자료 본문을 찾지 못해 자료와 대조하지 않고 진행했어요.']);
  eq(L.devOnlyDegraded(j), ['question_unverified']);
  eq(L.degradedLines({ degraded: [], degraded_notes: [], grounded_on_deck: false }), ['자료 본문 없이 판정했어요.']);
  eq(L.degradedLines({ degraded: ['papers_timeout'], degraded_notes: ['문헌 검색이 늦어져 자료가 인용한 문헌만으로 질문을 만들었어요.'] }).length, 1);
  eq(L.devOnlyDegraded({ grounded_on_server: false }), ['grounded_on_server=false']);
  eq([L.degradedLines(null), L.degradedLines({ grounded_on_deck: true })], [[], []]);
});
test('함정 질문의 이유 줄은 함정임을 알리지 않는다 — 장만 가리키는 중립 문장 (B-01·H-07)', () => {
  const trapWhy = '「단백질 먼저」에 대해 질문이 말한 내용이 자료와 같은지 먼저 따져 보는 연습이에요.';
  const w = L.questionWhy({ trap: true, why: trapWhy, slide_nos: [6, 6, 2] });
  eq(w, '자료 6·2장을 근거로 설명할 수 있는지 보려고 물어요.');
  eq(/따져|함정|같은지/.test(w), false);
  eq(L.questionWhy({ trap: true, why: trapWhy }), '자료를 근거로 설명할 수 있는지 보려고 물어요.');
  eq(L.questionWhy({ why: ' 보통 이유예요. ' }), '보통 이유예요.');
  eq(L.questionWhy(null), '');
});
test('요청 제한·AI 지연 안내는 남은 초를 센다 (H-15)', () => {
  eq(L.retryWaitText(4.2), '요청이 몰려서 잠깐 기다렸다 다시 보낼게요 · 5초');
  eq(L.retryWaitText(0), '다시 보내는 중이에요.');
  eq(L.retryWaitText(3, 'upstream'), 'AI 서버가 늦어서 3초 뒤에 한 번 더 보낼게요.');
});

/* ── 발표 모드 — 실시간 말하기 피드백 ─────────────────────────────────────── */
/** 계기에 관찰을 순서대로 넣고 나온 지적 목록을 돌려준다 */
function run(obs) {
  let m = L.createDelivery(); const tells = [];
  for (const o of obs) { const r = L.deliveryObserve(m, o); m = r.meter; if (r.tell) tells.push({ at: o.now, kind: r.tell.kind }); }
  return { m, tells };
}
const 가 = (n) => '가'.repeat(n);
test('간투어 3번이면 지적하고, 쿨다운 안에는 다시 안 한다', () => {
  const { tells } = run([{ text: '', now: 0 }, { text: '어 음 저희 서비스는 그 이제', now: 1000 }, { text: '어 음 저희 서비스는 그 이제 어 음', now: 2000 }]);
  eq(tells, [{ at: 1000, kind: 'filler' }]);
});
test('빠름: 15초 창에서 분당 402자 넘게 말하면 fast — 앱의 cpmJudge 와 같은 배수', () => {
  // 0.5초마다 5자 = 600자/분
  const obs = []; for (let i = 0; i <= 20; i++) obs.push({ text: 가(5 * i), now: i * 500 });
  const { tells } = run(obs);
  eq(tells.map((t) => t.kind), ['fast']);
  if (tells[0].at < 6000) throw new Error('6초는 들어야 잰다: ' + tells[0].at);
});
test('느림: 분당 120자면 slow. 재료가 모자라면(25자 미만) 말하지 않는다', () => {
  const obs = []; for (let i = 0; i <= 40; i++) obs.push({ text: 가(i), now: i * 500 });
  const { tells } = run(obs);
  eq(tells.map((t) => t.kind), ['slow']);
  eq(run(obs.slice(0, 10)).tells, []);
});
test('같은 낱말 4번이면 repeat (간투어는 빼고), 더듬기 2번도 repeat', () => {
  eq(run([{ text: '', now: 0 }, { text: '그래서 저희는 그래서 이것을 그래서 만들고 그래서 팝니다', now: 1000 }]).tells.map((t) => t.kind), ['repeat']);
  eq(run([{ text: '', now: 0 }, { text: '지도 지도력은 리더십 리더십의 핵심', now: 1000 }]).tells.map((t) => t.kind), ['repeat']);
  eq(run([{ text: '', now: 0 }, { text: '음 음 저희 그 그 서비스', now: 1000 }]).tells.map((t) => t.kind), ['filler']);
});
test('멈춤: 말하다가 5초 조용하면 pause, 처음부터 아무 말 없으면 아니다', () => {
  const t = '저희 서비스를 소개할게요';
  eq(run([{ text: '', now: 0 }, { text: t, now: 1000 }, { text: t, now: 3000 }, { text: t, now: 6500 }]).tells.map((x) => x.kind), ['pause']);
  eq(run([{ text: '', now: 0 }, { text: '', now: 3000 }, { text: '', now: 7000 }]).tells, []);
});
test('산만한 움직임: 5초 동안 프레임 차이 평균이 기준 넘게 이어지면 fidget', () => {
  const obs = []; for (let i = 0; i <= 24; i++) obs.push({ text: '', now: i * 250, motion: 30 });
  eq(run(obs).tells.map((t) => t.kind), ['fidget']);
  const calm = []; for (let i = 0; i <= 24; i++) calm.push({ text: '', now: i * 250, motion: 3 });
  eq(run(calm).tells, []);
});
test('작은 목소리: 글자는 느는데 음량이 낮으면 quiet. 안 말하는 동안의 낮은 음량은 아니다', () => {
  const obs = []; for (let i = 0; i <= 28; i++) obs.push({ text: 가(i), now: i * 250, level: 0.005 });
  eq(run(obs).tells.map((t) => t.kind), ['quiet']);
  const silent = []; for (let i = 0; i <= 28; i++) silent.push({ text: '', now: i * 250, level: 0.005 });
  eq(run(silent).tells, []);
});
test('안정: 권장 속도로 60초 이어 말하면 칭찬 한 번, 그 다음은 60초 뒤', () => {
  // 0.5초에 2.7자 = 324자/분
  const obs = []; for (let i = 0; i <= 260; i++) obs.push({ text: 가(Math.round(2.7 * i)), now: i * 500 });
  const { tells, m } = run(obs);
  eq(tells.map((t) => t.kind), ['steady', 'steady']);
  eq(L.deliverySummary(m), '');
});
test('멈춤이 낀 구간을 「느려요」로 잘못 잡지 않는다 — 말한 시간은 글자가 는 시점끼리만 센다', () => {
  // 5초 말함(30자) → 6초 침묵(센서 관찰만 0.25초마다) → 7초 말함(42자, 분당 360자) → 6초 침묵
  const obs = [];
  for (let i = 0; i <= 10; i++) obs.push({ text: 가(3 * i), now: i * 500 });
  for (let t = 5250; t <= 11000; t += 250) obs.push({ text: 가(30), now: t });
  for (let k = 1; k <= 14; k++) obs.push({ text: 가(30 + 3 * k), now: 11000 + k * 500 });
  for (let t = 18250; t <= 24000; t += 250) obs.push({ text: 가(72), now: t });
  eq(run(obs).tells.map((t) => t.kind), ['pause']);
});
test('장면을 넘긴 직후 8초는 멈춤을 지적하지 않는다', () => {
  const t = '저희 서비스를 소개할게요';
  const base = [{ text: '', now: 0, slide: 0 }, { text: t, now: 1000, slide: 0 }];
  const quiet = (slide) => { const o = []; for (let x = 2000; x <= 9500; x += 500) o.push({ text: t, now: x, slide }); return o; };
  eq(run([...base, ...quiet(1)]).tells, []);                    // 2초에 장면을 넘김 → 10초까지 유예
  eq(run([...base, ...quiet(0)]).tells.map((x) => x.kind), ['pause']);
});
test('칭찬은 시작 60초 전엔 없다', () => {
  const obs = []; for (let i = 0; i <= 60; i++) obs.push({ text: 가(Math.round(2.7 * i)), now: i * 500 });   // 30초
  eq(run(obs).tells, []);
});
test('마친 화면 한 줄: 지적한 것만 세고 칭찬은 안 센다', () => {
  const m = { counts: { fast: 2, filler: 1, steady: 3 } };
  eq(L.deliverySummary(m), '발표 중 알려 준 것 · 빠름 2 · 간투어 1');
  eq(L.deliverySummary(L.createDelivery()), '');
});
test('발표 중 말로 조작: 「질문 받을게요」「다음 장면」— 앞은 남긴다', () => {
  eq(L.presentCommand('이상입니다 질문 받을게요'), { cmd: 'ask', rest: '이상입니다' });
  eq(L.presentCommand('다음 장면으로'), { cmd: 'next', rest: '' });
  eq(L.presentCommand('이전 슬라이드'), { cmd: 'prev', rest: '' });
  eq(L.presentCommand('이 질문 받기가 핵심이고'), null);
});
/* ── 계기와 기준 맞추기 (운영자용) ───────────────────────────────────────── */
test('기준 맞추기: 바닥값의 3배·4배로 문턱을 잡되 바닥 밑으로는 안 내려간다', () => {
  const c = L.calibrateDelivery(L.DELIVERY, { motionFloor: 6.2, levelFloor: 0.01 });
  eq([c.fidgetMotion, c.quietLevel], [19, 0.04]);
  eq(c.pauseMs, L.DELIVERY.pauseMs, '나머지 값은 그대로 가져온다');
  const quiet = L.calibrateDelivery(L.DELIVERY, { motionFloor: 0.2, levelFloor: 0.0001 });
  eq([quiet.fidgetMotion, quiet.quietLevel], [8, 0.006], '조용한 방에서도 문턱이 0 이 되지 않는다');
  eq(L.calibrateDelivery(L.DELIVERY, {}).fidgetMotion, L.DELIVERY.fidgetMotion, '안 잰 항목은 안 바꾼다');
});
test('계기 한 줄: 지금 값 / 지금 기준, 못 잰 것은 —', () => {
  let m = L.createDelivery();
  for (let i = 0; i <= 40; i++) m = L.deliveryObserve(m, { text: '가'.repeat(3 * i), now: i * 500, motion: 4 }).meter;
  const t = L.meterText(m, L.DELIVERY);
  if (!t.startsWith('움직임 4.0 / 기준 12 ')) throw new Error(t);
  if (!t.includes('음량 — / 기준')) throw new Error('마이크를 못 열었으면 — 라야 해요: ' + t);
  if (!/빠르기 3\d\d자\/분/.test(t)) throw new Error(t);
  eq(L.meterText(L.createDelivery(), L.DELIVERY), '움직임 — / 기준 12 · 음량 — / 기준 0.015');
});
test('계기: 지적한 것은 개수로 붙고, 창 안의 빠르기는 speakingRateOf 가 준다', () => {
  const m = { events: [{ t: 0, len: 0, chars: 0 }], counts: { filler: 2 } };
  if (!L.meterText(m, L.DELIVERY).endsWith('간투어 2')) throw new Error(L.meterText(m, L.DELIVERY));
  eq(L.speakingRateOf(L.createDelivery(), 0, L.DELIVERY), null, '재료가 모자라면 null');
});

test('자막 꼬리 · 시계', () => {
  eq(L.captionTail('가나다', 90), '가나다');
  eq(L.captionTail('a'.repeat(100), 90).length, 91);
  eq(L.clockText(65000), '01:05'); eq(L.clockText(-5), '00:00');
});

/* ── 말로 조작하기 ─────────────────────────────────────────────────────────── */
test('문장 끝의 「다음 질문」: 앞부분은 답으로 남기고 next', () => {
  eq(L.voiceCommand('빠른 수익화 때문이에요 다음 질문'), { cmd: 'next', rest: '빠른 수익화 때문이에요' });
  eq(L.voiceCommand('다음 질문으로.'), { cmd: 'next', rest: '' });
  eq(L.voiceCommand('넘어가 주세요'), { cmd: 'next', rest: '' });
});
test('「모르겠어요」는 짧을 때만 포기 — 답 문장 안의 모르겠어요는 그대로 답이다', () => {
  eq(L.voiceCommand('잘 모르겠어요'), { cmd: 'giveup', rest: '' });
  eq(L.voiceCommand('저도 잘 모르겠어요'), { cmd: 'giveup', rest: '저도' });
  eq(L.voiceCommand('정확한 수치까지는 제가 잘 모르겠어요'), null);
});
test('힌트 · 다시 답하기 · 답하기', () => {
  eq(L.voiceCommand('힌트 주세요').cmd, 'hint');
  eq(L.voiceCommand('힌트').cmd, 'hint');
  eq(L.voiceCommand('다시 답할게요').cmd, 'again');
  eq(L.voiceCommand('핵심은 기관 고객의 안정적 수요예요 이상입니다'), { cmd: 'answer', rest: '핵심은 기관 고객의 안정적 수요예요' });
});
test('지금 눌릴 수 없는 버튼은 말로도 안 눌린다 · 단어 일부는 명령이 아니다', () => {
  eq(L.voiceCommand('다음 질문', { next: false }), null);
  eq(L.voiceCommand('그 다음 질문이 뭔지 힌트요', { next: false }).cmd, 'hint');
  eq(L.voiceCommand('그다음 질문'), null, '붙어 있으면 단어의 일부');
  eq(L.voiceCommand(''), null);
  eq(L.voiceCommand('   '), null);
});

/* ── 오버레이 상태 (캠 트랙 P0-3) ─────────────────────────────────────────── */
/** renderOverlay 가 쓰는 칸만 흉내 낸 가짜 요소 */
function fakeEls() {
  const mk = (extra = {}) => ({ dataset: {}, hidden: false, textContent: '', ...extra });
  return { call: mk(), seat: mk(), status: mk(), clock: mk(), qaCount: mk({ hidden: true }), autotalk: mk({ hidden: true }), caption: mk() };
}
test('오버레이 첫 상태는 booth.html 기본값(발표 · 자료 메인 · present)과 같다', () => {
  const s = O.createOverlayState();
  eq([s.mode, s.main, s.phase, s.question, s.speaker, s.mood, s.caption, s.verdict, s.handRaised],
    ['present', 'slides', 'present', null, 'solar', 'neutral', '', '', false]);
});
test('전이 함수는 받은 상태를 고치지 않고 새 객체를 돌려준다', () => {
  const s = Object.freeze(O.createOverlayState());
  const steps = [O.enterQa(s), O.enterPresent(s), O.setMainOf(s, 'self'), O.setPhaseOf(s, 'asking'),
    O.askQuestion(s, { text: '왜요?', tag: '근거', scene: 1 }), O.setCaption(s, '안녕')];
  for (const n of steps) if (n === s) throw new Error('같은 객체를 돌려줬어요');
  eq(s.mode, 'present'); eq(s.main, 'slides'); eq(s.caption, '');
});
test('발표 → Q&A: 내 모습이 메인, 시계는 숨고 질문 번호·자동 대화가 뜬다', () => {
  const el = fakeEls();
  const a = O.createOverlayState();
  O.renderOverlay(a, el);
  eq([el.call.dataset.mode, el.clock.hidden, el.qaCount.hidden, el.autotalk.hidden], ['present', false, true, true]);
  const b = O.enterQa(a);
  O.renderOverlay(b, el, a);
  eq([el.call.dataset.mode, el.call.dataset.main, el.clock.hidden, el.qaCount.hidden, el.autotalk.hidden], ['qa', 'self', true, false, false]);
});
test('발표 → Q&A: 발표 자막을 비우고 자막 칸도 빈 글자로 다시 쓴다', () => {
  const el = fakeEls();
  const a = O.setCaption(O.createOverlayState(), '사내교육으로 넓힐 계획이에요');
  O.renderOverlay(a, el);
  eq(el.caption.textContent, '사내교육으로 넓힐 계획이에요');
  const b = O.enterQa(a);
  eq(b.caption, '');
  O.renderOverlay(b, el, a);
  eq(el.caption.textContent, '');
});
test('Q&A → 다시 발표: 자료가 메인이고 질문·판정·자막을 비운다', () => {
  let s = O.askQuestion(O.setPhaseOf(O.enterQa(O.createOverlayState()), 'judged', 'good'), { text: 'Q', tag: 't', scene: 2 });
  s = O.setCaption(s, '남은 자막');
  const p = O.enterPresent(s);
  eq([p.mode, p.main, p.question, p.verdict, p.caption], ['present', 'slides', null, '', '']);
});
test('단계 → 삐약이 기분은 booth_logic.partnerMood 규칙을 그대로 따른다', () => {
  for (const [phase, v] of [['asking', ''], ['hint', ''], ['listening', ''], ['judging', ''], ['judged', 'good'], ['judged', 'wrong'], ['judged', 'partial'], ['present', '']]) {
    const s = O.setPhaseOf(O.createOverlayState(), phase, v);
    eq(s.mood, L.partnerMood(phase, v), `${phase}/${v}`);
    eq([s.phase, s.verdict], [phase, v]);
  }
});
test('단계를 그리면 data-phase·표정·이름표 한 줄이 같이 바뀐다 (판정 뒤에는 이름표를 비운다)', () => {
  const el = fakeEls();
  let s = O.setPhaseOf(O.createOverlayState(), 'judging');
  O.renderOverlay(s, el);
  eq([el.call.dataset.phase, el.seat.dataset.mood, el.status.textContent], ['judging', 'neutral', '생각하는 중']);
  s = O.setPhaseOf(s, 'judged', 'good');
  O.renderOverlay(s, el);
  eq([el.call.dataset.phase, el.seat.dataset.mood, el.status.textContent], ['judged', 'happy', '']);
});
test('메인 바꾸기: slides ↔ self 만 받고, 모르는 값이면 그대로 둔다', () => {
  const s = O.createOverlayState();
  eq(O.setMainOf(s, 'self').main, 'self');
  eq(O.setMainOf(O.setMainOf(s, 'self'), 'slides').main, 'slides');
  if (O.setMainOf(s, 'face') !== s) throw new Error('모르는 값인데 새 상태를 만들었어요');
});
test('prev 를 주면 바뀐 칸만 쓴다 — 지적 중 작은 창을 눌러도 삐약이 표정·이름표를 덮지 않는다', () => {
  const el = fakeEls();
  const a = O.createOverlayState();
  O.renderOverlay(a, el);
  el.seat.dataset.mood = 'happy'; el.status.textContent = '좋아요';   // showTell 이 잠깐 바꿔 둔 것
  const b = O.setMainOf(a, 'self');
  O.renderOverlay(b, el, a);
  eq([el.call.dataset.main, el.seat.dataset.mood, el.status.textContent], ['self', 'happy', '좋아요']);
});
test('질문·자막: 질문은 {text, tag, scene} 로 담기고 자막은 그대로 그려진다', () => {
  const el = fakeEls();
  const a = O.createOverlayState();
  const b = O.setCaption(O.askQuestion(a, { text: '왜 SaaS 인가요?', tag: 'B2B', scene: 2 }), '저희 서비스는');
  eq(b.question, { text: '왜 SaaS 인가요?', tag: 'B2B', scene: 2 });
  O.renderOverlay(b, el, a);
  eq(el.caption.textContent, '저희 서비스는');
  eq(O.askQuestion(b, null).question, null);
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
/* H-11 자기검사 — 총평을 늘 붙이던 옛 규칙으로 되돌리면 「오답 풍선에 모범답이 없다」 시험이 깨져야 한다 */
const SUMMARY_LINE = "const showSummary = closed || stage === 'explain';";
test('총평을 늘 붙이던 옛 규칙으로 돌리면 H-11 시험이 깨진다', async () => {
  const src = readFileSync(LOGIC_PATH, 'utf8');
  if (!src.includes(SUMMARY_LINE)) throw new Error(`judgementView 가 바뀌었어요. 이 자기검사도 같이 고쳐야 해요: ${SUMMARY_LINE}`);
  const B = await importSource(src.replace(SUMMARY_LINE, 'const showSummary = true;'));
  const b = B.judgementBubble({ verdict: 'wrong', react: 'r', summary_sentence: '모범답', mastered: false });
  if (!b.text.includes('모범답')) throw new Error('깨진 규칙도 모범답을 숨겼어요 — 시험이 아무것도 안 지킨다');
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
