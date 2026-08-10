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

function liveHistory() {
  const L = qa.live;
  const done = (L.results || []).map((r) => ({
    질문: r.question, 답변: r.answer, 판정: r.verdict, 포기: !!r.gaveUp,
  }));
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
  return done.concat(current);
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
  for (let i = rs.length - 1; i >= 0; i--) {
    if (!rs[i].mastered || rs[i].revealed) break;
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
function stuckLabel() {
  const L = qa.live;
  // 두 번째 「모르겠어요」는 이제 넘어가기가 아니라 **답 보기**다 — 서버가 해설을
  // 풀어 주고, 그걸 보고 한 번 말해 본 뒤에 닫힌다 (coachedRetell).
  // CTA 문구만 보고 다음에 무슨 일이 벌어질지 예측돼야 한다 (CLAUDE.md §3-1).
  return (L.turns || []).some((t) => t.gaveUp)
    ? '그래도 모르겠어요 · 답 보기'
    : '모르겠어요';
}

/* ── 개념 퀘스트 (왼쪽 칸) ──────────────────────────────────────────────────
   질문 하나 = 개념 하나다 (F-08 규칙 2: "대상마다 정확히 하나씩"). 그래서 질문
   목록을 그대로 세우면 «오늘 채워야 할 개념 목록»이 된다. 지나온 것·지금 것·
   남은 것이 한눈에 보여야 대화가 길어져도 어디쯤인지 안 잃는다.

   판정 낱말은 새로 짓지 않는다. 바로 오른쪽 스트림이 `${label} — 설득 완료` 라고
   말하는데 여기서 «정복» 이라고 부르면 한 화면에서 같은 일이 두 이름이 된다.
   게임 느낌은 낱말이 아니라 **줄 세우기·현재 표식·남은 줄 흐리기**로 낸다. */
const QUEST_WORD = {
  won: '설득했어요',
  part: '절반만 설득했어요',
  /* 「미방어」는 한자어에 부정형이다. 지나간 일을 이름 붙이는 대신
     지금 할 수 있는 일로 말한다 (토스 UX 라이팅 §3 긍정적 말하기) */
  lost: '다시 설명해요',
  skip: '넘겼어요',
  now: '지금 답하고 있어요',
  next: '곧 물어봐요',
};
const QUEST_MARK = { won: '✓', part: '✓', lost: '✕', skip: '—', now: '▶', next: '' };

/** 질문 하나의 지금 상태. results 는 닫힌 순서대로 쌓이지만 id 로 맞춘다. */
function questState(q, i) {
  const L = qa.live;
  if (i > L.qi) return 'next';
  if (i === L.qi) return 'now';
  const byId = q.id != null && (L.results || []).find((r) => r.id === q.id);
  const r = byId || (L.results || [])[i] || {};
  if (r.gaveUp || r.revealed) return 'skip';
  // mastered 가 없는 옛 세션은 passed 로 읽는다 — 그때는 그게 닫는 기준이었다.
  const closed = r.mastered === undefined ? r.passed : r.mastered;
  if (closed) return r.verdict === 'partial' ? 'part' : 'won';
  return 'lost';
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
      ${streak >= 2 ? `<p class="quest-streak"><b>${streak}개 연속</b>으로 지켰어요</p>` : ''}
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
          const clean = st === 'won' && !r.hintLevel ? '<em class="qrow-clean">힌트 없이</em>' : '';
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

function presentLiveQuestion() {
  const L = qa.live;
  if (L.asked === L.qi) return;
  L.asked = L.qi;
  const q = L.questions[L.qi];
  pushTurn({
    who: 'ai',
    kind: q.trap ? 'claim' : 'question',
    meta: `예상 질문 ${L.qi + 1}/${L.questions.length} · ${SEVERITY_LINE[q.severity] || '보통이에요'}`,
    text: escapeHtml(q.question),
    basis: q.why ? escapeHtml(q.why) : '',
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
      <span>${L.questions.length}개 중 ${won}개를 자기 말로 지켰어요</span>
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

/** 힌트 한 칸 열기. 사용자가 눌러도, 라운드가 올라 자동으로 열려도 여기로 온다. */
function openNextHint({ auto = false } = {}) {
  const L = qa.live;
  const list = liveHints();
  if (L.hintLevel >= list.length) return false;
  L.hintLevel += 1;
  const text = list[L.hintLevel - 1];
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
    <div class="msg-bubble"><i class="dots" aria-hidden="true"><b></b><b></b><b></b></i><span>듣고 있어요</span></div>`;
  s.appendChild(el);
  scrollDown();
}

function hideCoachThinking() {
  const el = $('#coachThinking');
  if (el) el.remove();
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
  const modelAnswer = v.explanation || q.answer_gist || v.summary_sentence || '핵심 근거를 먼저 말하고, 자료의 수치나 사례로 뒷받침해 보세요.';
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

/** 남은 질문을 넘김 처리하고 결과 → 리포트 CTA 화면으로 */
function finishLiveQaEarly() {
  const L = qa.live;
  if (!L || L.busy) return;
  while (L.qi < L.questions.length) {
    const q = L.questions[L.qi];
    pushTurn({ who: 'sys', kind: 'lost', text: `${escapeHtml(q.label)} — 오늘은 넘겼어요. 리포트에 남겨둘게요` });
    closeLiveQuestion({
      id: q.id, label: q.label, question: q.question, answer: '(넘김)',
      verdict: 'skipped', score: 0, passed: false, mastered: false, summary: '',
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
          micSay(`${escapeHtml(msg)} — 마이크를 한 번 더 누르면 녹음해서 받아쓸게요. 타이핑으로 답하셔도 됩니다`);
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
    micSay(`마이크를 못 열었어요: ${escapeHtml(err.message || String(err))} — 타이핑으로 답하셔도 됩니다`);
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
    const text = await window.ChuckchuckBridge.transcribeAnswer(await mic.session.stop());
    if (text) fillLiveAnswer(text);
    else micSay('말소리를 못 알아들었어요 — 다시 녹음하거나 타이핑으로 답해 주세요');
  } catch (err) {
    micSay(`받아쓰기에 실패했어요: ${escapeHtml(err.message || String(err))} — 타이핑으로 답하셔도 됩니다`);
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

async function submitLiveAnswer({ giveUp = false } = {}) {
  const L = qa.live;
  // 녹음 중 전송을 허용하면 화면이 다시 그려지며 마이크 버튼이 사라지고,
  // 녹음은 아무도 안 멈추는 채로 남는다.
  if (liveMic) {
    micSay('녹음 중이에요 — 먼저 멈추고 받아쓴 뒤에 보내 주세요');
    return;
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
  pushTurn({ who: 'me', kind: 'say', text: escapeHtml(answer) });
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
  try {
    const v = await window.ChuckchuckBridge.judgeQaAnswer(L.sessionId, {
      questionId: q.id, answer, history: liveHistory(), question: q, giveUp,
      // 이 질문에 앞서 낸 답들. 판정은 누적 전체를 본다 (f09 "합쳐서 판정하라").
      // 포기 턴의 "(모르겠어요)" 자리표시자는 답이 아니라 뺀다.
      priorAnswers: (L.turns || []).filter((t) => !t.gaveUp).map((t) => t.answer),
      // 지금까지 펼쳐 본 힌트. 코치가 힌트와 이어지는 말로 반응한다.
      hintsShown: liveHints().slice(0, L.hintLevel || 0),
      artifacts: liveArtifacts(),
    });
    const m = LIVE_VERDICT[v.verdict] || LIVE_VERDICT.unknown;
    L.turn += 1;
    L.turns.push({ question: askedNow, questionId: q.id, answer, verdict: v.verdict, score: v.score || 0, gaveUp: giveUp });
    L.lastJudgement = v;
    // 판정 사다리가 지금 들고 있는 것보다 길면 그걸로 갈아탄다. **짧아져도 안 버린다** —
    // 버리면 다음 말풍선의 분모가 줄어 "힌트 2/4" 뒤에 "힌트 3/3" 이 뜬다.
    const judgedHints = Array.isArray(v.hints) ? v.hints : [];
    if (judgedHints.length > ((L.hintList || []).length)) L.hintList = judgedHints;
    L.judgeFailed = false;
    hideCoachThinking();
    if (v.react) {
      // 점수를 같이 싣는다. 「좋아지고 있다」는 말보다 62 → 78 이라는 진짜 숫자가
      // 세다 (UI_REDESIGN §14 — 숫자는 신성하다, 지어내지 않는다).
      pushTurn({
        who: 'ai', kind: 'react', verdict: m.react, text: escapeHtml(v.react),
        score: v.score || 0, before,
        // 「모르겠어요」에 온 응답은 **판정이 아니다** — 서버가 점수를 안 매기고
        // verdict 자리에 폴백을 넣어 보낸다 (f09_judge.coach_stuck). 그걸 판정표로
        // 그리면 솔직하게 모르겠다고 누른 사람이 틀린 답과 똑같은 빨간 칩을 받는다.
        // 단계를 그대로 실어서 «지금 무슨 일이 일어나는지» 를 대신 적는다.
        coach: v.coach_stage || '',
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
      askAgain(v, L.turn, { skipMissing: shownMissing });
    }
  } catch (err) {
    hideCoachThinking();
    // 「모르겠어요」도 판정을 타므로, 서버가 죽으면 이 질문에 갇힌다.
    // 아래 렌더에서 「답 보고 다시 말해보기」가 열려 서버 없이 다음 질문으로 간다.
    L.judgeFailed = true;
    failedAnswer = giveUp ? '' : answer;   // 포기 자리표시자는 되살릴 답이 아니다
    // 자료 정보가 통째로 사라진 경우는 다시 눌러도 똑같이 실패한다. 「다시
    // 시도」로 유도하면 같은 자리를 맴돌 뿐이라, 원인과 빠져나갈 길을 따로 낸다.
    pushTurn({
      who: 'sys',
      kind: 'lost',
      text: err.code === 'session_missing'
        ? '자료 정보가 사라져서 판정할 수 없어요. <a href="#/new">자료를 다시 올리면</a> 이어서 할 수 있어요 — 지금은 「답 보고 다시 말해보기」로 다음 질문에 갈 수 있어요'
        : `판정 실패: ${escapeHtml(err.message || String(err))} — 다시 시도하거나 「답 보고 다시 말해보기」로 다음 질문에 갈 수 있어요`,
    });
  }
  L.busy = false;
  saveSession('qa-flow', qa);
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
  enterRetell(v.explanation || q.answer_gist || v.summary_sentence, {
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
  const text = (model || '').trim()
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
  return (results || []).filter((r) => {
    if (r.gaveUp || r.revealed) return false;
    return r.mastered === undefined ? !!r.passed : !!r.mastered;
  }).length;
}

/* 되묻기 머리말. 서버가 좁혀 온 단계를 말로 옮긴다 — 같은 「이어서 묻습니다」를
   세 번 붙이면 사용자는 질문이 좁아진 걸 못 알아채고 벽에 세 번 부딪힌 걸로 읽는다. */
const TIER_META = {
  probe: '이어서 묻습니다',
  focus: '좁혀서 다시 묻습니다',
  converge: '마지막 한 걸음이에요',
};

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
      meta: `${TIER_META[tier] || TIER_META.probe} · ${turn + 1}번째 답변`,
      text: escapeHtml(v.followup),
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
  const answer = v.explanation || q.answer_gist || v.summary_sentence || '';
  // 둘 다 비면 열 것이 없다. 빈 카드를 띄우느니 되묻기만 이어 간다.
  if (!points.length && !answer) return false;
  L.halfShown = true;
  // 닫을 때 같은 문장을 또 띄우지 않기 위해 원문을 남긴다 (finishLiveQuestion).
  L.halfGist = answer;
  if (points.length) pushTurn({ who: 'ai', kind: 'missing', points: points.map(escapeHtml) });
  if (answer) pushTurn({ who: 'ai', kind: 'gist', mid: true, text: escapeHtml(answer) });
  return points.length > 0;
}

function closeLiveQuestion(record) {
  const L = qa.live;
  L.results.push({ ...record, turns: L.turn, hintLevel: L.hintLevel });
  L.qi++;
  L.turn = 0;
  L.turns = [];
  L.hintLevel = 0;
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
function finishLiveQuestion(q, v, answer) {
  const L = qa.live;
  const m = LIVE_VERDICT[v.verdict] || LIVE_VERDICT.unknown;
  pushTurn({
    who: 'sys', kind: 'done',
    flag: m.flag, outcome: v.verdict, word: m.word,
    concept: q.node_id, label: escapeHtml(q.label),
    summary: v.summary_sentence || '',
    // 되묻기 도중 이미 펼친 문장이면 다시 싣지 않는다 — 한 질문의 스트림에 같은
    // 완성 문장이 두 번 뜨면 두 번째는 안 읽는다 (revealHalf 가 halfGist 를 남긴다).
    gist: (q.answer_gist && q.answer_gist !== L.halfGist) ? escapeHtml(q.answer_gist) : '',
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
  pushTurn({ who: 'sys', kind: 'lost', text: `${escapeHtml(q.label)} — 답을 펼쳐 볼게요` });
  // 해설(explain 코칭)이 있으면 그게 낫다 — 이 사람이 실제로 막힌 지점에 맞춰
  // 쓴 글이라서다. 없으면 F-08 이 미리 만들어 둔 골자를 쓴다.
  enterRetell(v.explanation || q.answer_gist || v.summary_sentence, {
    id: q.id, label: q.label, question: q.question, answer: last.answer || '',
    verdict: v.verdict || 'unknown', score: v.score || 0,
    passed: !!v.passed, mastered: false,
    summary: v.summary_sentence || '', revealed: true,
  });
  growStream();
  refreshLiveChrome();
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

function qaLiveEnd() {
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
  const chipCls = { good: 'st-ok', partial: 'st-mid', wrong: 'st-no', unknown: 'st-om', skipped: 'st-om' };
  const chipWord = { good: '설득 완료', partial: '부분 인정', wrong: '미방어', unknown: '보류', skipped: '넘김' };
  /* 결과를 상태로 묶는다. 섞어 두면 "어디부터 손대야 하는지" 가 안 보인다.
     순서는 사용자가 다음에 할 일 순 — 다시 볼 것 → 넘긴 것 → 이미 지킨 것 */
  const bucketOf = (r) => {
    if (r.revealed || r.verdict === 'skipped') return 'skipped';
    if (r.verdict === 'good' || r.verdict === 'partial') return 'won';
    return 'redo';
  };
  const GROUPS = [
    { key: 'redo', title: '다시 볼 질문', hint: '자료엔 있는데 말로 못 지킨 것' },
    { key: 'skipped', title: '넘긴 질문', hint: '답을 보거나 건너뛴 것' },
    { key: 'won', title: '지켜낸 질문', hint: '자기 말로 방어한 것' },
  ];
  const grouped = { redo: [], skipped: [], won: [] };
  (L.results || []).forEach((r, i) => grouped[bucketOf(r)].push({ r, i }));
  const redoCount = grouped.redo.length + grouped.skipped.length;

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
    if (!g || !key) return '';
    const hit = (g.nodes || []).find((n) => String(n.label || '').trim() === key);
    return hit ? hit.id : '';
  };
  const rowHtml = ({ r, i }) => {
    const node = nodeIdOf(r.label);
    return `
    <button class="qres-row${node ? '' : ' is-flat'}" type="button" data-qi="${i}"
            data-node="${escapeHtml(node)}"${node ? '' : ' disabled'}>
      <span class="qres-main">
        <b>${escapeHtml(r.label || `질문 ${i + 1}`)}</b>
        <small>${escapeHtml(oneLine(r.summary || r.question))}</small>
      </span>
      <span class="qres-side">
        <!-- 답을 본 질문도 둘로 갈린다. 보고 나서 한 번 말해 본 것과 보기만 한 것은
             다음에 할 일이 다르다 — 뭉뚱그려 「답 확인」 이라고 하면 그게 안 보인다 -->
        <span class="chip chip-sm ${chipCls[r.verdict] || 'st-om'}">${r.revealed ? (r.retold ? '다시 말했어요' : '답만 봤어요') : (chipWord[r.verdict] || r.verdict)}</span>
        ${r.turns ? `<em class="qres-meta">${r.turns}번 만에${r.hintLevel ? ` · 힌트 ${r.hintLevel}단계` : ''}</em>` : ''}
      </span>
      ${node ? '<span class="qres-chev" aria-hidden="true">›</span>' : ''}
    </button>`;
  };

  /* 남은 게 0개일 때 「0개가 남았어요」 + 「남은 질문은 리포트에서 보세요」는
     없는 것을 가리킨다. 숫자가 문제가 아니라 다음에 할 일이 안 남는 게 문제다
     (2026-08-07 사용자, 리포트 100% 건과 같은 지적). 이길 때 쓴 힌트로 잇는다. */
  const wonRs = grouped.won.map((x) => x.r);
  const hinted = wonRs.filter((r) => r.hintLevel).length;
  const allWon = redoCount === 0 && wonRs.length > 0;
  // 「1개 전부」는 한국어가 안 된다. 하나일 때만 말을 바꾼다
  /* 「0개를 지켰고 1개가 남았어요」로 끝나면, 방금 질문을 끝까지 받아 낸 사람이
     0 이라는 숫자부터 본다. 실패 통보가 아니라 연습 결과다 — 한 일을 먼저 말하고
     남은 것은 「찾은 것」으로 말한다 (UI_REDESIGN §6: 박수가 먼저, 숫자는 그 뒤).
     숫자를 줄이거나 부풀리지는 않는다. 순서와 이름만 바꾼다. */
  const total = (L.results || []).length;
  const headHtml = allWon
    ? (wonRs.length === 1
        ? '질문 하나를 자기 말로 지켰어요'
        : `<b class="num" data-count="${wonRs.length}">${wonRs.length}</b>개를 모두 자기 말로 지켰어요`)
    : `질문 <b class="num" data-count="${total}">${total}</b>개를 끝까지 받아 냈어요`;
  const statHtml = allWon ? '' : `
    <div class="qres-stats">
      <div><b class="num" data-count="${grouped.won.length}">${grouped.won.length}</b><span>자기 말로 지킨 질문</span></div>
      <div><b class="num qres-redo" data-count="${redoCount}">${redoCount}</b><span>다시 볼 곳을 찾았어요</span></div>
    </div>`;
  const subText = !allWon
    ? '다시 볼 곳은 상세 리포트에서 근거 발화와 함께 짚어 줄게요.'
    : hinted
      ? `힌트를 받은 질문이 ${hinted}개 있어요. 상세 리포트에서 근거 발화와 같이 다시 보면 좋아요.`
      : '힌트 없이 전부 지켰어요. 같은 질문으로 한 번 더 하면 답이 더 짧아져요.';

  app.innerHTML = `
    <div class="coach-nav"><a href="#/">← 내 발표로 나가기</a><span>${historySaved ? '코칭 기록 저장됨' : '기록을 저장하지 못했어요 — 화면을 캡처해 두세요'}</span></div>
    <div class="card cere-card qres">
      <p class="qres-eyebrow">실전 질문 코칭 결과</p>
      <!-- 숫자는 아래 묶음과 반드시 같아야 한다. liveWonCount(퀘스트 막대)와
           여기 bucketOf 는 이제 같은 것을 센다 — 답을 본 질문은 양쪽 다 뺀다 -->
      <h1 class="qres-head">${headHtml}</h1>
      ${statHtml}
      <p class="qres-sub">${subText}</p>
      ${L.results.length ? GROUPS.map((g) => (grouped[g.key].length ? `
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
  $('#qaGateStart').addEventListener('click', () => {
    qa.started = true;
    saveSession('qa-flow', qa);
    renderQa();
  });
}
