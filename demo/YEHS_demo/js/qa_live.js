/**
 * 실전 질문 코칭(F-08 질문 · F-09 판정) 화면입니다.
 *
 * app.js 에서 떼어냈습니다 — 서버가 만든 질문으로 도는 루프라, 스크립트 기반
 * 데모 코칭(app.js 의 qaBeats 경로)과 성격이 다릅니다.
 *
 * 클래식 스크립트라 전역(qa · nf · app · pushTurn · saveSession …)을 app.js 와 공유합니다.
 * index.html 에서 app.js 보다 먼저 로드되며, 서로의 함수는 호출 시점에 찾으므로
 * 로드 순서가 동작을 바꾸지 않습니다.
 */

/* ── 실전 QA(서버 질문 생성·판정) — 스크립트 모드와 별도의 단순 루프 ── */
const LIVE_VERDICT = {
  good:    { flag: 'won',  react: 'full',    word: '설득 완료' },
  partial: { flag: 'won',  react: 'partial', word: '부분 인정' },
  wrong:   { flag: 'lost', react: 'none',    word: '미방어' },
  unknown: { flag: 'lost', react: 'none',    word: '판정 보류' },
};
/* 등급을 낱말로 부르면 「치명도 치명」처럼 명사가 겹친다 — 한 줄로 말한다 */
const SEVERITY_LINE = { 1: '꼭 넘어야 해요', 2: '보통이에요', 3: '가벼워요' };

/*
 * 마이크 버튼 아이콘.
 *
 * landing.html 의 심볼 스프라이트(#icMic)는 index.html 에 없어서 <use> 가 안 먹는다.
 * 그래서 같은 규격(24px · stroke 2 · round)으로 직접 넣는다 — 렌더가 innerHTML
 * 한 방이라 <use> 를 쓰려고 스프라이트를 따로 심을 이유가 없다.
 */
const IC_ATTRS = 'class="ic-i" viewBox="0 0 24 24" aria-hidden="true"';
const MIC_ICON = `<svg ${IC_ATTRS}><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><path d="M12 19v3"/></svg>`;
const STOP_ICON = `<svg ${IC_ATTRS}><rect x="6" y="6" width="12" height="12" rx="2"/></svg>`;

/**
 * 마이크 버튼의 상태별 아이콘과 이름.
 *
 * 글자를 뺀 아이콘 버튼이라 **label 이 유일한 이름**이다. aria-label 을 빠뜨리면
 * 스크린리더가 그냥 "버튼" 이라고 읽고, title 이 없으면 마우스 사용자도 무슨
 * 버튼인지 알 길이 없다.
 */
const MIC_STATE = {
  idle: { icon: MIC_ICON, label: '말해서 답하기' },
  opening: { icon: MIC_ICON, label: '마이크 여는 중' },
  dictating: { icon: STOP_ICON, label: '그만 말하기' },
  recording: { icon: STOP_ICON, label: '녹음 멈추고 받아쓰기' },
  transcribing: { icon: MIC_ICON, label: '받아쓰는 중' },
};

/**
 * 진행 중인 답변 녹음. **세션에 저장하지 않는다** — MediaRecorder 는 새로고침을
 * 못 넘기므로, 저장하면 다시 연 화면이 「녹음 중」 상태로 굳어 버린다.
 */
let liveMic = null;

/**
 * 마이크가 여닫는 중인가 ('' | 'opening' | 'transcribing').
 *
 * 여는 중(권한 팝업 대기)에는 liveMic 이 아직 null 이고, 받아쓰는 중에는 이미
 * null 이라 `if (liveMic)` 가드가 양쪽 가장자리를 못 막는다 — 그 틈에 제출하면
 * 녹음이 아무도 안 멈추는 채 남거나, 받아쓴 문장이 재렌더에 지워진다.
 */
let liveMicPending = '';

/**
 * 실시간 받아쓰기가 이 세션에서 이미 죽었는가.
 *
 * `hasLiveDictation()` 은 **생성자가 있는지만** 본다. 크롬은 그 생성자를 늘
 * 노출하지만 실제 인식은 구글 서버로 나가므로, 망이 막히면 `onerror('network')`
 * 로 죽는다. 그런데 다음에 마이크를 다시 눌러도 `hasLiveDictation()` 은 여전히
 * true 라 **같은 길로 다시 들어가 똑같이 죽는다** — 부스에서 이게 걸리면 마이크가
 * 통째로 못 쓰게 된다 (2026-08-07 "지금 녹음이 잘 안되는듯" 의 유력한 원인).
 *
 * 한 번 죽으면 이 세션 동안은 녹음 + 서버 STT 로 간다. 새로고침하면 다시 시도한다 —
 * 망이 돌아왔을 수 있는데 영영 막아 둘 이유는 없다.
 */
let liveDictationDead = false;

function qaLiveActive() {
  const L = qa.live;
  if (!L || !Array.isArray(L.questions) || !L.questions.length) return false;
  /* 이 질문들이 지금 올라와 있는 자료의 것인가.
     applySlideDoc 의 resetQa() 가 업로드 경로를 이미 막지만, 그 한 곳만 믿기엔
     #/new 로 들어오는 길이 많다(뒤로가기·주소 직타·리포트 링크). 지문을 질문에
     같이 붙여 두면 어느 길로 들어오든, 새로고침을 하든 같은 판단이 선다.
     옛 세션엔 docKey 가 없다 — 그때는 안 따진다. 없는 값을 낡음으로 치면
     진행 중인 코칭이 새로고침 한 번에 날아간다. */
  const now = typeof qaDocKey === 'function' ? qaDocKey() : '';
  if (L.docKey && now && L.docKey !== now) return false;
  return true;
}

function newLiveState(sessionId, questions, docKey = '') {
  return {
    sessionId,
    questions,
    // 이 질문을 만든 자료의 지문 (app.js qaDocKey). 자료가 바뀌면 낡은 것이 된다.
    docKey,
    qi: 0,
    asked: -1,
    results: [],
    turn: 0,
    turns: [],
    hintLevel: 0,
    // 이 질문에서 지금까지 본 **가장 긴** 힌트 사다리. 판정이 붙여 주는 사다리는
    // 턴마다 길이가 달라서, 그때그때 고르면 분모가 줄어든다 ("힌트 2/4" 다음에
    // "힌트 3/3"). 한 번 4단을 봤으면 그 4단을 질문이 끝날 때까지 들고 간다.
    // 옛 저장 세션엔 없어 undefined 로 복원되는데, liveHints() 가 폴백을 갖고 있다.
    hintList: [],
    // 이 질문에서 「빠진 절반」을 이미 펼쳤는가, 그때 보여준 완성 문장은 무엇인가.
    // 라운드마다 같은 문장을 다시 띄우지 않고, 닫을 때도 겹쳐 내지 않기 위해 둔다.
    // 옛 저장 세션엔 없어서 undefined 로 복원되는데, 그러면 다음 절반 판정에서
    // 한 번 열린다 — 그게 맞는 동작이라 폴백을 따로 두지 않는다.
    halfShown: false,
    halfGist: '',
    lastJudgement: null,
    // 답을 보고 나서 내 말로 다시 해보는 중인가. 「답 보고 다시 말해보기」는 예전엔
    // 질문을 바로 닫았는데, 그러면 답을 읽기만 하고 한 번도 말해 보지 않은 채
    // 넘어간다 — 읽은 것은 다음 질문에서 안 나온다. 보고 나서 한 번 말해야 남는다.
    retell: null,
    // 판정 직후 곧바로 다음 질문으로 넘기지 않는다. 사용자가 자기 답과
    // 완성 답의 차이를 한 화면에서 확인한 뒤 직접 다음으로 간다.
    checkpoint: null,
    // 마지막 질문까지 닫혔지만 아직 결과 화면으로 안 넘어간 상태. 답하자마자
    // 화면이 결과로 갈아치워지면 방금 닫힌 질문의 마무리를 한 글자도 못 읽는다.
    // 사용자가 「결과 확인하기」를 누를 때까지 스트림에 그대로 선다.
    awaitEnd: false,
    busy: false,
    // 직전 판정 요청이 실패했는가. 참이면 서버 없이 넘어갈 출구를 연다.
    judgeFailed: false,
  };
}

/**
 * 이 질문에 **채점된** 답들. 서버가 이 개수로 라운드를 센다 (f09 `_round_no`).
 *
 * 포기 턴의 자리표시자는 답이 아니라 뺀다. 되물음 턴(「질문이 무슨 뜻인가요?」)도
 * 뺀다 — 서버가 채점하지 않은 말인데 여기 남기면 두 가지가 어긋난다.
 * ① 라운드가 한 칸 올라 되묻기가 이유 없이 좁아지고,
 * ② 누적 답변 블록에 「1턴: 질문이 무슨 뜻인가요?」 가 실려 판정이 그걸 답으로 읽는다.
 */
function liveScoredAnswers() {
  return ((qa.live || {}).turns || [])
    .filter((t) => !t.gaveUp && !t.clarify)
    .map((t) => t.answer);
}

/**
 * 판정에 실어 보낼 대화 — **지금 질문의 턴만** 보낸다.
 *
 * 예전엔 끝난 질문의 Q/A 까지 실어 보내, 판정 react 가 다른 질문의 문장으로 답했다
 * (09-30 대화 감사 §10: 「…비교 근거는 어디서 가져왔나요?」 가 다음 질문의 react 로 나왔다).
 * 서버가 이 대화로 세는 것(코칭 단계·되물음 뒤 답)은 전부 이 질문 안의 일이다.
 */
function liveHistory() {
  const L = qa.live;
  const q = L.questions[L.qi];
  // 「모르겠어요」는 **의사**라 답변 글에서 역추정할 수 없다. 서버가 코칭 단계를
  // 정할 때 쓰므로(narrow → explain) 플래그를 그대로 실어 보낸다.
  const current = (L.turns || []).map((t) => ({
    질문: t.question || (q && q.question) || '',
    답변: t.answer,
    판정: t.verdict,
    포기: !!t.gaveUp,
    // 조인 키. 문면은 2턴째부터 되물음이 들어가 원래 질문과 달라지므로,
    // 서버(_coach_stage)가 이 id 로 "같은 질문에 몇 번 막혔는지" 를 센다.
    question_id: t.questionId || (q && q.id) || '',
  }));
  return current;
}

/** 판정에 실어 보낼 자료 근거. 없으면 판정이 "자료와 어긋난다"를 대조할 원본을 잃는다. */
function liveArtifacts() {
  // nf 는 app.js 의 전역이다. 새로고침한 직후나 QA 화면으로 바로 들어온 경우엔
  // 아직 안 채워져 있을 수 있는데, 그때 null 을 돌려주면 judgeQaAnswer 의 409
  // 자가 복구(세션 재등록)가 아예 안 돌아 이 질문에 영영 갇힌다.
  // 2026-08-07 실측: 브리지를 재시작한 뒤 모든 답변이 409 로 죽었고, 재등록
  // 요청은 로그에 한 번도 안 찍혔다. 세션에 남겨 둔 요약에서 한 번 더 찾는다.
  const src = (nf && nf.pipelineOut) ? nf : (loadSession('new-flow') || {});
  const out = src.pipelineOut || null;
  if (!out || !out.graph) return null;
  return {
    graph: out.graph,
    alignment: out.alignment || null,
    flow: out.flow || null,
    transcript: out.transcript || null,
    context: { situation: src.occ || '', audience: src.ctx || '', duration_min: src.min },
  };
}

/**
 * 막혔을 때 「답 보고 다시 말해보기」 를 연다.
 *
 * 예전 조건은 `hintLevel < 3` 이었는데 사다리가 실제로 3단계까지 온 적이 없어
 * 이 버튼이 한 번도 뜨지 않았다. 3단계(근접)는 빠뜨린 게 없으면 서버가 아예
 * 안 만든다 — 고정 숫자가 아니라 **남은 힌트가 있느냐**로 재야 맞는다.
 */
function liveStalled() {
  const L = qa.live;
  // 판정이 실패하면 이 질문을 넘길 길이 서버 말고는 없다. 「모르겠어요」도
  // 판정을 타므로, 여기서 안 열어 주면 사용자는 코칭 전체를 끝내는 수밖에 없다.
  if (L.judgeFailed) return true;
  // 답을 보고 다시 말하는 중에는 출구를 또 열지 않는다 — 그게 이미 출구다.
  if (L.retell) return false;
  if (L.turns.length < 2) return false;
  // 예전엔 셋을 **모두** 만족해야 열렸다 (2턴 이상 · 사다리 소진 · 점수 정체).
  // 그래서 힌트를 안 누른 사람에게는 영영 안 떴다 — 정작 막힌 사람이 힌트를
  // 안 누르는 사람인데. 이제 하나만 걸려도 연다. 출구는 넉넉해야 안심하고 문다.
  if (L.hintLevel >= liveQuestionHints().length) return true;
  const last = L.turns[L.turns.length - 1];
  const prev = L.turns[L.turns.length - 2];
  return (last.score || 0) <= (prev.score || 0);
}

/* ── 라운드 사다리 ──────────────────────────────────────────────────────────
   서버가 라운드마다 질문의 넓이를 좁힌다 (probe → focus → converge).
   화면도 그걸 그대로 보여 준다 — 「또 물어보네」와 「한 칸 좁아졌네」는
   같은 사건인데 표시가 없으면 전자로만 읽힌다.

   칸이 셋인 것은 서버 QA_PROBE_TIERS 가 셋이기 때문이지 라운드 상한이 셋이라서가
   아니다 (converge 는 3라운드 이상 전부). 상한을 여기 베껴 두면 서버가 바뀔 때
   조용히 어긋나므로, **서버가 보내는 단계 이름만 읽는다.** */
const PROBE_STEPS = [
  { key: 'probe', title: '내 말로 답해요', note: '아는 만큼만 말해도 돼요' },
  { key: 'focus', title: '좁혀서 다시 물어요', note: '한 단어로 답해도 돼요' },
  { key: 'converge', title: '마지막 한 걸음', note: '고개만 끄덕이면 돼요' },
];

/** 지금 서 있는 라운드 칸. 판정 전에는 첫 칸이다. */
function liveProbeIndex() {
  const tier = (qa.live.lastJudgement && qa.live.lastJudgement.probe_tier) || '';
  const at = PROBE_STEPS.findIndex((s) => s.key === tier);
  return at < 0 ? 0 : at;
}

/**
 * 연속으로 정복한 개념 수. **도파민은 진짜 숫자에서 온다** — XP 를 지어내지 않는다
 * (UI_REDESIGN §14 「숫자는 신성하다」). 답을 보고 넘어간 것은 연속을 끊는다.
 */
function liveStreak() {
  const rs = qa.live.results || [];
  let n = 0;
  // 스스로 설명한 것만 잇는다 — 힌트 셋째 칸·코칭·3라운드 출구로 닫힌 것도 연속을 끊는다 (09-30 C-09, liveBucket)
  for (let i = rs.length - 1; i >= 0; i--) {
    if (liveBucket(rs[i]) !== 'self') break;
    n += 1;
  }
  return n;
}

/**
 * 「모르겠어요」 버튼의 라벨.
 *
 * 예전엔 「모르겠어요」와 「이 질문 넘기기」가 따로 있었다. 그런데 두 번째로
 * 모르겠다고 하면 서버가 explain 단계로 올라가 답을 풀어 주고 질문을 닫는다
 * (f09_judge `_coach_stage`) — 그게 곧 넘어가기다. 버튼을 둘로 두면 코칭을
 * 건너뛰는 길만 하나 더 생길 뿐이라 하나로 합치고, 라벨로 다음에 무슨 일이
 * 벌어질지 미리 알린다.
 */
function stuckLabelFor(gaveUpCount) {
  // 서버 사다리(f09 _coach_stage)와 같은 셈: 0 → 위치, 1 → 발판(빈칸), 2+ → 해설.
  // CTA 문구만 보고 다음에 무슨 일이 벌어질지 예측돼야 한다 (CLAUDE.md §3-1).
  if (gaveUpCount >= 2) return '그래도 모르겠어요 · 답 보기';
  if (gaveUpCount === 1) return '그래도 모르겠어요 · 빈칸으로';
  return '모르겠어요';
}

function stuckLabel() {
  const L = qa.live;
  return stuckLabelFor((L.turns || []).filter((t) => t.gaveUp).length);
}

/** 코치 턴·되물음의 머리말. 「지금 몇 단째, 무엇을 하는지」 를 적는다. */
function coachMeta(stage) {
  return {
    narrow: '막힘 1/3 · 자료에서 같이 찾아요',
    scaffold: '막힘 2/3 · 빈칸을 채워요',
    explain: '막힘 3/3 · 답을 같이 풀어요',
    clarify: '질문을 다시 풀었어요',
  }[stage] || '더 쉬운 걸로 바꿔 물을게요';
}

/**
 * 코치 react 에서 자료 인용을 뗀다. 서버가 1단 react 뒤에 "자료 N장은 이렇게
 * 말해요: «…»" 를 붙여 보내는데(글로만 보는 클라이언트용), 이 화면은 같은 인용을
 * 카드로 그리므로 두 번 보이면 안 된다.
 */
function coachReactText(react, quote) {
  const text = String(react || '');
  if (!quote || !text.includes('«')) return text;
  const at = text.search(/\s자료(?:\s\d+장)?[은는]\s이렇게 말해요/);
  return at > 0 ? text.slice(0, at).trim() : text;
}

/* ── 개념 퀘스트 (왼쪽 칸) ──────────────────────────────────────────────────
   질문 하나 = 개념 하나다 (F-08 규칙 2: "대상마다 정확히 하나씩"). 그래서 질문
   목록을 그대로 세우면 «오늘 채워야 할 개념 목록»이 된다. 지나온 것·지금 것·
   남은 것이 한눈에 보여야 대화가 길어져도 어디쯤인지 안 잃는다.

   판정 낱말은 새로 짓지 않는다. 바로 오른쪽 스트림이 `${label} — 설득 완료` 라고
   말하는데 여기서 «정복» 이라고 부르면 한 화면에서 같은 일이 두 이름이 된다.
   게임 느낌은 낱말이 아니라 **줄 세우기·현재 표식·남은 줄 흐리기**로 낸다. */
const QUEST_WORD = {
  won: '스스로 설명했어요',
  /* 힌트 셋째 칸·보기·빈칸·3라운드 출구로 닫힌 것 (liveBucket helped) — 「절반만 설득」 이 아니라 도움을 받았다는 사실을 말한다 */
  part: '도움 받아 닫았어요',
  retold: '답 보고 다시 말했어요',
  /* 「미방어」는 한자어에 부정형이다. 지나간 일을 이름 붙이는 대신
     지금 할 수 있는 일로 말한다 (토스 UX 라이팅 §3 긍정적 말하기) */
  lost: '다시 설명해요',
  skip: '넘겼어요',
  now: '지금 답하고 있어요',
  next: '곧 물어봐요',
};
const QUEST_MARK = { won: '✓', part: '✓', retold: '↺', lost: '✕', skip: '—', now: '▶', next: '' };

/** 질문 하나의 지금 상태. results 는 닫힌 순서대로 쌓이지만 id 로 맞춘다. */
function questState(q, i) {
  const L = qa.live;
  if (i > L.qi) return 'next';
  if (i === L.qi) return 'now';
  const byId = q.id != null && (L.results || []).find((r) => r.id === q.id);
  const r = byId || (L.results || [])[i] || {};
  // 결과 화면과 같은 네 묶음으로 읽는다 (liveBucket) — 목록 표식과 결과 숫자가 같은 것을 세야 한다
  return { self: 'won', helped: 'part', retold: 'retold', skipped: 'skip' }[liveBucket(r)] || 'skip';
}

/**
 * 개념 그래프의 위계를 목록에 입힌다.
 *
 * 계산하지 않는다 — `parent_id` 는 f07 이 parent 간선에서 파생해 실어 주는
 * 값이다 (contracts.py "화면이 트리로 그릴 때 쓰라고 실어 준다").
 *
 * **절대 depth 로 들여쓰지 않는다.** 처음엔 그렇게 했는데 화면에서 아무 구조도
 * 안 보였다 (2026-08-09 사용자). 이 목록에는 **질문이 붙은 개념만** 들어간다 —
 * 실측에서 개념 17개 중 3개다. 그 셋이 같은 깊이면 다 같이 밀려서 평평한 것과
 * 구별이 안 되고, 부모가 목록에 없으면 «무엇 아래로» 들여쓴 건지도 알 수 없다.
 * 그래서 부모가 이 목록에 실제로 있을 때만 들여쓰고, 없으면 부모 이름을 글자로
 * 말한다. 그게 평평한 목록이 못 가진 정보이면서 걸러내도 살아남는 정보다.
 *
 * relates 는 **지금 묻고 있는 개념의 것만** 표시한다. 전부 그리면 실측 최대
 * 112개 선이 겹쳐 아무것도 안 읽힌다.
 *
 * 분석 결과가 없는 세션(샘플·새로고침 직후)에서는 빈 표를 돌려준다 —
 * 그러면 목록이 지금까지처럼 평평하게 나오고, 없는 구조를 지어내지 않는다.
 */
function liveConceptTree() {
  const art = liveArtifacts();
  const g = art && art.graph;
  if (!g || !Array.isArray(g.nodes)) return { parentOf: {}, labelOf: {}, kin: new Set() };
  const parentOf = {};
  const labelOf = {};
  g.nodes.forEach((n) => {
    if (!n || !n.id) return;
    parentOf[n.id] = n.parent_id || null;
    labelOf[n.id] = n.label || '';
  });
  const cur = ((qa.live.questions || [])[qa.live.qi] || {}).node_id;
  const kin = new Set();
  if (cur) {
    (g.edges || []).forEach((e) => {
      if (!e || e.kind !== 'relates') return;
      if (e.from === cur) kin.add(e.to);
      else if (e.to === cur) kin.add(e.from);
    });
  }
  return { parentOf, labelOf, kin };
}

function liveQuestHtml() {
  const L = qa.live;
  const total = L.questions.length;
  const won = liveWonCount(L.results);
  const streak = liveStreak();
  /* 막대는 «설득한 수» 로 잰다 — 머리줄 숫자와 같은 것을 재야 한다.
     지나온 질문 수로 재면 2/5 라고 써 놓고 막대는 60% 인 화면이 된다.
     어디까지 왔는지는 목록의 «지금» 표식과 흐린 줄이 이미 말한다. */
  const prog = Math.round(won / Math.max(1, total) * 100);
  return `<div class="quest">
      <div class="quest-head">
        <span class="quest-title">오늘 설득할 개념</span>
        <b class="quest-count num">${won}<i>/${total}</i></b>
      </div>
      <div class="quest-bar" style="--p:${prog}%" role="progressbar"
           aria-valuenow="${won}" aria-valuemin="0" aria-valuemax="${total}"
           aria-label="설득한 개념"><i></i></div>
      ${streak >= 2 ? `<p class="quest-streak"><b>${streak}개 연속</b>으로 스스로 설명했어요</p>` : ''}
      <ol class="quest-list">
        ${(() => {
          const tree = liveConceptTree();
          /* 이 목록에 실제로 서 있는 개념들. 부모가 여기 있어야 들여쓰기가 뜻을 가진다. */
          const listed = new Set(L.questions.map((x) => x.node_id).filter(Boolean));
          return L.questions.map((q, i) => {
          const st = questState(q, i);
          /* 순서는 질문 순서 그대로 둔다. 트리 순으로 다시 세우면 「지금」 표식이
             위아래로 튀어서 어디까지 왔는지가 안 읽힌다 — 세로축은 진행이다. */
          const pid = tree.parentOf[q.node_id] || null;
          const d = pid && listed.has(pid) ? 1 : 0;
          // 부모가 목록 밖이면 이름으로 말한다 — 「무엇 아래 개념인지」는 평평한
          // 목록이 못 가진 정보이고, 질문이 걸러져도 그 사실은 그대로 남는다.
          const upper = (!d && pid && tree.labelOf[pid])
            ? `<em class="qrow-up">${escapeHtml(tree.labelOf[pid])} 아래</em>` : '';
          const kin = tree.kin.has(q.node_id) ? ' is-kin' : '';
          const label = q.label || `질문 ${i + 1}`;
          const sev = SEVERITY_LINE[q.severity] || '';
          /* 「힌트 없이」는 지어낸 배지가 아니라 우리가 이미 기록하는 사실이다
             (results[].hintLevel). 없는 것을 상으로 주지 않는다 */
          const r = (L.results || []).find((x) => x.id === q.id) || {};
          const clean = st === 'won' && !liveHintsUsed(r) ? '<em class="qrow-clean">힌트 없이</em>' : '';
          return `<li class="qrow is-${st}${kin}" data-d="${d}" style="--d:${d}"${st === 'now' ? ' aria-current="step"' : ''}>
            <i class="qrow-mark" aria-hidden="true">${QUEST_MARK[st] || i + 1}</i>
            <span class="qrow-body">
              ${upper}
              <b>${escapeHtml(label)}</b>
              <small>${st === 'next' && sev ? sev : QUEST_WORD[st]}${clean}</small>
            </span>
          </li>`;
        }).join(''); })()}
      </ol>
    </div>`;
}

/* 사용자 피드백 버튼 (학습 동의 세션에만). app.js 의 fbButtonsHtml 이 동의·중복을 거른다 —
   하네스(qa_live.smoke)에는 그 전역이 없으니 없으면 조용히 빈 문자열이다. */
function liveFeedbackHtml(kind, target, buttons, payload) {
  if (typeof fbButtonsHtml !== 'function') return '';
  try { return fbButtonsHtml(kind, target, buttons, payload); } catch (_) { return ''; }
}

/* 논문을 근거로 든 질문은 그 논문으로 바로 갈 수 있어야 한다 (2026-09-29 사용자).
   「Paulsrud et al. (2026)는 …라고 봤는데」 만 보고는 그 논문이 정말 그렇게 말했는지 확인할 길이
   없었다 — 검색 문헌 요지를 LLM 이 한 절로 줄이다 보니 초록에 없는 주장이 붙기도 한다.
   F-08 QuestionDoc 은 이미 인용한 문헌(papers, url·doi)과 질문별 paper_ids 를 준다. 화면만 버리고 있었다. */

/** 문헌 링크 주소. http(s) 만 받는다 — 검색 API 가 준 값이라 javascript: 같은 것을 거른다. 없으면 DOI 로 */
function paperHref(ref) {
  const url = String((ref && ref.url) || '').trim();
  if (/^https?:\/\//i.test(url)) return url;
  const doi = String((ref && ref.doi) || '').trim().replace(/^https?:\/\/(dx\.)?doi\.org\//i, '');
  return /^10\.\d{4,}\/\S+$/.test(doi) ? `https://doi.org/${doi}` : '';
}

/** 질문마다 인용한 문헌(링크 재료만)을 붙인 새 배열. 세션에 저장되므로 질문 문서의 papers 를 따로 안 들고 다닌다 */
function attachQuestionPapers(questions, papers) {
  const byId = new Map((papers || []).map((r) => [String(r.id), r]));
  return (questions || []).map((q) => {
    const refs = (q.paper_ids || []).map((id) => byId.get(String(id))).filter(Boolean)
      .map((r) => ({ id: String(r.id), cite_key: r.cite_key || '', title: r.title || '', href: paperHref(r) }))
      .filter((r) => r.href);
    return refs.length ? { ...q, papers: refs } : q;
  });
}

function paperAnchor(ref, label) {
  return `<a class="msg-paper-link" href="${escapeHtml(ref.href)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(ref.title || ref.cite_key)}">${label}</a>`;
}

/** 질문 문장 속 「저자 (연도)」 에 링크를 건다. 이스케이프한 뒤에 감싸므로 질문 본문이 HTML 로 새지 않는다 */
function linkCitedText(text, refs) {
  let html = escapeHtml(text);
  (refs || []).forEach((ref) => {
    const key = escapeHtml(ref.cite_key);
    if (key && html.includes(key)) html = html.replace(key, paperAnchor(ref, key));
  });
  return html;
}

/** 질문 말풍선 아래 「근거 논문」 줄 — 문장 속 링크를 못 보고 지나쳐도 제목으로 찾아갈 수 있게 */
function questionPapersHtml(refs) {
  if (!(refs || []).length) return '';
  return `<span class="msg-papers">근거 논문 ${refs.map((r) =>
    paperAnchor(r, `${escapeHtml(r.cite_key)}${r.title ? ` · ${escapeHtml(r.title)}` : ''} ↗`)).join(' · ')}</span>`;
}

/* 「이 질문의 근거」 (P1, 2026-09-29) — 사용자가 "이 질문은 어떤 근거로 나왔는지" 물었는데 답할 곳이 없었다.
   F-08 이 질문마다 basis(배합 자리·근거·탐침·자료 인용)를 남긴다. 화면은 그걸 사람 말로만 옮긴다 —
   영문 id(tension·weak…)는 보이지 않는다. 옛 세션 질문은 basis 가 없어 이 줄이 안 생긴다. */
const QA_ORIGIN_SLOT = { theme: '발표 주제', part: '주제를 이루는 요소', weak: '더 짚어 볼 곳' };
/** 탐침(자료 안에서 코드가 찾은 것) — 「자료 N장에서 …」 로 이어 읽힌다 */
const QA_ORIGIN_PROBE = {
  tension: '서로 부딪히는 표현',
  unsolved: '해결책이 빠진 요소',
  unsupported_cause: '근거 없이 말한 원인과 결과',
  absolute_boundary: '단정적으로 말한 대목',
  sibling_priority: '나란히 둔 요소 사이의 우선순위',
};
const QA_ORIGIN_SOURCE = {
  contradiction: '발표에서 자료와 다르게 말한 곳',
  // WP-S2: 발표자가 말로 건너뛴 핵심 장(「시간 관계상 넘어갈게요」)의 개념 — 없으면 근거 줄에 자리(slot)만 남았다
  skipped_slide: '발표에서 말로 건너뛴 장',
  missing: '자료에 있는데 발표에서 말하지 않은 개념',
  under_spoken: '발표에서 짧게 지나간 개념',
  weak_flow: '다른 개념과의 연결이 드러나지 않은 곳',
  extra: '발표에서 새로 꺼낸 개념',
  core_weight: '자료가 크게 다룬 개념',
  justified_skip: '생략해도 괜찮았던 개념',
};

/** 「발표 주제 · 자료 1·4장에서 서로 부딪히는 표현」. basis 가 없거나 모르는 근거면 빈 문자열 */
function questionOriginLine(basis) {
  if (!basis || typeof basis !== 'object') return '';
  const kind = basis.probe && basis.probe.kind;
  let what = '';
  if (kind && QA_ORIGIN_PROBE[kind]) {
    const nos = [...new Set(((basis.probe.evidence) || []).map((e) => Number(e.slide_no)).filter((n) => n > 0))].sort((a, b) => a - b);
    what = `${nos.length ? `자료 ${nos.join('·')}장에서 ` : '자료에서 '}${QA_ORIGIN_PROBE[kind]}`;
  } else {
    what = QA_ORIGIN_SOURCE[basis.source] || '';
  }
  return [QA_ORIGIN_SLOT[basis.slot] || '', what].filter(Boolean).join(' · ');
}

/**
 * 질문 말풍선 아래 접힌 「이 질문의 근거」 — 한 줄 설명 + 근거 장 번호.
 *
 * **자료 원문 인용은 싣지 않는다** (09-30 held-out C-03). 이 칸은 질문을 띄울 때(아직 답하기 전) 한 번 그려진다 —
 * 함정은 근거 인용이 곧 바로잡은 사실 줄이라 정답이 질문 바로 아래 펼쳐져 있었고(함정 15개 중 13개), 다른 질문도
 * 인용이 답을 흘린다. 어디를 보면 되는지(장 번호)까지만 말한다. 풀이는 닫힌 뒤·「모르겠어요」 해설 단계에서 따로 보인다.
 */
function questionOriginHtml(q) {
  const basis = q && q.basis;
  const line = questionOriginLine(basis);
  if (!line) return '';
  // 탐침 줄은 이미 「자료 1·4장에서 …」 로 장을 말한다 — 그 밖의 근거만 장 번호 줄을 따로 붙인다
  const probeSaysSlides = !!(basis.probe && QA_ORIGIN_PROBE[basis.probe.kind]);
  const nos = [...new Set((basis.evidence || []).map((e) => Number(e && e.slide_no)).filter((n) => n > 0))].sort((a, b) => a - b);
  const slides = !probeSaysSlides && nos.length ? `<p class="msg-origin-slides">근거 자료 ${nos.join('·')}장</p>` : '';
  return `<details class="msg-origin"><summary>이 질문의 근거</summary><p>${escapeHtml(line)}</p>${slides}</details>`;
}

function presentLiveQuestion() {
  const L = qa.live;
  if (L.asked === L.qi) return;
  L.asked = L.qi;
  const q = L.questions[L.qi];
  // 질문 묶음이 폴백 재료로 만들어졌으면(문헌 검색·주장 없이) 첫 질문 앞에 한 번 짧게 말한다 (09-30 WP-B degraded_notes)
  if (L.qi === 0 && Array.isArray(L.notes) && L.notes.length) {
    pushTurn({ who: 'sys', kind: 'note', text: escapeHtml(L.notes.join(' ')) });
  }
  const why = liveQuestionWhy(q);
  pushTurn({
    who: 'ai',
    // 함정도 다른 질문과 같은 말풍선이다 — 예전 'claim'(주황 테두리)은 그 자체로 함정임을 알려 줬다 (09-30 B-01·H-07)
    kind: 'question',
    meta: `예상 질문 ${L.qi + 1}/${L.questions.length} · ${SEVERITY_LINE[q.severity] || '보통이에요'}`,
    text: linkCitedText(q.question, q.papers),
    papers: questionPapersHtml(q.papers),
    basis: why ? escapeHtml(why) : '',
    origin: questionOriginHtml(q),
    // 👍/👎 — 「이 자료에서 나올 만한 질문이었나」. 이것이 질문 생성의 라벨이다.
    fb: liveFeedbackHtml('question_vote', String(q.id), [['up', '👍 좋은 질문이에요'], ['down', '👎 이 질문은 별로예요']],
      { question: q.question, node_id: q.node_id, slide_nos: q.slide_nos || [], trap: !!q.trap, source: q.source || '' }),
  });
}

function renderQaLive() {
  const L = qa.live;
  if (qa.ended) return qaLiveEnd();
  // 마지막 질문까지 닫혔으면 결과로 바로 넘기지 않고 마무리 자리에 선다.
  // 새로고침으로 돌아와도 같은 자리다 — 여기서 결과로 튀면 읽던 것이 날아간다.
  if (L.qi >= L.questions.length) markLiveFinale();
  // 체크포인트(전체 화면 학습 카드)는 걷어냈다 — 대화 스트림이 유지된다.
  // 이 변경 전에 저장된 세션이 checkpoint 를 들고 있으면 기록만 닫고 이어간다.
  if (L.checkpoint) return completeLiveCheckpoint();
  qa.started = true;
  if (!L.awaitEnd) presentLiveQuestion();
  saveSession('qa-flow', qa);
  if (typeof callFlowOn === 'function' && callFlowOn()) return renderQaLiveCall();
  app.innerHTML = `
    <div class="coach-nav"><a href="#/">← 저장하고 나가기</a><span>자동으로 저장하고 있어요</span></div>
    <div class="qa-shell">
      <aside class="qa-context" id="qaContext">${liveContextHtml()}</aside>
      <section class="qa-dialog">
        <div class="qa-stream" id="stream">${qa.turns.map(streamRow).join('')}</div>
        <div class="card qa-live-input">${liveInputHtml()}</div>
      </section>
    </div>`;
  scrollDown();
  wireLiveInput();
  if (typeof wireFeedback === 'function') wireFeedback(app);
}

/** 왼쪽 칸 — 퀘스트 목록 + 지금 라운드. 판정 뒤 이것만 갈아 끼운다. */
function liveContextHtml() {
  const L = qa.live;
  const q = L.questions[L.qi];
  // 마무리 자리에는 진행 중인 질문이 없다. 되묻기 단계 칸은 지금 답할 질문을
  // 비추는 것이라 다 끝난 화면에 남아 있으면 아직 할 일이 있는 것처럼 읽힌다.
  if (!q) return liveQuestHtml();
  const at = liveProbeIndex();
  return `${liveQuestHtml()}
    <div class="qa-loop-card">
      <h2>이번엔 <b>${escapeHtml(q.label || `질문 ${L.qi + 1}`)}</b>${josaEulReul(q.label || '질문')} 설명해요</h2>
      <!-- 예전 3단계는 「질문을 읽어요 → 힌트를 봐요 → 내 말로 답해요」 라는
           고정 안내였다. 세 칸이 늘 같은 말을 해서 두 번째 질문부터는 아무도
           안 봤다. 이제 **서버가 좁혀 온 라운드**를 그대로 비춘다 — 되물음이
           올 때마다 칸이 하나씩 차서, 「또 물어보네」가 「한 칸 좁아졌네」로 읽힌다. -->
      <div class="qa-loop-steps" aria-label="되묻기 단계">
        ${PROBE_STEPS.map((s, i) => `
          <div class="${i <= at ? 'on' : ''}${i === at ? ' at' : ''}">
            <i>${i < at ? '✓' : i + 1}</i>
            <span><b>${s.title}</b><small>${s.note}</small></span>
          </div>`).join('')}
      </div>
    </div>`;
}

/**
 * 입력 카드 속. 답을 보고 다시 말하는 중이면 **다른 카드가 된다** —
 * 같은 자리에 같은 문구를 두면 방금 답을 본 사람이 무엇을 해야 하는지 모른다.
 *
 * 버튼은 **두 줄**이다. 주 행동(답 보내기 · 마이크)만 첫 줄에 두고, 나머지
 * (모르겠어요 · 힌트 · 답 보기 · 여기까지)는 보조 줄로 내린다. 한 줄에 여섯이
 * 서면 주인공이 사라진다 (MVP_SPEC §3).
 *
 * **보조 줄에도 `step-actions` 를 남겨 둔다.** 판정 중 잠금이
 * `.qa-live-input .step-actions button` 으로 걸려서(`setLiveBusy`), 클래스를
 * 떼면 판정을 기다리는 동안 「모르겠어요」·힌트가 계속 눌린다.
 */
function liveInputHtml() {
  const L = qa.live;
  if (L.awaitEnd) return liveEndCardHtml();
  if (L.retell) {
    return `
      <div class="qa-input-label is-retell">
        <b>이제 내 말로 다시 해볼까요</b><span>답을 그대로 옮기지 않아도 돼요 — 기억나는 만큼만</span>
      </div>
      <textarea id="liveAnswer" rows="3" placeholder="예: 핵심은 …이고, 그래서 …이에요"></textarea>
      <div class="step-actions">
        <button class="btn btn-primary" id="liveSend" type="button">내 말로 말했어요</button>
        ${micBtnHTML(false)}
      </div>
      <div class="step-actions step-actions-sub">
        <button class="btn btn-text" id="liveSkipRetell" type="button">이건 건너뛰고 다음 질문</button>
        <button class="btn btn-text qa-exit-action" id="liveFinish" type="button">여기까지 하고 저장</button>
      </div>`;
  }
  const hints = liveHints();
  return `
    <div class="qa-input-label"><b>내 말로 답해보세요</b><span>한 문장만 말해도 괜찮아요</span></div>
    <textarea id="liveAnswer" rows="3" ${L.busy ? 'disabled' : ''}
      placeholder="예: 이 방법의 핵심은 …이에요"></textarea>
    <div class="step-actions">
      <button class="btn btn-primary" id="liveSend" type="button" ${L.busy ? 'disabled' : ''}>${liveSendLabel()}</button>
      ${micBtnHTML(L.busy)}
    </div>
    <div class="step-actions step-actions-sub">
      <button class="btn btn-text" id="liveStuck" type="button" ${L.busy ? 'disabled' : ''}>${stuckLabel()}</button>
      ${hints.length > L.hintLevel ? `<button class="btn btn-text" id="liveHint" type="button" ${L.busy ? 'disabled' : ''}>힌트 ${L.hintLevel + 1}단계 보기</button>` : ''}
      ${liveStalled() ? `<button class="btn btn-text" id="liveReveal" type="button" ${L.busy ? 'disabled' : ''}>답 보고 다시 말해보기</button>` : ''}
      <button class="btn btn-text qa-exit-action" id="liveFinish" type="button" ${L.busy ? 'disabled' : ''}>여기까지 하고 저장</button>
    </div>`;
}

/**
 * 질문이 다 끝난 자리의 입력 카드. **답 쓰는 칸을 없앤다** — 더 받을 답이
 * 없는데 빈 칸이 남아 있으면 아직 뭔가 해야 하는 화면으로 읽힌다.
 *
 * 버튼은 하나만 둔다. 여기서 리포트로 바로 가는 길을 같이 열면 기록을 닫는
 * 경로가 둘이 되고, 한쪽으로 나가면 코칭 기록이 안 남는다. 결과 화면에
 * 「상세 리포트 보기」가 이미 있으니 거기서 고르면 된다 (한 화면에 주인공 하나).
 */
function liveEndCardHtml() {
  const L = qa.live;
  const won = liveWonCount(L.results);
  return `
    <div class="qa-input-label is-end">
      <b>오늘 질문은 여기까지예요</b>
      <span>${L.questions.length}개 중 ${won}개를 스스로 설명했어요</span>
    </div>
    <p class="qa-end-note">위로 올리면 방금 주고받은 내용을 다시 볼 수 있어요. 다 봤으면 결과를 확인해요.</p>
    <div class="step-actions">
      <button class="btn btn-primary" id="liveSeeResult" type="button">결과 확인하기</button>
    </div>`;
}

function liveSendLabel() {
  const L = qa.live;
  if (L.busy) return '답변 살펴보는 중…';
  return L.turn ? '보완해서 다시 답하기' : '이 답변 확인하기';
}

/** 입력 카드의 버튼·단축키를 다시 묶는다. innerHTML 을 갈아 끼울 때마다 부른다. */
function wireLiveInput() {
  const L = qa.live;
  const on = (sel, fn) => { const el = $(sel); if (el) el.addEventListener('click', fn); };
  installChoiceDelegate();
  on('#liveSend', () => submitLiveAnswer());
  on('#liveMic', () => toggleLiveMic());
  on('#liveStuck', () => submitLiveAnswer({ giveUp: true }));
  on('#liveReveal', () => revealLiveAnswer());
  on('#liveSkipRetell', () => closeRetell(''));
  on('#liveFinish', () => finishLiveQaEarly());
  on('#liveSeeResult', () => { qaLiveEnd(); window.scrollTo(0, 0); });
  // 힌트는 말풍선으로 붙고(growStream), 버튼은 남은 칸 수에 맞춰 다시 그려진다
  on('#liveHint', () => { if (openNextHint()) { growStream(); refreshLiveChrome(); } });

  const ta = $('#liveAnswer');
  if (!ta) return;
  // 판정 대기 중 새로고침으로 걷어 둔 답(초안)이 있으면 되살린다 (app.js 복원 블록).
  if (L.pendingAnswer) {
    ta.value = L.pendingAnswer;
    delete L.pendingAnswer;
    saveSession('qa-flow', qa);
  }
  ta.focus();
  ta.selectionStart = ta.selectionEnd = ta.value.length;
  ta.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    if (e.metaKey || e.ctrlKey) { e.preventDefault(); submitLiveAnswer(); return; }
    if (e.shiftKey) return;
    if (e.isComposing || e.keyCode === 229) return;
    e.preventDefault();
    submitLiveAnswer();
  });
}

/** 힌트에 보여줄 슬라이드 최대 장수. 넷을 넘기면 말풍선이 자료 뷰어가 된다. */
const HINT_SLIDE_SHOW_MAX = 3;

/**
 * 힌트 문장이 부르는 장 번호. "27, 28장에서 …" · "27, 28장 외 3장에 …" 를 읽는다.
 *
 * 서버가 장 번호를 따로 안 실어 준다. 사다리 어느 칸이 장을 부르는지도 질문마다
 * 달라서(폴백 힌트도 장을 부른다) 칸 번호로 재면 어긋난다 — **문장이 실제로 부른
 * 번호**를 읽는 게 어긋날 여지가 없다. 못 읽으면 그림 없이 글자만 남는다.
 *
 * 진짜 렌더가 있는 장만 남긴다 — 회색 자리표시자를 띄우면 "27장을 떠올려 보세요"
 * 를 빈 사각형으로 다시 내는 꼴이다 (app.js hasRealSlideImage).
 */
function hintSlideNos(text) {
  const m = String(text || '').match(/(\d+(?:\s*,\s*\d+)*)\s*장/);
  if (!m) return [];
  return m[1].split(',')
    .map((s) => Number(s.trim()))
    .filter((n) => n > 0 && (typeof hasRealSlideImage !== 'function' || hasRealSlideImage(n)))
    .slice(0, HINT_SLIDE_SHOW_MAX);
}

/**
 * 선택 칩 클릭을 문서에서 한 번만 받는다. 스트림은 말풍선마다 innerHTML 을 갈아
 * 끼우므로(growStream) 칩마다 묶으면 새 칩은 못 받는다. 누르면 답칸에 넣고 커서를
 * 준다 — 바로 보내지 않는다. 고쳐 쓸 여지가 있어야 「선택」이지 「버튼」이 아니다.
 */
function installChoiceDelegate() {
  if (typeof document === 'undefined' || document.__qaChoiceDelegate) return;
  document.__qaChoiceDelegate = true;
  document.addEventListener('click', (e) => {
    const chip = e.target && e.target.closest ? e.target.closest('.qa-choice-chip') : null;
    if (!chip) return;
    const ta = $('#liveAnswer');
    if (!ta || ta.disabled) return;
    ta.value = chip.textContent.trim();
    ta.focus();
    ta.selectionStart = ta.selectionEnd = ta.value.length;
  });
}

/** 힌트 한 칸 열기. 사용자가 눌러도, 라운드가 올라 자동으로 열려도 여기로 온다. */
function openNextHint({ auto = false } = {}) {
  const L = qa.live;
  const list = liveHints();
  if (L.hintLevel >= list.length) return false;
  L.hintLevel += 1;
  // 라운드가 올라 저절로 연 칸은 따로 센다 — 결과의 「힌트 N번 봤어요」 는 사용자가 누른 것만이다 (09-30 L-05)
  if (auto) L.hintAuto = (L.hintAuto || 0) + 1;
  const text = list[L.hintLevel - 1];
  // 보여 준 글을 그대로 남긴다 — 판정 뒤 사다리가 갈아 끼워져도(넷째 칸이 「아직 안 나온 것」 으로) 판정에는 본 글이 간다 (09-30 B-09)
  // 옛 저장 세션(hintsSeen 없음)이 질문 한가운데서 이어지면 이미 연 칸을 사다리에서 채워 둔다
  L.hintsSeen = (Array.isArray(L.hintsSeen) ? L.hintsSeen : list.slice(0, L.hintLevel - 1)).concat([text]);
  // total 을 같이 싣는다 — 말풍선의 "힌트 N/3" 이 하드코딩이라, 판정 후
  // 사다리가 4단으로 길어지면 "힌트 4/3" 이라는 거짓 숫자가 떴다.
  pushTurn({
    who: 'ai', kind: 'hint', level: L.hintLevel, total: list.length,
    auto, text: escapeHtml(text), slides: hintSlideNos(text),
  });
  saveSession('qa-flow', qa);
  return true;
}

/**
 * 판정 뒤에 **주변 UI 만** 갈아 끼운다. 화면 전체를 다시 그리면 방금 애니메이션과
 * 함께 올라온 말풍선이 통째로 새로고침되어 깜빡인다 — 대화가 이어진다는 느낌이 깨진다.
 */
function refreshLiveChrome() {
  const ctx = $('#qaContext');
  if (ctx) ctx.innerHTML = liveContextHtml();
  const card = $('.qa-live-input');
  if (!card) return;
  // 카드를 갈아 끼우면 쳐 놓은 글이 날아간다. 힌트 한 칸 보려고 눌렀다가
  // 쓰던 답이 사라지면 그 다음부터는 아무도 힌트를 안 누른다.
  const prev = $('#liveAnswer');
  const draft = (prev && prev.value) || '';
  card.innerHTML = liveInputHtml();
  wireLiveInput();
  const next = $('#liveAnswer');
  if (next && draft && !next.value) {
    next.value = draft;
    next.selectionStart = next.selectionEnd = draft.length;
  }
  // 입력 카드 높이가 바뀌면(버튼 줄·머리말) 스트림 칸이 줄어 방금 붙은 말풍선 아래가 카드 뒤로 숨는다 —
  // 통화 배치(/temp 390px)에서 「모르겠어요」 보기 칩이 반쯤 가려졌다 (09-30 M-13). 카드를 갈아 끼운 뒤 한 번 더 바닥에 붙인다
  if (typeof scrollDown === 'function') scrollDown();
}

/** 답을 보내는 동안 입력만 잠근다 (재렌더 금지 — 쳐 놓은 글과 스트림을 지키려고). */
function setLiveBusy(on) {
  const ta = $('#liveAnswer');
  if (ta) ta.disabled = on;
  $$('.qa-live-input .step-actions button').forEach((b) => { b.disabled = on; });
  const send = $('#liveSend');
  if (send) send.textContent = liveSendLabel();
}

/**
 * 「듣고 있어요」 표시. **말할 때마다 즉시 반응이 있어야 한다** — 예전에는 답을
 * 보내면 버튼이 잠긴 채 몇 초간 아무 일도 안 일어났고, 그 침묵이 대화를 끊었다.
 */
function showCoachThinking() {
  const s = $('#stream');
  if (!s || $('#coachThinking')) return;
  const el = document.createElement('div');
  el.id = 'coachThinking';
  el.className = 'msg ai thinking enter';
  el.setAttribute('aria-live', 'polite');
  el.innerHTML = `<span class="msg-avatar av-${persona().accent}">${audInit()}</span>
    <div class="msg-bubble"><i class="dots" aria-hidden="true"><b></b><b></b><b></b></i><span class="thinking-text">듣고 있어요</span></div>`;
  s.appendChild(el);
  scrollDown();
}

function hideCoachThinking() {
  const el = $('#coachThinking');
  if (el) el.remove();
}

/** 「듣고 있어요」 자리의 글을 바꾼다 — 요청 제한으로 기다렸다 다시 보내는 동안 남은 초를 센다 (09-30 H-15) */
function setCoachThinkingText(text) {
  const span = $('#coachThinking .thinking-text');   // 첫 span 은 아바타(「교」)다 — 이름으로 찾는다
  if (span) span.textContent = text || '듣고 있어요';
}

/** 기다렸다 다시 보낼 때의 안내. 부스 booth_logic.retryWaitText 와 같은 말 */
function liveRetryWaitText(secondsLeft, reason = 'rate') {
  const n = Math.max(0, Math.ceil(Number(secondsLeft) || 0));
  if (reason === 'upstream') return n > 0 ? `AI 서버가 늦어서 ${n}초 뒤에 한 번 더 보낼게요` : '한 번 더 보내는 중이에요';
  return n > 0 ? `요청이 몰려서 잠깐 기다렸다 다시 보낼게요 · ${n}초` : '다시 보내는 중이에요';
}

/** 판정 직후의 학습 화면. 대화 로그 대신 변화 하나만 크게 보여 준다. */
function renderLiveCheckpoint() {
  const L = qa.live;
  const C = L.checkpoint;
  const q = L.questions[L.qi];
  const v = C.verdict || {};
  const passed = !!C.record.passed;
  const score = Math.max(0, Math.min(100, Math.round(v.score || 0)));
  const missing = (v.missing_points || []).filter(Boolean).slice(0, 2);
  // explanation 이 먼저다 — 「모르겠어요」 2회로 받은 맞춤 해설인데, gist 를
  // 앞세우면 F-08 폴백이 항상 차 있어 이 분기가 영영 죽는다. explanation 은
  // explain 코칭에서만 채워지므로 일반 경로의 표시는 변하지 않는다.
  const modelAnswer = liveRevealModel(q, v) || v.summary_sentence || '핵심 근거를 먼저 말하고, 자료의 수치나 사례로 뒷받침해 보세요.';
  const nextLabel = L.qi + 1 >= L.questions.length ? '결과 확인하기' : `다음 질문으로 · ${L.qi + 2}/${L.questions.length}`;
  app.innerHTML = `
    <div class="coach-nav"><a href="#/">← 저장하고 나가기</a><span>질문 ${L.qi + 1}/${L.questions.length}</span></div>
    <main class="qa-checkpoint">
      <div class="qa-check-hero ${passed ? 'is-pass' : 'is-learn'}">
        <span class="qa-check-icon">${passed ? '✓' : '↑'}</span>
        <p>${passed ? '내 말로 지켜냈어요' : '이 한 조각만 챙기면 돼요'}</p>
        <h1>${passed ? escapeHtml(q.label || '답변 완성') : escapeHtml(missing[0] || q.label || '핵심 근거 보완')}</h1>
        ${score ? `<div class="qa-score-pill">답변 완성도 <b>${score}%</b></div>` : ''}
      </div>
      <section class="qa-compare-card">
        <div class="qa-compare-row mine">
          <span>내가 한 답</span>
          <p>${escapeHtml(C.answer || '(답을 확인했어요)')}</p>
        </div>
        <div class="qa-compare-arrow" aria-hidden="true">↓</div>
        <div class="qa-compare-row coach">
          <span>${passed ? '기억할 한 문장' : '이렇게 말하면 완성'}</span>
          <p>${escapeHtml(modelAnswer)}</p>
        </div>
        ${missing.length ? `<div class="qa-memory-chips">${missing.map((x) => `<span># ${escapeHtml(x)}</span>`).join('')}</div>` : ''}
      </section>
      <p class="qa-check-note">외우지 않아도 괜찮아요. 다음 질문에서 다시 꺼내게 해드려요.</p>
      <div class="qa-check-actions">
        <button class="btn btn-primary" id="liveNext" type="button">${nextLabel}</button>
        ${passed ? '' : '<button class="btn btn-text" id="liveRetry" type="button">이 질문 한 번 더 답하기</button>'}
      </div>
    </main>`;
  $('#liveNext').addEventListener('click', completeLiveCheckpoint);
  const retry = $('#liveRetry');
  if (retry) retry.addEventListener('click', () => {
    L.checkpoint = null;
    saveSession('qa-flow', qa);
    renderQaLive();
  });
  window.scrollTo(0, 0);
}

function completeLiveCheckpoint() {
  const L = qa.live;
  if (!L || !L.checkpoint) return;
  const record = L.checkpoint.record;
  L.checkpoint = null;
  closeLiveQuestion(record);
  saveSession('qa-flow', qa);
  renderQaLive();
}

/**
 * 「여기까지 하고 저장」 — 지금 질문과 남은 질문을 닫고 결과로 간다.
 *
 * 지금 질문에 이미 답했으면 그 시도를 **그대로 남긴다** (09-30 held-out M-11: 두 번 답하고 저장해도 기록은
 * 「(넘김)·답하지 않고 넘겼어요」 였다). 마지막으로 채점된 답·판정·몇 번 답했는지가 결과·리포트에 간다(stopped).
 * 답을 보고 다시 말하던 중이면 그 기록(답만 봄)으로, 아직 답이 없으면 넘김으로 닫는다.
 * 한 번도 안 띄운 질문은 「안 물음」(unasked)이다 — 넘긴 것과 다르다.
 */
function finishLiveQaEarly() {
  const L = qa.live;
  if (!L || L.busy) return;
  if (L.qi < L.questions.length && !L.awaitEnd) {
    const q = L.questions[L.qi];
    const scored = (L.turns || []).filter((t) => !t.gaveUp && !t.clarify);
    const last = scored[scored.length - 1] || null;
    if (L.retell) {
      const base = L.retell.record || { id: q.id, label: q.label, question: q.question, verdict: 'unknown', score: 0, passed: false, mastered: false, summary: '', revealed: true };
      L.retell = null;
      pushTurn({ who: 'sys', kind: 'lost', text: `${escapeHtml(q.label)} — 답만 보고 마쳤어요. 리포트에 남겨둘게요` });
      closeLiveQuestion({ ...base, retold: false });
    } else if (last) {
      pushTurn({ who: 'sys', kind: 'lost', text: `${escapeHtml(q.label)} — 답 ${scored.length}번 하고 멈췄어요. 한 답을 리포트에 남겨둘게요` });
      closeLiveQuestion({
        id: q.id, label: q.label, question: q.question, answer: last.answer,
        verdict: last.verdict || 'unknown', score: last.score || 0, passed: false, mastered: false,
        stopped: true, answers: scored.length, viaCoach: (L.turns || []).some((t) => t.gaveUp), summary: '',
      });
    } else {
      const said = (L.turns || []).some((t) => t.gaveUp) ? '모르겠다고 한 뒤 마쳤어요' : '답하지 않고 넘겼어요';
      pushTurn({ who: 'sys', kind: 'lost', text: `${escapeHtml(q.label)} — ${said}. 리포트에 남겨둘게요` });
      closeLiveQuestion({
        id: q.id, label: q.label, question: q.question, answer: '',
        verdict: 'skipped', score: 0, passed: false, mastered: false, skipped: true, summary: '',
      });
    }
  }
  const unasked = L.questions.length - L.qi;
  if (unasked > 0) pushTurn({ who: 'sys', kind: 'lost', text: `남은 질문 ${unasked}개는 묻지 않고 마쳤어요` });
  while (L.qi < L.questions.length) {
    const q = L.questions[L.qi];
    closeLiveQuestion({
      id: q.id, label: q.label, question: q.question, answer: '',
      verdict: 'skipped', score: 0, passed: false, mastered: false, unasked: true, summary: '',
    });
  }
  saveSession('qa-flow', qa);
  qaLiveEnd();
}

/**
 * 마이크 쪽 알림. 전체를 다시 그리면 사용자가 쳐 놓은 답이 날아가므로,
 * 말풍선만 붙이고 화면은 건드리지 않는다.
 */
function micSay(html) {
  pushTurn({ who: 'sys', kind: 'lost', text: html });
  growStream();
  saveSession('qa-flow', qa);
}

/**
 * 버튼 속을 채운다. **아이콘 옆에 이름을 글자로 같이 낸다** — 마이크 그림만
 * 두었더니 무슨 버튼인지 못 알아봐서 아무도 누르지 않았다 (2026-08-07 사용자).
 */
function micBtnInner(state) {
  return `${state.icon}<span>${state.label}</span>`;
}

/** 마이크 버튼을 상태 하나로 갈아 끼운다 (아이콘 · 이름 · 잠금이 늘 같이 움직인다). */
function setMicBtn(state, disabled = false) {
  const btn = $('#liveMic');
  if (!btn) return;
  const s = MIC_STATE[state] || MIC_STATE.idle;
  btn.innerHTML = micBtnInner(s);
  // 눈에 보이는 글자와 접근성 이름이 어긋나면 음성 제어 사용자가 화면에 보이는
  // 대로 말해도 안 먹는다. 둘 다 같은 label 에서 뽑는다.
  btn.setAttribute('aria-label', s.label);
  btn.title = s.label;
  btn.disabled = !!disabled;
  btn.classList.toggle('is-rec', state === 'recording');
}

/** 화면을 새로 그릴 때의 마이크 버튼. 듣는 중이면 정지 아이콘으로 나온다. */
function micBtnHTML(busy) {
  const state = liveMic ? (liveMic.dictation ? 'dictating' : 'recording') : 'idle';
  const s = MIC_STATE[state];
  // is-rec 조건은 setMicBtn 과 같아야 한다 — 다르면 다시 그릴 때만 색이 튄다.
  return `<button class="btn btn-text btn-voice${state === 'recording' ? ' is-rec' : ''}" id="liveMic" type="button"
        aria-label="${s.label}" title="${s.label}" ${busy ? 'disabled' : ''}>${micBtnInner(s)}</button>`;
}

/**
 * 마이크 버튼 한 개로 시작·정지를 오간다.
 *
 * 되는 브라우저에서는 말하는 대로 글자가 뜨는 실시간 받아쓰기를 쓴다. 안 되면
 * 녹음해서 서버 STT 로 돌린다 — 그쪽은 다 말한 뒤에야 글자가 나오지만,
 * 입력 수단이 아예 없는 것보다는 낫다.
 */
async function toggleLiveMic() {
  if (liveMic) return stopLiveMic();
  const L = qa.live;
  if (!L || L.busy) return;
  // 마이크는 보안 컨텍스트에서만 열린다. localhost 는 예외로 쳐 주지만
  // http://10.x.x.x 같은 사내망 주소는 안 된다 — 그냥 두면 「시작하지 못했어요」만
  // 나와서 기능이 고장 난 줄 안다. 무엇을 해야 하는지 대신 말해 준다.
  if (window.isSecureContext === false) {
    micSay('마이크는 https 주소에서만 열려요. 공개 데모 주소(https)나 이 컴퓨터의 127.0.0.1 로 접속해 주세요 — 타이핑은 지금도 됩니다');
    setMicBtn('idle');
    return;
  }
  liveMicPending = 'opening';
  setMicBtn('opening', true);
  // 받아쓰기가 이미 죽었으면 다시 시도하지 않는다 — 같은 오류로 또 죽고,
  // 사용자는 마이크가 고장 난 줄 안다 (liveDictationDead 주석 참고).
  if (!liveDictationDead && window.ChuckchuckBridge.hasLiveDictation()) {
    return startDictationMic();
  }
  return startRecordingMic();
}

/** 실시간 받아쓰기 — 말하는 중에 입력창이 채워진다. */
function startDictationMic() {
  const ta = $('#liveAnswer');
  /* 이미 쳐 놓은 글은 기준선으로 잡아 둔다. 중간 결과가 올 때마다 입력창을 통째로
     다시 쓰기 때문에, 기준선을 안 두면 사용자가 친 글이 매번 지워진다.

     기준선을 시작할 때 한 번만 잡으면 **말하는 도중에 타이핑한 글자**가 다음
     중간 결과에 지워진다. 우리가 마지막으로 쓴 값을 같이 들고 있다가, 입력창이
     그것과 다르면 사용자가 손댄 것으로 보고 기준선을 다시 잡는다. */
  const pen = { base: ((ta && ta.value) || '').trim(), painted: null };
  try {
    liveMic = {
      dictation: true,
      session: window.ChuckchuckBridge.startLiveDictation({
        onText: ({ final, interim }) => paintLiveAnswer(pen, final + interim),
        onError: (msg) => {
          // 오류가 나면 인식기는 거기서 끝난다. 버튼을 안 되돌리면 이미 죽은
          // 세션에 「받아쓰기 멈추기」가 남아 사용자가 헛클릭한다.
          liveMic = null;
          // 여기 오는 오류(권한 거부·마이크 없음·망)는 다시 시작해도 같은 결과다.
          // 표시해 두지 않으면 다음에 눌러도 같은 길로 들어가 똑같이 죽는다.
          // 여기서 곧바로 녹음을 시작하지는 않는다 — onError 는 비동기라 사용자
          // 조작 권한이 이미 풀렸을 수 있고, 그러면 getUserMedia 가 막힌다.
          liveDictationDead = true;
          micSay(`${escapeHtml(msg)} — 마이크를 한 번 더 누르면 녹음해서 받아쓸게요. 타이핑으로 답해도 돼요`);
          setMicBtn('idle', !!(qa.live && qa.live.busy));
        },
      }),
    };
  } catch (err) {
    liveMicPending = '';
    // 시작조차 못 했으면 이 브라우저에서는 안 되는 것이다. 다음부터는 녹음으로 간다.
    liveDictationDead = true;
    micSay(`받아쓰기를 시작하지 못했어요: ${escapeHtml(err.message || String(err))} — 마이크를 한 번 더 누르면 녹음해서 받아쓸게요`);
    setMicBtn('idle');
    return;
  }
  liveMicPending = '';
  setMicBtn('dictating');
}

/** 실시간이 안 되는 브라우저용 — 녹음해 두었다가 멈출 때 서버 STT 로 넘긴다. */
async function startRecordingMic() {
  try {
    liveMic = {
      dictation: false,
      session: await window.ChuckchuckBridge.startAnswerRecording({
        onAutoStop: () => {
          micSay('녹음이 너무 길어져 자동으로 멈췄어요 — 받아쓰는 중입니다');
          stopLiveMic();
        },
      }),
    };
  } catch (err) {
    liveMicPending = '';
    // 권한 거부·미지원. 삼키면 사용자는 버튼이 왜 안 먹는지 알 수 없다.
    micSay(`마이크를 못 열었어요: ${escapeHtml(err.message || String(err))} — 타이핑으로 답해도 돼요`);
    setMicBtn('idle');
    return;
  }
  liveMicPending = '';
  setMicBtn('recording');
}

/** 마이크를 멈춘다. **어느 길이든 답을 보내지는 않는다.** */
async function stopLiveMic() {
  const mic = liveMic;
  if (!mic) return;
  liveMic = null;
  // 받아쓰는 사이에 답을 보냈을 수 있다. 그럼 화면은 판정 중이므로 무턱대고
  // 열어 주면 안 된다 — 상태의 주인은 L.busy 하나다.
  const idle = () => setMicBtn('idle', !!(qa.live && qa.live.busy));

  if (mic.dictation) {
    // 실시간은 이미 입력창에 다 들어가 있다 — 뒤늦게 받아쓸 게 없다.
    mic.session.stop();
    const ta = $('#liveAnswer');
    if (ta) {
      ta.focus();
      ta.selectionStart = ta.selectionEnd = ta.value.length;
    }
    idle();
    return;
  }

  liveMicPending = 'transcribing';
  setMicBtn('transcribing', true);
  try {
    const text = await window.ChuckchuckBridge.transcribeAnswer(await mic.session.stop(), { sessionId: (qa.live && qa.live.sessionId) || null });
    if (text) fillLiveAnswer(text);
    else micSay('말소리를 못 알아들었어요 — 다시 녹음하거나 타이핑으로 답해 주세요');
  } catch (err) {
    micSay(`받아쓰기에 실패했어요: ${escapeHtml(err.message || String(err))} — 타이핑으로 답해도 돼요`);
  }
  liveMicPending = '';
  idle();
}

/**
 * 실시간 받아쓰기가 입력창을 다시 그린다. 확정 전 조각까지 그대로 보여 줘야
 * "말하는 대로 나온다" 는 느낌이 산다 — 확정된 것만 그리면 뚝뚝 끊겨 보인다.
 */
function paintLiveAnswer(pen, spoken) {
  const ta = $('#liveAnswer');
  if (!ta) return;
  // 우리가 마지막으로 쓴 값과 다르면 그 사이에 사용자가 타이핑한 것이다.
  // 그 글자를 새 기준선으로 삼는다 — 안 그러면 말하는 도중에 친 글이 지워진다.
  if (pen.painted !== null && ta.value !== pen.painted) {
    pen.base = ta.value.trim();
  }
  const next = pen.base && spoken ? `${pen.base} ${spoken}` : (pen.base || spoken);
  ta.value = next;
  pen.painted = next;
  ta.scrollTop = ta.scrollHeight;
}

/**
 * 받아쓴 문장은 **채워만 준다**. 바로 보내면 잘못 알아들은 문장을 고칠 틈이 없어
 * 마이크가 타이핑보다 못한 입력이 된다. 이미 쓴 글이 있으면 뒤에 잇는다.
 */
function fillLiveAnswer(text) {
  const ta = $('#liveAnswer');
  if (!ta) return;
  const prev = (ta.value || '').trim();
  ta.value = prev ? `${prev} ${text}` : text;
  ta.focus();
  ta.selectionStart = ta.selectionEnd = ta.value.length;
}

/** 서버가 다시 이어지면(conn_watch.js 의 chuckchuck:reconnected) 연결 끊김으로 실패한 판정을 한 번 다시 보낸다.
    답은 실패 때 입력칸에 되살려 두었으므로 그대로 보낸다. 사용자가 그새 다른 걸 했으면(칸을 비웠거나 질문이 넘어갔으면) 안 보낸다. */
function liveRetryAfterReconnect() {
  const L = qa && qa.live;
  if (!L || !L.retryOnReconnect || L.busy || !L.judgeFailed) return false;
  if (typeof onQaRoute === 'function' && !onQaRoute()) return false;
  const { giveUp } = L.retryOnReconnect;
  L.retryOnReconnect = null;
  const typed = (($('#liveAnswer') || {}).value || '').trim();
  if (!giveUp && !typed) return false;
  pushTurn({ who: 'sys', kind: 'won', text: '다시 연결됐어요 — 방금 답으로 다시 판정할게요' });
  submitLiveAnswer({ giveUp });
  return true;
}

async function submitLiveAnswer({ giveUp = false } = {}) {
  const L = qa.live;
  /* 마이크가 켜져 있어도 자막 칸에 쳐 둔 글은 언제든 보낼 수 있어야 한다
     (2026-09-23 사용자: "타이핑도 허용하게"). 예전엔 「먼저 멈추고 보내 주세요」로
     막아서, 말하다가 손으로 고쳐 쓴 사람이 전송을 못 했다. 보내기 전에 마이크를
     먼저 멈춘다 — 안 멈추면 재렌더에 버튼이 사라지고 녹음이 아무도 안 멈추는 채 남는다.
     - 실시간 받아쓰기: 말한 것은 이미 칸에 들어 있다 → 멈추고 그대로 보낸다.
     - 녹음(서버 STT): 칸에 쓴 글이 있으면 그 글이 답이다 → 녹음은 버리고 보낸다.
       칸이 비어 있으면 보낼 게 녹음뿐이라, 받아쓰기를 먼저 하라고 안내한다. */
  if (liveMic) {
    const typedNow = (($('#liveAnswer') || {}).value || '').trim();
    if (liveMic.dictation) {
      await stopLiveMic();
    } else if (typedNow || giveUp) {
      const mic = liveMic;
      liveMic = null;
      try { await mic.session.stop(); } catch (_) { /* 이미 멈춘 뒤 */ }
      setMicBtn('idle', !!(qa.live && qa.live.busy));
    } else {
      micSay('녹음 중이에요 — 마이크를 한 번 더 누르면 받아써서 칸에 담아요. 타이핑해서 보내도 돼요');
      return;
    }
  }
  // 여닫는 가장자리도 막는다 — 여는 중에 보내면 녹음이 아무도 안 멈추는 채
  // 남고, 받아쓰는 중에 보내면 받아쓴 문장이 재렌더에 지워진다.
  if (liveMicPending) {
    micSay(liveMicPending === 'transcribing'
      ? '받아쓰는 중이에요 — 문장이 입력창에 담기면 보내 주세요'
      : '마이크를 여는 중이에요 — 잠시 뒤에 보내 주세요');
    return;
  }
  const q = L.questions[L.qi];
  const ta = $('#liveAnswer');
  const typed = ((ta && ta.value) || '').trim();
  // 답을 보고 다시 말하는 중이면 판정하지 않는다 — 아래 closeRetell 참고.
  if (L.retell) return closeRetell(typed);
  const answer = giveUp ? (typed || '(모르겠어요)') : typed;
  if (!answer || L.busy) return;
  // 이번에 실제로 답하고 있는 질문 — 되물음이 떠 있으면 그것이다. 원래 질문만
  // 기록하면 판정 히스토리에 되물음이 안 남아, "네" 같은 증분 답이 무엇에 대한
  // 답인지 서버가 알 길이 없다 (그래서 정답을 말해도 unknown 이 반복됐다).
  const askedNow = (L.turn && L.lastJudgement && L.lastJudgement.followup) || q.question;
  // 내 말풍선에는 자리표시자 「(모르겠어요)」 대신 한 말 그대로 (09-30 L-01). 서버에는 예전처럼 자리표시자를 보낸다
  pushTurn({ who: 'me', kind: 'say', text: escapeHtml(giveUp ? (typed || '모르겠어요') : answer) });
  L.busy = true;
  saveSession('qa-flow', qa);
  // **재렌더하지 않는다.** 예전엔 여기서 화면을 통째로 다시 그려 스트림이 깜빡이고
  // 버튼만 잠긴 채 몇 초가 흘렀다 — 말한 직후가 반응이 가장 필요한 순간인데
  // 그 순간이 정적이었다. 내 말풍선을 붙이고, 코치가 듣고 있다고 바로 알린다.
  if (ta) ta.value = '';
  growStream();
  setLiveBusy(true);
  showCoachThinking();
  // 판정이 실패하면 입력창에 답을 되살린다 — 창을 비웠으므로, 안 되살리면
  // 「다시 시도」가 처음부터 다시 타이핑하기가 된다.
  let failedAnswer = '';
  let closed = false;
  const before = liveLastScore();
  // 기다리다 다시 보내는 사이 사용자가 다른 질문·화면으로 갔으면 다시 보내지 않는다
  const stillHere = () => qa.live === L && L.questions[L.qi] === q && (typeof onQaRoute !== 'function' || onQaRoute());
  try {
    const v = await window.ChuckchuckBridge.judgeQaAnswer(L.sessionId, {
      questionId: q.id, answer, history: liveHistory(), question: q, giveUp,
      // 이 질문에 앞서 낸 답들. 판정은 누적 전체를 본다 (f09 "합쳐서 판정하라").
      // 포기 턴의 "(모르겠어요)" 자리표시자는 답이 아니라 뺀다.
      priorAnswers: liveScoredAnswers(),
      // 지금까지 펼쳐 본 힌트. 코치가 힌트와 이어지는 말로 반응한다.
      // 「모르겠어요」 코칭이 방금 둘 중 하나·빈칸으로 되물었으면 그 되물음도 싣는다 — 이번 답은 그 물음의 답이다
      // (09-30 대화 감사 §3: 칩 「항목」 이 원래 질문의 답으로 채점돼 good 85 로 닫혔다).
      hintsShown: liveHintsShown(),
      artifacts: liveArtifacts(),
      // 요청 제한(429)·AI 서버 지연(503) — 브리지 클라이언트가 기다렸다 같은 답을 다시 보낸다. 남은 초를 「듣고 있어요」 자리에 센다 (09-30 H-15)
      onWait: ({ left, reason }) => setCoachThinkingText(liveRetryWaitText(left, reason)),
      stillWanted: stillHere,
    });
    const m = LIVE_VERDICT[v.verdict] || LIVE_VERDICT.unknown;
    L.turn += 1;
    // clarify 는 «질문을 못 알아들어 되물었다» 는 뜻이라 채점된 답이 아니다.
    // 대화에는 남기되 라운드에서는 뺀다 (liveScoredAnswers).
    L.turns.push({
      question: askedNow, questionId: q.id, answer,
      verdict: v.verdict, score: v.score || 0, gaveUp: giveUp,
      clarify: v.coach_stage === 'clarify',
    });
    L.lastJudgement = v;
    // 판정 사다리가 지금 들고 있는 것보다 짧지 않으면 그걸로 갈아탄다. **짧아지면 안 버린다** —
    // 버리면 다음 말풍선의 분모가 줄어 "힌트 2/4" 뒤에 "힌트 3/3" 이 뜬다. 길이가 같아도 갈아탄다 —
    // 서버가 판정 뒤 넷째 칸(골자 조각)을 「아직 안 나온 것」 으로 바꿔 끼운다(칸 수는 그대로, 09-30 §11).
    const judgedHints = Array.isArray(v.hints) ? v.hints : [];
    if (judgedHints.length && judgedHints.length >= ((L.hintList || liveQuestionHints()).length)) L.hintList = judgedHints;
    L.judgeFailed = false;
    hideCoachThinking();
    // 폴백 표시(자료 본문 없이 판정 등)는 한 질문에 한 번만 짧게. 서버 질문을 못 찾은 것은 개발 로그로만 (09-30 WP-B)
    const notes = liveDegradedLines(v).filter((n) => !(L.notesShown || []).includes(n));
    if (notes.length) {
      L.notesShown = (L.notesShown || []).concat(notes);
      pushTurn({ who: 'sys', kind: 'note', text: escapeHtml(notes.join(' ')) });
    }
    if (v.grounded_on_server === false || (v.degraded || []).some((c) => LIVE_DEV_ONLY_DEGRADED.includes(c))) {
      console.info('[chuckchuck] 판정 폴백(화면 밖):', (v.degraded || []).join(', ') || 'grounded_on_server=false');
    }
    if (v.react) {
      // 점수를 같이 싣는다. 「좋아지고 있다」는 말보다 62 → 78 이라는 진짜 숫자가
      // 세다 (UI_REDESIGN §14 — 숫자는 신성하다, 지어내지 않는다).
      const quote = v.evidence_quote || '';
      pushTurn({
        // 70~79 통과(요지는 맞음)는 「절반쯤」 이 아니다 — 서버의 passed 를 그대로 칩에 옮긴다 (09-30 §10)
        who: 'ai', kind: 'react', verdict: (!v.coach_stage && v.passed && v.verdict === 'partial') ? 'full' : m.react,
        text: escapeHtml(v.coach_stage ? coachReactText(v.react, quote) : v.react),
        score: v.score || 0, before,
        // 자료 인용 카드 재료 — 코칭 응답에만 실린다. 옛 세션 턴에는 없다.
        quote: v.coach_stage && quote ? escapeHtml(quote) : '',
        quoteSlide: v.coach_stage ? (v.evidence_slide_no || 0) : 0,
        slides: v.coach_stage && v.evidence_slide_no ? hintSlideNos(`${v.evidence_slide_no}장`) : [],
        // 「모르겠어요」에 온 응답은 **판정이 아니다** — 서버가 점수를 안 매기고
        // verdict 자리에 폴백을 넣어 보낸다 (f09_judge.coach_stuck). 그걸 판정표로
        // 그리면 솔직하게 모르겠다고 누른 사람이 틀린 답과 똑같은 빨간 칩을 받는다.
        // 단계를 그대로 실어서 «지금 무슨 일이 일어나는지» 를 대신 적는다.
        coach: v.coach_stage || '',
        // 판정 이의 — 코칭 응답(막힘 사다리)은 판정이 아니라 버튼을 안 단다.
        fb: v.coach_stage ? '' : liveFeedbackHtml('judgement_dispute', `q:${q.id}:r${L.turn || 1}`,
          [['wrong_verdict', '이 판정은 아닌 것 같아요']],
          { answer, verdict: v.verdict, score: v.score || 0, round: L.turn || 1, question: q.question }),
      });
    }

    // 닫는 기준은 **서버의 mastered 하나**다. passed 로 닫으면 요지만 맞힌 72점
    // 답이 곧바로 넘어가 되묻기가 아예 안 돈다 — 그게 이 화면이 밋밋했던 이유다.
    const done = v.mastered === undefined ? v.passed : v.mastered;
    if (v.coach_stage === 'explain') {
      // 해설을 받았다고 닫지 않는다 — 답을 봤으니 이제 한 번 말해 볼 차례다.
      coachedRetell(q, v, answer);
    } else if (done) {
      finishLiveQuestion(q, v, answer);
      closed = true;
    } else {
      // 절반은 맞혔는데 또 물으면 뭘 더 말해야 하는지 모른 채 같은 답을 낸다.
      // 빠진 절반을 펼쳐 주고 되묻기는 그대로 이어 간다 (2026-08-08 사용자 요청).
      const shownMissing = v.verdict === 'partial' ? revealHalf(q, v) : false;
      // 「N번째 답변」 은 서버가 센 라운드로 — 예전 L.turn 은 「모르겠어요」 턴까지 세어 서버(2라운드)와 어긋났다 (09-30 §10)
      askAgain(v, v.round_no || L.turn, { skipMissing: shownMissing });
    }
  } catch (err) {
    hideCoachThinking();
    // 「모르겠어요」도 판정을 타므로, 서버가 죽으면 이 질문에 갇힌다.
    // 아래 렌더에서 「답 보고 다시 말해보기」가 열려 서버 없이 다음 질문으로 간다.
    // 단 요청 제한(429)은 판정 실패가 아니다 — 출구를 열지 않고 답만 되살린다 (liveJudgeFailure · 09-30 H-15).
    const f = liveJudgeFailure(err, giveUp);
    L.judgeFailed = f.judgeFailed;
    failedAnswer = f.restore ? answer : '';   // 포기 자리표시자는 되살릴 답이 아니다
    // 서버에 못 닿아 실패했으면, 다시 연결될 때 같은 답으로 한 번 더 보낸다 (liveRetryAfterReconnect)
    L.retryOnReconnect = f.retryOnReconnect;
    // 자료 정보가 통째로 사라진 경우는 다시 눌러도 똑같이 실패한다. 「다시
    // 시도」로 유도하면 같은 자리를 맴돌 뿐이라, 원인과 빠져나갈 길을 따로 낸다.
    if (f.text) pushTurn({ who: 'sys', kind: f.judgeFailed ? 'lost' : 'note', text: f.text });
  }
  L.busy = false;
  saveSession('qa-flow', qa);
  if (qa.live !== L) return;   // 기다리는 사이 코칭이 새로 시작됐다 — 옛 판정으로 새 화면을 건드리지 않는다
  if (closed) advanceLiveStream();
  else { growStream(); refreshLiveChrome(); }
  if (failedAnswer) {
    const retryTa = $('#liveAnswer');
    if (retryTa) {
      retryTa.value = failedAnswer;
      retryTa.selectionStart = retryTa.selectionEnd = retryTa.value.length;
    }
  }
}

/**
 * 질문을 닫은 뒤 다음 질문으로 잇는다. **스트림을 다시 그리지 않는다.**
 *
 * 전체 재렌더는 방금 올라온 「설득 완료」 표식과 총평을 통째로 새로고침해서,
 * 정복하는 순간의 연출이 그대로 날아간다 — 하필 이 화면에서 가장 기분 좋아야 할
 * 한 박자다. 이긴 줄과 다음 질문을 이어 붙이고 왼쪽 칸(막대·연속)만 갱신한다.
 *
 * 마지막 질문이었으면 결과 화면으로 가야 하므로 그때만 renderQaLive 에 넘긴다.
 */
function advanceLiveStream() {
  const L = qa.live;
  if (qa.ended) return renderQaLive();
  if (L.qi >= L.questions.length) return enterLiveFinale();
  presentLiveQuestion();
  saveSession('qa-flow', qa);
  growStream();
  refreshLiveChrome();
}

/**
 * 마지막 질문이 닫혔다는 표시만 세운다. 화면은 건드리지 않는다 —
 * 새로고침 복원(renderQaLive)과 진행 중 전환(enterLiveFinale)이 같이 쓴다.
 */
function markLiveFinale() {
  const L = qa.live;
  if (L.awaitEnd) return false;
  L.awaitEnd = true;
  pushTurn({ who: 'sys', kind: 'finale', text: `질문 ${L.questions.length}개를 모두 마쳤어요` });
  return true;
}

/**
 * 마지막 질문이 닫혔다. **결과 화면으로 곧바로 갈아치우지 않는다.**
 *
 * 예전에는 마지막 답을 보내는 순간 스트림이 통째로 결과 화면으로 바뀌었다.
 * 그래서 방금 닫힌 질문의 판정도 마무리 카드도 한 글자 못 읽고 끝났다 —
 * 여섯 번 답한 사람이 마지막 한 번만 못 보고 나가는 셈이다 (2026-08-10 사용자).
 * 이제 마무리 알림을 스트림에 얹고, 입력칸 자리를 「결과 확인하기」 로 바꾼다.
 * 넘어가는 시점은 사용자가 고른다.
 */
function enterLiveFinale() {
  markLiveFinale();
  saveSession('qa-flow', qa);
  growStream();
  refreshLiveChrome();
  scrollDown();
}

/** 이 질문에서 직전에 받은 점수. 없으면 0 — 첫 답에는 「올랐다」가 성립하지 않는다. */
function liveLastScore() {
  const turns = qa.live.turns || [];
  return turns.length ? (turns[turns.length - 1].score || 0) : 0;
}

/**
 * 「모르겠어요」 2회 — 서버가 해설(explain)로 답을 풀어 준 자리.
 *
 * **이것도 곧 「답 확인하기」다.** 예전에는 해설만 띄우고 질문을 닫았는데,
 * 그러면 이 사람은 그 개념에 대해 **한 마디도 하지 않은 채** 넘어간다.
 * 정작 두 번이나 막혔던 개념이라 가장 말해 봐야 하는 자리인데.
 * 「답 보고 다시 말해보기」와 같은 곳으로 보낸다 — 출구가 둘인데 뒤처리가
 * 다르면 어느 문으로 나갔느냐가 결과를 바꾼다.
 */
function coachedRetell(q, v, answer) {
  enterRetell(liveRevealModel(q, v) || v.summary_sentence, {
    id: q.id, label: q.label, question: q.question, answer,
    verdict: 'unknown', score: 0, passed: false, mastered: false, gaveUp: true,
    summary: v.summary_sentence || '', revealed: true, coached: true,
  });
}

/**
 * 재현 모드로 들어간다. 답을 펼쳐 놓고 **질문은 열어 둔다.**
 *
 * record 를 여기서 들고 있는 이유: 재현을 끝낼 때 질문을 닫아야 하는데, 어느
 * 문으로 들어왔느냐(막힘 해설 · 답 공개)에 따라 남길 기록이 다르다. closeRetell
 * 이 그때 가서 짐작하게 하면 gaveUp·coached 같은 플래그가 조용히 사라진다.
 */
function enterRetell(model, record) {
  const L = qa.live;
  // 서버가 길이 상한에서 자른 글이면 마지막 온전한 문장까지만 (문장 한가운데서 끊긴 모범답이 뜨지 않게)
  const text = liveWholeSentences(model)
    || '핵심 근거를 먼저 말하고, 자료의 수치나 사례로 뒷받침해 보세요.';
  pushTurn({ who: 'ai', kind: 'gist', text: escapeHtml(text) });
  pushTurn({
    who: 'ai', kind: 'question', meta: '이제 내 말로',
    text: '지금 본 걸 안 보고 다시 말해 보세요. 그대로 안 옮겨도 괜찮아요.',
  });
  L.retell = { model: text, record };
  // 막혀서 쓰다 만 글은 지운다 — 방금 답을 봤으니 처음부터 다시 말하는 자리다.
  const ta = $('#liveAnswer');
  if (ta) ta.value = '';
  saveSession('qa-flow', qa);
}

/**
 * 퀘스트 막대가 세는 「설득한 개념」 수. **임계는 서버 것을 그대로 쓴다** —
 * 프론트가 따로 계산하면 화면마다 다른 수가 나온다 (진행 중 헤더는 good|partial,
 * 결과 화면은 good 만 세어 3/3 이 1/3 으로 떨어진 적이 있다).
 *
 * 다만 **답을 보고 넘어간 것은 빼야 한다.** 예전엔 `passed` 만 봐서, 답을 펼쳐
 * 보고 넘어간 질문도 「설득했어요」로 세었다 — 왼쪽 막대는 2/2 인데 결과 화면은
 * 「1개 지킴 · 1개 다시 볼 곳」 이라고 말했다 (결과 화면 `bucketOf` 는 revealed 를
 * 넘긴 것으로 친다). 여기 조건을 `questState` 의 won·part 분기와 같게 맞춘다 —
 * 목록과 그 위의 숫자가 같은 것을 세야 한다.
 */
function liveWonCount(results) {
  // 스스로 설명한 것만 (liveBucket self) — 결과 헤드라인·리포트 「끝까지 설명」 과 같은 수다 (09-30 C-09)
  return (results || []).filter((r) => liveBucket(r) === 'self').length;
}

/**
 * 3라운드 출구로 닫힌 질문인가 — 설득(good)이 아니라 「세 번째 답이라 닫은」 것. 옛 세션(closeReason 없음)은
 * partial 로 닫힌 것을 그렇게 본다 (qa_mastered 가 partial 을 닫는 길은 라운드 출구뿐이다).
 * 09-30 대화 감사 §10: 결과 「7개를 모두 자기 말로 지켰어요」 중 4개가 이 출구였다.
 */
function liveForcedClose(r) {
  if (!r || r.revealed || r.gaveUp) return false;
  if (r.closeReason) return r.closeReason === 'rounds' || r.closeReason === 'guard';
  return !!r.mastered && r.verdict !== 'good';
}

/** 이 칸(방향·범위·인용 다음)까지 힌트를 본 질문은 「도움 받아 닫힘」 — 셋째 칸부터 답에 가까워진다. 부스 HINT_HELP_LEVEL 과 같다 */
const LIVE_HINT_HELP = 3;

/**
 * 닫힌 질문 하나를 결과 묶음 넷 중 하나로 (09-30 held-out C-09 — 결과·리포트가 강제 닫힘·힌트로 본 답까지 「자기 말로 지켰어요」 로 셌다).
 *   self    스스로 설명    판정으로 닫혔고(good) 3라운드 출구·힌트 셋째 칸·「모르겠어요」 코칭(보기·빈칸) 없이
 *   helped  도움 받아 닫힘  3라운드 출구(rounds·guard) · 힌트 셋째 칸 이상 · 코칭 되물음 뒤에 닫힘
 *   retold  답 보고 다시 말함 답(해설)을 펼친 뒤 내 말로 말해 봤다
 *   skipped 넘김·안 물음   답만 보고 넘김 · 답하지 않고 넘김 · 묻기 전에 마침 · 답하다 멈춤
 * 헤드라인·퀘스트 막대·연속은 self 만 센다. 옛 저장 결과(플래그 없음)도 같은 칸으로 떨어진다.
 */
function liveBucket(r) {
  if (!r) return 'skipped';
  if (r.revealed) return r.retold ? 'retold' : 'skipped';
  if (r.unasked || r.stopped || r.verdict === 'skipped') return 'skipped';
  const closed = r.mastered === undefined ? !!r.passed : !!r.mastered;
  if (!closed || r.gaveUp) return 'skipped';
  if (liveForcedClose(r) || (r.hintLevel || 0) >= LIVE_HINT_HELP || r.viaCoach) return 'helped';
  return 'self';
}

/** 사용자가 **스스로 누른** 힌트 수 (09-30 L-05 — 라운드가 올라 저절로 열린 칸은 「힌트 N단계」 로 안 센다). 옛 결과는 hintLevel */
function liveHintsUsed(r) {
  if (!r) return 0;
  return typeof r.hintUsed === 'number' ? r.hintUsed : (r.hintLevel || 0);
}

/**
 * 서버가 길이 상한에서 자른 글(끝이 「…」)을 마지막 온전한 문장까지로 되돌린다 — 문장 한가운데서 끊긴 모범답이 뜨지 않게.
 * 온전한 문장이 없으면 그대로 둔다. 부스 booth_logic.wholeSentences 와 같은 규칙 (이 파일은 클래식 스크립트라 import 를 못 한다).
 */
function liveWholeSentences(text) {
  const t = String(text || '').trim();
  if (!/(?:…|\.\.\.)$/.test(t)) return t;
  const body = t.replace(/(?:…|\.\.\.)$/, '');
  const end = /[.!?。](?:["'」』”’»)\]]*)(?=\s|$)/g;
  let cut = -1;
  for (let m = end.exec(body); m; m = end.exec(body)) cut = m.index + m[0].length;
  return cut > 0 ? body.slice(0, cut).trim() : t;
}

/**
 * 판정·질문 응답의 폴백 표시를 짧은 사람 말로 (09-30 WP-B degraded_notes). 자료 본문 없이 판정했으면(grounded_on_deck=false) 그렇다고 한다.
 * 서버가 만든 질문을 못 찾은 것(grounded_on_server=false · question_unverified·question_mismatch)은 사용자가 할 일이 없어 화면에 싣지 않는다.
 * 부스 booth_logic.degradedLines 와 같은 규칙.
 */
const LIVE_DEV_ONLY_DEGRADED = ['question_unverified', 'question_mismatch'];
/** 녹음이 이 자료와 다른 발표라 F-08 이 자료만 보고 물었다 — 질문 묶음에 한 번, 조용히 (09-30 WP-J2 · F-08 speech_mismatch_deck_only) */
const LIVE_SPEECH_MISMATCH_NOTE = '녹음이 이 자료와 달라서 자료만 보고 질문했어요.';
function liveDegradedLines(res) {
  if (!res || typeof res !== 'object') return [];
  const codes = Array.isArray(res.degraded) ? res.degraded : [];
  const notes = Array.isArray(res.degraded_notes) ? res.degraded_notes : [];
  const out = [];
  notes.forEach((n, i) => {
    if (typeof n === 'string' && n.trim() && !LIVE_DEV_ONLY_DEGRADED.includes(codes[i])) out.push(n.trim());
  });
  if (res.grounded_on_deck === false && !codes.includes('slide_doc_missing')) out.push('자료 본문 없이 판정했어요.');
  if (liveSpeechMismatch(res)) out.push(LIVE_SPEECH_MISMATCH_NOTE);
  return [...new Set(out)];
}

/**
 * 첫 질문 앞에 한 번 띄우는 알림 줄 (09-30 녹음 대화 감사 REC-14).
 *
 * 녹음을 받았는데 질문 재료로 못 썼으면(QuestionDoc.speech_unused — 다른 발표 · 판정이 짐작뿐) 그 까닭(speech_note)이 **맨 앞**이다.
 * 예전엔 끝에 붙여 「문헌 검색 일부가 실패해서…」 뒤에 묻혔다 — 녹음이 다른 발표라는 건 질문 전체의 재료가 바뀐 일이라 문헌보다 먼저다.
 * speech_note 가 있으면 같은 사실을 줄여 말한 LIVE_SPEECH_MISMATCH_NOTE 는 뺀다 — 한 사실을 두 번 말하지 않는다.
 */
function liveEntryNotes(doc) {
  const lines = liveDegradedLines(doc);
  const note = doc && doc.speech_unused && typeof doc.speech_note === 'string' ? doc.speech_note.trim() : '';
  if (!note) return lines;
  return [note, ...lines.filter((n) => n !== note && n !== LIVE_SPEECH_MISMATCH_NOTE)];
}

/**
 * 질문 묶음이 녹음을 버리고 자료만으로 만들어졌나 — F-08 은 질문마다 basis.checks 에 speech_mismatch_deck_only 를 남긴다
 * (문서 단위 칸이 계약에 없어서). 묶음 머리에 같은 이름의 참 값이 오면 그것도 받는다. 판정 응답에는 questions 가 없어 늘 거짓이다.
 */
function liveSpeechMismatch(res) {
  if (!res || typeof res !== 'object') return false;
  if (res.speech_mismatch_deck_only === true) return true;
  const qs = Array.isArray(res.questions) ? res.questions : [];
  return qs.some((q) => q && q.basis && Array.isArray(q.basis.checks) && q.basis.checks.includes('speech_mismatch_deck_only'));
}

/**
 * 질문 아래 이유 한 줄. 함정 질문은 서버 이유가 「질문이 말한 내용이 자료와 같은지 먼저 따져 보는 연습이에요」 라
 * **함정임을 알려 준다** (09-30 B-01·H-07) — 다른 질문과 같은 모양이어야 하므로 장만 가리키는 중립 문장으로 바꾼다.
 */
function liveQuestionWhy(q) {
  if (!q) return '';
  if (q.trap) {
    const nos = [...new Set((q.slide_nos || []).map(Number).filter((n) => n > 0))];
    return `${nos.length ? `자료 ${nos.join('·')}장을` : '자료를'} 근거로 설명할 수 있는지 보려고 물어요.`;
  }
  return typeof q.why === 'string' ? q.why.trim() : '';
}

/**
 * 판정 요청이 끝내 실패했을 때 무엇을 할지 (09-30 H-15). 요청 제한(rate_limited)은 **판정 실패가 아니다** —
 * 출구(「답 보고 다시 말해보기」)를 열지 않고(judgeFailed=false), 결과에 「넘긴 질문」 으로 남기지 않는다. 답은 되살려 다시 보내게 한다.
 * 자동 재시도는 bridge judgeQaAnswer 가 이미 했다 — 여기 오는 것은 그래도 막힌 것이다.
 */
function liveJudgeFailure(err, giveUp = false) {
  const code = (err && err.code) || '';
  if (code === 'cancelled') return { judgeFailed: false, retryOnReconnect: null, restore: !giveUp, text: '' };
  if (err && (err.rateLimited || code === 'rate_limited' || err.status === 429)) {
    return {
      judgeFailed: false, retryOnReconnect: null, restore: !giveUp,
      text: '요청이 몰려서 판정을 아직 못 받았어요. 조금 뒤에 답을 다시 보내면 판정해요 — 이 질문은 넘긴 걸로 세지 않아요',
    };
  }
  return {
    judgeFailed: true,
    retryOnReconnect: code === 'server_unreachable' ? { giveUp } : null,
    restore: !giveUp,
    text: code === 'session_missing'
      ? '자료 정보가 사라져서 판정할 수 없어요. <a href="#/new">자료를 다시 올리면</a> 이어서 할 수 있어요 — 지금은 「답 보고 다시 말해보기」로 다음 질문에 갈 수 있어요'
      : code === 'server_unreachable'
        ? '서버와 연결이 끊겨서 판정하지 못했어요. 다시 연결되면 방금 답으로 자동으로 다시 판정해요'
        : `판정 실패: ${escapeHtml((err && err.message) || String(err))} — 다시 시도하거나 「답 보고 다시 말해보기」로 다음 질문에 갈 수 있어요`,
  };
}

/* 되묻기 머리말. 서버가 좁혀 온 단계를 말로 옮긴다 — 같은 「이어서 묻습니다」를
   세 번 붙이면 사용자는 질문이 좁아진 걸 못 알아채고 벽에 세 번 부딪힌 걸로 읽는다. */
const TIER_META = {
  // 해요체 (CLAUDE.md §3-1) — 09-30 대화 감사 §9: 「이어서 묻습니다」 합쇼체 머리말이 58번 나갔다
  probe: '이어서 물어볼게요',
  focus: '좁혀서 다시 물어볼게요',
  converge: '마지막 한 걸음이에요',
};

/**
 * 방금 「모르겠어요」 코칭이 던진 되물음(둘 중 하나·빈칸). 다음 답은 그 물음에 대한 답이라 판정에 같이 싣는다.
 * 코칭이 아니면 빈 배열이다.
 */
/**
 * 판정에 「보여 준 힌트」 로 싣는 것 — **연 칸의 글 그대로** + 코칭 되물음 (09-30 B-09). 판정 사다리를 그때그때 잘라 보내면
 * 갈아 끼운 넷째 칸처럼 사용자가 본 적 없는 글이 「본 힌트」 로 갔다. 옛 저장 세션(hintsSeen 없음)은 사다리를 연 칸만큼 자른다.
 */
function liveHintsShown() {
  const L = qa.live || {};
  const seen = Array.isArray(L.hintsSeen) ? L.hintsSeen : liveHints().slice(0, L.hintLevel || 0);
  return seen.concat(liveCoachAsk());
}

function liveCoachAsk() {
  const v = (qa.live || {}).lastJudgement || {};
  return (['narrow', 'scaffold'].includes(v.coach_stage) && v.followup) ? [`되물음: ${v.followup}`] : [];
}

function askAgain(v, turn, { skipMissing = false } = {}) {
  const points = (v.missing_points || []).filter(Boolean);
  // revealHalf 가 방금 같은 points 로 같은 말풍선을 붙였으면 또 붙이지 않는다 —
  // 한 판정에 「빠진 것」이 연달아 두 번 뜨면 두 번째는 안 읽는다.
  if (points.length && !skipMissing) {
    pushTurn({ who: 'ai', kind: 'missing', points: points.map(escapeHtml) });
  }
  const tier = v.probe_tier || 'probe';
  if (v.followup) {
    pushTurn({
      who: 'ai',
      kind: 'question',
      // 코칭 되물음은 라운드가 아니라 사다리 단계가 머리말이다.
      meta: v.coach_stage ? coachMeta(v.coach_stage) : `${TIER_META[tier] || TIER_META.probe} · ${turn + 1}번째 답변`,
      text: escapeHtml(v.followup),
      // 둘 중 하나 — 누르면 답칸에 들어간다 (바로 보내지 않는다: 고쳐 쓸 여지를 둔다)
      choices: (v.choices || []).map((c) => escapeHtml(String(c))),
    });
  }
  autoHint(tier);
}

/**
 * 라운드가 오르면 힌트를 **한 칸 알아서 연다.**
 *
 * 예전에는 사용자가 「힌트 보기」를 눌러야만 열렸다. 그런데 정작 막힌 사람이
 * 그 버튼을 안 누른다 — 누르면 지는 것 같아서다. 그래서 힌트를 다 가진 채로
 * 같은 질문에 세 번 막히는 일이 벌어졌다. 좁혀 물을 때 재료도 같이 준다.
 *
 * 이미 스스로 열어 둔 칸이 라운드보다 많으면 아무것도 안 한다 — 앞서 나간
 * 사람에게서 힌트를 빼앗지도, 두 칸씩 건너뛰지도 않는다.
 */
function autoHint(tier) {
  const L = qa.live;
  const want = tier === 'converge' ? 2 : (tier === 'focus' ? 1 : 0);
  if (L.hintLevel >= want) return;
  openNextHint({ auto: true });
}

/**
 * 「절반만 설득했어요」 자리에서 **빠진 절반과 완성 문장을 펼친다.**
 *
 * 절반을 맞힌 사람에게 빈손으로 또 물으면, 뭘 더 말해야 하는지 모르는 채 방금 쓴
 * 답을 조금 고쳐 다시 낸다 — 그게 되묻기가 지루해지는 지점이다. 모자란 쪽을
 * 이름 붙여 주고 완성 문장을 보여 주되, **질문은 닫지 않는다.** 보고 나서 자기
 * 말로 한 번은 해 봐야 남는다 (mastered 게이트를 그대로 지킨다).
 *
 * 한 질문에 한 번만 연다. 라운드마다 같은 완성 문장을 다시 띄우면 스트림이 답으로
 * 도배되고, 세 번째쯤엔 읽지 않고 넘긴다.
 *
 * @returns {boolean} 「빠진 것」 말풍선을 여기서 이미 붙였는가.
 *   바로 뒤에 오는 askAgain 이 같은 points 로 같은 말풍선을 한 번 더 밀어 넣어,
 *   partial 판정마다 「빠진 것」이 연달아 두 번 떴다 (2026-08-08 revealHalf 를
 *   넣으면서 생겼다). 누가 붙였는지는 호출자가 알 수 없으므로 여기서 알려 준다.
 */
function revealHalf(q, v) {
  const L = qa.live;
  if (L.halfShown) return false;
  const points = (v.missing_points || []).filter(Boolean).slice(0, 3);
  // 함정 질문의 골자는 **바로잡은 사실 그 자체**다 — 아직 못 바로잡았는데 펼치면 정답을 흘린다 (09-30 §7).
  // 브리지는 함정의 전제·골자를 화면 사본에서 뺀다(gist_withheld · 09-30 WP-J2) — 함정인지는 q.trap 으로, 바로잡은 뒤의 골자는 판정 응답으로 온다.
  const trapOpen = !!((q.trap || q.trap_premise || q.gist_withheld) && !v.passed);
  const answer = trapOpen ? '' : (liveRevealModel(q, v) || v.summary_sentence || '');
  // 둘 다 비면 열 것이 없다. 빈 카드를 띄우느니 되묻기만 이어 간다.
  if (!points.length && !answer) return false;
  L.halfShown = true;
  // 닫을 때 같은 문장을 또 띄우지 않기 위해 원문을 남긴다 (finishLiveQuestion).
  L.halfGist = answer;
  if (points.length) pushTurn({ who: 'ai', kind: 'missing', points: points.map(escapeHtml) });
  if (answer) pushTurn({ who: 'ai', kind: 'gist', mid: true, text: escapeHtml(liveWholeSentences(answer)) });
  return points.length > 0;
}

function closeLiveQuestion(record) {
  const L = qa.live;
  // hintLevel 은 본 사다리 칸의 끝(저절로 연 칸 포함 — 셋째 칸이면 도움으로 센다), hintUsed 는 사용자가 누른 칸 수 (L-05)
  L.results.push({
    ...record, turns: L.turn, hintLevel: L.hintLevel,
    hintUsed: Math.max(0, (L.hintLevel || 0) - (L.hintAuto || 0)),
  });
  L.qi++;
  L.turn = 0;
  L.turns = [];
  L.hintLevel = 0;
  L.hintAuto = 0;
  L.hintsSeen = [];
  L.notesShown = [];
  // 사다리는 질문에 딸린 상태다. 안 비우면 다음 질문이 지난 질문의 분모를 물려받는다.
  L.hintList = [];
  L.halfShown = false;
  L.halfGist = '';
  L.lastJudgement = null;
  L.judgeFailed = false;
  // 다시 말하기 모드는 질문에 딸린 상태다. 안 지우면 다음 질문이 「이제 내 말로」
  // 카드로 열려 사용자가 보지도 않은 답을 다시 말하라는 화면이 된다.
  L.retell = null;
}

/**
 * 질문 하나를 닫는다. **끝났다는 말은 한 번만 한다.**
 *
 * 예전에는 닫는 자리에 네 덩어리가 따로 쌓였다 — 판정 말풍선(「제대로
 * 설명했어요」) · 표식(「수면 주기 — 설득 완료」) · 총평 카드(「총평에
 * 적혔어요」) · 모범답 말풍선(「이렇게 답하면 좋았어요」). 앞의 셋은 어휘만
 * 다르지 같은 뜻이라 세 번째는 아무도 안 읽었고, 넷째는 하필 **상대 아바타를
 * 달고** 맨 끝에 서서 «교수가 아직 말을 걸고 있다» 로 읽혔다. 대화는 이미
 * 판정에서 닫혔는데 UI 만 계속 이어지는 모양이었다 (2026-08-10 사용자).
 *
 * 그래서 표식·총평·모범답을 **아바타 없는 마무리 카드 한 장**으로 묶는다.
 * 아바타가 없다는 것 자체가 «이건 발화가 아니라 정리다» 라는 신호다.
 * 판정 말풍선은 그대로 둔다 — 실제로 대화가 닫히는 순간이 거기라서다.
 *
 * 전체 화면 학습 카드로 갈아타지 않는 것은 그대로다 (2026-08-07 사용자 요청).
 */
/** 닫힌 까닭별 마무리 카드 칩 — good 은 판정 낱말 그대로, 3라운드 출구는 그렇다고 말한다 (결과 화면 칩과 같은 말) */
const CLOSE_CHIP = { rounds: '세 번째에 넘어갔어요', guard: '자료와 다시 맞춰 봐요' };

function finishLiveQuestion(q, v, answer) {
  const L = qa.live;
  const m = LIVE_VERDICT[v.verdict] || LIVE_VERDICT.unknown;
  // 왜 닫혔나 — good(설득) · rounds(3라운드에서 통과 수준) · guard(가드에 막힌 채 3라운드). 결과 화면이 나눠 센다 (09-30 §10)
  const closeReason = v.close_reason || (v.verdict === 'good' ? 'good' : 'rounds');
  // 함정의 골자는 화면 사본에 없다(gist_withheld) — 닫힌 판정 응답이 싣고 온다 (09-30 WP-J2)
  const closeGist = v.answer_gist || q.answer_gist || '';
  pushTurn({
    who: 'sys', kind: 'done',
    flag: m.flag, outcome: v.verdict, word: CLOSE_CHIP[closeReason] || m.word,
    concept: q.node_id, label: escapeHtml(q.label),
    summary: v.summary_sentence || '',
    // 좋은 답(good)으로 닫혔으면 「이렇게 답하면 좋았어요」 를 붙이지 않는다 — 방금 한 답보다 못한 골자(라벨 나열)가
    // 뜨곤 했다 (09-30 held-out M-10). 되묻기 도중 이미 펼친 문장이어도 다시 싣지 않는다 (revealHalf 가 halfGist 를 남긴다).
    gist: (closeReason !== 'good' && closeGist && closeGist !== L.halfGist) ? escapeHtml(liveWholeSentences(closeGist)) : '',
    // 카드 발치에 «몇 번째가 닫혔고 다음이 있는가» 를 적는다. 끝이 보이지 않으면
    // 사용자는 이 카드가 마무리인지 중간 안내인지 구분할 수 없다.
    idx: L.qi + 1, total: L.questions.length,
  });
  closeLiveQuestion({
    id: q.id, label: q.label, question: q.question, answer,
    verdict: v.verdict, score: v.score || 0, passed: !!v.passed,
    // 「연속 정복」·퀘스트 표식이 이 값을 센다. passed 로 세면 답을 보고 넘어간
    // 질문까지 연속에 들어가 숫자가 거짓말을 한다.
    mastered: true,
    closeReason,
    // 「모르겠어요」 코칭(보기·빈칸)을 거쳐 닫혔나 — 결과에서 「도움 받아 닫힘」 으로 센다 (liveBucket · 09-30 C-09)
    viaCoach: (L.turns || []).some((t) => t.gaveUp),
    summary: v.summary_sentence || '',
  });
}

/**
 * 「답 보고 다시 말해보기」 — **답만 보여 주고 질문을 닫지 않는다.**
 *
 * 예전에는 답을 띄우고 곧바로 다음 질문으로 넘어갔다. 그러면 사용자는 답을
 * **읽기만 하고 한 번도 말해 보지 않은 채** 그 개념을 지나친다. 읽은 것은
 * 다음에 안 나온다 — 자기 입으로 한 번 나와야 남는다. 그래서 답을 펼친 뒤
 * 「이제 내 말로」 입력창을 그대로 열어 둔다.
 */
function revealLiveAnswer() {
  const L = qa.live;
  const q = L.questions[L.qi];
  const v = L.lastJudgement || {};
  const last = L.turns[L.turns.length - 1] || {};
  if (L.busy) return;
  pushTurn({ who: 'sys', kind: 'lost', text: `${escapeHtml(q.label)} — 답을 펼쳐 볼게요` });
  const record = {
    id: q.id, label: q.label, question: q.question, answer: last.answer || '',
    verdict: v.verdict || 'unknown', score: v.score || 0,
    passed: !!v.passed, mastered: false,
    summary: v.summary_sentence || '', revealed: true,
  };
  // 해설(explain 코칭)이 있으면 그게 낫다 — 이 사람이 실제로 막힌 지점에 맞춰
  // 쓴 글이라서다. 없으면 F-08 이 미리 만들어 둔 골자를 쓴다.
  const model = liveRevealModel(q, v);
  if (model || !liveNeedsReveal(q, v) || L.judgeFailed) {
    enterRetell(model || v.summary_sentence, record);
    growStream();
    refreshLiveChrome();
    return;
  }
  // 함정 질문의 골자는 화면 사본에 없다(브리지 client_questions · 09-30 WP-J2) — 펼치겠다고 누른 지금 서버에서 받는다.
  // 판정이 아니라 LLM 을 안 부르는 reveal 요청이라 곧바로 온다. 실패하면 총평으로 물러난다(서버 없이도 다음 질문으로 간다).
  L.busy = true;
  setLiveBusy(true);
  showCoachThinking();
  liveFetchReveal(q).then((gist) => {
    hideCoachThinking();
    L.busy = false;
    setLiveBusy(false);
    if (qa.live !== L || L.questions[L.qi] !== q || L.retell) return;
    enterRetell(gist || v.summary_sentence, record);
    saveSession('qa-flow', qa);
    growStream();
    refreshLiveChrome();
  });
}

/**
 * 다시 말하기·펼치기에 쓸 기대 답 — 해설(explain) → 판정 응답의 골자(함정은 바로잡았거나 닫혔을 때만 서버가 싣는다) → 질문의 골자.
 * 함정 질문은 질문 사본에 골자가 없다(gist_withheld · 09-30 WP-J2). 없으면 ''.
 */
function liveRevealModel(q, v) {
  const j = v || {};
  return j.explanation || j.answer_gist || (q && q.answer_gist) || '';
}

/** 펼칠 골자를 서버에서 받아 와야 하는가 — 화면 사본에서 뺀 함정 질문(gist_withheld)인데 판정 응답에도 아직 없다 */
function liveNeedsReveal(q, v) {
  return !!(q && q.gist_withheld) && !liveRevealModel(q, v);
}

/**
 * 화면에 없는 함정의 기대 답을 서버에서 받는다 — 「답 보고 다시 말해보기」 를 누른 때만 (09-30 WP-J2). 브리지 판정 경로의 reveal 요청이라
 * LLM 을 부르지 않고 기록도 안 남는다. 실패하면 '' — 호출자가 총평으로 물러난다.
 */
async function liveFetchReveal(q) {
  const L = qa.live || {};
  const bridge = window.ChuckchuckBridge;
  if (!q || !bridge || typeof bridge.qaApiBase !== 'function' || typeof fetch !== 'function') return '';
  const sid = L.sessionId || 'flat';
  try {
    const res = await fetch(`${bridge.qaApiBase()}/api/v1/sessions/${encodeURIComponent(sid)}/qa/judge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sid, question_id: q.id, question: q, answer: '', reveal: true }),
    });
    const data = await res.json().catch(() => ({}));
    return res.ok && data && typeof data.answer_gist === 'string' ? data.answer_gist : '';
  } catch (_) {
    return '';
  }
}

/**
 * 다시 말한 답으로 질문을 닫는다. **판정하지 않는다** — 답을 본 뒤에 말한 것을
 * 채점하면 스스로 방어한 것과 구분이 안 되어 리포트가 부풀려진다. 그래서
 * passed 는 거짓으로 두고 `revealed`·`retold` 로 남긴다. 대신 왕복이 없어
 * 반응이 즉시 온다 — 답한 보람은 기다림 없이 오는 것이 맞다.
 */
function closeRetell(text) {
  const L = qa.live;
  if (!L || !L.retell) return;
  const q = L.questions[L.qi];
  const said = (text || '').trim();
  if (said) {
    pushTurn({ who: 'me', kind: 'say', text: escapeHtml(said) });
    pushTurn({
      who: 'sys', kind: 'won',
      text: `${escapeHtml(q.label)} — 한 번 말해 봤어요. 리포트에서 같이 다시 볼게요`,
    });
  } else {
    pushTurn({ who: 'sys', kind: 'lost', text: `${escapeHtml(q.label)} — 답만 보고 넘어갔어요` });
  }
  // 들어올 때 만들어 둔 기록을 그대로 닫는다 (enterRetell 참고). 옛 세션이
  // record 없이 복원됐으면 최소한으로 채워 — 여기서 죽으면 질문에 갇힌다.
  const base = L.retell.record || {
    id: q.id, label: q.label, question: q.question,
    verdict: 'unknown', score: 0, passed: false, mastered: false,
    summary: '', revealed: true,
  };
  L.retell = null;
  closeLiveQuestion({ ...base, answer: said || base.answer || '', retold: !!said });
  saveSession('qa-flow', qa);
  advanceLiveStream();
}

/**
 * 지금 질문의 힌트 사다리. 출처가 둘이라 **긴 쪽**을 쓴다.
 *
 * 질문과 함께 오는 3단계(방향·범위·접근)와, 판정이 붙여 주는 4단계(+근접)가 있다.
 * 둘 다 서버의 같은 `build_hint_ladder` 에서 나와 앞 세 칸이 일치하므로,
 * 이미 본 단계 번호가 사다리를 갈아타도 어긋나지 않는다. 길이로 고르는 이유는
 * 짧은 쪽으로 내려가면 소비한 인덱스가 무효가 되기 때문이다.
 *
 * **판정본을 그때그때 읽지 않고 `L.hintList` 에 쌓아 둔 것을 읽는다.** 판정 사다리는
 * 턴마다 길이가 달라서(중복 제거가 4단을 3단으로 만든다) 직접 읽으면 한 질문 안에서
 * 분모가 줄었다 — "힌트 2/4" 다음에 "힌트 3/3". 위 문단이 막으려던 것이 바로 그건데,
 * 비교 대상이 **직전에 보여준 길이가 아니라 `built`** 여서 못 막고 있었다.
 * 이제 `submitLiveAnswer` 가 더 긴 것만 채택하고, 질문이 끝날 때 비운다.
 */
function liveHints() {
  const L = qa.live;
  const kept = (L && L.hintList) || [];   // 옛 저장 세션엔 없다 → built 로 떨어진다
  const built = liveQuestionHints();
  return kept.length >= built.length ? kept : built;
}

/**
 * 질문이 들고 온 사다리(방향·범위·접근). 판정과 달리 **길이가 안 변한다** —
 * "힌트를 다 썼는가" 를 잴 때는 이 고정된 길이를 기준으로 삼아야 한다.
 *
 * `q.hint` 폴백은 서버 없이 도는 데모 질문용이다 — 그 길엔 사다리가 없다.
 */
function liveQuestionHints() {
  const L = qa.live;
  const q = L.questions[L.qi];
  return (q && q.hints) || (q && q.hint ? [q.hint] : []);
}

/* ── 결과 화면 — 네 묶음 (09-30 held-out C-09) ─────────────────────────────
   예전 결과는 판정 등급(good·partial)만 보고 「지켜낸 질문 · 자기 말로 방어한 것」 에 넣었다 — 3라운드 강제 닫힘·힌트
   셋째 칸(정답 인용)을 보고 옮긴 답·보기를 골라 닫은 답까지. 헤드라인 「질문 7개를 끝까지 받아 냈어요」 는 넘김·요청 제한도 셌다.
   이제 liveBucket 의 네 묶음으로 나누고, 헤드라인 숫자는 **스스로 설명(self)만** 센다. */
const LIVE_RESULT_GROUPS = [
  { key: 'helped', title: '도움 받아 닫은 질문', hint: '힌트·보기·세 번째 답으로 닫았어요' },
  { key: 'retold', title: '답을 보고 다시 말한 질문', hint: '답을 본 뒤 내 말로 말해 봤어요' },
  { key: 'skipped', title: '넘기거나 안 물은 질문', hint: '답하지 않았거나 묻기 전에 마쳤어요' },
  { key: 'self', title: '스스로 설명한 질문', hint: '힌트·보기 없이 내 말로 닫았어요' },
];
const LIVE_STAT_WORD = { self: '스스로 설명', helped: '도움 받아 닫음', retold: '답 보고 다시 말함', skipped: '넘김·안 물음' };

/**
 * 결과 한 줄의 칩·곁말. 한 줄이 스스로 모순되지 않게 묶음마다 따로 쓴다 (「설명 못함 · … · 5번 만에 방어」 가 한 줄에 있었다).
 * 리포트 「질문 코칭 내역」(app.js qaHistoryPanelHtml)도 저장한 묶음(bucket)을 넘겨 같은 말을 쓴다.
 */
function liveResultRow(r, bucket = liveBucket(r)) {
  const used = liveHintsUsed(r);
  if (bucket === 'self') {
    const how = (r.turns || 0) <= 1 ? '첫 답에 설명했어요' : `${r.turns}번 만에 설명했어요`;
    return { bucket, chip: '스스로 설명', cls: 'st-ok', meta: used ? `${how} · 힌트 ${used}번 봤어요` : how };
  }
  if (bucket === 'helped') {
    const why = [];
    if (r.closeReason === 'rounds' || (liveForcedClose(r) && r.closeReason !== 'guard')) why.push('세 번째 답에서 닫혔어요');
    if (r.closeReason === 'guard') why.push('자료와 다시 맞춰 볼 곳이 남았어요');
    if (r.viaCoach) why.push('보기·빈칸 도움으로 닫았어요');
    if ((r.hintLevel || 0) >= LIVE_HINT_HELP) why.push(`힌트 ${r.hintLevel}칸까지 봤어요`);
    return { bucket, chip: '도움 받아 닫힘', cls: 'st-mid', meta: why.slice(0, 2).join(' · ') };
  }
  if (bucket === 'retold') return { bucket, chip: '답 보고 다시 말함', cls: 'st-om', meta: '답을 보고 내 말로 다시 말했어요' };
  if (r.unasked) return { bucket, chip: '안 물음', cls: 'st-om', meta: '묻기 전에 마쳤어요' };
  if (r.stopped) return { bucket, chip: '멈춤', cls: 'st-om', meta: `답 ${r.answers || r.turns || 1}번 하고 멈췄어요` };
  if (r.revealed) return { bucket, chip: '답만 봄', cls: 'st-om', meta: '답만 보고 넘어갔어요' };
  return { bucket, chip: '넘김', cls: 'st-om', meta: '답하지 않고 넘겼어요' };
}

/**
 * 결과 머리 — 헤드라인 숫자는 스스로 설명한 것만 (C-09). speech: 상세 리포트에 발화 분석이 있는가 (자료만 쓴 세션은 없다 —
 * 「근거 발화와 함께 짚어 줄게요」 는 그때만 약속한다).
 */
function liveResultSummary(results, { speech = true, unrelated = false } = {}) {
  const rs = results || [];
  const count = { self: 0, helped: 0, retold: 0, skipped: 0 };
  rs.forEach((r) => { count[liveBucket(r)] += 1; });
  const asked = rs.filter((r) => !r.unasked).length;
  const self = count.self;
  const allSelf = asked > 0 && self === asked;
  const head = !asked
    ? '질문에 답하면 여기에 결과가 쌓여요'
    : allSelf
      ? (asked === 1 ? '질문 하나를 스스로 설명했어요' : `질문 <b class="num" data-count="${asked}">${asked}</b>개를 모두 스스로 설명했어요`)
      : self
        ? `질문 ${asked}개 중 <b class="num" data-count="${self}">${self}</b>개를 스스로 설명했어요`
        /* 0 을 앞세우지 않는다 — 박수가 먼저, 숫자는 그 뒤 (UI_REDESIGN §6). 성취로 세지도 않는다: 연습할 질문을 찾은 것이다 */
        : `다음엔 스스로 설명해 볼 질문 <b class="num qres-redo" data-count="${asked}">${asked}</b>개를 찾았어요`;
  const stats = allSelf || !asked ? [] : ['self', 'helped', 'retold', 'skipped']
    .filter((k) => k === 'self' || count[k] > 0).map((k) => ({ key: k, n: count[k], word: LIVE_STAT_WORD[k] }));
  const hinted = rs.filter((r) => liveBucket(r) === 'self' && liveHintsUsed(r) > 0).length;
  const sub = !asked ? ''
    : allSelf
      ? (hinted ? `힌트를 본 질문이 ${hinted}개 있어요. 같은 질문으로 한 번 더 하면 힌트 없이도 될 거예요.` : '힌트 없이 전부 스스로 설명했어요. 같은 질문으로 한 번 더 하면 답이 더 짧아져요.')
      : speech && !unrelated
        ? '다시 볼 곳은 상세 리포트에서 근거 발화와 함께 짚어 줄게요.'
        /* 녹음은 받았는데 이 자료의 발표가 아니었다 — 「발표를 녹음하면」 이 아니라 맞는 녹음을 올리면이다 (09-30 REC-10) */
        : unrelated
          ? '상세 리포트에 질문마다 내 답을 남겨 뒀어요. 이 자료로 발표한 녹음을 올리면 말과 자료를 같이 짚어 줘요.'
          : '상세 리포트에 질문마다 내 답을 남겨 뒀어요. 발표를 녹음하면 말과 자료를 같이 짚어 줘요.';
  return { count, asked, self, allSelf, head, stats, sub };
}

function qaLiveEnd() {
  // 통화 배치로 코칭했으면 층과 카메라를 거둔다 — 결과 화면은 일반 배치다
  if (typeof callFlowUnmount === 'function') callFlowUnmount();
  qa.ended = true;
  // 발표 플로우도 끝난 걸로 표시 — 홈/이어하기에서 리포트로 이어지게
  if (typeof nf !== 'undefined' && nf) {
    nf.completed = true;
    saveSession('new-flow', nf);
  }
  saveSession('qa-flow', qa);
  // 저장 성공 여부를 상단 라벨이 그대로 말한다 — 실패했는데 "저장됨" 이라고
  // 하면 사용자는 기록이 있는 줄 알고 떠난다 (§14 정직한 상태 유지).
  const historySaved = recordQaHistory();
  const L = qa.live;
  // 상세 리포트에 개념 판정(발화 분석)이 있는가 — 자료만 쓴 세션은 없다. 없으면 행 화살표도 안 단다 (09-30 L-03: 빈 리포트로 데려갔다)
  const speech = typeof qaReportHasJudge === 'function' ? qaReportHasJudge() : true;
  const unrelated = typeof qaRecordingUnrelated === 'function' ? qaRecordingUnrelated() : false;
  /* 결과를 상태로 묶는다. 섞어 두면 "어디부터 손대야 하는지" 가 안 보인다.
     순서는 사용자가 다음에 할 일 순 — 도움 받은 것 → 답을 본 것 → 넘긴 것 → 스스로 한 것 */
  const grouped = { helped: [], retold: [], skipped: [], self: [] };
  (L.results || []).forEach((r, i) => grouped[liveBucket(r)].push({ r, i }));
  const sum = liveResultSummary(L.results, { speech, unrelated });

  /* 질문 원문은 길고 여섯 개가 다 "…설명해 주시겠어요?" 로 끝나 벽처럼 읽힌다.
     제목은 개념 이름으로, 질문은 한 줄로 줄여 보조 텍스트에 둔다 (TDS ListRow 2RowTypeA) */
  const oneLine = (s) => {
    const t = String(s || '').replace(/\s+/g, ' ').trim();
    return t.length > 62 ? `${t.slice(0, 61)}…` : t;
  };
  /* 행의 화살표는 "이 질문의 근거를 보여준다"는 약속이다. 예전에는 모든 행이
     #/report 맨 위로만 갔다 — 여섯 행에 화살표 여섯 개, 목적지는 하나.
     개념 이름이 그래프 노드와 맞으면 그 개념의 판정으로 데려가고,
     못 맞추면 화살표를 안 단다. 못 지킬 약속은 하지 않는다. */
  const nodeIdOf = (label) => {
    const g = (typeof nf !== 'undefined' && nf && nf.pipelineOut && nf.pipelineOut.graph) || null;
    const key = String(label || '').trim();
    if (!speech || !g || !key) return '';
    const hit = (g.nodes || []).find((n) => String(n.label || '').trim() === key);
    return hit ? hit.id : '';
  };
  const rowHtml = ({ r, i }) => {
    const node = nodeIdOf(r.label);
    const row = liveResultRow(r);
    return `
    <button class="qres-row${node ? '' : ' is-flat'}" type="button" data-qi="${i}"
            data-node="${escapeHtml(node)}"${node ? '' : ' disabled'}>
      <span class="qres-main">
        <b>${escapeHtml(r.label || `질문 ${i + 1}`)}</b>
        <small>${escapeHtml(oneLine(r.summary || r.question))}</small>
      </span>
      <span class="qres-side">
        <span class="chip chip-sm ${row.cls}">${row.chip}</span>
        ${row.meta ? `<em class="qres-meta">${escapeHtml(row.meta)}</em>` : ''}
      </span>
      ${node ? '<span class="qres-chev" aria-hidden="true">›</span>' : ''}
    </button>`;
  };

  const statHtml = sum.stats.length ? `
    <div class="qres-stats">
      ${sum.stats.map((st) => `<div><b class="num${st.key === 'self' ? '' : ' qres-redo'}" data-count="${st.n}">${st.n}</b><span>${st.word}</span></div>`).join('')}
    </div>` : '';

  app.innerHTML = `
    <div class="coach-nav"><a href="#/">← 내 발표로 나가기</a><span>${historySaved ? '코칭 기록 저장됨' : '기록을 저장하지 못했어요 — 화면을 캡처해 두세요'}</span></div>
    <div class="card cere-card qres">
      <p class="qres-eyebrow">실전 질문 코칭 결과</p>
      <!-- 숫자는 아래 묶음과 반드시 같아야 한다. 헤드라인·퀘스트 막대(liveWonCount)·리포트 「끝까지 설명」 이
           모두 liveBucket 의 self 를 센다 -->
      <h1 class="qres-head">${sum.head}</h1>
      ${statHtml}
      ${sum.sub ? `<p class="qres-sub">${sum.sub}</p>` : ''}
      ${L.results.length ? LIVE_RESULT_GROUPS.map((g) => (grouped[g.key].length ? `
        <div class="qres-group">
          <div class="qres-gh"><b>${g.title}</b><span class="num">${grouped[g.key].length}</span><small>${g.hint}</small></div>
          ${grouped[g.key].map(rowHtml).join('')}
        </div>` : '')).join('')
        : '<p class="note">첫 질문에 답하면 여기에 쌓여요.</p>'}
    </div>
    <div class="cere-actions">
      <a class="btn btn-primary" href="#/report">상세 리포트 보기</a>
      <button class="btn btn-text" id="liveAgain" type="button">같은 질문으로 다시</button>
      <a class="btn btn-text" href="#/">홈으로</a>
    </div>`;
  /* 행 전체가 눌린다 — TDS ListRow 는 누를 수 있으면 화살표와 터치 효과를 준다.
     goJudge 는 app.js 의 전역이고 이 파일보다 뒤에 실린다(index.html 64 < 68).
     그래서 파싱 때가 아니라 클릭 때 찾는다. 해시를 먼저 바꿔 리포트를 그린 뒤
     goJudge 가 탭과 개념을 고르고 그 행으로 스크롤한다. */
  /* 끝난 화면이 그냥 툭 떠 있으면 방금 여섯 번 답한 일이 아무 일도 아닌 게 된다.
     숫자는 굴러 올라가고 묶음은 차례로 들어온다 (app.js 전역, 없으면 그냥 건너뛴다) */
  if (typeof countUp === 'function') {
    $$('.qres .num[data-count]').forEach((el) => countUp(el, Number(el.dataset.count) || 0, 700));
  }
  if (typeof staggerIn === 'function') {
    staggerIn($$('.qres-head, .qres-stats, .qres-sub, .qres-group, .cere-actions'));
  }

  $$('.qres-row:not(.is-flat)').forEach((el) => el.addEventListener('click', () => {
    const node = el.dataset.node || '';
    location.hash = '#/report';
    if (node && typeof window.goJudge === 'function') {
      requestAnimationFrame(() => window.goJudge(node));
    }
  }));
  const again = $('#liveAgain');
  if (again) again.addEventListener('click', () => {
    const keep = qa.live;
    resetQa();
    // 같은 자료의 같은 질문을 다시 푸는 것이라 지문도 그대로 물려받는다.
    qa.live = newLiveState(keep.sessionId, keep.questions, keep.docKey || '');
    qa.started = true;
    saveSession('qa-flow', qa);
    renderQaLive();
  });
  window.scrollTo(0, 0);
}

/* #/qa 직접 진입: 시작 전에 시간 모드를 고르는 게이트 */
function qaModeGate() {
  app.className = 'narrow';
  app.innerHTML = `
    <div class="coach-nav"><a href="#/">← 내 발표로 나가기</a><span>시작 전 설정</span></div>
    <div class="card qa-quick">
      <div class="qm-head"><b>질문 코칭 시간을 골라주세요</b><span>시간에 맞춰 질문 범위를 짜요 — 짧을수록 치명적인 것만 다뤄요</span></div>
      ${qaModeButtonsHtml()}
      <!-- 범위·시간은 위 카드가 이미 말한다. CTA 에 또 붙이면 버튼의 역할이
           흐려진다 — 토스 다크패턴 §5 "CTA 위에 중복된 보조 설명" -->
      <button class="btn btn-primary" id="qaGateStart" type="button">질문 코칭 시작하기</button>
    </div>`;
  wireQaModeButtons(qaModeGate);
  // 고르는 동안 지금 골라진 시간의 질문을 미리 만든다 (app.js prefetchLiveQuestions)
  if (typeof prefetchLiveQuestions === 'function') prefetchLiveQuestions(qa.mode || '10');
  $('#qaGateStart').addEventListener('click', () => {
    qa.started = true;
    saveSession('qa-flow', qa);
    renderQa();
  });
}
