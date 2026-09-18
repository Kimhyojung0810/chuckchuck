/**
 * 부스 체험 — 카메라로 찍거나 화면을 담아, 말로 답하며 질문을 받는다 (booth.html).
 *
 * 흐름: 카메라/화면 공유/사진 → /api/v1/parse (이미지 여러 장 = 한 자료) → F-06 개념
 * → F-07 그래프 → F-08 질문 → (말해서·쳐서 답) → F-09 판정. 발화가 없으니 정합·흐름은
 * 비운다 — 브리지의 questions/judge 는 graph 만 있으면 돈다.
 *
 * app.js 를 건드리지 않는다. API·마이크·받아쓰기는 chuckchuck_bridge.js 의 것을 그대로
 * 쓴다 (요청 본문 계약이 앱과 같아야 브리지 캐시·세션 보관소가 같은 길로 돈다).
 * 브라우저 없이 판단할 수 있는 것은 booth_logic.js 에 있고 node 스모크가 잡는다.
 *
 * 규율 — 마이크는 **채워만 주고 보내지 않는다**(잘못 들은 문장을 고칠 틈), 소리는 기본
 * 무음(UI_REDESIGN §14), 분석이 실패하면 실패로 보여 준다(CLAUDE.md §4).
 */

import {
  apiBase,
  buildGraph,
  buildQuestions,
  extractConcepts,
  hasLiveDictation,
  judgeQaAnswer,
  registerSessionArtifacts,
  startAnswerRecording,
  startLiveDictation,
  transcribeAnswer,
} from './chuckchuck_bridge.js';
import {
  MAX_SHOTS, MIC_LABEL, VERDICT_WORD,
  appendTranscript, cameraErrorText, captureRoutes, fitScale, hintLadder, newPen,
  paintDictation, shotFileName, shotsAdvice, speakableJudgement, tally,
} from './booth_logic.js?v=b2';

const PARSE_TIMEOUT_MS = 120000;
const SOUND_KEY = 'cheokcheok:booth-sound';

const $ = (id) => document.getElementById(id);

/* ─── 상태 ───────────────────────────────────────────────────────────────── */
const state = {
  routes: captureRoutes({
    secure: window.isSecureContext !== false,
    hasUserMedia: !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia),
    hasDisplayMedia: !!(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia),
    coarse: !!(window.matchMedia && window.matchMedia('(pointer: coarse)').matches),
  }),
  shots: [],            // [{ blob, url }]
  stream: null,
  source: null,         // 'camera' | 'display'
  cameras: [],          // videoinput deviceId 목록 (권한 뒤에만 이름이 보인다)
  cameraIdx: -1,
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
  // 마이크. 세션에 저장하지 않는다 — MediaRecorder 는 새로고침을 못 넘긴다.
  mic: null,            // { dictation: bool, session }
  micPending: '',       // '' | 'opening' | 'transcribing'
  dictationDead: false, // 실시간 받아쓰기가 이 세션에서 죽었으면 녹음 + 서버 STT 로 간다
  sound: false,
};

function showStep(name) {
  for (const el of document.querySelectorAll('.booth-step')) el.hidden = el.dataset.step !== name;
}

function note(id, text) {
  const el = $(id);
  if (!el) return;
  el.textContent = text || '';
  el.hidden = !text;
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
  const n = state.shots.length;
  $('btn-go').disabled = n === 0;
  $('btn-go').textContent = n ? `${n}장으로 질문 만들기` : '질문 만들기';
  $('btn-grab').disabled = n >= MAX_SHOTS;
  $('shots-advice').textContent = shotsAdvice(n);
}

function addShot(blob) {
  if (state.shots.length >= MAX_SHOTS) return;
  state.shots.push({ blob, url: URL.createObjectURL(blob) });
  renderShots();
}

/** 화면 공유 — 자료가 열린 창을 고르면 미리보기가 뜨고, 「이 장면 담기」로 한 프레임씩 담는다. */
async function startShare() {
  if (!state.routes.share) { note('capture-note', '이 브라우저는 화면 공유가 안 돼요. 카메라로 찍거나 사진을 올리면 같은 체험을 할 수 있어요.'); return; }
  stopStream();
  try {
    const stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 5 }, audio: false });
    attachStream(stream, 'display');
  } catch (err) {
    // 사용자가 공유 창을 닫은 것은 오류가 아니다
    if (err && err.name !== 'NotAllowedError') note('capture-note', '화면 공유를 열지 못했어요. 카메라로 찍거나 사진을 올리면 같은 체험을 할 수 있어요.');
  }
}

/**
 * 카메라 — 폰이면 뒷카메라, 노트북이면 웹캠. 미리보기를 보며 「찍기」로 담는다.
 * 미리보기를 못 여는 곳(http 로 들어온 폰·권한 거부)은 기기 카메라 앱으로 간다 (파일 입력 capture).
 */
async function openCamera(deviceId = null) {
  if (state.routes.camera !== 'live') { $('file-camera').click(); return; }
  stopStream();
  const video = deviceId ? { deviceId: { exact: deviceId } } : { facingMode: { ideal: 'environment' } };
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { ...video, width: { ideal: 1920 }, height: { ideal: 1080 } },
      audio: false,
    });
    attachStream(stream, 'camera');
    note('capture-note', '');
    await listCameras(stream);
  } catch (err) {
    note('capture-note', cameraErrorText(err));
    // 미리보기가 안 되면 기기 카메라 앱이 다음 길이다 — 버튼을 그쪽으로 돌린다
    state.routes = { ...state.routes, camera: 'file' };
    $('btn-camera').textContent = '사진 찍어 올리기';
  }
}

/** 카메라가 둘 이상이면 「카메라 바꾸기」를 보여 준다 (폰 앞/뒤, 노트북 + USB 문서 카메라). */
async function listCameras(stream) {
  if (!navigator.mediaDevices.enumerateDevices) return;
  try {
    const all = await navigator.mediaDevices.enumerateDevices();
    state.cameras = all.filter((d) => d.kind === 'videoinput').map((d) => d.deviceId).filter(Boolean);
    const cur = stream.getVideoTracks()[0].getSettings().deviceId;
    state.cameraIdx = Math.max(0, state.cameras.indexOf(cur));
    $('btn-switch-camera').hidden = state.cameras.length < 2;
  } catch (_) { $('btn-switch-camera').hidden = true; }
}

function switchCamera() {
  if (state.cameras.length < 2) return;
  state.cameraIdx = (state.cameraIdx + 1) % state.cameras.length;
  openCamera(state.cameras[state.cameraIdx]);
}

function attachStream(stream, source) {
  state.stream = stream;
  state.source = source;
  const v = $('share-video');
  v.srcObject = stream;
  $('share-stage').hidden = false;
  $('share-stage').dataset.source = source;
  $('btn-grab').textContent = source === 'camera' ? '찍기' : '이 장면 담기';
  $('btn-stop-share').textContent = source === 'camera' ? '카메라 닫기' : '공유 끝내기';
  $('stage-tip').textContent = source === 'camera' ? '글자가 읽히게 화면을 꽉 채워 찍어요. 흔들리면 한 번 더 찍으면 돼요.' : '슬라이드를 넘기며 장면마다 담아요.';
  if (source !== 'camera') $('btn-switch-camera').hidden = true;
  stream.getVideoTracks()[0].addEventListener('ended', stopStream);
}

function stopStream() {
  if (state.stream) for (const t of state.stream.getTracks()) t.stop();
  state.stream = null;
  state.source = null;
  $('share-video').srcObject = null;
  $('share-stage').hidden = true;
  $('btn-switch-camera').hidden = true;
}

function grabFrame() {
  const v = $('share-video');
  if (!v.videoWidth) return;
  const c = document.createElement('canvas');
  const scale = fitScale(v.videoWidth, v.videoHeight);
  c.width = Math.round(v.videoWidth * scale);
  c.height = Math.round(v.videoHeight * scale);
  c.getContext('2d').drawImage(v, 0, 0, c.width, c.height);
  // 사진은 JPEG(작다), 화면 캡처는 PNG(글자가 또렷하다)
  if (state.source === 'camera') c.toBlob((blob) => blob && addShot(blob), 'image/jpeg', 0.9);
  else c.toBlob((blob) => blob && addShot(blob), 'image/png');
  flashStage();
}

function flashStage() {
  const st = $('share-stage');
  st.classList.remove('is-flash');
  void st.offsetWidth;   // 다시 시작하려면 리플로우가 한 번 필요하다
  st.classList.add('is-flash');
}

/**
 * 올린 사진을 업로드 크기로 맞춘다. 폰 사진은 12MP·수 MB 에 EXIF 회전이 붙어 있다 —
 * 그대로 올리면 부스 와이파이에서 느리고, 회전을 안 풀면 옆으로 누운 채 읽힌다.
 * 못 하면(옛 브라우저) 원본을 그대로 쓴다. 서버는 내용으로 형식을 판별한다.
 */
async function normalizeImage(file) {
  if (typeof window.createImageBitmap !== 'function') return file;
  let bmp;
  try {
    try { bmp = await createImageBitmap(file, { imageOrientation: 'from-image' }); }
    catch (_) { bmp = await createImageBitmap(file); }   // 옵션을 모르는 브라우저
    const scale = fitScale(bmp.width, bmp.height);
    if (scale === 1 && file.size < 2_000_000) { bmp.close(); return file; }
    const c = document.createElement('canvas');
    c.width = Math.round(bmp.width * scale);
    c.height = Math.round(bmp.height * scale);
    c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
    bmp.close();
    const blob = await new Promise((r) => c.toBlob(r, 'image/jpeg', 0.9));
    return blob || file;
  } catch (_) {
    return file;
  }
}

async function onFiles(ev) {
  const files = Array.from(ev.target.files || []).filter((f) => /^image\//.test(f.type));
  ev.target.value = '';
  for (const f of files) addShot(await normalizeImage(f));
  if (files.length && ev.target.id === 'file-camera') note('capture-note', '');
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
  state.shots.forEach((s, i) => fd.append('document', s.blob, shotFileName(i, s.blob.type)));
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
    if (!state.questions.length) throw new Error('이 장면에서는 질문을 만들지 못했어요. 글자가 더 잘 보이게 다시 찍으면 만들 수 있어요.');
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
  $('btn-sound').hidden = !('speechSynthesis' in window);
  $('btn-mic').hidden = !(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
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
  note('qa-mic-note', '');
  $('btn-hint').disabled = hintLadder(cur).length === 0;
  setAnswering(true);
  // 손가락 기기에서 자동 포커스는 키보드를 띄워 마이크 버튼을 가린다 — 말하는 게 먼저다
  if (!isCoarse()) $('qa-answer').focus();
  speak(cur.question);
}

function isCoarse() { return !!(window.matchMedia && window.matchMedia('(pointer: coarse)').matches); }

function setAnswering(on) {
  for (const id of ['btn-answer', 'btn-hint', 'btn-giveup']) $(id).disabled = !on;
  $('qa-answer').disabled = !on;
  if (!state.mic && !state.micPending) setMic('idle', !on);
}

function showHint() {
  const cur = q(); const p = pq();
  const ladder = hintLadder(cur);
  if (p.hintLevel >= ladder.length) return;
  const h = ladder[p.hintLevel++];
  p.hintsShown.push(h);
  const box = $('qa-hints');
  const el = document.createElement('p');
  el.textContent = `힌트 ${p.hintLevel}. ${h}`;
  box.appendChild(el); box.hidden = false;
  if (p.hintLevel >= ladder.length) $('btn-hint').disabled = true;
  speak(h);
}

async function submit(giveUp) {
  // 말하는 중에 보내면 화면이 판정으로 넘어가고 녹음은 아무도 안 멈춘다
  if (state.mic) { note('qa-mic-note', '말하는 중이에요 — 먼저 멈춘 뒤 보내 주세요.'); return; }
  if (state.micPending) { note('qa-mic-note', state.micPending === 'transcribing' ? '받아쓰는 중이에요 — 글자가 채워지면 보내 주세요.' : '마이크를 여는 중이에요.'); return; }
  const cur = q(); const p = pq();
  const answer = $('qa-answer').value.trim();
  if (!giveUp && !answer) { $('qa-answer').focus(); return; }
  hush();
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
    note('qa-mic-note', (err && err.message) || '판정을 받지 못했어요. 다시 답하면 할 수 있어요.');
  }
}

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
  $('btn-next').focus();
  speak(speakableJudgement(j, { giveUp, answerGist: q().answer_gist || '' }));
}

function next() {
  hush();
  if (state.idx + 1 >= state.questions.length) return finish();
  state.idx += 1;
  renderQuestion();
}

function again() {
  // 같은 질문에 다시 답한다. 힌트·앞선 답은 유지 (판정이 누적 전체를 본다)
  hush();
  $('qa-result').hidden = true;
  $('qa-answer').value = '';
  setAnswering(true);
  if (!isCoarse()) $('qa-answer').focus();
}

function finish() {
  $('qa-card').hidden = true;
  const ul = $('qa-tally'); ul.innerHTML = '';
  for (const row of tally(state.questions, state.perQ)) {
    const li = document.createElement('li'); li.dataset.v = row.verdict;
    li.textContent = `${row.no}. ${row.label} · ${row.word}`;
    ul.appendChild(li);
  }
  $('qa-done').hidden = false;
}

function restart() {
  hush();
  stopMic();
  closePip();
  for (const s of state.shots) URL.revokeObjectURL(s.url);
  state.shots = []; renderShots();
  state.questions = []; state.graph = null; state.sessionId = null;
  showStep('capture');
}

/* ─── 말해서 답하기 — 채워만 주고 보내지 않는다 ─────────────────────────── */
function setMic(name, disabled = false) {
  const btn = $('btn-mic');
  btn.textContent = MIC_LABEL[name] || MIC_LABEL.idle;
  btn.dataset.state = name;
  btn.setAttribute('aria-label', MIC_LABEL[name] || MIC_LABEL.idle);
  btn.disabled = !!disabled;
}

function toggleMic() {
  if (state.mic) return stopMic();
  if (state.micPending) return;
  // 마이크는 보안 컨텍스트에서만 열린다. http://10.x 로 들어온 폰은 못 연다 — 왜 안 되는지 말해 준다.
  if (window.isSecureContext === false) {
    note('qa-mic-note', '마이크는 https 주소나 이 컴퓨터의 127.0.0.1 에서만 열려요. 타이핑으로 답해도 돼요.');
    return;
  }
  hush();   // 코치가 읽는 중이면 멈춘다 — 안 그러면 코치 목소리를 받아쓴다
  state.micPending = 'opening';
  setMic('opening', true);
  if (!state.dictationDead && hasLiveDictation()) return startDictation();
  return startRecording();
}

/** 실시간 받아쓰기 — 말하는 중에 입력창이 채워진다 (크롬·엣지). */
function startDictation() {
  const ta = $('qa-answer');
  let pen = newPen(ta.value);
  try {
    state.mic = {
      dictation: true,
      session: startLiveDictation({
        onText: ({ final, interim }) => {
          const r = paintDictation(pen, ta.value, final + interim);
          pen = r.pen;
          ta.value = r.value;
          ta.scrollTop = ta.scrollHeight;
        },
        onError: (msg) => {
          // 여기 오는 오류(권한·마이크 없음·망)는 다시 시작해도 같다. 다음부터는 녹음으로 간다.
          state.mic = null;
          state.dictationDead = true;
          note('qa-mic-note', `${msg} 마이크를 한 번 더 누르면 녹음해서 받아쓸게요. 타이핑으로 답해도 돼요.`);
          setMic('idle');
        },
      }),
    };
  } catch (err) {
    state.micPending = '';
    state.dictationDead = true;
    note('qa-mic-note', `받아쓰기를 시작하지 못했어요: ${err.message || err}. 마이크를 한 번 더 누르면 녹음해서 받아쓸게요.`);
    setMic('idle');
    return;
  }
  state.micPending = '';
  note('qa-mic-note', '듣고 있어요. 다 말하면 「그만 말하기」를 누르고, 글자를 확인한 뒤 「답하기」를 눌러요.');
  setMic('dictating');
}

/** 실시간이 안 되는 브라우저용 — 녹음해 두었다가 멈출 때 서버 STT 로 넘긴다. */
async function startRecording() {
  try {
    state.mic = {
      dictation: false,
      session: await startAnswerRecording({
        onAutoStop: () => { note('qa-mic-note', '녹음이 길어져 자동으로 멈췄어요. 받아쓰는 중이에요.'); stopMic(); },
      }),
    };
  } catch (err) {
    state.micPending = '';
    note('qa-mic-note', `마이크를 못 열었어요: ${err.message || err}. 타이핑으로 답해도 돼요.`);
    setMic('idle');
    return;
  }
  state.micPending = '';
  note('qa-mic-note', '녹음 중이에요. 다 말하면 「녹음 멈추고 받아쓰기」를 눌러요.');
  setMic('recording');
}

async function stopMic() {
  const mic = state.mic;
  if (!mic) return;
  state.mic = null;
  const ta = $('qa-answer');
  if (mic.dictation) {
    mic.session.stop();
    note('qa-mic-note', ta.value.trim() ? '받아쓴 글을 확인하고 「답하기」를 눌러요.' : '말소리를 못 알아들었어요. 다시 말하거나 타이핑으로 답해 주세요.');
    setMic('idle', !!$('qa-answer').disabled);
    if (ta.value.trim()) $('btn-answer').focus();
    return;
  }
  state.micPending = 'transcribing';
  setMic('transcribing', true);
  try {
    const text = await transcribeAnswer(await mic.session.stop());
    if (text) {
      ta.value = appendTranscript(ta.value, text);
      note('qa-mic-note', '받아쓴 글을 확인하고 「답하기」를 눌러요.');
      $('btn-answer').focus();
    } else {
      note('qa-mic-note', '말소리를 못 알아들었어요. 다시 녹음하거나 타이핑으로 답해 주세요.');
    }
  } catch (err) {
    note('qa-mic-note', `받아쓰기에 실패했어요: ${err.message || err}. 타이핑으로 답해도 돼요.`);
  }
  state.micPending = '';
  setMic('idle', !!$('qa-answer').disabled);
}

/* ─── 읽어 주기 — 기본 무음. 켜면 질문·힌트·판정을 화면에 있는 말 그대로 읽는다 ─── */
function koVoice() {
  const voices = window.speechSynthesis.getVoices() || [];
  return voices.find((v) => /^ko/i.test(v.lang)) || null;
}

function speak(text) {
  if (!state.sound || !('speechSynthesis' in window) || !text) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'ko-KR';
  u.rate = 1.0;
  const v = koVoice();
  if (v) u.voice = v;
  window.speechSynthesis.speak(u);
}

function hush() {
  if ('speechSynthesis' in window) window.speechSynthesis.cancel();
}

function setSound(on) {
  state.sound = !!on;
  const btn = $('btn-sound');
  btn.textContent = state.sound ? '소리 끄기' : '소리 켜기';
  btn.setAttribute('aria-pressed', String(state.sound));
  try { localStorage.setItem(SOUND_KEY, state.sound ? '1' : '0'); } catch (_) { /* 사생활 모드 */ }
  if (!state.sound) hush();
}

function toggleSound() {
  setSound(!state.sound);
  // 켜자마자 지금 질문을 읽어 준다 — 소리가 나는지 바로 안다 (첫 발화는 사용자 조작 안에서만 된다)
  if (state.sound && state.questions.length && !$('qa-card').hidden) speak($('qa-result').hidden ? q().question : $('qa-summary').textContent);
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
function wireCapture() {
  const r = state.routes;
  $('btn-share').hidden = !r.share;
  $('btn-camera').textContent = r.camera === 'live' ? '카메라로 찍기' : '사진 찍어 올리기';
  // 첫 버튼 하나만 primary — 한 화면의 주인공은 하나 (MVP_SPEC §3)
  $('btn-camera').className = `btn ${r.primary === 'camera' ? 'btn-primary' : 'btn-secondary'}`;
  $('btn-share').className = `btn ${r.primary === 'share' ? 'btn-primary' : 'btn-secondary'}`;
  if (r.primary === 'share') $('capture-actions').prepend($('btn-share'));
}

$('btn-camera').onclick = () => openCamera();
$('btn-switch-camera').onclick = switchCamera;
$('btn-share').onclick = startShare;
$('btn-stop-share').onclick = stopStream;
$('btn-grab').onclick = grabFrame;
$('file-shots').onchange = onFiles;
$('file-camera').onchange = onFiles;
$('btn-go').onclick = () => { stopStream(); runPipeline(); };
$('btn-retry').onclick = runPipeline;
$('btn-back-capture').onclick = () => showStep('capture');
$('btn-answer').onclick = () => submit(false);
$('btn-giveup').onclick = () => submit(true);
$('btn-hint').onclick = showHint;
$('btn-mic').onclick = toggleMic;
$('btn-sound').onclick = toggleSound;
$('btn-next').onclick = next;
$('btn-again').onclick = again;
$('btn-restart').onclick = restart;
$('btn-pip').onclick = openPip;
$('qa-answer').addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') submit(false);
});
window.addEventListener('pagehide', () => { hush(); stopStream(); });
wireCapture();
try { setSound(localStorage.getItem(SOUND_KEY) === '1'); } catch (_) { setSound(false); }
renderShots();
