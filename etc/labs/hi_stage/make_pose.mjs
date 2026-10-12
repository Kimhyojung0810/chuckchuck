/**
 * /hi/stage 시안 A 「들어오자마자 채점당한다」 — 무대 위 사람 그래프의 움직임 좌표를 미리 계산한다 (2026-10-13).
 *
 * ⚠️ 정직성 — 이 좌표는 «녹화한 사람의 움직임이 아니다».
 *   서버에 팀원 발표 영상 · 랜드마크 녹화가 없었다(find *.mp4/*.webm · labs 픽스처 · booth_scan 실험실 출력 모두 확인).
 *   그래서 (1) 퍼블릭 도메인 그림 「모나리자」 한 장에 MediaPipe FaceLandmarker · PoseLandmarker 를 실제로 돌려 얻은 «한 장의 실제 랜드마크»
 *   (etc/labs/hi_stage/mona_landmarks.json) 를 뼈대로 쓰고, (2) 그 위에 호흡 · 고개(끄덕임 · 기울임 · 돌림) · 눈 깜박임 · 입 벌림 · 손짓을
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
const L = ctx.BoothScanLogic;
const base = JSON.parse(fs.readFileSync(path.join(HERE, 'mona_landmarks.json'), 'utf8'));
const AR = base.image[0] / base.image[1];   // 가로 정규 좌표에 곱해 세로와 같은 길이로

const LOOP_SEC = 8;
const FPS = 15;
const FRAMES = LOOP_SEC * FPS;
const STILL_T = 3.6;          // 정지 그림 · 움직임 줄이기 · 연출 끝 프레임 — 손짓이 올라가 칩 쪽을 가리키는 순간
const TAU = Math.PI * 2;

const graph = L.buildGraph();

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

function frameAt(t) {
  const face = {};
  const pose = {};
  for (const [k, v] of Object.entries(base.face)) face[k] = [v[0] * AR, v[1]];
  for (const [k, v] of Object.entries(base.pose)) pose[k] = [v[0] * AR, v[1], v[2]];

  // 호흡 — 4초에 한 번. 어깨 · 팔이 조금 오르내리고 머리가 따라간다
  const br = Math.sin(TAU * t / 4);
  for (const k of [11, 12, 13, 14, 15, 16]) pose[k][1] -= 0.006 * br * (k <= 12 ? 1 : 0.6);
  for (const k of Object.keys(face)) face[k][1] -= 0.004 * br;
  pose[0][1] -= 0.004 * br;

  // 고개 — 턱(152)을 축으로 기울임(roll) · 끄덕임(nod) · 돌림(yaw: 안쪽 점이 바깥 윤곽보다 더 움직인다)
  const chin = face[152].slice();
  const roll = (2.4 * Math.sin(TAU * t / 8) + 1.2 * gestureL(t)) * Math.PI / 180;
  const nod = 0.006 * Math.sin(TAU * 3 * t / 8) * speaking(t);
  const yaw = 0.016 * Math.sin(TAU * t / 8 + 1.3) + 0.012 * gestureL(t);
  const cx = (face[234][0] + face[454][0]) / 2;
  const half = Math.abs(face[454][0] - face[234][0]) / 2;
  const oval = new Set(L.FACE_PARTS[0].idx.map(String));
  for (const [k, p] of Object.entries(face)) {
    const depth = oval.has(k) ? Math.max(0, 1 - Math.abs(p[0] - cx) / half) * 0.6 : (k === '4' || k === '1' || k === '195' ? 1 : 0.75);
    let x = p[0] + yaw * depth;
    let y = p[1] + nod * Math.max(0, (chin[1] - p[1]) / 0.2);
    const dx = x - chin[0], dy = y - chin[1];
    face[k] = [chin[0] + dx * Math.cos(roll) - dy * Math.sin(roll), chin[1] + dx * Math.sin(roll) + dy * Math.cos(roll)];
  }

  // 눈 깜박임 — 위 눈꺼풀 점이 아래 눈꺼풀 쪽으로
  const bl = blink(t);
  for (const [up, low] of [[160, 144], [158, 153], [387, 373], [385, 380], [159, 145], [386, 374]]) {
    if (!face[up] || !face[low]) continue;
    face[up][1] += (face[low][1] - face[up][1]) * 0.85 * bl;
  }

  // 입 — 말하는 동안 아랫입술이 음절 박자로 벌어진다(11 · 17 번 겹친 박자)
  const open = 0.011 * speaking(t) * Math.max(0, 0.55 * Math.sin(TAU * 11 * t / 8) + 0.45 * Math.sin(TAU * 17 * t / 8 + 0.7));
  for (const k of [321, 17, 91]) face[k][1] += open;
  for (const k of [61, 291]) face[k][1] += open * 0.35;

  // 손짓 — 왼손(영상 오른쪽, 칩이 있는 쪽)을 들어 옆을 가리키고, 질문 답 때 오른손을 조금 든다
  const gL = gestureL(t);
  if (gL > 0) {
    const sh = pose[11];
    const wob = 0.008 * Math.sin(TAU * 5 * t / 8);
    const elbow = [sh[0] + 0.07, sh[1] + 0.2];
    const wrist = [sh[0] + 0.2, sh[1] + 0.05 + wob];
    pose[13] = [pose[13][0] + (elbow[0] - pose[13][0]) * gL, pose[13][1] + (elbow[1] - pose[13][1]) * gL, pose[13][2]];
    pose[15] = [pose[15][0] + (wrist[0] - pose[15][0]) * gL, pose[15][1] + (wrist[1] - pose[15][1]) * gL, pose[15][2]];
  }
  const gR = gestureR(t);
  if (gR > 0) {
    pose[16] = [pose[16][0] - 0.05 * gR, pose[16][1] - 0.14 * gR, pose[16][2]];
    pose[14] = [pose[14][0] + 0.02 * gR, pose[14][1] - 0.05 * gR, pose[14][2]];
  }

  // booth_scan_logic 의 한 줄 형식(얼굴 x,y · 몸 x,y,vis)으로 묶어 nodeTargets 에 그대로 넘긴다
  const faceArr = L.PICK_FACE.flatMap((i) => face[i]);
  const poseArr = L.PICK_POSE.flatMap((i) => pose[i]);
  return L.nodeTargets(graph, { face: faceArr, pose: poseArr });
}

// ── 모든 프레임 + 정지 프레임을 계산하고 상자에 맞춘다 ──
const raw = Array.from({ length: FRAMES }, (_, f) => frameAt(f / FPS));
const still = frameAt(STILL_T);
let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
for (const fr of [...raw, still]) for (const p of fr) {
  if (!p) throw new Error('빠진 노드가 있어요 — 몸 점 visibility 를 확인해요');
  minX = Math.min(minX, p[0]); maxX = Math.max(maxX, p[0]); minY = Math.min(minY, p[1]); maxY = Math.max(maxY, p[1]);
}
const pad = 0.04;
const span = Math.max(maxX - minX, maxY - minY) * (1 + 2 * pad);
const W = 1000;
const H = Math.round(W * (maxY - minY) * (1 + 2 * pad) / ((maxX - minX) + 2 * pad * (maxY - minY)));
const sx = W / ((maxX - minX) + 2 * pad * (maxY - minY));
const ox = minX - pad * (maxY - minY), oy = minY - pad * (maxY - minY);
const q = (p) => [Math.round((p[0] - ox) * sx), Math.round((p[1] - oy) * sx)];
void span;

const nodeAt = (key) => graph.nodes.findIndex((n) => n.key === key);
const out = {
  schema: 'chuckchuck.hi-stage-pose',
  version: 1,
  note: '절차적 움직임 — 퍼블릭 도메인 그림 한 장의 실제 랜드마크(MediaPipe) 위에 호흡·고개·깜박임·입·손짓을 계산해 입혔어요. 사람을 녹화한 좌표가 아니에요.',
  fps: FPS,
  box: [W, H],
  still_t: STILL_T,
  nodes: graph.nodes.map((n) => [n.group, n.kind === 'iris' ? 1 : 0]),
  edges: graph.edges,
  anchors: { voice: nodeAt('face:17'), hand: nodeAt('pose:15'), head: nodeAt('face:10') },
  /** 장면(근거 칩)과 고리 시간 — 0 말 빠르기 · 1 3장 핵심 주장(손짓) · 2 질문 답 */
  moments: [[0, 2.0, 'pace'], [2.0, 4.8, 'claim'], [4.8, 7.0, 'qa'], [7.0, 8.0, 'pace']],
  frames: raw.map((fr) => fr.flatMap(q)),
  still: still.flatMap(q),
};
fs.mkdirSync(path.join(WEB, 'data/hi_stage'), { recursive: true });
const jsonPath = path.join(WEB, 'data/hi_stage/pose.json');
fs.writeFileSync(jsonPath, JSON.stringify(out));

// ── JS 없이 보이는 첫 그림 — 정지 프레임을 인라인 SVG 로 ──
const sp = still.map(q);
const lines = graph.edges.map(([a, b]) => `M${sp[a][0]} ${sp[a][1]}L${sp[b][0]} ${sp[b][1]}`).join('');
const dots = graph.nodes.map((n, i) => (n.kind === 'iris' ? '' : `M${sp[i][0] - 8} ${sp[i][1]}a8 8 0 1 0 16 0a8 8 0 1 0-16 0`)).join('');
const iris = graph.nodes.map((n, i) => (n.kind === 'iris' ? `<circle cx="${sp[i][0]}" cy="${sp[i][1]}" r="9"/>` : '')).join('');
const svg = `<svg class="fig-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMax meet" aria-hidden="true" focusable="false">`
  + `<path d="${lines}" fill="none" stroke="#CEFADC" stroke-opacity=".5" stroke-width="3" stroke-linecap="round"/>`
  + `<path d="${dots}" fill="#0CAF68" stroke="#CEFADC" stroke-opacity=".7" stroke-width="2"/>`
  + `<g fill="#ECFFF7">${iris}</g></svg>`;
const htmlPath = path.join(WEB, 'intro_stage.html');
if (fs.existsSync(htmlPath)) {
  const html = fs.readFileSync(htmlPath, 'utf8');
  const re = /(<!-- stage-svg:start[^>]*-->)[\s\S]*?(<!-- stage-svg:end -->)/;
  if (!re.test(html)) throw new Error('intro_stage.html 에 stage-svg 표시가 없어요');
  fs.writeFileSync(htmlPath, html.replace(re, `$1${svg}$2`));
}
console.log(`pose.json ${fs.statSync(jsonPath).size}B · ${graph.nodes.length} nodes · ${graph.edges.length} edges · box ${W}x${H} · svg ${svg.length}B`);
