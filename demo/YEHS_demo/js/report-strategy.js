/*
리포트 '연습 도구 › 발표 구성' 화면입니다. (F-20)

이 발표를 어떤 순서로 다시 짜면 좋을지 LLM 에게 묻고, 1순위 하나만 펼쳐서
보여줍니다. 나머지는 "다른 방법도 있어요" 한 줄로만 남깁니다 — 넷을 나란히
늘어놓으면 고르라는 화면이 되지, 제안하는 화면이 못 됩니다.

유형 이름에 실존 인물이 들어가지만 그 사람의 말을 옮기지 않습니다. 이름은
구성 방식을 가리키는 수식어이고, 모든 문장은 "당신의 발표를 이렇게 바꾸면"
관점입니다. 화면 아래에 그 사실을 명시합니다.

호출 규약
  ReportStrategy.render(hostEl, { sessionId, analysis })
  analysis 는 /api/v1/strategy 요청 본문의 analysis 필드 그대로입니다.
*/
window.ReportStrategy = (function () {
  'use strict';

  const CACHE_KEY = 'cheokcheok:strategy';
  const ENDPOINT = '/api/v1/strategy';

  /** 핵심을 어디에 두는 구성인가 — 서버가 유형 표에서 채워 준 값을 사람 말로. */
  const CLIMAX = {
    early: { label: '핵심을 앞에', desc: '결론을 먼저 던지고 나머지를 근거로 씁니다.' },
    late: { label: '핵심을 뒤에', desc: '쌓아 올리다 마지막 한 방으로 남깁니다.' },
    throughline: { label: '축 하나로 관통', desc: '주장 하나를 세우고 전부 거기에 종속시킵니다.' },
  };

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── 캐시 ─────────────────────────────────────────────────────────────
  // 탭을 오갈 때마다 LLM 을 다시 부르면 느리고 비싸다. 같은 세션이면 재사용한다.

  function readCache() {
    try {
      const raw = sessionStorage.getItem(CACHE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (err) {
      console.error('구성 제안 캐시를 읽지 못했어요:', err);
      return {};
    }
  }

  function cacheGet(sessionId) {
    return sessionId ? (readCache()[sessionId] || null) : null;
  }

  function cacheSet(sessionId, data) {
    if (!sessionId) return;
    try {
      sessionStorage.setItem(CACHE_KEY, JSON.stringify({ ...readCache(), [sessionId]: data }));
    } catch (err) {
      // 캐시는 편의일 뿐이라 실패해도 화면은 그대로 간다
      console.error('구성 제안 캐시를 저장하지 못했어요:', err);
    }
  }

  function invalidate(sessionId) {
    if (!sessionId) {
      sessionStorage.removeItem(CACHE_KEY);
      return;
    }
    const next = { ...readCache() };
    delete next[sessionId];
    try {
      sessionStorage.setItem(CACHE_KEY, JSON.stringify(next));
    } catch (err) {
      console.error('구성 제안 캐시를 비우지 못했어요:', err);
    }
  }

  // ── 호출 ─────────────────────────────────────────────────────────────

  async function requestStrategy(analysis) {
    let res;
    try {
      res = await fetch(ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ analysis }),
      });
    } catch (err) {
      console.error('구성 제안 요청이 닿지 않았어요:', err);
      throw new Error('서버에 닿지 못했어요. 데모 서버가 켜져 있는지 확인해 주세요.');
    }
    let body = null;
    try {
      body = await res.json();
    } catch (err) {
      console.error('구성 제안 응답을 읽지 못했어요:', err);
      throw new Error(`응답을 읽지 못했어요 (HTTP ${res.status}).`);
    }
    if (!res.ok) {
      throw new Error((body && body.message) || `구성 제안에 실패했어요 (HTTP ${res.status}).`);
    }
    if (!body || !body.chosen || !(body.chosen.outline || []).length) {
      throw new Error('구성표가 비어 있어요. 잠시 뒤 다시 시도해 주세요.');
    }
    return body;
  }

  /** 제안을 만들 만한 재료가 있는가. 없으면 부르지 않는다. */
  function hasEnoughInput(analysis) {
    if (!analysis) return false;
    const concepts = analysis.concepts || [];
    const alloc = analysis.time_alloc || [];
    const quotes = analysis.quotes || [];
    return concepts.length + alloc.length + quotes.length >= 2;
  }

  // ── 화면 ─────────────────────────────────────────────────────────────

  /** 슬라이드 번호 묶음을 'S01-S04' 처럼 이어 붙인다. 흩어져 있으면 쉼표로. */
  function slideRange(nos) {
    if (!nos || !nos.length) return '';
    const sorted = [...nos].sort((a, b) => a - b);
    const runs = [];
    sorted.forEach((n) => {
      const last = runs[runs.length - 1];
      if (last && n === last[1] + 1) last[1] = n;
      else runs.push([n, n]);
    });
    const pad = n => `S${String(n).padStart(2, '0')}`;
    return runs.map(([a, b]) => (a === b ? pad(a) : `${pad(a)}-${pad(b)}`)).join(', ');
  }

  /** 'M:SS'·'MM:SS' → 초. 그 형식이 아니면 null. */
  function parseMarkSec(text) {
    const m = /^(\d+):(\d{2})$/.exec(String(text || '').trim());
    return m ? Number(m[1]) * 60 + Number(m[2]) : null;
  }

  function fmtMin(sec) {
    return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;
  }

  /**
   * 구간별 「지금 → 제안」 시간 대비. 제안이 내 실측에서 나왔음을 구간마다 증명한다.
   * 실측이 없는 장이 하나라도 섞이면 만들지 않는다 — 반쪽 합계는 거짓말이다.
   */
  function blockDelta(b, spentBySlide) {
    const from = parseMarkSec(b.from);
    const to = parseMarkSec(b.to);
    const proposed = from != null && to != null && to > from ? to - from : null;
    if (b.new) return proposed != null ? `새로 ${fmtMin(proposed)}` : '';
    if (!b.slides || !b.slides.length) return '';
    let sum = 0;
    for (const n of b.slides) {
      const sec = spentBySlide[n];
      if (sec == null) return '';
      sum += sec;
    }
    return proposed != null ? `지금 ${fmtMin(sum)} → 제안 ${fmtMin(proposed)}` : `지금 ${fmtMin(sum)}`;
  }

  /** 재구성한 발표 순서표. 이게 이 화면의 본문이다. */
  function outlineHtml(outline, spentBySlide) {
    if (!outline || !outline.length) return '';
    return `
      <ol class="strat-outline">
        ${outline.map((b, i) => {
          const delta = blockDelta(b, spentBySlide || {});
          return `
        <li class="strat-block${b.new ? ' is-new' : ''}">
          <div class="strat-block-head">
            <span class="strat-no">${String(i + 1).padStart(2, '0')}</span>
            <b class="strat-role">${esc(b.role)}</b>
            ${b.from && b.to ? `<span class="strat-span">${esc(b.from)}–${esc(b.to)}</span>` : ''}
            <span class="strat-slides">${b.new ? '새로 만들기' : esc(slideRange(b.slides))}</span>
          </div>
          <p class="strat-what">${esc(b.what)}</p>
          ${delta ? `<p class="strat-delta">${esc(delta)}</p>` : ''}
          ${b.add ? `<p class="strat-add"><span>추가</span>${esc(b.add)}</p>` : ''}
        </li>`;
        }).join('')}
      </ol>`;
  }

  /** 왜 바꿔야 하는가 — 서버가 입력 값 대조로 걸러낸 근거만 온다. 없으면 그리지 않는다. */
  function gainsHtml(gains) {
    if (!gains || !gains.length) return '';
    return `
      <div class="strat-gains">
        <span class="strat-tag">이 순서로 바꾸면</span>
        <ul>
          ${gains.map(g => `
          <li><b>${esc(g.claim)}</b><small>${esc(g.evidence)}</small></li>`).join('')}
        </ul>
      </div>`;
  }

  function keepHtml(keep) {
    if (!keep || !keep.quote) return '';
    return `
      <div class="strat-keep">
        <span class="strat-tag">그대로 살릴 문장</span>
        <blockquote>“${esc(keep.quote)}”</blockquote>
        ${keep.at ? `<small>${esc(keep.at)}에 실제로 하신 말이에요.</small>` : ''}
      </div>`;
  }

  function altsHtml(alternatives) {
    if (!alternatives || !alternatives.length) return '';
    return `
      <div class="strat-alts">
        <p class="strat-alts-head">다른 방법도 있어요</p>
        <ul>
          ${alternatives.map(a => `
          <li><b>${esc(a.type)}</b> — ${esc(a.one_line)}</li>`).join('')}
        </ul>
      </div>`;
  }

  function resultHtml(data, analysis) {
    const c = data.chosen || {};
    const climax = CLIMAX[c.climax] || { label: '구성 제안', desc: '' };
    // 순서표 델타 계산용 — 슬라이드별 실측 사용 시간
    const spentBySlide = {};
    (((analysis || {}).slides) || []).forEach((s) => {
      const sec = parseMarkSec(s.spent);
      if (s.no != null && sec != null) spentBySlide[s.no] = sec;
    });
    return `
      <div class="card strat-card">
        <div class="strat-head">
          <span class="strat-badge">${esc(climax.label)}</span>
          <h3 class="strat-type">${esc(c.type)}</h3>
          <p class="strat-climax">${esc(climax.desc)}</p>
        </div>
        ${c.why ? `<p class="strat-why">${esc(c.why)}</p>` : ''}
        ${gainsHtml(c.gains)}
        <span class="strat-tag">이 순서로 다시 짜 보세요</span>
        ${outlineHtml(c.outline, spentBySlide)}
        ${keepHtml(c.keep)}
      </div>
      ${altsHtml(data.alternatives)}
      <p class="note strat-disclaim">
        유형 이름의 인물은 <b>구성 방식을 가리키는 수식어</b>예요.
        그분들이 한 말을 옮기거나 지어내지 않아요 — 제안은 전부 이 발표의 실제 수치와 발화에서 나옵니다.
      </p>
      <div class="strat-actions">
        <button class="btn btn-secondary btn-sm" data-strat="retry">다시 제안받기</button>
      </div>`;
  }

  function introHtml() {
    return `
      <div class="card strat-intro">
        <h3 class="section-title">이 발표, 순서를 바꾼다면</h3>
        <p class="note">
          개념 판정과 구간별 시간, 실제 발화를 함께 읽어서
          <b>핵심을 앞에 둘지 뒤에 남길지</b>부터 정하고 재배치를 제안해요.
        </p>
        <div class="step-actions">
          <button class="btn btn-primary" data-strat="go">구성 제안받기</button>
        </div>
      </div>`;
  }

  function emptyHtml() {
    return `
      <div class="card">
        <h3 class="section-title">아직 제안할 재료가 없어요</h3>
        <p class="note">개념 판정이나 실제 발화가 있어야 구성을 다시 짤 수 있어요.
          리허설을 마치고 분석이 끝나면 여기에 제안이 생깁니다.</p>
        <div class="step-actions"><a class="btn btn-primary" href="#/new">발표 연습으로</a></div>
      </div>`;
  }

  function loadingHtml() {
    return `
      <div class="card strat-loading">
        <p class="note">발표 내용을 읽고 어떤 구성이 맞을지 고르는 중이에요…</p>
      </div>`;
  }

  function errorHtml(message) {
    return `
      <div class="card strat-error">
        <h3 class="section-title">구성을 제안하지 못했어요</h3>
        <p class="note">${esc(message)}</p>
        <div class="step-actions">
          <button class="btn btn-secondary" data-strat="retry">다시 시도</button>
        </div>
      </div>`;
  }

  /**
   * 호스트 엘리먼트 안에 구성 제안 화면을 그린다.
   * 이미 받아 둔 제안이 있으면 바로 결과부터 보여준다.
   */
  function render(host, options) {
    if (!host) {
      console.error('구성 제안을 그릴 대상이 없어요.');
      return;
    }
    const opts = options || {};
    const sessionId = opts.sessionId || '';
    const analysis = opts.analysis || null;

    if (!hasEnoughInput(analysis)) {
      host.innerHTML = emptyHtml();
      return;
    }

    const paint = (html) => {
      host.innerHTML = html;
      const btn = host.querySelector('[data-strat="go"], [data-strat="retry"]');
      if (btn) btn.addEventListener('click', () => { invalidate(sessionId); load(); });
    };

    async function load() {
      paint(loadingHtml());
      try {
        const data = await requestStrategy(analysis);
        cacheSet(sessionId, data);
        paint(resultHtml(data, analysis));
      } catch (err) {
        console.error('구성 제안 실패:', err);
        paint(errorHtml(err.message || '알 수 없는 이유로 실패했어요.'));
      }
    }

    const hit = cacheGet(sessionId);
    paint(hit ? resultHtml(hit, analysis) : introHtml());
  }

  return { render, invalidate };
})();
