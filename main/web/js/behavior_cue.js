/**
 * 발표 중 자세 알림 — 리허설(#/rehearsal) 비전 리허설에서 녹음하는 동안 카메라 기록(js/behavior_cv.js)이 쌓는 줄을 엿보고,
 * 오래 이어진 자세 하나만 짧게 알린다. 판단은 순수 함수(decide · conditions), 그리기는 아래 작은 DOM 층.
 *
 * 원칙 (계획 2026-10-17 §1 · 바퀴 4):
 *  - 관찰만 · 감정 낱말 없음 · 「많을수록 좋다」 없음. 손짓은 알리지 않는다(묘사 손짓과 만지작거림을 못 가른다 — 근거조사 §1-6).
 *  - 드물게: 알림은 20초에 하나, 2.5초 뒤 사라짐, 같은 자세가 끝나기 전엔 다시 안 알림, 삐약이 목소리 반응이 막 뜨거나 바뀌었으면 미룬다
 *    (그 반대로 목소리 반응이 새로 뜨면 떠 있던 자세 알림을 걷는다 — 한꺼번에 둘이 눈을 끌지 않게).
 *    즉시 피드백 도구(Presentation Trainer · Schneider 외 2015)가 여러 피드백을 한꺼번에 띄우지 않고 하나씩 보여 준 것과 같은 쪽 — 세부 문턱은 공개된 것이 없다(근거조사 §1-8).
 *  - 「화면 쪽」: Haar 는 카메라와 노트북 화면(자료)을 가르지 못한다 — 눈 맞춤이라고 부르지 않는다.
 *  - 「아래」 는 다른 곳과 따로 센다: 대본 · 자료를 잠깐 보는 건 자연스럽다 — 8초 넘게 이어질 때만.
 *  - 측정 문제(화면 밖 · 너무 멂 · 역광)는 한 테이크에 한 번씩만.
 *  - 문턱은 이름 붙은 상수 · 「설계값 · 검증 전」. 엔진 파일은 고치지 않는다 — BehaviorCV.snapshot() 과 BehaviorCvLogic 의 공개 함수만 쓴다.
 *
 * 노드 스모크: etc/tests/js/behavior_cue.smoke.mjs
 */
(function (root) {
  'use strict';

  /* ─── 문턱 (설계값 · 검증 전) ─────────────────────────────────────────── */
  const CUE = {
    awayMs: 4000,       // 화면 쪽이 아닌 「다른 곳」(옆 · 방향 모름)이 이만큼 이어지면 — 리포트(3초)보다 느긋하게. 실시간은 드물어야 한다.
                        // 엔진은 이탈을 실제보다 0.1~0.7초 짧게 잰다(실험실 s03: 5.0 · 4.3 · 4.1초 → 4.9 · 4.0 · 3.4초) — 4초 ≈ 실제 4.3~4.7초
    downMs: 8000,       // 아래를 본 채 이만큼 — 대본 한두 줄 읽는 건(1~5초, 실험실 s04) 알리지 않는다
    downShare: 0.7,     // 정면이 아닌 채 이어진 구간 중 「아래」 가 이 몫 넘을 때만 아래로 센다 (나머지는 숙인 동안 얼굴을 놓친 시간)
    swayMs: 8000,       // 흔들리는 중(아래 conditions)이 이만큼 이어지면 — 짧은 창이 부푸는 몫(최대 ≈ 2~3초)을 더해 실제로 ≈ 10초 흔들림.
                        // 8초 창만 이었을 때는 7초 흔들림을 멎고 2.6초 뒤에 알렸다 (실험실 d6 · d9 · s06, 엔진 줄 다시 돌리기)
    swayShortMs: 4000,  // 「아직 흔들리는 중」 을 보는 짧은 창 · 걸음 — 0.3~0.45Hz 의 아주 느린 흔들림은 4초 창이 못 본다(알림 없음 쪽으로 틀림)
    swayShortStepMs: 1000,
    frameMs: 3000,      // 사람이 화면에 없는 채 이만큼 (화면 밖 — 측정 문제, 한 번만)
    setupWinMs: 6000,   // 너무 멂 · 역광은 최근 이만큼의 얼굴 줄 중앙값으로
    setupMinRows: 12,   // 그 안에 얼굴 줄이 이만큼은 있어야 판단한다
    warmMs: 4000,       // 기록 시작 뒤 이만큼은 아무 알림도 없다 — 엔진 · 기준선이 자리 잡는 동안
    gapMs: 20000,       // 알림 사이 최소 간격 (모든 종류 합쳐서)
    showMs: 2500,       // 보이는 시간
    bufMs: 24000,       // 판단에 넘기는 최근 줄 — 흔들림 창(8초) 여럿 + 아래 8초가 들어가게
    voiceFreshMs: 3000, // 삐약이 목소리 반응(말풍선)이 새로 뜨거나 바뀐 뒤 이만큼은 자세 알림을 미룬다 — 둘이 한꺼번에 눈을 끌지 않게
    cutMs: 1200,        // 목소리 말풍선에 이만큼도 못 보이고 걷힌 알림은 안 본 것으로 — 「한 번만」 · 「같은 자세 한 번」 표시는 되돌린다(다시 뜰 수 있게).
                        // 20초 간격은 그대로 센다 — 간격까지 되돌렸더니 같은 알림이 4~6초마다 세 번 깜박였다 (실험실 d7, 녹음 첫 몇 초에 「하암~」 · 「잘 안 들려」)
    backHoldMs: 600,    // 리포트 「발표 중 알림」 — 알림 뒤 기대한 자세(화면 쪽 · 화면 안)가 이만큼 이어져야 「돌아왔다」 로 센다 (깜박임 무시)
    backMaxMs: 15000,   // 이만큼 안에 안 돌아오면 「15초 안에 안 돌아옴」(late)
    voiceQuietMs: 1500, // 말풍선이 사라진 뒤에도 이만큼은 더 기다린다
                        // 같은 말풍선이 오래 떠 있는 것(느린 말에 「하암~」 이 수십 초)은 막지 않는다 — 막으면 자세 알림이 아예 안 떴다(실험실 c01: 말풍선이 표본 92%)
  };

  /** 해요체 · 짧게 · 할 행동으로 (CLAUDE.md §3-1). 감정 · 평가 낱말 없음 */
  const COPY = {
    frame: '화면 안으로 들어와요',
    far: '카메라에 조금 다가와요',
    backlit: '얼굴 앞쪽을 밝혀 봐요',
    away: '화면 쪽으로 돌아와요',
    down: '고개를 들고 말해 봐요',
    sway: '두 발에 무게를 나눠 서 봐요',
  };
  const SETUP = ['frame', 'far', 'backlit'];      // 한 테이크에 한 번씩
  const POSTURE = ['away', 'down', 'sway'];       // 그 자세가 끝나야 다시 알릴 수 있다
  const ORDER = [...SETUP, ...POSTURE];           // 같은 때 여럿이면 앞의 것 하나만
  const AWAY_STATES = new Set(['left', 'right', 'away']);

  const median = (a) => { if (!a.length) return null; const s = a.slice().sort((p, q) => p - q); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

  function createMeter() {
    return { lastAt: -Infinity, shown: {}, armed: { away: true, down: true, sway: true }, log: [] };
  }

  /** 상태열 끝에서부터 조건이 이어진 길이(ms). 끝 줄이 조건이 아니면 0 */
  function tailRun(seq, pred) {
    if (!seq.length || !pred(seq[seq.length - 1])) return 0;
    const last = seq[seq.length - 1];
    let start = last.t;
    for (let i = seq.length - 1; i >= 0 && pred(seq[i]); i -= 1) start = seq[i].t;
    return last.t + last.dt - start;
  }

  /** tailRun 과 같되 그 구간 안 상태별 시간도 — { ms, by: { down: ms, … } } */
  function tailSpan(seq, pred) {
    const by = {};
    if (!seq.length || !pred(seq[seq.length - 1])) return { ms: 0, by };
    const last = seq[seq.length - 1];
    let start = last.t;
    for (let i = seq.length - 1; i >= 0 && pred(seq[i]); i -= 1) { start = seq[i].t; by[seq[i].state] = (by[seq[i].state] || 0) + seq[i].dt; }
    return { ms: last.t + last.dt - start, by };
  }

  /** 맨 끝 흔들림 창부터 이어 켜진 창들의 폭(ms). 끝 창이 꺼졌거나 지금과 멀면 0 */
  function swayRun(wins, tEnd, cfg) {
    if (!wins.length) return 0;
    const last = wins[wins.length - 1];
    if (!last.on || tEnd - last.end > cfg.swayStepGap) return 0;
    let first = last;
    for (let i = wins.length - 2; i >= 0; i -= 1) {
      const w = wins[i];
      if (!w.on || first.start - w.start > cfg.swayStepGap) break;
      first = w;
    }
    return last.end - first.start;
  }

  /**
   * 최근 줄 → 지금 이어지고 있는 것들. logic = BehaviorCvLogic (states · swayWindows · CFG).
   * 돌려주는 것: { t(마지막 줄 시각) · away · down · none · sway (이어진 ms) · far · backlit (true | false | null 모름) }
   */
  function conditions(rows, logic, cfg = CUE) {
    const list = (rows || []).filter((r) => r && Number.isFinite(r.t));
    if (!list.length || !logic) return { t: null, away: 0, down: 0, none: 0, sway: 0, far: null, backlit: null };
    const tEnd = list[list.length - 1].t;
    const recent = list.filter((r) => r.t >= tEnd - cfg.bufMs);
    const seq = logic.states(recent);
    const away = tailRun(seq, (x) => AWAY_STATES.has(x.state));
    // 아래 — 고개를 숙이면 정면 Haar 가 얼굴을 놓치고 머리 추적(CamShift)도 6초에 끊겨 「아래」 가 6.5초에서 끊기고 놓침 · 다른 곳이 섞인다
    // (실험실 c01: 11초 숙임 → 아래 6.5 · 다른 곳 0.8 · 없음 1.0 · 아래 2.7초). 그래서 정면이 아닌 채 이어진 구간 중 아래가 대부분이면 그 길이로 센다
    const bent = tailSpan(seq, (x) => x.state !== 'front' && x.state !== 'face');
    const down = bent.ms && (bent.by.down || 0) / bent.ms >= cfg.downShare ? bent.ms : 0;
    // 화면 밖 — 사람 없음이 이어지되, 그동안 옆얼굴 전체 보기가 옆얼굴을 한 번도 안 봤을 때만(row.ps · src P). 처음부터 옆을 본 사람은 사람 없음이 아니다 (바퀴 7 · c01 첫 7초)
    const none0 = tailRun(seq, (x) => x.state === 'none');
    const none = none0 && recent.some((r) => r.t >= tEnd - none0 && (r.ps || r.src === 'P')) ? 0 : none0;
    // 흔들림 — 엔진의 8초 창(대역 몫 · 순도 규칙까지)이 지금 켜져 있고, 짧은 4초 창(1초 걸음)이 끊김 없이 켜진 폭이 얼마나 되나.
    // 8초 창만 이으면 센 흔들림은 4초만 흔들어도 창 다섯이 켜져(창 하나에 2초만 들어도 켜짐) 16초로 셌고, 멎은 뒤 몇 초까지 켜져 있었다
    let sway = 0;
    try {
      const long = logic.swayWindows(seq);
      const lastLong = long[long.length - 1];
      if (lastLong && lastLong.on && tEnd - lastLong.end <= ((logic.CFG && logic.CFG.swayStepMs) || 2000) + 600) {
        const short = logic.swayWindows(seq, { ...logic.CFG, swayWinMs: cfg.swayShortMs, swayStepMs: cfg.swayShortStepMs });
        sway = swayRun(short, tEnd, { swayStepGap: cfg.swayShortStepMs + 600 });
        if (sway) sway -= cfg.swayShortMs;   // 창 폭만큼은 앞으로 부푼다 — 「첫 창이 켜진 끝」 부터 잰다
      }
    } catch (_) { sway = 0; }
    const faces = recent.filter((r) => r.t >= tEnd - cfg.setupWinMs && r.box && (r.src === 'F' || r.src === 'P'));
    let far = null; let backlit = null;
    if (faces.length >= cfg.setupMinRows) {
      const L = logic.CFG || {};
      const w = median(faces.map((r) => r.box[2]));
      far = w !== null && Number.isFinite(L.minFaceW) ? w < L.minFaceW : null;
      const ratio = median(faces.filter((r) => Number.isFinite(r.fb) && Number(r.br) > 0).map((r) => r.fb / r.br));
      backlit = ratio !== null && Number.isFinite(L.backlit) ? ratio < L.backlit : null;
    }
    return { t: tEnd, away, down, none, sway: Math.max(0, sway), far, backlit };
  }

  /** 지금 알릴 만한 것 — 우선순위 순으로 하나. 간격 · 꺼짐 · 목소리는 decide 가 본다 */
  function wanted(meter, c, cfg) {
    for (const k of ORDER) {
      if (SETUP.includes(k)) {
        if (meter.shown[k]) continue;
        if (k === 'frame' && c.none >= cfg.frameMs) return k;
        if ((k === 'far' || k === 'backlit') && c[k] === true) return k;
        continue;
      }
      if (!meter.armed[k]) continue;
      if (c[k] >= cfg[`${k}Ms`]) return k;
    }
    return null;
  }

  /**
   * 한 번 판단. ctx: { enabled, voiceBusy, t0(기록 시작 줄 시각, 기본 0) }.
   * 돌려주는 것: { meter(새것), cue: null | { type, text, t } }. meter 는 고치지 않는다(새로 만든다).
   */
  function decide(meter, c, ctx = {}, cfg = CUE) {
    const m = { lastAt: meter.lastAt, shown: { ...meter.shown }, armed: { ...meter.armed }, log: meter.log.slice() };
    if (!c || c.t === null) return { meter: m, cue: null };
    POSTURE.forEach((k) => { if (!(c[k] > 0)) m.armed[k] = true; });   // 그 자세가 끝났다 → 다음에 다시 알릴 수 있다
    if (ctx.enabled === false) return { meter: m, cue: null };
    if (c.t - (ctx.t0 || 0) < cfg.warmMs) return { meter: m, cue: null };
    if (c.t - m.lastAt < cfg.gapMs) return { meter: m, cue: null };
    if (ctx.voiceBusy) return { meter: m, cue: null };
    const type = wanted(m, c, cfg);
    if (!type) return { meter: m, cue: null };
    m.lastAt = c.t;
    if (SETUP.includes(type)) m.shown[type] = true;
    else m.armed[type] = false;
    const cue = { type, text: COPY[type], t: c.t };
    m.log.push(cue);
    return { meter: m, cue };
  }

  /**
   * 목소리 반응과 겹치지 않게 — 말풍선 글자(text, 안 보이면 '')를 0.1초마다 넣는다.
   * 돌려주는 것: { g(새 상태), busy(지금 자세 알림을 미룰까), fresh(말풍선이 방금 새로 떴나 — 떠 있던 자세 알림을 걷는다) }
   */
  function voiceGate(g, text, now, cfg = CUE) {
    const t = text || '';
    const changed = t !== g.text;
    const at = changed ? now : g.at;
    const busy = t ? now - at < cfg.voiceFreshMs : now - at < cfg.voiceQuietMs;
    return { g: { text: t, at }, busy, fresh: changed && !!t };
  }

  /* ─── 알림 뒤 돌아오기 (리포트 「발표 중 알림」, 바퀴 6) ─────────────────────── */
  /** 알림마다 기대한 자세 — 화면 쪽(정면 · 얼굴만 잡힘) · 화면 안(사람 있음). 흔들림은 아래 backAfter 가 창으로 본다. 너무 멂 · 역광은 재지 않는다 */
  const BACK_OK = {
    away: (st) => st === 'front' || st === 'face',
    down: (st) => st === 'front' || st === 'face',
    frame: (st) => st !== 'none',
  };

  /**
   * 알림(tMs, 엔진 줄 시각) 뒤 기대한 자세로 돌아오기까지 ms. seq = BehaviorCvLogic.states(rows), logic = BehaviorCvLogic(흔들림 창).
   * 돌려주는 것: 숫자(ms ≥ 0) · 'late'(backMaxMs 안에 안 돌아옴) · 'end'(그 전에 기록이 끝남, final 일 때만) · 'na'(재지 않는 종류) ·
   * null(아직 모름 — 줄이 더 와야 한다).
   * - 화면 쪽 · 아래 · 화면 밖: 기대한 상태가 backHoldMs 넘게 이어진 첫 줄의 시각 − tMs.
   * - 흔들림: 짧은 4초 창(1초 걸음)이 처음 꺼진 창의 시작 + 1초 − tMs (4초 창 안에 1~2초 흔들림이면 아직 켜진다 — 멎은 때는 그 언저리, ±1초)
   */
  function backAfter(seq, tMs, type, logic, { final = false } = {}, cfg = CUE) {
    const list = (seq || []).filter((x) => x && Number.isFinite(x.t));
    const lastT = list.length ? list[list.length - 1].t + (list[list.length - 1].dt || 0) : -Infinity;
    const undecided = () => (lastT - tMs >= cfg.backMaxMs ? 'late' : final ? 'end' : null);
    if (type === 'sway') {
      if (!logic || typeof logic.swayWindows !== 'function') return 'na';
      let wins = [];
      try { wins = logic.swayWindows(list, { ...logic.CFG, swayWinMs: cfg.swayShortMs, swayStepMs: cfg.swayShortStepMs }); } catch (_) { return 'na'; }
      const off = wins.find((w) => w.end > tMs && !w.on);
      if (off) { const ms = Math.max(0, off.start + 1000 - tMs); return ms > cfg.backMaxMs ? 'late' : ms; }
      return undecided();
    }
    const ok = BACK_OK[type];
    if (!ok) return 'na';
    for (let i = 0; i < list.length; i += 1) {
      const x = list[i];
      if (x.t + (x.dt || 0) <= tMs || !ok(x.state)) continue;
      const from = Math.max(x.t, tMs);
      let j = i; let until = x.t + (x.dt || 0);
      while (j + 1 < list.length && ok(list[j + 1].state)) { j += 1; until = list[j].t + (list[j].dt || 0); }
      if (until - from >= cfg.backHoldMs) { const ms = from - tMs; return ms > cfg.backMaxMs ? 'late' : ms; }
      if (j === list.length - 1) return final ? (until - from > 0 && from - tMs <= cfg.backMaxMs ? from - tMs : 'end') : null;   // 끝에서 돌아오는 중 — 줄을 더 본다
      i = j;
    }
    return undecided();
  }

  const api = { CUE, COPY, SETUP, POSTURE, ORDER, createMeter, tailRun, tailSpan, swayRun, conditions, decide, voiceGate, backAfter };

  /* ─── 화면 (브라우저에서만) ──────────────────────────────────────────────── */
  if (root.document) {
    const PREF_KEY = 'cheokcheok:behavior-cue';
    const POLL_MS = 120;      // 엔진이 줄을 0.2~0.33초마다 낸다 — 그보다 자주 엿봐야 줄을 안 놓친다
    const EVAL_MS = 500;
    const ui = { timer: 0, rows: [], lastT: null, lastN: 0, meter: createMeter(), t0: null, lastEval: 0,
      hideTimer: 0, showing: null, shownAt: 0, before: null, voice: { text: '', at: -Infinity }, voiceBusy: false, list: [], pend: [] };

    const prefOn = () => { try { return root.localStorage.getItem(PREF_KEY) !== '0'; } catch (_) { return true; } };
    const prefSet = (on) => { try { root.localStorage.setItem(PREF_KEY, on ? '1' : '0'); } catch (_) { /* 사생활 모드 — 이번 화면만 */ } };
    let enabled = prefOn();

    const nfRef = () => { try { return typeof nf !== 'undefined' ? nf : null; } catch (_) { return null; } };   // eslint-disable-line no-undef
    const recording = () => { const n = nfRef(); return !!n && n.mic === 'on'; };

    function resetTake() {
      ui.rows = []; ui.lastT = null; ui.lastN = 0; ui.t0 = null; ui.meter = createMeter(); ui.list = []; ui.pend = [];
      hide();
    }

    function switchEl() { return document.getElementById('vrBcueSwitch'); }

    function paintSwitch() {
      const b = switchEl();
      if (!b) return;
      // 0.12초마다 불리므로 값이 다를 때만 쓴다 (vision_rehearsal.js visionSetIf 와 같은 까닭)
      if (b.getAttribute('aria-checked') !== String(enabled)) b.setAttribute('aria-checked', String(enabled));
      const live = recording();   // 시작 전에만 — 발표 중엔 위 띠를 비운다
      if (b.hidden !== live) b.hidden = live;
    }

    function ensureDom(layer) {
      if (!layer.querySelector('#vrBcue')) {
        const p = document.createElement('p');
        p.className = 'vr-bcue vr-glass';
        p.id = 'vrBcue';
        p.setAttribute('role', 'status');
        p.setAttribute('aria-live', 'polite');
        p.hidden = true;
        layer.appendChild(p);
      }
      const top = layer.querySelector('.vr-top');
      if (top && !top.querySelector('#vrBcueSwitch')) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'btn vr-glass vr-bc-switch';
        b.id = 'vrBcueSwitch';
        b.setAttribute('role', 'switch');
        b.title = '발표하는 동안 오래 이어진 자세를 20초에 한 번까지 짧게 알려 줘요';
        b.innerHTML = '<span class="vr-bc-label"><span class="vr-bc-long">발표 중 </span>자세 알림</span><i class="vr-bc-knob" aria-hidden="true"></i>';
        b.addEventListener('click', () => { enabled = !enabled; prefSet(enabled); paintSwitch(); if (!enabled) hide(); });
        const cam = top.querySelector('#vrCamToggle');
        top.insertBefore(b, cam || null);
      }
      paintSwitch();
    }

    function hide() {
      if (ui.hideTimer) { clearTimeout(ui.hideTimer); ui.hideTimer = 0; }
      ui.showing = null;
      const el = document.getElementById('vrBcue');
      if (el && !el.hidden) { el.hidden = true; el.textContent = ''; delete el.dataset.cue; }
    }

    function show(cue) {
      const el = document.getElementById('vrBcue');
      if (!el) return;
      el.textContent = cue.text;
      el.dataset.cue = cue.type;
      el.hidden = false;
      ui.showing = cue;
      if (ui.hideTimer) clearTimeout(ui.hideTimer);
      ui.hideTimer = setTimeout(hide, CUE.showMs);
    }

    /** 삐약이 목소리 반응(#vrLine — vision_rehearsal.js visionPaintCue)을 엿본다. 말풍선이 새로 뜨면 떠 있던 자세 알림은 걷는다(목소리가 먼저) */
    function watchVoice(now) {
      const line = document.getElementById('vrLine');
      const text = line && !line.hidden ? (line.textContent || '') : '';
      const r = voiceGate(ui.voice, text, now);
      ui.voice = r.g;
      ui.voiceBusy = r.busy;
      if (r.fresh && ui.showing) {
        // 목소리가 먼저 — 걷는다. 거의 못 보였으면 「한 번만」 표시를 띄우기 전으로 되돌린다(간격은 그대로)
        if (now - ui.shownAt < CUE.cutMs && ui.before) {
          ui.meter = { ...ui.meter, shown: { ...ui.before.shown }, armed: { ...ui.before.armed } };
          const last = ui.list[ui.list.length - 1];
          if (last) last.cut = true;
        }
        hide();
      }
    }

    function slideNo() { const n = nfRef(); return (n && Number(n.slide)) || 1; }
    function recSec() {
      const n = nfRef();
      return n && n.mic === 'on' ? Math.round((Number(n.sec) || 0) * 10) / 10 : null;
    }

    function poll() {
      const layer = document.getElementById('vrCall');
      if (!layer) { stop(); return; }
      ensureDom(layer);
      const now = performance.now();
      watchVoice(now);
      const CV = root.BehaviorCV;
      const L = root.BehaviorCvLogic;
      if (!CV || !L || typeof CV.snapshot !== 'function') return;
      const snap = CV.snapshot();
      if (snap.phase !== 'present' || !recording()) {
        if (ui.rows.length && snap.phase !== 'present') resetTake();
        return;
      }
      const last = snap.last;
      // 새 기록(다시 발표) — 줄 수가 줄었거나 시각이 뒤로 갔다
      if (snap.rows < ui.lastN || (last && ui.lastT !== null && last.t < ui.lastT)) resetTake();
      ui.lastN = snap.rows;
      if (last && last.t !== ui.lastT) {
        ui.lastT = last.t;
        if (ui.t0 === null) ui.t0 = last.t;
        ui.rows.push(last);
        const cut = last.t - CUE.bufMs;
        while (ui.rows.length && ui.rows[0].t < cut) ui.rows.shift();
      }
      if (now - ui.lastEval < EVAL_MS || !ui.rows.length) return;
      ui.lastEval = now;
      settleBacks(false);
      let r;
      try {
        r = decide(ui.meter, conditions(ui.rows, L), { enabled, voiceBusy: ui.voiceBusy, t0: ui.t0 });
      } catch (err) { console.warn('[chuckchuck] 자세 알림', err); return; }
      const before = ui.meter;
      ui.meter = r.meter;
      if (!r.cue) return;
      ui.before = before;
      ui.shownAt = now;
      const rec = { type: r.cue.type, text: r.cue.text, t: Math.round(r.cue.t / 100) / 10, sec: recSec(), slide: slideNo() };
      ui.list.push(rec);
      ui.pend.push({ rec, tMs: r.cue.t });
      show(r.cue);
      try { root.dispatchEvent(new CustomEvent('chuck:behavior-cue', { detail: rec })); } catch (_) { /* 옛 브라우저 */ }
    }

    /** 알림 뒤 돌아오기를 지금 줄로 매긴다(back: 초 · 'late' · 'end' · 'na'). 줄 버퍼(24초)가 15초 상한보다 길어 알림 줄이 안 밀린다 */
    function settleBacks(final) {
      if (!ui.pend.length) return;
      const L = root.BehaviorCvLogic;
      let seq = [];
      try { seq = L ? L.states(ui.rows) : []; } catch (_) { seq = []; }
      ui.pend = ui.pend.filter((p) => {
        let b = null;
        try { b = backAfter(seq, p.tMs, p.rec.type, L, { final }); } catch (_) { b = final ? 'na' : null; }
        if (b === null) return true;
        p.rec.back = typeof b === 'number' ? Math.round(b / 100) / 10 : b;
        return false;
      });
    }

    function stop() {
      if (ui.timer) { clearInterval(ui.timer); ui.timer = 0; }
      hide();
    }

    /** rehearsal_behavior.js rhBehaviorVisionMount 가 부른다 — 비전 리허설 층이 있는 동안 돈다. 층이 사라지면 스스로 멈춘다 */
    function mount() {
      const layer = document.getElementById('vrCall');
      if (!layer) return;
      enabled = prefOn();
      ensureDom(layer);
      if (!ui.timer) ui.timer = setInterval(poll, POLL_MS);
    }

    /**
     * 이번 테이크에 뜬 알림을 꺼내고 비운다 — rhBehaviorFinishPresent 가 nf.behavior.present.liveCues 로 둔다(이 탭만, 서버로 안 감:
     * BehaviorSummary 계약은 모르는 키를 버린다). { on: 켜 두었나, list: [{ type, text, t(기록 시작부터 초), sec(녹음 초), slide, cut? }] }
     * cut: true = 목소리 말풍선에 밀려 1.2초도 못 보이고 걷힌 알림(20초 뒤 다시 뜰 수 있다) — 「몇 번 알렸나」 를 셀 때는 뺀다
     * back: 알림 뒤 기대한 자세로 돌아오기까지 초 · 'late'(15초 안에 안 돌아옴) · 'end'(그 전에 발표가 끝남) · 'na'(너무 멂 · 역광 — 재지 않음) (backAfter)
     */
    function take() {
      settleBacks(true);
      const out = { on: enabled, list: ui.list.slice() };
      resetTake();
      return out;
    }

    Object.assign(api, { mount, take, reset: resetTake, enabled: () => enabled, setEnabled: (on) => { enabled = !!on; prefSet(enabled); paintSwitch(); },
      peek: () => ({ list: ui.list.slice(), rows: ui.rows.length, showing: ui.showing, meter: ui.meter }) });
  }

  root.BehaviorCue = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
