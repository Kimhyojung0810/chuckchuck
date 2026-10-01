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

const bc = {
  sayCount: 0, rowCount: 0, speakTimer: 0, thinkSince: 0, slowTimer: 0, dockH: 0, mounted: false,
  syncAt: 0, syncN: 0, syncLater: 0,
  mcQi: -1, mc: '', mcUntil: 0, mcTimer: 0,   // 삐약이 진행 멘트 (bcMcSync)
  hostH: 0,
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
  if (bcMicOn()) return '듣고 있어요 · 다 말했으면 「그만 말하기」를 눌러요';
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
  bc.hostH = 0;
  bc.mounted = false;
  bc.mcQi = -1;
  bc.mc = '';
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
  bq.dockWatch = new ResizeObserver((entries) => {
    const h = Math.round(dock.getBoundingClientRect().height);
    if (h !== bc.dockH) { bc.dockH = h; layer.style.setProperty('--bc-dock-h', `${h}px`); }
    // 삐약이 카드도 진행 멘트·큰 글자로 두 줄이 되면 높아진다 — 대화 기둥 밑동을 그 위로 (10-02 맥 1512×860: 지금 질문이 카드 뒤로 숨었다)
    const hh = host ? Math.round(host.getBoundingClientRect().height) : 0;
    if (hh && hh !== bc.hostH) { bc.hostH = hh; layer.style.setProperty('--bc-host-h', `${hh}px`); }
    if (stream && entries.some((e) => e.target === stream)) bcStickBottom(stream);
  });
  bq.dockWatch.observe(dock);
  if (host) bq.dockWatch.observe(host);
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
  bcMcSync();
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
  const kids = [...stream.children];
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
    const now = stream.querySelector(':scope > .msg.is-now');
    const floor = now ? at(now) + 72 - stream.clientHeight : 0;
    stream.scrollTop = Math.max(0, Math.min(max, Math.max(floor, at(keep) - 6)));
  };
  requestAnimationFrame(down);
  setTimeout(down, 450);
}

/** 지금 질문에서 마지막 판정 말풍선 — 그 뒤에 내 말이 없을 때만 (= 방금 받은 판정) */
function bcFreshVerdict(stream) {
  const kids = [...stream.children];
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
