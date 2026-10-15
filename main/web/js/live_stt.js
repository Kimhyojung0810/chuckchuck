/**
 * 실시간 받아쓰기 — 마이크 → 16kHz mono PCM16 → 브리지 /api/v1/stt/live → SKT A.X realtime STT (2026-10-15).
 *
 * 왜 — 예전엔 브라우저 Web Speech API 를 썼는데, 크롬은 음성을 구글 서버로 보낸다.
 * 국내 AI 트랙 규정(AI 모델 · API 는 100% 국내 AI)에 걸려서 A.X 로 바꿨다. 키는 브리지에만 있다(main/server/live_stt.py).
 *
 * A.X 는 **문장 단위로만** 확정 글을 준다(확정 전 조각이 없다). 그래서 말하는 동안은 가짜 글 대신 vad(bos/eos)로
 * 「듣고 있어요…」 를 보인다 — onSpeech(true/false). onText 의 interim 은 늘 빈 문자열이다(예전 호출부와 모양만 맞춘다).
 *
 * 순수 함수(makeDownsampler · floatTo16 · liveSttUrl · liveSttApply)는 etc/tests/js/live_stt.smoke.mjs 가 브라우저 없이 본다.
 */

export const LIVE_STT_RATE = 16000;
/** 한 번에 보내는 오디오 — 100ms (3200바이트). A.X 실측에서 이 크기로 지연 없이 받았다 */
export const LIVE_STT_FRAME_SAMPLES = 1600;
/** 다 말한 뒤(stop) 남은 문장을 기다리는 최대 시간 */
const FINISH_WAIT_MS = 4000;
/** 연결이 ready 까지 가는 최대 시간 */
const OPEN_WAIT_MS = 9000;

/** 입력 표본율 → 16kHz. 출력 표본 하나 = 그 구간 입력의 평균(간단한 저역 통과). 조각 사이 남는 표본은 다음 조각으로 넘긴다. */
export function makeDownsampler(inRate, outRate = LIVE_STT_RATE) {
  const ratio = inRate / outRate;
  let carry = new Float32Array(0);
  let t = 0;
  return function push(chunk) {
    const buf = new Float32Array(carry.length + chunk.length);
    buf.set(carry, 0);
    buf.set(chunk, carry.length);
    const out = [];
    while (t + ratio <= buf.length) {
      const a = Math.floor(t);
      const b = Math.min(buf.length, Math.floor(t + ratio));
      let v;
      if (b > a) {
        let s = 0;
        for (let i = a; i < b; i++) s += buf[i];
        v = s / (b - a);
      } else {
        v = buf[a];
      }
      out.push(v);
      t += ratio;
    }
    const keep = Math.floor(t);
    carry = buf.slice(keep);
    t -= keep;
    return Float32Array.from(out);
  };
}

/** [-1, 1] 실수 → 16비트 부호 있는 정수, 작은 끝(little-endian) 바이트 */
export function floatTo16(samples) {
  const buf = new ArrayBuffer(samples.length * 2);
  const view = new DataView(buf);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buf;
}

/** API 주소(apiBase) → WebSocket 주소. https 면 wss. purpose: answer(질문 답 · 5분) · present(발표 중 · 20분) */
export function liveSttUrl(base, purpose = 'answer') {
  const b = String(base || '').replace(/\/+$/, '');
  const ws = b.startsWith('https://') ? `wss://${b.slice(8)}` : b.startsWith('http://') ? `ws://${b.slice(7)}` : b;
  return `${ws}/api/v1/stt/live?purpose=${purpose === 'present' ? 'present' : 'answer'}`;
}

/**
 * 브리지 말 하나를 상태에 반영한다 (순수). state = { final, speaking, ready, done, reason, error }.
 * 문장은 띄어 이어 붙인다. done · error 뒤에 온 글은 버린다.
 * @returns {{ state: object, changed: 'text'|'speech'|'ready'|'done'|'error'|'' }}
 */
export function liveSttApply(state, msg) {
  const s = { final: '', speaking: false, ready: false, done: false, reason: '', error: null, ...state };
  if (!msg || typeof msg !== 'object' || s.done) return { state: s, changed: '' };
  if (msg.type === 'ready') return { state: { ...s, ready: true }, changed: 'ready' };
  if (msg.type === 'speech') return { state: { ...s, speaking: !!msg.on }, changed: 'speech' };
  if (msg.type === 'text') {
    const text = String(msg.text || '').trim();
    if (!text) return { state: s, changed: '' };
    return { state: { ...s, final: s.final ? `${s.final} ${text}` : text, speaking: false }, changed: 'text' };
  }
  if (msg.type === 'done') return { state: { ...s, done: true, speaking: false, reason: String(msg.reason || 'stop') }, changed: 'done' };
  if (msg.type === 'error') {
    return { state: { ...s, done: true, speaking: false, error: { code: String(msg.code || 'error'), message: String(msg.message || '') } }, changed: 'error' };
  }
  return { state: s, changed: '' };
}

/** 이 브라우저에서 실시간 받아쓰기를 열 수 있나 — 마이크 · 오디오 처리 · WebSocket · 보안 컨텍스트 */
export function canLiveStt(win = typeof window !== 'undefined' ? window : null) {
  if (!win) return false;
  const AC = win.AudioContext || win.webkitAudioContext;
  return typeof win.WebSocket === 'function' && typeof AC === 'function' && win.isSecureContext !== false
    && !!(win.navigator && win.navigator.mediaDevices && typeof win.navigator.mediaDevices.getUserMedia === 'function');
}

const ERRORS = {
  NotAllowedError: '마이크 권한이 없어요.',
  SecurityError: '마이크 권한이 없어요.',
  NotFoundError: '마이크를 찾지 못했어요.',
  OverconstrainedError: '마이크를 찾지 못했어요.',
  NotReadableError: '다른 앱이 마이크를 쓰고 있어요.',
};

/**
 * 받아쓰기를 연다. 바로 핸들을 돌려주고(마이크 · 연결은 뒤에서 연다), 실패는 onError 한 번으로 알린다.
 *
 * @param {{ base: string, purpose?: string, onText: Function, onError: Function, onSpeech?: Function, onReady?: Function,
 *           workletUrl?: string }} opts
 * @returns {{ stop: () => string, finish: () => Promise<string>, readonly speaking: boolean, readonly ready: boolean }}
 *   stop — 바로 끊고 지금까지 확정된 글을 준다(늦게 오는 문장은 버린다).
 *   finish — 「다 말했어요」: 남은 문장까지 받아(최대 4초) onText 로 그린 뒤 전문을 준다.
 */
export function startLiveStt({ base, purpose = 'answer', onText, onError, onSpeech, onReady, workletUrl }) {
  const win = window;
  const AC = win.AudioContext || win.webkitAudioContext;
  // 오디오 문맥은 **누른 그 순간에** 만든다 — iOS 사파리 · 크롬은 사용자 조작 밖에서 만든 문맥을 멈춰(suspended) 둔다
  const ctx = new AC();
  let st = { final: '', speaking: false, ready: false, done: false, reason: '', error: null };
  let ws = null;
  let stream = null;
  let node = null;
  let source = null;
  let closed = false;       // 우리가 끝냈다 — 그 뒤 소리 · 글은 버린다
  let finishing = null;     // finish() 가 기다리는 { resolve, timer }
  let failed = false;
  let stopQueued = false;   // 연결이 열리기 전에 finish() — 열리면 쥔 소리를 보낸 뒤 stop
  const queue = [];         // 연결 전 소리 (ArrayBuffer)
  const down = makeDownsampler(ctx.sampleRate);
  let pending = new Float32Array(0);

  /** code: limit · idle(브리지가 끝냄 — 다시 켜면 된다) · busy · upstream · closed · mic */
  const fail = (message, code = 'upstream') => {
    if (failed || closed) return;
    failed = true;
    teardown();
    try { onError(message, { code }); } catch (_) { /* 호출부 오류는 삼킨다 */ }
  };

  const settleFinish = () => {
    if (!finishing) return;
    const f = finishing;
    finishing = null;
    clearTimeout(f.timer);
    f.resolve(st.final.trim());
  };

  const teardown = () => {
    closed = true;
    clearTimeout(openTimer);
    try { if (node) { node.port && (node.port.onmessage = null); node.onaudioprocess = null; node.disconnect(); } } catch (_) { /* 이미 끊김 */ }
    try { if (source) source.disconnect(); } catch (_) { /* 이미 끊김 */ }
    if (stream) stream.getTracks().forEach((t) => t.stop());
    if (ctx.state !== 'closed') ctx.close().catch(() => {});
    if (ws && ws.readyState <= 1) { try { ws.close(1000); } catch (_) { /* 이미 닫힘 */ } }
    settleFinish();
  };

  const send = (buf) => {
    if (closed || st.done) return;
    if (ws && ws.readyState === 1) ws.send(buf);
    else if (queue.length < 100) queue.push(buf);    // 10초까지 쥐고 있다 (브리지도 ready 전 소리를 쥔다)
  };

  const onSamples = (f32) => {
    if (closed) return;
    const out = down(f32);
    const merged = new Float32Array(pending.length + out.length);
    merged.set(pending, 0);
    merged.set(out, pending.length);
    let at = 0;
    while (merged.length - at >= LIVE_STT_FRAME_SAMPLES) {
      send(floatTo16(merged.subarray(at, at + LIVE_STT_FRAME_SAMPLES)));
      at += LIVE_STT_FRAME_SAMPLES;
    }
    pending = merged.slice(at);
  };

  const onMessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch (_) { return; }
    if (closed && !finishing) return;
    const r = liveSttApply(st, msg);
    st = r.state;
    if (r.changed === 'ready') {
      clearTimeout(openTimer);
      if (typeof onReady === 'function') onReady();
    } else if (r.changed === 'speech') {
      if (typeof onSpeech === 'function') onSpeech(st.speaking);
    } else if (r.changed === 'text') {
      if (typeof onSpeech === 'function') onSpeech(false);
      onText({ final: st.final, interim: '' });
    } else if (r.changed === 'done') {
      if (finishing) { teardown(); return; }
      // 브리지가 먼저 끝냈다 (세션 상한 · 오래 조용함) — 받은 글은 그대로 두고 알린다
      fail(st.reason === 'limit' ? '받아쓰기 시간이 다 됐어요.' : '한동안 소리가 없어서 받아쓰기를 멈췄어요.',
        st.reason === 'limit' ? 'limit' : 'idle');
    } else if (r.changed === 'error') {
      fail(st.error.message || '받아쓰기 서버에 닿지 못했어요.', st.error.code);
    }
  };

  const openTimer = setTimeout(() => { if (!st.ready) fail('받아쓰기 서버에 닿지 못했어요.'); }, OPEN_WAIT_MS);

  const startAudio = async () => {
    // 장치는 고르지 않는다 — mic_pref.js 가 getUserMedia 를 감싸 연속성(iPhone) 마이크 대신 컴퓨터 마이크를 넣는다.
    // 잡음 억제 · 자동 음량은 끈다 — 켜면 A.X 가 문장 가운데서 끊어 「몰리는가를」 의 「가」 를 잃었다(10-15 헤드리스 실측, 끄면 원본 PCM 과 같은 글)
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: false, autoGainControl: false },
    });
    if (closed) { stream.getTracks().forEach((t) => t.stop()); return; }
    if (ctx.state === 'suspended') await ctx.resume().catch(() => {});
    source = ctx.createMediaStreamSource(stream);
    if (ctx.audioWorklet && workletUrl) {
      await ctx.audioWorklet.addModule(workletUrl);
      if (closed) return;
      node = new AudioWorkletNode(ctx, 'cc-pcm-tap');
      node.port.onmessage = (e) => onSamples(e.data);
      source.connect(node);
      // 출력에 소리를 안 낸다 — 일부 브라우저는 그래프 끝이 출력에 닿아야 돌린다. 무음(gain 0)으로 잇는다
      const mute = ctx.createGain();
      mute.gain.value = 0;
      node.connect(mute).connect(ctx.destination);
    } else {
      // AudioWorklet 이 없는 옛 사파리 — ScriptProcessor (주 스레드)
      node = ctx.createScriptProcessor(4096, 1, 1);
      node.onaudioprocess = (e) => onSamples(new Float32Array(e.inputBuffer.getChannelData(0)));
      source.connect(node);
      node.connect(ctx.destination);
    }
  };

  try {
    ws = new WebSocket(liveSttUrl(base, purpose));
    ws.binaryType = 'arraybuffer';
  } catch (err) {
    clearTimeout(openTimer);
    teardown();
    throw new Error('받아쓰기 서버에 닿지 못했어요.');
  }
  ws.onopen = () => {
    while (queue.length && ws.readyState === 1) ws.send(queue.shift());
    if (stopQueued) ws.send(JSON.stringify({ type: 'stop' }));
  };
  ws.onmessage = onMessage;
  ws.onerror = () => { /* onclose 가 이어서 온다 */ };
  ws.onclose = () => {
    if (finishing) { settleFinish(); teardown(); return; }
    if (!closed && !st.done) fail('받아쓰기 서버와 연결이 끊겼어요.', 'closed');
  };
  startAudio().catch((err) => fail(ERRORS[err && err.name] || '마이크를 열지 못했어요.', 'mic'));

  return {
    get speaking() { return st.speaking; },
    get ready() { return st.ready; },
    stop() {
      const text = st.final.trim();
      if (!closed && ws && ws.readyState === 1) { try { ws.send(JSON.stringify({ type: 'cancel' })); } catch (_) { /* 닫힘 */ } }
      teardown();
      return text;
    },
    finish() {
      if (closed || failed) return Promise.resolve(st.final.trim());
      // 마이크부터 끊는다 — 멈춘 뒤의 소리는 보내지 않는다. 남은 반쪽 프레임은 같이 보낸다
      if (pending.length) { send(floatTo16(pending)); pending = new Float32Array(0); }
      try { if (node) node.disconnect(); } catch (_) { /* 이미 끊김 */ }
      if (stream) stream.getTracks().forEach((t) => t.stop());
      return new Promise((resolve) => {
        finishing = { resolve, timer: setTimeout(() => { settleFinish(); teardown(); }, FINISH_WAIT_MS) };
        if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: 'stop' }));
        else if (ws && ws.readyState === 0) stopQueued = true;
        else { settleFinish(); teardown(); }
      });
    },
  };
}
