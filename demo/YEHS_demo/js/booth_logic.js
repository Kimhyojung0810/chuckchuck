/**
 * 부스 체험(booth.js)의 순수 함수. DOM·브라우저 API 를 만지지 않는다.
 *
 * 왜 따로 두나 — booth.js 는 최상위에서 버튼을 배선하므로 브라우저 없이는 못 올린다.
 * 여기 있는 것은 node 스모크(tests/js/booth.smoke.mjs)가 그대로 import 해서 시험한다.
 * 담기 경로 결정·받아쓰기 붓·읽어 줄 문장처럼 "브라우저에서만 틀리는" 판단을 모아 둔다.
 */

export const MAX_SHOTS = 8;
/** 업로드 이미지의 긴 변. Upstage 가 글자를 읽기엔 충분하고 부스 와이파이엔 가볍다. */
export const IMAGE_LONG_EDGE = 1600;

/**
 * 어느 담기 버튼을 보여 줄지. 브라우저 사정은 인자로만 받는다.
 *
 * - 카메라 미리보기(getUserMedia)는 보안 컨텍스트에서만 열린다. http://10.x 로 들어온 폰은
 *   파일 입력의 capture 속성으로 기기 카메라 앱을 연다 — http 에서도 된다.
 * - 화면 공유는 데스크톱 전용. 폰은 API 가 없거나, 있어도 자기 화면밖에 못 담아 의미가 없다.
 * - 첫 번째 버튼(primary)은 손가락 기기면 카메라, 마우스 기기면 화면 공유. 부스 노트북은
 *   자료가 열린 창을 공유하는 게 제일 빠르고, 폰은 찍는 게 제일 빠르다.
 */
export function captureRoutes({ secure = true, hasUserMedia = false, hasDisplayMedia = false, coarse = false } = {}) {
  const camera = secure && hasUserMedia ? 'live' : 'file';
  const share = !coarse && secure && hasDisplayMedia;
  const primary = coarse || !share ? 'camera' : 'share';
  return { camera, share, primary };
}

/** 긴 변을 maxLong 아래로 맞추는 배율. 작은 그림은 키우지 않는다. */
export function fitScale(w, h, maxLong = IMAGE_LONG_EDGE) {
  const long = Math.max(Number(w) || 0, Number(h) || 0);
  if (!long) return 1;
  return Math.min(1, maxLong / long);
}

/** 담은 장면 이름. 카메라 사진은 JPEG, 화면 캡처는 PNG — 서버는 내용으로 판별하지만 이름도 맞춘다. */
export function shotFileName(index, mimeType) {
  const ext = /jpe?g/i.test(mimeType || '') ? 'jpg' : 'png';
  return `장면-${index + 1}.${ext}`;
}

/** 담은 장면 수에 따른 안내. 1장은 그래프가 얕아 「1번 장면」질문만 나온다 (plan §5). */
export function shotsAdvice(n) {
  if (n <= 0) return '장면을 2~4장 담으면 질문이 깊어져요.';
  if (n === 1) return '한 장 더 담으면 장면끼리 잇는 질문이 나와요.';
  if (n >= MAX_SHOTS) return `최대 ${MAX_SHOTS}장까지 담을 수 있어요.`;
  return `${n}장 담았어요. 서로 다른 장면일수록 좋아요.`;
}

/**
 * 카메라 오류 코드 → 무슨 일 · 왜 · 이제 뭘 (토스 오류 문구 시스템, cam-track §3-1).
 * 담기 단계용 — 다음 길은 「사진 찍어 올리기」다 (버튼이 그쪽으로 바뀐다).
 */
export function cameraErrorText(err) {
  const name = (err && err.name) || '';
  if (name === 'NotAllowedError' || name === 'SecurityError') return '카메라 권한이 꺼져 있어서 열 수 없어요. 사진을 찍어 올리면 같은 체험을 할 수 있어요.';
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return '이 기기에서 카메라를 찾을 수 없어요. 사진을 찍어 올리면 같은 체험을 할 수 있어요.';
  if (name === 'NotReadableError') return '다른 앱이 카메라를 쓰고 있어서 열 수 없어요. 그 앱을 닫고 다시 누르면 열려요.';
  if (name === 'AbortError') return '카메라를 여는 중에 끊겼어요. 다른 앱이 쓰고 있거나 장치가 잠깐 응답하지 않았어요. 그 앱을 닫고 다시 누르면 열려요.';
  return '카메라를 열지 못했어요. 이 브라우저가 지원하지 않을 수 있어요. 사진을 찍어 올리면 같은 체험을 할 수 있어요.';
}

/**
 * 통화 중 내 모습(앞카메라)을 못 열었을 때. 통화는 목소리로 이어진다 — 다음 길은 「카메라 켜기」다.
 * (예전엔 cameraErrorText 에서 문장을 잘라 붙였다 — 문장이 바뀌면 조용히 안 잘렸다)
 */
export function selfViewErrorText(err) {
  const name = (err && err.name) || '';
  if (name === 'NotAllowedError' || name === 'SecurityError') return '카메라 권한이 꺼져 있어요. 권한을 켜고 「카메라 켜기」를 눌러요. 그때까지 목소리로 통화해요.';
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return '카메라를 찾을 수 없어요. 카메라를 연결하고 「카메라 켜기」를 눌러요. 그때까지 목소리로 통화해요.';
  if (name === 'NotReadableError') return '다른 앱이 카메라를 쓰고 있어요. 그 앱을 닫고 「카메라 켜기」를 눌러요. 그때까지 목소리로 통화해요.';
  if (name === 'AbortError') return '카메라를 여는 중에 끊겼어요. 다른 앱이 쓰고 있거나 장치가 잠깐 응답하지 않았어요. 그 앱을 닫고 「카메라 켜기」를 눌러요. 그때까지 목소리로 통화해요.';
  return '카메라를 열지 못했어요. 「카메라 켜기」를 한 번 더 눌러요. 그때까지 목소리로 통화해요.';
}

/* ─── 말해서 답하기 ─────────────────────────────────────────────────────── */

/** 마이크 버튼 이름. 앱(qa_live.js MIC_STATE)과 같은 말을 쓴다 — 부스에서 앱으로 넘어가도 낯설지 않게. */
export const MIC_LABEL = {
  idle: '말해서 답하기',
  opening: '마이크 여는 중',
  dictating: '그만 말하기',
  recording: '녹음 멈추고 받아쓰기',
  transcribing: '받아쓰는 중',
};

/** 받아쓰기 붓의 시작점. 이미 쳐 놓은 글은 기준선으로 잡아 둔다. */
export function newPen(current) {
  return { base: (current || '').trim(), painted: null };
}

/**
 * 받아쓰기 한 조각을 입력창 값으로 만든다 (qa_live.js paintLiveAnswer 의 순수 부분).
 *
 * 중간 결과가 올 때마다 입력창을 통째로 다시 쓰므로, 우리가 마지막으로 쓴 값(painted)과
 * 지금 값(current)이 다르면 그 사이에 사용자가 타이핑한 것이다 — 그 글자를 새 기준선으로
 * 삼는다. 안 그러면 말하는 도중에 친 글이 다음 조각에 지워진다.
 * 붓은 바꾸지 않고 새 붓을 돌려준다.
 */
export function paintDictation(pen, current, spoken) {
  let base = pen.base;
  if (pen.painted !== null && current !== pen.painted) base = (current || '').trim();
  const said = (spoken || '').trim();
  const value = base && said ? `${base} ${said}` : (base || said);
  return { pen: { base, painted: value }, value };
}

/** 받아쓴 문장을 기존 글 뒤에 잇는다. 채워만 주고 보내지는 않는다. */
export function appendTranscript(current, text) {
  const prev = (current || '').trim();
  const add = (text || '').trim();
  if (!add) return prev;
  return prev ? `${prev} ${add}` : add;
}

/* ─── 말로 조작하기 (9/23) ─────────────────────────────────────────────────
   사용자: "모르겠어요·다음 질문… 전부 말로 진행할 수 있도록". 받아쓰기의 **확정된 조각** 끝에서만 본다 —
   중간 결과(interim)는 글자가 계속 바뀌어서 명령으로 읽으면 헛발질한다.
   명령은 문장 **끝**에 있어야 한다("…때문이에요 다음 질문"). 앞부분(rest)은 답으로 남긴다.
   「모르겠어요」는 답 안에도 흔히 나오므로("정확한 수치는 모르겠어요") 앞이 두 어절 이하일 때만 포기로 본다.
   allowed 로 지금 눌릴 수 있는 버튼만 허용한다 — 판정 전에 「다음 질문」이라고 해도 아무 일도 안 일어난다. */
export const VOICE_COMMANDS = [
  { cmd: 'next',   re: /(?:다음\s*질문(?:이요|으로|이요)?|다음\s*문제|넘어가\s*(?:요|자|줘|주세요|겠어요)?|통화\s*마치기|여기까지\s*할게요)$/ },
  { cmd: 'giveup', re: /(?:잘\s*)?모르겠(?:어요|어|습니다|네요|는데요)$/, shortRest: 2 },
  { cmd: 'hint',   re: /힌트(?:요|\s*주세요|\s*줘요|\s*줘|\s*하나만|\s*보여\s*줘요|\s*보여\s*줘|\s*볼게요)?$/ },
  { cmd: 'again',  re: /다시\s*(?:답|말)(?:할게요|해\s*볼게요|해볼게요|하기)$/ },
  { cmd: 'answer', re: /(?:답할게요|보낼게요|답하기|보내기|보내\s*주세요|이상입니다|이상이에요|끝이에요|여기까지예요)$/ },
];
const VOICE_TRAIL = /[\s.,!?。…~]+$/;

/**
 * 확정 조각 하나에서 명령을 찾는다. 없으면 null.
 * 반환: { cmd, rest } — rest 는 명령을 뗀 앞부분(답으로 남길 글).
 */
export function voiceCommand(chunk, allowed = {}) {
  const text = (chunk || '').replace(VOICE_TRAIL, '').replace(/\s+/g, ' ').trim();
  if (!text) return null;
  for (const { cmd, re, shortRest } of VOICE_COMMANDS) {
    if (allowed[cmd] === false) continue;
    const m = text.match(re);
    if (!m) continue;
    const rest = text.slice(0, m.index).replace(VOICE_TRAIL, '').trim();
    // 명령 앞이 붙어 있으면(공백 없이) 단어의 일부다: "다음질문" 은 되지만 "그다음 질문" 의 "다음 질문" 은 안 된다
    if (rest && !/\s$/.test(text.slice(0, m.index))) continue;
    if (shortRest !== undefined && rest && rest.split(' ').length > shortRest) continue;
    return { cmd, rest };
  }
  return null;
}

/* ─── 판정 · 읽어 주기 ──────────────────────────────────────────────────── */

export const VERDICT_WORD = { good: '잘 답했어요', partial: '반쯤 왔어요', wrong: '자료와 달라요', unknown: '아직 모르겠어요' };
/** 「모르겠어요」에 온 응답은 판정이 아니다 — pill 에 판정 낱말 대신 코치가 지금 하는 일을 적는다 (앱 qa_live coachMeta 와 같은 뜻) */
export const COACH_WORD = { narrow: '같이 찾아봐요', scaffold: '빈칸을 채워요', explain: '답을 같이 풀어요', clarify: '질문을 다시 풀었어요' };
/** 요지는 맞았는데(passed) 서버가 한 걸음 더 묻는 판정의 pill */
export const PASSED_WORD = '요지는 맞아요';
/** 3라운드 출구로 닫힌 질문 (서버 close_reason) — 설득(good)과 따로 말한다. 앱 결과 화면 칩과 같은 말 */
export const CLOSE_WORD = { rounds: '요지는 통과했어요', guard: '자료와 다시 맞춰 봐요' };
/** 이 칸(방향·범위·인용 다음)까지 힌트를 연 질문은 「도움 받아 답했어요」로 센다 — 셋째 칸부터 답에 가까워진다 */
export const HINT_HELP_LEVEL = 3;

const isText = (s) => typeof s === 'string' && !!s.trim();

/** 질문의 힌트 사다리. 새 계약(hints[])이 있으면 그것, 없으면 옛 hint 한 칸. */
export function hintLadder(q) {
  if (Array.isArray(q && q.hints) && q.hints.length) return q.hints.filter(isText);
  return q && isText(q.hint) ? [q.hint] : [];
}

/**
 * 판정이 준 사다리와 지금 들고 있는 사다리 중 쓸 것. 판정본이 **짧지 않으면** 갈아탄다 — 짧아지면 안 버린다
 * (분모가 「힌트 2/4」 다음에 「3/3」 으로 줄지 않게). 같은 길이도 갈아탄다 — 서버가 판정 뒤 넷째 칸을
 * 「아직 안 나온 것」 으로 바꿔 끼운다 (앱 qa_live submitLiveAnswer 와 같은 규칙).
 */
export function mergeLadder(kept, incoming) {
  const inc = Array.isArray(incoming) ? incoming.filter(isText) : [];
  const cur = Array.isArray(kept) ? kept : [];
  return inc.length && inc.length >= cur.length ? inc : cur;
}

/**
 * 판정에 「보여 준 힌트」 로 실어 보낼 것 (09-30 H-14·B-08) — **사용자가 실제로 연 칸만**, 연 그때의 글 그대로.
 * 예전엔 판정이 붙여 준 사다리 여섯 칸을 통째로 넣어, 한 번도 안 연 힌트까지 「본 힌트」 가 됐다.
 * 「모르겠어요」 코칭이 방금 보기·빈칸으로 되물었으면 그 되물음도 싣는다 — 이번 답은 그 물음의 답이다.
 */
export function hintsForJudge(seen, lastJudgement) {
  const opened = (Array.isArray(seen) ? seen : []).filter(isText);
  return opened.concat(coachAsk(lastJudgement));
}

/** 방금 코칭이 던진 되물음(보기·빈칸). 코칭이 아니면 빈 배열 — 앱 qa_live liveCoachAsk 와 같은 모양 */
export function coachAsk(j) {
  return j && ['narrow', 'scaffold'].includes(j.coach_stage) && isText(j.followup) ? [`되물음: ${j.followup.trim()}`] : [];
}

/** 판정에 보낼 대화 — **이 질문의 턴만** (09-30 M-08: 끝난 질문 Q/A 가 react 에 새어 들었다). 앱 liveHistory 와 같다 */
export function questionHistory(history, questionId) {
  return (Array.isArray(history) ? history : []).filter((t) => t && t.question_id === questionId);
}

/**
 * 이 질문에 **채점된** 답들 — 서버가 이 개수로 라운드를 센다 (f09 `_round_no`). 「모르겠어요」 턴과 되물음(clarify) 턴은 뺀다
 * (09-30 B-10: 부스는 되물음 턴까지 누적 답으로 보내 라운드가 이유 없이 올랐다). 앱 liveScoredAnswers 와 같다.
 */
export function scoredAnswers(turns) {
  return (Array.isArray(turns) ? turns : []).filter((t) => t && !t.giveUp && !t.clarify && isText(t.answer)).map((t) => t.answer.trim());
}

/** 서버가 이 질문을 닫았는가 (mastered). 옛 브리지(mastered 없음)는 good 만 닫는다. 코칭 응답은 닫지 않는다 (H-12·B-10) */
export function judgementClosed(j) {
  if (!j || j.coach_stage) return false;
  return typeof j.mastered === 'boolean' ? j.mastered : j.verdict === 'good';
}

/**
 * 서버가 길이 상한에서 자른 글(끝이 「…」)을 **마지막 온전한 문장까지**로 되돌린다 — 문장 한가운데서 끊긴 채 보이지 않게 (09-30 H-10:
 * 「…PoC 단계에서 아이디어 및 개념 검증을 진행」 에서 끊긴 골자). 온전한 문장이 하나도 없으면 말줄임을 단 그대로 둔다.
 * 안 잘린 글은 건드리지 않는다.
 */
export function wholeSentences(text) {
  const t = String(text || '').trim();
  if (!/(?:…|\.\.\.)$/.test(t)) return t;
  const body = t.replace(/(?:…|\.\.\.)$/, '');
  const end = /[.!?。](?:["'」』”’»)\]]*)(?=\s|$)/g;
  let cut = -1;
  for (let m = end.exec(body); m; m = end.exec(body)) cut = m.index + m[0].length;
  return cut > 0 ? body.slice(0, cut).trim() : t;
}

/** 판정 풍선의 「빠진 것」 — 가드 사유 표기(「질문이 묻는 것:」「자료 N장과 어긋난 곳:」)는 결손이 아니다 (09-30 H-11·M-02) */
export function cleanMissing(points) {
  return (Array.isArray(points) ? points : [])
    .filter(isText).map((m) => m.trim())
    .filter((m) => !/^(?:질문이 묻는 것|자료\s*\d*\s*장?과 어긋난 곳)\s*:/.test(m));
}

/**
 * 판정 한 풍선이 무엇을 보이고 무엇을 숨길지 (09-30 held-out H-10·H-11·H-12). 화면·읽어 주기가 같은 결과를 쓴다.
 *
 * - 머리: pill 한 낱말 + react. 총평(summary_sentence)은 **닫혔거나(mastered) 해설 단계일 때만** 붙인다 — 오답·절반
 *   풍선에 붙이면 모범답을 흘린다 (H-11: 「…두 가지 과금 구조로 설계되어야 해요」 가 「자료와 달라요」 아래 붙었다).
 * - 「모르겠어요」는 서버의 코칭 단계를 따른다 (H-10): narrow·scaffold 는 되물음 + 보기 칩 · explain 은 해설 · clarify 는
 *   다시 푼 질문. 골자(answer_gist)는 **해설 단계에서 해설이 비었을 때만**, 함정이 아니면 쓴다. 예전엔 첫 「모르겠어요」에
 *   (잘리고 틀린) 골자를 바로 보여 주고 답칸을 잠갔다.
 * - 닫혔으면 되묻지 않는다 (H-12). 3라운드 출구로 닫힌 것은 pill 이 그렇다고 말한다(CLOSE_WORD).
 * 판정 색은 pill 의 data-v(good·partial·wrong·unknown)로만 — 코칭 응답은 판정이 아니라 unknown(회색)이다.
 */
export function judgementView(j, { giveUp = false, answerGist = '', trap = false } = {}) {
  if (!j) return null;
  const stage = j.coach_stage || '';
  const closed = judgementClosed(j);
  // 닫힌 까닭 — 옛 브리지(close_reason 없음)는 good 이 아닌 닫힘을 라운드 출구로 읽는다 (qa_mastered 가 그 길뿐이다)
  const reason = closed ? (j.close_reason || (j.verdict === 'good' ? 'good' : 'rounds')) : '';
  let verdict = stage ? 'unknown' : (j.verdict || 'unknown');
  let word = stage ? (COACH_WORD[stage] || COACH_WORD.narrow) : (VERDICT_WORD[verdict] || verdict);
  if (CLOSE_WORD[reason]) { word = CLOSE_WORD[reason]; verdict = 'partial'; }
  // 70~79 통과(요지는 맞음)인데 아직 한 걸음 더 묻는 판정 — 「반쯤 왔어요」 가 아니다. 앱 qa_live 칩과 같은 규칙 (09-30 §10)
  else if (!stage && !closed && j.verdict === 'partial' && j.passed === true) { word = PASSED_WORD; verdict = 'good'; }
  const showSummary = closed || stage === 'explain';
  const text = [j.react, showSummary ? j.summary_sentence : ''].filter(isText).map((s) => s.trim()).join(' ');
  const missing = reason === 'good' || stage ? [] : cleanMissing(j.missing_points);
  let tail = null;
  if (stage === 'explain' || (giveUp && !stage && isText(j.explanation))) {
    // 해설 — 서버 해설이 먼저. 비었을 때만 골자로 (함정의 골자는 바로잡은 사실 그 자체라 질문 사본에 없다 — 브리지가 해설 단계
    // 판정 응답에 answer_gist 로 싣는다, 09-30 WP-J2)
    const ex = wholeSentences(j.explanation) || wholeSentences(isText(j.answer_gist) ? j.answer_gist : (trap ? '' : answerGist));
    if (ex) tail = { kind: 'explain', text: ex, choices: [] };
  } else if (!closed && isText(j.followup)) {
    const choices = stage ? (Array.isArray(j.choices) ? j.choices.filter(isText).map((c) => c.trim()).slice(0, 4) : []) : [];
    tail = { kind: 'followup', text: j.followup.trim(), choices };
  }
  return { verdict, word, text, missing, missingHead: closed ? '다시 볼 것' : '빠진 것', tail, closed, stage };
}

/**
 * 코치가 소리 내어 읽을 문장. **화면에 있는 말만** 읽는다 — 화면과 다른 말을 하면
 * 소리가 데이터를 가린다 (UI_REDESIGN §14). judgementView 가 풍선에 담은 것(반응·총평·되묻기/해설)을 그대로 읽는다.
 */
export function speakableJudgement(j, opts = {}) {
  const v = judgementView(j, opts);
  if (!v) return '';
  return [v.text, v.tail ? v.tail.text : ''].filter(isText).map((s) => s.trim()).join(' ');
}

/** 「모르겠어요」 버튼 이름 — 서버 사다리(narrow → scaffold → explain)를 따라 다음에 무슨 일이 생길지 미리 말한다.
    앱 qa_live stuckLabelFor 와 같은 말 (09-30 L-01: 첫 「모르겠어요」 부터 「답 볼게요」 라고 했는데 서버는 되물음 단계였다) */
export function giveupLabel(gaveUpCount) {
  if (gaveUpCount >= 2) return '그래도 모르겠어요 · 답 보기';
  if (gaveUpCount === 1) return '그래도 모르겠어요 · 빈칸으로';
  return '모르겠어요';
}

/** 내 말풍선에 남길 「모르겠어요」 — 자리표시자 「(모르겠어요)」 가 그대로 보이지 않게. 적어 둔 글이 있으면 그 글이다 */
export function giveupSaid(typed) {
  return isText(typed) ? typed.trim() : '모르겠어요';
}

/**
 * 판정·질문 응답의 폴백 표시를 짧은 사람 말로 (09-30 WP-B degraded). 자료 본문 없이 판정했으면(grounded_on_deck=false) 그렇다고 한다.
 * 서버가 만든 질문을 못 찾은 것(grounded_on_server=false · question_unverified·question_mismatch)은 사용자가 할 일이 없어
 * 화면에 싣지 않는다 — 개발 로그 몫이다.
 */
const DEV_ONLY_DEGRADED = new Set(['question_unverified', 'question_mismatch']);
/** 녹음이 이 자료와 다른 발표라 F-08 이 자료만 보고 물었다 — 앱 qa_live LIVE_SPEECH_MISMATCH_NOTE 와 같은 말 (09-30 WP-J2) */
export const SPEECH_MISMATCH_NOTE = '녹음이 이 자료와 달라서 자료만 보고 질문했어요.';
export function degradedLines(res) {
  if (!res || typeof res !== 'object') return [];
  const codes = Array.isArray(res.degraded) ? res.degraded : [];
  const notes = Array.isArray(res.degraded_notes) ? res.degraded_notes : [];
  const out = [];
  notes.forEach((n, i) => { if (isText(n) && !DEV_ONLY_DEGRADED.has(codes[i])) out.push(n.trim()); });
  if (res.grounded_on_deck === false && !codes.includes('slide_doc_missing')) out.push('자료 본문 없이 판정했어요.');
  if (speechMismatch(res)) out.push(SPEECH_MISMATCH_NOTE);
  return [...new Set(out)];
}

/** 질문 묶음이 녹음을 버리고 자료만으로 만들어졌나 — 질문마다의 basis.checks(F-08) 또는 묶음 머리의 같은 이름 참 값 */
export function speechMismatch(res) {
  if (!res || typeof res !== 'object') return false;
  if (res.speech_mismatch_deck_only === true) return true;
  const qs = Array.isArray(res.questions) ? res.questions : [];
  return qs.some((q) => q && q.basis && Array.isArray(q.basis.checks) && q.basis.checks.includes('speech_mismatch_deck_only'));
}

/** 개발 로그로만 남길 폴백 (화면에는 안 싣는다) */
export function devOnlyDegraded(res) {
  if (!res || typeof res !== 'object') return [];
  const codes = Array.isArray(res.degraded) ? res.degraded.filter((c) => DEV_ONLY_DEGRADED.has(c)) : [];
  return res.grounded_on_server === false && !codes.length ? ['grounded_on_server=false'] : codes;
}

/**
 * 질문 아래 이유 한 줄. 함정 질문은 서버 이유가 「질문이 말한 내용이 자료와 같은지 먼저 따져 보는 연습이에요」 라 **함정임을
 * 알려 준다** (09-30 B-01·H-07) — 다른 질문과 같은 모양이어야 하므로 장만 가리키는 중립 문장으로 바꾼다.
 */
export function questionWhy(q) {
  if (!q) return '';
  if (q.trap) {
    const nos = [...new Set((q.slide_nos || []).map(Number).filter((n) => n > 0))];
    return `${nos.length ? `자료 ${nos.join('·')}장을` : '자료를'} 근거로 설명할 수 있는지 보려고 물어요.`;
  }
  return isText(q.why) ? q.why.trim() : '';
}

/** 요청 제한·AI 서버 지연으로 기다렸다가 다시 보낼 때의 안내 (09-30 H-15). 몇 초 남았는지 보인다 */
export function retryWaitText(secondsLeft, reason = 'rate') {
  const n = Math.max(0, Math.ceil(Number(secondsLeft) || 0));
  if (reason === 'upstream') return n > 0 ? `AI 서버가 늦어서 ${n}초 뒤에 한 번 더 보낼게요.` : '한 번 더 보내는 중이에요.';
  return n > 0 ? `요청이 몰려서 잠깐 기다렸다 다시 보낼게요 · ${n}초` : '다시 보내는 중이에요.';
}

/**
 * 마지막 화면의 질문별 결과 (09-30 held-out H-12·H-13) — 마지막 판정 낱말을 그대로 옮기지 않고 무슨 일이 있었는지 적는다.
 *   안 물었어요 (한 번도 안 띄웠다) · 답하기 전에 마쳤어요 (띄웠는데 답이 없다)
 *   잘 답했어요 (도움 없이 닫힘) · 도움 받아 답했어요 (코칭·해설·힌트 셋째 칸 뒤에 닫힘)
 *   요지는 통과했어요 · 자료와 다시 맞춰 봐요 (3라운드 출구) · 답을 같이 풀었어요 (해설을 봤고 안 닫힘)
 *   그 밖 — 닫히지 않은 마지막 판정 낱말 (반쯤 왔어요·자료와 달라요·아직 모르겠어요)
 * verdict(data-v)는 판정 색 넷(good·partial·wrong·unknown) + 회색 unasked 만 쓴다.
 * 옛 모양(verdicts 만 있고 closed 가 없는 기록)은 마지막 판정이 good 이면 닫힌 것으로 읽는다.
 */
export function tally(questions, perQ) {
  return (questions || []).map((q, i) => {
    const p = (perQ && perQ[q.id]) || {};
    const vs = Array.isArray(p.verdicts) ? p.verdicts : [];
    const row = (verdict, word) => ({ no: i + 1, label: q.label || '질문', verdict, word });
    if (!vs.length) return p.asked ? row('unasked', '답하기 전에 마쳤어요') : row('unasked', '안 물었어요');
    const last = vs[vs.length - 1];
    const closed = p.closed === undefined ? last === 'good' : !!p.closed;
    if (closed) {
      if (CLOSE_WORD[p.closeReason]) return row('partial', CLOSE_WORD[p.closeReason]);
      const helped = !!(p.coached || p.explained || (p.hintLevel || 0) >= HINT_HELP_LEVEL);
      return helped ? row('partial', '도움 받아 답했어요') : row('good', VERDICT_WORD.good);
    }
    if (p.explained) return row('unknown', '답을 같이 풀었어요');
    return row(VERDICT_WORD[last] ? last : 'unknown', VERDICT_WORD[last] || VERDICT_WORD.unknown);
  });
}

/* ─── 통화 모드 — 화상통화처럼 내 모습 위로 질문·자막·판정이 오간다 ─────── */

/** 상대(병아리)의 기분. chatter.css 의 data-mood 훅(curious·happy·grumpy·excited)과 같은 이름만 쓴다. */
export function partnerMood(phase, verdict = '') {
  if (phase === 'asking' || phase === 'hint') return 'curious';
  if (phase === 'listening' || phase === 'judging') return 'neutral';
  if (phase === 'judged') {
    if (verdict === 'good') return 'happy';
    if (verdict === 'wrong') return 'grumpy';
    return 'curious';
  }
  return 'neutral';
}

/** 자동 대화의 침묵 판정 — 마지막으로 글자가 바뀐 뒤 quietMs 가 지났고, 말한 게 있으면 끝난 것으로 본다. */
export function speechSettled({ lastChangeAt, now, text, quietMs = 2500 }) {
  if (!text || !String(text).trim()) return false;
  if (!Number.isFinite(lastChangeAt) || !Number.isFinite(now)) return false;
  return now - lastChangeAt >= quietMs;
}

/** 보내기 전 카운트다운 문구. 고칠 틈을 눈에 보이게 남긴다 — 자동으로 보내되 몰래 보내지 않는다. */
export function countdownText(secondsLeft) {
  const n = Math.max(0, Math.ceil(Number(secondsLeft) || 0));
  return n > 0 ? `${n}초 뒤에 보낼게요. 고치려면 자막을 눌러요.` : '보내는 중이에요.';
}

/**
 * 상대 말풍선 목록 — 판정 하나를 통화의 말풍선 몇 개로 나눈다 (judgementView 를 조각으로 편 것).
 * 화면 카드와 같은 재료만 쓴다. 판정 색은 pill 로만.
 */
export function judgementBubbles(j, opts = {}) {
  const v = judgementView(j, opts);
  if (!v) return [];
  const out = [{ kind: 'verdict', verdict: v.verdict, text: v.text }];
  if (v.missing.length) out.push({ kind: 'missing', verdict: v.verdict, items: v.missing });
  if (v.tail) out.push({ kind: v.tail.kind, verdict: v.verdict, text: v.tail.text });
  return out;
}

/**
 * 판정 한 풍선 — 9/23 사용자: "판정 뒤에 말풍선 쌓이는 것도 최근 하나만 남게".
 * judgementView 의 조각(반응+요약 · 빠진 것 · 되묻기/해설 · 보기)을 버리지 않고 한 풍선에 담는다.
 * 화면은 이 풍선 하나로 앞 풍선(질문·내 답·힌트)을 갈아 끼운다. 판정 색은 pill 로만 — 숫자·판정은 잃지 않는다.
 */
export function judgementBubble(j, opts = {}) {
  const v = judgementView(j, opts);
  if (!v) return null;
  return { verdict: v.verdict, word: v.word, text: v.text, missing: v.missing, missingHead: v.missingHead, tail: v.tail, closed: v.closed, stage: v.stage };
}

/* ─── 발표 모드 — 실시간 말하기 피드백 (9/23) ───────────────────────────────
   사용자: "발표를 하는 와중에도 삐약이가 시무룩해하면서 너무 말이 빨라요 · 느려요 · 똑같은 말을 많이 해요 ·
   '어' '음' 을 많이 써요 · 산만하게 움직여요 … 비슷한 상황 전부". LLM 없이 브라우저 안에서 잰다 —
   받아쓰기 글자 수(빠르기·간투어·반복·멈춤), 웹캠 프레임 차이(움직임), 마이크 음량(작은 목소리).
   Q&A 로 넘어가면 쓰지 않는다. 숫자는 실측이고, 재료가 모자라면 말하지 않는다 (샘플로 위장하지 않는다). */

/** f18_habits.FILLERS 의 거울 — 서버가 세는 간투어와 같은 낱말만 센다 */
export const FILLERS = new Set([
  '어', '음', '그', '저', '에', '아', '뭐', '이제', '약간', '좀',
  '그게', '그냥', '사실은', '일단', '뭐랄까', '그니까', '그러니까',
  '어쨌든', '아무튼', '막',
]);
/** app.js CPM_REC 와 같은 값 — F-17 권장이 없을 때의 화면 기본(자/분). 빠름·느림 판정도 앱과 같은 배수(1.15 · 0.85) */
export const CPM_REC = { min: 300, max: 350 };

export const DELIVERY = {
  windowMs: 15000,      // 빠르기 창
  recentMs: 30000,      // 간투어·반복 창
  gapMs: 2000,          // 이보다 긴 틈은 말한 시간에서 뺀다
  minChars: 25,         // 창 안에 이만큼은 말해야 빠르기를 잰다
  minSpeakMs: 6000,
  cooldownMs: 12000,    // 지적과 지적 사이
  sameKindMs: 45000,    // 같은 지적은 이 안에 다시 안 한다
  steadyMs: 60000,      // 칭찬 간격
  pauseMs: 5000,        // f18 PAUSE_SEC 와 같다
  slideGraceMs: 8000,   // 장면을 넘긴 직후엔 멈춤을 지적하지 않는다 — 넘기며 숨 고르는 건 자연스럽다
  fidgetMotion: 12,     // 32×18 회색 프레임의 평균 픽셀 차 — 정지 화면 잡음 2~4, 몸 흔들림 8~15 (부스 리허설에서 보정)
  fidgetMs: 5000,
  quietLevel: 0.015,    // RMS. 보통 말소리 0.05~0.2 (부스 마이크에서 보정)
  quietMs: 6000,
};

export const TELL_WORD = { fast: '빠름', slow: '느림', filler: '간투어', repeat: '반복', pause: '멈춤', fidget: '움직임', quiet: '작은 목소리', steady: '안정' };
/** 지적하는 동안 병아리 이름표 아래 한 줄 */
export const TELL_STATUS = {
  fast: '조금 빨라요', slow: '조금 느려요', filler: '「어」「음」이 들려요', repeat: '같은 말이 반복돼요',
  pause: '잠깐 멈췄어요', fidget: '움직임이 많아요', quiet: '목소리가 작아요', steady: '좋아요',
};
export const MIC_LABEL_PRESENT = {
  idle: '발표 듣게 하기', opening: '마이크 여는 중', dictating: '듣기 멈추기', recording: '녹음 중', transcribing: '받아쓰는 중',
};

export function createDelivery() {
  return { events: [], lastTellAt: -1e12, lastByKind: {}, counts: {}, startedAt: null, slide: null, slideAt: -1e12 };
}

function speechChars(text) { return ((text || '').match(/[가-힣A-Za-z0-9]/g) || []).length; }
function tokens(text) {
  return (text || '').split(/\s+/).map((t) => t.replace(/[^\w가-힣]/g, '').toLowerCase()).filter(Boolean);
}

/** 창 안의 말 빠르기. "말한 시간"은 글자가 늘어난 시점들 사이의 간격을 더하되 한 간격은 gapMs 까지만 —
   센서가 0.25초마다 관찰을 넣으므로 관찰 간격으로 재면 5초 멈춤도 말한 시간에 들어가 「느려요」가 잘못 뜬다.
   재료가 모자라면 null — 그러면 말하지 않는다 */
function speakingRate(events, now, D) {
  const win = events.filter((e) => now - e.t <= D.windowMs && e.chars !== undefined);
  if (win.length < 2) return null;
  const grow = [];
  let maxChars = win[0].chars;
  for (let i = 1; i < win.length; i++) { if (win[i].chars > maxChars) { maxChars = win[i].chars; grow.push(win[i].t); } }
  if (grow.length < 2) return null;
  let speakMs = 0;
  for (let i = 1; i < grow.length; i++) speakMs += Math.min(grow[i] - grow[i - 1], D.gapMs);
  const chars = win[win.length - 1].chars - win[0].chars;
  if (chars < D.minChars || speakMs < D.minSpeakMs) return null;
  return { chars, sec: speakMs / 1000, cpm: chars / (speakMs / 60000) };
}

/** 최근 낱말 중 4번 이상 나온 것(간투어 제외) 또는 바로 이어서 더듬은 것("지도 지도") */
function repeatedWord(toks) {
  const counts = new Map();
  let stutter = 0;
  for (let i = 0; i < toks.length; i++) {
    const t = toks[i];
    if (t.length < 2 || FILLERS.has(t)) continue;
    counts.set(t, (counts.get(t) || 0) + 1);
    // 더듬기 — 같은 말 또는 접두 반복("지도 지도력은"). f18 의 REP 와 같은 규칙
    if (i > 0 && toks[i - 1].length >= 2 && t.startsWith(toks[i - 1])) stutter += 1;
  }
  let best = null;
  for (const [word, n] of counts) if (n >= 4 && (!best || n > best.n)) best = { word, n };
  if (best) return { kind: 'word', ...best };
  if (stutter >= 2) return { kind: 'stutter', n: stutter };
  return null;
}

function avg(xs) { return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0; }

function pickTell(m, text, now, D) {
  if (now - m.lastTellAt < D.cooldownMs) return null;
  const ok = (kind, ms = D.sameKindMs) => now - (m.lastByKind[kind] || -1e12) >= ms;
  const ev = m.events;
  const first = ev.find((e) => now - e.t <= D.recentMs) || ev[0];
  const recent = first ? text.slice(first.len) : text;
  const toks = tokens(recent);

  const fillers = toks.filter((t) => FILLERS.has(t));
  if (fillers.length >= 3 && ok('filler')) {
    const uniq = [...new Set(fillers)].slice(0, 2).map((f) => `「${f}」`).join('');
    return { kind: 'filler', text: `${uniq}이 자주 들려요. 그 자리에서 잠깐 쉬는 게 더 나아요.` };
  }
  const rep = repeatedWord(toks);
  if (rep && ok('repeat')) {
    return rep.kind === 'word'
      ? { kind: 'repeat', text: `「${rep.word}」를 ${rep.n}번 말했어요. 다른 말로 이어 봐요.` }
      : { kind: 'repeat', text: '같은 말을 더듬으며 반복했어요. 한 번에 천천히 말해 봐요.' };
  }
  // 멈춤 — 말한 적이 있고, 마지막으로 글자가 는 뒤 pauseMs 가 지났다
  const spoke = ev.filter((e) => e.chars !== undefined);
  if (spoke.length >= 2) {
    let lastGrow = spoke[0].t;
    for (let i = 1; i < spoke.length; i++) if (spoke[i].chars > spoke[i - 1].chars) lastGrow = spoke[i].t;
    const maxChars = spoke[spoke.length - 1].chars;
    const slideGrace = now - m.slideAt < D.slideGraceMs;
    if (maxChars > 0 && !slideGrace && now - lastGrow >= D.pauseMs && ok('pause')) return { kind: 'pause', text: '잠깐 멈췄어요. 다음 문장으로 이어 가요.' };
  }
  const rate = speakingRate(ev, now, D);
  if (rate && rate.cpm > CPM_REC.max * 1.15 && ok('fast')) return { kind: 'fast', text: '조금 빨라요. 문장 끝에서 한 박자 쉬어도 돼요.' };
  if (rate && rate.cpm < CPM_REC.min * 0.85 && ok('slow')) return { kind: 'slow', text: '조금 느려요. 템포를 살짝 올려도 좋아요.' };
  // 작은 목소리 — 말은 늘고 있는데(글자가 는다) 음량이 낮다
  const lv = ev.filter((e) => now - e.t <= D.quietMs && e.level !== undefined);
  if (lv.length >= 8 && ok('quiet')) {
    const grew = spoke.length >= 2 && spoke[spoke.length - 1].chars - (spoke.find((e) => now - e.t <= D.quietMs) || spoke[0]).chars >= 10;
    if (grew && avg(lv.map((e) => e.level)) < D.quietLevel) return { kind: 'quiet', text: '목소리가 작게 들려요. 조금만 크게 말해요.' };
  }
  // 산만한 움직임 — 최근 fidgetMs 동안 프레임 차이가 계속 크다
  const mv = ev.filter((e) => now - e.t <= D.fidgetMs && e.motion !== undefined);
  if (mv.length >= 8 && avg(mv.map((e) => e.motion)) > D.fidgetMotion && ok('fidget')) {
    return { kind: 'fidget', text: '몸이 많이 움직여요. 자세를 잡고 말해 봐요.' };
  }
  // 칭찬 — 시작하고 60초는 지나야 한다(6초 만에 「좋아요」는 근거가 없다), 그 뒤엔 60초에 한 번
  const settled = m.startedAt !== null && now - m.startedAt >= D.steadyMs;
  if (rate && settled && now - m.lastTellAt >= D.steadyMs && ok('steady', D.steadyMs) && rate.chars >= 60) {
    return { kind: 'steady', text: '좋아요, 이 속도로 가요.' };
  }
  return null;
}

/**
 * 관찰 한 번. 받아쓰기 텍스트(누적)·지금 시각·(있으면) 프레임 차이·음량을 넣으면
 * 새 계기와 지적(없으면 null)을 돌려준다. 계기는 바꾸지 않고 새로 만든다.
 */
export function deliveryObserve(meter, { text = '', now, motion, level, slide } = {}, D = DELIVERY) {
  const e = { t: now, len: text.length, chars: speechChars(text) };
  if (motion !== undefined) e.motion = motion;
  if (level !== undefined) e.level = level;
  const keepMs = Math.max(D.recentMs, D.steadyMs);
  const events = [...meter.events.filter((x) => now - x.t <= keepMs), e];
  const next = { ...meter, events, startedAt: meter.startedAt === null || meter.startedAt === undefined ? now : meter.startedAt };
  // 장면이 바뀐 시각 — 멈춤 지적의 유예에 쓴다. 첫 장면(처음 알게 된 값)은 바뀐 것이 아니다
  if (slide !== undefined && slide !== next.slide) { next.slideAt = next.slide === null || next.slide === undefined ? next.slideAt : now; next.slide = slide; }
  const tell = pickTell(next, text, now, D);
  if (!tell) return { meter: next, tell: null };
  return {
    meter: { ...next, lastTellAt: now, lastByKind: { ...next.lastByKind, [tell.kind]: now }, counts: { ...next.counts, [tell.kind]: (next.counts[tell.kind] || 0) + 1 } },
    tell,
  };
}

/** 마친 화면 한 줄. 지적이 없었으면 빈 문자열 — 없던 걸 있던 것처럼 쓰지 않는다 */
export function deliverySummary(meter) {
  if (!meter || !meter.counts) return '';
  const parts = Object.keys(TELL_WORD).filter((k) => k !== 'steady' && meter.counts[k]).map((k) => `${TELL_WORD[k]} ${meter.counts[k]}`);
  return parts.length ? `발표 중 알려 준 것 · ${parts.join(' · ')}` : '';
}

/* ─── 계기와 기준 맞추기 (9/23) ─────────────────────────────────────────────
   움직임(프레임 차)·목소리 크기(RMS)의 절대값은 웹캠·마이크·조명마다 다르다. 부스 컴퓨터에서
   가만히·조용히 5초를 재서 그 바닥값으로 문턱을 다시 잡는다. 운영자용이고 방문객에겐 안 보인다. */

/** 바닥값(가만히 있을 때의 잡음)으로 새 문턱을 만든다. 나머지 값은 그대로 가져간다 */
export function calibrateDelivery(base = DELIVERY, { motionFloor, levelFloor } = {}) {
  const next = { ...base };
  if (Number.isFinite(motionFloor)) next.fidgetMotion = Math.max(8, Math.round(motionFloor * 3));
  if (Number.isFinite(levelFloor)) next.quietLevel = Math.max(0.006, levelFloor * 4);
  return next;
}

/** 지금 창의 말 빠르기 — 계기 화면이 쓰는 문. 재료가 모자라면 null (deliveryObserve 와 같은 규칙) */
export function speakingRateOf(meter, now, D = DELIVERY) {
  if (!meter || !Array.isArray(meter.events)) return null;
  return speakingRate(meter.events, now, D);
}

function recentAvg(events, now, key, ms = 1000) {
  const xs = events.filter((e) => now - e.t <= ms && e[key] !== undefined).map((e) => e[key]);
  return xs.length ? avg(xs) : null;
}

/** 운영자용 한 줄 — 지금 값 / 지금 기준. 못 잰 것은 「—」로 둔다 (0 으로 위장하지 않는다) */
export function meterText(meter, D = DELIVERY) {
  if (!meter || !meter.events || !meter.events.length) return `움직임 — / 기준 ${D.fidgetMotion} · 음량 — / 기준 ${D.quietLevel}`;
  const now = meter.events[meter.events.length - 1].t;
  const motion = recentAvg(meter.events, now, 'motion');
  const level = recentAvg(meter.events, now, 'level');
  const rate = speakingRateOf(meter, now, D);
  const parts = [
    `움직임 ${motion === null ? '—' : motion.toFixed(1)} / 기준 ${D.fidgetMotion}`,
    `음량 ${level === null ? '—' : level.toFixed(3)} / 기준 ${D.quietLevel}`,
    `빠르기 ${rate ? `${Math.round(rate.cpm)}자/분` : '—'}`,
  ];
  const counts = meter.counts || {};
  for (const k of Object.keys(TELL_WORD)) if (counts[k]) parts.push(`${TELL_WORD[k]} ${counts[k]}`);
  return parts.join(' · ');
}

/** 발표 중 말로 조작 — 「질문 받을게요」「다음 장면」「이전 장면」. voiceCommand 와 같은 규율(문장 끝, 앞은 남긴다) */
export const PRESENT_COMMANDS = [
  { cmd: 'ask',  re: /질문\s*(?:받을게요|받기|주세요|해\s*주세요|받자|시작(?:할게요)?)$/ },
  { cmd: 'next', re: /다음\s*(?:장면|슬라이드|장|페이지)(?:이요|으로)?$/ },
  { cmd: 'prev', re: /이전\s*(?:장면|슬라이드|장|페이지)(?:이요|으로)?$/ },
];
export function presentCommand(chunk) {
  const text = (chunk || '').replace(VOICE_TRAIL, '').replace(/\s+/g, ' ').trim();
  if (!text) return null;
  for (const { cmd, re } of PRESENT_COMMANDS) {
    const m = text.match(re);
    if (!m) continue;
    const rest = text.slice(0, m.index).replace(VOICE_TRAIL, '').trim();
    if (rest && !/\s$/.test(text.slice(0, m.index))) continue;
    return { cmd, rest };
  }
  return null;
}

/** 자막 한 줄 — 긴 전문의 꼬리만. 발표 중 자막은 지금 말하는 문장이 보이면 된다 */
export function captionTail(text, max = 90) {
  const t = (text || '').replace(/\s+/g, ' ').trim();
  return t.length <= max ? t : `…${t.slice(t.length - max)}`;
}

/** mm:ss */
export function clockText(ms) {
  const s = Math.max(0, Math.floor((Number(ms) || 0) / 1000));
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}
