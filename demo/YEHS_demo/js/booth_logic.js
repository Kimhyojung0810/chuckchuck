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

/** 카메라 오류 코드 → 다음에 뭘 하면 되는지가 보이는 말. */
export function cameraErrorText(err) {
  const name = (err && err.name) || '';
  if (name === 'NotAllowedError' || name === 'SecurityError') return '카메라 권한이 없어요. 사진을 찍어 올리면 같은 체험을 할 수 있어요.';
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return '카메라를 찾지 못했어요. 사진을 찍어 올리면 같은 체험을 할 수 있어요.';
  if (name === 'NotReadableError' || name === 'AbortError') return '다른 앱이 카메라를 쓰고 있어요. 그 앱을 닫고 다시 누르면 열려요.';
  return '카메라를 열지 못했어요. 사진을 찍어 올리면 같은 체험을 할 수 있어요.';
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

/** 질문의 힌트 사다리. 새 계약(hints[])이 있으면 그것, 없으면 옛 hint 한 칸. */
export function hintLadder(q) {
  if (Array.isArray(q && q.hints) && q.hints.length) return q.hints.filter((h) => typeof h === 'string' && h.trim());
  return q && typeof q.hint === 'string' && q.hint.trim() ? [q.hint] : [];
}

/** 마지막 화면의 질문별 결과. 마지막 판정이 그 질문의 결과다 (다시 답하면 덮는다). */
export function tally(questions, perQ) {
  return (questions || []).map((q, i) => {
    const vs = (perQ && perQ[q.id] && perQ[q.id].verdicts) || [];
    const verdict = vs.length ? vs[vs.length - 1] : 'unknown';
    return { no: i + 1, label: q.label || '질문', verdict, word: VERDICT_WORD[verdict] || verdict };
  });
}

/**
 * 코치가 소리 내어 읽을 문장. **화면에 있는 말만** 읽는다 — 화면과 다른 말을 하면
 * 소리가 데이터를 가린다 (UI_REDESIGN §14). 포기했거나 코치가 설명 단계면 정답 요지를,
 * 아니면 되묻기를 붙인다.
 */
export function speakableJudgement(j, { giveUp = false, answerGist = '' } = {}) {
  if (!j) return '';
  const parts = [j.react, j.summary_sentence];
  if (giveUp || j.coach_stage === 'explain') parts.push(j.explanation || answerGist);
  else parts.push(j.followup);
  return parts.filter((s) => typeof s === 'string' && s.trim()).map((s) => s.trim()).join(' ');
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
  return n > 0 ? `${n}초 뒤에 보낼게요. 고치려면 자막을 누르세요.` : '보내는 중이에요.';
}

/**
 * 상대 말풍선 목록 — 판정 하나를 통화의 말풍선 몇 개로 나눈다.
 * 화면 카드와 같은 재료(react·summary·missing·followup·explanation)만 쓴다. 판정 색은 pill 로만.
 */
export function judgementBubbles(j, { giveUp = false, answerGist = '' } = {}) {
  if (!j) return [];
  const v = j.verdict || 'unknown';
  const out = [];
  const head = [j.react, j.summary_sentence].filter((s) => typeof s === 'string' && s.trim()).map((s) => s.trim()).join(' ');
  out.push({ kind: 'verdict', verdict: v, text: head });
  const missing = Array.isArray(j.missing_points) ? j.missing_points.filter((m) => typeof m === 'string' && m.trim()) : [];
  if (missing.length) out.push({ kind: 'missing', verdict: v, items: missing });
  if (giveUp || j.coach_stage === 'explain') {
    const ex = (typeof j.explanation === 'string' && j.explanation.trim()) || (answerGist || '').trim();
    if (ex) out.push({ kind: 'explain', verdict: v, text: ex });
  } else if (typeof j.followup === 'string' && j.followup.trim()) {
    out.push({ kind: 'followup', verdict: v, text: j.followup.trim() });
  }
  return out;
}

/**
 * 판정 한 풍선 — 9/23 사용자: "판정 뒤에 말풍선 쌓이는 것도 최근 하나만 남게".
 * judgementBubbles 의 조각(반응+요약 · 빠진 것 · 되묻기/정답 요지)을 버리지 않고 한 풍선에 담는다.
 * 화면은 이 풍선 하나로 앞 풍선(질문·내 답·힌트)을 갈아 끼운다. 판정 색은 pill 로만 — 숫자·판정은 잃지 않는다.
 */
export function judgementBubble(j, opts = {}) {
  const parts = judgementBubbles(j, opts);
  if (!parts.length) return null;
  const head = parts.find((b) => b.kind === 'verdict');
  const missing = parts.find((b) => b.kind === 'missing');
  const tail = parts.find((b) => b.kind === 'followup' || b.kind === 'explain') || null;
  return { verdict: head.verdict, text: head.text, missing: missing ? missing.items : [], tail: tail ? { kind: tail.kind, text: tail.text } : null };
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
