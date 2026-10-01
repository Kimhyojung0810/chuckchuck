/**
 * 부스 화상 Q&A 무대 — 주소창 /booth/call (→ index.html#/booth/call) 의 질문 화면.
 *
 * 2026-10-01 사용자: "부스를 위해서 만드는 전용 QA 페이지 … 왼쪽 하단에는 삐약이가 나와서 QA 를 진행하고
 * (교수님이건, 어떤 역할이던 위임을 받게 됨) 나는 정면에 그대로 나와서 그 질문에 대한 답을 이어서 하게 돼.
 * overlay 로 내 대화와 삐약이 대화가 화면에 오버레이되어 애플 liquid glass 처럼 은은하게."
 *
 * 시작 · 발표 고르기(+ 역할 고르기) · 훑어보기 · 마무리는 booth_qa.js 가 그대로 그린다. 이 파일은 #/qa 의 무대 한 장만
 * 다른 배치로 놓는다 — 내 얼굴(웹캠)이 화면을 채우고, 왼쪽 아래 삐약이가 고른 역할의 이름표를 달고 묻고,
 * 질문·내 답·판정이 삐약이 위로 글라스 말풍선이 되어 쌓인다. 질문이 가리키는 장은 오른쪽 위 작은 창.
 *
 * 로직은 새로 만들지 않는다. 질문·판정·힌트·되묻기는 qa_live.js 의 같은 id(#stream · .qa-live-input · #liveAnswer …),
 * 카메라·판단(구도 안내 · 정면 비율)은 booth_qa.js 의 bqCam* · bqOnCv 가 같은 id(#bqHint · #bqGazeNow · #bqCamToggle)를 찾는다.
 * 얼굴 가운데를 가리지 않는다(9/22 회의안 1-2) — 대화는 왼쪽 기둥, 답 칸은 아래 띠, 자료는 오른쪽 위.
 */

/** 삐약이가 새 말을 꺼낸 뒤 「말하는 중」 으로 보이는 시간 */
const BC_SPEAK_MS = 2600;
/** 질문을 맡는 병아리 — /booth/qa 무대의 쏠라 심사위원과 같은 새 */
const BC_HOST_BIRD = 'solar';

const bc = { aiCount: 0, rowCount: 0, speakTimer: 0 };

function bcRole() {
  return qa.aud || BOOTH_ROLES[0].aud;
}

function bcCounterText() {
  const L = qa.live;
  const n = L.questions.length;
  if (L.awaitEnd || L.qi >= n) return `질문 ${n}개를 마쳤어요`;
  return `질문 ${L.qi + 1} / ${n}`;
}

/** 삐약이 이름표 아래 한 줄 — 지금 무엇을 하고 있는지 */
function bcSayText(thinking) {
  if (thinking) return '답을 자료와 맞춰 보고 있어요';
  if (qa.live.awaitEnd) return '오늘 질문은 여기까지예요';
  return '답을 기다리고 있어요';
}

function renderQaLiveBoothCall() {
  const no = bqQaSlideNo();
  const role = bcRole();
  bqMount('qa', `
    <div class="bc-call">
      <div class="bc-self" data-bq-cam-box data-camera="off">
        <video data-bq-cam autoplay muted playsinline></video>
        <p class="bc-self-off"><b>카메라 없이 목소리로 답해요</b><span id="bqCamNote"></span></p>
      </div>

      <p class="bc-hint bc-glass" id="bqHint" hidden></p>

      <aside class="bc-side">
        <div class="bc-side-row">
          <span class="bc-pill bc-glass" id="bqGazeNow" hidden></span>
          <button type="button" class="bc-pill bc-glass bc-btn" id="bqCamToggle">카메라 끄기</button>
        </div>
        <figure class="bq-slide bc-slide bc-glass" id="bqSlide" data-no="${no}">${bqSlideHtml(no)}</figure>
      </aside>

      <section class="bc-talk" aria-label="${escapeHtml(role)}${josa(role, '과', '와')} 주고받은 말">
        <div class="qa-stream bc-stream" id="stream">${qa.turns.map(streamRow).join('')}</div>
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
      <p class="sr-only" id="bcLive" aria-live="polite"></p>
    </div>`);
  bc.aiCount = 0;
  bc.rowCount = 0;
  $('#bqCamToggle').addEventListener('click', bqCamToggle);
  if (window.BoothCV && !BoothCV.readGaze()) BoothCV.startGaze();
  bcSync();
  const stream = $('#stream');
  if (stream) {
    bq.observer = new MutationObserver(bcSync);
    bq.observer.observe(stream, { childList: true });
  }
  paintDeckThumbs(document.getElementById('bqStage'));
  bqWatchSlide();
  bqCamPaint();
  scrollDown();
  wireLiveInput();
  const card = document.querySelector('#bqStage .bq-answer');
  if (card) {
    bq.inputObserver = new MutationObserver(bqRelabelInput);
    bq.inputObserver.observe(card, { childList: true });
  }
  bqRelabelInput();
  bcWatchDock();
}

/**
 * 삐약이 · 진행 칩은 답 칸 바로 위에 선다. 답 칸 높이는 판정·힌트·끝 카드마다 바뀌므로 잰 값을 쓴다.
 * 창 크기가 바뀌어 대화 칸 높이가 달라지면 지금 질문이 아래로 밀려 가려지므로 다시 맨 아래로 붙인다.
 */
function bcWatchDock() {
  const layer = document.getElementById('bqStage');
  const dock = layer && layer.querySelector('.bc-dock');
  const stream = document.getElementById('stream');
  if (!dock || !window.ResizeObserver) return;
  bq.dockWatch = new ResizeObserver((entries) => {
    layer.style.setProperty('--bc-dock-h', `${Math.round(dock.getBoundingClientRect().height)}px`);
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

/** 스트림이 자랄 때마다 — 번호 · 진행 칩 · 자료 장 · 삐약이 표정과 말하기 · 지금 질문 강조를 맞춘다 */
function bcSync() {
  const stream = document.getElementById('stream');
  if (!stream || !qa.live) return;
  const thinking = !!document.getElementById('coachThinking');

  const count = document.getElementById('bcCount');
  if (count) count.textContent = bcCounterText();
  const prog = document.getElementById('bqProg');
  if (prog) prog.innerHTML = bqProgressHtml();
  const slide = document.getElementById('bqSlide');
  const no = bqQaSlideNo();
  if (slide && Number(slide.dataset.no) !== no) {
    slide.dataset.no = String(no);
    slide.innerHTML = bqSlideHtml(no);
    paintDeckStage(slide);
  }

  const now = bcNowQuestionRow(stream);
  stream.querySelectorAll(':scope > .is-now').forEach((el) => { if (el !== now) el.classList.remove('is-now'); });
  if (now) now.classList.add('is-now');
  bcDimPast(stream);
  const rows = stream.children.length;
  if (rows !== bc.rowCount) {
    bc.rowCount = rows;
    bcStickBottom(stream);
  }

  const host = document.getElementById('bcHost');
  const bird = host && host.querySelector('.bq-bird');
  if (bird) {
    const mood = thinking ? 'curious' : bqJudgeMood();
    if ((bird.dataset.mood || '') !== mood) bird.dataset.mood = mood;
  }
  const say = document.getElementById('bqJudgeSay');
  if (say) say.textContent = bcSayText(thinking);

  // 삐약이 쪽 말(질문·판정·힌트)이 새로 붙으면 잠깐 말하는 모습 + 화면 읽기 프로그램에 같은 문장
  const aiRows = stream.querySelectorAll(':scope > .msg.ai:not(.thinking)');
  if (aiRows.length > bc.aiCount && bc.aiCount > 0) bcSpeak(aiRows[aiRows.length - 1]);
  bc.aiCount = aiRows.length;
}

/** 지난 질문까지의 말은 옅게 — 지금 질문과 그 뒤의 말(내 답 · 판정 · 힌트)만 또렷하다 */
function bcDimPast(stream) {
  const kids = [...stream.children];
  let lastQ = -1;
  kids.forEach((el, i) => { if (el.matches('.msg.ai.q')) lastQ = i; });
  kids.forEach((el, i) => el.classList.toggle('is-past', i < lastQ));
}

/** 새 말이 붙으면 맨 아래(삐약이 바로 위)로. 장 그림이 늦게 그려져 높이가 바뀌므로 한 번 더 내린다 */
function bcStickBottom(stream) {
  const down = () => { if (stream.isConnected) stream.scrollTop = stream.scrollHeight; };
  requestAnimationFrame(down);
  setTimeout(down, 450);
}

function bcSpeak(row) {
  const host = document.getElementById('bcHost');
  if (host) {
    host.dataset.speaking = '1';
    clearTimeout(bc.speakTimer);
    bc.speakTimer = setTimeout(() => { if (host.isConnected) host.dataset.speaking = ''; }, BC_SPEAK_MS);
  }
  const live = document.getElementById('bcLive');
  const text = row && (row.querySelector('.msg-q, .msg-bubble > p') || row.querySelector('.msg-bubble'));
  if (live && text) live.textContent = `${bcRole()}: ${text.textContent.replace(/\s+/g, ' ').trim()}`;
}
