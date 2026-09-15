/**
 * 부스 체험 — 화면을 담아 바로 질문을 받는다 (booth.html).
 *
 * 흐름: 화면 공유/스크린샷 → /api/v1/parse (이미지 여러 장 = 한 자료) → F-06 개념
 * → F-07 그래프 → F-08 질문 → F-09 판정. 발화가 없으니 정합·흐름은 비운다 —
 * 브리지의 questions/judge 는 graph 만 있으면 돈다.
 *
 * app.js 를 건드리지 않는다. API 호출은 chuckchuck_bridge.js 의 것을 그대로 쓴다
 * (요청 본문 계약이 앱과 같아야 브리지 캐시·세션 보관소가 같은 길로 돈다).
 */

import {
  apiBase,
  buildGraph,
  buildQuestions,
  extractConcepts,
  judgeQaAnswer,
  registerSessionArtifacts,
} from './chuckchuck_bridge.js';

const MAX_SHOTS = 8;
const PARSE_TIMEOUT_MS = 120000;

const $ = (id) => document.getElementById(id);

/* ─── 상태 ───────────────────────────────────────────────────────────────── */
const state = {
  shots: [],            // [{ blob, url }]
  stream: null,
  context: null,
  track: '5',
  sessionId: null,
  graph: null,
  questions: [],
  idx: 0,
  history: [],          // QaTurn dict (한글 키 — 굳은 계약)
  perQ: {},             // question_id → { priorAnswers, hintsShown, hintLevel, verdicts[] }
  timers: {},
  pipWindow: null,
};

function showStep(name) {
  for (const el of document.querySelectorAll('.booth-step')) el.hidden = el.dataset.step !== name;
}

/* ─── 1. 담기 ────────────────────────────────────────────────────────────── */
function renderShots() {
  const box = $('shots');
  box.innerHTML = '';
  state.shots.forEach((s, i) => {
    const d = document.createElement('div');
    d.className = 'booth-shot';
    d.innerHTML = `<img alt="담은 장면 ${i + 1}"><span class="booth-shot-no">${i + 1}</span><button class="booth-shot-del" type="button" aria-label="이 장면 빼기">×</button>`;
    d.querySelector('img').src = s.url;
    d.querySelector('button').onclick = () => { URL.revokeObjectURL(s.url); state.shots.splice(i, 1); renderShots(); };
    box.appendChild(d);
  });
  $('btn-go').disabled = state.shots.length === 0;
  $('btn-go').textContent = state.shots.length ? `${state.shots.length}장으로 질문 만들기` : '질문 만들기';
  $('btn-grab').disabled = state.shots.length >= MAX_SHOTS;
}

function addShot(blob) {
  if (state.shots.length >= MAX_SHOTS) return;
  state.shots.push({ blob, url: URL.createObjectURL(blob) });
  renderShots();
}

async function startShare() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
    $('share-unsupported').hidden = false;
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 5 }, audio: false });
    state.stream = stream;
    const v = $('share-video');
    v.srcObject = stream;
    $('share-stage').hidden = false;
    stream.getVideoTracks()[0].addEventListener('ended', stopShare);
  } catch (err) {
    // 사용자가 공유 창을 닫은 것은 오류가 아니다
    if (err && err.name !== 'NotAllowedError') $('share-unsupported').hidden = false;
  }
}

function stopShare() {
  if (state.stream) for (const t of state.stream.getTracks()) t.stop();
  state.stream = null;
  $('share-video').srcObject = null;
  $('share-stage').hidden = true;
}

function grabFrame() {
  const v = $('share-video');
  if (!v.videoWidth) return;
  const c = document.createElement('canvas');
  // 긴 변 1600px — Upstage 가 읽기엔 충분하고 업로드는 가볍다
  const scale = Math.min(1, 1600 / Math.max(v.videoWidth, v.videoHeight));
  c.width = Math.round(v.videoWidth * scale);
  c.height = Math.round(v.videoHeight * scale);
  c.getContext('2d').drawImage(v, 0, 0, c.width, c.height);
  c.toBlob((blob) => blob && addShot(blob), 'image/png');
}

function onFiles(ev) {
  for (const f of Array.from(ev.target.files || [])) {
    if (/^image\/(png|jpeg)$/.test(f.type)) addShot(f);
  }
  ev.target.value = '';
}

/* ─── 2. 분석 — 걸린 시간은 실측만 보여 준다 ────────────────────────────── */
function stageEl(name) { return document.querySelector(`#stages li[data-stage="${name}"]`); }

function stageStart(name) {
  const li = stageEl(name);
  li.className = 'is-running';
  const t0 = performance.now();
  const tick = () => { li.querySelector('.st-time').textContent = `${((performance.now() - t0) / 1000).toFixed(0)}초`; };
  tick();
  state.timers[name] = { t0, id: setInterval(tick, 500) };
}

function stageDone(name, ok = true) {
  const t = state.timers[name];
  if (!t) return;
  clearInterval(t.id);
  const li = stageEl(name);
  li.className = ok ? 'is-done' : 'is-failed';
  li.querySelector('.st-time').textContent = `${((performance.now() - t.t0) / 1000).toFixed(1)}초`;
}

function resetStages() {
  for (const li of document.querySelectorAll('#stages li')) { li.className = ''; li.querySelector('.st-time').textContent = '—'; }
  for (const t of Object.values(state.timers)) clearInterval(t.id);
  state.timers = {};
  $('progress-error').hidden = true;
}

async function uploadShots() {
  const fd = new FormData();
  state.shots.forEach((s, i) => fd.append('document', s.blob, `화면-${i + 1}.png`));
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), PARSE_TIMEOUT_MS);
  try {
    const res = await fetch(apiBase() + '/api/v1/parse', { method: 'POST', body: fd, signal: ctl.signal });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) throw new Error(data.message || data.error || `parse HTTP ${res.status}`);
    return data;
  } finally { clearTimeout(timer); }
}

async function runPipeline() {
  showStep('progress');
  resetStages();
  state.context = { situation: $('ctx-situation').value, duration_min: Number($('ctx-track').value) };
  state.track = $('ctx-track').value;
  let stage = 'parse';
  try {
    stageStart('parse');
    const slideDoc = await uploadShots();
    state.sessionId = slideDoc.session_id || null;
    stageDone('parse');

    stage = 'concepts';
    stageStart('concepts');
    const concepts = await extractConcepts({ slideDoc, context: state.context, sessionId: state.sessionId });
    stageDone('concepts');

    stage = 'graph';
    stageStart('graph');
    const graph = await buildGraph({ concepts, slideDoc, context: state.context, sessionId: state.sessionId });
    state.graph = graph;
    stageDone('graph');

    stage = 'questions';
    stageStart('questions');
    if (state.sessionId) {
      await registerSessionArtifacts(state.sessionId, { graph, context: state.context });
    }
    const qdoc = await buildQuestions({
      graph, alignment: null, flow: null, transcript: null,
      context: state.context, track: state.track, sessionId: state.sessionId,
    });
    stageDone('questions');
    state.questions = (qdoc.questions || []).filter((q) => q && q.question);
    if (!state.questions.length) throw new Error('이 화면에서는 질문을 만들지 못했어요. 글자가 더 잘 보이는 장면을 담으면 만들 수 있어요.');
    state.idx = 0; state.history = []; state.perQ = {};
    startQa();
  } catch (err) {
    stageDone(stage, false);
    // 분석이 실패하면 실패로 보여 준다 — 샘플로 위장하지 않는다 (CLAUDE.md §4)
    $('progress-error-text').textContent = (err && err.message) || String(err);
    $('progress-error').hidden = false;
  }
}

/* ─── 3. 질문 코칭 ───────────────────────────────────────────────────────── */
function q() { return state.questions[state.idx]; }
function pq() {
  const id = q().id;
  if (!state.perQ[id]) state.perQ[id] = { priorAnswers: [], hintsShown: [], hintLevel: 0, verdicts: [] };
  return state.perQ[id];
}

function startQa() {
  showStep('qa');
  $('qa-done').hidden = true;
  $('qa-card').hidden = false;
  $('btn-pip').hidden = !('documentPictureInPicture' in window);
  renderQuestion();
}

function renderQuestion() {
  const cur = q();
  $('qa-count').textContent = `${state.idx + 1} / ${state.questions.length}`;
  $('qa-label').textContent = cur.label || '';
  $('qa-slide').textContent = (cur.slide_nos || []).length ? `${cur.slide_nos.join('·')}번 장면` : '';
  $('qa-question').textContent = cur.question;
  $('qa-why').textContent = cur.why || '';
  $('qa-hints').hidden = true; $('qa-hints').innerHTML = '';
  $('qa-answer').value = '';
  $('qa-result').hidden = true;
  $('qa-busy').hidden = true;
  $('btn-hint').disabled = !(cur.hints || cur.hint);
  setAnswering(true);
  $('qa-answer').focus();
}

function setAnswering(on) {
  for (const id of ['btn-answer', 'btn-hint', 'btn-giveup']) $(id).disabled = !on;
  $('qa-answer').disabled = !on;
}

function showHint() {
  const cur = q(); const p = pq();
  const ladder = Array.isArray(cur.hints) && cur.hints.length ? cur.hints : (cur.hint ? [cur.hint] : []);
  if (p.hintLevel >= ladder.length) return;
  const h = ladder[p.hintLevel++];
  p.hintsShown.push(h);
  const box = $('qa-hints');
  const el = document.createElement('p');
  el.textContent = `힌트 ${p.hintLevel}. ${h}`;
  box.appendChild(el); box.hidden = false;
  if (p.hintLevel >= ladder.length) $('btn-hint').disabled = true;
}

async function submit(giveUp) {
  const cur = q(); const p = pq();
  const answer = $('qa-answer').value.trim();
  if (!giveUp && !answer) { $('qa-answer').focus(); return; }
  setAnswering(false);
  $('qa-busy').hidden = false;
  try {
    const j = await judgeQaAnswer(state.sessionId, {
      questionId: cur.id,
      answer,
      history: state.history,
      question: cur,
      giveUp,
      priorAnswers: p.priorAnswers,
      hintsShown: p.hintsShown,
      artifacts: { graph: state.graph, context: state.context },
    });
    state.history.push({ '질문': cur.question, '답변': answer, '판정': j.verdict || 'unknown', question_id: cur.id, '포기': !!giveUp });
    if (answer) p.priorAnswers.push(answer);
    p.verdicts.push(j.verdict || 'unknown');
    renderJudgement(j, giveUp);
  } catch (err) {
    $('qa-busy').hidden = true;
    setAnswering(true);
    alert((err && err.message) || '판정을 받지 못했어요. 다시 답하면 할 수 있어요.');
  }
}

const VERDICT_WORD = { good: '잘 답했어요', partial: '반쯤 왔어요', wrong: '자료와 달라요', unknown: '아직 모르겠어요' };

function renderJudgement(j, giveUp) {
  $('qa-busy').hidden = true;
  const v = j.verdict || 'unknown';
  const pill = $('qa-pill'); pill.dataset.v = v; pill.textContent = VERDICT_WORD[v] || v;
  $('qa-react').textContent = j.react || '';
  $('qa-summary').textContent = j.summary_sentence || '';
  const ul = $('qa-missing'); ul.innerHTML = '';
  for (const m of j.missing_points || []) { const li = document.createElement('li'); li.textContent = m; ul.appendChild(li); }
  $('qa-followup').textContent = j.followup || '';
  $('qa-explain').textContent = (giveUp || j.coach_stage === 'explain') ? (j.explanation || q().answer_gist || '') : '';
  // 판정이 준 힌트는 사다리에 이어 붙인다 — 코치가 힌트와 이어지는 말로 반응한다
  if (Array.isArray(j.hints) && j.hints.length) {
    const p = pq(); const box = $('qa-hints');
    for (const h of j.hints) {
      if (p.hintsShown.includes(h)) continue;
      p.hintsShown.push(h);
      const el = document.createElement('p'); el.textContent = h; box.appendChild(el);
    }
    box.hidden = box.childElementCount === 0;
  }
  const last = state.idx + 1 >= state.questions.length;
  $('btn-next').textContent = last ? '결과 보기' : '다음 질문';
  $('btn-again').hidden = !!giveUp || v === 'good';
  $('qa-result').hidden = false;
}

function next() {
  if (state.idx + 1 >= state.questions.length) return finish();
  state.idx += 1;
  renderQuestion();
}

function again() {
  // 같은 질문에 다시 답한다. 힌트·앞선 답은 유지 (판정이 누적 전체를 본다)
  $('qa-result').hidden = true;
  $('qa-answer').value = '';
  setAnswering(true);
  $('qa-answer').focus();
}

function finish() {
  $('qa-card').hidden = true;
  const ul = $('qa-tally'); ul.innerHTML = '';
  state.questions.forEach((cur, i) => {
    const vs = (state.perQ[cur.id] || { verdicts: [] }).verdicts;
    const v = vs.length ? vs[vs.length - 1] : 'unknown';
    const li = document.createElement('li'); li.dataset.v = v;
    li.textContent = `${i + 1}. ${cur.label || '질문'} · ${VERDICT_WORD[v] || v}`;
    ul.appendChild(li);
  });
  $('qa-done').hidden = false;
}

function restart() {
  closePip();
  for (const s of state.shots) URL.revokeObjectURL(s.url);
  state.shots = []; renderShots();
  state.questions = []; state.graph = null; state.sessionId = null;
  showStep('capture');
}

/* ─── 작은 창 — 발표 화면 위에 질문 카드만 띄운다 (Chrome 116+) ───────────── */
async function openPip() {
  if (state.pipWindow) return closePip();
  try {
    const w = await window.documentPictureInPicture.requestWindow({ width: 440, height: 640 });
    for (const link of document.querySelectorAll('link[rel="stylesheet"]')) w.document.head.appendChild(link.cloneNode(true));
    w.document.body.className = 'booth-pip-window';
    w.document.body.appendChild($('qa-panel'));
    w.addEventListener('pagehide', () => { $('step-qa').appendChild($('qa-panel')); state.pipWindow = null; $('btn-pip').textContent = '작은 창으로 띄우기'; });
    state.pipWindow = w;
    $('btn-pip').textContent = '작은 창 닫기';
  } catch (_) {
    $('btn-pip').hidden = true;
  }
}

function closePip() {
  if (state.pipWindow) { state.pipWindow.close(); state.pipWindow = null; }
}

/* ─── 배선 ───────────────────────────────────────────────────────────────── */
$('btn-share').onclick = startShare;
$('btn-stop-share').onclick = stopShare;
$('btn-grab').onclick = grabFrame;
$('file-shots').onchange = onFiles;
$('btn-go').onclick = () => { stopShare(); runPipeline(); };
$('btn-retry').onclick = runPipeline;
$('btn-back-capture').onclick = () => showStep('capture');
$('btn-answer').onclick = () => submit(false);
$('btn-giveup').onclick = () => submit(true);
$('btn-hint').onclick = showHint;
$('btn-next').onclick = next;
$('btn-again').onclick = again;
$('btn-restart').onclick = restart;
$('btn-pip').onclick = openPip;
$('qa-answer').addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') submit(false);
});
if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) $('share-unsupported').hidden = false;
renderShots();
