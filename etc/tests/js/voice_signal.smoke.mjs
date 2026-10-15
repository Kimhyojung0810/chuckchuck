/**
 * 음성 시각화(js/voice-viz.js) 신호 판단 스모크 — 원본 main/web/studio-app/src/voice/signal.js.
 *
 *   node etc/tests/js/voice_signal.smoke.mjs
 *
 * 왜 있나 — 마이크 · WebGL 은 이 서버에서 못 본다. 「언제 무엇을 그리나」 「진짜 신호가 있으면 흉내를 안 쓰나」 만 브라우저 없이 잡는다.
 * 마지막 케이스는 하네스가 진짜로 회귀를 잡는지 스스로 검사한다 (qa_live.smoke.mjs 와 같은 규율).
 */
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const S = await import(pathToFileURL(path.join(ROOT, 'main/web/studio-app/src/voice/signal.js')).href);

let failed = 0;
function check(name, ok) {
  if (ok) console.log(`  ok  ${name}`);
  else { failed++; console.log(`  FAIL ${name}`); }
}

// 음량
check('무음 RMS 0 → 0', S.rmsToVolume(0) === 0);
check('잡음(-70dB) → 0', S.rmsToVolume(10 ** (-70 / 20)) === 0);
check('큰 소리(-10dB) → 1', S.rmsToVolume(10 ** (-10 / 20)) === 1);
const mid = S.rmsToVolume(10 ** (-36 / 20));
check('말소리(-36dB) 는 중간', mid > 0.3 && mid < 0.7);
check('NaN 은 0', S.rmsToVolume(NaN) === 0);

// 상태 우선순위
check('생각이 가장 먼저', S.qaVoiceState({ thinking: true, micOn: true, speaking: true }) === 'thinking');
check('내가 말하면 삐약이 말하기를 끊는다', S.qaVoiceState({ micOn: true, speaking: true }) === 'listening');
check('삐약이 말하기', S.qaVoiceState({ speaking: true }) === 'speaking');
check('아무 일 없으면 쉼', S.qaVoiceState({}) === 'idle');

// 그림 고르기 — 사용자 지정(10-13): 발표=Bars, Q&A 생각·말=구, 내 답=Bars, 쉴 땐 없음(WebGL 쉼)
check('발표 Bars', S.viewFor('bars', 'listening') === 'bars');
check('발표 쉼 → 그리지 않음', S.viewFor('bars', 'idle') === null);
check('Q&A 생각 → 구', S.viewFor('qa', 'thinking') === 'orb');
check('Q&A 말하기 → 구', S.viewFor('qa', 'speaking') === 'orb');
check('Q&A 내 답 → Bars', S.viewFor('qa', 'listening') === 'bars');
check('Q&A 쉼 → 그리지 않음', S.viewFor('qa', 'idle') === null);

// 말하는 시간
check('짧은 말도 1.6초', S.speakMsFor('네') === 1600);
check('긴 말은 7초까지', S.speakMsFor('가'.repeat(500)) === 7000);
check('35자 ≈ 5초', S.speakMsFor('가'.repeat(35)) === 5000);

// 진짜 신호 우선 · 흉내는 없을 때만
check('진짜 0 은 0 그대로(흉내 아님)', S.pickVolume(0, 'listening', 1234).volume === 0 && !S.pickVolume(0, 'listening', 1234).simulated);
check('신호 없으면 흉내', S.pickVolume(null, 'speaking', 1234).simulated === true);
let inRange = true;
for (let t = 0; t < 5000; t += 37) {
  const a = S.simulatedVolume('speaking', t), b = S.simulatedVolume('listening', t);
  if (!(a >= 0.25 && a <= 1 && b >= 0 && b <= 0.6)) inRange = false;
}
check('흉내 음량 범위', inRange);
check('생각 중 흉내는 0', S.simulatedVolume('thinking', 999) === 0);

// 하네스 자가 검사 — 거꾸로 된 우선순위를 실제로 잡아내는가
const broken = ({ thinking, micOn, speaking }) => (speaking ? 'speaking' : micOn ? 'listening' : thinking ? 'thinking' : 'idle');
check('하네스가 회귀를 잡는다', broken({ micOn: true, speaking: true }) !== S.qaVoiceState({ micOn: true, speaking: true }));

if (failed) { console.log(`\n${failed} failed`); process.exit(1); }
console.log('\nvoice_signal: all ok');
