/**
 * 엔진 줄(engine_rows) → 채점기 예측 모양 — web/adapter_default.js stop() 과 같은 변환. replay_logic.mjs · node_engine.mjs 가 같이 쓴다.
 * L = BehaviorCvLogic, rows = 엔진 줄(seg · _frame 포함), fps = 영상 fps(정답)
 */
export function predsFromRows(L, rows, fps) {
  const seq = L.states(rows);
  const gflags = L.gestureFlags(seq);
  const sw = L.swayWindows(seq);
  const out = seq.map((x, i) => {
    const inOn = sw.filter((w) => w.on && x.t >= w.start && x.t < w.end);
    const any = sw.filter((w) => x.t >= w.start && x.t < w.end);
    return {
      frame: x.row._frame, orient: x.state, orient_raw: x.raw, present: x.present,
      sway: { active: inOn.length > 0, amp_fw: any.length ? Math.max(...any.map((w) => w.amp)) : null, freq: (inOn[0] || any[0] || {}).freq ?? null },
      gesture: gflags[i] === true, motion: Number.isFinite(x.row.meb) ? x.row.meb : (Number.isFinite(x.row.body) ? x.row.body : null), ms: x.row.ms,
      raw: { src: x.row.src, box: x.row.box, gs: x.row.gs },
    };
  });
  const t2f = (t) => { let best = seq[0]; for (const x of seq) { if (x.t <= t) best = x; else break; } return best ? best.row._frame : 0; };
  const m = L.measure(seq);
  const lookaways = m.look.map((r) => ({ t0: t2f(r.start) / fps, t1: (t2f(r.start) / fps) + r.dur / 1000 }));
  const view = L.analyze(rows);
  const slides = (view.segs || []).map((s) => ({
    i: Number(String(s.seg).slice(1)) - 1, presence_ratio: s.present, front_ratio: s.gaze,
    down_sec: s.down !== null && s.down !== undefined ? s.down * s.present * s.dur / 1000 : null, gesture_ratio: s.gesture, lookaway_n: s.lookaway,
  }));
  return { rows: out, summary: { slides, lookaways, engine: L.summaryOf ? L.summaryOf(view) : null } };
}
