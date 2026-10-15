/**
 * 실시간 받아쓰기(main/web/js/live_stt.js) 스모크 — 브라우저 없이.
 *
 *   node etc/tests/js/live_stt.smoke.mjs
 *
 * 왜 있나 — 받아쓰기는 2026-10-15 부터 브라우저 Web Speech(크롬 → 구글 서버) 대신 마이크 → 16kHz PCM16 →
 * 브리지 /api/v1/stt/live → A.X 실시간 STT 다. 이 서버엔 마이크가 없어 손으로 못 눌러 보므로
 * 줄이기(48k/44.1k → 16k) · PCM 바꾸기 · 주소 · 서버 말 반영 · finish/stop 의 약속을 여기서 잡는다.
 * 마지막 케이스는 하네스가 진짜로 회귀를 잡는지 스스로 검사한다.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const SRC = readFileSync(path.join(ROOT, 'main/web/js/live_stt.js'), 'utf8');
const load = (src) => import(`data:text/javascript;base64,${Buffer.from(src).toString('base64')}`);
const L = await load(SRC);

const cases = [];
function test(name, fn) { cases.push({ name, fn }); }
function eq(a, b, msg = '') {
  const A = JSON.stringify(a); const B = JSON.stringify(b);
  if (A !== B) throw new Error(`${msg}\n  expected ${B}\n  got      ${A}`);
}
function ok(v, msg) { if (!v) throw new Error(msg || 'not ok'); }
const tick = () => new Promise((r) => setTimeout(r, 0));

/* ── 줄이기 · PCM ── */
test('48kHz 1초 → 16kHz 16000표본 (조각을 어떻게 나눠도 같다)', () => {
  const N = 48000;
  const sig = Float32Array.from({ length: N }, (_, i) => Math.sin(i / 10));
  const whole = L.makeDownsampler(48000)(sig).length;
  const d = L.makeDownsampler(48000);
  let parts = 0;
  for (let i = 0; i < N; i += 128 * 7) parts += d(sig.subarray(i, Math.min(N, i + 128 * 7))).length;
  eq([whole, parts], [16000, 16000]);
});
test('44.1kHz 도 1초 ≈ 16000표본', () => {
  const d = L.makeDownsampler(44100);
  let n = 0;
  for (let i = 0; i < 44100; i += 2048) n += d(new Float32Array(Math.min(2048, 44100 - i))).length;
  ok(Math.abs(n - 16000) <= 1, `got ${n}`);
});
test('평균이라 고른 소리(직류)는 값이 그대로', () => {
  const out = L.makeDownsampler(48000)(new Float32Array(4800).fill(0.5));
  ok(out.every((v) => Math.abs(v - 0.5) < 1e-6));
});
test('16kHz 입력은 그대로', () => {
  const x = Float32Array.from([0.1, -0.2, 0.3]);
  eq(Array.from(L.makeDownsampler(16000)(x)).map((v) => +v.toFixed(3)), [0.1, -0.2, 0.3]);
});
test('PCM16 작은 끝 · 넘치는 값은 자른다', () => {
  const v = new DataView(L.floatTo16(Float32Array.from([0, 1, -1, 0.5, 2, -3])));
  eq([0, 2, 4, 6, 8, 10].map((o) => v.getInt16(o, true)), [0, 32767, -32768, 16383, 32767, -32768]);
});

/* ── 주소 · 서버 말 ── */
test('주소 — https 는 wss, 끝 슬래시 정리, purpose 는 둘 중 하나', () => {
  eq(L.liveSttUrl('https://chuckchuck-present.com'), 'wss://chuckchuck-present.com/api/v1/stt/live?purpose=answer');
  eq(L.liveSttUrl('http://127.0.0.1:8812/', 'present'), 'ws://127.0.0.1:8812/api/v1/stt/live?purpose=present');
  eq(L.liveSttUrl('http://x', '<script>'), 'ws://x/api/v1/stt/live?purpose=answer');
});
test('서버 말 — 문장은 띄어 잇고, 끝난 뒤 글은 버린다', () => {
  let s = {};
  const seq = [{ type: 'ready' }, { type: 'speech', on: true }, { type: 'text', text: ' 준호입니다 ' },
    { type: 'speech', on: true }, { type: 'text', text: '별점은 왜 4.7에 몰리는가' }, { type: 'text', text: '' },
    { type: 'done', reason: 'stop' }, { type: 'text', text: '늦은 글' }];
  const changes = seq.map((m) => { const r = L.liveSttApply(s, m); s = r.state; return r.changed; });
  eq(changes, ['ready', 'speech', 'text', 'speech', 'text', '', 'done', '']);
  eq([s.final, s.speaking, s.done, s.reason], ['준호입니다 별점은 왜 4.7에 몰리는가', false, true, 'stop']);
});
test('서버 오류는 code · 문구를 남긴다', () => {
  const r = L.liveSttApply({ final: '앞말' }, { type: 'error', code: 'busy', message: '지금 받아쓰기를 쓰는 사람이 많아요.' });
  eq([r.changed, r.state.error.code, r.state.final], ['error', 'busy', '앞말']);
});
test('열 수 있나 — WebSocket · 오디오 · 마이크 · https 가 다 있어야', () => {
  const md = { getUserMedia() {} };
  const full = { WebSocket: function W() {}, AudioContext: function A() {}, isSecureContext: true, navigator: { mediaDevices: md } };
  ok(L.canLiveStt(full));
  ok(L.canLiveStt({ ...full, AudioContext: undefined, webkitAudioContext: function B() {} }), '옛 사파리 webkitAudioContext');
  ok(!L.canLiveStt({ ...full, isSecureContext: false }), 'http 사내망 주소');
  ok(!L.canLiveStt({ ...full, navigator: {} }), '마이크 없음');
  ok(!L.canLiveStt({ ...full, WebSocket: undefined }));
});

/* ── startLiveStt — 가짜 WebSocket · 오디오 ── */
function rig() {
  const sockets = [];
  class FakeWS {
    constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this); }
    send(x) { this.sent.push(x); }
    close() { this.readyState = 3; if (this.onclose) this.onclose({}); }
    open() { this.readyState = 1; this.onopen && this.onopen(); }
    say(m) { this.onmessage && this.onmessage({ data: JSON.stringify(m) }); }
  }
  const proc = {};
  class FakeAC {
    constructor() { this.sampleRate = 48000; this.state = 'running'; this.destination = {}; }
    createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
    createScriptProcessor() { Object.assign(proc, { connect() {}, disconnect() {} }); return proc; }
    createGain() { return { gain: {}, connect: (x) => x }; }
    resume() { return Promise.resolve(); }
    close() { this.state = 'closed'; return Promise.resolve(); }
  }
  const stopped = [];
  const stream = { getTracks: () => [{ stop: () => stopped.push(1) }] };
  globalThis.window = { AudioContext: FakeAC, WebSocket: FakeWS, isSecureContext: true };
  globalThis.WebSocket = FakeWS;
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { mediaDevices: { getUserMedia: async () => stream } } });
  const feed = (n) => proc.onaudioprocess({ inputBuffer: { getChannelData: () => new Float32Array(n).fill(0.25) } });
  return { sockets, feed, stopped };
}

test('finish — stop 을 보내고 남은 문장까지 그린 뒤 전문으로 끝난다', async () => {
  const r = rig();
  const texts = []; const speech = []; const errors = [];
  const h = L.startLiveStt({ base: 'https://a.b', onText: (p) => texts.push(p), onError: (m) => errors.push(m), onSpeech: (on) => speech.push(on) });
  await tick(); await tick();
  const ws = r.sockets[0];
  eq(ws.url, 'wss://a.b/api/v1/stt/live?purpose=answer');
  r.feed(4800);                                   // 0.1초 = 1600표본 = 한 프레임 — 연결 전이라 쥐고 있는다
  eq(ws.sent.length, 0);
  ws.open();
  eq([ws.sent.length, ws.sent[0].byteLength], [1, 3200], '연결되면 쥔 소리를 보낸다');
  ws.say({ type: 'ready' });
  ws.say({ type: 'speech', on: true });
  ok(h.speaking, 'bos → 말하는 중');
  ws.say({ type: 'text', text: '첫 문장' });
  const done = h.finish();
  eq(ws.sent[ws.sent.length - 1], JSON.stringify({ type: 'stop' }));
  ws.say({ type: 'text', text: '마지막 문장' });  // stop 뒤에 확정된 문장도 그린다
  ws.say({ type: 'done', reason: 'stop' });
  eq(await done, '첫 문장 마지막 문장');
  eq(texts.map((t) => [t.final, t.interim]), [['첫 문장', ''], ['첫 문장 마지막 문장', '']]);
  eq([speech, errors], [[true, false, false], []]);
  ok(r.stopped.length >= 1, '마이크 트랙을 끈다');
});

test('stop — cancel 을 보내고 늦게 온 문장은 버린다', async () => {
  const r = rig();
  const texts = [];
  const h = L.startLiveStt({ base: 'http://x', onText: (p) => texts.push(p.final), onError: () => {} });
  await tick(); await tick();
  const ws = r.sockets[0];
  ws.open(); ws.say({ type: 'ready' }); ws.say({ type: 'text', text: '하나' });
  eq(h.stop(), '하나');
  eq(ws.sent[ws.sent.length - 1], JSON.stringify({ type: 'cancel' }));
  ws.say({ type: 'text', text: '늦음' });
  eq(texts, ['하나']);
});

test('서버가 먼저 끝내면(limit) onError 에 code 를 준다 — 호출부가 「죽음」 으로 치지 않게', async () => {
  const r = rig();
  const errs = [];
  L.startLiveStt({ base: 'http://x', onText: () => {}, onError: (m, info) => errs.push([m, info.code]) });
  await tick(); await tick();
  const ws = r.sockets[0];
  ws.open(); ws.say({ type: 'ready' }); ws.say({ type: 'done', reason: 'limit' });
  eq(errs, [['받아쓰기 시간이 다 됐어요.', 'limit']]);
});

test('연결이 끊기면 한 번만 알린다', async () => {
  const r = rig();
  const errs = [];
  L.startLiveStt({ base: 'http://x', onText: () => {}, onError: (m, info) => errs.push(info.code) });
  await tick(); await tick();
  const ws = r.sockets[0];
  ws.open(); ws.say({ type: 'error', code: 'busy', message: '많아요' });
  ws.close();
  eq(errs, ['busy']);
});

/* ── 하네스 자가 검사: 문장 잇기를 망가뜨린 사본이 위 케이스에 걸려야 한다 ── */
test('하네스가 회귀를 잡는다 (문장 사이 띄어쓰기를 지운 사본)', async () => {
  const broken = SRC.replace('final: s.final ? `${s.final} ${text}` : text', 'final: s.final + text');
  if (broken === SRC) throw new Error('자가 검사용 치환이 안 먹었어요 — liveSttApply 가 바뀌었으면 이 치환도 고쳐요');
  const B = await load(broken);
  let s = {};
  for (const m of [{ type: 'text', text: '가' }, { type: 'text', text: '나' }]) s = B.liveSttApply(s, m).state;
  if (s.final === '가 나') throw new Error('망가뜨린 사본이 통과했어요 — 하네스가 회귀를 못 잡아요');
});

let failed = 0;
for (const c of cases) {
  try { await c.fn(); console.log(`  ok  ${c.name}`); } catch (e) { failed++; console.log(`  FAIL ${c.name}\n${e.message}`); }
}
console.log(failed ? `\n${failed} 실패` : `\n${cases.length}개 통과`);
process.exit(failed ? 1 : 0);
