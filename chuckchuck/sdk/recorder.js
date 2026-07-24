/**
 * [F-03] 마이크 녹음만 담당하는 브라우저 SDK입니다.
 * 발표 음성을 audio blob으로 만듭니다.
 */

export class PresentationRecorder {
  constructor({
    mimeType = _pickMime(),
    timesliceMs = 1000,
    onTick = null,
    onState = null,
  } = {}) {
    this.mimeType = mimeType;
    this.timesliceMs = timesliceMs;
    this.onTick = onTick;
    this.onState = onState;

    this._stream = null;
    this._recorder = null;
    this._chunks = [];
    this._startedAt = 0;
    this._raf = 0;
    this.state = 'idle'; // idle | requesting | recording | denied | stopped
  }

  /** 녹음 시작 후 경과 초 (상대 타임라인). */
  get elapsedSec() {
    if (!this._startedAt) return 0;
    return (performance.now() - this._startedAt) / 1000;
  }

  async start() {
    this._setState('requesting');
    try {
      this._stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          channelCount: 1,
        },
      });
    } catch (err) {
      this._setState('denied');
      throw err;
    }

    this._chunks = [];
    const opts = this.mimeType ? { mimeType: this.mimeType } : undefined;
    this._recorder = new MediaRecorder(this._stream, opts);
    this.mimeType = this._recorder.mimeType || this.mimeType;

    this._recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) this._chunks.push(e.data);
    };

    this._startedAt = performance.now();
    this._recorder.start(this.timesliceMs);
    this._setState('recording');
    this._tick();
    return { startedAt: this._startedAt, mimeType: this.mimeType };
  }

  async stop() {
    if (!this._recorder || this.state !== 'recording') {
      return { blob: null, mimeType: this.mimeType, durationSec: 0, chunks: [] };
    }

    const durationSec = this.elapsedSec;
    const blob = await new Promise((resolve) => {
      this._recorder.onstop = () => {
        resolve(new Blob(this._chunks, { type: this.mimeType || 'audio/webm' }));
      };
      this._recorder.stop();
    });

    this._cleanupStream();
    cancelAnimationFrame(this._raf);
    this._setState('stopped');

    return {
      blob,
      mimeType: blob.type || this.mimeType,
      durationSec,
      chunks: this._chunks.slice(),
    };
  }

  /** FormData 로 바로 서버에 올릴 때. */
  async toFormData(fieldName = 'audio') {
    const { blob, mimeType, durationSec } = await this.stop();
    const fd = new FormData();
    const ext = mimeType.includes('mp4') ? 'm4a' : 'webm';
    fd.append(fieldName, blob, `recording.${ext}`);
    fd.append('duration_sec', String(durationSec));
    fd.append('mime_type', mimeType);
    return fd;
  }

  _tick = () => {
    if (this.state !== 'recording') return;
    if (typeof this.onTick === 'function') this.onTick(this.elapsedSec);
    this._raf = requestAnimationFrame(this._tick);
  };

  _cleanupStream() {
    if (this._stream) {
      this._stream.getTracks().forEach((t) => t.stop());
      this._stream = null;
    }
  }

  _setState(s) {
    this.state = s;
    if (typeof this.onState === 'function') this.onState(s);
  }
}

function _pickMime() {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4',
  ];
  if (typeof MediaRecorder === 'undefined') return '';
  return candidates.find((m) => MediaRecorder.isTypeSupported(m)) || '';
}
