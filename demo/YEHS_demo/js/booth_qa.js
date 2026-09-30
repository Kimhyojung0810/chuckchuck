/**
 * 부스 Q&A 무대 — 주소창 /booth/qa (→ index.html#/booth/qa). Festa 부스 운영 중에 Q&A 세션을 보여 주는 전용 입구.
 *
 * 2026-09-30 사용자: "부스 시연을 위해 QA 가 작동하는 모습을 체험감 있게 … 시작화면을 고정하고,
 * #/test/qa 의 발표 목록 → 바로 QA 흐름만 따로 빼서 전용 UI 로." 이어서 "부스 운영 중에 QA 세션을
 * 보여 주기 위함이니 다른 URL 로 명시해서" — 그래서 개발용 /test/qa 와 짝이 되는 /booth/qa 로 둔다.
 *
 * 화면 다섯 장이 body 위 #bqStage 층에 그려진다 (call_flow.js 의 #cfCall 과 같은 이유 — 데스크톱
 * 아트보드가 transform 으로 줄어 position:fixed 가 창이 아니라 판에 붙는다).
 *
 *   시작(고정) → 발표 고르기 → 훑어보기 + 질문 준비 → Q&A 무대(#/qa) → 마무리 → (자동) 시작
 *
 * 로직은 새로 만들지 않는다. 덱 되살리기·선분석·질문 생성은 #/test/qa(startTestDeck 3-a 자료만)와
 * 같은 함수(ensureSlideDoc · applySlideDoc · startPrecompute · ensureLiveQuestions)를 부르고,
 * 질문 무대는 qa_live.js 의 같은 id(#stream · .qa-live-input · #liveAnswer …)를 새 배치에 놓는다.
 * 카메라 판단(사람이 다가옴 · 구도 · 정면 비율)은 booth_cv.js(OpenCV.js)가 한다.
 *
 * 공개 방문자에게는 잠긴다(app.js BETA_ROUTES). 부스 노트북은 /auth 로 개발자 모드를 한 번 켜 둔다.
 * 부스용 덱은 **지난 파싱본이 있는 것만** 보여 준다 — 부스에서 파싱 몇 분을 기다리지 않게.
 * 클래식 스크립트라 app.js 전역(nf · qa · app · $ …)을 호출 시점에 찾는다.
 */

const BOOTH_QA_KEY = 'cheokcheok:booth-qa';
const BOOTH_QA_HASH = '#/booth/qa';
/** 질문 3개 트랙 (contracts.py QA_TRACK_LIMITS["5"]) — 부스 1회 체험 3~4분 (booth-operations §2) */
const BOOTH_QA_TRACK = '5';
/**
 * 부스에서 고를 수 있는 발표. key 는 서버 ppt/<폴더> 이름이다. 제목·갈래는 부스 카드에 쓰는 이름표일 뿐,
 * 슬라이드·질문은 전부 그 덱의 실제 파싱본에서 나온다. 제목은 각 덱 표지의 질문을 옮겼다. 여기 없는 ppt/ 덱은 부스에 안 뜬다.
 */
const BOOTH_DECKS = [
  { key: '수면발표', title: '분명 잤는데 왜 피곤할까?', kind: '과학 교양 발표' },
  { key: '수익률격차', title: '개인 투자자는 왜 시장을 이기지 못하는가', kind: '분석 보고' },
  { key: 'focus_notification', title: '알림 하나 확인했을 뿐인데, 왜 다시 집중하기 어려울까?', kind: '연구 발표' },
];
/** 심사위원단 — 척척발표가 쓰는 모델 넷의 병아리 (chatter.js) */
const BOOTH_JUDGES = [
  { id: 'solar', name: '쏠라' }, { id: 'midm', name: '믿:음' },
  { id: 'exaone', name: '엑사원' }, { id: 'ax', name: '엑씨' },
];
/** 시작 화면에서 도는 말풍선. 실제 질문이 아니라서 「예시」 표를 단다 */
const BOOTH_SAMPLE_QS = [
  '이 수치는 어디서 가져왔는지 설명해 줄 수 있어요?',
  '결론이 3번 슬라이드의 근거와 어떻게 이어지나요?',
  '비교한 두 집단이 공정했는지 어떻게 확인했어요?',
];
const BOOTH_SKIM_MS = 3600;          // 훑어보기 한 장
const BOOTH_FINALE_RETURN_SEC = 40;  // 마무리 뒤 처음 화면으로
const BOOTH_PREP_POLL_MS = 400;

const bq = {
  screen: '',
  decks: null,
  deckError: '',
  covers: new Map(),       // session_id → Promise<pdf>
  prepToken: 0,
  timers: [],
  cam: { stream: null, opening: null, error: '', off: false },
  video: null,             // 판단용 숨은 video — 화면이 바뀌어도 이것 하나를 본다
  cvUnsub: null,
  observer: null,
  inputObserver: null,
  slideWatch: null,
  sampleIdx: 0,
};

function boothQaOn() {
  try { return sessionStorage.getItem(BOOTH_QA_KEY) === '1'; } catch (_) { return false; }
}

function boothQaSet(on) {
  try {
    if (on) sessionStorage.setItem(BOOTH_QA_KEY, '1');
    else sessionStorage.removeItem(BOOTH_QA_KEY);
  } catch (_) { /* 사생활 모드 — 이번 화면만 */ }
}

function bqIsBoothHash() {
  const parts = location.hash.replace(/^#\/?/, '').split('/');
  return parts[0] === 'booth' && parts[1] === 'qa';
}

/** route() 가 화면을 바꾸기 전에 부른다. 부스 흐름(#/booth/qa · #/qa)을 벗어나면 끄고 카메라도 닫는다 */
function boothQaOnRoute(key) {
  bqClearTimers();
  bqUnmount();
  if (key === 'booth' || key === 'qa') return;
  if (!boothQaOn()) return;
  boothQaSet(false);
  bqCamStop();
}

/** #/booth/qa — 새 체험. 지난 사람의 발표·질문을 지우고 시작 화면을 연다 */
function renderBoothQa() {
  if (typeof callFlowSet === 'function') callFlowSet(false);
  if (typeof visionFlowSet === 'function') visionFlowSet(false);
  boothQaSet(true);
  bq.prepToken += 1;         // 준비 중이던 체험이 있으면 그 결과를 버린다
  bqStopMic();
  resetNf();
  resetQa();
  try { sessionStorage.removeItem('cheokcheok:chuckchuck-session'); } catch (_) { /* ignore */ }
  if (window.BoothCV) { BoothCV.stopGaze(); BoothCV.load(); }
  bqShowAttract();
}

/** 처음으로 — 해시가 이미 #/booth/qa 면 hashchange 가 안 뜨므로 직접 그린다 */
function bqGoHome() {
  if (bqIsBoothHash()) { bqClearTimers(); renderBoothQa(); return; }
  location.hash = BOOTH_QA_HASH;
}

/* ─── 층 ─────────────────────────────────────────────────────────────────── */

function bqClearTimers() {
  bq.timers.forEach((t) => { clearTimeout(t); clearInterval(t); });
  bq.timers = [];
}

function bqUnmount() {
  if (bq.observer) { bq.observer.disconnect(); bq.observer = null; }
  if (bq.inputObserver) { bq.inputObserver.disconnect(); bq.inputObserver = null; }
  if (bq.slideWatch) { bq.slideWatch.disconnect(); bq.slideWatch = null; }
  const layer = document.getElementById('bqStage');
  if (layer) layer.remove();
  document.body.classList.remove('bq-open');
}

const BQ_STEPS = [
  { key: 'pick', word: '발표 고르기' },
  { key: 'prep', word: '훑어보기' },
  { key: 'qa', word: '질문 3개' },
  { key: 'finale', word: '결과' },
];

function bqTopHtml(screen) {
  const at = BQ_STEPS.findIndex((s) => s.key === screen);
  const steps = at < 0 ? '' : `<ol class="bq-steps-top" aria-label="체험 단계">${BQ_STEPS.map((s, i) => `
    <li class="${i < at ? 'done' : ''}${i === at ? ' on' : ''}"${i === at ? ' aria-current="step"' : ''}><i>${i < at ? '✓' : i + 1}</i>${s.word}</li>`).join('')}</ol>`;
  return `<header class="bq-top">
    <span class="bq-brand"><img src="assets/chuckchuck-app-icon-64.png?v=qk13" alt="">척척발표<small>Q&amp;A 체험</small></span>
    ${steps}
    <span class="bq-top-fill"></span>
    ${screen === 'attract' ? '' : '<button type="button" class="bq-ghost" data-bq-home>처음으로</button>'}
  </header>`;
}

function bqMount(screen, html) {
  bqUnmount();
  bq.screen = screen;
  app.className = '';
  app.innerHTML = '';
  const layer = document.createElement('div');
  layer.id = 'bqStage';
  layer.className = 'bq';
  layer.dataset.screen = screen;
  layer.innerHTML = `${bqTopHtml(screen)}<div class="bq-body">${html}</div>`;
  document.body.appendChild(layer);
  document.body.classList.add('bq-open');
  layer.querySelectorAll('[data-bq-home]').forEach((b) => b.addEventListener('click', bqHomeClicked));
  bqCamEnsure();
  bqCamPaint();
  return layer;
}

function bqHomeClicked() {
  const L = qa && qa.live;
  const midQa = bq.screen === 'qa' && L && !L.awaitEnd && L.qi < ((L.questions || []).length);
  if (midQa && !window.confirm('처음 화면으로 갈까요? 지금까지 답한 내용은 남지 않아요.')) return;
  bqGoHome();
}

function bqStopMic() {
  try { if (typeof liveMic !== 'undefined' && liveMic && typeof stopLiveMic === 'function') stopLiveMic(); }
  catch (_) { /* 이미 멈췄다 */ }
}

function bqBird(id, mood = '') {
  if (!window.Chatter || !Chatter.chickSvg) return '';
  return `<span class="bq-bird ch-seat" data-bird="${id}"${mood ? ` data-mood="${mood}"` : ''} aria-hidden="true">${Chatter.chickSvg(id)}</span>`;
}

/* ─── 카메라 — 한 번 연 스트림을 체험 내내 쓴다 (다시 묻지 않게) ───────────────── */

function bqCamErrorText(err) {
  if (typeof callCamErrorText === 'function') return callCamErrorText(err);
  return '카메라를 열지 못했어요. 카메라 없이도 체험할 수 있어요.';
}

async function bqCamEnsure() {
  const cam = bq.cam;
  if (cam.off) return null;
  if (cam.stream && cam.stream.getVideoTracks().some((t) => t.readyState === 'live')) return cam.stream;
  if (cam.opening) return cam.opening;
  if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) {
    cam.error = bqCamErrorText(null);
    bqCamPaint();
    return null;
  }
  // 영상만 연다 — 소리는 받아쓰기가 따로 연다 (call_flow.js 와 같은 이유)
  cam.opening = navigator.mediaDevices.getUserMedia({
    video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } },
    audio: false,
  }).then((s) => {
    cam.stream = s;
    cam.error = '';
    return s;
  }).catch((err) => {
    cam.stream = null;
    cam.error = bqCamErrorText(err);
    return null;
  }).finally(() => {
    cam.opening = null;
    bqCamPaint();
  });
  return cam.opening;
}

function bqCamStop() {
  if (bq.cam.stream) bq.cam.stream.getTracks().forEach((t) => t.stop());
  bq.cam.stream = null;
  if (window.BoothCV) BoothCV.unwatch();
  if (bq.video) bq.video.srcObject = null;
}

function bqCamLive() {
  return !!bq.cam.stream && !bq.cam.off;
}

/** 보이는 video 들과 판단용 숨은 video 에 스트림을 물린다 */
function bqCamPaint() {
  const live = bqCamLive();
  const stream = live ? bq.cam.stream : null;
  if (!bq.video) {
    bq.video = document.createElement('video');
    bq.video.muted = true;
    bq.video.playsInline = true;
    bq.video.setAttribute('aria-hidden', 'true');
  }
  if (bq.video.srcObject !== stream) {
    bq.video.srcObject = stream;
    if (stream) bq.video.play().catch(() => { /* muted 라 보통은 안 막힌다 */ });
  }
  if (window.BoothCV) {
    if (stream) BoothCV.watch(bq.video);
    else BoothCV.unwatch();
  }
  document.querySelectorAll('#bqStage video[data-bq-cam]').forEach((v) => {
    if (v.srcObject !== stream) {
      v.srcObject = stream;
      if (stream) v.play().catch(() => {});
    }
  });
  document.querySelectorAll('#bqStage [data-bq-cam-box]').forEach((box) => { box.dataset.camera = live ? 'on' : 'off'; });
  const note = document.getElementById('bqCamNote');
  if (note) note.textContent = bq.cam.off ? '카메라를 껐어요' : (bq.cam.error || (bq.cam.opening ? '카메라를 여는 중이에요' : ''));
  const btn = document.getElementById('bqCamToggle');
  if (btn) btn.textContent = live ? '카메라 끄기' : '카메라 켜기';
  bqWireCv();
}

function bqCamToggle() {
  if (bqCamLive()) {
    bq.cam.off = true;
    bqCamStop();
    bqCamPaint();
    return;
  }
  bq.cam.off = false;
  bq.cam.error = '';
  bqCamPaint();
  bqCamEnsure();
}

/* ─── 카메라 판단 → 화면 ───────────────────────────────────────────────── */

function bqWireCv() {
  if (bq.cvUnsub || !window.BoothCV) return;
  bq.cvUnsub = BoothCV.subscribe(bqOnCv);
}

function bqOnCv(s) {
  const layer = document.getElementById('bqStage');
  if (!layer) return;
  layer.dataset.present = s.present ? '1' : '0';
  const status = document.getElementById('bqCvStatus');
  if (status) status.textContent = bqCvStatusText(s);
  if (bq.screen === 'attract' && s.arrived) bqGreet();
  const hint = document.getElementById('bqHint');
  if (hint) {
    hint.textContent = s.hint || '';
    hint.hidden = !s.hint;
  }
  bqPaintFaceBox(s.face);
  const gaze = document.getElementById('bqGazeNow');
  if (gaze) {
    const pct = window.BoothCvLogic ? BoothCvLogic.gazePercent(s.gaze) : null;
    gaze.textContent = pct === null ? '' : `정면 ${pct}%`;
    gaze.hidden = pct === null;
  }
}

function bqCvStatusText(s) {
  if (!bqCamLive()) return bq.cam.error ? '카메라 없이도 체험할 수 있어요' : '';
  if (s.status === 'loading') return '얼굴을 찾을 준비를 하고 있어요';
  if (s.status === 'failed') return '카메라 판단 없이 진행해요';
  if (s.status !== 'ready') return '';
  return s.present ? '반가워요! 앞에 서 있는 모습이 보여요' : '앞에 서면 병아리들이 인사해요';
}

/** 얼굴 테두리 — 내 모습 창(거울처럼 뒤집어 보인다)에 맞춰 좌우를 뒤집는다 */
function bqPaintFaceBox(face) {
  const box = document.getElementById('bqFace');
  if (!box) return;
  if (!face || !bqCamLive()) { box.hidden = true; return; }
  box.hidden = false;
  box.style.left = `${((1 - face.cx) - face.w / 2) * 100}%`;
  box.style.top = `${(face.cy - face.h / 2) * 100}%`;
  box.style.width = `${face.w * 100}%`;
  box.style.height = `${face.h * 100}%`;
}

/* ─── S0 시작 ──────────────────────────────────────────────────────────── */

function bqShowAttract() {
  bqMount('attract', `
    <div class="bq-attract">
      <section class="bq-hero">
        <p class="bq-eyebrow">부스 Q&amp;A 체험</p>
        <h1>발표 자료를 읽은 AI가<br>심사위원처럼 물어봐요</h1>
        <p class="bq-lead">발표 하나를 고르고 질문 3개에 답해 보세요. 3분이면 끝나요.</p>
        <button type="button" class="bq-cta" id="bqStart">체험 시작하기</button>
        <ol class="bq-how">
          <li><b>1</b><span>발표를 골라요</span></li>
          <li><b>2</b><span>30초 동안 훑어봐요</span></li>
          <li><b>3</b><span>질문 3개에 말로 답해요</span></li>
        </ol>
      </section>
      <aside class="bq-panel">
        <div class="bq-bubble" id="bqGreet" aria-live="polite">
          <span class="bq-bubble-tag">예시 질문</span>
          <p id="bqGreetText">${escapeHtml(BOOTH_SAMPLE_QS[0])}</p>
        </div>
        <div class="bq-judges">${BOOTH_JUDGES.map((j) => `
          <figure>${bqBird(j.id)}<figcaption>${escapeHtml(j.name)}</figcaption></figure>`).join('')}</div>
        <div class="bq-mirror" data-bq-cam-box data-camera="off">
          <video data-bq-cam autoplay muted playsinline></video>
          <p><b id="bqCvStatus"></b><span id="bqCamNote"></span></p>
        </div>
      </aside>
      <p class="bq-privacy">카메라 영상은 이 컴퓨터 안에서만 봐요. 저장하거나 보내지 않아요.</p>
    </div>`);
  $('#bqStart').addEventListener('click', bqShowPick);
  bq.sampleIdx = 0;
  bq.timers.push(setInterval(bqRotateSample, 4200));
  if (window.BoothCV) bqOnCv(BoothCV.snapshot());
}

function bqRotateSample() {
  const box = document.getElementById('bqGreet');
  if (!box || box.dataset.greeting === '1') return;
  bq.sampleIdx = (bq.sampleIdx + 1) % BOOTH_SAMPLE_QS.length;
  const p = document.getElementById('bqGreetText');
  if (!p) return;
  box.classList.remove('swap');
  void box.offsetWidth;   // 같은 애니메이션을 다시 태운다
  box.classList.add('swap');
  p.textContent = BOOTH_SAMPLE_QS[bq.sampleIdx];
}

/** 사람이 다가오면 — 병아리들이 돌아보고 말풍선이 인사로 바뀐다. 몇 초 뒤 예시로 돌아간다 */
function bqGreet() {
  const box = document.getElementById('bqGreet');
  if (!box) return;
  box.dataset.greeting = '1';
  box.querySelector('.bq-bubble-tag').textContent = '반가워요';
  document.getElementById('bqGreetText').textContent = '안녕하세요! 내 답을 자료와 맞춰 보는 질문, 받아 볼래요?';
  document.querySelectorAll('#bqStage .bq-judges .bq-bird').forEach((b, i) => {
    b.dataset.mood = i % 2 ? 'excited' : 'happy';
  });
  const cta = document.getElementById('bqStart');
  if (cta) cta.classList.add('pulse');
  bq.timers.push(setTimeout(() => {
    if (!document.getElementById('bqGreet')) return;
    box.dataset.greeting = '';
    box.querySelector('.bq-bubble-tag').textContent = '예시 질문';
    document.querySelectorAll('#bqStage .bq-judges .bq-bird').forEach((b) => { b.dataset.mood = ''; });
    bqRotateSample();
  }, 9000));
}

/* ─── S1 발표 고르기 ───────────────────────────────────────────────────── */

async function bqLoadDecks() {
  if (bq.decks) return bq.decks;
  const res = await fetch('/api/v1/dev/decks', { credentials: 'same-origin' });
  if (res.status === 404) throw new Error('부스 노트북에서 개발자 모드를 켜야 열려요. 주소창에 /auth 를 열어 팀 코드를 넣어 주세요.');
  if (!res.ok) throw new Error(`발표 목록을 못 받았어요 (HTTP ${res.status})`);
  const body = (await res.json()) || {};
  const rows = body.decks || [];
  const byKey = new Map(rows.map((r) => [String(r.key || '').normalize('NFC'), r]));
  bq.decks = BOOTH_DECKS.map((d) => ({ ...d, row: byKey.get(d.key.normalize('NFC')) || null }));
  return bq.decks;
}

function bqDeckReady(d) {
  return !!(d.row && d.row.cached_session_id);
}

async function bqShowPick() {
  bqClearTimers();
  bqMount('pick', `
    <div class="bq-pick">
      <h1 class="bq-h1">어떤 발표로 질문을 받아 볼까요?</h1>
      <p class="bq-lead">고른 발표의 발표자가 됐다고 생각하고 답하면 돼요. 질문은 그 자료에서만 나와요.</p>
      <div class="bq-decks" id="bqDecks"><p class="bq-wait">발표를 불러오고 있어요…</p></div>
      <p class="bq-foot" id="bqDeckFoot"></p>
    </div>`);
  let decks;
  try {
    decks = await bqLoadDecks();
  } catch (err) {
    const box = $('#bqDecks');
    if (box) box.innerHTML = `<div class="bq-fail"><b>발표 목록을 못 불러왔어요</b><p>${escapeHtml(String(err.message || err))}</p>
      <button type="button" class="bq-ghost" id="bqDeckRetry">다시 불러오기</button></div>`;
    const retry = $('#bqDeckRetry');
    if (retry) retry.addEventListener('click', () => { bq.decks = null; bqShowPick(); });
    return;
  }
  if (bq.screen !== 'pick') return;
  const ready = decks.filter(bqDeckReady);
  const box = $('#bqDecks');
  if (!ready.length) {
    box.innerHTML = `<div class="bq-fail"><b>지금 고를 수 있는 발표가 없어요</b>
      <p>부스용 발표를 개발 화면 /test/qa 에서 한 번씩 열어 두면 여기에 나타나요.</p></div>`;
    return;
  }
  box.innerHTML = ready.map((d) => `
    <button type="button" class="bq-deck" data-deck="${escapeHtml(d.key)}">
      <span class="bq-cover"><canvas data-cover="${escapeHtml(d.row.cached_session_id)}"></canvas><i>표지를 불러오고 있어요</i></span>
      <span class="bq-deck-kind" data-pages="${escapeHtml(d.row.cached_session_id)}">${escapeHtml(d.kind)}</span>
      <b class="bq-deck-title">${escapeHtml(d.title)}</b>
      <span class="bq-deck-go">이 발표로 질문 받기</span>
    </button>`).join('');
  const missing = decks.length - ready.length;
  const foot = $('#bqDeckFoot');
  if (foot && missing) foot.textContent = `준비 안 된 발표 ${missing}개는 숨겼어요 (운영진: /test/qa 에서 한 번 열면 나타나요)`;
  box.querySelectorAll('[data-deck]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const d = ready.find((x) => x.key === btn.dataset.deck);
      if (d) bqPrepare(d);
    });
  });
  ready.forEach((d) => bqPaintCover(d));
}

function bqCoverPdf(sessionId) {
  if (!bq.covers.has(sessionId)) {
    if (!window.pdfjsLib) return Promise.reject(new Error('pdf.js 가 없어요'));
    const url = `/api/v1/preview-pdf?session_id=${encodeURIComponent(sessionId)}`;
    const p = pdfjsLib.getDocument({ url }).promise;
    p.catch(() => bq.covers.delete(sessionId));
    bq.covers.set(sessionId, p);
  }
  return bq.covers.get(sessionId);
}

async function bqPaintCover(d) {
  const sid = d.row.cached_session_id;
  const canvas = document.querySelector(`#bqStage canvas[data-cover="${CSS.escape(sid)}"]`);
  if (!canvas) return;
  try {
    const pdf = await bqCoverPdf(sid);
    const page = await pdf.getPage(1);
    const base = page.getViewport({ scale: 1 });
    const vp = page.getViewport({ scale: Math.min(2, 520 / base.width) });
    canvas.width = Math.floor(vp.width);
    canvas.height = Math.floor(vp.height);
    await page.render({ canvasContext: canvas.getContext('2d'), viewport: vp }).promise;
    if (!canvas.isConnected) return;
    canvas.parentElement.classList.add('ready');
    const kind = document.querySelector(`#bqStage [data-pages="${CSS.escape(sid)}"]`);
    if (kind) kind.textContent = `${d.kind} · ${pdf.numPages}장`;
  } catch (err) {
    if (canvas.isConnected) canvas.parentElement.querySelector('i').textContent = '표지를 못 불러왔어요';
    console.warn('[chuckchuck] booth cover', err);
  }
}

/* ─── S2 훑어보기 + 질문 준비 ────────────────────────────────────────────── */

const BQ_PREP_STEPS = [
  { key: 'doc', word: '발표 자료를 펼쳐요' },
  { key: 'concepts', word: '핵심 개념을 찾아요' },
  { key: 'graph', word: '개념 사이를 이어요' },
  { key: 'questions', word: '질문 3개를 골라요' },
];

function bqPrepHtml(d) {
  return `
    <div class="bq-prep">
      <section class="bq-skim">
        <div class="bq-skim-frame"><canvas id="bqSkimCanvas" aria-label="발표 슬라이드"></canvas><i id="bqSkimWait">슬라이드를 펼치고 있어요</i></div>
        <div class="bq-skim-bar">
          <button type="button" class="bq-ghost bq-round" data-skim="-1" aria-label="이전 슬라이드">‹</button>
          <span class="bq-skim-meta"><b id="bqSkimNo" class="num"></b><span id="bqSkimTitle"></span></span>
          <button type="button" class="bq-ghost bq-round" data-skim="1" aria-label="다음 슬라이드">›</button>
        </div>
        <p class="bq-skim-tip">「${escapeHtml(d.title)}」의 발표자가 됐다고 생각하고 훑어보세요. 질문은 이 자료에서 나와요.</p>
      </section>
      <aside class="bq-build">
        <h2>질문을 만들고 있어요</h2>
        <ol class="bq-build-steps" id="bqBuildSteps">${BQ_PREP_STEPS.map((s) => `
          <li data-step="${s.key}" data-state="wait"><i></i><span>${s.word}</span></li>`).join('')}</ol>
        <p class="bq-elapsed" id="bqElapsed">0초 지났어요</p>
        <div id="bqPrepFail"></div>
        <button type="button" class="bq-cta" id="bqGo" disabled>질문을 만들고 있어요…</button>
        <button type="button" class="bq-ghost" id="bqRepick">다른 발표 고르기</button>
      </aside>
    </div>`;
}

function bqSetStep(key, state) {
  const li = document.querySelector(`#bqBuildSteps [data-step="${key}"]`);
  if (li && li.dataset.state !== state) li.dataset.state = state;
}

function bqPrepFail(message, d) {
  const box = document.getElementById('bqPrepFail');
  if (!box) return;
  box.innerHTML = `<div class="bq-fail"><b>질문을 만들다 멈췄어요</b><p>${escapeHtml(message)}</p>
    <button type="button" class="bq-ghost" id="bqRetry">다시 해 보기</button></div>`;
  const go = document.getElementById('bqGo');
  if (go) { go.disabled = true; go.textContent = '질문을 만들지 못했어요'; }
  document.getElementById('bqRetry').addEventListener('click', () => bqPrepare(d));
}

/**
 * 덱 하나를 질문 3개까지 준비한다 — #/test/qa 의 startTestDeck 3-a(자료만)와 같은 길이지만
 * #/new 화면을 거치지 않는다. 지난 파싱본이 있는 덱만 여기 온다.
 */
async function bqPrepare(d) {
  bqClearTimers();
  const token = ++bq.prepToken;
  const alive = () => token === bq.prepToken && bq.screen === 'prep';
  bqMount('prep', bqPrepHtml(d));
  $('#bqRepick').addEventListener('click', () => { bq.prepToken += 1; bqShowPick(); });
  const go = $('#bqGo');
  go.addEventListener('click', () => { if (!go.disabled) location.hash = '#/qa'; });
  const startedAt = Date.now();
  bq.timers.push(setInterval(() => {
    const el = document.getElementById('bqElapsed');
    if (el) el.textContent = `${Math.round((Date.now() - startedAt) / 1000)}초 지났어요`;
  }, 1000));

  resetNf();
  resetQa();
  nf.occ = TEST_DECK_OCC;
  nf.ctx = '';
  nf.occTouched = true;
  nf.fileName = d.row.deck;
  nf.sessionId = d.row.cached_session_id;
  if (typeof setUploadedPdf === 'function') setUploadedPdf(null);   // 앞 사람 덱의 PDF 가 남아 있으면 그 장이 그려진다

  // 1. 파싱본 되살리기 — 미리보기 PDF 까지 메모리에 올린다 (#/replay · #/test/qa 와 같다)
  bqSetStep('doc', 'run');
  const doc = await ensureSlideDoc();
  if (!alive()) return;
  if (!doc) {
    bqSetStep('doc', 'fail');
    bqPrepFail('지난 파싱본을 못 찾았어요. 운영진이 /test/qa 에서 이 발표를 한 번 열어 두면 돼요.', d);
    return;
  }
  applySlideDoc(doc, { keepDemoImages: false });
  nf.fileName = doc.file_name || d.row.deck;
  nf.gate = 'done';
  nf.occ = TEST_DECK_OCC;
  nf.occTouched = true;
  bqSetStep('doc', 'done');
  bqStartSkim();

  // 2. 발표 정보 화면의 「다음」이 하는 일 — 개념·그래프 선분석
  nf.step = 1;
  startPrecompute();
  nf.step = 2;
  saveSession('new-flow', nf);
  if (!precompute || !precompute.graphP) {
    bqPrepFail('자료를 분석하는 모듈을 부르지 못했어요. 새로고침하면 다시 불러와요.', d);
    return;
  }
  bqSetStep('concepts', 'run');
  const poll = setInterval(() => {
    const st = (precompute && precompute.state) || {};
    if (st.conceptsReady) { bqSetStep('concepts', 'done'); bqSetStep('graph', st.graphReady ? 'done' : 'run'); }
  }, BOOTH_PREP_POLL_MS);
  bq.timers.push(poll);
  let graph = null;
  try {
    graph = await precompute.graphP;
  } catch (err) {
    if (!alive()) return;
    const st = (precompute && precompute.state) || {};
    bqSetStep(st.conceptsReady ? 'graph' : 'concepts', 'fail');
    bqPrepFail(humanErrorText(String((err && err.message) || err)), d);
    return;
  }
  clearInterval(poll);
  if (!alive()) return;
  bqSetStep('concepts', 'done');
  bqSetStep('graph', 'done');
  nf.pipelineOut = { ...(nf.pipelineOut || {}), graph };
  nf.pipelinePhase = 'partial';     // 정합·흐름은 없다 — 자료만으로 묻는 질문이라는 뜻 (#/test/qa 와 같다)
  nf.pipelineDetail = '부스 체험 — 자료만으로 그래프까지 만들었어요. 받아쓰기·정합은 없어요.';
  saveSession('new-flow', nf);

  // 3. 질문 3개 — #/qa 로 가기 전에 여기서 만든다. 만드는 동안 사람은 슬라이드를 훑는다
  qa.mode = BOOTH_QA_TRACK;
  qa.aud = '심사위원';        // 말풍선 아바타 「심」 — 무대의 심사위원과 같은 사람으로 보이게 (질문·판정 요청에는 안 실린다)
  qa.started = true;
  saveSession('qa-flow', qa);
  bqSetStep('questions', 'run');
  ensureLiveQuestions();
  const waitQ = setInterval(() => {
    if (!alive()) { clearInterval(waitQ); return; }
    if (qaLiveActive()) {
      clearInterval(waitQ);
      bqSetStep('questions', 'done');
      go.disabled = false;
      go.textContent = '질문 받으러 가기';
      go.classList.add('pulse');
      go.focus();
      return;
    }
    if (qaBuildFailed && !qaBuilding) {
      clearInterval(waitQ);
      bqSetStep('questions', 'fail');
      bqPrepFail(qa.liveError || '질문 생성 요청이 실패했어요.', d);
    }
  }, BOOTH_PREP_POLL_MS);
  bq.timers.push(waitQ);
}

/* 훑어보기 — 준비하는 동안 슬라이드가 한 장씩 넘어간다. 손으로 넘기면 그 장에서 잠시 멈춘다 */
function bqStartSkim() {
  const total = rehearsalCount();
  let at = 1;
  let holdUntil = 0;
  const paint = async () => {
    const canvas = document.getElementById('bqSkimCanvas');
    if (!canvas) return;
    const no = document.getElementById('bqSkimNo');
    const title = document.getElementById('bqSkimTitle');
    if (no) no.textContent = `${at} / ${total}`;
    if (title) title.textContent = ((nf.slideTitles || [])[at - 1] || '').trim();
    if (!uploadedPdf) return;
    const ok = await renderPdfToCanvas(at, canvas, { maxWidth: 1200 });
    const wait = document.getElementById('bqSkimWait');
    if (ok && wait) wait.hidden = true;
  };
  const step = (dir) => { at = ((at - 1 + dir + total) % total) + 1; paint(); };
  document.querySelectorAll('#bqStage [data-skim]').forEach((b) => b.addEventListener('click', () => {
    holdUntil = Date.now() + BOOTH_SKIM_MS * 2;
    step(Number(b.dataset.skim));
  }));
  paint();
  bq.timers.push(setInterval(() => { if (Date.now() >= holdUntil) step(1); }, BOOTH_SKIM_MS));
}

/* ─── S3 Q&A 무대 (#/qa · qa_live.js renderQaLive 가 부른다) ───────────────── */

function bqCurrentQuestionTurn() {
  for (let i = qa.turns.length - 1; i >= 0; i -= 1) {
    const t = qa.turns[i];
    if (t.who === 'ai' && (t.kind === 'question' || t.kind === 'claim')) return t;
  }
  return null;
}

function bqSpotHtml() {
  const L = qa.live;
  const n = L.questions.length;
  if (L.awaitEnd || L.qi >= n) {
    return `<p class="bq-spot-meta">질문 ${n}개를 모두 마쳤어요</p>
      <p class="bq-spot-q">수고했어요! 아래 「결과 확인하기」를 누르면 오늘의 결과가 나와요.</p>`;
  }
  const t = bqCurrentQuestionTurn();
  const q = L.questions[L.qi] || {};
  const slides = (q.slide_nos || []).filter(Boolean);
  // 되묻기(qa_live.js askAgain)도 question 말풍선으로 온다 — 지금 답할 말은 그것이라 카드에 올리고, 되묻기라고 밝힌다
  const follow = t && bqIsFollowUp(t);
  const choices = (t && t.choices) || [];
  return `<p class="bq-spot-meta"><b>질문 ${L.qi + 1}</b><span>/ ${n}</span>${q.severity === 1 && !follow ? '<em>꼭 넘어야 해요</em>' : ''}${follow ? `<em class="is-follow">${t.meta || '한 번 더 물어요'}</em>` : ''}</p>
    <p class="bq-spot-q">${t ? t.text : escapeHtml(q.question || '')}</p>
    ${choices.length ? `<div class="qa-choices bq-choices">${choices.map((c) => `<button type="button" class="qa-choice-chip">${c}</button>`).join('')}</div>` : ''}
    ${slides.length ? `<p class="bq-spot-basis">근거 자료 · ${slides.slice(0, 3).map((s) => `${s}장`).join(' · ')}</p>` : ''}`;
}

/** 처음 묻는 질문은 머리말이 「예상 질문 n/N」 이다 (qa_live.js presentLiveQuestion). 나머지는 되묻기 */
function bqIsFollowUp(t) {
  return !String(t.meta || '').startsWith('예상 질문');
}

function bqProgressHtml() {
  const L = qa.live;
  return `<ol class="bq-prog" aria-label="질문 진행">${L.questions.map((q, i) => {
    const r = (L.results || [])[i];
    const row = r && typeof liveResultRow === 'function' ? liveResultRow(r) : null;
    const state = row ? row.cls : (i === L.qi && !L.awaitEnd ? 'now' : '');
    return `<li class="${state}"><span>질문 ${i + 1}</span>${row ? `<em>${escapeHtml(row.chip)}</em>` : ''}</li>`;
  }).join('')}</ol>`;
}

function bqQaSlideNo() {
  const L = qa.live;
  const q = L && L.questions && L.questions[Math.min(L.qi, L.questions.length - 1)];
  return Number(((q && q.slide_nos) || [])[0]) || 1;
}

/* 큰 슬라이드는 썸네일(240px)을 늘리면 부스 거리에서 뭉개진다 — 무대용 렌더(app.js paintDeckStage)로 크게 그린다 */
function bqSlideHtml(no) {
  const pic = uploadedPdf
    ? `<span class="bq-slide-pic"><canvas data-stage-page="${no}" aria-label="${no}번 슬라이드"></canvas></span>`
    : `<span class="bq-slide-pic"><img src="${deckImageSrc(no)}" alt="${no}번 슬라이드"></span>`;
  return `<figcaption>질문이 가리키는 <b>${no}장</b></figcaption>${pic}`;
}

/** 판정이 붙으면 심사위원 표정이 바뀐다. 판정 칩(색)은 스트림 쪽이 말하고, 표정은 거기에 얹는 층이다 */
function bqJudgeMood() {
  for (let i = qa.turns.length - 1; i >= 0; i -= 1) {
    const t = qa.turns[i];
    if (t.who === 'me') return 'curious';
    if ((t.kind === 'question' || t.kind === 'claim') && !bqIsFollowUp(t)) return '';
    if (t.kind === 'react' && !t.coach) return t.verdict === 'full' ? 'happy' : (t.verdict === 'partial' ? 'curious' : 'grumpy');
    if (t.kind === 'done') return t.outcome === 'good' ? 'excited' : '';
  }
  return '';
}

function bqQaSync() {
  const spot = document.getElementById('bqSpot');
  if (spot) {
    const next = bqSpotHtml();
    if (spot.dataset.html !== next) {
      spot.dataset.html = next;
      spot.innerHTML = next;
      spot.classList.remove('enter');
      void spot.offsetWidth;
      spot.classList.add('enter');
    }
  }
  const prog = document.getElementById('bqProg');
  if (prog) prog.innerHTML = bqProgressHtml();
  const slide = document.getElementById('bqSlide');
  const no = bqQaSlideNo();
  if (slide && Number(slide.dataset.no) !== no) {
    slide.dataset.no = String(no);
    slide.innerHTML = bqSlideHtml(no);
    paintDeckStage(slide);
  }
  const judge = document.querySelector('#bqStage .bq-judge .bq-bird');
  const thinking = !!document.getElementById('coachThinking');
  if (judge) {
    const mood = thinking ? 'curious' : bqJudgeMood();
    if ((judge.dataset.mood || '') !== mood) judge.dataset.mood = mood;
  }
  const say = document.getElementById('bqJudgeSay');
  if (say) say.textContent = thinking ? '듣고 있어요' : (qa.live.awaitEnd ? '오늘 질문은 여기까지예요' : '답을 기다리고 있어요');
}

function renderQaLiveBooth() {
  const no = bqQaSlideNo();
  bqMount('qa', `
    <div class="bq-qa">
      <section class="bq-main">
        <div class="bq-qa-head">
          <div class="bq-judge">${bqBird('solar')}<span><b>쏠라 심사위원</b><small id="bqJudgeSay">답을 기다리고 있어요</small></span></div>
          <div id="bqProg">${bqProgressHtml()}</div>
        </div>
        <article class="bq-spot" id="bqSpot" aria-live="polite"></article>
        <div class="qa-stream bq-feed" id="stream">${qa.turns.map(streamRow).join('')}</div>
        <div class="card qa-live-input bq-answer">${liveInputHtml()}</div>
      </section>
      <aside class="bq-side">
        <figure class="bq-slide" id="bqSlide" data-no="${no}">${bqSlideHtml(no)}</figure>
        <div class="bq-self" data-bq-cam-box data-camera="off">
          <video data-bq-cam autoplay muted playsinline></video>
          <i class="bq-facebox" id="bqFace" hidden></i>
          <p class="bq-hint" id="bqHint" hidden></p>
          <span class="bq-gaze-now" id="bqGazeNow" hidden></span>
          <p class="bq-self-note"><span id="bqCamNote"></span><b id="bqCvStatus"></b></p>
          <button type="button" class="bq-ghost bq-cam-btn" id="bqCamToggle">카메라 끄기</button>
        </div>
      </aside>
    </div>`);
  $('#bqCamToggle').addEventListener('click', bqCamToggle);
  if (window.BoothCV && !BoothCV.readGaze()) BoothCV.startGaze();
  bqQaSync();
  const stream = $('#stream');
  if (stream) {
    bq.observer = new MutationObserver(bqQaSync);
    bq.observer.observe(stream, { childList: true });
  }
  paintDeckThumbs(document.getElementById('bqStage'));
  bqWatchSlide();
  bqCamPaint();
  scrollDown();
  wireLiveInput();
  // 입력 카드는 판정·힌트 때마다 qa_live.js refreshLiveChrome 이 통째로 갈아 끼운다 — 그때마다 부스 문구로 다시 맞춘다
  const card = document.querySelector('#bqStage .bq-answer');
  if (card) {
    bq.inputObserver = new MutationObserver(bqRelabelInput);
    bq.inputObserver.observe(card, { childList: true });
  }
  bqRelabelInput();
}

/** 슬라이드는 그린 폭 그대로 남는다(canvas) — 창 크기가 바뀌면 그 칸 폭으로 다시 그린다 */
function bqWatchSlide() {
  const fig = document.getElementById('bqSlide');
  if (!fig) return;
  paintDeckStage(fig);
  if (!window.ResizeObserver) return;
  let lastW = 0;
  let timer = 0;
  bq.slideWatch = new ResizeObserver(() => {
    const w = Math.round(fig.clientWidth);
    if (!w || Math.abs(w - lastW) < 24) return;
    lastW = w;
    clearTimeout(timer);
    timer = setTimeout(() => { if (fig.isConnected) paintDeckStage(fig); }, 180);
  });
  bq.slideWatch.observe(fig);
}

/** 부스는 코칭 기록을 남기지 않는다 — 「여기까지 하고 저장」 은 여기서 거짓말이다 */
function bqRelabelInput() {
  const finish = document.getElementById('liveFinish');
  if (finish && finish.textContent !== '여기까지 하고 결과 보기') finish.textContent = '여기까지 하고 결과 보기';
}

/* ─── S4 마무리 (qa_live.js qaLiveEnd 가 부른다) ──────────────────────────── */

function boothQaFinale() {
  bqStopMic();
  qa.ended = true;
  if (nf) { nf.completed = true; saveSession('new-flow', nf); }
  saveSession('qa-flow', qa);
  // 부스 노트북의 코칭 기록(qa-history)에는 남기지 않는다 — 방문객 수백 명의 답이 쌓이면 다음 사람이 본다
  const L = qa.live;
  const sum = liveResultSummary(L.results, { speech: false });
  const gaze = window.BoothCV ? BoothCV.stopGaze() : null;
  const pct = window.BoothCvLogic ? BoothCvLogic.gazePercent(gaze) : null;
  const oneLine = (s) => {
    const t = String(s || '').replace(/\s+/g, ' ').trim();
    return t.length > 70 ? `${t.slice(0, 69)}…` : t;
  };
  const rows = L.questions.map((q, i) => {
    const r = (L.results || [])[i] || { unasked: true };
    const row = liveResultRow(r);
    return `<li>
      <span class="bq-fin-no">${i + 1}</span>
      <span class="bq-fin-q"><b>${escapeHtml(q.label || `질문 ${i + 1}`)}</b><small>${escapeHtml(oneLine(q.question))}</small></span>
      <span class="chip chip-sm ${row.cls}">${escapeHtml(row.chip)}</span>
    </li>`;
  }).join('');
  const happy = sum.self > 0;
  bqMount('finale', `
    <div class="bq-finale">
      <section class="bq-fin-main">
        <div class="bq-judges bq-judges-sm">${BOOTH_JUDGES.map((j, i) => bqBird(j.id, happy ? (i % 2 ? 'excited' : 'happy') : 'curious')).join('')}</div>
        <p class="bq-eyebrow">체험을 마쳤어요</p>
        <h1 class="bq-fin-head">${sum.head}</h1>
        <ol class="bq-fin-list">${rows}</ol>
      </section>
      <aside class="bq-fin-side">
        ${pct === null ? '' : `<div class="bq-card bq-gaze">
          <span>질문을 받는 동안 얼굴이 정면으로 잡힌 시간</span>
          <b class="num">${pct}<small>%</small></b>
          <p>카메라가 정면 얼굴을 찾은 순간의 비율이에요. 심사위원을 보고 답하면 올라가요.</p>
        </div>`}
        <div class="bq-card bq-more">
          <b>내 발표 자료로도 해 볼 수 있어요</b>
          <p>chuckchuck-present.com 에서 자료를 올리고 발표를 녹음하면, 내 말과 자료를 맞춰 보는 질문이 나와요.</p>
        </div>
        <button type="button" class="bq-cta" data-bq-home>처음으로 돌아가기</button>
        <p class="bq-return" id="bqReturn"></p>
      </aside>
    </div>`);
  bqStartReturnCountdown();
  document.querySelectorAll('#bqStage .bq-fin-head .num[data-count]').forEach((el) => {
    if (typeof countUp === 'function') countUp(el, Number(el.dataset.count) || 0, 600);
  });
}

/** 마무리 화면은 가만히 두면 처음 화면으로 돌아간다. 누가 만지면 다시 센다 */
function bqStartReturnCountdown() {
  let left = BOOTH_FINALE_RETURN_SEC;
  const paint = () => {
    const el = document.getElementById('bqReturn');
    if (el) el.textContent = `${left}초 뒤 처음 화면으로 돌아가요`;
  };
  const reset = () => { left = BOOTH_FINALE_RETURN_SEC; paint(); };
  const layer = document.getElementById('bqStage');
  if (layer) {
    layer.addEventListener('pointerdown', reset);
    layer.addEventListener('keydown', reset);
  }
  paint();
  bq.timers.push(setInterval(() => {
    left -= 1;
    if (left <= 0) { bqGoHome(); return; }
    paint();
  }, 1000));
}
