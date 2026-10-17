/**
 * 발표 태도(베타) — 카메라 특징 줄(js/behavior_cv_features.js) → 평활 · 상태 · 구간 · 장별/질문별 집계 · 품질 게이트 · 3단계 낱말 · 근거 카드 · 서버 요약.
 * 순수 함수만 — 노드 스모크(etc/tests/js/behavior_cv.smoke.mjs)가 브라우저 없이 시험한다.
 *
 * 원칙 (계획 2026-10-17 §1 — 바꾸지 않음):
 *  - 관찰만 쓴다. 감정 · 자신감 · 성격을 짐작하지 않는다 (EU AI Act 5(1)(f) · Barrett 외 2019). 「많을수록 좋다」 고 말하지 않는다.
 *  - 화면엔 3단계 낱말, 숫자는 「자세히 보기」. 근거 카드 = 관찰 · 측정값 · 비교 기준 · 장면 · 신뢰도 · 제안.
 *  - 측정 품질이 모자라면 그 지표는 「이번엔 잴 수 없었어요」 와 까닭. 0 으로 채우지 않는다.
 *  - 문턱은 이름 붙은 상수로 두고 출처나 「설계값 · 검증 전」 을 적는다. 사람 채점과 맞춰 본(ICC) 문턱은 아직 없다 — 그래서 총점 가중치 0(베타).
 *
 * 줄(row) 모양 — features.process() 가 낸 숫자 + 화면이 붙인 장면 표시:
 *   t(ms, 기록 시작부터) · src('F' 정면 | 'P' 옆얼굴 | 'T' 이어 붙임 | '' 없음) · side(+1 코가 화면 왼쪽 · -1 오른쪽) · box[x,y,w,h](0~1)
 *   eyes(0~2) · roll · ey · ex · sep · br(밝기) · bl(흐림) · mv · body · hl · hr · hf · skin · ms
 *   seg('s3' 3장 · 'q2' 두 번째 질문) · sp(1 말하는 중 · 0 조용 · 없으면 모름)
 */
(function (root) {
  'use strict';

  /* ─── 문턱 (전부 이름 붙은 상수) ─────────────────────────────────────────── */
  const CFG = {
    dtCapMs: 1000,          // 줄 사이가 이보다 길면(탭 숨김 · 멈춤) 이만큼만 센다 — 빈 시간을 어떤 상태로도 부풀리지 않게
    minDwellMs: 400,        // 새 방향이 이만큼 이어져야 바꾼다(히스테리시스) — 5fps 에서 두 장. Haar 의 한 장짜리 헛잡음을 거른다 (설계값 · 검증 전)
    fillMs: 800,            // 정면이 잠깐 끊긴 동안(이어 붙임 · 놓침)은 하던 방향을 그대로 든다 — Haar 는 멀쩡한 정면도 몇 장씩 놓친다 (booth_cv 실측)
    awayHoldMs: 10000,      // 얼굴을 놓친 뒤 이만큼은 「자리에 있는데 다른 곳을 본다」 로 친다 — 돌아서서 화면을 보는 발표자를 자리 비움으로 세지 않게 (설계값)
    awayMotion: 0.12,       // 얼굴이 없어도 화면 흐름 평균이 이 위면(80px 기준 화소/장) 사람이 있다고 본다 (설계값 · 검증 전)
    downEy: 0.47,           // 두 눈이 얼굴 상자 위에서 이 비율보다 아래면 「아래를 봄」 — 정면 모나리자 0.38 (노드 벤치 10-17). 설계값 · 검증 전
    yawEx: 0.09,            // 눈 가운데가 상자 가운데에서 얼굴 폭의 이만큼 넘게 비끼면 옆을 보는 중 — 정면 ±0.03 (노드 벤치). 설계값 · 검증 전
    downDrift: 0.25,        // 얼굴을 놓치기 직전 0.8초 동안 얼굴 높이의 이만큼 아래로 내려갔으면 그 뒤 놓친 시간은 「아래를 봄」 (설계값 · 검증 전)
    driftWinMs: 800,
    lostDownMaxMs: 6000,    // 위 「아래를 봄」 추정은 이만큼까지만 — 더 길면 방향을 모름(다른 곳)으로 둔다
    lookAwayMs: 3000,       // 청중 쪽에서 눈을 뗀 구간이 이보다 길면 「오래 눈을 뗐다」 — 발표 코칭에서 흔히 쓰는 3~5초 규칙의 아래쪽 (설계값 · 검증 전)
    downSegMs: 2000,        // 아래를 본 구간 짚기 — 2초 넘게 (설계값 · 검증 전)
    // 흔들림: 얼굴 가운데 x(얼굴 폭 단위)의 0.3~1.5Hz 반복 성분. 자세 흔들림 연구가 보는 대역(서 있는 사람 몸 흔들림 ≈ 0.1~1Hz)에 걸음 · 체중 옮김을 더한 설계값
    swayLoHz: 0.3, swayHiHz: 1.5,
    swayWinMs: 10000, swayStepMs: 5000, swayFs: 4,
    swayAmp: 0.25,          // 대역 진폭이 얼굴 폭의 이만큼(≈ 4cm) 넘으면 흔들림 창 (설계값 · 검증 전)
    swayShare: 0.5,         // 대역 힘이 전체(0.1Hz~)의 절반 넘을 때만 — 천천히 자리 옮김은 흔들림이 아니다
    swayCover: 0.7,         // 창 안에 얼굴 자리가 이만큼 있어야 그 창을 잰다
    // 움직임 양 — 몸 영역 흐름을 얼굴 폭/초로 (거리에 상관없게). 3단계 경계는 설계값 · 검증 전
    moveLo: 0.25, moveHi: 0.8,
    // 손짓 — 손 자리에서 몸통과 따로 움직인 점의 비율. 켜짐 0.05 · 꺼짐 0.025 (히스테리시스, 설계값 · 검증 전)
    gestOn: 0.05, gestOff: 0.025,
    // ── 품질 게이트 ──
    minDurMs: 20000, minFrames: 40, minFps: 2.5,
    minPresence: 0.6,       // 얼굴(또는 사람)이 있는 시간이 이 아래면 방향 지표를 재지 않는다 (계획 §2)
    darkBr: 40,             // 평균 밝기 이 아래 줄은 어둡다 (계획 §2 「밝기 ≥ 40」)
    maxDark: 0.3,           // 어두운 줄이 이보다 많으면 못 잼
    blurMin: 15,            // 얼굴 라플라시안 분산 중앙값이 이 아래면 흐림 — 노드 벤치: 또렷 ≈ 340, 가우스 3.5px 흐림 ≈ 3.7 (설계값)
    minFaceW: 0.10,         // 얼굴 폭 중앙값이 화면 폭의 이 비율 아래면 방향을 재지 않는다 (계획 §2)
    minEyes: 0.1, lowEyes: 0.3,  // 정면 줄 중 두 눈이 잡힌 비율 — 0.1 아래면 「아래를 봄」 못 잼, 0.3 아래면 신뢰도 낮음
    minTrack: 0.7,          // 흔들림: 있는 시간 중 얼굴 자리가 있는 비율
    minBody: 0.5,           // 움직임 · 손짓: 있는 시간 중 몸 영역이 화면에 있는 비율
    minSpeakShare: 0.2, minSilentShare: 0.1, minSpeakKnown: 0.6,
    minSegMs: 8000,         // 장 · 질문별 값은 이만큼 넘게 머문 곳만
    // 3단계 낱말 경계 (설계값 · 검증 전)
    gazeHi: 0.7, gazeLo: 0.4,
    awayPerMinLo: 0.5, awayPerMinHi: 1.5,
    downLo: 0.1, downHi: 0.3,
    swayLo: 0.1, swayHi: 0.3,
    gestLo: 0.1, gestHi: 0.4,
    sizeLo: 0.10, sizeHi: 0.35, offCenter: 0.2,
    // 서버 요약 크기 상한 (bridge 쪽 검증과 같은 값 — main/pipeline/contracts.py BehaviorSummary)
    maxSegs: 60, maxEvents: 40, maxBytes: 24000,
  };

  const VERSION = 1;
  const UNMEASURED = '이번엔 잴 수 없었어요';

  const sum = (a) => a.reduce((x, y) => x + y, 0);
  const median = (a) => { if (!a.length) return null; const s = a.slice().sort((p, q) => p - q); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
  const quant = (a, q) => { if (!a.length) return null; const s = a.slice().sort((p, r) => p - r); return s[Math.min(s.length - 1, Math.floor(q * s.length))]; };
  const rd = (v, k = 3) => (v === null || v === undefined || !Number.isFinite(v) ? null : Math.round(v * 10 ** k) / 10 ** k);
  const sec = (ms) => rd(ms / 1000, 1);

  /* ─── 1. 줄마다 날 방향 ─────────────────────────────────────────────────── */

  /**
   * 한 줄의 날(raw) 방향 — 'front' | 'left' | 'right' | 'down' | 'unknown'(얼굴 자리만 있음) | 'none'.
   * 왼쪽 · 오른쪽은 **발표자 기준**이다. 카메라 프레임은 거울상이 아니라서, 코가 화면 왼쪽을 가리키면 발표자는 자기 오른쪽을 본다.
   * Haar 옆얼굴 캐스케이드는 코가 화면 왼쪽인 얼굴을 찾는다 (Getty 줄리아 티티 두상 left/right profile 로 확인, 10-17) — side +1.
   */
  function rawDir(row, cfg = CFG) {
    if (!row || !row.src) return 'none';
    if (row.src === 'P') return row.side > 0 ? 'right' : 'left';
    if (row.src === 'T') return 'unknown';
    if (row.eyes === 2 && Number.isFinite(row.ey)) {
      if (row.ey > cfg.downEy) return 'down';
      if (row.ex < -cfg.yawEx) return 'right';
      if (row.ex > cfg.yawEx) return 'left';
    }
    return 'front';
  }

  const cyOf = (row) => (row && row.box ? row.box[1] + row.box[3] / 2 : null);

  /**
   * 줄들 → 시간 순 상태열. 끊긴 정면 메우기 · 놓친 뒤 아래로 내려갔나 · 히스테리시스까지.
   * 돌려주는 것: [{ t, dt, state, raw, present, row }]
   */
  function states(rows, cfg = CFG) {
    const list = (rows || []).filter((r) => r && Number.isFinite(r.t)).slice().sort((a, b) => a.t - b.t);
    const out = [];
    let lastDef = null; let lastDefAt = -Infinity;     // 마지막 확실한 방향 · 시각
    let lastFaceAt = -Infinity; let lostMode = '';     // 놓친 구간의 해석 ('down' | 'away' | '')
    let lostStart = -Infinity;
    for (let i = 0; i < list.length; i += 1) {
      const row = list[i];
      const next = list[i + 1];
      const dt = next ? Math.min(cfg.dtCapMs, Math.max(0, next.t - row.t)) : Math.min(cfg.dtCapMs, out.length ? out[out.length - 1].dt : 200);
      let raw = rawDir(row, cfg);
      if (raw === 'front' || raw === 'left' || raw === 'right' || raw === 'down') {
        lastDef = raw; lastDefAt = row.t; lostMode = '';
      }
      if (row.src) lastFaceAt = row.t;
      let s = raw;
      if (raw === 'unknown') {
        // 이어 붙인 얼굴 — 잠깐이면 하던 방향, 아래로 내려갔으면 아래, 길면 다른 곳
        const ref = findLastDetected(list, i);
        const fall = ref && row.box && ref.box ? (cyOf(row) - cyOf(ref)) / Math.max(0.01, ref.box[3]) : 0;
        if (fall > cfg.downDrift) s = 'down';
        else if (lastDef && row.t - lastDefAt <= cfg.fillMs) s = lastDef;
        else s = 'away';
      } else if (raw === 'none') {
        if (!lostMode) {
          lostStart = row.t;
          lostMode = droppedDown(list, i, cfg) ? 'down' : 'away';
        }
        const sinceFace = row.t - lastFaceAt;
        const moving = Number(row.mv) > cfg.awayMotion;
        if (lastDef && row.t - lastDefAt <= cfg.fillMs) s = lastDef;
        else if (lostMode === 'down' && row.t - lostStart <= cfg.lostDownMaxMs) s = 'down';
        else if (sinceFace <= cfg.awayHoldMs || moving) s = 'away';
        else s = 'none';
      }
      out.push({ t: row.t, dt, raw, state: s, row });
    }
    return hysteresis(out, cfg).map((x) => ({ ...x, present: x.state !== 'none' }));
  }

  function findLastDetected(list, i) {
    for (let k = i - 1; k >= 0 && list[i].t - list[k].t <= 3000; k -= 1) {
      if (list[k].src === 'F' || list[k].src === 'P') return list[k];
    }
    return null;
  }

  /** 얼굴을 놓치기 직전 driftWinMs 동안 얼굴 가운데가 얼굴 높이의 downDrift 넘게 내려갔나 */
  function droppedDown(list, i, cfg) {
    let last = null; let first = null;
    for (let k = i - 1; k >= 0 && list[i].t - list[k].t <= cfg.driftWinMs + 400; k -= 1) {
      if (!list[k].box) continue;
      if (!last) last = list[k];
      if (last.t - list[k].t <= cfg.driftWinMs) first = list[k];
    }
    if (!last || !first || last === first) return false;
    return (cyOf(last) - cyOf(first)) / Math.max(0.01, first.box[3]) > cfg.downDrift;
  }

  /** 새 상태가 minDwellMs 이어져야 바꾼다. 바꿀 때는 그 상태가 시작된 줄부터 고친다(구간 시작 시각이 밀리지 않게) */
  function hysteresis(seq, cfg) {
    if (!seq.length) return seq;
    const out = seq.map((x) => ({ ...x }));
    let cur = out[0].state;
    let candStart = -1;
    for (let i = 0; i < out.length; i += 1) {
      const s = seq[i].state;
      if (s === cur) { candStart = -1; out[i].state = cur; continue; }
      if (candStart < 0 || seq[candStart].state !== s) candStart = i;
      if (seq[i].t - seq[candStart].t + seq[i].dt >= cfg.minDwellMs) {
        cur = s;
        for (let k = candStart; k <= i; k += 1) out[k].state = cur;
        candStart = -1;
      } else {
        out[i].state = cur;
      }
    }
    return out;
  }

  /* ─── 2. 구간 ───────────────────────────────────────────────────────────── */

  /** 조건이 참인 연속 구간 — [{ start, end, dur, seg, side }]. 같은 seg 안에서만 잇지 않는다(장이 바뀌어도 구간은 이어진다 — 시작 장으로 적는다) */
  function runs(seq, pred, minMs) {
    const out = [];
    let cur = null;
    seq.forEach((x) => {
      if (pred(x)) {
        if (!cur) cur = { start: x.t, end: x.t + x.dt, seg: x.row.seg || '', states: {} };
        cur.end = x.t + x.dt;
        cur.states[x.state] = (cur.states[x.state] || 0) + x.dt;
      } else if (cur) { out.push(cur); cur = null; }
    });
    if (cur) out.push(cur);
    return out.map((r) => ({ ...r, dur: r.end - r.start })).filter((r) => r.dur >= minMs);
  }

  /* ─── 3. 흔들림 (대역 에너지) ───────────────────────────────────────────── */

  /** 고르게 다시 뽑기 — 얼굴 자리가 1초 넘게 비면 null(그 창은 안 잰다) */
  function resample(points, t0, t1, fs) {
    const n = Math.floor(((t1 - t0) / 1000) * fs);
    const out = [];
    let j = 0;
    for (let k = 0; k < n; k += 1) {
      const t = t0 + (k * 1000) / fs;
      while (j < points.length - 2 && points[j + 1].t < t) j += 1;
      const a = points[j]; const b = points[j + 1];
      if (!a || !b || t < a.t - 500 || t > b.t + 500 || b.t - a.t > 1000) return null;
      const u = b.t === a.t ? 0 : Math.max(0, Math.min(1, (t - a.t) / (b.t - a.t)));
      out.push(a.v + u * (b.v - a.v));
    }
    return out;
  }

  /** 한 창의 대역 진폭(얼굴 폭) · 대역 몫. 직선 추세를 빼고 DFT(작은 N 이라 직접) */
  function bandOf(x, fs, lo, hi) {
    const n = x.length;
    if (n < 8) return null;
    const mt = (n - 1) / 2; const mx = sum(x) / n;
    let sxy = 0; let sxx = 0;
    x.forEach((v, k) => { sxy += (k - mt) * (v - mx); sxx += (k - mt) ** 2; });
    const slope = sxx ? sxy / sxx : 0;
    const y = x.map((v, k) => v - mx - slope * (k - mt));
    let band = 0; let total = 0;
    for (let k = 1; k < n / 2; k += 1) {
      const f = (k * fs) / n;
      if (f < 0.1) continue;
      let re = 0; let im = 0;
      for (let m = 0; m < n; m += 1) { const a = (-2 * Math.PI * k * m) / n; re += y[m] * Math.cos(a); im += y[m] * Math.sin(a); }
      const p = (2 * (re * re + im * im)) / (n * n);   // 한쪽 스펙트럼 힘 (Parseval)
      total += p;
      if (f >= lo && f <= hi) band += p;
    }
    return { amp: Math.sqrt(2 * band), share: total > 0 ? band / total : 0 };
  }

  /** 흔들림 창들 — [{ start, end, amp, share, on, seg }]. 얼굴 폭 중앙값으로 나눠 거리에 상관없게 */
  function swayWindows(seq, cfg = CFG) {
    const pts = seq.filter((x) => x.row.box).map((x) => ({ t: x.t, v: x.row.box[0] + x.row.box[2] / 2, w: x.row.box[2], seg: x.row.seg || '' }));
    if (pts.length < 8) return [];
    const fw = median(pts.map((p) => p.w)) || 0.1;
    const P = pts.map((p) => ({ ...p, v: p.v / fw }));
    const t0 = seq[0].t; const tEnd = seq[seq.length - 1].t;
    const out = [];
    for (let a = t0; a + cfg.swayWinMs <= tEnd + 1; a += cfg.swayStepMs) {
      const b = a + cfg.swayWinMs;
      const inWin = P.filter((p) => p.t >= a && p.t < b);
      const cover = inWin.length / Math.max(1, ((b - a) / 1000) * fpsOf(seq));
      if (cover < cfg.swayCover || inWin.length < 8) continue;
      const fs = Math.min(cfg.swayFs, fpsOf(seq));
      const x = resample(inWin, a, b, fs);
      if (!x) continue;
      const hi = Math.min(cfg.swayHiHz, 0.45 * fs);
      const r = bandOf(x, fs, cfg.swayLoHz, hi);
      if (!r) continue;
      out.push({ start: a, end: b, amp: r.amp, share: r.share, on: r.amp >= cfg.swayAmp && r.share >= cfg.swayShare, seg: inWin[inWin.length >> 1].seg });   // 창 가운데의 장
    }
    return out;
  }

  function fpsOf(seq) {
    if (seq.length < 2) return 0;
    const span = (seq[seq.length - 1].t - seq[0].t) / 1000;
    return span > 0 ? (seq.length - 1) / span : 0;
  }

  /* ─── 4. 움직임 · 손짓 ──────────────────────────────────────────────────── */

  /** 줄마다 몸 움직임(얼굴 폭/초) — 흐름은 앞 줄과의 차이라서 앞 줄과의 간격으로 나눈다 */
  function bodySpeed(seq) {
    const out = [];
    for (let i = 1; i < seq.length; i += 1) {
      const r = seq[i].row; const gap = (seq[i].t - seq[i - 1].t) / 1000;
      if (!Number.isFinite(r.body) || !r.box || gap <= 0 || gap > 1.2) continue;
      out.push({ i, v: r.body / gap / Math.max(1, r.box[2] * 80) });   // 80 = features 의 흐름 폭(FX.flowW)
    }
    return out;
  }

  /** 손짓 켜짐/꺼짐 (히스테리시스) — 손 자리를 잴 수 있는 줄만 */
  function gestureFlags(seq, cfg = CFG) {
    let on = false;
    return seq.map((x) => {
      const r = x.row;
      const vals = [r.hl, r.hr, r.hf].filter(Number.isFinite);
      if (!x.present || !vals.length || !Number.isFinite(r.body)) return null;
      const g = Math.max(...vals);
      on = on ? g >= cfg.gestOff : g >= cfg.gestOn;
      return on;
    });
  }

  /* ─── 5. 품질 ───────────────────────────────────────────────────────────── */

  function quality(seq, cfg = CFG) {
    const total = sum(seq.map((x) => x.dt));
    const present = sum(seq.filter((x) => x.present).map((x) => x.dt));
    const faceRows = seq.filter((x) => x.row.box);
    const frontRows = seq.filter((x) => x.row.src === 'F');
    const presentRows = seq.filter((x) => x.present);
    const ms = seq.map((x) => x.row.ms).filter(Number.isFinite);
    return {
      dur: total,
      frames: seq.length,
      fps: fpsOf(seq),
      presence: total ? present / total : 0,
      dark: seq.length ? seq.filter((x) => Number(x.row.br) < cfg.darkBr).length / seq.length : 1,
      bright: median(seq.map((x) => x.row.br).filter(Number.isFinite)),
      blur: median(faceRows.map((x) => x.row.bl).filter(Number.isFinite)),
      face: median(faceRows.map((x) => x.row.box[2])),
      eyes: frontRows.length ? frontRows.filter((x) => x.row.eyes === 2).length / frontRows.length : 0,
      track: presentRows.length ? presentRows.filter((x) => x.row.box).length / presentRows.length : 0,
      body: presentRows.length ? presentRows.filter((x) => Number.isFinite(x.row.body)).length / presentRows.length : 0,
      msP50: median(ms), msP90: quant(ms, 0.9),
    };
  }

  /** 지표마다 게이트 — 통과면 '', 아니면 사람이 고칠 수 있는 까닭 */
  function gateWhy(kind, q, cfg = CFG) {
    if (q.dur < cfg.minDurMs || q.frames < cfg.minFrames) return '카메라로 본 시간이 20초가 안 돼요';
    if (q.fps < (kind === 'movement' || kind === 'gesture' ? 2 : cfg.minFps)) return '이 기기에서 화면을 충분히 자주 보지 못했어요';
    if (q.dark > cfg.maxDark) return '화면이 어두웠어요 — 얼굴 앞쪽을 밝게 하면 잴 수 있어요';
    if (kind === 'framing') return q.presence < 0.3 ? '얼굴이 화면에 거의 없었어요' : '';
    if (kind === 'movement' || kind === 'gesture') {
      if (q.presence < 0.3) return '사람이 화면에 거의 없었어요';
      if (q.body < cfg.minBody) return '몸이 화면에 거의 안 보였어요 — 카메라를 조금 멀리 두면 잴 수 있어요';
      return '';
    }
    if (q.presence < cfg.minPresence) return '얼굴이 화면에 잡힌 시간이 짧았어요';
    if (q.face !== null && q.face < cfg.minFaceW) return '얼굴이 화면에서 너무 작았어요 — 카메라에 조금 가까이 오면 잴 수 있어요';
    if (q.blur !== null && q.blur < cfg.blurMin) return '화면이 흐렸어요 — 카메라 렌즈를 닦거나 초점을 맞추면 잴 수 있어요';
    if (kind === 'down' && q.eyes < cfg.minEyes) return '눈 위치를 거의 못 찾았어요 — 안경 반사 · 앞머리 · 조명 때문일 수 있어요';
    if (kind === 'sway' && q.track < cfg.minTrack) return '얼굴 자리를 이어서 따라가지 못했어요';
    return '';
  }

  /** 측정 품질 → 신뢰도 낱말. 문턱 자체가 검증 전이라 「높음」 은 측정이 깨끗했다는 뜻이지 판정이 맞았다는 뜻이 아니다 */
  function confidence(kind, q, cfg = CFG) {
    let pts = 0;
    if (q.presence >= 0.85) pts += 1;
    if (q.fps >= 4) pts += 1;
    if (q.face !== null && q.face >= 0.13) pts += 1;
    if (q.dark <= 0.05) pts += 1;
    if (kind === 'down' && q.eyes < cfg.lowEyes) pts -= 2;
    if (kind === 'sway' && q.track < 0.85) pts -= 1;
    if ((kind === 'gesture' || kind === 'movement') && q.body < 0.8) pts -= 1;
    return pts >= 4 ? '높음' : pts >= 2 ? '보통' : '낮음';
  }

  /* ─── 6. 지표 ───────────────────────────────────────────────────────────── */

  const level3 = (v, lo, hi) => (v < lo ? 0 : v < hi ? 1 : 2);

  /** 낱말 · 제안 — 관찰만. 「좋아요/나빠요」 · 감정 낱말을 쓰지 않는다. look: 연습해 볼 만한 쪽이면 true */
  const WORDS = {
    gaze: { label: '청중 쪽을 본 시간', words: ['짧아요', '보통이에요', '길어요'], look: [true, false, false],
      tip: '장을 넘길 때마다 한 문장은 카메라(청중)를 보며 말해 봐요.' },
    lookaway: { label: '오래 눈을 뗀 구간', words: ['드물어요', '가끔 있어요', '잦아요'], look: [false, false, true],
      tip: '자료를 볼 때는 짧게 보고 다시 청중 쪽으로 돌아오는 연습을 해 봐요.' },
    down: { label: '아래를 본 시간', words: ['짧아요', '보통이에요', '길어요'], look: [false, false, true],
      tip: '대본을 읽는 장이 있다면 첫 문장을 외워 고개를 든 채 시작해 봐요.' },
    sway: { label: '몸 좌우 흔들림', words: ['거의 없어요', '가끔 있어요', '자주 있어요'], look: [false, false, true],
      tip: '두 발을 어깨너비로 두고 무게를 양발에 나눠 서 봐요.' },
    movement: { label: '몸 움직임 양', words: ['적어요', '보통이에요', '많아요'], look: [false, false, false],
      tip: '' },
    gesture: { label: '손짓', words: ['적어요', '보통이에요', '많아요'], look: [false, false, false],
      tip: '' },
    framing: { label: '화면 구도', words: ['얼굴이 작아요', '알맞아요', '얼굴이 커요'], look: [true, false, true],
      tip: '얼굴이 화면 가운데 위쪽, 폭의 5분의 1쯤 되게 카메라를 맞춰 봐요.' },
  };

  const BASIS = {
    gaze: `${Math.round(CFG.gazeLo * 100)}% 아래 짧아요 · ${Math.round(CFG.gazeHi * 100)}% 넘으면 길어요 (설계값 · 검증 전)`,
    lookaway: `청중 쪽에서 ${CFG.lookAwayMs / 1000}초 넘게 눈을 뗀 구간을 1분에 몇 번 했나 — ${CFG.awayPerMinLo}번 아래 드물어요 · ${CFG.awayPerMinHi}번 넘으면 잦아요 (설계값 · 검증 전)`,
    down: `있는 시간 중 ${Math.round(CFG.downLo * 100)}% 아래 짧아요 · ${Math.round(CFG.downHi * 100)}% 넘으면 길어요 (설계값 · 검증 전)`,
    sway: `10초 창에서 얼굴이 ${CFG.swayLoHz}~${CFG.swayHiHz}Hz 로 얼굴 폭의 ${Math.round(CFG.swayAmp * 100)}% 넘게 오간 창의 비율 (설계값 · 검증 전)`,
    movement: `몸 영역이 1초에 얼굴 폭의 ${CFG.moveLo}배 아래면 적어요 · ${CFG.moveHi}배 넘으면 많아요 (설계값 · 검증 전)`,
    gesture: `있는 시간 중 손이 움직인 시간 ${Math.round(CFG.gestLo * 100)}% 아래 적어요 · ${Math.round(CFG.gestHi * 100)}% 넘으면 많아요 — 많을수록 좋다는 뜻이 아니에요 (설계값 · 검증 전)`,
    framing: `얼굴 폭이 화면의 ${Math.round(CFG.sizeLo * 100)}~${Math.round(CFG.sizeHi * 100)}% 면 알맞아요 (설계값)`,
  };

  function metric(kind, q, value, lvl, extra = {}, cfg = CFG) {
    const why = gateWhy(kind, q, cfg);
    const W = WORDS[kind];
    if (why) return { kind, label: W.label, ok: false, word: UNMEASURED, why, basis: BASIS[kind] };
    return { kind, label: W.label, ok: true, value: rd(value), level: lvl, word: W.words[lvl], look: !!W.look[lvl],
      conf: confidence(kind, q, cfg), basis: BASIS[kind], tip: W.look[lvl] ? W.tip : '', ...extra };
  }

  /** 상태열 하나(전체 · 장 하나 · 질문 하나)의 숫자 */
  function measure(seq, cfg = CFG) {
    const pres = seq.filter((x) => x.present);
    const presMs = sum(pres.map((x) => x.dt));
    const ms = (st) => sum(pres.filter((x) => x.state === st).map((x) => x.dt));
    const front = ms('front'); const down = ms('down');
    const left = ms('left'); const right = ms('right'); const away = ms('away');
    const look = runs(seq, (x) => x.present && x.state !== 'front', cfg.lookAwayMs);
    const downs = runs(seq, (x) => x.state === 'down', cfg.downSegMs);
    const speeds = bodySpeed(seq).filter((s) => seq[s.i].present).map((s) => s.v);
    const flags = gestureFlags(seq, cfg);
    let gOn = 0; let gAll = 0; let spOn = 0; let spAll = 0; let siOn = 0; let siAll = 0; let spKnown = 0;
    seq.forEach((x, i) => {
      const f = flags[i];
      if (f === null) return;
      gAll += x.dt; if (f) gOn += x.dt;
      if (x.row.sp === 1 || x.row.sp === 0) {
        spKnown += x.dt;
        if (x.row.sp === 1) { spAll += x.dt; if (f) spOn += x.dt; } else { siAll += x.dt; if (f) siOn += x.dt; }
      }
    });
    const faces = seq.filter((x) => x.row.box).map((x) => x.row.box);
    return {
      presMs, front, down, left, right, away,
      gaze: presMs ? front / presMs : null,
      downShare: presMs ? down / presMs : null,
      look, downs,
      move: median(speeds),
      gesture: gAll ? gOn / gAll : null,
      gestMs: gAll,
      speak: spAll ? spOn / spAll : null, silent: siAll ? siOn / siAll : null,
      speakShare: gAll ? spAll / gAll : 0, silentShare: gAll ? siAll / gAll : 0, speakKnown: gAll ? spKnown / gAll : 0,
      size: median(faces.map((b) => b[2])),
      off: median(faces.map((b) => Math.abs(b[0] + b[2] / 2 - 0.5))),
      skin: median(seq.filter((x, i) => flags[i]).map((x) => x.row.skin).filter(Number.isFinite)),
    };
  }

  /* ─── 7. 장 · 질문별 ────────────────────────────────────────────────────── */

  function bySeg(seq, cfg = CFG) {
    const order = [];
    const groups = {};
    seq.forEach((x) => {
      const k = x.row.seg || '';
      if (!groups[k]) { groups[k] = []; order.push(k); }
      groups[k].push(x);
    });
    return order.filter((k) => k).map((k) => {
      const s = groups[k];
      const m = measure(s, cfg);
      const dur = sum(s.map((x) => x.dt));
      return {
        seg: k, slide: segSlide(k), q: segQ(k), dur, enough: dur >= cfg.minSegMs,
        present: dur ? m.presMs / dur : 0,
        gaze: m.gaze, down: m.downShare, gesture: m.gesture, move: m.move,
        lookaway: m.look.length, start: s[0].t,
      };
    });
  }

  const segSlide = (k) => (/^s(\d+)$/.test(k) ? Number(k.slice(1)) : null);
  const segQ = (k) => (/^q(\d+)$/.test(k) ? Number(k.slice(1)) : null);
  const where = (seg) => (segSlide(seg) ? `${segSlide(seg)}장` : segQ(seg) ? `${segQ(seg)}번째 질문` : '');

  /* ─── 8. 근거 카드 ──────────────────────────────────────────────────────── */

  const SIDE_WORD = { left: '왼쪽', right: '오른쪽', down: '아래', away: '다른 곳' };

  function mainDir(states) {
    let best = ''; let bestMs = 0;
    Object.entries(states || {}).forEach(([k, v]) => { if (k !== 'front' && v > bestMs) { best = k; bestMs = v; } });
    return SIDE_WORD[best] || '다른 곳';
  }

  function cards(res, cfg = CFG) {
    const out = [];
    const M = res.metrics;
    const t0 = res.t0 || 0;
    const scene = (seg, t, dur) => ({ seg, where: where(seg), sec: sec(t - t0), dur: sec(dur) });
    if (M.lookaway.ok) {
      res.raw.look.slice().sort((a, b) => b.dur - a.dur).slice(0, 3).forEach((r) => {
        out.push({ kind: 'lookaway', observation: `${where(r.seg) || '발표 중'}에서 ${sec(r.dur)}초 동안 청중 쪽이 아니라 ${mainDir(r.states)}을 봤어요`,
          value: `${sec(r.dur)}초 · 주로 ${mainDir(r.states)}`, basis: `${cfg.lookAwayMs / 1000}초 넘게 이어지면 짚어요 (설계값 · 검증 전)`,
          scene: scene(r.seg, r.start, r.dur), conf: M.lookaway.conf, tip: WORDS.lookaway.tip });
      });
    }
    if (M.down.ok) {
      res.raw.downs.slice().sort((a, b) => b.dur - a.dur).slice(0, 2).forEach((r) => {
        out.push({ kind: 'down', observation: `${where(r.seg) || '발표 중'}에서 ${sec(r.dur)}초 동안 아래를 봤어요`,
          value: `${sec(r.dur)}초`, basis: `${cfg.downSegMs / 1000}초 넘게 이어지면 짚어요 (설계값 · 검증 전)`,
          scene: scene(r.seg, r.start, r.dur), conf: M.down.conf, tip: WORDS.down.tip });
      });
    }
    if (M.gaze.ok) {
      const segs = res.segs.filter((s) => s.enough && s.gaze !== null);
      if (segs.length >= 2) {
        const low = segs.slice().sort((a, b) => a.gaze - b.gaze)[0];
        const all = M.gaze.value;
        if (low.gaze < all - 0.15) {
          out.push({ kind: 'gaze_seg', observation: `${where(low.seg)}에서는 청중 쪽을 본 시간이 ${Math.round(low.gaze * 100)}%로 발표 전체(${Math.round(all * 100)}%)보다 짧았어요`,
            value: `${Math.round(low.gaze * 100)}% (${sec(low.dur)}초 중)`, basis: '이 발표의 다른 장과 견줘서 15%p 넘게 낮을 때 짚어요 (설계값 · 검증 전)',
            scene: scene(low.seg, low.start, low.dur), conf: M.gaze.conf, tip: WORDS.gaze.tip });
        }
      }
    }
    if (M.sway.ok && M.sway.look) {
      const w = res.raw.sway.filter((x) => x.on).sort((a, b) => b.amp - a.amp)[0];
      if (w) {
        out.push({ kind: 'sway', observation: `${where(w.seg) || '발표 중'} 무렵 10초 동안 몸이 좌우로 되풀이해 오갔어요`,
          value: `얼굴 폭의 ${Math.round(w.amp * 100)}% 진폭`, basis: BASIS.sway,
          scene: scene(w.seg, w.start, w.end - w.start), conf: M.sway.conf, tip: WORDS.sway.tip });
      }
    }
    if (M.gesture.ok && M.gesture.speak !== null && M.gesture.silent !== null) {
      const d = M.gesture.speak - M.gesture.silent;
      out.push({ kind: 'gesture_speech',
        observation: d > 0.1 ? '말하는 동안 손이 쉴 때보다 자주 움직였어요' : d < -0.1 ? '쉬는 동안 손이 말할 때보다 자주 움직였어요' : '말할 때와 쉴 때 손이 움직인 정도가 비슷했어요',
        value: `말할 때 ${Math.round(M.gesture.speak * 100)}% · 쉴 때 ${Math.round(M.gesture.silent * 100)}%`,
        basis: '마이크 소리 크기로 말하는 때를 나눴어요 — 10%p 넘게 차이 날 때만 다르다고 써요 (설계값)',
        scene: null, conf: M.gesture.conf, tip: '' });
    }
    if (M.framing.ok && M.framing.look) {
      out.push({ kind: 'framing', observation: M.framing.level === 0 ? '얼굴이 화면에서 작게 잡혔어요' : '얼굴이 화면을 크게 채웠어요',
        value: `얼굴 폭 ${Math.round(M.framing.value * 100)}%`, basis: BASIS.framing, scene: null, conf: M.framing.conf, tip: WORDS.framing.tip });
    }
    return out;
  }

  /* ─── 8-2. 갈래 낱말 · 가장 먼저 고칠 한 가지 (리포트 첫 줄용) ───────────── */

  /** 리포트가 갈래(시선 · 고개 / 몸 움직임 / 손짓 / 구도)마다 낱말 하나만 보여 줄 때 — 지표 낱말을 그대로 묶는다(새 판정 없음) */
  const AREAS = [
    { key: 'gaze', label: '시선 · 고개', from: ['gaze', 'lookaway', 'down'] },
    { key: 'body', label: '몸 움직임', from: ['sway', 'movement'] },
    { key: 'hands', label: '손짓', from: ['gesture'] },
    { key: 'frame', label: '구도', from: ['framing'] },
  ];
  const LOOK_WORDS = ['짚을 곳이 없어요', '한 가지 살펴봐요', '여러 가지 살펴봐요'];

  function areasOf(metrics) {
    return AREAS.map((a) => {
      const ms = a.from.map((k) => metrics[k]).filter(Boolean);
      const ok = ms.filter((m) => m.ok);
      if (!ok.length) return { key: a.key, label: a.label, ok: false, level: null, word: UNMEASURED, line: (ms[0] && ms[0].why) || '' };
      const looks = ok.filter((m) => m.look);
      let level; let word;
      if (a.key === 'gaze') { level = Math.min(2, looks.length); word = LOOK_WORDS[level]; }
      else if (a.key === 'body') {
        const sw = metrics.sway; const mv = metrics.movement;
        if (sw && sw.ok) { level = sw.level; word = `흔들림 ${sw.word}`; } else { level = 0; word = `움직임 ${mv.word}`; }
      } else { const m = ok[0]; level = m.look ? Math.max(1, m.level) : (a.key === 'hands' ? m.level : 0); word = m.word; }
      const lead = looks[0] || ok[0];
      return { key: a.key, label: a.label, ok: true, level, word, line: `${lead.label} ${lead.word}`, look: looks.length > 0 };
    });
  }

  const FIRST_ORDER = ['lookaway', 'down', 'gaze_seg', 'sway', 'framing'];
  const CARD_METRIC = { lookaway: 'lookaway', down: 'down', gaze_seg: 'gaze', sway: 'sway', framing: 'framing' };
  const CARD_AREA = { lookaway: 'gaze', down: 'gaze', gaze_seg: 'gaze', sway: 'body', framing: 'frame' };

  /**
   * 가장 먼저 고칠 한 가지 — 근거 카드 중 「연습해 볼 쪽」(look) 지표의 것을 순서(오래 눈 뗌 → 아래 → 장별 시선 → 흔들림 → 구도)대로 하나.
   * 카드가 없지만 청중 쪽 시간이 짧으면 그 지표 자체. 없으면 null — 개수를 채우려고 지어내지 않는다
   */
  function firstFix(res) {
    const M = res.metrics || {};
    for (const kind of FIRST_ORDER) {
      const m = M[CARD_METRIC[kind]];
      if (!m || !m.ok || !m.look) continue;
      const c = (res.cards || []).find((x) => x.kind === kind);
      if (!c) continue;
      const sc = c.scene || {};
      return { kind, area: CARD_AREA[kind], text: c.observation, tip: c.tip || m.tip || '', slide: segSlide(sc.seg || '') , q: segQ(sc.seg || ''), sec: sc.sec ?? null, conf: c.conf };
    }
    if (M.gaze && M.gaze.ok && M.gaze.look) {
      return { kind: 'gaze', area: 'gaze', text: `청중 쪽을 본 시간이 ${Math.round(M.gaze.value * 100)}%로 짧았어요`, tip: M.gaze.tip, slide: null, q: null, sec: null, conf: M.gaze.conf };
    }
    return null;
  }

  /* ─── 9. 묶음 ───────────────────────────────────────────────────────────── */

  /**
   * rows → 분석 묶음. opts.phase: 'present'(발표) | 'qa'(질문). 줄이 없으면 status 'none' 과 까닭(opts.why).
   * 돌려주는 것: { v, phase, status, why, quality, metrics, segs, cards, raw } — raw 는 화면 계산용(서버로 안 보낸다)
   */
  function analyze(rows, opts = {}) {
    const cfg = { ...CFG, ...(opts.cfg || {}) };
    const phase = opts.phase === 'qa' ? 'qa' : 'present';
    const seq = states(rows, cfg);
    if (!seq.length) return { v: VERSION, phase, status: 'none', why: opts.why || '카메라로 본 기록이 없어요', metrics: {}, segs: [], cards: [] };
    const q = quality(seq, cfg);
    const m = measure(seq, cfg);
    const minutes = Math.max(1 / 60, m.presMs / 60000);
    const sway = swayWindows(seq, cfg);
    const swayShare = sway.length ? sway.filter((w) => w.on).length / sway.length : null;
    const metrics = {
      gaze: metric('gaze', q, m.gaze, level3(m.gaze || 0, cfg.gazeLo, cfg.gazeHi), {
        sides: { left: rd(m.left / Math.max(1, m.presMs)), right: rd(m.right / Math.max(1, m.presMs)), down: rd(m.down / Math.max(1, m.presMs)), away: rd(m.away / Math.max(1, m.presMs)) } }, cfg),
      lookaway: metric('lookaway', q, m.look.length / minutes, level3(m.look.length / minutes, cfg.awayPerMinLo, cfg.awayPerMinHi), {
        n: m.look.length, total: sec(sum(m.look.map((r) => r.dur))), longest: m.look.length ? sec(Math.max(...m.look.map((r) => r.dur))) : 0 }, cfg),
      down: metric('down', q, m.downShare, level3(m.downShare || 0, cfg.downLo, cfg.downHi), { n: m.downs.length }, cfg),
      sway: sway.length < 2
        ? { kind: 'sway', label: WORDS.sway.label, ok: false, word: UNMEASURED, why: gateWhy('sway', q, cfg) || '얼굴 자리를 10초 넘게 이어서 따라간 구간이 모자랐어요', basis: BASIS.sway }
        : metric('sway', q, swayShare, level3(swayShare, cfg.swayLo, cfg.swayHi), { windows: sway.length, amp: rd(median(sway.map((w) => w.amp))) }, cfg),
      movement: m.move === null
        ? { kind: 'movement', label: WORDS.movement.label, ok: false, word: UNMEASURED, why: gateWhy('movement', q, cfg) || '몸 영역의 움직임을 재지 못했어요', basis: BASIS.movement }
        : metric('movement', q, m.move, level3(m.move, cfg.moveLo, cfg.moveHi), {}, cfg),
      gesture: m.gesture === null
        ? { kind: 'gesture', label: WORDS.gesture.label, ok: false, word: UNMEASURED, why: gateWhy('gesture', q, cfg) || '손 자리를 재지 못했어요', basis: BASIS.gesture }
        : metric('gesture', q, m.gesture, level3(m.gesture, cfg.gestLo, cfg.gestHi), speechSplit(m, cfg), cfg),
      framing: metric('framing', q, m.size || 0, m.size === null ? 1 : (m.size < cfg.sizeLo ? 0 : m.size > cfg.sizeHi ? 2 : 1), { off: rd(m.off), offside: m.off !== null && m.off > cfg.offCenter }, cfg),
    };
    if (metrics.framing.ok && metrics.framing.offside) {
      metrics.framing.look = true;
      metrics.framing.tip = WORDS.framing.tip;
      if (metrics.framing.level === 1) metrics.framing.word = '한쪽으로 치우쳤어요';
    }
    const res = { v: VERSION, phase, status: 'ok', why: '', t0: seq[0].t, quality: q, metrics, segs: bySeg(seq, cfg), raw: { look: m.look, downs: m.downs, sway } };
    if (Object.values(metrics).every((x) => !x.ok)) { res.status = 'unmeasured'; res.why = metrics.gaze.why || UNMEASURED; }
    res.cards = res.status === 'ok' ? cards(res, cfg) : [];
    res.areas = areasOf(metrics);
    res.first = res.status === 'ok' ? firstFix(res) : null;
    return res;
  }

  function speechSplit(m, cfg) {
    if (m.speakKnown < cfg.minSpeakKnown || m.speakShare < cfg.minSpeakShare || m.silentShare < cfg.minSilentShare) return { speak: null, silent: null };
    return { speak: rd(m.speak), silent: rd(m.silent) };
  }

  /* ─── 10. 서버로 보내는 요약 (숫자만 · 크기 상한) ───────────────────────── */

  const METRIC_KEYS = ['gaze', 'lookaway', 'down', 'sway', 'movement', 'gesture', 'framing'];

  function summaryOf(res, cfg = CFG) {
    if (!res || res.status === 'none') return { v: VERSION, phase: (res && res.phase) || 'present', status: 'none', why: String((res && res.why) || '').slice(0, 120) };
    const q = res.quality;
    const metrics = {};
    METRIC_KEYS.forEach((k) => {
      const x = res.metrics[k];
      if (!x) return;
      metrics[k] = x.ok
        ? { ok: true, value: x.value, level: x.level, conf: x.conf,
          ...(k === 'lookaway' ? { n: x.n, total: x.total, longest: x.longest } : {}),
          ...(k === 'sway' ? { amp: x.amp, windows: x.windows } : {}),
          ...(k === 'gesture' ? { speak: x.speak, silent: x.silent } : {}),
          ...(k === 'framing' ? { off: x.off } : {}),
          ...(k === 'gaze' ? { sides: x.sides } : {}) }
        : { ok: false, why: String(x.why || '').slice(0, 120) };
    });
    const out = {
      v: VERSION, phase: res.phase, status: res.status, why: String(res.why || '').slice(0, 120),
      dur: sec(q.dur), frames: q.frames, fps: rd(q.fps, 2), ms_p50: q.msP50, ms_p90: q.msP90,
      quality: { presence: rd(q.presence), dark: rd(q.dark), bright: rd(q.bright, 1), blur: rd(q.blur, 1), face: rd(q.face), eyes: rd(q.eyes), track: rd(q.track), body: rd(q.body) },
      metrics,
      areas: (res.areas || []).map((a) => ({ key: a.key, ok: a.ok, level: a.level, word: a.word })),
      first: res.first ? { kind: res.first.kind, area: res.first.area, text: String(res.first.text).slice(0, 160), slide: res.first.slide, q: res.first.q, sec: res.first.sec } : null,
      segs: res.segs.slice(0, cfg.maxSegs).map((s) => ({ seg: s.seg, dur: sec(s.dur), present: rd(s.present), gaze: rd(s.gaze), down: rd(s.down), gesture: rd(s.gesture), move: rd(s.move), lookaway: s.lookaway })),
      events: [
        ...res.raw.look.map((r) => ({ k: 'lookaway', seg: r.seg, t: sec(r.start - res.t0), d: sec(r.dur) })),
        ...res.raw.downs.map((r) => ({ k: 'down', seg: r.seg, t: sec(r.start - res.t0), d: sec(r.dur) })),
        ...res.raw.sway.filter((w) => w.on).map((w) => ({ k: 'sway', seg: w.seg, t: sec(w.start - res.t0), d: sec(w.end - w.start) })),
      ].sort((a, b) => b.d - a.d).slice(0, cfg.maxEvents),
    };
    // 크기 상한 — 넘으면 장면 → 장 순으로 줄인다 (숫자 요약은 남긴다)
    while (JSON.stringify(out).length > cfg.maxBytes && (out.events.length || out.segs.length)) {
      if (out.events.length) out.events = out.events.slice(0, Math.floor(out.events.length / 2));
      else out.segs = out.segs.slice(0, Math.floor(out.segs.length / 2));
    }
    return out;
  }

  /** 카메라 분석이 없었던 까닭만 담은 묶음 (카메라 끔 · 권한 없음 · 도구를 못 받음 · 녹음 파일로 대신함) */
  function none(why, phase = 'present') {
    return { v: VERSION, phase, status: 'none', why: String(why || '카메라 분석이 없었어요'), metrics: {}, segs: [], cards: [] };
  }

  const api = { CFG, VERSION, UNMEASURED, WORDS, BASIS, METRIC_KEYS, AREAS, areasOf, firstFix, rawDir, states, runs, hysteresis, bandOf, swayWindows, quality, gateWhy, confidence, measure, bySeg, cards, analyze, summaryOf, none, where };
  root.BehaviorCvLogic = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof self !== 'undefined' ? self : (typeof window !== 'undefined' ? window : globalThis));
