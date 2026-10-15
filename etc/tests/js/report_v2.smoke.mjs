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
const loose = selectors.flatMap((s) => s.split(',').map((x) => x.trim())).filter((x) => x && !/^(\.rv2\b|body\.rv2-page\b|(html\.sx-studio )?#app\.rv2-host\b)/.test(x));
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

// 하네스 자가 검사 — 범위 밖 규칙을 넣으면 잡는가
const badLoose = ['body', '.rv2 .ok'].filter((x) => !/^(\.rv2\b|body\.rv2-page\b|#app\.rv2-host\b)/.test(x));
check('하네스가 회귀를 잡는다', badLoose.length === 1);

if (failed) { console.log(`\n${failed} failed`); process.exit(1); }
console.log('\nreport_v2: all ok');
