/**
 * 리포트의 「발표 태도 · 베타」 — 카메라 분석(js/behavior_cv_logic.js) 결과를 그린다. 이 파일만 그리고, 리포트 쪽은 몇 줄로 부른다
 * (옛 리포트 app.js rSummary · 리포트 2.0 report_v2.js — 리포트 개편 때 옮기기 쉽게).
 *
 * 입력 b = nf.behavior = { present: 묶음 | null, qa: 묶음 | null }. 묶음 = analyze() 결과(화면용) 또는 summaryOf()(숫자만) — 둘 다 그린다.
 * 화면 규칙: 갈래마다 3단계 낱말 + 한 줄 관찰. 숫자 · 비교 기준 · 재는 법은 「자세히 보기」 안에만.
 * 감정 · 자신감 · 성격 낱말을 쓰지 않는다. 「많을수록 좋다」 고 쓰지 않는다. 총점에 안 들어간다고 분명히 쓴다.
 *
 *  BehaviorReport.headline(b) → { status, word, oneLine, first, topEvidence[] }   — 리포트 첫 줄 하나만 보일 때
 *  BehaviorReport.html(b, { titles })                                               — 카드 통째(옛 리포트)
 *  BehaviorReport.rv2Row(b, { I, esc }) · rv2Screen(b, { titles })                   — 리포트 2.0 입구 줄 · 화면
 * 순수 함수 — 노드 스모크(etc/tests/js/behavior_cv.smoke.mjs)가 그린 글을 본다.
 */
(function (root) {
  'use strict';

  const esc = (s) => String(s === undefined || s === null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pct = (v) => (Number.isFinite(v) ? `${Math.round(v * 100)}%` : '–');
  const BETA = '베타 · 총점에 안 들어가요';
  const NONE_WORD = '카메라 분석 없음';
  const LABEL = {
    gaze: '화면 쪽을 향한 시간', lookaway: '3초 넘게 벗어난 구간', down: '아래를 본 시간', sway: '몸 좌우 흔들림',
    movement: '몸 움직임 양', gesture: '손이 움직인 시간', framing: '화면 구도',
  };
  const AREA_LABEL = { gaze: '시선 · 고개', body: '몸 움직임', hands: '손짓', frame: '구도' };
  const ORDER = ['gaze', 'lookaway', 'down', 'sway', 'movement', 'gesture', 'framing'];

  const okOf = (x) => !!(x && (x.status === 'ok'));
  const segWhere = (seg) => (/^s\d+$/.test(seg || '') ? `${seg.slice(1)}장` : /^q\d+$/.test(seg || '') ? `${seg.slice(1)}번째 질문` : '');
  const fmtSec = (s) => { if (!Number.isFinite(s)) return ''; const v = Math.max(0, Math.round(s)); return `${Math.floor(v / 60)}:${String(v % 60).padStart(2, '0')}`; };

  /** 지표 숫자를 사람 말로 (자세히 보기 안에서만) */
  function valueText(k, m) {
    if (!m || !m.ok) return '';
    if (k === 'lookaway') return `${m.n || 0}번 · 가장 길게 ${m.longest || 0}초 · 1분에 ${(m.value || 0).toFixed(1)}번`;
    if (k === 'movement') return `몸 영역 ${pct(m.value)} (0.2초 사이 바뀐 점)`;
    if (k === 'framing') return `얼굴 폭 ${pct(m.value)}${Number.isFinite(m.off) ? ` · 가운데에서 ${pct(m.off)} 비낌` : ''}`;
    if (k === 'sway') return `흔들린 10초 창 ${pct(m.value)}${Number.isFinite(m.amp) ? ` · 진폭 얼굴 폭의 ${pct(m.amp)}` : ''}`;
    if (k === 'gesture') return `${pct(m.value)}${Number.isFinite(m.speak) ? ` · 말할 때 ${pct(m.speak)} · 쉴 때 ${pct(m.silent)}` : ''}`;
    return pct(m.value);
  }

  /** 리포트 첫 줄 — 낱말 하나 · 한 줄 · 가장 먼저 고칠 한 가지 · 근거 카드 위 셋 */
  function headline(b) {
    const p = b && b.present;
    if (!okOf(p)) return { status: p ? p.status : 'none', word: NONE_WORD, oneLine: (p && p.why) || '카메라 분석이 없었어요', first: null, topEvidence: [] };
    const looks = (p.areas || []).filter((a) => a.ok && a.look);
    const word = looks.length ? `${looks.length}가지 살펴봐요` : '짚을 곳이 없어요';
    const oneLine = p.first ? p.first.text : (looks[0] ? `${looks[0].label} — ${looks[0].word}` : '카메라로 본 얼굴 방향 · 몸 · 손에서 크게 짚을 곳은 없었어요');
    const topEvidence = (p.cards || []).slice(0, 3).map((c) => ({ text: c.observation, where: c.scene ? c.scene.where : '', sec: c.scene ? c.scene.sec : null }));
    return { status: 'ok', word, oneLine, first: p.first || null, topEvidence };
  }

  function areasHtml(p) {
    return `<div class="bh-areas">${(p.areas || []).map((a) => `
      <div class="bh-area" data-look="${a.ok && a.look ? '1' : '0'}">
        <span class="bh-name">${esc(a.label || AREA_LABEL[a.key] || a.key)}</span>
        <b class="bh-word">${esc(a.word)}</b>
        <p class="bh-line">${esc(a.ok ? (a.line || '') : (a.line || '이번엔 잴 수 없었어요'))}</p>
      </div>`).join('')}</div>`;
  }

  function firstHtml(p, titles) {
    const f = p.first;
    if (!f) return '';
    const title = f.slide && titles && titles[f.slide - 1] ? titles[f.slide - 1] : '';
    const scene = [f.slide ? `${f.slide}장${title ? ` · ${title}` : ''}` : (f.q ? `${f.q}번째 질문` : ''), Number.isFinite(f.sec) ? `${fmtSec(f.sec)}부터` : ''].filter(Boolean).join(' · ');
    return `<div class="bh-first">
        <span class="bh-cap">먼저 살펴볼 한 가지</span>
        <p class="bh-first-text">${esc(f.text)}</p>
        ${scene ? `<small class="bh-scene">${esc(scene)}</small>` : ''}
        ${f.tip ? `<p class="bh-tip"><b>다음엔</b> ${esc(f.tip)}</p>` : ''}
      </div>`;
  }

  /** 근거 카드 — 화면엔 관찰 · 장면 · 신뢰도, 측정값 · 비교 기준은 접힌 칸 */
  function cardsHtml(p, titles) {
    const cards = (p.cards || []).filter((c) => !p.first || c.observation !== p.first.text);
    if (!cards.length) return '';
    return `<h4 class="bh-sub">장면별로 본 것</h4>
      <ul class="bh-cards">${cards.map((c) => {
        const s = c.scene || null;
        const n = s && /^s\d+$/.test(s.seg || '') ? Number(s.seg.slice(1)) : 0;
        const title = n && titles && titles[n - 1] ? titles[n - 1] : '';
        return `<li class="bh-ev">
          <p class="bh-obs">${esc(c.observation)}</p>
          <p class="bh-meta">${s ? `<span>${esc(s.where || '')}${title ? ` · ${esc(title)}` : ''}${Number.isFinite(s.sec) ? ` · ${fmtSec(s.sec)}` : ''}</span>` : ''}<span>신뢰도 ${esc(c.conf || '낮음')}</span></p>
          <details class="bh-more"><summary>측정값 · 비교 기준</summary>
            <p>측정값: ${esc(c.value)}</p><p>비교 기준: ${esc(c.basis)}</p>${c.tip ? `<p>제안: ${esc(c.tip)}</p>` : ''}
          </details>
        </li>`;
      }).join('')}</ul>`;
  }

  function prevText(k, m, prev) {
    if (!prev || !prev.metrics || !m || !m.ok) return '';
    const before = prev.metrics[k];
    if (!Number.isFinite(before) || !Number.isFinite(m.value) || k === 'lookaway' || k === 'framing') return '';
    const d = Math.round((m.value - before) * 100);
    return d === 0 ? '지난번과 같아요' : `지난번보다 ${Math.abs(d)}%p ${d > 0 ? '늘었어요' : '줄었어요'}`;
  }

  function detailHtml(p, b, titles) {
    const M = p.metrics || {};
    const q = p.quality || {};
    const rows = ORDER.filter((k) => M[k]).map((k) => {
      const m = M[k];
      return `<tr data-ok="${m.ok ? 1 : 0}"><th scope="row">${esc(LABEL[k])}</th><td><b>${esc(m.ok ? (m.word || '') : '이번엔 잴 수 없었어요')}</b></td>
        <td>${esc(m.ok ? valueText(k, m) : (m.why || ''))}${m.ok && prevText(k, m, b.prev) ? `<small>${esc(prevText(k, m, b.prev))}</small>` : ''}</td>
        <td>${m.ok ? `신뢰도 ${esc(m.conf || '낮음')}` : ''}</td></tr>`;
    }).join('');
    const bases = ORDER.filter((k) => M[k] && M[k].basis).map((k) => `<li><b>${esc(LABEL[k])}</b> ${esc(M[k].basis)}</li>`).join('');
    const segs = (p.segs || []).filter((s) => s.enough !== false && Number.isFinite(s.gaze !== undefined ? s.gaze : NaN));
    const segRows = segs.slice(0, 40).map((s) => {
      const n = /^s\d+$/.test(s.seg) ? Number(s.seg.slice(1)) : 0;
      return `<tr><th scope="row">${esc(segWhere(s.seg))}${n && titles && titles[n - 1] ? ` <small>${esc(titles[n - 1])}</small>` : ''}</th><td>${pct(s.gaze)}</td><td>${pct(s.down)}</td><td>${pct(s.gesture)}</td><td>${s.lookaway || 0}</td></tr>`;
    }).join('');
    const dur = Number.isFinite(q.dur) ? Math.round(q.dur / 1000) : (Number.isFinite(p.dur) ? Math.round(p.dur) : null);
    const fps = Number.isFinite(q.fps) ? q.fps : p.fps;
    return `<details class="bh-fold">
        <summary>자세히 보기<span class="bh-fold-meta">숫자 · 비교 기준 · 재는 법</span></summary>
        <div class="bh-detail">
          <table class="bh-table"><tbody>${rows}</tbody></table>
          ${segRows ? `<h5>${p.phase === 'qa' ? '질문별' : '장별'}</h5><table class="bh-table bh-segs"><thead><tr><th></th><th>화면 쪽</th><th>아래</th><th>손</th><th>3초+ 벗어남</th></tr></thead><tbody>${segRows}</tbody></table>` : ''}
          <h5>비교 기준</h5><ul class="bh-bases">${bases}</ul>
          <p class="bh-note">잰 시간 ${dur !== null ? `${dur}초` : '–'} · 1초에 ${Number.isFinite(fps) ? fps.toFixed(1) : '–'}장 · 얼굴이 잡힌 시간 ${pct(q.presence)} · 두 눈을 찾은 정면 ${pct(q.eyes)}</p>
          <p class="bh-note">브라우저 안에서 고전 OpenCV(Haar 캐스케이드 · 템플릿 맞추기 · 광학 흐름 · 프레임 차분)로 쟀어요. Haar 는 신경망은 아니지만 AdaBoost 로 학습한 검출기예요.
            카메라를 보는 것과 노트북 화면을 보는 것은 가르지 못해서 「화면 쪽」 이라고 불러요. 영상은 이 기기 밖으로 보내지 않고, 서버에는 위 숫자만 남겨요.</p>
          <p class="bh-note">문턱은 모두 설계값이에요. 같은 발표를 사람이 매긴 점수와 맞는지 확인하기 전이라 발표 점수에는 넣지 않아요. 표정이나 마음은 짐작하지 않아요.</p>
        </div>
      </details>`;
  }

  /** 질문별 화면 쪽 시간 — 화면엔 낱말만 (숫자는 자세히 보기). 경계는 logic 의 설계값을 그대로 */
  function gazeWord(v) {
    const L = root.BehaviorCvLogic;
    const lo = L ? L.CFG.gazeLo : 0.4; const hi = L ? L.CFG.gazeHi : 0.7;
    return v < lo ? '짧아요' : v < hi ? '보통이에요' : '길어요';
  }

  function qaHtml(qa) {
    if (!qa) return '';
    if (!okOf(qa)) return `<p class="bh-qa-none"><b>Q&amp;A 하는 동안</b> · ${esc(qa.why || '카메라 분석이 없었어요')}</p>`;
    const g = (qa.metrics || {}).gaze || {};
    const segs = (qa.segs || []).filter((s) => Number.isFinite(s.gaze));
    return `<div class="bh-qa">
        <h4 class="bh-sub">Q&amp;A 하는 동안</h4>
        <p class="bh-line">${esc(LABEL.gaze)} <b>${esc(g.ok ? g.word : '이번엔 잴 수 없었어요')}</b>${g.ok ? '' : ` — ${esc(g.why || '')}`}</p>
        ${segs.length ? `<ul class="bh-qa-list">${segs.slice(0, 10).map((s) => `<li><span>${esc(segWhere(s.seg))}</span><b>${esc(gazeWord(s.gaze))}</b></li>`).join('')}</ul>` : ''}
      </div>`;
  }

  function noneHtml(p, qa) {
    return `<section class="card bh-card" data-state="none" id="bhCard">
        <h3 class="section-title">발표 태도<span class="bh-beta">${BETA}</span></h3>
        <p class="bh-none"><b>${NONE_WORD}</b> · ${esc((p && p.why) || '카메라 분석이 없었어요')}</p>
        <p class="note">다음 발표에서 카메라를 켜 두면 얼굴 방향 · 몸 · 손 움직임을 같이 짚어 줘요. 영상은 이 기기 안에서만 분석해요.</p>
        ${qaHtml(qa)}
      </section>`;
  }

  /** 옛 리포트 카드 통째 */
  function html(b, { titles = null } = {}) {
    if (!b || (!b.present && !b.qa)) return '';
    const p = b.present;
    if (!okOf(p)) return noneHtml(p, b.qa);
    return `<section class="card bh-card" data-state="ok" id="bhCard">
        <h3 class="section-title">발표 태도<span class="bh-beta">${BETA}</span></h3>
        <p class="note bh-lede">카메라로 본 얼굴 방향 · 몸 · 손 움직임을 본 그대로 적었어요. 표정이나 마음은 짐작하지 않아요.</p>
        ${firstHtml(p, titles)}
        ${areasHtml(p)}
        ${cardsHtml(p, titles)}
        ${qaHtml(b.qa)}
        ${detailHtml(p, b, titles)}
      </section>`;
  }

  /** 리포트 2.0 홈의 입구 한 줄 — 「더 살펴보기」 묶음에 들어간다 */
  function rv2Row(b, { I = {}, esc: e = esc } = {}) {
    if (!b || (!b.present && !b.qa)) return '';
    const h = headline(b);
    return `<button type="button" class="nv-row" data-push="attitude"><span class="nv-ico i-gray">${I.people || ''}</span>
      <span class="nv-row-main"><b>발표 태도 <small class="bh-beta-inline">베타</small></b><small>${e(h.oneLine)}</small></span><span class="nv-val">${e(h.word)}</span><i class="nv-chev">${I.chev || ''}</i></button>`;
  }

  /** 리포트 2.0 화면 하나 — 카드 본문을 그대로 쓴다 */
  function rv2Screen(b, { titles = null } = {}) {
    return { title: '발표 태도', short: '발표 태도', eyebrow: BETA, html: `<div class="bh-rv2">${html(b, { titles }) || `<p class="nv-empty">${NONE_WORD}</p>`}</div>` };
  }

  const api = { headline, html, rv2Row, rv2Screen, valueText };
  root.BehaviorReport = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
