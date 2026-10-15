/**
 * 가상 발표 스튜디오 ↔ 앱 흐름 순수 함수 스모크 — 원본 main/web/studio-app/src/ui/keys.js (SPACE §6 · §7).
 *
 *   node etc/tests/js/studio_flow.smoke.mjs
 *
 * 왜 있나 — 앱 주소가 정거장을 정하고, 키보드가 앱의 주 버튼 · 뒤로 가기를 부른다. 「② 발표에서 방향키를 가로채
 * 슬라이드 넘김(클리커)을 막는」 회귀가 가장 아프다 — 브라우저 없이 잡는다. 마지막 케이스는 하네스 자가 검사.
 */
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const K = await import(pathToFileURL(path.join(ROOT, 'main/web/studio-app/src/ui/keys.js')).href);

let failed = 0;
function check(name, ok) {
  if (ok) console.log(`  ok  ${name}`);
  else { failed++; console.log(`  FAIL ${name}`); }
}

// 주소 → 정거장
check('#/rehearsal → ①', K.stationOfHash('#/rehearsal') === 0);
check('#/rehearsal/occ → ①', K.stationOfHash('#/rehearsal/occ') === 0);
check('#/rehearsal/new → ② 발표', K.stationOfHash('#/rehearsal/new') === 1);
check('발표 주소라도 분석 기다림 층이면 ③ 분석', K.stationOf({ hash: '#/rehearsal/new', wait: true }) === 2);
check('기다림 층이 없으면 ② 발표', K.stationOf({ hash: '#/rehearsal/new', wait: false }) === 1);
check('질문 주소는 층과 무관', K.stationOf({ hash: '#/rehearsal/qa', wait: true }) === 3);
check('#/rehearsal/qa → ④ 질의응답', K.stationOfHash('#/rehearsal/qa') === 3);
check('#/rehearsal/report → ⑤ 리포트', K.stationOfHash('#/rehearsal/report') === 4);
check('#/report/last → ⑤ 리포트', K.stationOfHash('#/report/last') === 4);
check('리포트 2.0 뿌리 화면이 정거장을 가른다 — 다시 보기 ⑥', K.stationOf({ hash: '#/rehearsal/report', rv2Root: 'replay' }) === 5);
check('리포트 결과(home) · 모르는 뿌리는 ⑤', K.stationOf({ hash: '#/rehearsal/report', rv2Root: 'home' }) === 4 && K.stationOf({ hash: '#/rehearsal/report', rv2Root: 'x' }) === 4);
check('리포트 연습은 ⑨', K.stationOf({ hash: '#/report/last', rv2Root: 'practice' }) === 8);
check('리포트 정거장 → 는 옆 탭', K.keyAction({ key: 'ArrowRight', station: 5 }) === 'tabNext' && K.keyAction({ key: 'ArrowLeft', station: 5 }) === 'tabPrev');
check('리포트 끝 탭에서 → · 첫 탭에서 ← 는 없다', K.keyAction({ key: 'ArrowRight', station: 8 }) === null && K.keyAction({ key: 'ArrowLeft', station: 4 }) === null);
check('#/home → 흐름 밖', K.stationOfHash('#/home') === -1);
check('빈 주소 → 흐름 밖', K.stationOfHash('') === -1);
check('#/rehearsals 는 흐름이 아니다', K.stationOfHash('#/rehearsals') === -1);

// 키
check('① → 는 다음', K.keyAction({ key: 'ArrowRight', station: 0 }) === 'next');
check('④ Enter 는 다음', K.keyAction({ key: 'Enter', station: 3 }) === 'next');
check('← 는 이전', K.keyAction({ key: 'ArrowLeft', station: 3 }) === 'back');
check('② 발표 · 앱 안 초점 → 는 앱(클리커)', K.keyAction({ key: 'ArrowRight', station: 1, inApp: true }) === null);
check('② 발표 · 앱 안 초점 ← 는 앱', K.keyAction({ key: 'ArrowLeft', station: 1, inApp: true }) === null);
check('② 발표 · 바깥 초점 → 는 앱의 다음 장', K.keyAction({ key: 'ArrowRight', station: 1 }) === 'slideNext');
check('② 발표 · 바깥 초점 PageUp 은 앞 장', K.keyAction({ key: 'PageUp', station: 1 }) === 'slidePrev');
check('② 발표 Enter 는 맡기지 않는다', K.keyAction({ key: 'Enter', station: 1 }) === null);
check('글 입력 중이면 그 칸의 것', K.keyAction({ key: 'Enter', station: 2, typing: true }) === null);
check('버튼에 초점이면 Enter 는 그 버튼', K.keyAction({ key: 'Enter', station: 0, onControl: true }) === null);
check('버튼에 초점이어도 → 는 다음', K.keyAction({ key: 'ArrowRight', station: 0, onControl: true }) === 'next');
check('조합키는 브라우저 것', K.keyAction({ key: 'ArrowLeft', station: 0, mod: true }) === null);
check('다른 키는 안 받는다', K.keyAction({ key: 'a', station: 0 }) === null);

// 앱 안 이동 기록
let st = [];
st = K.trackHash(st, '#/rehearsal');
st = K.trackHash(st, '#/rehearsal/occ');
check('앞으로 가면 쌓인다', st.length === 2);
st = K.trackHash(st, '#/rehearsal/occ');
check('같은 주소는 그대로', st.length === 2);
st = K.trackHash(st, '#/rehearsal');
check('바로 앞 주소로 오면 덜어낸다(뒤로 가기)', st.length === 1 && st[0] === '#/rehearsal');

// 하네스 자가 검사 — ② 에서 방향키를 가로채는 잘못된 규칙을 실제로 잡아내는가
const broken = ({ key }) => (key === 'ArrowRight' ? 'next' : null);
check('하네스가 회귀를 잡는다', broken({ key: 'ArrowRight', station: 1, inApp: true }) !== K.keyAction({ key: 'ArrowRight', station: 1, inApp: true }));

if (failed) { console.log(`\n${failed} failed`); process.exit(1); }
console.log('\nstudio_flow: all ok');
