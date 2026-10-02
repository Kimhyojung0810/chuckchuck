/**
 * 부스 운영 장치 — /booth/qa · /booth/call 공통. 하루 종일 새로고침 없이 방문객이 이어지는 노트북 한 대를 위한 것.
 *
 * 2026-10-01 부스 점검(UX · 접근성 · 성능 세 갈래)에서 나온 운영 구멍을 막는다:
 *   - 방문객이 질문 도중 떠나면 앞사람의 답·판정이 다음 사람에게 그대로 보였다 → 자리 비움 자동 복귀
 *   - 스태프가 바로 처음으로 돌릴 키가 없었다 → Esc 두 번
 *   - 「처음으로」가 브라우저 confirm(「확인/취소」 회색 창)이었다 → 화면 안 시트 [닫기] [처음으로 갈게요]
 *   - 마지막 질문 뒤 「결과 확인하기」에서 멈춰 섰다 → 12초 뒤 결과로
 *   - 하루 몇백 명이면 남는 메모리가 쌓인다 → 방문객 40명마다, 아무도 없을 때 한 번 새로고침
 * 로직(질문·판정)은 건드리지 않는다. 클래식 스크립트라 booth_qa.js 의 bq · bqGoHome 등을 호출 시점에 찾는다.
 */

/** 카메라가 사람을 보고 있으면: 사람이 안 보인 채 이만큼 지나면 묻는다 */
const BQ_IDLE_AWAY_MS = 30000;
/** 카메라 판단이 없으면: 아무 조작 없이 이만큼 지나면 묻는다 */
const BQ_IDLE_NOINPUT_MS = 120000;
/** 「아무도 없는 것 같아요」 를 띄운 뒤 처음으로 가기까지 */
const BQ_IDLE_WARN_SEC = 20;
/** 마지막 질문을 마친 뒤 결과 화면으로 넘어가기까지 */
const BQ_AUTO_END_SEC = 12;
/** Esc 두 번 사이 */
const BQ_ESC_GAP_MS = 1500;
/** 방문객 이만큼마다 아무도 없을 때 새로고침 — 남는 메모리를 비우는 보험 */
const BQ_RELOAD_EVERY = 40;
const BQ_VISITS_KEY = 'cheokcheok:booth-visits';

const bqOps = { idleTimer: 0, warnTimer: 0, lastInput: 0, awaySince: 0, escAt: 0, keysOn: false, endTimer: 0, endLeft: 0, reloadTimer: 0 };

/* ─── 자리 비움 ─────────────────────────────────────────────────────────── */

function bqTouch() {
  bqOps.lastInput = Date.now();
  if (bqOps.warnTimer) bqIdleCancelWarn();
}

/** 화면마다 bqMount 가 부른다. 조작은 어느 화면에서나 세고, 자리 비움은 발표 고르기 · 훑어보기 · 질문 화면에서만 본다 */
const BQ_IDLE_SCREENS = new Set(['pick', 'prep', 'qa']);

function bqArmIdle(layer, screen) {
  bqDisarmIdle();
  bqOps.lastInput = Date.now();
  bqOps.awaySince = 0;
  ['pointerdown', 'keydown', 'input', 'wheel'].forEach((ev) => layer.addEventListener(ev, bqTouch, { capture: true, passive: true }));
  if (BQ_IDLE_SCREENS.has(screen)) bqOps.idleTimer = setInterval(bqIdleTick, 1000);
}

function bqDisarmIdle() {
  if (bqOps.idleTimer) clearInterval(bqOps.idleTimer);
  bqOps.idleTimer = 0;
  bqIdleCancelWarn();
}

/** 받아쓰기 결과가 이만큼 안에 들어왔으면 사람이 말하고 있는 것이다 */
const BQ_SPEAKING_MS = 20000;

/**
 * 지금 누가 체험 중인 게 분명한가 — 판정을 기다리거나, 최근에 받아쓰기 글이 들어왔으면 자리에 있다.
 * 예전엔 마이크가 켜져 있기만 하면 바쁨이라 자리 비움이 영영 안 떴다 — 자동 받아쓰기가 들어오면 늘 켜져 있다 (10-02 사냥 2 #4).
 * 녹음 길(서버 받아쓰기)은 글이 늦게 오므로 켜져 있는 동안 바쁨으로 본다
 */
function bqBusyNow() {
  const L = typeof qa !== 'undefined' && qa && qa.live;
  if (L && L.busy) return true;
  const mic = typeof liveMic !== 'undefined' && liveMic;
  if (!mic) return false;
  if (!mic.dictation) return true;
  return !!mic.lastTextAt && Date.now() - mic.lastTextAt < BQ_SPEAKING_MS;
}

function bqIdleTick() {
  const now = Date.now();
  if (typeof bqCamCheckAlive === 'function') bqCamCheckAlive();
  if (bqBusyNow()) { bqOps.lastInput = now; return; }
  const cv = window.BoothCV ? BoothCV.snapshot() : null;
  const seeing = typeof bqCamLive === 'function' && bqCamLive() && cv && cv.status === 'ready';
  let idleFor;
  if (seeing) {
    if (cv.present) bqOps.awaySince = 0;
    else if (!bqOps.awaySince) bqOps.awaySince = now;
    // 사람이 안 보인 시간과 마지막 조작 뒤 시간 중 짧은 쪽 — 카메라 밖에서 타이핑하는 사람을 내쫓지 않게
    idleFor = bqOps.awaySince ? Math.min(now - bqOps.awaySince, now - bqOps.lastInput) : 0;
    if (idleFor >= BQ_IDLE_AWAY_MS && !bqOps.warnTimer) bqIdleWarn();
  } else {
    idleFor = now - bqOps.lastInput;
    if (idleFor >= BQ_IDLE_NOINPUT_MS && !bqOps.warnTimer) bqIdleWarn();
  }
}

function bqIdleWarn() {
  const layer = document.getElementById('bqStage');
  if (!layer) return;
  let left = BQ_IDLE_WARN_SEC;
  const box = document.createElement('div');
  box.className = 'bq-toast';
  box.id = 'bqIdleToast';
  box.setAttribute('role', 'alertdialog');
  box.setAttribute('aria-labelledby', 'bqIdleText');
  box.innerHTML = `<p id="bqIdleText"></p><button type="button" class="bq-cta bq-cta-sm" id="bqIdleStay">계속할게요</button>`;
  layer.appendChild(box);
  const paint = () => {
    const p = document.getElementById('bqIdleText');
    if (p) p.textContent = `아무도 없는 것 같아요. ${left}초 뒤 처음 화면으로 돌아가요`;
  };
  paint();
  const stay = document.getElementById('bqIdleStay');
  stay.addEventListener('click', bqTouch);
  stay.focus({ preventScroll: true });
  bqOps.warnTimer = setInterval(() => {
    left -= 1;
    if (left <= 0) { bqDisarmIdle(); bqGoHome(); return; }
    paint();
  }, 1000);
}

function bqIdleCancelWarn() {
  if (bqOps.warnTimer) clearInterval(bqOps.warnTimer);
  bqOps.warnTimer = 0;
  bqOps.awaySince = 0;
  const box = document.getElementById('bqIdleToast');
  if (box) box.remove();
}

/* ─── 처음으로 — 스태프 키 · 확인 시트 ─────────────────────────────────────── */

/**
 * 스태프 키 — Shift+Esc 는 묻지 않고 바로 처음으로. Esc 를 1.5초 안에 두 번은 질문 도중이면 확인 시트(방문객이 연타해도 날아가지 않게),
 * 그 밖의 화면(시작 · 고르기 · 준비 · 결과)에서는 바로 처음으로 (10-02 버그 사냥 P2-3). 한 번만 설치한다
 */
function bqInstallKeys() {
  if (bqOps.keysOn) return;
  bqOps.keysOn = true;
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || !document.getElementById('bqStage')) return;
    if (e.shiftKey) { bqOps.escAt = 0; const s = document.getElementById('bqSheet'); if (s) s.remove(); bqGoHome(); return; }
    const sheet = document.getElementById('bqSheet');
    if (sheet) { sheet.remove(); return; }
    const now = Date.now();
    if (now - bqOps.escAt < BQ_ESC_GAP_MS) { bqOps.escAt = 0; bqHomeClicked(); return; }
    bqOps.escAt = now;
  });
}

/** 질문 도중 「처음으로」 — 브라우저 confirm 대신 화면 안 시트. 왼쪽은 「닫기」 (CLAUDE.md §3-1) */
function bqConfirmHome() {
  const layer = document.getElementById('bqStage');
  if (!layer || document.getElementById('bqSheet')) return;
  const back = document.activeElement;
  const sheet = document.createElement('div');
  sheet.className = 'bq-sheet-wrap';
  sheet.id = 'bqSheet';
  sheet.innerHTML = `<div class="bq-sheet" role="dialog" aria-modal="true" aria-labelledby="bqSheetTitle" aria-describedby="bqSheetBody">
      <h2 id="bqSheetTitle">처음 화면으로 갈까요?</h2>
      <p id="bqSheetBody">지금까지 답한 내용은 지워져요.</p>
      <div class="bq-sheet-actions">
        <button type="button" class="bq-ghost" data-sheet="close">닫기</button>
        <button type="button" class="bq-cta bq-cta-sm" data-sheet="home">처음으로 갈게요</button>
      </div>
    </div>`;
  layer.appendChild(sheet);
  // 시트가 떠 있는 동안 뒤 층은 inert — Tab 세 번이면 뒤 버튼으로 빠져나갔다 (사냥 3). 시트 안에서 Tab 이 돈다
  const behind = [...layer.children].filter((el) => el !== sheet);
  behind.forEach((el) => { el.inert = true; });
  const release = () => behind.forEach((el) => { el.inert = false; });
  new MutationObserver((recs, mo) => { if (!sheet.isConnected) { release(); mo.disconnect(); } }).observe(layer, { childList: true });
  sheet.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    const items = [...sheet.querySelectorAll('button')];
    const i = items.indexOf(document.activeElement);
    e.preventDefault();
    items[(i + (e.shiftKey ? -1 : 1) + items.length) % items.length].focus();
  });
  const close = () => { sheet.remove(); release(); if (back && back.focus) back.focus(); };
  sheet.addEventListener('click', (e) => {
    const act = e.target.closest('[data-sheet]');
    if (e.target === sheet || (act && act.dataset.sheet === 'close')) close();
    else if (act && act.dataset.sheet === 'home') { sheet.remove(); bqGoHome(); }
  });
  sheet.querySelector('[data-sheet="close"]').focus();
}

/* ─── 마지막 질문 뒤 — 결과로 넘어가기 ──────────────────────────────────────── */

/**
 * 질문을 다 마친 자리(qa.live.awaitEnd)면 12초를 세고 결과 화면으로. 무대 sync 가 매번 부른다.
 * 끝 카드 초읽기 글은 **바뀔 때만** 쓴다 — 같은 글이어도 textContent 를 쓰면 글 마디가 갈려 MutationObserver 가 깨고,
 * 화상판의 답 칸 감시가 다시 이 함수를 불러 탭이 멈췄다 (10-01 점검 P0: 1초에 수천 번 돌았다).
 */
function bqArmAutoEnd() {
  const L = qa && qa.live;
  if (!L || !L.awaitEnd) return;
  const note = document.querySelector('#bqStage .qa-end-note');
  if (bqOps.endTimer) {
    bqEndNote(note);
    return;
  }
  bqOps.endLeft = BQ_AUTO_END_SEC;
  bqEndNote(note);
  bqOps.endTimer = setInterval(() => {
    bqOps.endLeft -= 1;
    const n = document.querySelector('#bqStage .qa-end-note');
    if (!n || bq.screen !== 'qa') { bqStopAutoEnd(); return; }
    if (bqOps.endLeft <= 0) { bqStopAutoEnd(); qaLiveEnd(); return; }
    bqEndNote(n);
  }, 1000);
}

function bqEndNote(el) {
  const text = `${bqOps.endLeft}초 뒤 결과를 보여 줘요`;
  if (el && el.textContent !== text) el.textContent = text;
}

function bqStopAutoEnd() {
  if (bqOps.endTimer) clearInterval(bqOps.endTimer);
  bqOps.endTimer = 0;
}

/* ─── 하루 운영 — 방문객 수 · 새로고침 보험 ──────────────────────────────────── */

/** 체험을 시작할 때(「체험 시작하기」) 센다 */
function bqCountVisit() {
  try {
    const n = Number(sessionStorage.getItem(BQ_VISITS_KEY) || 0) + 1;
    sessionStorage.setItem(BQ_VISITS_KEY, String(n));
  } catch (_) { /* 사생활 모드 — 세지 않는다 */ }
}

/**
 * 시작 화면에서 — 방문객이 40명을 넘었고, 아무도 없고, 30초 동안 조작이 없으면 새로고침한다.
 * 해시가 #/booth/… 그대로라 같은 무대로 다시 열리고, 카메라 권한·OpenCV 는 캐시돼 1~2초면 다시 뜬다.
 */
function bqArmReloadGuard() {
  if (bqOps.reloadTimer) clearInterval(bqOps.reloadTimer);
  bqOps.reloadTimer = setInterval(() => {
    if (bq.screen !== 'attract') { clearInterval(bqOps.reloadTimer); bqOps.reloadTimer = 0; return; }
    let n = 0;
    try { n = Number(sessionStorage.getItem(BQ_VISITS_KEY) || 0); } catch (_) { return; }
    if (n < BQ_RELOAD_EVERY) return;
    const cv = window.BoothCV ? BoothCV.snapshot() : null;
    if (cv && cv.present) return;
    if (Date.now() - bqOps.lastInput < 30000) return;
    try { sessionStorage.setItem(BQ_VISITS_KEY, '0'); } catch (_) { return; }
    location.reload();
  }, 5000);
}

/* ─── 무대 오른쪽 자료 창 — 지금 이야기하는 장 ──────────────────────────────── */

/**
 * 지금 질문에서 가장 최근에 짚은 장. 판정 근거(groundSlides)·힌트(slides)가 장을 가리키면 그 장, 아니면 질문 장.
 * 질문 장은 질문이 근거로 든 장(evidence_slide_no)이 먼저다 — slide_nos 의 첫 비표지 장을 고르면 「질문이 가리키는 5장」 인데
 * 질문은 6장·9장 이야기인 일이 있었다 (10-01 2차). 근거 장이 없으면 표지(1장)보다 다른 장을 먼저 (10-01 1차).
 */
function bqFocusSlide() {
  const L = qa.live;
  for (let i = qa.turns.length - 1; i >= 0; i -= 1) {
    const t = qa.turns[i];
    if (t.who === 'ai' && (t.kind === 'question' || t.kind === 'claim') && !bqIsFollowUp(t)) break;
    if (t.kind === 'react' && (t.groundSlides || []).length) return { no: Number(t.groundSlides[0]), why: '판정이 가리키는' };
    if (t.kind === 'hint' && (t.slides || []).length) return { no: Number(t.slides[0]), why: '힌트가 가리키는' };
  }
  const q = L && L.questions && L.questions[Math.min(L.qi, L.questions.length - 1)];
  const nos = ((q && q.slide_nos) || []).map(Number).filter(Boolean);
  const pick = Number(q && q.evidence_slide_no) || nos.find((n) => n !== 1) || nos[0] || 1;
  return { no: pick, why: '질문이 가리키는' };
}
