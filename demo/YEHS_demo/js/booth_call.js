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
const BC_SAY_ROWS = [':scope > .msg.ai:not(.thinking)', ':scope > .qa-flag', ':scope > .qa-note-line', ':scope > .qa-done']
  .map((sel) => `${sel}:not(.bc-wait):not(.bc-merged)`).join(', ');

const bc = {
  sayCount: 0, rowCount: 0, speakTimer: 0, thinkSince: 0, slowTimer: 0, dockH: 0, mounted: false,
  syncAt: 0, syncN: 0, syncLater: 0,
  mcQi: -1, mc: '', mcUntil: 0, mcTimer: 0,   // 삐약이 진행 멘트 (bcMcSync)
  hostH: 0, progH: 0, draft: '',
  autoMicKey: '', autoOffKey: '', sendOffKey: '', sendAt: 0,   // 자동 받아쓰기 · 자동 보내기 (bcAutoTick)
  q: [], qTimer: 0, qL: null, paceReady: false, lastAiAt: 0,     // 삐약이 말풍선 차례로 띄우기 (bcPace)
};

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

/** 실패 표식인가 — 빨간 ✕ 줄(.qa-flag.lost)은 「답을 펼쳐 볼게요」·「답만 보고 넘어갔어요」 같은 진행 알림도 쓴다. 판정을 못 받은 줄만 */
function bcIsFailRow(el) {
  return !!el && el.matches('.qa-flag.lost') && /판정/.test(el.textContent) && /못|실패/.test(el.textContent);
}

/** 마지막 줄이 판정 실패 표식인가 — 그러면 삐약이가 다시 보내라고 말한다 */
function bcLastFailed(stream) {
  return bcIsFailRow(stream.lastElementChild);
}

/** 삐약이 진행 멘트를 보여 주는 시간 — 들어올 때 인사 · 질문이 넘어갈 때 한 줄 (LLM 없이 정해 둔 말) */
const BC_MC_MS = 6500;

/** 질문 번호가 바뀌면 진행 멘트 한 줄. 처음 들어올 때는 인사 (새로고침으로 질문 중간에 다시 그리면 안 한다) */
function bcMcLine() {
  const L = qa.live;
  const n = L.questions.length;
  if (L.awaitEnd || L.qi >= n) return '';
  if (L.qi === 0) {
    if (L.turn || (L.results || []).length || (L.turns || []).length) return '';
    const role = bcRole();
    return `반가워요! 오늘은 제가 ${role}${josa(role, '이에요', '예요')}. 질문 ${n}개, 말로 편하게 답해요`;
  }
  if (L.qi === n - 1) return '좋아요, 마지막 질문이에요. 이것만 답하면 끝나요';
  return `좋아요, ${L.qi + 1}번째 질문으로 넘어갈게요`;
}

function bcMcSync() {
  const qi = qa.live.qi;
  if (qi === bc.mcQi) return;
  // 질문이 바뀌면 앞 질문에 쓰다 만 글을 새 답 칸에 들고 오지 않는다 (사냥 2 #1 — 카드를 갈아 끼울 때 쳐 둔 글을 옮겨 심는다)
  if (bc.mcQi >= 0 && !qa.live.busy) {
    const ta = document.getElementById('liveAnswer');
    if (ta && ta.value) ta.value = '';
  }
  bc.mcQi = qi;
  const line = bcMcLine();
  bc.mc = line;
  bc.mcUntil = line ? Date.now() + BC_MC_MS : 0;
  clearTimeout(bc.mcTimer);
  if (line) {
    bcSpeak();
    bc.mcTimer = setTimeout(() => { if (document.getElementById('bcHost')) bcSync(); }, BC_MC_MS + 60);
  }
}

/** 삐약이 이름표 아래 한 줄 — 지금 무슨 일이 일어나는지. 판정 중 · 기다림 · 실패 · 마이크를 따로 말한다 */
function bcSayText(stream, thinking) {
  if (thinking) {
    const wait = (document.querySelector('#coachThinking .thinking-text') || {}).textContent || '';
    if (/요청이 몰려|AI 서버가|한 번 더 보내/.test(wait)) return wait;      // 기다렸다 다시 보내는 중 — 남은 초를 그대로
    if (bc.thinkSince && Date.now() - bc.thinkSince >= BC_SLOW_JUDGE_MS) return '자료를 한 번 더 보고 있어요. 조금만 기다려요';
    return '답을 자료와 맞춰 보고 있어요';
  }
  // 들어올 때 인사 · 질문이 넘어갈 때 한 줄은 자동으로 켜진 마이크보다 먼저 (듣는 중이라는 건 내 쪽 말풍선이 말한다)
  if (bc.mc && Date.now() < bc.mcUntil && !bc.sendAt && !String(((document.getElementById('liveAnswer') || {}).value) || '').trim()) return bc.mc;
  if (bcMicOn()) {
    // 버튼 이름과 같은 말로 (사냥 2 #10 — 녹음 길에서 「그만 말하기」 는 없는 버튼이었다)
    if (liveMic && !liveMic.dictation) return '녹음 중이에요 · 다 말했으면 「녹음 멈추고 받아쓰기」를 눌러요';
    return bc.sendAt ? '곧 보내요 · 더 말하면 이어서 받아요' : '듣고 있어요 · 다 말하고 잠깐 멈추면 알아서 보내요';
  }
  if (qa.live.awaitEnd) return '오늘 질문은 여기까지예요';
  if (bcLastFailed(stream)) return '판정을 못 받았어요. 답은 그대로 두었으니 다시 보내요';
  if (bc.mc && Date.now() < bc.mcUntil) return bc.mc;
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
        <div class="bc-typing" id="bcTyping" hidden aria-hidden="true"><span><b></b><b></b><b></b></span></div>
        <div class="bc-draft" id="bcDraft" hidden><span class="bc-draft-tag" aria-hidden="true"></span><p aria-hidden="true"></p>
          <span class="bc-draft-send" hidden><span></span><button type="button" id="bcSendCancel">보내지 않기</button></span></div>
      </section>

      <div class="bc-host" id="bcHost">
        <span class="bc-host-bird">${bqBird(BC_HOST_BIRD)}</span>
        <span class="bc-host-text">
          <b>${escapeHtml(role)}<small> 역할 삐약이</small></b>
          <em id="bcCount"></em>
          <span id="bqJudgeSay" class="bc-say"></span>
        </span>
      </div>
      <section id="bqProg" class="bc-prog" aria-label="자료에서 뽑은 질문 3개"></section>

      <div class="card qa-live-input bq-answer bc-dock bc-glass">${liveInputHtml()}</div>
      <p class="bq-sr" id="bcLive" role="status" aria-atomic="true"></p>
      <p class="bq-sr" id="bcAlert" role="alert"></p>
    </div>`);
  bc.sayCount = 0;
  bc.rowCount = 0;
  bc.thinkSince = 0;
  bc.dockH = 0;
  bc.hostH = 0;
  bc.mounted = false;
  bc.mcQi = -1;
  bc.mc = '';
  bc.autoMicKey = '';
  bc.autoOffKey = '';
  bc.sendOffKey = '';
  bc.sendAt = 0;
  bcPaceDrop();
  bc.paceReady = false;
  bc.qL = qa.live;
  bcPaceWire();
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
  const host = layer.querySelector('.bc-host');
  const prog = layer.querySelector('.bc-prog');
  bq.dockWatch = new ResizeObserver((entries) => {
    const h = Math.round(dock.getBoundingClientRect().height);
    if (h !== bc.dockH) { bc.dockH = h; layer.style.setProperty('--bc-dock-h', `${h}px`); }
    // 삐약이 카드도 진행 멘트·큰 글자로 두 줄이 되면 높아진다 — 대화 기둥 밑동을 그 위로 (10-02 맥 1512×860: 지금 질문이 카드 뒤로 숨었다)
    const hh = host ? Math.round(host.getBoundingClientRect().height) : 0;
    if (hh && hh !== bc.hostH) { bc.hostH = hh; layer.style.setProperty('--bc-host-h', `${hh}px`); }
    // 질문 목록(진행)도 이름 · 장 · 상태 줄이라 높이가 바뀐다 — 자료 창이 그 위에서 멈추게
    const ph = prog ? Math.round(prog.getBoundingClientRect().height) : 0;
    if (ph !== bc.progH) { bc.progH = ph; layer.style.setProperty('--bc-prog-h', `${ph}px`); }
    if (stream && entries.some((e) => e.target === stream)) bcStickBottom(stream);
  });
  bq.dockWatch.observe(dock);
  if (host) bq.dockWatch.observe(host);
  if (prog) bq.dockWatch.observe(prog);
  // 받아쓰는 글은 답 칸 value 로만 들어와 감시로 못 잡는다 — 질문 화면에 있는 동안 0.25초마다 내 쪽 말풍선에 옮긴다
  bq.timers.push(setInterval(bcDraftSync, BC_DRAFT_MS));
  if (stream) bq.dockWatch.observe(stream);
}

/** 지금 답할 질문(되묻기 포함) 말풍선 — 맨 마지막 질문 줄. 다 마쳤으면 없다 */
function bcNowQuestionRow(stream) {
  if (qa.live.awaitEnd || qa.live.qi >= qa.live.questions.length) return null;
  const rows = [...stream.querySelectorAll(':scope > .msg.ai.q')].filter(bcShown);
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
  bcMcSync();
  bcSyncProg();
  bqSyncSlide();
  bqMoveLeadNote();
  bqArmAutoEnd();
  bcMerge(stream);
  bcPace(stream);

  const now = bcNowQuestionRow(stream);
  stream.querySelectorAll(':scope > .is-now').forEach((el) => { if (el !== now) el.classList.remove('is-now'); });
  if (now) {
    now.classList.add('is-now');
    bcTrimMeta(now);
  }
  bcLinkAnswer(now);
  bcDimPast(stream);
  bcMarkSides(stream);
  bcClipGrounds(stream);
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

/** 이 질문 줄이 질문의 첫 물음(머리말 「예상 질문 n/N」)인가 — 되묻기·「이제 내 말로」 와 가른다. 머리말을 줄이기 전에 한 번 적어 둔다 */
function bcIsLead(row) {
  if (!('lead' in row.dataset)) {
    const meta = row.querySelector('.msg-meta');
    row.dataset.lead = meta && /^예상 질문/.test(meta.textContent.trim()) ? '1' : '';
  }
  return row.dataset.lead === '1';
}

/**
 * 「예상 질문 1/3 · 꼭 넘어야 해요」 — 앞머리는 이름표의 「질문 1 / 3」 과 겹치고, 중요도(꼭 넘어야 해요 · 보통이에요 · 가벼워요)는
 * 부스 방문객에게 성적 기준처럼 읽힌다 (10-01 2차) — 둘 다 화면 글에서만 뗀다 (턴 데이터는 그대로). 남는 게 없으면 머리말 줄을 지운다.
 */
function bcTrimMeta(row) {
  const meta = row.querySelector('.msg-meta');
  bcIsLead(row);
  if (!meta || meta.dataset.trimmed) return;
  meta.dataset.trimmed = '1';
  const t = meta.textContent
    .replace(/^예상 질문 \d+\/\d+\s*·?\s*/, '')
    .replace(/^(꼭 넘어야 해요|보통이에요|가벼워요)\s*·?\s*/, '')
    .trim();
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

/**
 * 지난 질문의 말은 작고 옅게 — 지금 질문의 첫 물음부터 그 뒤(내 답 · 판정 · 되묻기 · 힌트)는 또렷하다.
 * 예전에는 마지막 질문 줄(되묻기 포함) 앞을 다 물려서, 되묻기가 붙는 순간 방금 받은 판정이 흐려졌다 (10-01 2차).
 */
function bcDimPast(stream) {
  const kids = [...stream.children].filter(bcShown);
  let lead = -1;
  kids.forEach((el, i) => { if (el.matches('.msg.ai.q') && bcIsLead(el)) lead = i; });
  kids.forEach((el, i) => {
    const past = i < lead;
    if (el.classList.contains('is-past') !== past) el.classList.toggle('is-past', past);
  });
}

/**
 * 새 말이 붙으면 맨 아래(삐약이 바로 위)로. 장 그림이 늦게 그려져 높이가 바뀌므로 한 번 더 내린다.
 * 단 방금 받은 판정 말풍선의 윗머리는 화면 안에 남긴다 — 판정 뒤에 빠진 것 · 펼친 절반 · 되묻기가 한꺼번에 붙으면 대화 칸이 낮은 폰에서
 * 판정이 위로 밀려 안 보였다 (10-01 2차). 그 뒤로 내 답이 붙었으면(다시 답하는 중) 그냥 맨 아래다.
 */
function bcStickBottom(stream) {
  const down = () => {
    if (!stream.isConnected) return;
    const max = stream.scrollHeight - stream.clientHeight;
    const keep = bcFreshVerdict(stream);
    if (!keep) { stream.scrollTop = max; return; }
    const at = (el) => el.getBoundingClientRect().top - stream.getBoundingClientRect().top + stream.scrollTop;
    // 둘 다 들어가면 맨 아래. 안 들어가면 판정 윗머리를 지키되, 지금 질문은 첫 두 줄(72px)은 꼭 보이게 — 질문이 더 먼저다
    // 지금 질문은 140px(대개 질문 전체 · 긴 되묻기면 앞 서너 줄)까지 먼저 보이게 — 72px 만 지켰더니 1440×780 에서 긴 되묻기가 절반만 보였다 (사냥 3)
    const now = stream.querySelector(':scope > .msg.is-now');
    const floor = now ? at(now) + Math.min(now.offsetHeight, 140) - stream.clientHeight : 0;
    stream.scrollTop = Math.max(0, Math.min(max, Math.max(floor, at(keep) - 6)));
  };
  requestAnimationFrame(down);
  setTimeout(down, 450);
}

/** 지금 질문에서 마지막 판정 말풍선 — 그 뒤에 내 말이 없을 때만 (= 방금 받은 판정) */
function bcFreshVerdict(stream) {
  const kids = [...stream.children].filter(bcShown);
  for (let i = kids.length - 1; i >= 0; i -= 1) {
    const el = kids[i];
    if (el.matches('.msg.me, .is-past')) return null;
    if (el.matches('.msg.ai.react')) return el;
  }
  return null;
}

/* ─── 화면 읽기 · 삐약이가 말하는 모습 ─────────────────────────────────────── */

/** 같은 문장이 다시 와도 읽히게 비웠다가 넣는다 */
function bcAnnounce(text, { alert = false } = {}) {
  const el = document.getElementById(alert ? 'bcAlert' : 'bcLive');
  if (!el || !text) return;
  el.textContent = '';
  requestAnimationFrame(() => { el.textContent = text; });
}

/** 한 줄을 읽을 말로 — 판정 칩까지. 이 줄들은 한꺼번에 붙어서 마지막 줄만 읽으면 판정이 빠진다. 점수는 화면에서 뺀 것과 같게 안 읽는다 */
function bcRowSpeech(el) {
  const chip = el.querySelector('.react-head .chip, .qd-head .chip');
  const body = el.querySelector('.msg-q') || el.querySelector('.msg-bubble > p') || el.querySelector('.qd-head b') || el.querySelector('.msg-bubble') || el;
  const parts = [];
  if (chip) parts.push(chip.textContent.trim());
  parts.push(body.textContent.replace(/\s+/g, ' ').trim());
  // 판정 말풍선에 모은 「아직 안 나온 것」 도 같이 (bcMerge) — 따로 읽던 말풍선이 없어졌다
  const miss = [...el.querySelectorAll('.bc-miss .chip')].map((c) => c.textContent.trim()).filter(Boolean);
  if (miss.length) parts.push(`아직 안 나온 것: ${miss.join(', ')}`);
  if (el.querySelector('.bc-gist')) parts.push('완성 답은 「완성 답 보기」를 누르면 펼쳐져요');
  return parts.filter(Boolean).join(' · ');
}

/** 새로 붙은 줄을 모두 한 번씩 — 처음 그릴 때 이미 있던 줄은 세기만 한다 */
function bcAnnounceNew(stream) {
  const rows = [...stream.querySelectorAll(BC_SAY_ROWS)];
  if (!bc.mounted) { bc.mounted = true; bc.sayCount = rows.length; return; }
  if (rows.length <= bc.sayCount) { bc.sayCount = rows.length; return; }
  const fresh = rows.slice(bc.sayCount);
  bc.sayCount = rows.length;
  // 경고(role=alert)는 판정을 못 받은 줄만 — 「답을 펼쳐 볼게요」 같은 진행 알림은 보통 읽기로
  const lost = fresh.filter(bcIsFailRow);
  const said = fresh.filter((el) => !bcIsFailRow(el));
  // 판정·다음 질문이 새로 왔으면 지난 실패 경고는 끝난 일이다 — 남겨 두면 화면 읽기 사용자가 아직 실패 중인 줄 안다 (10-01 2차)
  if (!lost.length && said.some((el) => el.matches('.msg.ai, .qa-done'))) {
    const alert = document.getElementById('bcAlert');
    if (alert && alert.textContent) alert.textContent = '';
  }
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

/* ─── 10-02 대화처럼 — 말풍선 편 · 꼬리 · 받아쓰는 말 · 질문 목록 ─────────────────────────── */

/** 받아쓰는 말을 내 쪽 말풍선에 옮기는 간격 */
const BC_DRAFT_MS = 250;

/** 줄의 편 — 삐약이(ai) · 나(me) · 안내(sys). 질문 마무리 카드도 삐약이 쪽 정리다 */
function bcSide(el) {
  if (el.matches('.msg.me')) return 'me';
  if (el.matches('.msg.ai, .qa-done')) return 'ai';
  return 'sys';
}

/**
 * 카카오톡처럼 — 같은 편이 이어 말하면 꼬리는 마지막 말풍선에만. 판 색은 편이 정한다(css data-side).
 * 지지난 질문까지의 말은 「오래된 말」 로 더 옅게 (위로 밀리며 흐려진다).
 */
function bcMarkSides(stream) {
  const kids = [...stream.children].filter(bcShown);
  const leads = [];
  kids.forEach((el, i) => { if (el.matches('.msg.ai.q') && bcIsLead(el)) leads.push(i); });
  const oldBefore = leads.length >= 2 ? leads[leads.length - 2] : -1;
  kids.forEach((el, i) => {
    const side = bcSide(el);
    if (el.dataset.side !== side) el.dataset.side = side;
    const next = kids[i + 1];
    const tail = !next || bcSide(next) !== side || el.matches('#coachThinking') ? '1' : '';
    if ((el.dataset.tail || '') !== tail) el.dataset.tail = tail;
    const old = i < oldBefore;
    if (el.classList.contains('is-old') !== old) el.classList.toggle('is-old', old);
  });
}

/** 받아쓰는 중이거나 쳐 둔 글 — 내 쪽 말풍선에 실시간으로 차오른다. 보낸 답은 스트림의 내 말풍선이 된다 */
function bcDraftSync() {
  const box = document.getElementById('bcDraft');
  if (!box || !qa.live) return;
  bcAutoTick();
  const stream = document.getElementById('stream');
  if (stream) bqSet(document.getElementById('bqJudgeSay'), 'textContent', bcSayText(stream, !!document.getElementById('coachThinking')));
  const ta = document.getElementById('liveAnswer');
  const text = ta && !ta.disabled ? ta.value.trim() : '';
  const mic = bcMicOn();
  const show = !!text || mic;
  if (box.hidden === show) box.hidden = !show;
  const tag = mic ? '듣고 있어요' : '보내기 전이에요';
  bqSet(box.querySelector('.bc-draft-tag'), 'textContent', tag);
  const shown = text || (mic ? '말하면 여기에 글자로 적혀요' : '');
  if (bc.draft !== shown) {
    bc.draft = shown;
    box.querySelector('p').textContent = shown;
    box.dataset.empty = text ? '' : '1';
  }
  if ((box.dataset.mic || '') !== (mic ? '1' : '')) box.dataset.mic = mic ? '1' : '';
}

/**
 * 오른쪽 질문 목록 — 「질문 1 · 질문 2」 만으로는 무엇을 나눈 건지 몰랐다 (10-02 사용자).
 * 머리 한 줄 + 질문마다 번호 · 주제(질문 데이터의 label) · 근거 장 · 상태. 안 연 질문은 주제와 장만(질문 글은 안 보인다),
 * 함정 여부는 드러내지 않는다. 누르는 것이 아니라 목록이다(버튼처럼 안 보이게).
 */
function bcProgHtml() {
  const L = qa.live;
  const rows = L.questions.map((q, i) => {
    const r = (L.results || [])[i];
    const row = r && typeof liveResultRow === 'function' ? liveResultRow(r) : null;
    const now = !row && i === L.qi && !L.awaitEnd;
    const state = row ? row.chip : (now ? '지금 묻는 중' : '아직');
    const cls = row ? row.cls : (now ? 'now' : 'wait');
    const slide = Number(q.evidence_slide_no) || ((q.slide_nos || []).map(Number).find((n) => n > 1)) || 0;
    const topic = String(q.label || '').trim() || `질문 ${i + 1}`;
    // 판정 색은 data-st 로 — 클래스 .st-ok 를 달면 app.css 의 판정 칩(밝은 면)이 줄 전체에 씌워진다
    return `<li data-st="${cls}"${now ? ' aria-current="step"' : ''}>
      <span class="bc-prog-no">${i + 1}</span>
      <span class="bc-prog-topic">${escapeHtml(topic)}${slide ? `<small> · ${slide}장</small>` : ''}</span>
      <em class="bc-prog-state">${escapeHtml(state)}</em>
    </li>`;
  }).join('');
  return `<h3 class="bc-prog-h">자료에서 뽑은 질문 ${L.questions.length}개</h3><ol class="bc-prog-list">${rows}</ol>`;
}

function bcSyncProg() {
  const prog = document.getElementById('bqProg');
  if (!prog) return;
  const next = bcProgHtml();
  if (prog.dataset.html !== next) { prog.dataset.html = next; prog.innerHTML = next; }
}

/** 근거 인용 — 머리(자료 N장 · 빠진 것)는 두고 인용 글만 감싸 세 줄로 자른다 (css .bc-q-clip). 한 번만 감싼다 */
function bcClipGrounds(stream) {
  stream.querySelectorAll('.qa-evidence.qa-ground:not([data-clip])').forEach((q) => {
    q.dataset.clip = '1';
    const head = q.querySelector(':scope > span');
    const wrap = document.createElement('span');
    wrap.className = 'bc-q-clip';
    [...q.childNodes].filter((n) => n !== head).forEach((n) => wrap.appendChild(n));
    q.appendChild(wrap);
  });
}

/* ─── 10-02 자동 받아쓰기 · 자동 보내기 (부스 화상판만) ──────────────────────────────────────────
   사용자: 「말해서 답하기」 를 안 눌러도 질문이 뜨면 바로 듣고, 말을 멈추면 알아서 「이 답변 확인하기」 를 보낸다.
   기존 받아쓰기 길(toggleLiveMic · startDictationMic)과 보내기(submitLiveAnswer)를 그대로 부른다 — 질문·판정 요청은 그대로.
   - 켜는 때: 질문(되묻기 · 다시 말하기 포함)이 떠 있고, 답 칸이 비었고, 판정 중 · 끝 카드 · 자리 비움 알림 · 처음으로 시트 · 탭 숨김이 아닐 때.
     물음(질문 번호 · 판정 횟수 · 다시 말하기)마다 한 번 — 사람이 「그만 말하기」 로 끄면 그 물음에서는 다시 안 켠다
   - 보내는 때: 확정된 글이 있고 확정 전 조각이 없고 마지막 글 뒤 2.2초 조용하면 3초 초읽기(「곧 보내요 · 더 말하면 이어서 받아요」 + 「보내지 않기」),
     더 말하면 초읽기를 접고, 타이핑하면 그 물음에서는 자동 보내기를 멈춘다(손으로 고쳐 보내게)
   - 실시간 받아쓰기가 없는 브라우저(사파리 등) · 마이크 거부 · 망 오류(liveDictationDead)면 켜지 않는다 — 버튼 · 타이핑 그대로 */
const BC_AUTO_SILENCE_MS = 2200;
const BC_AUTO_SEND_MS = 3000;

function bcAskKey() {
  const L = qa.live;
  return `${L.qi}|${L.turn || 0}|${L.retell ? 1 : 0}|${(L.turns || []).length}`;
}

function bcCanAutoListen() {
  const br = window.ChuckchuckBridge;
  return typeof liveDictationDead !== 'undefined' && !liveDictationDead && window.isSecureContext !== false
    && !!br && typeof br.hasLiveDictation === 'function' && br.hasLiveDictation();
}

function bcAutoTick() {
  const L = qa.live;
  if (!L || bq.screen !== 'qa' || bq.variant !== 'call') return;
  const key = bcAskKey();
  const micOn = bcMicOn();
  const hold = L.awaitEnd || (typeof bqOps !== 'undefined' && bqOps.warnTimer) || !!document.getElementById('bqSheet') || document.hidden;
  if (micOn && hold) {
    // 끝 카드 · 자리 비움 · 시트 · 탭 숨김 — 듣지 않는다
    bcAutoCancelSend();
    if (typeof dropLiveMic === 'function') dropLiveMic();
    bc.autoMicKey = '';
    return;
  }
  const pending = typeof liveMicPending !== 'undefined' && liveMicPending;
  // 내가 켠 마이크가 (보내기 · 질문 바뀜이 아니라) 꺼졌으면 사람이 끈 것 — 이 물음에서는 다시 안 켠다
  if (bc.autoMicKey && bc.autoMicKey === key && !micOn && !pending && !L.busy) { bc.autoOffKey = key; bc.autoMicKey = ''; }
  const ta = document.getElementById('liveAnswer');
  if (ta && !ta.dataset.bcAuto) {
    ta.dataset.bcAuto = '1';
    ta.addEventListener('input', () => { bc.sendOffKey = bcAskKey(); bcAutoCancelSend(); });   // 손으로 고치는 중 — 자동으로 안 보낸다
  }
  // 삐약이 말풍선이 아직 차례로 뜨는 중이면 듣지 않는다 — 되묻기(다음에 답할 질문)가 나타난 뒤에 듣는다 (bcPace)
  const pacing = bc.q.length > 0;
  if (!micOn && !hold && !pacing && !L.busy && !pending && bc.autoOffKey !== key && ta && !ta.disabled && !ta.value.trim() && bcCanAutoListen()) {
    bc.autoMicKey = key;
    bc.sendOffKey = '';
    toggleLiveMic();
    return;
  }
  bcAutoSend(key, micOn, ta);
}

function bcAutoSend(key, micOn, ta) {
  const mic = micOn ? liveMic : null;
  const text = ta ? ta.value.trim() : '';
  const quiet = !!mic && mic.dictation && !!mic.lastTextAt && Date.now() - mic.lastTextAt >= BC_AUTO_SILENCE_MS
    && !String(mic.interim || '').trim() && !!String(mic.final || '').trim();
  if (!mic || bc.sendOffKey === key || qa.live.busy || bc.q.length || !text || !quiet) { bcAutoCancelSend(); return; }
  if (!bc.sendAt) {
    bc.sendAt = Date.now() + BC_AUTO_SEND_MS;
    bcAnnounce('곧 보내요. 더 말하면 이어서 받아요');
  }
  const left = Math.max(0, Math.ceil((bc.sendAt - Date.now()) / 1000));
  bcPaintSend(left);
  if (Date.now() >= bc.sendAt) {
    bcAutoCancelSend();
    submitLiveAnswer();
  }
}

function bcPaintSend(left) {
  const row = document.querySelector('#bcDraft .bc-draft-send');
  if (!row) return;
  if (row.hidden) {
    row.hidden = false;
    const btn = row.querySelector('button');
    if (btn && !btn.dataset.wired) {
      btn.dataset.wired = '1';
      btn.addEventListener('click', () => { bc.sendOffKey = bcAskKey(); bcAutoCancelSend(); });
    }
  }
  bqSet(row.querySelector('span'), 'textContent', `곧 보내요 · ${left}초 — 더 말하면 이어서 받아요`);
}

function bcAutoCancelSend() {
  bc.sendAt = 0;
  const row = document.querySelector('#bcDraft .bc-draft-send');
  if (row && !row.hidden) row.hidden = true;
}

/* ─── 10-02 판정 하나 = 말풍선 하나 · 말풍선은 차례로 ──────────────────────────────────────────────
   사용자: 답을 보내면 판정 뒤에 「절반쯤」 · 「아직 안 나온 것」 · 「이렇게 말하면 완성이에요」 · 되묻기 네 개가 한꺼번에 와다다 올라온다.
   - 판정에 딸린 조각(아직 안 나온 것 · 되묻기 도중 펼친 완성 답)은 판정 말풍선 안으로 모은다. 완성 답은 「완성 답 보기」 접힘
     (revealHalf 가 펼치는 답은 사다리 단계가 아니라 partial 판정 때 보여 주는 덤이다 — 막힘 3단 해설 답은 그대로 따로 둔다)
   - 한 번에 붙은 삐약이 말풍선은 실제 채팅처럼 하나씩 — 사이에 「입력 중」 점. 되묻기(다음에 답할 질문)는 맨 끝에, 그 뒤에 듣기 시작한다(bcAutoTick)
   - 화면을 누르거나 키를 누르면 남은 말을 바로 다 보여 준다 · 움직임 줄이기면 간격 없이
   - 화면에서만 숨기고 붙인다 — 스트림 줄 수는 그대로다(growStream 이 줄 수로 새 턴을 잇는다). 턴 데이터 · 판정 로직은 그대로 */
const BC_PACE_MIN_MS = 600;
const BC_PACE_MAX_MS = 900;

/** 화면에 보이는 줄인가 — 차례를 기다리는 줄(.bc-wait) · 판정 말풍선에 모은 줄(.bc-merged)은 아니다 */
function bcShown(el) {
  return !el.classList.contains('bc-wait') && !el.classList.contains('bc-merged');
}

function bcReducedMotion() {
  return !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
}

/**
 * 판정 말풍선 뒤에 바로 붙은 「아직 안 나온 것」 · 되묻기 도중 펼친 완성 답(gist.mid)을 그 판정 말풍선 안으로.
 * 원래 줄은 화면에서만 숨긴다(.bc-merged). 다시 그리면(새로고침) 다시 모은다.
 */
function bcMerge(stream) {
  let host = null;
  for (const el of stream.children) {
    if (el.id === 'coachThinking') continue;
    if (el.matches('.msg.ai.react')) { host = el; continue; }
    if (!host) continue;
    if (el.matches('.msg.ai.miss') || el.matches('.msg.ai.gist.mid')) {
      if (!el.classList.contains('bc-merged')) bcAbsorb(host, el);
      continue;
    }
    host = null;   // 질문 · 내 말 · 힌트 · 정리 카드 — 판정 하나가 끝났다
  }
}

function bcAbsorb(host, row) {
  const bubble = host.querySelector('.msg-bubble');
  if (!bubble) return;
  row.classList.add('bc-merged');
  const lead = bubble.querySelector(':scope > p');
  const after = (node) => {
    const anchor = bubble.querySelector(':scope > .bc-gist') || bubble.querySelector(':scope > .bc-miss') || lead;
    if (anchor) anchor.after(node); else bubble.appendChild(node);
  };
  if (row.matches('.miss')) {
    if (bubble.querySelector(':scope > .bc-miss')) return;
    const chips = row.querySelector('.miss-chips');
    const box = document.createElement('div');
    box.className = 'bc-miss';
    box.innerHTML = '<span class="bc-miss-h">아직 안 나온 것</span>';
    if (chips) box.appendChild(chips.cloneNode(true));
    // 「아직 안 나온 것」 은 판정 문장 바로 아래 — 완성 답 접힘보다 위
    if (lead) lead.after(box); else bubble.prepend(box);
    return;
  }
  if (bubble.querySelector(':scope > .bc-gist')) return;
  const text = row.querySelector('.msg-bubble > p');
  if (!text) return;
  const det = document.createElement('details');
  det.className = 'bc-gist';
  det.innerHTML = '<summary>완성 답 보기</summary>';
  const p = document.createElement('p');
  p.innerHTML = text.innerHTML;   // streamRow 가 이미 escape 한 글
  det.appendChild(p);
  // 펼치면 높이가 바뀐다 — 펼친 글이 대화 칸 아래로 숨지 않게 그 끝을 보여 준다
  det.addEventListener('toggle', () => { if (det.open) det.scrollIntoView({ block: 'nearest' }); });
  after(det);
}

/** 새로 붙은 줄을 차례로 — 처음 그릴 때 있던 줄은 그대로 다 보인다 */
function bcPace(stream) {
  const fresh = [...stream.children].filter((el) => el.id !== 'coachThinking' && !el.dataset.bcSeen);
  if (!fresh.length) return;
  fresh.forEach((el) => { el.dataset.bcSeen = '1'; });
  if (!bc.paceReady) { bc.paceReady = true; return; }
  // 다른 방문객(새 코칭)이면 앞 대기열은 버린다 — 앞 사람의 말풍선이 다음 사람 화면에 뜨지 않게 (8c3fa86 과 같은 원칙)
  if (bc.qL !== qa.live) { bcPaceDrop(); bc.qL = qa.live; }
  // 내가 새로 답했으면(다음 판정이 온다) 남은 말은 바로 다 보여 주고 새로 센다
  if (fresh.some((el) => el.matches('.msg.me'))) bcPaceFlush({ sync: false });
  if (bcReducedMotion()) { bcPaceFlush({ sync: false }); return; }
  let first = !bc.q.length && Date.now() - bc.lastAiAt >= BC_PACE_MIN_MS;
  for (const el of fresh) {
    if (el.classList.contains('bc-merged')) continue;
    const ai = bcSide(el) === 'ai';
    if (!bc.q.length && (!ai || first)) {
      if (ai) { first = false; bc.lastAiAt = Date.now(); }
      continue;   // 바로 보인다
    }
    el.classList.add('bc-wait');
    bc.q.push(el);
  }
  bcPaceQuestionLast(stream);
  if (bc.q.length && !bc.qTimer) {
    bcTyping(true);
    bc.qTimer = setTimeout(bcPaceNext, bcPaceGap());
  }
}

/**
 * 되묻기(다음에 답할 질문)는 맨 끝에 — 판정 뒤에 저절로 연 힌트가 질문 뒤에 붙으면 그 줄들을 질문 앞으로 옮긴다.
 * 자리만 바꾼다(줄 수는 그대로). 새로 그리면 턴 순서로 돌아간다
 */
function bcPaceQuestionLast(stream) {
  const qi = bc.q.findIndex((el) => el.matches('.msg.ai.q'));
  if (qi < 0 || qi === bc.q.length - 1) return;
  const ask = bc.q[qi];
  const rest = bc.q.slice(qi + 1);
  rest.forEach((el) => stream.insertBefore(el, ask));
  bc.q = bc.q.slice(0, qi).concat(rest, [ask]);
}

/** 다음 말풍선까지 — 앞 말풍선이 길면 조금 더 (0.6~0.9초) */
function bcPaceGap(prev) {
  const len = prev ? (prev.textContent || '').length : 0;
  return Math.round(Math.min(BC_PACE_MAX_MS, BC_PACE_MIN_MS + len * 2));
}

function bcReveal(el) {
  el.classList.remove('bc-wait');
  if (bcSide(el) === 'ai') bc.lastAiAt = Date.now();
}

function bcPaceNext() {
  bc.qTimer = 0;
  const stream = document.getElementById('stream');
  if (!stream || bc.qL !== qa.live) { bcPaceDrop(); return; }
  let el = bc.q.shift();
  while (el && !el.isConnected) el = bc.q.shift();
  if (el) bcReveal(el);
  if (bc.q.length) bc.qTimer = setTimeout(bcPaceNext, bcPaceGap(el));
  else bcTyping(false);
  bcSync();
  bcStickBottom(stream);
}

/** 남은 말을 바로 다 — 스킵 · 다음 답 · 움직임 줄이기 */
function bcPaceFlush({ sync = true } = {}) {
  clearTimeout(bc.qTimer);
  bc.qTimer = 0;
  const had = bc.q.length;
  bc.q.forEach((el) => { if (el.isConnected) bcReveal(el); });
  bc.q = [];
  bcTyping(false);
  if (had && sync) {
    bcSync();
    const stream = document.getElementById('stream');
    if (stream) bcStickBottom(stream);
  }
}

/** 대기열 버리기 — 화면이 바뀌었거나 다른 방문객이다. 줄은 이미 없거나 곧 새로 그려진다 */
function bcPaceDrop() {
  clearTimeout(bc.qTimer);
  bc.qTimer = 0;
  bc.q = [];
  bcTyping(false);
}

/** 「삐약이가 입력 중」 점 세 개 — 대화 칸 바로 아래, 삐약이 쪽 */
function bcTyping(on) {
  const el = document.getElementById('bcTyping');
  if (el && el.hidden === on) el.hidden = !on;
}

/** 누르거나 키를 누르면 남은 말을 바로 — 한 번만 건다(문서 전체). 그 누름은 원래 하던 일도 그대로 한다 */
function bcPaceWire() {
  if (bc.paceWired) return;
  bc.paceWired = true;
  const skip = () => { if (bc.q.length) bcPaceFlush(); };
  document.addEventListener('pointerdown', skip, true);
  document.addEventListener('keydown', skip, true);
}
