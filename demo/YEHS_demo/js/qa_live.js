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
const SEVERITY_WORD = { 1: '치명', 2: '보통', 3: '가벼움' };

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
  idle: { icon: MIC_ICON, label: '음성 입력' },
  opening: { icon: MIC_ICON, label: '마이크 여는 중' },
  dictating: { icon: STOP_ICON, label: '음성 입력 멈추기' },
  recording: { icon: STOP_ICON, label: '녹음 멈추고 받아쓰기' },
  transcribing: { icon: MIC_ICON, label: '받아쓰는 중' },
};

/**
 * 진행 중인 답변 녹음. **세션에 저장하지 않는다** — MediaRecorder 는 새로고침을
 * 못 넘기므로, 저장하면 다시 연 화면이 「녹음 중」 상태로 굳어 버린다.
 */
let liveMic = null;

function qaLiveActive() {
  return !!(qa.live && Array.isArray(qa.live.questions) && qa.live.questions.length);
}

function newLiveState(sessionId, questions) {
  return {
    sessionId,
    questions,
    qi: 0,
    asked: -1,
    results: [],
    turn: 0,
    turns: [],
    hintLevel: 0,
    lastJudgement: null,
    // 판정 직후 곧바로 다음 질문으로 넘기지 않는다. 사용자가 자기 답과
    // 완성 답의 차이를 한 화면에서 확인한 뒤 직접 다음으로 간다.
    checkpoint: null,
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
 * 힌트를 다 쓰고도 점수가 안 오르면 "답 보고 넘어가기" 를 연다.
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
  if (L.turns.length < 2) return false;
  // 기준은 **질문이 들고 온 사다리**다. 판정이 붙으면 사다리가 한 칸 길어지는데,
  // 그걸 기준으로 삼으면 3단계까지 다 쓴 사람의 출구가 판정 직후에 다시 닫힌다.
  if (L.hintLevel < liveQuestionHints().length) return false;
  const last = L.turns[L.turns.length - 1];
  const prev = L.turns[L.turns.length - 2];
  return (last.score || 0) <= (prev.score || 0);
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
  return (L.turns || []).some((t) => t.gaveUp)
    ? '그래도 모르겠어요 · 넘어가기'
    : '모르겠어요';
}

function presentLiveQuestion() {
  const L = qa.live;
  if (L.asked === L.qi) return;
  L.asked = L.qi;
  const q = L.questions[L.qi];
  pushTurn({
    who: 'ai',
    kind: q.trap ? 'claim' : 'question',
    meta: `예상 질문 ${L.qi + 1}/${L.questions.length} · 치명도 ${SEVERITY_WORD[q.severity] || '보통'}`,
    text: escapeHtml(q.question),
    basis: q.why ? escapeHtml(q.why) : '',
  });
}

function renderQaLive() {
  const L = qa.live;
  if (qa.ended || L.qi >= L.questions.length) return qaLiveEnd();
  if (L.checkpoint) return renderLiveCheckpoint();
  qa.started = true;
  presentLiveQuestion();
  saveSession('qa-flow', qa);
  const q = L.questions[L.qi];
  const hints = liveHints();
  const won = liveWonCount(L.results);
  const prog = Math.round((L.qi + .35) / L.questions.length * 100);
  const learningStep = L.turn ? 3 : (L.hintLevel ? 2 : 1);
  app.innerHTML = `
    <div class="coach-nav"><a href="#/">← 저장하고 나가기</a><span>자동 저장됨</span></div>
    <div class="qa-shell">
      <aside class="qa-context">
        <div class="qa-loop-card">
          <span class="qa-loop-kicker">질문 ${L.qi + 1} · ${L.questions.length}개 중</span>
          <h2>${L.qi + 1}개만 끝내도<br><b>답변 하나가 완성돼요</b></h2>
          <div class="qa-loop-steps" aria-label="학습 단계">
            <div class="${learningStep >= 1 ? 'on' : ''}"><i>${learningStep > 1 ? '✓' : '1'}</i><span><b>질문 이해</b><small>핵심을 잡아요</small></span></div>
            <div class="${learningStep >= 2 ? 'on' : ''}"><i>${learningStep > 2 ? '✓' : '2'}</i><span><b>힌트로 정리</b><small>막히면 한 칸만</small></span></div>
            <div class="${learningStep >= 3 ? 'on' : ''}"><i>3</i><span><b>내 말로 답하기</b><small>코치가 바로 다듬어요</small></span></div>
          </div>
          <div class="qa-loop-score"><span>지금까지 완성한 답</span><b>${won}개</b></div>
        </div>
        <div class="persuade-track" style="--p:${prog}%"><i></i></div>
      </aside>
      <section class="qa-dialog">
    <div class="qa-stream" id="stream">${qa.turns.map(streamRow).join('')}</div>
    <div class="card qa-live-input">
      <div class="qa-input-label"><b>내 말로 답해보세요</b><span>한 문장만 말해도 괜찮아요</span></div>
      <textarea id="liveAnswer" rows="3" ${L.busy ? 'disabled' : ''}
        placeholder="예: 이 방법의 핵심은 …이에요"></textarea>
      <div class="step-actions">
        <button class="btn btn-primary" id="liveSend" type="button" ${L.busy ? 'disabled' : ''}>${L.busy ? '답변 살펴보는 중…' : (L.turn ? '보완해서 다시 답하기' : '이 답변 확인하기')}</button>
        ${micBtnHTML(L.busy)}
        <button class="btn btn-text" id="liveStuck" type="button" ${L.busy ? 'disabled' : ''}>${stuckLabel()}</button>
        ${hints.length > L.hintLevel ? `<button class="btn btn-text" id="liveHint" type="button" ${L.busy ? 'disabled' : ''}>힌트 ${L.hintLevel + 1}단계 보기</button>` : ''}
        ${liveStalled() ? `<button class="btn btn-text" id="liveReveal" type="button" ${L.busy ? 'disabled' : ''}>답 보고 넘어가기</button>` : ''}
        <button class="btn btn-text qa-exit-action" id="liveFinish" type="button" ${L.busy ? 'disabled' : ''}>여기까지 하고 저장</button>
      </div>
    </div>
      </section>
    </div>`;
  scrollDown();

  const sendBtn = $('#liveSend');
  if (sendBtn) sendBtn.addEventListener('click', () => submitLiveAnswer());
  const ta = $('#liveAnswer');
  if (ta) {
    ta.focus();
    ta.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;
      if (e.metaKey || e.ctrlKey) { e.preventDefault(); submitLiveAnswer(); return; }
      if (e.shiftKey) return;
      if (e.isComposing || e.keyCode === 229) return;
      e.preventDefault();
      submitLiveAnswer();
    });
  }
  const micBtn = $('#liveMic');
  if (micBtn) micBtn.addEventListener('click', () => toggleLiveMic());
  const stuckBtn = $('#liveStuck');
  if (stuckBtn) stuckBtn.addEventListener('click', () => submitLiveAnswer({ giveUp: true }));
  const hintBtn = $('#liveHint');
  if (hintBtn) hintBtn.addEventListener('click', () => {
    const list = liveHints();
    if (L.hintLevel >= list.length) return;
    L.hintLevel += 1;
    // total 을 같이 싣는다 — 말풍선의 "힌트 N/3" 이 하드코딩이라, 판정 후
    // 사다리가 4단으로 길어지면 "힌트 4/3" 이라는 거짓 숫자가 떴다.
    pushTurn({ who: 'ai', kind: 'hint', level: L.hintLevel, total: list.length, text: escapeHtml(list[L.hintLevel - 1]) });
    growStream();
    if (L.hintLevel >= list.length) hintBtn.remove();
    else hintBtn.textContent = `힌트 ${L.hintLevel + 1}단계 보기`;
    saveSession('qa-flow', qa);
  });
  const revealBtn = $('#liveReveal');
  if (revealBtn) revealBtn.addEventListener('click', () => revealLiveAnswer());
  const finishBtn = $('#liveFinish');
  if (finishBtn) finishBtn.addEventListener('click', () => finishLiveQaEarly());
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
  const modelAnswer = q.answer_gist || v.explanation || v.summary_sentence || '핵심 근거를 먼저 말하고, 자료의 수치나 사례로 뒷받침해 보세요.';
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
      verdict: 'skipped', score: 0, passed: false, summary: '',
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
  setMicBtn('opening', true);
  if (window.ChuckchuckBridge.hasLiveDictation()) return startDictationMic();
  return startRecordingMic();
}

/** 실시간 받아쓰기 — 말하는 중에 입력창이 채워진다. */
function startDictationMic() {
  const ta = $('#liveAnswer');
  // 이미 쳐 놓은 글은 기준선으로 잡아 둔다. 중간 결과가 올 때마다 통째로
  // 다시 쓰기 때문에, 기준선을 안 두면 사용자가 친 글이 매번 지워진다.
  const base = ((ta && ta.value) || '').trim();
  try {
    liveMic = {
      dictation: true,
      session: window.ChuckchuckBridge.startLiveDictation({
        onText: ({ final, interim }) => paintLiveAnswer(base, final + interim),
        onError: (msg) => {
          // 오류가 나면 인식기는 거기서 끝난다. 버튼을 안 되돌리면 이미 죽은
          // 세션에 「받아쓰기 멈추기」가 남아 사용자가 헛클릭한다.
          liveMic = null;
          micSay(`${escapeHtml(msg)} — 타이핑으로 답하셔도 됩니다`);
          setMicBtn('idle', !!(qa.live && qa.live.busy));
        },
      }),
    };
  } catch (err) {
    micSay(`받아쓰기를 시작하지 못했어요: ${escapeHtml(err.message || String(err))} — 타이핑으로 답하셔도 됩니다`);
    setMicBtn('idle');
    return;
  }
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
    // 권한 거부·미지원. 삼키면 사용자는 버튼이 왜 안 먹는지 알 수 없다.
    micSay(`마이크를 못 열었어요: ${escapeHtml(err.message || String(err))} — 타이핑으로 답하셔도 됩니다`);
    setMicBtn('idle');
    return;
  }
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

  setMicBtn('transcribing', true);
  try {
    const text = await window.ChuckchuckBridge.transcribeAnswer(await mic.session.stop());
    if (text) fillLiveAnswer(text);
    else micSay('말소리를 못 알아들었어요 — 다시 녹음하거나 타이핑으로 답해 주세요');
  } catch (err) {
    micSay(`받아쓰기에 실패했어요: ${escapeHtml(err.message || String(err))} — 타이핑으로 답하셔도 됩니다`);
  }
  idle();
}

/**
 * 실시간 받아쓰기가 입력창을 다시 그린다. 확정 전 조각까지 그대로 보여 줘야
 * "말하는 대로 나온다" 는 느낌이 산다 — 확정된 것만 그리면 뚝뚝 끊겨 보인다.
 */
function paintLiveAnswer(base, spoken) {
  const ta = $('#liveAnswer');
  if (!ta) return;
  ta.value = base && spoken ? `${base} ${spoken}` : (base || spoken);
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
  const q = L.questions[L.qi];
  const ta = $('#liveAnswer');
  const typed = ((ta && ta.value) || '').trim();
  const answer = giveUp ? (typed || '(모르겠어요)') : typed;
  if (!answer || L.busy) return;
  // 이번에 실제로 답하고 있는 질문 — 되물음이 떠 있으면 그것이다. 원래 질문만
  // 기록하면 판정 히스토리에 되물음이 안 남아, "네" 같은 증분 답이 무엇에 대한
  // 답인지 서버가 알 길이 없다 (그래서 정답을 말해도 unknown 이 반복됐다).
  const askedNow = (L.turn && L.lastJudgement && L.lastJudgement.followup) || q.question;
  pushTurn({ who: 'me', kind: 'say', text: escapeHtml(answer) });
  L.busy = true;
  saveSession('qa-flow', qa);
  renderQaLive();
  // 판정이 실패하면 입력창에 답을 되살린다 — 전송 즉시 화면을 다시 그려 창이
  // 비워지므로, 안 되살리면 「다시 시도」가 처음부터 다시 타이핑하기가 된다.
  let failedAnswer = '';
  try {
    const v = await window.ChuckchuckBridge.judgeQaAnswer(L.sessionId, {
      questionId: q.id, answer, history: liveHistory(), question: q, giveUp,
      // 이 질문에 앞서 낸 답들. 판정은 누적 전체를 본다 (f09 "합쳐서 판정하라").
      // 포기 턴의 "(모르겠어요)" 자리표시자는 답이 아니라 뺀다.
      priorAnswers: (L.turns || []).filter((t) => !t.gaveUp).map((t) => t.answer),
      artifacts: liveArtifacts(),
    });
    const m = LIVE_VERDICT[v.verdict] || LIVE_VERDICT.unknown;
    L.turn += 1;
    L.turns.push({ question: askedNow, questionId: q.id, answer, verdict: v.verdict, score: v.score || 0, gaveUp: giveUp });
    L.lastJudgement = v;
    L.judgeFailed = false;
    if (v.react) pushTurn({ who: 'ai', kind: 'react', verdict: m.react, text: escapeHtml(v.react) });

    if (v.coach_stage === 'explain') {
      closeLiveCoached(q, v, answer);
    } else if (v.passed) {
      finishLiveQuestion(q, v, answer);
    } else {
      askAgain(v, L.turn);
    }
  } catch (err) {
    // 「모르겠어요」도 판정을 타므로, 서버가 죽으면 이 질문에 갇힌다.
    // 아래 렌더에서 「답 보고 넘어가기」가 열려 서버 없이 다음 질문으로 간다.
    L.judgeFailed = true;
    failedAnswer = giveUp ? '' : answer;   // 포기 자리표시자는 되살릴 답이 아니다
    // 자료 정보가 통째로 사라진 경우는 다시 눌러도 똑같이 실패한다. 「다시
    // 시도」로 유도하면 같은 자리를 맴돌 뿐이라, 원인과 빠져나갈 길을 따로 낸다.
    pushTurn({
      who: 'sys',
      kind: 'lost',
      text: err.code === 'session_missing'
        ? '자료 정보가 사라져서 판정할 수 없어요. <a href="#/new">자료를 다시 올리면</a> 이어서 할 수 있어요 — 지금은 「답 보고 넘어가기」로 다음 질문에 갈 수 있어요'
        : `판정 실패: ${escapeHtml(err.message || String(err))} — 다시 시도하거나 「답 보고 넘어가기」로 다음 질문에 갈 수 있어요`,
    });
  }
  L.busy = false;
  saveSession('qa-flow', qa);
  renderQaLive();
  if (failedAnswer) {
    const retryTa = $('#liveAnswer');
    if (retryTa) {
      retryTa.value = failedAnswer;
      retryTa.selectionStart = retryTa.selectionEnd = retryTa.value.length;
    }
  }
}

function closeLiveCoached(q, v, answer) {
  if (v.explanation) pushTurn({ who: 'ai', kind: 'gist', text: escapeHtml(v.explanation) });
  qa.live.checkpoint = {
    answer, verdict: v,
    record: {
      id: q.id, label: q.label, question: q.question, answer,
      verdict: 'unknown', score: 0, passed: false, gaveUp: true,
      summary: v.summary_sentence || '', revealed: true, coached: true,
    },
  };
}

/**
 * 설득으로 셀 결과인지. **기준은 서버 하나뿐이다** (`contracts.qa_passed`).
 * 프론트가 임계를 따로 계산하면 화면마다 다른 수가 나온다 — 실제로 진행 중 헤더는
 * good|partial, 결과 화면은 good 만 세어 3/3 이 1/3 으로 떨어졌다.
 */
function liveWonCount(results) {
  return (results || []).filter((r) => r.passed).length;
}

function askAgain(v, turn) {
  const points = (v.missing_points || []).filter(Boolean);
  if (points.length) {
    pushTurn({ who: 'ai', kind: 'missing', points: points.map(escapeHtml) });
  }
  if (v.followup) {
    pushTurn({
      who: 'ai',
      kind: 'question',
      meta: `이어서 묻습니다 · ${turn + 1}번째 답변`,
      text: escapeHtml(v.followup),
    });
  }
}

function closeLiveQuestion(record) {
  const L = qa.live;
  L.results.push({ ...record, turns: L.turn, hintLevel: L.hintLevel });
  L.qi++;
  L.turn = 0;
  L.turns = [];
  L.hintLevel = 0;
  L.lastJudgement = null;
  L.judgeFailed = false;
}

function finishLiveQuestion(q, v, answer) {
  const m = LIVE_VERDICT[v.verdict] || LIVE_VERDICT.unknown;
  pushTurn({ who: 'sys', kind: m.flag, text: `${escapeHtml(q.label)} — ${m.word}` });
  if (v.summary_sentence) {
    pushTurn({ who: 'sys', kind: 'summary', concept: q.node_id, outcome: v.verdict, label: escapeHtml(q.label), text: v.summary_sentence });
  }
  if (q.answer_gist) pushTurn({ who: 'ai', kind: 'gist', text: escapeHtml(q.answer_gist) });
  qa.live.checkpoint = {
    answer, verdict: v,
    record: {
      id: q.id, label: q.label, question: q.question, answer,
      verdict: v.verdict, score: v.score || 0, passed: !!v.passed,
      summary: v.summary_sentence || '',
    },
  };
}

function revealLiveAnswer() {
  const L = qa.live;
  const q = L.questions[L.qi];
  const v = L.lastJudgement || {};
  const last = L.turns[L.turns.length - 1] || {};
  pushTurn({ who: 'sys', kind: 'lost', text: `${escapeHtml(q.label)} — 오늘은 여기까지. 답을 보고 넘어갈게요` });
  if (q.answer_gist) pushTurn({ who: 'ai', kind: 'gist', text: escapeHtml(q.answer_gist) });
  L.checkpoint = {
    answer: last.answer || '', verdict: v,
    record: {
      id: q.id, label: q.label, question: q.question, answer: last.answer || '',
      verdict: v.verdict || 'unknown', score: v.score || 0, passed: !!v.passed,
      summary: v.summary_sentence || '', revealed: true,
    },
  };
  saveSession('qa-flow', qa);
  renderQaLive();
}

/**
 * 지금 질문의 힌트 사다리. 출처가 둘이라 **긴 쪽**을 쓴다.
 *
 * 질문과 함께 오는 3단계(방향·범위·접근)와, 판정이 붙여 주는 4단계(+근접)가 있다.
 * 둘 다 서버의 같은 `build_hint_ladder` 에서 나와 앞 세 칸이 일치하므로,
 * 이미 본 단계 번호가 사다리를 갈아타도 어긋나지 않는다. 길이로 고르는 이유는
 * 짧은 쪽으로 내려가면 소비한 인덱스가 무효가 되기 때문이다.
 */
function liveHints() {
  const judged = (qa.live.lastJudgement && qa.live.lastJudgement.hints) || [];
  const built = liveQuestionHints();
  return judged.length >= built.length ? judged : built;
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
  recordQaHistory();
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
  const rowHtml = ({ r, i }) => `
    <button class="qres-row" type="button" data-qi="${i}">
      <span class="qres-main">
        <b>${escapeHtml(r.label || `질문 ${i + 1}`)}</b>
        <small>${escapeHtml(oneLine(r.summary || r.question))}</small>
      </span>
      <span class="qres-side">
        <span class="chip chip-sm ${chipCls[r.verdict] || 'st-om'}">${r.revealed ? '답 확인' : (chipWord[r.verdict] || r.verdict)}</span>
        ${r.turns ? `<em class="qres-meta">${r.turns}번 만에${r.hintLevel ? ` · 힌트 ${r.hintLevel}단계` : ''}</em>` : ''}
      </span>
      <span class="qres-chev" aria-hidden="true">›</span>
    </button>`;

  app.innerHTML = `
    <div class="coach-nav"><a href="#/">← 내 발표로 나가기</a><span>코칭 기록 저장됨</span></div>
    <div class="card cere-card qres">
      <p class="qres-eyebrow">실전 질문 코칭 결과</p>
      <!-- 숫자는 아래 묶음과 반드시 같아야 한다. liveWonCount 는 부분 인정을
           빼고 세기 때문에 화면의 「지켜낸 질문」 개수와 어긋난다 -->
      <h1 class="qres-head"><b class="num">${grouped.won.length}</b>개를 자기 말로 지켰고,
        <b class="num qres-redo">${redoCount}</b>개가 남았어요</h1>
      <p class="qres-sub">남은 질문은 상세 리포트에서 근거 발화와 함께 다시 볼 수 있어요.</p>
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
  /* 행 전체가 눌린다 — TDS ListRow 는 누를 수 있으면 화살표와 터치 효과를 준다 */
  $$('.qres-row').forEach((el) => el.addEventListener('click', () => { location.hash = '#/report'; }));
  const again = $('#liveAgain');
  if (again) again.addEventListener('click', () => {
    const keep = qa.live;
    resetQa();
    qa.live = newLiveState(keep.sessionId, keep.questions);
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
