/**
 * [F-03+F-04] 녹음과 슬라이드 넘김을 한 번에 다루는 통합 녹음기입니다.
 * 리허설 화면에서 주로 이 클래스를 씁니다.
 */

class RehearsalRecorder {
  /**
   * @param {object} opts
   * @param {number} opts.totalSlides         전체 슬라이드 수
   * @param {string} [opts.mimeType]          기본은 브라우저가 지원하는 것 자동 선택
   * @param {function} [opts.onSlideChange]   (slideNo, visit, elapsedSec) => void
   * @param {function} [opts.onTick]          (elapsedSec) => void  타이머 표시용
   * @param {function} [opts.onLevel]         (0~1) => void  음성 레벨 미터용
   */
  constructor(opts = {}) {
    this.totalSlides = opts.totalSlides || 1;
    this.mimeType = opts.mimeType || RehearsalRecorder.pickMimeType();
    this.onSlideChange = opts.onSlideChange || (() => {});
    this.onTick = opts.onTick || (() => {});
    this.onLevel = opts.onLevel || null;

    this.state = 'idle';        // idle | requesting | recording | paused | stopped
    this.currentSlide = 1;

    this._stream = null;
    this._recorder = null;
    this._chunks = [];
    this._startedAt = 0;        // performance.now() 기준
    this._pausedTotal = 0;
    this._pausedAt = 0;
    this._marks = [];           // 확정된 구간
    this._openMark = null;      // 아직 안 끝난 현재 구간
    this._visits = {};          // slideNo -> 방문 횟수
    this._timer = null;
    this._audioCtx = null;
  }

  /** 브라우저가 지원하는 오디오 포맷 고르기 */
  static pickMimeType() {
    const candidates = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/mp4',
      'audio/ogg;codecs=opus',
    ];
    for (const t of candidates) {
      if (window.MediaRecorder && MediaRecorder.isTypeSupported(t)) return t;
    }
    return '';
  }

  /** 녹음 시작을 0으로 한 상대 시각(초) */
  elapsed() {
    if (!this._startedAt) return 0;
    const now = this.state === 'paused' ? this._pausedAt : performance.now();
    return (now - this._startedAt - this._pausedTotal) / 1000;
  }

  // ---------------------------------------------------------------- F-03

  /**
   * 마이크 권한을 요청하고 녹음을 시작한다.
   * 이 시점이 타임라인의 0초다.
   */
  async start() {
    if (this.state === 'recording') return;
    this.state = 'requesting';

    try {
      this._stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (err) {
      this.state = 'idle';
      throw new RecorderError(
        err.name === 'NotAllowedError'
          ? '마이크 권한이 필요해요. 브라우저 주소창의 자물쇠 아이콘에서 허용해주세요.'
          : `마이크를 열 수 없어요: ${err.message}`,
        err.name
      );
    }

    this._chunks = [];
    this._recorder = new MediaRecorder(
      this._stream,
      this.mimeType ? { mimeType: this.mimeType } : undefined
    );
    this._recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) this._chunks.push(e.data);
    };
    this._recorder.start(1000);   // 1초마다 조각 저장 — 중간에 끊겨도 살아남게

    this._startedAt = performance.now();
    this._pausedTotal = 0;
    this.state = 'recording';

    // 첫 슬라이드 구간 열기
    this._openSlide(this.currentSlide);

    this._timer = setInterval(() => this.onTick(this.elapsed()), 200);
    if (this.onLevel) this._startLevelMeter();
  }

  pause() {
    if (this.state !== 'recording') return;
    this._recorder.pause();
    this._pausedAt = performance.now();
    this.state = 'paused';
  }

  resume() {
    if (this.state !== 'paused') return;
    this._pausedTotal += performance.now() - this._pausedAt;
    this._recorder.resume();
    this.state = 'recording';
  }

  /**
   * 녹음을 끝내고 결과를 돌려준다.
   * @returns {Promise<{audioBlob: Blob, marks: Array, durationSec: number}>}
   */
  async stop() {
    if (this.state === 'idle' || this.state === 'stopped') {
      throw new RecorderError('녹음 중이 아닙니다.');
    }
    const endAt = this.elapsed();
    this._closeSlide(endAt);
    clearInterval(this._timer);

    const blob = await new Promise((resolve) => {
      this._recorder.onstop = () => {
        resolve(new Blob(this._chunks, { type: this.mimeType || 'audio/webm' }));
      };
      this._recorder.stop();
    });

    this._stream.getTracks().forEach((t) => t.stop());
    if (this._audioCtx) this._audioCtx.close();
    this.state = 'stopped';

    return { audioBlob: blob, marks: this.marks(), durationSec: endAt };
  }

  // ---------------------------------------------------------------- F-04

  /**
   * 슬라이드 이동. 넘긴 시각이 자동으로 기록된다.
   * 되돌아가기도 그냥 goTo 로 처리하면 된다 — 재방문으로 따로 남는다.
   */
  goTo(slideNo) {
    const n = Math.max(1, Math.min(this.totalSlides, slideNo));
    if (n === this.currentSlide) return;

    if (this.state === 'recording' || this.state === 'paused') {
      const t = this.elapsed();
      this._closeSlide(t);
      this.currentSlide = n;
      this._openSlide(n, t);
    } else {
      this.currentSlide = n;   // 녹음 전이면 그냥 이동만
    }
    this.onSlideChange(this.currentSlide, this._visits[this.currentSlide] || 1, this.elapsed());
  }

  next() { this.goTo(this.currentSlide + 1); }
  prev() { this.goTo(this.currentSlide - 1); }

  /** 좌우 방향키로 슬라이드를 넘기게 한다. 해제 함수를 돌려준다. */
  bindKeys(target = window) {
    const handler = (e) => {
      if (e.key === 'ArrowRight' || e.key === 'PageDown') { e.preventDefault(); this.next(); }
      if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); this.prev(); }
    };
    target.addEventListener('keydown', handler);
    return () => target.removeEventListener('keydown', handler);
  }

  _openSlide(slideNo, at = 0) {
    this._visits[slideNo] = (this._visits[slideNo] || 0) + 1;
    this._openMark = {
      slide_no: slideNo,
      start_sec: round3(at),
      end_sec: null,
      visit: this._visits[slideNo],
    };
  }

  _closeSlide(at) {
    if (!this._openMark) return;
    this._openMark.end_sec = round3(at);
    // 0.3초도 안 머문 건 실수로 넘긴 것 — 버린다
    if (this._openMark.end_sec - this._openMark.start_sec >= 0.3) {
      this._marks.push(this._openMark);
    } else {
      this._visits[this._openMark.slide_no] -= 1;
    }
    this._openMark = null;
  }

  /**
   * 지금까지의 슬라이드 구간.
   * contracts.py 의 SlideMark 와 같은 모양이라 그대로 서버로 보내면 된다.
   */
  marks() {
    const out = this._marks.slice();
    if (this._openMark) {
      out.push({ ...this._openMark, end_sec: round3(this.elapsed()) });
    }
    return out;
  }

  /** 화면에 보여줄 이동 기록 — "02:04 → 4번 슬라이드" */
  timeline() {
    return this.marks().map((m) => ({
      time: fmt(m.start_sec),
      slide: m.slide_no,
      revisit: m.visit > 1,
      label: m.visit > 1
        ? `${fmt(m.start_sec)} ↩ ${m.slide_no}번 슬라이드 (${m.visit}번째 방문)`
        : `${fmt(m.start_sec)} → ${m.slide_no}번 슬라이드`,
    }));
  }

  // ---------------------------------------------------------------- 부가

  _startLevelMeter() {
    this._audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const src = this._audioCtx.createMediaStreamSource(this._stream);
    const analyser = this._audioCtx.createAnalyser();
    analyser.fftSize = 512;
    src.connect(analyser);
    const buf = new Uint8Array(analyser.frequencyBinCount);

    const loop = () => {
      if (this.state === 'stopped') return;
      analyser.getByteTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) sum += (v - 128) ** 2;
      this.onLevel(Math.min(1, Math.sqrt(sum / buf.length) / 40));
      requestAnimationFrame(loop);
    };
    loop();
  }

  /** 중간 저장용 — 나갔다 돌아와도 이어할 수 있게 */
  snapshot() {
    return {
      currentSlide: this.currentSlide,
      elapsed: this.elapsed(),
      marks: this.marks(),
      state: this.state,
    };
  }
}

class RecorderError extends Error {
  constructor(message, code = '') {
    super(message);
    this.name = 'RecorderError';
    this.code = code;
  }
}

const round3 = (n) => Math.round(n * 1000) / 1000;
const fmt = (sec) => {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
};

/**
 * 서버로 보내기 — F-05 로 넘어가는 지점.
 *
 *   const result = await uploadRehearsal('/api/v1/rehearsal', audioBlob, marks, sessionId);
 */
async function uploadRehearsal(endpoint, audioBlob, marks, sessionId) {
  const fd = new FormData();
  fd.append('audio', audioBlob, `rehearsal-${sessionId || Date.now()}.webm`);
  fd.append('marks', JSON.stringify(marks));
  if (sessionId) fd.append('session_id', sessionId);

  const res = await fetch(endpoint, { method: 'POST', body: fd });
  if (!res.ok) {
    throw new RecorderError(`업로드 실패 ${res.status}: ${await res.text()}`);
  }
  return res.json();
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { RehearsalRecorder, RecorderError, uploadRehearsal };
}

// 브라우저 전역 (데모 / ES module bridge)
if (typeof globalThis !== 'undefined') {
  globalThis.RehearsalRecorder = RehearsalRecorder;
  globalThis.RecorderError = RecorderError;
  globalThis.uploadRehearsal = uploadRehearsal;
}
