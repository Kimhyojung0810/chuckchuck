/**
 * 행동 실험실 탭(LabTap) — 엔진을 고치지 않고 「엔진이 본 프레임이 영상의 몇 번째 프레임인가」 를 알아낸다.
 * browser_adapter.py 가 page.add_init_script 로 **페이지 스크립트보다 먼저** 심는다.
 *
 * 1) Worker 감싸기: 엔진이 워커로 보내는 { type:'frame', w, h, data:RGBA, id, t } 를 보내기 직전에 읽어
 *    오른쪽 위 프레임 번호 바코드(gen.py barcode)를 풀고, 워커가 돌려준 { type:'row', id, row } 와 id 로 잇는다.
 *    → LabTap.joined() = [{ id, frame, t, perfSent, perfRow, row }]
 * 2) 시계: 실험 화면의 <video> 에 requestVideoFrameCallback 을 걸어 지금 보이는 프레임 번호를 계속 푼다.
 *    → LabTap.cur = { frame, perf } · LabTap.frameOfPerf(perfMs) (워커를 안 쓰는 엔진용 예비 시계)
 * 영상은 어디로도 보내지 않는다 — 탭은 바코드 20칸만 읽는다.
 */
(function (root) {
  'use strict';
  const BITS = 16;
  const tap = {
    videoW: 640,           // harness 가 실제 영상 폭으로 고친다 — 바코드 칸 크기 = max(4, W/160)
    sent: new Map(),       // id → { frame, t, perfSent, w, h }
    rows: [],              // { id, row, perfRow }
    other: [],             // 워커가 보낸 다른 메시지 종류 (ready · failed …) — 진단용
    samples: [],           // [perf, frame] — 시계
    cur: null,
    badBar: 0,
  };

  /** RGBA 버퍼(폭 w)에서 바코드를 푼다. 실패하면 -1 */
  function decode(px, w, h, srcW) {
    const W = srcW || tap.videoW;
    const cs = Math.max(4, Math.floor(W / 160)) * (w / W);   // 이 버퍼 안의 칸 폭(px)
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
    if (par % 2 !== bits[2 + BITS]) return -1;
    return v;
  }

  // ── 1) Worker 감싸기 ──
  const W0 = root.Worker;
  if (typeof W0 === 'function') {
    class TapWorker extends W0 {
      constructor(url, opts) {
        super(url, opts);
        this.addEventListener('message', (e) => {
          const m = e.data || {};
          if (m.type === 'row') tap.rows.push({ id: m.id, row: m.row || null, error: m.error || null, perfRow: performance.now() });
          else tap.other.push({ type: m.type, error: m.error, info: m.info, perf: performance.now() });
        });
      }
      postMessage(msg, transfer) {
        try {
          if (msg && msg.type === 'frame' && msg.data && msg.w && msg.h) {
            const px = new Uint8ClampedArray(msg.data);
            const f = decode(px, msg.w, msg.h);
            if (f < 0) tap.badBar += 1;
            tap.sent.set(msg.id, { frame: f, t: msg.t, perfSent: performance.now(), w: msg.w, h: msg.h });
          }
        } catch (err) { /* 탭이 엔진을 깨면 안 된다 */ }
        return super.postMessage(msg, transfer);
      }
    }
    root.Worker = TapWorker;
  }

  // ── 2) 시계 ──
  function watch(video) {
    const c = document.createElement('canvas');
    const ctx = c.getContext('2d', { willReadFrequently: true });
    const step = () => {
      try {
        const vw = video.videoWidth; const vh = video.videoHeight;
        if (vw) {
          tap.videoW = vw;
          const cs = Math.max(4, Math.floor(vw / 160));
          const bw = cs * (BITS + 4); const bh = cs + 2;
          if (c.width !== bw || c.height !== bh) { c.width = bw; c.height = bh; }
          ctx.drawImage(video, vw - bw, 0, bw, bh, 0, 0, bw, bh);
          const px = ctx.getImageData(0, 0, bw, bh).data;
          const f2 = decodeCrop(px, bw, bh, cs);
          if (f2 >= 0) {
            const now = performance.now();
            tap.cur = { frame: f2, perf: now };
            tap.samples.push([now, f2]);
            if (tap.samples.length > 20000) tap.samples.splice(0, 5000);
          }
        }
      } catch (err) { /* 다음 프레임에 */ }
      if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(step);
      else setTimeout(step, 20);
    };
    if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(step); else setTimeout(step, 20);
  }

  /** 잘라 낸 바코드 조각(칸 폭 cs px)에서 풀기 */
  function decodeCrop(px, w, h, cs) {
    const n = BITS + 4;
    const y = Math.floor(cs * 0.5);
    const bits = [];
    for (let k = 0; k < n; k += 1) {
      const x = Math.floor((k + 0.5) * cs);
      const i = (y * w + x) * 4;
      bits.push((px[i] + px[i + 1] + px[i + 2]) / 3 > 127 ? 1 : 0);
    }
    if (bits[0] !== 1 || bits[1] !== 0 || bits[n - 1] !== 1) return -1;
    let v = 0; let par = 0;
    for (let k = 0; k < BITS; k += 1) { v = (v << 1) | bits[2 + k]; par += bits[2 + k]; }
    return par % 2 === bits[2 + BITS] ? v : -1;
  }

  /** performance.now() → 그때 화면에 있던 프레임 (시계 표본 사이를 잇는다) */
  function frameOfPerf(p, after = 0) {
    const s = tap.samples.filter((x) => x[0] >= after);
    if (!s.length) return -1;
    let best = s[0];
    for (const x of s) { if (x[0] <= p) best = x; else break; }
    return best[1];
  }

  function joined(sinceId = 0) {
    return tap.rows.filter((r) => r.id > sinceId).map((r) => {
      const s = tap.sent.get(r.id) || {};
      return { id: r.id, frame: s.frame, t: s.t, perfSent: s.perfSent, perfRow: r.perfRow, row: r.row, error: r.error };
    });
  }

  root.LabTap = Object.assign(tap, { decode, watch, frameOfPerf, joined });
})(typeof window !== 'undefined' ? window : globalThis);
