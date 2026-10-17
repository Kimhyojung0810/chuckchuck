/**
 * 실시간 받아쓰기(js/live_stt.js)의 마이크 꼭지 — AudioWorklet 안에서 도는 처리기.
 * 128표본씩 오는 입력을 2048표본쯤 모아 주 스레드로 넘긴다(16kHz 로 줄이기 · PCM16 바꾸기는 live_stt.js 의 순수 함수가 한다).
 */
class CcPcmTap extends AudioWorkletProcessor {
  constructor() {
    super();
    this.chunks = [];
    this.count = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch && ch.length) {
      this.chunks.push(new Float32Array(ch));
      this.count += ch.length;
      if (this.count >= 2048) {
        const out = new Float32Array(this.count);
        let at = 0;
        for (const c of this.chunks) { out.set(c, at); at += c.length; }
        this.port.postMessage(out, [out.buffer]);
        this.chunks = [];
        this.count = 0;
      }
    }
    return true;
  }
}

registerProcessor('cc-pcm-tap', CcPcmTap);
