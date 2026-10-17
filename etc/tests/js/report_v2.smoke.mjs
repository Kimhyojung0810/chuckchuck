/**
 * 리포트 2.0 앱 연결 스모크 — 입력 묶음(ReportV2.inputFromApp) · 스타일이 앱을 덮지 않는가(.rv2 범위) · 저장본 줄이기(app.js rv2TranscriptExtras).
 *
 *   node etc/tests/js/report_v2.smoke.mjs
 *
 * 마지막 케이스는 하네스 자가 검사.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const WEB = path.join(ROOT, 'main/web');
const ctx = { window: {}, document: { getElementById: () => null } };
vm.runInNewContext(readFileSync(path.join(WEB, 'js/report_v2.js'), 'utf8'), ctx);
const { inputFromApp } = ctx.window.ReportV2;

let failed = 0;
function check(name, ok) {
  if (ok) console.log(`  ok  ${name}`);
  else { failed++; console.log(`  FAIL ${name}`); }
}

// ─── 입력 묶음 ───
const po = { graph: { file_name: 'a.pptx', nodes: [] }, alignment: { items: [] }, score: { score: 70 },
  transcript: { full_text: '안녕', duration_sec: 3 } };
const words = [{ text: '안녕', start_sec: 0.1, end_sec: 0.5 }];
const a = inputFromApp({ pipelineOut: po, words, marks: [{ slide_no: 1, start_sec: 0, end_sec: 3 }], deck: { audio_url: '/x.m4a' } });
check('저장본에 단어가 없으면 따로 받은 단어로 채운다', a.transcript.words.length === 1 && a.transcript.marks.length === 1);
check('원래 transcript 를 바꾸지 않는다', !po.transcript.words);
check('녹음 · 단어가 있으면 「없어요」 안내가 없다', !a.provenance.words && !a.provenance.audio);
const b = inputFromApp({ pipelineOut: po, deck: {}, qa: { questions: [], results: [] }, saved: ' (2026.10.16 10:00)' });
check('단어 · 녹음이 없으면 그렇다고 적는다', /장 단위/.test(b.provenance.words) && /다시 들을 수 없어요/.test(b.provenance.audio));
check('저장본이면 언제 것인지 적는다', /2026\.10\.16/.test(b.provenance.presentation));
check('Q&A 결과가 비면 qa 는 없음(전환점 화면이 「기록이 없어요」)', b.qa === null);
check('덱 제목이 없으면 그래프 파일 이름', b.deck.title === 'a.pptx');
check('분석 결과는 그대로 옮긴다(새 판정 없음)', b.score === po.score && b.alignment === po.alignment);

// ─── 스타일이 앱을 덮지 않는다 — 모든 규칙이 .rv2 아래(앱 app.css 와 토큰 이름이 겹친다: --bg · --ink · --accent …) ───
const css = readFileSync(path.join(WEB, 'css/report_v2.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const selectors = [];
let depth = 0; let buf = ''; const kf = [];
for (const ch of css) {
  if (ch === '{') {
    const sel = buf.trim(); buf = '';
    if (sel.startsWith('@keyframes')) kf.push(depth);
    if (!sel.startsWith('@') && !kf.length) selectors.push(sel);
    depth += 1;
  } else if (ch === '}') {
    depth -= 1; buf = '';
    if (kf.length && kf[kf.length - 1] === depth) kf.pop();
  } else buf += ch;
}
const loose = selectors.flatMap((s) => s.split(',').map((x) => x.trim())).filter((x) => x && !/^(\.rv2\b|:where\(\.rv2\b|body\.rv2-page\b|(html\.sx-studio )?#app\.rv2-host\b)/.test(x));
check(`스타일 규칙이 모두 .rv2 범위 안 (${selectors.length}개)`, selectors.length > 50 && loose.length === 0);
if (loose.length) console.log('    범위 밖:', loose.slice(0, 5));
check('토큰을 :root 에 두지 않는다', !/:root\b/.test(css));

// ─── app.js 저장본 줄이기 ───
const appSrc = readFileSync(path.join(WEB, 'js/app.js'), 'utf8');
const cut = (name) => { const m = appSrc.match(new RegExp(`function ${name}\\([\\s\\S]*?\\n}\\n`)); return m ? m[0] : ''; };
const box = {};
vm.runInNewContext(`const RV2_WORDS_MAX = 4000;\n${cut('rv2TranscriptExtras')}\nthis.f = rv2TranscriptExtras;`, box);
const many = Array.from({ length: 4100 }, (_, i) => ({ text: `w${i}`, start_sec: i * 0.333333, end_sec: i * 0.333333 + 0.2, extra: 'x' }));
const ex = box.f({ words: many, marks: [{ slide_no: 2, start_sec: 1.23456, end_sec: 9.87654, visit: 1 }], marks_estimated: true });
check('단어는 최대 4000개 · 소수 둘째 자리 · 필요한 필드만', ex.words.length === 4000 && ex.words[1].start_sec === 0.33 && !('extra' in ex.words[0]));
check('장 구간 · 추정 표시도 남긴다', ex.marks[0].start_sec === 1.23 && ex.marks_estimated === true);
check('transcript 가 없으면 빈 묶음', JSON.stringify(box.f(null)) === '{}');
check('Q&A 기록이 실제 질문의 node_id · slide_nos 를 읽는다(빈 개념 · 장 버그)', /src\.node_id/.test(cut('recordQaHistory')) && /src\.slide_nos/.test(cut('recordQaHistory')));

// ─── Q&A 돌아보기 화면(js/report_v2_qa.js, 10-17) — 그래프 뷰모델 → 화면 글. 지어낸 칸 · 개발 용어 · 자리표시자가 없는가 ───
const gctx = { window: {} };
vm.runInNewContext(readFileSync(path.join(WEB, 'js/report_graph.js'), 'utf8'), gctx);
const qctx = { window: {} };
vm.runInNewContext(readFileSync(path.join(WEB, 'js/report_v2_qa.js'), 'utf8'), qctx);
const sample = JSON.parse(readFileSync(path.join(WEB, 'js/report_sample.js'), 'utf8').replace(/^[\s\S]*?window\.__RV2_SAMPLE = /, '').replace(/;\s*$/, ''));
const RG = gctx.window.ReportGraph;
const SV = RG.buildViewModel(RG.buildGraph({ ...sample, reportId: 's' }), sample);
const esc2 = (x) => String(x == null ? '' : x).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const QS = qctx.window.ReportV2Qa.screens({ esc: esc2, I: { chev: '', check: '', bang: '', q: '', redo: '', chat: '' }, asset: (x) => x, V: () => SV, D: () => sample, QB: () => null, QBS: null,
  slideTag: (n) => `<i data-slide="${n}"></i>`, EMBED: false });
const cardHtml = QS.card();
check('홈 Q&A 카드: 질문마다 한 줄 · 판정 3단계 나눔', (cardHtml.match(/data-push="qa:/g) || []).length === SV.qa.filter((q) => q.result).length && /스스로 설명/.test(cardHtml) && /넘김/.test(cardHtml));
const screensHtml = SV.qa.filter((q) => q.result).map((q) => QS.qa(q.id).html).join('');
check('질문 화면: 30초 뼈대(결론 → 근거 → 잇기) · 판정 · 내 답', /30초 뼈대/.test(screensHtml) && /결론 먼저/.test(screensHtml) && /근거 하나/.test(screensHtml) && /내 답/.test(screensHtml));
check('공개 샘플 Q&A 에 자리표시자 · 개발 용어가 없다', !/어느 정도|decided_by|F-0\d|rehearsal_flow|\/api\//.test(screensHtml + cardHtml + JSON.stringify(sample.qa) + Object.values(sample.provenance).join(' ')));
check('공개 샘플: Q&A 와 「질문은 이렇게 골랐어요」 판이 같은 판(질문 글이 판 후보 · 3번+ 에 있다)', (() => {
  const b = JSON.parse(readFileSync(path.join(WEB, 'js/report_qaboard_sample.js'), 'utf8').replace(/^[\s\S]*?window\.__RV2_QA_BOARD = /, '').replace(/;\s*$/, ''));
  const qs = [...b.candidates.map((c) => c.question), ...(b.rounds || []).map((r) => r.question)];
  return sample.qa.results.every((r) => qs.includes(r.question));
})());
const emptyQS = qctx.window.ReportV2Qa.screens({ esc: esc2, I: {}, asset: (x) => x, V: () => ({ qa: [] }), D: () => ({}), QB: () => null, QBS: null, slideTag: () => '', EMBED: false });
check('Q&A 를 안 했으면 빈 상태 + 「Q&A 연습하기」', /Q&A를 하면/.test(emptyQS.card()) && /Q&A 연습하기/.test(emptyQS.card()));

// ─── 다시 보기 「순간」(10-17 바퀴 4) — 진단 근거 · 발표 태도 장면을 녹음 시각으로. Q&A 는 넣지 않는다 ───
const RV = ctx.window.ReportV2;
const dur = SV.duration_sec;
const cardsBeh = { present: { status: 'ok', t0: 2000, cards: [
  { kind: 'lookaway', observation: '2장에서 4.5초 동안 화면 쪽이 아니라 다른 곳을 향했어요', scene: { seg: 's2', where: '2장', sec: 10, dur: 4.5 } },
  { kind: 'down', observation: '2장에서 4.5초 동안 아래를 봤어요', scene: { seg: 's2', where: '2장', sec: 10.4, dur: 4.5 } },   // 같은 장면 — 한 번만
  { kind: 'sway', observation: '멀리', scene: { seg: 's3', where: '3장', sec: dur + 30, dur: 8 } },                          // 녹음 밖 — 버린다
  { kind: 'gesture_speech', observation: '장면 없음', scene: null },
  { kind: 'lookaway', observation: '질문', scene: { seg: 'q1', where: '1번째 질문', sec: 5, dur: 4 } },                      // Q&A — 따로
] }, qa: { status: 'ok', cards: [{ kind: 'lookaway', observation: 'qa', scene: { seg: 'q1', sec: 3, dur: 4 } }] } };
const MS = RV.momentsOf(SV, cardsBeh);
const beh = MS.filter((m) => m.lane === 'beh');
check('발표 태도 장면 → 녹음 시각(sec + t0) · 같은 장면 한 번 · 녹음 밖 · 장면 없음 · Q&A 는 뺀다', beh.length === 1 && beh[0].t === 12 && beh[0].slide === 2 && beh[0].end === 16.5);
check('진단 근거 순간 — 근거가 있는 시각만, 판정 색 · 진단 id 를 단다', MS.filter((m) => m.lane === 'fix').length > 0
  && MS.filter((m) => m.lane === 'fix').every((m) => m.insight && ['mid', 'ct', 'ok'].includes(m.tone) && m.t >= 0 && m.t <= dur + 1));
check('순간은 시각 순', MS.every((m, k) => k === 0 || MS[k - 1].t <= m.t));
const sumBeh = { present: { status: 'ok', summary: { events: [{ k: 'down', seg: 's1', t: 3, d: 2.4 }, { k: 'sway', seg: 's2', t: 20, d: 8 }, { k: 'lookaway', seg: 'q2', t: 9, d: 4 }] } } };
const sb = RV.momentsOf(SV, sumBeh).filter((m) => m.lane === 'beh');
check('숫자 요약(서버 보관본)만 있어도 장면 문장을 만든다(장 장면만)', sb.length === 2 && sb[0].title === '1장에서 2.4초 동안 아래를 봤어요' && /몸이 좌우로/.test(sb[1].title));
check('카메라 분석이 없거나 못 쟀으면 태도 순간이 없다', RV.momentsOf(SV, { present: { status: 'none' } }).every((m) => m.lane === 'fix')
  && RV.momentsOf(SV, null).every((m) => m.lane === 'fix') && RV.momentsOf(SV, { present: { status: 'unmeasured', cards: cardsBeh.present.cards } }).every((m) => m.lane === 'fix'));
check('「그 순간 듣기」 주소가 같은 순간으로 돌아온다(진단 · 태도 모두)', MS.every((m) => RV.momentAt(MS, RV.momentRoute(m).slice('replay:'.length)) === m));
check('주소 인자가 순간이 아니면 null (진단 id 만 · 빈 값 · 먼 시각)', RV.momentAt(MS, 'I:x') === null && RV.momentAt(MS, '') === null && RV.momentAt(MS, '@9999') === null);
const U = [{ id: 'U1', start: 1, end: 4, text: '하나' }, { id: 'U2', start: 6, end: 9, text: '둘' }];
check('그때 한 말 — 시각을 품은 발화 · 구간이 겹치는 발화 · 3초 안 가장 가까운 발화 · 없으면 null',
  RV.lineAt(U, 2).id === 'U1' && RV.lineAt(U, 4.5, 7).id === 'U2' && RV.lineAt(U, 4.6).id === 'U1' && RV.lineAt(U, 5.4).id === 'U2' && RV.lineAt(U, 20) === null);
const rctx = { window: {} };
vm.runInNewContext(readFileSync(path.join(WEB, 'js/behavior_report.js'), 'utf8'), rctx);
const bhHtml = rctx.window.BehaviorReport.rv2Html({ present: { status: 'ok', metrics: {}, areas: [], first: { text: '첫', slide: 2, sec: 10 },
  cards: [{ observation: '장면', scene: { seg: 's3', where: '3장', sec: 24.2 }, conf: '높음' }, { observation: '장면 없음', scene: null }] } });
check('발표 태도 화면이 장면 시각(data-sec)을 단다 — 리포트 쪽이 「그 순간 듣기」 를 붙인다', /bh-hero"[^>]*data-sec="10"/.test(bhHtml) && /bh-scene" data-sec="24.2"/.test(bhHtml) && (bhHtml.match(/data-sec=/g) || []).length === 2);
const rv2Src = readFileSync(path.join(WEB, 'js/report_v2.js'), 'utf8');
check('다시 보기는 「그 순간 듣기」 로 열 때만 바로 소리를 낸다(다시 그리기 · 복원에선 안 튼다)', /autoPlayNext = false; select\(el, pick, \{ sound \}\)/.test(rv2Src) && /function goMoment\(route\) \{ if \(busy\) return; autoPlayNext = !!audio;/.test(rv2Src));
check('옛 시트(nv-sheet)는 걷었다 — 표시는 한 줄 설명으로', !/nv-sheet/.test(rv2Src) && !/nv-sheet/.test(css));

// 하네스 자가 검사 — 범위 밖 규칙을 넣으면 잡는가
const badLoose = ['body', '.rv2 .ok'].filter((x) => !/^(\.rv2\b|body\.rv2-page\b|#app\.rv2-host\b)/.test(x));
check('하네스가 회귀를 잡는다', badLoose.length === 1);

if (failed) { console.log(`\n${failed} failed`); process.exit(1); }
console.log('\nreport_v2: all ok');
