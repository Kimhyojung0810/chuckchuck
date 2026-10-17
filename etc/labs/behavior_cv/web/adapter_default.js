/**
 * 행동 실험실 어댑터 — 엔진(main/web/js/behavior_cv*.js, 2026-10-17 6dd2891 모양)을 실험 하네스에 잇는다.
 * 엔진 이름 · 함수가 바뀌면 **이 파일만** 고친다 (run.py browser --adapter 다른파일.js 로 바꿔 끼워도 된다).
 *
 * 하네스가 부르는 것:
 *   scripts            — 하네스가 먼저 읽을 엔진 파일(엔진 worktree 의 main/web 기준 상대 경로)
 *   prepare(cfg)       — 도구 받기(OpenCV · 캐스케이드). 다 되면 끝나는 Promise. 이게 끝나야 가짜 카메라를 연다(영상 0번부터 재려고)
 *   start(ctx)         — 기록 시작. ctx.video(<video>) · ctx.seg() → 's1','s2'… (지금 프레임의 장) · ctx.frameNow()
 *   markSlide(i, t)    — 장이 바뀐 순간(엔진이 seg() 를 줄마다 물으면 따로 할 일 없음)
 *   stop(ctx)          — 기록 끝 → { rows:[…], summary:{ slides:[…], lookaways:[…] }, engine_view, adapter_note }
 *
 * rows 한 줄(채점기 계약): { frame, orient, present, sway:{active, amp_fw, freq?}, gesture, motion, ms, raw }
 *   frame = LabTap 이 워커로 가는 RGBA 에서 푼 바코드 번호(엔진이 실제로 본 프레임). 못 풀면 시계로 추정.
 *   orient = BehaviorCvLogic.states() 의 state (front/left/right/down/away/none) — 좌우는 **발표자 기준**이라 채점은 --yaw-convention subject.
 */
(function (root) {
  'use strict';
  const PHASE = 'present';

  root.LabAdapter = {
    scripts: ['js/behavior_cv_logic.js', 'js/behavior_cv.js'],

    async prepare() {
      if (!root.BehaviorCV) throw new Error('BehaviorCV 가 없어요');
      const ok = await root.BehaviorCV.load();
      if (!ok) throw new Error('BehaviorCV.load 실패: ' + JSON.stringify(root.BehaviorCV.snapshot()));
    },

    start(ctx) {
      root.BehaviorCV.start(PHASE, { video: () => ctx.video, seg: ctx.seg, active: () => true });
    },

    markSlide() { /* 엔진이 줄마다 seg() 를 묻는다 */ },

    async stop(ctx) {
      const L = root.BehaviorCvLogic;
      const view = root.BehaviorCV.finish(PHASE);
      const tap = root.LabTap.joined(ctx.sinceId).filter((x) => x.row && x.perfSent >= ctx.startPerf - 5);
      // 워커 줄 + 엔진이 붙이는 장 표시(seg) — 엔진 안 줄과 같게 만든다 (seg 는 프레임 번호에서 다시 셈)
      const fps = ctx.cfg.fps;
      const slideOf = (f) => { const t = f / fps; let k = 0; ctx.cfg.slides.forEach((s, i) => { if (t >= s.t0) k = i; }); return k; };
      let nClock = 0;
      const rows = tap.map((x) => {
        let f = x.frame;
        if (!(f >= 0)) { f = root.LabTap.frameOfPerf(x.perfSent, ctx.startPerf - 2000); nClock += 1; }
        return { ...x.row, seg: 's' + (slideOf(f) + 1), _frame: f };
      });
      const seq = L.states(rows);
      // 손짓 켜짐/꺼짐 — 엔진이 gestureFlags 를 내놓으면(10-17 바퀴 2~) 그대로, 옛 엔진이면 같은 규칙을 여기서 되풀이한다
      let on = false;
      const gflags = L.gestureFlags ? L.gestureFlags(seq) : seq.map((x) => {
        const r = x.row; const vals = [r.hl, r.hr, r.hf].filter(Number.isFinite);
        if (!x.present || !vals.length || !Number.isFinite(r.body)) return null;
        const g = Math.max(...vals); on = on ? g >= L.CFG.gestOff : g >= L.CFG.gestOn; return on;
      });
      const sw = L.swayWindows(seq);
      const out = seq.map((x, i) => {
        const inOn = sw.filter((w) => w.on && x.t >= w.start && x.t < w.end);
        const any = sw.filter((w) => x.t >= w.start && x.t < w.end);
        return {
          frame: x.row._frame, orient: x.state, orient_raw: x.raw, present: x.present,
          sway: { active: inOn.length > 0, amp_fw: any.length ? Math.max(...any.map((w) => w.amp)) : null, freq: (inOn[0] || any[0] || {}).freq ?? null },
          gesture: gflags[i] === true, motion: Number.isFinite(x.row.meb) ? x.row.meb : (Number.isFinite(x.row.body) ? x.row.body : null), ms: x.row.ms,
          raw: { src: x.row.src, side: x.row.side, box: x.row.box, eyes: x.row.eyes, ey: x.row.ey, ex: x.row.ex, br: x.row.br, bl: x.row.bl, fb: x.row.fb, gs: x.row.gs, meb: x.row.meb, mea: x.row.mea, body: x.row.body, sw: x.row.sw, dead: x.row.dead },
        };
      });
      // 엔진 자체 집계 — 긴 이탈 구간(영상 초) · 장별 값
      const t2f = (t) => { let best = seq[0]; for (const x of seq) { if (x.t <= t) best = x; else break; } return best ? best.row._frame : 0; };
      const m = L.measure(seq);
      const lookaways = m.look.map((r) => ({ t0: t2f(r.start) / fps, t1: (t2f(r.start) / fps) + r.dur / 1000 }));
      const slides = (view && view.segs ? view.segs : []).map((s) => ({
        i: Number(String(s.seg).slice(1)) - 1, presence_ratio: s.present, front_ratio: s.gaze,
        down_sec: s.down !== null && s.down !== undefined ? s.down * s.present * s.dur / 1000 : null,
        gesture_ratio: s.gesture, lookaway_n: s.lookaway,
      }));
      return {
        rows: out, summary: { slides, lookaways, engine: view ? view.summary : null },
        // 엔진 줄 그대로(장 표시 · 프레임 번호 포함) — logic 만 바꿨을 때 브라우저 없이 다시 채점하려고 (etc/labs/behavior_cv/replay_logic.mjs)
        engine_rows: rows,
        engine_view: view ? { status: view.status, why: view.why, metrics: view.metrics, quality: view.quality, device: view.device } : null,
        adapter_note: `줄 ${out.length} · 바코드 못 풂 ${nClock} · 흔들림 창 ${sw.length}(켜짐 ${sw.filter((w) => w.on).length})`,
      };
    },
  };
})(window);
