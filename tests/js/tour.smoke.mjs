/**
 * 모바일 체험 투어(js/tour_logic.js) 순수 함수 스모크.
 *
 *   node tests/js/tour.smoke.mjs
 *
 * 왜 있나 — 투어는 녹화 응답을 재생할 뿐이라 틀릴 곳이 「몇 초에 어느 장 · 자막 · 코칭 칩」, 「주소 → 단계」,
 * 「인앱 브라우저 판별 · 바깥 브라우저로 여는 주소」 에 몰려 있다. 폰이 없는 서버에서 이것들을 브라우저 없이 잡는다.
 * 데이터는 계약 예시(data/tour/_example.json) 그대로 쓴다 — 예시가 바뀌면 여기서 같이 드러난다.
 *
 * 마지막 케이스는 하네스가 진짜로 회귀를 잡는지 스스로 검사한다 (booth.smoke.mjs 와 같은 규율).
 * 이 파일은 pytest 가 수집하지 않는다.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const WEB = path.join(ROOT, 'demo/YEHS_demo');
const SRC = readFileSync(path.join(WEB, 'js/tour_logic.js'), 'utf8');
const EX = JSON.parse(readFileSync(path.join(WEB, 'data/tour/_example.json'), 'utf8'));

/** 브라우저 전역 없이 원본 파일 그대로 올린다 — window 하나만 준다 */
function load(src) {
  const sandbox = { window: {} };
  vm.runInNewContext(src, sandbox, { filename: 'tour_logic.js' });
  return sandbox.window.TourLogic;
}
const T = load(SRC);

const cases = [];
const test = (name, fn) => cases.push({ name, fn });
const eq = (a, b, msg = '') => {
  const A = JSON.stringify(a), B = JSON.stringify(b);
  if (A !== B) throw new Error(`${msg}\n  expected ${B}\n  got      ${A}`);
};
const ok = (v, msg) => { if (!v) throw new Error(msg); };

const UA = {
  iosSafari: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1',
  androidChrome: 'Mozilla/5.0 (Linux; Android 14; SM-S921N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36',
  kakaoIos: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 KAKAOTALK 10.8.5',
  naverAndroid: 'Mozilla/5.0 (Linux; Android 14; SM-S921N; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/129.0 Mobile Safari/537.36 NAVER(inapp; search; 2000; 12.6.3)',
  instaIos: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 350.0.0.0.0',
};

function suite(T) {
  const out = [];
  const t = (name, fn) => out.push({ name, fn: () => fn(T) });

  t('주소 → 단계: 시작 · 다섯 단계 · 끝 · 질문 번호', (T) => {
    eq(T.parseTourHash('#/tour').screen, 'intro');
    eq(T.parseTourHash('#/tour/').screen, 'intro');
    ['deck', 'present', 'analysis', 'qa', 'report', 'done'].forEach((s) => eq(T.parseTourHash(`#/tour/${s}`).screen, s, s));
    eq(T.parseTourHash('#/tour/qa/3'), { screen: 'qa', q: 2, alias: false });
    eq(T.parseTourHash('#/tour/qa/0').q, 0, '0 이하 번호는 첫 질문');
    eq(T.parseTourHash('#/rehearsal'), null, '투어 밖 주소는 null');
  });
  t('작업 지시의 analyze 도 분석으로 받는다(계약은 analysis) · 모르는 단계는 시작', (T) => {
    eq(T.parseTourHash('#/tour/analyze'), { screen: 'analysis', q: 0, alias: true });
    eq(T.parseTourHash('#/tour/nope').screen, 'intro');
  });
  t('단계 → 주소는 되돌리면 같다', (T) => {
    T.SCREENS.forEach((s) => eq(T.parseTourHash(T.tourHash(s)).screen, s, s));
    eq(T.tourHash('qa', 0), '#/tour/qa');
    eq(T.tourHash('qa', 1), '#/tour/qa/2');
    eq(T.parseTourHash(T.tourHash('qa', 2)).q, 2);
  });
  t('단계 막대는 1~5, 시작 · 끝은 막대 밖', (T) => {
    eq(T.stepIndex('deck'), 1);
    eq(T.stepIndex('report'), 5);
    eq(T.stepIndex('intro'), 0);
    eq(T.stepIndex('done'), 0);
  });
  t('뒤로: 질문 2 → 질문 1, 자료 → 시작, 시작 → 없음(팀 소개)', (T) => {
    eq(T.prevScreen('qa', 1), { screen: 'qa', q: 0 });
    eq(T.prevScreen('qa', 0), { screen: 'analysis', q: 0 });
    eq(T.prevScreen('deck'), { screen: 'intro', q: 0 });
    eq(T.prevScreen('intro'), null);
  });
  t('예시 녹화 파일은 계약 뼈대를 지킨다 · 모르는 버전은 거절', (T) => {
    eq(T.tourProblem(EX), '');
    ok(T.tourProblem({ ...EX, version: 2 }).includes('버전'), 'v2 를 받아들였어요');
    ok(T.tourProblem({ ...EX, qa: { questions: [] } }), '질문 없는 파일을 받아들였어요');
    ok(T.tourProblem(null), 'null 을 받아들였어요');
  });
  t('index.json 세 모양 — 투어 그 자체 · {tours, default} · 배열', (T) => {
    eq(T.indexIds(EX).inline.id, '_example');
    eq(T.indexIds({ tours: [{ id: 'a' }, 'b.json', { id: '../x' }], default: 'b' }), { ids: ['a', 'b'], inline: null, first: 'b' });
    eq(T.indexIds(['c', 'd']).first, 'c');
    eq(T.indexIds({}).ids, []);
  });
  t('시각 → 장: 넘김 시각대로, 경계는 다음 장', (T) => {
    const p = EX.present;
    eq(T.slideAt(p, 0), 1);
    eq(T.slideAt(p, 21.9), 1);
    eq(T.slideAt(p, 22), 2);
    eq(T.slideAt(p, 95), 3);
    eq(T.slideAt(p, 999), 3);
    eq(T.slideStart(p, 3), 70);
  });
  t('시각 → 자막: 반열림 [start, end) · 빈틈이면 null', (T) => {
    const p = EX.present;
    eq(T.captionAt(p, 0).text.startsWith('배달앱'), true);
    eq(T.captionAt(p, 9).start_sec, 9, '경계에서 두 조각이 겹치지 않는다');
    eq(T.captionAt(p, 96), null);
  });
  t('시각 → 코칭 칩: 뜬 뒤 HOLD 초 동안만 「지금」, 수는 계속 센다', (T) => {
    const p = EX.present;
    eq(T.chipAt(p, 5).live, null);
    eq(T.chipAt(p, 46).live.kind, 'fast');
    eq(T.chipAt(p, 46 + T.CHIP_HOLD_SEC).live, null);
    eq(T.chipAt(p, 46).seen, 3);
    eq(T.chipAt(p, 200).seen, 5);
    ok(Object.keys(T.CHIP_KIND).every((k) => T.CHIP_KIND[k].looks), '칩 종류마다 「AI 가 보는 것」 한 줄이 있어야 해요');
    p.coaching_chips.forEach((c) => ok(T.CHIP_KIND[c.kind], `모르는 칩 종류 ${c.kind}`));
  });
  t('장 넘기기: 끝에서는 그대로 + edge', (T) => {
    eq(T.stepSlide(EX.deck, 1, 1), { no: 2, edge: false });
    eq(T.stepSlide(EX.deck, 3, 1), { no: 3, edge: true });
    eq(T.stepSlide(EX.deck, 1, -1), { no: 1, edge: true });
  });
  t('주장 그래프: 루트부터 깊이 순, 모든 노드를 한 번씩', (T) => {
    const rows = T.graphRows(EX.analysis.claim_graph);
    eq(rows[0].node.id, 'claim');
    eq(rows[0].depth, 0);
    eq(rows.length, EX.analysis.claim_graph.nodes.length);
    eq(new Set(rows.map((r) => r.node.id)).size, rows.length);
    const ia = rows.findIndex((r) => r.node.id === 'hyp_a');
    eq(rows[ia + 1].node.id, 'ev_reorder', '자식은 부모 바로 아래');
    eq(T.graphCounts(EX.analysis.claim_graph), { aligned: 5, justified_skip: 0, missing: 2, contradiction: 0 });
  });
  t('3단계 말 · 판정 낱말은 계약 그대로', (T) => {
    eq(T.LEVEL_WORD, { good: '좋아요', fair: '보통', practice: '더 연습' });
    eq(Object.keys(T.VERDICT).sort(), ['good', 'partial', 'unknown', 'wrong']);
    eq(T.GROUND_ROLE, { covered: '짚은 것', missing: '빠진 것', conflict: '다시 볼 곳' });
  });
  t('근거 줄 위치: S2-3 → 2장 3번째 줄', (T) => {
    eq(T.refText('S2-3'), '2장 3번째 줄');
    eq(T.refText('x', 4), '4장');
  });
  t('말 속도 막대: 권장 띠 안팎', (T) => {
    const g = T.paceGauge(372);
    ok(g.at > g.hi, '372자/분은 권장(350)보다 오른쪽');
    eq(T.paceGauge(0).at, 0);
    eq(T.paceGauge(9999).at, 1);
  });
  t('인앱 판별: 사파리 · 크롬은 아님, 카톡 · 네이버 · 인스타는 인앱', (T) => {
    eq(T.inAppKind(UA.iosSafari), '');
    eq(T.inAppKind(UA.androidChrome), '');
    eq(T.inAppKind(UA.kakaoIos), 'kakao');
    eq(T.inAppKind(UA.naverAndroid), 'naver');
    eq(T.inAppKind(UA.instaIos), 'instagram');
  });
  t('바깥 브라우저로 여는 주소: 카톡은 자기 스킴 · 안드로이드 인앱은 크롬 intent · iOS 인스타는 없음(복사 안내)', (T) => {
    const url = 'https://chuckchuck-present.com/rehearsal';
    eq(T.externalOpenUrl(url, UA.kakaoIos), `kakaotalk://web/openExternal?url=${encodeURIComponent(url)}`);
    eq(T.externalOpenUrl(url, UA.naverAndroid), 'intent://chuckchuck-present.com/rehearsal#Intent;scheme=https;package=com.android.chrome;end');
    eq(T.externalOpenUrl(url, UA.instaIos), '');
    eq(T.externalOpenUrl(url, UA.iosSafari), '');
  });
  t('퍼널 신호: {step, deck, t} — t 는 시작 뒤 지난 초', (T) => {
    eq(T.eventPayload('qa', '_example', 1000, 61_400), { step: 'qa', deck: '_example', t: 60 });
    eq(T.eventPayload('deck', '', 0, 5000).t, 0);
  });
  t('퍼널 이름: 투어 화면 → 계약 이름(tour_*) — 서버 허용 목록(demo/tour_events.py STEPS) 밖 이름은 400 이라 안 세어진다', (T) => {
    eq(T.funnelStep('deck'), 'tour_deck');
    eq(T.funnelStep('present'), 'tour_present');
    eq(T.funnelStep('analysis'), 'tour_analysis');
    eq(T.funnelStep('qa'), 'tour_qa');
    eq(T.funnelStep('report'), 'tour_report');
    eq(T.funnelStep('intro'), '', '시작 안내는 /hi 의 intro 와 겹치지 않게 안 센다');
    eq(T.funnelStep('done'), '');
    eq(T.funnelStep('toString'), '', '객체 원형 이름이 새지 않는다');
    const py = readFileSync(path.join(ROOT, 'demo/tour_events.py'), 'utf8');
    const block = py.slice(py.indexOf('STEPS: tuple'), py.indexOf('STEP_SET'));
    const server = [...block.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
    ok(server.length >= 10, `서버 STEPS 를 못 읽었어요: ${server}`);
    for (const sc of T.SCREENS) {
      const st = T.funnelStep(sc);
      ok(!st || server.includes(st), `${sc} → ${st} 가 서버 STEPS 에 없어요`);
    }
  });
  return out;
}

suite(T).forEach((c) => test(c.name, c.fn));

test('하네스 자기 검사 — 장 경계를 하나 밀어 놓은 파일을 넣으면 잡는다', () => {
  const broken = load(SRC.replace('if (t >= s.start_sec) cur = s.slide_no;', 'if (t > s.start_sec) cur = s.slide_no;'));
  const failed = suite(broken).filter((c) => { try { c.fn(); return false; } catch (_) { return true; } });
  ok(failed.length > 0, '고장 낸 tour_logic 이 스모크를 통과했어요 — 하네스가 회귀를 못 잡는다');
});

let pass = 0, fail = 0;
for (const c of cases) {
  try { c.fn(); pass += 1; console.log(`  ✓ ${c.name}`); }
  catch (e) { fail += 1; console.log(`  ✗ ${c.name}\n    ${String(e.message).split('\n').join('\n    ')}`); }
}
console.log(`\n${pass}개 통과${fail ? ` · ${fail}개 실패` : ''}`);
process.exit(fail ? 1 : 0);
