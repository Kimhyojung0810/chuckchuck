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
    if (k === 'lookaway') return m.n ? `${m.n}번 · 가장 길게 ${Math.round(m.longest || 0)}초 · 1분에 약 ${(m.value || 0) < 1 ? (m.value || 0).toFixed(1) : Math.round(m.value)}번` : '없었어요';
    if (k === 'movement') return `몸 영역 ${pct(m.value)} (0.2초 사이 바뀐 점)`;
    if (k === 'framing') return `얼굴 폭 ${pct(m.value)}${Number.isFinite(m.off) ? ` · 가운데에서 ${pct(m.off)} 비낌` : ''}`;
    if (k === 'sway') return m.value ? `흔들린 8초 창 ${pct(m.value)}${Number.isFinite(m.amp) ? ` · 진폭 대략 얼굴 폭의 ${pct(m.amp)}` : ''}` : '없었어요';
    if (k === 'gesture') return `${m.value ? pct(m.value) : '거의 없었어요'}${Number.isFinite(m.speak) ? ` · 말할 때 ${pct(m.speak)} · 쉴 때 ${pct(m.silent)}` : ''}`;
    if (k === 'down' && !m.value) return '없었어요';
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

  /** 갈래 넷 — 리포트 2.0 화면과 같은 낱말(areaView: 「화면 쪽 조금 짧아요」 · 잴 수 없으면 까닭 + 고치는 법) */
  function areasHtml(p) {
    const M = p.metrics || {};
    return `<div class="bh-areas">${(p.areas || []).map((a) => {
      const v = areaView(a, M);
      return `
      <div class="bh-area" data-look="${v.look ? '1' : '0'}">
        <span class="bh-name">${esc(v.name)}</span>
        <b class="bh-word">${esc(v.word)}</b>
        ${v.line ? `<p class="bh-line">${esc(v.line)}</p>` : ''}
      </div>`;
    }).join('')}</div>`;
  }

  /**
   * 같은 장면을 두 지표가 짚으면(오래 눈 뗌 = 아래를 봄) 한 번만 — 장 · 시각(1초 안)이 같으면 앞의 것.
   * first(먼저 살펴볼 한 가지)가 짚은 장면도 이미 본 것으로 친다 — 위 흰 카드 「2장 5.9초 아래를 향했어요」 아래에 같은 순간 「2장 5.9초 아래를 봤어요」 가 또 나왔다(바퀴 5 · s03 · s04).
   * 남은 카드는 시각 순(장면 없는 카드는 뒤) — 길이 순이면 「1장 · 3장 · 2장」 처럼 읽혔다
   */
  function uniqCards(cards, first = null) {
    const seen = [];
    if (first && Number.isFinite(first.sec) && (first.slide || first.q)) seen.push({ seg: first.slide ? `s${first.slide}` : `q${first.q}`, sec: first.sec });
    const sec = (c) => (c.scene && Number.isFinite(c.scene.sec) ? c.scene.sec : Infinity);
    return cards.slice().sort((a, b) => sec(a) - sec(b)).filter((c) => {
      const s = c.scene;
      if (!s || !Number.isFinite(s.sec)) return true;
      if (seen.some((x) => x.seg === s.seg && Math.abs(x.sec - s.sec) <= 1)) return false;
      seen.push({ seg: s.seg, sec: s.sec });
      return true;
    });
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
    const cards = uniqCards((p.cards || []).filter((c) => !p.first || c.observation !== p.first.text), p.first);
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
      return `<tr data-ok="${m.ok ? 1 : 0}"><th scope="row">${esc(LABEL[k])}</th><td class="bh-w"><b>${esc(m.ok ? (m.word || '') : '이번엔 잴 수 없었어요')}</b></td>
        <td class="bh-v">${esc(m.ok ? valueText(k, m) : (m.why || ''))}${m.ok && prevText(k, m, b.prev) ? `<small>${esc(prevText(k, m, b.prev))}</small>` : ''}</td>
        <td class="bh-c">${m.ok ? `신뢰도 ${esc(m.conf || '낮음')}` : ''}</td></tr>`;
    }).join('');
    const bases = ORDER.filter((k) => M[k] && M[k].basis).map((k) => `<li><b>${esc(LABEL[k])}</b> ${esc(M[k].basis)}</li>`).join('');
    const segs = (p.segs || []).filter((s) => s.enough !== false && Number.isFinite(s.gaze !== undefined ? s.gaze : NaN));
    const segRows = segs.slice(0, 40).map((s) => {
      const n = /^s\d+$/.test(s.seg) ? Number(s.seg.slice(1)) : 0;
      return `<tr><th scope="row">${esc(segWhere(s.seg))}${n && titles && titles[n - 1] ? ` <small>${esc(titles[n - 1])}</small>` : ''}</th><td data-k="화면 쪽">${pct(s.gaze)}</td><td data-k="아래">${pct(s.down)}</td><td data-k="손">${pct(s.gesture)}</td><td data-k="3초+ 벗어남">${s.lookaway ? `${s.lookaway}번` : '없음'}</td></tr>`;
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
    const W = L ? L.WORDS.gaze.words : ['짧아요', '조금 짧아요', '충분해요'];
    return v < lo ? W[0] : v < hi ? W[1] : W[2];
  }
  function gazeLevel(v) {
    const L = root.BehaviorCvLogic;
    const lo = L ? L.CFG.gazeLo : 0.4; const hi = L ? L.CFG.gazeHi : 0.7;
    return v < lo ? 0 : v < hi ? 1 : 2;
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

  function noneHtml(p, qa, bare = false) {
    return `<section class="${bare ? 'bh-card is-bare' : 'card bh-card'}" data-state="none"${bare ? '' : ' id="bhCard"'}>
        ${bare ? '' : `<h3 class="section-title">발표 태도<span class="bh-beta">${BETA}</span></h3>`}
        <p class="bh-none"><b>${NONE_WORD}</b> · ${esc((p && p.why) || '카메라 분석이 없었어요')}</p>
        <p class="note">다음 발표에서 카메라를 켜 두면 얼굴 방향 · 몸 · 손 움직임을 같이 짚어 줘요. 영상은 이 기기 안에서만 분석해요.</p>
        ${qaHtml(qa)}
      </section>`;
  }

  /** 옛 리포트 카드 통째 */
  function html(b, { titles = null, bare = false } = {}) {
    if (!b || (!b.present && !b.qa)) return '';
    const p = b.present;
    if (!okOf(p)) return noneHtml(p, b.qa, bare);
    return `<section class="${bare ? 'bh-card is-bare' : 'card bh-card'}" data-state="ok"${bare ? '' : ' id="bhCard"'}>
        ${bare ? '' : `<h3 class="section-title">발표 태도<span class="bh-beta">${BETA}</span></h3>`}
        <p class="note bh-lede">카메라로 본 얼굴 방향 · 몸 · 손 움직임을 본 그대로 적었어요. 표정이나 마음은 짐작하지 않아요.</p>
        ${firstHtml(p, titles)}
        ${areasHtml(p)}
        ${cardsHtml(p, titles)}
        ${qaHtml(b.qa)}
        ${detailHtml(p, b, titles)}
      </section>`;
  }

  /** 리포트 2.0 홈의 입구 한 줄 — 리포트 쪽(report_v2.js behaviorRow)이 headline() 으로 직접 그린다. 옛 호출을 위해 남긴다 */
  function rv2Row(b, { I = {}, esc: e = esc } = {}) {
    if (!b || (!b.present && !b.qa)) return '';
    const h = headline(b);
    return `<button type="button" class="nv-row" data-push="attitude"><span class="nv-ico i-gray">${I.cam || I.people || ''}</span>
      <span class="nv-row-main"><b>발표 태도 <small class="bh-beta-inline">베타</small></b><small>${e(h.oneLine)}</small></span><span class="nv-val">${e(h.word)}</span><i class="nv-chev">${I.chev || ''}</i></button>`;
  }

  /* ═══ 리포트 2.0 화면 (docs/report-v2/BEHAVIOR_SCREEN.md) — 흰 카드 · iOS 묶음 목록 · 3단계 낱말 + 점 셋. 퍼센트는 「자세히 보기」 안에만 ═══ */

  const L = () => root.BehaviorCvLogic || null;
  /** 지표 낱말 — 화면용 묶음엔 word 가 있고, 서버 보관 요약(summaryOf)엔 level 만 있다 */
  function wordOf(k, m) {
    if (!m || !m.ok) return '';
    if (m.word) return m.word;
    const W = L() && L().WORDS[k];
    return W && Number.isInteger(m.level) ? W.words[m.level] || '' : '';
  }
  function lookOf(k, m) {
    if (!m || !m.ok) return false;
    if (typeof m.look === 'boolean') return m.look;
    const W = L() && L().WORDS[k];
    return !!(W && Number.isInteger(m.level) && W.look[m.level]);
  }
  /** 잴 수 없던 까닭 + 고치는 법 (당근 오류 문구 — 「~하면 잴 수 있어요」). 까닭에 이미 방법이 붙어 있으면 그대로 */
  const FIX = [
    [/20초가 안 돼요/, '20초 넘게 발표하면 잴 수 있어요'],
    [/충분히 자주 보지/, '다른 탭과 프로그램을 닫고 발표하면 잴 수 있어요'],
    [/거의 없었어요|잡힌 시간이 짧았어요|기록이 없어요/, '카메라 가운데에 앉아 발표하면 잴 수 있어요'],
    [/따라가지 못했어요|모자랐어요/, '얼굴을 가리지 않고 카메라 가운데에 있으면 잴 수 있어요'],
    [/재지 못했어요/, '상반신이 화면에 들어오게 앉으면 잴 수 있어요'],
    [/꺼 두고|꺼 둬서/, '카메라를 켜고 발표하면 잴 수 있어요'],
    [/열리지 않아서/, '브라우저에서 카메라를 허용하면 잴 수 있어요'],
    [/녹음 파일로/, '리허설에서 카메라를 켜고 발표하면 잴 수 있어요'],
  ];
  function whyFix(why) {
    const w = String(why || '').trim();
    if (!w) return '카메라 가운데에 앉아 다시 발표하면 잴 수 있어요';
    if (/잴 수 있어요|—/.test(w)) return w;
    const f = FIX.find(([re]) => re.test(w));
    return f ? `${w} — ${f[1]}` : w;
  }
  const LOOK_ICON = '<svg class="bh-look-i" viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.6" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8 4.6v4.2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="8" cy="11.2" r="1" fill="currentColor"/></svg>';
  const dotsHtml = (lv) => (Number.isInteger(lv) && lv >= 0 ? `<span class="bh-dots" aria-hidden="true">${[0, 1, 2].map((k) => `<i${k <= lv ? ' class="on"' : ''}></i>`).join('')}</span>` : '');
  const sceneChip = (where, sec, from) => [where, Number.isFinite(sec) ? `${fmtSec(sec)}${from ? '부터' : ''}` : ''].filter(Boolean).join(' · ');
  const slideOfSeg = (seg) => (/^s\d+$/.test(seg || '') ? Number(seg.slice(1)) : 0);

  /** 갈래 하나를 화면 줄로 — 낱말은 방향이 보이게(「화면 쪽 충분해요」), 점 셋은 그 양(짧아요 ●○○ … 충분해요 ●●●). 판정 아님 */
  function areaView(a, M) {
    const name = a.label || AREA_LABEL[a.key] || a.key;
    if (!a.ok) return { key: a.key, name, ok: false, word: '이번엔 잴 수 없었어요', line: whyFix(a.line), lv: null, look: false };
    if (a.key === 'gaze') {
      const g = M.gaze;
      const subs = ['lookaway', 'down'].filter((k) => M[k] && M[k].ok).map((k) => `${LABEL[k]} ${wordOf(k, M[k])}`);
      return { key: a.key, name, ok: true, word: g && g.ok ? `화면 쪽 ${wordOf('gaze', g)}` : (a.word || ''), line: subs.join(' · '),
        lv: g && g.ok ? g.level : null, look: ['gaze', 'lookaway', 'down'].some((k) => lookOf(k, M[k])) };
    }
    if (a.key === 'body') {
      const sw = M.sway; const mv = M.movement;
      if (sw && sw.ok) return { key: a.key, name, ok: true, word: `흔들림 ${wordOf('sway', sw)}`, line: mv && mv.ok ? `${LABEL.movement} ${wordOf('movement', mv)}` : '', lv: sw.level, look: lookOf('sway', sw) };
      // 왜 못 쟀는지 붙인다 — 「멀어요」 · 「1초에 3장」 처럼 고칠 수 있는 까닭이 있는데 맨 문장만 보였다(바퀴 5 · d7)
      const why = sw && !sw.ok && sw.why ? String(sw.why).split(' — ')[0] : '';
      return { key: a.key, name, ok: true, word: `움직임 ${wordOf('movement', mv)}`, line: `좌우 흔들림은 이번엔 잴 수 없었어요${why ? ` — ${why}` : ''}`, lv: mv && mv.ok ? mv.level : null, look: false };
    }
    if (a.key === 'hands') {
      const g = M.gesture;
      return { key: a.key, name, ok: true, word: `손 움직임 ${wordOf('gesture', g) || a.word || ''}`.trim(), line: a.line || '', lv: g && g.ok ? g.level : null, look: false };
    }
    const f = M.framing;
    return { key: a.key, name, ok: true, word: a.word || wordOf('framing', f), line: a.line || '', lv: f && f.ok ? f.level : null, look: lookOf('framing', f) };
  }

  function rowHtml(v) {
    return `<div class="nv-row is-static bh-arow${v.ok ? '' : ' is-off'}" data-look="${v.look ? 1 : 0}">
        <span class="nv-row-main"><span class="bh-aname">${esc(v.name)}</span>
          <b class="bh-aword">${v.look ? LOOK_ICON : ''}${esc(v.word)}</b>${v.line ? `<small class="bh-aline">${esc(v.line)}</small>` : ''}</span>
        ${dotsHtml(v.lv)}</div>`;
  }

  /** 지난번(같은 덱) 대비 — 5%p 넘게 바뀐 것만, 방향 낱말로 (좋고 나쁨 말 없음) */
  function prevLine(p, prev) {
    const M = p.metrics || {};
    if (!prev || !prev.metrics) return '';
    const NAME = { gaze: '화면 쪽을 향한 시간', down: '아래를 본 시간', sway: '몸 좌우 흔들림', gesture: '손이 움직인 시간' };
    const out = Object.keys(NAME).map((k) => {
      const m = M[k]; const before = prev.metrics[k];
      if (!m || !m.ok || !Number.isFinite(m.value) || !Number.isFinite(before)) return '';
      const d = m.value - before;
      return Math.abs(d) < 0.05 ? '' : `${NAME[k]}이 ${d > 0 ? '늘었어요' : '줄었어요'}`;
    }).filter(Boolean);
    return out.length ? `<p class="bh-prev"><b>지난번보다</b> ${esc(out.slice(0, 2).join(' · '))}</p>` : '';
  }

  function firstCard(p, h, titles) {
    const f = p.first;
    if (!f) {
      return `<section class="bh-hero" aria-label="먼저 살펴볼 한 가지"><p class="bh-label">먼저 살펴볼 한 가지</p>
        <p class="bh-head">크게 짚을 곳은 없었어요</p><p class="bh-tip">${esc(h.oneLine)}</p></section>`;
    }
    const title = f.slide && titles && titles[f.slide - 1] ? titles[f.slide - 1] : '';
    const chip = sceneChip(f.slide ? `${f.slide}장` : (f.q ? `${f.q}번째 질문` : ''), f.sec, true);
    // data-sec — 리포트 쪽이 「그 순간 듣기」 를 단다(report_v2.js attitude). 카메라 기록 첫 장면 기준 초
    return `<section class="bh-hero" aria-label="먼저 살펴볼 한 가지"${Number.isFinite(f.sec) && f.slide ? ` data-sec="${f.sec}"` : ''}><p class="bh-label">먼저 살펴볼 한 가지</p>
        <p class="bh-head">${esc(f.text)}</p>
        ${chip ? `<div class="bh-chips"><span class="bh-chip">${esc(chip)}</span>${title ? `<span class="bh-ttl">${esc(title)}</span>` : ''}</div>` : ''}
        ${f.tip ? `<p class="bh-tip"><b>다음엔</b> ${esc(f.tip)}</p>` : ''}</section>`;
  }

  function scenesHtml(p, titles) {
    const cards = uniqCards((p.cards || []).filter((c) => !p.first || c.observation !== p.first.text), p.first);
    if (!cards.length) return '';
    return `<h3 class="nv-sec">장면별로 본 것</h3><div class="bh-scenes">${cards.map((c) => {
      const s = c.scene || null;
      const n = s ? slideOfSeg(s.seg) : 0;
      const title = n && titles && titles[n - 1] ? titles[n - 1] : '';
      const chip = s ? sceneChip(s.where || '', s.sec, false) : '';
      return `<article class="bh-scene"${s && n && Number.isFinite(s.sec) ? ` data-sec="${s.sec}"` : ''}><p class="bh-obs">${esc(c.observation)}</p>
          <div class="bh-chips">${chip ? `<span class="bh-chip">${esc(chip)}</span>` : ''}${title ? `<span class="bh-ttl">${esc(title)}</span>` : ''}<span class="bh-conf">신뢰도 ${esc(c.conf || '낮음')}</span></div>
          <details class="bh-more"><summary>측정값 · 비교 기준</summary><p>측정값 ${esc(c.value)}</p><p>비교 기준 ${esc(c.basis)}</p></details></article>`;
    }).join('')}</div>`;
  }

  /** 질문별 화면 쪽 시간 — 8초 넘게 머문 질문만 (logic CFG.minSegMs). 없으면 [] */
  function qaSegs(qa) {
    if (!okOf(qa) || !((qa.metrics || {}).gaze || {}).ok) return [];
    const min = L() ? L().CFG.minSegMs : 8000;
    return (qa.segs || []).filter((s) => /^q\d+$/.test(s.seg || '') && Number.isFinite(s.gaze) && (s.enough === true || (s.enough === undefined && Number(s.dur || 0) * 1000 >= min)));
  }

  function qaSection(qa, questions) {
    if (!qa) return '';
    if (!okOf(qa)) {
      return `<h3 class="nv-sec">Q&amp;A 하는 동안</h3><div class="nv-group">${rowHtml({ name: '화면 쪽을 향한 시간', ok: false, word: '이번엔 잴 수 없었어요', line: whyFix(qa.why), lv: null, look: false })}</div>`;
    }
    const g = (qa.metrics || {}).gaze || {};
    const segs = qaSegs(qa);
    const rows = segs.slice(0, 12).map((s) => {
      const n = Number(s.seg.slice(1));
      const lv = gazeLevel(s.gaze);
      return rowHtml({ name: `질문 ${n}`, ok: true, word: `화면 쪽 ${gazeWord(s.gaze)}`, line: (questions && questions[n - 1]) || '', lv, look: lv === 0 });
    }).join('');
    return `<h3 class="nv-sec">Q&amp;A 하는 동안${g.ok ? `<small>화면 쪽 ${esc(wordOf('gaze', g))}</small>` : ''}</h3>
      ${rows ? `<div class="nv-group bh-qrows">${rows}</div>` : `<p class="nv-note">${g.ok ? '질문마다 8초 넘게 답한 곳이 없어서 질문별로는 나누지 않았어요.' : esc(whyFix(g.why))}</p>`}`;
  }

  /* ─── 발표 중 알림 (js/behavior_cue.js 가 남긴 present.liveCues, 바퀴 6) — 몇 번 · 무엇을 · 알림 뒤 돌아오기까지 ─── */
  const CUE_ORDER = ['away', 'down', 'sway', 'frame', 'far', 'backlit'];
  const CUE_BACK = { away: '화면 쪽으로 돌아오기까지', down: '고개를 들기까지', sway: '흔들림이 멎기까지', frame: '화면 안으로 들어오기까지' };
  const CUE_LATE = { away: '15초 안에 화면 쪽으로 돌아오지 않았어요', down: '15초 안에 고개를 들지 않았어요', sway: '15초 안에 멎지 않았어요', frame: '15초 안에 들어오지 않았어요' };
  /**
   * liveCues → { total, rows: [{ type, text, n, avg(초 | null), nBack, late, end }] } · 꺼 두었거나 보인 알림이 없으면 null.
   * 목소리 말풍선에 밀려 거의 못 보인 알림(cut)은 안 센다. 돌아오기 평균은 숫자(back)만 — late · end 는 따로 센다
   */
  function cueSummary(lc) {
    if (!lc || lc.on === false || !Array.isArray(lc.list)) return null;
    const seen = lc.list.filter((c) => c && !c.cut && c.type);
    if (!seen.length) return null;
    const rows = CUE_ORDER.concat([...new Set(seen.map((c) => c.type))].filter((k) => !CUE_ORDER.includes(k)))
      .map((type) => {
        const cs = seen.filter((c) => c.type === type);
        if (!cs.length) return null;
        const nums = cs.map((c) => c.back).filter((b) => typeof b === 'number' && isFinite(b));
        return { type, text: cs[0].text || '', n: cs.length, nBack: nums.length, avg: nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : null,
          late: cs.filter((c) => c.back === 'late').length, end: cs.filter((c) => c.back === 'end').length };
      }).filter(Boolean);
    return { total: seen.length, rows };
  }

  /** 돌아오기 한 줄 — 「화면 쪽으로 돌아오기까지 평균 1.8초」 · 흔들림은 4초 창이라 「약 N초」. 숫자가 없으면 late · end 만 */
  function cueBackLine(r) {
    const head = CUE_BACK[r.type];
    if (!head) return '';
    const parts = [];
    if (r.avg !== null) {
      const v = r.type === 'sway' ? `약 ${Math.max(1, Math.round(r.avg))}초` : `${(Math.round(r.avg * 10) / 10).toFixed(1)}초`;
      parts.push(`${head} ${r.nBack > 1 ? '평균 ' : ''}${v}`);
    }
    const pre = (k) => (r.n > 1 || parts.length ? `${k}번은 ` : '');
    if (r.late) parts.push(`${pre(r.late)}${CUE_LATE[r.type]}`);
    if (r.end) parts.push(`${pre(r.end)}그 전에 발표가 끝났어요`);
    return parts.join(' · ');
  }

  function cuesHtml(p) {
    const sm = cueSummary(p && p.liveCues);
    if (!sm) return '';
    // 한 줄 = 「문구」 · N번 (횟수는 머리글처럼 키우지 않는다 — 바퀴 7), 아래 곁말 = 돌아오기
    const rows = sm.rows.map((r) => `<div class="nv-row is-static bh-arow bh-cue" data-cue="${esc(r.type)}">
        <span class="nv-row-main"><span class="bh-cline">「${esc(r.text)}」<span class="bh-cn"> · ${r.n}번</span></span>${cueBackLine(r) ? `<small class="bh-aline">${esc(cueBackLine(r))}</small>` : ''}</span></div>`).join('');
    return `<h3 class="nv-sec">발표 중 알림<small>${sm.total}번 알렸어요</small></h3>
      <div class="nv-group bh-cues">${rows}</div>
      <p class="nv-note">알림 뒤 카메라가 본 자세로 쟀어요. 시험 기능이라 1초쯤 어긋날 수 있어요.</p>`;
  }

  /** 리포트 2.0 「발표 태도」 화면 본문. opts = { titles: 장 제목[], questions: 질문 글[] }. 베타 배너는 리포트 쪽(attitude())이 한 번 그린다 */
  function rv2Html(b, { titles = null, questions = null } = {}) {
    if (!b || (!b.present && !b.qa)) return '';
    const p = b.present;
    const lead = '<p class="bh-lead">카메라로 본 얼굴 방향 · 몸 · 손 움직임을 그대로 적었어요. 각도와 조명에 따라 달라지고, 표정이나 마음은 짐작하지 않아요.</p>';
    if (!okOf(p)) {
      const st = p && p.status === 'unmeasured' ? 'unmeasured' : 'none';
      const head = st === 'unmeasured' ? '이번엔 잴 수 없었어요' : '발표 동안 카메라 분석이 없었어요';
      return `<div class="bh-rv2" data-state="${st}">${lead}
        <section class="bh-hero is-off"><p class="bh-label">발표하는 동안</p><p class="bh-head">${head}</p><p class="bh-tip">${esc(whyFix(p && p.why))}</p></section>
        ${qaSection(b.qa, questions)}</div>`;
    }
    const M = p.metrics || {};
    const h = headline(b);
    return `<div class="bh-rv2" data-state="ok">${lead}
      ${firstCard(p, h, titles)}
      ${prevLine(p, b.prev || p.prev)}
      <h3 class="nv-sec">네 갈래로 본 것<small>점이 찰수록 많았어요</small></h3>
      <div class="nv-group bh-areas2">${(p.areas || []).map((a) => rowHtml(areaView(a, M))).join('')}</div>
      ${scenesHtml(p, titles)}
      ${cuesHtml(p)}
      ${qaSection(b.qa, questions)}
      ${detailHtml(p, b, titles).replace('<details class="bh-fold">', '<details class="bh-fold bh-fold2">')}
    </div>`;
  }

  /** 리포트 2.0 화면 하나 */
  function rv2Screen(b, opts = {}) {
    return { title: '발표 태도', short: '발표 태도', eyebrow: BETA, html: rv2Html(b, opts) || `<p class="nv-empty">${NONE_WORD}</p>` };
  }

  /** Q&A 돌아보기의 질문 한 장에 붙이는 사실 한 줄 — n 번째 질문(1부터)에 8초 넘게 답했고 화면 쪽 시간을 잴 수 있었을 때만. 아니면 null */
  function qaFact(b, n) {
    const qa = b && b.qa;
    const s = qaSegs(qa).find((x) => x.seg === `q${n}`);
    if (!s) return null;
    const word = gazeWord(s.gaze);
    return { level: gazeLevel(s.gaze), word, text: `답하는 동안 화면 쪽을 향한 시간이 ${word}` };
  }

  /** 옛 리포트 요약 — 접힌 줄 하나(리포트 2.0 홈 줄과 같은 말). 펼치면 카드 본문. 카메라 기록이 없으면 그리지 않는다(D-018) */
  function foldHtml(b, { titles = null } = {}) {
    if (!b || (!b.present && !b.qa)) return '';
    const h = headline(b);
    if (h.status === 'none' && !okOf(b.qa)) return '';
    const line = h.status === 'ok' ? h.oneLine : h.status === 'none' ? 'Q&A 동안만 쟀어요' : `이번엔 잴 수 없었어요 — ${h.oneLine}`;
    return `<details class="fold bh-oldfold" id="bhCard">
        <summary><span>발표 태도 <small class="bh-beta">${BETA}</small></span><span class="fold-meta">${esc(line)}</span></summary>
        <div class="fold-body">${html(b, { titles, bare: true })}</div>
      </details>`;
  }

  const api = { headline, html, rv2Row, rv2Screen, rv2Html, qaFact, foldHtml, whyFix, valueText, cueSummary, cueBackLine };
  root.BehaviorReport = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
