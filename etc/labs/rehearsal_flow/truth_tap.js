/**
 * 리포트 문장 검증 탭 (바퀴 5) — 실 흐름(/rehearsal)에서 카메라 엔진이 본 줄마다 「정답 영상의 몇 번째 프레임이었나」 를 붙여 남긴다.
 * run.py --init-js 로 페이지 스크립트보다 먼저 심는다. 엔진 · 리포트 코드는 건드리지 않는다.
 *
 * 1) Worker 감싸기 — 엔진이 워커로 보내는 { type:'frame', data:RGBA, id } 의 오른쪽 위 바코드(behavior_cv/gen.py)를 풀어 두고,
 *    워커가 돌려준 { type:'row', id, row } 에 row.__f = 프레임 번호를 붙인다(엔진의 onRow 보다 먼저 듣는다 — 같은 event.data).
 * 2) BehaviorCvLogic.analyze 감싸기 — 기록을 닫을 때 넘어온 줄(장면 표시 seg · 말소리 sp 포함)을 localStorage 'lab:truth-rows:<phase>' 에.
 *    run.py --storage-out 이 저장소째 남기므로, 리포트 문장 검증(report_truth.mjs)이 같은 줄로 logic 을 다시 돌려 볼 수 있다.
 * 바코드: [1,0] + 16비트 + 짝수 패리티 + 1, 칸 폭 = max(4, W/160) px (behavior_cv/web/labtap.js 와 같은 풀이).
 */
(function (root) {
  'use strict';
  const BITS = 16;
  const sent = new Map();
  let srcW = 640;
  try { const w = Number(root.localStorage.getItem('lab:truth-srcw')); if (w > 0) srcW = w; } catch (_) { /* 기본 640 */ }

  function decode(px, w, h) {
    const cs = Math.max(4, Math.floor(srcW / 160)) * (w / srcW);
    const n = BITS + 4;
    const x0 = w - cs * n;
    const y = Math.max(0, Math.min(h - 1, Math.floor(cs * 0.5)));
    const bits = [];
    for (let k = 0; k < n; k += 1) {
      const x = Math.min(w - 1, Math.max(0, Math.floor(x0 + (k + 0.5) * cs)));
      const i = (y * w + x) * 4;
      bits.push((px[i] + px[i + 1] + px[i + 2]) / 3 > 127 ? 1 : 0);
    }
    if (bits[0] !== 1 || bits[1] !== 0 || bits[n - 1] !== 1) return -1;
    let v = 0; let par = 0;
    for (let k = 0; k < BITS; k += 1) { v = (v << 1) | bits[2 + k]; par += bits[2 + k]; }
    return par % 2 === bits[2 + BITS] ? v : -1;
  }

  const W0 = root.Worker;
  if (typeof W0 === 'function') {
    class TruthWorker extends W0 {
      constructor(url, opts) {
        super(url, opts);
        this.addEventListener('message', (e) => {
          const m = e.data || {};
          if (m.type === 'row' && m.row && sent.has(m.id)) { m.row.__f = sent.get(m.id); sent.delete(m.id); }
        });
      }
      postMessage(msg, transfer) {
        try {
          if (msg && msg.type === 'frame' && msg.data && msg.w && msg.h) sent.set(msg.id, decode(new Uint8ClampedArray(msg.data), msg.w, msg.h));
        } catch (_) { /* 탭이 엔진을 깨면 안 된다 */ }
        return super.postMessage(msg, transfer);
      }
    }
    root.Worker = TruthWorker;
  }

  let logic = null;
  Object.defineProperty(root, 'BehaviorCvLogic', {
    configurable: true,
    get() { return logic; },
    set(v) {
      if (v && typeof v.analyze === 'function' && !v.__truth) {
        const real = v.analyze;
        v.analyze = function (rows, opts) {
          try {
            const phase = opts && opts.phase === 'qa' ? 'qa' : 'present';
            root.localStorage.setItem(`lab:truth-rows:${phase}`, JSON.stringify(rows || []));
          } catch (_) { /* 저장소가 넘치면 이번만 */ }
          return real.apply(this, arguments);
        };
        v.__truth = true;
      }
      logic = v;
    },
  });
})(window);
