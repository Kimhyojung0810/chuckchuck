/**
 * Report 2.0 화면 — iOS 내비게이션 스택 + 토스식 큰 숫자 (10-16 사용자 「iOS + 토스 · 리포트 하나로 만들지 마라 · 화면 전환 여러 개 ·
 * 기능은 죽이지 말고 강약 조절 · 대회 와우 포인트는 살리면서 디테일까지」).
 * 홈(요약)에서 진단 · 근거 · 코칭 · 다시 보기 · 청중석 · Q&A · 연습 · 점수를 저마다 한 화면으로 밀어 넣는다(push). 뒤로는 ‹ 단추 · 왼쪽 가장자리 밀기.
 * 데이터는 js/report_graph.js 의 뷰모델만 읽는다 — 새 판정 없음. 설계: docs/report-v2/ (PRODUCT_SPEC · UX_PROTOTYPES · DECISIONS D-011)
 *
 * 쓰는 법: ReportV2.mount(root, data, { mode: 'page' | 'app', slideImage(n), onLegacy() }) → { update(patch), destroy() }
 *  - page: 단독 페이지(/report-v2). 스택이 주소(#/home/issue:…)에 남아 뒤로 가기 · 새로고침이 된다
 *  - app : 앱 안(/VRShow 리포트 단계). 앱 주소를 건드리지 않고 스택은 sessionStorage 에만
 */
(function () {
  /* ─── 순수: 앱 상태 → 입력 묶음 (etc/tests/js/report_v2.smoke.mjs) ─────────────────────────── */
  function inputFromApp(raw) {
    const po = (raw && raw.pipelineOut) || {};
    const t = po.transcript ? { ...po.transcript } : null;
    if (t && (!t.words || !t.words.length) && raw.words && raw.words.length) t.words = raw.words;
    if (t && (!t.marks || !t.marks.length) && raw.marks && raw.marks.length) t.marks = raw.marks;
    const deck = raw.deck || {};
    const hasWords = !!(t && t.words && t.words.length);
    return {
      schema: 'report-v2-live',
      provenance: {
        presentation: raw.saved ? `이 브라우저에 저장한 리포트예요${raw.saved}.` : '방금 한 발표의 분석이에요.',
        ...(hasWords ? {} : { words: '단어 시각이 없어서 발언 위치는 장 단위로만 보여요.' }),
        ...(deck.audio_url ? {} : { audio: '녹음이 이 탭에 없어서 다시 들을 수 없어요.' }),
      },
      deck: { title: deck.title || (po.graph && po.graph.file_name) || '', slides: deck.slides || [], slide_images: deck.slide_images || [], audio_url: deck.audio_url || '' },
      transcript: t, graph: po.graph || null, alignment: po.alignment || null, flow: po.flow || null, score: po.score || null,
      pace: po.pace || null, habits: po.habits || null, report: po.report || null,
      chatter: raw.chatter || null, questions: null,
      // 네 모델 Q&A 후보 판 (js/report_qaboard.js) — 판이 없을 때의 까닭: loading · single(한 모델) · missing(이 탭에 없음)
      qa_board: raw.qaBoard || null, qa_board_state: raw.qaBoardState || '',
      qa: raw.qa && Array.isArray(raw.qa.results) && raw.qa.results.length ? { questions: raw.qa.questions || [], results: raw.qa.results } : null,
      behavior: raw.behavior || null,   // 발표 태도(베타) — 그리기는 js/behavior_report.js
    };
  }

  /* ─── 순수: 다시 보기 시간축의 「순간」 (10-17 바퀴 4 — 근거를 들을 수 있게) ───────────────────────
     진단 근거(말한 구절 · 말버릇 · 장별 시간)와 발표 태도 장면(오래 눈 뗌 · 아래 봄 · 흔들림)을 녹음 시각으로 맞춘다. Q&A 는 따로라 넣지 않는다.
     카메라 장면 시각은 첫 장면(t0) 기준이라 녹음 시각 = sec + t0/1000 (기록은 녹음이 켜질 때 함께 시작한다 — js/rehearsal_behavior.js).
     V = report_graph 뷰모델, behavior = D.behavior. → [{ id, lane:'fix'|'beh', t, end, slide, tone, title, sub, insight, more }] 시각 순 */
  const BEH_LINE = {
    lookaway: (w, d) => `${w}에서 ${d}초 동안 화면 쪽이 아니라 다른 곳을 봤어요`,
    down: (w, d) => `${w}에서 ${d}초 동안 아래를 봤어요`,
    sway: (w, d) => `${w} 무렵 ${d}초 동안 몸이 좌우로 되풀이해 오갔어요`,
  };
  function momentsOf(V, behavior) {
    const dur = (V && V.duration_sec) || 0;
    const out = [];
    const fin = (x) => typeof x === 'number' && isFinite(x);
    const toneOf = (x) => (x.status === 'conflicting' ? 'ct' : x.polarity === 'strength' ? 'ok' : 'mid');
    const near = (lane, t) => out.some((m) => m.lane === lane && Math.abs(m.t - t) < 1);
    [...((V && V.issues) || []), ...((V && V.strengths) || [])].forEach((x) => {
      (x.proofs || []).forEach((p, k) => {
        const a = p.anchor || {};
        if (p.status !== 'supported' || !fin(a.start_sec) || a.start_sec > dur + 1) return;
        if (out.some((m) => m.insight === x.id && Math.abs(m.t - a.start_sec) < 1)) return;
        out.push({ id: `f${out.length}`, lane: 'fix', t: Math.max(0, a.start_sec), end: fin(a.end_sec) ? a.end_sec : null, slide: a.slide_no || null,
          tone: toneOf(x), title: x.title, sub: p.kind === 'said' ? '' : String(p.text || ''), span: p.kind === 'time', quote: p.kind === 'said' ? String(p.text || '') : '', insight: x.id, proof: k,
          more: x.polarity === 'strength' ? '잘한 점' : x.status === 'conflicting' ? '판정이 흔들려요' : '고칠 것' });
      });
    });
    const p = behavior && behavior.present;
    if (p && p.status === 'ok' && dur) {
      const t0 = fin(p.t0) ? p.t0 / 1000 : 0;
      // 화면용 묶음엔 cards, 서버 보관 요약(summaryOf)엔 events 만 있다
      const list = Array.isArray(p.cards) && p.cards.length
        ? p.cards.filter((c) => c.scene && fin(c.scene.sec)).map((c) => ({ kind: c.kind, seg: c.scene.seg, where: c.scene.where, sec: c.scene.sec, d: c.scene.dur, text: c.observation }))
        : ((p.summary || p).events || []).filter((e) => BEH_LINE[e.k] && fin(e.t)).map((e) => {
          const w = /^s\d+$/.test(e.seg || '') ? `${e.seg.slice(1)}장` : '발표 중';
          return { kind: e.k, seg: e.seg, where: w, sec: e.t, d: e.d, text: BEH_LINE[e.k](w, e.d) };
        });
      list.forEach((c) => {
        const t = Math.max(0, c.sec + t0);
        if (t > dur + 1 || !/^s\d+$/.test(c.seg || '') || near('beh', t)) return;   // 같은 장면을 두 지표가 짚으면 한 번만(behavior_report uniqCards 와 같은 규칙)
        out.push({ id: `b${out.length}`, lane: 'beh', t, end: fin(c.d) ? Math.min(dur, t + c.d) : null, slide: Number(c.seg.slice(1)),
          tone: 'beh', title: c.text, sub: '', quote: '', insight: '', more: '발표 태도 · 베타' });
      });
    }
    return out.sort((a, b) => a.t - b.t || (a.lane === b.lane ? 0 : a.lane === 'fix' ? -1 : 1));
  }
  /** 그 순간에 한 말 — 시각을 품은 발화, 없으면 3초 안의 가장 가까운 발화. 구간이면 겹치는 첫 발화.
      first: 장 구간 근거(「2장 실제 93초」)처럼 구간의 시작이 뜻일 때 — 그 구간 안에서 처음 시작한 발화(앞 장 말끝을 집지 않게) */
  function lineAt(utts, t, end, first = false) {
    const list = utts || [];
    if (first && end != null) { const f = list.find((u) => u.start >= t - 0.3 && u.start < end); if (f) return f; }
    const hit = list.find((u) => u.start <= t && u.end >= t) || (end != null ? list.find((u) => u.start < end && u.end > t) : null);
    if (hit) return hit;
    let best = null; let gap = 3;
    list.forEach((u) => { const g = Math.min(Math.abs(u.start - t), Math.abs(u.end - t)); if (g <= gap) { gap = g; best = u; } });
    return best;
  }
  /** 주소 인자 「@18.3」 · 「@18.3:beh」 · 「진단id@18.3」 → 그 시각에 가장 가까운(1초 안) 순간. 진단 id 가 있으면 그 진단의 순간만. 없으면 null */
  function momentAt(moments, arg) {
    const m = /^(.*)@(\d+(?:\.\d+)?)(?::(fix|beh))?$/.exec(String(arg || ''));
    if (!m) return null;
    const t = Number(m[2]);
    let best = null; let gap = 1;
    (moments || []).forEach((x) => {
      if ((m[3] && x.lane !== m[3]) || (m[1] && x.insight !== m[1])) return;
      const g = Math.abs(x.t - t); if (g <= gap) { gap = g; best = x; }
    });
    return best;
  }
  /** 「그 순간 듣기」 가 여는 주소 — 다시 보기 화면이 이 순간을 고른 채 열린다 */
  const momentRoute = (m) => `replay:${m.lane === 'fix' ? m.insight : ''}@${(Math.round(m.t * 10) / 10).toFixed(1)}${m.lane === 'beh' ? ':beh' : ''}`;

  /* ─── 공통 ─────────────────────────────────────────────────────────── */
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = (sec) => { if (sec == null || !isFinite(sec)) return '–'; const s = Math.max(0, Math.round(sec)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
  /** 등급 — 기존 app.js scoreGrade 와 같은 규칙 */
  const grade = (v) => (v >= 90 ? 'A+' : v >= 80 ? 'A' : v >= 70 ? 'B+' : v >= 60 ? 'B' : v >= 50 ? 'C+' : v >= 40 ? 'C' : 'D');
  const plainDeck = (t) => String(t).replace(/\|\s*-{3,}\s*/g, ' ').replace(/\s*\|\s*/g, ' · ').replace(/(?:·\s*){2,}/g, '· ').replace(/\s{2,}/g, ' ').trim();
  const asset = (p) => (typeof window !== 'undefined' && window.__RV2_ASSET ? window.__RV2_ASSET(p) : p);
  const ST = { supported: '근거 있음', conflicting: '근거끼리 어긋나요', unsupported: '근거 없음', inferred: '추정으로 이었어요', missing: '근거 없음' };
  const EV = { high: '발언과 시각까지 확인했어요', mid: '장까지 확인했어요', low: '채점 글만 있어요', none: '근거가 없어요' };
  const CRIT = { content: '개념 전달', time: '시간', logic: '흐름', delivery: '말하기', visual: '시각자료', clarity: '명료성', audience: '청중 적합성' };
  const UI_WORD = { ok: '설명함', no: '안 나옴', ct: '자료와 모순', om: '정당한 생략', na: '판정 안 함' };
  const MOOD = { happy: 'happy', curious: 'curious', excited: 'excited', grumpy: 'neutral', neutral: 'neutral' };
  const tone = (x) => (x.status === 'conflicting' ? 'ct' : x.polarity === 'strength' ? 'ok' : x.polarity === 'unknown' ? 'na' : 'mid');

  /* 아이콘 — SF Symbols 는 웹에 못 실어서 같은 결의 선 아이콘(둥근 끝)을 직접 */
  const I = {
    chev: '<svg viewBox="0 0 8 14" aria-hidden="true"><path d="M1.5 1.5 6.5 7l-5 5.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    back: '<svg viewBox="0 0 12 20" aria-hidden="true"><path d="M10 2 2 10l8 8" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    play: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 2.8v10.4c0 .6.7 1 1.2.6l8-5.2a.7.7 0 0 0 0-1.2l-8-5.2c-.5-.4-1.2 0-1.2.6Z" fill="currentColor"/></svg>',
    pause: '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3.5" y="2.5" width="3" height="11" rx="1" fill="currentColor"/><rect x="9.5" y="2.5" width="3" height="11" rx="1" fill="currentColor"/></svg>',
    wave: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 9v2M6.5 6v8M10 3v14M13.5 6v8M17 9v2" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>',
    chat: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 4.5h12a1.5 1.5 0 0 1 1.5 1.5v7a1.5 1.5 0 0 1-1.5 1.5H9l-4 3v-3H4A1.5 1.5 0 0 1 2.5 13V6A1.5 1.5 0 0 1 4 4.5Z" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/></svg>',
    chart: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 16V9M10 16V4M16 16v-5" stroke="currentColor" stroke-width="2.3" stroke-linecap="round"/></svg>',
    people: '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="7" cy="7" r="2.8" fill="none" stroke="currentColor" stroke-width="1.9"/><circle cx="14" cy="8" r="2.2" fill="none" stroke="currentColor" stroke-width="1.9"/><path d="M2.5 16c.6-2.6 2.4-4 4.5-4s3.9 1.4 4.5 4M12 12.3c2.2-.4 4.2.9 4.9 3.7" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/></svg>',
    redo: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M15.5 7.5A6 6 0 1 0 16 12" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/><path d="M16 3.5v4.2h-4.2" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    check: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3.5 8.3 3 3 6-6.6" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    q: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5.8 5.9a2.3 2.3 0 1 1 3.3 2.1c-.7.3-1.1.9-1.1 1.6v.4M8 12.2v.1" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"/></svg>',
    bang: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3.5v5.3M8 11.9v.1" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round"/></svg>',
    cam: '<svg viewBox="0 0 20 20" aria-hidden="true"><rect x="2.5" y="5" width="11" height="10" rx="2" fill="none" stroke="currentColor" stroke-width="1.9"/><path d="m13.5 9 4-2.3v6.6l-4-2.3" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/></svg>',
    doc: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M6 2.8h5.5L15.5 7v9.2A1.3 1.3 0 0 1 14.2 17.5H6a1.3 1.3 0 0 1-1.3-1.3V4.1A1.3 1.3 0 0 1 6 2.8Z" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/><path d="M11 3v4.5h4.5" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/></svg>',
  };
  /** 옛 리포트 분석 탭 (app.js R_TAB_VIEWS 순서 그대로) */
  const LEGACY = [
    { name: '슬라이드로 보는 발표', short: '슬라이드', line: '장마다 판정 · 그 장에서 한 말', icon: 'doc', ico: 'i-blue' },
    { name: '말하기', short: '말하기', line: '말 속도 · 시간 배분 · 말버릇 · 청중 반응', icon: 'wave', ico: 'i-orange' },
    { name: '개념 전달', short: '개념 전달', line: '개념마다 설명했는지 · 판정 근거', icon: 'check', ico: 'i-green' },
    { name: '흐름', short: '흐름', line: '설명 순서 · 빠진 고리 · 잘 이은 곳', icon: 'chart', ico: 'i-gray' },
    { name: '채점 근거', short: '채점 근거', line: '39개 항목의 점수와 근거 · 이의 제기', icon: 'doc', ico: 'i-gray' },
    { name: '연습 도구', short: '연습 도구', line: '개념도 · 펀치라인 · 용어 카드', icon: 'redo', ico: 'i-green' },
    { name: '발표 구성', short: '발표 구성', line: '발표 순서를 다시 짜 보기', icon: 'chart', ico: 'i-blue' },
  ];
  const badge = (x) => `<span class="nv-badge t-${tone(x)}">${tone(x) === 'ok' ? I.check : tone(x) === 'na' ? I.q : I.bang}</span>`;

  /* ═══ 마운트 ═══════════════════════════════════════════════════════════ */
  function mount(root, data, opts = {}) {
    const MODE = opts.mode || 'page';
    const EMBED = !!window.__RV2_EMBED;
    /* 탭 모드(스튜디오 /VRShow) — 뿌리 화면 다섯이 스튜디오 정거장 다섯(05 결과 · 06 다시 보기 · 07 청중석 · 08 코칭 · 09 연습)이다.
       그 다섯으로 가는 push 는 뿌리를 바꾸고(opts.onRoot 로 알린다 → 스튜디오 창이 곡선을 따라 미끄러진다), 그 아래 깊은 화면만 창 안에서 밀어 넣는다 */
    const TABS = Array.isArray(opts.tabs) && opts.tabs.length ? opts.tabs : null;
    let D = data; let G = null; let V = null; let QB = null;
    let audio = null; let stopAt = null; let playingKey = '';
    let autoPlayNext = false;   // 「그 순간 듣기」 로 다시 보기를 열 때만 그 순간을 바로 들려준다(다시 그리기 · 복원에선 안 튼다)
    const stack = [];      // [{ route, el, short, onTime }]
    const imgCache = {};
    const STATE_KEY = 'cheokcheok:rv2-stack';
    root.classList.add('rv2');
    root.innerHTML = '<div class="nv" aria-roledescription="리포트"></div>';
    const NV = root.querySelector('.nv');

    /* ── 데이터 ── */
    function build() {
      G = window.ReportGraph.buildGraph({ ...D, reportId: D.schema || 'report' });
      V = window.ReportGraph.buildViewModel(G, D);
      QB = window.ReportQaBoard ? window.ReportQaBoard.model(D.qa_board, D.qa) : null;
      if (MODE === 'page') window.__RV2 = { D, G, V, validate: () => window.ReportGraph.validate(G) };
    }
    const all = () => [...V.issues, ...V.unknown, ...V.strengths];
    const insight = (id) => (id ? all().find((x) => x.id === id) || null : null);
    const timeOf = (ins) => {
      const p = (ins && ins.proofs || []).find((x) => x.anchor && x.anchor.start_sec != null && x.status === 'supported');
      return p ? [p.anchor.start_sec, p.anchor.end_sec] : null;
    };
    const slideImg = (n) => (D.deck.slide_images || [])[n - 1] || imgCache[n] || '';
    function slideTag(n, cls = 'nv-slide') {
      if (!slideImg(n) && typeof opts.slideImage === 'function') {
        Promise.resolve(opts.slideImage(n)).then((url) => {
          if (!url) return;
          imgCache[n] = url;
          NV.querySelectorAll(`img[data-slide="${n}"]`).forEach((el) => { el.src = url; el.hidden = false; });
        }).catch(() => {});
      }
      const u = slideImg(n);
      return `<div class="${cls}"><img data-slide="${n}" src="${esc(u)}" alt="${esc(n)}장" ${u ? '' : 'hidden'}><span>${esc(n)}장</span></div>`;
    }

    /* ── 소리 — 구간 재생(끝나면 멈춤). 같은 단추를 다시 누르면 멈춘다 ── */
    function setAudio() {
      if (audio) { try { audio.pause(); } catch (_) { /* 멈춤 */ } }
      audio = null;
      if (D.deck && D.deck.audio_url) {
        audio = new Audio(); audio.preload = 'metadata'; audio.src = D.deck.audio_url;
        audio.addEventListener('timeupdate', onTime);
        audio.addEventListener('pause', paintPlay); audio.addEventListener('play', paintPlay);
      }
    }
    function play(a, b, key = '') {
      if (!audio) return;
      if (playingKey === key && !audio.paused) { audio.pause(); return; }
      playingKey = key;
      audio.currentTime = Math.max(0, a); stopAt = b != null && isFinite(b) ? b + 0.3 : null;
      audio.play().catch(() => {});
    }
    function onTime() {
      if (stopAt != null && audio.currentTime >= stopAt) { audio.pause(); stopAt = null; }
      const top = stack[stack.length - 1];
      if (top && top.onTime) top.onTime(audio.currentTime);
    }
    function paintPlay() {
      NV.querySelectorAll('[data-play]').forEach((b) => {
        const on = !!audio && !audio.paused && b.dataset.play === playingKey;
        b.classList.toggle('is-on', on);
        const ic = b.querySelector('.nv-pi'); if (ic) ic.innerHTML = on ? I.pause : I.play;
      });
    }
    const playBtn = (key, a, b, label) => `<button type="button" class="nv-play" data-play="${esc(key)}" data-a="${a}" data-b="${b == null ? '' : b}" ${audio ? '' : 'disabled'}><span class="nv-pi">${I.play}</span><span>${esc(label)}</span></button>`;

    /* ── 스택 ── */
    /* 「질문은 이렇게 골랐어요」 — 네 모델 후보 판 (js/report_qaboard.js). 파일이 없으면 진입점도 없다 */
    const QBS = window.ReportQaBoard ? window.ReportQaBoard.screens({ esc, I, asset, Q: () => QB }) : null;
    /* Q&A 돌아보기 (10-17 개편 §3) — js/report_v2_qa.js. 파일이 없으면 옛 전환점 화면(qaChat)으로 */
    const QAS = window.ReportV2Qa ? window.ReportV2Qa.screens({ esc, I, asset, V: () => V, D: () => D, QB: () => QB, QBS, slideTag, EMBED }) : null;
    const qa = QAS ? QAS.qa : qaChat;
    const ROUTES = { home, issue, replay, coach, audience, chick, practice, qa, scores, legacy, issues, strengths, unsure, details, attitude,
      ...(QBS ? { board: QBS.board, slot: QBS.slot, round: QBS.round } : {}) };
    const parse = (r) => { const k = r.indexOf(':'); return k < 0 ? [r, ''] : [r.slice(0, k), r.slice(k + 1)]; };
    function renderScreen(route) {
      const [name, arg] = parse(route);
      const sc = (ROUTES[name] || home)(arg);
      const el = document.createElement('section');
      el.className = `nv-screen nv-${ROUTES[name] ? name : 'home'}${sc.wide ? ' is-wide' : ''}${sc.home ? ' is-home' : ''}`;
      el.setAttribute('aria-label', sc.title);
      const prev = stack[stack.length - 1];
      const backWord = prev ? prev.short : '';
      el.innerHTML = `
        <header class="nv-bar">
          ${backWord ? `<button type="button" class="nv-back" data-back>${I.back}<span>${esc(backWord)}</span></button>`
            : (typeof opts.onLegacy === 'function' && name === 'home' ? '<button type="button" class="nv-oldbtn" data-legacy>이전 리포트</button>' : '<span></span>')}
          <h2 class="nv-small">${esc(sc.short || sc.title)}</h2><span class="nv-bar-end"></span>
        </header>
        <div class="nv-scroll">
          ${sc.top || ''}
          ${sc.eyebrow ? `<p class="nv-eyebrow">${esc(sc.eyebrow)}</p>` : ''}
          <h1 class="nv-large${sc.size ? ` is-${sc.size}` : ''}" tabindex="-1">${esc(sc.title)}</h1>
          ${sc.html}
          ${name === 'home' ? `<footer class="nv-foot">${Object.values(D.provenance || {}).map((t) => `<p>${esc(t)}</p>`).join('')}</footer>` : ''}
        </div>
        ${sc.cta ? `<div class="nv-cta"><button type="button" class="nv-pill" ${sc.cta.attr}>${sc.cta.icon || ''}<span>${esc(sc.cta.label)}</span></button></div>` : ''}`;
      const scroller = el.querySelector('.nv-scroll');
      const bar = el.querySelector('.nv-bar');
      scroller.addEventListener('scroll', () => bar.classList.toggle('is-compact', scroller.scrollTop > 40), { passive: true });
      wire(el);
      if (sc.wire) sc.wire(el);
      return { route, el, short: sc.short || sc.title, onTime: sc.onTime || null };
    }
    function goMoment(route) { if (busy) return; autoPlayNext = !!audio; push(route); }
    function wire(el) {
      el.querySelectorAll('[data-push]').forEach((b) => b.addEventListener('click', (e) => { e.stopPropagation(); push(b.dataset.push); }));
      el.querySelectorAll('[data-moment]').forEach((b) => b.addEventListener('click', (e) => { e.stopPropagation(); goMoment(b.dataset.moment); }));
      el.querySelectorAll('[data-back]').forEach((b) => b.addEventListener('click', () => back()));
      el.querySelectorAll('[data-legacy]').forEach((b) => b.addEventListener('click', () => opts.onLegacy()));
      el.querySelectorAll('[data-play]').forEach((b) => b.addEventListener('click', (e) => { e.stopPropagation(); play(+b.dataset.a, b.dataset.b === '' ? null : +b.dataset.b, b.dataset.play); }));
      el.querySelectorAll('[data-href]').forEach((b) => b.addEventListener('click', () => { if (!EMBED) location.href = b.dataset.href; }));
    }
    const reduced = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const EASE = 'cubic-bezier(0.32, 0.72, 0, 1)';   // iOS 밀기 곡선 — 빠르게 출발해 부드럽게 멈춘다. 길이는 200ms(10-17 기조 R18 · 설계 §6)
    function animate(el, from, to, ms) {
      return new Promise((done) => {
        if (reduced() || !el.animate) { el.style.transform = to; done(); return; }
        const a = el.animate([{ transform: from }, { transform: to }], { duration: ms, easing: EASE, fill: 'forwards' });
        a.onfinish = () => { el.style.transform = to; a.cancel(); done(); };
      });
    }
    let busy = false;
    function goRoot(route) {
      if (stack.length === 1 && stack[0].route === route) return;
      if (audio) audio.pause();
      rebuild([route]);
      saveStack();
    }
    const notifyRoot = () => { if (typeof opts.onRoot === 'function' && stack[0]) opts.onRoot(parse(stack[0].route)[0]); };
    async function push(route) {
      if (TABS && TABS.includes(route)) { goRoot(route); return; }
      if (busy) return;
      busy = true;
      const prev = stack[stack.length - 1];
      const next = renderScreen(route);
      NV.appendChild(next.el);
      stack.push(next);
      if (prev) { prev.el.setAttribute('inert', ''); prev.el.setAttribute('aria-hidden', 'true'); }
      NV.classList.add('is-moving');
      await Promise.all([animate(next.el, 'translateX(100%)', 'translateX(0)', 200), prev ? animate(prev.el, 'translateX(0)', 'translateX(-28%)', 200) : null]);
      NV.classList.remove('is-moving');
      if (prev) prev.el.classList.add('is-under');
      const h = next.el.querySelector('.nv-large'); if (h) h.focus({ preventScroll: true });
      if (MODE === 'page') history.pushState({ rv2: stack.map((s) => s.route) }, '', hashOf());
      saveStack();
      busy = false;
    }
    async function back({ fromHistory = false } = {}) {
      if (busy || stack.length < 2) return;
      if (MODE === 'page' && !fromHistory) { history.back(); return; }   // popstate 가 다시 부른다
      busy = true;
      const top = stack.pop();
      const under = stack[stack.length - 1];
      under.el.classList.remove('is-under');
      under.el.removeAttribute('inert'); under.el.removeAttribute('aria-hidden');
      NV.classList.add('is-moving');
      const fromX = top.el.style.transform || 'translateX(0)';
      const underFrom = under.el.style.transform || 'translateX(-28%)';
      await Promise.all([animate(top.el, fromX, 'translateX(100%)', 200), animate(under.el, underFrom, 'translateX(0)', 200)]);
      NV.classList.remove('is-moving');
      top.el.remove();
      saveStack();
      busy = false;
    }
    function hashOf() { return EMBED ? '#r' : `#/${stack.map((s) => encodeURIComponent(s.route).replace(/%3A/g, ':')).join('/')}`; }
    function saveStack() {
      if (MODE !== 'app') return;
      try { sessionStorage.setItem(STATE_KEY, JSON.stringify({ key: D.deck.title, routes: stack.map((s) => s.route) })); } catch (_) { /* 처음부터 */ }
    }
    function routesFromHash() {
      const h = location.hash.replace(/^#\/?/, '');
      if (!h || h === 'r') return null;
      return h.split('/').filter(Boolean).map((p) => decodeURIComponent(p));
    }
    function rebuild(routes) {
      stack.splice(0).forEach((s) => s.el.remove());
      const list = routes && routes.length ? routes.slice() : ['home'];
      if (list[0] !== 'home' && !(TABS && TABS.includes(list[0]))) list.unshift('home');
      list.forEach((r, k) => {
        if (k > 0) { const p = stack[stack.length - 1]; p.el.style.transform = 'translateX(-28%)'; p.el.classList.add('is-under'); p.el.setAttribute('inert', ''); p.el.setAttribute('aria-hidden', 'true'); }
        const s = renderScreen(r);
        NV.appendChild(s.el);
        stack.push(s);
      });
      notifyRoot();
    }

    /* ── 왼쪽 가장자리 밀기 — 손가락을 1:1 로 따라오고, 놓을 때의 속도 · 거리로 정한다(중간에 되돌릴 수 있다) ── */
    let drag = null;
    NV.addEventListener('pointerdown', (e) => {
      if (stack.length < 2 || busy) return;
      const r = NV.getBoundingClientRect();
      if (e.clientX - r.left > 22) return;
      drag = { x0: e.clientX, w: r.width, t0: performance.now(), x: e.clientX, v: 0, id: e.pointerId };
      NV.setPointerCapture(e.pointerId);
    });
    NV.addEventListener('pointermove', (e) => {
      if (!drag || e.pointerId !== drag.id) return;
      const now = performance.now();
      drag.v = (e.clientX - drag.x) / Math.max(1, now - drag.t0); drag.x = e.clientX; drag.t0 = now;
      const dx = Math.max(0, e.clientX - drag.x0);
      stack[stack.length - 1].el.style.transform = `translateX(${dx}px)`;
      stack[stack.length - 2].el.style.transform = `translateX(${-28 + 28 * (dx / drag.w)}%)`;
    });
    const endDrag = async (e) => {
      if (!drag || e.pointerId !== drag.id) return;
      const dx = Math.max(0, drag.x - drag.x0); const w = drag.w; const go = drag.v > 0.45 || dx > w * 0.4;
      drag = null;
      if (go) { if (MODE === 'page') history.back(); else back({ fromHistory: true }); return; }
      const top = stack[stack.length - 1].el; const under = stack[stack.length - 2].el;
      await Promise.all([animate(top, `translateX(${dx}px)`, 'translateX(0)', 200), animate(under, `translateX(${-28 + 28 * (dx / w)}%)`, 'translateX(-28%)', 200)]);
    };
    NV.addEventListener('pointerup', endDrag); NV.addEventListener('pointercancel', endDrag);

    /* ═══ 화면들 ═══════════════════════════════════════════════════════ */

    /* 홈 (10-17 리포트 개편 §2) — 총점 하나 · 가장 먼저 고칠 한 가지 · Q&A 돌아보기 · 발표 태도(베타) · 청중석, 나머지는 입구 한 줄씩.
       헤드라인 = 근거 있는 1번 진단 제목(D1). 판정이 흔들린 진단은 위 셋에서 빼서 「판정을 못 한 것」 으로(D2). 옛 분석은 「자세한 분석」 한 줄(D4) */
    const GRADE_WORD = { 'A+': '아주 잘했어요', A: '잘했어요', 'B+': '괜찮아요', B: '괜찮아요', 'C+': '고칠 곳이 보여요', C: '고칠 곳이 보여요', D: '다시 연습해 봐요' };
    const fixesOf = () => V.fixes || V.issues;
    const unsureOf = () => [...(V.shaky || []), ...V.unknown];
    function proofChips(x) {
      const out = [];
      x.proofs.forEach((p, k) => {
        if (p.kind === 'said' && p.status === 'supported' && p.anchor.start_sec != null && out.length < 3) {
          out.push(`<button type="button" class="hm-chip is-play" data-play="h${k}" data-a="${p.anchor.start_sec}" data-b="${p.anchor.end_sec == null ? '' : p.anchor.end_sec}" ${audio ? '' : 'disabled'}><span class="nv-pi">${I.play}</span><span><b>${fmt(p.anchor.start_sec)}</b>${p.anchor.slide_no ? ` · ${esc(p.anchor.slide_no)}장` : ''} · 실제 목소리</span></button>`);
        } else if (p.kind === 'deck' && p.anchor.slide_no && out.length < 3) out.push(`<span class="hm-chip">자료 <b>${esc(p.anchor.slide_no)}</b>장 원문</span>`);
        else if (p.kind === 'time' && p.anchor.slide_no && out.length < 3 && !out.some((o) => o.includes('data-t'))) {
          out.push(`<button type="button" class="hm-chip is-play" data-t="1" data-play="h${k}" data-a="${p.anchor.start_sec}" data-b="${p.anchor.end_sec == null ? '' : p.anchor.end_sec}" ${audio && p.anchor.start_sec != null ? '' : 'disabled'}><span class="nv-pi">${I.play}</span><span>${esc(p.text)}</span></button>`);
        }
      });
      return out.join('');
    }
    /** 「그 순간 듣기」 — 이 진단의 첫 순간을 고른 채 다시 보기를 연다(녹음이 있으면 그 구간을 바로 들려준다). 녹음이 없으면 「그 순간 보기」 */
    const momentWord = () => (audio ? '그 순간 듣기' : '그 순간 보기');
    function momentLink(x) {
      const m = momentsOf(V, null).find((y) => y.insight === x.id);
      return m ? `<button type="button" class="nv-link hm-moment" data-moment="${esc(momentRoute(m))}">${momentWord()}</button>` : '';
    }
    function behaviorRow() {
      const BR = window.BehaviorReport;
      if (!BR || !D.behavior || typeof BR.headline !== 'function') return '';
      let h = null;
      try { h = BR.headline(D.behavior); } catch (_) { return ''; }
      if (!h || h.status === 'none') return '';   // D5 — 카메라 분석이 없으면 줄 자체를 숨긴다
      const line = h.status === 'ok' ? h.oneLine : `이번엔 잴 수 없었어요 — ${h.oneLine}`;
      return `<div class="nv-group hm-beh"><button type="button" class="nv-row" data-push="attitude"><span class="nv-ico i-gray">${I.cam}</span>
        <span class="nv-row-main"><span class="hm-beta">베타 · 총점에 안 들어가요</span><b>발표 태도</b><small>${esc(line)}</small></span><i class="nv-chev">${I.chev}</i></button></div>`;
    }
    function home() {
      const sc = V.score;
      const val = sc ? Math.round(sc.value) : null;
      const C = 2 * Math.PI * 46;
      const fixes = fixesOf();
      const first = fixes[0] || null;
      const more = fixes.slice(1, 3);
      const thesisNa = V.unknown.find((u) => u.impact === 'high');
      const unsure = unsureOf();
      const real = V.evaluators.filter((e) => !e.absent);
      const remarks = V.evaluators.reduce((n, e) => n + e.remarks.filter((r) => !r.filler).length, 0);
      const wk = sc && sc.weakest;
      const row = (push, ico, icon, title, sub, val2) => `<button type="button" class="nv-row" data-push="${esc(push)}"><span class="nv-ico ${ico}">${I[icon]}</span><span class="nv-row-main"><b>${esc(title)}</b>${sub ? `<small>${esc(sub)}</small>` : ''}</span>${val2 != null && val2 !== '' ? `<span class="nv-val">${esc(val2)}</span>` : ''}<i class="nv-chev">${I.chev}</i></button>`;
      const hero = `<section class="hm-hero" aria-label="총점">
          ${val != null ? `<div class="hm-score" role="img" aria-label="총점 ${esc(val)}점, 100점 만점">
            <svg class="nv-ring" viewBox="0 0 108 108" aria-hidden="true"><circle cx="54" cy="54" r="46" class="bg"/><circle cx="54" cy="54" r="46" class="fg" style="--c:${C.toFixed(1)};--off:${(C * (1 - Math.max(0, Math.min(100, val)) / 100)).toFixed(1)}"/></svg>
            <p class="hm-num"><b>${esc(val)}</b><span>점</span></p></div>` : ''}
          <div class="hm-hero-txt">
            <p class="hm-cap">발표 완성도${sc && sc.situation ? ` · ${esc(sc.situation)}` : ''}</p>
            ${val != null ? `<p class="hm-grade"><b>${esc(grade(val))}</b> ${esc(GRADE_WORD[grade(val)] || '')}</p>` : '<p class="hm-grade">점수를 매기지 못했어요</p>'}
            ${V.duration_sec ? `<p class="hm-meta">${fmt(V.duration_sec)} 발표 · ${(V.slides || []).length}장</p>` : ''}
          </div>
          ${wk ? `<button type="button" class="hm-weak" data-push="scores"><span>가장 약한 기준</span><b>${esc(wk.name)} <em>${esc(Math.round(wk.average))}점</em></b><i class="nv-chev">${I.chev}</i></button>` : ''}
        </section>`;
      const firstCard = first ? `<section class="hm-first" aria-label="가장 먼저 고칠 한 가지">
          <p class="hm-label">가장 먼저 고칠 한 가지</p>
          <button type="button" class="hm-first-title" data-push="issue:${esc(first.id)}"><span class="nv-headline">${esc(first.title)}</span><i class="nv-chev">${I.chev}</i></button>
          ${first.why ? `<p class="hm-why">${esc(first.why)}</p>` : ''}
          <div class="hm-chips">${proofChips(first)}${momentLink(first)}</div>
          <p class="hm-ev">${esc(EV[first.evidence])}</p>
          <button type="button" class="hm-fix" data-push="coach:${esc(first.id)}">고쳐 보기</button>
        </section>` : `<section class="hm-first is-none"><p class="hm-label">가장 먼저 고칠 한 가지</p><p class="nv-headline">근거가 있는 고칠 점은 찾지 못했어요</p>
          <p class="hm-why">분석이 근거까지 남긴 문제만 고칠 것으로 보여 줘요. 잘한 점과 Q&A 돌아보기를 먼저 봐요.</p></section>`;
      const moreRows = more.length ? `<p class="hm-sub">그다음 고칠 것</p><div class="nv-group">${more.map((x, k) => `<button type="button" class="nv-row" data-push="issue:${esc(x.id)}"><span class="nv-num t-${tone(x)}">${k + 2}</span><span class="nv-row-main"><b>${esc(x.title)}</b><small>${esc(EV[x.evidence])}</small></span><i class="nv-chev">${I.chev}</i></button>`).join('')}</div>` : '';
      const audienceRow = `<div class="nv-group"><button type="button" class="nv-row hm-aud" data-push="audience"><span class="nv-ico i-orange">${I.people}</span><span class="nv-row-main"><b>삐약이 청중석</b><small>${real.length ? `${real.length}마리가 ${remarks}마디 했어요` : V.evaluators.length ? '이번엔 다 못 왔어요' : '청중 반응을 불러오고 있어요'}</small></span>
            <span class="nv-faces">${V.evaluators.map((e) => `<img src="${esc(asset(`assets/chick-${e.key}-neutral.svg`))}" alt="" class="${e.absent ? 'off' : ''}">`).join('')}</span><i class="nv-chev">${I.chev}</i></button></div>`;
      const entries = `<h3 class="hm-sec">더 살펴보기</h3><div class="nv-group hm-entries">
          ${row('issues', 'i-orange', 'bang', '진단 전체', '고칠 것을 근거 순서로', `${fixes.length}개`)}
          ${sc ? row('scores', 'i-gray', 'chart', '기준별 점수', '39개 항목을 7개 기준으로 · 약한 순', `${val}점`) : ''}
          ${first ? row(`coach:${first.id}`, 'i-green', 'redo', '이렇게 고쳐요', '원래 발표 → 까닭 → 바꿔 말하기') : ''}
          ${row('replay', 'i-blue', 'wave', '발표 다시 보기', D.deck.audio_url ? '실제 녹음 · 받아쓰기 · 장 그림' : '받아쓰기 · 장 그림', fmt(V.duration_sec))}
          ${V.strengths.length ? row('strengths', 'i-green', 'check', '잘한 점', V.strengths[0].title, `${V.strengths.length}개`) : ''}
          ${unsure.length ? row('unsure', 'i-gray', 'q', '판정을 못 한 것', '믿기 어려워서 고칠 것에서 뺀 판정', `${unsure.length}개`) : ''}
          ${typeof window.__rv2Legacy === 'function' ? row('details', 'i-gray', 'doc', '자세한 분석', '슬라이드 · 말하기 · 개념 전달 · 흐름 · 채점 근거 · 연습 도구 · 발표 구성') : ''}
        </div>`;
      return {
        title: D.deck.title || '발표 리포트', short: '리포트', size: 'md', home: true, eyebrow: D.sample ? '샘플 리포트' : '발표 리포트',
        html: `
        ${D.sample ? '<p class="hm-sample">미리 돌려 둔 부스 시연 발표의 실제 분석이에요. 직접 발표를 마치면 이 자리에 내 리포트가 떠요.</p>' : ''}
        <div class="hm-grid">
          <div class="hm-main">
            ${hero}
            ${thesisNa ? `<button type="button" class="hm-na" data-push="issue:${esc(thesisNa.id)}">${I.q}<span>${esc(thesisNa.title)}</span><i class="nv-chev">${I.chev}</i></button>` : ''}
            ${firstCard}
            ${moreRows}
          </div>
          <div class="hm-side">
            ${QAS ? QAS.card() : ''}
            ${behaviorRow()}
            ${audienceRow}
          </div>
          <div class="hm-rest">${entries}</div>
        </div>`,
        cta: { label: '다시 연습하기', attr: 'data-push="practice"', icon: I.redo },
      };
    }

    /* 진단 전체 · 잘한 점 · 판정을 못 한 것 · 자세한 분석 — 홈 「더 살펴보기」 의 한 줄 입구가 여는 화면 (10-17 §2-7) */
    function issues() {
      const fixes = fixesOf();
      return { title: '진단 전체', short: '진단',
        html: `<div class="nv-group">${fixes.map((x, k) => `<button type="button" class="nv-row" data-push="issue:${esc(x.id)}"><span class="nv-num t-${tone(x)}">${k + 1}</span><span class="nv-row-main"><b>${esc(x.title)}</b><small>${esc(EV[x.evidence])}</small></span><i class="nv-chev">${I.chev}</i></button>`).join('') || '<p class="nv-empty">근거가 있는 문제를 찾지 못했어요.</p>'}</div>
          <p class="nv-note">순서는 영향 → 근거 → 바로 고칠 수 있는가 순이에요. 개수를 채우려고 지어내지 않았어요.</p>
          ${unsureOf().length ? `<div class="nv-group" style="margin-top:12px"><button type="button" class="nv-row" data-push="unsure"><span class="nv-ico i-gray">${I.q}</span><span class="nv-row-main"><b>판정을 못 한 것</b><small>믿기 어려워서 위 목록에서 뺐어요</small></span><span class="nv-val">${unsureOf().length}개</span><i class="nv-chev">${I.chev}</i></button></div>` : ''}` };
    }
    function strengths() {
      return { title: '잘한 점', short: '잘한 점',
        html: `<div class="nv-group">${V.strengths.map((x) => `<button type="button" class="nv-row" data-push="issue:${esc(x.id)}">${badge(x)}<span class="nv-row-main"><b>${esc(x.title)}</b><small>${esc(EV[x.evidence])}</small></span><i class="nv-chev">${I.chev}</i></button>`).join('') || '<p class="nv-empty">근거가 있는 잘한 점이 아직 없어요.</p>'}</div>` };
    }
    function unsure() {
      const list = unsureOf();
      return { title: '판정을 못 한 것', short: '판정 못 함',
        html: `<div class="nv-callout"><b>믿기 어려운 판정은 고칠 것에서 뺐어요</b><p>근거끼리 어긋나거나 분석이 끝까지 판정하지 못한 것이에요. 자료 장을 보며 한 번 더 설명해 보면 다음 분석에서 판정할 수 있어요.</p></div>
          <div class="nv-group" style="margin-top:12px">${list.map((x) => `<button type="button" class="nv-row" data-push="issue:${esc(x.id)}">${badge(x)}<span class="nv-row-main"><b>${esc(x.title)}</b><small>${x.status === 'conflicting' ? '판정과 근거 글이 어긋나요' : '분석이 끝까지 판정하지 못했어요'}</small></span><i class="nv-chev">${I.chev}</i></button>`).join('')}</div>` };
    }
    function details() {
      return { title: '자세한 분석', short: '자세히',
        html: `<div class="nv-group">${LEGACY.map((L, k) => `<button type="button" class="nv-row" data-push="legacy:${k}"><span class="nv-ico ${L.ico}">${I[L.icon]}</span><span class="nv-row-main"><b>${esc(L.name)}</b><small>${esc(L.line)}</small></span><i class="nv-chev">${I.chev}</i></button>`).join('')}</div>
          <p class="nv-note">「이전 리포트」 의 분석 탭을 그대로 담았어요. 같은 분석 결과를 다른 모양으로 보여 줘요.</p>` };
    }
    /* 발표 태도(베타) — 그리기는 js/behavior_report.js(rv2Html, docs/report-v2/BEHAVIOR_SCREEN.md). 없으면 빈 상태(기조 R17).
       맨 위에 베타 배너 한 줄 한 번(기조 R6) — 닫기 없음 */
    function attitude() {
      const BR = window.BehaviorReport;
      const banner = `<p class="hm-betabanner" role="note"><span class="hm-bb-i"><svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.6" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8 7.2v4.2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="8" cy="4.8" r="1" fill="currentColor"/></svg></span><b>시험 기능</b><span>총점에 안 들어가요</span></p>`;
      if (!BR || !D.behavior || typeof BR.rv2Screen !== 'function') {
        return { title: '발표 태도', short: '발표 태도', html: `${banner}<div class="rq-empty"><span class="nv-ico i-gray">${I.cam}</span><div><b>카메라를 켜고 발표하면 시선과 자세를 볼 수 있어요</b><p>영상은 이 기기 안에서만 분석해요.</p></div></div>` };
      }
      let sc = null;
      try {
        sc = BR.rv2Screen(D.behavior, { titles: (D.deck.slides || []).map((x) => x.title), questions: V.qa.map((q) => q.text) });
      } catch (err) { console.warn('[report-v2] 발표 태도', err); sc = null; }
      return { title: '발표 태도', short: '발표 태도', html: `${banner}${(sc && sc.html) || '<p class="nv-empty">카메라 분석을 그리지 못했어요.</p>'}`,
        /* 장면 카드 · 「먼저 살펴볼 한 가지」 에 「그 순간 듣기」 — 카메라 장면 시각(data-sec, t0 기준)을 녹음 시각으로 맞춰 다시 보기 순간을 찾는다.
           녹음 시간 밖이거나 장면 시각이 없으면 단추를 달지 않는다 */
        wire(el) {
          const p = D.behavior && D.behavior.present;
          const MS = momentsOf(V, D.behavior).filter((m) => m.lane === 'beh');
          if (!p || !MS.length) return;
          const t0 = typeof p.t0 === 'number' && isFinite(p.t0) ? p.t0 / 1000 : 0;
          el.querySelectorAll('.bh-rv2 [data-sec]').forEach((card) => {
            const sec = Number(card.dataset.sec);
            const m = isFinite(sec) ? momentAt(MS, `@${(sec + t0).toFixed(2)}:beh`) : null;
            const row = card.querySelector('.bh-chips');
            if (!m || !row) return;
            const box = document.createElement('div'); box.className = 'bh-act';
            const b = document.createElement('button');
            b.type = 'button'; b.className = 'nv-link bh-moment'; b.dataset.moment = momentRoute(m); b.textContent = momentWord();
            b.addEventListener('click', (e) => { e.stopPropagation(); goMoment(b.dataset.moment); });
            box.appendChild(b);
            // 장면 카드는 장면 칩 바로 아래, 「먼저 살펴볼 한 가지」 는 「다음엔」 아래(카드 끝) — 늘 같은 자리에 한 줄
            if (card.classList.contains('bh-hero')) card.appendChild(box); else row.after(box);
          });
        } };
    }

    /* 진단 하나 — 무엇이 · 왜 · 근거(실제 음성으로) · 청중 반응, 아래 「고쳐 보기」 */
    function issue(id) {
      const x = insight(id) || fixesOf()[0] || all()[0];
      if (!x) return { title: '진단', html: '<p class="nv-empty">진단이 없어요.</p>' };
      const t = timeOf(x);
      const cards = []; const rows = [];
      x.proofs.forEach((p, k) => {
        if (p.kind === 'said') cards.push(`<div class="nv-card nv-quote"><p class="nv-cap">말한 구절${p.anchor.start_sec != null ? ` · ${fmt(p.anchor.start_sec)}` : ''}${p.anchor.slide_no ? ` · ${p.anchor.slide_no}장` : ''}</p>
          <blockquote>${esc(p.text)}</blockquote><div class="nv-acts">${p.anchor.start_sec != null ? playBtn(`q${k}`, p.anchor.start_sec, p.anchor.end_sec, '실제 목소리로 듣기') : ''}
          <button type="button" class="nv-link" data-push="replay:${esc(x.id)}">발표에서 보기</button></div></div>`);
        else if (p.kind === 'deck') cards.push(`<div class="nv-card nv-deckq">${p.anchor.slide_no ? slideTag(p.anchor.slide_no, 'nv-thumb') : ''}<div><p class="nv-cap">자료 ${esc(p.anchor.slide_no || '')}장 원문</p><p class="nv-body">${esc(plainDeck(p.text))}</p></div></div>`);
        else if (p.kind === 'time') rows.push(`<div class="nv-row is-static"><span class="nv-ico i-gray">${I.wave}</span><span class="nv-row-main"><b>${esc(p.text)}</b><small>${fmt(p.anchor.start_sec)}–${fmt(p.anchor.end_sec)}</small></span>${p.anchor.start_sec != null ? playBtn(`t${k}`, p.anchor.start_sec, p.anchor.end_sec, '듣기') : ''}</div>`);
        else rows.push(`<div class="nv-row is-static"><span class="nv-ico i-gray">${I.doc}</span><span class="nv-row-main"><b>${esc(p.text)}</b></span></div>`);
      });
      return {
        title: x.title, short: '진단', eyebrow: `${x.polarity === 'strength' ? '잘한 점' : x.polarity === 'unknown' ? '판정 못 함' : '고칠 것'} · ${CRIT[x.criterion] || '종합'}`,
        html: `
        <div class="nv-status">${badge(x)}<span>${esc(EV[x.evidence])}</span></div>
        ${x.conflict ? `<div class="nv-callout t-ct"><b>판정이 흔들려요</b><p>${esc(x.conflict)}</p></div>` : ''}
        ${x.why ? `<h3 class="nv-sec">왜 이렇게 봤나요</h3><div class="nv-card"><p class="nv-body">${esc(x.why)}</p></div>` : ''}
        ${cards.length || rows.length ? `<h3 class="nv-sec">근거</h3>${cards.join('')}${rows.length ? `<div class="nv-group">${rows.join('')}</div>` : ''}`
          : '<div class="nv-callout"><b>근거가 없어요</b><p>분석이 이 판정의 근거를 남기지 않았어요. 믿기 어려운 판정이라 순위에서 뒤로 뺐어요.</p></div>'}
        ${x.remarks.length ? `<h3 class="nv-sec">청중 반응</h3><div class="nv-group">${x.remarks.map((r) => `<button type="button" class="nv-row" data-push="chick:${esc(r.speaker)}"><img class="nv-face" src="${esc(asset(`assets/chick-${r.speaker}-neutral.svg`))}" alt=""><span class="nv-row-main"><b>${esc(r.text)}</b><small>${esc(ST[r.status] || '')}</small></span><i class="nv-chev">${I.chev}</i></button>`).join('')}</div>` : ''}`,
        cta: x.polarity === 'strength' ? (t && audio ? { label: '이 부분 다시 듣기', attr: `data-play="cta" data-a="${t[0]}" data-b="${t[1]}"`, icon: I.play } : null) : { label: '고쳐 보기', attr: `data-push="coach:${esc(x.id)}"` },
      };
    }

    /* 코칭 — 원래 → 까닭 → 바꿔 말하기 를 옆으로 넘기는 카드 */
    function coach(id) {
      const x = insight(id) || fixesOf()[0];
      if (!x) return { title: '코칭', html: '<p class="nv-empty">고칠 것이 없어요.</p>' };
      const said = x.proofs.find((p) => p.kind === 'said' && p.status === 'supported');
      const times = x.proofs.filter((p) => p.kind === 'time');
      const acts = x.actions.filter((a) => a.text);
      const act = acts[0] || x.actions[0];
      const slide = (act && act.anchor && act.anchor.slide_no) || x.anchor.slide_no;
      const deck = (D.deck.slides || []).find((s) => s.slide_no === slide);
      const pages = [
        { k: '원래 발표', body: said ? `<blockquote>${esc(said.text)}</blockquote><p class="nv-cap">${fmt(said.anchor.start_sec)}–${fmt(said.anchor.end_sec)} · 받아쓰기 원문</p><div class="nv-acts">${playBtn('c0', said.anchor.start_sec, said.anchor.end_sec, '들어 보기')}</div>`
          : times.length ? times.map((p) => `<blockquote>${esc(p.text)}</blockquote>`).join('') : '<blockquote>이 부분을 말한 구절을 찾지 못했어요.</blockquote>' },
        { k: '진단한 까닭', body: `<blockquote>${esc(x.why || '분석이 까닭을 남기지 않았어요.')}</blockquote>${x.conflict ? `<p class="nv-cap t-ct-text">${esc(x.conflict)}</p>` : ''}` },
        { k: '이렇게 바꿔 말해요', accent: true, body: `${acts.length ? acts.slice(0, 3).map((a) => `<blockquote>${esc(a.text)}</blockquote>`).join('') : '<blockquote>제안 문장이 아직 없어요. 자료 원문을 보며 다시 설명해 봐요.</blockquote>'}<p class="nv-cap">근거 · ${esc((act && act.basis) || '없음')}</p>` },
      ];
      return {
        title: '이렇게 고쳐요', short: '코칭', eyebrow: x.title,
        html: `
        <div class="nv-pager" tabindex="0" aria-label="코칭 카드 세 장 — 옆으로 넘겨요">${pages.map((p, k) => `<article class="nv-page${p.accent ? ' is-accent' : ''}"><p class="nv-step">${k + 1} / ${pages.length} · ${esc(p.k)}</p>${p.body}</article>`).join('')}</div>
        <div class="nv-dots" aria-hidden="true">${pages.map((_, k) => `<i${k === 0 ? ' class="on"' : ''}></i>`).join('')}</div>
        <p class="nv-note">새로 지은 문장이 아니에요. ${esc((act && act.basis) || '')}에서 가져왔어요. 개념 전달 판정은 말한 내용을 자료와 대조해서 내리니, 자료의 핵심을 말로 옮기면 대조할 거리가 생겨요.</p>
        ${deck ? `<h3 class="nv-sec">자료 ${esc(slide)}장</h3><div class="nv-card nv-deckq">${slideTag(slide, 'nv-thumb')}<p class="nv-body">${esc(plainDeck(deck.raw_text || deck.title || '').slice(0, 360))}</p></div>` : ''}`,
        cta: { label: '이 부분 연습하기', attr: `data-push="practice:${esc(x.id)}"`, icon: I.redo },
        wire(el) {
          const pg = el.querySelector('.nv-pager'); const dots = [...el.querySelectorAll('.nv-dots i')];
          pg.addEventListener('scroll', () => { const w = pg.firstElementChild ? pg.firstElementChild.getBoundingClientRect().width : pg.clientWidth; const k = Math.round(pg.scrollLeft / Math.max(1, w)); dots.forEach((d, j) => d.classList.toggle('on', j === Math.min(dots.length - 1, k))); }, { passive: true });
        },
      };
    }

    /* 발표 다시 보기 — 장 그림 · 재생 · 시간축 · 받아쓰기 (10-17 바퀴 4: 근거를 들을 수 있게).
       시간축 아래 두 줄 — 진단 근거(점 · 판정 색)와 발표 태도 장면(막대 · 베타). 표시를 누르면 그 순간으로 간다: 장 그림 · 그때 한 말 · (녹음이 있으면) 그 구간 소리.
       녹음이 없으면 소리만 빠지고 장 그림 · 받아쓰기 줄은 그대로. 발표 태도 기록이 없으면 그 줄이 없다. Q&A 는 따로라 넣지 않는다.
       arg: 진단 id(「발표에서 보기」) · 「@초」 · 「진단id@초」 · 「@초:beh」(그 순간 듣기) */
    function replay(arg) {
      const at = String(arg || '').lastIndexOf('@');
      const focus = insight(at > 0 ? arg.slice(0, at) : arg);
      const MS = momentsOf(V, D.behavior);
      const pick = momentAt(MS, arg) || (focus ? MS.find((m) => m.insight === focus.id) : null);
      const t = timeOf(focus);
      const dur = V.duration_sec || 0;
      const pct = (s) => `${(100 * Math.max(0, Math.min(dur, s)) / (dur || 1)).toFixed(3)}%`;
      const hit = new Set(focus && at < 0 ? focus.proofs.flatMap((p) => (p.kind === 'said' && p.anchor.utt_ids) || []) : []);
      const slideAt = (s) => (V.slides.find((sl) => sl.spans.some((sp) => s >= sp.start && s < sp.end)) || {}).no || 1;
      const s0 = pick ? pick.slide || slideAt(pick.t) : t ? slideAt(t[0]) : (focus && focus.anchor.slide_no) || 1;
      const LANES = [['fix', '진단'], ['beh', '태도']].filter(([k]) => MS.some((m) => m.lane === k));
      const tones = ['mid', 'ct', 'ok'].filter((k) => MS.some((m) => m.lane === 'fix' && m.tone === k));
      const TONE_WORD = { mid: '고칠 것', ct: '판정이 흔들림', ok: '잘한 점' };
      const marker = (m) => (m.lane === 'beh'
        ? `<button type="button" class="rp-m is-bar" data-m="${m.id}" style="left:${pct(m.t)};width:${pct((m.end || m.t) - m.t)}" aria-label="${esc(`${fmt(m.t)} · ${m.title}`)}"></button>`
        : `<button type="button" class="rp-m is-dot t-${m.tone}" data-m="${m.id}" style="left:${pct(m.t)}" aria-label="${esc(`${fmt(m.t)} · ${m.title}`)}"></button>`);
      const hint = audio ? '표시를 누르면 그 순간의 장 · 말 · 소리로 가요' : '표시를 누르면 그 순간의 장과 그때 한 말로 가요';
      const timeline = `<div class="rp-tl${LANES.length ? '' : ' is-bare'}" style="--rows:${LANES.length}">
            ${LANES.length ? `<div class="rp-keys" aria-hidden="true"><span></span>${LANES.map(([, w]) => `<span>${w}</span>`).join('')}</div>` : ''}
            <div class="rp-axis">
              <div class="nv-track" role="slider" tabindex="0" aria-label="발표 시간축" aria-valuemin="0" aria-valuemax="${Math.round(dur)}">
                ${V.slides.flatMap((s) => s.spans.map((sp) => `<span class="nv-band" style="left:${pct(sp.start)};width:${pct(sp.end - sp.start)}"><em>${s.no}${(sp.end - sp.start) / (dur || 1) < 0.1 ? '' : '장'}</em></span>`)).join('')}
              </div>
              ${LANES.map(([k, w]) => `<div class="rp-lane" role="group" aria-label="${w === '태도' ? '발표 태도 장면 · 베타' : '진단 근거'}">${MS.filter((m) => m.lane === k).map(marker).join('')}</div>`).join('')}
              <i class="nv-head"></i>
            </div>
          </div>`;
      const caption = MS.length ? `<div class="rp-cap" aria-live="polite">
            <div class="rp-cap-top"><p class="rp-cap-k">순간 ${MS.length}개</p>
              <span class="rp-steps"><button type="button" class="rp-step" data-step="-1" aria-label="앞 순간">${I.back}</button><span class="rp-n"></span><button type="button" class="rp-step is-next" data-step="1" aria-label="다음 순간">${I.chev}</button></span></div>
            <p class="rp-cap-t">${hint}</p><p class="rp-cap-s" hidden></p><p class="rp-cap-q" hidden></p><div class="rp-cap-acts" hidden></div>
          </div>` : '';
      let cur = null;
      let forced = 0;   // 발표 태도 장면은 카메라가 본 장(seg)을 그대로 보인다 — 재생이 시작되면 녹음 시각의 장으로
      function seekView(el, now, slide) {
        const head = el.querySelector('.nv-head'); if (head) head.style.left = pct(now);
        const clk = el.querySelector('.nv-clock'); if (clk) clk.textContent = `${fmt(now)} / ${fmt(dur)}`;
        const u = V.utterances.find((x) => x.start <= now && x.end >= now);
        el.querySelectorAll('.nv-line.is-now').forEach((l) => l.classList.remove('is-now'));
        if (u) { const l = el.querySelector(`.nv-line[data-u="${u.id}"]`); if (l) l.classList.add('is-now'); }
        const sl = slide || slideAt(now); const img = el.querySelector('.nv-stage img');
        if (img && img.dataset.slide !== String(sl)) el.querySelector('.nv-stage').innerHTML = slideTag(sl, 'nv-slide');
      }
      function select(el, m, { sound = false } = {}) {
        if (!m) return;
        cur = m;
        el.querySelectorAll('.rp-m.is-on').forEach((b) => b.classList.remove('is-on'));
        const mk = el.querySelector(`.rp-m[data-m="${m.id}"]`); if (mk) mk.classList.add('is-on');
        const k = MS.indexOf(m);
        const line = m.quote ? { text: m.quote } : lineAt(V.utterances, m.t, m.end, !!m.span);
        const sl = m.slide || slideAt(m.t);
        el.querySelector('.rp-cap-k').textContent = `${m.more} · ${fmt(m.t)} · ${sl}장`;
        el.querySelector('.rp-n').textContent = `${k + 1} / ${MS.length}`;
        el.querySelector('.rp-cap-t').textContent = m.title;
        const s = el.querySelector('.rp-cap-s'); s.textContent = m.sub; s.hidden = !m.sub;
        const q = el.querySelector('.rp-cap-q'); q.textContent = line ? `그때 한 말 “${line.text}”` : '이 순간엔 받아쓴 말이 없어요'; q.hidden = false;
        const a = m.lane === 'beh' ? Math.max(0, m.t - 1) : m.t;
        const b = m.end != null ? m.end + (m.lane === 'beh' ? 0.5 : 0) : Math.min(dur, m.t + 8);
        const acts = el.querySelector('.rp-cap-acts'); acts.hidden = false;
        acts.innerHTML = `${audio ? playBtn(`m:${m.id}`, a, b, '그 순간 듣기') : ''}<button type="button" class="nv-link" data-push="${m.lane === 'beh' ? 'attitude' : `issue:${esc(m.insight)}`}">${m.lane === 'beh' ? '발표 태도 보기' : '자세히 보기'}</button>`;
        wire(acts);
        forced = m.lane === 'beh' ? sl : 0;
        seekView(el, m.t, sl);
        if (audio) {
          if (sound || !audio.paused) play(a, b, `m:${m.id}`);
          else { try { audio.currentTime = m.t; } catch (_) { /* 메타데이터 전 */ } }
        }
        paintPlay();
      }
      return {
        title: '발표 다시 보기', short: '다시 보기', eyebrow: focus ? focus.title : `${D.sample ? '샘플 · ' : ''}${D.deck.title}`,
        html: `
        <div class="rp-stick"><div class="nv-stage">${slideTag(s0, 'nv-slide')}</div></div>
        <div class="nv-card nv-player">
          <div class="nv-player-row">
            <button type="button" class="nv-bigplay" data-play="${t ? 'focus' : 'all'}" data-a="${t ? t[0] : 0}" data-b="${t ? t[1] : ''}" ${audio ? '' : 'disabled'} aria-label="${t ? '이 구간 듣기' : '처음부터 듣기'}" ${audio ? '' : 'hidden'}><span class="nv-pi">${I.play}</span></button>
            <div class="nv-player-txt"><b>${!audio ? '받아쓰기로 다시 보기' : t ? `${fmt(t[0])}–${fmt(t[1])} 구간` : '처음부터 듣기'}</b><small class="nv-clock">0:00 / ${fmt(dur)}</small></div>
          </div>
          ${timeline}
          ${tones.length ? `<div class="nv-legend">${tones.map((k) => `<span><i class="t-${k}"></i>${TONE_WORD[k]}</span>`).join('')}</div>` : ''}
          ${caption}
          ${D.transcript && D.transcript.marks_estimated ? '<p class="nv-cap rp-note">장 경계는 녹음 내용으로 추정한 대략 위치예요.</p>' : ''}
          ${audio ? '' : '<p class="nv-cap rp-note">녹음이 이 기기에 남아 있지 않아 소리는 들을 수 없어요.</p>'}
        </div>
        ${typeof window.__rv2Legacy === 'function' ? `<div class="nv-group" style="margin-top:12px"><button type="button" class="nv-row" data-push="legacy:0"><span class="nv-ico i-blue">${I.doc}</span><span class="nv-row-main"><b>슬라이드로 보는 발표</b><small>장마다 판정 · 그 장에서 한 말</small></span><i class="nv-chev">${I.chev}</i></button><button type="button" class="nv-row" data-push="legacy:1"><span class="nv-ico i-orange">${I.wave}</span><span class="nv-row-main"><b>말하기</b><small>말 속도 · 시간 배분 · 말버릇</small></span><i class="nv-chev">${I.chev}</i></button></div>` : ''}
        <h3 class="nv-sec">받아쓰기</h3>
        <div class="nv-group nv-lines">${V.utterances.map((u) => `<button type="button" class="nv-line${hit.has(u.id) ? ' is-hit' : ''}" data-u="${esc(u.id)}" data-s="${u.start}"><time>${fmt(u.start)}</time><span>${esc(u.text)}</span></button>`).join('') || '<p class="nv-empty">받아쓰기가 없어요.</p>'}</div>`,
        onTime(now) {
          const el = stack[stack.length - 1].el;
          if (audio && !audio.paused) forced = 0;
          seekView(el, now, forced);
        },
        wire(el) {
          el.querySelectorAll('.nv-line').forEach((b) => b.addEventListener('click', () => { forced = 0; if (audio) play(+b.dataset.s, null, `u${b.dataset.u}`); else seekView(el, +b.dataset.s); }));
          const tr = el.querySelector('.nv-track');
          tr.addEventListener('click', (e) => { const r = tr.getBoundingClientRect(); const s = ((e.clientX - r.left) / r.width) * dur; forced = 0; if (audio) play(s, null, 'scrub'); else seekView(el, s); });
          tr.addEventListener('keydown', (e) => { if (!audio) return; if (e.key === 'ArrowRight') audio.currentTime += 5; if (e.key === 'ArrowLeft') audio.currentTime -= 5; });
          el.querySelectorAll('.rp-m').forEach((b) => b.addEventListener('click', (e) => { e.stopPropagation(); select(el, MS.find((m) => m.id === b.dataset.m), { sound: true }); }));
          el.querySelectorAll('.rp-step').forEach((b) => b.addEventListener('click', () => {
            const k = cur ? MS.indexOf(cur) + Number(b.dataset.step) : (Number(b.dataset.step) > 0 ? 0 : MS.length - 1);
            select(el, MS[(k + MS.length) % MS.length]);
          }));
          if (pick) {
            const sound = autoPlayNext; autoPlayNext = false; select(el, pick, { sound });
            // 「그 순간 듣기」 로 왔으면 시간축 · 고른 순간이 보이게 — 폰에선 붙어 있는 장 그림 바로 아래로
            if (at >= 0) setTimeout(() => {
              const sc = el.querySelector('.nv-scroll'); const st = el.querySelector('.rp-stick'); const pl = el.querySelector('.nv-player');
              if (!sc || !st || !pl || getComputedStyle(st).position !== 'sticky') return;
              const y = pl.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop - st.offsetHeight;
              sc.scrollTo({ top: Math.max(0, y), behavior: reduced() ? 'auto' : 'smooth' });
            }, 220);
          }
          const h = el.querySelector('.nv-line.is-hit');
          if (h) setTimeout(() => { const sc = el.querySelector('.nv-scroll'); sc.scrollTo({ top: h.offsetTop - sc.clientHeight / 2, behavior: reduced() ? 'auto' : 'smooth' }); }, 240);
        },
      };
    }

    /* 삐약이 청중석 — 와우 포인트: 조명이 켜지는 어두운 무대 한 칸. 고르면 그 삐약이 화면으로 */
    function audience() {
      const evs = V.evaluators;
      return {
        title: '삐약이 청중석', short: '청중석',
        html: `<div class="nv-theater"><i class="nv-spot"></i>
          <p>점수를 매기는 심사위원이 아니에요.<br>넷이 저마다 맡은 것만 보고 한마디씩 해요.</p>
          <div class="nv-seats">${evs.length ? evs.map((e, k) => `<button type="button" class="nv-seat${e.absent ? ' is-off' : ''}" data-push="chick:${esc(e.key)}" style="--k:${k}">
            <img src="${esc(asset(`assets/chick-${e.key}-${e.absent ? 'neutral' : MOOD[(e.remarks.find((r) => !r.filler) || {}).mood] || 'neutral'}.svg`))}" alt="">
            <b>${esc(e.name)}</b><small>${e.absent ? '이번엔 못 왔어요' : `${e.remarks.filter((r) => !r.filler).length}마디`}</small></button>`).join('')
            : '<p class="nv-empty">청중 반응을 불러오고 있어요.</p>'}</div></div>
        <h3 class="nv-sec">맡은 것</h3>
        <div class="nv-group">${evs.map((e) => `<button type="button" class="nv-row" data-push="chick:${esc(e.key)}"><img class="nv-face" src="${esc(asset(`assets/chick-${e.key}-neutral.svg`))}" alt=""><span class="nv-row-main"><b>${esc(e.name)}</b><small>${esc(e.lane)} · ${esc(e.model)}</small></span><span class="nv-val">${e.absent ? '결석' : `${e.remarks.filter((r) => !r.filler).length}마디`}</span><i class="nv-chev">${I.chev}</i></button>`).join('')}</div>
        <p class="nv-note">말마다 분석 근거와 맞는지 같이 보여 드려요. 근거가 없는 말은 근거처럼 보이지 않게 표시해요.</p>`,
      };
    }
    function chick(key) {
      const e = V.evaluators.find((x) => x.key === key);
      if (!e) return { title: '청중', html: '<p class="nv-empty">이 삐약이의 기록이 없어요.</p>' };
      const real = e.remarks.filter((r) => !r.filler);
      const engine = (cid) => { const a = G.nodes.get(`A:align:${cid.slice(2)}`); const v = G.nodes.get(`V:said:${cid.slice(2)}`);
        return a ? { word: UI_WORD[a.ui_status] || a.ui_status, cls: `v-${a.ui_status}`, said: v && v.status === 'supported' ? v.text : '' } : null; };
      const jump = (cid) => { const hit = all().find((x) => x.concepts.some((c) => c.id === cid)); return hit ? `issue:${hit.id}` : 'replay'; };
      const stTone = (s) => (s === 'supported' ? 'ok' : s === 'conflicting' ? 'ct' : s === 'unsupported' ? 'no' : 'na');
      return {
        title: e.name, short: e.name, eyebrow: `${e.model} · ${e.lane}`,
        top: `<div class="nv-chickhero"><img src="${esc(asset(`assets/chick-${e.key}-${e.absent ? 'neutral' : MOOD[(real[0] || {}).mood] || 'neutral'}.svg`))}" alt=""></div>`,
        html: `
        ${e.absent ? '<div class="nv-callout"><b>이번엔 객석에 못 왔어요</b><p>모델 응답이 실패했어요. 대신 나온 대사는 근거로 쓰지 않아요.</p></div>' : ''}
        ${real.map((r) => { const eng = r.concepts.map((c) => ({ c, x: engine(c.id) })).filter((y) => y.x);
          return `<div class="nv-card nv-remark"><p class="nv-bubble">${esc(r.text)}</p>
            <div class="nv-status"><span class="nv-dot t-${stTone(r.status)}"></span><span>${esc(ST[r.status] || '')}</span></div>
            ${r.why && !eng.length ? `<p class="nv-cap">${esc(r.why)}</p>` : ''}
            ${eng.map(({ c, x }) => `<p class="nv-cap">분석 엔진은 「${esc(c.label)}」을 <b class="${x.cls}">${esc(x.word)}</b>으로 봤어요${x.said ? ` — “${esc(x.said)}”` : ''}</p>`).join('')}
            ${r.concepts.length ? `<div class="nv-acts">${r.concepts.map((c) => `<button type="button" class="nv-link" data-push="${esc(jump(c.id))}">「${esc(c.label)}」 근거 보기</button>`).join('')}</div>` : ''}</div>`; }).join('')}
        ${real.some((r) => r.status === 'conflicting') ? '<p class="nv-note">의견이 갈리는 곳이 있어요. 청중은 그 낱말이 나왔는지를, 분석 엔진은 뜻이 자료와 맞는지를 봐요. 억지로 맞추지 않았어요.</p>' : ''}`,
      };
    }

    /* 다시 연습 — 갈 곳. Q&A 돌아보기 목록은 홈 카드로 옮겼다(10-17 §5-4) — 여기엔 「질문 다시 받기」 행동만 */
    function practice(id) {
      const x = insight(id) || fixesOf()[0];
      const targets = [];
      (x ? x.actions : []).forEach((a) => { if (a.practice && !targets.some((p) => p.label === a.practice.label)) targets.push(a.practice); });
      if (V.qa.some((q) => q.result) && !targets.some((p) => p.kind === 'qa')) targets.push({ label: '질문 다시 받기', route: '#/rehearsal/qa', kind: 'qa' });
      targets.push({ label: '처음부터 다시 발표하기', route: '#/rehearsal', kind: 'full' });
      const why = (p) => (p.kind === 'qa' ? '받았던 질문을 Q&A 에서 다시 받아요' : p.kind === 'slide' ? '리허설에서 그 장부터 다시 말해요' : '리허설을 새로 시작해요');
      return {
        title: '다시 연습', short: '연습', eyebrow: x ? x.title : '',
        html: `
        <h3 class="nv-sec">어디부터 할까요</h3>
        <div class="nv-group">${targets.map((p) => `<button type="button" class="nv-row" data-href="index.html${esc(p.route)}"><span class="nv-ico i-green">${I.redo}</span><span class="nv-row-main"><b>${esc(p.label)}</b><small>${why(p)}${EMBED ? ' — 앱에서 열려요' : ''}</small></span><i class="nv-chev">${I.chev}</i></button>`).join('')}</div>
        <p class="nv-note">다시 연습한 결과는 아직 이 진단에 이어지지 않아요. 그래서 나아졌는지는 보여 주지 않아요.</p>
        ${typeof window.__rv2Legacy === 'function' ? `<h3 class="nv-sec">연습 도구</h3><div class="nv-group"><button type="button" class="nv-row" data-push="legacy:5"><span class="nv-ico i-green">${I.doc}</span><span class="nv-row-main"><b>개념도 · 펀치라인 · 용어 카드</b><small>발표 직전에 챙길 것</small></span><i class="nv-chev">${I.chev}</i></button><button type="button" class="nv-row" data-push="legacy:6"><span class="nv-ico i-blue">${I.chart}</span><span class="nv-row-main"><b>발표 구성 다시 짜기</b><small>누르면 순서 · 클라이맥스 · 덧붙일 장을 제안해요</small></span><i class="nv-chev">${I.chev}</i></button></div>` : ''}`,
      };
    }
    /* Q&A 한 질문 — 메신저처럼 다 늘어놓지 않고 전환점만: 내 답 → AI 가 주목한 말 → 꼬리질문 (report_v2_qa.js 가 없을 때만) */
    function qaChat(qid) {
      const q = V.qa.find((x) => x.id === qid);
      if (!q) return { title: 'Q&A', html: '<p class="nv-empty">이 질문의 기록이 없어요.</p>' };
      const hl = (text, claim) => { const k = claim ? text.indexOf(claim) : -1; return k < 0 ? esc(text) : `${esc(text.slice(0, k))}<mark>${esc(claim)}</mark>${esc(text.slice(k + claim.length))}`; };
      return {
        title: q.text, short: '질문', eyebrow: q.label,
        html: `
        <div class="nv-chat">${q.steps.length ? q.steps.map((s) => `
          <div class="nv-msg me"><p>${s.answer ? hl(s.answer, s.claim) : s.claim ? `<mark>${esc(s.claim)}</mark>` : ''}</p></div>
          ${s.claim ? `<p class="nv-why">AI 가 주목한 내 말 「${esc(s.claim)}」</p>` : ''}
          ${s.followup ? `<div class="nv-msg ai"><img src="${esc(asset('assets/chick-solar-curious.svg'))}" alt=""><p>${esc(s.followup)}</p></div>` : ''}`).join('') : '<p class="nv-empty">답하지 않았어요.</p>'}</div>
        ${q.gist ? `<h3 class="nv-sec">자료가 기대한 답</h3><div class="nv-card"><p class="nv-body">${esc(q.gist)}</p></div>` : ''}
        ${D.provenance && D.provenance.qa ? `<p class="nv-note">${esc(D.provenance.qa)}</p>` : ''}
        ${QBS ? QBS.link(q.text) : ''}`,
      };
    }
    /* 자세한 분석 — 옛 리포트(#/rehearsal/report)의 분석 탭을 그대로(같은 코드 · 같은 데이터) 한 화면에 품는다. 기능을 지우지 않는다
       (10-16 사용자 「리포트 기능들을 삭제하면 안 되는데 — 슬라이드 보여 주고 말 어투 찾아 주고 등등」). 앱 안에서만(window.__rv2Legacy) */
    function legacy(arg) {
      const i = Math.max(0, Math.min(LEGACY.length - 1, Number(arg) || 0));
      const L = LEGACY[i];
      if (typeof window.__rv2Legacy !== 'function') return { title: L.name, short: L.short, html: '<p class="nv-empty">이 분석은 앱 안 리포트에서 볼 수 있어요.</p>' };
      return { title: L.name, short: L.short, eyebrow: '자세한 분석', wide: true,
        html: '<div class="nv-legacyhost"></div>',
        // 옛 탭은 문서에서 #rbody 를 찾는다 — 화면이 문서에 붙은 뒤에 그린다
        wire(el) { const host = el.querySelector('.nv-legacyhost'); const run = () => (host.isConnected ? window.__rv2Legacy(i, host) : requestAnimationFrame(run)); run(); } };
    }
    /* 기준별 점수 — 약한 순 · 비중 · 못 잰 항목 · 안 본 항목 · 항목별 근거 · AI 총평(접힘) (10-17 §4-1) */
    function scores() {
      const sc = V.score;
      if (!sc) return { title: '기준별 점수', short: '점수', html: '<p class="nv-empty">점수가 없어요.</p>' };
      const list = sc.criteria.slice().sort((a, b) => (a.scored === b.scored ? a.average - b.average : a.scored ? -1 : 1));
      const ai = V.ai || {};
      const aiList = (t, xs) => (xs && xs.length ? `<p class="sc-ai-k">${t}</p><ul>${xs.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : '');
      return {
        title: '기준별 점수', short: '점수', eyebrow: sc.situation ? `${sc.situation} 기준` : '',
        html: `<div class="sc-total"><b>${esc(Math.round(sc.value))}</b><span>점</span><small>${esc(grade(sc.value))} 등급 · 기준마다 비중을 곱해 더했어요</small></div>
          <div class="nv-group sc-list">${list.map((k, i) => `<div class="nv-row is-static nv-crit${i === 0 && k.scored ? ' is-weak' : ''}"><span class="nv-row-main"><b>${esc(k.name)}${i === 0 && k.scored ? ' <em class="sc-weak">가장 약해요</em>' : ''}</b>
            <span class="nv-meter"><i style="--w:${k.scored ? Math.round(k.average) : 0}%"></i></span>${k.weight != null ? `<small>비중 ${esc(Math.round(k.weight))}%</small>` : ''}</span>
            <span class="sc-val">${k.scored ? `<b>${Math.round(k.average)}</b><span>점</span>` : '<span>못 잼</span>'}</span></div>`).join('')}</div>
          ${sc.unmeasured.length || sc.excluded.length ? `<details class="nv-card sc-fold"><summary>못 잰 항목 <b>${sc.unmeasured.length}</b>개 · 안 본 항목 <b>${sc.excluded.length}</b>개</summary>
            ${sc.unmeasured.length ? `<p class="sc-ai-k">못 잰 항목 — 재료가 없어서 점수에서 뺐어요</p><ul>${sc.unmeasured.map((u) => `<li><b>${esc(u.name)}</b>${u.why ? ` — ${esc(u.why)}` : ''}</li>`).join('')}</ul>` : ''}
            ${sc.excluded.length ? `<p class="sc-ai-k">안 본 항목 — 이 발표 상황엔 맞지 않아요</p><ul>${sc.excluded.map((u) => `<li>${esc(u.name)}</li>`).join('')}</ul>` : ''}</details>` : ''}
          <p class="nv-note">39개 항목 → 7개 기준 채점 그대로예요. 같은 녹음도 채점할 때마다 조금씩 달라서 소수점은 보이지 않아요.${behaviorRow() ? ' 카메라로 본 발표 태도는 시험 기능이라 이 점수에 넣지 않았어요.' : ''}</p>
          ${typeof window.__rv2Legacy === 'function' ? `<div class="nv-group" style="margin-top:16px"><button type="button" class="nv-row" data-push="legacy:4"><span class="nv-ico i-gray">${I.doc}</span><span class="nv-row-main"><b>항목별 근거</b><small>39개 항목의 점수와 근거 · 이 점수는 아닌 것 같을 때</small></span><i class="nv-chev">${I.chev}</i></button></div>` : ''}
          ${ai.one_liner || (ai.strengths || []).length ? `<details class="nv-card sc-fold"><summary>AI 총평 보기</summary>
            ${ai.one_liner ? `<p class="nv-body">${esc(ai.one_liner)}</p>` : ''}${aiList('강점', ai.strengths)}${aiList('약점', ai.weaknesses)}${aiList('할 일', ai.actions)}
            <p class="nv-cap">근거와 잇지 않은 자유 글이라 홈 첫 줄에서 내렸어요.</p></details>` : ''}`,
      };
    }

    /* ── 시작 ── */
    build();
    setAudio();
    if (MODE === 'page') {
      rebuild(routesFromHash());
      history.replaceState({ rv2: stack.map((s) => s.route) }, '', hashOf());
      window.addEventListener('popstate', (e) => {
        const want = (e.state && e.state.rv2) || routesFromHash() || ['home'];
        if (want.length === stack.length - 1 && want.every((r, k) => r === stack[k].route)) back({ fromHistory: true });
        else rebuild(want);
      });
    } else {
      let saved = null;
      try { saved = JSON.parse(sessionStorage.getItem(STATE_KEY) || 'null'); } catch (_) { saved = null; }
      rebuild(saved && saved.key === D.deck.title ? saved.routes : null);
    }
    return {
      /** 늦게 온 재료(청중석 등)를 얹고 지금 스택 그대로 다시 그린다 */
      update(patch) { D = { ...D, ...patch }; build(); rebuild(stack.map((s) => s.route)); },
      /** 화면 하나를 밀어 넣는다 — 옛 분석 탭 안의 「판정 근거 자세히 보기」 같은 이동이 쓴다 */
      open(route) { push(route); },
      /** 탭 i 로 (스튜디오 정거장 · ← → 키) */
      tab(i) { if (TABS && TABS[i]) goRoot(TABS[i]); },
      destroy() { if (audio) audio.pause(); root.classList.remove('rv2'); root.innerHTML = ''; },
    };
  }

  /* ═══ 단독 페이지 ═══════════════════════════════════════════════════════ */
  async function loadPageData() {
    if (window.__RV2_DATA) return window.__RV2_DATA;
    const qs = new URLSearchParams(location.search);
    if (qs.get('src') === 'last') {
      let last = null;
      try { last = JSON.parse(localStorage.getItem('cheokcheok:last-report') || 'null'); } catch (_) { last = null; }
      if (!last || !last.pipelineOut) throw new Error('이 브라우저에 저장한 리포트가 없어요. 발표를 한 번 분석하면 생겨요.');
      return inputFromApp({ pipelineOut: last.pipelineOut, deck: { title: last.fileName || '', slides: (last.slideTitles || []).map((t, k) => ({ slide_no: k + 1, title: t })),
        audio_url: last.deckAudio ? `/api/v1/dev/decks/file?deck=${encodeURIComponent(last.deckAudio)}&kind=audio` : '' }, qa: last.qa, saved: '' });
    }
    const res = await fetch('data/report_v2_rec.json', { credentials: 'same-origin' });
    if (!res.ok) throw new Error(res.status === 404 ? '실측 묶음은 팀 브라우저에서만 열려요. /auth 에서 팀 코드를 넣은 뒤 다시 열어요.' : `데이터를 불러오지 못했어요 (${res.status}).`);
    return res.json();
  }
  async function bootPage(el) {
    try {
      mount(el, await loadPageData(), { mode: 'page' });
    } catch (err) {
      el.classList.add('rv2');
      el.innerHTML = `<div class="nv"><section class="nv-screen"><div class="nv-scroll"><h1 class="nv-large">리포트를 열지 못했어요</h1><p class="nv-lead">${esc(err.message || err)}</p></div></section></div>`;
    }
  }

  if (typeof window !== 'undefined') {
    window.ReportV2 = { mount, inputFromApp, bootPage, momentsOf, lineAt, momentAt, momentRoute };
    const pageRoot = typeof document !== 'undefined' && document.getElementById && document.getElementById('rv2Page');
    if (pageRoot) bootPage(pageRoot);
  }
})();
