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
 * 질문 단계는 **통화 화면**이다 (9/18 사용자: "화상통화를 한다는 느낌이어야 해") — 큰 타일에
 * 내 모습, 작은 타일에 병아리 상대, 그 위로 질문·내 말 자막·판정이 말풍선으로 오간다.
 * 자동 대화(기본 켬)는 질문 뒤에 알아서 듣고, 말이 끝나면 3초 카운트다운 뒤에 보낸다 —
 * 자막을 누르면 멈추고 고칠 수 있다. 몰래 보내지 않는다.
 *
 * 규율 — 소리는 기본 무음(UI_REDESIGN §14), 판정 색 5종은 pill 로만, 병아리는 얹는 층이지
 * 가리는 층이 아니다, 분석이 실패하면 실패로 보여 준다(CLAUDE.md §4).
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
  appendTranscript, cameraErrorText, captureRoutes, countdownText, fitScale, hintLadder,
  judgementBubbles, newPen, paintDictation, partnerMood, shotFileName, shotsAdvice,
  speakableJudgement, speechSettled, tally, voiceCommand,
} from './booth_logic.js?v=b4';

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
  // 통화
  selfStream: null,     // 내 모습 (앞카메라/웹캠)
  autoTalk: true,       // 손 안 대고: 질문 뒤 듣기 → 침묵 → 카운트다운 → 보내기
  lastSpeechAt: 0,      // 자막이 마지막으로 바뀐 시각 (침묵 판정)
  quietTimer: null,
  countdown: null,      // { id, until }
  phase: 'asking',      // asking | listening | judging | judged | hint
};
const QUIET_MS = 2500;
const COUNTDOWN_S = 3;

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

/* ─── 3. 통화 — 내 모습 위로 질문·자막·판정이 오간다 ────────────────────── */
function q() { return state.questions[state.idx]; }
function pq() {
  const id = q().id;
  if (!state.perQ[id]) state.perQ[id] = { priorAnswers: [], hintsShown: [], hintLevel: 0, verdicts: [] };
  return state.perQ[id];
}

function isCoarse() { return !!(window.matchMedia && window.matchMedia('(pointer: coarse)').matches); }

async function startQa() {
  showStep('qa');
  document.body.classList.add('booth-in-call');
  $('qa-done').hidden = true;
  $('call').hidden = false;
  $('btn-pip').hidden = !('documentPictureInPicture' in window);
  $('btn-sound').hidden = !('speechSynthesis' in window);
  $('btn-mic').hidden = !(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  document.querySelector('.booth-qa-tools').hidden = false;
  $('call-bubbles').innerHTML = '';
  mountPartner();
  await openSelfView();
  renderQuestion();
}

/** 상대편 타일 — 객석의 병아리를 한 마리 앉힌다 (chatter.js chickSvg, 기분은 data-mood). */
function mountPartner() {
  const seat = $('call-partner-seat');
  if (seat.childElementCount) return;
  if (window.Chatter && typeof window.Chatter.chickSvg === 'function') seat.innerHTML = window.Chatter.chickSvg('solar');
  else seat.innerHTML = '<div class="call-partner-fallback" aria-hidden="true"></div>';
}

function setPhase(phase, verdict = '') {
  state.phase = phase;
  $('call-partner-seat').dataset.mood = partnerMood(phase, verdict);
  $('call').dataset.phase = phase;
  $('call-partner-status').textContent = {
    asking: '묻고 있어요', hint: '힌트를 줬어요', listening: '듣고 있어요', judging: '생각하는 중', judged: '',
  }[phase] || '';
}

/** 내 모습 — 앞카메라/웹캠. 못 열면 목소리만으로도 통화는 된다. */
async function openSelfView() {
  closeSelfView();
  const tile = $('call-self');
  if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia) || window.isSecureContext === false) {
    tile.dataset.camera = 'off';
    $('call-self-note').textContent = '카메라 없이 목소리로 통화해요.';
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
    state.selfStream = stream;
    $('call-self-video').srcObject = stream;
    tile.dataset.camera = 'on';
    $('call-self-note').textContent = '';
    stream.getVideoTracks()[0].addEventListener('ended', closeSelfView);
  } catch (err) {
    tile.dataset.camera = 'off';
    $('call-self-note').textContent = `${cameraErrorText(err).replace(' 사진을 찍어 올리면 같은 체험을 할 수 있어요.', '')} 목소리로 통화해요.`;
  }
  $('btn-self-camera').textContent = state.selfStream ? '카메라 끄기' : '카메라 켜기';
}

function closeSelfView() {
  if (state.selfStream) for (const t of state.selfStream.getTracks()) t.stop();
  state.selfStream = null;
  $('call-self-video').srcObject = null;
  $('call-self').dataset.camera = 'off';
  $('btn-self-camera').textContent = '카메라 켜기';
}

function toggleSelfView() {
  if (state.selfStream) { closeSelfView(); $('call-self-note').textContent = '카메라를 껐어요. 목소리로 통화해요.'; }
  else openSelfView();
}

/* 말풍선 — 상대는 왼쪽, 나는 오른쪽. 마지막 몇 개만 보이고 위는 흐려진다 (가리는 층이 아니다) */
function bubble(side, html, { kind = '', verdict = '' } = {}) {
  const log = $('call-bubbles');
  const el = document.createElement('div');
  el.className = `call-bubble glass is-${side}${kind ? ` is-${kind}` : ''}`;
  if (verdict) el.dataset.v = verdict;
  el.innerHTML = html;
  log.appendChild(el);
  while (log.childElementCount > 8) log.removeChild(log.firstChild);
  log.scrollTop = log.scrollHeight;
  return el;
}
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function renderQuestion() {
  const cur = q();
  cancelCountdown();
  $('qa-count').textContent = `${state.idx + 1} / ${state.questions.length}`;
  const chips = `<span class="booth-chip">${esc(cur.label || '')}</span>${(cur.slide_nos || []).length ? `<span class="booth-chip booth-chip-slide">${esc(cur.slide_nos.join('·'))}번 장면</span>` : ''}`;
  bubble('partner', `<div class="booth-chiprow">${chips}</div><p class="call-q">${esc(cur.question)}</p>${cur.why ? `<p class="call-why">${esc(cur.why)}</p>` : ''}`, { kind: 'question' });
  $('qa-answer').value = '';
  $('qa-answer').placeholder = '말하면 여기에 자막으로 떠요. 눌러서 고칠 수도 있어요.';
  note('qa-mic-note', '');
  $('btn-hint').disabled = hintLadder(cur).length === 0;
  $('btn-again').hidden = true;
  $('btn-next').hidden = true;
  setAnswering(true);
  setPhase('asking');
  // 상대가 말을 마치면(읽어 주기 켬) 또는 잠깐 뒤(무음) 듣기 시작 — 통화에서는 상대가 묻고 내가 말한다
  const after = () => { if (state.autoTalk && state.phase === 'asking') toggleMic(); };
  if (!speak(cur.question, after)) setTimeout(after, 900);
}

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
  bubble('partner', `<p class="call-hint">힌트 ${p.hintLevel}. ${esc(h)}</p>`, { kind: 'hint' });
  if (p.hintLevel >= ladder.length) $('btn-hint').disabled = true;
  setPhase('hint');
  speak(h);
}

async function submit(giveUp) {
  cancelCountdown();
  if (state.mic) await stopMic({ silent: true });
  if (state.micPending) { note('qa-mic-note', state.micPending === 'transcribing' ? '받아쓰는 중이에요. 글자가 채워지면 보내 주세요.' : '마이크를 여는 중이에요.'); return; }
  const cur = q(); const p = pq();
  const answer = $('qa-answer').value.trim();
  if (!giveUp && !answer) { note('qa-mic-note', '아직 아무 말도 없어요. 말하거나 자막을 눌러 적어 주세요.'); return; }
  hush();
  setAnswering(false);
  bubble('me', `<p>${esc(giveUp ? (answer || '모르겠어요, 답 볼게요') : answer)}</p>`, { kind: giveUp ? 'giveup' : 'answer' });
  $('qa-answer').value = '';
  setPhase('judging');
  try {
    const j = await judgeQaAnswer(state.sessionId, {
      questionId: cur.id, answer, history: state.history, question: cur, giveUp,
      priorAnswers: p.priorAnswers, hintsShown: p.hintsShown,
      artifacts: { graph: state.graph, context: state.context },
    });
    state.history.push({ '질문': cur.question, '답변': answer, '판정': j.verdict || 'unknown', question_id: cur.id, '포기': !!giveUp });
    if (answer) p.priorAnswers.push(answer);
    p.verdicts.push(j.verdict || 'unknown');
    renderJudgement(j, giveUp);
  } catch (err) {
    setAnswering(true);
    setPhase('asking');
    bubble('partner', `<p>${esc((err && err.message) || '판정을 받지 못했어요. 다시 답하면 할 수 있어요.')}</p>`, { kind: 'error' });
  }
}

function renderJudgement(j, giveUp) {
  const v = j.verdict || 'unknown';
  note('qa-mic-note', '');
  for (const b of judgementBubbles(j, { giveUp, answerGist: q().answer_gist || '' })) {
    if (b.kind === 'verdict') bubble('partner', `<span class="booth-pill" data-v="${b.verdict}">${esc(VERDICT_WORD[b.verdict] || b.verdict)}</span><p>${esc(b.text)}</p>`, { kind: 'verdict', verdict: b.verdict });
    else if (b.kind === 'missing') bubble('partner', `<p class="call-missing-head">빠진 것</p><ul class="booth-missing">${b.items.map((m) => `<li>${esc(m)}</li>`).join('')}</ul>`, { kind: 'missing' });
    else bubble('partner', `<p class="${b.kind === 'followup' ? 'call-followup' : 'call-explain'}">${esc(b.text)}</p>`, { kind: b.kind });
  }
  // 판정이 준 힌트는 사다리에 이어 붙인다 — 코치가 힌트와 이어지는 말로 반응한다
  if (Array.isArray(j.hints) && j.hints.length) {
    const p = pq();
    for (const h of j.hints) { if (!p.hintsShown.includes(h)) p.hintsShown.push(h); }
  }
  const last = state.idx + 1 >= state.questions.length;
  $('btn-next').textContent = last ? '통화 마치기' : '다음 질문';
  $('btn-next').hidden = false;
  $('btn-again').hidden = !!giveUp || v === 'good';
  setPhase('judged', v);
  const again = !giveUp && v !== 'good';
  if (again) { setAnswering(true); $('qa-answer').placeholder = '되물었어요. 이어서 말해도 되고, 다음 질문으로 가도 돼요.'; }
  $('btn-next').focus();
  // 되물었으면 상대 말이 끝난 뒤 다시 듣는다 — 통화가 이어진다
  const after = () => { if (state.autoTalk && again && state.phase === 'judged') toggleMic(); };
  if (!speak(speakableJudgement(j, { giveUp, answerGist: q().answer_gist || '' }), after) && again) setTimeout(after, 1200);
}

function next() {
  hush(); cancelCountdown();
  if (state.mic) stopMic({ silent: true });
  if (state.idx + 1 >= state.questions.length) return finish();
  state.idx += 1;
  renderQuestion();
}

function again() {
  hush(); cancelCountdown();
  $('qa-answer').value = '';
  setAnswering(true);
  setPhase('asking');
  if (state.autoTalk) toggleMic(); else if (!isCoarse()) $('qa-answer').focus();
}

function finish() {
  if (state.mic) stopMic({ silent: true });
  closeSelfView();
  document.body.classList.remove('booth-in-call');
  $('call').hidden = true;
  document.querySelector('.booth-qa-tools').hidden = true;
  const ul = $('qa-tally'); ul.innerHTML = '';
  for (const row of tally(state.questions, state.perQ)) {
    const li = document.createElement('li'); li.dataset.v = row.verdict;
    li.textContent = `${row.no}. ${row.label} · ${row.word}`;
    ul.appendChild(li);
  }
  $('qa-done').hidden = false;
}

function restart() {
  hush(); cancelCountdown();
  if (state.mic) stopMic({ silent: true });
  closeSelfView();
  closePip();
  document.body.classList.remove('booth-in-call');
  for (const s of state.shots) URL.revokeObjectURL(s.url);
  state.shots = []; renderShots();
  state.questions = []; state.graph = null; state.sessionId = null;
  showStep('capture');
}

/* ─── 말하기 — 자막으로 채우고, 자동 대화면 침묵 뒤 카운트다운을 거쳐 보낸다 ── */
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
  if (window.isSecureContext === false) {
    note('qa-mic-note', '마이크는 https 주소나 이 컴퓨터의 127.0.0.1 에서만 열려요. 자막을 눌러 적어도 돼요.');
    return;
  }
  hush();   // 상대가 읽는 중이면 멈춘다 — 안 그러면 상대 목소리를 받아쓴다
  cancelCountdown();
  state.micPending = 'opening';
  setMic('opening', true);
  if (!state.dictationDead && hasLiveDictation()) return startDictation();
  return startRecording();
}

function markSpeech() {
  state.lastSpeechAt = performance.now();
  if (!state.autoTalk) return;
  clearTimeout(state.quietTimer);
  state.quietTimer = setTimeout(watchQuiet, QUIET_MS + 50);
}

/** 침묵을 본다. 말한 게 있고 2.5초 조용하면 마이크를 멈추고 카운트다운을 시작한다. */
function watchQuiet() {
  if (!state.mic || !state.mic.dictation || !state.autoTalk) return;
  if (speechSettled({ lastChangeAt: state.lastSpeechAt, now: performance.now(), text: $('qa-answer').value })) {
    stopMic().then(() => { if ($('qa-answer').value.trim()) startCountdown(); });
  } else {
    state.quietTimer = setTimeout(watchQuiet, 500);
  }
}

function startCountdown() {
  cancelCountdown();
  const until = performance.now() + COUNTDOWN_S * 1000;
  const tick = () => {
    const left = (until - performance.now()) / 1000;
    note('qa-mic-note', countdownText(left));
    if (left <= 0) { state.countdown = null; submit(false); return; }
    state.countdown = { until, id: setTimeout(tick, 250) };
  };
  tick();
}

function cancelCountdown() {
  clearTimeout(state.quietTimer);
  if (state.countdown) { clearTimeout(state.countdown.id); state.countdown = null; note('qa-mic-note', ''); }
}

/** 자막(입력창)을 누르면 자동 보내기를 멈춘다 — 고칠 틈이 손에 잡혀야 한다. */
function holdCaption() {
  if (state.countdown) { cancelCountdown(); note('qa-mic-note', '멈췄어요. 고친 뒤 「답하기」를 눌러요.'); }
}

/** 지금 말로 누를 수 있는 버튼 — 화면의 버튼 상태를 그대로 따른다 (숨은·꺼진 버튼은 말로도 안 눌린다). */
function voiceAllowed() {
  return {
    next: !$('btn-next').hidden,
    again: !$('btn-again').hidden,
    hint: !$('btn-hint').disabled,
    giveup: !$('btn-giveup').disabled,
    answer: !$('btn-answer').disabled,
  };
}

/** 말로 누른 버튼. 자막에는 「'다음 질문' 이라고 했어요」처럼 남겨 무엇이 왜 일어났는지 보이게 한다. */
function runVoiceCommand(cmd) {
  const said = { next: $('btn-next').textContent, giveup: '모르겠어요', hint: '힌트', again: '다시 답하기', answer: '답하기' }[cmd];
  note('qa-mic-note', `「${said}」라고 말해서 눌렀어요.`);
  if (cmd === 'next') return next();
  if (cmd === 'giveup') return submit(true);
  if (cmd === 'hint') return showHint();
  if (cmd === 'again') return again();
  if (cmd === 'answer') return submit(false);
}

/** 실시간 받아쓰기 — 말하는 중에 자막이 채워진다 (크롬·엣지). */
function startDictation() {
  const ta = $('qa-answer');
  let pen = newPen(ta.value);
  // 말로 조작하기 — 확정 조각이 늘어날 때마다 새 조각 끝에서 명령을 본다. 명령은 자막에서 뗀다(cut).
  let seenFinal = 0; const cuts = [];
  try {
    state.mic = {
      dictation: true,
      session: startLiveDictation({
        onText: ({ final, interim }) => {
          let command = null;
          if (final.length > seenFinal) {
            const chunk = final.slice(seenFinal);
            const hit = voiceCommand(chunk, voiceAllowed());
            if (hit) { cuts.push([seenFinal + hit.rest.length, final.length]); command = hit.cmd; }
            seenFinal = final.length;
          }
          let clean = ''; let at = 0;
          for (const [a, b] of cuts) { clean += final.slice(at, a); at = b; }
          clean += final.slice(at);
          const r = paintDictation(pen, ta.value, `${clean} ${command ? '' : interim}`.trim());
          pen = r.pen;
          if (ta.value !== r.value) { ta.value = r.value; ta.scrollTop = ta.scrollHeight; markSpeech(); }
          if (command) runVoiceCommand(command);
        },
        onError: (msg) => {
          state.mic = null;
          state.dictationDead = true;
          note('qa-mic-note', `${msg} 마이크를 한 번 더 누르면 녹음해서 받아쓸게요. 자막을 눌러 적어도 돼요.`);
          setMic('idle'); setPhase('asking');
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
  state.lastSpeechAt = performance.now();
  note('qa-mic-note', state.autoTalk ? '듣고 있어요. 다 말하고 잠깐 쉬면 보내요.' : '듣고 있어요. 다 말하면 「그만 말하기」를 누르고 「답하기」를 눌러요.');
  setMic('dictating'); setPhase('listening');
}

/** 실시간이 안 되는 브라우저용 — 녹음해 두었다가 멈출 때 서버 STT 로 넘긴다. 침묵 판정은 없다. */
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
    note('qa-mic-note', `마이크를 못 열었어요: ${err.message || err}. 자막을 눌러 적어도 돼요.`);
    setMic('idle');
    return;
  }
  state.micPending = '';
  note('qa-mic-note', '녹음 중이에요. 다 말하면 「녹음 멈추고 받아쓰기」를 눌러요.');
  setMic('recording'); setPhase('listening');
}

async function stopMic({ silent = false } = {}) {
  const mic = state.mic;
  if (!mic) return;
  state.mic = null;
  clearTimeout(state.quietTimer);
  const ta = $('qa-answer');
  if (mic.dictation) {
    mic.session.stop();
    if (!silent) note('qa-mic-note', ta.value.trim() ? '자막을 확인하고 「답하기」를 눌러요.' : '말소리를 못 알아들었어요. 다시 말하거나 자막을 눌러 적어 주세요.');
    setMic('idle', !!ta.disabled);
    if (state.phase === 'listening') setPhase('asking');
    return;
  }
  state.micPending = 'transcribing';
  setMic('transcribing', true);
  try {
    const text = await transcribeAnswer(await mic.session.stop());
    if (text) {
      ta.value = appendTranscript(ta.value, text);
      if (state.autoTalk) startCountdown();
      else { note('qa-mic-note', '자막을 확인하고 「답하기」를 눌러요.'); $('btn-answer').focus(); }
    } else if (!silent) {
      note('qa-mic-note', '말소리를 못 알아들었어요. 다시 녹음하거나 자막을 눌러 적어 주세요.');
    }
  } catch (err) {
    note('qa-mic-note', `받아쓰기에 실패했어요: ${err.message || err}. 자막을 눌러 적어도 돼요.`);
  }
  state.micPending = '';
  setMic('idle', !!ta.disabled);
  if (state.phase === 'listening') setPhase('asking');
}

function setAutoTalk(on) {
  state.autoTalk = !!on;
  const btn = $('btn-autotalk');
  btn.textContent = state.autoTalk ? '자동 대화 끄기' : '자동 대화 켜기';
  btn.setAttribute('aria-pressed', String(state.autoTalk));
  if (!state.autoTalk) cancelCountdown();
}

/* ─── 읽어 주기 — 기본 무음. 켜면 상대가 질문·힌트·판정을 화면에 있는 말 그대로 읽는다 ─── */
function koVoice() {
  const voices = window.speechSynthesis.getVoices() || [];
  return voices.find((v) => /^ko/i.test(v.lang)) || null;
}

/** 읽기 시작했으면 true. onEnd 는 읽기가 끝났을 때만 부른다 (안 읽었으면 호출부가 알아서). */
function speak(text, onEnd = null) {
  if (!state.sound || !('speechSynthesis' in window) || !text) return false;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'ko-KR';
  u.rate = 1.0;
  const v = koVoice();
  if (v) u.voice = v;
  $('call-partner-seat').classList.add('is-talking');
  const done = () => { $('call-partner-seat').classList.remove('is-talking'); if (typeof onEnd === 'function') onEnd(); };
  u.onend = done;
  u.onerror = done;
  window.speechSynthesis.speak(u);
  return true;
}

function hush() {
  if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  const seat = $('call-partner-seat');
  if (seat) seat.classList.remove('is-talking');
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
  if (state.sound && state.questions.length && !$('call').hidden && state.phase === 'asking') speak(q().question);
}

/* ─── 작은 창 — 발표 화면 위에 통화만 띄운다 (Chrome 116+) ────────────────── */
async function openPip() {
  if (state.pipWindow) return closePip();
  try {
    const w = await window.documentPictureInPicture.requestWindow({ width: 480, height: 720 });
    for (const link of document.querySelectorAll('link[rel="stylesheet"]')) w.document.head.appendChild(link.cloneNode(true));
    w.document.body.className = 'booth-pip-window booth-in-call';
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
$('btn-autotalk').onclick = () => setAutoTalk(!state.autoTalk);
$('btn-self-camera').onclick = toggleSelfView;
$('btn-next').onclick = next;
$('btn-again').onclick = again;
$('btn-restart').onclick = restart;
$('btn-leave').onclick = finish;
$('btn-pip').onclick = openPip;
$('qa-answer').addEventListener('pointerdown', holdCaption);
$('qa-answer').addEventListener('focus', holdCaption);
$('qa-answer').addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') submit(false);
});
window.addEventListener('pagehide', () => { hush(); stopStream(); closeSelfView(); });
wireCapture();
setAutoTalk(true);
try { setSound(localStorage.getItem(SOUND_KEY) === '1'); } catch (_) { setSound(false); }
renderShots();
