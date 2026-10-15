/**
 * 발표 채점판 순수 계산 스모크 — 원본 main/web/studio-app/src/ui/scoreModel.js.
 *
 *   node etc/tests/js/score_model.smoke.mjs
 *
 * 왜 있나 — 채점판은 앱의 실제 결과만 보여야 한다. 판정 색 규칙(aligned→ok · missing→no · contradiction→ct · justified_skip→om,
 * 대체 판정 · 녹음 불일치 → na 「판정 안 함」)이 앱(app.js STATUS_FROM_VERDICT · conceptUnjudgedWhy)과 어긋나면 리포트와 다른 말을 한다.
 * 마지막 케이스는 하네스 자가 검사.
 */
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const M = await import(pathToFileURL(path.join(ROOT, 'main/web/studio-app/src/ui/scoreModel.js')).href);

let failed = 0;
function check(name, ok) {
  if (ok) console.log(`  ok  ${name}`);
  else { failed++; console.log(`  FAIL ${name}`); }
}

const graph = {
  thesis: 'T',
  nodes: [
    { id: 'T', label: '주장', weight: 0.8 },
    { id: 'A', label: '근거 A', weight: 0.9 },
    { id: 'B', label: '근거 B', weight: 0.4 },
    { id: 'A1', label: '세부 A1', weight: 0.95 },
    { id: 'X', label: '따로 선 개념', weight: 0.1 },
  ],
  edges: [{ from: 'T', to: 'A', kind: 'parent' }, { from: 'T', to: 'B', kind: 'parent' }, { from: 'A', to: 'A1', kind: 'parent' }, { from: 'B', to: 'X', kind: 'relates' }],
};

// 고르기 — 조상까지 함께
const two = M.pickNodes(graph, 3);
check('최대 수를 지킨다', two.length <= 3);
check('무거운 A1 을 고르면 조상 A · 뿌리 T 도 들어온다', ['T', 'A', 'A1'].every((id) => two.some((n) => n.id === id)));
const all = M.pickNodes(graph);
check('relates 는 부모가 아니다', all.find((n) => n.id === 'X').parent === null);
check('뿌리는 thesis', M.rootOf(all, 'T') === 'T');
const order = M.bfsOrder(all, 'T');
check('너비 우선 — 뿌리가 먼저', order[0] === 'T');
check('너비 우선 — 무거운 자식이 먼저', order.indexOf('A') < order.indexOf('B'));
check('끊긴 나무도 빠지지 않는다', order.includes('X') && order.length === all.length);
const links = all.filter((n) => n.parent).map((n) => ({ from: n.parent, to: n.id, kind: 'parent' }));
const pos = M.forceLayout(all, 'T', links, 800, 500);
check('뿌리는 가운데', pos.get('T').x === 0 && pos.get('T').y === 0);
check('판 밖으로 나가지 않는다', [...pos.values()].every((p) => (p.x / (800 * 0.46)) ** 2 + (p.y / (500 * 0.44)) ** 2 <= 1.0001));
const pos2 = M.forceLayout(all, 'T', links, 800, 500);
check('같은 그래프면 같은 배치', [...pos.keys()].every((id) => pos.get(id).x === pos2.get(id).x && pos.get(id).y === pos2.get(id).y));
check('깊이 — 부모를 따라 센다', pos.get('A1').depth === 2 && pos.get('T').depth === 0);
const co = M.cooccurEdges([{ id: 'p', weight: 1, slide_nos: [1] }, { id: 'q', weight: .5, slide_nos: [1] }, { id: 'r', weight: .2, slide_nos: [2] }]);
check('같은 장 개념끼리만 잇는다', co.length === 1 && co[0].kind === 'slide');
const secs = M.sectionsOf({ sections: [{ name: '도입', slide_nos: [1] }, { name: '결과', slide_nos: [2, 3] }] }, [{ id: 'a', slide_nos: [3, 1] }, { id: 'b', slide_nos: [2] }]);
check('섹션 — 처음 나온 장으로 묶는다', secs.find((x) => x.name === '도입').ids.includes('a') && secs.find((x) => x.name === '결과').ids.includes('b'));
const st = M.sectionStat(['a', 'b', 'c'], new Map([['a', 'ok'], ['b', 'na'], ['c', 'no']]), new Set(['a', 'b', 'c']));
check('섹션 비율 — 판정 안 함은 빼고 다룸 비율', st.judged === 2 && st.ok === 1 && st.pct === 50);
check('섹션 비율 — 판정한 게 없으면 null', M.sectionStat(['a'], new Map(), new Set()).pct === null);

// 판정 — 앱과 같은 규칙
const al = { basis: 'llm', speech_match: 'matched', items: [
  { node_id: 'T', verdict: 'aligned', decided_by: 'llm' },
  { node_id: 'A', verdict: 'missing', decided_by: 'llm' },
  { node_id: 'B', verdict: 'contradiction', decided_by: 'code' },
  { node_id: 'A1', verdict: 'justified_skip', decided_by: 'llm' },
  { node_id: 'X', verdict: 'missing', decided_by: 'fallback' },
] };
check('aligned → ok', M.verdictOf(al, 'T') === 'ok');
check('missing → no', M.verdictOf(al, 'A') === 'no');
check('contradiction → ct', M.verdictOf(al, 'B') === 'ct');
check('justified_skip → om', M.verdictOf(al, 'A1') === 'om');
check('대체 판정은 판정 안 함', M.verdictOf(al, 'X') === 'na');
check('녹음이 자료와 안 맞으면 전부 판정 안 함', M.verdictOf({ ...al, speech_match: 'unrelated' }, 'T') === 'na');
check('판정이 없으면 null(숫자를 만들지 않는다)', M.verdictOf(null, 'T') === null);
const t = M.tally(['ok', 'ok', 'no', 'na', null]);
check('셈', t.ok === 2 && t.no === 1 && t.na === 1);

// 단계 문구 — 실제 진행만
check('받아쓰는 중', M.phaseLine({ steps: { stt: 'run' } }).includes('받아쓰'));
check('그래프 전', M.phaseLine({ phase: 'graph' }).includes('개념 지도'));
check('그래프 뒤 판정 전', M.phaseLine({ phase: 'align', hasGraph: true }).includes('찾고'));
check('판정 뒤', M.phaseLine({ hasGraph: true, hasAlign: true }).includes('채점했어요'));
check('긴 이름 줄이기', M.shortLabel('가나다라마바사아자차카타파하', 8) === '가나다라마바사…');

// 하네스 자가 검사 — 대체 판정을 「빠뜨림」 으로 보는 잘못된 규칙을 잡아내는가
const broken = (a, id) => ({ aligned: 'ok', missing: 'no' })[(a.items.find((x) => x.node_id === id) || {}).verdict];
check('하네스가 회귀를 잡는다', broken(al, 'X') !== M.verdictOf(al, 'X'));

if (failed) { console.log(`\n${failed} failed`); process.exit(1); }
console.log('\nscore_model: all ok');
