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
    busy: false,
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
  }));
  return done.concat(current);
}

/** 판정에 실어 보낼 자료 근거. 없으면 판정이 "자료와 어긋난다"를 대조할 원본을 잃는다. */
function liveArtifacts() {
  const out = (nf && nf.pipelineOut) || null;
  if (!out || !out.graph) return null;
  return {
    graph: out.graph,
    alignment: out.alignment || null,
    flow: out.flow || null,
    transcript: out.transcript || null,
    context: { situation: nf.occ || '', audience: nf.ctx || '', duration_min: nf.min },
  };
}

function liveStalled() {
  const L = qa.live;
  if (L.hintLevel < 3 || L.turns.length < 2) return false;
  const last = L.turns[L.turns.length - 1];
  const prev = L.turns[L.turns.length - 2];
  return (last.score || 0) <= (prev.score || 0);
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
  qa.started = true;
  presentLiveQuestion();
  saveSession('qa-flow', qa);
  const q = L.questions[L.qi];
  const hints = liveHints();
  const won = liveWonCount(L.results);
  const prog = Math.round(L.qi / L.questions.length * 100);
  app.innerHTML = `
    <div class="coach-nav"><a href="#/">← 저장하고 나가기</a><span>자동 저장됨</span></div>
    <div class="persuade-track" style="--p:${prog}%">
      <div class="pt-head"><span>실전 질문 코칭 · 내 자료 기준</span>
        <span class="pt-right"><b>${won}<i>/${L.questions.length} 설득</i></b></span></div>
    </div>
    <div class="qa-stream" id="stream">${qa.turns.map(streamRow).join('')}</div>
    <div class="card qa-live-input">
      <textarea id="liveAnswer" rows="3" ${L.busy ? 'disabled' : ''}
        placeholder="상대를 설득한다는 생각으로, 자기 말로 답해보세요 (Enter 전송 · Shift+Enter 줄바꿈)"></textarea>
      <div class="step-actions">
        <button class="btn btn-primary" id="liveSend" type="button" ${L.busy ? 'disabled' : ''}>${L.busy ? '판정 중…' : (L.turn ? '다시 답해보기' : '답변 보내기')}</button>
        <button class="btn btn-text" id="liveStuck" type="button" ${L.busy ? 'disabled' : ''}>모르겠어요</button>
        ${hints.length > L.hintLevel ? `<button class="btn btn-text" id="liveHint" type="button" ${L.busy ? 'disabled' : ''}>힌트 ${L.hintLevel + 1}단계 보기</button>` : ''}
        ${liveStalled() ? `<button class="btn btn-text" id="liveReveal" type="button" ${L.busy ? 'disabled' : ''}>답 보고 넘어가기</button>` : ''}
        <button class="btn btn-text" id="liveSkip" type="button" ${L.busy ? 'disabled' : ''}>이 질문 넘기기</button>
        <button class="btn btn-text" id="liveFinish" type="button" ${L.busy ? 'disabled' : ''}>코칭 끝내고 리포트</button>
      </div>
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
  const stuckBtn = $('#liveStuck');
  if (stuckBtn) stuckBtn.addEventListener('click', () => submitLiveAnswer({ giveUp: true }));
  const hintBtn = $('#liveHint');
  if (hintBtn) hintBtn.addEventListener('click', () => {
    const list = liveHints();
    if (L.hintLevel >= list.length) return;
    L.hintLevel += 1;
    pushTurn({ who: 'ai', kind: 'hint', level: L.hintLevel, text: escapeHtml(list[L.hintLevel - 1]) });
    growStream();
    if (L.hintLevel >= list.length) hintBtn.remove();
    else hintBtn.textContent = `힌트 ${L.hintLevel + 1}단계 보기`;
    saveSession('qa-flow', qa);
  });
  const revealBtn = $('#liveReveal');
  if (revealBtn) revealBtn.addEventListener('click', () => revealLiveAnswer());
  const skipBtn = $('#liveSkip');
  if (skipBtn) skipBtn.addEventListener('click', () => {
    pushTurn({ who: 'sys', kind: 'lost', text: `${escapeHtml(q.label)} — 오늘은 넘겼어요. 리포트에 남겨둘게요` });
    closeLiveQuestion({
      id: q.id, label: q.label, question: q.question, answer: '(넘김)',
      verdict: 'skipped', score: 0, passed: false, summary: '',
    });
    saveSession('qa-flow', qa);
    renderQaLive();
  });
  const finishBtn = $('#liveFinish');
  if (finishBtn) finishBtn.addEventListener('click', () => finishLiveQaEarly());
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

async function submitLiveAnswer({ giveUp = false } = {}) {
  const L = qa.live;
  const q = L.questions[L.qi];
  const ta = $('#liveAnswer');
  const typed = ((ta && ta.value) || '').trim();
  const answer = giveUp ? (typed || '(모르겠어요)') : typed;
  if (!answer || L.busy) return;
  pushTurn({ who: 'me', kind: 'say', text: escapeHtml(answer) });
  L.busy = true;
  saveSession('qa-flow', qa);
  renderQaLive();
  try {
    const v = await window.ChuckchuckBridge.judgeQaAnswer(L.sessionId, {
      questionId: q.id, answer, history: liveHistory(), question: q, giveUp,
      artifacts: liveArtifacts(),
    });
    const m = LIVE_VERDICT[v.verdict] || LIVE_VERDICT.unknown;
    L.turn += 1;
    L.turns.push({ question: q.question, answer, verdict: v.verdict, score: v.score || 0, gaveUp: giveUp });
    L.lastJudgement = v;
    if (v.react) pushTurn({ who: 'ai', kind: 'react', verdict: m.react, text: escapeHtml(v.react) });

    if (v.coach_stage === 'explain') {
      closeLiveCoached(q, v, answer);
    } else if (v.passed) {
      finishLiveQuestion(q, v, answer);
    } else {
      askAgain(v, L.turn);
    }
  } catch (err) {
    pushTurn({ who: 'sys', kind: 'lost', text: `판정 실패: ${err.message || err} — 같은 질문으로 다시 시도할 수 있어요` });
  }
  L.busy = false;
  saveSession('qa-flow', qa);
  renderQaLive();
}

function closeLiveCoached(q, v, answer) {
  if (v.explanation) pushTurn({ who: 'ai', kind: 'gist', text: escapeHtml(v.explanation) });
  closeLiveQuestion({
    id: q.id, label: q.label, question: q.question, answer,
    verdict: 'unknown', score: 0, passed: false, gaveUp: true,
    summary: v.summary_sentence || '', revealed: true, coached: true,
  });
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
}

function finishLiveQuestion(q, v, answer) {
  const m = LIVE_VERDICT[v.verdict] || LIVE_VERDICT.unknown;
  pushTurn({ who: 'sys', kind: m.flag, text: `${escapeHtml(q.label)} — ${m.word}` });
  if (v.summary_sentence) {
    pushTurn({ who: 'sys', kind: 'summary', concept: q.node_id, outcome: v.verdict, label: escapeHtml(q.label), text: v.summary_sentence });
  }
  if (q.answer_gist) pushTurn({ who: 'ai', kind: 'gist', text: escapeHtml(q.answer_gist) });
  closeLiveQuestion({
    id: q.id, label: q.label, question: q.question, answer,
    verdict: v.verdict, score: v.score || 0, passed: !!v.passed,
    summary: v.summary_sentence || '',
  });
}

function revealLiveAnswer() {
  const L = qa.live;
  const q = L.questions[L.qi];
  const v = L.lastJudgement || {};
  const last = L.turns[L.turns.length - 1] || {};
  pushTurn({ who: 'sys', kind: 'lost', text: `${escapeHtml(q.label)} — 오늘은 여기까지. 답을 보고 넘어갈게요` });
  if (q.answer_gist) pushTurn({ who: 'ai', kind: 'gist', text: escapeHtml(q.answer_gist) });
  closeLiveQuestion({
    id: q.id, label: q.label, question: q.question, answer: last.answer || '',
    verdict: v.verdict || 'unknown', score: v.score || 0, passed: !!v.passed,
    summary: v.summary_sentence || '', revealed: true,
  });
  saveSession('qa-flow', qa);
  renderQaLive();
}

function liveHints() {
  const L = qa.live;
  const q = L.questions[L.qi];
  const ladder = (L.lastJudgement && L.lastJudgement.hints) || [];
  if (ladder.length) return ladder;
  return q && q.hint ? [q.hint] : [];
}

function qaLiveEnd() {
  qa.ended = true;
  // 발표 플로우도 끝난 걸로 표시 — 홈/이어하기에서 리포트로 이어지게
  if (typeof nf !== 'undefined' && nf) {
    nf.completed = true;
    saveSession('new-flow', nf);
  }
  saveSession('qa-flow', qa);
  const L = qa.live;
  const won = liveWonCount(L.results);
  const chipCls = { good: 'st-ok', partial: 'st-mid', wrong: 'st-no', unknown: 'st-om', skipped: 'st-om' };
  const chipWord = { good: '설득 완료', partial: '부분 인정', wrong: '미방어', unknown: '보류', skipped: '넘김' };
  app.innerHTML = `
    <div class="coach-nav"><a href="#/">← 내 발표로 나가기</a><span>코칭 기록 저장됨</span></div>
    <div class="card cere-card">
      <div class="cere-row-head">
        <span class="cere-label">실전 질문 코칭 결과</span>
        <b class="cere-count num">${won} <i>/</i> ${L.questions.length}</b>
      </div>
      <div class="cere-sums">
        ${L.results.map((r) => `<div class="qsum-row">
          <b><span class="chip chip-sm ${chipCls[r.verdict] || 'st-om'}">${r.revealed ? '답 확인' : (chipWord[r.verdict] || r.verdict)}</span> ${escapeHtml(r.label || '')}</b>
          <p>${escapeHtml(r.summary || r.question || '')}</p>
          ${r.turns ? `<span class="qsum-meta">${r.turns}번 만에 방어${r.hintLevel ? ` · 힌트 ${r.hintLevel}단계` : ''}</span>` : ''}
        </div>`).join('') || '<p class="note">기록이 없어요.</p>'}
      </div>
      <p class="cere-hint">이 총평이 상세 리포트로 이어져요 — 미방어·넘긴 질문부터 다시 보세요</p>
    </div>
    <div class="cere-actions">
      <a class="btn btn-primary" href="#/report">상세 리포트 보기</a>
      <button class="btn btn-text" id="liveAgain" type="button">같은 질문으로 다시</button>
      <a class="btn btn-text" href="#/">홈으로</a>
    </div>`;
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
      <button class="btn btn-primary" id="qaGateStart" type="button">이 설정으로 시작하기 · 최대 ${qaScope().count}개 개념 · 약 ${qaScope().min}분</button>
    </div>`;
  wireQaModeButtons(qaModeGate);
  $('#qaGateStart').addEventListener('click', () => {
    qa.started = true;
    saveSession('qa-flow', qa);
    renderQa();
  });
}
