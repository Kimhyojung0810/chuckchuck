/**
 * 부스 「사람 그래프」 스캔 화면(/booth/scan) — 화면 없이 도는 순수 함수 (2026-10-12, ~/meetings/2026-10-12_부스_사람그래프_스캔화면.md).
 *
 * 지나가는 사람이 자기 모습이 점·선 그래프로 읽히는 것을 보는 연출 화면이다. 점수·리포트·발표 흐름에는 아무것도 넘기지 않는다.
 * 이 파일이 맡는 것: 어느 점을 고르나(성긴 60~70점) · 영상 좌표 → 화면 좌표(거울 + cover 잘림) · 떨림 거르기(One-Euro) ·
 * 사람 짝짓기(얼굴 ↔ 몸, 프레임 사이 같은 사람) · 모이기/흩어지기 시간 · 「읽는 것」 다섯 줄이 «바뀌었을 때만» 켜지는 판단.
 * 브라우저에서만 틀리는 판단을 여기로 빼 두고 tests/js/booth_scan.smoke.mjs 가 node 로 잡는다(vm 으로 이 파일 그대로 올린다).
 *
 * 지킬 것 — 감정·자신감 추정 없음. 시선은 «방향이 바뀌었는가» 만 본다(어디를 보는지 자리로 나누지 않는다). 숫자·점수를 화면에 내지 않는다.
 * 전역은 window.BoothScanLogic 하나. js/booth_scan.js · js/booth_scan_draw.js 가 쓴다.
 */
(function (root) {
  'use strict';

  // ── 고르는 점 — MediaPipe FaceLandmarker 478점 · PoseLandmarker 33점의 번호 ─────────────────────────
  /** 얼굴 부위 — 고리(loop)는 끝과 처음을 잇는다. 번호는 MediaPipe 얼굴 그물 표준 번호 (사람 기준 오른쪽 = 영상 왼쪽) */
  const FACE_PARTS = [
    { name: 'oval', group: 'head', loop: true,
      idx: [10, 297, 284, 389, 454, 361, 397, 379, 400, 152, 176, 150, 172, 132, 234, 162, 54, 67] },
    { name: 'eyeR', group: 'gaze', loop: true, idx: [33, 160, 158, 133, 153, 144] },
    { name: 'eyeL', group: 'gaze', loop: true, idx: [263, 387, 385, 362, 380, 373] },
    { name: 'browR', group: 'gaze', loop: false, idx: [70, 63, 105, 66, 107] },
    { name: 'browL', group: 'gaze', loop: false, idx: [300, 293, 334, 296, 336] },
    // 입술은 8점만 — 12점이면 「목소리·쉼」 이 켜져 노드가 커질 때 입이 한 덩어리 빛으로 뭉친다 (10-12 헤드리스 사진)
    { name: 'lips', group: 'voice', loop: true, idx: [61, 40, 0, 270, 291, 321, 17, 91] },
  ];
  /** 홍채 가운데 두 점 — 밝은 점으로 따로 그린다 */
  const IRIS = [{ idx: 468, group: 'gaze' }, { idx: 473, group: 'gaze' }];
  /** 코 — 콧등 사슬 + 콧방울 */
  const NOSE = { group: 'head', idx: [168, 6, 195, 4, 98, 327, 2],
    edges: [[168, 6], [6, 195], [195, 4], [4, 98], [4, 327], [98, 2], [327, 2]] };
  /** 부위끼리 잇는 선 — 윤곽만 있으면 가면처럼 보여서, 마디를 이어 «그래프» 로 읽히게 */
  const FACE_LINKS = [
    [107, 168], [336, 168], [133, 168], [362, 168], [33, 234], [263, 454], [70, 162], [300, 389],
    [2, 0], [61, 172], [291, 397], [17, 152],
  ];
  /** 몸 — 어깨 · 팔꿈치 · 손목. 0(코)은 얼굴과 짝지을 때만 쓴다 */
  const POSE_PARTS = [
    { idx: 11, group: 'shoulder' }, { idx: 12, group: 'shoulder' },
    { idx: 13, group: 'hand' }, { idx: 14, group: 'hand' }, { idx: 15, group: 'hand' }, { idx: 16, group: 'hand' },
  ];
  const POSE_LINKS = [[11, 13], [13, 15], [12, 14], [14, 16]];
  /** 신호 계산에만 쓰는 얼굴 점 — 눈꺼풀 위아래 · 코끝 */
  const FACE_EXTRA = [159, 145, 386, 374, 1];

  /** 워커가 돌려줄 얼굴 점 번호(이 순서로 x,y 를 한 줄에) · 몸 점 번호(x,y,visibility) */
  const PICK_FACE = (() => {
    const s = new Set();
    FACE_PARTS.forEach((p) => p.idx.forEach((i) => s.add(i)));
    IRIS.forEach((p) => s.add(p.idx));
    NOSE.idx.forEach((i) => s.add(i));
    FACE_EXTRA.forEach((i) => s.add(i));
    return Array.from(s);
  })();
  const PICK_POSE = [0, 11, 12, 13, 14, 15, 16];
  const FACE_AT = new Map(PICK_FACE.map((idx, k) => [idx, k]));
  const POSE_AT = new Map(PICK_POSE.map((idx, k) => [idx, k]));

  /** 몸 점을 믿는 visibility 하한 — 화면 밖 팔꿈치·손목은 MediaPipe 가 낮게 준다 */
  const POSE_VIS_MIN = 0.5;
  /** 얼굴 코끝 ↔ 몸 코가 이 거리(영상 짧은 변 기준) 안이면 같은 사람 */
  const PAIR_MAX = 0.12;
  /** 프레임 사이 같은 사람으로 보는 코끝 이동 상한 (짧은 변 기준) */
  const TRACK_MAX = 0.18;
  /** 보이는 사람 상한 — 모델의 numFaces · numPoses 와 같다 */
  const MAX_PEOPLE = 3;

  // ── 그래프(노드 · 선) ─────────────────────────────────────────────────────────────────────
  /**
   * 그릴 노드 목록과 선. 노드 하나 = { key, src:'face'|'pose'|'neck', idx, group, kind:'node'|'iris' }.
   * 목(neck)은 두 어깨의 가운데 — 턱과 어깨를 이어 머리와 몸이 한 그래프가 되게.
   */
  function buildGraph() {
    const nodes = [];
    const at = new Map();
    const add = (src, idx, group, kind) => {
      const key = `${src}:${idx}`;
      if (at.has(key)) return at.get(key);
      at.set(key, nodes.length);
      nodes.push({ key, src, idx, group, kind: kind || 'node' });
      return nodes.length - 1;
    };
    const edges = [];
    const link = (a, b) => { if (a !== b) edges.push([a, b]); };
    FACE_PARTS.forEach((p) => {
      const ids = p.idx.map((i) => add('face', i, p.group));
      for (let k = 0; k + 1 < ids.length; k += 1) link(ids[k], ids[k + 1]);
      if (p.loop) link(ids[ids.length - 1], ids[0]);
    });
    NOSE.idx.forEach((i) => add('face', i, NOSE.group));
    NOSE.edges.forEach(([a, b]) => link(at.get(`face:${a}`), at.get(`face:${b}`)));
    FACE_LINKS.forEach(([a, b]) => link(at.get(`face:${a}`), at.get(`face:${b}`)));
    IRIS.forEach((p) => add('face', p.idx, p.group, 'iris'));
    POSE_PARTS.forEach((p) => add('pose', p.idx, p.group));
    const neck = add('neck', 0, 'shoulder');
    POSE_LINKS.forEach(([a, b]) => link(at.get(`pose:${a}`), at.get(`pose:${b}`)));
    link(at.get('face:152'), neck);
    link(neck, at.get('pose:11'));
    link(neck, at.get('pose:12'));
    return { nodes, edges };
  }

  // ── 영상 좌표 → 화면 좌표 ─────────────────────────────────────────────────────────────────
  /**
   * object-fit: cover 로 가운데 맞춰 깔린 영상 + 좌우 거울(scaleX(-1)).
   * 영상(vw×vh)의 정규 좌표(0~1) → 화면(W×H) 픽셀. 넘친 쪽은 양옆(또는 위아래)이 똑같이 잘린다.
   * eval_lab_draw.js 는 contain 을 가정한다 — 거기 식을 그대로 가져오면 넓은 화면에서 점이 얼굴 옆으로 밀린다.
   */
  function coverMap(vw, vh, W, H, mirror) {
    const ok = vw > 0 && vh > 0 && W > 0 && H > 0;
    const s = ok ? Math.max(W / vw, H / vh) : 1;
    const dw = vw * s, dh = vh * s;
    const ox = (W - dw) / 2, oy = (H - dh) / 2;
    const flip = mirror !== false;
    return {
      s, ox, oy, dw, dh,
      x: (nx) => { const X = ox + nx * dw; return flip ? W - X : X; },
      y: (ny) => oy + ny * dh,
    };
  }

  // ── 떨림 거르기 (One-Euro, Casiez 2012) ────────────────────────────────────────────────────
  function lowpassAlpha(cutoff, dt) {
    const tau = 1 / (2 * Math.PI * cutoff);
    return 1 / (1 + tau / dt);
  }
  /**
   * 값 하나의 One-Euro 거르개. 정규 좌표(0~1) 기준 기본값 — 가만히 있으면 1.5Hz 로 떨림을 누르고,
   * 빨리 움직이면(초당 화면 하나) 컷오프가 ~8Hz 로 올라 늦지 않게.
   */
  function makeOneEuro(opts) {
    const o = opts || {};
    const minCutoff = o.minCutoff != null ? o.minCutoff : 1.5;
    const beta = o.beta != null ? o.beta : 6;
    const dCutoff = o.dCutoff != null ? o.dCutoff : 1;
    let x = null, dx = 0, lastT = null;
    return {
      filter(value, tMs) {
        if (x === null || lastT === null || !(tMs > lastT)) {
          x = value; lastT = tMs; dx = 0;
          return x;
        }
        const dt = Math.min(1, (tMs - lastT) / 1000);
        lastT = tMs;
        const rawD = (value - x) / dt;
        dx += lowpassAlpha(dCutoff, dt) * (rawD - dx);
        const cutoff = minCutoff + beta * Math.abs(dx);
        x += lowpassAlpha(cutoff, dt) * (value - x);
        return x;
      },
      reset() { x = null; dx = 0; lastT = null; },
    };
  }

  /** 화면에 그릴 때 추론 사이(10~15fps)를 메우는 지수 따라가기 — rate 는 초당 비율, 프레임 길이와 무관하게 같은 빠르기 */
  function follow(cur, target, dtSec, rate) {
    const k = 1 - Math.exp(-(rate || 18) * Math.max(0, dtSec));
    return cur + (target - cur) * k;
  }

  // ── 사람 짝짓기 ───────────────────────────────────────────────────────────────────────────
  /** 워커가 준 한 줄(Float32Array) 에서 MediaPipe 번호의 점 — 없으면 null */
  function facePt(arr, idx) {
    const k = FACE_AT.get(idx);
    if (!arr || k === undefined || arr.length < 2 * k + 2) return null;
    return [arr[2 * k], arr[2 * k + 1]];
  }
  function posePt(arr, idx, visMin) {
    const k = POSE_AT.get(idx);
    if (!arr || k === undefined || arr.length < 3 * k + 3) return null;
    const vis = arr[3 * k + 2];
    if (visMin != null && !(vis >= visMin)) return null;
    return [arr[3 * k], arr[3 * k + 1]];
  }
  /** 영상 짧은 변 기준 거리 — 정규 좌표는 x·y 의 길이가 달라서(16:9) 가로에 aspect 를 곱한다 */
  function dist(a, b, aspect) {
    const dx = (a[0] - b[0]) * (aspect || 1), dy = a[1] - b[1];
    return Math.sqrt(dx * dx + dy * dy);
  }

  /** 거리표에서 가까운 짝부터 하나씩 — 사람이 셋 이하라 헝가리안까지 갈 일이 없다 */
  function greedyPairs(n, m, cost, maxCost) {
    const cand = [];
    for (let i = 0; i < n; i += 1) for (let j = 0; j < m; j += 1) {
      const c = cost(i, j);
      if (c <= maxCost) cand.push([c, i, j]);
    }
    cand.sort((a, b) => a[0] - b[0]);
    const usedI = new Set(), usedJ = new Set(), pairs = [];
    cand.forEach(([, i, j]) => {
      if (usedI.has(i) || usedJ.has(j)) return;
      usedI.add(i); usedJ.add(j); pairs.push([i, j]);
    });
    return pairs;
  }

  /**
   * 얼굴 목록 + 몸 목록 → 사람 목록 [{face, pose|null, center}]. 얼굴이 있는 사람만 (몸만 잡힌 것은 그래프의 머리가 없어 버린다).
   * 짝은 얼굴 코끝(1)과 몸 코(0)의 거리로. 많으면 큰 얼굴(가까운 사람)부터 MAX_PEOPLE 명.
   */
  function pairPeople(faces, poses, aspect) {
    const F = (faces || []).filter((f) => facePt(f, 1));
    const P = (poses || []).filter((p) => posePt(p, 0));
    const pairs = greedyPairs(F.length, P.length, (i, j) => dist(facePt(F[i], 1), posePt(P[j], 0), aspect), PAIR_MAX);
    const poseOf = new Map(pairs.map(([i, j]) => [i, P[j]]));
    const people = F.map((face, i) => ({ face, pose: poseOf.get(i) || null, center: facePt(face, 1), size: faceSize(face, aspect) }));
    people.sort((a, b) => b.size - a.size);
    return people.slice(0, MAX_PEOPLE);
  }
  function faceSize(face, aspect) {
    const a = facePt(face, 234), b = facePt(face, 454);
    return a && b ? dist(a, b, aspect) : 0;
  }

  /**
   * 지난 사람들(tracks: [{id, center}]) 과 이번 사람들(people) 을 잇는다 — 코끝이 TRACK_MAX 안이면 같은 사람.
   * 돌려줌: { matched: [[trackIndex, personIndex]], fresh: [personIndex], missing: [trackIndex] }
   */
  function matchTracks(tracks, people, aspect) {
    const T = tracks || [], P = people || [];
    const matched = greedyPairs(T.length, P.length, (i, j) => dist(T[i].center, P[j].center, aspect), TRACK_MAX);
    const ti = new Set(matched.map((m) => m[0])), pj = new Set(matched.map((m) => m[1]));
    return {
      matched,
      fresh: P.map((_, j) => j).filter((j) => !pj.has(j)),
      missing: T.map((_, i) => i).filter((i) => !ti.has(i)),
    };
  }

  /**
   * 그래프 노드마다 이번 프레임의 정규 좌표 — 못 믿는 점(몸이 없거나 visibility 가 낮은 팔)은 null.
   * 목은 두 어깨가 다 보일 때만.
   */
  function nodeTargets(graph, person) {
    const out = new Array(graph.nodes.length).fill(null);
    graph.nodes.forEach((n, i) => {
      if (n.src === 'face') out[i] = facePt(person.face, n.idx);
      else if (n.src === 'pose') out[i] = person.pose ? posePt(person.pose, n.idx, POSE_VIS_MIN) : null;
    });
    graph.nodes.forEach((n, i) => {
      if (n.src !== 'neck' || !person.pose) return;
      const a = posePt(person.pose, 11, POSE_VIS_MIN), b = posePt(person.pose, 12, POSE_VIS_MIN);
      if (a && b) out[i] = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    });
    return out;
  }

  // ── 모이기 · 따라가기 · 흩어지기 ─────────────────────────────────────────────────────────────
  const ASSEMBLE_MS = 1100;
  /** 노드마다 조금씩 늦게 출발 — 한꺼번에 날아오면 덩어리로 보인다 */
  const STAGGER_MS = 6;
  /**
   * 놓친 것으로 보는 때 — 추론 결과가 MISS_MAX 번 연달아 이 사람 없이 왔고, 마지막으로 본 지 LOST_GRACE_MS 가 지났을 때 둘 다.
   * 시간만 보면 약한 노트북(추론 2fps)에서 결과와 결과 사이에 흩어졌다 다시 모여 깜빡인다. 결과가 아예 안 오면(워커 멈춤) 그대로 둔다.
   */
  const LOST_GRACE_MS = 450;
  const MISS_MAX = 2;
  const SCATTER_MS = 950;

  /** 사람 하나의 단계 — born(처음 본 시각) · lastSeen · missed(연달아 못 본 결과 수) · lostAt(흩어지기 시작, 없으면 null) */
  function phaseOf(track, now) {
    if (track.lostAt != null) return now - track.lostAt >= SCATTER_MS ? 'gone' : 'scatter';
    if ((track.missed || 0) >= MISS_MAX && now - track.lastSeen > LOST_GRACE_MS) return 'lost';
    return now - track.born < ASSEMBLE_MS ? 'assemble' : 'track';
  }

  const easeOutCubic = (t) => 1 - Math.pow(1 - Math.min(1, Math.max(0, t)), 3);
  /** 모이는 중인 노드 i 의 진행(0~1) — 노드마다 STAGGER 만큼 늦게 출발해서 같은 시각(ASSEMBLE_MS)에 도착 */
  function assembleProgress(elapsedMs, i, count) {
    const lead = STAGGER_MS * Math.max(0, count - 1);
    const span = Math.max(1, ASSEMBLE_MS - lead);
    return easeOutCubic((elapsedMs - STAGGER_MS * i) / span);
  }
  function lerp2(a, b, t) { return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]; }

  /** 흩어지는 노드 — 무게중심에서 바깥으로 날아가며 옅어진다. 돌려줌 {pos, alpha} */
  function scatterAt(from, vel, elapsedMs) {
    const t = Math.max(0, elapsedMs) / 1000;
    const drag = 1 - Math.exp(-2.2 * t);  // 처음엔 빠르고 점점 느려진다
    const k = drag / 2.2;
    return {
      pos: [from[0] + vel[0] * k, from[1] + vel[1] * k],
      alpha: Math.max(0, 1 - elapsedMs / SCATTER_MS),
    };
  }
  /** 흩어질 때 노드마다 바깥 방향 속도(px/s) — rng 를 받아 시험에서 같은 값이 나오게 */
  function scatterVelocities(points, rng) {
    const live = points.filter(Boolean);
    const c = live.length ? live.reduce((s, p) => [s[0] + p[0] / live.length, s[1] + p[1] / live.length], [0, 0]) : [0, 0];
    return points.map((p) => {
      if (!p) return [0, 0];
      let dx = p[0] - c[0], dy = p[1] - c[1];
      const d = Math.hypot(dx, dy) || 1;
      dx /= d; dy /= d;
      const speed = 140 + rng() * 260, wob = (rng() - 0.5) * 0.9;
      return [(dx + wob * -dy) * speed, (dy + wob * dx) * speed];
    });
  }

  // ── 떠다니는 점 (아무도 없을 때) ──────────────────────────────────────────────────────────────
  /** 시험에서 같은 값이 나오는 난수 (mulberry32) */
  function rng32(seed) {
    let a = (seed >>> 0) || 1;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  /** 화면 비율 좌표(0~1)의 점들 — 느린 흐름 + 저마다 다른 흔들림 */
  function makeParticles(n, rng) {
    return Array.from({ length: n }, () => ({
      x: rng(), y: rng(),
      vx: (rng() - 0.5) * 0.018, vy: (rng() - 0.5) * 0.014,
      ph: rng() * Math.PI * 2, r: 1.4 + rng() * 1.6,
    }));
  }
  /** 새 배열을 돌려준다 (원본을 안 바꾼다). 화면 밖으로 나간 점은 반대편에서 들어온다 */
  function driftParticles(ps, dtSec, tSec) {
    const dt = Math.min(0.1, Math.max(0, dtSec));
    const wrap = (v) => (v < -0.04 ? v + 1.08 : v > 1.04 ? v - 1.08 : v);
    return ps.map((p) => ({
      ...p,
      x: wrap(p.x + (p.vx + 0.006 * Math.sin(tSec * 0.31 + p.ph)) * dt),
      y: wrap(p.y + (p.vy + 0.006 * Math.cos(tSec * 0.27 + p.ph * 1.3)) * dt),
    }));
  }

  // ── 「읽는 것」 신호 — 바뀌었을 때만 켜진다 ───────────────────────────────────────────────────
  /**
   * 두 눈에서 홍채가 눈 안 어디쯤인지(가로 0~1 · 세로 0~1)의 평균. 방향만 — 어디를 보는지 자리로 나누지 않는다.
   * 가로는 두 눈 다 «영상 왼쪽 눈꼬리 → 오른쪽 눈꼬리» 로 잰다 — 눈마다 바깥→안쪽으로 재면 옆을 볼 때 두 눈 값이 반대로 가서 평균이 그대로다.
   */
  function gazeDir(face) {
    const one = (a, b, upper, lower, iris) => {
      const o = facePt(face, b), n = facePt(face, a), u = facePt(face, upper), l = facePt(face, lower), c = facePt(face, iris);
      if (!o || !n || !u || !l || !c) return null;
      const ax = o[0] - n[0], ay = o[1] - n[1], len2 = ax * ax + ay * ay;
      const h = len2 > 1e-9 ? ((c[0] - n[0]) * ax + (c[1] - n[1]) * ay) / len2 : 0.5;
      const vh = l[1] - u[1];
      const v = Math.abs(vh) > 1e-6 ? (c[1] - u[1]) / vh : 0.5;
      return [h, v];
    };
    const r = one(33, 133, 159, 145, 468), l = one(362, 263, 386, 374, 473);
    if (!r || !l) return r || l;
    return [(r[0] + l[0]) / 2, (r[1] + l[1]) / 2];
  }
  /** 고개 — 돌림(코끝이 얼굴 가운데서 얼마나 옆)·숙임(눈과 턱 사이 코끝 높이)·기울임(두 눈꼬리 각도). 단위 없는 근사값 */
  function headPose(face) {
    const l = facePt(face, 234), r = facePt(face, 454), nose = facePt(face, 1), chin = facePt(face, 152);
    const eR = facePt(face, 33), eL = facePt(face, 263);
    if (!l || !r || !nose || !chin || !eR || !eL) return null;
    const w = Math.hypot(r[0] - l[0], r[1] - l[1]) || 1;
    const eyeMid = [(eR[0] + eL[0]) / 2, (eR[1] + eL[1]) / 2];
    const yaw = (nose[0] - (l[0] + r[0]) / 2) / w;
    const span = chin[1] - eyeMid[1];
    const pitch = Math.abs(span) > 1e-6 ? (nose[1] - eyeMid[1]) / span : 0;
    const roll = Math.atan2(eL[1] - eR[1], eL[0] - eR[0]);
    return [yaw, pitch, roll];
  }
  /** 어깨선 기울기(라디안) — 두 어깨가 다 보일 때만 */
  function shoulderTilt(pose, aspect) {
    const a = posePt(pose, 11, POSE_VIS_MIN), b = posePt(pose, 12, POSE_VIS_MIN);
    if (!a || !b) return null;
    return Math.atan2(a[1] - b[1], (a[0] - b[0]) * (aspect || 1));
  }
  /** 손목 두 개 중 빠른 쪽의 빠르기 — 어깨너비/초. 손목이 안 보이면 null */
  function handSpeed(prevPose, pose, dtSec, aspect) {
    if (!prevPose || !pose || !(dtSec > 0)) return null;
    const a = posePt(pose, 11, POSE_VIS_MIN), b = posePt(pose, 12, POSE_VIS_MIN);
    const sw = a && b ? dist(a, b, aspect) : 0.25;
    let best = null;
    [15, 16].forEach((i) => {
      const p0 = posePt(prevPose, i, POSE_VIS_MIN), p1 = posePt(pose, i, POSE_VIS_MIN);
      if (!p0 || !p1) return;
      const v = dist(p0, p1, aspect) / Math.max(0.05, sw) / dtSec;
      best = best === null ? v : Math.max(best, v);
    });
    return best;
  }

  /**
   * 「바뀌었나」 판단 — 빠른 평균과 느린 평균의 차이가 문턱을 넘으면 켜고, hold 동안 유지한다.
   * 가만히 있으면 두 평균이 붙어서 꺼진다(자세 자체가 아니라 «움직임» 에만 반응). 값이 없으면(null) 서서히 꺼진다.
   * 돌려줌 { on, level(0~1, 빛 세기), fired(이번에 막 켜짐) }
   */
  function makeChange(opts) {
    const thr = opts.thr, hold = opts.hold != null ? opts.hold : 900;
    const fastTau = opts.fast != null ? opts.fast : 0.12, slowTau = opts.slow != null ? opts.slow : 1.0;
    let fast = null, slow = null, lastT = null, onUntil = -Infinity, level = 0;
    return {
      update(value, tMs) {
        const dt = lastT === null ? 0 : Math.min(1, Math.max(0, (tMs - lastT) / 1000));
        lastT = tMs;
        let act = 0;
        if (value == null) {
          fast = slow = null;
        } else {
          const v = Array.isArray(value) ? value : [value];
          if (!fast || fast.length !== v.length) { fast = v.slice(); slow = v.slice(); }
          const kf = 1 - Math.exp(-dt / fastTau), ks = 1 - Math.exp(-dt / slowTau);
          fast = fast.map((f, i) => f + (v[i] - f) * kf);
          slow = slow.map((s, i) => s + (v[i] - s) * ks);
          act = Math.max(...fast.map((f, i) => Math.abs(f - slow[i]))) / thr;
        }
        return settle(act, tMs, dt);
      },
      /** 이미 「얼마나 센가」 가 나온 신호(손 빠르기 · 목소리)를 그대로 — activity 1 이상이면 켜진다 */
      level(activity, tMs) {
        const dt = lastT === null ? 0 : Math.min(1, Math.max(0, (tMs - lastT) / 1000));
        lastT = tMs;
        return settle(activity == null ? 0 : activity, tMs, dt);
      },
    };
    function settle(act, tMs, dt) {
      const was = tMs < onUntil;
      if (act >= 1) onUntil = tMs + hold;
      const on = tMs < onUntil;
      const target = on ? Math.min(1, 0.55 + 0.45 * Math.min(1, act)) : Math.min(0.35, act * 0.35);
      level += (target - level) * (1 - Math.exp(-dt / (target > level ? 0.08 : 0.5)));
      return { on, level, fired: on && !was };
    }
  }

  /**
   * 마이크 소리 크기(RMS) → 말하는 중 · 막 쉼. 바닥 소음은 스스로 맞춘다(행사장은 시끄럽다) — 조용해지면 바로 내려가고 천천히 올라간다.
   * 소리는 크기 숫자 하나만 쓴다 — 녹음하지 않는다. 돌려줌 { speaking, pause(막 쉬기 시작함), activity }
   */
  function makeVoice() {
    let floor = null, speaking = false, quietSince = null, lastT = null;
    const PAUSE_MS = 280;
    return {
      update(rms, tMs) {
        if (rms == null || !isFinite(rms)) { speaking = false; return { speaking: false, pause: false, activity: 0 }; }
        const dt = lastT === null ? 0 : Math.min(1, Math.max(0, (tMs - lastT) / 1000));
        lastT = tMs;
        if (floor === null || rms < floor) floor = rms;
        else floor += (rms - floor) * (1 - Math.exp(-dt / 8));
        const gate = Math.max(0.012, floor * 2.6);
        const loud = rms > gate;
        let pause = false;
        if (loud) { speaking = true; quietSince = null; }
        else if (speaking) {
          if (quietSince === null) quietSince = tMs;
          if (tMs - quietSince >= PAUSE_MS) { speaking = false; pause = true; }
        }
        return { speaking, pause, activity: speaking || pause ? 1.2 : rms / gate * 0.5 };
      },
    };
  }

  /** 「읽는 것」 다섯 줄 — 화면 글자 · 그래프에서 같이 밝아지는 무리 */
  const SIGNALS = [
    { id: 'gaze', label: '시선 방향', sub: '눈이 어느 쪽으로 움직이는지' },
    { id: 'head', label: '고개 각도', sub: '고개를 돌리고 숙이는 것' },
    { id: 'shoulder', label: '어깨 기울기', sub: '몸이 한쪽으로 기우는 것' },
    { id: 'hand', label: '손 움직임', sub: '손짓이 얼마나 오가는지' },
    { id: 'voice', label: '목소리·쉼', sub: '말하고 쉬는 박자' },
  ];

  /**
   * 다섯 신호를 한 번에 — 사람마다 값을 내고 그중 가장 센 쪽을 쓴다.
   * people: [{gaze, head, tilt, hand}] (없으면 null) · rms: 마이크 크기(없으면 null).
   */
  function makeSignals() {
    const det = {
      gaze: makeChange({ thr: 0.06, hold: 900 }),
      head: makeChange({ thr: 0.035, hold: 900 }),
      shoulder: makeChange({ thr: 0.035, hold: 900 }),
      hand: makeChange({ thr: 1, hold: 700 }),
      voice: makeChange({ thr: 1, hold: 600 }),
    };
    const voice = makeVoice();
    const pick = (people, key) => {
      const v = (people || []).map((p) => p && p[key]).filter((x) => x != null);
      return v.length ? v[0] : null;  // 가장 큰(가까운) 사람 — 여럿을 섞으면 서로 다른 머리의 차이가 «움직임» 으로 읽힌다
    };
    return {
      update(people, rms, tMs) {
        const hands = (people || []).map((p) => p && p.hand).filter((x) => x != null);
        const v = voice.update(rms, tMs);
        return {
          gaze: det.gaze.update(pick(people, 'gaze'), tMs),
          head: det.head.update(pick(people, 'head'), tMs),
          shoulder: det.shoulder.update(pick(people, 'tilt'), tMs),
          hand: det.hand.level(hands.length ? Math.max(...hands) / 0.9 : null, tMs),
          voice: { ...det.voice.level(rms == null ? null : v.activity, tMs), speaking: v.speaking, pause: v.pause, mic: rms != null },
        };
      },
    };
  }

  // ── 선 위를 흐르는 빛 ─────────────────────────────────────────────────────────────────────
  /**
   * 이번 프레임에 새로 띄울 빛 — 켜진 신호의 무리에 걸친 선은 더 자주. 돌려줌 [{edge, t0, dur}].
   * groupOn: { gaze: true, ... } · rate: 초당 기본 개수.
   */
  function spawnPulses(graph, groupOn, dtSec, nowMs, rng, rate) {
    const base = (rate || 5) * Math.max(0, Math.min(0.1, dtSec));
    const out = [];
    let n = Math.floor(base) + (rng() < base - Math.floor(base) ? 1 : 0);
    const hot = graph.edges.map((e, k) => k).filter((k) => {
      const [a, b] = graph.edges[k];
      return groupOn[graph.nodes[a].group] || groupOn[graph.nodes[b].group];
    });
    if (hot.length) n += rng() < base * 1.5 ? 1 : 0;
    for (let i = 0; i < n; i += 1) {
      const useHot = hot.length && rng() < 0.7;
      const edge = useHot ? hot[Math.floor(rng() * hot.length)] : Math.floor(rng() * graph.edges.length);
      out.push({ edge, t0: nowMs, dur: 520 + rng() * 420, rev: rng() < 0.5 });
    }
    return out;
  }
  /** 끝난 빛을 걸러 낸 새 배열 */
  function livePulses(pulses, nowMs) {
    return pulses.filter((p) => nowMs - p.t0 < p.dur);
  }

  const api = {
    FACE_PARTS, IRIS, NOSE, POSE_PARTS, PICK_FACE, PICK_POSE, SIGNALS, MAX_PEOPLE,
    ASSEMBLE_MS, SCATTER_MS, LOST_GRACE_MS, MISS_MAX, POSE_VIS_MIN,
    buildGraph, coverMap, makeOneEuro, follow,
    facePt, posePt, pairPeople, matchTracks, nodeTargets,
    phaseOf, assembleProgress, lerp2, scatterAt, scatterVelocities, easeOutCubic,
    rng32, makeParticles, driftParticles,
    gazeDir, headPose, shoulderTilt, handSpeed, makeChange, makeVoice, makeSignals,
    spawnPulses, livePulses,
  };
  root.BoothScanLogic = api;
})(typeof window !== 'undefined' ? window : globalThis);
