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
    awayHoldMs: 1500,       // 얼굴도 머리 추적(CamShift, 6초)도 끊긴 뒤 이만큼만 「다른 곳」, 넘으면 자리 비움 — 머리 추적이 돌아선 발표자를 잇는다 (실험실 absent_after 1초)
    sideHoldMs: 1500,       // 옆얼굴을 본 뒤 머리만 따라가는 동안 그 옆을 든다 (실험실 side_hold_s)
    baseEma: 0.05,          // 정면 기준선 갱신 속도 (실험실 참조 엔진)
    downEy: 0.47,           // 두 눈이 얼굴 상자 위에서 이 비율보다 아래면 「아래를 봄」 — 정면 모나리자 0.38 (노드 벤치 10-17). 설계값 · 검증 전
    yawEx: 0.09,            // 눈 가운데가 상자 가운데에서 얼굴 폭의 이만큼 넘게 비끼면 옆을 보는 중 — 정면 ±0.03 (노드 벤치). 설계값 · 검증 전
    downShift: 0.22,        // 얼굴 가운데가 정면 기준선보다 얼굴 폭의 이만큼 아래면 「아래를 봄」 — 실험실 v2 pitch -35° 84% · -45° 90% (권고 5). 눈은 보조만(안경 · 짙은 톤에서 0%)
    downDrift: 0.25,        // 얼굴을 놓치기 직전 0.8초 동안 얼굴 높이의 이만큼 아래로 내려갔으면 그 뒤 놓친 시간은 「아래를 봄」 (설계값 · 검증 전)
    driftWinMs: 800,
    lostDownMaxMs: 6000,    // 위 「아래를 봄」 추정은 이만큼까지만 — 더 길면 방향을 모름(다른 곳)으로 둔다
    lookAwayMs: 3000,       // 화면 쪽에서 벗어난 구간이 이보다 길면 짚는다 — 3초를 검증한 연구는 없다(근거조사 §1-2, 가까운 근거 Binetti 2016 선호 응시 ≈3.3초). 설계값 · 검증 전
    downSegMs: 2000,        // 아래를 본 구간 짚기 — 2초 넘게 (설계값 · 검증 전)
    // 흔들림: 얼굴 가운데 x(얼굴 폭 단위)의 0.3~1.5Hz 반복 성분. 자세 흔들림 연구가 보는 대역(서 있는 사람 몸 흔들림 ≈ 0.1~1Hz)에 걸음 · 체중 옮김을 더한 설계값
    swayLoHz: 0.3, swayHiHz: 1.5,
    swayWinMs: 8000, swayStepMs: 2000, swayFs: 5,   // 8초 창 · 2초 걸음 — 실험실 참조 엔진(주파수 오차 중앙 0.005Hz). 1.5Hz 를 보려면 처리 5fps 유지
    swayAmp: 0.12,          // 대역 진폭이 얼굴 폭의 이만큼(≈ 2cm, 봉우리 간 0.3 폭) 넘으면 흔들림 창 — 근거조사 §1-4 권장(봉우리 간 0.1 폭)보다 높게 둔 건 Haar 상자 떨림(±0.03 폭) 때문 (설계값 · 검증 전)
    swayShare: 0.55,        // 대역 힘이 전체(0.05Hz~)의 이 몫 넘을 때만 — 천천히 자리 옮김은 흔들림이 아니다 (실험실 sway_ratio)
    // 대역 아래쪽(0.3~0.42Hz)은 느린 이동(0.12Hz)이 끝날 때의 꺾임이 새어 들어오는 자리다 — 거기 봉우리면 대역 몫이 0.85 넘게 깨끗할 때만 (실험실 s07 오탐 10초 → 0)
    swayPure: 0.85, swayLowF: 0.42,
    swayCover: 0.7,         // 창 안에 얼굴 자리가 이만큼 있어야 그 창을 잰다
    // 움직임 양 — 몸 영역에서 0.2초 사이 바뀐 점 비율(MEA). 노드 벤치: 가만히 0.01~0.04 · 흔들림 0.2. 3단계 경계는 설계값 · 검증 전
    // (근거조사 §1-5: 팀 녹화 백분위 P20/P80 으로 다시 정할 자리)
    moveLo: 0.05, moveHi: 0.15,
    // 손짓 — 손 크기 덩어리의 움직인 피부 넓이 / 얼굴 넓이(features gs). 최근 3장 중 2장 넘으면 켜짐 (실험실 gest_thr 0.035)
    gestThr: 0.035,
    // 켜짐 = 최근 3장 중 2장, 꺼짐 = 최근 2장이 다 문턱 아래일 때 (히스테리시스 — 흐림 · 압축에서 손 덩어리가 한 장씩 끊겨 켜짐이 깜빡였다, 실험실 바퀴 3)
    gestOnN: 2, gestOnWin: 3, gestHoldN: 1, gestOffWin: 2,
    gestSoftK: 0.7,         // 무른 켜짐 · 유지 기준(gestThr × 이 값) — 문턱 언저리에서 손짓 시작이 장마다 흔들렸다(d8 2장 손짓 비율 위상별 표준편차 5.3 → 3.9%p, 바퀴 3)
    gestBridgeMs: 3000,     // 장 넘김으로 뺀 줄(최대 이만큼) 뒤 gestBridgeWin 장 중 gestBridgeN 장이 문턱 위면 넘김 동안도 손짓을 잰다 (gestureFlags)
    gestBridgeWin: 4, gestBridgeN: 2,
    gestResetMs: 1000,      // 이만큼 넘게 못 잰 뒤엔 손짓 상태기계를 처음부터
    gestOn: 0.05, gestOff: 0.025,   // 옛 줄(gs 없음, hl/hr/hf)용
    slideGuardMs: 1000,     // 장 넘김 앞뒤 1초는 움직임 · 손짓에서 뺀다 (자료를 넘기는 손 · 몸 — 실험실 권고 6)
    sceneSpike: 0.35,       // 화면 전체에서 바뀐 점이 이 몫 넘는 장(조명 · 카메라 흔들림 · 장면 바뀜)은 움직임 · 손짓에서 뺀다
    // ── 품질 게이트 ──
    minDurMs: 20000, minFrames: 40, minFps: 2.5,
    minPresence: 0.6,       // 얼굴(또는 사람)이 있는 시간이 이 아래면 방향 지표를 재지 않는다 (계획 §2)
    darkBr: 40,             // 평균 밝기 이 아래 줄은 어둡다 (계획 §2 「밝기 ≥ 40」)
    maxDark: 0.3,           // 어두운 줄이 이보다 많으면 못 잼
    blurMin: 15,            // 얼굴 라플라시안 분산 중앙값이 이 아래면 흐림 — 노드 벤치: 또렷 ≈ 340, 가우스 3.5px 흐림 ≈ 3.7 (설계값)
    minFaceW: 0.08,         // 얼굴 폭 중앙값이 화면 폭의 이 비율 아래면 「너무 멀어요」 — 엔진이 0.06 얼굴은 아예 못 찾았다 (실험실 d7, 권고 8)
    backlit: 0.5,           // 얼굴 상자 밝기 / 화면 밝기가 이 아래면 역광 — 역광은 화면 평균 밝기로는 못 잡는다 (실험실 d5, 권고 8)
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
    if (row.src === 'C') return 'face';   // 캐스케이드 없는 예비 모드 — 얼굴 자리만 있고 방향은 모른다
    if (row.src === 'P') return row.side > 0 ? 'right' : 'left';
    if (row.src === 'T') return 'unknown';
    // 정면 Haar(alt2)는 고개를 20~35° 돌려도 잡는다 — 이 범위는 Haar 로 가를 수 없어 「화면 쪽」 으로 둔다 (실험실 각도 곡선 · 권고 4).
    // 그래서 눈 가운데 비낌(ex)으로 옆을 나누지 않는다. 아래는 states() 가 얼굴 가운데 하강으로 본다
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
    let lastDef = null; let lastDefAt = -Infinity;     // 마지막 확실한 방향(정면 · 아래) · 시각
    let lastSide = null; let lastSideAt = -Infinity;   // 마지막 옆얼굴 방향 — 놓친 뒤 sideHoldMs 동안 든다
    let lastFaceAt = -Infinity; let lostMode = '';
    let lostStart = -Infinity;
    let base = null;                                   // 정면 기준선 — 얼굴 가운데 y (지수 평균, 정면일 때만 천천히)
    const fhs = [];                                    // 최근 정면 얼굴 높이 (= 정사각 Haar 상자의 폭)
    for (let i = 0; i < list.length; i += 1) {
      const row = list[i];
      const next = list[i + 1];
      const dt = next ? Math.min(cfg.dtCapMs, Math.max(0, next.t - row.t)) : Math.min(cfg.dtCapMs, out.length ? out[out.length - 1].dt : 200);
      let raw = rawDir(row, cfg);
      if (raw === 'face') { out.push({ t: row.t, dt, raw, state: 'face', row }); lastFaceAt = row.t; continue; }
      // 숙임 = 얼굴 가운데가 정면 기준선보다 얼굴 폭의 downShift 넘게 내려감 (실험실 권고 5 — 주 신호). 눈은 보조
      if (row.box && (row.src === 'F' || row.src === 'T')) {
        if (row.src === 'F') { fhs.push(row.box[3]); if (fhs.length > 50) fhs.shift(); }
        const fh = fhs.length ? median(fhs) : row.box[3];
        const cy = cyOf(row);
        const dy = base === null ? null : (cy - base) / Math.max(0.01, fh);
        if (raw === 'front' && (dy === null || dy < cfg.downShift * 0.5)) base = base === null ? cy : (1 - cfg.baseEma) * base + cfg.baseEma * cy;
        if (dy !== null && dy > cfg.downShift && (raw === 'front' || raw === 'unknown')) raw = 'down';
        else if (raw === 'front' && row.eyes === 2 && row.ey > cfg.downEy && dy !== null && dy > cfg.downShift * 0.5) raw = 'down';
      }
      if (raw === 'front' || raw === 'down') { lastDef = raw; lastDefAt = row.t; lostMode = ''; }
      if (raw === 'left' || raw === 'right') { lastSide = raw; lastSideAt = row.t; lostMode = ''; }
      if (row.src) lastFaceAt = row.t;
      let s = raw;
      if (raw === 'unknown') {
        // 이어 붙인 머리 — 옆을 보다 놓쳤으면 그 옆, 잠깐이면 하던 방향, 길면 방향 모름(다른 곳)
        if (lastSide && row.t - lastSideAt <= cfg.sideHoldMs) s = lastSide;
        else if (lastDef && row.t - lastDefAt <= cfg.fillMs) s = lastDef;
        else s = 'away';
      } else if (raw === 'none') {
        if (!lostMode) {
          lostStart = row.t;
          lostMode = droppedDown(list, i, cfg) ? 'down' : 'away';
        }
        if (lastDef && row.t - lastDefAt <= cfg.fillMs) s = lastDef;
        else if (lostMode === 'down' && row.t - lostStart <= cfg.lostDownMaxMs) s = 'down';
        else if (row.t - lastFaceAt <= cfg.awayHoldMs) s = 'away';
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
    // 2차 추세 빼기 — 천천히 자리 옮김(0.12Hz 같은)이 대역으로 새지 않게 (실험실 참조 엔진)
    const u = x.map((_, k) => (k - (n - 1) / 2) / n);
    const S = [0, 0, 0, 0, 0]; const T = [0, 0, 0];
    u.forEach((v, k) => { for (let p = 0; p <= 4; p += 1) S[p] += v ** p; for (let p = 0; p <= 2; p += 1) T[p] += x[k] * v ** p; });
    const A = [[S[0], S[1], S[2]], [S[1], S[2], S[3]], [S[2], S[3], S[4]]];
    const det = (m) => m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
    const D = det(A);
    const c = [0, 1, 2].map((j) => (D ? det(A.map((row, r) => row.map((v, q) => (q === j ? T[r] : v)))) / D : 0));
    const y = x.map((v, k) => v - (c[0] + c[1] * u[k] + c[2] * u[k] * u[k]));
    // 한닝 창 — 창 끝의 잘림이 대역으로 새지 않게(느린 이동 0.12Hz 가 0.3Hz 칸으로 새어 흔들림으로 켜졌다, 실험실 s07 9.8초).
    // 대역 몫 · 주파수는 한닝 스펙트럼으로, 진폭은 창 없는 Parseval 로 (한닝은 진폭을 줄인다)
    const han = y.map((_, m) => 0.5 - 0.5 * Math.cos((2 * Math.PI * m) / (n - 1)));
    const pw = (f, win) => {
      let re = 0; let im = 0;
      for (let m = 0; m < n; m += 1) { const v = win ? y[m] * han[m] : y[m]; const ang = (-2 * Math.PI * f * m) / fs; re += v * Math.cos(ang); im += v * Math.sin(ang); }
      return (2 * (re * re + im * im)) / (n * n);   // 한쪽 스펙트럼 힘 (Parseval)
    };
    let band = 0; let bandW = 0; let totalW = 0;
    const df = fs / (4 * n);   // 네 배 촘촘한 격자 (한닝 몫 · 주파수)
    for (let f = df; f < fs / 2; f += df) {
      if (f < 0.05) continue;
      const p = pw(f, true);
      totalW += p;
      if (f >= lo && f <= hi) bandW += p;
    }
    for (let k = 1; k < n / 2; k += 1) {
      const f = (k * fs) / n;
      if (f >= lo && f <= hi) band += pw(f, false);
    }
    // 주파수 — 대역 안 0.02Hz 격자에서 가장 센 곳
    let freq = null; let best = -1;
    for (let f = lo; f <= hi + 1e-9; f += 0.02) { const p = pw(f, true); if (p > best) { best = p; freq = f; } }
    return { amp: Math.sqrt(2 * band), share: totalW > 0 ? bandW / totalW : 0, freq: freq === null ? null : Math.round(freq * 100) / 100 };
  }

  /**
   * 흔들림 창들 — [{ start, end, amp, share, freq, on, seg }]. 얼굴 폭 중앙값으로 나눠 거리에 상관없게.
   * **고개를 돌린 동안(옆 · 다른 곳 · 놓침)은 뺀다** — 옆얼굴 상자는 머리 가운데에서 비껴 있어 돌림이 흔들림으로 셌다(실험실 s02 오탐 14.8초).
   * 진폭은 대역 거르기 손실로 15~20% 작게 나온다(실험실) — 화면엔 「대략」.
   */
  function swayWindows(seq, cfg = CFG) {
    const okState = (x) => x.state === 'front' || x.state === 'face';
    const pts = seq.filter((x) => x.row.box && okState(x)).map((x) => ({ t: x.t, v: x.row.box[0] + x.row.box[2] / 2, w: x.row.box[2], seg: x.row.seg || '' }));
    if (pts.length < 8) return [];
    const fw = median(pts.map((p) => p.w)) || 0.1;
    const P = pts.map((p) => ({ ...p, v: p.v / fw }));
    const t0 = seq[0].t; const tEnd = seq[seq.length - 1].t;
    const fps = fpsOf(seq);
    const out = [];
    for (let a = t0; a + cfg.swayWinMs <= tEnd + 1; a += cfg.swayStepMs) {
      const b = a + cfg.swayWinMs;
      const inWin = P.filter((p) => p.t >= a && p.t < b);
      const cover = inWin.length / Math.max(1, ((b - a) / 1000) * fps);
      if (cover < cfg.swayCover || inWin.length < 8) continue;
      const fs = Math.min(cfg.swayFs, Math.round(fps));
      const x = resample(inWin, a, b, fs);
      if (!x) continue;
      const hi = Math.min(cfg.swayHiHz, 0.49 * fs);
      const r = bandOf(x, fs, cfg.swayLoHz, hi);
      if (!r) continue;
      out.push({ start: a, end: b, amp: r.amp, share: r.share, freq: r.freq, on: r.amp >= cfg.swayAmp && (r.share >= cfg.swayPure || (r.share >= cfg.swayShare && r.freq >= cfg.swayLowF)), seg: inWin[inWin.length >> 1].seg });   // 창 가운데의 장
    }
    return out;
  }

  function fpsOf(seq) {
    if (seq.length < 2) return 0;
    const span = (seq[seq.length - 1].t - seq[0].t) / 1000;
    return span > 0 ? (seq.length - 1) / span : 0;
  }

  /* ─── 4. 움직임 · 손짓 ──────────────────────────────────────────────────── */

  /**
   * 줄마다 몸 움직임 — 프레임 차분(MEA) 몸 영역에서 바뀐 점 비율을 0.2초(5fps 한 장) 사이 몫으로 맞춘다.
   * 차분은 앞 줄과의 차이라서 3fps 로 느려지면 값이 커진다 — 간격으로 나눠 기기 속도와 상관없게 (근거조사 §7-4: 움직임 양은 MEA 가 주 신호)
   */
  function bodySpeed(seq, cfg = CFG) {
    const ex = excluded(seq, cfg);
    const out = [];
    for (let i = 1; i < seq.length; i += 1) {
      const r = seq[i].row; const gap = (seq[i].t - seq[i - 1].t) / 1000;
      if (ex[i] || !Number.isFinite(r.meb) || gap <= 0 || gap > 1.2) continue;
      out.push({ i, v: Math.min(1, (r.meb * 0.2) / gap) });
    }
    return out;
  }

  /** 움직임 · 손짓에서 뺄 줄 — 장 넘김 앞뒤 slideGuardMs('turn'), 화면 전체가 크게 바뀐 장(sceneSpike, 'spike'). 안 빼면 '' */
  function excludedWhy(seq, cfg = CFG) {
    const turns = [];
    for (let i = 1; i < seq.length; i += 1) if ((seq[i].row.seg || '') !== (seq[i - 1].row.seg || '')) turns.push(seq[i].t);
    return seq.map((x) => (Number(x.row.mea) > cfg.sceneSpike ? 'spike' : turns.some((t) => Math.abs(x.t - t) <= cfg.slideGuardMs) ? 'turn' : ''));
  }
  function excluded(seq, cfg = CFG) { return excludedWhy(seq, cfg).map(Boolean); }

  /**
   * 손짓 켜짐/꺼짐 상태기계 — skip[i] 인 줄은 건너뛴다(null). gs 줄: 최근 gestOnWin 장 중 gestOnN 장이 문턱 위면 켜짐,
   * 켜진 뒤엔 최근 gestOffWin 장 중 gestHoldN 장만 넘어도 유지 (히스테리시스 — 흐림 · 압축에서 손 덩어리가 한 장씩 끊겨 켜짐이 깜빡였다, 실험실 바퀴 3).
   * 옛 줄(gs 없음, hl/hr/hf)은 gestOn/gestOff 히스테리시스
   */
  function gestureRun(seq, skip, cfg) {
    let on = false;
    const recent = [];
    let lastT = -Infinity;
    return seq.map((x, i) => {
      const r = x.row;
      if (!x.present || skip[i]) return null;
      // 1초 넘게 못 잰 뒤(장 넘김 · 자리 비움)는 처음부터 — 앞에서 남은 표로 켜짐을 잇지 않는다 (s08 손짓 → 장 넘김 → 가만한 손 오탐)
      if (x.t - lastT > cfg.gestResetMs) { recent.length = 0; on = false; }
      lastT = x.t;
      if (Number.isFinite(r.gs)) {
        recent.push(r.gs);
        if (recent.length > Math.max(cfg.gestOnWin, cfg.gestOffWin)) recent.shift();
        const win = recent.slice(-cfg.gestOnWin);
        const nOn = win.filter((g) => g > cfg.gestThr).length;
        // 문턱 언저리(손이 잠깐 멈췄다 움직임) — 반 문턱 넘은 장이 gestOnN 장이고 평균이 문턱 위면 켜짐. 한 장짜리 큰 값만으로는 안 켜진다
        const soft = cfg.gestSoftK > 0 && win.filter((g) => g > cfg.gestThr * cfg.gestSoftK).length >= cfg.gestOnN && win.reduce((a, b) => a + b, 0) / win.length > cfg.gestThr;
        const nHold = recent.slice(-cfg.gestOffWin).filter((g) => g > cfg.gestThr * (cfg.gestSoftK > 0 ? cfg.gestSoftK : 1)).length;
        on = on ? nHold >= cfg.gestHoldN : (nOn >= cfg.gestOnN || soft);
        return on;
      }
      const vals = [r.hl, r.hr, r.hf].filter(Number.isFinite);
      if (!vals.length || !Number.isFinite(r.body)) return null;
      const g = Math.max(...vals);
      on = on ? g >= cfg.gestOff : g >= cfg.gestOn;
      return on;
    });
  }

  /**
   * 손짓 켜짐/꺼짐 — 손 자리를 잴 수 있는 줄만 (null = 못 잼).
   * 장 넘김 앞뒤(slideGuardMs)는 자료를 넘기는 손 때문에 빼되, **넘김 뒤 gestBridgeWin 장 안에 손짓이 다시 gestOnN 장 넘게 보이면**
   * 넘김 동안도 손짓을 잰다 — 장을 넘기는 사이에도 이어진 손짓이다(넘기는 손 하나는 넘김 뒤까지 이어지지 않는다). 손짓 재현율 .49 → (바퀴 3)
   */
  function gestureFlags(seq, cfg = CFG) {
    const why = excludedWhy(seq, cfg);
    const flags = gestureRun(seq, why.map(Boolean), cfg);
    if (!(cfg.gestBridgeMs > 0) || !why.includes('turn')) return flags;
    const all = gestureRun(seq, why.map((w) => w === 'spike'), cfg);   // 넘김 줄도 센 상태기계
    for (let i = 0; i < seq.length; i += 1) {
      if (why[i] !== 'turn') continue;
      let b = i; while (b < seq.length && why[b] === 'turn') b += 1;
      const after = seq.slice(b, b + cfg.gestBridgeWin).filter((x) => Number(x.row.gs) > cfg.gestThr).length;
      if (b < seq.length && after >= cfg.gestBridgeN && seq[b].t - seq[i].t <= cfg.gestBridgeMs) {
        for (let k = i; k < b; k += 1) flags[k] = all[k];
        // 이은 뒤 몇 장은 이어 센 상태기계를 따른다 — 넘김 뒤 처음부터 다시 세느라 켜짐이 잠깐 끊기지 않게
        for (let k = b; k < Math.min(seq.length, b + cfg.gestOnWin + cfg.gestOffWin) && !why[k] && flags[k] !== all[k]; k += 1) flags[k] = all[k];
      }
      i = b;
    }
    return flags;
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
      body: presentRows.length ? presentRows.filter((x) => Number.isFinite(x.row.body) || Number.isFinite(x.row.meb)).length / presentRows.length : 0,
      // 역광 — 얼굴 상자 밝기 / 화면 밝기 (정면 · 옆얼굴 줄)
      backlit: median(faceRows.filter((x) => Number.isFinite(x.row.fb) && Number(x.row.br) > 0).map((x) => x.row.fb / x.row.br)),
      msP50: median(ms), msP90: quant(ms, 0.9),
      noc: seq.length ? seq.filter((x) => x.row.mode === 'noc').length / seq.length : 0,
    };
  }

  /** 지표마다 게이트 — 통과면 '', 아니면 사람이 고칠 수 있는 까닭 */
  function gateWhy(kind, q, cfg = CFG) {
    if (q.dur < cfg.minDurMs || q.frames < cfg.minFrames) return '카메라로 본 시간이 20초가 안 돼요';
    if (q.fps < (kind === 'movement' || kind === 'gesture' ? 2 : cfg.minFps)) return '이 기기에서 화면을 충분히 자주 보지 못했어요';
    if (q.dark > cfg.maxDark) return '화면이 어두웠어요 — 얼굴 앞쪽을 밝게 하면 잴 수 있어요';
    if (kind === 'framing') return q.presence < 0.3 ? '얼굴이 화면에 거의 없었어요' : '';
    if (q.noc > 0.5 && (kind === 'gaze' || kind === 'lookaway' || kind === 'down')) return '캐스케이드 없는 예비 모드라 얼굴 방향은 재지 않았어요';
    if (kind === 'movement' || kind === 'gesture') {
      if (q.presence < 0.3) return '사람이 화면에 거의 없었어요';
      if (q.body < cfg.minBody) return '몸이 화면에 거의 안 보였어요 — 카메라를 조금 멀리 두면 잴 수 있어요';
      return '';
    }
    if (q.presence < cfg.minPresence) return '얼굴이 화면에 잡힌 시간이 짧았어요';
    if (q.face !== null && q.face < cfg.minFaceW) return '카메라에서 너무 멀어요 — 조금 가까이 오면 잴 수 있어요';
    if (q.backlit !== null && q.backlit < cfg.backlit) return '뒤쪽이 밝아(역광) 얼굴이 어두웠어요 — 얼굴 앞쪽을 밝히면 잴 수 있어요';
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
    // 「화면 쪽」 — Haar 는 카메라를 보는 것과 노트북 화면(자료)을 보는 것을 가르지 못한다. 눈 맞춤이라고 부르지 않는다 (근거조사 §0-2)
    gaze: { label: '화면 쪽을 향한 시간', words: ['짧아요', '조금 짧아요', '충분해요'], look: [true, false, false],
      tip: '장을 넘길 때마다 한 문장은 카메라를 보며 말해 봐요.' },
    lookaway: { label: '3초 넘게 벗어난 구간', words: ['드물어요', '가끔 있어요', '잦아요'], look: [false, false, true],
      tip: '자료를 볼 때는 짧게 보고 다시 화면 쪽으로 돌아오는 연습을 해 봐요.' },
    down: { label: '아래를 본 시간', words: ['짧아요', '조금 길어요', '길어요'], look: [false, false, true],
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
    gaze: `있는 시간 중 ${Math.round(CFG.gazeLo * 100)}% 아래 짧아요 · ${Math.round(CFG.gazeHi * 100)}% 넘으면 충분해요 (설계값 · 검증 전). 고개를 20~35° 돌린 정도는 「화면 쪽」 으로 세요 — 이 정도는 고전 얼굴 검출로 가를 수 없어요`,
    lookaway: `화면 쪽에서 ${CFG.lookAwayMs / 1000}초 넘게 눈을 뗀 구간을 1분에 몇 번 했나 — ${CFG.awayPerMinLo}번 아래 드물어요 · ${CFG.awayPerMinHi}번 넘으면 잦아요 (설계값 · 검증 전)`,
    down: `있는 시간 중 ${Math.round(CFG.downLo * 100)}% 아래 짧아요 · ${Math.round(CFG.downHi * 100)}% 넘으면 길어요 (설계값 · 검증 전). 얼굴이 평소 자리보다 얼굴 폭의 ${Math.round(CFG.downShift * 100)}% 넘게 내려가면 아래로 봐요`,
    sway: `8초 창에서 얼굴이 ${CFG.swayLoHz}~${CFG.swayHiHz}Hz 로 얼굴 폭의 ${Math.round(CFG.swayAmp * 100)}% 넘게 오간 창의 비율 — 고개를 돌린 동안은 빼요. 진폭은 대략이에요(15~20% 작게 잴 수 있어요) (설계값 · 검증 전)`,
    movement: `몸 영역에서 0.2초 사이 바뀐 점이 ${Math.round(CFG.moveLo * 100)}% 아래면 적어요 · ${Math.round(CFG.moveHi * 100)}% 넘으면 많아요 — 많고 적음에 좋고 나쁨은 없어요 (설계값 · 검증 전)`,
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
    const look = runs(seq, (x) => x.present && x.state !== 'front' && x.state !== 'face', cfg.lookAwayMs);
    const downs = runs(seq, (x) => x.state === 'down', cfg.downSegMs);
    const speeds = bodySpeed(seq, cfg).filter((s) => seq[s.i].present).map((s) => s.v);
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

  // 왼쪽 · 오른쪽은 화면에 따로 쓰지 않는다 — 옆얼굴 검출이 약해 대부분 「방향 모름」 이라 가를 수 있는 때가 드물다 (실험실 권고 3). 안의 상태 이름은 실험실 채점용으로 둔다
  const SIDE_WORD = { left: '다른 곳', right: '다른 곳', down: '아래', away: '다른 곳' };

  function mainDir(states) {
    const ms = { 다른곳: 0, 아래: 0 };
    Object.entries(states || {}).forEach(([k, v]) => { if (k === 'down') ms.아래 += v; else if (k !== 'front') ms.다른곳 += v; });
    return ms.아래 > ms.다른곳 ? '아래' : '다른 곳';
  }

  function cards(res, cfg = CFG) {
    const out = [];
    const M = res.metrics;
    const t0 = res.t0 || 0;
    const scene = (seg, t, dur) => ({ seg, where: where(seg), sec: sec(t - t0), dur: sec(dur) });
    if (M.lookaway.ok) {
      res.raw.look.slice().sort((a, b) => b.dur - a.dur).slice(0, 3).forEach((r) => {
        out.push({ kind: 'lookaway', observation: `${where(r.seg) || '발표 중'}에서 ${sec(r.dur)}초 동안 화면 쪽이 아니라 ${mainDir(r.states)}을 향했어요`,
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
          out.push({ kind: 'gaze_seg', observation: `${where(low.seg)}에서는 화면 쪽을 향한 시간이 발표 전체보다 눈에 띄게 짧았어요`,
            value: `${Math.round(low.gaze * 100)}% (${sec(low.dur)}초 중) · 발표 전체 ${Math.round(all * 100)}%`, basis: '이 발표의 다른 장과 견줘서 15%p 넘게 낮을 때 짚어요 (설계값 · 검증 전)',
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
    // 말할 때도 쉴 때도 손이 거의 안 움직였으면 견줄 거리가 없다 — 「비슷했어요」 카드를 내지 않는다 (헤드리스 사진: 0% · 0% 에 「비슷」)
    if (M.gesture.ok && M.gesture.speak !== null && M.gesture.silent !== null && Math.max(M.gesture.speak, M.gesture.silent) >= 0.05) {
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
      return { key: a.key, label: a.label, ok: true, level, word, line: areaLine(a.key, metrics, looks), look: looks.length > 0 };
    });
  }

  /** 갈래 낱말 아래 한 줄 — 낱말을 되풀이하지 않고 그 갈래의 나머지 관찰을 붙인다 */
  function areaLine(key, M, looks) {
    const say = (k) => (M[k] && M[k].ok ? `${M[k].label} ${M[k].word}` : '');
    if (key === 'gaze') {
      const parts = (looks.length ? looks.map((m) => `${m.label} ${m.word}`) : [say('gaze'), say('lookaway')]).filter(Boolean);
      return parts.join(' · ');
    }
    if (key === 'body') {
      return M.sway && M.sway.ok ? say('movement') || '몸 좌우 흔들림을 쟀어요' : '좌우 흔들림은 이번엔 잴 수 없었어요';
    }
    if (key === 'hands') {
      const g = M.gesture;
      if (g && Number.isFinite(g.speak) && Number.isFinite(g.silent) && Math.max(g.speak, g.silent) >= 0.05) {
        const d = g.speak - g.silent;
        return d > 0.1 ? '말할 때 손이 더 자주 움직였어요' : d < -0.1 ? '쉴 때 손이 더 자주 움직였어요' : '말할 때와 쉴 때 비슷하게 움직였어요';
      }
      return g && g.ok && g.value < 0.05 ? '손이 화면에서 거의 움직이지 않았어요' : '손 자리 움직임만 봤어요 — 많고 적음에 좋고 나쁨은 없어요';
    }
    const f = M.framing;
    return f && f.offside ? '얼굴이 화면 가운데에서 비껴 있었어요' : '얼굴 크기 · 자리를 봤어요';
  }

  const FIRST_ORDER = ['lookaway', 'down', 'gaze_seg', 'sway', 'framing'];
  const CARD_METRIC = { lookaway: 'lookaway', down: 'down', gaze_seg: 'gaze', sway: 'sway', framing: 'framing' };
  const CARD_AREA = { lookaway: 'gaze', down: 'gaze', gaze_seg: 'gaze', sway: 'body', framing: 'frame' };

  /**
   * 가장 먼저 고칠 한 가지 — 근거 카드 중 「연습해 볼 쪽」(look) 지표의 것을 순서(오래 눈 뗌 → 아래 → 장별 시선 → 흔들림 → 구도)대로 하나.
   * 카드가 없지만 화면 쪽 시간이 짧으면 그 지표 자체. 없으면 null — 개수를 채우려고 지어내지 않는다
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
      return { kind: 'gaze', area: 'gaze', text: '발표하는 동안 화면 쪽을 향한 시간이 짧았어요', tip: M.gaze.tip, slide: null, q: null, sec: null, conf: M.gaze.conf };
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

  const api = { CFG, VERSION, UNMEASURED, WORDS, BASIS, METRIC_KEYS, AREAS, areasOf, firstFix, gestureFlags, excluded, excludedWhy, bodySpeed, rawDir, states, runs, hysteresis, bandOf, swayWindows, quality, gateWhy, confidence, measure, bySeg, cards, analyze, summaryOf, none, where };
  root.BehaviorCvLogic = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof self !== 'undefined' ? self : (typeof window !== 'undefined' ? window : globalThis));
