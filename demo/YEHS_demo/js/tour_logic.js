/**
 * 모바일 체험 투어(#/tour/*) — 화면 없이 도는 순수 함수 (2026-10-11, docs/booth-mobile/).
 *
 * 투어는 녹화된 응답만 재생한다(API 0 · 카메라·마이크 0). 그래서 「지금 몇 초에 어느 장 · 어느 자막 · 어느 코칭 칩이
 * 떠야 하나」 · 「주소가 어느 단계인가」 · 「녹화 파일이 계약(tour.schema.json v1)대로인가」 가 이 파일의 전부다.
 * 브라우저에서만 틀리는 판단을 여기로 빼 두고 tests/js/tour.smoke.mjs 가 node 로 잡는다(vm 으로 이 파일 그대로 올린다).
 *
 * 전역은 window.TourLogic 하나. js/tour.js · js/tour_play.js 가 쓴다.
 */
(function (root) {
  'use strict';

  /** 단계 막대에 서는 다섯 단계 — 주소 마디 · 막대 글자. 시작 안내(#/tour)와 끝 화면(#/tour/done)은 막대 밖이다 */
  const STEPS = [
    { id: 'deck', label: '자료' },
    { id: 'present', label: '발표' },
    { id: 'analysis', label: '분석' },
    { id: 'qa', label: '질문' },
    { id: 'report', label: '리포트' },
  ];
  const SCREENS = ['intro', ...STEPS.map((s) => s.id), 'done'];
  /** 옛 이름 · 다른 이름 → 계약 이름 (계약 README 는 analysis, 작업 지시는 analyze 라고 적었다 — 둘 다 받는다) */
  const ALIASES = { analyze: 'analysis', start: 'intro', end: 'done', finish: 'done' };

  /** 3단계 말 — 계약 공통 규칙. 화면 글자는 이 셋으로 고정 */
  const LEVEL_WORD = { good: '좋아요', fair: '보통', practice: '더 연습' };
  /** 3단계 → 판정 색 칩 (eval_lab 과 같은 짝: 좋아요 ok · 보통 mid · 더 연습 no) */
  const LEVEL_TONE = { good: 'ok', fair: 'mid', practice: 'no' };
  /** 답 판정(F-09) — 질문 코칭(qa_live.js LIVE_VERDICT)과 같은 낱말 · 색. 새로 짓지 않는다 */
  const VERDICT = {
    good: { word: '설득 완료', tone: 'ok' },
    partial: { word: '부분 인정', tone: 'mid' },
    wrong: { word: '미방어', tone: 'no' },
    unknown: { word: '판정 보류', tone: 'om' },
  };
  /** 근거 줄 역할 — qa_live.js LIVE_GROUND_ROLE 과 같은 글자 */
  const GROUND_ROLE = { covered: '짚은 것', missing: '빠진 것', conflict: '다시 볼 곳' };
  /** 주장 그래프 상태 — graph3d.js 범례와 같은 짧은 말 · 긴 말 · 색 */
  const GRAPH_STATUS = {
    aligned: { word: '잘 설명함', long: '자기 말로 설명했어요', tone: 'ok' },
    justified_skip: { word: '넘어가도 됨', long: '넘어가도 되는 개념이에요', tone: 'om' },
    missing: { word: '아직', long: '아직 설명하지 않았어요', tone: 'no' },
    contradiction: { word: '다르게', long: '자료와 다르게 말했어요', tone: 'ct' },
  };
  /** 코칭 칩 종류 → 삐약이 표정 · 「AI 가 지금 보는 것」 한 줄 */
  const CHIP_KIND = {
    listen: { mood: 'happy', looks: '발표를 듣고 있어요' },
    fast: { mood: 'curious', looks: '말 속도를 재고 있어요' },
    slow: { mood: 'neutral', looks: '말 속도를 재고 있어요' },
    quiet: { mood: 'neutral', looks: '목소리 크기를 듣고 있어요' },
    loud: { mood: 'curious', looks: '목소리 크기를 듣고 있어요' },
    filler: { mood: 'curious', looks: '군더더기 말을 세고 있어요' },
    time: { mood: 'curious', looks: '장마다 쓴 시간을 재고 있어요' },
  };
  /** 코칭 칩이 「지금」 으로 떠 있는 시간(녹화 초) */
  const CHIP_HOLD_SEC = 7;

  /**
   * 주소 → { screen, q }. #/tour → intro, #/tour/qa/2 → { screen:'qa', q:1 }(0부터). 모르는 마디는 intro.
   * @param {string} hash location.hash
   */
  function parseTourHash(hash) {
    const parts = String(hash || '').replace(/^#\/?/, '').split('?')[0].split('/').filter(Boolean);
    if (parts[0] !== 'tour') return null;
    const raw = String(parts[1] || 'intro').toLowerCase();
    const screen = ALIASES[raw] || raw;
    if (!SCREENS.includes(screen)) return { screen: 'intro', q: 0, alias: true };
    const n = Number(parts[2]);
    const q = screen === 'qa' && Number.isInteger(n) && n >= 1 ? n - 1 : 0;
    return { screen, q, alias: screen !== raw };
  }

  /** 화면 → 주소. qa 는 둘째 질문부터 번호를 붙인다(#/tour/qa/2) */
  function tourHash(screen, q = 0) {
    if (!screen || screen === 'intro') return '#/tour';
    if (screen === 'qa' && q > 0) return `#/tour/qa/${q + 1}`;
    return `#/tour/${screen}`;
  }

  /** 단계 막대 번호(1~5). 막대 밖 화면은 0 */
  function stepIndex(screen) {
    const i = STEPS.findIndex((s) => s.id === screen);
    return i < 0 ? 0 : i + 1;
  }

  /** 뒤로 — 앞 화면. 시작 안내의 앞은 팀 소개(/hi) */
  function prevScreen(screen, q = 0) {
    if (screen === 'qa' && q > 0) return { screen: 'qa', q: q - 1 };
    const i = SCREENS.indexOf(screen);
    if (i <= 0) return null;
    const prev = SCREENS[i - 1];
    return { screen: prev, q: 0 };
  }

  /**
   * 위 띠 「‹」 가 할 일 (10-12 점검 layout-touch-a11y-r1-3 · flow-regression-inapp-r1-3).
   *  · 시작 안내의 앞은 언제나 팀 소개. /hi 에서 막 들어온 첫 기록이면 브라우저 뒤로(기록을 하나 더 쌓으면 그다음 폰 뒤로가 투어로
   *    돌아오는 고리가 됐다), 아니면 /hi 로 바꿔 간다(replace). 투어 안에서 쌓은 시작 안내(처음부터 다시)도 뒤로 가 끝 화면이 나오지 않게 /hi.
   *  · 다른 화면은 투어 안에서 쌓은 기록이면 브라우저 뒤로, 바로 들어왔으면 앞 화면으로 바꿔 간다.
   * @returns {{kind:'history'}|{kind:'hi'}|{kind:'screen',screen:string,q:number}}
   */
  function backAction({ screen, q = 0, tourIn = false, fromHi = false }) {
    if (screen === 'intro' || !SCREENS.includes(screen)) return !tourIn && fromHi ? { kind: 'history' } : { kind: 'hi' };
    if (tourIn) return { kind: 'history' };
    const prev = prevScreen(screen, q);
    return prev ? { kind: 'screen', screen: prev.screen, q: prev.q } : { kind: 'hi' };
  }

  /** 처음부터 다시 — 투어 안에서 쌓은 깊이(history.state.depth)만큼 되돌아가 첫 시작 안내 기록으로. 모르면 시작 안내로 바꿔 간다 */
  function restartAction(depth) {
    const d = Number(depth) || 0;
    return d > 0 ? { kind: 'go', delta: -d } : { kind: 'replace' };
  }

  /** document.referrer 가 같은 출처의 /hi · /hi/<id> 인가 */
  function cameFromHi(referrer, origin) {
    const m = String(referrer || '').match(/^(https?:\/\/[^/]+)(\/[^?#]*)/i);
    return !!m && m[1] === origin && /^\/hi(?:\/[a-z0-9-]{1,24})?\/?$/i.test(m[2]);
  }

  /* ── 녹화 데이터 ─────────────────────────────────────────────── */

  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : NaN);

  /**
   * 녹화 파일이 화면이 그릴 수 있는 모양인가 — 계약 v1 의 뼈대만 본다(전체 검사는 pytest 가 스키마로 한다).
   * 모르는 버전 · 빠진 칸이면 이유 문자열, 괜찮으면 ''.
   */
  function tourProblem(t) {
    if (!t || typeof t !== 'object') return '파일이 비어 있어요';
    if (t.schema !== 'chuckchuck.tour') return '투어 파일이 아니에요';
    if (t.version !== 1) return `모르는 버전(${t.version})이에요`;
    const d = t.deck, p = t.present, a = t.analysis, q = t.qa, r = t.report;
    if (!d || !Array.isArray(d.slides) || !d.slides.length) return '자료 장이 없어요';
    if (!p || !Array.isArray(p.slides) || !p.slides.length || !(num(p.duration_sec) > 0)) return '발표 녹화가 없어요';
    if (!a || !Array.isArray(a.slide_times)) return '분석이 없어요';
    if (!q || !Array.isArray(q.questions) || !q.questions.length) return '질문이 없어요';
    if (!r || !Array.isArray(r.items)) return '리포트가 없어요';
    return '';
  }

  /**
   * data/tour/index.json 의 모양을 투어 id 목록으로 편다. 계약에 아직 없는 파일이라 셋을 다 받는다:
   *  ① 투어 파일 그 자체(schema chuckchuck.tour) → 그 하나  ② { tours:[{id}|"id"], default? }  ③ ["id", …]
   * @returns {{ ids: string[], inline: object|null, first: string }}
   */
  function indexIds(idx) {
    if (idx && idx.schema === 'chuckchuck.tour') return { ids: [String(idx.id || '')], inline: idx, first: String(idx.id || '') };
    const list = Array.isArray(idx) ? idx : (idx && Array.isArray(idx.tours) ? idx.tours : []);
    const ids = list.map((x) => (typeof x === 'string' ? x : x && (x.id || x.file))).filter(Boolean)
      .map((s) => String(s).replace(/\.json$/i, '')).filter((s) => /^[A-Za-z0-9_][A-Za-z0-9_.-]*$/.test(s));
    const want = idx && typeof idx.default === 'string' ? idx.default : '';
    const first = ids.includes(want) ? want : (ids[0] || '');
    return { ids: Array.from(new Set(ids)), inline: null, first };
  }

  /** 그 시각(녹화 초)에 화면에 있을 장 번호. 넘김 시각 사이 빈틈이면 앞 장 */
  function slideAt(present, t) {
    const ss = (present && present.slides) || [];
    if (!ss.length) return 1;
    let cur = ss[0].slide_no;
    for (const s of ss) {
      if (t >= s.start_sec) cur = s.slide_no;
      else break;
    }
    return cur;
  }

  /** 그 장이 시작하는 시각 — 버튼 · 밀기로 장을 옮기면 재생 위치를 여기로 */
  function slideStart(present, no) {
    const s = ((present && present.slides) || []).find((x) => x.slide_no === no);
    return s ? s.start_sec : 0;
  }

  /** 그 시각의 자막 조각(없으면 null) — 끝 시각은 다음 조각과 겹치지 않게 반열림 [start, end) */
  function captionAt(present, t) {
    const tr = (present && present.transcript) || [];
    return tr.find((c) => t >= c.start_sec && t < c.end_sec) || null;
  }

  /** 지금 떠 있을 코칭 칩(가장 최근 · CHIP_HOLD_SEC 안) 과 지금까지 뜬 칩 수 */
  function chipAt(present, t) {
    const chips = ((present && present.coaching_chips) || []).slice().sort((a, b) => a.at_sec - b.at_sec);
    const seen = chips.filter((c) => c.at_sec <= t);
    const last = seen[seen.length - 1] || null;
    const live = last && t - last.at_sec < CHIP_HOLD_SEC ? last : null;
    return { live, seen: seen.length, total: chips.length };
  }

  /** 장 하나를 더 가거나(+1) 덜 가거나(-1). 끝이면 그대로 + edge 표시 */
  function stepSlide(deck, no, d) {
    const nos = ((deck && deck.slides) || []).map((s) => s.no);
    const i = nos.indexOf(no);
    const j = i + d;
    if (i < 0) return { no: nos[0] || 1, edge: false };
    if (j < 0 || j >= nos.length) return { no, edge: true };
    return { no: nos[j], edge: false };
  }

  /** 초 → 「1분 36초」 · 「22초」 */
  function durationText(sec) {
    const s = Math.max(0, Math.round(Number(sec) || 0));
    const m = Math.floor(s / 60);
    return m ? (s % 60 ? `${m}분 ${s % 60}초` : `${m}분`) : `${s}초`;
  }

  /** 초 → m:ss (재생 시계) */
  function clock(sec) {
    const s = Math.max(0, Math.floor(Number(sec) || 0));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }

  /**
   * 주장 그래프 → 들여 쓴 줄 목록 [{node, depth}]. 루트부터 깊이 우선, 한 번 그린 노드는 다시 안 그린다.
   * 끝점이 없는 선은 건너뛴다(계약 테스트가 막지만 화면이 죽지 않게).
   */
  function graphRows(g) {
    const nodes = (g && g.nodes) || [];
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const kids = new Map();
    ((g && g.edges) || []).forEach((e) => {
      if (!byId.has(e.from) || !byId.has(e.to)) return;
      if (!kids.has(e.from)) kids.set(e.from, []);
      kids.get(e.from).push(e.to);
    });
    const out = [];
    const seen = new Set();
    const walk = (id, depth) => {
      if (seen.has(id) || !byId.has(id) || depth > 3) return;
      seen.add(id);
      out.push({ node: byId.get(id), depth });
      (kids.get(id) || []).forEach((k) => walk(k, depth + 1));
    };
    walk(g && g.root, 0);
    nodes.forEach((n) => { if (!seen.has(n.id)) walk(n.id, 1); });   // 루트에 안 닿은 노드도 빠뜨리지 않는다
    return out;
  }

  /** 상태별 개수 — 그래프 요약 줄 */
  function graphCounts(g) {
    const c = { aligned: 0, justified_skip: 0, missing: 0, contradiction: 0 };
    ((g && g.nodes) || []).forEach((n) => { if (n.status in c) c[n.status] += 1; });
    return c;
  }

  /**
   * 말 속도 막대 위 자리(0~1). 축은 200~500자/분, 권장 300~350 띠.
   * @returns {{ at:number, lo:number, hi:number }}
   */
  function paceGauge(cpm) {
    const MIN = 200, MAX = 500;
    const f = (v) => Math.min(1, Math.max(0, (v - MIN) / (MAX - MIN)));
    return { at: f(Number(cpm) || 0), lo: f(300), hi: f(350) };
  }

  /**
   * 카메라·마이크를 못 쓰는 앱 안 브라우저인가 — 카카오톡 · 네이버 · 인스타 · 페이스북 · 라인 · 다음 · 에브리타임 · 안드로이드 웹뷰.
   * @returns {''|'kakao'|'naver'|'instagram'|'facebook'|'line'|'other'}
   */
  function inAppKind(ua) {
    const s = String(ua || '');
    if (/KAKAOTALK/i.test(s)) return 'kakao';
    if (/NAVER\(inapp|NAVER\//i.test(s)) return 'naver';
    if (/Instagram/i.test(s)) return 'instagram';
    if (/FBAN|FBAV|FB_IAB/i.test(s)) return 'facebook';
    if (/\bLine\//i.test(s)) return 'line';
    if (/DaumApps|everytimeApp|; wv\)/i.test(s)) return 'other';
    return '';
  }

  /** 안드로이드인가 · iOS 인가 — 외부 브라우저로 여는 길이 다르다 */
  function platformOf(ua) {
    const s = String(ua || '');
    if (/Android/i.test(s)) return 'android';
    if (/iPhone|iPad|iPod/i.test(s)) return 'ios';
    return 'other';
  }

  /**
   * 바깥 브라우저로 여는 주소 — 카카오톡은 자기 스킴, 안드로이드는 크롬 intent, 그 밖(iOS 인앱)은 없음(주소 복사로 안내).
   * @returns {string} 빈 문자열이면 자동으로 열 길이 없다
   */
  function externalOpenUrl(url, ua) {
    const kind = inAppKind(ua);
    const plat = platformOf(ua);
    if (kind === 'kakao') return `kakaotalk://web/openExternal?url=${encodeURIComponent(url)}`;
    if (plat === 'android' && kind) {
      const m = String(url).match(/^(https?):\/\/(.*)$/i);
      if (m) return `intent://${m[2]}#Intent;scheme=${m[1].toLowerCase()};package=com.android.chrome;end`;
    }
    return '';
  }

  /** 근거 줄 위치 — "S2-3" → 「2장 3번째 줄」. 모양이 다르면 장 번호만 */
  function refText(ref, slideNo) {
    const m = String(ref || '').match(/^S(\d+)-(\d+)$/);
    if (m) return `${Number(m[1])}장 ${Number(m[2])}번째 줄`;
    return slideNo ? `${slideNo}장` : '';
  }

  /** 퍼널 신호 한 건 — {step, deck, t}. t 는 이 방문자가 투어를 시작한 뒤 지난 초(정수) */
  /**
   * 투어 화면 → 퍼널 신호 이름 (docs/booth-mobile/funnel-events.md, demo/tour_events.py STEPS).
   * 시작 안내(intro)는 /hi 의 「소개 카드」(intro) 와 이름이 겹쳐 세지 않고, 끝(done)은 리포트까지 본 것과 같아 따로 안 센다.
   */
  const FUNNEL_STEP = { deck: 'tour_deck', present: 'tour_present', analysis: 'tour_analysis', qa: 'tour_qa', report: 'tour_report' };
  function funnelStep(screen) {
    return Object.prototype.hasOwnProperty.call(FUNNEL_STEP, screen) ? FUNNEL_STEP[screen] : '';
  }

  function eventPayload(step, deck, startedAt, now) {
    const t = startedAt ? Math.max(0, Math.round((now - startedAt) / 1000)) : 0;
    return { step: String(step), deck: String(deck || ''), t };
  }

  const api = {
    STEPS, SCREENS, LEVEL_WORD, LEVEL_TONE, VERDICT, GROUND_ROLE, GRAPH_STATUS, CHIP_KIND, CHIP_HOLD_SEC,
    parseTourHash, tourHash, stepIndex, prevScreen, backAction, restartAction, cameFromHi,
    tourProblem, indexIds, slideAt, slideStart, captionAt, chipAt, stepSlide,
    durationText, clock, graphRows, graphCounts, paceGauge,
    inAppKind, platformOf, externalOpenUrl, eventPayload, funnelStep, refText,
  };
  root.TourLogic = api;
})(typeof window !== 'undefined' ? window : globalThis);
