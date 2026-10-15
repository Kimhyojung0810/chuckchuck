/**
 * /hi/stage 시안 A 「들어오자마자 채점당한다」 — 무대 위 사람 그래프의 움직임 좌표를 미리 계산한다 (2026-10-13).
 *
 * ⚠️ 정직성 — 이 좌표는 «녹화한 사람의 움직임이 아니다».
 *   서버에 팀원 발표 영상 · 랜드마크 녹화가 없었다(find *.mp4/*.webm · labs 픽스처 · booth_scan 실험실 출력 모두 확인).
 *   그래서 (1) 퍼블릭 도메인 그림 「모나리자」 한 장에 MediaPipe FaceLandmarker · PoseLandmarker 를 실제로 돌려 얻은 «한 장의 실제 랜드마크»
 *   (etc/labs/hi_stage/mona_landmarks.json) 중 «얼굴 점만» 쓰고, 몸(어깨 · 팔 · 골반)은 머리 크기를 잣대로 한 사람 체형 템플릿으로 세운 뒤(10-13 2차), (2) 그 위에 호흡 · 고개(끄덕임 · 기울임 · 돌림) · 눈 깜박임 · 입 벌림 · 손짓을
 *   «절차적으로» 입혔다. 화면은 그래프를 「녹화」라고 부르지 않고, 칩의 숫자 · 문장에만 「미리 녹화한 발표에서 나온 값」 라벨을 단다.
 *   시선 방향을 자리로 나누는 코드는 없다(특허 미공개). 감정 추정도 없다.
 *
 * 그래프 모양(어느 점 · 어느 선)은 부스 화면과 같다 — main/web/js/booth_scan_logic.js 의 buildGraph · nodeTargets 를 vm 으로 그대로 쓴다.
 *
 *   node etc/labs/hi_stage/make_pose.mjs
 *
 * 결과: main/web/data/hi_stage/pose.json (8초 · 15fps 고리) + main/web/intro_stage.html 의 <!-- stage-svg --> 사이 정지 그림(JS 없이 첫 프레임)
 */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../../..');
const WEB = path.join(ROOT, 'main/web');

const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(WEB, 'js/booth_scan_logic.js'), 'utf8'), ctx);
const L_ = ctx.BoothScanLogic;
const base = JSON.parse(fs.readFileSync(path.join(HERE, 'mona_landmarks.json'), 'utf8'));
const AR = base.image[0] / base.image[1];   // 가로 정규 좌표에 곱해 세로와 같은 길이로

const LOOP_SEC = 8;
const FPS = 15;
const FRAMES = LOOP_SEC * FPS;
const STILL_T = 3.6;          // 정지 그림 · 움직임 줄이기 · 연출 끝 프레임 — 손짓이 올라가 칩 쪽을 가리키는 순간
const TAU = Math.PI * 2;

const graph = L_.buildGraph();

// ── 시간 함수 (모두 8초에 정수 번 돌아 고리가 이어진다) ──
const smooth = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
const windowed = (t, a, b, c, d) => smooth(a, b, t) * (1 - smooth(c, d, t));
/** 손짓 무게 — 2.2~2.7초 올림, 4.4~4.9초 내림 (그 사이 「3장 핵심 주장」 순간) */
const gestureL = (t) => windowed(t, 2.2, 2.75, 4.4, 4.95);
/** 반대 손 작은 손짓 — 질문 답 순간 */
const gestureR = (t) => 0.55 * windowed(t, 5.3, 5.8, 6.6, 7.1);
/** 말하는 중 — 순간과 순간 사이(1.9 · 4.8 · 7.0초 언저리)에 잠깐 쉰다 */
const speaking = (t) => 1 - windowed(t, 1.75, 1.9, 2.05, 2.2) - windowed(t, 4.7, 4.85, 5.0, 5.15) - windowed(t, 6.95, 7.1, 7.25, 7.4);
const blink = (t) => Math.max(windowed(t, 3.05, 3.11, 3.13, 3.2), windowed(t, 6.35, 6.41, 6.43, 6.5));

// ── 몸 템플릿 (10-13 2차) — 모나리자 원본의 몸 좌표는 쓰지 않는다 ─────────────────────────────────
// 원본 비율 그대로면 어깨가 넓게 벌어지고 팔이 화면 끝까지 뻗어 사람으로 안 읽혔다(코디네이터 검토).
// 얼굴 점(실제 랜드마크)만 쓰고, 머리 높이 Hh · 머리 폭 Hw 를 잣대로 어깨 · 팔 · 골반을 사람 체형 비율로 세운다:
//   어깨 폭 ≈ 머리 폭 × 2.5 · 위팔 ≈ Hh × 1.4 · 아래팔 ≈ Hh × 1.25 · 목 ≈ Hh × 0.45 · 어깨 → 골반 ≈ Hh × 2.7(화면 아래로 잘린다)
const F0 = {};
for (const [k, v] of Object.entries(base.face)) F0[k] = [v[0] * AR, v[1]];
const HH = F0[152][1] - F0[10][1];                 // 이마(10) → 턱(152)
const HW = Math.abs(F0[454][0] - F0[234][0]);       // 광대 폭
const CX = F0[152][0];
const SH_Y = F0[152][1] + 0.45 * HH;
const SH_HALF = 1.25 * HW;
const len = (v) => Math.hypot(v[0], v[1]);
const along = (o, dir, L) => { const n = len(dir); return [o[0] + dir[0] / n * L, o[1] + dir[1] / n * L]; };
const UPPER = 1.4 * HH, FORE = 1.25 * HH;
/** 쉬는 팔 — 팔꿈치는 몸 옆으로 조금 벌어지고, 손은 배 앞에서 모인다(발표자가 손을 모은 자세) */
function restArm(side) {          // side +1 = 영상 오른쪽(사람의 왼팔 · pose 11/13/15), -1 = 영상 왼쪽(12/14/16)
  const sh = [CX + side * SH_HALF, SH_Y];
  const el = along(sh, [side * 0.18, 1], UPPER);
  const wr = along(el, [-side * 0.62, 1], FORE);
  return { sh, el, wr };
}
const HIP_Y = SH_Y + 2.7 * HH, HIP_HALF = 0.95 * HW;

function frameAt(t) {
  const face = {};
  for (const [k, v] of Object.entries(F0)) face[k] = v.slice();
  const L = restArm(+1), R = restArm(-1);
  const pose = { 11: L.sh, 13: L.el, 15: L.wr, 12: R.sh, 14: R.el, 16: R.wr };

  // 호흡 — 4초에 한 번. 어깨 · 팔이 조금 오르내리고 머리가 따라간다
  const br = Math.sin(TAU * t / 4);
  for (const k of [11, 12, 13, 14, 15, 16]) pose[k] = [pose[k][0], pose[k][1] - 0.025 * HH * br * (k <= 12 ? 1 : 0.6)];
  for (const k of Object.keys(face)) face[k][1] -= 0.018 * HH * br;

  // 고개 — 턱(152)을 축으로 기울임(roll) · 끄덕임(nod) · 돌림(yaw: 안쪽 점이 바깥 윤곽보다 더 움직인다)
  const chin = face[152].slice();
  const roll = (2.4 * Math.sin(TAU * t / 8) + 1.5 * gestureL(t)) * Math.PI / 180;
  const nod = 0.025 * HH * Math.sin(TAU * 3 * t / 8) * speaking(t);
  const yaw = 0.07 * HW * Math.sin(TAU * t / 8 + 1.3) + 0.05 * HW * gestureL(t);
  const cx = (face[234][0] + face[454][0]) / 2;
  const half = HW / 2;
  const oval = new Set(L_.FACE_PARTS[0].idx.map(String));
  for (const [k, p] of Object.entries(face)) {
    const depth = oval.has(k) ? Math.max(0, 1 - Math.abs(p[0] - cx) / half) * 0.6 : (k === '4' || k === '1' || k === '195' ? 1 : 0.75);
    const x = p[0] + yaw * depth;
    const y = p[1] + nod * Math.max(0, (chin[1] - p[1]) / HH);
    const dx = x - chin[0], dy = y - chin[1];
    face[k] = [chin[0] + dx * Math.cos(roll) - dy * Math.sin(roll), chin[1] + dx * Math.sin(roll) + dy * Math.cos(roll)];
  }

  // 눈 깜박임 — 위 눈꺼풀 점이 아래 눈꺼풀 쪽으로
  const bl = blink(t);
  for (const [up, low] of [[160, 144], [158, 153], [387, 373], [385, 380], [159, 145], [386, 374]]) {
    if (!face[up] || !face[low]) continue;
    face[up][1] += (face[low][1] - face[up][1]) * 0.85 * bl;
  }

  // 입 — 말하는 동안 아랫입술이 음절 박자로 벌어진다
  const open = 0.045 * HH * speaking(t) * Math.max(0, 0.55 * Math.sin(TAU * 11 * t / 8) + 0.45 * Math.sin(TAU * 17 * t / 8 + 0.7));
  for (const k of [321, 17, 91]) face[k][1] += open;
  for (const k of [61, 291]) face[k][1] += open * 0.35;

  // 손짓 — 왼팔(영상 오른쪽, 칩 쪽)을 들어 옆을 가리킨다. 팔 길이(위팔 · 아래팔)는 그대로 — 관절 방향만 돌린다
  const lerpDir = (a, b, k) => [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k];
  const gL = gestureL(t);
  if (gL > 0) {
    const wob = 0.06 * Math.sin(TAU * 5 * t / 8) * gL;
    const upDir = lerpDir([0.18, 1], [0.62, 0.78], gL);
    const foreDir = lerpDir([-0.62, 1], [1, -0.42 + wob], gL);
    pose[13] = along(pose[11], upDir, UPPER);
    pose[15] = along(pose[13], foreDir, FORE);
  }
  // 질문 답 — 오른손을 가슴 높이로 조금
  const gR = gestureR(t);
  if (gR > 0) {
    const foreDir = lerpDir([0.62, 1], [0.35, -0.55], gR);
    pose[14] = along(pose[12], lerpDir([-0.18, 1], [-0.32, 1], gR), UPPER);
    pose[16] = along(pose[14], foreDir, FORE);
  }

  const faceArr = L_.PICK_FACE.flatMap((i) => face[i]);
  const poseArr = L_.PICK_POSE.flatMap((i) => (pose[i] ? [pose[i][0], pose[i][1], 1] : [0, 0, 1]));
  const nodes = L_.nodeTargets(graph, { face: faceArr, pose: poseArr });
  // 몸통 — 어깨 → 골반(부스 그래프에는 없는 두 점, 이 화면만 더한다). 호흡에 맞춰 같이 오르내린다
  const by = -0.012 * HH * br;
  return nodes.concat([[CX + HIP_HALF, HIP_Y + by], [CX - HIP_HALF, HIP_Y + by]]);
}

const raw = Array.from({ length: FRAMES }, (_, f) => frameAt(f / FPS));
const still = frameAt(STILL_T);
const HIP_L = graph.nodes.length, HIP_R = graph.nodes.length + 1;
const nodeAt = (key) => graph.nodes.findIndex((n) => n.key === key);
const edges = graph.edges.concat([[nodeAt('pose:11'), HIP_L], [nodeAt('pose:12'), HIP_R], [HIP_L, HIP_R]]);
const nodes = graph.nodes.map((n) => [n.group, n.kind === 'iris' ? 1 : 0]).concat([['shoulder', 0], ['shoulder', 0]]);

// 상자 — 쉬는 자세의 머리 위 ~ 몸통 가운데(골반은 아래로 잘린다). 손짓으로 뻗는 팔은 상자 밖(칩 쪽)으로 나가도 된다
const rest = frameAt(0.6);
let minX = Infinity, maxX = -Infinity;
for (const p of rest.slice(0, HIP_L)) { minX = Math.min(minX, p[0]); maxX = Math.max(maxX, p[0]); }
const top = F0[10][1] - 0.3 * HH;
const bottom = SH_Y + 2.15 * HH;
const padX = 0.15 * HW;
const W = 1000;
const sx = W / (maxX - minX + 2 * padX);
const H = Math.round((bottom - top) * sx);
const ox = minX - padX, oy = top;
const q = (p) => [Math.round((p[0] - ox) * sx), Math.round((p[1] - oy) * sx)];

const out = {
  schema: 'chuckchuck.hi-stage-pose',
  version: 2,
  note: '절차적 움직임 — 퍼블릭 도메인 그림 한 장의 실제 얼굴 랜드마크(MediaPipe)에 사람 체형 비율의 몸 템플릿을 붙이고 호흡·고개·깜박임·입·손짓을 계산해 입혔어요. 사람을 녹화한 좌표가 아니에요.',
  fps: FPS,
  box: [W, H],
  still_t: STILL_T,
  nodes,
  edges,
  anchors: { voice: nodeAt('face:17'), hand: nodeAt('pose:15'), head: nodeAt('face:10') },
  /** 장면(근거 칩)과 고리 시간 — 0 말 빠르기 · 1 3장 핵심 주장(손짓) · 2 질문 답 */
  moments: [[0, 2.0, 'pace'], [2.0, 4.8, 'claim'], [4.8, 7.0, 'qa'], [7.0, 8.0, 'pace']],
  frames: raw.map((fr) => fr.flatMap(q)),
  still: still.flatMap(q),
};
fs.mkdirSync(path.join(WEB, 'data/hi_stage'), { recursive: true });
const jsonPath = path.join(WEB, 'data/hi_stage/pose.json');
fs.writeFileSync(jsonPath, JSON.stringify(out));

// ── JS 없이 보이는 첫 그림 — 정지 프레임을 인라인 SVG 로. 상자 밖(골반 · 뻗은 팔)도 그리게 overflow visible ──
const sp = still.map(q);
const lines = edges.map(([a, b]) => `M${sp[a][0]} ${sp[a][1]}L${sp[b][0]} ${sp[b][1]}`).join('');
const dots = nodes.map((n, i) => (n[1] ? '' : `M${sp[i][0] - 9} ${sp[i][1]}a9 9 0 1 0 18 0a9 9 0 1 0-18 0`)).join('');
const iris = nodes.map((n, i) => (n[1] ? `<circle cx="${sp[i][0]}" cy="${sp[i][1]}" r="10"/>` : '')).join('');
const svg = `<svg class="fig-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMinYMax meet" overflow="visible" aria-hidden="true" focusable="false">`
  + `<path d="${lines}" fill="none" stroke="#CEFADC" stroke-opacity=".5" stroke-width="4" stroke-linecap="round"/>`
  + `<path d="${dots}" fill="#0CAF68" stroke="#CEFADC" stroke-opacity=".7" stroke-width="3"/>`
  + `<g fill="#ECFFF7">${iris}</g></svg>`;
const htmlPath = path.join(WEB, 'intro_stage.html');
if (fs.existsSync(htmlPath)) {
  const html = fs.readFileSync(htmlPath, 'utf8');
  const re = /(<!-- stage-svg:start[^>]*-->)[\s\S]*?(<!-- stage-svg:end -->)/;
  if (!re.test(html)) throw new Error('intro_stage.html 에 stage-svg 표시가 없어요');
  fs.writeFileSync(htmlPath, html.replace(re, `$1${svg}$2`));
}
console.log(`pose.json ${fs.statSync(jsonPath).size}B · ${nodes.length} nodes · ${edges.length} edges · box ${W}x${H} · HW/HH ${(HW / HH).toFixed(2)} · svg ${svg.length}B`);
