/**
 * 부스 「사람 그래프」 스캔 화면(/booth/scan) — 캔버스에 그리기만 한다 (2026-10-12).
 *
 * 무엇을 어디에 그릴지는 js/booth_scan_logic.js · js/booth_scan.js 가 정한다. 여기는 이미 화면 픽셀로 바뀐 점을 받아
 * 개념 그래프(graph3d)와 같은 말투 — 둥근 노드 + 가는 선 + 선을 따라 흐르는 빛 — 로 칠한다.
 * 색은 앱 토큰(css/app.css :root)의 어두운 면 위 강조(--cyan #3fd599 · --mint #aeefd5)와 브랜드(--brand #0E8850).
 * 전역은 window.BoothScanDraw 하나.
 */
(function (root) {
  'use strict';

  const C = {
    edge: [63, 213, 153],      // --cyan
    node: [174, 239, 213],     // --mint
    brand: [14, 136, 80],      // --brand
    iris: [236, 255, 247],
  };
  const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${Math.max(0, Math.min(1, a)).toFixed(3)})`;

  function clear(ctx, W, H) {
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, W, H);
  }

  /**
   * 아무도 없을 때 떠다니는 점 — 가까운 점끼리 옅은 선(그래프 냄새만). particles 는 화면 비율 좌표(0~1).
   * u = 기기 픽셀 비율(dpr). alpha 0 이면 아무것도 안 그린다.
   */
  function idle(ctx, particles, W, H, alpha, u) {
    if (!(alpha > 0.01)) return;
    const reach = 0.14 * Math.min(W, H), reach2 = reach * reach;
    const pts = particles.map((p) => [p.x * W, p.y * H, p.r]);
    ctx.lineWidth = 1 * u;
    for (let i = 0; i < pts.length; i += 1) {
      for (let j = i + 1; j < pts.length; j += 1) {
        const dx = pts[i][0] - pts[j][0], dy = pts[i][1] - pts[j][1], d2 = dx * dx + dy * dy;
        if (d2 > reach2) continue;
        ctx.strokeStyle = rgba(C.edge, alpha * 0.22 * (1 - d2 / reach2));
        ctx.beginPath(); ctx.moveTo(pts[i][0], pts[i][1]); ctx.lineTo(pts[j][0], pts[j][1]); ctx.stroke();
      }
    }
    pts.forEach(([x, y, r]) => {
      ctx.fillStyle = rgba(C.edge, alpha * 0.18);
      ctx.beginPath(); ctx.arc(x, y, r * 3 * u, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = rgba(C.node, alpha * 0.75);
      ctx.beginPath(); ctx.arc(x, y, r * u, 0, Math.PI * 2); ctx.fill();
    });
  }

  /**
   * 사람 하나. view = { pos:[[x,y]|null], alpha:[0~1], link:[0~1], scale } — 화면 픽셀(기기 픽셀).
   * link 는 선만 따로 옅게 — 모이는 중에는 점이 먼저 날아오고 선은 자리 잡을수록 진해진다(날아오는 선이 화면을 가로질러 엉키지 않게).
   * glow = { gaze:0~1, head, shoulder, hand, voice } — 「읽는 것」 이 켜진 무리는 노드가 커지고 선이 밝아진다.
   */
  function person(ctx, graph, view, glow, u) {
    const s = (view.scale || 1) * u;
    const lv = (n) => (glow && glow[n.group]) || 0;
    ctx.lineCap = 'round';
    graph.edges.forEach(([a, b]) => {
      const pa = view.pos[a], pb = view.pos[b];
      if (!pa || !pb) return;
      const lk = view.link ? Math.min(view.link[a], view.link[b]) : 1;
      const al = Math.min(view.alpha[a], view.alpha[b]) * lk;
      if (al <= 0.01) return;
      const g = Math.max(lv(graph.nodes[a]), lv(graph.nodes[b]));
      ctx.strokeStyle = rgba(C.edge, al * (0.42 + 0.4 * g));
      ctx.lineWidth = (1.1 + 0.9 * g) * s;
      ctx.beginPath(); ctx.moveTo(pa[0], pa[1]); ctx.lineTo(pb[0], pb[1]); ctx.stroke();
    });
    graph.nodes.forEach((n, i) => {
      const p = view.pos[i], al = view.alpha[i];
      if (!p || al <= 0.01) return;
      const g = lv(n);
      if (n.kind === 'iris') return irisDot(ctx, p, al, g, s);
      const r = (2.4 + 0.7 * g) * s;
      ctx.fillStyle = rgba(C.edge, al * (0.14 + 0.22 * g));
      ctx.beginPath(); ctx.arc(p[0], p[1], r * (2 + 0.5 * g), 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = rgba(C.brand, al * 0.9);
      ctx.beginPath(); ctx.arc(p[0], p[1], r + 1.1 * s, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = rgba(C.node, al);
      ctx.beginPath(); ctx.arc(p[0], p[1], r, 0, Math.PI * 2); ctx.fill();
    });
  }

  /** 홍채 — 제일 밝은 점. 시선 방향이 바뀌면 고리가 한 번 더 번진다 */
  function irisDot(ctx, p, al, g, s) {
    ctx.fillStyle = rgba(C.edge, al * (0.28 + 0.3 * g));
    ctx.beginPath(); ctx.arc(p[0], p[1], (6.5 + 3 * g) * s, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = rgba(C.iris, al * (0.5 + 0.4 * g));
    ctx.lineWidth = 1.2 * s;
    ctx.beginPath(); ctx.arc(p[0], p[1], (4.6 + 2 * g) * s, 0, Math.PI * 2); ctx.stroke();
    ctx.fillStyle = rgba(C.iris, al);
    ctx.beginPath(); ctx.arc(p[0], p[1], 2.8 * s, 0, Math.PI * 2); ctx.fill();
  }

  /** 선을 따라 흐르는 빛 — 「지금 읽는 중」. pulses: [{edge, t0, dur, rev}] */
  function pulses(ctx, graph, view, list, nowMs, u) {
    const s = (view.scale || 1) * u;
    const prev = ctx.globalCompositeOperation;
    ctx.globalCompositeOperation = 'lighter';
    list.forEach((pl) => {
      const [a0, b0] = graph.edges[pl.edge] || [];
      const a = pl.rev ? b0 : a0, b = pl.rev ? a0 : b0;
      const pa = view.pos[a], pb = view.pos[b];
      if (!pa || !pb) return;
      const al = Math.min(view.alpha[a], view.alpha[b]) * (view.link ? Math.min(view.link[a], view.link[b]) : 1);
      const t = (nowMs - pl.t0) / pl.dur;
      if (t < 0 || t > 1 || al <= 0.01) return;
      const fade = Math.sin(Math.PI * t);
      const x = pa[0] + (pb[0] - pa[0]) * t, y = pa[1] + (pb[1] - pa[1]) * t;
      const tt = Math.max(0, t - 0.22);
      const tx = pa[0] + (pb[0] - pa[0]) * tt, ty = pa[1] + (pb[1] - pa[1]) * tt;
      ctx.strokeStyle = rgba(C.node, al * fade * 0.55);
      ctx.lineWidth = 1.8 * s;
      ctx.beginPath(); ctx.moveTo(tx, ty); ctx.lineTo(x, y); ctx.stroke();
      ctx.fillStyle = rgba(C.edge, al * fade * 0.4);
      ctx.beginPath(); ctx.arc(x, y, 7 * s, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = rgba(C.iris, al * fade);
      ctx.beginPath(); ctx.arc(x, y, 2.4 * s, 0, Math.PI * 2); ctx.fill();
    });
    ctx.globalCompositeOperation = prev;
  }

  root.BoothScanDraw = { clear, idle, person, pulses, COLORS: C };
})(typeof window !== 'undefined' ? window : globalThis);
