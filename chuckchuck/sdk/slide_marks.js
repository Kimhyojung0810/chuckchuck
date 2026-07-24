/**
 * [F-04] 슬라이드를 넘긴 시각을 기록하는 브라우저 SDK입니다.
 * 녹음 타임라인과 맞춰 SlideMark 목록을 만듭니다.
 */

export class SlideMarkTracker {
  constructor({ getElapsedSec }) {
    if (typeof getElapsedSec !== 'function') {
      throw new Error('getElapsedSec() 콜백이 필요합니다.');
    }
    this.getElapsedSec = getElapsedSec;
    this.visits = {}; // slide_no → visit count
    this.log = []; // 사람이 읽는 로그용 [{sec, slide, visit, back}]
    this._open = null; // { slide_no, start_sec, visit }
    this._marks = [];
  }

  /** 녹음/리허설 시작 시 첫 슬라이드. */
  start(slideNo = 1) {
    this.visits = {};
    this.log = [];
    this._marks = [];
    this._open = null;
    this.goTo(slideNo, { initial: true });
  }

  /**
   * 슬라이드 이동.
   * @param {number} slideNo
   * @param {{ initial?: boolean }} [opts]
   */
  goTo(slideNo, opts = {}) {
    const sec = Math.max(0, this.getElapsedSec());
    this._closeOpen(sec);

    const prev = this.visits[slideNo] || 0;
    const visit = prev + 1;
    this.visits[slideNo] = visit;

    this._open = { slide_no: slideNo, start_sec: sec, visit };
    this.log.push({
      sec,
      slide: slideNo,
      visit,
      back: !opts.initial && visit > 1,
    });
  }

  /** 녹음 종료 — 열린 구간을 닫고 SlideMark 리스트 반환. */
  finish(endSec = null) {
    const sec = endSec == null ? Math.max(0, this.getElapsedSec()) : endSec;
    this._closeOpen(sec);
    return this._marks.map((m) => ({ ...m }));
  }

  /** contracts.SlideMark.to_dict() 와 동일한 형태. */
  toJSON() {
    return this.finish();
  }

  _closeOpen(endSec) {
    if (!this._open) return;
    const start = this._open.start_sec;
    const end = Math.max(start, endSec);
    // 0.3초 미만은 실수 클릭으로 보고 버림 (Claude SDK와 동일)
    if (end - start >= 0.3) {
      this._marks.push({
        slide_no: this._open.slide_no,
        start_sec: round3(start),
        end_sec: round3(end),
        visit: this._open.visit,
      });
    } else if (this.visits[this._open.slide_no]) {
      this.visits[this._open.slide_no] -= 1;
    }
    this._open = null;
  }
}

function round3(n) {
  return Math.round(n * 1000) / 1000;
}

/**
 * 데모 화면용 로그 포맷: "02:04 → 4번 슬라이드"
 */
export function formatMarkLog(entry) {
  const mm = String(Math.floor(entry.sec / 60)).padStart(2, '0');
  const ss = String(Math.floor(entry.sec % 60)).padStart(2, '0');
  if (entry.back) {
    return `${mm}:${ss} ↩ ${entry.slide}번 슬라이드 (${entry.visit}번째 방문)`;
  }
  return `${mm}:${ss} → ${entry.slide}번 슬라이드`;
}
