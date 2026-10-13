/**
 * Q&A 무대 「띠 · 틀 · 레일」 — 리허설 화상판(#bqStage[data-flow="rehearsal"][data-screen="qa"]) · 스튜디오 ④ (2026-10-13 사용자 브리프
 * 「Speak × LiveAvatar — 한 순간에는 하나의 주된 행동만」). 설계 · 프로토타입: design/qa_stage/prototype.html
 *
 *   위 띠     삐약이(표정 · 목소리 구) + 질문 + 실시간 내 말 — 높이 고정, 노트북 카메라 바로 아래라 질문을 읽는 눈이 카메라 근처에 머문다
 *   가운데    웹캠 16:9 틀 — 그 위에는 아무것도 얹지 않는다. 크기 · 자리는 어떤 순간에도 그대로
 *   오른쪽    자료 레일 — 앞뒤 넘기기 · 장 번호 · 크게 보기(얼굴 구역 오른쪽부터) · 질문 장으로
 *   아래      행동 줄 — 가운데엔 주된 행동 하나, 오른쪽에 「막혔어요」 · 「다른 주제로」
 *
 * 순간(qsScene) — A 묻기(asking) · B 답하기(listening) · B′ 곧 보내요(sending) · C 생각(thinking) · F 막힘(encouraging) · E 주제 바꾸기(switching) · 끝(done).
 * D 꼬리질문은 순간이 아니라 전환이다: 판정의 claim(내 말 원문 구절)에 밑줄 → 그 구절이 위 「내 말에서」 로 올라가고 → 새 질문.
 *
 * 로직은 새로 만들지 않는다. 받아쓰기 · 보내기 · 힌트 · 모르겠어요 · 답 보기 · 결과는 숨긴 원래 답 칸(qa_live.js liveInputHtml)의
 * 단추를 그대로 누르고, 자동 듣기 · 자동 보내기는 booth_call.js 그대로, 주제 바꾸기는 qa_live.js liveSwitch* 그대로다.
 * 카메라는 건드리지 않는다 — <video> 는 제자리에 두고 그 칸(.bc-self)을 틀 자리로 옮길 뿐이다.
 * booth_call.js bcSync(스트림이 자랄 때) · bcAutoLoop(0.3초마다)가 qsSync() 를 부른다.
 */

/** 주제 이름이 머무는 시간 */
const QS_TOPIC_MS = 900;
/** 묻는 시간 — 글자 수 ÷ 7자/초, 1.6~7초 (voice-viz 말하기 흉내와 같은 규칙). 그 뒤로는 말을 안 해도 「답하기」 */
const QS_READ_CPS = 7;
const QS_READ_MIN = 1600;
const QS_READ_MAX = 7000;
/** 막힘 사다리 줄 — app.js streamRow 와 같은 말 */
const QS_COACH_LINE = { narrow: '막힘 1/3 · 자료에서 같이 찾아요', scaffold: '막힘 2/3 · 빈칸을 채워요', explain: '막힘 3/3 · 답을 같이 풀어요', clarify: '질문을 다시 풀었어요' };

const qs = {
  askKey: '', askAt: 0, qi: -1, claimKey: '', weaving: false, topicTimer: 0,
  slide: 0, focusKey: '', menu: '', persp: false, typing: false, hist: false, sig: {},
};

/* ─── 순수 — 순간 계산 (etc/tests/js/qa_stage.smoke.mjs) ─────────────────────────── */

/** 말풍선 글(escape 된 HTML · 링크)을 맨 글자로 */
function qsPlain(html) {
  return String(html || '').replace(/<[^>]*>/g, '')
    .replace(/&#(\d+);/g, (_, n) => String.fromCharCode(Number(n)))
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ').trim();
}

function qsReadMs(text) {
  const n = String(text || '').replace(/\s+/g, '').length;
  return Math.round(Math.min(QS_READ_MAX, Math.max(QS_READ_MIN, (n / QS_READ_CPS) * 1000)));
}

/** 지금 답할 물음 — qa.turns 의 마지막 질문 항목 자리 */
function qsAskIndex(turns) {
  for (let i = (turns || []).length - 1; i >= 0; i -= 1) {
    const t = turns[i];
    if (t && t.who === 'ai' && (t.kind === 'question' || t.kind === 'claim')) return i;
  }
  return -1;
}

/** 이 물음을 부른 삐약이 반응 — 바로 앞 내 답 뒤의 react (없으면 null) */
function qsLeadReact(turns, ask) {
  for (let i = ask - 1; i >= 0; i -= 1) {
    const t = turns[i];
    if (t.who === 'me' || (t.who === 'ai' && (t.kind === 'question' || t.kind === 'claim'))) return null;
    if (t.kind === 'react') return t;
  }
  return null;
}

function qsHelpOf(t) {
  if (t.kind === 'hint') return { tag: `힌트 ${t.level}/${t.total || 3}`, text: qsPlain(t.text), slide: Number((t.slides || [])[0]) || 0 };
  if (t.kind === 'gist') return { tag: t.mid ? '이렇게 말하면 완성이에요' : '이렇게 답하면 좋았어요', text: qsPlain(t.text), slide: 0 };
  if (t.kind === 'react' && t.coach) return { tag: QS_COACH_LINE[t.coach] || '더 쉬운 걸로 바꿔 물을게요', text: qsPlain(t.text), slide: Number(t.quoteSlide) || 0 };
  return null;
}

/**
 * 이 물음에서 열린 도움 — 가장 최근 것 하나. 물음 뒤에 연 힌트 · 펼친 답(내가 다시 답하기 전까지),
 * 없으면 이 물음을 부른 자리(바로 앞 내 답 뒤)의 막힘 사다리 응답 · 「이렇게 말하면 완성이에요」
 */
function qsHelp(turns, ask) {
  for (let i = turns.length - 1; i > ask; i -= 1) {
    const t = turns[i];
    if (t.who === 'me') return null;
    const h = qsHelpOf(t);
    if (h) return h;
  }
  for (let i = ask - 1; i >= 0; i -= 1) {
    const t = turns[i];
    if (t.who === 'me' || (t.who === 'ai' && (t.kind === 'question' || t.kind === 'claim'))) return null;
    const h = qsHelpOf(t);
    if (h) return h;
  }
  return null;
}

/** 물음 뒤 내가 보낸 마지막 답 */
function qsLastAnswer(turns, from) {
  for (let i = turns.length - 1; i > from; i -= 1) if (turns[i].who === 'me') return qsPlain(turns[i].text);
  return '';
}

/**
 * 지금 순간 — 화면 전체가 이것 하나만 읽는다.
 * env: { now, askAt, text(받아쓰는 중인 글), sending(자동 보내기 초읽기), thinking(판정 기다림 줄) }
 */
function qsScene(L, turns, env = {}) {
  if (!L || !Array.isArray(L.questions)) return null;
  const n = L.questions.length;
  const ask = qsAskIndex(turns);
  const askItem = ask >= 0 ? turns[ask] : null;
  const react = ask >= 0 ? qsLeadReact(turns, ask) : null;
  const help = ask >= 0 ? qsHelp(turns, ask) : null;
  const base = {
    ask, question: askItem ? qsPlain(askItem.text) : '', questionHtml: askItem ? askItem.text : '',
    react: react && !react.coach ? { text: qsPlain(react.text), verdict: react.verdict || '' } : null,
    help, retell: !!L.retell, answer: ask >= 0 ? qsLastAnswer(turns, ask) : '',
  };
  let phase;
  if (L.awaitEnd || L.qi >= n) phase = 'done';
  else if (L.switching) phase = 'switching';
  else if (L.busy || env.thinking) phase = 'thinking';
  else if (env.sending) phase = 'sending';
  else if (help) phase = 'encouraging';
  else if (!String(env.text || '').trim() && (env.now || 0) - (env.askAt || 0) < qsReadMs(base.question)) phase = 'asking';
  else phase = 'listening';
  return { ...base, phase };
}

/* ─── 화면 ─────────────────────────────────────────────────────────────── */

function qsLayer() {
  const st = document.getElementById('bqStage');
  return st && st.dataset.flow === 'rehearsal' && st.dataset.screen === 'qa' ? st : null;
}

function qsEsc(s) {
  return typeof escapeHtml === 'function' ? escapeHtml(s) : String(s || '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function qsById(id) { return document.getElementById(id); }

/** 바뀔 때만 쓴다 — 0.3초마다 불려도 DOM 을 건드리지 않게 */
function qsPut(el, key, html) {
  if (!el || qs.sig[key] === html) return false;
  qs.sig[key] = html;
  el.innerHTML = html;
  return true;
}

function qsSlideCount() {
  const t = (typeof nf !== 'undefined' && nf && nf.slideTitles) || [];
  return t.length || (typeof uploadedPdf !== 'undefined' && uploadedPdf && uploadedPdf.pageCount) || 1;
}

/** 한 번만 — 띠 · 레일 · 행동 줄을 세우고 원래 조각(삐약이 · 카메라 단추 · 나가기 · 구도 안내 · 사생활 안내)을 옮겨 단다 */
function qsMount(layer, call) {
  layer.dataset.qs = '1';
  call.insertAdjacentHTML('beforeend', `
    <header class="qs-band" aria-label="삐약이와 지금 질문">
      <div class="qs-pres" id="qsPres"><span class="qs-pres-state" id="qsPresState"></span></div>
      <div class="qs-line" id="qsLine" aria-hidden="true">
        <p class="qs-meta" id="qsMeta"></p>
        <p class="qs-from" id="qsFrom"><span class="qs-tag">내 말에서</span><q id="qsFromQ"></q></p>
        <p class="qs-q" id="qsQ"></p>
        <div class="qs-say" id="qsSay"></div>
        <span class="qs-thread" id="qsThread"></span>
        <div class="qs-topic" id="qsTopic"><small>주제를 바꿔요</small><b id="qsTopicText"></b></div>
      </div>
      <div class="qs-sys" id="qsSys"></div>
    </header>
    <aside class="qs-rail" aria-label="발표 자료">
      <div class="qs-deck">
        <div class="qs-deck-head"><span>발표 자료</span><b id="qsDeckNo"></b></div>
        <button type="button" class="qs-deck-pic" id="qsDeckPic" aria-label="자료 크게 보기"><figure class="bq-slide qs-slide" id="qsSlide"></figure></button>
        <div class="qs-deck-cap" id="qsDeckCap"></div>
        <div class="qs-deck-nav">
          <button type="button" id="qsPrev" aria-label="이전 장">‹</button>
          <button type="button" class="qs-wide" id="qsZoomBtn" aria-expanded="false">크게 보기</button>
          <button type="button" id="qsNext" aria-label="다음 장">›</button>
        </div>
      </div>
      <div class="qs-rail-foot">
        <button type="button" class="qs-hist-btn" id="qsHist" aria-expanded="false" aria-controls="stream"></button>
        <button type="button" class="qs-textlink" id="qsFinish">여기까지 하고 리포트 보기</button>
      </div>
    </aside>
    <footer class="qs-strip">
      <div class="qs-aux" id="qsAux"></div>
      <div class="qs-act" id="qsAct"></div>
      <div class="qs-alt" id="qsAlt"></div>
    </footer>
    <section class="qs-zoom" id="qsZoom" hidden aria-label="자료 크게 보기"></section>
    <div class="qs-pop" id="qsPop" hidden role="group"></div>`);
  const pres = qsById('qsPres');
  const host = qsById('bcHost');
  if (pres && host) pres.prepend(host);
  const sys = qsById('qsSys');
  [qsById('bqCamToggle'), layer.querySelector('[data-rh-exit]')].forEach((el) => { if (el && sys) sys.appendChild(el); });
  const aux = qsById('qsAux');
  const hint = qsById('bqHint');
  if (hint && aux) aux.appendChild(hint);
  const privacy = layer.querySelector('.bc-privacy');
  const self = layer.querySelector('.bc-self');
  if (privacy && self) self.appendChild(privacy);
  qsWire(layer);
  Object.assign(qs, { askKey: '', askAt: Date.now(), qi: -1, claimKey: '', weaving: false, slide: 0, focusKey: '', menu: '', persp: false, typing: false, hist: false, sig: {} });
}

function qsWire(layer) {
  layer.querySelector('.qs-strip').addEventListener('click', qsStripClick);
  qsById('qsPop').addEventListener('click', qsPopClick);
  qsById('qsPrev').addEventListener('click', () => qsGo(qs.slide - 1));
  qsById('qsNext').addEventListener('click', () => qsGo(qs.slide + 1));
  qsById('qsZoomBtn').addEventListener('click', () => qsZoom(qsById('qsZoom').hidden));
  qsById('qsDeckPic').addEventListener('click', () => qsZoom(true));
  qsById('qsDeckCap').addEventListener('click', (e) => { if (e.target.closest('[data-qs-back]')) qsGo(qsFocus().no); });
  qsById('qsZoom').addEventListener('click', (e) => {
    const b = e.target.closest('[data-qs-z]');
    if (!b) return;
    const what = b.dataset.qsZ;
    if (what === 'prev') qsGo(qs.slide - 1);
    else if (what === 'next') qsGo(qs.slide + 1);
    else if (what === 'back') qsGo(qsFocus().no);
    else qsZoom(false);
  });
  qsById('qsHist').addEventListener('click', () => qsHistOpen(!qs.hist));
  qsById('qsFinish').addEventListener('click', () => qsPress('liveFinish'));
  layer.addEventListener('keydown', qsKeys, true);
  document.addEventListener('pointerdown', qsOutside, true);
}

/** 숨긴 원래 단추를 누른다 — 로직은 그쪽 그대로 */
function qsPress(id) {
  const b = qsById(id);
  if (b && !b.disabled) { b.click(); return true; }
  return false;
}

function qsKeys(e) {
  if (e.key === 'Escape' && (qs.menu || !qsById('qsZoom').hidden || qs.hist)) {
    e.stopPropagation();
    qsMenu('');
    qsZoom(false);
    qsHistOpen(false);
    return;
  }
  const typing = e.target && e.target.closest && e.target.closest('textarea, input');
  if (typing || qsById('qsZoom').hidden) return;
  if (e.key === 'ArrowLeft') { e.stopPropagation(); qsGo(qs.slide - 1); }
  if (e.key === 'ArrowRight') { e.stopPropagation(); qsGo(qs.slide + 1); }
}

function qsOutside(e) {
  if (!qs.menu && !qs.hist) return;
  if (!qsById('qsPop')) { document.removeEventListener('pointerdown', qsOutside, true); return; }
  const t = e.target;
  if (!t.closest) return;
  if (qs.menu && !t.closest('#qsPop, [data-qs-act="stuck"], [data-qs-act="switch"]')) qsMenu('');
  if (qs.hist && !t.closest('.bc-talk, #qsHist')) qsHistOpen(false);
}

/* ─── 행동 줄 ─── */

function qsStripClick(e) {
  const b = e.target.closest('[data-qs-act]');
  if (!b || b.disabled) return;
  const act = b.dataset.qsAct;
  if (act === 'mic') qsPress('liveMic');
  else if (act === 'send') qsPress('liveSend');
  else if (act === 'hold') qsPress('bcSendCancel');
  else if (act === 'result') qsPress('liveSeeResult');
  else if (act === 'skip-retell') qsPress('liveSkipRetell');
  else if (act === 'type') qsType(true);
  else if (act === 'untype') qsType(false);
  else if (act === 'stuck' || act === 'switch') qsMenu(qs.menu === act ? '' : act);
}

/** 글로 쓰기 — 숨긴 답 칸을 행동 줄 위 한 줄로 연다. 받아쓰기가 켜져 있으면 끈다(사람이 끈 것으로 남아 이 물음에선 다시 안 켜진다) */
function qsType(on) {
  qs.typing = !!on;
  const layer = qsLayer();
  if (layer) layer.dataset.qsType = qs.typing ? '1' : '';
  if (qs.typing && typeof bcMicOn === 'function' && bcMicOn()) qsPress('liveMic');
  if (qs.typing) { const ta = qsById('liveAnswer'); if (ta) ta.focus(); }
  qsSync();
}

function qsMicPill(scene, micOn) {
  const label = scene.phase === 'asking' ? '말하면 바로 들어요' : '듣고 있어요';
  return micOn
    ? `<button type="button" class="qs-mic is-on" data-qs-act="mic" aria-label="받아쓰기 멈추기"><i aria-hidden="true"></i>${label}</button>`
    : '<button type="button" class="qs-mic" data-qs-act="mic"><i aria-hidden="true"></i>말로 답하기</button>';
}

/** 가운데 — 주된 행동 하나 */
function qsActHtml(scene, env) {
  const p = scene.phase;
  if (qs.typing && !['thinking', 'switching', 'done'].includes(p)) {
    return '<button type="button" class="qs-textlink" data-qs-act="untype">말로 하기</button>';
  }
  if (p === 'done') return `<button type="button" class="qs-primary" data-qs-act="result">${qsEsc(env.resultLabel || '리포트 보러 가기')}</button>`;
  if (p === 'thinking' || p === 'switching') return `<span class="qs-status" role="status">${qsEsc(env.status || (p === 'thinking' ? '삐약이가 답을 읽고 있어요' : '다음 질문을 고르고 있어요'))}</span>`;
  if (p === 'sending') {
    return `<span class="qs-count"><svg viewBox="0 0 22 22" aria-hidden="true"><circle class="bg" cx="11" cy="11" r="9"/><circle class="fg" cx="11" cy="11" r="9"/></svg>곧 보내요
      <button type="button" class="qs-second" data-qs-act="hold">보내지 않기</button></span>`;
  }
  const send = env.hasText ? `<button type="button" class="qs-primary" data-qs-act="send">${scene.retell ? '내 말로 말했어요' : '다 말했어요'}</button>` : '';
  if (p === 'asking') return env.micOn ? qsMicPill(scene, true) : qsMicPill(scene, false);
  return `${qsMicPill(scene, env.micOn)}${send}`;
}

/** 오른쪽 — 막혔어요 · 다른 주제로 (다시 말하기 중이면 건너뛰기) */
function qsAltHtml(scene, env) {
  const p = scene.phase;
  if (!['asking', 'listening', 'sending', 'encouraging'].includes(p)) return '';
  const bits = [];
  if (scene.retell) bits.push('<button type="button" class="qs-second" data-qs-act="skip-retell">이건 건너뛰기</button>');
  else if (p !== 'asking' && env.stuckItems) bits.push(`<button type="button" class="qs-second${p === 'encouraging' ? ' is-em' : ''}" data-qs-act="stuck" aria-expanded="${qs.menu === 'stuck'}" aria-controls="qsPop">${p === 'encouraging' ? '도움 더 받기' : '막혔어요'}</button>`);
  if (env.canSwitch) bits.push(`<button type="button" class="qs-second" data-qs-act="switch" aria-expanded="${qs.menu === 'switch'}" aria-controls="qsPop">다른 주제로</button>`);
  return bits.join('');
}

function qsAuxHtml(scene) {
  const p = scene.phase;
  if (qs.typing || !['asking', 'listening', 'encouraging'].includes(p)) return '';
  return '<button type="button" class="qs-textlink" data-qs-act="type">글로 쓰기</button>';
}

/* ─── 메뉴 — 막혔어요 · 다른 주제로 ─── */

/** 막혔어요 — 원래 답 칸에 지금 떠 있는 도움 단추들(힌트 n단계 · 모르겠어요 · 답 보기 · 시연용 정답 보기 · 대충 답해 보기) */
function qsStuckItems() {
  const ids = [['liveHint', ''], ['liveStuck', '같이 좁혀 가요 · 기록에 「도움 받음」으로 남아요'], ['liveReveal', '답을 본 뒤 내 말로 다시 해요'], ['liveTryModel', '시연용'], ['liveTryWeak', '시연용 · 일부러 엉성하게']];
  return ids.map(([id, sub]) => {
    const b = qsById(id);
    return b && !b.disabled ? { id, label: b.textContent.trim(), sub } : null;
  }).filter(Boolean);
}

function qsMenu(which) {
  const can = which === 'switch' ? (typeof liveCanSwitch === 'function' && liveCanSwitch()) : which === 'stuck';
  qs.menu = can ? which : '';
  qs.persp = false;
  if (qs.menu === 'switch' && typeof liveWarmConceptPool === 'function') {
    const p = liveWarmConceptPool();
    if (p && p.then) p.then(() => { if (qs.menu === 'switch') qsPaintMenu(); });
  }
  qsPaintMenu();
  qs.sig.alt = '';
  qsSync();
  if (qs.menu) { const first = document.querySelector('#qsPop button:not(:disabled)'); if (first) first.focus({ preventScroll: true }); }
}

function qsPaintMenu() {
  const pop = qsById('qsPop');
  if (!pop) return;
  pop.hidden = !qs.menu;
  pop.dataset.kind = qs.menu;
  if (!qs.menu) { pop.innerHTML = ''; return; }
  if (qs.menu === 'stuck') {
    const items = qsStuckItems();
    pop.setAttribute('aria-label', '막혔을 때');
    pop.innerHTML = `<h2>천천히 해도 돼요. 이렇게 도와줄 수 있어요</h2>
      ${items.map((it) => `<button type="button" class="qs-opt" data-qs-press="${it.id}"><b>${qsEsc(it.label)}</b>${it.sub ? `<small>${qsEsc(it.sub)}</small>` : ''}</button>`).join('')}
      <div class="qs-pop-foot"><button type="button" class="qs-textlink" data-qs-close>닫기</button></div>`;
    return;
  }
  const L = qa.live;
  const q = L && L.questions[L.qi];
  const pick = typeof livePickConcept === 'function' ? livePickConcept() : null;
  const trap = !!(q && q.trap);
  pop.setAttribute('aria-label', '다른 주제로');
  pop.innerHTML = `<h2>어디로 가 볼까요? 지금까지 한 말은 기록에 남아요</h2>
    <button type="button" class="qs-opt" data-qs-sw="concept"><b>아직 안 다룬 개념으로</b><small>${qsEsc(pick ? `「${pick.label || '개념'}」 로 가요` : '발표와 어긋나거나 빠진 개념부터 골라요')}</small></button>
    <button type="button" class="qs-opt" data-qs-sw="perspective" aria-expanded="${qs.persp}" ${trap ? 'disabled' : ''}><b>같은 주제, 다른 관점으로</b><small>${trap ? '이 질문은 관점을 바꿀 수 없어요' : '개념은 그대로, 묻는 방향만 바꿔요'}</small></button>
    <div class="qs-chips" ${qs.persp && !trap ? '' : 'hidden'}>${(typeof QW_PERSPECTIVES !== 'undefined' ? QW_PERSPECTIVES : []).map(([k, name]) => `<button type="button" data-qs-p="${k}">${name}</button>`).join('')}</div>
    <button type="button" class="qs-opt" data-qs-sw="skip"><b>이 질문 건너뛰기</b><small>기록에 남고, 틀린 것으로 세지 않아요</small></button>
    <div class="qs-pop-foot"><button type="button" class="qs-textlink" data-qs-close>닫기</button></div>`;
}

function qsPopClick(e) {
  const b = e.target.closest('button');
  if (!b || b.disabled) return;
  if (b.hasAttribute('data-qs-close')) { const was = qs.menu; qsMenu(''); const t = document.querySelector(`[data-qs-act="${was}"]`); if (t) t.focus(); return; }
  if (b.dataset.qsPress) { const id = b.dataset.qsPress; qsMenu(''); qsPress(id); return; }
  if (b.dataset.qsP) return qsRun(() => liveSwitchPerspective(b.dataset.qsP));
  const sw = b.dataset.qsSw;
  if (sw === 'perspective') { qs.persp = !qs.persp; qsPaintMenu(); const c = document.querySelector('#qsPop .qs-chips button'); if (qs.persp && c) c.focus(); return; }
  if (sw === 'concept') return qsRun(() => liveSwitchConcept());
  if (sw === 'skip') return qsRun(() => liveSkipQuestion());
}

async function qsRun(work) {
  qsMenu('');
  try { await work(); } finally { qsSync(); }
}

/* ─── 자료 레일 ─── */

function qsFocus() {
  return typeof bqQaFocus === 'function' ? bqQaFocus() : { no: 1, why: '질문이 가리키는' };
}

function qsGo(no) {
  const n = qsSlideCount();
  const next = Math.min(n, Math.max(1, no));
  if (next === qs.slide) return;
  qs.slide = next;
  qsPaintRail(true);
}

function qsPaintSlide(fig, no) {
  if (!fig || typeof bqSlideHtml !== 'function') return;
  if (fig.dataset.no === String(no)) return;
  fig.dataset.no = String(no);
  fig.innerHTML = bqSlideHtml(no, '');
  if (typeof paintDeckStage === 'function') paintDeckStage(fig);
}

function qsPaintRail(force = false) {
  const f = qsFocus();
  const key = `${f.no}|${f.why}`;
  if (key !== qs.focusKey) { qs.focusKey = key; qs.slide = f.no; force = true; }
  if (!qs.slide) qs.slide = f.no;
  const n = qsSlideCount();
  qsPaintSlide(qsById('qsSlide'), qs.slide);
  bqSet(qsById('qsDeckNo'), 'textContent', `${qs.slide} / ${n}`);
  const prev = qsById('qsPrev'); const next = qsById('qsNext');
  if (prev) prev.disabled = qs.slide <= 1;
  if (next) next.disabled = qs.slide >= n;
  const at = qs.slide === f.no;
  qsPut(qsById('qsDeckCap'), 'cap', at
    ? `${qsEsc(f.why || '질문이 가리키는')} <b>${f.no}장</b>`
    : `<button type="button" class="qs-back" data-qs-back>질문 장으로 · ${f.no}장</button>`);
  const pic = qsById('qsDeckPic');
  if (pic) pic.classList.toggle('is-focus', at && /힌트|판정/.test(f.why || ''));
  if (force && !qsById('qsZoom').hidden) qsPaintZoom();
}

/** 크게 보기 — 얼굴 구역(틀 가운데 44%) 오른쪽 끝부터 레일 끝까지. 녹음 · 대화는 그대로 */
function qsZoom(on) {
  const z = qsById('qsZoom');
  if (!z) return;
  z.hidden = !on;
  const btn = qsById('qsZoomBtn');
  if (btn) { btn.setAttribute('aria-expanded', String(!!on)); btn.textContent = on ? '작게 보기' : '크게 보기'; }
  if (!on) { z.innerHTML = ''; return; }
  qsPlaceZoom();
  qsPaintZoom();
}

function qsPlaceZoom() {
  const z = qsById('qsZoom');
  const call = document.querySelector('#bqStage .bc-call');
  const video = document.querySelector('#bqStage .bc-self video');
  const rail = document.querySelector('#bqStage .qs-rail');
  if (!z || !call || !video || !rail) return;
  const c = call.getBoundingClientRect(); const v = video.getBoundingClientRect(); const r = rail.getBoundingClientRect();
  const left = v.left + v.width * 0.72;
  z.style.left = `${Math.round(left - c.left)}px`;
  z.style.width = `${Math.round(r.right - left)}px`;
  z.style.top = `${Math.round(v.top - c.top)}px`;
}

function qsPaintZoom() {
  const z = qsById('qsZoom');
  if (!z || z.hidden) return;
  const f = qsFocus();
  const n = qsSlideCount();
  z.innerHTML = `<figure class="bq-slide qs-slide qs-zoom-pic" id="qsZoomSlide"></figure>
    <div class="qs-zoom-bar">
      <button type="button" class="qs-second" data-qs-z="prev" aria-label="이전 장" ${qs.slide <= 1 ? 'disabled' : ''}>‹</button>
      <b>${qs.slide} / ${n}</b>
      <button type="button" class="qs-second" data-qs-z="next" aria-label="다음 장" ${qs.slide >= n ? 'disabled' : ''}>›</button>
      ${qs.slide !== f.no ? `<button type="button" class="qs-back" data-qs-z="back">질문 장으로 · ${f.no}장</button>` : ''}
      <span class="qs-grow"></span><span class="qs-rec">대화는 계속 이어져요</span>
      <button type="button" class="qs-second" data-qs-z="close">닫기</button>
    </div>`;
  qsPaintSlide(qsById('qsZoomSlide'), qs.slide);
}

/* ─── 기록 서랍 — 원래 대화 기둥(주고받은 말 · 판정 근거 · 힌트)을 왼쪽에 연다 ─── */

function qsHistOpen(on) {
  qs.hist = !!on;
  const layer = qsLayer();
  if (!layer) return;
  layer.dataset.qsHist = qs.hist ? 'open' : '';
  const btn = qsById('qsHist');
  if (btn) btn.setAttribute('aria-expanded', String(qs.hist));
  if (qs.hist && typeof bcStickBottom === 'function') bcStickBottom(qsById('stream'));
}

function qsHistLabel(L) {
  const done = Math.min(L.qi, L.questions.length);
  return done ? `지난 질문 ${done}개 · 기록 보기` : '주고받은 기록 보기';
}

/* ─── 띠 ─── */

function qsVerdictDot(v) {
  const k = { full: 'ok', partial: 'mid', none: 'no' }[v];
  return k ? `<i class="qs-dot is-${k}" aria-hidden="true"></i>` : '';
}

function qsMetaHtml(scene, L) {
  const mc = typeof bc !== 'undefined' && bc.mc && bc.mcUntil > Date.now() ? bc.mc : '';
  if (scene.phase === 'asking' && scene.react) return `<span class="qs-react">${qsVerdictDot(scene.react.verdict)}${qsEsc(scene.react.text)}</span>`;
  if (scene.phase === 'asking' && mc && !scene.react) return `<span class="qs-react">${qsEsc(mc)}</span>`;
  if (scene.phase === 'done') return '<span class="qs-num">질문을 모두 마쳤어요</span>';
  const n = L.questions.length;
  const model = typeof qwModel === 'function' ? qwModel(L) : null;
  const tag = model && typeof qwAskMeta === 'function' ? qwAskMeta(model, L) : '';
  return `<span class="qs-num">질문 ${Math.min(L.qi + 1, n)} / ${n}</span>${tag ? `<span aria-hidden="true">·</span><span class="qs-topic-name">${qsEsc(tag)}</span>` : ''}`;
}

/** 받아쓰는 중인 글 — 확정 글 + 아직 확정 안 된 끝(흐리게) */
function qsLiveText() {
  const ta = qsById('liveAnswer');
  const val = ta ? ta.value : '';
  const mic = typeof liveMic !== 'undefined' && liveMic ? liveMic : null;
  const interim = mic && mic.interim ? String(mic.interim) : '';
  if (interim && val.endsWith(interim)) return { final: val.slice(0, val.length - interim.length), interim };
  return { final: val, interim: '' };
}

/** claim 을 답 안에서 찾아 mark 로 — 없으면 답만 */
function qsAnswerHtml(answer, claim) {
  const a = String(answer || '');
  const at = claim ? a.indexOf(claim) : -1;
  if (at < 0) return `<span class="qs-tx">${qsEsc(a)}</span>`;
  return `<span class="qs-tx">${qsEsc(a.slice(0, at))}<mark class="qs-cl">${qsEsc(claim)}</mark>${qsEsc(a.slice(at + claim.length))}</span>`;
}

function qsSayHtml(scene, live) {
  const p = scene.phase;
  const help = scene.help ? `<span class="qs-help"><span class="qs-tag">${qsEsc(scene.help.tag)}</span><span>${qsEsc(scene.help.text)}</span></span>` : '';
  if (p === 'thinking') return `<span class="qs-tx is-thinking">${qsEsc(scene.answer)}</span>`;
  if (p === 'done') return `<span class="qs-nudge">${qsEsc(live.endNote || '리포트에서 내 답과 자료 근거를 다시 볼 수 있어요')}</span>`;
  if (p === 'switching' || p === 'asking') return '';
  const words = live.final || live.interim
    ? `<span class="qs-tx">${qsEsc(live.final)}<span class="qs-int">${qsEsc(live.interim)}</span></span>` : '';
  if (help) return `${help}${words}`;
  return words;
}

function qsQClass(text, phase) {
  if (!['asking', 'switching', 'done'].includes(phase)) return 'is-small';
  const n = String(text || '').length;
  return n <= 42 ? 'is-l' : n <= 72 ? 'is-m' : 'is-s';
}

/** 새 물음 — 같은 질문 안의 꼬리질문이고 내 말(claim)에서 나왔으면 엮기, 질문이 바뀌었으면 주제 이름, 아니면 살짝 올라오기 */
function qsOnNewAsk(layer, L, scene, prevAnswer) {
  const first = qs.qi < 0;
  const sameQ = L.qi === qs.qi;
  qs.qi = L.qi;
  qs.askAt = Date.now();
  const model = typeof qwModel === 'function' ? qwModel(L) : null;
  const claim = model && model.claim ? model.claim : null;
  const key = claim ? `${L.qi}|${claim.round}|${claim.text}` : '';
  const from = qsById('qsFrom');
  if (first) { qsSetFrom(claim); qsSetQ(scene, false); qs.claimKey = key; return; }
  if (sameQ && claim && key !== qs.claimKey) {
    qs.claimKey = key;
    qsWeave(layer, scene, prevAnswer, claim.text);
    return;
  }
  qs.claimKey = key;
  if (!sameQ && typeof qwTopicText === 'function') { qsSetFrom(null); qsTopic(layer, qwTopicText(L), scene); return; }
  if (from && !claim) qsSetFrom(null);
  qsSetQ(scene, true);
}

function qsSetFrom(claim) {
  const from = qsById('qsFrom');
  const thread = qsById('qsThread');
  if (!from) return;
  if (claim) {
    const q = qsById('qsFromQ');
    q.textContent = claim.text;
    q.title = claim.text;
  }
  from.classList.toggle('is-on', !!claim);
  if (thread) thread.classList.toggle('is-on', !!claim);
}

function qsSetQ(scene, animate) {
  const el = qsById('qsQ');
  if (!el) return;
  el.textContent = scene.question;
  qs.sig.qText = scene.question;
  el.classList.remove('is-out', 'is-in');
  if (animate) { void el.offsetWidth; el.classList.add('is-in'); }
}

/** D — 내 답의 claim 에 밑줄 → 질문 퇴장 → 구절이 위 「내 말에서」 자리로 → 연결선 → 새 질문 (합 1.6초, 모두 띠 안) */
function qsWeave(layer, scene, answer, claimText) {
  const say = qsById('qsSay');
  const q = qsById('qsQ');
  if (!say || !q) return;
  qs.weaving = true;
  layer.dataset.qsWeave = '1';
  say.innerHTML = qsAnswerHtml(answer, claimText);
  qs.sig.say = '';
  const mark = say.querySelector('mark.qs-cl');
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const finish = () => {
    qs.weaving = false;
    layer.dataset.qsWeave = '';
    qsSetFrom({ text: claimText });
    qsSetQ(scene, true);
    qs.sig.say = null;
    qsSync();
  };
  if (!mark || reduce) { finish(); return; }
  void say.offsetWidth;
  say.classList.add('is-caught');
  setTimeout(() => q.classList.add('is-out'), 700);
  setTimeout(() => {
    const from = qsById('qsFrom'); const fromQ = qsById('qsFromQ');
    if (!from || !fromQ || !mark.isConnected) { finish(); return; }
    fromQ.textContent = claimText;
    const a = mark.getBoundingClientRect();
    const b = fromQ.getBoundingClientRect();
    const cs = getComputedStyle(mark);
    const fly = document.createElement('p');
    fly.className = 'qs-fly';
    fly.textContent = claimText;
    fly.style.cssText = `left:${a.left}px;top:${a.top}px;font:${cs.font};max-width:${Math.max(a.width, 40)}px;`;
    document.body.appendChild(fly);
    say.classList.add('is-gone');
    const scale = parseFloat(getComputedStyle(fromQ).fontSize) / parseFloat(cs.fontSize);
    requestAnimationFrame(() => { fly.style.transform = `translate(${b.left - a.left}px, ${b.top - a.top}px) scale(${scale})`; fly.style.opacity = '.9'; });
    setTimeout(() => { fly.remove(); say.classList.remove('is-caught', 'is-gone'); finish(); }, 540);
  }, 950);
}

/** E — 질문이 왼쪽으로 빠지고 주제 이름 0.9초 → 새 질문. 웹캠은 그대로 */
function qsTopic(layer, text, scene) {
  const line = qsById('qsLine');
  const card = qsById('qsTopic');
  if (!line || !card || !text) { qsSetQ(scene, true); return; }
  qsById('qsTopicText').textContent = text;
  line.classList.add('is-leaving');
  clearTimeout(qs.topicTimer);
  setTimeout(() => card.classList.add('is-on'), 220);
  qs.topicTimer = setTimeout(() => {
    card.classList.remove('is-on');
    line.classList.remove('is-leaving');
    qsSetQ(scene, true);
  }, 220 + QS_TOPIC_MS);
}

/* ─── 맞추기 ─── */

function qsEnv(L) {
  const live = qsLiveText();
  const micOn = typeof bcMicOn === 'function' && bcMicOn();
  const end = document.querySelector('#bqStage .bc-dock .qa-input-label.is-end span');
  const see = qsById('liveSeeResult');
  return {
    now: Date.now(), askAt: qs.askAt, text: live.final + live.interim,
    sending: typeof bc !== 'undefined' && !!bc.sendAt,
    thinking: !!qsById('coachThinking'),
    micOn, live: { ...live, endNote: end ? end.textContent.trim() : '' },
    hasText: !!(live.final + live.interim).trim(),
    status: (qsById('bqJudgeSay') || {}).textContent || '',
    resultLabel: see ? see.textContent.trim() : '',
    canSwitch: typeof liveCanSwitch === 'function' && liveCanSwitch(),
    stuckItems: qsStuckItems().length > 0,
  };
}

const QS_PRES = { asking: '묻고 있어요', listening: '듣고 있어요', sending: '듣고 있어요', thinking: '생각하고 있어요', encouraging: '같이 찾아봐요', switching: '주제를 바꿔요', done: '수고했어요' };

/** bcSync · bcAutoLoop 에서 — qa.live 와 마이크에서 순간을 하나 정하고, 띠 · 레일 · 행동 줄을 그 순간에 맞춘다 */
function qsSync() {
  const layer = qsLayer();
  const call = layer && layer.querySelector('.bc-call');
  if (!call || !qa.live) return;
  if (layer.dataset.qs !== '1' || !qsById('qsLine')) qsMount(layer, call);
  const L = qa.live;
  const turns = qa.turns || [];
  const env = qsEnv(L);
  const scene = qsScene(L, turns, env);
  if (!scene) return;

  const askKey = `${L.qi}|${scene.ask}`;
  if (askKey !== qs.askKey) {
    const prevAnswer = scene.ask > 0 ? qsLastAnswer(turns.slice(0, scene.ask), -1) : '';
    qs.askKey = askKey;
    qsOnNewAsk(layer, L, scene, prevAnswer);
    env.askAt = qs.askAt;
    Object.assign(scene, qsScene(L, turns, env));
  }
  const phase = qs.weaving ? 'thinking' : scene.phase;
  if (layer.dataset.qsPhase !== phase) layer.dataset.qsPhase = phase;
  if (phase === 'done' && qs.qi !== -2) { qs.qi = -2; qsSetFrom(null); }

  const q = qsById('qsQ');
  if (q) {
    const text = phase === 'done' ? '오늘 질문은 여기까지예요' : scene.question;
    if (!qs.weaving && !q.classList.contains('is-out') && qs.sig.qText !== text) { q.textContent = text; qs.sig.qText = text; }
    const cls = qsQClass(text, phase);
    if (q.dataset.size !== cls) q.dataset.size = cls;
  }
  qsPut(qsById('qsMeta'), 'meta', qsMetaHtml({ ...scene, phase }, L));
  if (!qs.weaving) qsPut(qsById('qsSay'), 'say', qsSayHtml({ ...scene, phase }, env.live));
  bqSet(qsById('qsPresState'), 'textContent', QS_PRES[phase] || '');
  const bird = document.querySelector('#bcHost .bq-bird');
  if (bird && phase === 'encouraging' && bird.dataset.mood !== 'happy') bird.dataset.mood = 'happy';
  if (bird && phase === 'asking' && bird.dataset.mood === 'curious') bird.dataset.mood = '';

  qsPut(qsById('qsAct'), 'act', qs.weaving ? '' : qsActHtml({ ...scene, phase }, env));
  qsPut(qsById('qsAlt'), 'alt', qsAltHtml({ ...scene, phase }, env));
  const aux = qsById('qsAux');
  if (aux) {
    let slot = aux.querySelector('.qs-aux-act');
    if (!slot) { aux.insertAdjacentHTML('afterbegin', '<span class="qs-aux-act"></span>'); slot = aux.querySelector('.qs-aux-act'); }
    qsPut(slot, 'aux', qsAuxHtml({ ...scene, phase }));
  }
  if (phase === 'sending') { const c = layer.querySelector('.qs-count'); if (c && !c.classList.contains('is-run')) requestAnimationFrame(() => c.classList.add('is-run')); }
  if (qs.typing && ['thinking', 'switching', 'done'].includes(phase)) { qs.typing = false; layer.dataset.qsType = ''; }
  if (qs.menu === 'switch' && !env.canSwitch) qsMenu('');
  if (qs.menu && !['asking', 'listening', 'sending', 'encouraging'].includes(phase)) qsMenu('');

  bqSet(qsById('qsHist'), 'textContent', qsHistLabel(L));
  qsPaintRail();
}

window.addEventListener('resize', () => { if (qsById('qsZoom') && !qsById('qsZoom').hidden) qsPlaceZoom(); });
