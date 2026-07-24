/**
 * 새 브라우저 SDK를 만들 때 복사하는 템플릿입니다.
 */

export class MyClient {
  constructor(options = {}) {
    this._items = [];
    this._options = options;
  }

  /** 예시 이벤트 — 실제 F-ID 책임에 맞게 이름 변경 */
  push(slideNo, label, atSec) {
    this._items.push({
      slide_no: slideNo,
      label: label || '',
      score: 0,
      at_sec: Math.round(Number(atSec) * 1000) / 1000,
    });
  }

  /** 서버가 from_dict 할 수 있는 ours JSON */
  toJSON() {
    return {
      items: this._items.map((x) => ({ ...x })),
    };
  }

  /**
   * POST /api/v1/{action}
   * @param {string} endpoint
   * @param {object} [extra] 요청에 붙일 추가 ours 필드
   */
  async upload(endpoint, extra = {}) {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...this.toJSON(), ...extra }),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`upload failed ${res.status}: ${text}`);
    }
    return res.json(); // ours
  }
}

export class SdkError extends Error {
  constructor(message, code = '') {
    super(message);
    this.name = 'SdkError';
    this.code = code;
  }
}
