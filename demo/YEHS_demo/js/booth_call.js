/**
 * 부스 화상 Q&A 무대 — 주소창 /booth/call (→ index.html#/booth/call) 의 질문 화면.
 *
 * 2026-10-01 사용자: "부스를 위해서 만드는 전용 QA 페이지 … 왼쪽 하단에는 삐약이가 나와서 QA 를 진행하고
 * (교수님이건, 어떤 역할이던 위임을 받게 됨) 나는 정면에 그대로 나와서 그 질문에 대한 답을 이어서 하게 돼.
 * overlay 로 내 대화와 삐약이 대화가 화면에 오버레이되어 애플 liquid glass 처럼 은은하게."
 *
 * 시작 · 발표 고르기(+ 역할 고르기) · 훑어보기 · 마무리는 booth_qa.js 가 그대로 그린다. 이 파일은 #/qa 의 무대 한 장만
 * 다른 배치로 놓는다 — 내 얼굴(웹캠)이 화면을 채우고, 왼쪽 아래 삐약이가 고른 역할의 이름표를 달고 묻고,
 * 질문·내 답·판정이 삐약이 위로 글라스 말풍선이 되어 쌓인다. 지금 짚는 장은 오른쪽 위 작은 창.
 *
 * 로직은 새로 만들지 않는다. 질문·판정·힌트·되묻기는 qa_live.js 의 같은 id(#stream · .qa-live-input · #liveAnswer …),
 * 카메라·판단(구도 안내 · 정면 비율)은 booth_qa.js 의 bqCam* · bqOnCv 가 같은 id(#bqHint · #bqGazeNow · #bqCamToggle)를 찾는다.
 * 얼굴 가운데를 가리지 않는다(9/22 회의안 1-2) — 대화는 왼쪽 기둥, 답 칸은 아래 띠, 자료는 오른쪽 위.
 *
 * 10-01 점검 반영: 화면 읽기는 새 말을 빠짐없이 한 번씩(판정 칩·점수 포함), 오류는 role=alert ·
 * 판정 기다림·마이크 상태를 삐약이 줄이 말한다 · 아직(grumpy) 표정은 얼굴 정면 화면에서 사람을 평가하는 듯해 curious 로.
 */

/** 삐약이가 새 말을 꺼낸 뒤 「말하는 중」 으로 보이는 시간 */
const BC_SPEAK_MS = 2600;
/** 판정을 이만큼 기다리면 삐약이 줄이 「한 번 더 보고 있어요」 로 바뀐다 */
const BC_SLOW_JUDGE_MS = 6000;
/** 질문을 맡는 병아리 — /booth/qa 무대의 쏠라 심사위원과 같은 그림. 화상판에서는 이름을 「삐약이」 하나로 부른다 */
const BC_HOST_BIRD = 'solar';
/** 화면 읽기가 읽을 줄 — 삐약이 쪽 말 · 안내 · 오류 · 질문 마무리 카드 */
const BC_SAY_ROWS = ':scope > .msg.ai:not(.thinking), :scope > .qa-flag, :scope > .qa-note-line, :scope > .qa-done';

const bc = { sayCount: 0, rowCount: 0, speakTimer: 0, thinkSince: 0, slowTimer: 0, dockH: 0, mounted: false, syncAt: 0, syncN: 0, syncLater: 0 };

function bcRole() {
  return qa.aud || BOOTH_ROLES[0].aud;
}

function bcCounterText() {
  const L = qa.live;
  const n = L.questions.length;
  if (L.awaitEnd || L.qi >= n) return `질문 ${n}개를 마쳤어요`;
  return `질문 ${L.qi + 1} / ${n}`;
}

/** 마이크가 켜져 있나 (qa_live.js liveMic) */
function bcMicOn() {
  return typeof liveMic !== 'undefined' && !!liveMic;
}

/** 마지막 줄이 판정 실패 표식인가 — 그러면 삐약이가 다시 보내라고 말한다 */
function bcLastFailed(stream) {
  const last = stream.lastElementChild;
  return !!last && last.matches('.qa-flag.lost');
}

/** 삐약이 이름표 아래 한 줄 — 지금 무슨 일이 일어나는지. 판정 중 · 기다림 · 실패 · 마이크를 따로 말한다 */
function bcSayText(stream, thinking) {
  if (thinking) {
    const wait = (document.querySelector('#coachThinking .thinking-text') || {}).textContent || '';
    if (/요청이 몰려|AI 서버가|한 번 더 보내/.test(wait)) return wait;      // 기다렸다 다시 보내는 중 — 남은 초를 그대로
    if (bc.thinkSince && Date.now() - bc.thinkSince >= BC_SLOW_JUDGE_MS) return '자료를 한 번 더 보고 있어요. 조금만 기다려요';
    return '답을 자료와 맞춰 보고 있어요';
  }
  if (bcMicOn()) return '듣고 있어요 · 다 말했으면 「그만 말하기」를 눌러요';
  if (qa.live.awaitEnd) return '오늘 질문은 여기까지예요';
  if (bcLastFailed(stream)) return '판정을 못 받았어요. 답은 그대로 두었으니 다시 보내요';
  return '답을 기다리고 있어요';
}

function renderQaLiveBoothCall() {
  const role = bcRole();
  bqMount('qa', `
    <div class="bc-call">
      <div class="bc-self" data-bq-cam-box data-camera="off">
        <video data-bq-cam autoplay muted playsinline></video>
        <p class="bc-self-off"><b>카메라 없이도 말로 답할 수 있어요</b><span id="bqCamNote"></span></p>
      </div>

      <p class="bc-hint bc-chip" id="bqHint" hidden></p>

      <aside class="bc-side">
        <div class="bc-side-row">
          <span class="bc-pill bc-chip" id="bqGazeNow" hidden></span>
          <button type="button" class="bc-pill bc-chip bc-btn" id="bqCamToggle">카메라 끄기</button>
        </div>
        <figure class="bq-slide bc-slide bc-glass" id="bqSlide"></figure>
        <p class="bc-privacy bc-chip">영상은 이 화면에만 보여요 · 저장하지 않아요</p>
      </aside>

      <section class="bc-talk" aria-label="삐약이와 주고받은 말">
        <div class="qa-stream bc-stream" id="stream" tabindex="0"
          aria-label="삐약이와 주고받은 말 · 위아래 화살표로 지난 말을 볼 수 있어요">${qa.turns.map(streamRow).join('')}</div>
      </section>

      <div class="bc-host bc-glass" id="bcHost">
        <span class="bc-host-bird">${bqBird(BC_HOST_BIRD)}</span>
        <span class="bc-host-text">
          <b>${escapeHtml(role)}</b>
          <small>역할을 맡은 삐약이</small>
          <em id="bcCount"></em>
          <span id="bqJudgeSay" class="bc-say"></span>
        </span>
      </div>
      <div id="bqProg" class="bc-prog"></div>

      <div class="card qa-live-input bq-answer bc-dock bc-glass">${liveInputHtml()}</div>
      <p class="bq-sr" id="bcLive" role="status" aria-atomic="true"></p>
      <p class="bq-sr" id="bcAlert" role="alert"></p>
    </div>`);
  bc.sayCount = 0;
  bc.rowCount = 0;
  bc.thinkSince = 0;
  bc.dockH = 0;
  bc.mounted = false;
  $('#bqCamToggle').addEventListener('click', bqCamToggle);
  if (window.BoothCV && !BoothCV.readGaze()) BoothCV.startGaze();
  bcSync();
  const stream = $('#stream');
  if (stream) {
    // 판정 기다림 글(남은 초)이 바뀌는 것도 따라가야 해서 글자 변화까지 본다.
    // bcSync 가 스트림 안에 쓴 것(머리말 줄이기 · 기다림 글)으로 다시 깨지 않게 끝에 쌓인 기록을 버린다
    bq.observer = new MutationObserver(() => {
      bcSync();
      if (bq.observer) bq.observer.takeRecords();
    });
    bq.observer.observe(stream, { childList: true, subtree: true, characterData: true });
  }
  paintDeckThumbs(document.getElementById('bqStage'));
  bqWatchSlide();
  bqCamPaint();
  scrollDown();
  wireLiveInput();
  const card = document.querySelector('#bqStage .bq-answer');
  if (card) {
    // 입력 카드는 판정·힌트 때마다 통째로 바뀌고(카드 바로 아래 자식), 마이크 버튼은 aria-label 로 상태를 바꾼다 — 그 둘만 따라간다.
    // 카드 속 글자(끝 카드의 「12초 뒤 결과를 보여 줘요」 초읽기 등)에는 깨지 않는다 — 그 글을 쓰는 게 이 감시가 부르는
    // bqArmAutoEnd 라서, 예전(subtree 전부)에는 마지막 질문을 닫는 순간 서로를 끝없이 불러 탭이 멈췄다 (10-01 점검 P0)
    bq.inputObserver = new MutationObserver((records) => {
      if (!records.some((r) => r.type === 'attributes' || r.target === card)) return;
      bqRelabelInput();
      bcSync();
      if (bq.inputObserver) bq.inputObserver.takeRecords();   // 방금 우리가 쓴 것으로 다시 깨지 않게
    });
    bq.inputObserver.observe(card, { childList: true, subtree: true, attributes: true, attributeFilter: ['aria-label'] });
  }
  bqRelabelInput();
  bcWatchDock();
  // 들어오자마자 지금 질문을 한 번 읽는다 (그 뒤로는 새로 붙는 말만)
  setTimeout(() => {
    const q = document.querySelector('#stream .msg.is-now .msg-q');
    if (q && qa.live) bcAnnounce(`${bcCounterText()}. ${q.textContent.trim()}`);
  }, 400);
}

/**
 * 삐약이 · 진행 칩은 답 칸 바로 위에 선다. 답 칸 높이는 판정·힌트·끝 카드마다 바뀌므로 잰 값을 쓴다 (바뀔 때만 — 상속되는
 * 변수라 쓸 때마다 층 전체 스타일을 다시 계산한다). 창 크기가 바뀌면 지금 질문이 가려지지 않게 다시 맨 아래로 붙인다.
 */
function bcWatchDock() {
  const layer = document.getElementById('bqStage');
  const dock = layer && layer.querySelector('.bc-dock');
  const stream = document.getElementById('stream');
  if (!dock || !window.ResizeObserver) return;
  bq.dockWatch = new ResizeObserver((entries) => {
    const h = Math.round(dock.getBoundingClientRect().height);
    if (h !== bc.dockH) { bc.dockH = h; layer.style.setProperty('--bc-dock-h', `${h}px`); }
    if (stream && entries.some((e) => e.target === stream)) bcStickBottom(stream);
  });
  bq.dockWatch.observe(dock);
  if (stream) bq.dockWatch.observe(stream);
}

/** 지금 답할 질문(되묻기 포함) 말풍선 — 맨 마지막 질문 줄. 다 마쳤으면 없다 */
function bcNowQuestionRow(stream) {
  if (qa.live.awaitEnd || qa.live.qi >= qa.live.questions.length) return null;
  const rows = stream.querySelectorAll(':scope > .msg.ai.q');
  return rows.length ? rows[rows.length - 1] : null;
}

/**
 * 고리 차단기 — 1초에 BC_SYNC_MAX 번을 넘게 불리면 그 1초는 더 돌지 않고, 끝에 한 번만 다시 맞춘다.
 * 감시(MutationObserver)와 그 감시가 부르는 쓰기가 서로를 다시 깨우는 고리가 또 생겨도 탭이 멈추지 않게 (10-01 P0 방어).
 * 평소에는 1초에 몇 번(새 줄 · 판정 기다림 초읽기)이라 닿지 않는다.
 */
const BC_SYNC_MAX = 60;
function bcSyncAllowed() {
  const now = Date.now();
  if (now - bc.syncAt >= 1000) { bc.syncAt = now; bc.syncN = 0; }
  bc.syncN += 1;
  if (bc.syncN <= BC_SYNC_MAX) return true;
  if (bc.syncN === BC_SYNC_MAX + 1) {
    console.warn('[chuckchuck] booth call: 화면 맞추기가 1초에 너무 자주 불려 잠시 쉬어요 (감시 고리 의심)');
    clearTimeout(bc.syncLater);
    bc.syncLater = setTimeout(() => { bc.syncAt = 0; bcSync(); }, 1000);
  }
  return false;
}

/** 스트림이 자랄 때마다 — 번호 · 진행 칩 · 자료 장 · 삐약이 표정과 줄 · 지금 질문 강조 · 화면 읽기를 맞춘다 */
function bcSync() {
  const stream = document.getElementById('stream');
  if (!stream || !qa.live) return;
  if (!bcSyncAllowed()) return;
  const thinking = document.getElementById('coachThinking');

  bqSet(document.getElementById('bcCount'), 'textContent', bcCounterText());
  bqSyncProg();
  bqSyncSlide();
  bqMoveLeadNote();
  bqArmAutoEnd();

  const now = bcNowQuestionRow(stream);
  stream.querySelectorAll(':scope > .is-now').forEach((el) => { if (el !== now) el.classList.remove('is-now'); });
  if (now) {
    now.classList.add('is-now');
    bcTrimMeta(now);
  }
  bcLinkAnswer(now);
  bcDimPast(stream);
  bcThinking(thinking);

  const host = document.getElementById('bcHost');
  if (host) {
    const mic = bcMicOn() ? 'on' : '';
    if ((host.dataset.mic || '') !== mic) host.dataset.mic = mic;
    const bird = host.querySelector('.bq-bird');
    // 「아직」 의 언짢은 얼굴은 얼굴이 정면에 나온 화면에서 사람을 평가하는 듯 읽힌다 — 화상판은 갸웃까지만
    let mood = thinking ? 'curious' : bqJudgeMood();
    if (mood === 'grumpy') mood = 'curious';
    if (bird && (bird.dataset.mood || '') !== mood) bird.dataset.mood = mood;
  }
  bqSet(document.getElementById('bqJudgeSay'), 'textContent', bcSayText(stream, !!thinking));

  const rows = stream.children.length;
  if (rows !== bc.rowCount) {
    bc.rowCount = rows;
    bcStickBottom(stream);
  }
  bcAnnounceNew(stream);
}

/** 「예상 질문 1/3 · 꼭 넘어야 해요」 의 앞머리는 이름표의 「질문 1 / 3」 과 겹친다 — 화면 글만 줄인다 (턴 데이터는 그대로) */
function bcTrimMeta(row) {
  const meta = row.querySelector('.msg-meta');
  if (!meta || meta.dataset.trimmed) return;
  meta.dataset.trimmed = '1';
  const t = meta.textContent.replace(/^예상 질문 \d+\/\d+\s*·?\s*/, '').trim();
  if (t) meta.textContent = t;
  else meta.remove();
}

/** 답 칸이 지금 질문을 설명으로 갖는다 — 초점이 답 칸에 가면 질문이 같이 읽힌다 */
function bcLinkAnswer(now) {
  const q = now && now.querySelector('.msg-q');
  document.querySelectorAll('#stream #bcNowQ').forEach((el) => { if (el !== q) el.removeAttribute('id'); });
  if (q && q.id !== 'bcNowQ') q.id = 'bcNowQ';
  const ta = document.getElementById('liveAnswer');
  if (!ta) return;
  if (q) { if (ta.getAttribute('aria-describedby') !== 'bcNowQ') ta.setAttribute('aria-describedby', 'bcNowQ'); }
  else if (ta.hasAttribute('aria-describedby')) ta.removeAttribute('aria-describedby');
}

/**
 * 판정 기다림 표시 — 말풍선의 「듣고 있어요」 는 판정 중에는 사실과 다르다(마이크는 꺼져 있다) → 「자료와 맞춰 보고 있어요」.
 * 그 칸이 남은 초를 셀 때마다 읽히지 않게 aria-live 를 끄고, 6초가 지나면 삐약이 줄을 한 번 바꾼다.
 */
function bcThinking(el) {
  if (!el) {
    bc.thinkSince = 0;
    clearTimeout(bc.slowTimer);
    return;
  }
  if (el.getAttribute('aria-live') !== 'off') el.setAttribute('aria-live', 'off');
  const span = el.querySelector('.thinking-text');
  if (span && span.textContent === '듣고 있어요') span.textContent = '답을 자료와 맞춰 보고 있어요';
  if (!bc.thinkSince) {
    bc.thinkSince = Date.now();
    bcAnnounce('답을 자료와 맞춰 보고 있어요');
    clearTimeout(bc.slowTimer);
    bc.slowTimer = setTimeout(() => { if (document.getElementById('coachThinking')) bcSync(); }, BC_SLOW_JUDGE_MS + 50);
  }
}

/** 지난 질문까지의 말은 옅게 — 지금 질문과 그 뒤의 말(내 답 · 판정 · 힌트)만 또렷하다 */
function bcDimPast(stream) {
  const kids = [...stream.children];
  let lastQ = -1;
  kids.forEach((el, i) => { if (el.matches('.msg.ai.q')) lastQ = i; });
  kids.forEach((el, i) => {
    const past = i < lastQ;
    if (el.classList.contains('is-past') !== past) el.classList.toggle('is-past', past);
  });
}

/** 새 말이 붙으면 맨 아래(삐약이 바로 위)로. 장 그림이 늦게 그려져 높이가 바뀌므로 한 번 더 내린다 */
function bcStickBottom(stream) {
  const down = () => { if (stream.isConnected) stream.scrollTop = stream.scrollHeight; };
  requestAnimationFrame(down);
  setTimeout(down, 450);
}

/* ─── 화면 읽기 · 삐약이가 말하는 모습 ─────────────────────────────────────── */

/** 같은 문장이 다시 와도 읽히게 비웠다가 넣는다 */
function bcAnnounce(text, { alert = false } = {}) {
  const el = document.getElementById(alert ? 'bcAlert' : 'bcLive');
  if (!el || !text) return;
  el.textContent = '';
  requestAnimationFrame(() => { el.textContent = text; });
}

/** 한 줄을 읽을 말로 — 판정 칩 · 점수까지. 이 줄들은 한꺼번에 붙어서 마지막 줄만 읽으면 판정이 빠진다 */
function bcRowSpeech(el) {
  const chip = el.querySelector('.react-head .chip, .qd-head .chip');
  const score = el.querySelector('.msg-score');
  const body = el.querySelector('.msg-q') || el.querySelector('.msg-bubble > p') || el.querySelector('.qd-head b') || el.querySelector('.msg-bubble') || el;
  const parts = [];
  if (chip) parts.push(chip.textContent.trim());
  if (score) parts.push(`완성도 ${score.textContent.trim()}`);
  parts.push(body.textContent.replace(/\s+/g, ' ').trim());
  return parts.filter(Boolean).join(' · ');
}

/** 새로 붙은 줄을 모두 한 번씩 — 처음 그릴 때 이미 있던 줄은 세기만 한다 */
function bcAnnounceNew(stream) {
  const rows = [...stream.querySelectorAll(BC_SAY_ROWS)];
  if (!bc.mounted) { bc.mounted = true; bc.sayCount = rows.length; return; }
  if (rows.length <= bc.sayCount) { bc.sayCount = rows.length; return; }
  const fresh = rows.slice(bc.sayCount);
  bc.sayCount = rows.length;
  const lost = fresh.filter((el) => el.matches('.qa-flag.lost'));
  const said = fresh.filter((el) => !el.matches('.qa-flag.lost'));
  if (said.length) bcAnnounce(said.map(bcRowSpeech).join(' '));
  if (lost.length) bcAnnounce(lost.map((el) => el.textContent.trim()).join(' '), { alert: true });
  if (fresh.some((el) => el.matches('.msg.ai'))) bcSpeak();
}

/** 삐약이 쪽 새 말 — 소리가 나는 것처럼 들썩이지 않고, 테두리만 잠깐 빛난다 */
function bcSpeak() {
  const host = document.getElementById('bcHost');
  if (!host) return;
  host.dataset.speaking = '1';
  clearTimeout(bc.speakTimer);
  bc.speakTimer = setTimeout(() => { if (host.isConnected) host.dataset.speaking = ''; }, BC_SPEAK_MS);
}
