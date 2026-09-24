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
  if (L.countdownText(3) !== '3초 뒤에 보낼게요. 고치려면 자막을 눌러요.') throw new Error(L.countdownText(3));
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
test('판정 한 풍선(9/23): 조각을 잃지 않고 하나로 — 빠진 것·되묻기가 들어가고, 포기면 정답 요지', () => {
  const j = { verdict: 'partial', react: '음,', summary_sentence: '반은 맞아요.', missing_points: ['근거'], followup: '그럼요?', explanation: '정답 X' };
  eq(L.judgementBubble(j), { verdict: 'partial', text: '음, 반은 맞아요.', missing: ['근거'], tail: { kind: 'followup', text: '그럼요?' } });
  eq(L.judgementBubble(j, { giveUp: true }).tail, { kind: 'explain', text: '정답 X' });
  eq(L.judgementBubble({ verdict: 'good', react: '좋아요' }), { verdict: 'good', text: '좋아요', missing: [], tail: null });
  eq(L.judgementBubble(null), null);
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
