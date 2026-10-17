/**
 * 리포트 문장 검증 (바퀴 5) — 「리포트가 한 말」 이 정답 영상의 사실과 맞나. 엔진 → 요약 → 리포트 문장 사슬 전체를 본다.
 * (프레임 정확도는 etc/labs/behavior_cv 가 따로 잰다. 여기는 그 숫자가 문장 · 장 · 시각 · 게이트 까닭으로 옮겨질 때 틀리지 않나.)
 *
 *   node report_truth.mjs --storage <clip>.storage.json --gt <clip>.gt.json [--dom <clip>.dom.json] [--relogic] [--json out.json]
 *
 * 재료: run.py --init-js truth_tap.js --storage-out 이 남긴 저장소 — 'cheokcheok:last-report'(리포트가 그린 발표 태도) +
 *       'lab:truth-rows:present|qa'(엔진 줄마다 정답 영상 프레임 번호 __f). --dom 은 report_truth_cap.py 가 390 폭에서 뽑은 화면 글.
 * --relogic: 저장된 줄을 **지금** behavior_cv_logic.js 로 다시 분석하고 지금 behavior_report.js 로 다시 그려 본다(고친 뒤 브라우저 없이 확인).
 *
 * 규칙(정답 → 기대):
 *  - 정답 시간축 = 엔진 줄마다 그 순간 정답 프레임. 장(seg)은 그 줄의 앱 장. 「이탈」 = 사람 있음 & 정면 아님(사이 각도 포함)이 이어진 구간.
 *  - 리포트가 짚은 장면(먼저 살펴볼 한 가지 · 장면 카드 · 다시 보기 태도 막대)은 하나하나 같은 종류의 정답 구간과 시각 ±2초 · 장 ±1 로 맞아야 한다(지어내기 0).
 *  - 정답의 가장 긴 이탈(4초+)은 어딘가에 짚혀야 한다(시각 ±2초 · 장 ±1).
 *  - 갈래 낱말(화면 쪽 · 3초 이탈 · 아래 · 흔들림 · 손 · 구도)은 정답 몫으로 낸 낱말 단계와 맞아야 한다(경계 ±0.05 는 이웃 단계도 맞음).
 *  - 정답에 흔들림이 없으면 흔들림 낱말은 「거의 없어요」 거나 잴 수 없음, 흔들림 카드 · 막대 없음.
 *  - 게이트: 어두움(정답 밝기 < 40) · 멀리(얼굴 폭 < 0.08) · 사람 없음은 「이번엔 잴 수 없었어요」 + 그 까닭이어야 하고, 그때 장면 문장은 하나도 없어야 한다.
 *  - 손: 사실만(판단 · 감정 낱말 없음). 화면 전체에 감정 · 자신감 · 좋고 나쁨 낱말 없음.
 *  - Q&A 질문별 줄: 그 질문 동안 정답 정면 몫의 단계와 맞아야 한다.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const WEB = path.join(ROOT, 'main/web/js');
const argv = process.argv.slice(2);
const opt = (k, d = '') => { const i = argv.indexOf(`--${k}`); return i >= 0 ? argv[i + 1] : d; };
const flag = (k) => argv.includes(`--${k}`);

/* ── 코드 올리기 (원본 그대로 vm 에) ── */
const win = { console };
win.window = win; win.self = win;
vm.createContext(win);
vm.runInContext(readFileSync(path.join(WEB, 'behavior_cv_logic.js'), 'utf8'), win, { filename: 'behavior_cv_logic.js' });
vm.runInContext(readFileSync(path.join(WEB, 'behavior_report.js'), 'utf8'), win, { filename: 'behavior_report.js' });
const rvx = { window: {}, document: { getElementById: () => null } };
vm.runInNewContext(readFileSync(path.join(WEB, 'report_v2.js'), 'utf8'), rvx);
const L = win.BehaviorCvLogic; const BR = win.BehaviorReport; const RV = rvx.window.ReportV2;

/* ── 재료 ── */
const storage = JSON.parse(readFileSync(opt('storage'), 'utf8'));
const ls = {};
(storage.origins || []).forEach((o) => (o.localStorage || []).forEach((it) => { ls[it.name] = it.value; }));
const J = (k) => { try { return JSON.parse(ls[k] || 'null'); } catch (_) { return null; } };
const last = J('cheokcheok:last-report') || {};
const gt = JSON.parse(readFileSync(opt('gt'), 'utf8'));
const dom = opt('dom') ? JSON.parse(readFileSync(opt('dom'), 'utf8')) : null;
const rowsOf = { present: J('lab:truth-rows:present') || [], qa: J('lab:truth-rows:qa') || [] };

function viewOf(rows, phase) {
  if (!rows.length) return L.none('카메라로 본 기록이 없어요', phase);
  const res = L.analyze(rows, { phase });
  return { ...res, raw: undefined, summary: L.summaryOf(res) };
}
const B = flag('relogic') ? { present: viewOf(rowsOf.present, 'present'), qa: rowsOf.qa.length ? viewOf(rowsOf.qa, 'qa') : (last.behavior || {}).qa } : (last.behavior || {});
const P = B.present || {};
const durSec = (last.transcript && last.transcript.duration_sec) || ((last.pipelineOut || {}).transcript || {}).duration_sec || 139.7;

/* ── 정답 시간축 ── */
function gtSeq(rows) {
  const list = rows.filter((r) => Number.isFinite(r.t)).slice().sort((a, b) => a.t - b.t);
  return list.map((r, i) => {
    const nx = list[i + 1];
    const dt = Math.min(1000, Math.max(0, nx ? nx.t - r.t : 200));
    const f = Number.isInteger(r.__f) && r.__f >= 0 && r.__f < gt.frames.length ? gt.frames[r.__f] : null;
    return { t: r.t, dt, seg: r.seg || '', F: f };
  });
}
/** 조건이 이어진 구간 — 정답 프레임이 없거나 1초 넘게 끊기면 끊는다 */
function gtRuns(seq, pred, minMs) {
  const out = []; let cur = null;
  seq.forEach((x, i) => {
    const gap = i > 0 ? x.t - seq[i - 1].t : 0;
    if (x.F && pred(x.F) && !(cur && gap > 1000)) {
      if (!cur) cur = { start: x.t, end: x.t + x.dt, seg: x.seg, labels: {} };
      cur.end = x.t + x.dt; cur.labels[x.F.label] = (cur.labels[x.F.label] || 0) + x.dt;
    } else { if (cur) out.push(cur); cur = x.F && pred(x.F) ? { start: x.t, end: x.t + x.dt, seg: x.seg, labels: { [x.F.label]: x.dt } } : null; }
  });
  if (cur) out.push(cur);
  return out.map((r) => ({ ...r, dur: r.end - r.start })).filter((r) => r.dur >= minMs);
}
const share = (seq, pred, base = (F) => F.present) => {
  let a = 0; let n = 0;
  seq.forEach((x) => { if (!x.F || !base(x.F)) return; n += x.dt; if (pred(x.F)) a += x.dt; });
  return n ? a / n : null;
};
const segNo = (seg) => (/^[sq]\d+$/.test(seg || '') ? Number(seg.slice(1)) : null);
const mmss = (ms) => { const s = Math.max(0, Math.round(ms / 1000)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
const lv3 = (v, lo, hi) => (v < lo ? 0 : v < hi ? 1 : 2);
/** 정답 몫 [a, b] (± 여유) 가 걸치는 낱말 단계들 */
const levelsOf = (a, b, lo, hi, tol = 0.05) => { const s = new Set(); for (let v = Math.max(0, a - tol); v <= b + tol + 1e-9; v += 0.005) s.add(lv3(v, lo, hi)); return [...s]; };

const C = L.CFG;
const seq = gtSeq(rowsOf.present);
const covered = seq.filter((x) => x.F).length / Math.max(1, seq.length);
const present = share(seq, (F) => F.present, () => true) ?? 0;
const notFront = (F) => F.present && F.label !== 'front';
const GT = {
  covered, present,
  frontLo: share(seq, (F) => F.label === 'front' && !F.ignore), frontHi: share(seq, (F) => F.label === 'front' || F.ignore),
  down: share(seq, (F) => F.label === 'down'),
  gesture: share(seq, (F) => !!F.gesture), sway: share(seq, (F) => !!F.sway),
  look: gtRuns(seq, notFront, C.lookAwayMs), lookLoose: gtRuns(seq, notFront, 1500),
  lookStrict: gtRuns(seq, (F) => F.present && ['left', 'right', 'down'].includes(F.label), 3500),
  downs: gtRuns(seq, (F) => F.label === 'down', 1500),
  sways: gtRuns(seq, (F) => !!F.sway, 1000),
  bright: (() => { const b = seq.filter((x) => x.F).map((x) => x.F.bright); return b.length ? b.reduce((p, q) => p + q, 0) / b.length : null; })(),
  face: (() => { const w = seq.filter((x) => x.F && x.F.face).map((x) => x.F.face[2]).sort((a, b) => a - b); return w.length ? w[w.length >> 1] : null; })(),
  presMin: seq.reduce((n, x) => n + (x.F && x.F.present ? x.dt : 0), 0) / 60000,
};
// 정답이 보는 게이트 — 엔진 게이트와 같은 문턱(밝기 40 · 얼굴 폭 0.08 · 사람 있음 0.6)
GT.gate = GT.bright !== null && GT.bright < C.darkBr ? 'dark' : present < 0.3 ? 'absent' : present < C.minPresence ? 'presence' : GT.face !== null && GT.face < C.minFaceW ? 'far' : '';

/* ── 리포트가 한 말 (화면 글이 있으면 그것, 없으면 지금 코드로 그린 것) ── */
const strip = (h) => String(h || '').replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/\s+/g, ' ').trim();
const H = BR.headline(B);
const homeLine = H.status === 'none' ? '' : H.status === 'ok' ? H.oneLine : `이번엔 잴 수 없었어요 — ${H.oneLine}`;
const titles = (((last.deck || {}).slides) || []).map((s) => s.title);
const html = BR.rv2Html(B, { titles, questions: [] });
const said = {
  home: dom && !flag('relogic') ? (dom.home.beh_row || '') : homeLine,
  text: dom && !flag('relogic') ? (dom.attitude || {}).text || '' : strip(html),
  areas: dom && !flag('relogic') ? (dom.attitude || {}).areas || []
    : (String(html).split('bh-areas2')[1] || '').split(/<h3|<details/)[0].split('bh-arow').slice(1).map((h) => strip(`<${h}`).replace(/^[^ ]*?"?>\s*/, '')),
};
const moments = RV.momentsOf({ duration_sec: durSec, issues: [], strengths: [] }, B).filter((m) => m.lane === 'beh');

/* ── 판정 ── */
const checks = [];
const add = (rule, expected, got, verdict, note = '') => checks.push({ rule, expected, got, verdict, note });
const M = P.metrics || {};
const okP = P.status === 'ok';
const WORDS = L.WORDS;

// 0. 재료가 있나
add('재료', '엔진 줄 · 정답 프레임', `줄 ${seq.length} · 정답 맞춘 몫 ${Math.round(covered * 100)}%`, seq.length > 50 && covered > 0.9 ? 'PASS' : 'FAIL');

// 1. 게이트
const anyClaim = (P.cards || []).length + (P.first ? 1 : 0) + moments.length;
if (GT.gate) {
  const want = { dark: /어두웠어요/, absent: /얼굴이 화면에 거의 없었어요|사람이 화면에 거의 없었어요|잡힌 시간이 짧았어요/, presence: /잡힌 시간이 짧았어요|거의 없었어요/, far: /너무 멀어요/ }[GT.gate];
  const gazeWhy = (M.gaze && M.gaze.why) || P.why || '';
  const gated = !(M.gaze && M.gaze.ok);
  add(`게이트(${GT.gate})`, `시선 갈래 「잴 수 없었어요」 + 까닭 ${want}`, gated ? `잴 수 없음 — ${gazeWhy}` : `쟀음 — ${(M.gaze || {}).word}`, gated && want.test(gazeWhy) ? 'PASS' : 'FAIL');
  add('게이트 — 지어내기 없음', '장면 문장 0 · 먼저 살펴볼 것 없음 · 태도 막대 0', `카드 ${(P.cards || []).length} · 먼저 ${P.first ? P.first.text : '없음'} · 막대 ${moments.length}`,
    // 멀리(far)면 얼굴 방향 · 흔들림만 못 잰다 — 구도(얼굴이 작아요) · 손 사실 카드는 잴 수 있던 사실이라 괜찮다. 장면(시각) 문장은 0
    GT.gate === 'far' || GT.gate === 'dark' || GT.gate === 'absent' ? (anyClaim === 0 || (GT.gate === 'far' && moments.length === 0 && (P.cards || []).every((c) => ['framing', 'gesture_speech'].includes(c.kind))) ? 'PASS' : 'FAIL') : 'PASS');
  add('게이트 — 홈 줄', '「잴 수 없었어요」 또는 구도처럼 잴 수 있던 사실만', said.home || '(줄 없음)',
    /잴 수 없었어요/.test(said.home) || (GT.gate === 'far' && /얼굴이 화면에서 작게/.test(said.home)) || (P.status === 'none' && !said.home) ? 'PASS' : 'FAIL');
}

// 2. 장면 하나하나 — 정답 구간과 맞나
const t0 = Number.isFinite(P.t0) ? P.t0 : (seq[0] ? seq[0].t : 0);
function matchScene(kind, seg, ms) {
  const pool = kind === 'down' ? [...GT.downs, ...GT.lookLoose.filter((r) => (r.labels.down || 0) > r.dur * 0.4)]
    : kind === 'sway' ? GT.sways : GT.lookLoose;
  const hit = pool.find((r) => (kind === 'sway' ? (ms >= r.start - 4000 && ms <= r.end) : Math.abs(r.start - ms) <= 2000)
    && (segNo(seg) === null || segNo(r.seg) === null || Math.abs(segNo(seg) - segNo(r.seg)) <= 1));
  return hit || null;
}
const sceneList = [];
if (okP) {
  (P.cards || []).filter((c) => c.scene && Number.isFinite(c.scene.sec)).forEach((c) => sceneList.push({ src: '장면 카드', kind: c.kind, seg: c.scene.seg, ms: c.scene.sec * 1000 + t0, text: c.observation }));
  moments.forEach((m) => {
    const c = (P.cards || []).find((x) => x.observation === m.title);
    sceneList.push({ src: '다시 보기 막대', kind: c ? c.kind : (/아래/.test(m.title) ? 'down' : /좌우/.test(m.title) ? 'sway' : 'lookaway'), seg: `s${m.slide}`, ms: m.t * 1000, text: `${mmss(m.t * 1000)} · ${m.slide}장 · ${m.title}` });
  });
}
sceneList.filter((s) => ['lookaway', 'down', 'sway'].includes(s.kind)).forEach((s) => {
  const h = matchScene(s.kind, s.seg, s.ms);
  add(`${s.src} 사실`, h ? `정답 ${s.kind} ${segNo(h.seg)}장 ${mmss(h.start)} ${(h.dur / 1000).toFixed(1)}초` : `정답 ${s.kind} 구간(±2초 · 장±1)`, `${s.text}`, h ? 'PASS' : 'FAIL');
});
// 먼저 살펴볼 한 가지
if (okP && P.first) {
  const f = P.first;
  if (['lookaway', 'down', 'sway'].includes(f.kind)) {
    const h = matchScene(f.kind, f.slide ? `s${f.slide}` : '', (f.sec ?? 0) * 1000 + t0);
    add('먼저 살펴볼 한 가지', h ? `정답 ${segNo(h.seg)}장 ${mmss(h.start)} ${(h.dur / 1000).toFixed(1)}초` : '같은 종류 정답 구간', `${f.text} (${f.slide || '-'}장 · ${mmss((f.sec ?? 0) * 1000)})`, h ? 'PASS' : 'FAIL');
  } else add('먼저 살펴볼 한 가지', '낱말 근거', f.text, 'PASS');
}
// 문장 속 숫자 = 엔진이 잰 값 (「10초 동안」 처럼 고정 글이 잰 값과 다르면 안 된다)
(P.cards || []).filter((c) => c.scene && Number.isFinite(c.scene.dur)).forEach((c) => {
  const m = /([\d.]+)초 동안/.exec(c.observation || '');
  if (!m) return;
  const v = Number(m[1]);
  add('문장 숫자 = 잰 값', `${c.scene.dur}초 (${c.kind})`, c.observation, Math.abs(v - c.scene.dur) <= 0.6 ? 'PASS' : 'FAIL');
});
// 같은 순간을 두 번 — 「먼저 살펴볼 한 가지」 와 장면 카드가 같은 장 · 1초 안이면 한 번만 보여야 한다
if (dom && !flag('relogic') && dom.attitude) {
  const A = dom.attitude;
  const hs = A.hero_sec !== null && A.hero_sec !== undefined ? Number(A.hero_sec) : null;
  const heroSlide = (/(\d+)장/.exec(A.hero_chip || '') || [])[1];
  const dup = hs === null ? [] : (A.scenes || []).filter((x) => x.sec !== null && Math.abs(Number(x.sec) - hs) <= 1 && (/(\d+)장/.exec(x.chip || '') || [])[1] === heroSlide);
  add('같은 순간 한 번만', '먼저 살펴볼 한 가지와 같은 장면 카드 없음', dup.length ? dup.map((x) => x.obs).join(' / ') : '없음', dup.length ? 'FAIL' : 'PASS');
} else if (okP && P.first && P.first.sec != null) {
  const seg = P.first.slide ? `s${P.first.slide}` : '';
  const dup = (P.cards || []).filter((c) => c.observation !== P.first.text && c.scene && c.scene.seg === seg && Math.abs(c.scene.sec - P.first.sec) <= 1);
  const shown = strip(html);
  const dupShown = dup.filter((c) => shown.split(c.observation).length > 1);
  add('같은 순간 한 번만', '먼저 살펴볼 한 가지와 같은 장면 카드 없음', dupShown.length ? dupShown.map((c) => c.observation).join(' / ') : '없음', dupShown.length ? 'FAIL' : 'PASS');
}
// 가장 긴 정답 이탈이 짚혔나
if (okP && M.lookaway && M.lookaway.ok) {
  const big = GT.look.filter((r) => r.dur >= 4000).sort((a, b) => b.dur - a.dur)[0];
  if (big) {
    const claimed = [...(P.cards || []).filter((c) => (c.kind === 'lookaway' || c.kind === 'down') && c.scene).map((c) => ({ seg: c.scene.seg, ms: c.scene.sec * 1000 + t0, text: c.observation })),
      ...(P.first && P.first.sec != null ? [{ seg: `s${P.first.slide}`, ms: P.first.sec * 1000 + t0, text: P.first.text }] : [])];
    const hit = claimed.find((c) => Math.abs(c.ms - big.start) <= 2000 && Math.abs((segNo(c.seg) || 0) - (segNo(big.seg) || 0)) <= 1);
    add('가장 긴 이탈 짚기', `${segNo(big.seg)}장 ${mmss(big.start)} ${(big.dur / 1000).toFixed(1)}초 (±2초 · 장±1)`, hit ? hit.text : `못 짚음 — 짚은 것: ${claimed.map((c) => `${segNo(c.seg)}장 ${mmss(c.ms)}`).join(', ') || '없음'}`, hit ? 'PASS' : 'FAIL');
  }
}

// 3. 낱말 단계
function wordCheck(name, kind, a, b, lo, hi, tol) {
  const m = M[kind];
  if (!m) return;
  if (a === null || a === undefined) return;
  const want = levelsOf(a, b, lo, hi, tol);
  const wtxt = want.map((k) => WORDS[kind].words[k]).join('|');
  if (!m.ok) { add(name, `${wtxt} (정답 ${Math.round(a * 100)}${b !== a ? `~${Math.round(b * 100)}` : ''}%)`, `잴 수 없음 — ${m.why}`, GT.gate ? 'PASS' : 'WARN', '잴 수 있었는데 안 잼'); return; }
  add(name, `${wtxt} (정답 ${Math.round(a * 100)}${b !== a ? `~${Math.round(b * 100)}` : ''}%)`, `${m.word} (${Math.round((m.value || 0) * 100)}%)`, want.includes(m.level) ? 'PASS' : 'FAIL');
}
if (!GT.gate || GT.gate === 'far') {
  if (!GT.gate) {
    wordCheck('화면 쪽 시간', 'gaze', GT.frontLo, GT.frontHi, C.gazeLo, C.gazeHi, 0.05);
    wordCheck('아래 본 시간', 'down', GT.down, GT.down, C.downLo, C.downHi, 0.05);
    const rateA = GT.lookStrict.length / Math.max(1 / 60, GT.presMin); const rateB = GT.look.length / Math.max(1 / 60, GT.presMin);
    const m = M.lookaway;
    if (m) {
      const want = levelsOf(Math.min(rateA, rateB), Math.max(rateA, rateB), C.awayPerMinLo, C.awayPerMinHi, 0.25);
      add('3초 넘게 벗어난 구간', `${want.map((k) => WORDS.lookaway.words[k]).join('|')} (정답 ${GT.lookStrict.length}~${GT.look.length}번)`, m.ok ? `${m.word} (${m.n}번)` : `잴 수 없음 — ${m.why}`, !m.ok ? 'WARN' : want.includes(m.level) ? 'PASS' : 'FAIL');
    }
    // 흔들림 — 정답에 없으면 「거의 없어요」 (드리프트 · 돌림은 흔들림 아님)
    const sm = M.sway;
    if (sm) {
      if (!GT.sways.length) add('흔들림(정답 없음)', '거의 없어요 · 카드 · 막대 없음', sm.ok ? `${sm.word} (${Math.round(sm.value * 100)}%)` : `잴 수 없음 — ${sm.why}`, !sm.ok || sm.level === 0 ? 'PASS' : 'FAIL');
      else {
        const longest = Math.max(...GT.sways.map((r) => r.dur));
        add('흔들림(정답 있음)', `가끔|자주 (정답 ${(GT.sways.reduce((n, r) => n + r.dur, 0) / 1000).toFixed(0)}초 · 가장 긴 ${(longest / 1000).toFixed(0)}초)`, sm.ok ? `${sm.word} (${Math.round(sm.value * 100)}%)` : `잴 수 없음 — ${sm.why}`,
          !sm.ok ? (/1초에 3장/.test(sm.why) ? 'PASS' : 'WARN') : sm.level >= 1 || longest < 8000 ? 'PASS' : 'FAIL');
      }
    }
    // Q&A 질문별
    const qa = B.qa;
    if (qa && qa.status === 'ok') {
      const qseq = gtSeq(rowsOf.qa);
      (qa.segs || []).filter((s) => /^q\d+$/.test(s.seg) && Number.isFinite(s.gaze) && s.enough !== false).forEach((s) => {
        const part = qseq.filter((x) => x.seg === s.seg);
        const a = share(part, (F) => F.label === 'front' && !F.ignore); const b = share(part, (F) => F.label === 'front' || F.ignore);
        if (a === null) return;
        const want = levelsOf(a, b, C.gazeLo, C.gazeHi, 0.05);
        const lvl = lv3(s.gaze, C.gazeLo, C.gazeHi);
        add(`Q&A 질문 ${s.seg.slice(1)}`, `화면 쪽 ${want.map((k) => WORDS.gaze.words[k]).join('|')} (정답 ${Math.round(a * 100)}~${Math.round(b * 100)}%)`, `화면 쪽 ${WORDS.gaze.words[lvl]} (${Math.round(s.gaze * 100)}%)`, want.includes(lvl) ? 'PASS' : 'FAIL');
      });
    }
  }
  wordCheck('손 움직임', 'gesture', GT.gesture, GT.gesture, C.gestLo, C.gestHi, 0.06);
  if (M.framing && M.framing.ok && GT.face !== null) {
    const want = GT.face < C.sizeLo - 0.02 ? [0] : GT.face > C.sizeHi + 0.02 ? [2] : GT.face < C.sizeLo + 0.02 ? [0, 1] : [1];
    add('구도', `${want.map((k) => WORDS.framing.words[k]).join('|')} (정답 얼굴 폭 ${Math.round(GT.face * 100)}%)`, `${M.framing.word}`, want.includes(M.framing.level) ? 'PASS' : 'FAIL');
  }
}

// 4. 말투 — 손은 사실만 · 감정 · 좋고 나쁨 낱말 없음
const BAN = /자신감|긴장|불안|초조|산만|어색|훌륭|잘했|못했|좋았|나빴|좋아요|나빠요|부족|과해요|지나쳐|감정|표정이/;
const handLine = said.areas.find((a) => /^손짓/.test(a)) || '';
const plain = said.text.replace(/표정이나 마음은 짐작하지 않아요/g, '');
add('말투(판단 · 감정 낱말 없음)', '관찰만', BAN.test(plain) ? plain.match(BAN)[0] : '없음', BAN.test(plain) ? 'FAIL' : 'PASS');
if (handLine) add('손 — 사실만', '움직임 양 · 말할 때/쉴 때 사실', handLine, BAN.test(handLine) ? 'FAIL' : 'PASS');

// 5. 화면 글 ↔ 묶음 (DOM 이 있을 때 — 그린 글이 묶음과 같은 말인가)
if (dom && !flag('relogic')) {
  add('홈 줄 = 묶음 첫 줄', homeLine || '(줄 없음)', dom.home.beh_row || '(줄 없음)', (dom.home.beh_row || '').includes(homeLine) || (!homeLine && !dom.home.beh_row) ? 'PASS' : 'FAIL');
  add('다시 보기 막대 수', `${moments.length}`, `${(dom.replay || {}).bars ? dom.replay.bars.length : 0}`, ((dom.replay || {}).bars || []).length === moments.length ? 'PASS' : 'FAIL');
}

const n = (v) => checks.filter((c) => c.verdict === v).length;
const verdict = n('FAIL') ? 'FAIL' : n('WARN') ? 'WARN' : 'PASS';
const summary = {
  clip: gt.name, verdict, pass: n('PASS'), fail: n('FAIL'), warn: n('WARN'),
  gt: { gate: GT.gate, front: [GT.frontLo, GT.frontHi].map((v) => v === null ? null : Math.round(v * 100)), down: GT.down === null ? null : Math.round(GT.down * 100), gesture: GT.gesture === null ? null : Math.round(GT.gesture * 100),
    look: GT.look.map((r) => `${segNo(r.seg)}장 ${mmss(r.start)} ${(r.dur / 1000).toFixed(1)}s`), sways: GT.sways.map((r) => `${segNo(r.seg)}장 ${mmss(r.start)} ${(r.dur / 1000).toFixed(1)}s`),
    bright: GT.bright && Math.round(GT.bright), face: GT.face && Math.round(GT.face * 100) / 100, covered: Math.round(covered * 100) },
  report: { status: P.status, home: said.home, first: P.first ? P.first.text : null, areas: (P.areas || []).map((a) => `${a.label}: ${a.word}`),
    scenes: (P.cards || []).map((c) => `${c.observation}${c.scene ? ` [${c.scene.where} ${mmss(c.scene.sec * 1000)}]` : ''}`), bars: moments.map((m) => `${mmss(m.t * 1000)} ${m.slide}장 ${m.title}`),
    qa: ((B.qa || {}).segs || []).map((s) => `${s.seg} ${Math.round((s.gaze || 0) * 100)}%`), quality: P.quality ? { fps: +(P.quality.fps || 0).toFixed(1), presence: +(P.quality.presence || 0).toFixed(2), dark: +(P.quality.dark || 0).toFixed(2), face: P.quality.face && +P.quality.face.toFixed(3), bright: P.quality.bright && Math.round(P.quality.bright) } : null },
  checks,
};
if (opt('json')) writeFileSync(opt('json'), JSON.stringify(summary, null, 1));
console.log(`== ${gt.name} ${verdict}  (PASS ${summary.pass} · FAIL ${summary.fail} · WARN ${summary.warn})${flag('relogic') ? '  [relogic]' : ''}`);
checks.forEach((c) => { if (c.verdict !== 'PASS' || flag('all')) console.log(`  ${c.verdict.padEnd(4)} ${c.rule} | 기대 ${c.expected} | 리포트 ${c.got}`); });
