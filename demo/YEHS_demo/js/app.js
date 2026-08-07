/**
 * 데모 화면의 메인 로직입니다.
 * 업로드·리허설·질문 준비 UI와 슬라이드↔발화 매핑 표시를 담당합니다.
 */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const app = $('#app');

/* 타이머 관리: 화면 전환 시 전부 정리 */
let timers = [];
function later(fn, ms) { const t = setTimeout(fn, ms); timers.push(t); return t; }
function every(fn, ms) { const t = setInterval(fn, ms); timers.push(t); return t; }
function clearTimers() { timers.forEach(t => { clearTimeout(t); clearInterval(t); }); timers = []; }

const fmt = s => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
const slideNumber = s => Number(String(s).replace(/^S0?/, ''));
const chip = (st, sm) => `<span class="chip ${sm ? 'chip-sm' : ''} st-${st}">${STATUS[st]}</span>`;
const loadSession = key => {
  try { return JSON.parse(sessionStorage.getItem(`cheokcheok:${key}`)); }
  catch (_) { return null; }
};
const saveSession = (key, value) => {
  try {
    // SlideDoc / blob 결과는 용량이 커서 sessionStorage에서 제외
    const slim = { ...value };
    // qa-flow 의 concepts(게임 트래커)는 지우면 안 된다 — 지웠다 새로고침하면 resetQa 가 발동한다
    if (key === 'new-flow') {
      delete slim.slideDoc;
      delete slim.transcript;
      delete slim.concepts; // ConceptDoc (무거움)
      delete slim._pipelineStarted;
      if (slim.slideDocMeta == null && value.slideDoc) {
        slim.slideDocMeta = {
          file_name: value.slideDoc.file_name,
          total_slides: value.slideDoc.total_slides,
        };
      }
      // pipelineOut 전체는 quota 초과로 저장이 통째로 실패할 수 있다 → 리포트용 요약만 남긴다
      if (slim.pipelineOut) {
        const po = value.pipelineOut || {};
        slim.pipelineOut = {
          graph: po.graph || null,
          alignment: po.alignment || null,
          flow: po.flow || null,
          score: po.score || null,
          pace: po.pace || null,
          habits: po.habits || null,
          report: po.report || null,
          transcript: po.transcript ? {
            full_text: po.transcript.full_text || '',
            duration_sec: po.transcript.duration_sec || 0,
            provider: po.transcript.provider || '',
            error: po.transcript.error || null,
          } : null,
          conceptsError: po.conceptsError || null,
          failedStage: po.failedStage || null,
        };
      }
      if (!slim.fileName && value.fileName) slim.fileName = value.fileName;
    }
    sessionStorage.setItem(`cheokcheok:${key}`, JSON.stringify(slim));
  } catch (_) { /* file preview or privacy mode: keep the in-memory state */ }
};

/* 숫자 카운트업 + 바/링 채움 애니메이션 */
function countUp(el, to, ms = 800) {
  const t0 = performance.now();
  (function step(n) {
    const p = Math.min(1, (n - t0) / ms), e = 1 - Math.pow(1 - p, 3);
    el.textContent = Math.round(to * e);
    if (p < 1) requestAnimationFrame(step);
  })(t0);
}
function animateViz(root = document) {
  $$('.fill-bar i[data-w]', root).forEach(i => i.style.width = i.dataset.w);
  $$('.ring-fg[data-off]', root).forEach(r => r.style.strokeDashoffset = r.dataset.off);
  $$('[data-count]', root).forEach(el => el.textContent = el.dataset.count);
  // callers: renderReport tabs; data: /data/voice_report_live.json (pace/habits/report)
  // user: 쉬운 설명 + 권장/실제 시간 그래프 애니메이션 + 간투어 키워드 상자
  requestAnimationFrame(() => {
    $$('.voice-chart', root).forEach(el => el.classList.add('is-on'));
    $$('.filler-chip', root).forEach(el => el.classList.add('is-on'));
    $$('.slide-pill', root).forEach(el => el.classList.add('is-on'));
  });
}

/** 샘플 모드에서만 voice_report_live.json 폴백. 실발표 실패 시 목업을 덮어쓰지 않는다. */
let _voiceLiveCache = null;
async function ensureVoicePipelineOut() {
  if (nf && nf.pipelineOut && nf.pipelineOut.pace && (nf.pipelineOut.pace.slides || []).length) {
    return nf.pipelineOut;
  }
  // 실제 파이프라인이 돌다 깨졌거나 진행 중이면 fixture 목업을 끼워 넣지 않는다
  const phase = nf && nf.pipelinePhase;
  const realAttempt = !!(nf && (nf._pipelineStarted || nf.pipelineError || phase));
  const allowFixture = !!(nf && nf.useSample) && !realAttempt;
  if (!allowFixture) return nf && nf.pipelineOut;
  if (_voiceLiveCache) {
    nf = nf || {};
    nf.pipelineOut = { ...(nf.pipelineOut || {}), ..._voiceLiveCache };
    return nf.pipelineOut;
  }
  try {
    const res = await fetch('/data/voice_report_live.json', { cache: 'no-store' });
    if (!res.ok) return nf && nf.pipelineOut;
    const d = await res.json();
    _voiceLiveCache = {
      pace: d.pace,
      habits: d.habits,
      report: d.report,
      transcript: {
        full_text: d.transcript_preview || '',
        duration_sec: (d.transcript_stats && d.transcript_stats.duration_sec) || 0,
        provider: (d.transcript_stats && d.transcript_stats.provider) || '',
      },
    };
    nf = nf || {};
    nf.pipelineOut = { ...(nf.pipelineOut || {}), ..._voiceLiveCache };
    return nf.pipelineOut;
  } catch (_) {
    return nf && nf.pipelineOut;
  }
}

function fmtSec(sec) {
  const s = Math.max(0, Math.round(sec || 0));
  if (s < 60) return `${s}초`;
  return `${Math.floor(s / 60)}분 ${s % 60}초`;
}

function fillerKeywordStats(habits) {
  const spans = (habits && (habits.spans || habits.spans_sample)) || [];
  const count = {};
  spans.filter(s => s.kind === 'FIL').forEach(s => {
    const t = String(s.text || '').trim();
    if (!t) return;
    count[t] = (count[t] || 0) + 1;
  });
  return Object.entries(count)
    .map(([text, n]) => ({ text, n }))
    .sort((a, b) => b.n - a.n || a.text.localeCompare(b.text, 'ko'));
}

function voiceEasyBlocks(pace, habits, report) {
  const slides = (pace && pace.slides) || [];
  const shortCore = slides.filter(s => s.importance === 'core' && s.status === 'short');
  const longOnes = slides.filter(s => s.status === 'long');
  const okCore = slides.filter(s => s.importance === 'core' && s.status === 'ok');
  const fillers = fillerKeywordStats(habits);
  const target = fmtSec(pace.target_sec);
  const actual = fmtSec(pace.actual_sec);
  let headline = '시간 배분이랑 말하는 습관을 함께 살펴봤어요.';
  if (shortCore.length && longOnes.length) {
    headline = '중요한 장은 짧게 지나갔고, 어떤 장은 생각보다 길게 말했어요.';
  } else if (shortCore.length) {
    headline = '중요한 장에 시간을 조금 더 쓰면 전달력이 살아나요.';
  } else if (longOnes.length) {
    headline = '긴 장을 조금 줄이면 목표 시간에 더 잘 맞춰져요.';
  } else if (report && report.one_liner) {
    headline = report.one_liner;
  }
  const lead = `목표 ${target} 중에 실제로 약 ${actual} 말했어요. 평균 속도는 ${Math.round(pace.avg_chars_per_min || 0)}자/분이에요.`;
  const actions = [];
  if (shortCore.length) {
    actions.push(`핵심인 ${shortCore.map(s => `${s.slide_no}번`).join(', ')} 장에 시간을 더 써 보세요. 아래 상자를 눌러 각 장 시간을 확인해요.`);
  }
  if (longOnes.length) {
    const top = [...longOnes].sort((a, b) => (b.delta_sec || 0) - (a.delta_sec || 0)).slice(0, 3);
    actions.push(`${top.map(s => `${s.slide_no}번`).join(', ')} 장은 길게 말했어요. 세부 설명을 줄이면 좋아요.`);
  }
  if (fillers.length) {
    const topF = fillers.slice(0, 2).map(f => `「${f.text}」`).join(', ');
    actions.push(`자주 나온 간투어 ${topF} 를 줄이려면, 발표 전에 한 번 소리 내어 읽어보세요.`);
  }
  if (!actions.length && Array.isArray(report && report.actions)) {
    actions.push(...report.actions.slice(0, 3));
  }
  return { slides, shortCore, longOnes, okCore, fillers, headline, lead, target, actual, actions };
}

function slidePillHtml(slides, tone) {
  if (!slides.length) return '<span class="note">해당 없음</span>';
  return slides.map((s, i) => `
    <button type="button" class="slide-pill tone-${tone}" style="--i:${i}" title="${escapeHtml(s.title || '')}">
      <span class="sp-no">${s.slide_no}</span>
      <span class="sp-body">
        <b>${s.importance === 'core' ? '핵심' : '보조'}</b>
        <em>${fmtSec(s.actual_sec)} <i>/</i> 권장 ${fmtSec(s.recommended_sec)}</em>
      </span>
    </button>`).join('');
}

function voiceTimeChartHtml(pace) {
  const slides = pace.slides || [];
  const maxSec = Math.max(1, ...slides.map(s => Math.max(s.actual_sec || 0, s.recommended_sec || 0)));
  const cols = slides.map((s, i) => {
    const ah = Math.max(2, (s.actual_sec / maxSec) * 100);
    const rh = Math.max(2, (s.recommended_sec / maxSec) * 100);
    const tip = `${s.slide_no}번 · ${s.importance === 'core' ? '핵심' : '보조'} / 실제 ${fmtSec(s.actual_sec)} / 권장 ${fmtSec(s.recommended_sec)} / ${s.note || ''}`;
    return `<div class="voice-col status-${s.status} ${s.importance === 'core' ? 'is-core' : ''}" style="--i:${i}" title="${escapeHtml(tip)}">
      <div class="voice-bars" aria-hidden="true">
        <div class="vbar rec" style="--h:${rh.toFixed(1)}%"></div>
        <div class="vbar act" style="--h:${ah.toFixed(1)}%"></div>
      </div>
      <span class="vx">S${s.slide_no}</span>
      ${s.importance === 'core' ? '<span class="vcore">핵심</span>' : '<span class="vcore v-hide">·</span>'}
    </div>`;
  }).join('');
  return `
    <div class="voice-chart" role="img" aria-label="슬라이드별 권장 시간과 실제 시간 비교 그래프">
      <div class="voice-chart-head">
        <div>
          <h3 class="section-title">슬라이드별 시간<span class="soft">X축 슬라이드 · Y축 초</span></h3>
          <p class="note">회색은 권장, 파랑은 내가 쓴 시간이에요. 핵심 장은 위에 표시돼요.</p>
        </div>
        <div class="voice-lgd">
          <span><i class="rec"></i>권장</span>
          <span><i class="act"></i>실제</span>
        </div>
      </div>
      <div class="voice-plot-wrap">
        <div class="voice-y"><span>${Math.round(maxSec)}초</span><span>${Math.round(maxSec / 2)}초</span><span>0</span></div>
        <div class="voice-plot">${cols}</div>
      </div>
    </div>`;
}


function ringSvg(pct, size, sw, inner) {
  const r = size / 2 - sw, C = 2 * Math.PI * r;
  return `<div class="ring-wrap" style="width:${size}px;height:${size}px">
    <svg width="${size}" height="${size}">
      <circle class="ring-bg" cx="${size / 2}" cy="${size / 2}" r="${r}" style="stroke-width:${sw}"/>
      <circle class="ring-fg" cx="${size / 2}" cy="${size / 2}" r="${r}"
        style="stroke-width:${sw};stroke-dasharray:${C.toFixed(1)};stroke-dashoffset:${C.toFixed(1)}"
        data-off="${(C * (1 - pct / 100)).toFixed(1)}"/>
    </svg>
    <div class="ring-num">${inner}</div>
  </div>`;
}

/* 성장 추이 area 차트 — 그라디언트 채움 + 선 드로잉 애니메이션 + 끝점 강조 */
function areaChartSvg(vals, W, H) {
  const padX = 12, padT = 24, padB = 14;
  const min = Math.min(...vals), max = Math.max(...vals), span = (max - min) || 1;
  const n = vals.length;
  const X = i => padX + i / (n - 1) * (W - 2 * padX);
  const Y = v => padT + (1 - (v - min) / span) * (H - padT - padB);
  const pts = vals.map((v, i) => [X(i), Y(v)]);
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ');
  const area = `${line} L${X(n - 1).toFixed(1)} ${H - padB} L${X(0).toFixed(1)} ${H - padB} Z`;
  let len = 0; for (let i = 1; i < pts.length; i++) len += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
  const last = pts[n - 1];
  const dots = pts.slice(0, -1).map(p => `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="3" fill="#fff" stroke="var(--blue)" stroke-width="2"/>`).join('');
  return `<svg class="growth-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="최근 ${n}회 완성도 추이">
    <defs><linearGradient id="growthFill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="var(--blue)" stop-opacity=".20"/>
      <stop offset="1" stop-color="var(--blue)" stop-opacity="0"/>
    </linearGradient></defs>
    <path class="growth-area" d="${area}" fill="url(#growthFill)"/>
    <path class="growth-line" style="--len:${len.toFixed(0)}" d="${line}" fill="none" stroke="var(--blue)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
    ${dots}
    <circle class="growth-dot-last" cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="5.5" fill="var(--blue)" stroke="#fff" stroke-width="2.5"/>
    <text class="growth-val" x="${last[0].toFixed(1)}" y="${(last[1] - 12).toFixed(1)}" text-anchor="middle">${vals[n - 1]}</text>
  </svg>`;
}

/* ══ 라우팅 ══ */
const routes = {
  '': renderHome, 'new': renderNew, 'report': renderReport, 'qa': renderQa, 'about': renderAbout,
  // 랜딩은 js/landing.js 가 window 에 붙인다. 호출 시점에 찾으므로 로드 순서를 타지 않는다.
  'landing': () => window.renderLanding(),
};

/** 진행 중 세션을 버리고 새 연습 시작 */
function startFreshPractice() {
  resetNf();
  // 질문 코칭도 같이 지운다. 안 지우면 이전 발표의 qa.started 가 살아남는데,
  // syncTopbar()·renderHome() 은 qaActive 를 nf 보다 먼저 보므로 새 자료를 올려도
  // 상단이 「연습 이어하기」로 남아 지난 세션의 질문·대화로 데려간다.
  // (2026-08-07 사용자: "업로드 한 뒤에 연습 이어가기 누르면 이전 데이터가 남아있네")
  // mode 는 resetQa 가 보존한다 — 코칭 길이는 자료가 아니라 사용자의 선택이다.
  resetQa();
  try { sessionStorage.removeItem('cheokcheok:chuckchuck-session'); } catch (_) {}
  if (location.hash === '#/new' || location.hash === '#/new/') {
    route();
  } else {
    location.hash = '#/new';
  }
}

/* ─── 극장 셸 (§8) ──────────────────────────────────────────────────────────
   라우팅·데이터는 그대로 두고 전환 문법만 하나로 통일한다. 장면 전환 연출은
   두지 않는다 — 커튼 와이프는 화면마다 400ms 를 가려서 걷어냈다. */

/**
 * 무대 사고 — 오류 화면 (§8).
 *
 * 무대감독이 헐레벌떡 달려와 사과하되, 기술 원인은 그 아래 그대로 남긴다.
 * 귀여움이 원인을 가리면 그건 연출이 아니라 은폐다 (§14 정직한 상태 유지).
 */
function stageAccidentHtml(message, { title = '죄송해요, 무대 장치가 말썽이에요!' } = {}) {
  if (!message) return '';
  return `
    <div class="accident">
      <div class="ac-head">
        <span class="ac-badge">무대감독</span>
        <b>${escapeHtml(title)}</b>
      </div>
      <p class="ac-cause">${escapeHtml(message)}</p>
    </div>`;
}

function dismissF11Reveal() {
  const wrap = document.getElementById('f11RevealWrap');
  if (!wrap) return;
  wrap.remove();
}

function route() {
  clearTimers();
  unbindRehearsalNav();
  // 분석 오버레이가 남아 있으면 #/qa 가 흰 화면처럼 가려진다
  {
    const parts0 = location.hash.replace(/^#\/?/, '').split('/');
    if (parts0[0] !== 'new') dismissF11Reveal();
  }

  const parts = location.hash.replace(/^#\/?/, '').split('/');
  const key = parts[0];
  // #/new/reset 또는 completed 후 #/new → 초기화
  // 질문 코칭도 같이 지운다 (startFreshPractice 와 같은 이유). 리포트의
  // 「새 발표 연습」처럼 data-fresh-practice 없이 #/new 로 오는 링크는 여기로만
  // 들어오는데, qa.live 를 남겨 두면 새 발표를 분석해도 renderQa()·
  // ensureLiveQuestions() 가 qaLiveActive() 만 보고 지난 발표의 질문·대화를
  // 그대로 보여준다. nf.completed 는 QA 를 끝내야 서므로 진행 중인 코칭이
  // 여기서 지워질 일은 없고, 끝난 코칭 기록은 qa-history(localStorage)에 남아 있다.
  if (key === 'new' && (parts[1] === 'reset' || nf.completed)) { resetNf(); resetQa(); }
  (routes[key] || renderHome)();
  syncTopbar();
  wireFreshPracticeButtons();
  window.scrollTo(0, 0);
}

function syncTopbar() {
  const link = $('.topbar-right a'); if (!link) return;
  const qaActive = qa.started && !qa.ended;
  const nfActive = !nf.completed && (nf.step > 0 || nf.gate);
  if (qaActive) {
    link.href = '#/qa';
    link.textContent = '연습 이어하기';
    link.removeAttribute('data-fresh-practice');
  } else if (nfActive) {
    // 진행 중이면 이어하기, 옆에 새 시작은 홈에서
    link.href = '#/new';
    link.textContent = '연습 이어하기';
    link.removeAttribute('data-fresh-practice');
  } else {
    link.href = '#/new';
    link.textContent = '새 발표 연습';
    link.setAttribute('data-fresh-practice', '');
  }
}

function wireFreshPracticeButtons(root = document) {
  root.querySelectorAll('[data-fresh-practice]').forEach((el) => {
    if (el._freshBound) return;
    el._freshBound = true;
    el.addEventListener('click', (e) => {
      if (!el.hasAttribute('data-fresh-practice')) return;
      e.preventDefault();
      startFreshPractice();
    });
  });
}
addEventListener('hashchange', () => {
  route();
});
// 탑바 초기 바인딩
document.addEventListener('DOMContentLoaded', () => wireFreshPracticeButtons());
wireFreshPracticeButtons();

/* ══ 홈 ══ */
function renderHome() {
  app.className = 'home';   // 홈 전용 스코프 — 폭은 main 기본값(980px) 그대로
  const g = DATA.growth.scores;
  const totalUp = g[g.length - 1] - g[0];
  const qaActive = qa.started && !qa.ended;
  const nfActive = !nf.completed && (nf.step > 0 || nf.gate);
  const resume = qaActive
    ? {href:'#/qa', eyebrow:'질문 코칭 진행 중', title:`${qa.aud || '교수님'}${josa(qa.aud || '교수님','과','와')} 하던 질문 코칭을 이어서 할까요?`, sub:'지금까지 주고받은 대화를 이 브라우저에 저장했어요.'}
    : nfActive
      ? {href:'#/new', eyebrow:'발표 연습 진행 중', title:`${NF_STEPS[nf.step]}부터 이어서 할까요?`, sub:`${nf.slide || 1}번 슬라이드와 입력한 발표 정보를 저장했어요.`}
      : null;
  /* 토스 홈의 문법: 제목 → 핵심 숫자 한 장 → 목록 → 다음 행동.
     히어로 배너도, 면적 차트 옆 통계 타일도, 96px 공백으로 가른 블록 일곱 개도
     없다. 그건 대시보드 문법이지 앱 문법이 아니다.
     「새 발표 연습」은 상단 바에만 둔다 — 화면 안에 CTA 를 또 두면 어느 것이
     이 화면의 행동인지 흐려진다 (MVP_SPEC §5.1 · 토스 CTA 규칙) */
  const gm = loadGame();
  const streak = dayStreak(gm.days), lvl = gameLevel(gm.xp), inLvl = (gm.xp || 0) % 100;

  app.innerHTML = `
    <header class="t-head"><h1>내 발표</h1></header>

    ${resume ? `
    <a class="t-resume" href="${resume.href}">
      <span class="t-resume-main">
        <span class="t-resume-tag">${resume.eyebrow}</span>
        <b>${resume.title}</b>
      </span>
      <span class="t-chev" aria-hidden="true">›</span>
    </a>` : ''}

    <h2 class="t-sec-head t-lhead">내 기록</h2>

    <section class="t-card t-score-card" aria-label="최근 발표 완성도">
      <p class="t-label">최근 발표 완성도</p>
      <div class="t-score">
        <strong class="num">${DATA.session.score}</strong><span class="t-unit">점</span>
        <span class="t-delta num">▲ ${DATA.session.score - DATA.session.prevScore}</span>
      </div>
      <div class="t-spark">${areaChartSvg(g, 360, 84)}</div>
      <p class="t-caption">최근 5회 ${g[0]} → ${g[g.length - 1]} · 5회 동안 ${totalUp} 올랐어요</p>
    </section>

    <section class="t-card t-record-card" aria-label="연습 기록">
      <div class="t-stats">
        <div class="t-stat"><b class="num">${streak}일</b><small>연속 연습</small></div>
        <div class="t-stat"><b class="num">레벨 ${lvl}</b><small>설득력</small></div>
      </div>
      <div class="t-bar"><i style="width:${inLvl}%"></i></div>
      <p class="t-caption">다음 레벨까지 ${100 - inLvl} · 어려운 상대일수록 더 많이 쌓여요</p>
    </section>

    <div class="t-band" aria-hidden="true"></div>

    <section class="t-sec">
      <h2 class="t-sec-head">지난 발표</h2>
      <div class="t-card t-list">
        ${DATA.sessions.map(s => `
        <button class="t-row" type="button" data-go="#/report/${s.id}">
          <span class="t-row-main">
            <b>${s.title}</b>
            <small>${s.occasion} · ${s.date} · ${s.nth}번째 연습</small>
          </span>
          <span class="t-row-val num">${s.score}<i>점</i></span>
          <span class="t-chev" aria-hidden="true">›</span>
        </button>`).join('')}
      </div>
    </section>

    ${window.Playbill ? window.Playbill.wallHtml() : ''}

    <div class="t-band" aria-hidden="true"></div>

    <div class="t-card t-list">
      <button class="t-row" type="button" data-go="#/about">
        <span class="t-row-main"><b>척척발표가 판단하는 방식</b></span>
        <span class="t-chev" aria-hidden="true">›</span>
      </button>
    </div>`;
  $$('.t-row[data-go]').forEach(r => r.addEventListener('click', () => location.hash = r.dataset.go));
  if (window.Playbill) window.Playbill.paintWall(app);
  animateViz();
}

/* ══ 새 발표 연습 ══ */
let nf = loadSession('new-flow') || {};
/** F-01 결과 (sessionStorage 밖, 메모리만) */
let nfSlideDoc = null;
/** F-03/F-04 마지막 테이크 */
let ccRuntime = null;
let ccLastTake = null;
/* 한 번 받은 수다는 '다시 듣기'에서 재사용한다. 테이크에 딸린 상태라 resetNf()
   가 지우는데, resetNf() 는 모듈 최상위에서 한 번 실행된다 — 선언이 파일
   아래쪽에 있으면 그 시점엔 아직 TDZ 라 신규 세션에서 앱이 통째로 죽는다 */
let chatterCache = null;
/* 받는 중인 수다의 promise. 객석은 네 모델이 차례로 말하는 거라 목업으로도
   70초 넘게 걸린다 — 누른 뒤에 받기 시작하면 부스에서 그만큼 멈춰 있다.
   청중 반응 탭을 열 때 미리 받아 두고, 누르면 이 약속을 기다린다.
   두 번 부르지 않으려고 cache 와 따로 둔다 */
let chatterPending = null;

/** 업로드한 원본 슬라이드 (메모리). 리허설 화면에 페이지 렌더용 */
let uploadedPdf = null; // { file, pdf, pageCount }
let pdfRenderToken = 0;
let pdfRenderTask = null;
let rehearsalNavBound = false;

/* 썸네일 캐시는 uploadedPdf 와 수명이 같다. chatterCache 와 같은 이유로 선언이 여기 있다 —
   resetNf() 가 모듈 최상위에서 불리므로 아래쪽에 두면 TDZ 로 앱이 죽는다. */
const thumbCache = new Map();   // pageNo → dataURL (메모리만)
const THUMB_WIDTH = 240;

/** 원본 PDF 교체 창구. 캐시가 페이지 번호로만 키를 잡아서, 같이 안 비우면
    자료를 바꿔도 이전 자료의 슬라이드가 그대로 보인다. */
function setUploadedPdf(next) {
  uploadedPdf = next;
  thumbCache.clear();
}

function onRehearsalKeydown(e) {
  if (nf.step !== 2) return;
  const tag = (e.target && e.target.tagName) || '';
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
  if (e.key === 'ArrowLeft') {
    e.preventDefault();
    moveSlide(-1);
  } else if (e.key === 'ArrowRight') {
    e.preventDefault();
    moveSlide(1);
  }
}

function onRehearsalClick(e) {
  if (nf.step !== 2) return;
  const nav = e.target.closest('[data-slide-nav]');
  if (nav) {
    e.preventDefault();
    moveSlide(Number(nav.getAttribute('data-slide-nav')) || 0);
    return;
  }
  const filmBtn = e.target.closest('#slideFilm button[data-slide]');
  if (filmBtn) {
    e.preventDefault();
    moveSlideTo(Number(filmBtn.dataset.slide));
  }
}

function bindRehearsalNav() {
  if (rehearsalNavBound) return;
  rehearsalNavBound = true;
  window.addEventListener('keydown', onRehearsalKeydown);
  document.addEventListener('click', onRehearsalClick, true);
}

function unbindRehearsalNav() {
  if (!rehearsalNavBound) return;
  rehearsalNavBound = false;
  window.removeEventListener('keydown', onRehearsalKeydown);
  document.removeEventListener('click', onRehearsalClick, true);
}

function resetNf() {
  nf = { step: 0, gate: null, occ: null, ctx: '', min: 10,
         mic: 'idle', sec: 0, slide: 1, visits: { 1: 1 }, log: [], done: 0, completed: false,
         fileName: '', sparseSlides: [], parseError: null, useSample: false,
         marks: null, uploadedTake: null, pipelineOut: null, pipelineError: null,
         pipelinePhase: null, pipelineDetail: null, pipelineStartedAt: null,
         backstage: [], _pipelineTickStarted: false };
  nfSlideDoc = null;
  ccRuntime = null;
  ccLastTake = null;
  // 수다도 테이크에 딸린 것이다. 안 지우면 자료 A 의 객석이 자료 B 에서 재생되고,
  // currentShow() 가 A 의 absent 를 B 의 티켓에 빈 도장으로 찍는다
  chatterCache = null;
  chatterPending = null;
  setUploadedPdf(null);
  pdfRenderToken += 1;
  saveSession('new-flow', nf);
}
if (!Number.isInteger(nf.step)) resetNf();
// 새로고침/서버 재시작 후 'parsing'만 남은 건 가짜 로딩 — 요청이 없어서 풀어줌
if (nf.gate === 'parsing') {
  nf.gate = null;
  nf.parseError = null;
  saveSession('new-flow', nf);
}

const NF_STEPS = ['자료 올리기', '발표 정보', '리허설 녹음', '질문 준비'];
let parseTimer = null;
let parseGen = 0; // 취소/중복 요청 구분

/* ─── 선분석: 발표하는 동안 자료를 먼저 읽어 둔다 ────────────────────────────
   F-06 개념 추출(1분43초)과 F-07 개념 그래프(2분40초)는 녹음이 전혀 필요 없다
   (f07_graph.py 는 Transcript 를 아예 받지 않는다). 그런데 예전엔 STT 뒤에 줄을 세워
   실측 7분 30초 중 4분 23초를 녹음이 끝난 뒤에 태웠다. 사용자가 발표하는 3~20분 동안
   서버는 놀고 있었다.

   캐시가 아니라 promise 로 들고 있는다. 1분짜리 짧은 녹음이면 발표가 끝날 때 아직
   도는 중인데, 그때 "캐시에 없네" 하고 다시 부르면 같은 호출을 두 번 결제한다.
   보관하는 건 promise 라 sessionStorage 에 못 넣는다 — 새로고침하면 버리고 원래 경로로 간다. */
let precompute = null;   // { key, conceptsP, graphP, startedAt, state }

/** 이 조합이 바뀌면 먼저 뽑아 둔 개념은 다른 발표의 것이다. context 가 개념 중요도를 바꾼다 */
function precomputeKey() {
  return [nf.fileName || '', nf.occ || '', nf.ctx || '', nf.min || ''].join('|');
}

/**
 * 녹음 화면으로 들어갈 때 자료 축을 먼저 돌린다.
 *
 * 발화 지점이 업로드 직후가 아니라 여기인 이유: `situation`·`audience` 는 F-06 프롬프트에
 * 그대로 들어가 개념 중요도를 바꾼다. 업로드 시점엔 아직 안 정해져 있어서, 그때 돌리면
 * 사용자가 발표 정보를 채우는 순간 버려야 한다.
 */
function startPrecompute() {
  const bridge = window.ChuckchuckBridge;
  if (!bridge || typeof bridge.extractConcepts !== 'function') return;
  if (!nfSlideDoc) return;                       // 자료 없이는 F-06 이 돌 게 없다
  const key = precomputeKey();
  if (precompute && precompute.key === key) return;   // 이미 같은 조건으로 돌고 있다

  const context = { situation: nf.occ || '', audience: nf.ctx || '', duration_min: nf.min };
  const slideDoc = nfSlideDoc;
  const state = { conceptsReady: false, graphReady: false, failed: false, graph: null };

  // transcript 없이 부른다 — 아직 녹음이 시작도 안 했다 (§F-06 speech_hint 는 선택)
  const conceptsP = bridge.extractConcepts({ slideDoc, context })
    .then((c) => { state.conceptsReady = true; return c; })
    .catch((err) => { state.failed = true; console.warn('[chuckchuck] precompute concepts', err); throw err; });

  const graphP = conceptsP
    .then((concepts) => bridge.buildGraph({ concepts, slideDoc, context }))
    .then((g) => { state.graphReady = true; state.graph = g; return g; })
    .catch((err) => { state.failed = true; console.warn('[chuckchuck] precompute graph', err); throw err; });

  // 아무도 안 붙은 promise 가 reject 되면 콘솔이 unhandled 로 시끄럽다. 소비는 아래에서 한다
  conceptsP.catch(() => {});
  graphP.catch(() => {});

  precompute = { key, conceptsP, graphP, startedAt: Date.now(), state };
  console.info('[chuckchuck] precompute started', key);
}

/**
 * 녹음 화면 구석의 선분석 상태 한 줄.
 *
 * 연출이 아니라 기대치 설정이다. 발표가 끝나자마자 개념 그래프가 뜨는 이유를 안 알려주면
 * "덜 분석한 거 아닌가"로 읽힌다. 녹음 화면의 주인공은 슬라이드니까 작게 둔다
 * (MVP_SPEC §3 절제 규율 — 한 화면의 주인공은 하나).
 * 선분석이 안 걸렸으면 아무 말도 안 한다.
 */
function precomputeNoteHtml() {
  if (!precompute || precompute.key !== precomputeKey()) return '';
  const s = precompute.state || {};
  let text;
  if (s.failed) text = '자료를 미리 읽다가 멈췄어요. 발표가 끝난 뒤에 다시 해볼게요';
  else if (s.graphReady) text = '발표하는 동안 자료를 다 읽어 뒀어요';
  else if (s.conceptsReady) text = '자료의 개념을 찾았어요. 개념끼리 어떻게 이어지는지 보고 있어요';
  else text = '발표하는 동안 자료를 먼저 읽고 있어요';
  return `<p class="pre-note${s.graphReady ? ' is-done' : ''}">${escapeHtml(text)}</p>`;
}

let preNoteTickStarted = false;
/** 선분석은 몇 분 걸린다. 단계가 바뀌면 화면을 다시 안 그리고 그 줄만 갈아끼운다 */
function startPrecomputeNoteTimer() {
  if (preNoteTickStarted) return;
  preNoteTickStarted = true;
  every(paintPrecomputeNote, 1500);
}

function paintPrecomputeNote() {
  const host = $('.pre-note');
  if (!host) return;
  const tmp = document.createElement('div');
  tmp.innerHTML = precomputeNoteHtml();
  const next = tmp.firstElementChild;
  if (next && next.textContent !== host.textContent) host.replaceWith(next);
}

/** 파이프라인에 넘길 promise 묶음. 조건이 바뀌었으면 아무것도 안 넘긴다 */
function precomputeHandles() {
  if (!precompute) return null;
  if (precompute.key !== precomputeKey()) {
    console.info('[chuckchuck] precompute discarded — 발표 정보가 바뀌었어요');
    precompute = null;
    return null;
  }
  return { conceptsP: precompute.conceptsP, graphP: precompute.graphP };
}
/** 지나온 단계로 되돌아가도 잃을 게 없는 상태인가.
    녹음이 돌고 있거나 파싱·분석이 진행 중이면 되돌아가는 순간 그 작업이 사라진다 */
function canJumpBack() {
  if (nf.mic === 'on') return false;                    // 녹음 중
  if (nf.gate === 'parsing') return false;              // 자료 분석 중
  if (nf.pipelinePhase && !nf.pipelineOut && !nf.pipelineError) return false; // 파이프라인 중
  return true;
}

function stepsHtml() {
  const back = canJumpBack();
  return NF_STEPS.map((n, i) => {
    const cls = i < nf.step ? 'done' : i === nf.step ? 'cur' : '';
    const mark = i < nf.step ? '✓' : i + 1;
    // 지나온 단계만 누를 수 있다. 앞 단계는 아직 채울 내용이 없어서 열지 않는다
    if (back && i < nf.step) {
      return `<button type="button" class="${cls}" data-nf-step="${i}" title="${n} 단계로 돌아가기"><i>${mark}</i>${n}</button>`;
    }
    return `<span class="${cls}"><i>${mark}</i>${n}</span>`;
  }).join('');
}

/** 녹음이 시작·종료되면 되돌아갈 수 있는지가 바뀐다. 표시줄만 다시 그린다 */
function refreshStepBar() {
  const bar = document.querySelector('.steps');
  if (bar) bar.innerHTML = stepsHtml();
}

function nfSteps() {
  return `<div class="flow-toolbar">
    <div class="steps">${stepsHtml()}</div>
    <div class="flow-save"><span>자동 저장됨</span><a href="#/new" data-fresh-practice>처음부터</a><a href="#/">나가기</a></div>
  </div>`;
}

let stepNavBound = false;
/** 단계 표시줄은 화면마다 다시 그려지므로 document 에 한 번만 위임해서 듣는다 */
function bindStepNav() {
  if (stepNavBound) return;
  stepNavBound = true;
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-nf-step]');
    if (!btn) return;
    e.preventDefault();
    const to = Number(btn.dataset.nfStep);
    if (!Number.isInteger(to) || to >= nf.step || !canJumpBack()) return;
    nf.step = to;
    saveSession('new-flow', nf);
    renderNew();
  });
}

async function loadUploadedPdf(file, nameHint = '') {
  setUploadedPdf(null);
  const name = (file && file.name) || nameHint || '';
  const looksPdf = /\.pdf$/i.test(name)
    || (file && (file.type === 'application/pdf' || String(file.type || '').includes('pdf')));
  if (!file || !looksPdf) return null;
  if (!window.pdfjsLib) {
    console.warn('[chuckchuck] pdf.js 미로드');
    return null;
  }
  const data = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data }).promise;
  setUploadedPdf({ file, pdf, pageCount: pdf.numPages });
  return uploadedPdf;
}

/** 브리지가 PPTX→PDF 변환해 둔 원본 미리보기를 발표 화면에 붙인다. */
async function loadPreviewPdf(url, fileName = '') {
  if (!url) return null;
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`미리보기 PDF HTTP ${res.status}`);
  const blob = await res.blob();
  const pdfName = String(fileName || 'preview.pptx').replace(/\.pptx$/i, '.pdf');
  const file = new File([blob], /\.pdf$/i.test(pdfName) ? pdfName : `${pdfName}.pdf`, {
    type: 'application/pdf',
  });
  return loadUploadedPdf(file, file.name);
}

function previewPdfUrlFor(docOrName) {
  if (docOrName && typeof docOrName === 'object' && docOrName.preview_pdf) {
    return docOrName.preview_pdf;
  }
  const hint = typeof docOrName === 'string'
    ? docOrName
    : (docOrName && (docOrName.file_name || docOrName.fileName)) || nf.fileName || '';
  if (!hint) return null;
  return `/api/v1/preview-pdf?file=${encodeURIComponent(hint)}`;
}

async function ensurePreviewPdf(doc = null) {
  if (uploadedPdf) return uploadedPdf;
  const url = previewPdfUrlFor(doc || nfSlideDoc || nf.fileName);
  if (!url) return null;
  try {
    await loadPreviewPdf(url, (doc && doc.file_name) || nf.fileName || 'preview.pdf');
    return uploadedPdf;
  } catch (err) {
    console.warn('[chuckchuck] preview pdf', err);
    return null;
  }
}

async function renderPdfToCanvas(pageNo, canvas, { maxWidth = 960 } = {}) {
  if (!uploadedPdf || !canvas) return false;
  const pageCount = uploadedPdf.pageCount;
  const page = Math.min(Math.max(1, pageNo), pageCount);
  const token = ++pdfRenderToken;
  if (pdfRenderTask) {
    try { pdfRenderTask.cancel(); } catch (_) { /* already done */ }
    pdfRenderTask = null;
  }
  const pdfPage = await uploadedPdf.pdf.getPage(page);
  if (token !== pdfRenderToken) return false;
  const unscaled = pdfPage.getViewport({ scale: 1 });
  const scale = Math.min(2, maxWidth / unscaled.width);
  const viewport = pdfPage.getViewport({ scale });
  const ctx = canvas.getContext('2d');
  canvas.width = Math.floor(viewport.width);
  canvas.height = Math.floor(viewport.height);
  pdfRenderTask = pdfPage.render({ canvasContext: ctx, viewport });
  try {
    await pdfRenderTask.promise;
  } catch (err) {
    if (err && err.name === 'RenderingCancelledException') return false;
    throw err;
  } finally {
    pdfRenderTask = null;
  }
  return token === pdfRenderToken;
}

async function paintRehearsalSlide(pageNo) {
  const canvas = $('#slidePdfCanvas');
  const fallback = $('#slideCardWrap');
  if (canvas && uploadedPdf) {
    canvas.style.display = 'block';
    if (fallback) fallback.style.display = 'none';
    try {
      await renderPdfToCanvas(pageNo, canvas, { maxWidth: canvas.parentElement?.clientWidth || 960 });
    } catch (err) {
      console.warn('[chuckchuck] pdf render', err);
    }
    return;
  }
  if (canvas) canvas.style.display = 'none';
  if (fallback) fallback.style.display = 'block';
}

function activeTitles() {
  return (nf.slideTitles && nf.slideTitles.length) ? nf.slideTitles : DATA.slideTitles;
}
function activeImages() {
  return (nf.slideImages && nf.slideImages.length) ? nf.slideImages : DATA.slideImages;
}
function activeBodies() {
  return (nf.slideBodies && nf.slideBodies.length) ? nf.slideBodies : null;
}
/** F-05 매핑용: slide_no → 제목/본문/썸네일 */
function slideMetaForPipe(slideNo) {
  const n = Number(slideNo) || 0;
  const titles = activeTitles();
  const bodies = activeBodies();
  const images = activeImages();
  const fromDoc = nfSlideDoc && Array.isArray(nfSlideDoc.slides)
    ? nfSlideDoc.slides.find((s) => s.slide_no === n)
    : null;
  const idx = n - 1;
  const title = (fromDoc && fromDoc.title)
    || titles[idx]
    || `${n}번 슬라이드`;
  const body = fromDoc
    ? slideBodyFromSlide(fromDoc)
    : (bodies && bodies[idx]) || '';
  return {
    slide_no: n,
    title,
    body,
    image: images[idx] || null,
    text_sparse: !!(fromDoc && fromDoc.text_sparse),
  };
}

/** 검증 로그의 슬라이드↔발화 매핑 카드 */
function pipeSpeechMapHtml(segments) {
  return `<div class="pipe-map">
    <p class="pipe-map-lead">핵심: <b>몇 번 슬라이드를 보고 있을 때</b> 무엇을 말했는지 (슬라이드 전환 기록 × 받아쓰기)</p>
    ${segments.map((s) => {
      const meta = slideMetaForPipe(s.slide_no);
      const speech = (s.text || '').trim();
      const empty = !speech;
      const preview = String(meta.body || '')
        .split(/\n+/)
        .map((x) => x.trim())
        .filter(Boolean)
        .slice(0, 3)
        .join(' · ')
        .slice(0, 140);
      const thumb = uploadedPdf
        ? `<canvas class="pipe-map-canvas" data-pipe-page="${meta.slide_no}" width="320" height="180" aria-label="${meta.slide_no}번 슬라이드"></canvas>`
        : (meta.image
          ? `<img class="pipe-map-img" src="${meta.image}" alt="${meta.slide_no}번 슬라이드" loading="lazy">`
          : `<div class="pipe-map-ph">${meta.slide_no}</div>`);
      return `<article class="pipe-map-row ${empty ? 'is-empty' : ''}">
        <aside class="pipe-map-slide">
          <div class="pipe-map-thumb">${thumb}</div>
          <div class="pipe-map-meta">
            <div class="pipe-map-title"><b>${meta.slide_no}번</b> ${escapeHtml(meta.title)}</div>
            <p class="pipe-map-preview">${preview ? escapeHtml(preview) : (meta.text_sparse ? '(텍스트 거의 없음)' : '(본문 없음)')}</p>
          </div>
        </aside>
        <div class="pipe-map-speech">
          <header>${fmtMarkSec(s.start_sec)}–${fmtMarkSec(s.end_sec)} · visit ${s.visit || 1}</header>
          <p class="${empty ? 'empty' : ''}">${escapeHtml(speech || '(이 구간 발화 없음)')}</p>
        </div>
      </article>`;
    }).join('')}
  </div>`;
}

async function paintPipeMapThumbs() {
  if (!uploadedPdf) return;
  const canvases = $$('.pipe-map-canvas[data-pipe-page]');
  for (const canvas of canvases) {
    const pageNo = Number(canvas.getAttribute('data-pipe-page')) || 1;
    try {
      // 개별 렌더 — 검증용 작은 썸네일
      const page = Math.min(Math.max(1, pageNo), uploadedPdf.pageCount);
      const pdfPage = await uploadedPdf.pdf.getPage(page);
      const unscaled = pdfPage.getViewport({ scale: 1 });
      const scale = Math.min(1.2, 320 / unscaled.width);
      const viewport = pdfPage.getViewport({ scale });
      const ctx = canvas.getContext('2d');
      canvas.width = Math.floor(viewport.width);
      canvas.height = Math.floor(viewport.height);
      await pdfPage.render({ canvasContext: ctx, viewport }).promise;
    } catch (err) {
      console.warn('[pipe-map] thumb fail', pageNo, err);
    }
  }
}

function escapeHtml(s) {
  return String(s || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
/** SlideDoc 본문을 발표용 텍스트로 정리 */
function slideBodyFromSlide(s) {
  let raw = s.raw_text || '';
  if (!raw && Array.isArray(s.blocks)) {
    raw = s.blocks.map((b) => (b && b.text) || '').filter(Boolean).join('\n');
  }
  return String(raw)
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '') // markdown images
    .replace(/\|/g, ' ')
    .replace(/-{3,}/g, '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}
function slideCardHtml(n, title, body, { compact = false } = {}) {
  const t = escapeHtml(title || `${n}번 슬라이드`);
  const lines = String(body || '')
    .split(/\n+/)
    .map((x) => x.trim())
    .filter(Boolean)
    .slice(0, compact ? 4 : 18);
  const bodyHtml = lines.length
    ? lines.map((ln) => `<p>${escapeHtml(ln.slice(0, compact ? 60 : 160))}</p>`).join('')
    : '<p class="slide-doc-empty">이 슬라이드는 텍스트가 거의 없어요. 도식·이미지 중심으로 말해 보세요.</p>';
  return `<article class="slide-doc-card ${compact ? 'compact' : ''}">
    <header><span class="slide-doc-no">${n}</span><h2>${t}</h2></header>
    <div class="slide-doc-body">${bodyHtml}</div>
  </article>`;
}
function applySlideDoc(doc, { keepDemoImages = false } = {}) {
  nfSlideDoc = doc;
  nf.fileName = doc.file_name || '발표자료';
  nf.slideDocMeta = {
    file_name: doc.file_name || nf.fileName,
    total_slides: doc.total_slides || ((doc.slides || []).length) || 0,
  };
  nf.slideTitles = (doc.slides || []).map((s) => s.title || `${s.slide_no}번 슬라이드`);
  nf.slideBodies = (doc.slides || []).map(slideBodyFromSlide);
  nf.sparseSlides = (doc.slides || []).filter((s) => s.text_sparse).map((s) => s.slide_no);
  // 화면에는 원본 슬라이드(pdf.js 렌더)를 그린다. 파싱된 본문(slideBodies)은 F-06~11
  // 분석 입력으로만 보관하고 썸네일에 찍지 않는다. 아래 값은 원본 렌더가 도착하기 전과
  // 렌더 자체가 불가능할 때(PPTX + soffice 없음)만 보이는 자리표시자다.
  nf.slideImages = nf.slideTitles.map((t, i) => (
    (keepDemoImages && DATA.slideImages[i]) || slidePlaceholder(i + 1)
  ));
  nf.slide = 1;
  nf.visits = { 1: 1 };
  nf.log = [];
}
/** 원본 슬라이드 렌더가 붙기 전/불가능할 때 쓰는 빈 판. 파싱 텍스트를 넣지 않는다. */
function slidePlaceholder(n) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
    <rect width="960" height="540" fill="#f5f7fb"/>
    <rect x="40" y="36" width="880" height="468" rx="14" fill="#fff" stroke="#D5E2DA"/>
    <text x="480" y="290" text-anchor="middle" font-family="Pretendard,sans-serif" font-size="72" font-weight="700" fill="#c6cfdb">${n}</text>
  </svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

function renderNew() {
  saveSession('new-flow', nf);
  bindStepNav();
  app.className = 'narrow';
  app.innerHTML = `${nfSteps()}<div id="nf"></div>`;
  [nfStep1, nfStep2, nfStep3, nfStep4][nf.step]();
}

/* 스텝 1 — 자료 올리기 */
function nfStep1() {
  const box = $('#nf');
  if (nf.gate === null) {
    box.innerHTML = `
      <div class="dropzone" id="dz">
        <h3>발표자료를 올려주세요</h3>
        <p class="note">PDF, PPTX · 최대 30MB, 100장까지 (25장 안팎을 권장해요)</p>
        <div class="dz-actions">
          <button class="btn btn-secondary" id="pick">파일 선택</button>
        </div>
        <input type="file" id="file" accept=".pdf,.pptx" hidden>
      </div>
      <div class="step-actions">
        <button class="btn btn-primary" disabled>다음: 발표 정보 입력</button>
      </div>`;
    const dz = $('#dz');
    $('#pick').addEventListener('click', () => $('#file').click());
    $('#file').addEventListener('change', e => {
      const f = e.target.files[0]; if (!f) return;
      /\.(pdf|pptx)$/i.test(f.name) ? startParse({ file: f }) : failParse('PDF나 PPTX 파일만 분석할 수 있어요.');
    });
    dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('hover'); });
    dz.addEventListener('dragleave', () => dz.classList.remove('hover'));
    dz.addEventListener('drop', e => {
      e.preventDefault(); dz.classList.remove('hover');
      const f = e.dataTransfer.files[0]; if (!f) return;
      /\.(pdf|pptx)$/i.test(f.name) ? startParse({ file: f }) : failParse('PDF나 PPTX 파일만 분석할 수 있어요.');
    });
  } else if (nf.gate === 'parsing') {
    const label = nf.fileName || DATA.session.file;
    const elapsed = nf._parseStartedAt
      ? Math.max(0, Math.floor((Date.now() - nf._parseStartedAt) / 1000))
      : 0;
    box.innerHTML = `
      <div class="card">
        <b style="font-size:15px">${label}</b>
        <p class="note" style="margin-top:2px">Upstage Document Parse로 슬라이드 구조를 만드는 중</p>
        <div class="progress indeterminate"><i></i></div>
        <p class="parse-meta">경과 <b id="parseElapsed">${elapsed}</b>초 · 장수가 많으면 1~5분 걸릴 수 있어요. 진행 바가 가득 차 보여도 정상입니다.</p>
      </div>
      <div class="step-actions">
        <button class="btn btn-secondary" id="cancelParse">취소하고 다시 올리기</button>
        <button class="btn btn-primary" disabled>다음: 발표 정보 입력</button>
      </div>`;
    $('#cancelParse').addEventListener('click', () => {
      parseGen += 1;
      if (parseTimer) { clearInterval(parseTimer); parseTimer = null; }
      nf.gate = null;
      nf._parseStartedAt = null;
      nf.parseError = null;
      saveSession('new-flow', nf);
      nfStep1();
    });
    if (parseTimer) { clearInterval(parseTimer); parseTimer = null; }
    parseTimer = every(() => {
      const el = $('#parseElapsed');
      if (!el || !nf._parseStartedAt) return;
      el.textContent = String(Math.max(0, Math.floor((Date.now() - nf._parseStartedAt) / 1000)));
    }, 1000);
  } else if (nf.gate === 'fail') {
    box.innerHTML = `
      ${stageAccidentHtml(nf.parseError || 'PDF나 PPTX 파일만 분석할 수 있어요. 다른 파일로 올려주세요.', { title: '죄송해요, 대본을 못 받았어요!' })}
      <div class="step-actions"><button class="btn btn-secondary" id="retry">다시 올리기</button></div>`;
    $('#retry').addEventListener('click', () => { nf.gate = null; nf.parseError = null; nfStep1(); });
  } else {
    const titles = activeTitles();
    const images = activeImages();
    const sparse = new Set(nf.sparseSlides || []);
    const warnNote = sparse.size
      ? `${[...sparse].slice(0, 3).join(', ')}번 슬라이드는 텍스트가 적어요. 발표 때 말한 내용으로 구조를 보완할게요.`
      : '슬라이드 텍스트를 기준으로 개념을 추출할 준비가 됐어요.';
    box.innerHTML = `
      <div class="card">
        <div class="gate-ok">${titles.length}장에서 핵심 개념 후보를 준비했어요</div>
        <div class="thumbs">
          ${titles.map((t, i) => `
          <div class="thumb ${sparse.has(i + 1) ? 'warn' : ''}"><img src="${images[i]}" data-thumb-page="${i + 1}" alt="${i + 1}번 슬라이드" loading="lazy"><span><b>${i + 1}</b>${escapeHtml(t)}</span></div>`).join('')}
        </div>
        <div class="warn-note">${warnNote}</div>
      </div>
      <div class="step-actions">
        <button class="btn btn-primary" id="next">다음: 발표 정보 입력</button>
      </div>`;
    // 자리표시자를 원본 슬라이드 렌더로 교체 (리포트 필름과 같은 경로)
    paintDeckThumbs(box);
    $('#next').addEventListener('click', () => { nf.step = 1; renderNew(); });
  }
}

async function startParse({ file = null, fixture = false } = {}) {
  const myGen = ++parseGen;
  nf.gate = 'parsing';
  nf.parseError = null;
  nf.useSample = !!fixture || !file;
  nf.fileName = file ? file.name : '샘플 발표자료';
  nf._parseStartedAt = Date.now();
  nfStep1();

  const bridge = window.ChuckchuckBridge;
  if (!bridge || typeof bridge.parseDocument !== 'function') {
    await new Promise((r) => setTimeout(r, 300));
  }
  try {
    const b = window.ChuckchuckBridge;
    if (!b || typeof b.parseDocument !== 'function') {
      throw new Error('SDK bridge가 아직 준비되지 않았어요. 페이지를 새로고침 해주세요.');
    }
    const doc = await b.parseDocument({ file, fixture: nf.useSample });
    if (myGen !== parseGen) return; // 취소됨
    applySlideDoc(doc, { keepDemoImages: nf.useSample });
    setUploadedPdf(null); // 이전 자료 잔상 제거 (썸네일 캐시까지)
    if (file && /\.pdf$/i.test(file.name || '')) {
      try { await loadUploadedPdf(file); }
      catch (e) { console.warn('[chuckchuck] pdf load', e); }
    } else if (doc.preview_pdf || (file && /\.pptx$/i.test(file.name || ''))) {
      // PPTX는 텍스트만 파싱되므로, 변환된 PDF 원본으로 발표 화면을 그린다
      try {
        await ensurePreviewPdf(doc);
        if (uploadedPdf) nf.previewPdf = doc.preview_pdf || previewPdfUrlFor(doc);
      } catch (e) { console.warn('[chuckchuck] pptx preview', e); }
    }
    nf.gate = 'done';
    nf._parseStartedAt = null;
    if (parseTimer) { clearInterval(parseTimer); parseTimer = null; }
    saveSession('new-flow', nf);
  } catch (err) {
    if (myGen !== parseGen) return;
    console.warn('[chuckchuck] parse', err);
    nf.parseError = err.message || String(err);
    nf.gate = 'fail';
    nf._parseStartedAt = null;
    if (parseTimer) { clearInterval(parseTimer); parseTimer = null; }
  }
  if (myGen === parseGen) nfStep1();
}
function failParse(msg) {
  parseGen += 1;
  if (parseTimer) { clearInterval(parseTimer); parseTimer = null; }
  nf.parseError = msg || null;
  nf.gate = 'fail';
  nf._parseStartedAt = null;
  nfStep1();
}

/* 스텝 2 — 발표 정보 (선택) */
/** 발표 상황 칩 아이콘.
 *
 * 네 상황은 글자만으로는 한눈에 안 갈린다 — 앞 두 글자가 다 다른 명사라
 * 읽어야 구분된다. 아이콘은 장식이 아니라 그 구분을 대신하는 표식이다.
 *
 * 토스 그래픽 가이드(consumer-ux-guide §그래픽) 기준을 지킨다:
 *   - 24~40px 로 쓴다 (여기선 18px 박스에 24 뷰박스를 축소해 칩 높이 40 에 맞춘다)
 *   - 한 항목에 아이콘 하나. 둘 이상 병렬 조합은 지양한다
 *   - 토스가 제공하는 자산은 쓰지 않는다 — 앱인토스 제휴 환경 밖에서는
 *     복제·배포가 금지돼 있어서, 우리 선 두께로 직접 그렸다
 *
 * currentColor 를 쓰므로 칩이 선택되면(.on) 글자와 같이 브랜드색으로 바뀐다.
 */
function occIcon(occ) {
  const paths = {
    // 학사모 — 학교
    '학교 프로젝트 (교수 대상)': '<path d="M3 9l9-4 9 4-9 4-9-4z"/><path d="M7 11v4c0 1.1 2.2 2 5 2s5-.9 5-2v-4"/>',
    // 확성기 — 대중에게 알리는 자리
    '신제품 설명 (대중 대상)': '<path d="M4 9v6h3l6 4V5L7 9H4z"/><path d="M17 9a4 4 0 0 1 0 6"/>',
    // 막대 그래프 문서 — 숫자로 보고하는 자리
    '업무 보고 (상사 대상)': '<path d="M6 3h8l4 4v14H6z"/><path d="M9 17v-3M12 17v-6M15 17v-4"/>',
    // 말풍선 — 편하게 주고받는 자리
    '동료 간 캐주얼 PR': '<path d="M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H9l-5 4V6z"/>',
  };
  const d = paths[occ];
  if (!d) return '';
  return `<svg class="chip-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
}

function nfStep2() {
  /* 채점표 v3 의 상황 4열 그대로다. 라벨을 그대로 보내면 서버(rubric_v3.resolve_situation)가
     상황 key 로 옮긴다 — 프론트가 key 를 따로 들고 있지 않아도 되고, 이 문장이 F-06·07·11
     프롬프트에도 그대로 들어가서 한국어로 읽힌다. 문구를 바꾸면 가중치가 바뀐다. */
  const occs = [
    '학교 프로젝트 (교수 대상)',
    '신제품 설명 (대중 대상)',
    '업무 보고 (상사 대상)',
    '동료 간 캐주얼 PR',
  ];
  const times = [3, 5, 10, 15, 20, 30];
  const titles = activeTitles();
  const perSlide = Math.round(nf.min * 60 / titles.length);
  $('#nf').innerHTML = `
    <div class="card">
      <h2 style="font-size:19px;font-weight:800;letter-spacing:-.2px">어떤 발표인가요?</h2>
      <p class="note" style="margin:4px 0 22px">건너뛰어도 돼요. 입력하면 개념 중요도를 더 정확하게 정할 수 있어요.</p>
      <div class="field">
        <label>발표 상황</label>
        <div class="chips" id="occ">
          ${occs.map(o => `<button class="${nf.occ === o ? 'on' : ''}" data-occ="${o}">${occIcon(o)}<span>${o}</span></button>`).join('')}
        </div>
      </div>
      <div class="field">
        <label>조금 더 설명해주면 좋아요</label>
        <input type="text" id="ctx" value="${nf.ctx}" placeholder="예: 경영학 수업에서 교수님과 학생 30명 앞에서 발표해요">
      </div>
      <div class="field" style="margin-bottom:0">
        <label>발표 시간</label>
        <div class="time-presets" id="timePresets">
          ${times.map(t => `<button class="${nf.min === t ? 'on' : ''}" data-min="${t}">${t}분</button>`).join('')}
        </div>
        <div class="time-detail">
          <p><b>23장 기준 장당 약 ${perSlide}초</b><span>질문 시간을 포함하면 1~2분 여유를 두는 게 좋아요.</span></p>
        </div>
      </div>
    </div>
    <div class="step-actions">
      <button class="btn btn-primary" id="go">녹음하러 가기</button>
      <button class="btn btn-text" id="skip">건너뛰기</button>
    </div>`;
  $('#occ').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    // data-occ 로 읽는다. textContent 로 읽으면 버튼 안에 아이콘·부가 문구를
    // 넣는 순간 값이 오염되고, rubric_v3.py 는 이 한국어 문자열로 상황을
    // 매핑하므로(school_project 등) 조용히 기본 가중치로 떨어진다.
    nf.occ = b.dataset.occ || b.textContent.trim();
    $$('#occ button').forEach(x => x.classList.toggle('on', x === b));
    saveSession('new-flow', nf);
  });
  $('#ctx').addEventListener('input', e => { nf.ctx = e.target.value; saveSession('new-flow', nf); });
  $('#timePresets').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    nf.min = Number(b.dataset.min); nfStep2(); saveSession('new-flow', nf);
  });
  // 녹음 화면으로 넘어가는 순간 자료 축(F-06·F-07)을 먼저 건다 — 발표하는 동안 돈다
  $('#go').addEventListener('click', () => { startPrecompute(); nf.step = 2; renderNew(); });
  // 건너뛰면 상황을 비운다. 서버가 기본 기준으로 매기고 "안 골라서 …" 안내를 남긴다 —
  // 없는 상황을 지어내 보내면 어느 가중치로 매겼는지 알 수 없게 된다.
  $('#skip').addEventListener('click', () => {
    nf.occ = '';
    startPrecompute();   // occ 를 비운 뒤에 걸어야 그 조건 그대로 개념을 뽑는다
    nf.step = 2;
    renderNew();
  });
}

/* 스텝 3 — 리허설 녹음 */
function rehearsalCount() {
  const fromPdf = uploadedPdf && uploadedPdf.pageCount ? uploadedPdf.pageCount : 0;
  const fromTitles = activeTitles().length;
  return Math.max(fromPdf, fromTitles, 1);
}

function nfStep3() {
  // 새로고침 후 PPTX 원본 미리보기가 비면 서버 캐시 PDF를 비동기로 붙인 뒤 다시 그린다
  if (!uploadedPdf && (nf.previewPdf || nf.fileName) && !nf._previewLoading) {
    nf._previewLoading = true;
    ensurePreviewPdf(nfSlideDoc).then((pdf) => {
      nf._previewLoading = false;
      if (pdf && nf.step === 2) nfStep3();
    }).catch(() => { nf._previewLoading = false; });
  }
  const nPages = rehearsalCount();
  if (!nf.slide || nf.slide < 1) nf.slide = 1;
  if (nf.slide > nPages) nf.slide = nPages;
  const titles = activeTitles();
  const titleAt = (i) => titles[i] || `${i + 1}번 슬라이드`;
  const usePdf = !!uploadedPdf;
  const bodies = activeBodies();

  const stageInner = usePdf
    ? `<canvas id="slidePdfCanvas" class="slide-pdf-canvas" aria-label="원본 PDF 슬라이드"></canvas>
       <div id="slideCardWrap" class="slide-doc-wrap" style="display:none"></div>`
    : (bodies && bodies.length
      ? `<div id="slideCardWrap" class="slide-doc-wrap">${slideCardHtml(nf.slide, titleAt(nf.slide - 1), bodies[nf.slide - 1])}</div>`
      : `<img id="slideImage" src="${activeImages()[nf.slide - 1] || ''}" alt="">`);

  /* 필름은 "몇 번을 고를까"가 아니라 "어느 그림으로 갈까"를 고르는 자리다.
     원본 PDF 가 있으면 그 페이지를 그려 넣고(paintDeckThumbs 가 채운다),
     없으면 번호·제목만 남긴다 — 파싱 텍스트를 그림인 척 넣지 않는다 */
  const film = Array.from({ length: nPages }, (_, i) => {
    const on = i + 1 === nf.slide ? 'on' : '';
    const no = i + 1;
    const title = escapeHtml(String(titleAt(i)).slice(0, 28));
    if (!usePdf) {
      return `<button type="button" class="${on}" data-slide="${no}" aria-label="${no}번 슬라이드"><span class="film-no">${no}</span><span class="film-title">${title}</span></button>`;
    }
    return `<button type="button" class="${on}" data-slide="${no}" aria-label="${no}번 슬라이드">
      <img class="film-thumb" data-thumb-page="${no}" src="${slidePlaceholder(no)}" alt="">
      <span class="film-cap"><span class="film-no">${no}</span><span class="film-title">${title}</span></span>
    </button>`;
  }).join('');

  app.className = '';
  app.innerHTML = `${nfSteps()}
    <div class="rehearsal-head">
      <div><span class="mode-label">발표 모드</span><h1>슬라이드를 보며 실제처럼 발표해보세요</h1></div>
      <p>← → 키나 슬라이드 목록으로 넘길 수 있어요${usePdf ? ' · 업로드한 PDF 원본' : ''}</p>
      ${precomputeNoteHtml()}
    </div>
    <div class="rehearsal-shell">
      <div class="card rehearsal-control" id="recPanel"></div>
      <div class="card viewer presentation-viewer">
        <div class="viewer-stage ${usePdf ? 'has-pdf' : 'has-slide-doc'}">
          ${stageInner}
          <button type="button" class="stage-nav stage-prev" data-slide-nav="-1" aria-label="이전 슬라이드">‹</button>
          <button type="button" class="stage-nav stage-next" data-slide-nav="1" aria-label="다음 슬라이드">›</button>
        </div>
        <div class="viewer-caption">
          <div class="caption-nav">
            <button type="button" class="btn btn-secondary btn-sm" data-slide-nav="-1">이전</button>
            <button type="button" class="btn btn-secondary btn-sm" data-slide-nav="1">다음</button>
          </div>
          <strong id="slideTitle">${escapeHtml(titleAt(nf.slide - 1))}</strong>
          <small id="slideNo" class="num">${nf.slide} / ${nPages}</small>
        </div>
        <div class="slide-film ${usePdf ? 'slide-film-deck' : 'slide-film-text'}" id="slideFilm">${film}</div>
      </div>
    </div>
    <div class="sf" id="stagefront" aria-hidden="true"></div>
    <p class="privacy-note">녹음은 발표 분석에만 사용돼요.</p>`;
  renderRecPanel();
  bindRehearsalNav();
  paintRehearsalSlide(nf.slide);
  // 무대가 먼저다. 필름 썸네일은 그 뒤에 순차로 채워진다(캐시라 두 번째부터는 즉시)
  if (usePdf) paintDeckThumbs(app);
  startPrecomputeNoteTimer();
  if (nf.mic === 'on' && !ccRuntime) startRecClock();
  wireFreshPracticeButtons(app);
}

function moveSlide(d) {
  const n = rehearsalCount();
  moveSlideTo(Math.min(n, Math.max(1, (Number(nf.slide) || 1) + Number(d || 0))));
}

function moveSlideTo(next) {
  try {
    const nPages = rehearsalCount();
    next = Number(next);
    if (!Number.isFinite(next)) return;
    next = Math.min(nPages, Math.max(1, next));
    if (next === nf.slide) {
      paintRehearsalSlide(next);
      return;
    }
    const titles = activeTitles();
    const bodies = activeBodies();
    const titleAt = (i) => titles[i] || `${i + 1}번 슬라이드`;
    nf.slide = next;
    saveSession('new-flow', nf);
    const no = $('#slideNo'); if (no) no.textContent = `${next} / ${nPages}`;
    const title = $('#slideTitle'); if (title) title.textContent = titleAt(next - 1);
    $$('#slideFilm button').forEach((b) => b.classList.toggle('on', Number(b.dataset.slide) === next));
    const currentThumb = $(`#slideFilm button[data-slide="${next}"]`);
    if (currentThumb) currentThumb.scrollIntoView({ block: 'nearest', inline: 'center' });
    paintRehearsalSlide(next);
    const wrap = $('#slideCardWrap');
    if (wrap && wrap.style.display !== 'none' && bodies) {
      wrap.innerHTML = slideCardHtml(next, titleAt(next - 1), bodies[next - 1] || '');
    }
    const image = $('#slideImage');
    if (image) {
      const images = activeImages();
      image.src = images[next - 1] || '';
      image.alt = `${next}번 슬라이드 · ${titleAt(next - 1)}`;
    }
    if (nf.mic !== 'on') return;

    // 객석이 자세를 고쳐 앉는다. 방문 기록이 갱신되기 전이라 여기 값이 '직전'이다
    audienceOnSlide(((nf.visits && nf.visits[next]) || 0) >= 1);

    if (ccRuntime) {
      let entry = ccRuntime.goTo(next);
      // SDK가 무시해도(너무 짧은 체류 등) 화면 카운트/로그는 남긴다
      if (!entry) {
        const re = (nf.visits[next] || 0) > 1;
        entry = {
          txt: re
            ? `${fmt(nf.sec)} ↩ ${next}번 슬라이드 (${nf.visits[next]}번째 방문)`
            : `${fmt(nf.sec)} → ${next}번 슬라이드`,
          re,
        };
        if (!Array.isArray(nf.log)) nf.log = [];
        const prev = nf.log[nf.log.length - 1];
        if (!prev || prev.txt !== entry.txt) nf.log.push(entry);
      }
      appendRecLog(entry);
      return;
    }

    const re = !!nf.visits[next];
    nf.visits[next] = (nf.visits[next] || 0) + 1;
    const txt = re
      ? `${fmt(nf.sec)} ↩ ${next}번 슬라이드 (${nf.visits[next]}번째 방문)`
      : `${fmt(nf.sec)} → ${next}번 슬라이드`;
    if (!Array.isArray(nf.log)) nf.log = [];
    nf.log.push({ txt, re });
    appendRecLog({ txt, re });
  } catch (err) {
    console.warn('[chuckchuck] moveSlideTo', err);
  }
}

function slideSwitchCount() {
  return Math.max(0, ((nf.log && nf.log.length) || 0) - 1);
}

function appendRecLog(entry) {
  if (!entry) return;
  const countEl = $('#recSwitchCount');
  if (countEl) countEl.textContent = String(slideSwitchCount());
  const log = $('#tlog');
  if (!log) return;
  const s = document.createElement('span');
  s.textContent = entry.txt;
  if (entry.re) s.className = 're';
  log.appendChild(s);
  log.scrollTop = log.scrollHeight;
}

/** 마이크 없이 저장해 둔 녹음본으로 돌려보는 입구 (테스트용). */
function recUploadHtml() {
  return `
    <div class="rec-upload">
      <button class="btn btn-text btn-sm" id="recUploadPick">녹음 파일로 대신하기</button>
      <p class="note" id="recUploadNote">m4a · mp3 · wav · webm · 최대 ${MAX_AUDIO_MB}MB. 슬라이드 구간은 길이를 균등하게 나눠 채워요.</p>
      <input type="file" id="recUploadFile" accept="audio/*,.webm,.m4a,.mp4,.mp3,.wav,.ogg" hidden>
    </div>`;
}

function bindRecUpload() {
  const pick = $('#recUploadPick');
  const input = $('#recUploadFile');
  if (!pick || !input) return;
  pick.addEventListener('click', () => input.click());
  input.addEventListener('change', (e) => {
    const f = e.target.files[0];
    e.target.value = ''; // 같은 파일을 다시 고를 수 있게
    if (f) useUploadedRecording(f);
  });
}

function renderRecPanel() {
  const p = $('#recPanel'); if (!p) return;
  p.classList.toggle('is-live', nf.mic === 'on');
  refreshStepBar(); // 녹음 중에는 지나온 단계 버튼을 닫는다
  if (nf.mic === 'idle') {
    /* 단계 표시줄로 질문 준비에서 돌아온 경우다. nf.step=3 은 녹음을 마쳐야만
       세워지므로 길을 안 열어 주면 이미 끝난 분석으로 다시 갈 수가 없다 */
    const hasTake = !!(nf.pipelineOut || nf.pipelineError);
    p.innerHTML = `
      <div class="rec-copy"><span>준비되면 시작하세요</span><p>${hasTake
        ? '다시 발표해도 되고, 아까 발표한 결과로 바로 넘어가도 돼요.'
        : '발표하면서 넘긴 슬라이드와 말한 내용을 함께 기록해요.'}</p></div>
      ${hasTake ? '<button class="btn btn-secondary" id="recResume">아까 발표로 질문 준비하기</button>' : ''}
      <button class="btn btn-primary" id="recStart">발표 시작하기</button>
      ${recUploadHtml()}`;
    $('#recStart').addEventListener('click', startRec);
    if (hasTake) {
      $('#recResume').addEventListener('click', () => { nf.step = 3; renderNew(); });
    }
    bindRecUpload();
  } else if (nf.mic === 'denied') {
    p.innerHTML = `
      <div class="mic-denied"><b>마이크 권한이 필요해요</b><span>주소창의 권한 설정에서 허용한 뒤 다시 시작해주세요.</span></div>
      <button class="btn btn-secondary" id="recRetry">다시 시도하기</button>
      ${recUploadHtml()}`;
    $('#recRetry').addEventListener('click', startRec);
    bindRecUpload();
  } else {
    p.innerHTML = `
      <div class="rec-status">
        <div><span class="rec-live">발표 중</span><strong class="rec-clock" id="clock">${fmt(nf.sec)}</strong></div>
        <span class="meter" aria-label="마이크 입력 감지 중"><i></i><i></i><i></i><i></i><i></i></span>
      </div>
      <details class="rec-log-fold" open><summary>슬라이드 전환 <b id="recSwitchCount">${slideSwitchCount()}</b>회 기록</summary><div class="trans-log" id="tlog">
        ${(nf.log || []).map(l => `<span class="${l.re ? 're' : ''}">${l.txt}</span>`).join('')}
      </div></details>
      <button class="btn btn-primary" id="recEnd">발표 마치고 질문 준비하기</button>`;
    $('#recEnd').addEventListener('click', finishRecAndPrepare);
    audienceMount();   // 무대에 올랐으면 객석에도 넷이 앉아 있어야 한다
  }
}

/* ─── 정직한 관객 (UI_REDESIGN §2) ──────────────────────────────────────────
   공연 중이 타임라인에서 가장 길고 감정이 높은 구간인데 지금까지 아무도 없었다.

   철칙: 거짓 반응 금지. LLM 분석은 발표가 끝나야 시작하므로, 지금 이 순간
   실제로 아는 신호로만 반응을 만든다 — 마이크 레벨, 슬라이드 전환, 체류 시간,
   침묵. 내용을 아는 척하는 연기("이해했다는 끄덕임")는 절대 안 된다.
   허용되는 건 자세·주목·필기뿐이고, 판정 반응은 커튼콜 뒤에만 나온다.

   절제 규칙: 반응은 신호가 온 순간에만, 동시에 움직이는 건 1마리 (Staging).
   발표자의 시선을 뺏으면 안 되므로 기본은 어두운 실루엣이다. */

const SILENCE_SEC = 7;          // 이만큼 조용하면 한 마리가 갸웃 — 공연당 1회
const DWELL_SEC = 50;           // 한 장에 이만큼 머물면 믿:음이 밑줄을 긋는다
const NOD_LEVEL = 0.18;         // 이 위로 올라가야 '말하는 중'으로 본다
const NOD_GAP_MS = 1400;        // 끄덕임 간격. 매 프레임 끄덕이면 기계다

const aud = { lastNod: 0, silentFrom: 0, tilted: false, dwellFrom: 0, dwellDone: false };

function audienceHtml() {
  if (!window.Chatter) return '';
  return `<div class="sf-row">${window.Chatter.SEATS.map(s =>
    `<div class="ch-seat" data-speaker="${s}">${window.Chatter.chickSvg(s)}</div>`
  ).join('')}</div>`;
}

/** 한 마리에게 잠깐 반응을 입힌다. 같은 순간에 둘이 움직이지 않게 짧게 끝낸다. */
function audienceReact(speaker, cls, ms) {
  const el = $(`#stagefront .ch-seat[data-speaker="${speaker}"]`);
  if (!el) return;
  el.classList.add(cls);
  later(() => el.classList.remove(cls), ms);
}

function audienceMount() {
  const host = $('#stagefront');
  if (!host || host.dataset.on === '1') return;
  host.dataset.on = '1';
  host.innerHTML = audienceHtml();
  aud.lastNod = 0;
  aud.silentFrom = 0;
  aud.tilted = false;
  aud.dwellFrom = Date.now();
  aud.dwellDone = false;
}

/** 마이크 레벨 — 말하는 동안 엑씨(헤드폰)가 리듬 타듯 미세하게 끄덕인다. */
function audienceOnLevel(level) {
  const now = Date.now();
  if (level >= NOD_LEVEL) {
    aud.silentFrom = 0;
    if (now - aud.lastNod > NOD_GAP_MS) {
      aud.lastNod = now;
      audienceReact('ax', 'nodding', 700);
    }
    return;
  }
  // 긴 침묵 — 한 마리가 갸웃한다. 공연당 최대 1회 (놀리는 것처럼 보이면 안 된다)
  if (!aud.silentFrom) aud.silentFrom = now;
  if (!aud.tilted && now - aud.silentFrom > SILENCE_SEC * 1000) {
    aud.tilted = true;
    audienceReact('exaone', 'wondering', 1600);
  }
}

/** 슬라이드 전환 — 넷이 자세를 고쳐 앉고, 쏠라가 대본을 한 장 넘긴다. */
function audienceOnSlide(isRevisit) {
  const row = $('#stagefront .sf-row');
  if (!row) return;
  row.classList.add('shifting');
  later(() => row.classList.remove('shifting'), 700);
  // 재방문이면 쏠라가 대본을 '앞으로' 뒤적인다 — 방향이 사실을 따른다
  audienceReact('solar', isRevisit ? 'rewinding' : 'flipping', 900);
  aud.dwellFrom = Date.now();
  aud.dwellDone = false;
}

/** 한 장에 오래 머묾 — 믿:음이 형광펜으로 밑줄을 긋는다 (메모 중). */
function audienceOnTick() {
  if (aud.dwellDone || !aud.dwellFrom) return;
  if (Date.now() - aud.dwellFrom < DWELL_SEC * 1000) return;
  aud.dwellDone = true;
  audienceReact('midm', 'marking', 1800);
}

/* ─── 등장 의식 (§1) ────────────────────────────────────────────────────────
   녹음 시작이 이 제품에서 가장 무서운 버튼이다. "녹음"은 감시의 언어고
   "무대"는 역할의 언어다. 조명이 내려가고 큐 사인이 나는 1.5초가 불안을
   배역으로 바꾼다 — 사용자는 녹음당하는 게 아니라 무대에 오르는 것이다. */

const CUE_KEY = 'cheokcheok:stage-visits';
const CUE_MS = 1500;

function stageVisits() {
  try { return Number(localStorage.getItem(CUE_KEY)) || 0; }
  catch (_) { return 0; }
}

function showEntranceRitual() {
  if (!window.Chatter) return Promise.resolve();
  let n = stageVisits();
  try { localStorage.setItem(CUE_KEY, String(n + 1)); } catch (_) { /* ignore */ }
  // 2회차부터는 스킵. 매번 1.5초를 다시 보게 하면 의식이 아니라 지연이다
  if (n > 0) return Promise.resolve();

  const veil = document.createElement('div');
  veil.className = 'cue-veil';
  veil.innerHTML = `
    <div class="cue-row">
      ${window.Chatter.SEATS.map(s =>
        `<div class="ch-seat" data-speaker="${s}">${window.Chatter.chickSvg(s)}</div>`
      ).join('')}
    </div>
    <div class="cue-word">…큐!</div>`;
  document.body.appendChild(veil);
  requestAnimationFrame(() => veil.classList.add('on'));
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      veil.classList.remove('on');
      setTimeout(() => veil.remove(), 320);
      resolve();
    };
    veil.addEventListener('click', finish);   // 모든 연출은 스킵 가능하다 (§14)
    setTimeout(finish, CUE_MS);
  });
}

/* chuckchuck SDK 런타임 (F-03/F-04). bridge 모듈 로드 전엔 null. */

async function startRec() {
  await showEntranceRitual();
  const bridge = window.ChuckchuckBridge;
  if (bridge) {
    ccRuntime = bridge.attachRehearsalRuntime(nf, {
      totalSlides: rehearsalCount(),
      onLevel: audienceOnLevel,
      onTick: (sec) => {
        nf.sec = Math.floor(sec);
        const c = $('#clock'); if (c) c.textContent = fmt(nf.sec);
        audienceOnTick();
      },
    });
    ccRuntime.start(nf.slide).then(() => {
      renderRecPanel();
      saveSession('new-flow', nf);
    }).catch(() => {
      nf.mic = 'denied';
      ccRuntime = null;
      renderRecPanel();
      saveSession('new-flow', nf);
    });
    return;
  }
  // SDK 없을 때 데모 mock 폴백
  nf.mic = 'on'; nf.sec = 0;
  nf.visits = { [nf.slide]: 1 };
  nf.log = [{ txt: `00:00 → ${nf.slide}번 슬라이드` }];
  renderRecPanel();
  startRecClock();
  saveSession('new-flow', nf);
}

function startRecClock() {
  every(() => {
    nf.sec++;
    const c = $('#clock'); if (c) c.textContent = fmt(nf.sec);
    audienceOnTick();
    saveSession('new-flow', nf);
  }, 1000);
}

/* ─── 종연 3초 (UI_REDESIGN §3) ─────────────────────────────────────────────
   발표를 마치는 순간, 분석은 7분 걸리지만 박수칠 이유는 이미 안다: 끝까지 했다.
   네트워크 없이 즉시 아는 값(슬라이드 수·경과 시간)만 쓴다.

   이 박수는 점수와 무관하게 무조건 나온다 (§6 '두 개의 박수'). 성적을 정직하게
   따르는 박수는 커튼콜이 따로 맡는다. 둘을 합치면 박수가 성적표가 된다. */

const CURTAIN_CALL_MS = 3000;

function curtainCallCopy(slides, durationSec) {
  const sec = Math.max(0, Math.round(Number(durationSec) || 0));
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  const time = m ? `${m}분 ${s}초` : `${s}초`;
  return `${slides}장, ${time}, <b>완주!</b>`;
}

/** 3초 뒤(또는 아무 데나 누르면 바로) 해소되는 약속을 돌려준다. */
function showCurtainCall(slides, durationSec) {
  // Chatter 가 아직 안 붙었으면 연출을 건너뛴다 — 연출 때문에 흐름이 막히면 안 된다
  if (!window.Chatter) return Promise.resolve();

  const veil = document.createElement('div');
  veil.className = 'cc-veil';
  veil.innerHTML = `
    <div class="cc-row">
      ${window.Chatter.SEATS.map(s =>
        `<div class="ch-seat" data-speaker="${s}" data-mood="happy">
           ${window.Chatter.chickSvg(s)}
         </div>`).join('')}
    </div>
    <div class="cc-line">${curtainCallCopy(slides, durationSec)}</div>
    <div class="cc-sub">끝까지 하셨어요. 그동안 넷이서 발표를 뜯어볼게요.</div>
    <div class="cc-skip">아무 데나 누르면 바로 넘어가요</div>`;
  document.body.appendChild(veil);
  requestAnimationFrame(() => veil.classList.add('on'));

  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      veil.classList.remove('on');
      setTimeout(() => veil.remove(), 380);
      resolve();
    };
    veil.addEventListener('click', finish);
    setTimeout(finish, CURTAIN_CALL_MS);
  });
}

async function finishRecAndPrepare() {
  // 완주 박수에 쓸 값은 파이프라인 전에 확정한다. SDK 없이 mock 으로 돈
  // 테이크에는 durationSec 이 없으므로 화면 시계(nf.sec)가 유일한 사실이다.
  const slides = rehearsalCount();
  if (ccRuntime) {
    ccLastTake = await ccRuntime.finish();
    nf.marks = (ccLastTake && ccLastTake.marks) || [];
    nf.uploadedTake = null; // 실연 테이크가 업로드본을 덮는다
    nf.done = 0;
    nf._pipelineStarted = false;
    nf.pipelineOut = null;
    nf.pipelineError = null;
    nf.pipelinePhase = 'queued';
    nf.pipelineDetail = '파이프라인 대기';
    nf.pipelineStartedAt = Date.now();
    nf._pipelineTickStarted = false;
    saveSession('new-flow', nf);
  }
  nf.backstage = [];   // 막간 대사는 테이크마다 새로 쌓인다
  // 녹음은 여기서 끝났다. 'on' 으로 두면 리허설로 돌아왔을 때 이미 끝난 발표가
  // 「발표 중」 시계로 다시 그려지고, 단계 표시줄도 녹음 중인 줄 알고 잠긴다
  nf.mic = 'idle';
  await showCurtainCall(slides, (ccLastTake && ccLastTake.durationSec) || nf.sec);
  nf.step = 3;
  renderNew();
  showF11Reveal();
}

/**
 * F-01 결과를 되살린다.
 *
 * nfSlideDoc 은 메모리에만 있어서 새로고침 한 번에 사라지고, 없으면 파이프라인이
 * F-06 이후(개념·그래프·정합·수다)를 통째로 건너뛴다. 서버가 파싱할 때 남겨 둔
 * 캐시를 파일 이름으로 찾아 붙여, 같은 자료로 녹음만 바꿔가며 반복 테스트할 수 있게 한다.
 * 못 찾으면 null — 호출부가 재파싱을 안내한다.
 */
async function ensureSlideDoc() {
  if (nfSlideDoc) {
    if (!uploadedPdf) await ensurePreviewPdf(nfSlideDoc);
    return nfSlideDoc;
  }
  const hint = nf.fileName || '';
  try {
    const res = await fetch(`/api/v1/cached-slidedoc?file=${encodeURIComponent(hint)}`);
    if (!res.ok) return null;
    const doc = await res.json();
    if (!doc || doc.error || !Array.isArray(doc.slides)) return null;
    nfSlideDoc = doc;
    console.info('[chuckchuck] SlideDoc 캐시 복구', doc.file_name, doc.total_slides);
    if (!uploadedPdf) await ensurePreviewPdf(doc);
    return nfSlideDoc;
  } catch (err) {
    console.warn('[chuckchuck] cached-slidedoc', err);
  }
  return null;
}

/* ── 녹음 파일 업로드 (테스트용) ──────────────────────────────────────────
   마이크로 실연하는 대신 저장해 둔 녹음본을 그대로 파이프라인에 태운다.
   업로드본에는 슬라이드 전환 기록이 없으므로 marks 를 길이 균등 분할로 합성한다.
   합성 marks 는 측정값이 아니다 — 화면 곳곳에 그렇게 표시한다. */

const MAX_AUDIO_MB = 30;
const MAX_AUDIO_BYTES = MAX_AUDIO_MB * 1024 * 1024;
const AUDIO_EXT_RE = /\.(webm|m4a|mp4|mp3|wav|ogg|oga|flac|aac)$/i;
const AUDIO_META_TIMEOUT_MS = 4000;

/** 오디오 길이(초). 0 이면 못 읽은 것. */
async function audioDurationSec(file) {
  const url = URL.createObjectURL(file);
  let viaTag = 0;
  try {
    viaTag = await new Promise((resolve) => {
      const el = new Audio();
      let settled = false;
      const done = (v) => {
        if (settled) return;
        settled = true;
        el.removeAttribute('src');
        resolve(Number(v) || 0);
      };
      el.preload = 'metadata';
      el.onloadedmetadata = () => done(el.duration);
      el.onerror = () => done(0);
      setTimeout(() => done(0), AUDIO_META_TIMEOUT_MS);
      el.src = url;
    });
  } finally {
    URL.revokeObjectURL(url);
  }
  if (Number.isFinite(viaTag) && viaTag > 0) return viaTag;

  // MediaRecorder 가 만든 webm 은 duration 이 Infinity 로 오는 브라우저가 있다.
  // 우리 SDK 결과물을 다시 올리는 경우가 정확히 여기 걸리므로 디코딩으로 확정한다.
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return 0;
  const ctx = new Ctx();
  try {
    const buf = await ctx.decodeAudioData(await file.arrayBuffer());
    return buf.duration;
  } finally {
    try { ctx.close(); } catch (_) { /* 이미 닫힘 */ }
  }
}

/** 길이를 슬라이드 수로 균등 분할한 합성 marks. */
function evenSlideMarks(durationSec, nPages) {
  const total = Math.max(0.001, Number(durationSec) || 0);
  const n = Math.max(1, Number(nPages) || 1);
  const step = total / n;
  const round3 = (v) => Math.round(v * 1000) / 1000;
  return Array.from({ length: n }, (_, i) => ({
    slide_no: i + 1,
    start_sec: round3(i * step),
    end_sec: round3(i === n - 1 ? total : (i + 1) * step),
    visit: 1,
  }));
}

function recUploadFail(message) {
  const note = $('#recUploadNote');
  if (note) {
    note.textContent = message;
    note.style.color = '#f04452';
    return;
  }
  alert(message);
}

async function useUploadedRecording(file) {
  const looksAudio = AUDIO_EXT_RE.test(file.name) || /^audio\//i.test(file.type || '');
  if (!looksAudio) {
    return recUploadFail('오디오 파일만 올릴 수 있어요. (webm · m4a · mp3 · wav · ogg)');
  }
  if (file.size > MAX_AUDIO_BYTES) {
    const mb = (file.size / 1024 / 1024).toFixed(1);
    return recUploadFail(`파일이 ${mb}MB 예요. 최대 ${MAX_AUDIO_MB}MB까지 올릴 수 있어요.`);
  }

  const note = $('#recUploadNote');
  if (note) {
    note.style.color = '';
    note.textContent = `${file.name} 길이를 읽는 중…`;
  }

  let durationSec = 0;
  try {
    durationSec = await audioDurationSec(file);
  } catch (err) {
    console.warn('[chuckchuck] audio duration', err);
  }
  if (!Number.isFinite(durationSec) || durationSec <= 0) {
    return recUploadFail('오디오 길이를 읽지 못했어요. 다른 형식(m4a·mp3·wav)으로 다시 시도해주세요.');
  }

  const nPages = rehearsalCount();
  const marks = evenSlideMarks(durationSec, nPages);

  nf.marks = marks;
  nf.sec = Math.round(durationSec);
  nf.visits = Object.fromEntries(marks.map((m) => [m.slide_no, 1]));
  nf.log = marks.map((m) => ({
    txt: `${fmt(Math.round(m.start_sec))} → ${m.slide_no}번 슬라이드 (균등 분할)`,
    re: false,
  }));
  nf.uploadedTake = { name: file.name, durationSec, syntheticMarks: true };

  ccRuntime = null;
  ccLastTake = {
    marks,
    mimeType: file.type || '',
    durationSec,
    fileName: file.name,
    _blob: file,
  };

  nf.done = 0;
  nf._pipelineStarted = false;
  nf.pipelineOut = null;
  nf.pipelineError = null;
  nf.pipelinePhase = 'queued';
  nf.pipelineDetail = `업로드한 녹음 ${file.name} · 파이프라인 대기`;
  nf.pipelineStartedAt = Date.now();
  nf._pipelineTickStarted = false;
  saveSession('new-flow', nf);

  nf.step = 3;
  renderNew();
  showF11Reveal();
}

/**
 * 벤더 오류 문자열을 사람이 읽을 한 줄로 줄인다.
 *
 * 실제로 A.X STT 게이트웨이가 막혔을 때 이런 게 통째로 화면에 나왔다:
 *   「A.X STT upload 응답을 읽지 못했어요 (HTTP 200): <html><head><title>Request
 *    Rejected</title>…Your support ID is: 2165213351621314081…」
 * 태그가 그대로 보이는 건 정직한 게 아니라 그냥 못 읽는 것이다. 원문은 검증 로그에
 * 그대로 남기고(nf.pipelineError), 화면에는 앞부분만 태그 없이 보여준다.
 */
function humanErrorText(msg) {
  const raw = String(msg == null ? '' : msg);
  const cut = raw.indexOf('<');
  const head = (cut > 20 ? raw.slice(0, cut) : raw).replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
  if (!head) return '분석에 실패했어요';
  return head.length > 110 ? `${head.slice(0, 109)}…` : head;
}

/* F-11 분석 리빌 — 리허설 종료 → 질문 준비 사이에 전체 화면으로 재생.
   뒤에서는 파이프라인이 돌고, CTA(질문 코치 시작하기)를 누르면 걷힌다.

   순서가 바뀌었다. 예전엔 graph 와 alignment 가 **둘 다** 와야 화면이 움직였고,
   그건 실 API 로 450초쯤이라 90초에 포기하는 대기 루프에 매번 걸렸다 — 개념그래프도
   산점도도 실전에서는 한 번도 안 나왔다. 이제 선분석 덕에 그래프가 발표가 끝나는 순간
   이미 있으므로, 그래프부터 먼저 넘기고(f11Graph) 정합은 도착하는 대로 얹는다(f11Data). */
function showF11Reveal() {
  if (document.getElementById('f11RevealWrap')) return;
  const wrap = document.createElement('div');
  wrap.id = 'f11RevealWrap';
  wrap.style.cssText =
    'position:fixed;inset:0;z-index:999;opacity:0;transition:opacity .45s ease';
  wrap.innerHTML =
    '<iframe src="f11_reveal.html?embed=1" title="발표 분석 과정" ' +
    'style="width:100%;height:100%;border:0;display:block"></iframe>';
  document.body.appendChild(wrap);
  requestAnimationFrame(() => { wrap.style.opacity = '1'; });

  let graphSent = false;
  const feed = setInterval(() => {
    if (!document.getElementById('f11RevealWrap')) { clearInterval(feed); return; }
    const out = nf.pipelineOut || {};
    const iframe = wrap.querySelector('iframe');
    if (!iframe || !iframe.contentWindow) return;
    const post = (msg) => iframe.contentWindow.postMessage(msg, location.origin);

    // 대기 화면이 몇 %인지 알 수 있게 매 틱 진행률을 넘긴다 (실데이터 도착 전에도)
    const phase = nf.pipelinePhase || 'queued';
    post({
      type: 'f11Progress',
      phase,
      label: pipelinePhaseLabel(phase),
      detail: nf.pipelineDetail || '',
      percent: pipelinePercent(phase, phaseElapsedSec()),
      transcriptPreview: out.transcript
        ? String(out.transcript.full_text || '').slice(0, 120)
        : '',
    });

    if (phase === 'error' || (nf.pipelineError && !out.graph)) {
      clearInterval(feed);
      post({
        type: 'f11Error',
        message: humanErrorText(nf.pipelineError || nf.pipelineDetail),
        phase,
      });
      return;
    }

    /* 그래프는 선분석이 끝나 있으면 파이프라인보다 먼저 온다. 먼저 온 걸 먼저 보여준다 —
       기다리는 화면이 아니라 이미 아는 것부터 보여주는 화면이 된다. */
    /* 선분석 그래프를 앞질러 보낼 때는 **지금 조건의 것인지** 확인한다.
       발표 정보가 바뀐 뒤의 그래프를 먼저 그려 두면, 나중에 온 정합의 node.id 가
       안 맞아서 전부 「아직 설명하지 않았어요」로 찍힌다 — 오류가 아니라
       그럴듯하게 낮은 점수로 보여서 더 나쁘다. */
    const preGraph = precompute && precompute.key === precomputeKey()
      ? (precompute.state && precompute.state.graph) || null
      : null;
    const graph = out.graph || preGraph;
    if (graph && !graphSent) {
      graphSent = true;
      post({ type: 'f11Graph', graph });
    }
    if (out.graph && out.alignment) {
      clearInterval(feed);
      post({
        type: 'f11Data',
        graph: out.graph,
        alignment: out.alignment,
        flow: out.flow || null,
        transcript: out.transcript || null,
      });
    }
  }, 500);

  const onMsg = (e) => {
    if (e.data && e.data.type === 'f11RevealDone') {
      window.removeEventListener('message', onMsg);
      wrap.style.opacity = '0';
      setTimeout(() => {
        wrap.remove();
        /* 질문 코칭은 그래프·정합·흐름만 있으면 열린다. 예전엔 phase 가 'done' 이라야
           넘어갔는데, 그건 채점·속도·습관·리포트까지 끝난 시점이라 4분을 더 세웠다. */
        if (pipelineQaReady()) location.hash = '#/qa';
      }, 450);
    }
  };
  window.addEventListener('message', onMsg);
}

function fmtMarkSec(sec) {
  const s = Math.max(0, Number(sec) || 0);
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
}

/* 단계별 진행률 구간 [시작%, 천장%].
   폭은 그 단계가 보통 잡아먹는 시간에 비례한다 (STT·개념 추출이 압도적으로 길다).
   단계 안에서는 시간에 따라 천장으로 점근할 뿐 절대 넘지 않는다 —
   막대가 멈춰 보이지 않으면서도 "다 됐다"고 거짓말하지 않는다. */
/* 구간 폭은 실측 소요 시간에 비례한다 (2026-07-30, 12장 PPTX + 3분 녹음, 실 Solar):
     STT 30초 · F-06 1분43초 · F-07 2분40초 · F-11 2분27초 · 흐름 1초 미만 = 총 7분 30초
   추측으로는 STT 를 제일 무겁게 뒀었는데 실제로는 제일 가볍다. 느린 건 F-07·F-11 이다. */
/* 이 막대가 재는 건 「질문 코칭이 열릴 때까지」다. 그래서 flow_done 이 100% 고,
   그 뒤 리포트 축(채점·속도·습관·리포트)은 전부 100 에 눕는다 — 재는 대상이 아니다.
   손으로 적은 표를 두지 않고 실측 초에서 만든다. 선분석으로 이미 끝난 단계는 폭이 0 이 되고
   남은 폭이 자동으로 넓어진다 (안 그러면 막대가 6%→74% 로 튄 뒤 2분 27초를 기어간다). */
let pipelineMarks = null;

/** 질문 코칭 뒤에 도는 단계들 — 이 막대의 관심 밖이라 100 에 눕힌다 */
const PIPELINE_AFTER_QA_PHASES = [
  'pace', 'pace_done', 'habits', 'habits_done',
  'score', 'score_done', 'score_error',
  'voice_report', 'voice_report_done', 'voice_report_error',
  'partial', 'done', 'error',
];

function buildPipelineMarks({ conceptsReady = false, graphReady = false } = {}) {
  const secs = { ...PIPELINE_STAGE_SEC_BASE };
  if (conceptsReady) secs.concepts = 0;
  if (graphReady) secs.graph = 0;
  pipelineStageSec = secs;

  const total = PIPELINE_STAGE_ORDER.reduce((s, k) => s + (secs[k] || 0), 0) || 1;
  const marks = { queued: [0, 1] };
  let run = 0;
  for (const stage of PIPELINE_STAGE_ORDER) {
    const from = Math.round((run / total) * 100);
    run += secs[stage] || 0;
    const to = Math.max(from, Math.round((run / total) * 100));
    marks[stage] = [from, to];
    marks[`${stage}_done`] = [to, to];
    marks[`${stage}_error`] = [to, to];
  }
  for (const p of PIPELINE_AFTER_QA_PHASES) marks[p] = [100, 100];
  pipelineMarks = marks;
  return marks;
}

/** 이 초 수쯤 지나면 구간 천장의 63% 지점에 닿는다. 긴 단계가 100~160초라 그에 맞춘다 */
const PIPELINE_CREEP_TAU_SEC = 70;

/**
 * 지금 단계에서 막대가 천장으로 다가가는 속도(초).
 *
 * 고정 70초는 한 단계가 100~160초일 때 맞춘 값이다. 지금 실측은 STT 30초 · F-11 6초라
 * 그대로 두면 6초짜리 단계에서 막대가 10%도 못 움직이고 다음 단계로 넘어간다 —
 * 멈춘 화면으로 보인다. 그 단계가 실제로 걸리는 시간에 비례해서 잡는다.
 */
function pipelineCreepTau(phase) {
  const stage = pipelineStageOf(phase);
  const sec = (pipelineStageSec[stage] || 0) * pipelineSpeedFactor();
  return sec > 0 ? Math.max(3, sec * 0.7) : PIPELINE_CREEP_TAU_SEC;
}

/* 단계 안에서는 시간에 따라 천장으로 점근할 뿐 절대 넘지 않는다 —
   막대가 멈춰 보이지 않으면서도 "다 됐다"고 거짓말하지 않는다. */
function pipelinePercent(phase, phaseElapsedSec) {
  const marks = pipelineMarks || buildPipelineMarks();
  const [base, ceil] = marks[phase] || marks.queued;
  if (ceil <= base) return ceil;
  const k = 1 - Math.exp(-Math.max(0, Number(phaseElapsedSec) || 0) / pipelineCreepTau(phase));
  return Math.round(Math.min(ceil, base + (ceil - base) * k));
}

/** 지금 단계가 시작된 뒤 흐른 초 */
function phaseElapsedSec() {
  const t = nf._phaseStartedAt || nf.pipelineStartedAt || Date.now();
  return Math.max(0, (Date.now() - t) / 1000);
}

/* 질문 코칭이 열리는 flow_done 까지의 단계별 실측 소요(초).
   PIPELINE_MARKS 의 구간 폭과 같은 출처다 (2026-07-30, 12장 PPTX + 3분 녹음, 실 Solar).
   그 뒤 단계(채점·속도·습관·리포트)는 리포트 화면 몫이고 실측이 없어서 여기 안 넣는다 —
   모르는 시간을 남은 시간에 더하면 그 순간부터 화면이 거짓말을 한다.
   encoding 만 브라우저 로컬이라 실측이 아니지만 3초라 오차로 남는다. */
/* 2026-08-07 실 API 실측 (12장 PDF + 5분 51초 녹음, solar-pro3 · A.X STT):
     인코딩 2초 · STT 30초 · F-06 7초 · F-07 12초 · F-11 6초 · 흐름 1초 미만 = 총 58초
   2026-07-30 값(F-06 1분43초 · F-07 2분40초 · F-11 2분27초 = 총 7분30초)과 크게 다르다.
   STT 만 그대로고 LLM 단계가 10~25배 빨라졌다 — 자료가 더 가볍고 모델도 바뀌었다.

   그래서 이 표는 **시작 추정치일 뿐**이다. 무거운 자료에서 이 값만 믿으면
   「곧 끝나요」라고 해 놓고 5분을 세우게 된다. pipelineSpeedFactor() 가 이미 끝난
   단계의 실제 소요로 남은 단계를 다시 잰다 — 표가 틀렸으면 한 단계 만에 따라잡는다. */
const PIPELINE_STAGE_SEC_BASE = {
  encoding: 2, stt: 30, concepts: 7, graph: 12, align: 6, flow: 1,
};
const PIPELINE_STAGE_ORDER = ['encoding', 'stt', 'concepts', 'graph', 'align', 'flow'];

/** 이번 실행에서 임계경로에 실제로 남아 있는 단계별 초. 선분석이 끝난 단계는 0 이 된다 */
let pipelineStageSec = { ...PIPELINE_STAGE_SEC_BASE };

/** 지금 phase 의 기본 단계 이름 (`graph_done` → `graph`) */
function pipelineStageOf(phase) {
  return String(phase || '').replace(/_(done|error)$/, '');
}

/**
 * 질문 코칭이 열릴 때까지 남은 예상 초.
 *
 * 근거는 위 실측표뿐이다. 추측한 값을 더하지 않고, 예상을 넘기면 넘겼다고 말한다 —
 * 남은 시간을 슬쩍 늘려 잡으면 그 순간부터 막대와 문구가 따로 논다.
 */
/**
 * 이번 실행이 표보다 몇 배 느린가(빠른가).
 *
 * 실측표는 특정 자료·특정 모델에서 잰 값이라, 자료가 두 배 무거우면 통째로 어긋난다.
 * 실제로 2026-07-30 과 08-07 사이에 LLM 단계가 10~25배 차이 났다. 고정 표만 믿으면
 * 「곧 끝나요」라고 해 놓고 몇 분을 세우게 된다 — 지금 화면에서 제일 하면 안 되는 짓이다.
 *
 * 그래서 이미 끝난 단계의 **실제 소요**로 남은 단계를 다시 잰다. 같은 백엔드·같은 자료라
 * 한 단계가 3배 느렸으면 다음 단계도 그쯤 느리다. 한 단계만 끝나면 바로 따라잡는다.
 * 표본이 없으면 1 (표를 그대로 믿는다). 배율은 극단으로 튀지 않게 묶는다.
 */
function pipelineSpeedFactor() {
  const actual = nf._stageActual || {};
  let got = 0;
  let want = 0;
  for (const stage of PIPELINE_STAGE_ORDER) {
    const base = PIPELINE_STAGE_SEC_BASE[stage] || 0;
    // 선분석으로 임계경로에서 빠진 단계는 표본이 아니다 — 0 초로 끝난 게 아니라 딴 데서 돌았다
    if (actual[stage] == null || base <= 0 || (pipelineStageSec[stage] || 0) <= 0) continue;
    got += actual[stage];
    want += base;
  }
  if (want <= 0) return 1;
  return Math.max(0.2, Math.min(8, got / want));
}

function pipelineEtaSec() {
  const phase = nf.pipelinePhase || 'queued';
  if (['done', 'partial', 'error'].includes(phase)) return 0;
  const stage = pipelineStageOf(phase);
  const settled = /_(done|error)$/.test(phase);
  const factor = pipelineSpeedFactor();
  let i = PIPELINE_STAGE_ORDER.indexOf(stage);
  if (i < 0) i = 0;                       // queued — 처음부터 다 남았다
  let remain = 0;
  for (let k = settled ? i + 1 : i; k < PIPELINE_STAGE_ORDER.length; k++) {
    remain += (pipelineStageSec[PIPELINE_STAGE_ORDER[k]] || 0) * factor;
  }
  if (!settled) remain -= Math.min((pipelineStageSec[stage] || 0) * factor, phaseElapsedSec());
  return Math.round(remain);
}

/** 지금 단계가 예상 시간을 넘겼나. 넘겼으면 남은 시간을 말할 자격이 없다 */
function pipelineStageOverrun() {
  const phase = nf.pipelinePhase || 'queued';
  if (/_(done|error)$/.test(phase)) return false;
  const stage = pipelineStageOf(phase);
  const budget = (pipelineStageSec[stage] || 0) * pipelineSpeedFactor();
  return budget > 0 && phaseElapsedSec() > budget;
}

function pipelineEtaText() {
  const phase = nf.pipelinePhase || 'queued';
  if (phase === 'done') return '분석을 마쳤어요';
  if (phase === 'partial') return '일부 단계를 건너뛰고 끝냈어요';
  if (phase === 'error') return '중간에 멈췄어요';
  /* 이 단계가 예상을 넘겼으면 남은 시간을 말하지 않는다. 뒤 단계 몫만 남아서
     「곧 끝나요」가 나오는데, 정작 지금 단계가 언제 끝날지는 모르는 상태다 —
     그 상태에서 곧 끝난다고 하면 5분을 더 세워 놓고 거짓말한 게 된다. */
  if (pipelineStageOverrun()) return '예상보다 오래 걸리고 있어요';
  const sec = pipelineEtaSec();
  if (sec <= 0) return '예상보다 오래 걸리고 있어요';
  if (sec < 45) return '곧 끝나요';
  const min = Math.round(sec / 60);
  return min <= 1 ? '남은 예상 1분쯤' : `남은 예상 ${min}분쯤`;
}

/**
 * 파이프라인 상태 줄 — phase 와 상관없이 **항상** 떠 있다.
 *
 * pipelineLoadingHtml 은 특정 phase 에서만 나와서, 제일 긴 F-07·F-11 구간(합쳐 5분)에
 * 화면에서 통째로 사라졌다. 그동안 움직이는 게 하나도 없으니 멈춘 화면으로 읽힌다.
 * 진행률·단계 이름·경과 초는 연출과 무관하게 남긴다 (UI_REDESIGN §14 정직한 상태 유지).
 */
function pipelineStatusBarHtml() {
  const phase = nf.pipelinePhase || 'queued';
  const pct = pipelinePercent(phase, phaseElapsedSec());
  const started = nf.pipelineStartedAt || Date.now();
  const elapsed = Math.max(0, Math.floor((Date.now() - started) / 1000));
  const final = ['done', 'partial', 'error'].includes(phase);
  return `<div class="pipe-status-bar${final ? ' is-final' : ''}">
    <div class="psb-head">
      <span class="pipe-phase">${escapeHtml(pipelinePhaseLabel(phase))}</span>
      <b class="psb-pct">${pct}%</b>
    </div>
    <div class="progress"><i style="width:${pct}%"></i></div>
    <p class="psb-meta">
      경과 <b class="pipe-elapsed">${elapsed}</b>초 · <span class="psb-eta">${escapeHtml(pipelineEtaText())}</span>
    </p>
  </div>`;
}

/** 1초 틱이 상태 줄을 다시 그리지 않고 숫자만 갈아끼운다 (전체 렌더는 보던 화면을 날린다) */
function paintPipelineStatusBar() {
  const host = $('.pipe-status-bar');
  if (!host) return;
  const phase = nf.pipelinePhase || 'queued';
  const pct = pipelinePercent(phase, phaseElapsedSec());
  const label = host.querySelector('.pipe-phase');
  const pctEl = host.querySelector('.psb-pct');
  const fill = host.querySelector('.progress i');
  const eta = host.querySelector('.psb-eta');
  if (label) label.textContent = pipelinePhaseLabel(phase);
  if (pctEl) pctEl.textContent = `${pct}%`;
  if (fill) fill.style.width = `${pct}%`;
  if (eta) eta.textContent = pipelineEtaText();
  host.classList.toggle('is-final', ['done', 'partial', 'error'].includes(phase));
}

function pipelinePhaseLabel(phase) {
  const map = {
    /* 사람이 알아보는 말로 쓴다. 「F-05 STT 변환」은 우리 모듈 이름이지
       기다리는 사람이 아는 말이 아니다 — 토스 UX 라이팅(해요체·능동형).
       phase 키는 그대로 둔다. chuckchuck_bridge.js 의 report() 계약이다. */
    queued: '차례를 기다리고 있어요',
    encoding: '녹음을 정리하고 있어요',
    stt: '말한 내용을 글로 옮기고 있어요',
    stt_done: '말한 내용을 다 옮겼어요',
    concepts: '발표자료에서 핵심 개념을 찾고 있어요',
    concepts_done: '핵심 개념을 찾았어요',
    concepts_error: '핵심 개념을 찾지 못했어요',
    graph: '개념끼리 어떻게 이어지는지 보고 있어요',
    graph_done: '개념 사이 연결을 정리했어요',
    align: '자료와 실제 발표를 하나씩 대조하고 있어요',
    align_done: '자료와 발표 대조를 마쳤어요',
    align_error: '자료와 발표를 대조하지 못했어요',
    score: '점수를 매기고 있어요',
    score_done: '점수를 매겼어요',
    score_error: '점수를 매기지 못했어요',
    flow: '자료의 흐름과 말한 순서를 맞춰보고 있어요',
    flow_done: '흐름 비교를 마쳤어요',
    flow_error: '흐름을 비교하지 못했어요',
    pace: '말 속도와 시간 배분을 재고 있어요',
    pace_done: '시간 배분을 다 쟀어요',
    habits: '말버릇을 찾고 있어요',
    habits_done: '말버릇을 다 찾았어요',
    voice_report: '결과를 하나로 묶고 있어요',
    voice_report_done: '리포트를 다 썼어요',
    voice_report_error: '리포트를 쓰지 못했어요',
    partial: '일부만 끝났어요',
    done: '다 끝났어요',
    error: '중간에 멈췄어요',
  };
  return map[phase] || '진행 중';
}

/**
 * 체크리스트 항목 — 각 줄이 자기 산출물을 직접 보고 상태를 정한다.
 *
 * phase 로 세던 옛 방식은 `concepts_done` 에서 4개를 한꺼번에 ✓ 로 바꿨다. 그 시점에
 * F-11 정합은 시작도 안 했고 질문(F-08)은 이 파이프라인에서 돌지도 않는다 —
 * 다 됐다고 표시해 놓고 5분 동안 버튼이 안 생기니, 오지 않을 결과를 기다리게 된다.
 *
 * 산출물 기준으로 세면 선분석(녹음 중 F-06·F-07)처럼 순서가 뒤바뀌어 끝나도 정직하게 찍힌다.
 */
function pipelineChecklistItems() {
  const out = nf.pipelineOut || {};
  const t = out.transcript && !out.transcript.error ? out.transcript : null;
  return [
    { text: '말한 내용을 글로 옮겼어요', stage: 'stt', ok: !!t },
    {
      text: '슬라이드별로 발화를 나눴어요',
      stage: 'stt',
      ok: !!(t && Array.isArray(t.by_slide) && t.by_slide.length),
    },
    {
      text: '자료에서 핵심 개념을 찾았어요',
      stage: 'concepts',
      ok: !!(out.concepts && !out.concepts.error && !out.conceptsError),
    },
    { text: '개념끼리 어떻게 이어지는지 정리했어요', stage: 'graph', ok: !!out.graph },
    { text: '자료와 발표를 하나씩 대조했어요', stage: 'align', ok: !!out.alignment },
  ];
}

/** 실제로 끝난 항목 수 (0..5) */
function pipelineChecklistDone() {
  return pipelineChecklistItems().filter((i) => i.ok).length;
}

/**
 * 질문 코칭에 필요한 게 다 모였나 — 그래프·정합·흐름 셋뿐이다.
 *
 * F-08 질문 생성이 쓰는 입력이 정확히 이것이다. 채점(F-14)·속도(F-17)·습관(F-18)·
 * 리포트(F-19)는 리포트 화면 몫인데, 지금은 그것까지 다 기다리느라 4분을 더 세운다.
 */
function pipelineQaReady() {
  const out = nf.pipelineOut || {};
  return !!(out.graph && out.alignment && out.flow);
}

function pipelineLoadingHtml(kind) {
  const phase = nf.pipelinePhase || 'queued';
  const detail = nf.pipelineDetail || '';

  if (kind === 'stt') {
    if (['stt_done', 'concepts', 'concepts_done', 'concepts_error', 'done', 'error'].includes(phase)) return '';
  }
  if (kind === 'concepts') {
    if (!['stt_done', 'concepts'].includes(phase)) return '';
  }

  /* 진행률·단계 이름·경과 초는 위 pipeline-status-bar 가 항상 들고 있다.
     여기서 또 그리면 같은 숫자가 두 벌 돌아다니고, 그러다 한쪽만 멈추면 어느 쪽이 참인지 모른다.
     이 블록은 그 단계가 무엇을 기다리는지만 한 줄로 말한다.
     캐릭터는 얹는 층이다 (UI_REDESIGN §14 · 03_components.md §6). */
  const hint = kind === 'stt'
    ? '말한 내용을 글로 옮기는 데 30초쯤 걸려요. 이 화면을 닫아도 뒤에서 계속 돌아갑니다.'
    : '자료의 개념을 정리하는 중이에요. 발표하는 동안 미리 돌려 뒀으면 금방 끝나요.';

  return `<div class="pipe-loading" data-pipe-kind="${kind}">
    <div class="pipe-bird-row">
      ${emptyBirdHtml('ax', 'neutral')}
      <span class="pipe-bird-line">발표를 듣고 있어요…</span>
    </div>
    <p class="parse-meta">
      ${detail ? `<span class="pipe-detail">${escapeHtml(detail)}</span><br>` : ''}
      ${hint}
    </p>
  </div>`;
}

/* ─── 막간: 커튼 뒤의 소곤소곤 (UI_REDESIGN §5) ─────────────────────────────
   "언제 끝나지" 를 "쟤들이 내 얘기를 하고 있다" 로 바꾼다.

   철칙: 한 마디도 지어내지 않는다. 여기 나오는 숫자는 전부 그 단계가 실제로
   돌려준 값이다 — 실측값이 없으면 그 병아리는 그냥 입을 열지 않는다.
   진행률·단계 이름·경과 초는 아래에 그대로 남는다 (§14 정직한 상태 유지). */

const BACKSTAGE_NAMES = {
  midm: '믿:음', solar: '쏠라', exaone: '엑사원', ax: '엑씨', all: '넷이 동시에',
};

function backstageLine(phase) {
  const out = nf.pipelineOut || {};
  if (phase === 'stt_done') {
    const sec = out.transcript && out.transcript.duration_sec;
    // 길이를 못 받았으면 말하지 않는다. 엑씨의 대사는 실측이 전부다
    return sec ? { who: 'ax', text: `${fmtMarkSec(sec)}, 한마디도 안 놓쳤어` } : null;
  }
  if (phase === 'concepts_done') {
    const n = out.concepts && (out.concepts.slides || []).length;
    return n ? { who: 'solar', text: `${n}장, 다 읽었어` } : null;
  }
  if (phase === 'graph_done') {
    const n = out.graph && (out.graph.nodes || []).length;
    return n ? { who: 'solar', text: `개념 ${n}개 정리 끝!` } : null;
  }
  if (phase === 'align_done') {
    return { who: 'midm', text: '어? 잠깐, 이거…' };
  }
  if (phase === 'score_done') {
    return { who: 'all', text: '쉿—! 온다!' };
  }
  return null;
}

function backstageLineHtml(line) {
  return `<li class="bs-line" data-who="${escapeHtml(line.who)}">`
    + `<b>${escapeHtml(BACKSTAGE_NAMES[line.who] || line.who)}</b>`
    + `<span>${escapeHtml(line.text)}</span></li>`;
}

/**
 * 단계 완료 신호 하나를 커튼 틈으로 흘려보낸다.
 *
 * nf 에 쌓아 두는 이유: 파이프라인이 7분 도는 동안 화면이 여러 번 다시 그려지는데,
 * DOM 에만 넣으면 그때마다 지금까지의 대화가 통째로 사라진다.
 */
function pushBackstage(phase) {
  const line = backstageLine(phase);
  if (!line) return;
  if (!Array.isArray(nf.backstage)) nf.backstage = [];
  if (nf.backstage.some((l) => l.phase === phase)) return;   // 같은 단계는 한 번만
  nf.backstage.push({ ...line, phase });

  const host = $('#bsLines');
  if (!host) return;
  const murmur = host.querySelector('.bs-murmur');
  if (murmur) murmur.remove();
  host.insertAdjacentHTML('beforeend', backstageLineHtml(line));
}

function backstageHtml() {
  const lines = Array.isArray(nf.backstage) ? nf.backstage : [];
  const body = lines.length
    ? lines.map(backstageLineHtml).join('')
    : '<li class="bs-murmur" aria-label="객석이 웅성거리는 중"><i></i><i></i><i></i></li>';
  return `
    <div class="bs-stage">
      <div class="bs-curtain" aria-hidden="true"><i></i><i></i></div>
      <p class="bs-hint">막이 내려왔어요. 커튼 뒤에서 뭔가 상의하는 소리가 들립니다.</p>
      <ul class="bs-lines" id="bsLines">${body}</ul>
    </div>`;
}

function pipelineInspectHtml() {
  const marks = (ccLastTake && ccLastTake.marks) || nf.marks || [];
  const chuck = (window.ChuckchuckBridge && ChuckchuckBridge.loadChuckSession()) || {};
  const transcript = (nf.pipelineOut && nf.pipelineOut.transcript) || chuck.transcript || null;
  const concepts = (nf.pipelineOut && nf.pipelineOut.concepts) || chuck.concepts || null;
  const conceptsError = (nf.pipelineOut && nf.pipelineOut.conceptsError)
    || chuck.conceptsError
    || null;
  const phase = nf.pipelinePhase || 'queued';

  // 업로드본은 전환 기록이 없어 marks 를 합성했다. 측정값처럼 읽히면 안 된다.
  // 전환 기록 표 자체는 뺐지만(사용자 지시), 합성값이라는 사실은 계속 알려야 한다 —
  // 아래 슬라이드↔발화 매핑이 그 합성 marks 위에 서 있기 때문이다.
  const up = nf.uploadedTake;
  const uploadedNote = up
    ? `<p class="note" style="color:#f59e0b">업로드한 녹음 <b>${escapeHtml(up.name)}</b>
       (${fmtMarkSec(up.durationSec)})으로 돌렸어요. 슬라이드 구간은 <b>실제 전환 기록이 아니라
       길이를 ${marks.length}등분한 합성값</b>이라, 슬라이드별 발화 분할과 정합 판정은
       참고용으로만 보세요.</p>`
    : '';

  let speechHtml = '';
  if (transcript && transcript.error) {
    speechHtml = `<p class="note" style="color:#f04452">${escapeHtml(transcript.message || transcript.error)}</p>`;
  } else if (transcript && (Array.isArray(transcript.by_slide) || transcript.full_text)) {
    const slides = Array.isArray(transcript.by_slide) ? transcript.by_slide : [];
    if (slides.length) {
      speechHtml = pipeSpeechMapHtml(slides);
    } else {
      speechHtml = '<p class="note">슬라이드 구간(marks)이 없어 by_slide 가 비어 있어요. 아래 전체 전사문을 확인하세요.</p>';
    }
    if (transcript.full_text) {
      speechHtml += `<details class="pipe-full"><summary>전체 전사문만 보기 (${(transcript.words || []).length}단어)</summary><p>${escapeHtml(transcript.full_text)}</p></details>`;
    }
  } else if (phase === 'error' && nf.pipelineError) {
    speechHtml = `<p class="note" style="color:#f04452">받아쓰기까지 도달하지 못했어요: ${escapeHtml(nf.pipelineError)}</p>`;
  } else {
    speechHtml = pipelineLoadingHtml('stt') || '<p class="note">받아쓴 내용을 기다리는 중…</p>';
  }

  let conceptHtml = '';
  if (concepts && !concepts.error && Array.isArray(concepts.slides)) {
    conceptHtml = `<details class="pipe-block" open><summary>개념 추출 (${concepts.slides.length}장)</summary>
      <ul class="pipe-concepts">${concepts.slides.slice(0, 12).map((s) =>
        `<li><b>${s.slide_no}.</b> ${escapeHtml(s.topic || s.title || '')}
         <span>${escapeHtml((s.concepts || []).slice(0, 3).join(' · '))}</span></li>`
      ).join('')}</ul></details>`;
  } else if (conceptsError) {
    conceptHtml = `<details class="pipe-block" open><summary>개념 추출 (실패)</summary>
      <p class="note" style="color:#f04452">${escapeHtml(conceptsError)}</p>
      <p class="note">받아쓴 내용은 위에 그대로 남아 있어요.</p>
    </details>`;
  } else if (nfSlideDoc || ['stt_done', 'concepts', 'queued', 'encoding', 'stt'].includes(phase)) {
    const loading = pipelineLoadingHtml('concepts');
    if (loading || ['stt_done', 'concepts'].includes(phase)) {
      conceptHtml = `<details class="pipe-block" open><summary>개념 추출</summary>${loading || '<p class="note">받아쓰기 이후 개념 추출을 시작해요.</p>'}</details>`;
    }
  }

  const statusChip = (nf.pipelineError && !transcript)
    ? `<span class="pipe-status err">실패</span>`
    : (conceptsError
      ? `<span class="pipe-status err">부분 완료</span>`
      : (phase === 'done'
        ? `<span class="pipe-status ok">완료</span>`
        : `<span class="pipe-status run">${escapeHtml(pipelinePhaseLabel(phase))}</span>`));

  return `
    <div class="pipe-inspect">
      <h4 class="pipe-h">검증 로그 ${statusChip}</h4>
      <p class="note">발표한 말이 슬라이드별로 제대로 나뉘었는지 여기서 확인하세요.</p>
      ${uploadedNote}
      <details class="pipe-block" open>
        <summary>슬라이드 ↔ 발화 매핑 (${(transcript && Array.isArray(transcript.by_slide)) ? transcript.by_slide.length : 0}구간)</summary>
        ${speechHtml}
      </details>
      ${conceptHtml}
    </div>`;
}

/* 스텝 4 — 발표자료 + STT로 질문 준비 */
function refreshPipelineInspect() {
  const host = $('.pipe-inspect');
  if (!host) return;
  const tmp = document.createElement('div');
  tmp.innerHTML = pipelineInspectHtml();
  const next = tmp.firstElementChild;
  if (next) host.replaceWith(next);
  paintPipeMapThumbs();
}

/* 1초마다 상태 줄을 갈아끼운다. 단계가 안 바뀌어도 막대·경과 초·남은 시간은 움직여야 한다 —
   F-07·F-11 은 한 단계가 2분 30초라, 단계 전환 때만 그리면 화면이 멈춘 걸로 보인다.
   concepts_error 는 끝이 아니다. 개념 추출이 실패해도 그래프·정합은 계속 돈다 —
   여기서 시계를 멈추면 남은 5분 동안 경과 초가 얼어붙는다. */
function startPipelineElapsedTimer() {
  if (nf._pipelineTickStarted) return;
  nf._pipelineTickStarted = true;
  every(() => {
    if (!nf.pipelineStartedAt || ['done', 'partial', 'error'].includes(nf.pipelinePhase)) {
      return;
    }
    const elapsed = Math.max(0, Math.floor((Date.now() - nf.pipelineStartedAt) / 1000));
    $$('.pipe-elapsed').forEach((el) => { el.textContent = String(elapsed); });
    paintPipelineStatusBar();
  }, 1000);
}

/**
 * 파이프라인이 끝났을 때만 스텝 4 를 다시 그린다.
 *
 * 실 LLM 파이프라인은 7분도 걸린다. 그 사이 사용자가 리포트나 질문코치로 넘어가
 * 있으면, 완료 콜백이 app.innerHTML 을 덮어써 보던 화면을 통째로 날려버린다.
 */
function refreshStep4IfVisible() {
  const onNewFlow = /^#\/?(new)?(\/|$)/.test(location.hash || '#/');
  if (onNewFlow && nf.step === 3) nfStep4();
}

function nfStep4() {
  app.className = 'narrow';
  const items = pipelineChecklistItems();
  const stage = pipelineStageOf(nf.pipelinePhase || 'queued');
  const doneN = items.filter((i) => i.ok).length;
  nf.done = doneN;
  const conceptsError = (nf.pipelineOut && nf.pipelineOut.conceptsError) || null;
  const pipeErr = conceptsError
    ? stageAccidentHtml(`개념 추출 실패 (받아쓰기는 성공): ${conceptsError}`)
    : (nf.pipelineError
      ? stageAccidentHtml(`연동 오류: ${humanErrorText(nf.pipelineError)}`)
      : '');
  /* 질문 코칭은 그래프·정합·흐름만 있으면 열린다. 리포트 축(채점·속도·습관·리포트)이
     아직 도는 중이면 그 사실을 숨기지 않고 한 줄 남긴다 — "다 끝났어요" 라고만 하면
     리포트 화면에서 왜 비어 있는지 알 수 없다. */
  const qaReady = pipelineQaReady();
  const reportPending = qaReady && !['done', 'partial', 'error'].includes(nf.pipelinePhase || '');
  app.innerHTML = `${nfSteps()}
    <div class="card">
      <h3 class="section-title">${qaReady ? '질문 준비가 끝났어요' : '발표를 듣고 질문을 준비하고 있어요'}</h3>
      <p class="note" style="margin-bottom:14px">최종 분석 전에, 설명이 비어 있던 개념을 질문으로 함께 확인해요.</p>
      ${pipelineStatusBarHtml()}
      ${backstageHtml()}
      ${pipeErr}
      <ul class="checklist">
        ${items.map((it, i) => {
          const st = it.ok ? 'done' : (it.stage === stage ? 'doing' : 'todo');
          return `<li class="${st}"><i>${it.ok ? '✓' : i + 1}</i>${it.text}</li>`;
        }).join('')}
      </ul>
      ${pipelineInspectHtml()}
      <div class="step-actions">
        <button class="btn btn-secondary" type="button" data-fresh-practice>처음부터 다시</button>
        <button class="btn btn-secondary btn-sm" type="button" id="againTake">다른 녹음으로 다시</button>
        <a class="btn btn-text btn-sm skip-qa" href="#/report">질문코치 건너뛰고 상세 리포트</a>
        ${qaReady
          ? `<a class="btn btn-primary" href="#/qa">질문 코칭 시작하기</a>
             ${reportPending ? '<span class="note">상세 리포트는 뒤에서 마저 만들고 있어요.</span>' : ''}`
          : (nf.transcriptOk && conceptsError
            ? `<span class="note">말한 내용까지는 옮겼어요. 개념 추출만 실패했습니다.</span>`
            : '')}
      </div>
    </div>`;
  wireFreshPracticeButtons(app);
  startPipelineElapsedTimer();
  paintPipeMapThumbs();

  const again = $('#againTake');
  // 자료(nfSlideDoc·uploadedPdf)는 그대로 두고 테이크만 버린다 — resetNf 와 다르다
  if (again) again.addEventListener('click', () => {
    ccRuntime = null;
    ccLastTake = null;
    chatterCache = null;
  chatterPending = null;
    nf.mic = 'idle';
    nf.sec = 0;
    nf.marks = null;
    nf.uploadedTake = null;
    nf.log = [];
    nf.visits = { 1: 1 };
    nf.done = 0;
    nf._pipelineStarted = false;
    nf.pipelineOut = null;
    nf.pipelineError = null;
    nf.pipelinePhase = null;
    nf.pipelineDetail = null;
    nf.transcriptOk = false;
    nf.conceptsOk = false;
    nf.backstage = [];
    nf.step = 2;
    // 질문 코칭은 버리는 테이크의 발화로 만든 것이라 같이 버린다 — 남겨 두면
    // 새 녹음 분석이 끝나도 qaLiveActive() 가 참이라 지난 녹음의 질문이 그대로 나온다.
    resetQa();
    saveSession('new-flow', nf);
    renderNew();
  });

  if (ccLastTake && window.ChuckchuckBridge && !nf._pipelineStarted) {
    nf._pipelineStarted = true;
    nf.pipelineError = null;
    nf.pipelinePhase = 'queued';
    nf.pipelineDetail = '파이프라인 시작';
    nf.pipelineStartedAt = Date.now();
    nf._stageActual = null;   // 지난 테이크의 실측이 남아 있으면 이번 추정이 그걸 따라간다
    nf.transcriptOk = false;
    nf.conceptsOk = false;

    /* 진행률 표는 여기서 한 번만 만든다. 발표하는 동안 F-06·F-07 이 이미 끝났으면
       그 구간은 폭이 0 이 되고 남은 폭이 넓어진다. 중간에 다시 만들면 막대가 뒤로 간다 —
       한 번 지나온 %가 줄어드는 건 진행률이 아니라 소음이다. */
    const preState = (precompute && precompute.key === precomputeKey() && precompute.state) || {};
    buildPipelineMarks(preState);
    refreshPipelineInspect();

    // slideDoc 이 없으면 F-06 이후가 통째로 안 돈다. 캐시에서 먼저 되살린다.
    ensureSlideDoc().then((slideDoc) => window.ChuckchuckBridge.runPreparePipeline({
      marks: ccLastTake.marks,
      blob: ccLastTake._blob,
      mimeType: ccLastTake.mimeType,
      fileName: ccLastTake.fileName || '',
      slideDoc,
      precomputed: precomputeHandles(),
      context: {
        situation: nf.occ || '',
        audience: nf.ctx || '',
        duration_min: nf.min,
      },
      onProgress: ({ phase, detail, transcript, concepts, conceptsError: cErr, graph, alignment, flow, pace, habits, voiceReport, score }) => {
        if (phase !== nf.pipelinePhase) {
          /* 단계가 끝난 순간 그 단계가 실제로 몇 초 걸렸는지 적어 둔다.
             표가 틀렸을 때 남은 시간을 다시 재는 유일한 근거다 (pipelineSpeedFactor). */
          const prev = pipelineStageOf(nf.pipelinePhase || '');
          if (prev && PIPELINE_STAGE_ORDER.includes(prev) && !/_(done|error)$/.test(nf.pipelinePhase || '')) {
            nf._stageActual = { ...(nf._stageActual || {}), [prev]: phaseElapsedSec() };
          }
          nf._phaseStartedAt = Date.now();
        }
        nf.pipelinePhase = phase;
        nf.pipelineDetail = detail || '';
        if (transcript || concepts || cErr || graph || alignment || flow || pace || habits || voiceReport || score) {
          nf.pipelineOut = {
            ...(nf.pipelineOut || {}),
            ...(transcript ? { transcript } : {}),
            ...(concepts ? { concepts } : {}),
            ...(cErr ? { conceptsError: cErr } : {}),
            ...(graph ? { graph } : {}),
            ...(alignment ? { alignment } : {}),
            ...(flow ? { flow } : {}),
            ...(pace ? { pace } : {}),
            ...(habits ? { habits } : {}),
            ...(voiceReport ? { report: voiceReport } : {}),
            ...(score ? { score } : {}),
          };
        }
        if (transcript && !transcript.error) nf.transcriptOk = true;
        // 커튼 틈으로 한 마디. pipelineOut 을 갱신한 뒤라야 실측값이 들어 있다
        pushBackstage(phase);
        /* 산출물이 하나 늘어난 순간에만 전체를 다시 그린다 — 체크리스트 한 줄이 켜지고,
           flow_done 에서는 「질문 코칭 시작하기」가 열린다. 나머지 틱은 검증 로그만 갈아끼운다
           (7분짜리 파이프라인이라 매번 전체를 그리면 보던 화면이 계속 튄다). */
        const RERENDER_PHASES = [
          'stt_done', 'concepts_done', 'concepts_error',
          'graph_done', 'align_done', 'align_error', 'flow_done',
        ];
        if (RERENDER_PHASES.includes(phase)) {
          nf.done = pipelineChecklistDone();
          refreshStep4IfVisible();
        } else {
          refreshPipelineInspect();
          paintPipelineStatusBar();
        }
      },
    })).then((out) => {
      nf.pipelineOut = out;
      // 중간 단계가 죽었으면 '완료' 라고 하면 안 된다 — 오지 않을 결과를 기다리게 된다
      const failed = out && out.failedStage;
      nf.pipelinePhase = failed ? 'partial' : 'done';
      nf.pipelineDetail = failed
        ? `${out.failedStage} 실패`
        : (out && out.conceptsError ? out.conceptsError : '준비 완료');
      nf.transcriptOk = !!(out && out.transcript && !out.transcript.error);
      nf.conceptsOk = !!(out && out.concepts && !out.concepts.error && !out.conceptsError);
      if (out && out.conceptsError) {
        nf.pipelineError = null; // STT 성공분 유지 — 상단은 conceptsError 로 표시
      }
      console.info('[chuckchuck] pipeline ok', out);
      // 발표가 끝난 이 순간부터 객석 수다를 받아 둔다. 질문 코칭 내용은 섞지
      // 않는다 — 수다는 F-07/F-11 결과만 보고 만들어지므로 여기서 확정된다.
      // 사람이 질문 준비를 보고 리포트를 넘기는 동안 채워져, 「객석 들어가기」가
      // 곧바로 열린다 (예전엔 누른 뒤에 받기 시작해 실측 74초를 서 있었다)
      prefetchChatter();
      recordShow();
      nf.done = pipelineChecklistDone();
      refreshStep4IfVisible();
    }).catch((err) => {
      console.warn('[chuckchuck] prepare pipeline', err);
      nf.pipelineError = err.message || String(err);
      nf.pipelinePhase = 'error';
      nf.pipelineDetail = nf.pipelineError;
      // 부분 결과가 있으면 유지
      nf.done = pipelineChecklistDone();
      refreshStep4IfVisible();
    });
  }
}

/* ══ 리포트 ══ */

/** 업로드·실연동 세션이면 true. 샘플 IMU2CLIP 데모와 구분한다. */
function isLiveReportSession() {
  if (!nf) return false;
  if (nf.useSample) return false;
  if (nf.fileName) return true;
  if (nf.pipelineOut) return true;
  if (nf.pipelinePhase || nf.pipelineError) return true;
  if (nf.slideDocMeta && nf.slideDocMeta.file_name) return true;
  return false;
}

/** 리포트 헤더용 메타 — 실제 올린 자료/파이프라인 기준. 샘플 DATA.session 은 데모 전용. */
function reportSessionMeta() {
  const sample = DATA.session;
  const out = nf && nf.pipelineOut;
  const graph = out && out.graph;
  const live = isLiveReportSession();
  if (!live) {
    return {
      live: false,
      title: sample.title,
      occasion: sample.occasion,
      slides: sample.slides,
      duration: sample.duration,
      nth: sample.nth,
    };
  }
  const fileName = (graph && graph.file_name)
    || (nf.slideDocMeta && nf.slideDocMeta.file_name)
    || nf.fileName
    || '내 발표자료';
  // 확장자 뗀 이름을 제목으로
  const title = String(fileName).replace(/\.(pdf|pptx|ppt|key)$/i, '').trim() || fileName;
  const slides = (graph && graph.total_slides)
    || (nf.slideDocMeta && nf.slideDocMeta.total_slides)
    || (typeof rehearsalCount === 'function' ? rehearsalCount() : 0)
    || (nf.slideTitles && nf.slideTitles.length)
    || 0;
  const durSec = (out && out.transcript && out.transcript.duration_sec)
    || (typeof ccLastTake !== 'undefined' && ccLastTake && ccLastTake.durationSec)
    || nf.sec
    || 0;
  const duration = durSec
    ? (durSec >= 60
      ? `${Math.floor(durSec / 60)}분 ${Math.round(durSec % 60)}초`
      : `${Math.round(durSec)}초`)
    : (nf.min ? `목표 ${nf.min}분` : '—');
  return {
    live: true,
    title,
    occasion: nf.occ || '발표 연습',
    slides,
    duration,
    nth: 1,
  };
}

let rTab = 0, jSel = 'contrast', jFilter = 'all', toolSeg = 0, mapWeakOnly = false, repSlide = 7;

/**
 * 판정 헤드에 필요한 값만 모은다.
 *
 * 점수·차원·한 줄 판단은 원래 rSummary() 안에 있었는데, 판정은 탭이 바뀌어도
 * 유지돼야 하는 세션의 결론이라 헤드로 끌어올렸다. 계산 자체는 기존
 * realSummary()·realTrophy() 를 그대로 쓰고 여기서는 조합만 한다.
 */
function reportVerdict() {
  const live = isLiveReportSession();
  const real = realSummary();
  const tree = judgeTree();
  const isRealTree = !!(tree[0] && tree[0].real);
  const s = DATA.session;

  // 올린 자료인데 분석이 없으면 샘플 점수를 헤드에 띄우지 않는다
  if (live && !real && !isRealTree) return { hasAnalysis: false, isSample: false };

  if (real) {
    return {
      hasAnalysis: true, isSample: false,
      score: real.score,
      dims: real.dims,
      mood: real.mood,
      /* 큰 글씨는 한 줄이다. 예전엔 안내 문구를 전부 ' · ' 로 이어 붙여
         22px 굵은 글씨로 3~4줄을 쌓았다 — 결과 화면에서 가장 먼저 읽는 자리에
         가장 안 중요한 말이 가장 크게 있었다. 판단은 헤드, 단서는 아래 작은 줄. */
      headline: real.score >= 90 ? '아주 잘 전달했어요'
        : real.score >= 75 ? '핵심은 잘 전달됐어요'
          : real.score >= 60 ? '전달은 됐고, 보완할 곳이 보여요'
            : '다음 발표에서 더 좋아질 수 있어요',
      subnotes: real.notes,
      // 어느 기준으로 매겼는지 숨기지 않는다. 폴백이면 폴백이라고 쓴다
      delta: `<span class="prev num">${
        real.isFallback ? '예전 방식' : '채점표 v3'
      } · ${escapeHtml(real.situationLabel || real.basis)}</span>`,
    };
  }
  const diff = s.score - s.prevScore;
  return {
    hasAnalysis: true, isSample: true,
    mood: s.score >= 90 ? 'excited' : s.score >= 75 ? 'happy' : 'neutral',
    score: s.score,
    dims: s.dims,
    headline: s.oneLiner,
    delta: `<span class="delta num">▲ ${diff}</span><span class="prev num">지난 연습 ${s.prevScore}점</span>`,
  };
}

/**
 * ③ 장식이 아니라 데이터가 배경이다.
 * 판정 헤드 바닥에 발화 파형과 슬라이드 전환 시각을 깐다.
 * 매 로드 같은 모양이 나오도록 결정적으로 생성한다.
 */
function paintVerdictBg() {
  const bg = $('#verdictBg');
  if (!bg || bg.childElementCount) return;
  for (let i = 0; i < 150; i++) {
    const b = document.createElement('i');
    b.style.height = (12 + Math.abs(Math.sin(i * .37) * Math.cos(i * .11)) * 88).toFixed(1) + '%';
    bg.appendChild(b);
  }
  // 전환 시각을 따로 갖고 있지 않으므로 장수에 맞춰 균등하게 나눈다
  const total = Math.min(rehearsalCount() || DATA.session.slides || 0, 14);
  for (let n = 1; n < total; n++) {
    const m = document.createElement('b');
    m.style.left = (n / total * 100).toFixed(2) + '%';
    bg.appendChild(m);
  }
}

async function renderReport() {
  await ensureVoicePipelineOut();
  const reportId = location.hash.replace(/^#\/?/, '').split('/')[1] || 'imu2clip';
  if (reportId !== 'imu2clip' && DATA.reportProfiles[reportId]) {
    renderProfileReport(DATA.reportProfiles[reportId]);
    return;
  }
  app.className = 'wide';
  // 객석 수다는 70초쯤 걸린다. 여기서부터 받아 두면 요약·판정을 보는 동안 채워진다
  prefetchChatter();
  const s = reportSessionMeta();
  const v = reportVerdict();
  const tabs = ['요약', '채점표', '개념별 판정', '논리 흐름', '음성 습관', '청중 반응', '연습 도구'];
  const meta = [
    escapeHtml(s.occasion),
    s.slides ? `${s.slides}장` : '',
    escapeHtml(s.duration),
    s.live ? '' : `${s.nth}번째 연습`,
  ].filter(Boolean);
  app.innerHTML = `
    <section class="verdict${v.hasAnalysis ? '' : ' is-plain'}">
      <div class="verdict-bg" id="verdictBg" aria-hidden="true"></div>
      <div class="verdict-inner">
        <p class="verdict-meta">${meta.map(m => `<span>${m}</span>`).join('<i></i>')}</p>
        <h1 class="verdict-title">${escapeHtml(s.title)}</h1>
        ${v.hasAnalysis ? `
        <div class="verdict-grid">
          <div class="verdict-score">
            <span class="vs-label">발표 완성도</span>
            <div class="vs-body">
              <div class="vs-num">
                <strong class="num">${v.score}<span class="of">/100</span></strong>
                ${scoreBirdHtml(v.mood)}
              </div>
              ${v.delta}
            </div>
          </div>
          <div class="verdict-judgement">
            <h2>${escapeHtml(v.headline)}</h2>
            ${(v.subnotes || []).length
              ? `<ul class="verdict-subnotes">${v.subnotes
                  .map(n => `<li>${escapeHtml(n)}</li>`).join('')}</ul>`
              : ''}
            <div class="verdict-dims">
              ${v.dims.map(d => `
              <div class="vd">
                <span class="lb">${escapeHtml(d[0])}</span>
                <span class="vl num">${d[1]}</span>
                <div class="bar"><i style="width:${d[1]}%"></i></div>
              </div>`).join('')}
            </div>
          </div>
        </div>` : ''}
      </div>
      ${v.isSample ? `<p class="verdict-note">아래는 <b>샘플 데이터</b>예요. 리허설을 마쳐 정합 판정까지 끝나면 실제 결과로 바뀝니다.</p>` : ''}
    </section>
    <div class="tabs" id="rtabs">
      ${tabs.map((t, i) => `<button class="${i === rTab ? 'on' : ''}">${t}</button>`).join('')}
    </div>
    <div id="rbody"></div>`;
  paintVerdictBg();
  $('#rtabs').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    rTab = $$('#rtabs button').indexOf(b);
    renderReport();
  });
  [rSummary, rRubric, rJudge, rLogic, rPace, rAudience, rTools][rTab]();
  animateViz();
}

function renderProfileReport(p) {
  app.className = 'wide';
  app.innerHTML = `
    <div class="report-head history-head">
      <a class="back-link" href="#/">← 내 발표</a>
      <span class="final-label">발표 + 질문 코칭 최종 분석</span>
      <h1 class="page-title">${p.title}</h1>
      <p class="report-meta">${p.occasion} · ${p.slides}장 · ${p.duration} · ${p.nth}번째 연습</p>
    </div>

    <div class="final-insight">
      <div><span>질문 전 설명 가능</span><strong>${p.before}/${p.total}</strong></div>
      <i>→</i>
      <div class="after"><span>질문 후 설명 가능</span><strong>${p.after}/${p.total}${p.after > p.before ? `<em class="fi-delta">+${p.after - p.before}</em>` : ''}</strong></div>
      <p><b>대화로 이해했어요</b>${p.mastered}<small>다음 발표 연습 · ${p.weak}</small></p>
    </div>

    <div class="card profile-score">
      <div class="profile-score-main"><strong class="num">${p.score}</strong><span>점</span><small>지난 연습보다 +${p.diff}점</small></div>
      <div class="profile-score-body"><h2>${p.oneLiner}</h2>
        <div class="dims">${p.dims.map(d => `<div class="dim-row"><span class="lb">${d[0]}</span><div class="fill-bar"><i style="width:${d[1]}%"></i></div><span class="vl num">${d[1]}</span></div>`).join('')}</div>
      </div>
    </div>

    <h2 class="section-title history-section-title">발표와 Q&A에서 확인한 근거</h2>
    <div class="history-evidence">${p.evidence.map(e => `
      <article class="card history-evidence-card">
        <div class="history-evidence-top">${chip(e.status, true)}<span>${e.slide}번 슬라이드 · ${e.time}</span></div>
        <h3>${e.title}</h3>
        <blockquote>${e.quote}</blockquote>
        <p>${e.note}</p>
      </article>`).join('')}</div>

    <div class="card history-priorities">
      <h2 class="section-title">다음 발표에서 고칠 3가지</h2>
      <ol>${p.priorities.map(x => `<li>${x}</li>`).join('')}</ol>
      <div class="step-actions"><a class="btn btn-primary" href="#/new">이 자료로 다시 연습하기</a><a class="btn btn-text" href="#/">내 발표로 돌아가기</a></div>
    </div>`;
}
function goJudge(node) {
  jSel = node; rTab = 1; renderReport();
  // 탭만 바꾸면 긴 목록에서 선택한 개념이 화면 밖에 있을 수 있다
  const picked = $('#jtree .sel') || $(`#jtree [data-node="${node}"]`);
  if (picked) picked.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

/* 탭 1 — 요약 */

/** 덱 필름에 그릴 슬라이드 목록. 상태는 실판정이 있으면 그걸, 없으면 샘플을 쓴다. */
function deckThumbList() {
  const tree = judgeTree();
  const isReal = !!(tree[0] && tree[0].real);
  const total = (nfSlideDoc && nfSlideDoc.total_slides)
    || (uploadedPdf && uploadedPdf.pageCount)
    || DATA.slideStatus.length;
  // 한 장에 여러 개념이 걸리면 가장 나쁜 판정을 그 장의 색으로 쓴다
  const RANK = { ct: 0, no: 1, mid: 2, om: 3, ok: 4 };
  const worst = {};
  if (isReal) {
    tree.forEach(n => {
      const no = slideNumber(n.slide);
      if (!worst[no] || RANK[n.status] < RANK[worst[no]]) worst[no] = n.status;
    });
  }
  const titles = activeTitles();
  return Array.from({ length: total }, (_, i) => {
    const no = i + 1;
    return {
      no,
      status: isReal ? (worst[no] || 'om') : (DATA.slideStatus[i] || 'om'),
      title: titles[i] || DATA.slideTitles[i] || `${no}번 슬라이드`,
      // 업로드 PDF 가 있으면 렌더가 채운다. 없으면 샘플 이미지로 떨어진다.
      src: (uploadedPdf && uploadedPdf.pdf) ? '' : (DATA.slideImages[i] || ''),
    };
  });
}


/* ── 슬라이드 썸네일 ───────────────────────────────────────────────────────
   업로드한 PDF 를 pdf.js 로 직접 렌더한다. 리허설 화면이 쓰는 렌더 경로와
   달리 취소·경합이 없어야 하므로(썸네일은 여러 장을 한 번에 그린다) 별도로 둔다.
   PPTX 는 브라우저에서 렌더할 방법이 없어 이름표만 남는다. */

/* thumbCache · THUMB_WIDTH 선언은 파일 위쪽(uploadedPdf 옆)에 있다 — setUploadedPdf 참고. */

async function slideThumb(pageNo) {
  if (!uploadedPdf || !uploadedPdf.pdf) return null;
  if (thumbCache.has(pageNo)) return thumbCache.get(pageNo);
  try {
    const page = await uploadedPdf.pdf.getPage(pageNo);
    const unscaled = page.getViewport({ scale: 1 });
    const viewport = page.getViewport({ scale: THUMB_WIDTH / unscaled.width });
    const canvas = document.createElement('canvas');
    canvas.width = Math.floor(viewport.width);
    canvas.height = Math.floor(viewport.height);
    await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise;
    const url = canvas.toDataURL('image/jpeg', 0.7);
    thumbCache.set(pageNo, url);
    return url;
  } catch (err) {
    console.warn('[chuckchuck] thumb', pageNo, err);
    return null;
  }
}

/** 화면에 이미 붙은 썸네일 자리를 실제 PDF 렌더로 채운다 (순차 — 한꺼번에 돌리면 버벅인다). */
async function paintDeckThumbs(root = document) {
  if (!uploadedPdf || !uploadedPdf.pdf) return;
  const slots = [...root.querySelectorAll('img[data-thumb-page]')];
  for (const img of slots) {
    const no = Number(img.dataset.thumbPage);
    if (!no) continue;
    const url = await slideThumb(no);
    if (url && img.isConnected) img.src = url;
  }
}

/**
 * "오늘 만든 문장" — 실데이터 출처는 F-11 의 suggestion 이다.
 *
 * 자료가 제일 힘줬는데 설명이 비었거나 어긋난 개념의 제안 문장을 고른다.
 * 그게 다음 리허설에서 실제로 말해볼 한 문장이라 트로피 자리에 맞다.
 * 전부 잘 설명했으면 aligned 중 가장 무거운 개념의 유지 멘트를 쓴다.
 */
function realTrophy() {
  const out = nf && nf.pipelineOut;
  const al = out && out.alignment;
  const graph = out && out.graph;
  if (!al || !graph) return null;
  const slideOf = {};
  (graph.nodes || []).forEach(n => {
    if (n.slide_nos && n.slide_nos.length) slideOf[n.id] = Math.min(...n.slide_nos);
  });
  const withText = (al.items || []).filter(i => (i.suggestion || '').trim() && slideOf[i.node_id]);
  if (!withText.length) return null;
  const rank = { contradiction: 0, missing: 1, justified_skip: 2, aligned: 3 };
  const best = withText.slice().sort((a, b) =>
    (rank[a.verdict] ?? 9) - (rank[b.verdict] ?? 9) || (b.doc_weight || 0) - (a.doc_weight || 0)
  )[0];
  const label = ((graph.nodes || []).find(n => n.id === best.node_id) || {}).label || '';
  return {
    text: best.suggestion.trim(),
    slide: slideOf[best.node_id],
    verdict: best.verdict,
    label,
  };
}

/**
 * F-13 점수를 히어로 카드가 쓰는 모양으로 옮긴다.
 *
 * 막대는 항별 raw 값이다 — 가중치가 아니라 원지표를 보여줘야 "무엇을 잘했나" 가 읽힌다.
 * 결과가 없으면 null (호출부가 샘플로 떨어지고 화면에 그렇게 표시한다).
 */
/* F-13 항목 4개가 병아리와 1:1 이다. 배정 근거는 §9 와 같다 — 그 모델이
   파이프라인에서 실제로 본 축. 막대 옆에 얼굴이 붙으면 "누가 왜 이 점수를
   줬는지"가 보인다 (§6). */
const SCORE_CHICK = {
  content: 'midm',     // 자료와 발화의 정합 판정 (F-11)
  logic: 'midm',       // 같은 축 — 자료가 말한 것과 발화의 관계
  audience: 'ax',      // 발화 축 — 누구에게 어떻게 말했나 (F-05)
  clarity: 'ax',       // 같은 축 — 말 자체의 결
  delivery: 'solar',   // 시간·소리 축 (F-17/18)
  time: 'solar',
  visual: 'exaone',    // 자료 축 (F-01/06/07)
};

/* ── 채점표 탭 ────────────────────────────────────────────────
   이 프로젝트의 출발점은 "평가 로직이 블랙박스다" 였다. 채점표 v3 로 로직은
   바꿨지만, 화면에 클러스터 7개 숫자만 나가면 밖에서 보기엔 여전히 블랙박스다.
   39개 항목을 근거와 함께 펴서 82점이 왜 82점인지 끝까지 되짚게 한다.

   히트맵을 쓰지 않는다. 색칸은 크기만 말하고 근거를 못 싣는다. 무엇보다
   '낮은 점수'와 '이 상황에서는 안 봄'과 '못 쟀음'을 한 색면에 넣으면
   세 가지가 한 가지로 읽힌다 — 우리가 안 뭉개기로 한 바로 그 셋이다. */
const RUBRIC_STATUS = {
  scored:             { t: '',              c: '' },
  situation_excluded: { t: '이번 상황에서는 안 봐요', c: 'var(--om)' },
  unmeasured:         { t: '이번엔 못 쟀어요',        c: 'var(--ct)' },
};
const RUBRIC_SOURCE = { det: '계산', llm: 'AI 판단', na: '' };

function rRubric() {
  const sc = nf && nf.pipelineOut && nf.pipelineOut.score;
  const items = (sc && sc.items) || [];
  if (!items.length) {
    $('#rbody').innerHTML = `
      <div class="card">
        <h3 class="section-title">채점표</h3>
        <p class="note">아직 채점 결과가 없어요. 리허설을 한 번 마치면 항목별로 볼 수 있어요.</p>
      </div>`;
    return;
  }
  const byCluster = {};
  items.forEach((it) => { (byCluster[it.cluster] = byCluster[it.cluster] || []).push(it); });
  const clusters = (sc.clusters || []);
  const nScored = items.filter((i) => i.status === 'scored').length;

  const rowHtml = (it) => {
    const st = RUBRIC_STATUS[it.status] || RUBRIC_STATUS.scored;
    const right = it.status === 'scored'
      ? `<b class="num">${Math.round(it.score)}</b>`
      : `<span class="rb-flag" style="color:${st.c}">${st.t}</span>`;
    const why = it.evidence || it.note || '';
    return `<li class="rb-item is-${it.status}">
      <div class="rb-line"><span class="rb-no num">${it.no}</span>
        <span class="rb-name">${escapeHtml(it.name)}</span>
        ${it.source && RUBRIC_SOURCE[it.source] ? `<span class="rb-src">${RUBRIC_SOURCE[it.source]}</span>` : ''}
        ${right}</div>
      ${why ? `<p class="rb-why">${escapeHtml(why)}</p>` : ''}
    </li>`;
  };

  const blocks = clusters.map((c) => {
    const rows = (byCluster[c.key] || []);
    if (!rows.length) return '';
    const head = c.status === 'scored'
      ? `<b class="num">${Math.round(c.average || 0)}</b>`
      : `<span class="rb-flag" style="color:var(--ct)">이번엔 못 쟀어요</span>`;
    return `<section class="rb-cluster">
      <h4>${escapeHtml(c.name)}${head}</h4>
      <ol class="rb-list">${rows.map(rowHtml).join('')}</ol>
    </section>`;
  }).join('');

  $('#rbody').innerHTML = `
    <div class="card">
      <h3 class="section-title">채점표</h3>
      <p class="note" style="margin-bottom:14px">
        ${escapeHtml(sc.situation_label || '기본 기준')} 기준으로 ${items.length}개 항목 중
        ${nScored}개를 채점했어요. 항목마다 왜 그 점수인지 근거를 남겨요.
      </p>
      ${blocks}
    </div>`;
}

function realSummary() {
  const sc = nf && nf.pipelineOut && nf.pipelineOut.score;
  if (!sc || typeof sc.score !== 'number') return null;
  const dims = (sc.clusters || [])
    .filter(c => c.status === 'scored')
    .map(c => [c.name, Math.round(c.average || 0), SCORE_CHICK[c.key] || '']);
  const notes = [];
  // 두 안내를 합치지 않는다 — '이 상황에서 안 봄'과 '이번에 못 잼'은 다른 말이다.
  // 문구는 부드럽게 바꾸되 개수는 그대로 — 못 잰 걸 숨기면 리포트가 거짓말이 된다
  if ((sc.excluded || []).length) {
    notes.push(`이번 발표 상황에서는 평가하지 않는 항목이 ${sc.excluded.length}개 있어요`);
  }
  if ((sc.unmeasured || []).length) {
    notes.push(
      `이번엔 측정하지 못한 항목이 ${sc.unmeasured.length}개 있어요. `
      + '다음 발표에서는 더 많은 피드백을 받아봐요!'
    );
  }
  if (sc.note) notes.push(sc.note);
  return {
    score: sc.score, dims, notes, basis: sc.basis,
    situationLabel: sc.situation_label || '',
    isFallback: String(sc.rubric_version || '').endsWith('-fallback'),
    // 점수는 판결이 아니라 박수다 — 낮아도 응원(neutral)이지 우는 표정은 없다
    mood: sc.score >= 90 ? 'excited' : sc.score >= 75 ? 'happy' : 'neutral',
  };
}

/* 점수 옆에 앉는 한 마리. 엑씨(헤드폰)는 발표를 귀로 들은 관객이라
   점수 옆에서 "들었다"고 말할 자격이 있다 (04_screens.md §2).
   좌석 래퍼가 있어야 data-mood 로 표정이 걸린다 */
function scoreBirdHtml(mood) {
  if (!window.Chatter || !Chatter.chickSvg) return '';
  return `<span class="verdict-bird ch-seat" data-mood="${mood || 'neutral'}"
                aria-hidden="true">${Chatter.chickSvg('ax')}</span>`;
}

/* 빈 화면·로딩에 세우는 한 마리. 캐릭터는 얹는 층이라 실패해도 화면은 살아야 하므로
   Chatter 가 아직 안 붙었으면 조용히 빈 문자열을 낸다 (03_components.md §6) */
function emptyBirdHtml(speaker, mood) {
  if (!window.Chatter || !Chatter.chickSvg) return '';
  return `<span class="empty-bird ch-seat" data-mood="${mood || 'neutral'}"
                aria-hidden="true">${Chatter.chickSvg(speaker || 'solar')}</span>`;
}

/* ─── 기억하는 객석 (§13) ───────────────────────────────────────────────────
   회차가 끝나면 포스터 벽에 티켓 한 장이 붙는다. 이 기록이 있어야 다음 회차에
   "지난번에 안 했던 X, 오늘은 들었어요" 를 **증명해서** 말할 수 있다. */

/** 이번 회차의 기록. 파이프라인 결과가 없으면 null. */
function currentShow() {
  if (!window.Playbill) return null;
  const out = nf && nf.pipelineOut;
  if (!out || !out.alignment) return null;
  const t = realTrophy();
  return window.Playbill.extract(out, {
    takeId: nf.pipelineStartedAt || '',
    title: (out.graph && out.graph.file_name) || nf.fileName || '',
    slides: (out.graph && out.graph.total_slides) || rehearsalCount(),
    durationSec: (ccLastTake && ccLastTake.durationSec)
      || (out.transcript && out.transcript.duration_sec)
      || nf.sec,
    trophy: t ? t.label : '',
    absent: (chatterCache && chatterCache.absent) || [],
  });
}

function recordShow() {
  const show = currentShow();
  if (show) window.Playbill.record(show);
  return show;
}

/* ─── 커튼콜 (§6) ───────────────────────────────────────────────────────────
   막이 오르면 병아리 넷이 박수를 친다. 숫자는 그 다음에 조용히.

   이 박수는 종연 3초의 완주 박수(§3)와 다르다. 저건 시도에 무조건 주는 것이고
   이건 정직하게 성적을 따른다 (규칙 1 + 토스 규율). 순서를 바꾸거나 합치면
   박수가 성적표가 되거나 성적이 무뎌진다. */

const CURTAINCALL_KEY = 'cheokcheok:curtaincall-shown';
const CURTAINCALL_MS = 2800;

/** 점수 구간별 반응. 갸웃/손드는 건 '자기 담당 항목이 가장 낮은' 병아리다. */
function applauseTier(score, dims) {
  const weakest = (dims || [])
    .filter(d => d[2])
    .slice()
    .sort((a, b) => a[1] - b[1])[0];
  const odd = weakest ? weakest[2] : 'midm';
  if (score >= 90) return { mood: 'ovation', odd: null, line: '기립박수!', sub: '한 마리는 울고 있어요.' };
  if (score >= 75) return { mood: 'cheer', odd: null, line: '넷 다 신나게 박수!', sub: '' };
  if (score >= 60) {
    return {
      mood: 'mixed', odd,
      line: '박수 — 그리고 한 마리가 갸웃',
      sub: `${BACKSTAGE_NAMES[odd] || ''}이 아직 못 들은 게 있대요.`,
    };
  }
  return {
    mood: 'question', odd,
    line: '짝… 짝…',
    sub: `${BACKSTAGE_NAMES[odd] || ''}: "저, 질문 있어요!"`,
  };
}

function showCurtainCallApplause(score, dims) {
  if (!window.Chatter) return Promise.resolve();
  // 2회차부터 스킵 (§14). 같은 박수를 매번 보면 박수가 아니라 인터스티셜이다
  try {
    if (sessionStorage.getItem(CURTAINCALL_KEY) === String(score)) return Promise.resolve();
    sessionStorage.setItem(CURTAINCALL_KEY, String(score));
  } catch (_) { /* ignore */ }

  const t = applauseTier(score, dims);
  const veil = document.createElement('div');
  veil.className = `cc-veil cc-applause cc-${t.mood}`;
  veil.innerHTML = `
    <div class="cc-row">
      ${window.Chatter.SEATS.map(s =>
        `<div class="ch-seat" data-speaker="${s}" data-mood="${
          s === t.odd ? 'curious' : (score >= 75 ? 'happy' : 'neutral')
        }"${s === t.odd ? ' data-odd="1"' : ''}>${window.Chatter.chickSvg(s)}</div>`
      ).join('')}
    </div>
    <div class="cc-line">${escapeHtml(t.line)}</div>
    ${t.sub ? `<div class="cc-sub">${escapeHtml(t.sub)}</div>` : ''}
    <div class="cc-skip">누르면 점수를 볼게요</div>`;
  document.body.appendChild(veil);
  requestAnimationFrame(() => veil.classList.add('on'));

  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      veil.classList.remove('on');
      setTimeout(() => veil.remove(), 380);
      resolve();
    };
    veil.addEventListener('click', finish);
    setTimeout(finish, CURTAINCALL_MS);
  });
}

/* ─── 배웅 (§4) ─────────────────────────────────────────────────────────────
   카너먼: 경험의 기억은 피크와 엔드로 결정된다. 피크는 커튼콜이 맡는데,
   엔드는 지금까지 아무것도 없었다 — 리포트를 보다가 그냥 나갔다.

   외치는 문장은 F-11 트로피 문장 그대로다. 수십 개의 판정 중 사용자가 집에
   가져갈 단 하나의 문장이라, 리포트를 안 읽었어도 이 한 줄은 남는다. */

const SENDOFF_MS = 2400;

function sendoffLine() {
  const t = realTrophy();
  if (t && t.label) {
    return t.verdict === 'aligned'
      ? `다음 공연에서도 '${t.label}' 그대로 들려주세요!!`
      : `다음 공연 땐 '${t.label}' 꼭 들려주세요!!`;
  }
  // 데이터가 없으면 지어내지 않는다. 근거 없는 회상 대사 금지와 같은 규칙이다
  return '오늘 완벽했어요, 또 오세요!';
}

function showSendoff() {
  if (!window.Chatter) return Promise.resolve();
  const veil = document.createElement('div');
  veil.className = 'cc-veil so-veil';
  veil.innerHTML = `
    <div class="cc-row">
      ${window.Chatter.SEATS.map(s =>
        `<div class="ch-seat" data-speaker="${s}" data-mood="happy">
           ${window.Chatter.chickSvg(s)}
         </div>`).join('')}
    </div>
    <div class="cc-line so-shout">${escapeHtml(sendoffLine())}</div>
    <div class="cc-sub">— 오늘의 관객 넷 드림</div>`;
  document.body.appendChild(veil);
  requestAnimationFrame(() => veil.classList.add('on'));
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      veil.classList.remove('on');
      setTimeout(() => veil.remove(), 380);
      resolve();
    };
    veil.addEventListener('click', finish);
    setTimeout(finish, SENDOFF_MS);
  });
}

/**
 * 리포트를 떠나는 순간을 가로채 배웅을 끼워 넣는다.
 *
 * 실판정이 없으면(샘플 화면) 배웅하지 않는다 — 들어본 적 없는 발표를 배웅하면
 * 그 한 줄이 거짓말이 된다.
 */
let sendoffWired = false;
let sendoffPassthrough = null;

function wireSendoff() {
  if (sendoffWired) return;
  sendoffWired = true;
  // 요소마다 붙이면 나중에 그려지는 탭(개념별 판정·논리 흐름·말 속도·연습 도구)의
  // 링크가 영영 안 잡힌다. §4 는 '요약 탭을 떠날 때'가 아니라 '리포트를 떠날 때'다
  document.addEventListener('click', (e) => {
    const el = e.target.closest('a[href="#/new"], a[href="#/"], a[href="#/landing"], [data-fresh-practice]');
    if (!el || el === sendoffPassthrough) return;
    // 상단바 버튼은 라우트가 바뀌어도 살아 있다. 리포트를 떠날 때만 배웅한다
    if (!/^#\/?report/.test(location.hash || '')) return;
    // 들어본 적 없는 발표(샘플 화면)를 배웅하면 트로피 문장이 거짓말이 된다
    if (!realTrophy() && !realSummary()) return;
    e.preventDefault();
    e.stopPropagation();
    showSendoff().then(() => {
      sendoffPassthrough = el;
      el.click();
      sendoffPassthrough = null;
    });
  }, true);
}

/**
 * 회상 카드 — diff 가 증명할 때만 나온다 (§13).
 *
 * 지난 회차에 비었던 개념이 이번엔 채워졌을 때만 렌더된다. 증명이 없으면
 * 아예 자리를 만들지 않는다 — 빈 격려 문구는 성장 기록이 아니라 소음이다.
 */
function recallCardHtml() {
  if (!window.Playbill) return '';
  const line = window.Playbill.recallLine(currentShow());
  if (!line) return '';
  return `
    <div class="card recall-card">
      <span class="rc-face">${window.Chatter ? window.Chatter.chickSvg(line.who) : ''}</span>
      <div class="rc-body">
        <b>${escapeHtml(BACKSTAGE_NAMES[line.who] || '')}</b>
        <p>${escapeHtml(line.text)}</p>
        <span class="rc-proof">지난 회차 판정과 대조한 결과예요</span>
      </div>
    </div>`;
}

const QA_VERDICT = {
  full: { label: '설명함', cls: 'ok' },
  partial: { label: '부분 이해', cls: 'mid' },
  none: { label: '설명 못함', cls: 'no' },
};

/**
 * 지난 발표의 질문 코칭 내역.
 * 기록이 없으면(코칭 전) 아무것도 그리지 않는다 — 빈 껍데기를 두지 않는다.
 */
function qaHistoryPanelHtml() {
  if (!window.QaHistory) return '';
  const reportId = location.hash.replace(/^#\/?/, '').split('/')[1] || 'imu2clip';
  const rec = window.QaHistory.get(reportId);
  if (!rec || !rec.beats || !rec.beats.length) return '';

  const when = new Date(rec.at);
  const stamp = `${when.getFullYear()}.${String(when.getMonth() + 1).padStart(2, '0')}.${String(when.getDate()).padStart(2, '0')}`;

  return `
    <section class="qa-log">
      <div class="block-head">
        <h2>질문 코칭 내역</h2>
        <p>${escapeHtml(rec.aud)}${josa(rec.aud, '과', '와')} 주고받은 ${rec.beats.length}개 질문 · ${stamp}</p>
      </div>
      <div class="qa-log-list">
        ${rec.beats.map((b, i) => {
          const v = QA_VERDICT[b.verdict] || QA_VERDICT.partial;
          return `
          <details class="qa-log-item">
            <summary>
              <span class="st ${v.cls}">${v.label}</span>
              <span class="ql-concept">${escapeHtml(b.label || '')}</span>
              <span class="ql-slide num">${escapeHtml(b.slide || '')}</span>
              <span class="ql-n num">${String(i + 1).padStart(2, '0')}</span>
            </summary>
            <div class="qa-log-body">
              <p class="ql-line"><b>질문</b>${escapeHtml(b.q) || '<i class="ql-empty">기록 없음</i>'}</p>
              <p class="ql-line ql-answer"><b>내 답변</b>${
                b.skipped ? '<i class="ql-empty">답하지 않고 넘겼어요</i>' : (escapeHtml(b.a) || '<i class="ql-empty">기록 없음</i>')}</p>
              ${b.note ? `<p class="ql-note">${escapeHtml(b.note)}</p>` : ''}
              ${(b.turns || b.hint) ? `<p class="ql-meta">${[
                b.turns ? `${b.turns}번 만에 방어` : '',
                b.hint ? `힌트 ${b.hint}단계` : '',
              ].filter(Boolean).join(' · ')}</p>` : ''}
            </div>
          </details>`;
        }).join('')}
      </div>
    </section>`;
}

function rSummary() {
  const meta = reportSessionMeta();
  const live = meta.live;
  const s = DATA.session;
  const prio = DATA.priorities[s.occasion] || DATA.priorities['범용'] || Object.values(DATA.priorities)[0];
  const tr = s.qa.trophy;
  const trophy = realTrophy();
  const real = realSummary();
  const tree = judgeTree();
  const isRealTree = !!(tree[0] && tree[0].real);

  // 올린 자료인데 분석이 없으면 IMU2CLIP 샘플을 절대 보여주지 않는다
  if (live && !real && !isRealTree) {
    const why = (nf && nf.pipelineError)
      || (nf && nf.pipelineOut && nf.pipelineOut.conceptsError)
      || (nf && nf.pipelineDetail)
      || '발표 분석 결과가 이 화면에 없어요. 분석이 끝난 뒤 다시 열어주세요.';
    $('#rbody').innerHTML = `
      <div class="card empty-card">
        ${emptyBirdHtml('solar', 'neutral')}
        <h2 class="section-title">아직 내 발표 분석이 없어요</h2>
        <p class="note" style="margin:8px 0 14px">${escapeHtml(String(why))}</p>
        <p class="note">제목은 <b>${escapeHtml(meta.title)}</b> 기준이에요. 샘플(IMU2CLIP) 리포트로 바꿔 보여주지 않아요.</p>
        <div class="step-actions">
          <a class="btn btn-primary" href="#/new">발표 연습으로 돌아가기</a>
          <a class="btn btn-text" href="#/">홈으로</a>
        </div>
      </div>`;
    return;
  }

  const score = real ? real.score : s.score;
  const dims = real ? real.dims : s.dims;
  const headline = real
    ? (real.notes.length ? real.notes.join(' · ') : '자료와 발표를 대조한 결과예요')
    : s.oneLiner;
  const nextLabel = (trophy && trophy.label) ? trophy.label : '약한 개념';
  // 점수·차원·한 줄 판단은 판정 헤드(renderReport)로 올라갔다 — 여기서 다시 그리지 않는다
  $('#rbody').innerHTML = `
    ${qaHistoryPanelHtml()}
    ${recallCardHtml()}

    ${trophy || !live ? `<button class="card trophy-strip" id="trophyStrip" data-slide="${trophy ? trophy.slide : tr.slide}">
      <span class="ts-label">${trophy
        ? (trophy.verdict === 'aligned' ? '이 흐름을 지키세요' : '다음엔 이렇게 말해보세요')
        : '오늘 만든 문장'}</span>
      <p class="ts-quote">“${escapeHtml(trophy ? trophy.text : tr.after)}”</p>
      <i class="ts-go">${trophy ? trophy.slide : tr.slide}번 슬라이드에서 보기 →</i>
    </button>` : ''}

    <div class="card rep-deck">
      <h3 class="section-title">슬라이드로 보는 발표<span class="soft">장을 누르면 그 장에서 있었던 일을 보여줘요</span></h3>
      <div id="deckBody">${deckHtml()}</div>
      <div class="deck-film" id="deckFilm">
        ${deckThumbList().map(t => `
          <button class="slidethumb st-${t.status} has ${t.no === repSlide ? 'on' : ''}" data-slide="${t.no}" title="${t.no}. ${escapeHtml(t.title)} · ${STATUS[t.status]}">
            <img ${t.src ? `src="${t.src}"` : ''} data-thumb-page="${t.no}" alt="${t.no}번 슬라이드" loading="lazy">
            <span class="stnum">${t.no}</span>
          </button>`).join('')}
      </div>
      <div class="legend">
        <span><i class="dot st-ok"></i>설명함</span>
        <span><i class="dot st-mid"></i>언급만 함</span>
        <span><i class="dot st-no"></i>안 나옴</span>
        <span><i class="dot st-ct"></i>자료와 모순</span>
        <span><i class="dot st-om"></i>정당한 생략</span>
      </div>
    </div>

    ${(!live && prio && prio[0]) ? `
    <h2 class="section-title" style="margin:26px 0 12px">이것부터 고치면 돼요<span class="soft">효과가 가장 큰 한 가지</span></h2>
    ${prioCard(prio[0], 1)}
    <details class="fold">
      <summary>보완 2가지 더 보기</summary>
      <div class="fold-body">${prio.slice(1).map((p, i) => prioCard(p, i + 2)).join('')}</div>
    </details>` : ''}

    <div class="card next-card">
      <h3>${live
        ? (trophy ? `다음 연습은 ‘${escapeHtml(nextLabel)}’부터 다듬어 보세요` : '다음엔 같은 자료로 한 번 더 연습해 보세요')
        : '다음 연습은 ‘IMU Encoder’ 설명부터 시작해요'}</h3>
      <p>${live
        ? '이 리포트는 방금 올린 자료와 발표 분석 결과예요. 질문 코칭을 건너뛰어도 같은 분석이 이어집니다.'
        : 'Q&A로 두 개념은 설명할 수 있게 됐어요. 발표에서 통째로 빠진 Encoder 구조를 다음 리허설 목표로 가져가세요.'}</p>
      <div class="step-actions">
        <a class="btn btn-primary" href="#/new">새 발표 연습</a>
        <a class="btn btn-tint" href="#/qa" style="background:#fff">질문 연습 다시 하기</a>
      </div>
    </div>

    <details class="fold">
      <summary>개념별 판정 전체 보기</summary>
      <div class="fold-body">
        ${(isRealTree ? tree : (live ? [] : DATA.tree)).map(n => `
        <div class="mini-row" data-node="${n.id}">
          <span class="dot st-${n.status}"></span>
          <span class="lbl" style="${n.depth === 2 ? 'padding-left:16px' : ''}">${escapeHtml(n.label)}</span>
          <span class="sl">${slideNumber(n.slide)}번 슬라이드</span>
          ${chip(n.status, true)}
        </div>`).join('') || '<p class="note">표시할 개념 판정이 없어요.</p>'}
      </div>
    </details>`;
  const trophyEl = $('#trophyStrip');
  if (trophyEl) trophyEl.addEventListener('click', (e) => {
    selectDeckSlide(Number(e.currentTarget.dataset.slide) || (trophy && trophy.slide) || 1);
    const deck = $('.rep-deck'); if (deck) deck.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  const film = $('#deckFilm');
  if (film) film.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    selectDeckSlide(Number(b.dataset.slide));
  });
  $$('.mini-row').forEach(r => r.addEventListener('click', () => goJudge(r.dataset.node)));
  bindDeckPanel();
  paintDeckThumbs();
  wireSendoff();
  if (real) showCurtainCallApplause(real.score, real.dims).then(() => animateViz($('#rbody')));
}

/** 파이프라인이 더 돌지 않는 상태인가. 문구와 색이 같은 답을 봐야 해서 한 곳에 둔다. */
function pipelineFinished() {
  return ['done', 'partial', 'error'].includes(nf && nf.pipelinePhase);
}

/** 청중 반응 탭 — 예전엔 요약 탭 맨 아래에 묻혀 있어 찾기 어려웠다. */
function rAudience() {
  const blocked = audienceBlockReason();
  // '아직 안 왔다' 와 '분석이 실패했다' 는 다른 일이다. 둘 다 빨갛게 칠하면
  // 진짜 실패가 친절한 안내로 읽힌다 (CLAUDE.md §4 "실패하면 실패로 보여준다")
  // 색과 문구가 같은 신호를 봐야 한다. 예전엔 문구는 pipelinePhase 로,
  // 색은 pipelineOut 유무로 갈라서 "아직 …단계예요" 가 빨갛게 떴다
  const notYet = !pipelineFinished();
  $('#rbody').innerHTML = `
    <div class="card">
      <h3 class="section-title">삐약 청중석</h3>
      ${blocked ? `<p class="aud-block ${notYet ? 'is-waiting' : 'is-failed'}">${escapeHtml(blocked)}</p>` : ''}
      <div id="audMount"></div>
      ${blocked ? '' : '<div class="step-actions"><button class="btn btn-primary" id="audOpen">객석 들어가기</button></div>'}
    </div>`;
  if (window.Chatter) {
    $('#audMount').innerHTML = window.Chatter.entryCardHtml();
    const card = $('#audCard');
    if (card && !blocked) card.addEventListener('click', openAudience);
  }
  const open = $('#audOpen');
  if (open) open.addEventListener('click', openAudience);
  if (!blocked) prefetchChatter();
}

/**
 * 객석 수다를 미리 받아 둔다. 네 모델이 차례로 말하는 거라 목업으로도 70초가
 * 넘게 걸려서, 「객석 들어가기」를 누른 뒤에 받기 시작하면 그동안 화면이 멈춘다.
 * 리포트를 열 때부터 받아 두면 사람이 요약·판정을 보는 동안 채워진다.
 * 실패는 삼키지 않고 pending 만 풀어 준다 — 누를 때 openAudience 가 다시 부르고,
 * 그때 실패 문구를 판정 색으로 보여준다 (CLAUDE.md 4)
 */
function prefetchChatter() {
  if (chatterCache || chatterPending || !window.Chatter) return;
  const b = pipelineBundle();
  if (!b) return;
  chatterPending = window.Chatter.fetchChatter(b.graph, b.alignment, b.flow);
  chatterPending.catch(() => { chatterPending = null; });
}

/* ---------------------------------------------------------------------------
   삐약 청중석 — 리포트 '청중 반응' 탭에서 객석으로 들어간다
   --------------------------------------------------------------------------- */


function pipelineBundle() {
  const out = nf && nf.pipelineOut;
  if (out && out.graph && out.alignment && out.flow) return out;
  return null;
}

/** 청중이 왜 못 오는지 — '리허설을 마치세요'는 이미 마친 사람에게 거짓말이다. */
function audienceBlockReason() {
  const out = (nf && nf.pipelineOut) || null;
  if (!out) {
    return nf && nf.transcriptOk
      ? '발표는 기록됐는데 분석 결과가 없어요. 스텝 4의 검증 로그를 확인해 주세요.'
      : '아직 청중이 도착하지 않았어요. 리허설을 한 번 마치면 들을 수 있어요.';
  }
  const missing = ['graph', 'alignment', 'flow'].filter((k) => !out[k]);
  if (!missing.length) return null;

  const err = out.graphError || out.alignError || out.flowError || out.conceptsError;
  const stage = out.failedStage
    || { graph: '개념 그래프', alignment: '정합 판정', flow: '흐름 비교' }[missing[0]];

  // 실패로 끝난 건지 아직 도는 중인지를 구분한다. 끝난 걸 '진행 중' 처럼 말하면
  // 사용자가 오지 않을 결과를 계속 기다린다.
  if (pipelineFinished()) {
    return `${stage}에서 실패해서 분석이 멈췄어요${err ? ` (${err})` : ''}. `
      + '기다려도 진행되지 않아요 — 「다른 녹음으로 다시」로 재시도해 주세요.';
  }
  return `아직 ${stage} 단계예요. 실API 는 12장 기준 7분쯤 걸려요. `
    + '청중은 판정 결과를 놓고 수군거리는 거라, 거기까지 끝나야 열려요.';
}

/* 여는 동안 한 번 더 누르면 70초짜리 요청이 두 번 나간다 */
let audienceOpening = false;

async function openAudience() {
  if (audienceOpening) return;
  const card = $('#audCard');
  const bundle = pipelineBundle();
  if (!bundle) {
    // 그릴 때는 멀쩡했는데 누를 때 결과가 사라진 경우다. 실패 문구를 평범한
    // 안내 글씨로 흘리면 실패가 안 보인다 (CLAUDE.md §4)
    const reason = audienceBlockReason();
    const status = card && card.querySelector('.aud-status');
    if (status && reason) {
      status.textContent = reason;
      status.classList.add('aud-block', 'is-failed');
    }
    return;
  }

  // 근거 배지에 슬라이드 번호를 쓰려면 node → slide 매핑이 필요하다
  const nodeSlides = {};
  (bundle.graph.nodes || []).forEach(n => {
    if (n.slide_nos && n.slide_nos.length) nodeSlides[n.id] = Math.min(...n.slide_nos);
  });

  /** 진입 카드의 상태 한 줄. 실패일 때만 판정 색을 입힌다 */
  const say = (text, failed) => {
    const el = card && card.querySelector('.aud-status');
    if (!el) return;
    el.textContent = text;
    el.classList.toggle('aud-block', !!failed);
    el.classList.toggle('is-failed', !!failed);
  };
  say('객석에서 수군거리는 중...', false);
  audienceOpening = true;
  try {
    if (!chatterCache) {
      // 탭을 열 때 미리 받기 시작했으면 그 약속을 기다린다 (두 번 부르지 않는다)
      chatterCache = await (chatterPending || window.Chatter.fetchChatter(
        bundle.graph, bundle.alignment, bundle.flow
      ));
      chatterPending = null;
      // 누가 못 왔는지는 객석을 열어봐야 안다. 티켓의 빈 도장이 여기서 확정된다
      recordShow();
    }
    window.Chatter.show(chatterCache, {
      nodeSlides: nodeSlides,
      onRef: (id) => {
        if (!/^#\/?report/.test(location.hash || '')) location.hash = '#/report';
        goJudge(id);
      },
      onClose: () => {
        // 객석 나가기 / 리포트에서 자세히 보기 → 리포트 화면이 보여야 한다
        if (!/^#\/?report/.test(location.hash || '')) location.hash = '#/report';
        else if (typeof renderReport === 'function') {
          // 오버레이에 가려졌던 리포트를 다시 그리진 않고, 스크롤만 복구
          document.body.style.overflow = '';
        }
      },
    });
    say('발표 끝나고 객석에 남은 네 청중이 뭐라고 하는지 엿들어 볼까요?', false);
  } catch (err) {
    say((err && err.message) || '객석을 여는 데 실패했어요. 잠시 뒤에 다시 누르면 열 수 있어요.', true);
  } finally {
    audienceOpening = false;
  }
}

function selectDeckSlide(n) {
  repSlide = n;
  const body = $('#deckBody'); if (!body) return;
  body.innerHTML = deckHtml();
  $$('#deckFilm button').forEach(b => b.classList.toggle('on', Number(b.dataset.slide) === n));
  const cur = $(`#deckFilm button[data-slide="${n}"]`);
  if (cur) cur.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
  animateViz(body);
  bindDeckPanel();
}

function bindDeckPanel() {
  const go = $('#deckJudgeGo');
  if (go) go.addEventListener('click', () => goJudge(go.dataset.node));
}

/* 선택된 슬라이드의 무대 + 그 장에서 있었던 일 */
function deckHtml() {
  const n = repSlide;
  const st = DATA.slideStatus[n - 1];
  const nodeId = DATA.slideMainNode[n];
  const node = nodeId ? DATA.tree.find(t => t.id === nodeId) : null;
  const moments = DATA.timeline.filter(e => e.onSlide === n);
  let panel = '';
  if (node) {
    panel = `
      <div class="dp-top">${chip(node.status, true)}<b>${node.label}</b></div>
      ${node.status === 'ct' ? `
        <span class="bubble-label" style="margin-top:0">자료에 적힌 것</span>
        <div class="bubble">“${node.docSays}”</div>
        <span class="bubble-label">실제로 한 말</span>
        <div class="bubble" style="background:var(--ct-bg)">${node.spokeSays}<time>${node.spokeTime}</time></div>`
      : `
        <span class="bubble-label" style="margin-top:0">이 장에서 한 말</span>
        <div class="bubble">${node.ev}${node.evTime ? `<time>${node.evTime}</time>` : ''}</div>`}
      <div class="dp-fix"><b>이렇게 말해보세요</b><p>${node.fix}</p></div>
      <button class="btn btn-tint btn-sm" id="deckJudgeGo" data-node="${node.id}">판정 근거 자세히 보기</button>`;
  } else {
    panel = `<p class="dp-none">이 장은 핵심 개념 판정 대상이 아니에요.</p>`;
  }
  if (moments.length) {
    panel += `<div class="dp-moments">${moments.map(m =>
      `<div class="dp-moment"><time class="num">${m.time}</time>${chip(m.type, true)}<span>${m.label}</span></div>`).join('')}</div>`;
  }
  return `
    <div class="deck-main">
      <figure class="deck-stage st-${st}">
        <img src="${DATA.slideImages[n - 1]}" alt="${n}번 슬라이드 · ${DATA.slideTitles[n - 1]}">
        <figcaption><span class="num">${n} / ${DATA.slideTitles.length}</span>${DATA.slideTitles[n - 1]}<em>${STATUS[st]}</em></figcaption>
      </figure>
      <div class="deck-panel">${panel}</div>
    </div>`;
}

function prioCard(p, num) {
  return `
    <div class="card prio-card ${num === 1 ? 'prio-first' : ''}">
      <div class="prio-head">
        <span class="n">${num}</span>
        <h3>${p.t}</h3>
        ${p.gain ? `<span class="chip chip-sm prio-gain">+${p.gain}점 기대</span>` : ''}
      </div>
      <p class="prio-desc">${p.d}</p>
      ${p.spoke || p.spokeNote ? `
        <span class="bubble-label">실제로 한 말</span>
        <div class="bubble">${p.spoke ? `${p.spoke.text}<time>${p.spoke.time}</time>` : `<i style="color:var(--text-3)">${p.spokeNote}</i>`}</div>` : ''}
      ${p.fix ? `
        <span class="bubble-label right blue">이렇게 바꿔보세요</span>
        <div class="bubble fixup">${p.fix}</div>` : ''}
    </div>`;
}

/* 탭 2 — 개념별 판정 */
/* API verdict → 화면 상태. 'mid'(언급만)는 사람이 쓰던 중간값이라 API 에 대응이 없다. */
const STATUS_FROM_VERDICT = {
  aligned: 'ok', missing: 'no', contradiction: 'ct', justified_skip: 'om',
};

/**
 * 실제 파이프라인 결과(F-07 그래프 + F-11 판정)를 판정 탭 트리로 옮긴다.
 * 결과가 없으면 null — 호출부가 DATA 샘플로 떨어지고 화면에 그렇게 표시한다.
 */
function realJudgeTree() {
  const out = nf && nf.pipelineOut;
  if (!out || !out.graph || !out.alignment) return null;
  const itemBy = {};
  (out.alignment.items || []).forEach(i => { itemBy[i.node_id] = i; });
  const nodes = (out.graph.nodes || []).filter(n => itemBy[n.id]);
  if (!nodes.length) return null;

  return nodes
    .slice()
    .sort((a, b) => (b.weight || 0) - (a.weight || 0))
    .map((n) => {
      const it = itemBy[n.id];
      const basis = it.speech_basis || {};
      const slideNo = (n.slide_nos && n.slide_nos.length) ? Math.min(...n.slide_nos) : 1;
      return {
        id: n.id,
        label: n.label || n.id,
        depth: n.depth || 1,
        parent: n.parent_id || null,
        w: n.weight || 0,
        slide: `S${String(slideNo).padStart(2, '0')}`,
        status: STATUS_FROM_VERDICT[it.verdict] || 'no',
        conf: Math.round((it.confidence || 0) * 100),
        checks: it.checks || {},
        ev: it.evidence || '',
        evTime: basis.first_mention_sec != null ? fmtMarkSec(basis.first_mention_sec) : '',
        why: it.note || '',
        fix: it.suggestion || '',
        real: true,
      };
    });
}

/** 실데이터가 있으면 그것. 업로드 세션인데 분석이 없으면 빈 트리(샘플 IMU2CLIP 위장 금지). */
function judgeTree() {
  const real = realJudgeTree();
  if (real) return real;
  if (isLiveReportSession()) return [];
  return DATA.tree.map(n => ({ ...n, real: false }));
}

function rJudge() {
  const tree = judgeTree();
  const isReal = !!(tree[0] && tree[0].real);
  if (isLiveReportSession() && !tree.length) {
    $('#rbody').innerHTML = `
      <div class="card">
        <h3 class="section-title">개념 판정이 아직 없어요</h3>
        <p class="note">내 발표 분석(그래프·정합)이 없어 샘플 개념으로 채우지 않았어요.</p>
        <div class="step-actions"><a class="btn btn-primary" href="#/new">발표 연습으로</a></div>
      </div>`;
    return;
  }
  const counts = { all: tree.length };
  tree.forEach(n => counts[n.status] = (counts[n.status] || 0) + 1);
  const filters = [['all', '전체'], ['ok', '설명함'], ['mid', '언급만'], ['no', '안 나옴'], ['ct', '모순'], ['om', '생략']];
  const items = tree.filter(n => jFilter === 'all' || n.status === jFilter);
  if (!items.some(n => n.id === jSel) && items.length) jSel = items[0].id;
  const n = tree.find(t => t.id === jSel);
  $('#rbody').innerHTML = `
    <div class="filter-chips" id="jf">
      ${filters.map(f => `<button class="${jFilter === f[0] ? 'on' : ''}" data-f="${f[0]}">${f[1]} ${counts[f[0]] || 0}</button>`).join('')}
    </div>
    <div class="judge-grid">
      <div class="card" style="padding:8px">
        <div class="tree" id="jtree">
          ${items.map(t => `
          <button class="${t.id === jSel ? 'sel' : ''} ${t.depth === 2 ? 'child' : ''}" data-id="${t.id}">
            <span class="dot st-${t.status}"></span>${t.label}
            <small>${slideNumber(t.slide)}번</small>
          </button>`).join('')}
        </div>
      </div>
      <div class="card" id="jdetail">${n ? jDetail(n, tree) : '<p class="note">이 상태의 개념이 없어요.</p>'}</div>
    </div>
    <p class="ai-note">${isReal
      ? '판정은 AI 분석 결과예요. 이상하다고 느껴지면 근거 발화를 직접 확인해보세요.'
      : (isLiveReportSession()
        ? '내 발표 분석 결과가 없어 개념 판정을 그리지 못했어요. 샘플(IMU2CLIP)로 대체하지 않았어요.'
        : '⚠️ 지금 보시는 건 <b>샘플 데이터</b>예요. 리허설을 마쳐 정합 판정까지 끝나면 실제 발표 결과로 바뀝니다.')}</p>`;
  $('#jf').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    jFilter = b.dataset.f; rJudge(); animateViz($('#rbody'));
  });
  $('#jtree').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    jSel = b.dataset.id; rJudge(); animateViz($('#rbody'));
  });
}

function jDetail(n, tree = DATA.tree) {
  const slideNum = slideNumber(n.slide);
  const title = activeTitles()[slideNum - 1] || DATA.slideTitles[slideNum - 1] || `${slideNum}번 슬라이드`;
  const img = DATA.slideImages[slideNum - 1];
  // 실데이터는 4축을 checks 로, 샘플은 옛 필드명 check 로 준다
  const checks = n.checks || n.check || {};
  return `
    <div class="detail-top">
      <h3>${escapeHtml(n.label)}</h3>${chip(n.status)}
    </div>
    <p class="detail-meta">${slideNum}번 슬라이드 · 중요도 ${Number(n.w || 0).toFixed(2)}${n.depth === 2 ? ` · 상위 개념: ${escapeHtml(tree.find(t => t.id === n.parent)?.label || '—')}` : ''}</p>
    ${img ? `<figure class="judge-slide st-${n.status}">
      <img src="${img}" alt="${slideNum}번 슬라이드 · ${escapeHtml(title)}">
      <figcaption><span class="num">${slideNum}번 슬라이드</span>${escapeHtml(title)}</figcaption>
    </figure>` : ''}
    ${n.conf ? `<div class="confbar">판정 확신도 <span class="fill-bar"><i data-w="${n.conf}%"></i></span><b class="num">${n.conf}%</b></div>` : ''}
    ${Object.keys(checks).length ? `<div class="checks">
      ${Object.entries(checks).map(([k, v]) => `<span class="${v ? 'y' : ''}">${v ? '✓' : '—'} ${escapeHtml(k)}</span>`).join('')}
    </div>` : ''}
    ${n.status === 'ct' ? `
    <div class="drow"><b>자료와 발화 비교</b>
      <span class="bubble-label" style="margin-top:0">자료에 적힌 것</span>
      <div class="bubble">“${n.docSays}”</div>
      <span class="bubble-label right" style="color:var(--ct)">실제로 한 말</span>
      <div class="bubble fixup" style="background:var(--ct-bg)">${n.spokeSays}<time>${n.spokeTime}</time></div>
    </div>` : `
    <div class="drow"><b>근거 발화</b>
      <div class="bubble">${n.ev ? escapeHtml(n.ev) : '<span class="note">이 개념에 해당하는 발화를 찾지 못했어요.</span>'}${n.evTime ? `<time>${n.evTime}</time>` : ''}</div>
    </div>`}
    ${n.why ? `<div class="drow"><b>판정 이유</b>${escapeHtml(n.why)}</div>` : ''}
    ${n.fix ? `<div class="fixbox"><b>이렇게 말해보세요</b><p>${escapeHtml(n.fix)}</p></div>` : ''}
    <div class="step-actions">
      <a class="btn btn-tint btn-sm" href="#/qa">이 개념으로 질문 연습</a>
    </div>`;
}

/* 탭 3 — 논리 흐름. 파이프라인이 FlowDiff 를 내면 실데이터, 아니면 데모 데이터 */
const FLOW_KIND = {
  missing_link: { type: '연결 멘트 없음', good: false },
  order_jump: { type: '근거 점프', good: false },
  good_link: { type: '잘된 연결', good: true },
};

function rLogicRealCards(flow) {
  const cards = (flow.issues || []).map((i) => {
    const kind = FLOW_KIND[i.kind] || { type: escapeHtml(i.kind), good: false };
    const slides = i.slide_nos || [];
    const from = slides.length ? `${slides[0]}번` : '—';
    const to = slides.length > 1 ? `${slides[slides.length - 1]}번` : from;
    return `
    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        ${chip(kind.good ? 'ok' : 'no', true)}
        <span class="note">${kind.type}</span>
      </div>
      <div class="flow-vis">
        <span class="slide-chip">${from} 슬라이드</span>
        <span class="flow-line ${kind.good ? 'good' : ''}"><em>${kind.good ? '✓' : '✕'}</em></span>
        <span class="slide-chip">${to} 슬라이드</span>
      </div>
      <p class="logic-note"><b>${kind.type}</b> — ${escapeHtml(i.note || '')}</p>
      ${i.cue ? `<div class="bubble">“${escapeHtml(i.cue)}”</div>` : ''}
    </div>`;
  }).join('');

  const tau = flow.order_tau;
  const tauNote = tau == null
    ? ''
    : `<p class="ai-note">자료 순서와 발표 순서 일치도 ${Math.round(((tau + 1) / 2) * 100)}%${
      (flow.ghost_node_ids || []).length
        ? ` · 한 번도 언급되지 않은 개념 ${flow.ghost_node_ids.length}개`
        : ''}</p>`;
  return cards + tauNote;
}

function rLogic() {
  const flow = nf && nf.pipelineOut && nf.pipelineOut.flow;
  if (flow && Array.isArray(flow.issues) && flow.issues.length) {
    $('#rbody').innerHTML = rLogicRealCards(flow);
    return;
  }
  $('#rbody').innerHTML = `
    ${DATA.logicBreaks.map(l => `
    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
        ${chip(l.good ? 'ok' : 'no', true)}
        <span class="note num">${l.time}</span>
      </div>
      <div class="flow-vis">
        <span class="slide-chip">${l.from} 슬라이드</span>
        <span class="flow-line ${l.good ? 'good' : ''}"><em>${l.good ? '✓' : '✕'}</em></span>
        <span class="slide-chip">${l.to} 슬라이드</span>
      </div>
      <p class="logic-note"><b>${l.type}</b> — ${l.note}</p>
      <div class="bubble">${l.ev}<time>${l.time}</time></div>
    </div>`).join('')}
    <p class="ai-note">논리가 끊긴 곳은 최대 5곳까지만 짚어요 — 위치와 실제 발화를 함께 확인하세요.</p>`;
}

/* 탭 4 — 말 속도 */
/** F-14/F-17 결과를 말 속도·음성 습관 탭이 쓰는 모양으로. */
function realPace() {
  const p = nf && nf.pipelineOut && nf.pipelineOut.pace;
  if (!p) return null;
  if (Array.isArray(p.slides) && p.slides.length && (p.avg_chars_per_min != null || p.slides[0].actual_sec != null)) {
    const avg = Math.round(p.avg_chars_per_min || 0);
    const ranked = [...p.slides].sort((a, b) => (b.chars_per_min || 0) - (a.chars_per_min || 0));
    const fastest = ranked[0] || {};
    const rows = p.slides.map(s => [
      `${s.slide_no}번`,
      (s.title || '').slice(0, 18) || `${s.slide_no}번`,
      Math.round(s.chars_per_min || 0),
      s.status === 'fast' || (avg && s.chars_per_min >= avg * 1.15),
      s.importance === 'core',
    ]);
    const allocations = (p.sections || []).map(a => ({
      name: a.name,
      recommended_pct: p.target_sec ? Math.round((a.recommended_sec || 0) / p.target_sec * 100) : 0,
      actual_pct: (p.actual_sec || p.target_sec) ? Math.round((a.actual_sec || 0) / Math.max(1, p.actual_sec || p.target_sec) * 100) : 0,
      gap_pct: 0,
      verdict: a.status === 'ok' ? 'ok' : (a.status === 'long' ? 'over' : 'under'),
    }));
    return {
      avg,
      max: Math.round(fastest.chars_per_min || avg),
      maxSeg: fastest.slide_no ? `${fastest.slide_no}번 슬라이드` : '—',
      rec: p.recommended_cpm || '300~350',
      rows,
      allocations,
      dropped: 0,
      f17: p,
    };
  }
  if (!p.avg_cpm) return null;
  // 못 믿는 구간(너무 짧음)은 막대에서 뺀다 — 한두 마디로 자/분이 튄다
  const segs = (p.segments || []).filter(s => s.reliable);
  if (!segs.length) return null;
  return {
    avg: Math.round(p.avg_cpm),
    rec: `${p.recommended_min}~${p.recommended_max}`,
    max: p.fastest ? Math.round(p.fastest.cpm) : Math.round(p.avg_cpm),
    maxSeg: p.fastest ? p.fastest.label : '—',
    rows: segs.map(s => [s.label, s.slide_no, Math.round(s.cpm), !!s.is_fast, !!s.is_slow]),
    allocations: p.allocations || [],
    dropped: (p.segments || []).length - segs.length,
  };
}

function rPace() {
  const livePace = nf && nf.pipelineOut && nf.pipelineOut.pace;
  const liveHabits = nf && nf.pipelineOut && nf.pipelineOut.habits;
  const liveReport = nf && nf.pipelineOut && nf.pipelineOut.report;
  if (livePace && Array.isArray(livePace.slides) && livePace.slides.length && livePace.slides[0].actual_sec != null && typeof voiceTimeChartHtml === 'function') {
    const avg = livePace.avg_chars_per_min || 0;
    const easy = voiceEasyBlocks(livePace, liveHabits, liveReport || {});
    const fillers = easy.fillers;
    const tip = (easy.actions && easy.actions[0]) || (livePace.tips && livePace.tips[0]) || '핵심 장은 조금 더, 긴 장은 조금 덜 말해 보세요.';
    $('#rbody').innerHTML = `
      <div class="stat-row voice-stat-row">
        <div class="stat-card pop-in" style="--i:0"><small>목표 시간</small><strong>${easy.target}</strong></div>
        <div class="stat-card pop-in" style="--i:1"><small>내가 쓴 시간</small><strong>${easy.actual}</strong></div>
        <div class="stat-card pop-in" style="--i:2"><small>평균 말 속도</small><strong class="num" data-count="${Math.round(avg)}">0</strong><span class="unit">자/분</span></div>
      </div>
      <div class="card voice-chart-card">${voiceTimeChartHtml(livePace)}<p class="voice-tip">${escapeHtml(tip)}</p></div>
      <div class="card">
        <h3 class="section-title">짧게 말한 핵심 장<span class="soft">여기 시간을 늘려보세요</span></h3>
        <div class="slide-pill-row">${slidePillHtml(easy.shortCore, 'short')}</div>
        <h3 class="section-title" style="margin-top:18px">길게 말한 장<span class="soft">여기를 줄이면 목표에 더 가까워져요</span></h3>
        <div class="slide-pill-row">${slidePillHtml(easy.longOnes, 'long')}</div>
      </div>
      <div class="card">
        <h3 class="section-title">자주 쓴 간투어<span class="soft">같은 말 반복 ${(liveHabits && liveHabits.repeat_cnt) || 0}회 · 긴 쉼 ${(liveHabits && liveHabits.pause_cnt) || 0}회</span></h3>
        ${fillers.length ? `<div class="filler-cloud">${fillers.map((f, i) => `<span class="filler-chip size-${Math.min(4, Math.max(1, f.n))}" style="--i:${i}"><b>${escapeHtml(f.text)}</b><small>${f.n}회</small></span>`).join('')}</div>
          <p class="note" style="margin-top:12px">박스가 클수록 더 자주 나왔어요.</p>` : `<p class="note">눈에 띄는 간투어는 거의 없었어요. 좋아요!</p>`}
      </div>`;
    return;
  }
  const real = realPace();
  const st = real
    ? { avg: real.avg, max: real.max, maxSeg: real.maxSeg, rec: real.rec }
    : DATA.paceStats;
  const rows = real
    ? real.rows
    : DATA.pace.map(p => [p[0], p[1], p[2], !!p[3], false]);
  // 시간 배분 — '권장' 은 자료가 배분한 weight 다 (F-14). 임의의 이상적 배분이 아니다.
  const ALLOC_LABEL = { over: '초과', under: '부족', ok: '적절' };
  const allocRows = real && real.allocations.length
    ? real.allocations.map(a => [
        a.name, a.recommended_pct, a.actual_pct,
        a.verdict === 'ok' ? '적절' : `${a.gap_pct > 0 ? '+' : ''}${Math.round(a.gap_pct)}%p ${ALLOC_LABEL[a.verdict]}`,
      ])
    : DATA.timeAlloc;
  const allocMax = Math.max(35, ...allocRows.map(r => Math.max(r[1], r[2]))) * 1.05;
  const under = allocRows.filter(r => String(r[3]).includes('부족'));
  const allocNote = real && real.allocations.length
    ? (under.length
      ? `${under.map(r => escapeHtml(String(r[0]))).join(' · ')} 구획에 자료가 실은 비중보다 시간을 적게 썼어요.`
      : '자료가 힘을 실은 만큼 시간을 고르게 썼어요.')
    : '방법론 구간에 권장 시간보다 적게 썼어요. 배경을 조금 줄이고 7~12번 슬라이드의 원리 설명에 시간을 옮겨보세요.';
  const MAX = Math.max(460, ...rows.map(r => r[2])) * 1.05;
  const ratio = st.avg / MAX;
  const fastRows = rows.filter(r => r[3]);
  const note = real
    ? (fastRows.length
      ? `${fastRows.map(r => escapeHtml(r[0])).join(' · ')} 구간이 본인 평균보다 15% 넘게 빨라요. 그 개념의 판정을 함께 확인해 보세요.`
      : '구간별 속도가 고르게 유지됐어요.')
      + (real.dropped ? ` (너무 짧은 ${real.dropped}개 구간은 속도를 못 재 제외했어요)` : '')
    : '수식 설명 구간이 본인 평균보다 24% 빨라요. Temperature Parameter와 loss 모두 설명이 부족하다고 판정된 개념과 겹쳐요.';
  $('#rbody').innerHTML = `
    ${real ? '' : `<p class="note" style="color:#f59e0b;margin-bottom:10px">
      ⚠️ <b>샘플 데이터</b>예요. 리허설을 마치면 실제 발화로 계산됩니다.</p>`}
    <div class="stat-row">
      <div class="stat-card"><small>내 평균</small><strong class="num" data-count="${st.avg}">0</strong><span class="unit">자/분</span></div>
      <div class="stat-card"><small>가장 빨랐던 구간</small><strong class="num">${st.max}</strong><span class="unit">자/분</span><p class="note" style="margin-top:4px">${escapeHtml(String(st.maxSeg))}</p></div>
      <div class="stat-card"><small>발표 권장 속도</small><strong class="num">${st.rec}</strong><span class="unit">자/분</span></div>
    </div>
    <div class="card">
      <h3 class="section-title">구간별 말 속도<span class="soft">점선이 내 평균이에요</span></h3>
      <div class="pace-rows">
        <span class="pace-base" style="left:calc(122px + (100% - 226px) * ${ratio.toFixed(3)})"><em>내 평균 ${st.avg}</em></span>
        ${rows.map(r => `
        <div class="pace-row ${r[3] ? 'fast' : ''}">
          <span class="nm">${escapeHtml(String(r[0]))}</span>
          <div class="fill-bar"><i class="${r[3] ? 'red' : ''}" data-w="${(r[2] / MAX * 100).toFixed(1)}%"></i></div>
          <span class="vl">${r[2]}자/분${r[3] ? ' · 빠름' : (r[4] ? ' · 느림' : '')}</span>
        </div>`).join('')}
      </div>
      <p class="note" style="margin-top:14px">${note}</p>
    </div>
    <div class="card">
      <h3 class="section-title">시간 배분<span class="soft">보조 분석 · 권장 대비 실제</span></h3>
      <div class="alloc-lgd">
        <span><i style="background:#C9D5CE"></i>권장</span>
        <span><i style="background:var(--blue)"></i>실제</span>
      </div>
      ${allocRows.map(r => `
      <div class="alloc-row">
        <span class="nm">${escapeHtml(String(r[0]))}</span>
        <div class="alloc-bars">
          <div class="fill-bar"><i class="gray" data-w="${(r[1] / allocMax * 100).toFixed(0)}%"></i></div>
          <div class="fill-bar"><i class="${r[3] === '적절' ? '' : 'red'}" data-w="${(r[2] / allocMax * 100).toFixed(0)}%"></i></div>
        </div>
        <span class="alloc-st ${r[3] === '적절' ? 'fine' : 'warn'}">${r[3]}</span>
      </div>`).join('')}
      <p class="note" style="margin-top:12px">${allocNote}</p>
    </div>`;
}

/* 탭 5 — 연습 도구 */
function rTools() {
  const segs = ['발표 구성', '개요 이미지', '펀치라인', '용어 카드'];
  $('#rbody').innerHTML = `
    <div class="seg-ctl" id="seg">
      ${segs.map((t, i) => `<button class="${i === toolSeg ? 'on' : ''}">${t}</button>`).join('')}
    </div>
    <div id="toolBody"></div>`;
  $('#seg').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    toolSeg = $$('#seg button').indexOf(b); rTools();
  });
  [tStrategy, tMap, tPunch, tTerms][toolSeg]();
}

/**
 * F-20 구성 제안 캐시 키.
 * 같은 자료를 같은 길이로 발표했으면 같은 세션으로 본다 — 탭을 오갈 때마다
 * LLM 을 다시 부르지 않기 위한 키일 뿐이라 이 정도 해상도면 충분하다.
 */
function strategySessionKey() {
  const m = reportSessionMeta();
  return m.live ? `live:${m.title}|${m.duration}` : 'sample';
}

/**
 * F-20 에 보낼 분석 요약.
 *
 * 인용은 개념 판정의 근거 발화(evidence)에서 가져온다 — 서버가 keep.quote 를
 * 실제 발화와 대조해 없으면 버리므로, 진짜 한 말만 넣어야 제안에 살아남는다.
 */
function strategyAnalysis() {
  const meta = reportSessionMeta();
  const tree = judgeTree();
  const sections = (nf && nf.pipelineOut && nf.pipelineOut.pace
    && nf.pipelineOut.pace.sections) || [];

  const concepts = tree.slice(0, 14).map(n => ({
    label: n.label,
    slide: n.slide,
    verdict: STATUS[n.status] || n.status,
  }));

  const quotes = tree
    .filter(n => n.ev)
    .slice(0, 8)
    .map(n => ({
      at: n.evTime || '',
      // 화면용 겹따옴표는 떼고 보낸다 — 대조는 발화 원문끼리 해야 한다
      text: String(n.ev).replace(/^[“"']+|[”"']+$/g, '').trim(),
    }));

  const sampleAlloc = DATA.timeAlloc.map(r => ({
    slide: '', label: r[0], recommended: `${r[1]}%`, actual: `${r[2]}%`,
  }));
  const timeAlloc = sections.length
    ? sections.map(s => ({
      slide: (s.slide_nos && s.slide_nos.length)
        ? `S${String(Math.min(...s.slide_nos)).padStart(2, '0')}` : '',
      label: s.name || '',
      recommended: fmtMarkSec(s.recommended_sec || 0),
      actual: fmtMarkSec(s.actual_sec || 0),
    }))
    // 실데이터 세션인데 구간 배분이 없으면 비운다. 샘플 수치로 위장하지 않는다.
    : (meta.live ? [] : sampleAlloc);

  // 순서표가 짚을 슬라이드 목록. F-17 이 있으면 실제 사용 시간까지 함께 넘긴다.
  const paceSlides = (nf && nf.pipelineOut && nf.pipelineOut.pace
    && nf.pipelineOut.pace.slides) || [];
  const titles = (nf && nf.slideTitles && nf.slideTitles.length)
    ? nf.slideTitles : (meta.live ? [] : DATA.slideTitles);
  const slides = paceSlides.length
    ? paceSlides.map(s => ({
      no: s.slide_no,
      title: (s.title || '').slice(0, 40),
      spent: s.actual_sec ? fmtMarkSec(s.actual_sec) : '',
    }))
    : titles.map((t, i) => ({ no: i + 1, title: String(t).slice(0, 40) }));

  return {
    title: meta.title,
    occasion: meta.occasion,
    duration: meta.duration,
    slides,
    concepts,
    time_alloc: timeAlloc,
    quotes,
  };
}

function tStrategy() {
  if (!window.ReportStrategy) {
    $('#toolBody').innerHTML = `
      <div class="card"><p class="note">구성 제안 모듈을 불러오지 못했어요.</p></div>`;
    return;
  }
  window.ReportStrategy.render($('#toolBody'), {
    sessionId: strategySessionKey(),
    analysis: strategyAnalysis(),
  });
}

function mapSvgString() {
  // 이 SVG는 파일로도 내려받으므로(:root 없음) CSS 토큰 대신 리터럴을 쓴다.
  // 값은 app.css 의 --ok/--mid/--no/--ct 계열과 같게 유지한다.
  const FILL = { ok: '#E9F7EF', mid: '#FDF6E3', no: '#FDF0EF', ct: '#F6EDFD' };
  const LINE = { ok: '#0A8F68', mid: '#B45309', no: '#DC2626', ct: '#9333EA' };
  const nodes = DATA.mapNodes.filter(n => n.root || !mapWeakOnly || n.status !== 'ok');
  const POS = {
    r: [440, 36, 200], a: [170, 120, 150], b: [440, 120, 160], c: [710, 120, 140],
    a1: [170, 210, 150], b1: [360, 210, 140], b2: [520, 210, 130], c1: [640, 210, 140], c2: [790, 210, 100],
  };
  const has = id => nodes.some(n => n.id === id);
  let links = '';
  DATA.mapNodes.filter(n => !n.root).forEach(n => {
    const pid = n.p || 'r';
    if (!has(n.id) || !has(pid)) return;
    const [x1, y1] = POS[pid], [x2, y2] = POS[n.id];
    links += `<path d="M${x1} ${y1 + 24} C ${x1} ${(y1 + y2) / 2 + 14}, ${x2} ${(y1 + y2) / 2 - 6}, ${x2} ${y2 - 6}" fill="none" stroke="#D6DAE0" stroke-width="1.4"/>`;
  });
  const boxes = nodes.map(n => {
    const [x, y, w] = POS[n.id];
    if (n.root) return `<g>
      <rect x="${x - w / 2}" y="${y - 6}" width="${w}" height="36" rx="10" fill="#191F28"/>
      <text x="${x}" y="${y + 17}" text-anchor="middle" font-size="14" font-weight="700" fill="#fff" font-family="Pretendard,sans-serif">${n.label}</text></g>`;
    return `<g>
      <rect x="${x - w / 2}" y="${y - 6}" width="${w}" height="48" rx="10" fill="${FILL[n.status]}" stroke="${LINE[n.status]}" stroke-width="1.4"/>
      <text x="${x}" y="${y + 13}" text-anchor="middle" font-size="13" font-weight="700" fill="#191F28" font-family="Pretendard,sans-serif">${n.label}</text>
      <text x="${x}" y="${y + 31}" text-anchor="middle" font-size="10.5" font-weight="600" fill="${LINE[n.status]}" font-family="Pretendard,sans-serif">${STATUS[n.status]} · ${slideNumber(n.slide)}번</text></g>`;
  }).join('');
  return `<svg viewBox="0 0 880 280" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="발표 개념 지도"><rect width="880" height="280" fill="#FFFFFF"/>${links}${boxes}</svg>`;
}

function tMap() {
  $('#toolBody').innerHTML = `
    <div class="map-tools">
      <label class="toggle"><input type="checkbox" id="weakOnly" ${mapWeakOnly ? 'checked' : ''}> 취약 개념만 보기</label>
      <button class="btn btn-secondary btn-sm" id="dl">SVG로 저장</button>
    </div>
    <div class="map-box">${mapSvgString()}</div>
    <p class="note" style="margin-top:10px">발표 직전에 이 그림 한 장으로 전체 구조와 신경 쓸 개념을 확인하세요.</p>`;
  $('#weakOnly').addEventListener('change', e => { mapWeakOnly = e.target.checked; tMap(); });
  $('#dl').addEventListener('click', () => {
    const blob = new Blob([mapSvgString()], { type: 'image/svg+xml' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'IMU2CLIP_발표개요.svg';
    a.click(); URL.revokeObjectURL(a.href);
  });
}

function tPunch() {
  $('#toolBody').innerHTML = `
    ${DATA.punchlines.map(p => `
    <div class="card punch-card">
      <p class="phrase">“${p.main}”</p>
      <p class="pos">${p.time} · ${p.pos}</p>
      <p class="why">${p.why}</p>
    </div>`).join('')}
    <p class="note" style="margin-top:10px">내 말투 기반으로 만들었어요 · 실제 발화의 “~구조입니다” 패턴 반영</p>`;
}

function tTerms() {
  $('#toolBody').innerHTML = `
    ${DATA.terms.map(t => `
    <div class="card">
      <div class="term-top"><h3>${t.term}</h3>${chip(t.status, true)}<span class="sl">근거: ${slideNumber(t.slide)}번 슬라이드</span></div>
      <p class="term-def">${t.def}</p>
      <p class="term-q"><b>예상 질문</b> — ${t.q}</p>
      <p class="term-f"><b>답변 프레임</b> — ${t.frame}</p>
    </div>`).join('')}
    <p class="note" style="margin-top:10px">정의는 발표자료에 있는 내용으로만 만들어요.</p>`;
}

/* ══ Q&A · 대화형 질문 코칭 ══ */
/* 시간 모드 라디오 (질문 코칭 게이트 공용) */
function qaModeButtonsHtml() {
  const cur = (qa && qa.mode) || '10';
  /* TDS ListRow 구조 — left(시간) / contents(무엇을 하는지) / right(범위·선택).
     예전엔 세 장이 다 같은 무게의 네모라 무엇이 골라져 있는지 안 보였다 */
  return `<div class="qa-modes" role="radiogroup" aria-label="질문 코칭 시간">
    ${Object.keys(QA_MODES).map((k) => {
      const md = QA_MODES[k];
      const on = cur === k;
      return `<button type="button" class="qa-mode ${on ? 'on' : ''}" data-mode="${k}" role="radio" aria-checked="${on}">
        <span class="qm-time">${escapeHtml(String(md.short).split('·')[0].trim())}</span>
        <span class="qm-body"><b>${escapeHtml(String(md.short).split('·').slice(1).join('·').trim() || md.short)}</b><span>${escapeHtml(md.desc)}</span></span>
        <!-- scopeLabel 은 바로 왼쪽 desc 를 줄여 쓴 말이라 한 줄에 같은 말이 두 번 나왔다.
             ListRow 의 right 슬롯에는 고른 상태만 남긴다 -->
        <span class="qm-right"><i class="qm-check" aria-hidden="true">${on ? '✓' : ''}</i></span>
      </button>`;
    }).join('')}
  </div>`;
}
function wireQaModeButtons(rerender) {
  $$('.qa-mode').forEach((btn) => btn.addEventListener('click', () => {
    resetQa();
    qa.mode = btn.dataset.mode;
    saveSession('qa-flow', qa);
    rerender();
  }));
}
/* 플랫(세션 없는) 질문 경로가 쓰는 판정용 세션 자리표시자. */
const FLAT_QA_SESSION_ID = 'flat';

/* 실전 질문을 만들 수 없는 **영구적** 이유. null 이면 만들 수 있다. */
function qaLiveBlockReason(out) {
  if (!out || !out.graph) {
    return '내 발표 분석 결과가 없어 데모 질문으로 진행해요. 「새 발표 연습」에서 준비를 먼저 끝내 주세요.';
  }
  return null;
}

const QA_BRIDGE_RETRY_MS = 120;
const QA_BRIDGE_MAX_TRIES = 25;   // 약 3초
let qaBridgeTries = 0;

function onQaRoute() {
  return location.hash.replace(/^#\/?/, '').split('/')[0] === 'qa';
}

function qaNoticeHtml() {
  if (!qa.liveNotice) return '';
  return `<p class="qa-notice" role="status">${escapeHtml(qa.liveNotice)}</p>`;
}

/* 실전 질문이 아직 없으면 지금 만든다 — #/qa 로 오는 모든 경로의 단일 보장 지점.
 * @returns {boolean} true 면 생성이 시작됐다 (호출자는 로딩 화면을 그린다) */
function ensureLiveQuestions() {
  if (qaLiveActive() || qaBuilding || qaBuildFailed) return false;

  const out = nf && nf.pipelineOut;
  const bridge = window.ChuckchuckBridge;

  if (!bridge || !bridge.buildQuestions) {
    if (qaBridgeTries < QA_BRIDGE_MAX_TRIES) {
      qaBridgeTries += 1;
      setTimeout(() => { if (onQaRoute()) renderQa(); }, QA_BRIDGE_RETRY_MS);
      return true;
    }
    qaBuildFailed = true;
    qa.liveNotice = '질문 생성 모듈을 불러오지 못했어요. 새로고침 후 다시 시도해 주세요.';
    saveSession('qa-flow', qa);
    return false;
  }

  const blocked = qaLiveBlockReason(out);
  if (blocked) {
    if (qa.liveNotice !== blocked) {
      qa.liveNotice = blocked;
      saveSession('qa-flow', qa);
    }
    return false;
  }

  qaBuilding = true;
  qa.liveNotice = '';
  // 아티팩트를 세션에 먼저 등록해 둔다 — 이후 판정은 session_id 만 보내면 되고,
  // 실패해도 아래 요청이 본문으로 그대로 싣고 가므로 흐름이 막히지 않는다.
  const artifacts = liveArtifacts();
  const registered = artifacts && bridge.registerSessionArtifacts
    ? bridge.registerSessionArtifacts(FLAT_QA_SESSION_ID, artifacts).catch((err) => {
        console.warn('[chuckchuck] register session artifacts', err);
      })
    : Promise.resolve();

  registered.then(() => bridge.buildQuestions({
    sessionId: FLAT_QA_SESSION_ID,
    graph: out.graph,
    alignment: out.alignment || null,
    flow: out.flow || null,
    transcript: out.transcript || null,
    context: { situation: nf.occ || '', audience: nf.ctx || '', duration_min: nf.min },
    track: (qa && qa.mode) || '10',
  })).then((doc) => {
    const questions = (doc && doc.questions) || [];
    if (questions.length) {
      qa.live = newLiveState(FLAT_QA_SESSION_ID, questions);
      qa.turns = [];
      qa.sub = 'answer';
      qa.ended = false;
      qa.liveNotice = '';
    } else {
      qaBuildFailed = true;
      qa.liveNotice = '내 발표에서는 질문이 만들어지지 않았어요. 데모 질문으로 진행해요.';
    }
  }).catch((err) => {
    qaBuildFailed = true;
    console.warn('[chuckchuck] build questions', err);
    qa.liveNotice = `내 발표로 질문을 만들지 못했어요 (${err.message || err}). 데모 질문으로 진행해요.`;
  }).finally(() => {
    qaBuilding = false;
    saveSession('qa-flow', qa);
    if (location.hash.replace(/^#\/?/, '').split('/')[0] === 'qa') renderQa();
  });
  return true;
}

function renderQaBuilding() {
  app.className = 'narrow';
  app.innerHTML = `
    <div class="coach-nav"><a href="#/">← 저장하고 나가기</a><span>질문 준비 중</span></div>
    <div class="card qa-building" role="status" aria-live="polite">
      <b>내 발표에서 예상 질문을 만들고 있어요</b>
      <p class="note">개념 그래프와 실제 발화를 대조해 치명적인 것부터 골라요. 10초쯤 걸려요.</p>
      <div class="qb-bar"><i></i></div>
      <div class="step-actions" style="justify-content:center;margin-top:14px">
        <button class="btn btn-text" id="qbSkip" type="button">기다리지 않고 데모 질문으로 진행하기</button>
      </div>
    </div>`;
  const skip = $('#qbSkip');
  if (skip) skip.addEventListener('click', () => {
    qaBuildFailed = true;
    qaBuilding = false;
    qa.liveNotice = '질문 생성을 기다리지 않고 데모 질문으로 진행해요.';
    saveSession('qa-flow', qa);
    renderQa();
  });
}

/* 질문 생성이 진행 중인지. sessionStorage 밖에 둔다 —
 * 생성 도중 새로고침하면 저장된 true 가 영원히 재생성을 막기 때문이다. */
let qaBuilding = false;
/* 이번 코칭에서 생성이 이미 실패했는지 — 무한 재시도 루프 방지. */
let qaBuildFailed = false;

let qa = loadSession('qa-flow') || {};
function resetQa() {
  qa = {
    aud: '교수님', started: false, ended: false,
    mode: (qa && qa.mode) || '10',
    bi: 0, sub: 'answer', hint: 0,
    turns: [],
    concepts: { joint: 'wait', temp: 'wait', aria: 'wait' },
    lost: [],
    combo: 0, comboMax: 0, awarded: false, award: null,
    liveNotice: '',
  };
  qaBuildFailed = false;
  saveSession('qa-flow', qa);
}
if (!Array.isArray(qa.turns) || !qa.mode || !qa.concepts) resetQa();

/* 구버전 브라우저 상태 복원 — turn/turns/hintLevel 이 없으면 실전 코칭이 빈다. */
if (qa.live && Array.isArray(qa.live.questions)) {
  qa.live = { ...newLiveState(qa.live.sessionId, qa.live.questions), ...qa.live };
  if (!Array.isArray(qa.live.turns)) qa.live.turns = [];
  if (!Array.isArray(qa.live.results)) qa.live.results = [];
  if (typeof qa.live.turn !== 'number') qa.live.turn = 0;
  if (typeof qa.live.hintLevel !== 'number') qa.live.hintLevel = 0;
  qa.live.busy = false;
}
let qaTimerId = null;

/* ── 게임 레이어: 설득력 XP · 연속 방어 · 복습 (localStorage, 다크패턴 없이 정직한 상태값) ── */
const GAME_KEY = 'cheokcheok:game';
function loadGame() { try { return JSON.parse(localStorage.getItem(GAME_KEY)) || defaultGame(); } catch (_) { return defaultGame(); } }
function saveGame(g) { try { localStorage.setItem(GAME_KEY, JSON.stringify(g)); } catch (_) { /* privacy mode */ } }
function isoDay(d) { return d.toISOString().slice(0, 10); }
function defaultGame() {
  const t = new Date(), d1 = new Date(t), d2 = new Date(t);
  d1.setDate(t.getDate() - 1); d2.setDate(t.getDate() - 2);
  return { xp: 80, days: [isoDay(d2), isoDay(d1)] };
}
function gameLevel(xp) { return Math.floor((xp || 0) / 100) + 1; }
function dayStreak(days) {
  const set = new Set(days || []), d = new Date();
  if (!set.has(isoDay(d))) d.setDate(d.getDate() - 1);
  let n = 0; while (set.has(isoDay(d))) { n++; d.setDate(d.getDate() - 1); }
  return n;
}
/* 어려운 상대일수록 보상이 큼 — 페르소나 재도전 동기와 연결 */
const XP_MULT = { '교수님': 1, '심사위원': 1.5, '회사 상사': 1.3, '일반 청중': 1.1 };
/* 홈: 연속 연습 스트릭 + 설득력 레벨 + 복습 큐 (말해보카식 루프, 토스식 정보 위계) */
function gameStripHtml() {
  const g = loadGame(), streak = dayStreak(g.days), lvl = gameLevel(g.xp), inLvl = (g.xp || 0) % 100;
  const L = { joint: '공동 임베딩 정렬', temp: 'Temperature Parameter', aria: 'Aria 일반화' };
  const items = [];
  (qa.lost || []).forEach(c => items.push({ label: L[c], when: '지금 복습', due: true }));
  ['joint', 'temp'].forEach((c, i) => {
    if (qa.concepts && (qa.concepts[c] === 'won' || qa.concepts[c] === 'review'))
      items.push({ label: L[c], when: `${[3, 7][i]}일 뒤` });
  });
  return `<div class="card game-card">
    <div class="game-top">
      <div class="game-streak"><strong class="num">${streak}</strong><span>일 연속<br>연습 중</span></div>
      <div class="game-level">
        <div class="gl-head"><b>설득력 레벨 ${lvl}</b><span class="num soft-x">${inLvl} / 100</span></div>
        <div class="fill-bar"><i data-w="${inLvl}%"></i></div>
        <p class="note" style="margin-top:8px">다음 레벨까지 설득력 ${100 - inLvl} · 어려운 상대일수록 더 많이 쌓여요</p>
      </div>
    </div>
    ${items.length ? `<div class="review-list">
      <h4>오늘 다시 만날 개념<span>말해보카식 복습 · 시간이 지나도 설명되는지 확인해요</span></h4>
      ${items.map(r => `<div class="rev-row ${r.due ? 'due' : ''}"><i></i><span>${r.label}</span><em>${r.when}</em></div>`).join('')}
      <a class="btn btn-tint btn-sm" href="#/qa">복습 코칭 시작하기</a></div>` : ''}
  </div>`;
}
function awardGame() {
  const g = loadGame();
  let base = 0;
  ['joint', 'temp', 'aria'].forEach(c => { const s = qa.concepts[c]; if (s === 'won') base += 20; else if (s === 'review') base += 30; });
  base += (qa.comboMax || 0) * 3;
  const earned = Math.round(base * (XP_MULT[qa.aud] || 1));
  const today = isoDay(new Date());
  g.days = g.days || [];
  if (!g.days.includes(today)) g.days.push(today);
  g.xp = (g.xp || 0) + earned;
  saveGame(g);
  return { earned, xp: g.xp, level: gameLevel(g.xp), streak: dayStreak(g.days) };
}

/* 상대(페르소나)별 성격 · 통과 조건 · 압박 방식 */
const PERSONAS = {
  '교수님':   { init: '교', accent: 'blue',   tag: '소크라테스식', style: '이유를 끝까지 되물어요', pass: '원리와 이유까지' },
  '심사위원': { init: '심', accent: 'purple', tag: '날카로운 심사위원', style: '근거와 한계를 파고들어요', pass: '근거와 한계까지' },
  '회사 상사': { init: '팀', accent: 'green',  tag: '바쁜 팀장', style: '결론부터 15초 안에 요구해요', pass: '결론부터 한 문장', limit: 15 },
  '일반 청중': { init: '청', accent: 'orange', tag: '비전공 청중', style: '전문용어를 쓰면 되물어요', pass: '쉬운 말로' },
};
const AUDS = Object.keys(PERSONAS);
const CONCEPT_LABELS = { joint: '공동 임베딩', temp: 'Temperature', aria: 'Aria 일반화' };
const CONCEPT_FULL = { joint: '공동 임베딩 정렬', temp: 'Temperature Parameter', aria: 'Aria 데이터셋 해석' };

/* ── QA 시간 모드: 치명도 순으로 질문 범위를 채운다 ──
 * 키는 서버 계약의 track 과 같은 문자열이다. */
const QA_MODES = {
  '1':  { min: 1,  short: '1분 · 핵심만',   desc: '가장 치명적인 개념 하나만 빠르게 확인해요. 복습은 생략해요.',
          scopeLabel: '가장 치명적인 개념 하나', count: 1, demoConcepts: ['joint'], review: false },
  '5':  { min: 5,  short: '5분 · 핵심+α',  desc: '핵심 개념에 함정 검증과 시차 복습까지 붙여 제대로 코칭해요.',
          scopeLabel: '핵심 개념 + 놓친 개념', count: 3, demoConcepts: ['joint', 'temp'], review: true },
  '10': { min: 10, short: '10분 · 전체 커버', desc: '아쉬운 개념 전부에, 자료와 모순된 설명까지 대조해요.',
          scopeLabel: '아쉬운 개념 전부 + 모순 대조', count: 7, demoConcepts: ['joint', 'temp', 'aria'], review: true },
};
const qaScope = () => QA_MODES[qa.mode] || QA_MODES['10'];
/* 모드 범위에 맞는 비트만 통과 (1분 모드는 시차 복습 비트 제외) */
function qaBeatList() {
  const sc = qaScope();
  return DATA.qaBeats.filter(b => sc.demoConcepts.includes(b.concept) && (sc.review || b.kind !== 'review'));
}
function pushSummary(concept, outcome) {
  const text = (DATA.qaSummaries && DATA.qaSummaries[concept] || {})[outcome];
  if (!text) return;
  pushTurn({ who: 'sys', kind: 'summary', concept, outcome, label: CONCEPT_FULL[concept], text });
}
const persona = () => PERSONAS[qa.aud] || PERSONAS['교수님'];
const audInit = () => persona().init;
/* 받침 유무에 따라 한국어 조사 선택 (과/와, 이/가, 을/를) */
const hasBatchim = w => { const c = (w || '').charCodeAt((w || '').length - 1); return c >= 0xAC00 && c <= 0xD7A3 ? (c - 0xAC00) % 28 !== 0 : true; };
const josa = (w, withB, noB) => hasBatchim(w) ? withB : noB;
/* 상대별 대사/행동 오버레이(by)를 기본 비트 위에 병합 */
const beat = () => {
  const list = qaBeatList();
  const b = list[Math.min(qa.bi, list.length - 1)];
  const ov = b.by && b.by[qa.aud];
  return ov ? { ...b, ...ov } : b;
};
const qText = b => (b.q && (b.q[qa.aud] || b.q['공통'])) || '';

function pushTurn(item) { qa.turns.push(item); saveSession('qa-flow', qa); }
/* 가로형에서는 대화가 #stream 안에서만 스크롤된다(css/tablet.css).
   그때 창을 내리면 아무 일도 일어나지 않아 새 질문이 화면 밖에 남는다. */
function scrollDown() {
  const stream = document.getElementById('stream');
  if (stream && stream.scrollHeight > stream.clientHeight + 1) {
    stream.scrollTop = stream.scrollHeight;
    return;
  }
  window.scrollTo({ top: document.body.scrollHeight, behavior: 'auto' });
}

/* ── 설득 트래커 ── */
const TRACK_ICON = { wait: '', current: '', won: '✓', review: '✓', lost: '✕' };
const TRACK_WORD = { wait: '아직', current: '설득 중', won: '설득 완료', review: '두 번 확인', lost: '미방어' };
function trackerHTML() {
  const sc = qaScope();
  const order = sc.demoConcepts;
  const won = order.filter(c => qa.concepts[c] === 'won' || qa.concepts[c] === 'review').length;
  const lost = qa.lost.length;
  const total = qaBeatList().length;
  const prog = Math.min(100, Math.round(qa.bi / Math.max(1, total - 1) * 100));
  return `<div class="persuade-track" id="ptrack" style="--p:${prog}%">
    <div class="pt-head"><span>${qa.aud} 설득하기 · ${sc.short}</span>
      <span class="pt-right">${qa.combo >= 2 ? `<span class="combo-live">🔥 ${qa.combo}연속 방어</span>` : ''}<b>${won}<i>/${order.length} 설득</i>${lost ? ` · <em>${lost} 미방어</em>` : ''}</b></span></div>
    <div class="pt-items">${order.map(c => {
      const s = qa.concepts[c];
      return `<div class="pt ${s}"><i>${TRACK_ICON[s]}</i><span>${CONCEPT_LABELS[c]}</span><small>${TRACK_WORD[s]}</small></div>`;
    }).join('')}</div></div>`;
}
function updateTracker() { const el = $('#ptrack'); if (el) el.outerHTML = trackerHTML(); }

/* ── 스트림 한 줄 렌더 ── */
function streamRow(it) {
  if (it.who === 'sys' && it.kind === 'summary') {
    return `<div class="qa-sum">
      <span class="qs-eyebrow">총평에 적혔어요</span>
      <b class="qs-name">${it.label}</b>
      <p class="qs-text" data-full="${escapeHtml(it.text)}">${escapeHtml(it.text)}</p>
    </div>`;
  }
  if (it.who === 'sys') return `<div class="qa-flag ${it.kind}"><i>${it.kind === 'won' ? '✓' : it.kind === 'lost' ? '✕' : '🔥'}</i>${it.text}</div>`;
  if (it.who === 'me') {
    const tag = it.kind === 'choice' ? '<span class="mb-tag">내 선택</span>' : '';
    return `<div class="msg me${it.partial ? ' partial' : ''}"><div class="msg-bubble">${it.text}${tag}</div></div>`;
  }
  const av = `<span class="msg-avatar av-${persona().accent}">${audInit()}</span>`;
  if (it.kind === 'question' || it.kind === 'claim') {
    return `<div class="msg ai q${it.review ? ' review' : ''}${it.kind === 'claim' ? ' trap' : ''}">${av}
      <div class="msg-bubble">
        <span class="msg-meta">${it.meta || ''}${it.slide ? ` · ${slideNumber(it.slide)}번 슬라이드` : ''}</span>
        <p class="msg-q">${it.text}</p>
        ${it.basis ? `<span class="msg-basis">${it.basis}</span>` : ''}
      </div></div>`;
  }
  if (it.kind === 'interject') return `<div class="msg ai cut">${av}<div class="msg-bubble">${it.text}</div></div>`;
  if (it.kind === 'hint') return `<div class="msg ai hint">${av}<div class="msg-bubble"><b>힌트 ${it.level}/3</b>${it.text}</div></div>`;
  if (it.kind === 'react') {
    const lab = { full: '제대로 설명했어요', partial: '절반쯤', none: '아직' }[it.verdict];
    const cls = { full: 'st-ok', partial: 'st-mid', none: 'st-no' }[it.verdict];
    return `<div class="msg ai react">${av}<div class="msg-bubble"><span class="chip chip-sm ${cls}">${lab}</span><p>${it.text}</p></div></div>`;
  }
  if (it.kind === 'missing') {
    return `<div class="msg ai miss">${av}<div class="msg-bubble">
      <span class="msg-meta">아직 안 나온 것</span>
      <div class="miss-chips">${it.points.map((p) => `<span class="chip chip-sm st-mid">${p}</span>`).join('')}</div>
    </div></div>`;
  }
  if (it.kind === 'gist') {
    return `<div class="msg ai gist">${av}<div class="msg-bubble">
      <span class="msg-meta">이렇게 답하면 좋았어요</span>
      <p>${it.text}</p>
    </div></div>`;
  }
  if (it.kind === 'concede') return `<div class="msg ai">${av}<div class="msg-bubble">${it.text}</div></div>`;
  return '';
}

/* 스트림에 새로 쌓인 줄만 append (기존 줄 재애니메이션 방지) */
function growStream() {
  const s = $('#stream'); if (!s) return;
  for (let k = s.children.length; k < qa.turns.length; k++) {
    const wrap = document.createElement('div');
    wrap.innerHTML = streamRow(qa.turns[k]);
    const node = wrap.firstElementChild;
    if (node) {
      node.classList.add('enter');
      s.appendChild(node);
      if (node.classList.contains('qa-sum')) typeSummary(node);
    }
  }
  scrollDown();
}

/* 총평 문장이 눈앞에서 작성되는 타자 효과 */
function typeSummary(node) {
  const p = node.querySelector('.qs-text'); if (!p) return;
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const full = p.dataset.full || p.textContent;
  p.textContent = '';
  let i = 0;
  const tick = () => {
    if (!p.isConnected) return;
    i += 2;
    p.textContent = full.slice(0, i);
    if (i < full.length) later(tick, 22); else scrollDown();
  };
  tick();
}

/* 실전 QA(서버 질문 생성·판정) 화면은 js/qa_live.js 로 분리했습니다. */

/* ── 화면 ── */
function renderQa() {
  app.className = 'narrow';
  dismissF11Reveal();
  try {
  if (qaLiveActive()) return renderQaLive();
  if (qa.ended) return qaEnd();
  // 시간 트랙(1/5/10분)을 먼저 고르게 한다 — 질문 개수가 트랙에 달려 있다
  if (!qa.started && !qa.turns.length) return qaModeGate();
  // 트랙이 정해졌으면 여기서 실제 질문을 보장한다
  if (ensureLiveQuestions()) return renderQaBuilding();
  qa.started = true;
  // 첫 진입: 첫 질문을 스레드에 올림 (데모 폴백)
  const firstBeat = qaBeatList()[0];
  if (!qa.turns.length) {
    if (!firstBeat) {
      app.innerHTML = `${stageAccidentHtml('질문 목록을 만들지 못했어요. 홈으로 돌아가 다시 시도해 주세요.')}
        <div class="step-actions"><a class="btn btn-primary" href="#/">홈으로</a></div>`;
      return;
    }
    if (!qa.concepts) qa.concepts = { joint: 'wait', temp: 'wait', aria: 'wait' };
    qa.concepts.joint = 'current';
    presentQuestion(firstBeat);
  }
  // 새로고침 등으로 중간 상태가 저장돼 있으면 안전한 상태로 되돌림
  if (qa.sub === 'speaking' || qa.sub === 'thinking' || qa.sub === 'committed' || qa.sub === 'typing')
    qa.sub = beat().kind === 'trap' ? 'choice' : 'answer';
  saveSession('qa-flow', qa);
  app.innerHTML = `
    <div class="coach-nav"><a href="#/">← 저장하고 나가기</a><span>자동 저장됨</span></div>
    <div class="qa-shell">
      <aside class="qa-context">
    ${qaNoticeHtml()}
    <div class="qa-top">
      <div>
        <h1 class="page-title" style="font-size:19px">${qa.aud} 질문 코칭</h1>
        <p class="page-sub" style="font-size:13px">${DATA.session.title} · 슬라이드를 사이에 두고 실제처럼 주고받아요</p>
      </div>
      <label class="aud-select">상대
        <select id="aud">${AUDS.map(a => `<option ${a === qa.aud ? 'selected' : ''}>${a}</option>`).join('')}</select>
      </label>
    </div>
    <div class="persona-card">
      <span class="persona-av av-${persona().accent}">${persona().init}</span>
      <div class="pc-txt"><b>${qa.aud}</b><span class="pc-style">${persona().tag} · ${persona().style}</span></div>
      <div class="pc-pass"><span>통과 조건</span><b>${persona().pass}${persona().limit ? ` · ${persona().limit}초` : ''}</b></div>
    </div>
    ${trackerHTML()}
      </aside>
      <section class="qa-dialog">
    <div class="qa-stream" id="stream">${qa.turns.map(streamRow).join('')}</div>
    <div class="qa-live" id="live"></div>
      </section>
    </div>`;
  $('#aud').addEventListener('change', e => {
    qa.aud = e.target.value;
    const last = qa.turns[qa.turns.length - 1];
    if (last && last.who === 'ai' && (last.kind === 'question' || last.kind === 'claim') &&
        (qa.sub === 'answer' || qa.sub === 'choice')) {
      const b = beat();
      last.text = b.kind === 'trap' ? b.claim : qText(b);
    }
    clearTimers(); saveSession('qa-flow', qa); renderQa();
  });
  renderLive();
  scrollDown();
  } catch (err) {
    console.warn('[chuckchuck] renderQa', err);
    app.innerHTML = `${stageAccidentHtml(err.message || String(err), { title: '질문 코칭 화면을 그리지 못했어요' })}
      <div class="step-actions"><a class="btn btn-primary" href="#/">홈으로</a>
      <button class="btn btn-text" type="button" id="qaReset">코칭 초기화</button></div>`;
    const b = document.getElementById('qaReset');
    if (b) b.addEventListener('click', () => { resetQa(); renderQa(); });
  }
}

function renderLive() {
  const el = $('#live'); if (!el) return;
  const b = beat();
  if (qa.sub === 'answer') {
    el.innerHTML = `
      <div class="live-actions">
        <button class="btn btn-primary qa-speak" id="speak"><svg class="mic-svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="2" width="6" height="11" rx="3"/><path d="M5 10a7 7 0 0 0 14 0"/><path d="M12 17v4"/></svg>말로 답하기</button>
        <button class="btn btn-secondary" id="hint">막혀요, 힌트</button>
      </div>
      <span class="live-tip">답하다 멈추면 ${qa.aud}${josa(qa.aud,'이','가')} 이어받아요</span>`;
    $('#speak').addEventListener('click', qaSpeak);
    $('#hint').addEventListener('click', qaHint);
  } else if (qa.sub === 'speaking') {
    const lim = persona().limit;
    el.innerHTML = `<div class="caption"><span class="cap-live">듣는 중</span><p id="capT"></p>${lim ? `<span class="cap-timer" id="capTimer">⏱ ${lim}</span>` : ''}</div>`;
    if (lim) {
      if (qaTimerId) clearInterval(qaTimerId);
      let t = lim;
      qaTimerId = every(() => {
        const x = $('#capTimer'); if (!x) return;
        t = Math.max(0, t - 1); x.textContent = `⏱ ${t}`;
        if (t <= 5) x.classList.add('urgent');
      }, 1000);
    }
  } else if (qa.sub === 'thinking') {
    el.innerHTML = '';
  } else if (qa.sub === 'choice') {
    el.innerHTML = `
      <div class="trap-choices">
        <button class="btn btn-secondary" id="cW">${b.wrong}</button>
        <button class="btn btn-secondary" id="cR">${b.right}</button>
      </div>
      <span class="live-tip">${qa.aud}${josa(qa.aud,'이','가')} 방금 한 말, 맞을까요?</span>`;
    $('#cW').addEventListener('click', () => qaChoose(false));
    $('#cR').addEventListener('click', () => qaChoose(true));
  } else if (qa.sub === 'decide') {
    el.innerHTML = `
      <div class="live-actions">
        <button class="btn btn-primary" id="push">한 번 더 설명해볼게요</button>
        <button class="btn btn-text" id="give">오늘은 여기까지 할게요</button>
      </div>`;
    $('#push').addEventListener('click', () => qaDecide(true));
    $('#give').addEventListener('click', () => qaDecide(false));
  } else if (qa.sub === 'ended') {
    el.innerHTML = `<button class="btn btn-primary" id="fin">발표와 대화 결과 보기</button>`;
    $('#fin').addEventListener('click', () => {
      if (!qa.awarded) { qa.award = awardGame(); qa.awarded = true; }
      qa.ended = true; nf.completed = true;
      saveSession('qa-flow', qa); saveSession('new-flow', nf); renderQa();
    });
  }
}

/* ── 질문 제시 ── */
function presentQuestion(b) {
  if (qa.concepts[b.concept] !== 'won' && qa.concepts[b.concept] !== 'review')
    qa.concepts[b.concept] = 'current';
  qa.hint = 0;
  pushTurn({ who: 'ai', kind: b.kind === 'trap' ? 'claim' : 'question',
    text: b.kind === 'trap' ? b.claim : qText(b),
    meta: b.meta, slide: b.slide, basis: b.basis, review: b.kind === 'review' });
  if (b.autoHint) pushTurn({ who: 'ai', kind: 'hint', level: b.autoHint, text: DATA.qaHints[b.autoHint - 1] });
  qa.sub = b.kind === 'trap' ? 'choice' : 'answer';
  saveSession('qa-flow', qa);
}

function goNextBeat() {
  if (qa.bi >= qaBeatList().length - 1) { qa.sub = 'ended'; renderLive(); return; }
  qa.bi++;
  qaThink(() => { presentQuestion(beat()); growStream(); updateTracker(); renderLive(); });
}

/* ── 사용자 발화 (실시간 자막) ── */
function qaSpeak() {
  const b = beat();
  qa.sub = 'speaking'; renderLive();
  if (b.kind === 'interrupt') return speakInterrupt(b);
  streamCaption(b.answer, () => {
    commitAnswer(b.answer);
    qaThink(() => react(b, b.verdict, b.react));
  });
}

function speakInterrupt(b) {
  const words = b.answer.split(' ');
  const cut = Math.max(1, Math.round(words.length * (b.cutAt || 0.6)));
  let i = 0;
  const step = () => {
    const el = $('#capT'); if (!el) return;
    i++; el.textContent = words.slice(0, i).join(' ') + ' …'; scrollDown();
    if (i < cut) { later(step, 120); return; }
    commitAnswer(words.slice(0, cut).join(' ') + ' …');
    qaThink(() => {
      pushTurn({ who: 'ai', kind: 'interject', text: b.interject }); growStream();
      qa.sub = 'speaking'; renderLive();
      streamCaption(b.answerAfter, () => {
        commitAnswer(b.answerAfter);
        qaThink(() => react(b, b.verdict, b.react));
      });
    });
  };
  step();
}

function streamCaption(text, done) {
  const words = text.split(' ');
  let i = 0;
  const tick = () => {
    const el = $('#capT'); if (!el) { done(); return; }
    i++; el.textContent = words.slice(0, i).join(' '); scrollDown();
    if (i < words.length) later(tick, 95 + Math.min(130, words[i - 1].length * 20));
    else later(done, 950); // 침묵 후 자동 제출
  };
  tick();
}

function commitAnswer(text, partial) {
  pushTurn({ who: 'me', kind: 'answer', text, partial });
  qa.sub = 'committed';
  const el = $('#live'); if (el) el.innerHTML = '';
  growStream(); saveSession('qa-flow', qa);
}

/* AI가 생각하는 타이핑 인디케이터 */
function qaThink(done) {
  qa.sub = 'thinking'; renderLive();
  const s = $('#stream'); let node;
  if (s) {
    const d = document.createElement('div');
    d.className = 'msg ai typing enter';
    d.innerHTML = `<span class="msg-avatar av-${persona().accent}">${audInit()}</span><span class="msg-bubble typing-dots"><i></i><i></i><i></i></span>`;
    s.appendChild(d); node = d; scrollDown();
  }
  later(() => { if (node) node.remove(); done(); }, 900);
}

/* ── 반응 + 개념 상태 반영 ── */
function react(b, verdict, text) {
  pushTurn({ who: 'ai', kind: 'react', verdict, text });
  if (b.mastered) { qa.concepts[b.concept] = 'won'; pushTurn({ who: 'sys', kind: 'won', text: `${b.conceptLabel} — ${qa.aud}${josa(qa.aud,'을','를')} 설득했어요` }); }
  if (b.reviewed) { qa.concepts[b.concept] = 'review'; pushTurn({ who: 'sys', kind: 'won', text: `${b.conceptLabel} — 시간이 지나도 설명했어요` }); }
  if (verdict === 'full') {
    qa.combo = (qa.combo || 0) + 1;
    qa.comboMax = Math.max(qa.comboMax || 0, qa.combo);
    if (qa.combo === 3 || qa.combo === 5) pushTurn({ who: 'sys', kind: 'combo', text: `${qa.combo}연속 방어! 흐름 탔어요` });
  } else {
    qa.combo = 0;
  }
  growStream(); updateTracker();
  saveSession('qa-flow', qa);
  if (b.offerConcede) { qa.sub = 'decide'; renderLive(); scrollDown(); return; }
  goNextBeat();
}

function qaHint() {
  qa.hint = Math.min(3, qa.hint + 1);
  pushTurn({ who: 'ai', kind: 'hint', level: qa.hint, text: DATA.qaHints[qa.hint - 1] });
  growStream(); saveSession('qa-flow', qa);
}

/* ── 함정 턴: 클릭이 실제로 등급을 바꿈 ── */
function qaChoose(correct) {
  const b = beat();
  pushTurn({ who: 'me', kind: 'choice', text: correct ? b.right : b.wrong, partial: !correct });
  growStream();
  qaThink(() => react(b, correct ? 'full' : 'partial', correct ? b.onRight : b.onWrong));
}

/* ── 실패/방어 갈림길 (Aria) ── */
function qaDecide(push) {
  const b = beat();
  if (push) {
    qa.sub = 'speaking'; renderLive();
    streamCaption(b.pushAnswer, () => {
      commitAnswer(b.pushAnswer);
      qaThink(() => {
        qa.concepts.aria = 'won';
        qa.combo = (qa.combo || 0) + 1;
        qa.comboMax = Math.max(qa.comboMax || 0, qa.combo);
        pushTurn({ who: 'ai', kind: 'react', verdict: 'full', text: b.onPush });
        pushTurn({ who: 'sys', kind: 'won', text: 'Aria 일반화 — 끝까지 밀어붙여 설득했어요' });
        growStream(); updateTracker();
        qa.sub = 'ended'; renderLive();
      });
    });
  } else {
    pushTurn({ who: 'me', kind: 'choice', text: '오늘은 여기까지 할게요' });
    growStream();
    qaThink(() => {
      qa.concepts.aria = 'lost'; qa.lost = ['aria'];
      pushTurn({ who: 'ai', kind: 'concede', text: b.onConcede });
      pushTurn({ who: 'sys', kind: 'lost', text: 'Aria 일반화 — 오늘은 방어하지 못했어요. 리포트에 남겨둘게요' });
      growStream(); updateTracker();
      qa.sub = 'ended'; renderLive();
    });
  }
}

/* ── 마무리 세리머니: 문장 → 개념 점등 → 보상 ── */
/**
 * 이번 코칭을 발표별 내역으로 남긴다.
 *
 * qa 상태는 sessionStorage 한 칸이라 새 코칭이 시작되면 덮어써진다.
 * 지난 발표에서 다시 보려면 세션 id 를 키로 따로 적어두어야 한다.
 */
/* 실데이터 판정 코드 → 내역 3단계. 넘김·보류는 '설명 못함'으로 모으되
   skipped 플래그로 "못 한 것"과 "안 한 것"을 구분해 둔다. */
const QA_LOG_VERDICT = { good: 'full', partial: 'partial', wrong: 'none', unknown: 'none', skipped: 'none' };

function recordQaHistory() {
  if (!window.QaHistory) return;
  const L = qa.live;
  const s = DATA.session.qa || {};

  // 실데이터 경로 — qa.live.results 가 실제 주고받은 기록이다
  if (L && Array.isArray(L.results) && L.results.length) {
    const beats = L.results.map((r, i) => {
      const src = (L.questions && L.questions[i]) || {};
      return {
        concept: src.concept || src.node || '',
        label: src.label || src.conceptLabel || src.concept || `질문 ${i + 1}`,
        slide: src.slide || (src.slide_no ? `S${String(src.slide_no).padStart(2, '0')}` : ''),
        q: r.question || src.question || src.q || '',
        a: r.summary || '',
        verdict: QA_LOG_VERDICT[r.verdict] || 'partial',
        note: '',
        turns: r.turns || 0,
        hint: r.hintLevel || 0,
        skipped: r.verdict === 'skipped' || !!r.revealed,
      };
    });
    window.QaHistory.save(L.sessionId || 'live', {
      live: true,
      aud: qa.aud || '청중',
      mode: qa.mode || 'full',
      turns: beats.length,
      before: s.before, after: s.after, total: beats.length,
      mastered: beats.filter(b => b.verdict === 'full').map(b => b.label),
      weak: beats.filter(b => b.verdict === 'none').map(b => b.label),
      beats,
    });
    return;
  }

  // mock 시나리오 경로
  const played = (DATA.qaBeats || []).filter(b => b.kind === 'ask');
  if (!played.length) return;
  window.QaHistory.save('imu2clip', {
    live: false,
    aud: qa.aud || '교수님',
    mode: qa.mode || 'full',
    turns: qa.turns || played.length,
    before: s.before, after: s.after, total: s.total,
    mastered: String(s.mastered || '').split('·').map(x => x.trim()).filter(Boolean),
    weak: String(s.weak || '').split('·').map(x => x.trim()).filter(Boolean),
    beats: played.map(b => ({
      concept: b.concept,
      label: b.conceptLabel,
      slide: b.slide,
      q: (b.q && (b.q[qa.aud] || Object.values(b.q)[0])) || '',
      a: b.answer || '',
      verdict: b.verdict || 'partial',
      note: b.react || '',
    })),
  });
}

function qaEnd() {
  if (!qa.awarded) { qa.award = awardGame(); qa.awarded = true; }
  saveSession('qa-flow', qa);
  recordQaHistory();
  const tr = DATA.session.qa.trophy;
  const ariaLost = qa.lost.includes('aria');
  const concepts = [
    { label: 'Self-Supervised Learning', pre: true },
    { label: 'CLIP', pre: true },
    { label: 'IMU2CLIP의 동기', pre: true },
    { label: '공동 임베딩 정렬', pre: false },
    { label: 'Temperature Parameter', pre: false },
  ];
  const aw = qa.award || { earned: 0, level: 1, streak: 1, xp: 0 };
  app.innerHTML = `
    <div class="coach-nav"><a href="#/">← 내 발표로 나가기</a><span>코칭 기록 저장됨</span></div>
    <div class="cere">
      <div class="cere-head">
        <span class="cere-eyebrow">${qa.aud} 질문 코칭 완료</span>
        <h1 class="page-title">오늘 연습의 결과예요</h1>
      </div>

      <div class="card cere-card c1">
        <span class="cere-label">오늘 새로 말할 수 있게 된 문장</span>
        <div class="cere-diff">
          <p class="cd-before"><span>발표에선</span>“${tr.before}”</p>
          <span class="cd-arrow">대화를 거치며 ↓</span>
          <p class="cd-after">“${tr.after}”</p>
        </div>
        <p class="cere-hint">이 문장을 ${tr.slide}번 슬라이드에서 그대로 쓰면 돼요</p>
      </div>

      <div class="card cere-card c2">
        <div class="cere-row-head">
          <span class="cere-label">설명할 수 있는 핵심 개념</span>
          <b class="cere-count num">3 <i>→</i> 5</b>
        </div>
        <ul class="cere-concepts">
          ${concepts.map((c, i) => `
          <li class="${c.pre ? 'pre' : 'neo'}" style="${c.pre ? '' : `animation-delay:${1.3 + (i - 3) * .35}s`}">
            <i>✓</i><span>${c.label}</span>${c.pre ? '' : '<em>+ 오늘</em>'}
          </li>`).join('')}
        </ul>
        <p class="cere-sub ${ariaLost ? 'warn' : 'good'}">${ariaLost
          ? 'Aria 일반화는 오늘 방어하지 못했어요 — 복습으로 다시 만나요'
          : '자료와 어긋났던 Aria 설명도 대화로 바로잡았어요'}</p>
      </div>

      <div class="card cere-card c3">
        <div class="cere-reward">
          <div class="cr-xp"><span>이번에 쌓은 설득력</span><div class="cr-amount"><b>+</b><strong class="num" id="cereXp">0</strong></div></div>
          <div class="cr-facts">
            <span>레벨 ${aw.level}</span>
            <span>🔥 ${aw.streak}일 연속</span>
            ${qa.comboMax >= 2 ? `<span>${qa.comboMax}연속 방어</span>` : ''}
            <span>${qa.aud} 보너스 ×${XP_MULT[qa.aud] || 1}</span>
          </div>
        </div>
        <div class="cere-next"><span>다음 목표</span><b>${ariaLost ? 'Aria 일반화 다시 방어하기' : 'IMU Encoder를 한 문장으로 설명하기'}</b></div>
      </div>

      <div class="cere-actions">
        <a class="btn btn-primary" href="#/report">상세 리포트 보기</a>
        <a class="btn btn-text" href="#/">홈으로</a>
        <button class="btn btn-text" id="again">질문 코칭 다시 하기</button>
      </div>
    </div>`;
  $('#again').addEventListener('click', () => { resetQa(); qa.started = true; renderQa(); });
  later(() => { const el = $('#cereXp'); if (el) countUp(el, aw.earned, 700); }, 2100);
  window.scrollTo(0, 0);
}

/* ══ 서비스 정보 ══ */
function renderAbout() {
  app.className = '';
  app.innerHTML = `
    <h1 class="page-title" style="margin-bottom:24px">척척발표가 판단하는 방식</h1>

    <div class="card about-sec">
      <h2 class="section-title">분석 파이프라인</h2>
      <p class="lead note">발표자료와 실제 발화가 리포트가 되기까지의 단계예요. 아직 확정하지 않은 기술은 후보로 표기해요.</p>
      <table class="plain">
        <thead><tr><th style="width:90px">단계</th><th>하는 일</th><th>쓰는 기술</th><th style="width:110px">상태</th></tr></thead>
        <tbody>
          <tr><td>1</td><td>발표자료(PPT·PDF)를 슬라이드별 텍스트·구조로 변환</td><td>Upstage Document Parse</td><td><span class="chip chip-sm st-ok">확정</span></td></tr>
          <tr><td>2</td><td>녹음을 단어별 시간과 함께 글로 변환, 슬라이드 구간으로 분할</td><td>SKT A.X 계열</td><td><span class="chip chip-sm chip-plain">검증 중</span></td></tr>
          <tr><td>3</td><td>핵심 개념 추출과 중요도 순 개념 트리 구성</td><td>메인 LLM</td><td><span class="chip chip-sm chip-plain">후보 테스트</span></td></tr>
          <tr><td>4</td><td>개념별 설명 여부 판정 (근거 발화 포함)</td><td>문장 유사도 검색 + KT 믿:음</td><td><span class="chip chip-sm chip-plain">후보 테스트</span></td></tr>
          <tr><td>5</td><td>자료·발표 내용·앞선 답변 기반 질문 생성과 소크라테스식 코칭</td><td>판정 LLM</td><td><span class="chip chip-sm chip-plain">후보 테스트</span></td></tr>
          <tr><td>6</td><td>논리가 끊긴 곳 탐지 (최대 5곳)</td><td>LG EXAONE / SKT A.X</td><td><span class="chip chip-sm chip-plain">후보 테스트</span></td></tr>
          <tr><td>7</td><td>발표자 맞춤 방향 제안 (실제 발화 인용 필수)</td><td>SKT A.X / LG EXAONE</td><td><span class="chip chip-sm chip-plain">후보 테스트</span></td></tr>
          <tr><td>8</td><td>발표 판정과 Q&A 전후 이해 변화를 하나의 결과로 통합</td><td>규칙 계산 + 판정 결과 결합</td><td><span class="chip chip-sm chip-plain">준비 중</span></td></tr>
        </tbody>
      </table>
    </div>

    <div class="card about-sec">
      <h2 class="section-title">판단 원칙</h2>
      <ul class="principles">
        <li>모든 판정에 근거 발화를 붙여요. 근거 없는 총평은 하지 않아요.</li>
        <li>계산으로 되는 건 AI를 쓰지 않아요. 말 속도·시간 배분은 수식으로 계산해 결과가 늘 같아요.</li>
        <li>‘설명 안 함’ 판정은 사람 판단과 10번 중 8번 이상 일치해야 출시해요.</li>
      </ul>
    </div>

    <div class="card about-sec">
      <h2 class="section-title">데이터 정책</h2>
      <p class="lead note" style="margin:0">자료와 녹음은 분석에만 사용해요. 원본 보존·폐기 주기는 정책 확정 전이에요.</p>
    </div>`;
}

/* ── 시작 ── */
route();
