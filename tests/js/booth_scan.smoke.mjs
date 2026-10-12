/**
 * 부스 「사람 그래프」 스캔 화면(js/booth_scan_logic.js) 순수 함수 스모크.
 *
 *   node tests/js/booth_scan.smoke.mjs
 *
 * 왜 있나 — 이 서버엔 웹캠이 없다. 틀릴 곳은 「점이 얼굴 위에 앉나(거울 + cover 잘림)」 · 「떨림 거르기」 · 「같은 사람을 이어 가나」 ·
 * 「모이기 · 흩어지기 시간」 · 「읽는 것이 바뀔 때만 켜지나」 에 몰려 있다. 이것들을 브라우저 없이 잡는다.
 * 그리고 지킬 것 두 가지를 글자로 지킨다 — 시선 자리 구분(렌즈·슬라이드·대본) 코드가 없다 · 화면 글자에 감정·점수 말이 없다.
 *
 * 마지막 케이스는 하네스가 진짜로 회귀를 잡는지 스스로 검사한다 (booth.smoke.mjs · tour.smoke.mjs 와 같은 규율).
 * 이 파일은 pytest 가 수집하지 않는다.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const WEB = path.join(ROOT, 'demo/YEHS_demo');
const SRC = readFileSync(path.join(WEB, 'js/booth_scan_logic.js'), 'utf8');
const SHIPPED = ['js/booth_scan_logic.js', 'js/booth_scan_draw.js', 'js/booth_scan.js', 'js/booth_scan_worker.js']
  .map((f) => [f, readFileSync(path.join(WEB, f), 'utf8')]);
const HTML = readFileSync(path.join(WEB, 'booth_scan.html'), 'utf8');

/** 브라우저 전역 없이 원본 파일 그대로 올린다 — window 하나만 준다 */
function load(src) {
  const sandbox = { window: {}, Math, Array, Map, Set, Float32Array, isFinite, Infinity, Object, Number, String, JSON };
  vm.runInNewContext(src, sandbox, { filename: 'booth_scan_logic.js' });
  return sandbox.window.BoothScanLogic;
}
const L = load(SRC);

const cases = [];
const test = (name, fn) => cases.push({ name, fn });
const eq = (a, b, msg = '') => {
  const A = JSON.stringify(a), B = JSON.stringify(b);
  if (A !== B) throw new Error(`${msg}\n  expected ${B}\n  got      ${A}`);
};
const ok = (v, msg) => { if (!v) throw new Error(msg); };
const near = (a, b, tol, msg = '') => { if (!(Math.abs(a - b) <= tol)) throw new Error(`${msg} — ${a} ≠ ${b} (±${tol})`); };

/** 가짜 얼굴 — 고른 번호마다 점을 정해 워커가 주는 모양(Float32Array x,y…)으로 */
function fakeFace(L, at) {
  const arr = new Float32Array(L.PICK_FACE.length * 2);
  L.PICK_FACE.forEach((idx, k) => {
    const p = at(idx) || [0.5, 0.5];
    arr[2 * k] = p[0]; arr[2 * k + 1] = p[1];
  });
  return arr;
}
/** 정면을 보는 얼굴 하나 — 코끝 (cx, cy), 얼굴 폭 w */
function frontFace(L, cx, cy, w, tweak) {
  const base = {
    1: [cx, cy], 4: [cx, cy], 234: [cx - w / 2, cy - 0.02], 454: [cx + w / 2, cy - 0.02], 152: [cx, cy + 0.12],
    33: [cx - 0.08, cy - 0.06], 133: [cx - 0.03, cy - 0.06], 159: [cx - 0.055, cy - 0.075], 145: [cx - 0.055, cy - 0.045],
    263: [cx + 0.08, cy - 0.06], 362: [cx + 0.03, cy - 0.06], 386: [cx + 0.055, cy - 0.075], 374: [cx + 0.055, cy - 0.045],
    468: [cx - 0.055, cy - 0.06], 473: [cx + 0.055, cy - 0.06],
  };
  Object.assign(base, tweak || {});
  return fakeFace(L, (idx) => base[idx] || [cx, cy]);
}
/** 가짜 몸 — 번호 → [x, y, visibility] */
function fakePose(L, pts) {
  const arr = new Float32Array(L.PICK_POSE.length * 3);
  L.PICK_POSE.forEach((idx, k) => {
    const p = pts[idx] || [0.5, 0.5, 0];
    arr[3 * k] = p[0]; arr[3 * k + 1] = p[1]; arr[3 * k + 2] = p[2];
  });
  return arr;
}

function suite(L) {
  const out = [];
  const t = (name, fn) => out.push({ name, fn: () => fn(L) });

  t('그래프는 성기다 — 노드 60~80개 · 선은 있는 노드만 잇는다 · 홍채 두 점', (L) => {
    const g = L.buildGraph();
    ok(g.nodes.length >= 60 && g.nodes.length <= 80, `노드 ${g.nodes.length}개`);
    ok(g.edges.length >= g.nodes.length - 1, '선이 너무 적다 — 한 그래프로 안 이어진다');
    g.edges.forEach(([a, b]) => ok(g.nodes[a] && g.nodes[b] && a !== b, `잘못된 선 ${a}-${b}`));
    eq(g.nodes.filter((n) => n.kind === 'iris').map((n) => n.idx), [468, 473]);
    ['head', 'gaze', 'shoulder', 'hand', 'voice'].forEach((grp) => ok(g.nodes.some((n) => n.group === grp), `${grp} 무리가 없다`));
    eq(new Set(g.nodes.map((n) => n.key)).size, g.nodes.length, '같은 노드가 두 번');
  });

  t('그래프가 한 덩어리 — 얼굴 · 목 · 어깨 · 손목이 선으로 다 이어진다', (L) => {
    const g = L.buildGraph();
    const adj = g.nodes.map(() => []);
    g.edges.forEach(([a, b]) => { adj[a].push(b); adj[b].push(a); });
    const seen = new Set([0]), st = [0];
    while (st.length) { const v = st.pop(); adj[v].forEach((w) => { if (!seen.has(w)) { seen.add(w); st.push(w); } }); }
    const lone = g.nodes.filter((n, i) => !seen.has(i) && n.kind !== 'iris').map((n) => n.key);
    eq(lone, [], '떨어진 노드');
  });

  t('워커가 줄 번호에 그래프 · 신호가 쓰는 점이 다 있다 (478점 전체는 아니다)', (L) => {
    const g = L.buildGraph();
    g.nodes.filter((n) => n.src === 'face').forEach((n) => ok(L.PICK_FACE.includes(n.idx), `얼굴 ${n.idx} 없음`));
    [1, 33, 133, 159, 145, 263, 362, 386, 374, 468, 473, 234, 454, 152].forEach((i) => ok(L.PICK_FACE.includes(i), `신호용 ${i} 없음`));
    eq(new Set(L.PICK_FACE).size, L.PICK_FACE.length, '번호가 겹친다');
    ok(L.PICK_FACE.length < 100, `얼굴 점 ${L.PICK_FACE.length}개 — 성긴 그래프가 아니다`);
    eq(L.PICK_POSE, [0, 11, 12, 13, 14, 15, 16]);
  });

  t('영상 → 화면: 같은 비율이면 거울만 · 왼쪽 영상 점이 화면 오른쪽에', (L) => {
    const m = L.coverMap(1280, 720, 1920, 1080, true);
    near(m.s, 1.5, 1e-9);
    near(m.x(0.25), 1440, 1e-6, '거울');
    near(m.y(0.25), 270, 1e-6);
    near(L.coverMap(1280, 720, 1920, 1080, false).x(0.25), 480, 1e-6, '거울 끔');
  });

  t('영상 → 화면: cover 는 넘친 쪽을 양쪽으로 똑같이 자른다 (contain 이 아니다)', (L) => {
    // 4:3 캠을 16:9 모니터에 — 위아래가 잘린다
    const a = L.coverMap(640, 480, 1920, 1080, true);
    near(a.s, 3, 1e-9);
    near(a.oy, -180, 1e-9);
    near(a.y(0.5), 540, 1e-9, '가운데는 가운데');
    near(a.y(0), -180, 1e-9, '맨 위는 화면 밖');
    near(a.x(0), 1920, 1e-9);
    // 16:9 캠을 16:10 노트북에 — 양옆이 잘린다
    const b = L.coverMap(1280, 720, 1280, 800, true);
    near(b.s, 800 / 720, 1e-9);
    near(b.x(0.5), 640, 1e-6, '가운데는 가운데');
    ok(b.x(0) > 1280 && b.x(1) < 0, '양 끝이 화면 밖');
    near(b.x(0) - 1280, -b.x(1), 1e-6, '양쪽이 같은 만큼 잘린다');
  });

  t('One-Euro: 가만히 있으면 떨림이 줄고, 크게 옮기면 따라간다', (L) => {
    const f = L.makeOneEuro();
    const rnd = L.rng32(7);
    let raw = 0, filt = 0, prev = null;
    for (let i = 0; i < 120; i += 1) {
      const x = 0.5 + (rnd() - 0.5) * 0.01;
      const y = f.filter(x, i * 80);
      if (prev !== null && i > 10) { raw += Math.abs(x - 0.5); filt += Math.abs(y - 0.5); }
      prev = y;
    }
    ok(filt < raw * 0.6, `떨림이 안 줄었다 ${filt.toFixed(4)} vs ${raw.toFixed(4)}`);
    let y = 0;
    for (let i = 120; i < 140; i += 1) y = f.filter(0.8, i * 80);
    near(y, 0.8, 0.01, '옮긴 자리로 1.6초 안에');
  });

  t('얼굴 ↔ 몸 짝: 순서가 달라도 코가 가까운 쪽끼리 · 먼 몸은 안 붙인다 · 큰 얼굴이 먼저', (L) => {
    const fA = frontFace(L, 0.3, 0.4, 0.12), fB = frontFace(L, 0.7, 0.4, 0.2);
    const pA = fakePose(L, { 0: [0.3, 0.41, 0.99], 11: [0.38, 0.6, 0.9], 12: [0.22, 0.6, 0.9] });
    const pB = fakePose(L, { 0: [0.7, 0.41, 0.99], 11: [0.8, 0.6, 0.9], 12: [0.6, 0.6, 0.9] });
    const people = L.pairPeople([fA, fB], [pB, pA], 16 / 9);
    eq(people.length, 2);
    near(people[0].center[0], 0.7, 1e-6, '큰 얼굴(가까운 사람)이 먼저');
    ok(people[0].pose === pB && people[1].pose === pA, '몸 짝이 바뀌었다');
    const far = fakePose(L, { 0: [0.1, 0.9, 0.99] });
    eq(L.pairPeople([fA], [far], 16 / 9)[0].pose, null, '먼 몸을 붙였다');
    eq(L.pairPeople([], [pA], 16 / 9).length, 0, '얼굴 없는 몸은 사람이 아니다');
  });

  t('사람 이어 가기: 조금 움직이면 같은 사람 · 멀리 나타나면 새 사람 · 빠지면 missing', (L) => {
    const tracks = [{ center: [0.3, 0.4] }, { center: [0.7, 0.4] }];
    const people = [{ center: [0.72, 0.41] }, { center: [0.1, 0.8] }];
    const m = L.matchTracks(tracks, people, 16 / 9);
    eq(m.matched, [[1, 0]]);
    eq(m.fresh, [1]);
    eq(m.missing, [0]);
  });

  t('노드 자리: 안 보이는 손목은 null · 목은 두 어깨 가운데 · 몸이 없으면 얼굴만', (L) => {
    const g = L.buildGraph();
    const face = frontFace(L, 0.5, 0.4, 0.15);
    const pose = fakePose(L, { 0: [0.5, 0.4, 1], 11: [0.6, 0.6, 0.9], 12: [0.4, 0.62, 0.9], 15: [0.65, 0.8, 0.2], 16: [0.35, 0.8, 0.95] });
    const tg = L.nodeTargets(g, { face, pose });
    const at = (key) => tg[g.nodes.findIndex((n) => n.key === key)];
    eq(at('pose:15'), null, '흐린 손목');
    ok(at('pose:16') !== null, '보이는 손목');
    near(at('neck:0')[0], 0.5, 1e-6); near(at('neck:0')[1], 0.61, 1e-6);
    const solo = L.nodeTargets(g, { face, pose: null });
    eq(solo.filter((p, i) => p && g.nodes[i].src !== 'face').length, 0);
    ok(solo.filter(Boolean).length >= 55, '얼굴 점이 다 나와야 한다');
  });

  t('단계: 모이기(1.1초) → 따라가기 → 잠깐 놓쳐도 그대로 → 오래 놓치면 흩어지기 → 사라짐', (L) => {
    const tr = { born: 0, lastSeen: 0, lostAt: null, missed: 0 };
    eq(L.phaseOf(tr, 100), 'assemble');
    tr.lastSeen = 1000;
    eq(L.phaseOf({ ...tr }, L.ASSEMBLE_MS + 10), 'track');
    eq(L.phaseOf({ ...tr, missed: L.MISS_MAX }, 1000 + L.LOST_GRACE_MS - 10), 'track', '한두 프레임 놓쳤다고 흩어지면 깜빡인다');
    eq(L.phaseOf({ ...tr, missed: L.MISS_MAX }, 1000 + L.LOST_GRACE_MS + 10), 'lost');
    // 약한 노트북(추론 2fps) — 결과 사이 시간이 길어도 결과가 사람 없이 두 번 오기 전엔 그대로
    eq(L.phaseOf({ ...tr, missed: 1 }, 1000 + 3000), 'track', '느린 추론에서 결과 사이에 흩어진다');
    eq(L.phaseOf({ ...tr, missed: 0 }, 1000 + 60000), 'track', '결과가 안 오면(워커 멈춤) 그대로 둔다');
    eq(L.phaseOf({ ...tr, lostAt: 2000 }, 2000 + L.SCATTER_MS / 2), 'scatter');
    eq(L.phaseOf({ ...tr, lostAt: 2000 }, 2000 + L.SCATTER_MS + 1), 'gone');
  });

  t('모이기: 처음엔 떠다니던 점 자리 · 1.1초에 모든 노드가 도착 · 노드마다 조금씩 늦게 출발', (L) => {
    const n = 68;
    near(L.assembleProgress(0, 0, n), 0, 1e-9);
    for (let i = 0; i < n; i += 1) near(L.assembleProgress(L.ASSEMBLE_MS, i, n), 1, 1e-9, `노드 ${i}`);
    ok(L.assembleProgress(300, 0, n) > L.assembleProgress(300, 60, n), '뒤 노드가 늦게 출발');
    eq(L.lerp2([0, 0], [10, 20], 0.5), [5, 10]);
  });

  t('흩어지기: 무게중심에서 바깥으로 · 옅어지다 0', (L) => {
    const pts = [[100, 100], [200, 100], null, [150, 200]];
    const vel = L.scatterVelocities(pts, L.rng32(3));
    eq(vel[2], [0, 0]);
    const a = L.scatterAt(pts[0], vel[0], 300), b = L.scatterAt(pts[0], vel[0], 900);
    ok(Math.hypot(a.pos[0] - 150, a.pos[1] - 133) > Math.hypot(100 - 150, 100 - 133), '바깥으로 안 간다');
    ok(b.alpha < a.alpha && a.alpha < 1, '안 옅어진다');
    eq(L.scatterAt(pts[0], vel[0], L.SCATTER_MS).alpha, 0);
  });

  t('떠다니는 점: 원본을 안 바꾸고 · 화면 근처를 벗어나지 않는다', (L) => {
    const ps = L.makeParticles(30, L.rng32(1));
    const before = JSON.stringify(ps);
    let cur = ps;
    for (let i = 0; i < 2000; i += 1) cur = L.driftParticles(cur, 0.1, i * 0.1);
    eq(JSON.stringify(ps), before, '원본이 바뀌었다');
    cur.forEach((p) => ok(p.x >= -0.05 && p.x <= 1.05 && p.y >= -0.05 && p.y <= 1.05, `밖으로 샌 점 ${p.x},${p.y}`));
  });

  t('시선 방향: 가운데면 0.5 언저리 · 홍채가 눈꼬리 쪽이면 값이 바뀐다 (방향 값만, 자리 이름 없음)', (L) => {
    const c = L.gazeDir(frontFace(L, 0.5, 0.4, 0.15));
    near(c[0], 0.5, 0.01); near(c[1], 0.5, 0.01);
    // 두 홍채가 함께 영상 왼쪽으로 — 한 눈은 바깥 눈꼬리, 다른 눈은 안쪽 눈꼬리 쪽이 된다. 평균이 그대로면 옆을 봐도 안 켜진다
    const side = L.gazeDir(frontFace(L, 0.5, 0.4, 0.15, { 468: [0.43, 0.34], 473: [0.54, 0.34] }));
    ok(side[0] < c[0] - 0.2, `홍채를 옮겨도 안 바뀐다 ${side[0]}`);
    ok(Array.isArray(side) && side.length === 2 && side.every((v) => typeof v === 'number'), '방향은 숫자 둘');
  });

  t('고개: 코끝이 옆으로 가면 돌림 값의 부호가 바뀐다', (L) => {
    const r = L.headPose(frontFace(L, 0.5, 0.4, 0.15, { 1: [0.54, 0.4] }));
    const l = L.headPose(frontFace(L, 0.5, 0.4, 0.15, { 1: [0.46, 0.4] }));
    ok(r[0] > 0 && l[0] < 0, `돌림 ${r[0]} ${l[0]}`);
    eq(L.headPose(new Float32Array(4)), null, '점이 모자라면 null');
  });

  t('어깨 기울기 · 손 빠르기: 안 보이면 null, 보이면 값', (L) => {
    const lvl = fakePose(L, { 11: [0.6, 0.6, 0.9], 12: [0.4, 0.6, 0.9], 15: [0.6, 0.8, 0.9] });
    const tilt = fakePose(L, { 11: [0.6, 0.65, 0.9], 12: [0.4, 0.6, 0.9], 15: [0.7, 0.7, 0.9] });
    near(L.shoulderTilt(lvl, 16 / 9), 0, 1e-6);
    ok(L.shoulderTilt(tilt, 16 / 9) > 0.05, '기울었는데 0');
    eq(L.shoulderTilt(fakePose(L, { 11: [0.6, 0.6, 0.1], 12: [0.4, 0.6, 0.9] }), 16 / 9), null);
    ok(L.handSpeed(lvl, tilt, 0.1, 16 / 9) > 1, '손목이 움직였는데 느리다');
    eq(L.handSpeed(null, tilt, 0.1, 16 / 9), null);
  });

  t('바뀔 때만 켜진다: 가만히 있으면 꺼짐 · 움직이면 한 번 켜짐(fired) · 다시 가만히 있으면 꺼짐', (L) => {
    const c = L.makeChange({ thr: 0.05, hold: 600 });
    let r;
    for (let i = 0; i < 40; i += 1) { r = c.update([0.3, 0.5], i * 33); ok(!r.on, `가만히 있는데 켜짐 ${i}`); }
    let fired = 0;
    for (let i = 40; i < 50; i += 1) { r = c.update([0.5, 0.5], i * 33); fired += r.fired ? 1 : 0; }
    ok(r.on, '움직였는데 안 켜짐');
    eq(fired, 1, '켜짐 신호는 한 번');
    for (let i = 50; i < 200; i += 1) r = c.update([0.5, 0.5], i * 33);
    ok(!r.on && r.level < 0.2, '멈췄는데 안 꺼짐');
    r = c.update(null, 200 * 33);
    ok(!r.on, '사람이 없어지면 꺼짐');
  });

  t('자세 자체는 안 켠다 — 고개를 돌린 채 가만히 있으면 꺼진다', (L) => {
    const c = L.makeChange({ thr: 0.035, hold: 600 });
    let r;
    for (let i = 0; i < 300; i += 1) r = c.update([0.25, 0.1, 0.2], i * 33);
    ok(!r.on, '돌린 채 가만히 있는데 켜져 있다');
  });

  t('목소리·쉼: 조용하면 꺼짐 · 말하면 켜짐 · 말을 멈추면 「쉼」 한 번 · 마이크가 없으면 null', (L) => {
    const v = L.makeVoice();
    let r;
    for (let i = 0; i < 60; i += 1) { r = v.update(0.004, i * 16); ok(!r.speaking, '조용한데 말한다고'); }
    for (let i = 60; i < 100; i += 1) r = v.update(0.08, i * 16);
    ok(r.speaking, '말하는데 꺼짐');
    let pauses = 0;
    for (let i = 100; i < 160; i += 1) { r = v.update(0.004, i * 16); pauses += r.pause ? 1 : 0; }
    eq(pauses, 1, '쉼은 한 번');
    const s = L.makeSignals().update([], null, 0);
    ok(!s.voice.mic && !s.voice.on, '마이크가 없으면 흐리게');
  });

  t('신호 다섯 줄: 사람이 없으면 다 꺼져 있다', (L) => {
    const sig = L.makeSignals();
    let r;
    for (let i = 0; i < 30; i += 1) r = sig.update([], 0.003, i * 33);
    ['gaze', 'head', 'shoulder', 'hand', 'voice'].forEach((k) => ok(!r[k].on, `${k} 켜짐`));
    eq(L.SIGNALS.map((s) => s.label), ['시선 방향', '고개 각도', '어깨 기울기', '손 움직임', '목소리·쉼']);
  });

  t('빛: 켜진 무리의 선에 더 자주 · 끝난 빛은 걸러진다 · 같은 씨앗이면 같은 결과', (L) => {
    const g = L.buildGraph();
    const run = (on) => {
      const rnd = L.rng32(11);
      let all = [];
      for (let i = 0; i < 600; i += 1) all = all.concat(L.spawnPulses(g, on, 1 / 60, i * 16, rnd, 6));
      return all;
    };
    const quiet = run({}), hot = run({ hand: true });
    ok(quiet.length > 30 && quiet.length < 120, `빛 ${quiet.length}개 (10초)`);
    const handEdges = (list) => list.filter((p) => g.edges[p.edge].some((n) => g.nodes[n].group === 'hand')).length;
    ok(handEdges(hot) > handEdges(quiet) * 3, '손이 켜졌는데 손 선의 빛이 안 늘었다');
    eq(JSON.stringify(run({})), JSON.stringify(quiet), '씨앗이 같은데 다르다');
    eq(L.livePulses([{ t0: 0, dur: 500 }, { t0: 400, dur: 500 }], 600).length, 1);
  });

  return out;
}

suite(L).forEach((c) => test(c.name, c.fn));

/** 주석을 걷어 낸 코드만 — 「왜 없는지」 를 적은 주석까지 막지 않게 */
const codeOnly = (src) => src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`])\/\/.*$/gm, '$1');

// 특허 미공개(10-09 근거 문서) — 시선은 방향만. lab/eval-1008 eval_vision.js 의 3자리 구분이 섞여 들어오면 여기서 막는다
test('실어 보내는 JS 에 시선 자리 구분(렌즈 · 슬라이드 · 대본) 코드가 없다', () => {
  const ban = /렌즈|슬라이드|대본|\blens\b|\bslide\b|\bscript(?!s?\b\s*[=(])|zone|gazeZone|classifyGaze|calib/i;
  SHIPPED.forEach(([f, src]) => {
    const hit = codeOnly(src).match(ban);
    ok(!hit, `${f} 에 「${hit && hit[0]}」 — 시선은 방향만 (특허 미공개)`);
  });
  ok(!/eval_vision|eval_lab_draw|eval_session|eval_lab\.js/.test(SHIPPED.map(([, s]) => codeOnly(s)).join('\n') + HTML.replace(/<!--[\s\S]*?-->/g, '')), 'eval-lab 모듈을 부른다');
});

test('화면 글자에 감정 · 자신감 · 점수 · 좋고 나쁨이 없다', () => {
  const words = /감정|자신감|긴장|떨림|불안|표정|점수|잘했|못했|좋아요|나빠요|좋은|나쁜|\d+\s*점|%/;
  const copy = [HTML.replace(/<!--[\s\S]*?-->/g, '').replace(/<[^>]+>/g, ' ')];
  L.SIGNALS.forEach((s) => copy.push(s.label, s.sub));
  const main = SHIPPED.find(([f]) => f === 'js/booth_scan.js')[1];
  (main.match(/MESSAGES = \{[\s\S]*?\n {2}\};/) || [''])[0].replace(/'([^']*)'/g, (_, s) => { copy.push(s); return ''; });
  ok(copy.length > 15, '화면 글자를 못 모았다');
  copy.forEach((s) => { const hit = s.match(words); ok(!hit, `「${s.trim().slice(0, 40)}」 에 「${hit && hit[0]}」`); });
});

test('영상 · 소리는 밖으로 안 나간다 — 화면 JS 에 서버 호출 · 녹화가 없다', () => {
  SHIPPED.forEach(([f, src]) => {
    const code = codeOnly(src);
    ok(!/MediaRecorder|\/api\/|XMLHttpRequest|sendBeacon|WebSocket|toDataURL|toBlob/.test(code), `${f} 가 밖으로 보낸다`);
    if (f !== 'js/booth_scan_worker.js') ok(!/\bfetch\(/.test(code), `${f} 가 fetch 를 부른다`);
  });
});

test('하네스 자기 검사 — 거울을 빼먹은 파일 · 늘 켜지는 판단을 넣으면 잡는다', () => {
  const broken = [
    SRC.replace('const flip = mirror !== false;', 'const flip = false;'),
    SRC.replace('if (act >= 1) onUntil = tMs + hold;', 'onUntil = tMs + hold;'),
  ];
  broken.forEach((src, k) => {
    ok(src !== SRC, `고장 ${k} 이 원본에 안 먹혔다 — 원본 글자가 바뀌었나`);
    const failed = suite(load(src)).filter((c) => { try { c.fn(); return false; } catch (_) { return true; } });
    ok(failed.length > 0, `고장 ${k} 을 낸 booth_scan_logic 이 스모크를 통과했어요 — 하네스가 회귀를 못 잡는다`);
  });
});

let pass = 0, fail = 0;
for (const c of cases) {
  try { c.fn(); pass += 1; console.log(`  ✓ ${c.name}`); }
  catch (e) { fail += 1; console.log(`  ✗ ${c.name}\n    ${String(e.message).split('\n').join('\n    ')}`); }
}
console.log(`\n${pass}개 통과${fail ? ` · ${fail}개 실패` : ''}`);
process.exit(fail ? 1 : 0);
