/**
 * 모바일 체험 투어 #/tour/* — 셸 · 데이터 · 단계 이동 · 시작/자료/끝 화면 (2026-10-11, docs/booth-mobile/README.md).
 *
 * 결선 부스에서 QR 을 찍은 폰 방문객이 /hi 팀 소개 다음에 2~3분 동안 따라가는 화면이다.
 * 10/7 QR 실측 64명 → 덱 선택 14 → 리허설 8 → 분석 3 → 답변 2 — 실제 흐름(카메라·마이크·업로드)에서 97% 가 빠졌다.
 * 그래서 투어는 녹화된 응답만 재생한다: API 호출 0 · 권한 요청 0 · 인앱 브라우저(카카오톡·네이버·인스타)에서도 끝까지 돈다.
 *
 * 구조 — body 위 #tourStage 층 하나(부스 #bqStage 와 같은 이유: 데스크톱 아트보드는 body 를 transform 으로 줄여서
 * fixed 가 창에 안 붙는다). 층 = 위 띠(뒤로 · 단계 막대 n/5 · 닫기→/hi) + 본문(스크롤) + 아래 고정 주 버튼.
 * 일반 앱의 사이드바·탑바는 투어 동안 숨긴다(body.tour-open).
 *
 * 화면 그리기는 TourScreens[화면] = (ctx) => ({ html, foot, tone, mount }) 로 등록한다.
 * 시작 · 자료 · 끝은 이 파일, 발표 · 분석 · 질문 · 리포트는 js/tour_play.js.
 * 순수 판단(시각 → 장·자막·칩, 주소 → 단계, 인앱 판별)은 js/tour_logic.js — tests/js/tour.smoke.mjs 가 잡는다.
 */
(function () {
  'use strict';

  const L = window.TourLogic;
  const STATE_KEY = 'cheokcheok:tour';
  const DATA_DIR = 'data/tour/';
    const Screens = (window.TourScreens = window.TourScreens || {});

  /* ── 작은 도구 ─────────────────────────────────────────────── */

  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ESC[c]);
  const reduced = () => !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  /** 삐약이 한 마리 — 앱 객석과 같은 그림(chatter.js). 표정은 .ch-seat[data-mood] 가 바꾼다 */
  function chick(mood = 'neutral', cls = '') {
    const svg = window.Chatter && window.Chatter.chickSvg ? window.Chatter.chickSvg('solar') : '';
    return `<span class="ch-seat tour-chick ${cls}" data-mood="${esc(mood)}" aria-hidden="true">${svg}</span>`;
  }

  /** 3단계 말 칩 — 좋아요 · 보통 · 더 연습 */
  function levelChip(level, extra = '') {
    const word = L.LEVEL_WORD[level];
    if (!word) return '';
    return `<span class="chip chip-sm st-${L.LEVEL_TONE[level]} tour-level ${extra}">${word}</span>`;
  }

  /** 정직 표시 — 녹화본이면 「미리 녹화한 체험이에요」, 형식 예시면 그것까지 (CLAUDE.md §3-4) */
  function honestNote(tour) {
    const ex = tour && tour.source && tour.source.kind === 'example';
    return `<p class="tour-honest"><span aria-hidden="true">●</span>미리 녹화한 체험이에요${ex ? ' · 형식 예시 데이터로 보여 드려요' : ''}</p>`;
  }

  /* ── 상태(이 탭) ───────────────────────────────────────────── */

  function readState() {
    try {
      const s = JSON.parse(sessionStorage.getItem(STATE_KEY) || '{}');
      return s && typeof s === 'object' ? s : {};
    } catch (_) { return {}; }
  }
  let state = readState();
  function save(patch) {
    state = Object.assign({}, state, patch || {});
    try { sessionStorage.setItem(STATE_KEY, JSON.stringify(state)); } catch (_) { /* 사생활 모드 — 이 탭 메모리로만 */ }
    return state;
  }
  function resetState() {
    state = {};
    try { sessionStorage.removeItem(STATE_KEY); } catch (_) { /* 사생활 모드 */ }
  }

  /* ── 녹화 데이터 ───────────────────────────────────────────── */

  let loading = null;

  async function getJson(path) {
    const r = await fetch(path, { cache: 'no-cache', credentials: 'same-origin' });
    if (!r.ok) throw new Error(`${path} ${r.status}`);
    return r.json();
  }

  /** index.json 이 있으면 그 목록, 없으면 _example.json 하나. 계약에 안 맞는 파일은 빼고, 하나도 없으면 실패 */
  async function fetchTours() {
    let tours = [];
    let idx = null;
    try { idx = await getJson(`${DATA_DIR}index.json`); } catch (_) { idx = null; }
    if (idx) {
      const { ids, inline } = L.indexIds(idx);
      if (inline) tours = [inline];
      else tours = (await Promise.all(ids.map((id) => getJson(`${DATA_DIR}${id}.json`).catch(() => null)))).filter(Boolean);
    }
    if (!tours.filter((t) => !L.tourProblem(t)).length) tours = [await getJson(`${DATA_DIR}_example.json`)];
    const good = tours.filter((t) => !L.tourProblem(t));
    if (!good.length) throw new Error(L.tourProblem(tours[0]) || '투어 파일이 없어요');
    return good;
  }

  function loadTours() {
    if (!loading) loading = fetchTours().catch((e) => { loading = null; throw e; });
    return loading;
  }

  /** 지금 고른 투어 — 고른 게 목록에 없으면 첫째 */
  function currentTour(tours) {
    return tours.find((t) => t.id === state.deck) || tours[0];
  }

  /* ── 퍼널 신호 ─────────────────────────────────────────────── */

  /**
   * 퍼널 신호 — js/funnel.js 의 window.ccFunnel(step, {deck}) 로 보낸다 (POST /api/v1/tour/event, 계약 docs/booth-mobile/funnel-events.md).
   * 화면 이름(deck·present…)은 계약 이름(tour_deck·tour_present…)으로 바꾼다. 같은 탭에서 같은 단계는 ccFunnel 이 한 번만 보낸다.
   * funnel.js 가 안 왔으면(옛 캐시·차단) 조용히 넘긴다 — 신호는 덤이다.
   */
  function funnel(step, deck) {
    try { if (step && typeof window.ccFunnel === 'function') window.ccFunnel(step, deck ? { deck } : undefined); } catch (_) { /* 신호는 덤 */ }
  }
  function signal(screen, deck) {
    if (!state.started) save({ started: Date.now() });
    funnel(L.funnelStep(screen), deck);
  }

  /* ── 층 · 띠 ───────────────────────────────────────────────── */

  const ICON = {
    back: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.6 5.4 8 12l6.6 6.6"/></svg>',
    close: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/></svg>',
  };

  /* 노치 · 홈 막대 자리(env(safe-area-inset-*))는 viewport-fit=cover 일 때만 값이 생긴다. 다른 화면 배치를 안 건드리게 투어 동안만 켠다 */
  const VIEWPORT_TOUR = 'width=device-width, initial-scale=1, viewport-fit=cover';
  let viewportBefore = null;
  function viewportCover(on) {
    const m = document.querySelector('meta[name="viewport"]');
    if (!m) return;
    if (on && viewportBefore == null) { viewportBefore = m.getAttribute('content') || ''; m.setAttribute('content', VIEWPORT_TOUR); }
    if (!on && viewportBefore != null) { m.setAttribute('content', viewportBefore); viewportBefore = null; }
  }

  function layer() {
    let el = document.getElementById('tourStage');
    if (el) return el;
    viewportCover(true);
    el = document.createElement('div');
    el.id = 'tourStage';
    el.className = 'tour';
    el.innerHTML = `
      <header class="tour-top">
        <button class="tour-icon" type="button" data-tour-back aria-label="뒤로 가기">${ICON.back}</button>
        <div class="tour-progress" data-tour-progress></div>
        <a class="tour-icon" href="/hi" data-tour-close aria-label="체험 닫고 팀 소개로 가기">${ICON.close}</a>
      </header>
      <main class="tour-body" data-tour-body tabindex="-1"></main>
      <footer class="tour-foot" data-tour-foot></footer>
      <p class="tour-live" aria-live="polite" data-tour-live></p>`;
    document.body.appendChild(el);
    el.addEventListener('error', imgFailed, true);   // 그림 error 는 거품이 안 올라온다 — 잡기 단계에서 받는다
    el.querySelector('[data-tour-back]').addEventListener('click', goBack);
    // 「팀 소개로 돌아가기」(끝 화면 · 오류 화면) · 위 띠 X — 페이지가 /hi 로 바뀌기 직전이라 신호는 keepalive 로 간다.
    // 링크(href=/hi)를 그대로 따라가면 기록이 하나 더 쌓여 그다음 폰 뒤로가 투어로 돌아왔다 — /hi 기록으로 되돌아가거나 바꿔 간다
    el.addEventListener('click', (e) => {
      const a = e.target.closest && e.target.closest('[data-back-team], [data-tour-close]');
      if (!a || e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.button > 0) return;
      if (a.hasAttribute('data-back-team')) funnel('back_team');
      e.preventDefault();
      closeToHi();
    });
    return el;
  }

  /**
   * 장 그림 · 표지를 못 받으면(부스 와이파이 끊김 · 막힘) 깨진 그림 아이콘 대신 장 제목 카드로 바꾼다.
   * 한 번은 다시 받아 본다. 투어 흐름은 그대로 — JSON 실패는 오류 화면이지만 그림 하나로 체험을 멈추지 않는다.
   * 바꿀 글은 <img data-fallback="3장 · 제목">. 자리(클래스 · data-no)는 그대로 넘겨서 발표 장 넘기기가 계속 돈다.
   */
  const IMG_RETRY_MS = 800;
  function imgFailed(e) {
    const img = e.target;
    if (!img || img.tagName !== 'IMG' || img.dataset.fallback == null) return;
    if (!img.dataset.retried) {
      img.dataset.retried = '1';
      const src = img.getAttribute('src') || '';
      if (src) setTimeout(() => { if (img.isConnected) img.src = src + (src.includes('?') ? '&' : '?') + 'retry=1'; }, IMG_RETRY_MS);
      return;
    }
    const box = document.createElement('div');
    box.className = `${img.className} tour-img-fallback`;
    for (const k of Object.keys(img.dataset)) if (k !== 'fallback' && k !== 'retried') box.dataset[k] = img.dataset[k];
    const hidden = img.getAttribute('aria-hidden');
    if (hidden) box.setAttribute('aria-hidden', hidden);
    box.setAttribute('role', 'img');
    box.setAttribute('aria-label', img.getAttribute('alt') || img.dataset.fallback || '그림');
    const t = document.createElement('span');
    t.textContent = img.dataset.fallback || '그림을 불러오지 못했어요';
    box.appendChild(t);
    img.replaceWith(box);
  }

  function progressHtml(screen) {
    const n = L.stepIndex(screen);
    if (!n) return '';
    const label = L.STEPS[n - 1].label;
    const bars = L.STEPS.map((s, i) => `<li class="${i + 1 < n ? 'is-done' : i + 1 === n ? 'is-now' : ''}"></li>`).join('');
    return `<div role="progressbar" aria-valuemin="1" aria-valuemax="${L.STEPS.length}" aria-valuenow="${n}"
                 aria-valuetext="${L.STEPS.length}단계 가운데 ${n}단계 · ${label}" class="tour-progress-in">
              <ol class="tour-bar" aria-hidden="true">${bars}</ol>
              <span class="tour-count"><b>${n}</b>/${L.STEPS.length} · ${label}</span>
            </div>`;
  }

  /* ── 단계 이동 ─────────────────────────────────────────────── */

  let lastScreen = null;
  let leaveHook = null;

  const histState = () => (history.state && typeof history.state === 'object' ? history.state : {});

  /**
   * 앞으로 — 투어 안에서 쌓은 기록임을 표시해 두고(history.state.tourIn · depth), 뒤로 버튼이 그걸 보고 history.back() 한다.
   * hi 는 「이 사슬이 /hi 바로 뒤 기록에서 시작했다」 는 표시 — index.html 머리 스크립트가 첫 기록에 남기고 여기서 이어 준다
   */
  function go(screen, q = 0, { replace = false } = {}) {
    const hash = L.tourHash(screen, q);
    if (location.hash === hash) { render(); return; }
    const cur = histState();
    const depth = Number(cur.depth) || 0;
    if (replace) history.replaceState({ tourIn: !!cur.tourIn, depth, hi: !!cur.hi }, '', hash);
    else history.pushState({ tourIn: true, depth: depth + 1, hi: !!cur.hi }, '', hash);
    if (typeof window.route === 'function') window.route(); else render();
  }

  /** 팀 소개로 — 판단은 TourLogic.closeAction. /hi 바로 뒤에서 시작한 사슬이면 쌓은 만큼 되돌아가 그 /hi 기록으로,
   *  아니면 /hi 로 바꿔 간다(기록을 늘리지 않는다). referrer 는 문서 내내 /hi 라 믿지 않는다 (10-12 2차 flow-regression-inapp-r2-1) */
  function closeToHi() {
    const act = L.closeAction(history.state);
    if (act.kind === 'go') history.go(act.delta);
    else location.replace('/hi');
  }

  /** 뒤로 — 판단은 TourLogic.backAction (층이 떠 있으면 층만 · 시작 안내의 앞은 팀 소개 · 기록을 하나 더 쌓지 않는다) */
  function goBack() {
    const cur = L.parseTourHash(location.hash) || { screen: 'intro', q: 0 };
    const st = histState();
    const act = L.backAction({ screen: cur.screen, q: cur.q, tourIn: !!st.tourIn, fromHi: !!st.hi, overlay: overlayOpen() });
    if (act.kind === 'overlay') dismissOverlay();
    else if (act.kind === 'history') history.back();
    else if (act.kind === 'screen') go(act.screen, act.q, { replace: true });
    else closeToHi();
  }

  /** 앱 route() 가 투어 밖으로 나갈 때 부른다 — 층 · 타이머를 걷고 사이드바를 돌려놓는다 */
  function teardown() {
    if (leaveHook) { try { leaveHook(); } catch (_) { /* 다음 화면이 그린다 */ } leaveHook = null; }
    closeSheet(false);
    closeZoom(false);
    const el = document.getElementById('tourStage');
    if (el) el.remove();
    viewportCover(false);
    document.body.classList.remove('tour-open');
    lastScreen = null;
  }

  /* ── 그리기 ────────────────────────────────────────────────── */

  function ctxFor(tours, tour, at) {
    return {
      L, tours, tour, at, save, go, esc, chick, levelChip, honestNote, reduced, openSheet, restart, openRehearsal, openZoom,
      get state() { return state; },   // save() 가 새 객체로 갈아 끼우므로 늘 지금 값을 읽는다
    };
  }

  function errorView(msg) {
    return {
      tone: 'light',
      html: `<section class="tour-screen tour-center">
          ${chick('neutral', 'is-lg')}
          <h1 class="tour-h1" tabindex="-1">체험을 불러오지 못했어요</h1>
          <p class="tour-sub">잠깐 연결이 끊겼을 수 있어요. 다시 불러오면 이어서 볼 수 있어요.</p>
          <p class="tour-cause">${esc(msg)}</p>
        </section>`,
      foot: `<button class="tour-cta" type="button" data-tour-retry>다시 불러오기</button>
             <a class="tour-cta is-sub" href="/hi" data-back-team>팀 소개로 돌아가기</a>`,
      mount(root) {
        root.querySelector('[data-tour-retry]').addEventListener('click', () => { loading = null; render(); });
      },
    };
  }

  function paint(el, at, view) {
    const body = el.querySelector('[data-tour-body]');
    const foot = el.querySelector('[data-tour-foot]');
    // 단계 순서 × 10 + 질문 번호 — 질문 1 → 2 도 「앞으로」 로 움직이고 제목에 초점이 간다
    const key = L.SCREENS.indexOf(at.screen) * 10 + (at.q || 0);
    const from = lastScreen == null ? -1 : lastScreen;
    const to = key;
    el.dataset.screen = at.screen;
    el.dataset.tone = view.tone || 'light';
    el.dataset.dir = from < 0 || from === to ? 'none' : (to > from ? 'fwd' : 'back');
    el.querySelector('[data-tour-progress]').innerHTML = progressHtml(at.screen);
    body.innerHTML = view.html;
    foot.innerHTML = view.foot || '';
    foot.hidden = !view.foot;
    body.scrollTop = 0;
    lastScreen = key;
    if (typeof view.mount === 'function') leaveHook = view.mount(el) || null;
    // 화면이 바뀌면 제목으로 초점을 옮긴다 — 화면 읽기 프로그램이 새 화면을 처음부터 읽게(스크롤은 그대로)
    const h = body.querySelector('h1');
    if (h && from !== to) { h.setAttribute('tabindex', '-1'); try { h.focus({ preventScroll: true }); } catch (_) { /* 옛 브라우저 */ } }
  }

  let renderSeq = 0;
  async function render() {
    const at = L.parseTourHash(location.hash);
    if (!at) return;
    if (at.alias) { history.replaceState(history.state, '', L.tourHash(at.screen, at.q)); }
    const el = layer();
    document.body.classList.add('tour-open');
    document.documentElement.classList.remove('tour-boot', 'tour-boot-fail');   // index.html 이 앱 셸을 가려 둔 표시 — 이제 투어 층이 덮는다
    if (leaveHook) { try { leaveHook(); } catch (_) { /* 앞 화면 정리 실패는 무시 */ } leaveHook = null; }
    closeSheet(false);
    closeZoom(false);
    const seq = ++renderSeq;
    if (!el.dataset.screen) {
      el.dataset.tone = 'light';
      el.querySelector('[data-tour-body]').innerHTML = '<p class="tour-wait" role="status">체험을 준비하고 있어요…</p>';
    }
    let tours;
    try { tours = await loadTours(); } catch (e) {
      if (seq === renderSeq) paint(el, at, errorView(e && e.message ? e.message : String(e)));
      return;
    }
    if (seq !== renderSeq) return;   // 그 사이 다른 단계로 갔다
    const tour = currentTour(tours);
    if (!state.deck && tour) save({ deck: tour.id });
    const fn = Screens[at.screen] || Screens.intro;
    let view;
    try { view = fn(ctxFor(tours, tour, at)); } catch (e) {
      console.warn('[tour] 화면을 그리지 못했어요', e);
      view = errorView('화면을 그리다 멈췄어요. 다시 불러오면 이어서 볼 수 있어요.');
    }
    paint(el, at, view);
    signal(at.screen, tour && tour.id);
  }

  /** 처음부터 다시 — 상태를 지우고 첫 시작 안내 기록으로 되돌아간다(그 앞은 팀 소개). 끝 · 리포트 기록 위에 시작 안내를 또 쌓으면
   *  시작 안내의 ‹ 가 끝 화면 → 리포트로 갔다 (10-12 점검 flow-regression-inapp-r1-3) */
  function restart() {
    resetState();
    const act = L.restartAction(history.state && history.state.depth);
    if (act.kind === 'go') history.go(act.delta);
    else go('intro', 0, { replace: true });
  }

  /* ── 실제 흐름으로 — 인앱 브라우저면 바깥 브라우저 안내 ──────── */

  /**
   * 바깥 브라우저 안내 문구 — /hi(intro.html · intro.js)의 같은 시트와 글자까지 같게 둔다(tests/test_booth_mobile_contract.py 가 대조).
   * iOS 메뉴 자리는 앱마다 다르다(카톡 오른쪽 아래 · 인스타 오른쪽 위 …, 실기기 미확인) — 자리를 말하지 않고 「메뉴(···)」 로만 (10-12 점검)
   */
  const INAPP_COPY = {
    title: 'Safari나 Chrome에서 열면 돼요',
    iosTip: '앱 메뉴(<b>···</b>)에서 <b>Safari로 열기</b>를 고르거나, 주소를 복사해 Safari에 붙여 넣어요.',
    here: '여기서 계속 열기',
  };

  /**
   * 리허설 첫 화면의 「나가기」 가 앱 홈 대신 투어 끝 화면으로 오게 — 리허설 기록에 rhFrom:'tour' 를 남기고(나가기가 history.back() 으로
   * 끝 화면 기록에 돌아온다), 기록이 바뀐 뒤(#/rehearsal/occ)를 위해 이 탭에 'tour' 도 적는다 (js/rehearsal.js rhExitClicked).
   * location.hash = … 로 가면 state=null 기록이 쌓여, 나가기 뒤 「팀 소개로」 가 리허설로 되돌아갔다 (10-12 2차 flow-regression-inapp-r2-1).
   * 바깥 브라우저로 여는 길은 이 탭과 상관없어 표시하지 않는다 — 실제로 여기서 들어갈 때만 (flow-regression-inapp-r2-6)
   */
  const RH_FROM_KEY = 'cheokcheok:rh-from';
  function enterRehearsal() {
    try { sessionStorage.setItem(RH_FROM_KEY, 'tour'); } catch (_) { /* 사생활 모드 — 나가기는 기록으로만 */ }
    const cur = histState();
    const onSheet = cur.overlay === 'sheet';
    const st = { rhFrom: 'tour', hi: !!cur.hi, depth: (Number(cur.depth) || 0) + (onSheet ? 0 : 1) };
    // 시트가 쌓은 기록은 리허설 기록으로 바꿔 쓴다 — 리허설에서 뒤로 가면 시트 없는 끝 화면
    if (onSheet) { closeSheet(false); history.replaceState(st, '', '#/rehearsal'); }
    else history.pushState(st, '', '#/rehearsal');
    if (typeof window.route === 'function') window.route(); else location.hash = '#/rehearsal';
  }

  function openRehearsal() {
    const ua = navigator.userAgent || '';
    funnel('try_real');
    if (!L.inAppKind(ua)) { enterRehearsal(); return; }
    funnel('inapp_notice');
    const url = `${location.origin}/rehearsal`;
    const ext = L.externalOpenUrl(url, ua);
    const ios = L.platformOf(ua) === 'ios';
    openSheet({
      title: INAPP_COPY.title,
      body: `<p>지금 보는 앱 안의 브라우저에서는 카메라와 마이크를 쓸 수 없어요. 직접 해 보기는 카메라 앞에서 발표하는 화면이에요.</p>
             ${ios && !ext ? `<p class="tour-sheet-tip">${INAPP_COPY.iosTip}</p>` : ''}
             <p class="tour-sheet-url"><span>주소</span><b>${esc(url.replace(/^https?:\/\//, ''))}</b></p>`,
      actions: [
        ext ? `<a class="tour-cta" href="${esc(ext)}">${L.inAppKind(ua) === 'kakao' ? '다른 브라우저로 열기' : 'Chrome으로 열기'}</a>` : '',
        `<button class="tour-cta${ext ? ' is-sub' : ''}" type="button" data-copy="${esc(url)}">주소 복사하기</button>`,
        `<button class="tour-cta is-text" type="button" data-here>${INAPP_COPY.here}</button>`,
      ].join(''),
      mount(sheet) {
        const copy = sheet.querySelector('[data-copy]');
        copy.addEventListener('click', async () => {
          let ok = false;
          try { await navigator.clipboard.writeText(copy.dataset.copy); ok = true; } catch (_) { ok = false; }
          copy.textContent = ok ? '주소를 복사했어요' : '주소를 길게 눌러 복사해요';
          announce(copy.textContent);
        });
        sheet.querySelector('[data-here]').addEventListener('click', () => enterRehearsal());
      },
    });
  }

  /* ── 층(바텀 시트 · 크게 보기)과 뒤로 가기 ──────────────────────
   * 층을 열면 기록을 하나 쌓는다(state.overlay). 폰 뒤로 · 위 띠 ‹ 는 그 기록만 되돌려 층만 닫고 화면은 그대로 둔다.
   * 기록 없이 열었더니 크게 보기에서 뒤로를 누르면 발표 화면을 건너 자료 고르기로, 시트에서는 끝 화면을 잃고 리포트로 갔다
   * (10-12 2차 layout-touch-a11y-r2-1 · flow-regression-inapp-r2-6). 닫기 버튼 · Esc · 바깥 누르기도 history.back() 으로 닫아 기록을 맞춘다.
   * 화면이 바뀌며 걷는 길(render · teardown 의 closeSheet(false) · closeZoom(false))은 기록을 건드리지 않는다 */
  function overlayOpen() {
    const el = document.getElementById('tourStage');
    if (!el) return '';
    return el.querySelector('.tour-zoom') ? 'zoom' : (el.querySelector('.tour-sheet-wrap') ? 'sheet' : '');
  }
  function pushOverlay(kind) {
    const cur = histState();
    if (cur.overlay) history.replaceState(Object.assign({}, cur, { overlay: kind }), '');
    else history.pushState(Object.assign({}, cur, { overlay: kind, depth: (Number(cur.depth) || 0) + 1 }), '');
  }
  /** 사용자가 층을 닫는다 — 층이 쌓은 기록이면 되돌리고(popstate 가 닫는다), 아니면 바로 닫는다 */
  function dismissOverlay() {
    if (histState().overlay) { history.back(); return; }
    closeSheet();
    closeZoom();
  }
  window.addEventListener('popstate', () => {
    const want = histState().overlay || '';
    if (want !== 'sheet') closeSheet();
    if (want !== 'zoom') closeZoom();
  });

  /* ── 바텀 시트 — 사용자가 누른 뒤에만 연다(진입 즉시 시트 금지 · CLAUDE.md §3-1) ── */

  let sheetFrom = null;
  function openSheet({ title, body, actions, mount }) {
    const el = layer();
    closeSheet(false);
    sheetFrom = document.activeElement;
    pushOverlay('sheet');
    const wrap = document.createElement('div');
    wrap.className = 'tour-sheet-wrap';
    wrap.innerHTML = `
      <div class="tour-scrim" data-sheet-close></div>
      <section class="tour-sheet" role="dialog" aria-modal="true" aria-labelledby="tourSheetTitle">
        <span class="tour-grip" aria-hidden="true"></span>
        <h2 id="tourSheetTitle" class="tour-sheet-title">${esc(title)}</h2>
        <div class="tour-sheet-body">${body}</div>
        <div class="tour-sheet-actions">${actions}
          <button class="tour-cta is-text" type="button" data-sheet-close>닫기</button>
        </div>
      </section>`;
    el.appendChild(wrap);
    el.classList.add('has-sheet');
    wrap.querySelectorAll('[data-sheet-close]').forEach((b) => b.addEventListener('click', dismissOverlay));
    wrap.addEventListener('keydown', sheetKeys);
    const sheet = wrap.querySelector('.tour-sheet');
    if (typeof mount === 'function') mount(sheet);
    const first = sheet.querySelector('a, button');
    requestAnimationFrame(() => { wrap.classList.add('is-open'); if (first) first.focus({ preventScroll: true }); });
  }

  function sheetKeys(e) {
    if (e.key === 'Escape') { e.preventDefault(); dismissOverlay(); return; }
    if (e.key !== 'Tab') return;
    const items = Array.from(e.currentTarget.querySelectorAll('.tour-sheet a, .tour-sheet button'));
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  function closeSheet(restoreFocus = true) {
    const el = document.getElementById('tourStage');
    const wrap = el && el.querySelector('.tour-sheet-wrap');
    if (!wrap) return;
    wrap.remove();
    el.classList.remove('has-sheet');
    if (restoreFocus && sheetFrom && sheetFrom.focus) sheetFrom.focus({ preventScroll: true });
    sheetFrom = null;
  }

  /* ── 자료 크게 보기 — 960px 그림을 폰 폭(335px)에 줄이면 표 · 그래프 글자가 3~6px 라 못 읽었다 (10-12 점검) ── */

  let zoomFrom = null;
  /** 장 그림 한 장을 화면 가득 — 처음엔 폭 맞춤, 「2배로 보기」 로 키워 밀어서 본다. 두 손가락 확대도 막지 않는다 */
  function openZoom(src, label) {
    const el = layer();
    closeZoom(false);
    zoomFrom = document.activeElement;
    pushOverlay('zoom');
    const wrap = document.createElement('div');
    wrap.className = 'tour-zoom';
    wrap.setAttribute('role', 'dialog');
    wrap.setAttribute('aria-modal', 'true');
    wrap.setAttribute('aria-label', `${label} 크게 보기`);
    wrap.innerHTML = `
      <div class="tour-zoom-bar">
        <span class="tour-zoom-title">${esc(label)}</span>
        <button class="tour-zoom-btn" type="button" data-zoom-size aria-pressed="false">2배로 보기</button>
        <button class="tour-icon tour-zoom-close" type="button" data-zoom-close aria-label="크게 보기 닫기">${ICON.close}</button>
      </div>
      <div class="tour-zoom-pane" tabindex="0"><img src="${esc(src)}" alt="${esc(label)}" draggable="false"></div>`;
    el.appendChild(wrap);
    const size = wrap.querySelector('[data-zoom-size]');
    size.addEventListener('click', () => {
      const big = wrap.classList.toggle('is-big');
      size.textContent = big ? '화면에 맞추기' : '2배로 보기';
      size.setAttribute('aria-pressed', big ? 'true' : 'false');
    });
    wrap.querySelector('[data-zoom-close]').addEventListener('click', dismissOverlay);
    wrap.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); dismissOverlay(); }
    });
    requestAnimationFrame(() => wrap.querySelector('[data-zoom-close]').focus({ preventScroll: true }));
  }
  function closeZoom(restoreFocus = true) {
    const wrap = document.querySelector('#tourStage .tour-zoom');
    if (!wrap) return;
    wrap.remove();
    if (restoreFocus && zoomFrom && zoomFrom.focus) zoomFrom.focus({ preventScroll: true });
    zoomFrom = null;
  }

  function announce(text) {
    const live = document.querySelector('#tourStage [data-tour-live]');
    if (live) { live.textContent = ''; setTimeout(() => { live.textContent = text; }, 30); }
  }

  /* ── 화면: 시작 안내 ───────────────────────────────────────── */

  Screens.intro = (c) => ({
    tone: 'light',
    html: `<section class="tour-screen tour-intro">
        ${chick('neutral', 'is-lg')}
        <p class="tour-eyebrow">척척발표 둘러보기</p>
        <h1 class="tour-h1">발표 한 편을<br>AI 코치와 따라가 봐요</h1>
        <p class="tour-sub">미리 녹화한 발표로 2~3분이면 끝나요. 카메라·마이크는 켜지 않아요.</p>
        <ol class="tour-steps">
          ${L.STEPS.map((s, i) => `<li><span class="tour-steps-n">${i + 1}</span><div><b>${esc(INTRO_LINES[s.id][0])}</b><small>${esc(INTRO_LINES[s.id][1])}</small></div></li>`).join('')}
        </ol>
      </section>`,
    foot: '<button class="tour-cta" type="button" data-next>둘러보기 시작</button>',
    mount(root) { root.querySelector('[data-next]').addEventListener('click', () => c.go('deck')); },
  });

  const INTRO_LINES = {
    deck: ['자료 고르기', '발표할 자료를 골라요'],
    present: ['발표 보기', 'AI가 발표를 들으며 보는 것을 따라가요'],
    analysis: ['분석 보기', '시간 · 말 속도 · 빠진 내용을 짚어요'],
    qa: ['예상 질문 받기', '잘한 답과 엉성한 답을 비교해요'],
    report: ['리포트 받기', '다음에 무엇을 연습할지 알려 줘요'],
  };

  /* ── 화면: 자료 고르기 ─────────────────────────────────────── */

  Screens.deck = (c) => {
    const cards = c.tours.map((t) => {
      const on = t.id === c.tour.id;
      return `<label class="tour-deck${on ? ' is-on' : ''}">
          <input type="radio" name="tourDeck" value="${esc(t.id)}"${on ? ' checked' : ''}>
          <img class="tour-deck-cover" src="${esc(t.deck.cover || (t.deck.slides[0] || {}).image || '')}" alt="" data-fallback="표지" loading="lazy" decoding="async">
          <span class="tour-deck-text">
            <b>${esc(t.deck.title)}</b>
            ${t.deck.subtitle ? `<small>${esc(t.deck.subtitle)}</small>` : ''}
            <em>${t.deck.slides.length}장 · ${L.durationText(t.present.duration_sec)} 발표</em>
          </span>
        </label>`;
    }).join('');
    const strip = c.tour.deck.slides.map((s) => `
        <figure class="tour-strip-item">
          <img src="${esc(s.image)}" alt="${s.no}장 · ${esc(s.title)}" data-fallback="${s.no}장 · ${esc(s.title)}" loading="lazy" decoding="async">
          <figcaption><b>${s.no}</b>${esc(s.title)}</figcaption>
        </figure>`).join('');
    return {
      tone: 'light',
      html: `<section class="tour-screen">
          <h1 class="tour-h1">발표할 자료를 골라요</h1>
          <p class="tour-sub">고른 자료로 녹화한 발표를 보여 드려요.</p>
          <fieldset class="tour-decks"><legend class="sr-only">발표 자료</legend>${cards}</fieldset>
          <h2 class="tour-h2">자료 미리 보기 <small>옆으로 밀어 넘겨요</small></h2>
          <div class="tour-strip" tabindex="0" role="group" aria-label="${esc(c.tour.deck.title)} 장 미리 보기">${strip}</div>
          ${c.honestNote(c.tour)}
        </section>`,
      foot: '<button class="tour-cta" type="button" data-next>이 자료로 발표해 볼게요</button>',
      mount(root) {
        root.querySelectorAll('input[name="tourDeck"]').forEach((r) => r.addEventListener('change', () => {
          if (r.value === c.state.deck) return;
          c.save({ deck: r.value, picks: {}, presentT: 0, revealed: false });
          render();
        }));
        root.querySelector('[data-next]').addEventListener('click', () => c.go('present'));
      },
    };
  };

  /* ── 화면: 끝 ──────────────────────────────────────────────── */

  Screens.done = (c) => ({
    tone: 'light',
    html: `<section class="tour-screen tour-center tour-done">
        ${chick('happy', 'is-lg')}
        <h1 class="tour-h1">체험을 마쳤어요</h1>
        <p class="tour-sub">내 발표 자료를 올리면 카메라 앞에서 연습하고, 방금 본 분석과 질문을 똑같이 받을 수 있어요.</p>
        <ul class="tour-done-list">
          <li>PDF 나 PPT 자료 하나면 돼요</li>
          <li>카메라·마이크 권한이 필요해요</li>
        </ul>
      </section>`,
    foot: `<button class="tour-cta" type="button" data-real>내 자료로 직접 해 보기</button>
           <div class="tour-foot-row">
             <a class="tour-cta is-sub" href="/hi" data-back-team>팀 소개로 돌아가기</a>
             <button class="tour-cta is-sub" type="button" data-again>처음부터 다시</button>
           </div>`,
    mount(root) {
      root.querySelector('[data-real]').addEventListener('click', () => c.openRehearsal());
      root.querySelector('[data-again]').addEventListener('click', () => c.restart());
    },
  });

  /* ── 앱과 잇는 곳 ──────────────────────────────────────────── */

  /** app.js routes.tour 가 부른다 */
  window.renderTour = function renderTour() {
    const app = document.getElementById('app');
    if (app) { app.className = 'narrow'; app.innerHTML = ''; }
    render();
  };
  /** app.js route() 가 화면을 바꿀 때마다 부른다 — 투어 밖이면 층을 걷는다 */
  window.tourOnRoute = function tourOnRoute(key) {
    if (key !== 'tour') teardown();
  };
  /** tour_play.js 가 쓰는 것 */
  window.TourShell = { announce, render };
})();
