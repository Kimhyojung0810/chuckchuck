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
const SRC = readFileSync(path.join(ROOT, 'main/web/js/mic_pref.js'), 'utf8');
const ctx = { window: {} };
vm.runInNewContext(SRC, ctx);
const { pickMic, pickCam } = ctx.window.CcMicPref;

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

const cam = (deviceId, label) => ({ kind: 'videoinput', deviceId, label });
check('카메라: 폰 카메라가 보이면 FaceTime', pickCam([cam('p', '현석의 iPhone 카메라'), cam('f', 'FaceTime HD 카메라')]) === 'f');
check('카메라: 폰이 없으면 그대로', pickCam([cam('u', 'USB Webcam'), cam('f', 'FaceTime HD Camera')]) === null);
check('카메라: 폰밖에 없으면 그대로', pickCam([cam('p', 'iPhone Camera')]) === null);
check('카메라: 이름이 안 보이면 그대로', pickCam([cam('p', ''), cam('f', '')]) === null);

// getUserMedia 감싸기 — 가짜 mediaDevices 로 실제 흐름
function fakeMd(devices, openLabel) {
  const calls = [];
  const stopped = [];
  const track = (kind, label) => ({ kind, label, stop() { stopped.push(label); } });
  const md = {
    async enumerateDevices() { return devices(); },
    async getUserMedia(c) {
      calls.push(c);
      const lab = (want, kind) => {
        const id = want && want.deviceId && want.deviceId.exact;
        return id ? (devices().find((d) => d.deviceId === id) || {}).label : openLabel[kind];
      };
      const tracks = [];
      if (c.audio) tracks.push(track('audio', lab(c.audio, 'audio')));
      if (c.video) tracks.push(track('video', lab(c.video, 'video')));
      return { getTracks: () => tracks, getAudioTracks: () => tracks.filter((t) => t.kind === 'audio'), getVideoTracks: () => tracks.filter((t) => t.kind === 'video') };
    },
  };
  const c2 = { window: {}, navigator: { mediaDevices: md } };
  vm.runInNewContext(SRC, c2);
  return { md, calls, stopped };
}
const macDevs = () => [
  mic('default', '기본값 - 현석의 iPhone 마이크'), mic('a1', '현석의 iPhone 마이크'), mic('b2', 'MacBook Pro 마이크'),
  cam('p', '현석의 iPhone 카메라'), cam('f', 'FaceTime HD 카메라'),
];
{
  const { md, calls } = fakeMd(macDevs, { audio: '현석의 iPhone 마이크', video: '현석의 iPhone 카메라' });
  const s = await md.getUserMedia({ video: { width: { ideal: 1280 } }, audio: true });
  check('열기 전: 카메라·마이크 모두 컴퓨터 것', s.getVideoTracks()[0].label === 'FaceTime HD 카메라' && s.getAudioTracks()[0].label === 'MacBook Pro 마이크' && calls.length === 1);
  check('카메라 해상도 요청은 그대로', calls[0].video.width.ideal === 1280);
}
{
  // 첫 허락 — 열기 전엔 이름이 안 보이고, 열고 나면 보인다. 폰이 열렸으면 다시 연다
  let granted = false;
  const devs = () => granted ? macDevs() : macDevs().map((d) => ({ ...d, label: '' }));
  const { md, calls, stopped } = fakeMd(devs, { audio: '현석의 iPhone 마이크', video: '현석의 iPhone 카메라' });
  const s = await (async () => { const p = md.getUserMedia({ video: true, audio: true }); granted = true; return p; })();
  check('첫 허락: 폰이 열리면 컴퓨터 것으로 다시 연다', s.getVideoTracks()[0].label === 'FaceTime HD 카메라' && s.getAudioTracks()[0].label === 'MacBook Pro 마이크');
  check('첫 허락: 폰 트랙은 닫는다', stopped.includes('현석의 iPhone 카메라') && stopped.includes('현석의 iPhone 마이크') && calls.length === 2);
}
{
  const { md, calls } = fakeMd(macDevs, { audio: 'x', video: 'x' });
  await md.getUserMedia({ audio: { deviceId: { exact: 'a1' } } });
  check('기기를 고른 요청은 손대지 않는다', calls.length === 1 && calls[0].audio.deviceId.exact === 'a1');
}

// 하네스 자가 검사 — 폰을 걸러내지 않는 잘못된 고르기를 잡는가
const broken = (ds) => (ds.find((d) => d.kind === 'audioinput' && d.deviceId !== 'default') || {}).deviceId;
check('하네스가 회귀를 잡는다', broken(macWithPhone) !== pickMic(macWithPhone));

if (failed) { console.log(`\n${failed} failed`); process.exit(1); }
console.log('\nmic_pref: all ok');
