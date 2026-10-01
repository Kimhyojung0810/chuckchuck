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
/**
 * 같은 부스 흐름의 화상 통화판 — 주소창 /booth/call (→ #/booth/call). 시작 · 발표 고르기 · 준비 · 마무리는 같고,
 * 질문 화면만 내 얼굴이 정면 · 왼쪽 아래 삐약이가 역할을 맡아 묻고 · 대화가 글라스로 얹힌다 (js/booth_call.js).
 * 2026-10-01 사용자: "부스를 위해서 만드는 전용 QA 페이지 … 왼쪽 하단에 삐약이가 나와서 QA 를 진행하고(교수님이건
 * 어떤 역할이던 위임) 나는 정면에 … 내 대화와 삐약이 대화가 애플 liquid glass 처럼 은은하게 오버레이".
 */
const BOOTH_CALL_HASH = '#/booth/call';
/**
 * 삐약이가 맡는 역할. aud 는 qa.aud(app.js PERSONAS 의 이름)이고, 질문 코칭 화면에서도 **말풍선 이름표로만** 쓴다 —
 * 질문·판정 요청에는 실리지 않으므로 역할에 따라 질문 내용이 바뀌지 않는다. 그래서 설명도 「누가 묻는 자리인지」 만 적는다.
 */
const BOOTH_ROLES = [
  { aud: '교수님', where: '수업 발표 자리' },
  { aud: '심사위원', where: '공모전 심사 자리' },
  { aud: '회사 상사', where: '팀 보고 자리' },
  { aud: '일반 청중', where: '처음 듣는 청중 앞' },
];
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
  variant: 'stage',        // stage(/booth/qa) · call(/booth/call)
  role: BOOTH_ROLES[0].aud,
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
  dockWatch: null,         // 화상판 답 칸 높이 (booth_call.js)
  sampleIdx: 0,
};

/** 부스 흐름이 켜져 있으면 'stage' 또는 'call', 아니면 '' — 탭 단위로 기억해 #/qa 로 넘어가도 어느 무대인지 안다 */
function boothQaVariant() {
  try {
    const v = sessionStorage.getItem(BOOTH_QA_KEY);
    if (v === 'call') return 'call';
    return v === '1' ? 'stage' : '';
  } catch (_) { return ''; }
}

function boothQaOn() {
  return !!boothQaVariant();
}

function boothQaSet(on, variant = 'stage') {
  try {
    if (on) sessionStorage.setItem(BOOTH_QA_KEY, variant === 'call' ? 'call' : '1');
    else sessionStorage.removeItem(BOOTH_QA_KEY);
  } catch (_) { /* 사생활 모드 — 이번 화면만 */ }
}

/** 지금 주소의 부스 무대 — #/booth/qa → stage, #/booth/call → call, 그 밖이면 '' */
function bqHashVariant() {
  const parts = location.hash.replace(/^#\/?/, '').split('/');
  if (parts[0] !== 'booth') return '';
  if (parts[1] === 'qa') return 'stage';
  return parts[1] === 'call' ? 'call' : '';
}

function bqIsBoothHash() {
  return !!bqHashVariant();
}

function bqHomeHash() {
  return bq.variant === 'call' ? BOOTH_CALL_HASH : BOOTH_QA_HASH;
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

/** #/booth/qa · #/booth/call — 새 체험. 지난 사람의 발표·질문을 지우고 시작 화면을 연다 */
function renderBoothQa(variant = bqHashVariant() || 'stage') {
  if (typeof callFlowSet === 'function') callFlowSet(false);
  if (typeof visionFlowSet === 'function') visionFlowSet(false);
  bq.variant = variant === 'call' ? 'call' : 'stage';
  bq.role = BOOTH_ROLES[0].aud;     // 역할도 다음 방문객에게 넘기지 않는다
  // 앞 방문객이 끈 카메라 · 죽은 실시간 받아쓰기를 다음 사람에게 넘기지 않는다 — 안 그러면 그날 내내 꺼진 채다 (10-01 점검)
  bq.cam.off = false;
  bq.cam.error = '';
  if (typeof liveDictationDead !== 'undefined') liveDictationDead = false;
  if (typeof bqInstallKeys === 'function') bqInstallKeys();
  boothQaSet(true, bq.variant);
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
  location.hash = bqHomeHash();
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
  if (bq.dockWatch) { bq.dockWatch.disconnect(); bq.dockWatch = null; }
  if (typeof bqDisarmIdle === 'function') { bqDisarmIdle(); bqStopAutoEnd(); }
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

function bqStepWord(s) {
  return bq.variant === 'call' && s.key === 'pick' ? '발표·역할 고르기' : s.word;
}

function bqTopHtml(screen) {
  const at = BQ_STEPS.findIndex((s) => s.key === screen);
  const steps = at < 0 ? '' : `<ol class="bq-steps-top" aria-label="체험 단계">${BQ_STEPS.map((s, i) => `
    <li class="${i < at ? 'done' : ''}${i === at ? ' on' : ''}"${i === at ? ' aria-current="step"' : ''}><i aria-hidden="true">${i < at ? '✓' : i + 1}</i>${bqStepWord(s)}${i < at ? '<span class="bq-sr"> · 마쳤어요</span>' : ''}</li>`).join('')}</ol>`;
  return `<header class="bq-top">
    <span class="bq-brand"><img src="assets/chuckchuck-app-icon-64.png?v=qk13" alt="">척척발표<small>${bq.variant === 'call' ? 'Q&amp;A 화상 체험' : 'Q&amp;A 체험'}</small></span>
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
  layer.dataset.variant = bq.variant;
  layer.innerHTML = `${bqTopHtml(screen)}<div class="bq-body">${html}</div>`;
  document.body.appendChild(layer);
  document.body.classList.add('bq-open');
  layer.querySelectorAll('[data-bq-home]').forEach((b) => b.addEventListener('click', bqHomeClicked));
  if (typeof bqArmIdle === 'function') bqArmIdle(layer, screen);
  bqCamEnsure();
  bqCamPaint();
  return layer;
}

function bqHomeClicked() {
  const L = qa && qa.live;
  const midQa = bq.screen === 'qa' && L && !L.awaitEnd && L.qi < ((L.questions || []).length);
  if (midQa && typeof bqConfirmHome === 'function') { bqConfirmHome(); return; }
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

/**
 * 카메라를 못 열었을 때 할 일. 「카메라 없이도 말로 답할 수 있어요」 는 옆 굵은 줄(bqCvStatusText · .bc-self-off)이 말하고, 여기서는 여는 길만.
 * 권한이 막혔거나 까닭을 모를 때 「한 번 더 눌러요」 는 다시 눌러도 같은 답이 와서 막다른 길이었다 (10-01 2차) — 권한을 여는 자리를 가리킨다.
 */
function bqCamErrorText(err) {
  const name = (err && err.name) || '';
  if (window.isSecureContext === false) return '카메라는 https 주소나 이 컴퓨터(127.0.0.1)에서만 열려요.';
  if (!err) return '이 브라우저에서는 카메라를 열 수 없어요.';
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return '연결된 카메라가 없어요. 카메라를 꽂고 「카메라 켜기」를 눌러요.';
  if (name === 'NotReadableError' || name === 'AbortError') return '다른 앱이 카메라를 쓰고 있어요. 그 앱을 닫고 「카메라 켜기」를 눌러요.';
  return '카메라 권한이 막혀 있어요. 주소창 왼쪽 자물쇠를 눌러 카메라를 「허용」으로 바꾼 뒤 「카메라 켜기」를 눌러요.';
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
  // 판단은 쓰는 화면에서만 돈다 — 시작·고르기·훑어보기는 사람이 있는지만(느리게), 질문 화면은 구도·정면 비율(기본),
  // 마무리는 안 본다. 예전엔 카메라가 켜져 있으면 모든 화면에서 5.5fps 로 돌았다 (10-01 성능 점검)
  if (window.BoothCV) {
    const need = stream && bq.screen !== 'finale';
    if (need) BoothCV.watch(bq.video, { tickMs: bq.screen === 'qa' ? 180 : 400 });
    else BoothCV.unwatch();
  }
  document.querySelectorAll('#bqStage video[data-bq-cam]').forEach((v) => {
    if (v.srcObject !== stream) {
      v.srcObject = stream;
      if (stream) v.play().catch(() => {});
    }
  });
  document.querySelectorAll('#bqStage [data-bq-cam-box]').forEach((box) => { box.dataset.camera = live ? 'on' : 'off'; });
  // 카메라가 꺼지면 마지막 판단(구도 안내 · 얼굴 테두리)이 화면에 남지 않게 걷는다
  if (!live) {
    const hint = document.getElementById('bqHint');
    if (hint) hint.hidden = true;
    bqPaintFaceBox(null);
  }
  const note = document.getElementById('bqCamNote');
  if (note) note.textContent = bq.cam.off ? '카메라를 껐어요' : (bq.cam.error || (bq.cam.opening ? '카메라를 여는 중이에요' : ''));
  const btn = document.getElementById('bqCamToggle');
  if (btn) btn.textContent = live ? '카메라 끄기' : '카메라 켜기';
  // 시작 화면에는 꺼졌거나 못 열었을 때만 「카메라 켜기」 — 오류 문구가 가리키는 버튼이 그 화면에 있어야 한다
  if (btn && bq.screen === 'attract') btn.hidden = live || (!bq.cam.off && !bq.cam.error);
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

/** 값이 바뀔 때만 쓴다 — 판단 결과는 1초에 5번 오고, 같은 글을 다시 쓰면 그때마다 스타일·화면 읽기가 다시 돈다 */
function bqSet(el, prop, value) {
  if (el && el[prop] !== value) el[prop] = value;
}

function bqOnCv(s) {
  const layer = document.getElementById('bqStage');
  if (!layer) return;
  const present = s.present ? '1' : '0';
  if (layer.dataset.present !== present) layer.dataset.present = present;
  bqSet(document.getElementById('bqCvStatus'), 'textContent', bqCvStatusText(s));
  if (bq.screen === 'attract' && s.arrived) bqGreet();
  const hint = document.getElementById('bqHint');
  if (hint) {
    bqSet(hint, 'textContent', s.hint || '');
    bqSet(hint, 'hidden', !s.hint);
  }
  bqPaintFaceBox(s.face);
  const gaze = document.getElementById('bqGazeNow');
  if (gaze) {
    const pct = window.BoothCvLogic ? BoothCvLogic.gazePercent(s.gaze) : null;
    bqSet(gaze, 'textContent', pct === null ? '' : `정면 ${pct}%`);
    bqSet(gaze, 'hidden', pct === null);
    if (pct !== null && gaze.getAttribute('aria-label') !== `얼굴이 정면으로 잡힌 시간 ${pct}%`) gaze.setAttribute('aria-label', `얼굴이 정면으로 잡힌 시간 ${pct}%`);
  }
}

function bqCvStatusText(s) {
  if (!bqCamLive()) return bq.cam.error ? '카메라 없이도 체험할 수 있어요' : '';
  if (s.status === 'loading') return '얼굴을 찾을 준비를 하고 있어요';
  if (s.status === 'failed') return '카메라 없이도 체험할 수 있어요';
  if (s.status !== 'ready') return '';
  if (s.present) return '반가워요! 앞에 서 있는 모습이 보여요';
  return bq.variant === 'call' ? '앞에 서면 삐약이가 인사해요' : '앞에 서면 병아리들이 인사해요';
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
        ${bq.variant === 'call' ? `<p class="bq-eyebrow">부스 Q&amp;A 화상 체험</p>
        <h1><span id="bqRoleWord" class="bq-role-word">${escapeHtml(BOOTH_ROLES[0].aud)}</span> 역할을 맡은 삐약이와<br>화상 통화해 봐요</h1>
        <p class="bq-lead">교수님 · 심사위원 · 회사 상사 · 일반 청중 중 하나를 골라 삐약이에게 이름표를 달아 주고, 화상 통화처럼 카메라를 보며 질문 3개에 말로 답해 봐요. 질문은 고른 발표 자료에서 나와요. 3분이면 끝나요.</p>` : `<p class="bq-eyebrow">부스 Q&amp;A 체험</p>
        <h1>발표 자료를 읽은 AI가<br>심사위원처럼 물어봐요</h1>
        <p class="bq-lead">발표 하나를 고르고 질문 3개에 답해 봐요. 3분이면 끝나요.</p>`}
        <button type="button" class="bq-cta" id="bqStart">체험 시작하기</button>
        <ol class="bq-how">
          <li><b>1</b><span>${bq.variant === 'call' ? '발표와 역할을 골라요' : '발표를 골라요'}</span></li>
          <li><b>2</b><span>질문이 준비되는 동안 훑어봐요</span></li>
          <li><b>3</b><span>질문 3개에 말로 답해요</span></li>
        </ol>
      </section>
      <aside class="bq-panel">
        <div class="bq-bubble" id="bqGreet">
          <span class="bq-bubble-tag">예시 질문</span>
          <p id="bqGreetText">${escapeHtml(BOOTH_SAMPLE_QS[0])}</p>
        </div>
        ${bq.variant === 'call'
    ? `<div class="bq-judges bq-host-one"><figure>${bqBird(BC_HOST_BIRD)}<figcaption>삐약이</figcaption></figure></div>`
    : `<div class="bq-judges">${BOOTH_JUDGES.map((j) => `
          <figure>${bqBird(j.id)}<figcaption>${escapeHtml(j.name)}</figcaption></figure>`).join('')}</div>`}
        <div class="bq-mirror" data-bq-cam-box data-camera="off">
          <video data-bq-cam autoplay muted playsinline></video>
          <p><b id="bqCvStatus"></b><span id="bqCamNote"></span></p>
          <button type="button" class="bq-ghost" id="bqCamToggle" hidden>카메라 켜기</button>
        </div>
      </aside>
      <p class="bq-privacy">카메라 영상은 이 컴퓨터에서만 보고 저장하지 않아요.${bq.variant === 'call' ? ' 말로 한 답은 글자로 바꾸고 판정하려고 서버로 보내요.' : ''}</p>
      <p class="bq-sr" id="bqGreetLive" aria-live="polite"></p>
    </div>`);
  $('#bqStart').addEventListener('click', () => { if (typeof bqCountVisit === 'function') bqCountVisit(); bqShowPick(); });
  $('#bqCamToggle').addEventListener('click', bqCamToggle);
  bq.sampleIdx = 0;
  bq.timers.push(setInterval(bqRotateSample, 4200));
  if (typeof bqArmReloadGuard === 'function') bqArmReloadGuard();
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
  // 화상판 제목의 역할 낱말도 같이 돈다 — 고를 수 있는 역할이 넷이라는 걸 보여 준다 (뒷말 「역할을 맡은」 은 조사가 안 바뀐다)
  const word = document.getElementById('bqRoleWord');
  if (word) word.textContent = BOOTH_ROLES[bq.sampleIdx % BOOTH_ROLES.length].aud;
}

/** 사람이 다가오면 — 병아리들이 돌아보고 말풍선이 인사로 바뀐다. 몇 초 뒤 예시로 돌아간다 */
function bqGreet() {
  const box = document.getElementById('bqGreet');
  if (!box) return;
  box.dataset.greeting = '1';
  box.querySelector('.bq-bubble-tag').textContent = '반가워요';
  document.getElementById('bqGreetText').textContent = '안녕하세요! 내 답을 자료와 맞춰 보는 질문, 받아 볼래요?';
  // 돌아가는 예시는 읽지 않고(4초마다 읽으면 시끄럽다) 인사만 한 번 읽는다
  const live = document.getElementById('bqGreetLive');
  if (live) live.textContent = '안녕하세요! 내 답을 자료와 맞춰 보는 질문, 받아 볼래요?';
  document.querySelectorAll('#bqStage .bq-judges .bq-bird').forEach((b, i) => {
    b.dataset.mood = i % 2 ? 'excited' : 'happy';
  });
  const cta = document.getElementById('bqStart');
  if (cta) cta.classList.add('pulse');
  bq.timers.push(setTimeout(() => {
    if (!document.getElementById('bqGreet')) return;
    if (cta) cta.classList.remove('pulse');   // 계속 깜빡이면 시작 화면 내내 매 프레임 다시 그린다
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
      <p class="bq-lead">고른 발표의 발표자가 됐다고 생각하고 답하면 돼요. 질문은 고른 발표 자료와, 자료가 인용한 문헌에서 나와요.</p>
      ${bq.variant === 'call' ? bqRolesHtml() : ''}
      <div class="bq-decks" id="bqDecks"><p class="bq-wait">발표를 불러오고 있어요…</p></div>
      <p class="bq-foot" id="bqDeckFoot"></p>
    </div>`);
  bqWireRoles();
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
  // 운영진 안내는 방문객 화면이 아니라 콘솔로 — 부스 전날 준비 절차(booth-qa-stage.md §4)가 같은 말을 한다
  if (foot) foot.textContent = '';
  if (missing) console.info(`[chuckchuck] booth: 파싱본 없는 덱 ${missing}개 숨김 — /test/qa 에서 한 번 열면 나타나요`);
  box.querySelectorAll('[data-deck]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const d = ready.find((x) => x.key === btn.dataset.deck);
      if (d) bqPrepare(d);
    });
  });
  ready.forEach((d) => bqPaintCover(d));
}

/**
 * 화상 체험 — 삐약이에게 맡길 역할. 고른 역할은 질문 화면의 이름표가 된다.
 * 진짜 라디오다 — 화살표로 고르고 Tab 은 한 번만 멈춘다. 역할은 이름표에만 붙고 질문 내용은 안 바뀐다는 걸 같이 적는다(정직).
 */
function bqRolesHtml() {
  return `<fieldset class="bq-roles" aria-describedby="bqRoleNote">
    <legend>삐약이에게 어떤 역할을 맡길까요?</legend>
    <div class="bq-role-list">${BOOTH_ROLES.map((r) => `
      <label class="bq-role" data-role="${escapeHtml(r.aud)}">
        <input type="radio" name="bqRole" class="bq-sr" value="${escapeHtml(r.aud)}"${r.aud === bq.role ? ' checked' : ''}>
        <b>${escapeHtml(r.aud)}</b><small>${escapeHtml(r.where)}</small>
      </label>`).join('')}</div>
    <p class="bq-role-note" id="bqRoleNote">삐약이가 이 역할의 이름표를 달고 물어요. 질문은 어느 역할이든 같은 발표 자료에서 나와요.</p>
  </fieldset>`;
}

function bqWireRoles() {
  document.querySelectorAll('#bqStage input[name="bqRole"]').forEach((input) => input.addEventListener('change', () => {
    if (input.checked) bq.role = input.value;
  }));
}

function bqCoverPdf(sessionId) {
  if (!bq.covers.has(sessionId)) {
    const url = `/api/v1/preview-pdf?session_id=${encodeURIComponent(sessionId)}`;
    // pdf.js 는 한가할 때 받는다 (js/lazy.js) — 아직이면 기다린다
    const ready = typeof ccEnsurePdfjs === 'function' ? ccEnsurePdfjs() : Promise.resolve(!!window.pdfjsLib);
    const p = ready.then((ok) => {
      if (!ok) throw new Error('pdf.js 가 없어요');
      return (typeof ccPdfOpen === 'function' ? ccPdfOpen({ url }) : pdfjsLib.getDocument({ url })).promise;
    });
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
          <button type="button" class="bq-ghost" id="bqSkimPause" aria-pressed="false">멈추기</button>
        </div>
        <p class="bq-skim-tip">「${escapeHtml(d.title)}」의 발표자가 됐다고 생각하고 훑어봐요. 질문은 이 자료를 바탕으로 나와요.</p>
      </section>
      <aside class="bq-build">
        <h2>${bq.variant === 'call' ? '발표 자료에서 질문 3개를 고르고 있어요' : '질문을 만들고 있어요'}</h2>
        <p class="bq-build-note">처음 여는 발표는 1분쯤 걸려요. 그동안 자료를 훑어봐요.</p>
        <ol class="bq-build-steps" id="bqBuildSteps">${BQ_PREP_STEPS.map((s) => `
          <li data-step="${s.key}" data-state="wait"><i aria-hidden="true"></i><span>${s.word}</span><span class="bq-sr" data-sr>기다리는 중이에요</span></li>`).join('')}</ol>
        <p class="bq-elapsed" id="bqElapsed">0초 지났어요</p>
        <div id="bqPrepFail"></div>
        <button type="button" class="bq-cta" id="bqGo" disabled>질문을 만들고 있어요…</button>
        <button type="button" class="bq-ghost" id="bqRepick">다른 발표 고르기</button>
      </aside>
    </div>`;
}

const BQ_STEP_SR = { wait: '기다리는 중이에요', run: '하는 중이에요', done: '끝났어요', fail: '멈췄어요' };

function bqSetStep(key, state) {
  const li = document.querySelector(`#bqBuildSteps [data-step="${key}"]`);
  if (!li || li.dataset.state === state) return;
  li.dataset.state = state;
  const sr = li.querySelector('[data-sr]');
  if (sr) sr.textContent = BQ_STEP_SR[state] || '';
  if (state === 'run') li.setAttribute('aria-current', 'step');
  else li.removeAttribute('aria-current');
}

/**
 * 준비가 멈췄을 때 방문객에게 할 말 — 서버 원문(「upstream timeout」 같은)은 콘솔로 보내고 화면은 사람 말 + 다시 해 보기 (10-01 2차).
 * 운영진은 콘솔·브리지 로그에서 원문을 본다.
 */
function bqPrepFailText(stage, raw) {
  const text = String(raw || '');
  console.warn(`[chuckchuck] booth prep ${stage} 실패:`, text);
  const slow = /time\s*out|timed out|timeout|시간 초과|50[234]|upstream/i.test(text);
  if (stage === 'graph') {
    return slow ? '자료를 읽는 AI 가 늦게 답했어요. 「다시 해 보기」를 누르면 한 번 더 읽어요.'
      : '자료를 정리하다 멈췄어요. 「다시 해 보기」를 누르면 한 번 더 해요.';
  }
  return slow ? '질문을 만드는 AI 가 늦게 답했어요. 「다시 해 보기」를 누르면 한 번 더 만들어요.'
    : '질문을 만들지 못했어요. 「다시 해 보기」를 누르면 한 번 더 만들어요.';
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
  // 발표 고르기에서 표지를 그리려고 이미 연 문서를 그대로 쓴다 — 방문객마다 같은 PDF 를 다시 받고(홍콩 중계로 수 초)
  // 문서를 새로 열면 메모리가 쌓인다 (10-01 성능 점검). shared 라 다음 방문객 때 닫히지 않는다. 못 열면 원래 길(ensureSlideDoc)
  try {
    const pdf = await bqCoverPdf(d.row.cached_session_id);
    if (!alive()) return;
    setUploadedPdf({ file: null, pdf, pageCount: pdf.numPages, shared: true });
  } catch (err) {
    console.warn('[chuckchuck] booth cover reuse', err);
  }

  // 1. 파싱본 되살리기 — 미리보기 PDF 까지 메모리에 올린다 (#/replay · #/test/qa 와 같다)
  bqSetStep('doc', 'run');
  const doc = await ensureSlideDoc();
  if (!alive()) return;
  if (!doc) {
    bqSetStep('doc', 'fail');
    console.warn('[chuckchuck] booth: 파싱본 없음 — 운영진이 /test/qa 에서 이 발표를 한 번 열어 두면 돼요', d.key);
    bqPrepFail('이 발표는 지금 열 수 없어요. 「다른 발표 고르기」로 다른 발표를 골라요.', d);
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
    console.warn('[chuckchuck] booth: precompute 모듈 없음');
    bqPrepFail('자료를 여는 데 문제가 생겼어요. 「다시 해 보기」를 눌러요.', d);
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
    bqPrepFail(bqPrepFailText('graph', (err && err.message) || err), d);
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
  // 말풍선 아바타 이름 — 무대의 심사위원(화상판은 고른 역할)과 같은 사람으로 보이게 (질문·판정 요청에는 안 실린다)
  qa.aud = bq.variant === 'call' ? bq.role : '심사위원';
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
      // 역할은 이름표다 — 「교수님과 통화」 는 역할이 질문을 고른다는 약속으로 읽혔다 (10-01 2차). 역할극 느낌은 남긴다
      go.textContent = bq.variant === 'call' ? `${bq.role} 역할의 삐약이와 통화 시작하기` : '질문 받으러 가기';
      go.classList.add('pulse');
      go.focus();
      return;
    }
    if (qaBuildFailed && !qaBuilding) {
      clearInterval(waitQ);
      bqSetStep('questions', 'fail');
      bqPrepFail(bqPrepFailText('questions', qa.liveError), d);
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
  let paused = false;
  document.querySelectorAll('#bqStage [data-skim]').forEach((b) => b.addEventListener('click', () => {
    holdUntil = Date.now() + BOOTH_SKIM_MS * 2;
    step(Number(b.dataset.skim));
  }));
  // 저절로 넘어가는 것은 멈출 수 있어야 한다 (WCAG 2.2.2) — 천천히 읽는 사람도 있다
  const pause = document.getElementById('bqSkimPause');
  if (pause) pause.addEventListener('click', () => {
    paused = !paused;
    pause.textContent = paused ? '다시 넘기기' : '멈추기';
    pause.setAttribute('aria-pressed', String(paused));
  });
  paint();
  bq.timers.push(setInterval(() => { if (!paused && Date.now() >= holdUntil) step(1); }, BOOTH_SKIM_MS));
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
      <p class="bq-spot-q">수고했어요! 「결과 확인하기」를 누르거나 잠시 기다리면 오늘의 결과가 나와요.</p>`;
  }
  const t = bqCurrentQuestionTurn();
  const q = L.questions[L.qi] || {};
  const slides = (q.slide_nos || []).filter(Boolean);
  // 되묻기(qa_live.js askAgain)도 question 말풍선으로 온다 — 지금 답할 말은 그것이라 카드에 올리고, 되묻기라고 밝힌다
  const follow = t && bqIsFollowUp(t);
  const choices = (t && t.choices) || [];
  // 중요도(꼭 넘어야 해요)는 부스 방문객에게 성적 기준처럼 읽혀 뺀다 (10-01 2차 · 화상판과 같다)
  return `<p class="bq-spot-meta"><b>질문 ${L.qi + 1}</b><span>/ ${n}</span>${follow ? `<em class="is-follow">${t.meta || '한 번 더 물어요'}</em>` : ''}</p>
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

/** 자료 창에 띄울 장과 까닭 — 판정·힌트가 짚은 장이 있으면 그 장 (booth_ops.js bqFocusSlide) */
function bqQaFocus() {
  if (typeof bqFocusSlide === 'function') return bqFocusSlide();
  const L = qa.live;
  const q = L && L.questions && L.questions[Math.min(L.qi, L.questions.length - 1)];
  return { no: Number(((q && q.slide_nos) || [])[0]) || 1, why: '질문이 가리키는' };
}

function bqQaSlideNo() {
  return bqQaFocus().no;
}

/* 큰 슬라이드는 썸네일(240px)을 늘리면 부스 거리에서 뭉개진다 — 무대용 렌더(app.js paintDeckStage)로 크게 그린다 */
function bqSlideHtml(no, why = '질문이 가리키는') {
  const title = String((nf.slideTitles || [])[no - 1] || '').trim();
  const label = escapeHtml(`${no}장${title ? ` · ${title}` : ''}`);
  const pic = uploadedPdf
    ? `<span class="bq-slide-pic"><canvas data-stage-page="${no}" role="img" aria-label="${label}"></canvas></span>`
    : `<span class="bq-slide-pic"><img src="${deckImageSrc(no)}" alt="${label}"></span>`;
  return `<figcaption>${why} <b>${no}장</b></figcaption>${pic}`;
}

/** 자료 창을 지금 짚는 장으로 — 장이나 까닭이 바뀔 때만 다시 그린다. 두 무대가 같이 쓴다 */
function bqSyncSlide() {
  const slide = document.getElementById('bqSlide');
  if (!slide) return;
  const f = bqQaFocus();
  const key = `${f.no}|${f.why}`;
  if (slide.dataset.focus === key) return;
  slide.dataset.focus = key;
  slide.dataset.no = String(f.no);
  slide.innerHTML = bqSlideHtml(f.no, f.why);
  paintDeckStage(slide);
}

/** 진행 칩 — 바뀔 때만 다시 쓴다 */
function bqSyncProg() {
  const prog = document.getElementById('bqProg');
  if (!prog) return;
  const next = bqProgressHtml();
  if (prog.dataset.html !== next) { prog.dataset.html = next; prog.innerHTML = next; }
}

/**
 * 첫 질문 앞 안내 줄(「문헌 검색이 잠시 안 돼서 …」)은 방문객에게는 대화 한 칸을 통째로 차지하는 운영 정보다 —
 * 화면에서는 숨기고(css) 같은 글을 위 띠 이름표의 title 과 콘솔로 옮긴다. 숨기기만 하지 않는다(정직).
 */
function bqMoveLeadNote() {
  const first = document.querySelector('#stream > .qa-note-line:first-child');
  const badge = document.querySelector('#bqStage .bq-brand small');
  if (!first || !badge) return;
  const text = first.textContent.trim();
  if (badge.title === text) return;
  badge.title = text;
  badge.dataset.note = '1';
  console.info('[chuckchuck] booth note', text);
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
  bqSyncProg();
  bqSyncSlide();
  bqMoveLeadNote();
  if (typeof bqArmAutoEnd === 'function') bqArmAutoEnd();
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
  // 새로고침하면 bq 가 비어도 탭이 기억한 무대를 따른다
  bq.variant = boothQaVariant() || bq.variant;
  if (bq.variant === 'call' && typeof renderQaLiveBoothCall === 'function') return renderQaLiveBoothCall();
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
        <figure class="bq-slide" id="bqSlide" data-no="${no}"></figure>
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

/**
 * 부스는 코칭 기록을 남기지 않는다 — 「여기까지 하고 저장」 은 여기서 거짓말이다. 누르면 남은 질문이
 * 「안 물음」 이 되므로 그걸 버튼이 말한다 (CTA 만 보고 결과가 예측돼야 한다).
 */
function bqRelabelInput() {
  const finish = document.getElementById('liveFinish');
  const word = '남은 질문 건너뛰고 결과 보기';
  if (finish && finish.textContent !== word) finish.textContent = word;
  const ta = document.getElementById('liveAnswer');
  if (ta && ta.getAttribute('aria-label') !== '내 답') ta.setAttribute('aria-label', '내 답');
  if (typeof bqArmAutoEnd === 'function') bqArmAutoEnd();
}

/* ─── S4 마무리 (qa_live.js qaLiveEnd 가 부른다) ──────────────────────────── */

function boothQaFinale() {
  bq.variant = boothQaVariant() || bq.variant;
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
      <span class="bq-fin-q"><b>${escapeHtml(q.label || `질문 ${i + 1}`)}${q.trap ? '<em class="bq-fin-trap">함정 질문</em>' : ''}</b><small>${escapeHtml(oneLine(q.question))}</small></span>
      <span class="chip chip-sm ${row.cls}">${escapeHtml(row.chip)}</span>
    </li>`;
  }).join('');
  const happy = sum.self > 0;
  const call = bq.variant === 'call';
  const role = qa.aud || bq.role;
  const birds = call
    ? bqBird(BC_HOST_BIRD, happy ? 'happy' : 'curious')
    : BOOTH_JUDGES.map((j, i) => bqBird(j.id, happy ? (i % 2 ? 'excited' : 'happy') : 'curious')).join('');
  bqMount('finale', `
    <div class="bq-finale">
      <section class="bq-fin-main">
        <div class="bq-judges bq-judges-sm">${birds}</div>
        <p class="bq-eyebrow">${call ? `${escapeHtml(role)} 역할의 삐약이와 통화를 마쳤어요` : '체험을 마쳤어요'}</p>
        <h1 class="bq-fin-head">${sum.head}</h1>
        <ol class="bq-fin-list">${rows}</ol>
      </section>
      <aside class="bq-fin-side">
        ${pct === null ? '' : `<div class="bq-card bq-gaze">
          <span>${call ? '질문 받는 동안 카메라를 본 비율' : '질문을 받는 동안 얼굴이 정면으로 잡힌 시간'}</span>
          <b class="num">${pct}<small>%</small></b>
          <p>카메라가 정면 얼굴을 찾은 순간의 비율이에요. ${call ? '카메라를 보고 답하면 올라가요.' : '심사위원을 보고 답하면 올라가요.'}</p>
        </div>`}
        <div class="bq-card bq-more">
          <b>내 발표 자료로도 해 볼 수 있어요</b>
          <p>chuckchuck-present.com 에서 자료를 올리고 발표를 녹음하면, 내 말과 자료를 맞춰 보는 질문이 나와요.</p>
        </div>
        <button type="button" class="bq-cta" data-bq-home>처음으로 돌아가기</button>
        <p class="bq-return" id="bqReturn"></p>
        <p class="bq-sr" id="bqReturnLive" aria-live="polite"></p>
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
    // 매초 읽으면 시끄럽다 — 10초 남았을 때 한 번만 알린다
    const live = document.getElementById('bqReturnLive');
    if (live && left === 10) live.textContent = '10초 뒤 처음 화면으로 가요. 화면을 누르면 더 볼 수 있어요';
  }, 1000));
}
