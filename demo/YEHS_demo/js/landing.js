/*
랜딩 페이지(#/landing) 진입점입니다.
landing.html 조각을 받아 #app 에 넣고 각 구역의 동작을 붙입니다.

디자인 원본: 척척발표통합.html (1570-1803행)
- 정렬 쇼케이스는 300vh 스크롤 하이재킹을 걷어내고 완성 상태로 고정했습니다.
  renderAlign 이 진행도 p 하나만 받는 순수 함수라 구동원만 바꾸면 됩니다.
- [data-reveal] 등장 효과는 스크롤 위치에 연동되지 않는 1회 페이드라 유지합니다.
*/
(function () {
  'use strict';

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const { M, mIn, mPop, buildWave, reduceMotion } = window.LandingMotion;

  function initShell(signal) {
    /* ── ③ 스크롤 등장 모션 ───────────────────────────────────── */
    const io = new IntersectionObserver(entries => entries.forEach(e => {
      if (e.isIntersecting) { e.target.classList.add('is-visible'); io.unobserve(e.target); }
    }), { threshold: .16, rootMargin: '0px 0px -6% 0px' });
    function observeReveals() {
      $$('main:not([hidden]) [data-reveal]:not(.is-visible)').forEach(el => io.observe(el));
    }
    if (reduceMotion) $$('[data-reveal]').forEach(el => el.classList.add('is-visible'));
    /* 빠른 스크롤로 IO 알림을 놓친 요소 안전망: 화면 위로 지나간 요소는 즉시 표시 */
    let revealTick = false;
    addEventListener('scroll', () => {
      if (revealTick) return; revealTick = true;
      requestAnimationFrame(() => {
        revealTick = false;
        $$('main:not([hidden]) [data-reveal]:not(.is-visible)').forEach(el => {
          if (el.getBoundingClientRect().bottom < innerHeight * .5) el.classList.add('is-visible');
        });
      });
    }, { passive: true });

    /* ── ④ 히어로: 퍼즐 결합 시퀀스 + 마우스 패럴랙스 ─────────── */
    const hero = $('#hero'), heroVisual = $('#heroVisual');
    buildWave($('.waveform', heroVisual), 28, 12, 30);
    setTimeout(() => hero.classList.add('hero-ready'), reduceMotion ? 0 : 650);
    if (M && !$('main[data-page="home"]').hidden)
      mIn($$('.hero-copy > *'), { delay: M.stagger(.08, { startDelay: .05 }), duration: .6 });

    /* 가로형(≥900px)에서 랜딩은 옆으로 넘기는 덱이다 — css/tablet.css 가
       .landing-main 을 가로 스크롤 트랙으로 바꾼다. 그때는 창을 세로로 굴리는
       대신 트랙을 옆으로 밀어야 한다. 좁은 화면에서는 예전 그대로 세로로 간다. */
    const deckTrack = () => {
      const t = $('.landing-main');
      return t && getComputedStyle(t).overflowX !== 'visible' && t.scrollWidth > t.clientWidth + 1
        ? t : null;
    };
    const goSection = (el) => {
      if (!el) return;
      const track = deckTrack();
      const behavior = reduceMotion ? 'auto' : 'smooth';
      if (track) track.scrollTo({ left: el.offsetLeft, behavior });
      else el.scrollIntoView({ behavior });
    };

    $('#scrollCue').addEventListener('click', () => goSection($('.example-section')));

    const arrowSvg = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 10h11M11 6l4 4-4 4"></path></svg>';

    /* ── ⑪ 스크롤 고정형 시연: 발화 정렬 · SSA 판정 (클로드 1차 계승) ── */
    const scrubBars = [];
    (() => {
      /* 실제 리허설 녹음(fixtures/live/chuckchuck_rehearsal.m4a)의 진폭 봉투.
       합성 사인파와 달리 문장 사이 침묵과 호흡이 그대로 남아 있다. */
    const REAL_ENV = [0.709, 0.717, 0.644, 0.796, 0.656, 0.629, 0.635, 0.648, 0.714, 0.688, 0.046, 0.48, 0.785, 0.696, 0.663, 0.656, 0.649, 0.687, 0.57, 0.909, 0.043, 1.0, 0.742, 0.689, 0.829, 0.917, 0.764, 0.674, 0.568, 0.635, 0.043, 0.835, 0.616, 0.786, 0.635, 0.722, 0.801, 0.618, 0.536, 0.691, 0.35, 0.04, 0.735, 0.795, 0.785, 0.703, 0.893, 0.675, 0.701, 0.396, 0.907, 0.795, 0.935, 0.735, 0.611, 0.79, 0.66, 0.763, 0.629, 0.051, 0.816, 0.817, 0.732, 0.716, 0.616, 0.657, 0.702, 0.133, 0.683, 0.757, 0.675, 0.763, 0.823, 0.737, 0.745, 0.728, 0.155, 0.851, 0.752, 0.69, 0.576, 0.479, 0.77, 0.585, 0.744, 0.51, 0.752, 0.66, 0.78, 0.654, 0.693, 0.729, 0.663, 0.617, 0.734, 0.71, 0.945, 0.913, 0.573, 0.742, 0.703, 0.758, 0.694, 0.509, 0.778, 0.593, 0.889, 0.441, 0.274, 0.048];
    const tl = $('#scrubTimeline');
      for (let i = 0; i < 110; i++) {
        const b = document.createElement('i');
        b.style.height = Math.round(6 + REAL_ENV[i] * 52) + 'px';
        tl.appendChild(b); scrubBars.push(b);
      }
    })();
    const scrubSlides  = $$('#scrubSlides .sl');
    const scrubMarkers = $$('#scrubTimeline .marker');
    const bindSents    = $$('#bindSentence .s');
    const clampP = v => Math.min(1, Math.max(0, v));

    /* 정렬 스크럽 — 문장·슬라이드·마커·밴드가 모두 이 SEGS 하나를 기준으로 동작 */
    const SEGS = [
      { slide: 0, from: 0.02, to: 0.2876, t: '분명 침대에는 일찍 들어갔지만 실제로 잔 시간은 생각보다 길지 않았던 거죠', bind: '슬라이드 1의 발화로 기록' },
      { slide: 1, from: 0.2876, to: 0.3973, t: '이 하나의 주기는 보통 약 90분에서 110분 정도로 설명이 됩니다', bind: '슬라이드 2 구간에 묶임' },
      { slide: 2, from: 0.3973, to: 0.5144, t: '깊은 수면과 렘수면은 역할이 다릅니다', bind: '슬라이드 3 구간에 묶임' },
      { slide: 3, from: 0.5144, to: 0.5869, t: '수면의 질을 시간, 연속성, 규칙성으로 나누어 볼 수 있습니다', bind: '슬라이드 4 구간에 묶임' },
      { slide: 4, from: 0.5869, to: 0.6426, t: '늦은 시간에 마신 카페인, 음주, 스트레스, 그리고 환경 요인이 대표적입니다', bind: '슬라이드 5 구간에 묶임' },
      { slide: 5, from: 0.6426, to: 0.6947, t: '이런 차이를 사회적 시차라고 부르기도 합니다', bind: '슬라이드 6 구간에 묶임' },
      { slide: 6, from: 0.6947, to: 0.8731, t: '먼저 기상 시간을 일정하게 유지하는 것이 실천하기 쉽습니다', bind: '슬라이드 7 구간에 묶임' },
      { slide: 7, from: 0.8731, to: 0.94, t: '좋은 잠은 오래 누워 있는 잠이 아니라 몸과 뇌가 회복할 수 있도록 이어지는 잠입니다', bind: '슬라이드 8 구간에 묶임' }
    ];
    const MARKER_AT2 = [0.2876, 0.3973, 0.5144, 0.5869, 0.6426, 0.6947, 0.8731];
    const totalSec = 495;                       /* 08:15 · 실제 녹음 */
    let lastScrubSlide = -1;
    /* 파형 막대의 실제 픽셀 좌표 캐시 — 재생헤드와 픽셀 단위로 정렬 */
    const scrubTl = $('#scrubTimeline');
    let barX = [], barCacheW = 0;
    function cacheBarX() {
      barCacheW = scrubTl.clientWidth;
      barX = scrubBars.map(b => b.offsetLeft);
    }
    function renderAlign(p) {
      /* 파형·재생헤드는 동일한 hp 값 하나로 이동 — 항상 정확히 동시 */
      const hp = Math.min(p, .96);
      if (!barX.length || barCacheW !== scrubTl.clientWidth) cacheBarX();
      const headX = hp * scrubTl.clientWidth;   /* 재생헤드의 실제 x(px) */
      scrubBars.forEach((b, i) => b.classList.toggle('lit', barX[i] <= headX));
      const seg = SEGS.find(s => p >= s.from && p < s.to) || (p >= .94 ? SEGS[SEGS.length - 1] : SEGS[0]);
      /* 필름스트립: 현재 세그먼트의 슬라이드만 활성 (문장과 동일 기준) */
      scrubSlides.forEach((s, i) => {
        s.classList.toggle('on', p >= .02 && i === seg.slide);
        s.classList.toggle('revisit', p >= .02 && i === seg.slide && !!seg.re);
      });
      const curSlide = p >= .02 ? seg.slide : -1;
      if (curSlide !== lastScrubSlide) {
        if (curSlide > -1) mPop(scrubSlides[curSlide], .955);
        lastScrubSlide = curSlide;
      }
      /* A① 슬라이드별 누적 발화시간 바 — 재방문은 앰버 2겹으로 쌓임 */
      const acc = Array.from({ length: scrubSlides.length }, () => [0, 0]);
      SEGS.forEach(s => {
        const done = Math.max(0, Math.min(1, (p - s.from) / (s.to - s.from)));
        acc[s.slide][s.re ? 1 : 0] += done * (s.to - s.from) / .92 * totalSec;
      });
      const maxSec = 144;                              /* S01 도입(가장 김) 기준 */
      scrubSlides.forEach((s, i) => {
        const [v1, v2] = acc[i], tot = Math.round(v1 + v2);
        const t1 = s.querySelector('.sl-time .v1'), t2 = s.querySelector('.sl-time .v2'), lb = s.querySelector('.sl-sec');
        if (!t1) return;
        t1.style.width = Math.min(100, v1 / maxSec * 100) + '%';
        t2.style.width = Math.min(100, v2 / maxSec * 100) + '%';
        if (lb) lb.textContent = Math.floor(tot / 60) + ':' + String(tot % 60).padStart(2, '0');
      });
      /* A② 지나온 방문 구간 트레이스 — 덮어쓰지 않고 누적 보존 */
      const tl2 = $('#traceLayer');
      if (tl2) {
        if (!tl2.childElementCount)
          tl2.innerHTML = SEGS.map(s =>
            `<i class="trace ${s.re ? 're' : ''}" style="left:${s.from * 100}%;width:${(s.to - s.from) * 100}%"></i>`).join('');
        Array.from(tl2.children).forEach((t, i) => t.classList.toggle('show', p >= SEGS[i].to));
      }
      scrubMarkers.forEach((m, i) => { m.style.opacity = p >= MARKER_AT2[i] ? 1 : 0; });
      /* 현재 구간 밴드 + 재생헤드 (시간 표기) */
      const band = $('#segBand'), head = $('#playHead');
      if (band) {
        band.style.left = (seg.from * 100) + '%';
        band.style.width = ((seg.to - seg.from) * 100) + '%';
        band.classList.toggle('re', !!seg.re);
        band.style.opacity = p >= .02 ? 1 : 0;
      }
      if (head) {
        head.style.left = (hp * 100) + '%';
        head.style.opacity = p >= .02 ? 1 : 0;
        const sec = Math.round(p * totalSec);
        head.firstElementChild.dataset.t = Math.floor(sec / 60) + ':' + String(sec % 60).padStart(2, '0');
      }
      /* 발화 문장: 말한 단어 / 지금 단어 / 아직 안 말한 단어 */
      const bindEl = $('#bindSentence'), sumEl = $('#alignSummary');
      const done = p >= .94;
      bindEl.style.display = done ? 'none' : '';
      const wasOn = sumEl.classList.contains('on');
      sumEl.classList.toggle('on', done);
      sumEl.setAttribute('aria-hidden', String(!done));
      if (done && !wasOn) mIn($$('#alignVerdicts .av'), M ? { delay: M.stagger(.09, { startDelay: .25 }) } : null);
      /* B④ 타임라인 draw-in — 스크럽이 시작되는 순간 1회 */
      if (p >= .015) scrubTl.classList.add('drawn');
      if (!done) {
        if (p < .02) { bindEl.innerHTML = ''; return; }
        const words = seg.t.split(' ');
        const local = (p - seg.from) / (seg.to - seg.from);
        const spoken = Math.floor(local * words.length);
        bindEl.innerHTML = '<p class="line">“' + words.map((w, i) =>
          `<span class="w ${i < spoken ? 'said' : i === spoken ? 'now' : ''}">${w}</span>`).join(' ') + '”</p>' +
          `<small class="${seg.re ? 're' : ''}">→ ${seg.bind}</small>`;
      }
    }
    /* 스크롤 구동을 걷어내고 완성 상태로 한 번만 그린다.
       renderAlign 은 진행도 p 하나만 받는 순수 함수라 구동원만 바꾸면 된다. */
    renderAlign(.99);
    $('#alignSummary').classList.add('on');

    /* ═══ C⑥ 랜딩 진행 인디케이터 ═══ */
    const landProg = $('#landProgress');
    if (landProg) {
      const secs = ['hero', 'exampleSec', 'alignTrack', 'judgeSec', 'demoSec', 'start']
        .map(id => document.getElementById(id)).filter(Boolean);
      const btns = $$('#landProgress button');
      landProg.addEventListener('click', e => {
        const btn = e.target.closest('button'); if (!btn) return;
        goSection(document.getElementById(btn.dataset.sec));
      });
      let lpTick = false;
      /* 덱이면 지나온 칸을 가로 위치로, 아니면 예전처럼 세로 위치로 센다 */
      const paintDots = () => {
        lpTick = false;
        const track = deckTrack();
        let cur = 0;
        if (track) {
          const x = track.scrollLeft + track.clientWidth * .4;
          secs.forEach((s, i) => { if (x >= s.offsetLeft) cur = i; });
        } else {
          const y = scrollY + innerHeight * .4;
          secs.forEach((s, i) => { if (y >= s.offsetTop) cur = i; });
        }
        btns.forEach((b2, i) => b2.classList.toggle('on', i === cur));
        landProg.classList.toggle('lp-dark', cur === 5);
      };
      const onMove = () => {
        if (!document.querySelector('.landing-main') || lpTick) return;
        lpTick = true;
        requestAnimationFrame(paintDots);
      };
      addEventListener('scroll', onMove, { passive: true, signal });
      /* 트랙 자체의 스크롤은 창까지 올라오지 않으므로 따로 듣는다 */
      const track0 = $('.landing-main');
      if (track0) track0.addEventListener('scroll', onMove, { passive: true, signal });
      paintDots();
    }

    return io;
  }

  /* 재진입 때 이전 옵저버·리스너를 확실히 끊는다 */
  let mount = null;

  function teardown() {
    if (!mount) return;
    // v2 는 옵저버를 안 붙여서 둘 다 null 이다. v1 마운트가 남아 있을 수도 있으니
    // 있으면 정리하고 없으면 넘어간다 — 여기서 던지면 랜딩을 두 번 못 연다.
    if (mount.ctrl) mount.ctrl.abort();
    if (mount.io) mount.io.disconnect();
    mount = null;
  }

  async function renderLanding() {
    const app = document.getElementById('app');
    teardown();
    app.className = 'landing';
    app.innerHTML = '<p class="landing-loading">랜딩을 불러오는 중이에요…</p>';

    try {
      const res = await fetch('landing-v2.html?v=landing2');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      app.innerHTML = await res.text();
    } catch (err) {
      app.innerHTML = `
        <div class="landing-error">
          <h1>랜딩을 불러오지 못했어요</h1>
          <p>${err.message}</p>
          <a class="btn btn-primary" href="#/">내 발표로 가기</a>
        </div>`;
      return;
    }

    // v2 는 얹을 게 없다. v1 은 여기서 initShell(스크롤 스냅 옵저버)과
    // LandingWorkbench(히어로 목업 애니메이션)를 붙였는데, 둘 다 화면을
    // 가로채는 장치였다 (CLAUDE.md §3-4). 마크업과 CSS 만으로 끝난다.
    mount = { ctrl: null, io: null };
  }

  window.renderLanding = renderLanding;
})();
