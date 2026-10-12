/**
 * 마이크 고르기(main/web/js/mic_pref.js) 스모크 — Mac 연속성 iPhone 마이크 대신 컴퓨터 마이크.
 *
 *   node etc/tests/js/mic_pref.smoke.mjs
 *
 * 마지막 케이스는 하네스가 진짜로 회귀를 잡는지 스스로 검사한다.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const ctx = { window: {} };
vm.runInNewContext(readFileSync(path.join(ROOT, 'main/web/js/mic_pref.js'), 'utf8'), ctx);
const { pickMic } = ctx.window.CcMicPref;

let failed = 0;
function check(name, ok) {
  if (ok) console.log(`  ok  ${name}`);
  else { failed++; console.log(`  FAIL ${name}`); }
}
const mic = (deviceId, label) => ({ kind: 'audioinput', deviceId, label });

const macWithPhone = [
  mic('default', '기본값 - 현석의 iPhone 마이크'),
  mic('a1', '현석의 iPhone 마이크'),
  mic('b2', 'MacBook Pro 마이크 (Built-in)'),
  { kind: 'videoinput', deviceId: 'v1', label: 'FaceTime HD 카메라' },
];
check('기본이 iPhone 이면 내장 마이크', pickMic(macWithPhone) === 'b2');
check('연속성 이름도 폰으로 본다', pickMic([mic('default', 'Default - Continuity Microphone'), mic('x', 'Continuity Microphone'), mic('m', 'MacBook Air Microphone')]) === 'm');
check('기본이 폰이 아니면 그대로(외장 마이크 존중)', pickMic([mic('default', '기본값 - USB Audio'), mic('u', 'USB Audio'), mic('b', 'MacBook Pro 마이크')]) === null);
check('폰밖에 없으면 그대로', pickMic([mic('default', '기본값 - iPhone 마이크'), mic('a', 'iPhone 마이크')]) === null);
check('이름이 아직 안 보이면(허락 전) 그대로', pickMic([mic('default', ''), mic('a', '')]) === null);
check('내장이 없으면 폰 아닌 첫 마이크', pickMic([mic('default', 'iPhone Microphone'), mic('i', 'iPhone Microphone'), mic('z', 'Zoom H1')]) === 'z');
check('빈 목록', pickMic([]) === null);

// 하네스 자가 검사 — 폰을 걸러내지 않는 잘못된 고르기를 잡는가
const broken = (ds) => (ds.find((d) => d.kind === 'audioinput' && d.deviceId !== 'default') || {}).deviceId;
check('하네스가 회귀를 잡는다', broken(macWithPhone) !== pickMic(macWithPhone));

if (failed) { console.log(`\n${failed} failed`); process.exit(1); }
console.log('\nmic_pref: all ok');
