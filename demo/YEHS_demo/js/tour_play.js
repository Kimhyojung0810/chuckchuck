/**
 * 모바일 체험 투어 — 발표 · 분석 · 질문 · 리포트 화면 (js/tour.js 의 TourScreens 에 등록한다).
 *
 * 모두 녹화 데이터(data/tour/<id>.json, docs/booth-mobile/tour-schema.md)만 그린다. 서버에 묻지 않는다.
 *  · 발표: 장 그림 + 넘기기(밀기 · 좌우 1/3 누르기 · ‹ › 버튼 · 막대 끌기) + 녹화된 넘김 시각대로 자동 재생(2배속).
 *          받아쓴 말이 자막으로, 코칭 칩이 at_sec 에 「지금 여기서 AI가 이렇게 봐요」 로 뜬다.
 *  · 분석: 처음 한 번만 1.5초 연출(건너뛰기 가능) → 요약 · 장별 시간 · 말 속도 · 군더더기 · 주장 구조.
 *  · 질문: 삐약이가 묻고 → 「잘 답한 답」·「엉성한 답」 중 하나 → 판정 카드와 근거 줄(몇 장 몇 번째 줄 · 이유) → 다음 질문.
 *  · 리포트: 3단계 말 평가 + 다음 연습.
 * 장 넘기기 몸짓은 vision_rehearsal.js 의 10-08 교훈을 따른다 — 자료 칸은 touch-action:none + pointer capture
 * (pan-y 로 두면 손가락이 조금만 세로로 흔들려도 브라우저가 몸짓을 가져가 pointercancel 로 끝났다).
 */
(function () {
  'use strict';

  const Screens = (window.TourScreens = window.TourScreens || {});
  const L = window.TourLogic;
  const Shell = () => window.TourShell || { announce() {}, render() {} };
  /** 녹화 글을 그릴 때 — 이스케이프하고, 숫자와 단위 사이는 줄이 안 바뀌게(「1 / mg/L」 · 「p < / .05」 가 갈라졌다, 10-12 2차 r2-9) */
  const txt = (c, s) => c.esc(L.keepUnits(s));

  const PLAY_SPEED = 2;          // 녹화 1초 = 화면 0.5초 — 1분 36초 발표가 48초에 끝나 전체 투어가 2~3분 안에 든다
  const SWIPE_MIN = 36;          // 밀기로 볼 최소 가로 이동(px)
  const TAP_MAX = 12;            // 누르기로 볼 최대 이동(px)
  const TAP_MS = 600;
  const REVEAL_MS = 1500;        // 분석 연출 길이(처음 한 번만)
  const SAVE_EVERY_MS = 1000;

  /* ── 발표 ─────────────────────────────────────────────────── */

  /** 코칭 칩이 없을 때 코치 카드 — [큰 줄, 작은 줄] */
  const IDLE_CHIP = {
    listen: ['발표를 듣고 있어요', '말 속도 · 군더더기 · 장마다 쓴 시간을 같이 봐요'],
    paused: ['잠깐 멈췄어요', '이어 보기를 누르면 계속 들어요'],
    end: ['발표를 다 들었어요', '분석 보기를 누르면 결과가 나와요'],
  };
  const ARROW_L = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.6 5.4 8 12l6.6 6.6"/></svg>';
  const ARROW_R = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.4 5.4 16 12l-6.6 6.6"/></svg>';

  Screens.present = (c) => {
    const p = c.tour.present, d = c.tour.deck, dur = p.duration_sec;
    const slides = d.slides.map((s) => `
        <img class="tp-slide" data-no="${s.no}" src="${c.esc(s.image)}" alt="${s.no}장 · ${c.esc(s.title)}" data-fallback="${s.no}장 · ${c.esc(s.title)}" draggable="false" decoding="async">`).join('');
    const ticks = p.slides.slice(1).map((s) => `<i class="tp-tick" style="left:${(s.start_sec / dur) * 100}%"></i>`).join('');
    const marks = (p.coaching_chips || []).map((ch) => `<i class="tp-mark" data-at="${ch.at_sec}" style="left:${(ch.at_sec / dur) * 100}%"></i>`).join('');
    return {
      tone: 'dark',
      html: `<section class="tour-screen tour-present">
          <h1 class="sr-only">녹화한 발표 보기 — ${c.esc(d.title)}</h1>
          <div class="tp-stage" data-stage>
            <div class="tp-track">${slides}</div>
          </div>
          <div class="tp-time">
            <button class="tp-nav" type="button" data-turn="-1" aria-label="앞 장">${ARROW_L}</button>
            <div class="tp-mid">
              <div class="tp-rail">
                ${ticks}${marks}
                <input class="tp-seek" type="range" min="0" max="${dur}" step="0.5" value="0" data-seek aria-label="발표 위치">
              </div>
              <span class="tp-clock" data-clock></span>
            </div>
            <button class="tp-nav" type="button" data-turn="1" aria-label="다음 장">${ARROW_R}</button>
          </div>
          <div class="tp-coach" data-coach>
            ${c.chick('neutral', 'tp-coach-chick')}
            <div class="tp-coach-text" aria-live="polite">
              <p class="tp-eyebrow">지금 여기서 AI가 이렇게 봐요</p>
              <b class="tp-chip" data-chip>발표를 듣고 있어요</b>
              <small data-looks></small>
            </div>
            <span class="tp-coach-count" data-chip-count></span>
          </div>
          <div class="tp-caption">
            <span class="tp-cap-label">받아쓴 말</span>
            <p data-caption>&nbsp;</p>
          </div>
          <p class="tp-hint">자료를 옆으로 밀거나 ‹ ›를 눌러 장을 넘겨요. 가운데를 누르면 크게 봐요</p>
          <button class="tour-cta is-text tp-zoom" type="button" data-zoom>자료 크게 보기</button>
          ${c.honestNote(c.tour)}
        </section>`,
      foot: `<div class="tour-foot-row">
          <button class="tour-cta is-sub tp-play" type="button" data-play>멈추기</button>
          <button class="tour-cta" type="button" data-next>분석 보기</button>
        </div>`,
      mount: (root) => mountPresent(root, c),
    };
  };

  function mountPresent(root, c) {
    const p = c.tour.present, d = c.tour.deck, dur = p.duration_sec;
    const $ = (s) => root.querySelector(s);
    const stage = $('[data-stage]');
    const seek = $('[data-seek]');
    const playBtn = $('[data-play]');
    let t = Math.min(dur, Math.max(0, Number(c.state.presentT) || 0));
    let playing = t < dur;
    let shownNo = 0;
    let liveKey = '';
    let raf = 0, last = 0, lastSave = 0;

    function showSlide(no) {
      if (no === shownNo) return;
      const dir = no > shownNo ? 1 : -1;
      root.querySelectorAll('.tp-slide').forEach((img) => {
        const n = Number(img.dataset.no);
        img.classList.toggle('is-cur', n === no);
        img.classList.toggle('is-past', n < no);
        img.setAttribute('aria-hidden', n === no ? 'false' : 'true');
      });
      stage.dataset.dir = dir > 0 ? 'fwd' : 'back';
      shownNo = no;
    }

    function showChip() {
      const { live, seen, total } = L.chipAt(p, t);
      root.querySelectorAll('.tp-mark').forEach((m) => m.classList.toggle('is-seen', Number(m.dataset.at) <= t));
      $('[data-chip-count]').textContent = total ? `${seen}/${total}` : '';
      // 칩이 없을 때는 지금 상태를 정직하게 — 멈췄는데 「발표를 듣고 있어요」 로 남아 있었다 (10-12 점검)
      const idle = live ? '' : (t >= dur ? 'end' : (playing ? 'listen' : 'paused'));
      const key = live ? `${live.at_sec}:${live.kind}` : idle;
      if (key === liveKey) return;
      liveKey = key;
      const coach = $('[data-coach]');
      const kind = live ? (L.CHIP_KIND[live.kind] || L.CHIP_KIND.listen) : null;
      coach.classList.toggle('is-live', !!live);
      coach.dataset.kind = live ? live.kind : '';
      coach.querySelector('.ch-seat').dataset.mood = kind ? kind.mood : 'neutral';
      $('[data-chip]').textContent = live ? live.text : IDLE_CHIP[idle][0];
      $('[data-looks]').textContent = kind ? kind.looks : IDLE_CHIP[idle][1];
      if (live && !c.reduced()) { coach.classList.remove('is-pop'); void coach.offsetWidth; coach.classList.add('is-pop'); }
    }

    function update() {
      showSlide(L.slideAt(p, t));
      const cap = L.captionAt(p, t);
      const capEl = $('[data-caption]');
      const text = cap ? cap.text : '';
      // 받아쓴 말이 없으면 빈 상자 대신 회색 한 줄 — 멈추고 장을 넘기면 빈 칸만 보였다
      if (capEl.dataset.text !== text) {
        capEl.dataset.text = text;
        capEl.textContent = text || '이 장에서는 아직 말하지 않았어요';
        capEl.classList.toggle('is-empty', !text);
      }
      showChip();
      seek.value = String(t);
      seek.style.setProperty('--p', `${(t / dur) * 100}%`);
      seek.setAttribute('aria-valuetext', `${L.clock(t)} · ${shownNo}장`);
      // 장 번호는 자료 그림 위가 아니라 시계 줄에 — 그림 구석의 자료 쪽 번호를 가렸다 (360 캡처)
      $('[data-clock]').innerHTML = `<b data-no-label>${shownNo}</b>/${d.slides.length}장 · ${L.clock(t)} / ${L.clock(dur)}${playing ? ` <small>${PLAY_SPEED}배속</small>` : ''}`;
      playBtn.textContent = playing ? '멈추기' : (t >= dur ? '다시 보기' : '이어 보기');
      playBtn.setAttribute('aria-label', playing ? '자동 재생 멈추기' : (t >= dur ? '발표 처음부터 다시 보기' : '자동 재생 이어 보기'));
      root.querySelector('[data-next]').classList.toggle('is-ready', t >= dur);
    }

    function persist(force) {
      const now = performance.now();
      if (!force && now - lastSave < SAVE_EVERY_MS) return;
      lastSave = now;
      c.save({ presentT: Math.round(t * 10) / 10 });
    }

    function tick(now) {
      raf = 0;
      if (!playing) return;
      const dt = Math.min(0.25, Math.max(0, (now - last) / 1000));   // 탭을 숨겼다 돌아와도 한꺼번에 건너뛰지 않게
      last = now;
      t = Math.min(dur, t + dt * PLAY_SPEED);
      if (t >= dur) { playing = false; Shell().announce('발표가 끝났어요. 분석을 볼 수 있어요.'); }
      update();
      persist(false);
      if (playing) raf = requestAnimationFrame(tick);
    }
    function play(on) {
      playing = on;
      if (on && t >= dur) t = 0;
      if (on && !raf) { last = performance.now(); raf = requestAnimationFrame(tick); }
      update();
      persist(true);
    }

    function turn(dir) {
      const next = L.stepSlide(d, shownNo, dir);
      if (next.edge) { Shell().announce(dir > 0 ? '마지막 장이에요' : '첫 장이에요'); nudge(dir); return; }
      t = Math.min(dur, L.slideStart(p, next.no) + 0.01);
      update();
      persist(true);
    }
    function nudge(dir) {
      if (c.reduced()) return;
      stage.classList.remove('is-edge-fwd', 'is-edge-back');
      void stage.offsetWidth;
      stage.classList.add(dir > 0 ? 'is-edge-fwd' : 'is-edge-back');
    }

    const zoomCur = () => {
      const s = d.slides.find((x) => x.no === shownNo);
      if (!s || !root.querySelector('img.tp-slide.is-cur')) return;   // 그림을 못 받은 장(제목 카드)은 키울 것이 없다
      if (playing) play(false);
      c.openZoom(s.image, `${s.no}장 · ${s.title}`);
    };
    bindSwipe(stage, turn, zoomCur, root.querySelector('[data-tour-body]'));
    root.querySelector('[data-zoom]').addEventListener('click', zoomCur);
    root.querySelectorAll('[data-turn]').forEach((b) => b.addEventListener('click', () => turn(Number(b.dataset.turn))));
    seek.addEventListener('input', () => { t = Number(seek.value) || 0; update(); });
    seek.addEventListener('change', () => persist(true));
    playBtn.addEventListener('click', () => play(!playing));
    root.querySelector('[data-next]').addEventListener('click', () => { persist(true); c.go('analysis'); });
    const keys = (e) => {
      if (e.target.closest && e.target.closest('input')) return;
      if (e.key === 'ArrowRight') turn(1);
      else if (e.key === 'ArrowLeft') turn(-1);
    };
    document.addEventListener('keydown', keys);

    update();
    if (playing) play(true);
    return () => {
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      playing = false;
      document.removeEventListener('keydown', keys);
      persist(true);
    };
  }

  const SCROLL_LOCK_PX = 8;       // 세로로 이만큼 먼저 움직이면 장 넘기기가 아니라 본문 스크롤
  const FLING_DECAY = 0.93;      // 손을 뗀 뒤 관성 — 한 프레임마다 남는 속도
  const FLING_MIN = 0.02;        // px/ms 아래면 멈춘다
  const reducedMotion = () => !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  /**
   * 자료 칸 몸짓 — 밀기 · 좌우 1/3 누르기 · 가운데 누르기(크게 보기). 두 손가락(꼬집기)이 한 번이라도 닿으면 다 뗄 때까지 안 넘긴다.
   * 자료 칸은 touch-action:none(10-08 pan-y → pointercancel 교훈)이라 브라우저가 세로 스크롤도 안 한다. 그래서 세로가 먼저 우세하면
   * 몸짓을 본문 스크롤로 넘겨 코드가 scrollTop 을 옮긴다 — 아이폰 SE 에서 자료 칸을 밀면 90px 가 안 내려가고, 가로 화면에서는
   * 자료 칸이 본문 높이를 다 차지해 아래 칸에 못 닿았다 (10-12 2차 layout-touch-a11y-r2-2)
   */
  function bindSwipe(stage, turn, onMiddle, scroller) {
    let start = null;
    let fling = 0;
    const stopFling = () => { if (fling) cancelAnimationFrame(fling); fling = 0; };
    const flingFrom = (v) => {   // v: px/ms, 위로 밀면 양수(본문이 내려간다)
      stopFling();
      let last = performance.now();
      const step = (now) => {
        const dt = Math.min(32, now - last);
        last = now;
        v *= Math.pow(FLING_DECAY, dt / 16);
        if (!scroller || Math.abs(v) < FLING_MIN) { fling = 0; return; }
        const before = scroller.scrollTop;
        scroller.scrollTop += v * dt;
        if (scroller.scrollTop === before) { fling = 0; return; }   // 끝에 닿았다
        fling = requestAnimationFrame(step);
      };
      fling = requestAnimationFrame(step);
    };
    const down = new Set();
    let multi = false;
    const lift = (e) => { down.delete(e.pointerId); if (!down.size) multi = false; };
    stage.addEventListener('pointerdown', (e) => {
      if (e.isPrimary) { down.clear(); multi = false; }
      down.add(e.pointerId);
      const onCtl = !!(e.target.closest && e.target.closest('button, a, input'));
      if (!onCtl) { try { stage.setPointerCapture(e.pointerId); } catch (_) { /* 이미 놓였다 */ } }
      if (down.size > 1) { multi = true; start = null; return; }
      if (multi || onCtl || (e.button != null && e.button > 0)) { start = null; return; }
      stopFling();
      start = { id: e.pointerId, x: e.clientX, y: e.clientY, at: performance.now(), type: e.pointerType, scroll: false, lastY: e.clientY, lastAt: performance.now(), v: 0 };
    });
    stage.addEventListener('pointermove', (e) => {
      if (!start || e.pointerId !== start.id || !scroller) return;
      const dx = e.clientX - start.x, dy = e.clientY - start.y;
      if (!start.scroll) {
        if (Math.abs(dy) < SCROLL_LOCK_PX || Math.abs(dy) <= Math.abs(dx) * 1.2) return;
        start.scroll = true;   // 이 몸짓은 이제 스크롤 — 손을 떼도 장을 넘기거나 크게 보기를 열지 않는다
      }
      const now = performance.now();
      const step = start.lastY - e.clientY;
      scroller.scrollTop += step;
      const dt = Math.max(1, now - start.lastAt);
      start.v = start.v * 0.6 + (step / dt) * 0.4;
      start.lastY = e.clientY;
      start.lastAt = now;
    });
    stage.addEventListener('pointerup', (e) => {
      lift(e);
      if (!start || e.pointerId !== start.id) return;
      const s = start;
      start = null;
      if (s.scroll) { if (!reducedMotion() && performance.now() - s.lastAt < 80) flingFrom(s.v); return; }
      const dx = e.clientX - s.x, dy = e.clientY - s.y;
      if (Math.abs(dx) >= SWIPE_MIN && Math.abs(dx) > Math.abs(dy) * 1.2) { turn(dx < 0 ? 1 : -1); return; }
      if (Math.abs(dx) <= TAP_MAX && Math.abs(dy) <= TAP_MAX && performance.now() - s.at <= TAP_MS) {
        const r = stage.getBoundingClientRect();
        const at = (e.clientX - r.left) / Math.max(1, r.width);
        if (at >= 2 / 3) turn(1);
        else if (at <= 1 / 3) turn(-1);
        else if (onMiddle) onMiddle();
      }
    });
    stage.addEventListener('pointercancel', (e) => { lift(e); start = null; });
    stage.addEventListener('dragstart', (e) => e.preventDefault());
  }

  /** 접힌 글(.is-clamp, 줄 수 제한) — 정말 넘칠 때만 누를 수 있는 것(role=button)이 되어 누르면 편다/접는다. 안 넘치면 그냥 글 */
  function bindClamps(root) {
    root.querySelectorAll('[data-clamp]').forEach((b) => {
      const toggle = () => {
        const open = b.classList.toggle('is-open');
        b.setAttribute('aria-expanded', open ? 'true' : 'false');
      };
      requestAnimationFrame(() => {
        if (b.scrollHeight <= b.clientHeight + 1) { b.classList.add('is-fit'); return; }
        b.setAttribute('role', 'button');
        b.setAttribute('aria-expanded', 'false');
        b.tabIndex = 0;
        b.addEventListener('click', toggle);
        b.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
      });
    });
  }

  /* ── 분석 ─────────────────────────────────────────────────── */

  Screens.analysis = (c) => {
    const a = c.tour.analysis;
    const reveal = !c.state.revealed;
    const maxSec = Math.max(1, ...a.slide_times.map((s) => s.sec));
    const times = a.slide_times.map((s) => `
        <li class="ta-time">
          <span class="ta-sno">${s.slide_no}장</span>
          <span class="ta-bar"><i class="tone-${L.LEVEL_TONE[s.level] || 'om'}" style="--w:${(s.sec / maxSec) * 100}%"></i></span>
          <span class="ta-sec"><b>${L.durationText(s.sec)}</b>${s.level !== 'good' ? ` · ${L.LEVEL_WORD[s.level] || ''}` : ''}</span>
          ${s.note ? `<small class="ta-note">${c.esc(s.note)}</small>` : ''}
        </li>`).join('');
    const g = L.paceGauge(a.pace.cpm);
    const fill = a.fillers;
    const graph = a.claim_graph;
    const counts = L.graphCounts(graph);
    const legend = Object.keys(L.GRAPH_STATUS).filter((k) => counts[k])
      .map((k) => `<span class="ta-key"><i class="dot st-${L.GRAPH_STATUS[k].tone}"></i>${L.GRAPH_STATUS[k].word} ${counts[k]}</span>`).join('');
    // 루트(핵심 주장)는 다 보이고, 나머지는 두 줄로 접었다가 누르면 편다 — 데이터에서 「…」 로 잘려 펼 길이 없었다 (10-12 2차 r2-4 · copy r2-7)
    const rows = L.graphRows(graph).map(({ node, depth }) => {
      const st = L.GRAPH_STATUS[node.status] || L.GRAPH_STATUS.aligned;
      const label = `${txt(c, node.label)}<span class="sr-only"> — ${st.long}</span>`;
      return `<li class="ta-node${depth === 0 ? ' is-root' : ''}" style="--depth:${depth}">
          <i class="dot st-${st.tone}" aria-hidden="true"></i>
          ${depth === 0 ? `<span class="ta-node-label">${label}</span>`
            : `<span class="ta-node-label is-clamp" data-clamp>${label}</span>`}
          <span class="ta-node-st st-${st.tone}" aria-hidden="true">${st.word}</span>
        </li>`;
    }).join('');
    return {
      tone: 'light',
      html: `<section class="tour-screen tour-analysis">
          <p class="tour-eyebrow">발표를 분석했어요</p>
          <h1 class="tour-h1 ta-summary">${c.esc(a.summary)}</h1>
          <div class="ta-overall">${c.levelChip(a.level)}<span>전체 평가</span></div>

          <article class="tour-card ta-sec-card">
            <header><h2 class="tour-h2">장마다 쓴 시간</h2></header>
            <ul class="ta-times">${times}</ul>
          </article>

          <article class="tour-card">
            <header><h2 class="tour-h2">말 속도</h2>${c.levelChip(a.pace.level)}</header>
            <p class="ta-big ta-big-word"><b>${L.paceWord(a.pace.cpm, a.pace.level)}</b></p>
            <p class="ta-sub">1분에 ${Math.round(a.pace.cpm)}자를 말했어요</p>
            <div class="ta-gauge" aria-hidden="true">
              <span class="ta-band" style="left:${g.lo * 100}%;width:${(g.hi - g.lo) * 100}%"></span>
              <span class="ta-pin" style="left:${g.at * 100}%"></span>
            </div>
            <div class="ta-gauge-scale" aria-hidden="true"><span>느려요</span><span>권장 300~350</span><span>빨라요</span></div>
          </article>

          <article class="tour-card">
            <header><h2 class="tour-h2">군더더기 말</h2>${c.levelChip(fill.level)}</header>
            <p class="ta-big"><b>${fill.count}</b>번 <small>· 1분에 ${fill.per_min}번</small></p>
            ${fill.top && fill.top.length ? `<div class="ta-words">${fill.top.map((w) => `<span class="chip chip-sm">「${c.esc(w.word)}」 ${w.count}번</span>`).join('')}</div>` : ''}
          </article>

          <article class="tour-card">
            <header><h2 class="tour-h2">주장 구조</h2></header>
            <p class="ta-line">${c.esc(graph.summary)}</p>
            <div class="ta-legend">${legend}</div>
            <ul class="ta-tree">${rows}</ul>
          </article>
          ${c.honestNote(c.tour)}
        </section>
        ${reveal ? `<div class="ta-reveal" data-reveal role="status">
            ${c.chick('neutral', 'is-lg ta-reveal-chick')}
            <p class="ta-reveal-title">발표를 분석하고 있어요</p>
            <ol class="ta-reveal-steps"><li>말한 것을 받아썼어요</li><li>자료와 맞춰 보고 있어요</li><li>말 습관을 세고 있어요</li></ol>
            <button class="tour-cta is-text" type="button" data-skip>건너뛰기</button>
          </div>` : ''}`,
      foot: '<button class="tour-cta" type="button" data-next>예상 질문 받기</button>',
      mount(root) {
        root.querySelector('[data-next]').addEventListener('click', () => c.go('qa'));
        bindClamps(root);
        const ov = root.querySelector('[data-reveal]');
        if (!ov) return null;
        root.classList.add('is-revealing');
        // 연출이 덮고 있는 동안 아래 「예상 질문 받기」 는 누름을 받지 않는다 — 발표 화면 「분석 보기」 를 두 번 누르면 분석을 못 보고 질문으로 갔다 (r2-2)
        const foot = root.querySelector('[data-tour-foot]');
        if (foot) foot.inert = true;
        const done = () => {
          if (!ov.isConnected) return;
          c.save({ revealed: true });
          root.classList.remove('is-revealing');
          if (foot && Shell().settleFoot) Shell().settleFoot(foot, 400); else if (foot) foot.inert = false;
          ov.classList.add('is-out');
          setTimeout(() => ov.remove(), c.reduced() ? 0 : 220);
          const h = root.querySelector('h1');
          if (h) h.focus({ preventScroll: true });
        };
        ov.querySelector('[data-skip]').addEventListener('click', done);
        const timer = setTimeout(done, c.reduced() ? 300 : REVEAL_MS);
        return () => { clearTimeout(timer); root.classList.remove('is-revealing'); if (foot) foot.inert = false; };
      },
    };
  };

  /* ── 질문 ─────────────────────────────────────────────────── */

  const ANSWER_LABEL = { good: '잘 답한 답', rough: '엉성한 답' };

  function groundsHtml(c, ans) {
    const gs = (ans.grounds || []).filter((g) => L.GROUND_ROLE[g.role]);
    if (!gs.length) return '';
    return `<div class="qa-grounds tqa-grounds">
        <p class="qa-grounds-h">근거 — 자료의 이 줄을 봤어요</p>
        ${gs.map((g) => `<div class="qa-evidence qa-ground is-${g.role}">
            <span>${L.GROUND_ROLE[g.role]} · ${c.esc(L.refText(g.ref, g.slide_no))}</span>
            <div class="tqa-quote is-clamp" data-clamp>「${txt(c, g.quote)}」</div>
            ${g.note ? `<small>${txt(c, g.note)}</small>` : ''}
          </div>`).join('')}
      </div>`;
  }

  Screens.qa = (c) => {
    const qs = c.tour.qa.questions;
    const qi = Math.min(qs.length - 1, Math.max(0, c.at.q));
    const q = qs[qi];
    const picks = c.state.picks || {};
    const pick = picks[q.id] === 'good' || picks[q.id] === 'rough' ? picks[q.id] : '';
    const ans = pick ? q.answers[pick] : null;
    const slide = c.tour.deck.slides.find((s) => s.no === q.slide_no);
    const last = qi === qs.length - 1;
    const asker = c.tour.qa.asker || '삐약이';
    return {
      tone: 'dark',
      html: `<section class="tour-screen tour-qa">
          <p class="tqa-count">질문 <b>${qi + 1}</b>/${qs.length}</p>
          <div class="tqa-ask">
            ${c.chick(pick ? (ans.verdict === 'good' ? 'happy' : 'curious') : 'neutral', 'tqa-chick')}
            <div class="tqa-bubble">
              <small>${c.esc(asker)} 역할 삐약이</small>
              <h1 class="tqa-q">${c.esc(q.question)}</h1>
              ${slide ? `<span class="tqa-ref">${slide.no}장 「${c.esc(slide.title)}」 에 대한 질문</span>` : ''}
            </div>
          </div>
          ${pick ? `
            <div class="tqa-me" data-answer>
              <small>내 답 · ${ANSWER_LABEL[pick]}</small>
              <p>${txt(c, ans.text)}</p>
            </div>
            <article class="tqa-verdict" data-verdict>
              <header>
                <span class="tqa-verdict-h" tabindex="-1" data-verdict-h>AI 판정</span>
                ${c.levelChip(ans.level)}
              </header>
              <p class="tqa-feedback">${txt(c, ans.feedback)}</p>
              ${groundsHtml(c, ans)}
            </article>` : `
            ${slide ? `<figure class="tqa-slide"><button class="tqa-slide-btn" type="button" data-zoom aria-label="${slide.no}장 크게 보기"><img src="${c.esc(slide.image)}" alt="${slide.no}장 · ${c.esc(slide.title)}" data-fallback="${slide.no}장 · ${c.esc(slide.title)}" decoding="async"></button><figcaption>누르면 크게 봐요</figcaption></figure>` : ''}
            <p class="tqa-prompt">어떤 답을 들어 볼까요? 고른 답을 AI가 판정해요.</p>`}
        </section>`,
      foot: pick
        ? `<div class="tour-foot-row">
            <button class="tour-cta is-sub" type="button" data-pick="${pick === 'good' ? 'rough' : 'good'}">${pick === 'good' ? '엉성한 답' : '잘 답한 답'} 보기</button>
            <button class="tour-cta" type="button" data-next>${last ? '리포트 보기' : '다음 질문'}</button>
          </div>`
        : `<div class="tour-foot-row">
            <button class="tour-cta is-choice" type="button" data-pick="good">잘 답한 답</button>
            <button class="tour-cta is-choice" type="button" data-pick="rough">엉성한 답</button>
          </div>`,
      mount(root) {
        root.querySelectorAll('[data-pick]').forEach((b) => b.addEventListener('click', () => {
          const p2 = b.dataset.pick;
          c.save({ picks: Object.assign({}, c.state.picks || {}, { [q.id]: p2 }), qaJust: q.id });
          Shell().render();
        }));
        const next = root.querySelector('[data-next]');
        if (next) next.addEventListener('click', () => (last ? c.go('report') : c.go('qa', qi + 1)));
        const zoom = root.querySelector('[data-zoom]');
        bindClamps(root);
        if (zoom && slide) zoom.addEventListener('click', () => { if (zoom.querySelector('img')) c.openZoom(slide.image, `${slide.no}장 · ${slide.title}`); });
        // 방금 고른 답이면 판정 카드가 보이게 내리고, 판정을 읽어 준다
        if (pick && c.state.qaJust === q.id) {
          c.save({ qaJust: '' });
          root.classList.add('is-answered');
          const card = root.querySelector('[data-answer]');
          requestAnimationFrame(() => card && card.scrollIntoView({ block: 'start', behavior: c.reduced() ? 'auto' : 'smooth' }));
          // 고른 버튼이 다시 그려지며 사라져 포커스가 body 로 떨어졌다 — 판정 카드 머리로 옮긴다 (10-12 2차 layout-touch-a11y-r2-6)
          const head = root.querySelector('[data-verdict-h]');
          if (head) { try { head.focus({ preventScroll: true }); } catch (_) { /* 옛 브라우저 */ } }
          Shell().announce(`판정 ${L.LEVEL_WORD[ans.level] || ''}. ${ans.feedback}`);
        }
        return null;
      },
    };
  };

  /* ── 리포트 ───────────────────────────────────────────────── */

  Screens.report = (c) => {
    const r = c.tour.report;
    const items = r.items.map((it) => `
        <li class="tr-item">
          <div><b>${c.esc(it.label)}</b><small>${c.esc(it.note)}</small></div>
          ${c.levelChip(it.level)}
        </li>`).join('');
    const steps = (r.next_steps || []).map((s, i) => `
        <li><span class="tr-n">${i + 1}</span><p>${c.esc(s.text)}</p>${s.slide_no ? `<span class="chip chip-sm tr-slide">${s.slide_no}장</span>` : ''}</li>`).join('');
    return {
      tone: 'light',
      html: `<section class="tour-screen tour-report">
          <p class="tour-eyebrow">리포트</p>
          <h1 class="tour-h1">${c.esc(r.headline)}</h1>
          <article class="tour-card">
            <header><h2 class="tour-h2">이번 발표 평가</h2></header>
            <ul class="tr-items">${items}</ul>
          </article>
          <article class="tour-card">
            <header><h2 class="tour-h2">다음에 이렇게 연습해요</h2></header>
            <ol class="tr-next">${steps}</ol>
          </article>
          ${c.honestNote(c.tour)}
        </section>`,
      foot: '<button class="tour-cta" type="button" data-next>체험 마치기</button>',
      mount(root) { root.querySelector('[data-next]').addEventListener('click', () => c.go('done')); },
    };
  };
})();
