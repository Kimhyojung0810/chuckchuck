/**
 * 리포트 2.0 「질문은 이렇게 골랐어요」 — 후보 판 뷰모델 스모크 (js/report_qaboard.js · 샘플 판 js/report_qaboard_sample.js).
 *
 *   node etc/tests/js/report_qaboard.smoke.mjs
 *
 * 마지막 케이스는 하네스 자가 검사.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const WEB = path.join(ROOT, 'main/web');
const ctx = { window: {} };
vm.runInNewContext(readFileSync(path.join(WEB, 'js/report_qaboard.js'), 'utf8'), ctx);
vm.runInNewContext(readFileSync(path.join(WEB, 'js/report_qaboard_sample.js'), 'utf8'), ctx);
const QB = ctx.window.ReportQaBoard;
const B = ctx.window.__RV2_QA_BOARD;

let failed = 0;
function check(name, ok) {
  if (ok) console.log(`  ok  ${name}`);
  else { failed++; console.log(`  FAIL ${name}`); }
}

check('판이 없거나 후보가 없으면 null (진입점이 「한 모델이 골랐어요」로)', QB.model(null) === null && QB.model({ candidates: [] }) === null);
const Q = QB.model(B, null);
check('샘플 판 — 네 모델 모두 이름이 있다', Q && Q.models.length === 4 && Q.models.every((m) => m.name && m.logo));
check('후보 = 통과 + 버림', Q.totals.written === B.candidates.length + B.dropped.length && Q.totals.passed === B.candidates.length);
check('서로 평가 수는 자기 표를 뺀다', Q.totals.reviews === B.candidates.reduce((n, c) => n + c.peer_scores.filter((p) => !p.self).length, 0));
check('Q&A 기록이 없으면 판의 순서 — 1·2번 묶음 + 3번부터 음성', !Q.fromQa && Q.asked[0].kind === 'pool' && Q.asked[1].kind === 'pool' && Q.asked[2].kind === 'voice' && Q.asked[2].n === 3);
check('물은 자리에 번호가 붙는다', Q.slots.find((s) => s.id === Q.asked[0].slot).asked[0] === 1);
check('버림 까닭이 사람 말로 다 풀린다', Q.reasons.every(([r]) => QB.REASON[r]));
const qa = { results: [{ id: 'e01', question: Q.asked[1].question + ' ' }, { id: 'x', question: '준비한 다른 질문이에요?' }] };
const Q2 = QB.model(B, qa);
check('Q&A 기록과 글자로 맞추면 실제 받은 순서 (띄어쓰기 무시)', Q2.fromQa && Q2.asked[0].uid === Q.asked[1].uid && Q2.asked[0].n === 1 && Q2.asked[1].kind === 'other');
check('가중 점수 0~100', QB.scoreOf({ core: 5, grounded: 5, specific: 5, clear: 5 }) === 100 && QB.scoreOf({ core: 1, grounded: 1, specific: 1, clear: 1 }) === 0);
const L = QB.layout([{ id: 't', kind: 'thesis' }, { id: 'c', kind: 'concept', parent_id: 't' }, { id: 'k', kind: 'claim', parent_id: 'c' }]);
check('미니맵 층은 노드 종류로 (개념 아래 주장도 주장 줄)', L.pos.t.d === 0 && L.pos.k.d === 1 && L.pos.c.d === 2);
check('판정 색 이름을 쓰지 않는다 (과정이지 판정이 아니다)', !/(?<![\w-])(?:t-ok|t-no|v-ok|v-no)\b|var\(--(?:ok|no|mid|ct)\)/.test(readFileSync(path.join(WEB, 'js/report_qaboard.js'), 'utf8')));

// 하네스 자가 검사 — 일부러 틀린 기대가 실패로 잡히는가
const before = failed;
check('(자가 검사) 틀린 기대는 실패한다', Q.totals.written === -1);
const caught = failed === before + 1;
failed = before;
check('하네스가 실패를 잡는다', caught);

if (failed) { console.log(`\n${failed}개 실패`); process.exit(1); }
console.log('\n모두 통과');
