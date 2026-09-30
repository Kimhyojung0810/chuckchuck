/**
 * 통화 배치 흐름 (#/temp · 주소창 /temp) — 메인 흐름을 그대로 타되 발표·Q&A 두 화면만 화상통화처럼 그린다.
 *
 * 2026-09-28 사용자: "발표 단계에서는 발표 슬라이드가 정면에 있고 내가 오른쪽 하단에서 카메라로 보이고,
 * QA 에서는 내가 가운데 나오면서 그 레이아웃으로 QA 를 진행" — 부스 통화 화면(booth.html)의 배치를
 * 업로드 → 발표 녹음 → 분석 → 질문 코칭 → 리포트 **전체 서비스 흐름** 위에 얹는다.
 *
 * 로직은 하나도 새로 만들지 않는다. 녹음(renderRecPanel·startRec·finishRecAndPrepare)·슬라이드 이동
 * (moveSlide·paintRehearsalSlide)·질문 코칭(qa_live.js 의 입력 카드·스트림)은 **같은 id** 를 찾아 도므로,
 * 이 파일은 그 id 들을 통화 배치로 다시 놓는 층(body 에 붙는 #cfCall)만 만든다. #app 안에 두지 않는
 * 이유는 데스크톱 아트보드가 transform 으로 줄어들어 position:fixed 가 창이 아니라 판에 붙기 때문이다.
 *
 * 클래식 스크립트라 app.js 의 전역(nf · qa · app · $ …)을 호출 시점에 찾는다 (qa_live.js 와 같은 규칙).
 * 켜짐 여부는 탭 단위(sessionStorage)로 기억한다 — #/temp 로 들어온 탭만 통화 배치가 된다.
 */

const CALL_FLOW_KEY = 'cheokcheok:call-flow';
/** 이 화면들로 가면 통화 흐름을 벗어난 것이다 — 다음 연습은 일반 배치로 돈다 */
const CALL_FLOW_EXIT = new Set(['', 'landing', 'about', 'replay', 'test', 'graph']);

const callCam = { stream: null, opening: null, error: '', off: false };
let callObserver = null;
let callDockWatch = null;

function callFlowOn() {
  try { return sessionStorage.getItem(CALL_FLOW_KEY) === '1'; } catch (_) { return false; }
}

function callFlowSet(on) {
  try {
    if (on) sessionStorage.setItem(CALL_FLOW_KEY, '1');
    else sessionStorage.removeItem(CALL_FLOW_KEY);
  } catch (_) { /* 사생활 모드 — 이번 화면만 통화 배치가 된다 */ }
}

/** #/temp — 새 연습을 열고 통화 흐름을 켠다. 지난 발표·코칭이 남아 있으면 남의 질문이 뜨므로 지운다 */
function renderCallEntry() {
  if (typeof visionFlowSet === 'function') visionFlowSet(false);
  callFlowSet(true);
  resetNf();
  resetQa();
  try { sessionStorage.removeItem('cheokcheok:chuckchuck-session'); } catch (_) { /* ignore */ }
  // replace — 뒤로 가기가 #/temp 로 돌아와 방금 올린 자료를 또 지우지 않게
  location.replace('#/new');
}

/** route() 가 화면을 바꾸기 전에 부른다. 통화 층을 걷고, 흐름을 벗어났으면 카메라까지 끈다 */
function callFlowOnRoute(key) {
  if (CALL_FLOW_EXIT.has(key)) callFlowSet(false);
  const keepCam = callFlowOn() && (key === 'new' || key === 'qa');
  callFlowUnmount({ keepCam });
}

/* ─── 카메라 — 발표 → Q&A 로 넘어가도 한 번 연 스트림을 그대로 쓴다 (다시 묻지 않게) ─── */

function callCamErrorText(err) {
  const name = (err && err.name) || '';
  if (window.isSecureContext === false) return '카메라는 https 주소나 이 컴퓨터(127.0.0.1)에서만 열려요. 발표와 질문은 카메라 없이도 할 수 있어요.';
  if (name === 'NotAllowedError' || name === 'SecurityError') return '카메라 권한이 막혀 있어요. 주소창 왼쪽 권한에서 카메라를 허용하면 내 모습이 보여요.';
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return '연결된 카메라가 없어요. 카메라를 꽂고 「카메라 켜기」를 눌러요.';
  if (name === 'NotReadableError' || name === 'AbortError') return '다른 앱이 카메라를 쓰고 있어요. 그 앱을 닫고 「카메라 켜기」를 눌러요.';
  return '카메라를 열지 못했어요. 「카메라 켜기」를 한 번 더 눌러요.';
}

async function callCamEnsure() {
  if (callCam.off) return null;
  if (callCam.stream && callCam.stream.getVideoTracks().some((t) => t.readyState === 'live')) return callCam.stream;
  if (callCam.opening) return callCam.opening;
  if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) {
    callCam.error = callCamErrorText(null);
    callCamPaint();
    return null;
  }
  // 영상만 연다. 소리는 녹음기(chuckchuck_bridge)·받아쓰기가 따로 연다 — 여기서 같이 잡으면 두 쪽이 한 마이크를 다툰다
  callCam.opening = navigator.mediaDevices.getUserMedia({
    video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } },
    audio: false,
  }).then((s) => {
    callCam.stream = s;
    callCam.error = '';
    return s;
  }).catch((err) => {
    callCam.stream = null;
    callCam.error = callCamErrorText(err);
    return null;
  }).finally(() => {
    callCam.opening = null;
    callCamPaint();
  });
  return callCam.opening;
}

function callCamStop() {
  if (callCam.stream) callCam.stream.getTracks().forEach((t) => t.stop());
  callCam.stream = null;
}

/** 지금 층에 있는 내 모습 칸에 스트림·안내·버튼 이름을 맞춘다 */
function callCamPaint() {
  const video = $('#cfSelfVideo');
  const self = $('#cfSelf');
  const note = $('#cfSelfNote');
  const btn = $('#cfCamToggle');
  const live = !!callCam.stream && !callCam.off;
  if (video && video.srcObject !== (live ? callCam.stream : null)) {
    video.srcObject = live ? callCam.stream : null;
    if (live) video.play().catch(() => { /* 자동 재생 막힘 — muted 라 보통은 안 막힌다 */ });
  }
  if (self) self.dataset.camera = live ? 'on' : 'off';
  if (note) {
    note.textContent = callCam.off ? '카메라를 껐어요' : (callCam.error || (callCam.opening ? '카메라를 여는 중이에요' : ''));
  }
  if (btn) {
    btn.textContent = callCam.off || !live ? '카메라 켜기' : '카메라 끄기';
    btn.setAttribute('aria-pressed', String(live));
  }
}

function callCamToggle() {
  if (callCam.stream && !callCam.off) {
    callCam.off = true;
    callCamStop();
    callCamPaint();
    return;
  }
  callCam.off = false;
  callCam.error = '';
  callCamPaint();
  callCamEnsure();
}

/* ─── 통화 층 ─────────────────────────────────────────────────────────────── */

function callFlowUnmount({ keepCam = false } = {}) {
  if (callObserver) { callObserver.disconnect(); callObserver = null; }
  if (callDockWatch) { callDockWatch.disconnect(); callDockWatch = null; }
  const layer = document.getElementById('cfCall');
  if (layer) layer.remove();
  document.body.classList.remove('cf-open');
  if (!keepCam) callCamStop();
}

/**
 * 층을 띄운다. #app 은 비운다 — 같은 id(#recPanel · #stream …)가 두 군데 있으면 로직이 엉뚱한 쪽을 잡는다.
 * 모드: present(자료가 메인 · 내 모습이 오른쪽 아래) / qa(내 모습이 메인 · 자료가 오른쪽 아래).
 */
function callMount(mode, html) {
  callFlowUnmount({ keepCam: true });
  app.className = '';
  app.innerHTML = '';
  const layer = document.createElement('div');
  layer.id = 'cfCall';
  layer.className = 'cf-call';
  layer.dataset.mode = mode;
  layer.dataset.main = mode === 'present' ? 'slides' : 'self';
  layer.innerHTML = html;
  document.body.appendChild(layer);
  document.body.classList.add('cf-open');
  // 작은 창을 누르면 자리가 바뀐다 (페이스타임). 메인 쪽을 눌렀을 때는 아무 일도 안 한다
  layer.addEventListener('click', (e) => {
    const stage = e.target.closest('.cf-stage');
    if (!stage || e.target.closest('button, a, textarea, input, select, details')) return;
    const which = stage.dataset.stage;
    if (which && which !== layer.dataset.main) callSwap();
  });
  layer.addEventListener('keydown', (e) => {
    const stage = e.target.closest && e.target.closest('.cf-stage');
    if (stage && (e.key === 'Enter' || e.key === ' ') && stage.dataset.stage !== layer.dataset.main) {
      e.preventDefault();
      callSwap();
    }
  });
  const cam = $('#cfCamToggle');
  if (cam) cam.addEventListener('click', callCamToggle);
  // 작은 창은 아래 조작줄 바로 위에 선다. 조작줄 높이는 녹음 상태·창 폭에 따라 바뀌므로 잰 값을 쓴다
  const dock = layer.querySelector('.cf-dock, .cf-answer');
  if (dock && window.ResizeObserver) {
    callDockWatch = new ResizeObserver(() => layer.style.setProperty('--cf-dock-h', `${Math.round(dock.getBoundingClientRect().height)}px`));
    callDockWatch.observe(dock);
  }
  callCamPaint();
  callCamEnsure();
  return layer;
}

function callSwap() {
  const layer = document.getElementById('cfCall');
  if (!layer) return;
  layer.dataset.main = layer.dataset.main === 'slides' ? 'self' : 'slides';
  syncStageLabels();
  // 자료가 커지거나 작아졌으면 그 크기로 다시 그린다 (canvas 는 그린 폭 그대로 남는다)
  if (layer.dataset.mode === 'present') paintRehearsalSlide(nf.slide);
}

function syncStageLabels() {
  const layer = document.getElementById('cfCall');
  if (!layer) return;
  layer.querySelectorAll('.cf-stage').forEach((st) => {
    const small = st.dataset.stage !== layer.dataset.main;
    st.setAttribute('tabindex', small ? '0' : '-1');
    st.setAttribute('role', small ? 'button' : 'group');
    st.setAttribute('aria-label', `${st.dataset.stage === 'self' ? '내 모습' : '발표 자료'}${small ? '. 누르면 크게 보여요' : ''}`);
  });
}

function selfStageHtml() {
  return `
    <div class="cf-stage cf-self" id="cfSelf" data-stage="self" data-camera="off">
      <video id="cfSelfVideo" autoplay muted playsinline></video>
      <p class="cf-self-note" id="cfSelfNote"></p>
    </div>`;
}

/* ─── 발표 — 자료가 정면, 내 모습은 오른쪽 아래 ───────────────────────────── */

function nfStep3Call() {
  // 새로고침 뒤 PPTX 미리보기 PDF 가 비어 있으면 붙인 뒤 다시 그린다 (nfStep3 과 같은 길)
  if (!uploadedPdf && (nf.previewPdf || nf.fileName) && !nf._previewLoading) {
    nf._previewLoading = true;
    ensurePreviewPdf(nfSlideDoc).then((pdf) => {
      nf._previewLoading = false;
      // vision 리허설도 통화 흐름을 켜 둔다(질문 코칭을 통화 배치로 잇기 위해) — 그 발표 화면을 덮어 그리지 않는다
      const vision = typeof visionFlowOn === 'function' && visionFlowOn();
      if (pdf && nf.step === 2 && callFlowOn() && !vision) nfStep3Call();
    }).catch(() => { nf._previewLoading = false; });
  }
  const nPages = rehearsalCount();
  if (!nf.slide || nf.slide < 1) nf.slide = 1;
  if (nf.slide > nPages) nf.slide = nPages;
  const titles = activeTitles();
  const titleAt = (i) => titles[i] || `${i + 1}번 슬라이드`;
  const bodies = activeBodies();
  const stageInner = uploadedPdf
    ? `<canvas id="slidePdfCanvas" class="cf-slide-canvas" aria-label="원본 PDF 슬라이드"></canvas>
       <div id="slideCardWrap" class="cf-slide-doc" style="display:none"></div>`
    : (bodies && bodies.length
      ? `<div id="slideCardWrap" class="cf-slide-doc">${slideCardHtml(nf.slide, titleAt(nf.slide - 1), bodies[nf.slide - 1])}</div>`
      : `<img id="slideImage" class="cf-slide-img" src="${activeImages()[nf.slide - 1] || ''}" alt="">`);

  callMount('present', `
    <div class="cf-stage cf-slides" id="cfSlides" data-stage="slides">
      ${stageInner}
      <button type="button" class="cf-side-nav cf-prev" data-slide-nav="-1" aria-label="이전 슬라이드">‹</button>
      <button type="button" class="cf-side-nav cf-next" data-slide-nav="1" aria-label="다음 슬라이드">›</button>
    </div>
    ${selfStageHtml()}

    <header class="cf-top">
      <span class="cf-pill cf-glass">발표</span>
      <span class="cf-pill cf-glass cf-slide-meta"><b id="slideNo" class="num">${nf.slide} / ${nPages}</b><span id="slideTitle">${escapeHtml(titleAt(nf.slide - 1))}</span></span>
      <span class="cf-top-fill">${precomputeNoteHtml()}</span>
      <button class="btn cf-glass" id="cfCamToggle" type="button">카메라 끄기</button>
      <a class="btn cf-glass" href="#/" id="cfLeave">나가기</a>
    </header>

    <div class="cf-dock cf-glass">
      <button type="button" class="btn cf-nav-btn" data-slide-nav="-1">이전</button>
      <div class="cf-rec" id="recPanel"></div>
      <button type="button" class="btn cf-nav-btn" data-slide-nav="1">다음</button>
    </div>`);

  // 발표는 녹음이 멈추지 않는 한 나가기를 한 번 더 묻는다 — 누른 김에 녹음이 날아가지 않게
  const leave = $('#cfLeave');
  if (leave) leave.addEventListener('click', (e) => {
    if (nf.mic === 'on' && !window.confirm('발표를 녹음하고 있어요. 나가면 이번 녹음은 남지 않아요. 나갈까요?')) e.preventDefault();
  });
  syncStageLabels();
  renderRecPanel();
  bindRehearsalNav();
  syncRehearsalNav();
  paintRehearsalSlide(nf.slide);
  startPrecomputeNoteTimer();
  if (nf.mic === 'on' && !ccRuntime) startRecClock();
}

/* ─── Q&A — 내 모습이 가운데, 질문·답은 왼쪽에 겹쳐 오간다, 자료는 오른쪽 아래 ─── */

function callQaCounter() {
  const L = qa.live;
  if (!L || !L.questions) return '';
  const n = L.questions.length;
  if (L.awaitEnd || L.qi >= n) return `질문 ${n}개를 마쳤어요`;
  return `질문 ${L.qi + 1} / ${n}`;
}

/** 지금 질문이 가리키는 장. 없으면 발표 때 마지막으로 본 장 */
function callQaSlideNo() {
  const L = qa.live;
  const q = L && L.questions && L.questions[Math.min(L.qi, L.questions.length - 1)];
  const nos = (q && q.slide_nos) || [];
  return Number(nos[0]) || Number(nf.slide) || 1;
}

function callQaSlideHtml(no) {
  return `<img class="cf-slide-img" data-thumb-page="${no}" src="${deckImageSrc(no)}" alt="${no}번 슬라이드">
    <span class="cf-slide-no cf-glass">${no}번 슬라이드</span>`;
}

/** 판정·힌트로 스트림이 자랄 때 번호·자료 창을 따라 바꾼다. 스트림을 다시 그리지 않고 칸 둘만 고친다 */
function callQaSync() {
  const counter = $('#cfQaCount');
  if (counter) counter.textContent = callQaCounter();
  const slide = $('#cfSlides');
  const no = callQaSlideNo();
  if (slide && Number(slide.dataset.no) !== no) {
    slide.dataset.no = String(no);
    slide.innerHTML = callQaSlideHtml(no);
    paintDeckThumbs(slide);
  }
}

function renderQaLiveCall() {
  const no = callQaSlideNo();
  callMount('qa', `
    ${selfStageHtml()}
    <div class="cf-stage cf-slides" id="cfSlides" data-stage="slides" data-no="${no}">${callQaSlideHtml(no)}</div>

    <header class="cf-top">
      <span class="cf-pill cf-glass">Q&amp;A</span>
      <span class="cf-pill cf-glass" id="cfQaCount">${escapeHtml(callQaCounter())}</span>
      <span class="cf-top-fill"></span>
      <button class="btn cf-glass" id="cfQuestList" type="button" aria-expanded="false" aria-controls="qaContext">질문 목록</button>
      <button class="btn cf-glass" id="cfCamToggle" type="button">카메라 끄기</button>
      <a class="btn cf-glass" href="#/">저장하고 나가기</a>
    </header>
    <aside class="cf-drawer card" id="qaContext" hidden>${liveContextHtml()}</aside>

    <section class="cf-talk">
      <div class="qa-stream cf-stream" id="stream">${qa.turns.map(streamRow).join('')}</div>
      <div class="card qa-live-input cf-answer">${liveInputHtml()}</div>
    </section>`);
  syncStageLabels();
  const list = $('#cfQuestList');
  if (list) list.addEventListener('click', () => {
    const d = $('#qaContext');
    if (!d) return;
    d.hidden = !d.hidden;
    list.setAttribute('aria-expanded', String(!d.hidden));
  });
  const stream = $('#stream');
  if (stream) {
    callObserver = new MutationObserver(callQaSync);
    callObserver.observe(stream, { childList: true });
  }
  paintDeckThumbs($('#cfCall'));
  scrollDown();
  wireLiveInput();
  if (typeof wireFeedback === 'function') wireFeedback($('#cfCall'));
}
