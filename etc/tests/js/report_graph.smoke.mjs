/**
 * Report 2.0 Evidence Graph(main/web/js/report_graph.js) 스모크 — 인용 위치 · 발화 · 청중 대사 검사 · 인사이트 근거 · 검증기.
 *
 *   node etc/tests/js/report_graph.smoke.mjs
 *
 * 실제 데이터(main/web/data/report_v2_rec.json — 실 API 응답 묶음)의 불변식도 본다. 마지막 케이스는 하네스 자가 검사.
 */
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const ctx = { window: {} };
vm.runInNewContext(readFileSync(path.join(ROOT, 'main/web/js/report_graph.js'), 'utf8'), ctx);
const RG = ctx.window.ReportGraph;

let failed = 0;
function check(name, ok) {
  if (ok) console.log(`  ok  ${name}`);
  else { failed++; console.log(`  FAIL ${name}`); }
}
const w = (text, s, e) => ({ text, start_sec: s, end_sec: e });
const transcript = {
  duration_sec: 10, full_text: '안녕하세요 저는 발표자입니다. 별점은 높게 몰려요. 그래서 행동 지표를 봐야 해요.',
  words: [w('안녕하세요', 0, 0.5), w('저는', 0.6, 0.9), w('발표자입니다.', 1, 1.8), w('별점은', 3, 3.4), w('높게', 3.5, 3.8), w('몰려요.', 3.9, 4.5),
    w('그래서', 5, 5.3), w('행동', 5.4, 5.7), w('지표를', 5.8, 6.2), w('봐야', 6.3, 6.6), w('해요.', 6.7, 7)],
  marks: [{ slide_no: 1, start_sec: 0, end_sec: 3, visit: 1 }, { slide_no: 2, start_sec: 3, end_sec: 10, visit: 1 }],
};
const utts = RG.segmentUtterances(transcript);
check('발화: 문장 끝에서 끊는다(3개)', utts.length === 3 && utts[1].text === '별점은 높게 몰려요.' && utts[1].slide_no === 2);
const hit = RG.locateQuote(transcript, utts, '행동 지표를 봐야');
check('인용: 원문 그대로면 단어 시각 · 발화 id', hit.status === 'supported' && hit.start_sec === 5.4 && hit.end_sec === 6.6 && hit.utt_ids.join() === 'U3');
check('인용: 공백 · 문장부호 차이는 같은 말', RG.locateQuote(transcript, utts, '별점은높게 몰려요').status === 'supported');
check('인용: 원문에 없으면 inferred (지어내지 않음)', RG.locateQuote(transcript, utts, '별점은 낮게 몰려요').status === 'inferred');
check('인용: 비면 missing', RG.locateQuote(transcript, utts, '').status === 'missing');

const input = {
  reportId: 't', transcript, deck: { title: '시험', slides: [{ slide_no: 1, title: '처음' }, { slide_no: 2, title: '둘째' }] },
  graph: { total_slides: 2, nodes: [
    { id: 'th', label: '결론', kind: 'thesis', weight: 1, slide_nos: [2] },
    { id: 'jip', label: '행동 지표', kind: 'concept', weight: 0.9, slide_nos: [2] },
    { id: 'inf', label: '평점 인플레이션', kind: 'concept', weight: 0.6, slide_nos: [1] },
  ], edges: [] },
  alignment: { items: [
    { node_id: 'th', verdict: 'missing', decided_by: 'fallback', evidence: '', note: '' },
    { node_id: 'jip', verdict: 'aligned', decided_by: 'llm', evidence: '행동 지표를 봐야 해요', note: '설명' },
    { node_id: 'inf', verdict: 'aligned', decided_by: 'llm', evidence: '별점은 높게 몰려요', note: '뜻으로 설명' },
  ] },
  pace: { target_sec: 60, actual_sec: 10, slides: [
    { slide_no: 1, status: 'short', delta_sec: -20, actual_sec: 3, recommended_sec: 23, importance: 'core' },
    { slide_no: 2, status: 'short', delta_sec: -30, actual_sec: 7, recommended_sec: 37, importance: 'core' },
  ] },
  chatter: { absent: ['midm'], speaker_names: {}, turns: [
    { speaker: 'midm', text: '오늘 못 왔어요', mood: 'neutral', refs: [] },
    { speaker: 'solar', text: "'Model Architecture' 이야기가 없네", mood: 'curious', refs: [] },
    { speaker: 'ax', text: "'평점 인플레이션'은 한 번도 안 나와서 아쉬웠어", mood: 'curious', refs: [{ node_id: 'inf' }] },
    { speaker: 'exaone', text: "'행동 지표' 설명이 좋았어", mood: 'happy', refs: [{ node_id: 'jip' }] },
  ] },
  qa: { questions: [{ id: 'q1', node_id: 'jip', question: '왜 행동 지표인가요?', label: '행동 지표', answer_gist: '별점은 몰려서 구별이 안 돼요', slide_nos: [2] }],
    results: [{ id: 'q1', answer: '별점이 다 높아서요', verdict: 'partial', trail: [{ q: '왜 행동 지표인가요?', claim: '다 높아서' }, { q: '「다 높아서」 는 왜 문제죠?', claim: '별점이 다 높아서요' }] }] },
};
const g = RG.buildGraph(input);
const v = RG.validate(g);
const node = (id) => g.nodes.get(id);
check('청중: 그래프 · 받아쓰기에 없는 말은 unsupported', node('R2').status === 'unsupported' && v.issues.some((i) => i.kind === 'unsupported_remark' && i.id === 'R2'));
check('청중: 「안 나왔다」 + 정합 aligned 는 conflicting', node('R3').status === 'conflicting');
check('청중: refs 가 있는 개념 칭찬은 supported', node('R4').status === 'supported');
check('청중: 결석은 대사가 근거가 아니다(missing)', node('R1').status === 'missing' && node('E:midm').absent === true);
check('대체값 판정은 「판정 못 함」 인사이트 · 근거 없음으로 표시', node('I:unjudged:th') && node('I:unjudged:th').status === 'missing'
  && v.issues.some((i) => i.kind === 'insight_without_evidence' && i.id === 'I:unjudged:th'));
check('시간: 같은 쪽 장 둘은 인사이트 하나로', node('I:pace:short') && !node('I:pace:1') && g.out('I:pace:short', 'SUPPORTED_BY').length === 2);
check('잘한 개념: 인용이 원문에 있을 때만', node('I:good:jip') && RG.evidencePath(g, 'I:good:jip').some((p) => p[2] === 'U3'));
check('Q&A: 꼬리질문은 앞 답(claim)에 GROUNDED_IN', g.edges.some((e) => e.type === 'GROUNDED_IN' && e.from === 'F:q1:1' && e.to === 'A:qa:q1:1'));
const vmodel = RG.buildViewModel(g, input);
check('Q&A: 전환점 사슬 질문 → claim → 꼬리질문 → 답', vmodel.qa[0].steps.length === 2 && vmodel.qa[0].steps[0].followup.startsWith('「다 높아서」'));
check('검증: 시험 그래프에 끊긴 엣지 없음', !v.issues.some((i) => i.kind === 'dangling'));
g.edges.push({ id: 'X', type: 'POINTS_TO', from: 'V:said:jip', to: 'U99', source: { type: 't', id: '' } });
check('검증: 끊긴 엣지를 잡는다', RG.validate(g).issues.some((i) => i.kind === 'dangling' && i.end === 'U99'));

// 실제 데이터 불변식
const FIX = path.join(ROOT, 'main/web/data/report_v2_rec.json');
if (existsSync(FIX)) {
  const d = JSON.parse(readFileSync(FIX, 'utf8'));
  const rg = RG.buildGraph({ ...d, reportId: 'rec_v2' });
  const rv = RG.validate(rg);
  check('실측: 끊긴 엣지 · 출처 없는 노드 없음', !rv.issues.some((i) => ['dangling', 'node_no_source', 'edge_no_source', 'duplicate_edge'].includes(i.kind)));
  check('실측: 시각 · 장 범위 밖 앵커 없음', !rv.issues.some((i) => i.kind === 'time_out_of_range' || i.kind === 'slide_out_of_range'));
  check('실측: 말한 구절 인용은 모두 원문에 있다', !rv.issues.some((i) => i.kind === 'quote_not_verbatim'));
  check('실측: 쏠라의 지어낸 장 제목을 잡는다', [...rg.nodes.values()].some((n) => n.type === 'Remark' && n.speaker === 'solar' && n.status === 'unsupported'));
  const rvm = RG.buildViewModel(rg, d);
  check('실측: 이슈 인사이트마다 근거가 하나 이상', rvm.issues.every((i) => i.proofs.length > 0));
  check('실측: 근거 길 비율 ≥ 0.7', rv.metrics.evidencePathRate >= 0.7);
}

// 하네스 자가 검사 — 원문에 없는 인용도 supported 로 잇는 잘못된 위치 찾기를 잡는가
const brokenLocate = () => ({ status: 'supported' });
check('하네스가 회귀를 잡는다', brokenLocate().status !== RG.locateQuote(transcript, utts, '별점은 낮게 몰려요').status);

if (failed) { console.log(`\n${failed} failed`); process.exit(1); }
console.log('\nreport_graph: all ok');
