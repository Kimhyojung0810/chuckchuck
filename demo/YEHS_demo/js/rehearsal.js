/**
 * 리허설 한 줄 흐름 — 주소창 /rehearsal (→ index.html#/rehearsal).
 *
 * 2026-10-03 사용자: 발표 고르기 → 비전 리허설(카메라 앞 발표) → 분석 기다림 → 부스 글라스 화상판에서 질문 답하기 → 리포트를
 * 한 주소에서 끊김 없이. 부스(/booth/qa · /booth/call)는 지금 그대로 둔다 — 이 파일은 있는 화면들을 잇기만 한다.
 *
 *   #/rehearsal          발표 고르기 (부스 시연 세트 셋)                         ← 이 파일이 그린다 (#bqStage 층, 부스 고르기와 같은 카드)
 *   #/new  step 2        비전 리허설                                            ← vision_rehearsal.js nfStep3Vision 그대로 (VISION_FLOW_KEY 를 켠다)
 *                        「발표 마치고 질문 준비하기」(라이브) · 「녹음본을 넣어서 발표 마치기」(이 발표의 녹음)
 *   #/new  step 3        분석 기다림 — 부스 「질문 준비」 화면 모양                ← 이 파일 (뒤에서 app.js nfStep4 가 파이프라인을 그대로 돌린다)
 *   #/qa                 글라스 화상판                                          ← booth_call.js renderQaLiveBoothCall 그대로 + 자료 창 옮기기
 *   #/report             상세 리포트                                            ← 질문을 마치면 바로 간다 (부스 마무리 · 40초 처음으로는 없다)
 *
 * 켜짐은 탭 단위(sessionStorage REHEARSAL_FLOW_KEY). 위 세 주소(rehearsal · new · qa) 밖으로 나가면 이 표시와 이 흐름이 켠
 * 비전 표시를 같이 끈다 — 남겨 두면 다음 #/new · #/qa 가 리허설 배치로 뜬다. 리포트에 닿을 때도 끈다(흐름이 끝났다).
 * 부스 운영 장치(자리 비움 · Esc · 마무리 초읽기 · 뒤로 가기 덫 · 자동 결과)는 이 표시가 켜져 있으면 돌지 않는다 (booth_ops.js · booth_qa.js).
 *
 * 질문 · 판정 로직은 건드리지 않는다. 질문은 리허설 녹음의 분석(받아쓰기 · 정합 · 흐름)으로 일반 앱과 같은 함수(ensureLiveQuestions)가 만든다.
 * 클래식 스크립트라 app.js · booth_qa.js · booth_call.js · vision_rehearsal.js 의 전역을 호출 시점에 찾는다.
 */

const REHEARSAL_FLOW_KEY = 'cheokcheok:rehearsal-flow';
const REHEARSAL_HASH = '#/rehearsal';
/** 이 주소들 안에 있으면 리허설 흐름이다 — 그 밖으로 나가면 끈다 */
const REHEARSAL_KEEP = ['rehearsal', 'new', 'qa'];
/** 질문 3개 트랙 — 부스와 같은 길이 (contracts.py QA_TRACK_LIMITS["5"]) */
const REHEARSAL_QA_TRACK = '5';
const REHEARSAL_POLL_MS = 500;

/** 위 띠 단계 */
const RH_STEPS = [
  { key: 'pick', word: '발표 고르기' },
  { key: 'rehearse', word: '발표 리허설' },
  { key: 'wait', word: '질문 준비' },
  { key: 'qa', word: '질문 답하기' },
  { key: 'report', word: '리포트' },
];

/** 분석 기다림 — 파이프라인 단계(app.js PIPELINE_STAGE_ORDER)를 사람 말 다섯 줄로 */
const RH_WAIT_STEPS = [
  { key: 'rec', word: '발표 녹음을 정리해요' },
  { key: 'stt', word: '내가 한 말을 받아써요' },
  { key: 'align', word: '자료와 내 말을 맞춰 봐요' },
  { key: 'flow', word: '발표 흐름을 비교해요' },
  { key: 'questions', word: '질문 3개를 골라요' },
];
const RH_STAGE_ORDER = ['encoding', 'stt', 'concepts', 'graph', 'align', 'flow'];
/** 분석이 그 줄에서 멈췄을 때의 한 줄 */
const RH_WAIT_FAIL_WORD = {
  rec: '발표 녹음을 정리하다 멈췄어요',
  stt: '내가 한 말을 받아쓰다 멈췄어요',
  align: '자료와 내 말을 맞춰 보다 멈췄어요',
  flow: '발표 흐름을 비교하다 멈췄어요',
};

/* ─── 순수 함수 (tests/js/rehearsal.smoke.mjs) ─────────────────────────────── */

/** 이 화면으로 가면 리허설 흐름을 벗어난 것인가 */
function rehearsalLeaves(key) {
  return !REHEARSAL_KEEP.includes(String(key || ''));
}

/**
 * 분석 기다림의 다섯 줄 상태 — wait · run · done · fail.
 * 받은 산출물(받아쓰기 · 정합 · 흐름)이 있으면 그 줄은 끝난 것이다. 단계 이름만 믿지 않는다 — 새로고침으로 되살린 세션은 단계가 멈춰 있다.
 * 분석이 실패했으면(질문 재료가 다 모이기 전에) 아직 안 끝난 첫 줄이 실패다. 질문 줄은 질문 생성만 본다.
 * 'partial'(어느 단계가 실패한 채 끝남)도 질문 재료가 모자라면 실패로 친다.
 * 실패(phase 'error')는 단계 이름이 없다 — 실패 직전 단계(lastPhase)로 어디서 멈췄는지 본다. 녹음(테이크)이 있으면(hasTake)
 * 녹음 정리에서 멈춘 게 아닌 한 첫 줄은 끝이다 — 받아쓰기 실패가 「발표 녹음을 정리해요」 실패로 보였다 (10-03 점검 F5)
 */
function rehearsalWaitStates({ phase = '', out = null, qaReady = false, questionsReady = false, buildFailed = false, building = false,
  hasTake = false, lastPhase = '' } = {}) {
  const o = out || {};
  const failed = phase === 'error';
  const stage = String(failed ? lastPhase || '' : phase || '').replace(/_(done|error)$/, '');
  const at = RH_STAGE_ORDER.indexOf(stage);
  const finished = ['done', 'partial'].includes(phase);
  const transcript = !!(o.transcript && !o.transcript.error);
  const recDone = failed && hasTake && at !== 0;
  const s = {
    rec: qaReady || finished || transcript || recDone || at >= 1 ? 'done' : (at === 0 || phase === 'queued' ? 'run' : 'wait'),
    stt: qaReady || finished || transcript || at >= 2 ? 'done' : (at === 1 ? 'run' : 'wait'),
    align: qaReady || o.alignment ? 'done' : (at >= 2 && at <= 4 ? 'run' : 'wait'),
    flow: qaReady || o.flow ? 'done' : (at === 5 ? 'run' : 'wait'),
    questions: 'wait',
  };
  if (questionsReady) s.questions = 'done';
  else if (buildFailed && !building) s.questions = 'fail';
  else if (qaReady) s.questions = 'run';
  // 'partial' 도 끝난 것이다(한 단계가 죽은 채로 파이프라인이 닫혔다) — 질문 재료가 다 안 모였으면 오지 않을 결과를 기다리지 않게
  // 아직 안 끝난 첫 줄을 실패로. 예전엔 'error' 만 봐서 개념 · 그래프 · 정합 · 흐름 하나가 502 면 시계만 돌며 영영 기다렸다 (10-03 점검 F1)
  if ((phase === 'error' || phase === 'partial') && !qaReady) {
    const first = ['rec', 'stt', 'align', 'flow'].find((k) => s[k] !== 'done');
    if (first) s[first] = 'fail';
  }
  return s;
}

/**
 * #/qa 를 되살릴 수 없을 때 어디로 — 질문이 살아 있거나 끝난 기록이 있으면 그대로(null),
 * 자료가 있으면 리허설 · 분석 자리(#/new), 아무것도 없으면 발표 고르기. 일반 질문 코칭(트랙 고르기)으로 새지 않게.
 */
function rehearsalQaFallback({ live = false, ended = false, hasDeck = false } = {}) {
  if (live || ended) return null;
  return hasDeck ? '#/new' : REHEARSAL_HASH;
}

/* ─── 켜짐 ──────────────────────────────────────────────────────────────── */

function rehearsalFlowOn() {
  try { return sessionStorage.getItem(REHEARSAL_FLOW_KEY) === '1'; } catch (_) { return false; }
}

function rehearsalFlowSet(on) {
  try {
    if (on) sessionStorage.setItem(REHEARSAL_FLOW_KEY, '1');
    else sessionStorage.removeItem(REHEARSAL_FLOW_KEY);
  } catch (_) { /* 사생활 모드 — 이번 화면만 */ }
}

/** 리허설이 켠 것을 모두 끈다 — 표시 둘 · 화상판 카메라 · 마이크 · 정면 판단 */
function rehearsalTeardown({ keepVision = false } = {}) {
  rehearsalFlowSet(false);
  if (!keepVision && typeof visionFlowSet === 'function') visionFlowSet(false);
  if (typeof bqStopMic === 'function') bqStopMic();
  if (typeof bqCamStop === 'function') bqCamStop();
  // 정면 판단 워커(OpenCV)까지 내린다 — 리허설은 질문 화상판에서만 쓴다. 리포트에서도 「ready」 로 남아 메모리를 쥐었다 (perf-r2-1).
  // 부스(/booth)는 이 길을 안 탄다(시작 화면이 계속 쓴다)
  if (window.BoothCV) { try { BoothCV.stopGaze(); BoothCV.unwatch(); if (BoothCV.dispose) BoothCV.dispose(); } catch (_) { /* 이미 멈춤 */ } }
  // 화상판 자료 창의 감시 · 다시 그리기 함수가 떼어 낸 층(노드 ~680개)을 쥐고 있었다 — 다음 리허설까지 남았다 (10-03 점검 perf-6)
  if (rhSlideWatch) { rhSlideWatch.disconnect(); rhSlideWatch = null; }
  if (typeof visionSlideRepaint !== 'undefined') visionSlideRepaint = null;
}

/**
 * route() 가 화면을 바꾸기 전에 부른다 (비전 · 통화 층을 걷기 전에 — 카메라를 넘겨받으려고).
 * - #/qa 로 갈 때: 비전 리허설이 연 카메라를 화상판에 넘긴다(다시 묻지 않게). 질문을 아직 안 시작했으면 3개 트랙으로 시작해 둔다
 * - 흐름 밖으로 나갈 때: 표시 · 카메라를 끈다
 */
function rehearsalFlowOnRoute(key) {
  if (!rehearsalFlowOn()) return;
  // 녹음 중에 비전 리허설(#/new)을 떠나면 — 브라우저 · 아이패드 뒤로 가기, 주소 직접 입력 — 테이크를 멈춘다.
  // 「나가기」 시트만 멈춰서, 뒤로 가기로는 발표 목록 · 홈 뒤에서 녹음기와 마이크가 표시 없이 계속 돌았다 (10-03 점검 F2)
  if (key !== 'new' && typeof nf !== 'undefined' && nf && nf.mic === 'on' && typeof visionStopTake === 'function') {
    visionStopTake();
    rhTakeCut = true;   // 「어떤 발표인가요」 가 한 번 알린다
  }
  if (rehearsalLeaves(key)) {
    rehearsalTeardown({ keepVision: key === 'vision' });
    return;
  }
  if (key === 'qa') rhHandCamera();
}

/** route() 가 그리기 직전에 — 리허설 탭에서 #/qa 를 되살릴 수 없으면 일반 질문 코칭 대신 리허설 자리로. true 면 route() 가 멈춘다 */
function rehearsalGuard(key) {
  // 끝난 리허설의 #/new 로 뒤로 오면(발표 고르기 → 한 번 더 뒤로) 일반 앱이 끝난 세션을 지우고 빈 새 연습을 그린다 — 발표 고르기로
  if (key === 'new' && rehearsalFlowOn() && nf && nf.completed) { location.replace(REHEARSAL_HASH); return true; }
  if (key !== 'qa' || !rehearsalFlowOn()) return false;
  const to = rehearsalQaFallback({
    live: typeof qaLiveActive === 'function' && qaLiveActive(),
    ended: !!(qa && qa.ended && qa.live),
    hasDeck: !!(nf && (nf.gate === 'done' || nf.sessionId)),
  });
  if (!to) return false;
  location.replace(to);
  return true;
}

/* ─── 층 — 부스 층(#bqStage)과 같은 모양 ────────────────────────────────── */

function rhStepsHtml(screen) {
  const at = RH_STEPS.findIndex((s) => s.key === (screen === 'occ' ? 'pick' : screen));
  return `<ol class="bq-steps-top" aria-label="리허설 단계">${RH_STEPS.map((s, i) => `
    <li class="${i < at ? 'done' : ''}${i === at ? ' on' : ''}"${i === at ? ' aria-current="step"' : ''}><i aria-hidden="true">${i < at ? '✓' : i + 1}</i>${s.word}${i < at ? '<span class="bq-sr"> · 마쳤어요</span>' : ''}</li>`).join('')}</ol>`;
}

/** 위 띠 — booth_qa.js bqTopHtml 이 리허설 탭이면 이걸 쓴다. 오른쪽은 「처음으로」(부스 리셋) 대신 「나가기」 */
function rhTopHtml(screen) {
  return `<header class="bq-top">
    <span class="bq-brand"><img src="assets/chuckchuck-app-icon-64.png?v=qk13" alt="">척척발표<small>발표 리허설</small></span>
    ${rhStepsHtml(screen)}
    <span class="bq-top-fill"></span>
    <button type="button" class="bq-ghost" data-rh-exit>나가기</button>
  </header>`;
}

/**
 * 고르기 · 기다림 층. 화상판(#/qa)은 booth_qa.js bqMount 가 같은 층을 그린다 — 카메라 · 판단은 여기서 켜지 않는다.
 * 기다림은 #app 을 비우지 않는다 — 그 밑에서 nfStep4 가 파이프라인 진행을 그리고, 「다른 녹음으로 다시」(#againTake)를 이 층이 빌려 쓴다
 */
function rhMount(screen, html, { keepApp = false } = {}) {
  if (typeof bqUnmount === 'function') bqUnmount();
  if (typeof bqClearTimers === 'function') bqClearTimers();
  bq.screen = screen;
  bq.variant = 'call';
  if (!keepApp) {
    app.className = '';
    app.innerHTML = '';
  }
  const layer = document.createElement('div');
  layer.id = 'bqStage';
  layer.className = 'bq';
  layer.dataset.screen = screen;
  layer.dataset.variant = 'call';
  layer.dataset.flow = 'rehearsal';
  layer.innerHTML = `${rhTopHtml(screen)}<div class="bq-body">${html}</div>`;
  document.body.appendChild(layer);
  document.body.classList.add('bq-open');
  rhWireExit(layer);
  return layer;
}

function rhWireExit(layer) {
  layer.querySelectorAll('[data-rh-exit]').forEach((b) => b.addEventListener('click', rhExitClicked));
}

/** 나가기 — 발표 고르기에서는 바로, 그 뒤로는 화면 안 시트(왼쪽 「닫기」). 한 것은 이 브라우저에 남는다 */
function rhExitClicked() {
  if (bq.screen === 'pick' || bq.screen === 'occ') { location.hash = '#/'; return; }
  const layer = document.getElementById('bqStage');
  if (!layer || document.getElementById('bqSheet')) return;
  const back = document.activeElement;
  const sheet = document.createElement('div');
  sheet.className = 'bq-sheet-wrap';
  sheet.id = 'bqSheet';
  sheet.innerHTML = `<div class="bq-sheet" role="dialog" aria-modal="true" aria-labelledby="rhSheetTitle" aria-describedby="rhSheetBody">
      <h2 id="rhSheetTitle">리허설을 여기서 멈출까요?</h2>
      <p id="rhSheetBody">지금까지 한 발표와 답은 이 브라우저에 남아요. 홈에서 이어서 볼 수 있어요.</p>
      <div class="bq-sheet-actions">
        <button type="button" class="bq-ghost" data-sheet="close">닫기</button>
        <button type="button" class="bq-cta bq-cta-sm" data-sheet="leave">홈으로 나가기</button>
      </div>
    </div>`;
  layer.appendChild(sheet);
  const behind = [...layer.children].filter((el) => el !== sheet);
  behind.forEach((el) => { el.inert = true; });
  const close = () => { sheet.remove(); behind.forEach((el) => { el.inert = false; }); if (back && back.focus) back.focus(); };
  sheet.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { close(); return; }
    if (e.key !== 'Tab') return;
    const items = [...sheet.querySelectorAll('button')];
    const i = items.indexOf(document.activeElement);
    e.preventDefault();
    items[(i + (e.shiftKey ? -1 : 1) + items.length) % items.length].focus();
  });
  sheet.addEventListener('click', (e) => {
    const act = e.target.closest('[data-sheet]');
    if (e.target === sheet || (act && act.dataset.sheet === 'close')) close();
    else if (act && act.dataset.sheet === 'leave') { sheet.remove(); location.hash = '#/'; }
  });
  sheet.querySelector('[data-sheet="close"]').focus();
}

/* ─── #/rehearsal 발표 고르기 ───────────────────────────────────────────── */

/**
 * 리허설에서 고를 수 있는 발표 — 부스 시연 세트(ppt/decks.json booth) 셋. 셋 다 지난 파싱본과 발표 녹음(ppt/<폴더>)이 있다 —
 * 발표하지 않고 「녹음본을 넣어서 발표 마치기」로 그 녹음을 쓸 수 있어야 해서다 (10-03 사용자). 제목 · 갈래는 booth_qa.js BOOTH_DECKS 그대로.
 */
const REHEARSAL_DECK_KEYS = ['급속충전배터리열화A', '미세플라스틱물벼룩번식A', '배달앱별점인플레이션A'];

function renderRehearsalEntry() {
  if (typeof callFlowSet === 'function') callFlowSet(false);
  if (typeof boothQaSet === 'function') boothQaSet(false);
  rehearsalFlowSet(true);
  // 기다림에서 「다른 발표 고르기」 로 오면 넘겨받은 카메라가 아직 열려 있다 — 고르기 화면은 카메라를 안 쓴다. 비전 리허설이 다시 연다
  if (typeof bqCamStop === 'function') bqCamStop();
  bq.decks = null;   // 덱 목록은 들어올 때마다 새로 — 파싱본이 만료됐을 수 있다
  // 「어떤 발표인가요」 는 제 주소(#/rehearsal/occ)가 있다 — 뒤로 가기 · 새로고침이 고른 발표를 잃고 고르기(또는 홈)로 가지 않게 (10-03 점검 F7)
  const sub = location.hash.replace(/^#\/?/, '').split('/')[1] || '';
  if (sub === 'occ') {
    if (rhCanShowOcc()) {
      rhShowOcc({ title: nf.rehearsalDeck.title });
      ensureSlideDoc().catch(() => null);   // 새로고침이면 자료(선분석 재료)를 다시 받아 둔다
      return;
    }
    history.replaceState(history.state, '', REHEARSAL_HASH);
  }
  rhShowPick();
}

/** 발표를 골라 두었고 아직 발표하지 않았다 — 새로고침 · 뒤로 가기로 「어떤 발표인가요」 에 다시 설 수 있다 */
function rhCanShowOcc() {
  return !!(nf && nf.gate === 'done' && nf.rehearsalDeck && nf.rehearsalDeck.title && (Number(nf.step) || 0) <= 2
    && !nf.completed && !nf.uploadedTake && !(Number(nf.sec) > 0) && !nf.pipelineStartedAt);
}

async function rhShowPick() {
  rhMount('pick', `
    <div class="bq-pick">
      <h1 class="bq-h1">어떤 발표로 리허설할까요?</h1>
      <p class="bq-lead">카메라 앞에서 발표하면 삐약이가 말 빠르기와 크기에 반응해요. 발표가 끝나면 내가 한 말과 자료를 맞춰 본 질문 3개에 답하고, 리포트로 이어져요. 발표하기 어려우면 이 발표의 녹음으로 마쳐도 돼요.</p>
      <div class="bq-decks" id="bqDecks"><p class="bq-wait">발표를 불러오고 있어요…</p></div>
      <p class="bq-foot" id="bqDeckFoot" role="status"></p>
      <button type="button" class="bq-ghost" id="rhDeckRetry" hidden>다시 불러오기</button>
    </div>`);
  document.getElementById('rhDeckRetry').addEventListener('click', () => { bq.decks = null; rhShowPick(); });
  let decks = null;
  let why = '';
  try {
    decks = await bqLoadDecks();
  } catch (err) {
    console.warn('[chuckchuck] rehearsal decks', err);
    // bqLoadDecks 가 까닭을 한국어로 말하면 그대로 — 팀 쿠키가 없어 404 면 「다시 불러오기」 를 아무리 눌러도 같아서 맴돌았다 (10-03 점검 F8)
    const msg = String((err && err.message) || '');
    if (msg.includes('/auth')) why = '팀 코드를 넣어야 발표 목록이 열려요. 주소창에 /auth 를 열어 팀 코드를 넣은 뒤 「다시 불러오기」를 눌러요.';
    else if (/[가-힣]/.test(msg)) why = `${msg}. 「다시 불러오기」를 눌러요.`;
  }
  if (bq.screen !== 'pick' || !document.getElementById('bqDecks')) return;
  const ready = (decks || []).filter((d) => REHEARSAL_DECK_KEYS.includes(d.key) && bqDeckReady(d));
  const box = document.getElementById('bqDecks');
  box.innerHTML = ready.map((d) => `
    <button type="button" class="bq-deck" data-deck="${escapeHtml(d.key)}">
      <span class="bq-cover"><canvas data-cover="${escapeHtml(d.row.cached_session_id)}"></canvas><i>표지를 불러오고 있어요</i></span>
      <span class="bq-deck-kind" data-pages="${escapeHtml(d.row.cached_session_id)}">${escapeHtml(d.kind)}</span>
      <b class="bq-deck-title">${escapeHtml(d.title)}</b>
      <span class="bq-deck-go">이 발표로 리허설하기</span>
    </button>`).join('');
  if (!ready.length) {
    rhPickNote(decks ? '지금 고를 수 있는 발표가 없어요. 「다시 불러오기」를 눌러요.' : (why || '발표 목록을 불러오지 못했어요. 「다시 불러오기」를 눌러요.'));
    document.getElementById('rhDeckRetry').hidden = false;
    if (decks) console.info('[chuckchuck] rehearsal: 파싱본이 있는 리허설 덱이 없어요 — /test/qa 에서 한 번 열면 나타나요', REHEARSAL_DECK_KEYS);
    return;
  }
  box.querySelectorAll('[data-deck]').forEach((btn) => btn.addEventListener('click', () => {
    const d = ready.find((x) => x.key === btn.dataset.deck);
    if (d) rhPickDeck(d, btn);
  }));
  ready.forEach((d) => bqPaintCover(d));
}

function rhPickNote(text) {
  const foot = document.getElementById('bqDeckFoot');
  if (foot) foot.textContent = text;
}

/** 새 연습을 시작하는 공통 준비 — 지난 발표 · 질문 · 삐약이 반응을 지우고 질문은 3개 트랙으로 */
function rhFreshPractice() {
  resetNf();
  resetQa();
  qa.mode = REHEARSAL_QA_TRACK;
  saveSession('qa-flow', qa);
  try { sessionStorage.removeItem('cheokcheok:chuckchuck-session'); } catch (_) { /* ignore */ }
  if (typeof visionResetReactions === 'function') visionResetReactions();
}

/** 덱 — 지난 파싱본을 되살려 곧바로 비전 리허설로 (#/test/qa startTestDeck · 부스 bqPrepare 와 같은 길, 발표 정보 화면은 건너뛴다) */
async function rhPickDeck(d, btn) {
  const cards = [...document.querySelectorAll('#bqStage .bq-deck')];
  cards.forEach((b) => { b.disabled = true; });
  const go = btn.querySelector('.bq-deck-go');
  if (go) go.textContent = '자료를 펼치고 있어요…';
  const fail = (msg) => {
    cards.forEach((b) => { b.disabled = false; });
    if (go) go.textContent = '이 발표로 리허설하기';
    rhPickNote(msg);
    bq.decks = null;
  };
  rhFreshPractice();
  // 새 발표 — 지난 방문(부스 · 지난 리허설)에서 끈 카메라 · 오류를 넘기지 않는다
  bq.cam.off = false;
  bq.cam.error = '';
  bq.cam.denied = false;
  if (typeof visionCam !== 'undefined') { visionCam.off = false; visionCam.error = ''; }
  nf.occ = '';
  nf.ctx = '';
  nf.occTouched = false;
  nf.fileName = d.row.deck;
  nf.sessionId = d.row.cached_session_id;
  // 「녹음본을 넣어서 발표 마치기」가 쓸 이 발표의 녹음 — 새로고침해도 남게 nf 에 적는다
  nf.rehearsalDeck = { key: d.row.key, title: d.title, audio: d.row.audio || '', audioSec: Number(d.row.audio_sec) || 0 };
  if (typeof setUploadedPdf === 'function') setUploadedPdf(null);
  try {
    const pdf = await bqCoverPdf(d.row.cached_session_id);
    if (bq.screen !== 'pick') return;
    setUploadedPdf({ file: null, pdf, pageCount: pdf.numPages, shared: true });
  } catch (err) {
    console.warn('[chuckchuck] rehearsal cover reuse', err);
  }
  const doc = await ensureSlideDoc();
  if (bq.screen !== 'pick') return;
  if (!doc) { fail('이 발표는 지금 열 수 없어요. 다른 발표를 골라요.'); return; }
  applySlideDoc(doc, { keepDemoImages: false });
  nf.fileName = doc.file_name || d.row.deck;
  nf.gate = 'done';
  nf.step = 1;
  // 자료만 보고 발표 상황을 짐작해 둔다 — 일반 업로드(startParse)와 같은 F-23. 실패해도 고르기는 된다
  nf.suggest = null;
  const br = window.ChuckchuckBridge;
  if (br && typeof br.suggestContext === 'function') {
    try { nf.suggest = await br.suggestContext(doc); } catch (err) { console.warn('[chuckchuck] rehearsal suggest', err); }
  }
  if (bq.screen !== 'pick') return;
  saveSession('new-flow', nf);
  location.hash = `${REHEARSAL_HASH}/occ`;   // renderRehearsalEntry 가 「어떤 발표인가요」 를 그린다
}

/* ─── 어떤 발표인가요 — 발표 상황 (일반 흐름 nfStep2 의 칸 · 문구 그대로) ───────────────── */

/**
 * 10-03 사용자: 화상판 삐약이의 역할은 박아 두지 말고 발표 정보에서 고른 상황에서 온다 (app.js qaAudienceWord — 교수님 · 심사위원 · 상사 …).
 * 그래서 이 단계는 건너뛰지 않는다. 값 · 문구는 nfStep2 의 OCC_LABEL 과 F-23 추정(applyOccSuggestion) 그대로 — 부스 역할 고르기는 없다.
 * 고른 상황은 선분석(F-06 · F-07)과 채점에도 그대로 들어간다 — 그래서 선분석은 여기서 「발표하러 가기」를 누를 때 건다(nfStep2 와 같다).
 */
/** 「교수님이 물어요」 · 「상사가 물어요」 */
function rhAskerLine(word) {
  return `${word}${typeof josa === 'function' ? josa(word, '이', '가') : '이'} 물어요`;
}

/** 녹음 중에 뒤로 와서 테이크를 멈췄다 — 다음 「어떤 발표인가요」 가 한 번 말한다 */
let rhTakeCut = false;

function rhShowOcc(d) {
  const note = applyOccSuggestion();
  const cut = rhTakeCut;
  rhTakeCut = false;
  rhMount('occ', `
    <div class="bq-pick rh-occ">
      <p class="bq-eyebrow">${escapeHtml(d.title)}</p>
      <h1 class="bq-h1">어떤 발표인가요?</h1>
      <p class="bq-lead">고른 상황에 맞춰 개념 중요도를 정하고, 질문하는 삐약이가 그 자리의 사람이 돼요.</p>
      <fieldset class="bq-roles" aria-describedby="rhOccNote">
        <legend>발표 상황</legend>
        <div class="bq-role-list">${Object.entries(OCC_LABEL).map(([val, label]) => `
          <label class="bq-role" data-occ="${escapeHtml(val)}">
            <input type="radio" name="rhOcc" class="bq-sr" value="${escapeHtml(val)}"${nf.occ === val ? ' checked' : ''}>
            <b>${escapeHtml(label)}</b><small>${escapeHtml(rhAskerLine(QA_AUD_BY_OCC[val] || '질문자'))}</small>
          </label>`).join('')}</div>
        <p class="bq-role-note" id="rhOccNote">${note ? escapeHtml(note) : '하나를 골라요. 안 고르면 기본 기준으로 매기고 「질문자」가 물어요.'}</p>
      </fieldset>
      <label class="rh-ctx"><span>조금 더 설명해 주면 좋아요</span>
        <input type="text" id="rhCtx" value="${escapeHtml(nf.ctx || '')}" placeholder="예: 경영학 수업에서 교수님과 학생 30명 앞에서 발표해요"></label>
      ${cut ? '<p class="bq-foot rh-cut-note" role="status">녹음하던 발표는 멈췄어요. 다시 발표하려면 「카메라 앞에서 발표하러 가기」를 눌러요.</p>' : ''}
      <div class="rh-occ-actions">
        <button type="button" class="bq-cta" id="rhGoVision">카메라 앞에서 발표하러 가기</button>
        <button type="button" class="bq-ghost" id="rhRepick">다른 발표 고르기</button>
      </div>
    </div>`);
  document.querySelectorAll('#bqStage input[name="rhOcc"]').forEach((input) => input.addEventListener('change', () => {
    if (!input.checked) return;
    nf.occ = input.value;
    nf.occTouched = true;
    saveSession('new-flow', nf);
  }));
  document.getElementById('rhCtx').addEventListener('input', (e) => { nf.ctx = e.target.value; saveSession('new-flow', nf); });
  document.getElementById('rhRepick').addEventListener('click', () => { location.hash = REHEARSAL_HASH; });
  document.getElementById('rhGoVision').addEventListener('click', () => {
    // nfStep2 「녹음하러 가기」가 하는 일 — 발표하는 동안 개념 · 그래프를 먼저 만든다
    startPrecompute();
    nf.step = 2;
    saveSession('new-flow', nf);
    if (typeof visionFlowSet === 'function') visionFlowSet(true);
    location.hash = '#/new';
  });
}

/* ─── 비전 리허설 — 「녹음본을 넣어서 발표 마치기」 ─────────────────────────────── */

/** 2:19 처럼 */
function rhClock(sec) {
  const s = Math.max(0, Math.round(Number(sec) || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/**
 * vision_rehearsal.js nfStep3Vision 이 리허설 탭이면 부른다 — 조작줄의 「발표 마치고 질문 준비하기」 옆에 두 번째 끝내기를 둔다.
 * 10-03 사용자: 발표하고 싶지 않은 사람은 이 발표의 녹음으로 마친다. 녹음을 안 눌렀어도 · 카메라 · 마이크가 꺼져 있어도 된다.
 * 녹음 길은 새로 만들지 않는다 — #/test/qa 의 덱 녹음 받기(fetchDeckFile) + 일반 앱의 녹음 올리기(useUploadedRecording) 그대로.
 * 리허설은 직접 파일 올리기를 안 받는다 — 비전 조작줄의 「녹음 파일 올리기」는 이 탭에서 숨긴다(CSS).
 */
function rehearsalVisionDock(layer) {
  layer.dataset.flow = 'rehearsal';
  // 같은 흐름의 다른 화면(고르기 · 기다림 · 화상판)은 「발표 리허설」 — 비전 화면만 「비전 리허설」 이라 다른 기능처럼 보였다 (V-R2-5). /vision 은 그대로
  const pill = layer.querySelector('.vr-top .vr-pill');
  if (pill) pill.textContent = '발표 리허설';
  const deck = nf && nf.rehearsalDeck;
  const rec = layer.querySelector('#recPanel');
  if (!deck || !deck.audio || !rec) return;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'btn rh-rec-finish';
  btn.id = 'rhRecFinish';
  btn.textContent = '녹음본을 넣어서 발표 마치기';
  rec.after(btn);
  btn.addEventListener('click', () => rhConfirmRecording(layer));
}

function rhConfirmRecording(layer) {
  if (document.getElementById('rhRecSheet')) return;
  const deck = nf.rehearsalDeck;
  const clock = rhClock(deck.audioSec);
  const live = nf.mic === 'on' || (Number(nf.sec) || 0) > 0;
  const back = document.activeElement;
  const sheet = document.createElement('div');
  sheet.className = 'bq-sheet-wrap rh-rec-sheet';
  sheet.id = 'rhRecSheet';
  sheet.innerHTML = `<div class="bq-sheet" role="dialog" aria-modal="true" aria-labelledby="rhRecTitle" aria-describedby="rhRecBody">
      <h2 id="rhRecTitle">이 발표의 녹음으로 마칠까요?</h2>
      <p id="rhRecBody">발표하지 않아도 준비된 발표 녹음(${clock})으로 분석하고 질문 3개를 준비해요.${live ? ' <b>지금까지 녹음한 내 발표는 쓰지 않고 이 녹음으로 바꿔요.</b>' : ''} 카메라 반응(삐약이)은 리포트에 남지 않아요.</p>
      <p class="rh-rec-note" id="rhRecNote" role="status"></p>
      <div class="bq-sheet-actions">
        <button type="button" class="bq-ghost" data-sheet="close">닫기</button>
        <button type="button" class="bq-cta bq-cta-sm" data-sheet="use">이 발표의 녹음(${clock})으로 마칠게요</button>
      </div>
    </div>`;
  layer.appendChild(sheet);
  const close = () => { sheet.remove(); if (back && back.focus) back.focus(); };
  sheet.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { close(); return; }
    if (e.key !== 'Tab') return;
    const items = [...sheet.querySelectorAll('button:not(:disabled)')];
    const i = items.indexOf(document.activeElement);
    e.preventDefault();
    items[(i + (e.shiftKey ? -1 : 1) + items.length) % items.length].focus();
  });
  sheet.addEventListener('click', (e) => {
    const act = e.target.closest('[data-sheet]');
    if (e.target === sheet || (act && act.dataset.sheet === 'close')) close();
    else if (act && act.dataset.sheet === 'use') rhFinishWithRecording(sheet);
  });
  sheet.querySelector('[data-sheet="use"]').focus();
}

/**
 * 비전 리허설의 「나가기」 — 녹음 중이 아니면 바로 홈으로. 녹음 중이면 화면 안 시트(왼쪽 「닫기」)로 묻고, 나가면 테이크를 멈춘다.
 * 예전엔 브라우저 확인 창(확인/취소)이었고, 확인해도 녹음기 · 마이크가 홈에서 계속 돌았다 (10-03 점검 V3 · perf-1)
 */
function rehearsalVisionLeave(layer) {
  if (!nf || nf.mic !== 'on') { location.hash = '#/'; return; }
  if (document.getElementById('rhLeaveSheet')) return;
  const back = document.activeElement;
  const sheet = document.createElement('div');
  sheet.className = 'bq-sheet-wrap rh-rec-sheet';
  sheet.id = 'rhLeaveSheet';
  sheet.innerHTML = `<div class="bq-sheet" role="dialog" aria-modal="true" aria-labelledby="rhLeaveTitle" aria-describedby="rhLeaveBody">
      <h2 id="rhLeaveTitle">발표를 녹음하고 있어요</h2>
      <p id="rhLeaveBody">지금 나가면 이번 녹음은 남지 않아요. 계속 발표하려면 「닫기」를 눌러요.</p>
      <div class="bq-sheet-actions">
        <button type="button" class="bq-ghost" data-sheet="close">닫기</button>
        <button type="button" class="bq-cta bq-cta-sm" data-sheet="leave">녹음 멈추고 나가기</button>
      </div>
    </div>`;
  layer.appendChild(sheet);
  const close = () => { sheet.remove(); if (back && back.focus) back.focus(); };
  sheet.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { close(); return; }
    if (e.key !== 'Tab') return;
    const items = [...sheet.querySelectorAll('button')];
    const i = items.indexOf(document.activeElement);
    e.preventDefault();
    items[(i + (e.shiftKey ? -1 : 1) + items.length) % items.length].focus();
  });
  sheet.addEventListener('click', (e) => {
    const act = e.target.closest('[data-sheet]');
    if (e.target === sheet || (act && act.dataset.sheet === 'close')) close();
    else if (act && act.dataset.sheet === 'leave') {
      sheet.remove();
      if (typeof visionStopTake === 'function') visionStopTake();
      location.hash = '#/';
    }
  });
  sheet.querySelector('[data-sheet="close"]').focus();
}

/**
 * 분석이 멈춘 기다림에서 — 이 발표의 녹음으로 처음부터 다시 분석한다. 비전 리허설을 거치지 않는다 (10-03 점검 F4).
 * 지난 테이크의 질문 · 반응은 #againTake 처럼 버린다. useUploadedRecording 이 새 테이크(pipelineStartedAt)로 기다림 층을 새로 세운다
 */
async function rhReanalyzeWithRecording(btn) {
  const deck = nf.rehearsalDeck;
  if (!deck || !deck.audio) return;
  const note = document.getElementById('rhReRecNote');
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = '발표 녹음을 받고 있어요…';
  let file;
  try {
    file = await fetchDeckFile(deck.key, 'audio', deck.audio);
  } catch (err) {
    console.warn('[chuckchuck] rehearsal deck audio', err);
    btn.disabled = false;
    btn.textContent = label;
    if (note) note.textContent = '발표 녹음을 받지 못했어요. 한 번 더 눌러요.';
    return;
  }
  if (bq.screen !== 'wait' || rhRouteKey() !== 'new') return;
  try { sessionStorage.removeItem(RH_CUT_KEY); } catch (_) { /* ignore */ }
  resetQa();
  qa.mode = REHEARSAL_QA_TRACK;
  saveSession('qa-flow', qa);
  if (typeof chatterCache !== 'undefined') chatterCache = null;
  if (typeof visionCoachStop === 'function') visionCoachStop();
  if (typeof visionResetReactions === 'function') visionResetReactions();
  nf.visionSeen = false;
  nf.backstage = [];
  nf._pipelineLog = [];
  nf._stageActual = null;
  await useUploadedRecording(file, { knownDurationSec: deck.audioSec });
}

/** 덱 녹음을 받아 이번 발표의 녹음으로 — 라이브 녹음 · 반응은 버린다(useUploadedRecording 이 녹음기를 멈춘다) */
async function rhFinishWithRecording(sheet) {
  const deck = nf.rehearsalDeck;
  const note = sheet.querySelector('#rhRecNote');
  const buttons = [...sheet.querySelectorAll('button')];
  buttons.forEach((b) => { b.disabled = true; });
  if (note) note.textContent = '발표 녹음을 받고 있어요…';
  let file;
  try {
    file = await fetchDeckFile(deck.key, 'audio', deck.audio);
  } catch (err) {
    console.warn('[chuckchuck] rehearsal deck audio', err);
    buttons.forEach((b) => { b.disabled = false; });
    if (note) note.textContent = '발표 녹음을 받지 못했어요. 한 번 더 누르거나 「닫기」를 누르고 직접 발표할 수 있어요.';
    return;
  }
  if (!sheet.isConnected) return;
  // 라이브로 말한 동안 쌓인 삐약이 반응은 이 녹음의 것이 아니다 — 리포트가 녹음 위에 반응을 얹지 않게 비운다
  if (typeof visionCoachStop === 'function') visionCoachStop();
  if (typeof visionResetReactions === 'function') visionResetReactions();
  nf.visionSeen = false;
  // 녹음 중이었으면 녹음 시계를 멈추고 「발표 중」 을 내린다 — useUploadedRecording 은 녹음기만 멈춘다
  if (typeof clearTimers === 'function') clearTimers();
  nf.mic = 'idle';
  sheet.remove();
  await useUploadedRecording(file, { knownDurationSec: deck.audioSec });
}

/* ─── #/new step 3 분석 기다림 — 내 모습 위 글라스 한 장 ────────────────────────── */

/*
 * 10-03 사용자: 발표를 마치면(어느 끝내기든) 부스 앞 화면(시작 · 발표 고르기 · 역할 · 「통화 시작하기」)은 하나도 없이
 * 곧장 내 모습 + 삐약이 화상판으로. 분석 · 질문 생성 시간은 피할 수 없으니 같은 글라스 모양의 가벼운 화면 한 장에서
 * 진행을 정직하게 보여 주고, 질문이 준비되면 누르지 않아도 화상판으로 들어간다. 역할은 묻지 않고 기본(교수님).
 */

function rhRouteKey() {
  return location.hash.replace(/^#\/?/, '').split('/')[0];
}

function rhWaitHtml() {
  const title = rhWaitTitleText();
  return `
    <div class="bc-call rh-wait">
      <div class="bc-self" data-bq-cam-box data-camera="off">
        <video data-bq-cam autoplay muted playsinline></video>
        <p class="bc-self-off"><b>카메라 없이도 말로 답할 수 있어요</b><span id="bqCamNote"></span></p>
      </div>
      <section class="rh-wait-card bc-glass" aria-labelledby="rhWaitTitle">
        <div class="rh-wait-head">
          <span class="bc-host-bird">${bqBird(BC_HOST_BIRD, 'curious')}</span>
          <div>
            <h1 id="rhWaitTitle">발표를 듣고 질문 3개를 고르고 있어요</h1>
            <p class="rh-wait-tip" id="rhWaitTip">${escapeHtml(rhWaitTip(title))}</p>
          </div>
        </div>
        <ol class="bq-build-steps rh-wait-steps" id="bqBuildSteps">${RH_WAIT_STEPS.map((s) => `
          <li data-step="${s.key}" data-state="wait"><i aria-hidden="true"></i><span>${s.word}</span><span class="bq-sr" data-sr>기다리는 중이에요</span></li>`).join('')}</ol>
        <p class="rh-wait-foot"><span id="bqElapsed"></span><span id="rhWaitNext">질문이 준비되면 바로 시작해요</span></p>
        <div id="bqPrepFail" role="alert"></div>
        <button type="button" class="bq-cta" id="rhResume" hidden>질문에 이어서 답하기</button>
        <button type="button" class="bq-ghost" id="rhSkipReport" hidden>질문 없이 리포트 보기</button>
      </section>
      <p class="bq-sr" id="rhWaitLive" role="status" aria-atomic="true"></p>
    </div>`;
}

/**
 * 제목 밑 한 줄(글자 그대로 — 그리는 쪽이 escape). 녹음본으로 마쳤으면 그렇다고 말한다 — 카메라 반응이 없는 까닭도 (정직한 상태).
 * state: run(분석 중) · ready(질문까지 준비됨) · stopped(멈춤) — 멈췄는데 「분석하고 있어요」 가 제목 밑에 남아 서로 어긋났다 (10-03 점검 F4)
 */
function rhWaitTip(title, state = 'run') {
  const up = nf.uploadedTake;
  if (up) {
    const rec = `발표 녹음 「${up.name}」(${rhClock(up.durationSec)})`;
    if (state === 'stopped') return `${rec}으로 분석하다 멈췄어요.`;
    if (state === 'ready') return `${rec}으로 분석했어요. 카메라 앞 발표가 아니라서 삐약이 반응은 리포트에 없어요.`;
    return `${rec}으로 분석하고 있어요. 카메라 앞 발표가 아니라서 삐약이 반응은 리포트에 없어요.`;
  }
  const talk = `방금 한 ${title ? `「${title}」 ` : ''}발표`;
  if (state === 'stopped') return `${talk}를 분석하다 멈췄어요.`;
  if (state === 'ready') return `${talk}를 받아쓰고 자료와 맞춰 봤어요.`;
  return `${talk}를 받아쓰고 자료와 맞춰 봐요. 1~3분쯤 걸려요.`;
}

function rhWaitTitleText() {
  return (nf.rehearsalDeck && nf.rehearsalDeck.title) || String(nf.fileName || '').replace(/\.(pdf|pptx)$/i, '');
}

/**
 * 새로고침 · 탭 닫기로 분석이 끊겼는가 — 페이지를 떠날 때 돌던 분석의 테이크(pipelineStartedAt)를 적어 둔다.
 * 떠나는 순간 끊긴 요청이 'Failed to fetch' 로 저장돼서, 다시 열면 「연결이 끊겨서」 라고 거짓말을 했다 (10-03 점검 F4)
 */
const RH_CUT_KEY = 'cheokcheok:rehearsal-cut';
function rhMarkCutOnLeave() {
  try {
    if (!rehearsalFlowOn() || !nf || nf.step !== 3 || !nf.pipelineStartedAt) return;
    const phase = nf.pipelinePhase || '';
    if (phase === 'done' || phase === 'partial') return;
    if (phase === 'error' && !/fetch|network|abort/i.test(String(nf.pipelineError || ''))) return;
    sessionStorage.setItem(RH_CUT_KEY, String(nf.pipelineStartedAt));
  } catch (_) { /* 사생활 모드 — 예전 문구로 */ }
}
if (typeof window !== 'undefined' && window.addEventListener) {
  window.addEventListener('pagehide', rhMarkCutOnLeave);
  window.addEventListener('beforeunload', rhMarkCutOnLeave);
}
function rhCutByReload() {
  try { return !!nf.pipelineStartedAt && sessionStorage.getItem(RH_CUT_KEY) === String(nf.pipelineStartedAt); } catch (_) { return false; }
}

/** app.js nfStep4 가 그릴 때마다 부른다 — 층이 없으면 세우고, 있으면 줄 상태만 맞춘다 */
function rehearsalWaitSync() {
  if (!rehearsalFlowOn() || !nf || nf.step !== 3 || rhRouteKey() !== 'new') return;
  const layer = document.getElementById('bqStage');
  // 다른 테이크(다시 발표하기)의 기다림이면 새로 세운다 — 남은 층의 제목 · 도움말 · rhLiveAtMount 는 지난 테이크 것이다
  const take = String(nf.pipelineStartedAt || '');
  if (!layer || layer.dataset.screen !== 'wait' || (layer.dataset.take || '') !== take) {
    rhHandCamera();
    rhCarryCamChoice();
    // 화상판에서 뒤로 왔으면 자동 받아쓰기가 아직 듣고 있다 — 기다림에는 답 칸이 없어서 여기서 한 말이 다음 답 앞에 붙었다 (10-03 점검 perf-2).
    // 화상판으로 돌아가면 자동 받아쓰기가 다시 켠다
    if (typeof bcAutoCancelSend === 'function') { try { bcAutoCancelSend(); } catch (_) { /* 화상판이 없다 */ } }
    if (typeof bqStopMic === 'function') bqStopMic();
    rhMount('wait', rhWaitHtml(), { keepApp: true }).dataset.take = take;
    // 화상판에 들어가 본 적이 있으면(화상판에서 뒤로 가기) 저절로 되돌려 보내지 않는다 — 뒤로 가기가 막힌 것처럼 된다. 버튼으로만.
    // 질문이 있다는 것만으로는 아니다 — 들어가기 직전(「화상판으로 들어가요」 0.9초)에 새로고침하거나 기다림에서 뒤로 갔다 오면
    // 답한 적 없는데 「답하던 질문으로 돌아가서」 · 「질문에 이어서 답하기」 가 떠 저절로 들어가지 않았다 (10-03 점검 F6)
    bq.rhLiveAtMount = rhQaEntered();
    document.getElementById('rhSkipReport').addEventListener('click', rhGoReport);
    document.getElementById('rhResume').addEventListener('click', () => { location.hash = '#/qa'; });
    bqCamEnsure();
    bqCamPaint();
    rhWatchCamAlive();
    rhEnsureDeckPdf();   // 새로고침한 기다림이면 화상판 자료 창이 쓸 PDF 를 미리 받아 둔다 (F3)
    bq.timers.push(setInterval(rhWaitTick, REHEARSAL_POLL_MS));
  }
  rhWaitTick();
}

/** 화상판에서 질문을 받아 본 적이 있는가 — 첫 질문을 띄우면(presentLiveQuestion) asked 가 0 이 된다 */
function rhQaEntered() {
  const L = qa && qa.live;
  if (!qaLiveActive() || !L) return false;
  return (Number(L.asked) >= 0) || (Number(L.qi) > 0) || (L.turns || []).length > 0 || (L.results || []).length > 0;
}

/**
 * 기다림 층을 걷는다 — 다시 발표하러 비전 리허설로 돌아갈 때. 넘겨받은 카메라는 비전 쪽으로 돌려준다(다시 묻지 않게 · 두 개를 열지 않게)
 */
function rhReleaseWaitLayer() {
  if (typeof bqUnmount === 'function') bqUnmount();
  if (typeof bqClearTimers === 'function') bqClearTimers();
  bq.rhEntering = false;
  bq.rhLiveAtMount = false;
  bq.screen = '';
  // 화상판 쪽에서 꺼 둔 카메라는 비전 리허설에서도 꺼 둔다
  if (bq.cam.off && typeof visionCam !== 'undefined') { visionCam.off = true; bq.cam.off = false; }
  const s = bq.cam.stream;
  if (s && typeof visionCam !== 'undefined' && !visionCam.stream && s.getVideoTracks().some((t) => t.readyState === 'live')) {
    bq.cam.stream = null;
    if (window.BoothCV) { try { BoothCV.unwatch(); } catch (_) { /* 이미 멈춤 */ } }
    if (bq.video) bq.video.srcObject = null;
    visionCam.stream = s;
  } else if (typeof bqCamStop === 'function') {
    bqCamStop();
  }
}

/**
 * 비전 리허설에서 「카메라 끄기」 를 눌렀으면 기다림 · 화상판에서도 꺼 둔다 — 예전엔 넘겨받을 스트림이 없으면 off 를 풀고 새로 열어서
 * 끈 카메라가 다시 켜졌다 (10-03 점검 F3). 끈 선택은 bq.cam.off 로 옮겨 그 뒤로는 화상판의 「카메라 켜기」 가 정한다.
 * 끄지 않았는데 스트림이 없으면(비전에서 못 열었다 등) 지난 오류를 지우고 한 번 더 연다. 지난 방문의 off 는 발표를 고를 때 푼다(rhPickDeck)
 */
function rhCarryCamChoice() {
  if (typeof visionCam !== 'undefined' && visionCam.off) { bq.cam.off = true; visionCam.off = false; }
  if (bq.cam.stream || bq.cam.off) return;
  bq.cam.error = '';
  bq.cam.denied = false;
}

/** 비전 리허설이 연 카메라를 화상판 쪽으로 넘긴다 — 다시 묻지 않게 (app.js renderNew 가 리허설 탭이면 비전 카메라를 끄지 않고 둔다) */
function rhHandCamera() {
  if (typeof bq === 'undefined' || typeof visionCam === 'undefined') return;
  const s = visionCam.stream;
  if (s && !bq.cam.stream && s.getVideoTracks().some((t) => t.readyState === 'live')) {
    bq.cam.stream = s;
    bq.cam.off = false;
    bq.cam.error = '';
    visionCam.stream = null;
    // bqCamEnsure 가 연 스트림과 같이 — 카메라를 뽑거나 다른 앱이 가져가면 꺼짐 안내 · 「카메라 켜기」 로 바꾼다.
    // 안 그러면 화상판이 검은 화면에 마지막 「정면 n%」 와 「카메라 끄기」 를 띄운 채 멈췄다 (10-03 점검 V1)
    s.getVideoTracks().forEach((t) => t.addEventListener('ended', () => bqCamLost(s)));
  } else if (s && bq.cam.stream !== s) {
    visionCamStop();
  }
}

/**
 * ended 사건 없이 멈춘 트랙(다른 쪽이 stop() 등)도 잡는다 — 부스는 자리 비움 시계가 1초마다 bqCamCheckAlive 를 부르지만
 * 그 시계는 리허설 탭에서 돌지 않는다(booth_ops.js bqArmIdle). 리허설 층(기다림 · 화상판)이 있는 동안만 돌고 스스로 멈춘다
 */
let rhCamAliveTimer = 0;
function rhWatchCamAlive() {
  if (rhCamAliveTimer) return;
  rhCamAliveTimer = setInterval(() => {
    if (!document.querySelector('#bqStage[data-flow="rehearsal"]')) { clearInterval(rhCamAliveTimer); rhCamAliveTimer = 0; return; }
    if (typeof bqCamCheckAlive === 'function') bqCamCheckAlive();
  }, 1000);
}

/** 질문 재료(그래프 · 정합 · 흐름)가 모였으면 질문을 만든다 — 일반 앱 #/qa 와 같은 함수 · 같은 3개 트랙 */
function rhKickQuestions() {
  if (typeof pipelineQaReady !== 'function' || !pipelineQaReady()) return;
  if (qaLiveActive() || qaBuilding || qaBuildFailed) return;
  qa.mode = REHEARSAL_QA_TRACK;
  qa.started = true;
  qa.aud = qaAudienceWord();   // 발표 상황에서 고른 자리의 사람 — 화상판 삐약이 이름표(booth_call.js bcRole). 질문 · 판정 요청에는 안 실린다
  saveSession('qa-flow', qa);
  ensureLiveQuestions();
}

/** 다섯 줄 중 지금 도는 줄 — 화면 읽기가 단계가 바뀔 때 한 번씩 읽는다 */
function rhWaitNow(st) {
  const run = RH_WAIT_STEPS.find((s) => st[s.key] === 'run');
  return run ? run.word : '';
}

function rhWaitTick() {
  if (bq.screen !== 'wait' || !document.getElementById('bqBuildSteps')) return;
  rhKickQuestions();
  const qaReady = typeof pipelineQaReady === 'function' && pipelineQaReady();
  const live = qaLiveActive();
  // 실패 직전 단계를 층에 적어 둔다(테이크마다 층을 새로 세운다) — 실패하면 단계 이름이 'error' 하나뿐이다
  const layer = document.getElementById('bqStage');
  const phase = nf.pipelinePhase || '';
  if (layer && phase && phase !== 'error') layer.dataset.lastPhase = phase;
  const st = rehearsalWaitStates({
    phase, out: nf.pipelineOut, qaReady,
    questionsReady: live, buildFailed: !!qaBuildFailed, building: !!qaBuilding,
    hasTake: !!(nf.uploadedTake || Number(nf.sec) > 0 || (typeof ccLastTake !== 'undefined' && ccLastTake)), lastPhase: (layer && layer.dataset.lastPhase) || '',
  });
  Object.entries(st).forEach(([k, v]) => bqSetStep(k, v));
  const stopped = Object.values(st).includes('fail');
  const el = document.getElementById('bqElapsed');
  // 멈췄으면 시계도 멈춘다 — 「n초 지났어요」 · 「질문이 준비되면 바로 시작해요」 가 계속 가면 아직 기다리는 것처럼 보였다 (F5)
  // 질문이 준비됐으면 시계도 멈춘다 — 다 됐는데 「n초 지났어요」 가 계속 올라갔다 (F6)
  if (el && nf.pipelineStartedAt && !stopped && !live) bqSet(el, 'textContent', `${Math.max(0, Math.round((Date.now() - nf.pipelineStartedAt) / 1000))}초 지났어요`);
  // 멈춘 시계(「0초 지났어요」)를 남기지 않는다 — 금방 실패하면 0초에 선 채로 보였다
  bqSet(el, 'hidden', stopped || live);
  bqSet(document.getElementById('rhWaitNext'), 'hidden', stopped);
  bqSet(document.getElementById('rhWaitLive'), 'textContent', rhWaitNow(st));
  if (live && bq.rhLiveAtMount) {
    bqSet(document.getElementById('rhResume'), 'hidden', false);
    bqSet(document.getElementById('rhWaitTitle'), 'textContent', '질문 3개를 준비해 뒀어요');
    bqSet(document.getElementById('rhWaitTip'), 'textContent', '답하던 질문으로 돌아가서 이어서 답할 수 있어요.');
    bqSet(document.getElementById('rhWaitNext'), 'textContent', '');
  } else if (live && !bq.rhEntering) {
    // 질문이 준비됐다 — 누르지 않아도 화상판으로 (잠깐 「준비됐어요」 를 보여 주고)
    bq.rhEntering = true;
    bqSet(document.getElementById('rhWaitTitle'), 'textContent', '질문 3개를 준비했어요. 화상판으로 들어가요');
    // 다 끝났는데 밑줄이 「…맞춰 봐요. 1~3분쯤 걸려요」 로 남아 제목과 어긋났다 (V-R2-5)
    bqSet(document.getElementById('rhWaitTip'), 'textContent', rhWaitTip(rhWaitTitleText(), 'ready'));
    bq.timers.push(setTimeout(() => { bq.rhEntering = false; if (rhRouteKey() === 'new' && nf.step === 3) location.hash = '#/qa'; }, 900));
  }
  rhWaitFail(st, qaReady);
}

/** 멈췄으면 멈췄다고 — 분석이 멈춘 것과 질문을 못 만든 것은 할 일이 다르다 */
function rhWaitFail(st, qaReady) {
  const box = document.getElementById('bqPrepFail');
  if (!box) return;
  const skip = document.getElementById('rhSkipReport');
  let key = '';
  if (Object.values(st).includes('fail')) key = st.questions === 'fail' ? 'questions' : 'pipeline';
  if (box.dataset.key === key) return;
  box.dataset.key = key;
  if (skip) skip.hidden = !key;
  if (!key) { box.innerHTML = ''; return; }
  const cut = key === 'pipeline' && rhCutByReload();
  bqSet(document.getElementById('rhWaitTitle'), 'textContent',
    key === 'questions' ? '질문을 만들다 멈췄어요' : (cut ? '새로고침해서 분석이 멈췄어요' : '발표 분석이 멈췄어요'));
  bqSet(document.getElementById('rhWaitTip'), 'textContent',
    key === 'questions' ? '발표 분석은 끝났고, 질문을 고르다 멈췄어요.' : rhWaitTip(rhWaitTitleText(), 'stopped'));
  if (key === 'questions') {
    console.warn('[chuckchuck] rehearsal questions', qa.liveError);
    box.innerHTML = `<div class="bq-fail"><p>「다시 만들기」를 누르면 한 번 더 만들어요. 리포트는 질문 없이도 볼 수 있어요.</p>
      <button type="button" class="bq-ghost" id="rhRetryQ">다시 만들기</button></div>`;
    document.getElementById('rhRetryQ').addEventListener('click', () => {
      qaBuildFailed = false;
      qaBridgeTries = 0;
      qa.liveNotice = '';
      qa.liveError = '';
      // 실패 칸 · 「질문 없이 리포트 보기」 를 걷는다 — 다음 rhWaitFail 도 key '' 라 일찍 돌아가서, 다시 만드는 동안 실패 안내가 남았다 (10-03 점검 F4)
      box.dataset.key = '';
      box.innerHTML = '';
      if (skip) skip.hidden = true;
      bqSet(document.getElementById('rhWaitTitle'), 'textContent', '발표를 듣고 질문 3개를 고르고 있어요');
      bqSet(document.getElementById('rhWaitTip'), 'textContent', rhWaitTip(rhWaitTitleText()));
      rhKickQuestions();
      rhWaitTick();
    });
    return;
  }
  let why = typeof humanErrorText === 'function' ? humanErrorText(nf.pipelineError || nf.pipelineDetail || '') : '';
  // 영어 원문(「Failed to fetch.」 등)은 화면에 안 낸다 — 원문은 콘솔에 남는다 (F5)
  if (!/[가-힣]/.test(why)) why = /fetch|network|abort/i.test(why) ? '연결이 끊겨서 분석을 마치지 못했어요' : '';
  // 한 단계만 죽고 닫힌 분석('partial')은 「개념 추출 실패」 같은 내부 이름 대신 멈춘 줄을 사람 말로 (10-03 점검 F1)
  if ((nf.pipelinePhase || '') === 'partial') why = RH_WAIT_FAIL_WORD[RH_WAIT_STEPS.map((x) => x.key).find((k) => st[k] === 'fail')] || '';
  console.warn('[chuckchuck] rehearsal pipeline', nf.pipelineError || nf.pipelineDetail);
  // 녹음본으로 마친 발표는 발표하러 돌아갈 까닭이 없다 — 같은 녹음으로 곧장 다시 분석한다 (F4). 직접 발표한 테이크는 새로고침하면 남지 않는다
  const deck = nf.rehearsalDeck;
  const fromRec = !!nf.uploadedTake;
  const canRec = !!(deck && deck.audio);
  let lead;
  if (cut) {
    lead = fromRec
      ? '화면을 새로 고치면 하던 분석이 멈춰요. 「이 녹음으로 다시 분석하기」를 누르면 같은 녹음으로 처음부터 분석해요.'
      : '화면을 새로 고치면 하던 분석이 멈추고, 방금 한 발표 녹음은 남지 않아요. 「다시 발표하기」를 누르면 같은 자료로 다시 발표할 수 있어요.';
  } else {
    lead = `${why || '분석을 마치지 못했어요'}. ${fromRec && canRec
      ? '「이 녹음으로 다시 분석하기」를 누르면 같은 녹음으로 한 번 더 분석해요.'
      : '「다시 발표하기」를 누르면 같은 자료로 다시 발표할 수 있어요.'}`;
  }
  const reBtn = canRec
    ? `<button type="button" class="bq-ghost" id="rhReRec">${fromRec ? '이 녹음으로 다시 분석하기' : '이 발표의 녹음으로 분석하기'}</button> `
    : '';
  const reOrder = fromRec
    ? `${reBtn}<button type="button" class="bq-ghost" id="rhAgain">카메라 앞에서 발표하기</button>`
    : `<button type="button" class="bq-ghost" id="rhAgain">다시 발표하기</button> ${reBtn}`;
  box.innerHTML = `<div class="bq-fail"><p>${escapeHtml(lead)}</p>
    ${reOrder} <button type="button" class="bq-ghost" id="rhRepick">다른 발표 고르기</button>
    <p class="rh-rec-note" id="rhReRecNote" role="status"></p></div>`;
  const reRec = document.getElementById('rhReRec');
  if (reRec) reRec.addEventListener('click', () => rhReanalyzeWithRecording(reRec));
  // 자료는 그대로 두고 테이크만 버리는 길은 nfStep4 의 「다른 녹음으로 다시」와 같다 — 그 버튼을 그대로 누른다
  document.getElementById('rhAgain').addEventListener('click', () => {
    // 기다림 층을 먼저 걷는다 — #againTake 는 #app 만 다시 그려서, 이 층(1초 시계 · 넘겨받은 카메라)이 비전 리허설 밑에 남았고
    // 두 번째 기다림에서는 층을 새로 안 세워 「발표 분석이 멈췄어요」 가 그대로였다 (10-03 점검 F1)
    rhReleaseWaitLayer();
    const again = document.getElementById('againTake');
    if (again) again.click();
  });
  document.getElementById('rhRepick').addEventListener('click', () => { location.hash = REHEARSAL_HASH; });
  if (skip) skip.hidden = !qaReady && !(nf.pipelineOut && nf.pipelineOut.graph);
}

/* ─── #/qa 글라스 화상판 ──────────────────────────────────────────────── */

/**
 * qa_live.js renderQaLive 가 리허설 탭이면 부른다. 화상판은 부스 그대로(booth_call.js renderQaLiveBoothCall) 그리고,
 * 오른쪽 위 자료 창만 비전 리허설의 자료 창처럼 옮기고 · 크기를 바꾸고 · 불투명도를 바꿀 수 있게 꺼내 놓는다 —
 * 발표할 때 옮겨 둔 자리 · 불투명도(vision_rehearsal.js VISION_SLIDE_KEY)를 그대로 이어 쓴다.
 */
function renderQaLiveRehearsal() {
  bq.variant = 'call';
  if (typeof qaAudienceWord === 'function') qa.aud = qaAudienceWord();
  rhCarryCamChoice();
  if (window.BoothCV && typeof BoothCV.load === 'function') BoothCV.load();
  renderQaLiveBoothCall();
  const layer = document.getElementById('bqStage');
  if (!layer) return;
  rhWireExit(layer);
  rhFloatSlide(layer);
  rhWatchCamAlive();
  // 새로고침한 뒤면 자료 PDF 가 없어 자료 창이 회색 자리표시(장 번호)만 그렸다 — 받아서 지금 장을 다시 그린다 (10-03 점검 F3)
  if (!uploadedPdf) {
    rhEnsureDeckPdf().then((pdf) => {
      const slide = pdf && document.getElementById('bqSlide');
      if (!slide || typeof bqSyncSlide !== 'function') return;
      slide.dataset.focus = '';   // 같은 장이어도 다시 쓴다 — 자리표시 그림을 캔버스로
      bqSyncSlide();
    });
  }
}

/**
 * 자료 PDF 를 메모리에 — 새로고침하면 uploadedPdf 는 사라지고, 비전 리허설(nfStep3Vision)만 다시 받았다.
 * 고를 때(rhPickDeck)와 같은 길(파싱본 미리보기 PDF), 안 되면 일반 앱의 미리보기 PDF
 */
let rhPdfLoading = null;
function rhEnsureDeckPdf() {
  if (uploadedPdf) return Promise.resolve(uploadedPdf);
  if (rhPdfLoading) return rhPdfLoading;
  const sid = nf && nf.sessionId;
  rhPdfLoading = (async () => {
    if (sid && typeof bqCoverPdf === 'function') {
      try {
        const pdf = await bqCoverPdf(sid);
        if (!uploadedPdf && nf && nf.sessionId === sid) setUploadedPdf({ file: null, pdf, pageCount: pdf.numPages, shared: true });
        if (uploadedPdf) return uploadedPdf;
      } catch (err) {
        console.warn('[chuckchuck] rehearsal deck pdf', err);
      }
    }
    return typeof ensurePreviewPdf === 'function' ? ensurePreviewPdf(typeof nfSlideDoc !== 'undefined' ? nfSlideDoc : null) : null;
  })().finally(() => { rhPdfLoading = null; });
  return rhPdfLoading;
}

function rhFloatSlide(layer) {
  const fig = layer.querySelector('#bqSlide');
  const call = layer.querySelector('.bc-call');
  if (!fig || !call) return;
  const slot = document.createElement('div');
  slot.className = 'vr-slide-slot rh-slide-slot';
  slot.setAttribute('aria-hidden', 'true');
  slot.innerHTML = '<i></i>';
  fig.replaceWith(slot);
  const win = document.createElement('section');
  win.className = 'vr-slide rh-slide';
  win.id = 'vrSlide';
  win.setAttribute('aria-label', '발표 자료');
  win.innerHTML = `
    <div class="rh-slide-body"></div>
    <footer class="vr-slide-cap">
      <button type="button" class="vr-drag" id="vrSlideDrag" aria-label="발표 자료 옮기기" title="끌어서 옮기기. 두 번 누르면 원래 자리">⠿</button>
      <span class="rh-cap-fill"></span>
      <label class="vr-alpha">
        <span>불투명도</span>
        <input id="vrSlideAlpha" type="range" min="25" max="100" value="78" aria-label="발표 자료 불투명도">
      </label>
    </footer>
    <button type="button" class="vr-resize" id="vrSlideResize" aria-label="발표 자료 크기 조절"></button>`;
  win.querySelector('.rh-slide-body').appendChild(fig);
  call.appendChild(win);
  // 「질문이 가리키는 n장」 은 아래 조작줄의 빈 칸에 비춘다 — 장 그림이 창 높이를 다 쓰게. 장이 바뀌면 bqSyncSlide 가 그림 칸을 통째로 다시 쓴다
  const capFill = win.querySelector('.rh-cap-fill');
  // 앞말(「질문이 가리키는」)은 따로 감싼다 — 좁은 창(아이패드 세로 124px)에서는 접고 「n장」 만 남긴다. 예전엔 말줄임으로 「질문…」 만 보여 장 번호를 잃었다 (V-R2-2)
  const mirror = () => {
    const cap = fig.querySelector('figcaption');
    const html = cap ? cap.innerHTML.replace(/^([^<]+)(?=<b>)/, (m) => `<span class="rh-cap-why">${m}</span>`) : '';
    if (capFill.innerHTML !== html) capFill.innerHTML = html;
  };
  mirror();
  new MutationObserver(mirror).observe(fig, { childList: true });
  if (typeof visionSlideBind !== 'function') return;
  visionSlideBind(layer, { repaint: () => { if (fig.isConnected) paintDeckStage(fig); } });
  // 기본 자리(옮긴 적 없음)는 오른쪽 위 칸을 따라간다 — 위 질문 카드 높이가 정해지면 칸이 내려가므로 그때 다시 맞춘다
  if (rhSlideWatch) rhSlideWatch.disconnect();
  if (!window.ResizeObserver) return;
  rhSlideWatch = new ResizeObserver(() => { if (win.isConnected) visionSlideApply(win); });
  [slot, layer.querySelector('.bc-ask'), layer.querySelector('.bc-dock')].filter(Boolean).forEach((el) => rhSlideWatch.observe(el));
}
let rhSlideWatch = null;

/* ─── 질문을 마치면 — 리포트로 (qa_live.js qaLiveEnd 가 기록을 남긴 뒤 부른다) ─────────── */

function rehearsalQaDone() {
  if (typeof bqUnmount === 'function') bqUnmount();
  if (typeof bqClearTimers === 'function') bqClearTimers();
  rehearsalTeardown();
  rhGoReport();
}

/**
 * 리포트로 — 지금 칸(#/qa · 기다림의 #/new)을 #/rehearsal 로 바꿔 두고 리포트를 쌓는다. 리포트에서 뒤로 가면 발표 고르기다.
 * 예전엔 뒤로 가면 리허설 표시가 꺼진 일반 #/qa 결과 카드가 떴고, 한 번 더 가면 #/new 가 끝난 세션을 지워 리포트가 비었다 (10-03 점검 F6).
 * replaceState 는 hashchange 를 안 내므로 그 칸을 다시 그리지 않는다
 */
function rhGoReport() {
  try { history.replaceState(history.state, '', REHEARSAL_HASH); } catch (_) { /* 못 바꾸면 예전처럼 */ }
  location.hash = '#/report';
}
