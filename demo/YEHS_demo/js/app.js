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

/** 말하기(F-17 속도 · F-18 간투어) 결과가 없으면 시연·샘플 stub 으로 채운다. */
let _voiceLiveCache = null;
async function ensureVoicePipelineOut() {
  const hasVoice = !!(nf && nf.pipelineOut
    && nf.pipelineOut.pace && (nf.pipelineOut.pace.slides || []).length
    && nf.pipelineOut.habits);
  if (hasVoice) return nf.pipelineOut;

  /* 시연·샘플 리포트는 실 F-18(LoRA 간투어 태거) 대신 같은 모양의 stub 을 쓴다.
     없으면 말하기 탭이 DATA 폴백으로 떨어져 「자주 쓴 간투어」 카드 자체가 안 나온다. */
  if (isShowcaseDemo() || rSampleMode || (nf && nf.useSample)) {
    const voice = showcaseVoiceStub();
    nf = nf || {};
    nf.pipelineOut = { ...(nf.pipelineOut || {}), ...voice };
    return nf.pipelineOut;
  }

  // 예전 샘플 fixture 경로(useSample 이고 아직 실연을 안 돌린 경우)
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
    const res = await fetch('data/voice_report_live.json', { cache: 'no-store' });
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

function fillerKeywordStats(habits, kind = 'FIL') {
  const spans = (habits && (habits.spans || habits.spans_sample)) || [];
  const count = {};
  spans.filter(s => s.kind === kind).forEach(s => {
    const t = String(s.text || '').trim();
    if (!t) return;
    count[t] = (count[t] || 0) + 1;
  });
  return Object.entries(count)
    .map(([text, n]) => ({ text, n, kind }))
    .sort((a, b) => b.n - a.n || a.text.localeCompare(b.text, 'ko'));
}

function voiceEasyBlocks(pace, habits, report) {
  const slides = (pace && pace.slides) || [];
  const shortCore = slides.filter(s => s.importance === 'core' && s.status === 'short');
  const longOnes = slides.filter(s => s.status === 'long');
  const okCore = slides.filter(s => s.importance === 'core' && s.status === 'ok');
  const fillers = fillerKeywordStats(habits, 'FIL');
  const repeats = fillerKeywordStats(habits, 'REP');
  const target = fmtSec(pace.target_sec);
  const actual = fmtSec(pace.actual_sec);
  let headline = '시간 배분이랑 말하는 습관을 함께 살펴봤어요.';
  if (shortCore.length && longOnes.length) {
    headline = '중요한 슬라이드는 짧게 지나갔고, 어떤 슬라이드는 생각보다 길게 말했어요.';
  } else if (shortCore.length) {
    headline = '중요한 슬라이드에 시간을 조금 더 쓰면 전달력이 살아나요.';
  } else if (longOnes.length) {
    headline = '긴 슬라이드를 조금 줄이면 목표 시간에 더 잘 맞춰져요.';
  } else if (report && report.one_liner) {
    headline = report.one_liner;
  }
  const paceLabel = humanPaceLabel(Math.round(pace.avg_chars_per_min || 0), pace.recommended_cpm);
  const lead = `목표 ${target} 중에 실제로 약 ${actual} 말했어요. 전체 말 속도는 ${paceLabel.short}였어요.`;
  const actions = [];
  if (shortCore.length) {
    actions.push(`핵심인 ${shortCore.map(s => `${s.slide_no}번`).join(', ')} 슬라이드에 시간을 더 써 보세요. 아래 상자를 눌러 각 슬라이드 시간을 확인해요.`);
  }
  if (longOnes.length) {
    const top = [...longOnes].sort((a, b) => (b.delta_sec || 0) - (a.delta_sec || 0)).slice(0, 3);
    actions.push(`${top.map(s => `${s.slide_no}번`).join(', ')} 슬라이드는 길게 말했어요. 세부 설명을 줄이면 좋아요.`);
  }
  if (fillers.length) {
    const topF = fillers.slice(0, 2).map(f => `「${f.text}」`).join(', ');
    actions.push(`자주 나온 간투어 ${topF} 를 줄이려면, 발표 전에 한 번 소리 내어 읽어보세요.`);
  }
  if (!actions.length && Array.isArray(report && report.actions)) {
    actions.push(...report.actions.slice(0, 3));
  }
  return { slides, shortCore, longOnes, okCore, fillers, repeats, headline, lead, target, actual, actions };
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
          <p class="note">회색은 권장, 파랑은 내가 쓴 시간이에요. 핵심 슬라이드는 위에 표시돼요.</p>
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
  const dots = pts.slice(0, -1).map(p => `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="3" fill="#fff" stroke="var(--accent)" stroke-width="2"/>`).join('');
  return `<svg class="growth-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="최근 ${n}회 완성도 추이">
    <defs><linearGradient id="growthFill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="var(--accent)" stop-opacity=".20"/>
      <stop offset="1" stop-color="var(--accent)" stop-opacity="0"/>
    </linearGradient></defs>
    <path class="growth-area" d="${area}" fill="url(#growthFill)"/>
    <path class="growth-line" style="--len:${len.toFixed(0)}" d="${line}" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
    ${dots}
    <circle class="growth-dot-last" cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="5.5" fill="var(--accent)" stroke="#fff" stroke-width="2.5"/>
    <text class="growth-val" x="${last[0].toFixed(1)}" y="${(last[1] - 12).toFixed(1)}" text-anchor="middle">${vals[n - 1]}</text>
  </svg>`;
}

/* ══ 라우팅 ══ */
const routes = {
  '': renderHome, 'new': renderNew, 'report': renderReport, 'qa': renderQa, 'about': renderAbout,
  // 저장된 발표로 이어서 (개발용). 어디에도 링크를 걸지 않는다 — 부스 방문객이
  // 흘러 들어오면 남의 발표 기록을 보게 된다. 주소를 아는 사람만 들어온다.
  'replay': renderReplay,
  // 랜딩은 js/landing.js 가 window 에 붙인다. 호출 시점에 찾으므로 로드 순서를 타지 않는다.
  'landing': () => window.renderLanding(),
  // 개념 그래프 3D 무대 (js/graph3d.js). 데모 경로 밖이라 여기가 죽어도 시연은 돈다.
  'graph': () => window.renderGraph3D(),
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
  /* 샘플 모드는 renderReport() 안에서만 켜져서, 샘플 리포트를 보고 #/qa 로 나가면
     켜진 채로 남았다. reportOut() 이 이 값을 보고 결과를 가리므로 리포트를
     벗어나는 순간 꺼 준다 — 안 그러면 질문 코칭이 제 데이터를 못 읽는다 */
  if (key !== 'report') rSampleMode = false;
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
  syncSideNav(key);
  wireFreshPracticeButtons();
  window.scrollTo(0, 0);
}

/* 지금 어느 칸에 있는지 좌측 내비에 표시한다. 색만으로 말하지 않으려고
   aria-current 를 쓰고 CSS 가 그걸 따라간다 — 스크린리더도 같은 걸 읽는다.
   질문 코칭(#/qa)은 내비에 칸이 없다. 진행 중일 때만 의미가 있어서 링크로
   두면 죽은 칸이 되고, 이어하기는 탑바가 이미 맡는다 — 그동안은 「연습하기」를
   켜 둔다 (같은 발표 흐름 안이다) */
function syncSideNav(key) {
  /* 병아리 넷은 화면마다 바뀌지 않으니 사이드바에 한 번만 심는다.
     홈 본문에 있던 띠를 여기로 옮겼다 — 그 자리에선 화면마다 사라졌다 나타났고,
     왼쪽 칸은 아래쪽이 통째로 비어 있었다 */
  const crew = $('.sidenav-crew');
  if (crew && !crew.childElementCount) crew.innerHTML = crewFacesHtml();
  const here = key === 'qa' ? 'new' : key;
  $$('.sidenav [data-nav]').forEach(a => {
    if (a.dataset.nav === here) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
}

function syncTopbar() {
  const wrap = $('.topbar-right'); if (!wrap) return;
  const qaActive = qa.started && !qa.ended;
  const nfActive = !nf.completed && (nf.step > 0 || nf.gate);
  // 진행 중 세션이 주 버튼을 뺏지 않는다 — 예전엔 진행 중이면 유일한 버튼이
  // 「연습 이어하기」로 바뀌어 새 발표를 시작할 길이 없었다 (2026-08-07 사용자:
  // "연습 이어하기 때문에 처음부터 발표를 할 수가 없네"). 새 발표 연습은 항상
  // 있고, 이어하기는 진행 중일 때 그 옆에 하나 더 생기는 버튼이다.
  const resumeHref = qaActive ? '#/qa' : '#/new';
  wrap.innerHTML = `
    ${qaActive || nfActive ? `<a class="btn btn-secondary btn-sm" href="${resumeHref}">연습 이어하기</a>` : ''}
    <a class="btn btn-primary btn-sm" href="#/new" id="topFresh" data-fresh-practice>새 발표 연습</a>`;
  wireFreshPracticeButtons(wrap);
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

/* ══ 아트보드 스케일 ══════════════════════════════════════════════════
   데스크톱은 1336×1024 한 판을 창에 맞춰 통째로 줄인다. CSS(tablet.css)는
   판의 «안» 만 알고, 창과의 비율은 이 함수 하나가 정한다.

   창마다 요소를 제각각 압축하지 않는 이유: 이 화면은 발표 자료와 분석을 나란히
   놓고 대조하는 자리다. 노트북에서는 시간 분배 막대가 두 줄로 접히고 모니터에서는
   한 줄이면, 「어디를 보라」를 기기마다 새로 배워야 한다.

   900px 미만은 1 로 둬서 기존 모바일 레이아웃을 그대로 쓴다 — tablet.css 의
   아트보드 규칙도 같은 경계(@media (min-width: 900px))에서 켜진다. 두 값이
   어긋나면 판은 안 켜졌는데 스케일만 걸려서 화면이 반쪽으로 줄어든다. */
const ARTBOARD_W = 1336, ARTBOARD_H = 1024, ARTBOARD_MIN_W = 900;
function syncArtboard() {
  const desktop = window.innerWidth >= ARTBOARD_MIN_W;
  const scale = desktop
    ? Math.min(window.innerWidth / ARTBOARD_W, window.innerHeight / ARTBOARD_H)
    : 1;
  document.documentElement.style.setProperty('--artboard-scale', String(scale));
}
syncArtboard();
addEventListener('resize', syncArtboard);

/* ══ 홈 ══ */
/* 홈 첫 카드 — 네 모델이 각자 맡은 일 (04_screens.md 「홈 첫 화면」).
   예전엔 여기가 「최근 발표 완성도 86점 · 5회 동안 25 올랐어요」였다. 처음 온
   사람은 발표를 한 번도 안 했는데 샘플 점수가 자기 기록인 척했고, 서로 다른
   발표의 점수를 한 선으로 이어 "올랐다"고 말했다. 상황별로 가중치가 다르니
   애초에 비교 가능한 숫자가 아니다.

   대신 제품 구성을 보여준다 — 사용자 데이터가 아니라서 첫날에도 꽉 차고,
   비어 있을 수가 없다. 역할 문구는 파이프라인의 실제 담당과 1:1 이다. */
const HOME_CREW = [
  { id: 'midm',   name: '믿:음',  role: '대조', by: 'KT',      does: '자료와 어긋난 곳을 찾아요' },
  { id: 'solar',  name: '쏠라',   role: '자료', by: 'Upstage', does: '자료를 처음부터 끝까지 읽어요' },
  { id: 'ax',     name: '엑씨',   role: '듣기', by: 'SKT',     does: '발표를 귀로 들어요' },
  { id: 'exaone', name: '엑사원', role: '인정', by: 'LG',      does: '잘 설명한 개념을 짚어줘요' },
];

/* ══ 홈의 주인공: 다음에 고칠 것 하나 ═══════════════════════════════════
   홈이 「지난 발표 목록」이면 아카이브다. 부스에서 처음 보는 사람에게 필요한 건
   기록이 아니라 다음 행동이다 — 이 카드가 그 자리를 맡는다.

   지어내지 않는 것이 이 카드의 전부다. 「+8점 기대」·「지난 연습 대비 평균 +8」
   같은 숫자는 근거가 없다 (상황별 채점 가중치가 달라 발표 간 비교가 성립하지
   않는다 — 홈에서 점수 카드를 지운 이유가 그것이다). 그래서 새 문장을 만들지
   않고, 이미 실데이터로 처방을 만들고 있는 두 곳(F-12 흐름 · F-17/18 음성)의
   문장을 그대로 승격한다. 둘 다 조용하면 채점표에서 근거만 조립한다.

   카드에 「믿:음이 찾았어요」 같은 주어를 쓰지 않는다. SCORE_CHICK 과
   HOME_CREW 의 역할 배정이 서로 어긋나 있어서(쏠라=자료 / delivery=solar),
   말로 주장하면 둘 중 하나가 거짓이 된다. 얼굴만 리포트와 같은 것으로 맞춘다. */

/** 카드가 그릴 네 상태. 어느 상태에서도 카드 크기는 같고 안이 실데이터로 찬다 */
function homeStage() {
  const out = (nf && nf.pipelineOut) || null;
  // 부분 성공이 정상이다. 흐름·음성·채점표 중 하나만 살아도 고칠 것을 말할 수 있다
  if (out && (out.flow || out.pace || out.score)) return 'analyzed';
  if (nf && (nf.pipelineError || (pipelineFinished() && out))) return 'failed';
  if (nf && (nf.fileName || nf.slideDocMeta)) return 'uploaded';
  return 'empty';
}

/** 채점표에서 「먼저 볼 축」 하나. 처방 문장이 없으므로 지어내지 않고 근거만 편다 */
function rubricWeakest(sc) {
  const live = ((sc && sc.clusters) || []).filter(c => c.status === 'scored');
  if (!live.length) return null;
  /* 회복 여지 = 남은 점수 × 이 발표에서의 실제 비중. contracts 가 「살아 있는
     클러스터의 effective_weight 합 = 1.0」을 보증하므로 총점과 같은 단위다.
     정렬에만 쓰고 화면에는 내지 않는다 — 흐름·음성에는 대응 수치가 없어서
     소스마다 카드 모양이 달라지고, 숫자를 내면 주인공이 둘이 된다 */
  const room = c => (c.effective_weight || 0) * (100 - (c.average || 0));
  const top = [...live].sort((a, b) => room(b) - room(a))[0];
  if (!top || room(top) <= 0) return null;
  // 그 축에서 제일 낮은 항목의 근거 한 줄. 없으면 근거 줄을 안 그린다
  const nos = new Set(top.item_nos || []);
  const worst = ((sc && sc.items) || [])
    .filter(it => nos.has(it.no) && it.status === 'scored' && (it.evidence || it.note))
    .sort((a, b) => (a.score || 0) - (b.score || 0))[0];
  return {
    source: 'rubric', who: SCORE_CHICK[top.key] || 'solar', tab: 1, label: '채점표',
    headline: `「${top.name}」부터 보면 좋아요`,
    action: '',
    hint: DIM_HINT[top.name] || '',
    evidence: (worst && (worst.evidence || worst.note)) || '',
  };
}

/**
 * 다음에 고칠 것 하나를 고른다.
 *
 * 순서가 자의적이지 않다. 흐름과 음성은 `{headline, action}` 을 **이미 실데이터로
 * 반환하고**, 채점표는 처방이 없고 DIM_HINT 라는 *질문*만 있다. 「다음에 고칠 것」이
 * 되려면 「이렇게 하세요」가 있어야 하므로 처방을 가진 쪽이 앞선다.
 */
function nextFix() {
  const out = (nf && nf.pipelineOut) || null;
  if (!out) return null;

  // 1) 논리 흐름 — flowVerdict 가 FLOW_PRIORITY 로 이미 1건을 뽑고 위치 문장까지 만든다
  const flowBad = ((out.flow && out.flow.issues) || [])
    .some(i => flowIssueRank(i.kind) < FLOW_PRIORITY.length);
  if (flowBad) {
    const v = flowVerdict(out.flow);
    if (v) return { source: 'flow', who: 'midm', tab: 3, label: '논리 흐름', ...v };
  }

  // 2) 음성 습관 — voiceEasyBlocks 는 pace 없이 못 돈다(target_sec 를 읽는다)
  if (out.pace) {
    const easy = voiceEasyBlocks(out.pace, out.habits, out.report);
    const v = voiceVerdict(easy, out.pace);
    // 마지막 가지는 「모두 안정적이었어요」 칭찬이라 고칠 것이 아니다 — 4번으로 넘긴다
    if (v && !/안정적이었어요/.test(v.headline)) {
      return { source: 'voice', who: 'solar', tab: 4, label: '음성 습관', ...v };
    }
  }

  // 3) 채점표 — 처방은 없고 근거만 있다
  const weak = rubricWeakest(out.score);
  if (weak) return weak;

  // 4) 고칠 것이 없다. 「고칠 것」이라 부르면 그게 거짓말이라 라벨을 바꾼다
  const keep = (out.flow && flowVerdict(out.flow))
    || (out.pace && voiceVerdict(voiceEasyBlocks(out.pace, out.habits, out.report), out.pace));
  return keep ? { source: 'keep', who: 'exaone', tab: 0, label: '', ...keep } : null;
}

/** 분석이 통째로 실패했을 때 원인 한 줄. 실패를 성공처럼 그리지 않는다 */
function homeFailNote() {
  const out = (nf && nf.pipelineOut) || {};
  const STAGE = { graph: '개념 그래프', alignment: '정합 판정', flow: '흐름 비교', score: '채점' };
  const where = STAGE[out.failedStage] || '';
  const why = nf.pipelineError || out.conceptsError || nf.pipelineDetail || '';
  if (where && why) return `${where}에서 멈췄어요 — ${why}`;
  return why || (where ? `${where}에서 멈췄어요.` : '분석을 끝내지 못했어요.');
}

/** 네 모델 좌석. 발표 전에는 이 넷이 카드를 채운다 */
function crewSeatsHtml() {
  return HOME_CREW.map(c => `
    <li class="t-crew-one">
      <span class="t-crew-bird ch-seat" data-mood="happy" aria-hidden="true">${Chatter.chickSvg(c.id)}</span>
      <b>${c.name}</b>
      <span class="t-crew-role">${c.role}</span>
      <small>${escapeHtml(c.does)}</small>
      <span class="t-crew-by">${c.by}</span>
    </li>`).join('');
}

function nextCardHtml() {
  // 캐릭터는 얹는 층이다. Chatter 가 아직 안 붙었으면 카드를 통째로 접는다
  if (!window.Chatter || !Chatter.chickSvg) return '';
  const stage = homeStage();

  if (stage === 'empty' || stage === 'uploaded') {
    /* 진단이 아니라 예고다. 둘 다 실데이터로 찬다 —
       ①은 제품 사실(네 모델), ②는 사용자 사실(방금 올린 내 파일) */
    const meta = (nf && nf.slideDocMeta) || {};
    const name = meta.file_name || (nf && nf.fileName) || '';
    const lead = stage === 'uploaded' && name
      ? `${escapeHtml(name)}${meta.total_slides ? ` · 슬라이드 ${meta.total_slides}개` : ''}`
      : '네 모델이 각자 맡은 일로 발표를 봐요';
    const tail = stage === 'uploaded'
      ? '연습을 마치면 이 넷이 본 것 중 제일 급한 하나를 여기 띄워요'
      : '발표를 마치면 이 자리에 오늘 고칠 것 하나가 떠요';
    return `
      <section class="t-card t-next-card is-empty" aria-label="발표를 보는 네 모델">
        <p class="t-label">${lead}</p>
        <ul class="t-crew">${crewSeatsHtml()}</ul>
        <p class="t-caption">${tail}</p>
      </section>`;
  }

  const fix = nextFix();
  if (stage === 'failed' || !fix) {
    return `
      <section class="t-card t-next-card is-failed" aria-label="분석 결과">
        ${stageAccidentHtml(homeFailNote())}
      </section>`;
  }

  const keep = fix.source === 'keep';
  const label = keep ? '이번엔 지킬 것' : `다음에 고칠 것${fix.label ? ` · ${fix.label}` : ''}`;
  // 부분 실패면 살아남은 것으로 카드를 그리되 사고를 숨기지 않는다
  const partial = (nf.pipelineOut && nf.pipelineOut.failedStage) ? homeFailNote() : '';
  return `
    <section class="t-card t-next-card" data-go="#/report" data-tab="${fix.tab}"
             role="button" tabindex="0" aria-label="${escapeHtml(label)}">
      <p class="t-label">
        <span class="t-next-who ch-seat" data-mood="${keep ? 'happy' : 'curious'}"
              aria-hidden="true">${Chatter.chickSvg(fix.who)}</span>
        ${label}
      </p>
      <b class="t-next-head">${escapeHtml(fix.headline)}</b>
      ${fix.action ? `<p class="t-next-act">${escapeHtml(fix.action)}</p>` : ''}
      ${fix.hint ? `<p class="t-next-hint">${escapeHtml(fix.hint)}</p>` : ''}
      ${fix.evidence ? `<p class="t-next-ev">“${escapeHtml(fix.evidence)}”</p>` : ''}
      ${partial ? `<p class="t-caption">${escapeHtml(partial)}</p>` : ''}
      <span class="t-chev" aria-hidden="true">›</span>
    </section>`;
}

function renderHome() {
  app.className = 'home';
  const qaActive = qa.started && !qa.ended;
  const nfActive = !nf.completed && (nf.step > 0 || nf.gate);
  const resume = qaActive
    ? { href: '#/qa', tag: '질문 코칭', title: `${qa.aud || '교수님'}${josa(qa.aud || '교수님', '과', '와')} 하던 질문 코칭을 이어서 할까요?` }
    : nfActive
      ? { href: '#/new', tag: '발표 연습', title: `${NF_STEPS[nf.step]}부터 이어서 할까요?` }
      : null;

  /* 카드를 늘어놓지 않는다. 도구의 홈은 「지금 할 일 한 줄 + 표」다.
     2단 대시보드도 버렸다 — 발표가 5건뿐인데 칸을 둘로 가르면 양쪽 다 빈다.
     세로 예산 764px 안에서 표가 화면의 주인공이 되게 한다 (MVP_SPEC §5.1) */
  const gm = loadGame();
  const shows = (window.Playbill && Playbill.load) ? Playbill.load() : [];

  app.innerHTML = `
    <header class="h-head">
      <h1>내 발표</h1>
      ${(gm.days || []).length ? `<span class="h-sub">${dayStreak(gm.days)}일 연속 · 레벨 ${gameLevel(gm.xp)}</span>` : ''}
      <p class="h-lead">발표 자료와 실제로 말한 내용을 함께 보고, 다음 연습에서 고칠 곳을 찾아요.</p>
    </header>

    ${resume ? `
    <a class="h-resume" href="${resume.href}">
      <span class="h-resume-tag">${resume.tag}</span>
      <b>${escapeHtml(resume.title)}</b>
      <span class="t-chev" aria-hidden="true">›</span>
    </a>` : ''}

    ${nextBandHtml()}

    ${shows.length ? `
    <section class="h-sec">
      <div class="h-sec-head"><h2>지난 발표</h2><span>${shows.length}건</span></div>
      <div class="h-wall">${window.Playbill.wallHtml()}</div>
    </section>` : ''}

    <section class="h-sec">
      <div class="h-sec-head">
        <h2>${isShowcaseDemo() ? '연습 기록' : '샘플 발표'}</h2><span>${DATA.sessions.length}건</span>
      </div>
      ${isShowcaseDemo() ? '' : '<p class="h-sec-note">열어 보라고 넣어 둔 발표예요. 실제 리포트와 같은 화면이 나와요.</p>'}
      <table class="h-table">
        <thead>
          <tr><th>제목</th><th>상황</th><th class="num">슬라이드</th><th class="num">완성도</th><th></th></tr>
        </thead>
        <tbody>
          ${DATA.sessions.map(s => `
          <tr tabindex="0" role="link" data-go="#/report/${s.id}">
            <td class="h-t-title">${escapeHtml(s.title)}${isShowcaseDemo() ? '' : '<span class="t-tag">샘플</span>'}</td>
            <td class="h-t-occ">${escapeHtml(s.occasion)}</td>
            <td class="num h-t-dim">${s.slides}</td>
            <td class="num h-t-score">${s.score}</td>
            <td class="h-t-go" aria-hidden="true">›</td>
          </tr>`).join('')}
        </tbody>
      </table>
    </section>

`;

  $$('[data-go]').forEach(r => {
    const go = () => {
      if (r.dataset.tab) rTab = Number(r.dataset.tab) || 0;
      location.hash = r.dataset.go;
    };
    r.addEventListener('click', go);
    if (r.tagName !== 'BUTTON') {
      r.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
      });
    }
  });
  if (window.Playbill) window.Playbill.paintWall(app);
}

/** 크루 얼굴만 한 줄. 4열 격자 카드는 홈의 절반을 먹어서 마스코트가 주인공이 됐다 */
function crewFacesHtml() {
  if (!window.Chatter || !Chatter.chickSvg) return '';
  return HOME_CREW.map(c =>
    `<span class="h-crew-bird ch-seat" data-mood="happy">${Chatter.chickSvg(c.id)}</span>`).join('');
}

/* 홈 맨 위 한 줄. 카드가 아니라 띠다 — 「지금 할 일」은 화면에 하나뿐이어야 한다 */
function nextBandHtml() {
  const stage = homeStage();

  if (stage === 'empty') {
    return `
      <section class="h-start">
        <b>발표 자료를 올리면 시작해요</b>
        <p>자료에 있는 개념과 실제로 말한 것을 하나씩 대조해서, 설명이 빠진 곳을 짚어줘요.</p>
        <span class="h-start-act">
          <a class="btn btn-primary btn-sm" href="#/new" data-fresh-practice>자료 올리기</a>
          <a class="h-start-alt" href="#/report/sample-investor">${isShowcaseDemo() ? '최근 리포트 보기 →' : '샘플 리포트 먼저 보기 →'}</a>
        </span>
      </section>`;
  }

  if (stage === 'uploaded') {
    const meta = (nf && nf.slideDocMeta) || {};
    const name = meta.file_name || (nf && nf.fileName) || '올린 자료';
    return `
      <section class="h-start">
        <b>${escapeHtml(name)}${meta.total_slides ? ` · 슬라이드 ${meta.total_slides}개` : ''}</b>
        <p>연습을 마치면 네 모델이 본 것 중 제일 급한 하나를 여기에 띄워요.</p>
        <span class="h-start-act"><a class="btn btn-primary btn-sm" href="#/new">이어서 연습하기</a></span>
      </section>`;
  }

  const fix = nextFix();
  if (stage === 'failed' || !fix) {
    return `<section class="h-start is-failed">${stageAccidentHtml(homeFailNote())}</section>`;
  }

  const keep = fix.source === 'keep';
  const partial = (nf.pipelineOut && nf.pipelineOut.failedStage) ? homeFailNote() : '';
  return `
    <section class="h-next${keep ? ' is-keep' : ''}" data-go="#/report" data-tab="${fix.tab}"
             role="link" tabindex="0">
      <span class="h-next-label">
        <span class="h-next-who ch-seat" data-mood="${keep ? 'happy' : 'curious'}"
              aria-hidden="true">${Chatter && Chatter.chickSvg ? Chatter.chickSvg(fix.who) : ''}</span>
        ${keep ? '이번엔 지킬 것' : '다음에 고칠 것'}${fix.label ? ` · ${fix.label}` : ''}
      </span>
      <b class="h-next-head">${escapeHtml(fix.headline)}</b>
      ${fix.action ? `<p class="h-next-act">${escapeHtml(fix.action)}</p>` : ''}
      ${fix.hint ? `<p class="h-next-hint">${escapeHtml(fix.hint)}</p>` : ''}
      ${fix.evidence ? `<p class="h-next-ev">“${escapeHtml(fix.evidence)}”</p>` : ''}
      ${partial ? `<p class="h-next-hint">${escapeHtml(partial)}</p>` : ''}
      <span class="t-chev" aria-hidden="true">›</span>
    </section>`;
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

/**
 * 돌아가고 있는 리허설 녹음을 **실제로 멈춘다.**
 *
 * 여태 `resetNf()` 는 `ccRuntime = null` 로 **참조만 버렸다.** 그런데 그 객체가
 * MediaRecorder 와 마이크 스트림과 자기 타이머를 들고 있어서, 참조를 버려도
 * 녹음은 계속 돈다 — 마이크가 안 꺼지고(탭의 녹음 표시가 켜진 채 남는다),
 * onTick 이 1초마다 방금 초기화한 nf 에 `nf.sec` 를 도로 써 넣는다. 그래서
 * 발표 중에 「처음부터」를 눌러도 처음으로 돌아간 것처럼 동작하지 않았다
 * (2026-08-08 사용자 제보).
 *
 * `finish()` 가 `RehearsalRecorder.stop()` 을 타고 트랙까지 놓아 준다
 * (`chuckchuck/sdk/rehearsal-recorder.js`). 결과 Blob 은 버린다 — 버리는 테이크다.
 */
/* ─── 시연·발표용 쇼케이스 모드 ───────────────────────────────────────────
   올린 PPT·리허설 녹음은 무대 연출로 그대로 쓰고,
   분석·질문 코칭·리포트 결과만 DATA 쇼케이스 더미(sample-investor)로 고정한다. */
const SHOWCASE_DEMO = true;
const SHOWCASE_REPORT_HASH = '#/report/sample-investor';
/* 시연·샘플 리포트용 슬라이드 원본. DATA.slideImages 가 비어 있어도 이 PDF 로 그린다. */
const SHOWCASE_SLIDE_PDF = 'assets/samples/investor_preview.pdf';
let showcasePipeGen = 0;
function isShowcaseDemo() {
  return SHOWCASE_DEMO || !!(nf && nf.showcaseDemo);
}
function showcaseReportHref() {
  return SHOWCASE_REPORT_HASH;
}

function stopLiveRehearsal() {
  const rt = ccRuntime;
  if (!rt || typeof rt.finish !== 'function') return;
  ccRuntime = null;   // 먼저 끊는다 — finish() 를 기다리는 사이 또 부르지 않게
  try {
    Promise.resolve(rt.finish()).catch(() => { /* 이미 멈춘 뒤 */ });
  } catch (_) { /* 이미 멈춘 뒤 */ }
}

function resetNf() {
  // 참조를 버리기 전에 멈춘다. 순서가 바뀌면 멈출 대상을 잃는다.
  stopLiveRehearsal();
  showcasePipeGen += 1;
  nf = { step: 0, gate: null, occ: null, ctx: '', min: 10,
         mic: 'idle', sec: 0, slide: 1, visits: { 1: 1 }, log: [], done: 0, completed: false,
         fileName: '', sparseSlides: [], parseError: null, useSample: false,
         showcaseDemo: SHOWCASE_DEMO,
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

/**
 * 시연 말하기(F-17·F-18) stub.
 * 실서비스에선 LoRA 간투어 태거(f18)가 habits.spans 를 채우고, 말하기 탭이
 * 「자주 쓴 간투어」로 그린다. 시연은 같은 계약의 더미를 넣어 카드가 비지 않게 한다.
 */
function showcaseVoiceStub() {
  const dur = (DATA.session && DATA.session.durationSec) || 564;
  const target = (DATA.session && DATA.session.targetSec) || SAMPLE_TARGET_SEC || 600;
  const paceRows = DATA.pace || [];
  const n = Math.max(1, paceRows.length);
  const slides = paceRows.map((p, i) => {
    const no = p[1];
    const cpm = p[2] || 0;
    const fast = !!p[3];
    /* 11번(상위 그룹 비교)은 짧게, 4번(복리)은 길게 — DATA 서사와 동일 */
    let actual = Math.round(dur / n);
    if (no === 11) actual = 35;
    if (no === 4) actual = 95;
    let status = 'ok';
    if (no === 11) status = 'short';
    else if (no === 4) status = 'long';
    else if (fast) status = 'fast';
    return {
      slide_no: no,
      title: p[0],
      chars_per_min: cpm,
      actual_sec: actual,
      recommended_sec: Math.round(target / n),
      status,
      importance: (no === 11 || no === 6 || no === 3) ? 'core' : 'support',
    };
  });
  const sections = (DATA.timeAlloc || []).map((r) => {
    const label = String(r[3] || '');
    return {
      name: r[0],
      recommended_sec: Math.round(target * (r[1] || 0) / 100),
      actual_sec: Math.round(dur * (r[2] || 0) / 100),
      status: label.includes('부족') ? 'short' : (label.includes('초과') ? 'long' : 'ok'),
    };
  });
  const spans = [
    { kind: 'FIL', text: '그', start_sec: 48, end_sec: 48.4, slide_no: 3 },
    { kind: 'FIL', text: '그', start_sec: 52, end_sec: 52.3, slide_no: 3 },
    { kind: 'FIL', text: '음', start_sec: 118, end_sec: 118.5, slide_no: 5 },
    { kind: 'FIL', text: '그', start_sec: 190, end_sec: 190.3, slide_no: 6 },
    { kind: 'FIL', text: '이제', start_sec: 210, end_sec: 210.4, slide_no: 6 },
    { kind: 'FIL', text: '그', start_sec: 255, end_sec: 255.3, slide_no: 8 },
    { kind: 'FIL', text: '음', start_sec: 268, end_sec: 268.6, slide_no: 8 },
    { kind: 'FIL', text: '그냥', start_sec: 310, end_sec: 310.5, slide_no: 9 },
    { kind: 'FIL', text: '그', start_sec: 420, end_sec: 420.3, slide_no: 12 },
    { kind: 'REP', text: '그래서 그래서', start_sec: 200, end_sec: 201, slide_no: 6 },
    { kind: 'REP', text: '결국 결국', start_sec: 500, end_sec: 501, slide_no: 14 },
  ];
  return {
    pace: {
      target_sec: target,
      actual_sec: dur,
      avg_chars_per_min: (DATA.paceStats && DATA.paceStats.avg) || 328,
      max_chars_per_min: (DATA.paceStats && DATA.paceStats.max) || 430,
      max_slide_no: 11,
      recommended_cpm: (DATA.paceStats && DATA.paceStats.rec) || '300~350',
      slides,
      sections,
      tips: ['11번 상위 그룹 비교는 35초로 짧고, 4번 복리 설명은 길어요.'],
    },
    habits: {
      by_slide: [
        { slide_no: 3, repeat_cnt: 0, filler_cnt: 2, pause_cnt: 0 },
        { slide_no: 6, repeat_cnt: 1, filler_cnt: 2, pause_cnt: 0 },
        { slide_no: 8, repeat_cnt: 0, filler_cnt: 2, pause_cnt: 1 },
        { slide_no: 11, repeat_cnt: 0, filler_cnt: 0, pause_cnt: 0 },
      ],
      repeat_cnt: 2,
      filler_cnt: 9,
      pause_cnt: 1,
      provider: 'showcase-lora',
      tips: ['원인 설명 구간(3·6·8번)에 「그」「음」이 몰려 있어요.'],
      n_spans: spans.length,
      spans_sample: spans,
      spans,
    },
    report: {
      one_liner: (DATA.session && DATA.session.oneLiner)
        || '과잉 매매 설명은 좋았지만, 결론 근거인 상위 그룹 비교가 짧았어요.',
    },
  };
}

/**
 * 분석 연출(F-11 리빌·스텝4 검증 로그)용 파이프라인 stub.
 * 리포트 본문은 rSampleMode 가 DATA 를 쓰고, 여기 stub 은 그 직전 화면이
 * 같은 서사로 보이게 그래프·정합·발화 매핑을 채운다.
 */
function showcasePipelineStub() {
  const titles = DATA.slideTitles || [];
  const tree = DATA.tree || [];
  const dur = (DATA.session && DATA.session.durationSec) || nf.sec || 564;

  const verdictOf = (st) => (
    st === 'ok' ? 'aligned'
      : st === 'mid' ? 'partial'
        : st === 'ct' ? 'contradiction'
          : st === 'om' ? 'justified_skip'
            : 'missing'
  );
  const speechOf = (st, w) => (
    st === 'ok' ? Math.max(0.55, w)
      : st === 'mid' ? Math.max(0.18, w * 0.45)
        : st === 'ct' ? Math.max(0.35, w * 0.6)
          : 0
  );

  /* 리빌 무대(viewBox 380×418) 손배치 좌표 — 내장 mock 이 그랬듯 사람이 자리를
     잡아 줘야 원이 안 쪼그라들고 라벨도 안 잘린다. 자동 배치는 줄 세우기만 한다. */
  const revealPos = {
    gap: [190, 64], compound: [66, 58], myth: [312, 74],
    overtrade: [86, 172], timing: [196, 210], lossav: [306, 176],
    cost: [46, 282], rules: [140, 300], concentrate: [330, 288],
    checklist: [232, 356],
  };
  /* 원 안 마이크로 카피 — 자료(PPT)·리포트 근거의 수치를 그대로 옮긴다.
     이름은 원 밖 라벨이 말하고, 원 안은 그 개념의 핵심 숫자 하나만 말한다. */
  const revealSub = {
    gap: '연 −4.8%p',          // S03 개인 평균 vs 지수
    overtrade: '회전율↑ 수익↓', // S06 단조 감소
    timing: '8.7%→1.5%',        // S07 20일 놓치면
    lossav: '52일 vs 187일',    // S08 수익·손실 보유 기간
    concentrate: '1.2%→6.3%',   // S09 분산 시 평균
    cost: '확정 비용',           // S10 유일한 통제 변수
    rules: '71% vs 18%',        // S11 상·하위 매도규칙 보유율
    myth: '공부≠수익',           // S12 자료가 깨는 오해
    checklist: '오늘 정할 값',    // S13 실행 항목
    compound: '10년 누적',       // S04 배경 예시
  };
  const nodes = tree.map((t) => ({
    id: t.id,
    label: t.label,
    slide_nos: [slideNumber(t.slide) || 1],
    summary: t.why || t.label,
    importance: (t.w || 0) >= 0.8 ? 'core' : 'support',
    weight: t.w || 0.5,
    parent_id: t.parent || null,
    depth: t.depth || 1,
    x: revealPos[t.id] ? revealPos[t.id][0] : undefined,
    y: revealPos[t.id] ? revealPos[t.id][1] : undefined,
    sub: revealSub[t.id] || undefined,
  }));
  const idSet = new Set(nodes.map((n) => n.id));
  const edges = [];
  tree.forEach((t) => {
    if (t.parent && idSet.has(t.parent) && idSet.has(t.id)) {
      edges.push({ from: t.parent, to: t.id, kind: 'parent' });
    }
  });
  /* 원인끼리·결론 근거끼리 연결을 그려 개념들이 얽혀 있다는 걸 보여준다
     (2026-08-12 사용자: 트리처럼 보이니 간선이 늘어도 상관없다). 부모-자식
     간선과 겹치는 세 쌍(overtrade-rules, rules-checklist, gap-myth)은 이미
     parent 로 그려지므로 여기 다시 넣지 않는다 — 같은 두 점을 잇는 선을
     둘 그리면 하나는 숨어 보이지 않을 뿐 새 연결이 아니다. */
  const relates = [
    ['gap', 'overtrade'],       // 현황 → 가장 큰 원인
    ['overtrade', 'timing'],    // 「가장 큰 두 개는 언제의 문제」
    ['overtrade', 'cost'], ['timing', 'lossav'], ['lossav', 'concentrate'],
    // 격차의 원인 다섯이 gap 하나에만 매달려 있지 않다는 것
    ['gap', 'timing'], ['gap', 'lossav'], ['gap', 'concentrate'], ['gap', 'cost'],
    // 오해가 다른 원인으로 이어지는 것, 비용·체크리스트가 다른 원인과도 얽히는 것
    ['myth', 'overtrade'], ['myth', 'concentrate'],
    ['cost', 'rules'], ['checklist', 'cost'], ['checklist', 'timing'],
    ['compound', 'cost'],
  ];
  relates.forEach(([a, b]) => {
    if (idSet.has(a) && idSet.has(b)) edges.push({ from: a, to: b, kind: 'relates' });
  });

  const items = tree
    .filter((t) => t.status && t.status !== 'none')
    .map((t) => {
      const verdict = verdictOf(t.status);
      const sw = speechOf(t.status, t.w || 0.5);
      const first = t.evTime ? (() => {
        const m = String(t.evTime).match(/^(\d+):(\d+)/);
        return m ? (+m[1] * 60 + +m[2]) : null;
      })() : null;
      return {
        node_id: t.id,
        verdict,
        speech_weight: sw,
        speech_basis: {
          speech_sec: Math.round(sw * dur * 0.35),
          time_share: Math.min(0.95, sw * 0.8),
          mention_count: verdict === 'missing' ? 0 : (t.status === 'ok' ? 4 : 1),
          mentioned_slide_count: verdict === 'missing' ? 0 : 1,
          first_mention_sec: first,
        },
        doc_weight: t.w || 0.5,
        evidence: (t.ev || t.spokeSays || '').replace(/^“|”$/g, ''),
        note: t.why || '',
        /* F-11 suggestion — 요약 탭 트로피·판정 탭 「이렇게 말해보세요」가 이걸 읽는다 */
        suggestion: t.fix || '',
      };
    });

  const counts = { aligned: 0, partial: 0, missing: 0, contradiction: 0, justified_skip: 0 };
  items.forEach((i) => { counts[i.verdict] = (counts[i.verdict] || 0) + 1; });
  // 실 API 와 같게 justified_skip 은 커버리지 분모에서 뺀다.
  // 언급만(partial)은 절반만 설명한 것으로 센다 — 리포트 mid 와 같은 감각.
  const scored = items.filter((i) => i.verdict !== 'justified_skip');
  const alignedW = scored.reduce((s, i) => {
    if (i.verdict === 'aligned') return s + (i.doc_weight || 0);
    if (i.verdict === 'partial') return s + (i.doc_weight || 0) * 0.5;
    return s;
  }, 0);
  const totalW = scored.reduce((s, i) => s + (i.doc_weight || 0), 0) || 1;

  /* 말로 이은 연결 — 양쪽이 다 aligned 일 때만 세면 mid→partial 뒤엔 1개만 남아
     10%가 된다. 시연 서사(원인 구조→과잉 매매, 과잉↔비용, 언제 문제 두 축)에
     맞는 연결을 명시하고, 언급만(partial) 끝점도 허용한다. */
  const spokenCue = {
    'gap|overtrade': '그래서 원인을 행동에서 찾아야 합니다. 그중 첫째가 과잉 매매예요',
    'overtrade|timing': '가장 큰 두 개는 언제의 문제입니다',
    'overtrade|cost': '비용은 확정인데 수익은 불확실합니다',
    'lossav|concentrate': '다음은 집중 투자입니다',
  };
  const speech_edges = edges
    .filter((e) => e.kind === 'parent' || e.kind === 'relates')
    .filter((e) => {
      const direct = e.from + '|' + e.to;
      const key = Object.prototype.hasOwnProperty.call(spokenCue, direct)
        ? direct
        : [e.from, e.to].sort().join('|');
      // 시연용으로 고른 연결만 — 자동 전량 허용하면 누락 다리가 살아있는 것처럼 보인다
      return Object.prototype.hasOwnProperty.call(spokenCue, key);
    })
    .map((e) => {
      const direct = e.from + '|' + e.to;
      const key = Object.prototype.hasOwnProperty.call(spokenCue, direct)
        ? direct
        : [e.from, e.to].sort().join('|');
      return {
        from: e.from,
        to: e.to,
        cue: spokenCue[key] || '발표에서 두 개념을 이어서 설명했어요',
        in_graph: true,
      };
    });

  // 슬라이드별 발화 — 리포트 tree 근거를 장에 붙이고,
  // 4번(복리)은 길게·11번(상위 그룹 비교)은 짧게 잡아 속도 서사와 맞춘다
  const byNode = {};
  tree.forEach((t) => {
    const sn = slideNumber(t.slide) || 0;
    if (!sn) return;
    (byNode[sn] || (byNode[sn] = [])).push(t);
  });
  const nSlide = Math.max(titles.length, 1);
  const slideWeight = (no) => {
    if (no === 4) return 2.15;   // 복리 효과 — 권장의 두 배(~79초)
    if (no === 11) return 0.96;  // 상위 그룹 비교 — 리포트·타임라인과 같이 ~35초
    if (no === 1 || no === nSlide) return 0.65;
    if (no === 3 || no === 6 || no === 13) return 1.15;
    return 1;
  };
  const weights = titles.map((_, i) => slideWeight(i + 1));
  const wSum = weights.reduce((a, b) => a + b, 0) || 1;
  let cursor = 0;
  const by_slide = titles.map((title, i) => {
    const no = i + 1;
    const span = (weights[i] / wSum) * dur;
    const start = Math.round(cursor * 10) / 10;
    cursor += span;
    const end = i === nSlide - 1 ? dur : Math.round(cursor * 10) / 10;
    const nodesHere = byNode[no] || [];
    /* 누락·생략 노드의 ev 는 코칭 메모라 발화가 아니다. 말한 것만 전사에 넣는다. */
    const quotes = nodesHere.map((t) => {
      if (t.status === 'ct') return String(t.spokeSays || '').replace(/^“|”$/g, '').trim();
      if (t.status === 'ok' || t.status === 'mid') {
        return String(t.ev || '').replace(/^“|”$/g, '').trim();
      }
      return '';
    }).filter(Boolean);
    let text;
    if (quotes.length) text = quotes.join(' ');
    else if (no === 1) text = `안녕하세요. 오늘은 ${DATA.session.title}에 대해 말씀드리겠습니다.`;
    else if (no === 2) text = '결론부터 말씀드리면, 격차는 종목 선정이 아니라 행동에서 만들어집니다.';
    else if (no === 4) text = '연 4.8%p 차이가 10년 뒤에 얼마나 벌어지는지, 복리로 풀어보면… 1년 차엔 48만 원, 그런데 10년 뒤에는…';
    else if (no === 5) text = '원인은 다섯 가지 행동 요인으로 나뉩니다. 종목 선정은 목록에 없어요.';
    else if (no === 7) text = '타이밍 실패도 원인 중 하나인데요. 표가 나와 있습니다. 다음으로 넘어갈게요.';
    else if (no === 11) text = '상위와 하위 그룹을 비교한 표입니다. 다음으로 넘어가겠습니다.';
    else if (no === 14) text = '무엇을 살까보다, 얼마나 자주 팔까가 결과를 갈랐습니다.';
    else if (no === nSlide) text = '이상으로 발표를 마치겠습니다. 질문 받겠습니다.';
    else text = `${title}에 대해 이어서 설명하겠습니다.`;
    return { slide_no: no, visit: 1, start_sec: start, end_sec: end, text, words: [] };
  });

  const conceptBySlide = {};
  tree.forEach((t) => {
    const sn = slideNumber(t.slide) || 0;
    if (!sn) return;
    (conceptBySlide[sn] || (conceptBySlide[sn] = [])).push(t.label);
  });
  // slideMainNode 로 보조 매핑
  Object.entries(DATA.slideMainNode || {}).forEach(([sn, id]) => {
    const n = tree.find((t) => t.id === id);
    if (!n) return;
    const k = +sn;
    const arr = conceptBySlide[k] || (conceptBySlide[k] = []);
    if (!arr.includes(n.label)) arr.push(n.label);
  });

  const full_text = by_slide.map((s) => s.text).join(' ');

  return {
    graph: {
      file_name: DATA.session.file || 'showcase.pptx',
      total_slides: titles.length,
      model: 'showcase',
      nodes,
      edges,
      sections: [
        { name: '현황·배경', slide_role: 'intro', slide_nos: [1, 2, 3, 4] },
        { name: '핵심 원인', slide_role: 'body', slide_nos: [5, 6, 7, 8, 9, 10] },
        { name: '성공 요인·오해', slide_role: 'body', slide_nos: [11, 12] },
        { name: '실행·결론', slide_role: 'conclusion', slide_nos: [13, 14, 15] },
      ],
    },
    alignment: {
      file_name: DATA.session.file || 'showcase.pptx',
      total_slides: titles.length,
      model: 'showcase',
      items,
      speech_edges,
      extras: [],
      summary: {
        coverage: Math.round((alignedW / totalW) * 100) / 100,
        rank_correlation: 0.58,
        /* 그래프 간선 대비 말로 이은 비율. 시연은 ~40% — 다 잇지는 못했지만
           10%처럼 「거의 연결 없음」으로 읽히면 56% 커버·74점과 감각이 안 맞는다. */
        edge_coverage: (() => {
          const n = edges.length || 1;
          const raw = speech_edges.length / n;
          return Math.round(Math.min(0.9, Math.max(raw, speech_edges.length ? 0.35 : 0)) * 100) / 100;
        })(),
        verdict_counts: counts,
        speech_total_sec: dur,
      },
    },
    flow: {
      issues: (DATA.logicBreaks || []).filter((b) => !b.good).map((b) => ({
        type: b.type, from: b.from, to: b.to, note: b.note, evidence: b.ev,
      })),
      goods: (DATA.logicBreaks || []).filter((b) => b.good).map((b) => ({
        type: b.type, from: b.from, to: b.to, note: b.note, evidence: b.ev,
      })),
    },
    transcript: {
      full_text,
      duration_sec: dur,
      provider: 'showcase',
      marks_match: 'matched',
      marks_reason: '슬라이드 전환 기록에 맞춰 발화 구간을 나눴어요.',
      by_slide,
      words: [],
    },
    concepts: {
      slides: titles.map((title, i) => ({
        slide_no: i + 1,
        title,
        topic: title,
        concepts: (conceptBySlide[i + 1] || []).slice(0, 4),
      })),
    },
    score: DATA.score || null,
    ...showcaseVoiceStub(),
  };
}
/** 리허설이 끝난 뒤 짧은 분석 연출 → 질문 코칭으로 넘긴다. 실 LLM 은 부르지 않는다. */
async function beginShowcasePipeline() {
  const my = ++showcasePipeGen;
  nf.showcaseDemo = true;
  nf._pipelineStarted = true;
  nf.pipelineError = null;
  nf.pipelinePhase = 'queued';
  nf.pipelineDetail = '분석을 준비하고 있어요';
  nf.pipelineStartedAt = Date.now();
  nf._pipelineTickStarted = false;
  nf._stageActual = null;
  nf._pipelineLog = [];
  nf.pipelineOut = null;
  nf.transcriptOk = false;
  nf.conceptsOk = false;
  pipelineRunLive = true;
  /* 필름 스트립·장 제목은 업로드 파싱 값. 없거나 짧으면 쇼케이스 더미 제목을 쓴다 —
     비어 있으면 리빌 무대가 장 목록 없이 뜬다. */
  if (!Array.isArray(nf.slideTitles) || nf.slideTitles.length < (DATA.slideTitles || []).length) {
    nf.slideTitles = (DATA.slideTitles || []).slice();
  }
  if (!nf.fileName) nf.fileName = (DATA.session && DATA.session.file) || nf.fileName;
  /* 시연은 브라우저 인코딩이 없다. 남겨 두면 타임라인 앞에 2초 허수가 붙는다. */
  buildPipelineMarks({ encodingReady: true });
  pushPipelineLog('queued');
  saveSession('new-flow', nf);
  refreshStep4IfVisible();

  const phases = [
    ['stt', '말한 내용을 옮기는 중'],
    ['stt_done', '받아쓰기 완료'],
    ['concepts', '핵심 개념을 고르는 중'],
    ['concepts_done', '개념 추출 완료'],
    ['graph', '개념 지도를 그리는 중'],
    ['graph_done', '개념 지도 완료'],
    ['align', '발화와 자료를 맞춰 보는 중'],
    ['align_done', '정합 판정 완료'],
    ['flow', '흐름을 비교하는 중'],
    ['flow_done', '질문 준비 완료'],
    ['done', '분석 완료'],
  ];
  /* 시연은 실 7분이 아니라 약 12초 연출(023a2d3 의 리듬). 55초 예산으로 늘렸더니
     대기 화면만 한참 보다가 그래프 쇼가 늦게 시작돼 「분석 화면이 안 뜬다」로
     읽혔다 (2026-08-12 지적). 슈슈슉 지나가고 무대는 그래프 연출이 갖는다. */
  const phaseMs = (phase) => {
    if (phase === 'stt' || phase === 'concepts' || phase === 'graph') return 1100;
    if (phase === 'align') return 1400;
    if (phase === 'flow') return 900;
    if (phase === 'stt_done' || phase === 'concepts_done') return 700;
    if (phase === 'graph_done') return 1200;   // 그래프만 먼저 보여 줄 여유
    if (phase === 'align_done') return 900;
    return 500;
  };
  const stub = showcasePipelineStub();
  for (const [phase, detail] of phases) {
    if (my !== showcasePipeGen || !isShowcaseDemo()) return;
    nf.pipelinePhase = phase;
    nf.pipelineDetail = detail;
    if (phase === 'stt_done') {
      nf.transcriptOk = true;
      nf.pipelineOut = { ...(nf.pipelineOut || {}), transcript: stub.transcript };
    }
    if (phase === 'concepts_done') {
      nf.conceptsOk = true;
      nf.pipelineOut = { ...(nf.pipelineOut || {}), concepts: stub.concepts };
    }
    if (phase === 'graph_done') {
      nf.pipelineOut = { ...(nf.pipelineOut || {}), graph: stub.graph };
    }
    if (phase === 'align_done') {
      nf.pipelineOut = { ...(nf.pipelineOut || {}), alignment: stub.alignment, flow: stub.flow };
    }
    if (phase === 'flow_done' || phase === 'done') {
      nf.pipelineOut = { ...stub, ...(nf.pipelineOut || {}), ...stub };
    }
    pushBackstage(phase);
    pushPipelineLog(phase);
    nf.done = pipelineChecklistDone();
    refreshStep4IfVisible();
    saveSession('new-flow', nf);
    await new Promise((r) => setTimeout(r, phaseMs(phase)));
  }
  if (my !== showcasePipeGen) return;
  nf.pipelinePhase = 'done';
  nf.pipelineDetail = '분석을 마쳤어요';
  nf.pipelineOut = stub;
  pipelineRunLive = false;
  refreshStep4IfVisible();
  saveSession('new-flow', nf);
  autoAdvanceToQa();
}

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
  if (isShowcaseDemo()) return;                  // 시연은 결과 더미를 쓰므로 선분석을 돌리지 않는다
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
  // 다 읽었으면 아무 말도 안 한다 — 완료 안내까지 띄우면 문구가 화면을 어지럽힌다
  else if (s.graphReady) return '';
  else if (s.conceptsReady) text = '자료의 개념을 찾았어요. 개념끼리 어떻게 이어지는지 보고 있어요';
  else text = '발표하는 동안 자료를 먼저 읽고 있어요';
  return `<p class="pre-note">${escapeHtml(text)}</p>`;
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
  if (!next) { host.remove(); return; }   // 다 읽었으면 줄 자체를 거둔다
  if (next.textContent !== host.textContent) host.replaceWith(next);
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
    <div class="flow-save"><span>자동으로 저장하고 있어요</span><a href="#/new" data-fresh-practice>처음부터</a><a href="#/">나가기</a></div>
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

/** 시연·샘플은 서버 preview API 없이 로컬 PDF 로 슬라이드 덱을 채운다. */
async function ensureShowcasePreviewPdf() {
  if (uploadedPdf && uploadedPdf.pdf) return uploadedPdf;
  if (!(isShowcaseDemo() || rSampleMode || (nf && nf.useSample))) return null;
  try {
    const name = (DATA.session && DATA.session.file) || 'investor_preview.pdf';
    await loadPreviewPdf(SHOWCASE_SLIDE_PDF, name);
    return uploadedPdf;
  } catch (err) {
    console.warn('[chuckchuck] showcase slide pdf', err);
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
/**
 * 지금 올라와 있는 자료의 지문. 질문 코칭이 "이 질문들이 어느 자료 것인가" 를
 * 이 값으로 기억한다.
 *
 * 자료 이름만으로는 부족하다 — 같은 이름으로 다시 뽑은 자료는 같은 자료가 맞고,
 * 장수가 달라졌으면 다른 자료다. 둘을 같이 본다.
 *
 * 자료가 아직 없으면 빈 문자열이다. **빈 값은 판단에 쓰지 않는다** — 새로고침
 * 직후처럼 nf 가 아직 안 찬 순간에 진행 중인 코칭을 지워 버리면 안 된다.
 */
function qaDocKey() {
  const meta = (typeof nf !== 'undefined' && nf && nf.slideDocMeta) || null;
  if (!meta || !meta.file_name) return '';
  return `${meta.file_name}|${meta.total_slides || 0}`;
}

function applySlideDoc(doc, { keepDemoImages = false } = {}) {
  /* 자료가 바뀌면 지난 발표의 질문 코칭을 버린다.
     resetQa() 는 여태 「새 발표 연습」 버튼과 route() 의 nf.completed 가드에만
     걸려 있었다. 그런데 nf.completed 는 qaLiveEnd() 만 세우므로, **코칭을 끝내지
     않고** 새 자료를 올리면 아무 가드에도 안 걸렸다 — 새 분석이 끝나고 #/qa 로
     가면 ensureLiveQuestions() 가 qaLiveActive() 만 보고 지난 발표의 질문·대화를
     그대로 보여줬다 (2026-08-08 사용자 지적).
     여기가 자료의 정체성이 바뀌는 유일한 지점이라, 업로드든 캐시 재사용이든
     모든 경로가 이 한 곳을 지난다. */
  const prevKey = qaDocKey();

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

  // 처음 올리는 자료(prevKey 없음)는 지울 것이 없다. 같은 자료를 다시 파싱한
  // 경우도 지문이 같아 그냥 지나간다 — 캐시 재사용이 진행 중인 코칭을 날리면 안 된다.
  if (prevKey && qaDocKey() !== prevKey) resetQa();
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
  /* 샘플·시연 연습 화면의 슬라이드 필름도 PDF 가 있어야 채워진다.
     ensure 는 비동기라 그린 뒤 붙이고, 붙으면 썸네일만 다시 칠한다. */
  if ((isShowcaseDemo() || (nf && nf.useSample)) && !uploadedPdf) {
    ensureShowcasePreviewPdf().then((pdf) => {
      if (pdf && $('#nf')) paintDeckThumbs(app);
    });
  }
}

/* 스텝 1 — 자료 올리기 */
function nfStep1() {
  const box = $('#nf');
  if (nf.gate === null) {
    box.innerHTML = `
      <div class="dropzone" id="dz">
        <div class="dz-copy">
          <span class="dz-kicker">새 발표 연습</span>
          <h1>발표자료를<br>여기에 놓아주세요</h1>
          <p class="dz-note">자료를 읽은 뒤 발표 정보와 리허설 설정을 이어서 진행해요.</p>
          <p class="note">PDF, PPTX · 최대 30MB · 슬라이드 100개까지</p>
        </div>
        <div class="dz-actions">
          <button class="btn btn-primary" id="pick">내 컴퓨터에서 선택</button>
          <span class="dz-or">또는 이 화면에 파일을 끌어다 놓으세요</span>
        </div>
        <input type="file" id="file" accept=".pdf,.pptx" hidden>
      </div>`;
    /* 여기에 비활성 「다음」 버튼을 두지 않는다. 화면에서 제일 큰 물건이
       아무것도 안 하는 버튼이면 눈이 거기 먼저 가고, 정작 할 일(자료 올리기)이
       뒤로 밀린다. 이 단계의 CTA 는 드롭존 자체다 */
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
        <p class="parse-meta"><b id="parseElapsed">${elapsed}</b>초 지났어요 · 자료가 길면 1~5분까지 걸려요</p>
        ${parsePreview ? `
        <div class="parse-peek">
          <img src="${parsePreview.thumb}" alt="">
          <div>
            <b class="num" data-count="${parsePreview.pages}">${parsePreview.pages}</b><span class="parse-peek-unit">슬라이드짜리 자료예요</span>
            <p>기다리는 동안 브라우저에서 먼저 열어 봤어요. 슬라이드별 개념은 위 분석이 끝나면 이어서 보여줄게요.</p>
          </div>
        </div>` : ''}
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
    if (parsePreview) {
      const n = $('.parse-peek .num');
      if (n && !n.dataset.counted) { n.dataset.counted = '1'; countUp(n, parsePreview.pages, 500); }
      staggerIn($$('.parse-peek'));
    }
    if (parseTimer) { clearInterval(parseTimer); parseTimer = null; }
    parseTimer = every(() => {
      const el = $('#parseElapsed');
      if (!el || !nf._parseStartedAt) return;
      el.textContent = String(Math.max(0, Math.floor((Date.now() - nf._parseStartedAt) / 1000)));
    }, 1000);
  } else if (nf.gate === 'fail') {
    box.innerHTML = `
      ${stageAccidentHtml(nf.parseError || 'PDF나 PPTX 파일만 분석할 수 있어요. 다른 파일로 올려주세요.', { title: '죄송해요, 대본을 못 받았어요!' })}
      <div class="step-actions"><button class="btn btn-secondary" id="retry">다시 올리기</button><button class="btn btn-primary" id="sampleDemo">샘플 데모로 계속하기</button></div>`;
    $('#retry').addEventListener('click', () => { nf.gate = null; nf.parseError = null; nfStep1(); });
    $('#sampleDemo').addEventListener('click', () => startParse({ fixture: true }));
  } else {
    const titles = activeTitles();
    const images = activeImages();
    const sparse = new Set(nf.sparseSlides || []);
    const warnNote = sparse.size
      ? `${[...sparse].slice(0, 3).join(', ')}번 슬라이드는 텍스트가 적어요. 발표 때 말한 내용으로 구조를 보완할게요.`
      : '슬라이드 텍스트를 기준으로 개념을 추출할 준비가 됐어요.';
    box.innerHTML = `
      <div class="card">
        <div class="gate-ok">${nf.useSample ? '샘플 자료 · ' : ''}슬라이드 ${titles.length}개를 읽었어요</div>
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

/* 파싱을 기다리는 동안 보여줄 로컬 미리보기.
   nf 에 넣지 않는다 — saveSession 이 sessionStorage 로 밀어 넣는데 dataURL 이
   수십 KB 라 다른 세션 값까지 통째로 저장에 실패할 수 있다 */
let parsePreview = null;

/** GitHub Pages에서도 서버 없이 제품의 전체 흐름을 확인하는 명시적 샘플 자료. */
function clientSampleSlideDoc() {
  const topicBySlide = Object.fromEntries((DATA.tree || []).map((node) => [slideNumber(node.slide), node]));
  const slides = DATA.slideTitles.map((title, index) => {
    const no = index + 1;
    const topic = topicBySlide[no];
    const lines = [
      title,
      topic && topic.ev,
      topic && topic.why,
    ].filter(Boolean);
    return {
      slide_no: no,
      title,
      raw_text: lines.join('\n'),
      blocks: lines.map((text) => ({ text })),
      text_sparse: lines.length < 2,
    };
  });
  return {
    file_name: (DATA.session && DATA.session.file) || '개인투자자_수익률격차_분석.pdf',
    total_slides: slides.length,
    slides,
    sample: true,
  };
}

/**
 * 서버가 자료를 읽는 동안 브라우저가 같은 파일을 직접 열어 본다.
 *
 * 이 화면은 「1~5분 걸려요」와 흐르는 막대만 놓고 사람을 세워 뒀다. 서버 진행률은
 * 알 방법이 없지만(한 번의 동기 호출이다), **몇 장짜리인지와 첫 장이 어떻게
 * 생겼는지는 여기서 바로 알 수 있다.** 서버 응답을 기다려 얻은 척하는 게 아니라
 * 브라우저가 방금 연 사실이라 「먼저 열어 봤어요」라고 그대로 말한다.
 */
async function probeParsePreview(file, gen) {
  if (!file || !window.pdfjsLib || !/\.pdf$/i.test(file.name || '')) return;
  const alive = () => gen === parseGen && nf.gate === 'parsing';
  try {
    const pdf = await pdfjsLib.getDocument({ data: await file.arrayBuffer() }).promise;
    if (!alive()) return;
    const page = await pdf.getPage(1);
    const base = page.getViewport({ scale: 1 });
    const vp = page.getViewport({ scale: 240 / base.width });
    const cv = document.createElement('canvas');
    cv.width = Math.round(vp.width);
    cv.height = Math.round(vp.height);
    await page.render({ canvasContext: cv.getContext('2d'), viewport: vp }).promise;
    if (!alive()) return;
    parsePreview = { pages: pdf.numPages, thumb: cv.toDataURL('image/jpeg', 0.72) };
    nfStep1();
  } catch (e) {
    console.warn('[chuckchuck] parse preview', e);   // 미리보기는 실패해도 파싱은 그대로 간다
  }
}

async function startParse({ file = null, fixture = false } = {}) {
  const myGen = ++parseGen;
  nf.gate = 'parsing';
  nf.parseError = null;
  nf.useSample = !!fixture || !file;
  nf.fileName = file ? file.name : '발표자료';
  nf._parseStartedAt = Date.now();
  parsePreview = null;
  nfStep1();
  probeParsePreview(file, myGen);   // 기다리게 두지 않는다 — 되는 대로 화면에 얹는다

  const bridge = window.ChuckchuckBridge;
  if (!bridge || typeof bridge.parseDocument !== 'function') {
    await new Promise((r) => setTimeout(r, 300));
  }
  try {
    if (nf.useSample) {
      // 정적 배포에는 Python API가 없다. 샘플 버튼만 브라우저 내 fixture를 쓰고,
      // 실제 파일 업로드는 계속 실 API 계약을 타게 해 둘을 섞지 않는다.
      await new Promise((resolve) => setTimeout(resolve, 650));
      if (myGen !== parseGen) return;
      const doc = clientSampleSlideDoc();
      applySlideDoc(doc, { keepDemoImages: true });
      setUploadedPdf(null);
      await ensureShowcasePreviewPdf();
      nf.gate = 'done';
      nf._parseStartedAt = null;
      if (parseTimer) { clearInterval(parseTimer); parseTimer = null; }
      saveSession('new-flow', nf);
      nfStep1();
      return;
    }
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
    const rawMessage = err.message || String(err);
    /* 시연 빌드는 분석 서버가 아예 없다 — 브리지 없음을 「새로고침 해주세요」로
       안내하면 몇 번을 새로고침해도 같은 사고가 난다. 샘플 입구로 보낸다. */
    const noServer = /Unexpected token|not valid JSON|parse HTTP 40[45]/i.test(rawMessage)
      || (isShowcaseDemo() && /SDK bridge/i.test(rawMessage));
    nf.parseError = noServer
      ? '현재 배포본에는 실제 파일 분석 서버가 연결되지 않았어요. 샘플 데모로 전체 흐름을 먼저 확인해보세요.'
      : rawMessage;
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

/* ─── 고른 순간의 손맛 ────────────────────────────────────────────────
   모션은 예뻐 보이려고 넣는 게 아니라 「내가 눌렀고, 그게 먹혔다」를 몸이 알게
   하려고 넣는다. 스프링이 살짝 넘쳤다 돌아오는 0.4초가 그 신호다.
   Motion 이 없거나 모션 최소화면 아무 일도 안 일어나고 기능은 그대로다. */
function motionOn() {
  return !!(window.Motion && window.Motion.animate)
    && !(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
}

function springPick(el) {
  if (!el || !motionOn()) return;
  window.Motion.animate(el, { scale: [0.94, 1] },
    { type: 'spring', stiffness: 520, damping: 17 });
}

/** 화면이 한꺼번에 나타나면 어디부터 볼지 모른다. 위에서부터 차례로 들어온다 */
function staggerIn(nodes) {
  const list = Array.from(nodes || []).filter(Boolean);
  if (!list.length || !motionOn()) return;
  window.Motion.animate(list, { opacity: [0, 1], y: [10, 0] },
    { delay: window.Motion.stagger(0.055), duration: 0.34, ease: [0.22, 1, 0.36, 1] });
}

/**
 * 발표 상황 — 계약 문자열 → 사람이 쓰는 말.
 *
 * 왼쪽(키)은 채점표 v3 의 상황 4열이라 **한 글자도 바꾸면 안 된다**. 서버
 * (rubric_v3.resolve_situation)가 이 문자열로 가중치를 고르고, F-06·07·11
 * 프롬프트에도 그대로 들어간다. 오른쪽만 화면에 나간다.
 *
 * 선택 화면에서만 이 표를 쓰고 리포트는 계약 문자열을 그대로 뿌리고 있었다 —
 * 고를 땐 「수업에서 발표해요」였는데 결과에선 「학교 프로젝트 (교수 대상)」이
 * 떴다. 같은 걸 두 이름으로 부르면 사용자는 다른 것으로 읽는다. 화면에 나가는
 * 자리는 전부 occLabel() 을 거친다.
 */
const OCC_LABEL = {
  '학교 프로젝트 (교수 대상)': '수업에서 발표해요',
  '신제품 설명 (대중 대상)': '제품을 소개해요',
  '업무 보고 (상사 대상)': '팀에 보고해요',
  '동료 간 캐주얼 PR': '동료에게 공유해요',
};
/** 모르는 값이면 온 그대로 낸다 — 빈칸보다 낫고, 새 상황이 생겨도 화면은 산다 */
const occLabel = v => OCC_LABEL[String(v || '').trim()] || String(v || '');

function nfStep2() {
  /* 채점표 v3 의 상황 4열 그대로다. 라벨을 그대로 보내면 서버(rubric_v3.resolve_situation)가
     상황 key 로 옮긴다 — 프론트가 key 를 따로 들고 있지 않아도 되고, 이 문장이 F-06·07·11
     프롬프트에도 그대로 들어가서 한국어로 읽힌다. 문구를 바꾸면 가중치가 바뀐다. */
  /* 보내는 값은 위 계약 문자열 그대로, 화면에 보이는 말만 바꾼다.
     「교수 대상」·「상사 대상」은 사람이 쓰는 말이 아니다 — 누구 앞에서
     무엇을 하는지 한 문장으로 말한다 (해요체·능동형, CLAUDE.md §3-1) */
  const occs = Object.entries(OCC_LABEL);
  const times = [3, 5, 10, 15, 20, 30];
  const titles = activeTitles();
  const perSlide = Math.round(nf.min * 60 / titles.length);
  $('#nf').innerHTML = `
    <div class="card">
      <h2 class="nf-head">어떤 발표인가요?</h2>
      <p class="note nf-head-sub">건너뛰어도 돼요. 입력하면 개념 중요도를 더 정확하게 정할 수 있어요.</p>
      <div class="field">
        <label>발표 상황</label>
        <div class="chips" id="occ">
          ${occs.map(([val, label]) => `<button class="${nf.occ === val ? 'on' : ''}" data-occ="${val}">${occIcon(val)}<span>${label}</span></button>`).join('')}
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
          <p><b>슬라이드 ${titles.length}개 기준 슬라이드당 약 <em id="perSlide">${perSlide}</em>초</b><span>질문 시간을 포함하면 1~2분 여유를 두는 게 좋아요.</span></p>
        </div>
      </div>
    </div>
    <div class="step-actions">
      <button class="btn btn-primary" id="go">녹음하러 가기</button>
      <button class="btn btn-text" id="skip">건너뛰기</button>
    </div>`;
  staggerIn($$('#nf .nf-head, #nf .nf-head-sub, #nf .field, #nf .step-actions'));

  $('#occ').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    // data-occ 로 읽는다. textContent 로 읽으면 버튼 안에 아이콘·부가 문구를
    // 넣는 순간 값이 오염되고, rubric_v3.py 는 이 한국어 문자열로 상황을
    // 매핑하므로(school_project 등) 조용히 기본 가중치로 떨어진다.
    nf.occ = b.dataset.occ || b.textContent.trim();
    $$('#occ button').forEach(x => x.classList.toggle('on', x === b));
    springPick(b);
    saveSession('new-flow', nf);
  });
  $('#ctx').addEventListener('input', e => { nf.ctx = e.target.value; saveSession('new-flow', nf); });
  /* 예전엔 여기서 nfStep2() 를 통째로 다시 그렸다. 화면이 한 번 깜빡이면서
     방금 누른 버튼이 새 노드로 갈리니 눌린 느낌이 사라지고, 바뀐 숫자도
     그냥 다른 값으로 교체돼 무엇이 변했는지 안 보였다. 제자리에서 고친다 */
  $('#timePresets').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    nf.min = Number(b.dataset.min);
    $$('#timePresets button').forEach(x => x.classList.toggle('on', x === b));
    springPick(b);
    const per = $('#perSlide');
    const next = Math.round(nf.min * 60 / activeTitles().length);
    if (per) countUp(per, next, 420);      // 숫자가 굴러가면 무엇이 바뀌었는지 눈이 따라간다
    saveSession('new-flow', nf);
  });
  // 녹음 화면으로 넘어가는 순간 자료 축(F-06·F-07)을 먼저 건다 — 발표하는 동안 돈다
  $('#go').addEventListener('click', () => { if (!nf.useSample) startPrecompute(); nf.step = 2; renderNew(); });
  // 건너뛰면 상황을 비운다. 서버가 기본 기준으로 매기고 "안 골라서 …" 안내를 남긴다 —
  // 없는 상황을 지어내 보내면 어느 가중치로 매겼는지 알 수 없게 된다.
  $('#skip').addEventListener('click', () => {
    nf.occ = '';
    if (!nf.useSample) startPrecompute();   // 샘플은 브라우저 fixture를 쓰고 API를 호출하지 않는다
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
      ${precomputeNoteHtml()}
    </div>
    <div class="rehearsal-shell">
      <aside class="rehearsal-side" aria-label="발표 컨트롤">
        <div class="card rehearsal-control" id="recPanel"></div>
        <div class="card rehearsal-nav" aria-label="슬라이드 이동">
          <button type="button" class="btn btn-secondary rehearsal-nav-prev" data-slide-nav="-1">이전 슬라이드</button>
          <div class="rehearsal-slide-meta"><span>현재 슬라이드</span><strong id="slideNo" class="num">${nf.slide} / ${nPages}</strong></div>
          <button type="button" class="btn btn-primary rehearsal-nav-next" data-slide-nav="1">다음 슬라이드</button>
        </div>
        <div class="sf" id="stagefront" aria-hidden="true"></div>
      </aside>
      <div class="card viewer presentation-viewer">
        <div class="viewer-stage ${usePdf ? 'has-pdf' : 'has-slide-doc'}">
          ${stageInner}
          <button type="button" class="stage-nav stage-prev" data-slide-nav="-1" aria-label="이전 슬라이드">‹</button>
          <button type="button" class="stage-nav stage-next" data-slide-nav="1" aria-label="다음 슬라이드">›</button>
        </div>
        <div class="viewer-caption">
          <strong id="slideTitle">${escapeHtml(titleAt(nf.slide - 1))}</strong>
        </div>
        <div class="slide-film ${usePdf ? 'slide-film-deck' : 'slide-film-text'}" id="slideFilm">${film}</div>
      </div>
    </div>
    <p class="privacy-note">m4a · mp3 · wav · webm · 최대 ${MAX_AUDIO_MB}MB · 슬라이드 구간은 길이를 균등하게 나눠 채워요</p>`;
  renderRecPanel();
  bindRehearsalNav();
  syncRehearsalNav();
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

function syncRehearsalNav() {
  const current = Number(nf.slide) || 1;
  const last = rehearsalCount();
  $$('[data-slide-nav="-1"]').forEach((button) => { button.hidden = current <= 1; });
  $$('[data-slide-nav="1"]').forEach((button) => { button.hidden = current >= last; });
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
    syncRehearsalNav();
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
      <!-- 형식 안내는 화면 하단 privacy-note 자리로 갔다. 이 줄은 업로드
           진행·오류 상태가 생길 때만 채워진다 (recUploadFail·길이 읽는 중) -->
      <p class="note" id="recUploadNote"></p>
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
      <div class="rec-copy"><span>${nf.useSample ? '샘플 발표를 직접 녹음해보세요' : '준비되면 시작하세요'}</span>${nf.useSample ? '<p>녹음은 실제로 진행되고, 분석 결과만 준비된 샘플을 사용해요.</p>' : ''}</div>
      ${hasTake ? '<button class="btn btn-secondary" id="recResume">아까 발표로 질문 준비하기</button>' : ''}
      <button class="btn btn-primary" id="recStart">발표 시작하기</button>
      ${nf.useSample ? '<button class="btn btn-text btn-sm" id="sampleNoMic">마이크 없이 분석 화면만 보기</button>' : ''}
      ${recUploadHtml()}`;
    $('#recStart').addEventListener('click', startRec);
    if (hasTake) {
      $('#recResume').addEventListener('click', () => { nf.step = 3; renderNew(); });
    }
    if (nf.useSample) $('#sampleNoMic').addEventListener('click', startSampleWithoutRecording);
    bindRecUpload();
  } else if (nf.mic === 'denied') {
    p.innerHTML = `
      <div class="mic-denied"><b>마이크 권한이 필요해요</b><span>주소창의 권한 설정에서 허용한 뒤 다시 시작해주세요.</span></div>
      <button class="btn btn-secondary" id="recRetry">다시 시도하기</button>
      ${nf.useSample ? '<button class="btn btn-text" id="sampleNoMic">마이크 없이 분석 화면만 보기</button>' : ''}
      ${recUploadHtml()}`;
    $('#recRetry').addEventListener('click', startRec);
    if (nf.useSample) $('#sampleNoMic').addEventListener('click', startSampleWithoutRecording);
    bindRecUpload();
  } else {
    p.innerHTML = `
      <div class="rec-status">
        <div><span class="rec-live">발표 중</span><strong class="rec-clock" id="clock">${fmt(nf.sec)}</strong></div>
        <span class="meter" aria-label="마이크 입력 감지 중"><i></i><i></i><i></i><i></i><i></i></span>
      </div>
      <details class="rec-log-fold"><summary>슬라이드 전환 <b id="recSwitchCount">${slideSwitchCount()}</b>회 기록</summary><div class="trans-log" id="tlog">
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

function sampleTake(durationSec = 180) {
  const duration = Math.max(30, Number(durationSec) || 180);
  const marks = evenSlideMarks(duration, rehearsalCount());
  return {
    marks,
    mimeType: 'audio/webm',
    durationSec: duration,
    fileName: 'sample-demo.webm',
    _blob: new Blob([], { type: 'audio/webm' }),
    sample: true,
  };
}

function queueSampleAnalysis(take) {
  stopLiveRehearsal();
  ccLastTake = take || sampleTake(nf.sec);
  nf.marks = ccLastTake.marks || [];
  nf.sec = Math.round(ccLastTake.durationSec || nf.sec || 0);
  nf.mic = 'idle';
  nf.done = 0;
  nf._pipelineStarted = false;
  nf._samplePipelineStarted = false;
  nf.pipelineOut = null;
  nf.pipelineError = null;
  nf.pipelinePhase = 'queued';
  nf.pipelineDetail = '샘플 분석을 준비하고 있어요';
  nf.pipelineStartedAt = Date.now();
  nf._pipelineTickStarted = false;
  nf.backstage = [];
  nf._pipelineLog = [];
  nf.step = 3;
  saveSession('new-flow', nf);
  renderNew();
  /* 시연은 「마이크 없이」로 와도 리빌 연출이 본편이다 — 녹음 경로
     (finishRecAndPrepare)와 같은 화면을 연다. 이 함수만 스텝4 로 보내고
     리빌을 안 열어서, 이 경로로 온 사람은 그래프 쇼를 통째로 못 봤다. */
  if (isShowcaseDemo()) showF11Reveal();
}

function startSampleWithoutRecording() {
  queueSampleAnalysis(sampleTake(180));
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
  return `슬라이드 ${slides}개, ${time}, <b>완주!</b>`;
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
  if (nf.useSample && !ccLastTake) {
    ccLastTake = sampleTake(nf.sec);
    nf.marks = ccLastTake.marks;
    nf.pipelinePhase = 'queued';
    nf.pipelineDetail = '샘플 분석을 준비하고 있어요';
    nf.pipelineStartedAt = Date.now();
  }
  if (nf.useSample) nf._samplePipelineStarted = false;
  nf.backstage = [];   // 막간 대사는 테이크마다 새로 쌓인다
  // 녹음은 여기서 끝났다. 'on' 으로 두면 리허설로 돌아왔을 때 이미 끝난 발표가
  // 「발표 중」 시계로 다시 그려지고, 단계 표시줄도 녹음 중인 줄 알고 잠긴다
  nf.mic = 'idle';
  /* 시연은 결과 더미가 9분 24초라, 커튼콜·이후 화면에 실제 마이크 초를 쓰면 어긋난다. */
  const curtainSec = isShowcaseDemo()
    ? ((DATA.session && DATA.session.durationSec) || 564)
    : ((ccLastTake && ccLastTake.durationSec) || nf.sec);
  if (isShowcaseDemo()) {
    nf.sec = curtainSec;
    if (ccLastTake) ccLastTake.durationSec = curtainSec;
  }
  await showCurtainCall(slides, curtainSec);
  nf.step = 3;
  renderNew();
  /* 시연도 F-11 리빌을 띄운다 — 개념 그래프에 판정 도장이 찍히는 연출이 부스의
     핵심 장면이다. 리빌은 CTA 를 눌러야 닫히고, autoAdvanceToQa 도 리빌이 떠 있는
     동안은 기다리므로 중간에 튕기지 않는다. 친구 쪽 샘플 데모(useSample)는
     쇼케이스가 꺼진 빌드에서만 스텝4 연출로 간다. */
  if (!nf.useSample || isShowcaseDemo()) showF11Reveal();
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
    note.style.color = 'var(--no)';
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

  // 녹음이 돌고 있었다면 멈추고 버린다 (참조만 버리면 마이크가 안 꺼진다)
  stopLiveRehearsal();
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
  // 연출이 화면 전체를 먹으면 단계 표시줄이 사라졌다가 연출이 끝나야 돌아온다.
  // 어디쯤 왔는지가 제일 궁금한 구간에서 그 표지를 치우는 셈이라, 바와
  // 체크리스트를 연출 위에 남기고 나머지 자리를 연출에 준다 (2026-08-07 지적).
  wrap.style.cssText =
    'position:fixed;inset:0;z-index:999;opacity:0;transition:opacity .45s ease;'
    + 'display:flex;flex-direction:column;background:var(--canvas)';
  wrap.innerHTML =
    '<div id="f11Chrome" class="f11-chrome"></div>'
    + '<iframe src="f11_reveal.html?embed=1&v=showcase6" title="발표 분석 과정" '
    + 'style="flex:1 1 auto;width:100%;min-height:0;border:0;display:block"></iframe>';
  document.body.appendChild(wrap);
  // 첫 틱을 기다리면 그동안 위가 비어 보인다. 붙이자마자 한 번 채운다.
  // 이후 갱신은 통째 innerHTML 재작성이 아니라 1초 틱의 in-place 페인터가 한다 —
  // 매 틱 다시 쓰면 타임라인의 폭 전이가 처음부터 되감겨 모션이 전부 죽는다.
  const chrome0 = wrap.querySelector('#f11Chrome');
  if (chrome0) {
    /* 체크리스트는 여기 안 넣는다 — 바로 아래 iframe 의 「지금까지 한 일」이
       같은 다섯 단계를 미리 세워 두고 색칠하는 목록이라, 한 화면에 같은 말이
       두 번 있었다 (2026-08-10 지적). 띠는 진행률·타임라인만 말한다. */
    chrome0.innerHTML = nfSteps() + pipelineStatusBarHtml()
      + pipelineTimelineHtml('compact');
    paintPipelineTimeline();
  }
  requestAnimationFrame(() => { wrap.style.opacity = '1'; });

  /**
   * 리빌 필름 스트립에 넘길 장 목록.
   *
   * 그래프가 오기 전 오른쪽 무대는 비어 있다. 그 시점에 이미 손에 있는 건
   * **내가 올린 자료의 장 제목**이다 (업로드 파싱에서 nf.slideTitles 로 붙는다).
   * 개념 수는 F-06 이 도착하는 대로 장마다 채워져, 어느 장을 읽는 중인지가 보인다.
   * 없는 값을 0 으로 위장하지 않는다 — 아직 안 온 장은 found 가 undefined 다.
   */
  function revealSlideStrip(out) {
    const titles = (nf && nf.slideTitles) || [];
    if (!titles.length) return [];
    const conceptSlides = ((out.concepts || {}).slides) || [];
    const found = {};
    conceptSlides.forEach((s) => { found[s.slide_no] = (s.concepts || []).length; });
    const any = conceptSlides.length > 0;
    // 24장을 넘기면 칩이 글자보다 작아진다. 넘는 만큼은 스트립이 «+N장» 으로 말한다
    return titles.slice(0, 24).map((t, i) => ({
      no: i + 1,
      title: String(t || '').slice(0, 30),
      found: any ? (found[i + 1] || 0) : null,
    }));
  }

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
      slides: revealSlideStrip(out),
      slidesTotal: ((nf && nf.slideTitles) || []).length,
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

function buildPipelineMarks({ conceptsReady = false, graphReady = false, encodingReady = false } = {}) {
  const secs = { ...PIPELINE_STAGE_SEC_BASE };
  if (conceptsReady) secs.concepts = 0;
  if (graphReady) secs.graph = 0;
  if (encodingReady) secs.encoding = 0;
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

/** 예산을 모르는 단계(queued 등)에 쓰는 기본 예산(초) */
const PIPELINE_CREEP_TAU_SEC = 70;

/* 예산 안에서는 구간의 이 비율까지만 일정 속도로 찬다. 나머지는 예산을
   넘긴 뒤의 몫이다 — 천장 코앞까지 미리 다 써 버리면, 마지막 단계가
   늦어질 때 화면이 98%에서 몇십 초를 서 있게 된다 (2026-08-10 지적:
   97~98%까지는 빨리 차는데 그 뒤가 답답하다). */
const PIPELINE_STAGE_LINEAR_SHARE = 0.6;

/** 지금 단계의 예상 소요(초). 실측 배율까지 반영한 값이다 */
function pipelineStageBudgetSec(phase) {
  const stage = pipelineStageOf(phase);
  const sec = (pipelineStageSec[stage] || 0) * pipelineSpeedFactor();
  return sec > 0 ? Math.max(3, sec) : PIPELINE_CREEP_TAU_SEC;
}

/** 산출물이 실제로 나온 단계들의 시간 비중(%). 실패로 멈춘 화면의 정직한 진행률이다 */
function pipelineDonePercent() {
  const total = PIPELINE_STAGE_ORDER.reduce((a, k) => a + (pipelineStageSec[k] || 0), 0) || 1;
  const done = PIPELINE_STAGE_ORDER.reduce(
    (a, k) => a + (pipelineStageDone(k) ? (pipelineStageSec[k] || 0) : 0), 0);
  return Math.round((done / total) * 100);
}

/* 단계 안에서는 시간에 따라 천장으로 점근할 뿐 절대 넘지 않는다 —
   막대가 멈춰 보이지 않으면서도 "다 됐다"고 거짓말하지 않는다.

   곡선은 두 토막이다. 예산 안에서는 구간의 60%까지 일정 속도(눈이 따라오는
   전진), 예산을 넘기면 남은 40%를 쌍곡선으로 천천히 점근한다. 예전 지수
   점근(τ=0.7×예산)은 예산의 1.5배쯤에서 이미 천장에 붙어, 마지막 단계가
   늦어지면 정수 % 표시가 98에서 얼어붙었다. 쌍곡선은 같은 시간에 덜 올라가
   있어서 늦어지는 동안에도 1%씩 계속 움직인다. */
function pipelinePercent(phase, phaseElapsedSec) {
  /* 표는 error·partial 을 100 에 눕혀 놨다(질문 코칭 축의 관심 밖이라서). 그대로 쓰면
     「중간에 멈췄어요 · 100%」가 된다 — 멈춘 화면에는 실제로 끝난 만큼만 말한다. */
  if (phase === 'error' || phase === 'partial') return pipelineDonePercent();
  const marks = pipelineMarks || buildPipelineMarks();
  const [base, ceil] = marks[phase] || marks.queued;
  if (ceil <= base) return ceil;
  const t = Math.max(0, Number(phaseElapsedSec) || 0);
  const budget = pipelineStageBudgetSec(phase);
  const over = t - budget;
  const k = t <= budget
    ? PIPELINE_STAGE_LINEAR_SHARE * (t / budget)
    : PIPELINE_STAGE_LINEAR_SHARE
      + (1 - PIPELINE_STAGE_LINEAR_SHARE) * (over / (over + budget * 2));
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
  if (pipelineStageOverrun()) return '생각보다 조금 더 걸리고 있어요';
  const sec = pipelineEtaSec();
  if (sec <= 0) return '생각보다 조금 더 걸리고 있어요';
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
      <!-- 「경과 46초」는 계기판 말이다. 사람은 «46초 지났어요» 라고 말한다 -->
      <b class="pipe-elapsed">${elapsed}</b>초 지났어요 · <span class="psb-eta">${escapeHtml(pipelineEtaText())}</span>
    </p>
  </div>`;
}

/** 1초 틱이 상태 줄을 다시 그리지 않고 숫자만 갈아끼운다 (전체 렌더는 보던 화면을 날린다).
    스텝 4 와 F-11 띠에 하나씩, 두 개가 떠 있을 수 있어 전부 돈다. */
function paintPipelineStatusBar() {
  const phase = nf.pipelinePhase || 'queued';
  const pct = pipelinePercent(phase, phaseElapsedSec());
  $$('.pipe-status-bar').forEach((host) => {
    const label = host.querySelector('.pipe-phase');
    const pctEl = host.querySelector('.psb-pct');
    const fill = host.querySelector('.progress i');
    const eta = host.querySelector('.psb-eta');
    if (label) label.textContent = pipelinePhaseLabel(phase);
    if (pctEl) pctEl.textContent = `${pct}%`;
    if (fill) fill.style.width = `${pct}%`;
    if (eta) eta.textContent = pipelineEtaText();
    host.classList.toggle('is-final', ['done', 'partial', 'error'].includes(phase));
  });
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
    voice_report: '리포트로 정리하고 있어요',
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
/** 진행 체크리스트 마크업.
 *
 * nfStep4 와 F-11 연출 오버레이가 같이 쓴다. 연출이 화면을 덮는 동안에도
 * "지금 어디까지 됐나"는 계속 보여야 한다 — 덮어 놓고 숨기면 사용자는
 * 진행이 멈춘 줄 안다 (2026-08-07 지적). */
/**
 * 질문을 만드는 동안 보여주는 개념 지도.
 *
 * 이 화면은 스스로 「개념 그래프와 실제 발화를 대조해 고른다」고 말한다 —
 * 그 그래프를 정작 안 보여주고 있었다. 10초를 세는 막대만 보는 것보다,
 * 지금 무엇을 뒤지고 있는지 보이는 편이 낫다 (2026-08-10 지시).
 *
 * 그래프가 없으면 칸 자체를 안 만든다. 없는 게 정상인 순간이 있고,
 * 빈 판을 띄우면 「분석이 실패했나」로 읽힌다.
 */
function qaBuildGraphHtml() {
  if (typeof window.hasConceptGraph !== 'function' || !window.hasConceptGraph()) return '';
  return `
    <div class="rep-graph qb-graph">
      <div class="g3d-summary" id="qbGraphSummary"></div>
      <div class="rep-graph-stage" id="qbGraphStage"><p class="g3d-loading">개념 지도를 세우고 있어요…</p></div>
      <aside class="g3d-card in-report" id="qbGraphCard" hidden></aside>
    </div>`;
}

function pipelineChecklistHtml() {
  const items = pipelineChecklistItems();
  const stage = pipelineStageOf(nf.pipelinePhase || 'queued');
  return `<ul class="checklist">${items.map((it, i) => {
    const st = it.ok ? 'done' : (it.stage === stage ? 'doing' : 'todo');
    return `<li class="${st}"><i>${it.ok ? '✓' : i + 1}</i>${it.text}</li>`;
  }).join('')}</ul>`;
}

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

/* ─── 분석 타임라인 + 라이브 피드 ──────────────────────────────────────────
   영상 편집기의 타임라인처럼 단계가 시간축 위에 놓인다 — 언제 시작해서 몇 초
   걸렸는지가 폭으로 보인다. 막대는 실측으로만 움직인다: 완료 구간은 실제 걸린 초,
   진행 구간은 흐른 초, 앞으로 구간은 빗금 「예상」 (§14 — 숫자는 신성하다).
   정합(F-11)은 단일 호출이라 안쪽 진행을 모른다. 아는 척하지 않는다. */

const PIPELINE_STAGE_NAME = {
  encoding: '녹음 정리', stt: '받아쓰기', concepts: '개념 찾기',
  graph: '개념 연결', align: '발표 대조', flow: '흐름 비교',
};

/** 이번 페이지 로드에서 파이프라인 프라미스가 실제로 살아 있는가.
    새로고침으로 복원된 세션은 phase 만 남고 프라미스는 죽어 있다 —
    이 구분 없이 초를 계속 세면 「곧 끝나요」가 거짓말이 된다. */
let pipelineRunLive = false;

/** 타임라인 입장 연출을 이미 튼 실행(pipelineStartedAt). 재렌더마다 되풀이하지 않는다 */
let tlIntroPlayedAt = null;

/** 단계별 완료 판정 — 체크리스트와 같은 근거(산출물)를 본다. phase 로 세지 않는다 */
function pipelineStageDone(stage) {
  const out = nf.pipelineOut || {};
  const t = out.transcript && !out.transcript.error ? out.transcript : null;
  const actual = nf._stageActual || {};
  if (stage === 'encoding') return actual.encoding != null || !!t;
  if (stage === 'stt') return !!t;
  if (stage === 'concepts') return !!(out.concepts && !out.concepts.error && !out.conceptsError);
  if (stage === 'graph') return !!out.graph;
  if (stage === 'align') return !!out.alignment;
  if (stage === 'flow') return !!out.flow;
  return false;
}

/**
 * 타임라인의 순수 모델 — 단계마다 상태와 초만 계산하고 DOM 은 모른다.
 *
 *  - pre     선분석으로 임계경로에서 빠졌다. 이 축의 시간이 아니라 칩으로 뺀다
 *  - instant 1초 미만에 끝났다(대부분 저장해 둔 결과). 축에 그리면 0px 라 칩으로 뺀다
 *  - done    실측 초만큼의 폭. 실측이 없으면(복원) 표의 초로 폭만 잡고 라벨은 비운다
 *  - active  흐른 초 + 남은 예상(빗금). 예상을 넘기면 빗금이 사라지고 전진이 멈춘다
 *  - est     아직 안 온 단계 — 전부 빗금
 *  - idle    파이프라인이 죽은 뒤라 시작할 수 없는 단계 — 예상을 말하지 않는다
 *  - error   실패한 단계
 */
function pipelineTimelineModel() {
  const out = nf.pipelineOut || {};
  const phase = nf.pipelinePhase || 'queued';
  const curStage = pipelineStageOf(phase);
  const running = !/_(done|error)$/.test(phase)
    && !['queued', 'done', 'partial', 'error'].includes(phase);
  const dead = ['error', 'partial'].includes(phase);
  const factor = pipelineSpeedFactor();
  const actual = nf._stageActual || {};
  const stageErr = {
    concepts: !!out.conceptsError, graph: !!out.graphError,
    align: !!out.alignError, flow: !!out.flowError,
  };
  let hardErrorMarked = false;
  return PIPELINE_STAGE_ORDER.map((stage) => {
    const name = PIPELINE_STAGE_NAME[stage] || stage;
    const done = pipelineStageDone(stage);
    const sec = actual[stage];
    /* 선분석이 임계경로에서 뺀 단계(buildPipelineMarks 가 0폭 처리)는 산출물이
       아직 안 넘어왔어도 축 밖이다 — 여기서 BASE 로 다시 그리면 진행률 막대와
       타임라인이 서로 다른 말을 한다. 0폭 = 이미 끝난 선분석 결과다. */
    if ((pipelineStageSec[stage] || 0) <= 0 && (PIPELINE_STAGE_SEC_BASE[stage] || 0) > 0) {
      return { stage, name, state: 'pre', sec: null, ghostSec: 0 };
    }
    if (done && sec != null && sec < 1) {
      return { stage, name, state: 'instant', sec, ghostSec: 0 };
    }
    if (stageErr[stage] || phase === `${stage}_error`) {
      return { stage, name, state: 'error', sec: sec != null ? sec : phaseElapsedSec(), ghostSec: 0 };
    }
    if (done) {
      return {
        stage, name, state: 'done', ghostSec: 0,
        sec: sec != null ? sec : (PIPELINE_STAGE_SEC_BASE[stage] || 1),
        measured: sec != null,
      };
    }
    if (phase === 'error' && !hardErrorMarked) {
      hardErrorMarked = true;
      return { stage, name, state: 'error', sec: sec != null ? sec : phaseElapsedSec(), ghostSec: 0 };
    }
    const budget = (pipelineStageSec[stage] || PIPELINE_STAGE_SEC_BASE[stage] || 1) * factor;
    if (running && stage === curStage) {
      const el = phaseElapsedSec();
      return { stage, name, state: 'active', sec: el, ghostSec: Math.max(0, budget - el) };
    }
    if (dead) return { stage, name, state: 'idle', sec: 0, ghostSec: budget };
    return { stage, name, state: 'est', sec: 0, ghostSec: budget };
  });
}

/**
 * 초 → px 배치. 폭은 실측 초에 비례하고, 라벨이 들어갈 최소폭만 보장한다.
 * 최소폭 클램프로 축이 살짝 늘어난 자리는 눈금도 같은 매핑(secToPx)을 지나므로
 * 눈금과 막대가 서로 다른 말을 하지 않는다. 로그 스케일은 쓰지 않는다 — 비율을 속인다.
 */
function pipelineTimelineLayout(model, trackW, minW) {
  const axis = model.filter((m) => !['pre', 'instant'].includes(m.state));
  const spans = axis.map((m) => Math.max(0.5, (m.sec || 0) + (m.ghostSec || 0)));
  const totalSec = spans.reduce((a, b) => a + b, 0) || 1;
  /* 축의 최소 길이. 캐시가 다 맞아 전체가 10초쯤이면 축이 그 10초에 맞춰 늘어나
     눈금이 촘촘해지고 「다 끝났는데 왜 이러지」 싶게 답답해 보인다. 30초를
     바닥으로 두면 짧은 실행은 축의 앞부분만 쓰고 뒤가 남는다 — 남은 자리는
     아무것도 주장하지 않는 빈 트랙이라 거짓말이 아니다.
     실행이 30초를 넘으면 이 바닥은 아무 일도 하지 않는다. */
  const axisSec = Math.max(totalSec, PIPELINE_TL_MIN_AXIS_SEC);
  const usableW = trackW * (totalSec / axisSec);
  let widths = spans.map((s) => (s / totalSec) * usableW);
  for (let pass = 0; pass < 2; pass += 1) {
    const clamped = widths.map((w) => w < minW);
    const fixed = clamped.reduce((a, c) => a + (c ? minW : 0), 0);
    const rawFree = widths.reduce((a, w, i) => a + (clamped[i] ? 0 : w), 0);
    const scale = rawFree > 0 ? Math.max(0, usableW - fixed) / rawFree : 0;
    widths = widths.map((w, i) => (clamped[i] ? minW : w * scale));
  }
  let secAt = 0;
  let pxAt = 0;
  const pieces = axis.map((m, i) => {
    const p = { stage: m.stage, sec0: secAt, px0: pxAt, secLen: spans[i], pxLen: widths[i] };
    secAt += spans[i];
    pxAt += widths[i];
    return p;
  });
  const usedPx = pxAt;
  const secToPx = (s) => {
    for (let i = 0; i < pieces.length; i += 1) {
      const p = pieces[i];
      if (s <= p.sec0 + p.secLen) {
        const f = p.secLen > 0 ? Math.min(1, Math.max(0, (s - p.sec0) / p.secLen)) : 0;
        return p.px0 + p.pxLen * f;
      }
    }
    /* 단계가 끝난 뒤 남은 축(30초 바닥이 만든 꼬리)은 균등하게 편다 —
       눈금이 여기 놓일 수 있으므로 매핑이 끊기면 안 된다 */
    const tailSec = Math.max(0.001, axisSec - totalSec);
    const k = Math.min(1, Math.max(0, (s - totalSec) / tailSec));
    return usedPx + (trackW - usedPx) * k;
  };
  return { pieces, totalSec, axisSec, secToPx };
}

/** 타임라인 뼈대 — 마운트마다 한 번만 그린다. 이후엔 페인터가 폭·상태만 갈아끼운다 */
function pipelineTimelineHtml(variant) {
  const compact = variant === 'compact';
  const segs = PIPELINE_STAGE_ORDER.map((stage) =>
    `<div class="tl-seg" data-stage="${stage}" data-state="est">`
    + '<i class="tl-fill"></i><i class="tl-ghost"></i>'
    + `<span class="tl-name">${escapeHtml(PIPELINE_STAGE_NAME[stage] || stage)}</span>`
    + '<span class="tl-sec"></span></div>').join('');
  return `<div class="pipe-tl" data-variant="${compact ? 'compact' : 'full'}">
    <div class="tl-pre-chips"></div>
    <div class="tl-ruler" aria-hidden="true"></div>
    <div class="tl-band">
      <div class="tl-track">${segs}</div>
      <div class="tl-playhead" aria-hidden="true"></div>
    </div>
    ${compact ? '<p class="tl-after note" hidden>이제 질문 코칭을 시작할 수 있어요. 상세 리포트는 뒤에서 계속 만들고 있어요.</p>' : ''}
  </div>`;
}

/** 눈금 라벨 — 1분 밑에서는 「30초」가 「00:30」보다 한눈에 읽힌다 */
function tlTickLabel(sec) {
  return sec < 60 ? `${sec}초` : fmtMarkSec(sec);
}

function tlSecText(m) {
  const fmt1 = (s) => (s < 10 ? s.toFixed(1) : String(Math.round(s)));
  if (m.state === 'done') return m.measured ? `${fmt1(m.sec)}초` : '';
  if (m.state === 'error') return `${fmt1(m.sec)}초에 멈췄어요`;
  if (m.state === 'active') {
    return m.ghostSec > 0
      ? `${Math.round(m.sec)}초 · 예상 ${Math.max(1, Math.round(m.sec + m.ghostSec))}초`
      : `${Math.round(m.sec)}초 · 예상을 넘겼어요`;
  }
  // 1초 미만 추정을 0초로 적으면 「0초 예상」이라는 이상한 말이 된다 — 최소 1초
  if (m.state === 'est') return `예상 ${Math.max(1, Math.round(m.ghostSec))}초`;
  return '';
}

const PIPELINE_TL_MIN_PX = { full: 44, compact: 30 };

/* 축이 이보다 짧아지지는 않는다 — 캐시가 다 맞아 10초에 끝나면 눈금이 촘촘해져
   답답해 보인다 (2026-08-07 사용자 요청) */
const PIPELINE_TL_MIN_AXIS_SEC = 30;

/** 새 행·칩의 등장 한 번. Motion 스프링이 있으면 쓰고, 없거나 모션 최소화면 그냥 보여준다 */
function motionPop(el) {
  if (!el || !window.Motion || !window.Motion.animate) return;
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  window.Motion.animate(el, { y: [8, 0], opacity: [0, 1] }, { type: 'spring', stiffness: 340, damping: 26 });
}

/** 마운트 직후 구간들이 왼쪽부터 차례로 자리를 잡는다 — 한 번뿐인 입장 연출 */
function motionTimelineIntro(host) {
  if (!host || !window.Motion || !window.Motion.animate) return;
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const segs = host.querySelectorAll('.tl-seg');
  if (segs.length) {
    window.Motion.animate(segs, { opacity: [0, 1], y: [5, 0] },
      { delay: window.Motion.stagger(0.05), duration: 0.35, ease: 'easeOut' });
  }
}

/** in-place 페인터. 스텝 4 와 F-11 띠의 타임라인을 한 번에 갱신한다 — 자식을
    다시 만들지 않고 폭·상태·문구만 바꿔서 CSS 전이가 모션을 만들게 한다 */
function paintPipelineTimeline() {
  const hosts = $$('.pipe-tl');
  if (!hosts.length) return;
  const model = pipelineTimelineModel();
  const phase = nf.pipelinePhase || 'queued';
  hosts.forEach((host) => {
    const track = host.querySelector('.tl-track');
    if (!track || !track.clientWidth) return;
    const minW = PIPELINE_TL_MIN_PX[host.dataset.variant] || 44;
    const layout = pipelineTimelineLayout(model, track.clientWidth, minW);

    // 축 밖 칩 — 발표 중에 미리 끝났거나 1초 미만에 끝난 단계
    const chipHost = host.querySelector('.tl-pre-chips');
    model.filter((m) => m.state === 'pre' || m.state === 'instant').forEach((m) => {
      /* 0.05초짜리를 반올림해 「0.0초 만에 끝났어요」라고 쓰면 숫자가 고장으로
         읽힌다. 사람은 그 구간을 «바로» 라고 부른다 (2026-08-07 지적) */
      const text = m.state === 'pre'
        ? `${m.name} · 발표하는 동안 미리 끝냈어요`
        : m.sec < 0.05 ? `${m.name} · 바로 끝났어요`
          : `${m.name} · ${m.sec.toFixed(1)}초 만에 끝났어요`;
      let tlChip = chipHost && chipHost.querySelector(`.tl-chip[data-stage="${m.stage}"]`);
      if (!tlChip && chipHost) {
        tlChip = document.createElement('span');
        tlChip.className = 'tl-chip';
        tlChip.dataset.stage = m.stage;
        chipHost.appendChild(tlChip);
        motionPop(tlChip);
      }
      if (tlChip && tlChip.textContent !== text) tlChip.textContent = text;
    });

    // 축 위 구간
    let playheadPx = 0;
    model.forEach((m) => {
      const seg = track.querySelector(`.tl-seg[data-stage="${m.stage}"]`);
      if (!seg) return;
      const off = m.state === 'pre' || m.state === 'instant';
      seg.dataset.state = off ? 'off' : m.state;
      if (off) return;
      const piece = layout.pieces.find((p) => p.stage === m.stage);
      if (!piece) return;
      seg.style.width = `${Math.round(piece.pxLen)}px`;
      const fillFrac = (m.state === 'done' || m.state === 'error') ? 1
        : (m.state === 'active'
          ? (m.ghostSec > 0 ? Math.min(1, m.sec / piece.secLen) : 1)
          : 0);
      const fill = seg.querySelector('.tl-fill');
      const ghost = seg.querySelector('.tl-ghost');
      if (fill) fill.style.width = `${Math.round(fillFrac * 100)}%`;
      if (ghost) ghost.style.width = m.state === 'idle' || m.state === 'est' || m.state === 'active'
        ? `${Math.round((1 - fillFrac) * 100)}%` : '0%';
      seg.classList.toggle('is-overrun', m.state === 'active' && m.ghostSec <= 0);
      const secEl = seg.querySelector('.tl-sec');
      const secText = tlSecText(m);
      if (secEl && secEl.textContent !== secText) secEl.textContent = secText;
      /* 칸이 글자보다 좁으면 이름을 지운다. 「흐름 비」처럼 잘린 채로 두면
         화면이 깨진 것으로 읽힌다 — 이름은 title 로 남아 손을 올리면 보인다 */
      seg.classList.toggle('is-tight', piece.pxLen < 68);
      seg.title = `${m.name}${secText ? ` · ${secText}` : ''}`;
      if (host.dataset.variant === 'compact') seg.title = `${m.name}${secText ? ` · ${secText}` : ''}`;
      if (['done', 'error'].includes(m.state)) playheadPx = piece.px0 + piece.pxLen;
      else if (m.state === 'active') playheadPx = piece.px0 + piece.pxLen * fillFrac;
    });

    // 재생 헤드 — 완료 폭의 끝 = 실제로 지나온 지점. 예상 위로는 절대 앞서가지 않는다
    const ph = host.querySelector('.tl-playhead');
    if (ph) ph.style.transform = `translateX(${Math.round(playheadPx)}px)`;

    // 눈금 — 막대와 같은 secToPx 를 지나므로 서로 어긋나지 않는다
    const ruler = host.querySelector('.tl-ruler');
    if (ruler) {
      /* 눈금 간격은 개수가 아니라 **글자가 안 겹칠 폭**으로 정한다.
         「≤8개」로만 잡았더니 축이 14초일 때 2초 간격 일곱 개가 60px 안에 들어가
         「10초2초4초6초8초12초」처럼 붙어 버렸다 — 라벨 하나가 34px 쯤 되니
         최소 62px 을 띄운다 (2026-08-07 사용자 지적). */
      const trackW = track.clientWidth || 1;
      const TICK_MIN_PX = 62;
      const maxTicks = Math.max(2, Math.floor(trackW / TICK_MIN_PX));
      const iv = [1, 2, 5, 10, 15, 30, 60, 120, 300].find(
        (s) => layout.axisSec / s <= maxTicks) || 600;
      const want = [];
      /* 마지막 눈금이 오른쪽 끝에 딱 붙으면 잘린 것처럼 보인다. 한 칸 앞에서 멈춘다 */
      for (let s = iv; s < layout.axisSec - iv * 0.35; s += iv) want.push(s);
      const seen = new Set(want.map(String));
      Array.from(ruler.querySelectorAll('.tl-tick')).forEach((t) => {
        if (!seen.has(t.dataset.sec)) t.remove();
      });
      want.forEach((s) => {
        let tick = ruler.querySelector(`.tl-tick[data-sec="${s}"]`);
        if (!tick) {
          tick = document.createElement('span');
          tick.className = 'tl-tick';
          tick.dataset.sec = String(s);
          tick.textContent = tlTickLabel(s);
          ruler.appendChild(tick);
        }
        tick.style.left = `${Math.round(layout.secToPx(s))}px`;
      });
    }

    const after = host.querySelector('.tl-after');
    if (after) {
      after.hidden = !(pipelineQaReady() && !['done', 'partial', 'error'].includes(phase));
    }
  });
}

/** 파이프라인 실측 이벤트 한 줄. 만들 수 없는 phase 면 null — 지어내지 않는다 */
function pipelineLogLine(phase) {
  const out = nf.pipelineOut || {};
  const detail = String(nf.pipelineDetail || '');
  if (phase === 'queued') {
    // 선분석 여부는 buildPipelineMarks 가 임계경로에서 0폭으로 뺀 결과가 근거다
    const preDone = (pipelineStageSec.concepts || 0) <= 0 || (pipelineStageSec.graph || 0) <= 0;
    return preDone
      ? { kind: 'pre', text: '발표하는 동안 자료의 개념을 미리 정리해 뒀어요' }
      : { kind: 'start', text: '녹음을 넘겨받았어요' };
  }
  if (phase === 'graph_done' && out.graph && Array.isArray(out.graph.nodes) && out.graph.nodes.length) {
    const nodes = out.graph.nodes;
    const names = nodes.slice(0, 2).map((n) => `'${n.label}'`).join(' · ');
    return { kind: 'done', text: `${names} 등 개념 ${nodes.length}개를 발표와 대조할 준비를 했어요` };
  }
  if (phase === 'done') {
    const total = Math.max(0, Math.floor((Date.now() - (nf.pipelineStartedAt || Date.now())) / 1000));
    return { kind: 'done', text: `상세 리포트까지 다 만들었어요 · 총 ${total}초` };
  }
  if (phase === 'partial') {
    return { kind: 'error', text: `일부만 끝났어요 · ${humanErrorText(detail)}` };
  }
  if (phase === 'error') {
    return { kind: 'error', text: humanErrorText(nf.pipelineError || detail) };
  }
  if (/_error$/.test(phase)) {
    return { kind: 'error', text: `${pipelinePhaseLabel(phase)} · ${humanErrorText(detail)}` };
  }
  if (/_done$/.test(phase)) {
    return { kind: 'done', text: detail ? `${pipelinePhaseLabel(phase)} · ${detail}` : pipelinePhaseLabel(phase) };
  }
  return null;
}

function pipelineFeedRowHtml(entry) {
  return `<li class="feed-row" data-kind="${escapeHtml(entry.kind || 'done')}">`
    + `<span class="feed-time">${fmtMarkSec(entry.sec || 0)}</span>`
    + `<span>${escapeHtml(entry.text || '')}</span></li>`;
}

/**
 * 라이브 피드에 한 줄 쌓는다. nf._pipelineLog 가 원본이고 DOM 은 투영이다 —
 * 화면이 다시 그려져도 기록이 사라지지 않는 건 backstage 와 같은 이유다.
 * 기록은 절대 소급 수정하지 않는다. 실패 줄도 이전 줄을 지우지 않는다.
 */
function pushPipelineLog(phase) {
  const line = pipelineLogLine(phase);
  if (!line) return;
  if (!Array.isArray(nf._pipelineLog)) nf._pipelineLog = [];
  if (nf._pipelineLog.some((l) => l.phase === phase)) return;   // 같은 단계는 한 번만
  const sec = Math.max(0, Math.floor((Date.now() - (nf.pipelineStartedAt || Date.now())) / 1000));
  const entry = { ...line, phase, sec };
  nf._pipelineLog.push(entry);
  $$('.pipe-feed .feed-live').forEach((ul) => {
    ul.insertAdjacentHTML('beforeend', pipelineFeedRowHtml(entry));
    motionPop(ul.lastElementChild);
  });
}

const PIPELINE_FEED_MAX_ROWS = 8;

/** 라이브 피드 마크업 — 지난 기록은 접고 최근 몇 줄과 「지금 하는 일」만 편다 */
/**
 * 라이브 피드. **지금은 화면에 안 붙인다** (2026-08-09 사용자 지적).
 *
 * 바로 아래 체크리스트와 「지금까지 한 일」을 두 번 말하고 있었다. 남긴 쪽이
 * 체크리스트인 이유: 다섯 단계가 고정 목록이라 **남은 일까지** 보이는데,
 * 피드는 끝난 것만 쌓여서 얼마나 남았는지가 안 보인다.
 *
 * 사라지는 정보는 없다 — 실측 수치(단어 수·슬라이드 구간 수)는 아래 검증 로그가
 * 그대로 들고 있고, 지금 무엇을 하는 중인지는 위 상태 막대가 말한다.
 * 함수는 지우지 않는다. 마감 전이라 되돌릴 여지를 남긴다 (CLAUDE.md §4).
 * 원본 기록(nf._pipelineLog)도 계속 쌓인다 — 죽은 실행을 되짚는 근거다.
 */
function pipelineFeedHtml() {
  const log = Array.isArray(nf._pipelineLog) ? nf._pipelineLog : [];
  const recent = log.slice(-PIPELINE_FEED_MAX_ROWS);
  const older = log.slice(0, -PIPELINE_FEED_MAX_ROWS);
  const phase = nf.pipelinePhase || 'queued';
  const final = ['done', 'partial', 'error'].includes(phase);
  return `<div class="pipe-feed">
    ${older.length ? `<details class="feed-old"><summary>이전 기록 ${older.length}줄</summary>
      <ul class="feed-list">${older.map(pipelineFeedRowHtml).join('')}</ul></details>` : ''}
    <ul class="feed-list feed-live">${recent.map(pipelineFeedRowHtml).join('')}</ul>
    <div class="feed-now${final ? ' is-final' : ''}"><i></i>
      <span class="feed-now-label">${escapeHtml(pipelinePhaseLabel(phase))}</span>
      <span class="feed-now-sec"></span>
    </div>
  </div>`;
}

/** 「지금 하는 일」 줄 — 단계 라벨과 그 단계에서 흐른 초 */
function paintPipelineFeedNow() {
  const phase = nf.pipelinePhase || 'queued';
  const final = ['done', 'partial', 'error'].includes(phase);
  $$('.pipe-feed .feed-now').forEach((el) => {
    el.classList.toggle('is-final', final);
    const label = el.querySelector('.feed-now-label');
    const sec = el.querySelector('.feed-now-sec');
    if (label) label.textContent = pipelinePhaseLabel(phase);
    if (sec) sec.textContent = final ? '' : `${Math.floor(phaseElapsedSec())}초째`;
  });
}

/** F-11 띠의 체크리스트를 통째로 다시 그리지 않고 상태만 갈아끼운다 —
    innerHTML 재작성은 띠 안 타임라인의 폭 전이를 매 틱 처음으로 되감는다 */
function paintPipelineChecklist() {
  $$('.f11-chrome .checklist').forEach((ul) => {
    const items = pipelineChecklistItems();
    const stage = pipelineStageOf(nf.pipelinePhase || 'queued');
    if (ul.children.length !== items.length) return;
    items.forEach((it, i) => {
      const st = it.ok ? 'done' : (it.stage === stage ? 'doing' : 'todo');
      const li = ul.children[i];
      if (li.className !== st) li.className = st;
      const icon = li.querySelector('i');
      const want = it.ok ? '✓' : String(i + 1);
      if (icon && icon.textContent !== want) icon.textContent = want;
    });
  });
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
    return n ? { who: 'solar', text: `슬라이드 ${n}개, 다 읽었어` } : null;
  }
  if (phase === 'graph_done') {
    const n = out.graph && (out.graph.nodes || []).length;
    return n ? { who: 'solar', text: `개념 ${n}개 정리 끝!` } : null;
  }
  if (phase === 'align_done') {
    const cov = out.alignment && out.alignment.summary && out.alignment.summary.coverage;
    if (typeof cov === 'number') {
      return { who: 'midm', text: `커버 ${Math.round(cov * 100)}%… 빠진 개념이 있어` };
    }
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

  // 업로드본은 전환 기록이 없어 서버(F-04 파생)가 구간을 되짚는다. 그 결과가
  // 측정값처럼 읽히면 안 된다 — 아래 슬라이드↔발화 매핑이 이 값 위에 서 있다.
  //
  // 예전엔 늘 "길이를 N등분한 합성값" 이라고 썼는데, 되짚기가 성공한 경우엔 그게
  // 거짓말이었다 (균등 분할이 아니라 내용으로 맞춘 구간이다). 반대로 녹음이 자료와
  // 아예 다른 경우엔 **왜** 못 맞췄는지가 사용자에게 가장 중요한 정보인데, 그 문장이
  // 진행 로그에만 남고 화면에는 안 보였다 (2026-08-08 제보: "PPT 와 다른 내용의
  // 녹음본을 올리면 아예 인식을 못 한다"). 서버의 marks_reason 이 두 경우를 이미
  // 구분해 말하므로 그대로 싣는다 (§14 정직한 상태 유지).
  const up = nf.uploadedTake;
  const markReason = (transcript && transcript.marks_reason) || '';
  // 'unrelated' 는 구간을 못 맞춘 것이 아니라 다른 발표의 파일을 올렸다는
  // 판정이다 (f04 실측 임계). 안내가 아니라 경고로 세운다 — 이 경우 아래
  // 슬라이드↔발화 매핑 전체가 균등 분할 위의 허수다.
  const markUnrelated = !!(transcript && transcript.marks_match === 'unrelated');
  const markFallback = `슬라이드 구간은 <b>실제 전환 기록이 아니라 길이를 ${marks.length}등분한 합성값</b>이에요.`;
  const uploadedNote = up
    ? (isShowcaseDemo()
      ? `<p class="note">녹음 <b>${escapeHtml(up.name)}</b>
         (${fmtMarkSec(up.durationSec)})으로 분석했어요.
         ${markReason ? escapeHtml(markReason) : '슬라이드 전환 기록에 맞춰 발화 구간을 나눴어요.'}</p>`
      : `<p class="note" style="color:${markUnrelated ? 'var(--no)' : 'var(--mid)'}">업로드한 녹음 <b>${escapeHtml(up.name)}</b>
       (${fmtMarkSec(up.durationSec)})으로 돌렸어요.
       ${markReason ? (markUnrelated ? `<b>${escapeHtml(markReason)}</b>` : escapeHtml(markReason)) : markFallback}
       슬라이드별 발화 분할과 정합 판정은 참고용으로만 보세요.</p>`)
    : '';

  let speechHtml = '';
  if (transcript && transcript.error) {
    speechHtml = `<p class="note" style="color:var(--no)">${escapeHtml(transcript.message || transcript.error)}</p>`;
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
    speechHtml = `<p class="note" style="color:var(--no)">받아쓰기까지 도달하지 못했어요: ${escapeHtml(nf.pipelineError)}</p>`;
  } else {
    speechHtml = pipelineLoadingHtml('stt') || '<p class="note">받아쓴 내용을 기다리는 중…</p>';
  }

  let conceptHtml = '';
  if (concepts && !concepts.error && Array.isArray(concepts.slides)) {
    conceptHtml = `<details class="pipe-block" open><summary>개념 추출 (슬라이드 ${concepts.slides.length}개)</summary>
      <ul class="pipe-concepts">${concepts.slides.slice(0, 12).map((s) =>
        `<li><b>${s.slide_no}.</b> ${escapeHtml(s.topic || s.title || '')}
         <span>${escapeHtml((s.concepts || []).slice(0, 3).join(' · '))}</span></li>`
      ).join('')}</ul></details>`;
  } else if (conceptsError) {
    conceptHtml = `<details class="pipe-block" open><summary>개념 추출 (실패)</summary>
      <p class="note" style="color:var(--no)">${escapeHtml(conceptsError)}</p>
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
    paintPipelineTimeline();
    paintPipelineFeedNow();
    paintPipelineChecklist();
  }, 1000);
}

/**
 * 파이프라인이 끝났을 때만 스텝 4 를 다시 그린다.
 *
 * 실 LLM 파이프라인은 7분도 걸린다. 그 사이 사용자가 리포트나 질문코치로 넘어가
 * 있으면, 완료 콜백이 app.innerHTML 을 덮어써 보던 화면을 통째로 날려버린다.
 */
function refreshStep4IfVisible() {
  // 라우트 키가 정확히 'new' 일 때만 다시 그린다. 예전 정규식(/^#\/?(new)?(\/|$)/)은
  // '#' 뒤 어디서든 '/' 하나만 있으면 참이라 #/qa·#/report·홈까지 전부 통과했다 —
  // 파이프라인 후반부 완료 틱이 질문 코칭 화면을 스텝4로 덮어썼고, 해시는 이미
  // #/qa 라 「질문 코칭 시작하기」(href="#/qa")를 눌러도 아무 일도 안 일어났다.
  const key = (location.hash || '#/').replace(/^#\/?/, '').split('/')[0];
  if (key === 'new' && nf.step === 3) nfStep4();
}

function clientSamplePipelineData() {
  const duration = Math.max(180, Number((ccLastTake && ccLastTake.durationSec) || nf.sec) || 180);
  const marks = (ccLastTake && ccLastTake.marks && ccLastTake.marks.length)
    ? ccLastTake.marks
    : evenSlideMarks(duration, rehearsalCount());
  const topicBySlide = Object.fromEntries((DATA.tree || []).map((node) => [slideNumber(node.slide), node]));
  const bySlide = marks.map((mark) => {
    const no = Number(mark.slide_no) || 1;
    const topic = topicBySlide[no];
    return {
      slide_no: no,
      visit: mark.visit || 1,
      start_sec: Number(mark.start_sec) || 0,
      end_sec: Number(mark.end_sec) || 0,
      text: (topic && topic.ev) || `${DATA.slideTitles[no - 1] || `${no}번 슬라이드`}의 핵심 내용을 설명했습니다.`,
    };
  });
  const concepts = {
    slides: DATA.slideTitles.map((title, index) => {
      const node = topicBySlide[index + 1];
      return { slide_no: index + 1, title, topic: title, concepts: node ? [node.label] : [] };
    }),
  };
  const nodes = (DATA.tree || []).map((node) => ({
    id: node.id,
    label: node.label,
    slide_no: slideNumber(node.slide),
    status: node.status,
    importance: node.w,
  }));
  const graph = {
    nodes,
    edges: (DATA.tree || []).filter((node) => node.parent).map((node) => ({ source: node.parent, target: node.id })),
  };
  const alignment = {
    items: (DATA.tree || []).map((node) => ({
      node_id: node.id,
      slide_no: slideNumber(node.slide),
      status: node.status,
      confidence: node.conf,
      evidence: node.ev || node.spokeSays || '',
      reason: node.why || '',
    })),
  };
  const flow = {
    order_tau: 0.82,
    ghost_node_ids: (DATA.tree || []).filter((node) => ['no', 'om'].includes(node.status)).map((node) => node.id),
    issues: (DATA.logicBreaks || []).map((issue) => ({
      type: issue.type,
      from_slide: Number(String(issue.from || '').replace(/\D/g, '')) || null,
      to_slide: Number(String(issue.to || '').replace(/\D/g, '')) || null,
      evidence: issue.ev || '',
      suggestion: issue.note || '',
      good: !!issue.good,
    })),
  };
  return {
    transcript: {
      full_text: bySlide.map((part) => part.text).join(' '),
      duration_sec: duration,
      provider: 'sample-demo',
      by_slide: bySlide,
      words: [],
    },
    concepts,
    graph,
    alignment,
    flow,
    score: { total: DATA.session.score, dimensions: DATA.session.dims },
  };
}

function runClientSamplePipeline() {
  if (nf._samplePipelineStarted) return;
  nf._samplePipelineStarted = true;
  nf._pipelineStarted = true;
  nf.pipelineError = null;
  nf.pipelineStartedAt = Date.now();
  nf._phaseStartedAt = Date.now();
  nf._pipelineLog = [];
  nf.backstage = [];
  pipelineRunLive = true;
  buildPipelineMarks({ conceptsReady: false, graphReady: false });
  const sample = clientSamplePipelineData();
  const stages = [
    { delay: 100, phase: 'encoding', detail: '샘플 녹음을 정리하고 있어요' },
    { delay: 800, phase: 'stt_done', detail: '샘플 전사문을 슬라이드별로 나눴어요', data: { transcript: sample.transcript } },
    { delay: 1500, phase: 'concepts_done', detail: '발표자료의 핵심 개념을 찾았어요', data: { concepts: sample.concepts } },
    { delay: 2300, phase: 'graph_done', detail: '개념 사이 연결을 정리했어요', data: { graph: sample.graph } },
    { delay: 3100, phase: 'align_done', detail: '자료와 샘플 발화를 대조했어요', data: { alignment: sample.alignment } },
    { delay: 3900, phase: 'flow_done', detail: '발표 흐름을 비교했어요', data: { flow: sample.flow } },
    { delay: 4700, phase: 'done', detail: '샘플 분석이 끝났어요', data: { score: sample.score } },
  ];
  stages.forEach((stage) => later(() => {
    nf.pipelinePhase = stage.phase;
    nf.pipelineDetail = stage.detail;
    nf._phaseStartedAt = Date.now();
    if (stage.data) nf.pipelineOut = { ...(nf.pipelineOut || {}), ...stage.data };
    if (stage.phase === 'stt_done') nf.transcriptOk = true;
    if (stage.phase === 'concepts_done') nf.conceptsOk = true;
    pushBackstage(stage.phase);
    pushPipelineLog(stage.phase);
    nf.done = pipelineChecklistDone();
    if (stage.phase === 'done') pipelineRunLive = false;
    saveSession('new-flow', nf);
    refreshStep4IfVisible();
    if (stage.phase === 'done') {
      later(() => {
        if (location.hash.startsWith('#/new')) location.hash = '#/report/sample-imu2clip';
      }, 1600);
    }
  }, stage.delay));
}

function nfStep4() {
  app.className = 'narrow';
  const sampleRun = !!(nf.useSample && ccLastTake);
  if (sampleRun && !['done', 'partial', 'error'].includes(nf.pipelinePhase || '')) pipelineRunLive = true;
  /* 새로고침으로 복원된 세션이면 파이프라인 프라미스는 이미 죽어 있다. 살아 있는 척
     초를 계속 세면 문구 전부가 거짓말이 된다 — 끊겼다고 말하고 멈춘다. */
  const willStart = !!(ccLastTake && !nf._pipelineStarted
    && (isShowcaseDemo() || (!sampleRun && window.ChuckchuckBridge)));
  if (!willStart && !pipelineRunLive && nf.pipelinePhase
      && !['done', 'partial', 'error'].includes(nf.pipelinePhase)) {
    if (pipelineQaReady()) {
      nf.pipelinePhase = 'partial';
      nf.pipelineDetail = '화면을 새로 고치면서 상세 리포트 만들기가 끊겼어요';
    } else {
      nf.pipelineError = nf.pipelineError
        || '화면을 새로 고치면서 분석이 끊겼어요. 다른 녹음으로 다시 시작하면 돼요';
      nf.pipelinePhase = 'error';
      nf.pipelineDetail = nf.pipelineError;
    }
    pushPipelineLog(nf.pipelinePhase);   // 끊겼다는 사실도 기록의 한 줄이다
  }
  const items = pipelineChecklistItems();
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
      ${nf.useSample ? '<p class="sample-analysis-note"><b>샘플 데모 분석</b> · 녹음 과정은 실제지만 아래 판정과 리포트는 준비된 예시 데이터예요.</p>' : ''}
      ${pipelineStatusBarHtml()}
      ${pipelineTimelineHtml('full')}
      ${backstageHtml()}
      ${pipeErr}
      ${pipelineChecklistHtml()}
      ${pipelineInspectHtml()}
      <div class="step-actions">
        <button class="btn btn-secondary" type="button" data-fresh-practice>처음부터 다시</button>
        <button class="btn btn-secondary btn-sm" type="button" id="againTake">다른 녹음으로 다시</button>
        <a class="btn btn-text btn-sm skip-qa" href="${isShowcaseDemo() ? showcaseReportHref() : '#/report'}">질문코치 건너뛰고 상세 리포트</a>
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
  // 첫 틱(1초)을 기다리면 타임라인이 빈 뼈대로 보인다. 붙이자마자 한 번 칠한다.
  paintPipelineTimeline();
  paintPipelineFeedNow();
  // 입장 연출은 실행당 한 번 — 산출물이 올 때마다 화면을 다시 그리는데 그때마다
  // 구간이 다시 날아들면 연출이 데이터 읽기를 방해한다
  if (tlIntroPlayedAt !== nf.pipelineStartedAt) {
    tlIntroPlayedAt = nf.pipelineStartedAt || 0;
    motionTimelineIntro($('.pipe-tl[data-variant="full"]'));
  }

  const again = $('#againTake');
  // 자료(nfSlideDoc·uploadedPdf)는 그대로 두고 테이크만 버린다 — resetNf 와 다르다
  if (again) again.addEventListener('click', () => {
    stopLiveRehearsal();
    showcasePipeGen += 1;
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
    nf._samplePipelineStarted = false;
    nf.pipelineOut = null;
    nf.pipelineError = null;
    nf.pipelinePhase = null;
    nf.pipelineDetail = null;
    nf.transcriptOk = false;
    nf.conceptsOk = false;
    nf.backstage = [];
    nf._pipelineLog = [];
    nf._stageActual = null;   // 남겨 두면 스텝 2·3 로 돌아간 화면에 지난 테이크의 칩이 뜬다
    nf.step = 2;
    // 질문 코칭은 버리는 테이크의 발화로 만든 것이라 같이 버린다 — 남겨 두면
    // 새 녹음 분석이 끝나도 qaLiveActive() 가 참이라 지난 녹음의 질문이 그대로 나온다.
    resetQa();
    saveSession('new-flow', nf);
    renderNew();
  });

  if (ccLastTake && !nf._pipelineStarted && isShowcaseDemo()) {
    beginShowcasePipeline();
    return;
  }
  if (sampleRun && !nf._samplePipelineStarted) runClientSamplePipeline();

  if (!sampleRun && ccLastTake && window.ChuckchuckBridge && !nf._pipelineStarted) {
    nf._pipelineStarted = true;
    nf.pipelineError = null;
    nf.pipelinePhase = 'queued';
    nf.pipelineDetail = '파이프라인 시작';
    nf.pipelineStartedAt = Date.now();
    nf._stageActual = null;   // 지난 테이크의 실측이 남아 있으면 이번 추정이 그걸 따라간다
    nf._pipelineLog = [];     // 피드도 이번 실행의 기록만 — 지난 테이크 줄이 섞이면 안 된다
    pipelineRunLive = true;
    nf.transcriptOk = false;
    nf.conceptsOk = false;

    /* 진행률 표는 여기서 한 번만 만든다. 발표하는 동안 F-06·F-07 이 이미 끝났으면
       그 구간은 폭이 0 이 되고 남은 폭이 넓어진다. 중간에 다시 만들면 막대가 뒤로 간다 —
       한 번 지나온 %가 줄어드는 건 진행률이 아니라 소음이다. */
    const preState = (precompute && precompute.key === precomputeKey() && precompute.state) || {};
    buildPipelineMarks(preState);
    pushPipelineLog('queued');   // 첫 줄 — 선분석을 미리 끝냈으면 그 사실이 0초 기록으로 남는다
    refreshPipelineInspect();

    // slideDoc 이 없으면 F-06 이후가 통째로 안 돈다. 캐시에서 먼저 되살린다.
    ensureSlideDoc().then((slideDoc) => window.ChuckchuckBridge.runPreparePipeline({
      marks: ccLastTake.marks,
      blob: ccLastTake._blob,
      mimeType: ccLastTake.mimeType,
      fileName: ccLastTake.fileName || '',
      slideDoc,
      // #/replay 로 들어온 테이크는 저장된 받아쓰기를 그대로 쓴다 (재녹음·재과금 없음)
      reuse: !!ccLastTake.reuse,
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
        // 라이브 피드에도 같은 시점의 실측 한 줄 — 병아리 대사와 달리 기술 기록이다
        pushPipelineLog(phase);
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
          /* 산출물이 하나 늘 때마다 저장한다 — 새로고침해도 타임라인 실측·피드 기록이
             남아, 죽은 실행을 「어디까지는 했다」로 정직하게 보여줄 수 있다 */
          saveSession('new-flow', nf);
        } else {
          refreshPipelineInspect();
          paintPipelineStatusBar();
          // 단계가 막 시작된 순간이다. 다음 1초 틱을 기다리지 않고 바로 옮겨 칠한다
          paintPipelineTimeline();
          paintPipelineFeedNow();
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
      pushPipelineLog(nf.pipelinePhase);   // 총 소요 실측이 피드의 마지막 줄이 된다
      refreshStep4IfVisible();
      saveSession('new-flow', nf);
      if (!failed) autoAdvanceToQa();
    }).catch((err) => {
      console.warn('[chuckchuck] prepare pipeline', err);
      nf.pipelineError = err.message || String(err);
      nf.pipelinePhase = 'error';
      nf.pipelineDetail = nf.pipelineError;
      // 부분 결과가 있으면 유지
      nf.done = pipelineChecklistDone();
      pushPipelineLog('error');
      refreshStep4IfVisible();
      saveSession('new-flow', nf);
    });
  }
}

/* ══ 리포트 ══ */

/** 업로드·실연동 세션이면 true. 샘플 IMU2CLIP 데모와 구분한다. */
/* 「샘플」이라고 써 붙인 리포트를 보는 중인가. 홈에서 샘플 행을 눌러 들어왔는데
   내 실제 분석이 그 밑에 뜨면 라벨이 거짓말이 된다 — 방향만 반대인 같은 병이다 */
let rSampleMode = false;

/**
 * 리포트 탭이 읽어도 되는 파이프라인 결과.
 *
 * 탭들이 저마다 `nf && nf.pipelineOut` 을 직접 읽고 있었다. isLiveReportSession()
 * 은 rSampleMode 를 보는데 이 직독들은 안 봐서, 「샘플」 딱지를 붙인 리포트
 * 밑에 내 실제 발표 데이터가 섞여 떴다 — 라벨이 거짓말을 한다(§4 정직성).
 * 열다섯 곳에 가드를 흩는 대신 통로를 하나로 만든다. 샘플을 보는 중이면
 * 결과가 없는 것으로 친다: 호출부는 이미 전부 「없으면 DATA 샘플」 분기를 갖고 있다.
 */
function reportOut() {
  const out = (nf && nf.pipelineOut) || null;
  if (rSampleMode) {
    /* 샘플 딱지 리포트: 개념·흐름은 DATA, 말하기(F-17/F-18 간투어)만 stub/fixture 를 연다.
       전부 null 로 막으면 「자주 쓴 간투어」 카드가 말하기 탭에서 사라진다. */
    if (!out || !(out.pace || out.habits)) return null;
    return {
      pace: out.pace || null,
      habits: out.habits || null,
      report: out.report || null,
    };
  }
  return out;
}

/** 채점표(F-14) 결과. 시연·샘플 리포트는 DATA.score(채점표 v3)를 쓴다. */
function reportScore() {
  const live = reportOut();
  if (live && live.score && typeof live.score.score === 'number') return live.score;
  if ((rSampleMode || isShowcaseDemo()) && DATA.score && typeof DATA.score.score === 'number') {
    return DATA.score;
  }
  return null;
}

/**
 * 업로드 세션 자체(nf)를 리포트가 읽어도 되는가.
 *
 * reportOut() 은 pipelineOut 만 막는다. 그런데 내 자료에서 온 값이 그 밖에도
 * 있다 — slideTitles·transcriptOk 처럼 파이프라인을 안 거치고 nf 에 바로 붙는
 * 것들이다. 이걸 빼먹으면 「샘플」 리포트의 순서표에 내 발표 슬라이드 제목이
 * 그대로 뜬다. 같은 병이라 같은 모양으로 막는다.
 */
function reportNf() {
  return rSampleMode ? null : (nf || null);
}

function isLiveReportSession() {
  if (rSampleMode) return false;
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
  const out = reportOut();
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
    occasion: occLabel(nf.occ) || '발표 연습',
    slides,
    duration,
    nth: 1,
  };
}

let rTab = 0, jSel = 'lossav', jFilter = 'all', mapWeakOnly = false, repSlide = 8;

/* ─── 저장해 둔 마지막 리포트 (#/report/last) ──────────────────────────────
   개발·시연 준비용이다. 화면 한 장 보려고 매번 녹음하고 질문 코칭까지 할 수는
   없다. 세션(sessionStorage)은 탭을 닫으면 날아가므로, 마지막으로 **성공한**
   분석 한 벌만 localStorage 에 따로 남겨 두고 주소로 다시 연다.

   데모 흐름에는 링크를 걸지 않는다 — 주소를 직접 쳐야 열린다. 심사 중에
   「지난 리포트」가 화면에 보이면 방금 한 발표의 결과와 헷갈린다.
   열었을 때는 저장본이라는 것과 저장 시각을 띠로 남긴다 (CLAUDE.md §4:
   샘플·과거 데이터를 지금 것인 양 보여주지 않는다). */
const LAST_REPORT_KEY = 'cheokcheok:last-report';

/** 2026.08.08 15:04 — 며칠 전 것을 오늘 것으로 읽지 않게 시각까지 적는다 */
function stampText(ms) {
  const d = new Date(ms || 0);
  if (!ms || Number.isNaN(d.getTime())) return '언젠가';
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())} `
    + `${p(d.getHours())}:${p(d.getMinutes())}`;
}

function saveLastReport() {
  try {
    const out = nf.pipelineOut || {};
    localStorage.setItem(LAST_REPORT_KEY, JSON.stringify({
      at: Date.now(),
      fileName: nf.fileName || '',
      occ: nf.occ || '', ctx: nf.ctx || '',
      min: nf.min || 0, sec: nf.sec || 0,
      slideTitles: nf.slideTitles || null,
      slideDocMeta: nf.slideDocMeta || null,
      pipelinePhase: nf.pipelinePhase || 'done',
      /* 슬라이드 이미지(base64)는 뺀다. localStorage 는 5MB 라 몇 장만 넣어도
         quota 를 넘고, 넘으면 저장이 **통째로** 실패한다 — 썸네일 하나 살리려다
         리포트를 통째로 잃는다. 다시 열면 썸네일만 자리표시자로 뜬다. */
      pipelineOut: {
        graph: out.graph || null,
        alignment: out.alignment || null,
        flow: out.flow || null,
        score: out.score || null,
        pace: out.pace || null,
        habits: out.habits || null,
        report: out.report || null,
        transcript: out.transcript ? {
          full_text: out.transcript.full_text || '',
          duration_sec: out.transcript.duration_sec || 0,
          provider: out.transcript.provider || '',
          // 「아예 다른 내용」 경고가 복원한 리포트에서도 서야 한다 —
          // 판정 없이 점수만 남으면 그 점수가 허수라는 사실이 사라진다
          marks_match: out.transcript.marks_match || '',
          marks_reason: out.transcript.marks_reason || '',
        } : null,
      },
    }));
  } catch (_) { /* quota·프라이빗 모드: 편의 기능이라 실패해도 화면은 그대로 */ }
}

/** 저장본을 nf 에 얹는다. 성공하면 저장 시각(ms), 없으면 0. */
function restoreLastReport() {
  let snap = null;
  try { snap = JSON.parse(localStorage.getItem(LAST_REPORT_KEY)); }
  catch (_) { return 0; }
  if (!snap || !snap.pipelineOut || !snap.pipelineOut.score) return 0;
  Object.assign(nf, {
    fileName: snap.fileName, occ: snap.occ, ctx: snap.ctx,
    min: snap.min, sec: snap.sec,
    slideTitles: snap.slideTitles, slideDocMeta: snap.slideDocMeta,
    pipelinePhase: snap.pipelinePhase, pipelineOut: snap.pipelineOut,
    // 저장본은 실측이다. 남아 있던 샘플 플래그·옛 오류를 같이 걷지 않으면
    // 복원해 놓고 「샘플이에요」나 지난 오류 배너가 뜬다
    useSample: false, pipelineError: null, pipelineDetail: '',
  });
  return snap.at || 0;
}

/** 저장본이 있나 — 없으면 #/report/last 가 빈 화면을 열지 않게 미리 본다 */
function hasLastReport() {
  try { return !!JSON.parse(localStorage.getItem(LAST_REPORT_KEY) || 'null'); }
  catch (_) { return false; }
}

/**
 * 판정 헤드에 필요한 값만 모은다.
 *
 * 점수·차원·한 줄 판단은 원래 rSummary() 안에 있었는데, 판정은 탭이 바뀌어도
 * 유지돼야 하는 세션의 결론이라 헤드로 끌어올렸다. 계산 자체는 기존
 * realSummary()·realTrophy() 를 그대로 쓰고 여기서는 조합만 한다.
 */
/** 최종 점수는 학점형 등급으로 보여준다. 세부 축(dimsHtml)은 «어디를 고칠지»
 *  알려줘야 하니 100점 숫자를 남기고, 헤드의 한 점수는 «잘했다/못했다» 만
 *  한눈에 주면 된다 — 등급이 그 요약에 더 맞는다. */
function scoreGrade(score) {
  const n = Number(score) || 0;
  if (n >= 90) return 'A+';
  if (n >= 80) return 'A';
  if (n >= 70) return 'B+';
  if (n >= 60) return 'B';
  if (n >= 50) return 'C+';
  if (n >= 40) return 'C';
  return 'D';
}

/** 시간 관리가 왜 낮은지 한 줄. 「정한 시간 안에 들어왔나요」는 이 지표가 «무엇을»
 *  보는지 설명이지 «왜 이번에» 낮았는지는 말해 주지 않는다. 시간 분배 카드
 *  (timeSplitCard)와 같은 비교식으로 계획 대비 가장 벗어난 구간을 짚는다.
 *  구간 데이터가 없으면 빈 문자열을 내서 DIM_HINT 의 일반 설명으로 떨어진다. */
function timeManagementReason() {
  const pace = (reportOut() || {}).pace;
  const secs = (pace && pace.sections) || [];
  const rows = secs.length
    ? secs.map(s => ({ name: s.name, rec: s.recommended_sec || 0, act: s.actual_sec || 0 }))
    : (DATA.timeAlloc || []).map(r => ({ name: r[0], rec: r[1] || 0, act: r[2] || 0 }));
  const devs = rows
    .filter(r => r.rec > 0)
    .map(r => ({ name: r.name, pct: Math.round((r.act - r.rec) / r.rec * 100) }))
    .filter(d => Math.abs(d.pct) >= 20)
    .sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct));
  if (!devs.length) return '';
  const over = devs.find(d => d.pct > 0);
  const under = devs.find(d => d.pct < 0 && (!over || d.name !== over.name));
  if (over && under) {
    return `${over.name}에 계획보다 시간을 ${over.pct}% 더 쓰고, ${under.name}은 ${Math.abs(under.pct)}% 모자랐어요.`;
  }
  const only = devs[0];
  return only.pct > 0
    ? `${only.name}에 계획보다 시간을 ${only.pct}% 더 썼어요.`
    : `${only.name}이 계획보다 ${Math.abs(only.pct)}% 모자랐어요.`;
}

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
      /* '전달됐어요' 를 '전달했어요' 로 바꾼 이유: 발표를 한 사람은 사용자다.
         피동으로 쓰면 잘한 게 누구 덕인지 흐려진다 (토스 능동적 말하기) */
      headline: real.score >= 90 ? '아주 잘 전달했어요'
        : real.score >= 75 ? '핵심은 잘 전달했어요'
          : real.score >= 60 ? '핵심은 전했고, 다듬을 곳이 보여요'
            : '다음 발표에서 더 좋아질 수 있어요',
      subnotes: real.notes,
      excludedCount: real.excludedCount,
      unmeasuredCount: real.unmeasuredCount,
      /* 어느 기준으로 매겼는지 숨기지 않는다. 폴백이면 폴백이라고 쓴다.
         다만 자리가 바뀌었다 — 점수 바로 아래(.prev)가 아니라 기둥 맨 아래
         접힌 줄이다. 근거는 점수를 읽은 다음에 궁금해지는 것이지, 점수보다
         먼저 읽어야 하는 게 아니다 (verdictBasisHtml). */
      /* 「채점표 v3 · 학교 프로젝트 (교수 대상)」이었다. 버전 번호는 사용자의 말이
         아니고, 상황 이름은 고를 때 쓴 말과 달랐다. 고른 말을 그대로 따옴표로
         묶어 되돌려준다 — 내가 고른 그것으로 봤다는 게 한 줄로 읽힌다.
         폴백은 여전히 폴백이라고 쓴다 (숨기지 않는다). */
      basis: `‘${occLabel(real.situationLabel) || '기본 기준'}’에 맞춰 봤어요${
        real.isFallback ? ' · 예전 방식' : ''}`,
      delta: '',
    };
  }
  const diff = s.score - s.prevScore;
  /* 채점표가 있으면 클러스터 키를 붙여 막대 → 채점 근거로 이어지게 한다. */
  const sc = DATA.score;
  const dims = (sc && Array.isArray(sc.clusters) && sc.clusters.length)
    ? sc.clusters.filter((c) => c.status === 'scored').map((c) => [
      c.name, Math.round(c.average || 0), SCORE_CHICK[c.key] || '', c.weight || 0, c.key,
    ])
    : s.dims;
  return {
    hasAnalysis: true, isSample: true,
    mood: s.score >= 90 ? 'excited' : s.score >= 75 ? 'happy' : 'neutral',
    score: s.score,
    dims,
    headline: s.oneLiner,
    basis: sc ? `‘${occLabel(sc.situation_label) || '기본 기준'}’에 맞춰 봤어요` : '',
    excludedCount: sc && Array.isArray(sc.excluded) ? sc.excluded.length : 0,
    unmeasuredCount: sc && Array.isArray(sc.unmeasured) ? sc.unmeasured.length : 0,
    delta: `<span class="delta num">▲ ${diff}</span><span class="prev num">지난 연습 ${s.prevScore}점</span>`,
  };
}

/* 판정 헤드 뒤에 발화 파형 150개를 깔던 paintVerdictBg() 가 여기 있었다.
   「장식이 아니라 데이터가 배경」이라는 뜻으로 넣었지만, 읽을 수 없는 파형은
   데이터가 아니라 텍스처다. 토스 그래픽 가이드 6번이 그대로 짚는다 —
   「의미 없는 묘사, 파티클, 과한 그라데이션 같은 요소는 화면을 복잡하게 만들고
   정보 전달을 방해해요」. 기둥은 조용한 초록 면 한 장이면 된다. */

async function renderReport() {
  await ensureVoicePipelineOut();
  /* id 없는 #/report 는 실측이다 — 질문 코칭 끝의 「상세 리포트 보기」를 비롯해
     진입점 여덟 곳이 이 형태를 쓴다. 예전엔 기본값이 'imu2clip' 이라 샘플
     행과 실측이 같은 주소를 나눠 쓰고 있었다: 자료를 한 번이라도 올리면
     라벨은 샘플인데 열면 내 발표 리포트가 떴다 */
  let reportId = location.hash.replace(/^#\/?/, '').split('/')[1] || '';
  /* 시연 모드에서는 빈 #/report 도 쇼케이스 더미로 보낸다 — 올린 PPT 와
     무관하게 같은 결과 화면이 떠야 발표 플로우가 안 깨진다. */
  if (!reportId && isShowcaseDemo()) {
    location.replace(showcaseReportHref());
    return;
  }
  rSampleMode = reportId === 'sample-investor';
  /* 시연·샘플 리포트는 슬라이드 이미지가 비어 있다. 로컬 preview PDF 를 먼저 붙여
     「슬라이드로 보는 발표」가 번호 자리표시자만 보이지 않게 한다. */
  if (rSampleMode || isShowcaseDemo()) await ensureShowcasePreviewPdf();
  /* #/report/last — 저장해 둔 마지막 분석으로 연다 (개발용, 링크 없음).
     복원은 그리기 **전에** 끝나야 한다. reportSessionMeta·reportVerdict 가
     이미 nf 를 읽은 뒤면 옛 화면이 한 번 깜빡이고 덮인다. */
  const restoredAt = reportId === 'last' ? restoreLastReport() : 0;
  if (reportId === 'last' && !restoredAt) {
    app.className = 'narrow';
    app.innerHTML = `
      <div class="card empty-card">
        ${emptyBirdHtml('solar', 'neutral')}
        <h2 class="section-title">저장해 둔 리포트가 없어요</h2>
        <p class="note" style="margin:8px 0 14px">
          발표 분석을 한 번 끝내면 그 결과가 여기 남아요. 그 뒤로는 이 주소로 바로 열 수 있어요.
        </p>
        <div class="step-actions">
          <a class="btn btn-primary" href="#/new">발표 연습 시작하기</a>
          <a class="btn btn-text" href="#/report/sample-investor">${isShowcaseDemo() ? '리포트 보기' : '샘플 리포트 보기'}</a>
        </div>
      </div>`;
    return;
  }
  if (reportId && !rSampleMode && reportId !== 'last' && DATA.reportProfiles[reportId]) {
    renderProfileReport(DATA.reportProfiles[reportId]);
    return;
  }
  app.className = 'wide';
  // 객석 수다는 70초쯤 걸린다. 여기서부터 받아 두면 요약·판정을 보는 동안 채워진다
  prefetchChatter();
  const s = reportSessionMeta();
  const v = reportVerdict();
  /* 녹음이 자료와 아예 다른 내용이라는 판정(f04)이 있으면 리포트 맨 위에서
     말한다. 검증 로그에만 두면 점수·정합을 다 읽고 나서야 원인을 알게 된다 —
     아래 판정 전체가 균등 분할 위에 서 있다는 사실이 숫자보다 먼저다. */
  const outForNote = reportOut();
  const unrelatedNote = (!rSampleMode && outForNote && outForNote.transcript
    && outForNote.transcript.marks_match === 'unrelated')
    ? (outForNote.transcript.marks_reason
      || '녹음이 이 발표 자료와 아예 다른 내용으로 보여요.')
    : '';
  /* 저장은 여기 한 곳에서만 한다. 파이프라인 안쪽(완료 콜백이 여러 갈래다)이
     아니라 「리포트가 실제로 그려진 순간」이 데이터가 온전하다는 유일한 증거다.
     저장본을 다시 열었을 때(restoredAt) 또 저장하면 시각만 계속 갱신돼서
     "언제 한 발표인지" 가 거짓말이 된다 — 그때는 저장하지 않는다. */
  if (!rSampleMode && !restoredAt && s.live && v.hasAnalysis && !v.isSample) saveLastReport();
  /* 순서가 곧 우선순위다. 예전 2번은 「채점표」였다 — 39개 항목의 점수표는
     어느 발표 도구에나 있는 것이고, 우리만 하는 일이 아니다. 우리만 하는 일은
     «자료가 약속한 개념을 실제로 설명했는가» 를 발화 증거와 함께 대조하는
     것이라, 그게 요약 바로 다음에 와야 한다. 채점 근거는 그 판단이 미덥지
     않을 때 열어 보는 자리라 뒤로 보낸다.
     이름도 산출물이 아니라 «무엇을 답해 주는 화면인가» 로 바꿨다. */
  const tabs = ['요약', '말하기', '개념 전달', '흐름', '채점 근거', '연습 도구', '발표 구성'];
  const meta = [
    escapeHtml(s.occasion),
    s.slides ? `슬라이드 ${s.slides}개` : '',
    escapeHtml(s.duration),
    s.live ? '' : `${s.nth}번째 연습`,
  ].filter(Boolean);
  app.innerHTML = `
    <section class="verdict${v.hasAnalysis ? '' : ' is-plain'}">
      <div class="verdict-inner">
        <p class="verdict-meta">${meta.map(m => `<span>${m}</span>`).join('<i></i>')}</p>
        <h1 class="verdict-title">${escapeHtml(s.title)}</h1>
        ${v.hasAnalysis ? `
        <div class="verdict-grid">
          <div class="verdict-score">
            <span class="vs-label">발표 완성도</span>
            <div class="vs-body">
              <div class="vs-num">
                <strong class="num grade">${scoreGrade(v.score)}</strong>
                ${scoreBirdHtml(v.mood)}
              </div>
            </div>
          </div>
          <div class="verdict-judgement">
            <h2>${escapeHtml(v.headline)}</h2>
            <div class="verdict-dims">
              ${dimsHtml(v.dims)}
            </div>
          </div>
        </div>
        ${verdictBasisHtml(v)}` : ''}
      </div>
      ${unrelatedNote
        ? `<p class="verdict-note" style="color:var(--no)"><b>${escapeHtml(unrelatedNote)}</b> 아래 정합·개념 판정은 참고만 해 주세요.</p>`
        : ''}
      ${v.isSample && !isShowcaseDemo()
        ? `<p class="verdict-note">아래는 <b>샘플 데이터</b>예요. 리허설을 마치고 자료와 발화를 맞춰 보면 내 결과로 바뀌어요.</p>`
        : (!v.isSample && restoredAt
          ? `<p class="verdict-note"><b>저장해 둔 리포트</b>예요 · ${escapeHtml(stampText(restoredAt))}에 분석했어요. 방금 한 발표가 아니에요.</p>`
          : '')}
    </section>
    <div class="tabs" id="rtabs">
      ${tabs.map((t, i) => `<button class="${i === rTab ? 'on' : ''}">${t}</button>`).join('')}
    </div>
    <div id="rbody"></div>`;
  // 막대는 0 에서 차오른다. 숫자를 바꾸지 않고 읽는 순서만 만드는 연출이라
  // 데이터를 가리지 않는다 (§14 — 연출이 데이터를 가리면 연출을 버린다).
  requestAnimationFrame(() => {
    $$('.verdict-dims .bar i[data-w]').forEach(i => { i.style.width = i.dataset.w; });
  });
  // 기둥의 항목 줄 → 그 항목의 채점 근거
  $$('.vd-rest .vd[data-cluster]').forEach(b =>
    b.addEventListener('click', () => goRubric(b.dataset.cluster)));
  $('#rtabs').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    switchReportTab($$('#rtabs button').indexOf(b));
  });
  R_TAB_VIEWS[rTab]();
  animateViz($('#rbody'));
}

function renderProfileReport(p) {
  app.className = 'wide';
  app.innerHTML = `
    <div class="report-head history-head">
      <a class="back-link" href="#/">← 내 발표</a>
      <span class="final-label">발표 + 질문 코칭 최종 분석</span>
      <h1 class="page-title">${p.title}</h1>
      <p class="report-meta">${p.occasion} · 슬라이드 ${p.slides}개 · ${p.duration} · ${p.nth}번째 연습</p>
      ${isShowcaseDemo() ? '' : '<p class="sample-note">이 발표는 <b>샘플 데이터</b>예요. 화면 구성을 미리 볼 수 있게 넣어 뒀어요.</p>'}
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
/* 탭 순서의 단일 원본. renderReport 의 tabs 라벨 배열과 순서가 같아야 한다. */
const R_TAB_VIEWS = [rSummary, rDelivery, rJudge, rLogic, rRubric, rTools, rStrategy];

/**
 * 탭 전환은 본문(#rbody)만 다시 그린다.
 *
 * 예전엔 renderReport() 전체를 다시 불러서, 탭이 바뀔 때마다 판정 헤드
 * (발표 완성도 점수·차원 막대)까지 통째로 재렌더·재애니메이션됐다 — 헤드는
 * 탭이 바뀌어도 유지되는 세션의 결론이라 다시 그릴 이유가 없다.
 * renderReport 가 async(파이프라인 확인)라 goRubric·goJudge 가 렌더 직후
 * DOM 을 짚는 것도 사실은 경주였다 — 이 함수는 동기라 그 경주도 없앤다.
 * 리포트 껍데기가 아직 없으면(다른 화면에서 진입) 전체 렌더로 돌아간다.
 */
function switchReportTab(i) {
  const btns = $$('#rtabs button');
  if (!btns.length || !$('#rbody')) { rTab = i; renderReport(); return; }
  rTab = i;
  btns.forEach((b, k) => b.classList.toggle('on', k === i));
  R_TAB_VIEWS[i]();
  animateViz($('#rbody'));
}

/**
 * 기둥의 항목 줄 → 채점표 탭의 그 클러스터.
 *
 * 「목적·청중 적합성 30」만 보여주고 끝나면 「그래서 왜 30점인데」에 답할 데가
 * 없다. 채점표 탭이 항목별 근거를 이미 갖고 있으므로 그리로 데려간다.
 * rTab 4 는 R_TAB_VIEWS 의 [rSummary, rDelivery, rJudge, rLogic, rRubric, …] 순서다.
 */
function goRubric(key) {
  switchReportTab(4);
  // 탭만 바꾸면 7개 묶음 중 어디를 보라는 건지 알 수 없다.
  // 묶음은 접혀 있으므로 열어 준다 — 눌러서 왔는데 접힌 줄만 보이면 헛걸음이다
  const block = key && $(`#rb-${CSS.escape(key)}`);
  if (!block) return;
  block.open = true;
  block.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function goJudge(node) {
  // rTab 은 R_TAB_VIEWS 의 [rSummary, rJudge, …][rTab] 순서다.
  // 탭을 재배치할 때마다 여기가 어긋났다(예전엔 개념을 눌렀는데 채점표가 열렸다).
  // 개념 전달은 이제 2번이다.
  jSel = node; switchReportTab(2);
  // 탭만 바꾸면 긴 목록에서 선택한 개념이 화면 밖에 있을 수 있다
  const picked = $('#jtree .sel') || $(`#jtree [data-node="${node}"]`);
  if (picked) picked.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

/* 탭 1 — 요약 */

/** 덱 필름에 그릴 슬라이드 목록. 상태는 실판정이 있으면 그걸, 없으면 샘플을 쓴다. */
/* 한 장에 여러 개념이 걸리면 가장 나쁜 판정을 그 장의 색으로 쓴다.
   필름 스트립·무대·개념 판정이 같은 장을 다른 색으로 칠하면 리포트가 거짓말이 된다 —
   그래서 세 곳이 이 한 함수만 본다. */
const JUDGE_RANK = { ct: 0, no: 1, mid: 2, om: 3, ok: 4 };

/** 그 장에 걸린 실제 개념 판정 — 나쁜 순 · 무거운 순. 실데이터가 없으면 null. */
function slideJudgeNodes(no, tree = judgeTree()) {
  if (!(tree[0] && tree[0].real)) return null;
  return tree
    .filter(n => slideNumber(n.slide) === no)
    .sort((a, b) => (JUDGE_RANK[a.status] - JUDGE_RANK[b.status]) || ((b.w || 0) - (a.w || 0)));
}

/** 리포트가 그릴 장 수 — 올린 자료가 있으면 그 자료 기준이다. */
function deckTotalSlides() {
  return (nfSlideDoc && nfSlideDoc.total_slides)
    || (uploadedPdf && uploadedPdf.pageCount)
    || ((nf && nf.slideTitles && nf.slideTitles.length) || 0)
    || DATA.slideStatus.length;
}

/** 장 제목. 업로드 세션에서는 샘플(IMU2CLIP) 제목으로 떨어지지 않는다. */
function deckTitle(no, live = isLiveReportSession()) {
  const own = (nf && nf.slideTitles) || [];
  return own[no - 1] || (live ? '' : DATA.slideTitles[no - 1]) || `${no}번 슬라이드`;
}

/** 장 이미지. PDF 렌더가 붙기 전/불가능할 때도 남의 자료를 보여주지 않는다 (CLAUDE.md §2). */
function deckImageSrc(no, live = isLiveReportSession()) {
  const own = (nf && nf.slideImages) || [];
  if (live) return own[no - 1] || slidePlaceholder(no);
  return DATA.slideImages[no - 1] || slidePlaceholder(no);
}

/**
 * 이 장의 **진짜** 그림을 띄울 수 있는가.
 *
 * 힌트에 슬라이드를 같이 보여줄 때만 쓴다. 자리표시자(회색 판에 숫자만)를 띄우면
 * "27장을 떠올려 보세요" 라는 원래 문제를 빈 사각형으로 다시 내는 꼴이라,
 * 진짜 렌더가 없으면 아예 안 붙이고 글자 힌트로 남긴다.
 *
 * 두 갈래로 진짜가 된다 — 업로드 PDF 가 메모리에 있으면 paintDeckThumbs 가 곧
 * 채워 주고(PPTX 는 브라우저 렌더가 없어 여기서 걸러진다), 샘플 세션이면
 * assets 의 webp 가 이미 진짜다. 자리표시자는 svg data URL 이라 그것으로 가른다.
 */
function hasRealSlideImage(no) {
  if (!no || no < 1) return false;
  if (uploadedPdf && uploadedPdf.pdf) return no <= (uploadedPdf.pageCount || 0);
  return !String(deckImageSrc(no) || '').startsWith('data:image/svg+xml');
}

function deckThumbList() {
  const tree = judgeTree();
  const isReal = !!(tree[0] && tree[0].real);
  const live = isLiveReportSession();
  const total = deckTotalSlides();
  return Array.from({ length: total }, (_, i) => {
    const no = i + 1;
    const nodes = isReal ? slideJudgeNodes(no, tree) : null;
    return {
      no,
      status: isReal ? ((nodes[0] && nodes[0].status) || 'om') : (DATA.slideStatus[i] || 'om'),
      title: deckTitle(no, live),
      // 업로드 PDF 가 있으면 렌더가 채운다.
      src: (uploadedPdf && uploadedPdf.pdf) ? '' : deckImageSrc(no, live),
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

/**
 * 무대·판정 화면의 큰 슬라이드를 원본 PDF 렌더로 채운다.
 * 썸네일(240px)을 늘리면 부스 화면에서 뭉개지므로 여기만 별도로 크게 그린다.
 */
async function paintDeckStage(root = document) {
  const canvas = root.querySelector('canvas[data-stage-page]');
  if (!canvas || !uploadedPdf || !uploadedPdf.pdf) return;
  const page = Number(canvas.dataset.stagePage) || 1;
  try {
    await renderPdfToCanvas(page, canvas, { maxWidth: (canvas.parentElement && canvas.parentElement.clientWidth) || 960 });
  } catch (err) {
    console.warn('[chuckchuck] deck stage', page, err);
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
/** 시연·샘플 리포트용 트로피. QA 더미의 before/after 문장을 쓴다. */
function sampleTrophy() {
  const tr = DATA.session && DATA.session.qa && DATA.session.qa.trophy;
  if (!tr || !tr.after) return null;
  return {
    text: tr.after,
    slide: tr.slide || 11,
    verdict: 'missing',
    label: tr.node || '',
  };
}

function realTrophy() {
  const out = reportOut();
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
  const sc = reportScore();
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
  /* 펼쳐 둘 묶음 하나 — 기둥의 「여기부터 보세요」와 같은 기준으로 고른다.
     둘이 다른 묶음을 가리키면 같은 리포트가 두 곳에서 다른 말을 하는 셈이다. */
  const weakest = clusters.filter(c => c.status === 'scored')
    .sort((a, b) => (a.average - b.average) || ((b.weight || 0) - (a.weight || 0)))[0];
  const weakestKey = weakest ? weakest.key : '';

  /* 못 잰 항목은 줄로 그리지 않는다.
     예전엔 한 항목이 같은 말을 두 번 했다 — 오른쪽에 「이번엔 못 쟀어요」(플래그),
     아래에 「채점을 마치지 못해서 이번엔 못 쟀어요」(근거). 시각자료 활용처럼
     못 잰 게 4개면 그 반복이 묶음의 절반을 먹는다. 점수도 근거도 없는 줄은
     읽을 것이 없다.

     대신 개수는 남긴다 — 묶음 머리의 「6/10개 항목」과 묶음 끝의 한 줄이
     그 일을 한다. 못 잰 걸 안 보이게 치우면 리포트가 거짓말이 된다 (§4).
     지우는 건 «반복» 이지 «사실» 이 아니다. */
  const rowHtml = (it) => {
    const why = it.evidence || it.note || '';
    return `<li class="rb-item is-${it.status}">
      <div class="rb-line"><span class="rb-no num">${it.no}</span>
        <span class="rb-name">${escapeHtml(it.name)}</span>
        ${it.source && RUBRIC_SOURCE[it.source] ? `<span class="rb-src">${RUBRIC_SOURCE[it.source]}</span>` : ''}
        <b class="num">${Math.round(it.score)}</b></div>
      ${why ? `<p class="rb-why">${escapeHtml(why)}</p>` : ''}
    </li>`;
  };

  const blocks = clusters.map((c) => {
    const rows = (byCluster[c.key] || []);
    if (!rows.length) return '';
    const head = c.status === 'scored'
      ? `<b class="num">${Math.round(c.average || 0)}</b>`
      : `<span class="rb-flag" style="color:var(--ct)">이번엔 못 쟀어요</span>`;
    /* 예전엔 7묶음 39항목이 전부 펼쳐져 있었다. 근거를 남긴다는 뜻은 좋았지만,
       열자마자 39개 항목과 39줄의 근거가 한꺼번에 쏟아져서 「내 점수가 왜
       42인가」를 찾을 수가 없었다.

       묶음을 접는다. 접힌 줄이 곧 결론이다 — 이름 · 점수 · 항목 수. 궁금한
       묶음만 펼치면 근거가 나온다. 제일 낮은 묶음 하나는 펼쳐 둔다: 이 화면에
       들어온 사람이 제일 먼저 볼 곳이고, 전부 접혀 있으면 「아무것도 없는 화면」
       처럼 보인다. 기둥에서 줄을 눌러 들어온 경우엔 goRubric 이 그 묶음을 연다. */
    const done = rows.filter(r => r.status === 'scored');
    const scored = done.length;
    /* 「안 봄」과 「못 쟀음」은 다른 사실이다 (§4, RUBRIC_STATUS). 예전엔 둘을
       rows.length - scored 하나로 뭉쳐서 안 본 항목까지 "채점을 마치지 못해
       못 쟀어요"라고 거짓말했다 — 논리 구조의 두괄식 구조(상황상 안 봄)가
       실제 사례다. 줄로는 안 그리되(위 주석) 상태별로 세어 맞는 말을 낸다. */
    const excluded = rows.filter(r => r.status === 'situation_excluded');
    const unmeasured = rows.filter(r => r.status === 'unmeasured');
    return `<details class="rb-cluster" id="rb-${escapeHtml(c.key)}"${c.key === weakestKey ? ' open' : ''}>
      <summary>
        <span class="rb-cname">${escapeHtml(c.name)}</span>
        <span class="rb-cmeta">${scored}개 항목</span>
        ${head}
      </summary>
      <ol class="rb-list">${done.map(rowHtml).join('')}</ol>
      ${excluded.length ? `<p class="rb-unmeasured">${excluded.length}개 항목은 ${RUBRIC_STATUS.situation_excluded.t}</p>` : ''}
      ${unmeasured.length ? `<p class="rb-unmeasured">${unmeasured.length}개 항목은 채점을 마치지 못해 ${RUBRIC_STATUS.unmeasured.t}</p>` : ''}
    </details>`;
  }).join('');

  $('#rbody').innerHTML = `
    <div class="card">
      <h3 class="section-title">채점표</h3>
      <p class="note" style="margin-bottom:14px">
        ‘${escapeHtml(occLabel(sc.situation_label) || '기본 기준')}’ 기준으로 ${nScored}개 항목을
        채점했어요. 항목마다 왜 그 점수인지 근거를 남겨요.
      </p>
      ${blocks}
    </div>`;
}

function realSummary() {
  /* 샘플 리포트는 reportVerdict 가 oneLiner 를 쓰도록 여기선 막는다.
     채점 근거 탭은 reportScore() 로 직접 연다. */
  if (rSampleMode) return null;
  const sc = reportScore();
  if (!sc || typeof sc.score !== 'number') return null;
  /* 4번째 칸은 채점표의 클러스터 가중치(%)다. 「여기부터 보세요」가 동점을 만났을 때
     배열 순서 대신 이걸로 고른다 (dimsHtml 주석). 화면에는 나오지 않는다 */
  const dims = (sc.clusters || [])
    .filter(c => c.status === 'scored')
    .map(c => [c.name, Math.round(c.average || 0), SCORE_CHICK[c.key] || '', c.weight || 0, c.key]);
  const notes = [];
  // 두 안내를 합치지 않는다 — '이 상황에서 안 봄'과 '이번에 못 잼'은 다른 말이다.
  // 문구는 부드럽게 바꾸되 개수는 그대로 — 못 잰 걸 숨기면 리포트가 거짓말이 된다
  if ((sc.excluded || []).length) {
    notes.push(`이 자리에서 안 보는 항목 ${sc.excluded.length}개는 빼고 봤어요`);
  }
  if ((sc.unmeasured || []).length) {
    notes.push(
      `${sc.unmeasured.length}개 항목은 이번엔 재지 못했어요. `
      + '다음 연습에선 더 많이 알려드릴게요.'
    );
  }
  if (sc.note) notes.push(sc.note);
  return {
    score: sc.score, dims, notes, basis: sc.basis,
    // 접힌 줄에 개수를 남기려고 따로 센다 — 안내를 접어도 「못 잰 게 있다」는
    // 사실은 접히면 안 된다 (CLAUDE.md §4 정직성)
    excludedCount: (sc.excluded || []).length,
    unmeasuredCount: (sc.unmeasured || []).length,
    situationLabel: sc.situation_label || '',
    isFallback: String(sc.rubric_version || '').endsWith('-fallback'),
    // 점수는 판결이 아니라 박수다 — 낮아도 응원(neutral)이지 우는 표정은 없다
    mood: sc.score >= 90 ? 'excited' : sc.score >= 75 ? 'happy' : 'neutral',
  };
}

/** 지표가 무엇을 보는 것인지 한 줄. 이름만으로는 안 읽힌다 —
 *  "목적·청중 적합성 68" 을 보고 뭘 고쳐야 할지 아는 사람은 없다. */
const DIM_HINT = {
  '내용 충실도': '다뤄야 할 개념을 빠짐없이 설명했나요',
  '논리 구조': '앞뒤가 이어지게 말했나요',
  '목적·청중 적합성': '이 자리, 이 청중에 맞는 말이었나요',
  '언어적 명료성': '한 번에 알아듣게 말했나요',
  '음성적 전달': '속도·쉼·말버릇이 편하게 들렸나요',
  '시각자료 활용': '슬라이드를 말로 살렸나요',
  '시간 관리': '정한 시간 안에 들어왔나요',
};

/** 그 축에서 제일 낮은 항목의 근거 한 줄. DIM_HINT 는 «무엇을» 보는지고 «왜 이번에»
 *  낮았는지는 말해주지 않는다 (timeManagementReason 의 같은 문제, 여기선 전체 축으로
 *  일반화한다). 근거가 없으면 빈 문자열을 내서 DIM_HINT 의 질문으로 떨어진다. */
function clusterReason(key) {
  if (!key) return '';
  const items = ((reportScore() || {}).items) || [];
  const worst = items
    .filter(it => it.cluster === key && it.status === 'scored' && (it.evidence || it.note))
    .sort((a, b) => (a.score || 0) - (b.score || 0))[0];
  return worst ? (worst.evidence || worst.note) : '';
}

/**
 * 채점표 클러스터를 그린다.
 *
 * 예전엔 7개를 같은 크기로 늘어놨다. 다 똑같이 생겨서 어디부터 봐야 할지 알 수
 * 없고, 이름만 있고 뜻이 없어서 숫자가 무슨 뜻인지도 안 읽혔다 (2026-08-07 지적).
 *
 * 오늘 고칠 것은 하나다. 제일 낮은 축을 앞으로 빼서 크게 두고, 나머지는 그대로
 * 둔다. 낮은 축이 여럿이면 첫 번째만 표시한다 — 둘을 강조하면 강조가 아니다.
 *
 * 2026-08-08 — 기둥이 안 읽힌다는 지적. 원인은 7개가 전부 「이름 + 큰 숫자 + 막대
 * + 설명 한 줄」로 똑같이 서 있던 것이다. 설명 일곱 줄이 기둥 높이의 절반을
 * 먹으면서, 정작 결론(점수 · 한 줄 판정)이 스크롤 위로 밀려났다.
 *
 * 주인공은 하나다 (토스). 제일 낮은 축만 설명을 달고 카드로 서고, 나머지 여섯은
 * 두 칸짜리 조용한 목록으로 내린다 — 지우는 게 아니라 크기를 뺀다. 설명은
 * title 로 남겨서 눌러보지 않아도 마우스로 확인할 수 있다.
 */
function dimsHtml(dims) {
  if (!dims || !dims.length) return '';
  /* 동점이면 예전엔 배열 순서(=클러스터 정의 순서)로 앞의 것이 이겼다. 학교
     프로젝트에서 논리 구조(23%)와 시간 관리(13%)가 나란히 0 이면 「여기부터
     보세요」가 사실상 아무거나 골라진다는 뜻이다. 같은 점수면 채점 비중이 큰
     쪽이 고칠 값어치도 크다 — 순서가 아니라 비중으로 고른다. */
  const weakIdx = dims.reduce((best, d, i) => {
    const [, score, , weight = 0] = d;
    const [, bestScore, , bestWeight = 0] = dims[best];
    if (score < bestScore) return i;
    if (score === bestScore && weight > bestWeight) return i;
    return best;
  }, 0);

  /* 주인공 한 칸 — 카드로 서고 설명 한 줄과 막대를 갖는다 */
  const weakCard = (d) => {
    const hint = (d[0] === '시간 관리' && timeManagementReason()) || clusterReason(d[4]) || DIM_HINT[d[0]] || '';
    return `
      <div class="vd vd-weak">
        <span class="vd-tag">여기부터 보세요</span>
        <span class="lb">${escapeHtml(d[0])}</span>
        <span class="vl num">${d[1]}<span class="of">/100</span></span>
        <div class="bar"><i style="width:0" data-w="${d[1]}%"></i></div>
        ${hint ? `<span class="hint">${escapeHtml(hint)}</span>` : ''}
      </div>`;
  };

  /* 나머지 여섯 — 「이름 · 값 · 다음」 한 줄씩. 막대는 뺐다: 여섯 개가 나란히
     차 있으면 어느 것도 눈에 안 들어오고, 어차피 옆의 숫자가 같은 말을 더
     정확하게 한다. 누르면 그 항목의 채점 근거(채점표 탭)로 간다 —
     값만 보여주고 끝나면 «그래서 왜 30점인데» 에 답할 데가 없다.
     클러스터 키가 없는 샘플 데이터는 누를 곳이 없으므로 div 로 낸다. */
  const restRow = (d) => {
    const key = d[4] || '';
    const hint = clusterReason(key) || DIM_HINT[d[0]] || '';
    const attrs = `class="vd"${hint ? ` title="${escapeHtml(hint)}"` : ''}`;
    const inner = `
        <span class="lb">${escapeHtml(d[0])}</span>
        <span class="vl num">${d[1]}<span class="of">/100</span></span>
        ${key ? '<span class="vd-go" aria-hidden="true">›</span>' : ''}`;
    return key
      ? `<button type="button" ${attrs} data-cluster="${escapeHtml(key)}">${inner}</button>`
      : `<div ${attrs}>${inner}</div>`;
  };

  const rest = dims.filter((_, i) => i !== weakIdx);
  return weakCard(dims[weakIdx])
    + (rest.length ? `<div class="vd-rest">${rest.map(restRow).join('')}</div>` : '');
}

/**
 * 채점 근거와 못 잰 항목.
 *
 * 이건 결론이 아니라 단서다. 「채점표 v3 · 학교 프로젝트(교수 대상)」와 안내 두
 * 줄이 42점 바로 옆·아래에 같은 무게로 서 있어서, 점수를 읽기 전에 먼저 읽혔다.
 * 접어 두되 **개수는 접힌 줄에 남긴다** — 못 잰 걸 안 보이게 치우면 리포트가
 * 거짓말이 된다 (CLAUDE.md §4). 오히려 지금까지 목록 안에 묻혀 있던 개수가
 * 접힌 줄로 올라오면서 늘 보이게 된다.
 */
function verdictBasisHtml(v) {
  if (!v.basis) return '';
  const notes = v.subnotes || [];
  if (!notes.length) {
    return `<p class="verdict-basis is-flat">${escapeHtml(v.basis)}</p>`;
  }
  const missed = [
    v.excludedCount ? `안 본 항목 ${v.excludedCount}개` : '',
    v.unmeasuredCount ? `못 잰 항목 ${v.unmeasuredCount}개` : '',
  ].filter(Boolean).join(' · ');
  return `
    <details class="verdict-basis">
      <summary>
        <span class="vb-basis">${escapeHtml(v.basis)}</span>
        ${missed ? `<span class="vb-count">${escapeHtml(missed)}</span>` : ''}
      </summary>
      <ul class="verdict-subnotes">${notes
        .map(n => `<li>${escapeHtml(n)}</li>`).join('')}</ul>
    </details>`;
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
  const out = reportOut();
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
  // 해시에 id 가 없으면 **가장 최근 기록**을 보여준다. 실전 코칭은 'flat' 키로
  // 저장되는데 예전 기본값만 읽어서, 방금 끝낸 코칭이
  // 리포트에 안 뜨거나 목 시나리오가 내 기록인 양 떴다.
  /* 'last'(저장 리포트)·'sample-investor'(샘플 리포트)은 QaHistory 의 키가
     아니라 리포트 주소다 — 그대로 get() 에 넣으면 항상 빈손이라, 저장 리포트를
     열면 방금 한 코칭 내역이 소리 없이 사라졌다. 저장 리포트는 가장 최근 기록,
     샘플은 목 시나리오 키('investor')로 조회한다. */
  const hashId = location.hash.replace(/^#\/?/, '').split('/')[1];
  const latestId = (window.QaHistory.list()[0] || {}).id;
  const reportId = hashId === 'last' ? latestId
    : hashId === 'sample-investor' ? 'investor'
      : (hashId || latestId || 'investor');
  const rec = reportId ? window.QaHistory.get(reportId) : null;
  if (!rec || !rec.beats || !rec.beats.length) return '';

  const when = new Date(rec.at);
  const stamp = `${when.getFullYear()}.${String(when.getMonth() + 1).padStart(2, '0')}.${String(when.getDate()).padStart(2, '0')}`;

  /* 코칭의 결론은 「몇 개를 주고받았나」가 아니라 「대화로 몇 개가 늘었나」다.
     before/after/total 은 기록에 이미 있는데 화면에는 개수와 날짜만 나가고 있었다 —
     제일 중요한 값이 저장만 되고 안 보이던 셈이다. 프로필 리포트의 final-insight 가
     같은 값을 이미 이렇게 말한다 */
  const hasGain = typeof rec.before === 'number' && typeof rec.after === 'number' && rec.total;
  const gained = hasGain ? rec.after - rec.before : 0;

  /* 리포트가 「정보의 바다」가 된 자리라 통째로 예고형 접기로 둔다.
     접힌 줄이 결론(대화로 몇 개 늘었나)과 다시 볼 곳 유무를 먼저 말해야
     열지 말지를 정할 수 있다 — judge-fold 와 같은 규율. */
  const weakCount = rec.beats.filter(b => b.verdict === 'none').length;
  return `
    <details class="fold qa-log-fold">
      <summary>
        <span>질문 코칭 내역</span>
        <span class="fold-meta">${weakCount ? '<i class="dot st-no"></i> ' : ''}${escapeHtml(rec.aud)}${josa(rec.aud, '과', '와')} 주고받은 ${rec.beats.length}개 질문${
          hasGain && gained > 0 ? ` · 대화로 <b class="num">${gained}</b>개 늘었어요` : ''} · ${stamp}</span>
      </summary>
      <div class="fold-body">
    <section class="qa-log">
      ${hasGain ? `
      <p class="qa-log-gain">
        <span class="qg-step"><i>질문 전</i><b class="num">${rec.before}</b></span>
        <em class="qg-arrow" aria-hidden="true">→</em>
        <span class="qg-step qg-after"><i>질문 후</i><b class="num">${rec.after}</b></span>
        <span class="qg-note">${rec.total}개 개념 중 설명할 수 있게 된 개수예요${
          gained > 0 ? ` · 대화로 <b>${gained}개</b> 늘었어요` : ''}</span>
      </p>` : ''}
      <div class="qa-log-list">
        ${rec.beats.map((b, i) => {
          const v = QA_VERDICT[b.verdict] || QA_VERDICT.partial;
          return `
          <details class="qa-log-item">
            <summary>
              <!-- 여기는 class="st ok" 였다. CSS 에 있는 건 .st-ok (하이픈)이라 어느
                   규칙에도 안 걸려서, 판정 셋이 전부 같은 회색 글씨로 떨어졌다 —
                   리포트에서 제일 먼저 읽어야 할 신호가 색을 잃고 있었다. 앱이 다른
                   데서 쓰는 chip 관용구를 그대로 쓴다 (판정 색 5종은 §3-3 불변) -->
              <span class="chip chip-sm st-${v.cls}">${v.label}</span>
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
    </section>
      </div>
    </details>`;
}

function rSummary() {
  const meta = reportSessionMeta();
  const live = meta.live;
  const s = DATA.session;
  const prio = DATA.priorities[s.occasion] || DATA.priorities['범용'] || Object.values(DATA.priorities)[0];
  const trophy = realTrophy() || (!isLiveReportSession() ? sampleTrophy() : null);
  const real = realSummary();
  const tree = judgeTree();
  const isRealTree = !!(tree[0] && tree[0].real);

  // 올린 자료인데 분석이 없으면 IMU2CLIP 샘플을 절대 보여주지 않는다
  if (live && !real && !isRealTree) {
    const why = (nf && nf.pipelineError)
      || ((reportOut() || {}).conceptsError)
      || (nf && nf.pipelineDetail)
      || '발표 분석 결과가 이 화면에 없어요. 분석이 끝난 뒤 다시 열어주세요.';
    $('#rbody').innerHTML = `
      <div class="card empty-card">
        ${emptyBirdHtml('solar', 'neutral')}
        <h2 class="section-title">아직 내 발표 분석이 없어요</h2>
        <p class="note" style="margin:8px 0 14px">${escapeHtml(String(why))}</p>
        <p class="note">제목은 <b>${escapeHtml(meta.title)}</b> 기준이에요. 분석이 끝나면 여기에 결과가 채워져요.</p>
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

  /* 접힌 줄이 「개념별 판정 전체 보기」 다섯 글자뿐이라, 열어 볼 값어치가 있는지
     알 수가 없었다. 몇 개가 들어 있고 그중 다시 볼 게 몇 개인지를 접힌 채로
     보여준다 — 여는 수고를 하기 전에 열지 말지를 정할 수 있어야 한다. */
  const judgeRows = isRealTree ? tree : (live ? [] : DATA.tree);
  const judgeRedo = judgeRows.filter(n => n.status === 'no' || n.status === 'ct').length;
  const judgeMeta = judgeRows.length
    ? `${judgeRows.length}개${judgeRedo ? ` · 다시 볼 곳 ${judgeRedo}개` : ''}`
    : '';
  const judgeFold = `
    <details class="fold judge-fold">
      <summary>
        <span>개념별 판정 전체 보기</span>
        ${judgeMeta ? `<span class="fold-meta num">${judgeRedo ? '<i class="dot st-no"></i> ' : ''}${judgeMeta}</span>` : ''}
      </summary>
      <div class="fold-body">
        ${judgeRows.map(n => `
        <div class="mini-row" data-node="${n.id}">
          <span class="dot st-${n.status}"></span>
          <span class="lbl" style="${n.depth === 2 ? 'padding-left:16px' : ''}">${escapeHtml(n.label)}</span>
          <span class="sl">${slideNumber(n.slide)}번 슬라이드</span>
          ${chip(n.status, true)}
        </div>`).join('') || '<p class="note">표시할 개념 판정이 없어요.</p>'}
      </div>
    </details>`;
  // 점수·차원·한 줄 판단은 판정 헤드(renderReport)로 올라갔다 — 여기서 다시 그리지 않는다
  /* 질문 코칭 내역이 맨 위에 있었다. 요약 탭의 주인공은 이번 발표 자체인데,
     열면 코칭 기록 다섯 줄(332px)을 지나야 내 발표가 나왔다 — 코칭은 발표
     뒤에 한 일이라 순서로도 뒤가 맞다. 슬라이드로 보는 발표를 위로 올린다. */
  /* 복습 한 마디는 맨 위에서 개념 판정·코칭 내역과 함께 「더 보고 싶으면」
     층으로 내렸다. 열자마자 말을 거는 목소리가 여덟이던 화면이라(정보의 바다),
     기본 노출은 결론 층(판정 헤드·오늘의 문장·슬라이드 덱·보완 1가지)만 남긴다. */
  const recall = recallCardHtml();
  $('#rbody').innerHTML = `
    ${trophy ? `<button class="card trophy-strip" id="trophyStrip" data-slide="${trophy.slide}">
      <span class="ts-label">${trophy.verdict === 'aligned' ? '이 흐름을 지키세요' : '다음엔 이렇게 말해보세요'}</span>
      <p class="ts-quote">“${escapeHtml(trophy.text)}”</p>
      <i class="ts-go">${trophy.slide}번 슬라이드에서 보기 →</i>
    </button>` : ''}

    <!-- 개념 지도는 여기 두지 않는다. 질문 생성을 기다리는 대기 화면으로 옮겼다
         (2026-08-10 지시) — 리포트에는 개념 전달 탭의 성좌가 이미 있어서 한
         화면에 같은 그림이 둘이었다. 무대를 세우는 코드는 js/graph3d.js 에
         그대로 있고 #/graph 와 대기 화면이 같이 쓴다. -->

    <div class="card rep-deck">
      <h3 class="section-title">슬라이드로 보는 발표<span class="soft">슬라이드를 누르거나 <kbd>←</kbd><kbd>→</kbd> 로 넘겨요</span></h3>
      <div id="deckBody">${deckHtml()}</div>
      <!-- 탭 이동은 한 번만 멈춘다(선택된 장만 tabindex=0). 23장짜리 자료에서
           칸마다 멈추면 필름을 지나가는 데만 탭을 23번 눌러야 한다 —
           들어와서 ←→ 로 넘기고 탭으로 빠져나가는 게 맞는 흐름이다 -->
      <div class="deck-film" id="deckFilm" role="group" aria-label="슬라이드 목록 (좌우 화살표로 넘겨요)">
        ${deckThumbList().map(t => `
          <button class="slidethumb st-${t.status} has ${t.no === repSlide ? 'on' : ''}" data-slide="${t.no}"
                  tabindex="${t.no === repSlide ? 0 : -1}" aria-current="${t.no === repSlide ? 'true' : 'false'}"
                  title="${t.no}. ${escapeHtml(t.title)} · ${STATUS[t.status]}">
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

    ${judgeFold}

    ${qaHistoryPanelHtml()}

    ${recall ? `<details class="fold recall-fold">
      <summary><span>복습 한 마디</span><span class="fold-meta">지난 회차 판정과 대조했어요</span></summary>
      <div class="fold-body">${recall}</div>
    </details>` : ''}

    ${(!live && prio && prio[0]) ? `
    <h2 class="section-title" style="margin:26px 0 12px">이것부터 고치면 돼요<span class="soft">효과가 가장 큰 한 가지</span></h2>
    ${prioCard(prio[0], 1)}
    <details class="fold">
      <summary>보완 2가지 더 보기</summary>
      <div class="fold-body">${prio.slice(1).map((p, i) => prioCard(p, i + 2)).join('')}</div>
    </details>` : ''}

    <!-- 「다음에 뭘 할지」를 말하는 덩어리가 셋이었다: 오늘 만든 문장(트로피),
         이것부터 고치면 돼요(우선순위), 그리고 여기. 셋이 각자 제목을 달고 서
         있으니 어느 게 결론인지 알 수 없었다 — 정신없다는 말이 나온 자리다.
         무엇을 고칠지는 기둥의 「여기부터 보세요」와 위의 두 덩어리가 이미
         말했다. 여기는 마침표만 찍는다: 한 줄 안내와 버튼 둘. -->
    <div class="card next-card">
      <p>${live
        ? '이 리포트는 방금 올린 자료와 발표 분석 결과예요. 질문 코칭을 건너뛰어도 같은 분석이 이어집니다.'
        : '같은 자료로 한 번 더 연습하면 무엇이 달라졌는지 나란히 볼 수 있어요.'}</p>
      <div class="step-actions">
        <a class="btn btn-primary" href="#/new">새 발표 연습</a>
        <a class="btn btn-tint" href="#/qa" style="background:#fff">질문 연습 다시 하기</a>
      </div>
    </div>`;
  /* 개념별 판정 묶음은 next-card 아래에 있었다. 「새 발표 연습」 버튼이 페이지의
     끝처럼 읽히는 자리라, 그 밑에 뭘 두든 안 열린다. 다루는 내용도 바로 위
     「슬라이드로 보는 발표」와 같은 것(이 발표의 개념들)이라 붙여 두는 게 맞다 —
     범례가 설명한 판정 5종의 전체 목록이 곧 이 묶음이다. CTA 는 맨 뒤로 보낸다. */
  const trophyEl = $('#trophyStrip');
  if (trophyEl) trophyEl.addEventListener('click', (e) => {
    selectDeckSlide(Number(e.currentTarget.dataset.slide) || (trophy && trophy.slide) || 1);
    const deck = $('.rep-deck'); if (deck) deck.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  const film = $('#deckFilm');
  if (film) {
    film.addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      selectDeckSlide(Number(b.dataset.slide));
    });
    /* 좌우로 넘기기. 33장짜리 자료를 마우스로 하나씩 집어 가는 건 일이다 —
       필름에 들어와서 ←→ 로 훑는 게 이 묶음을 보는 자연스러운 방법이다.
       Home·End 도 받는다(첫 장·마지막 장). 브라우저 기본 가로 스크롤을
       막아야 우리가 옮긴 자리와 스크롤이 따로 놀지 않는다. */
    film.addEventListener('keydown', e => {
      const total = deckTotalSlides();
      const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
      let next = step ? repSlide + step
        : e.key === 'Home' ? 1
          : e.key === 'End' ? total : null;
      if (next == null) return;
      next = Math.min(total, Math.max(1, next));
      e.preventDefault();
      if (next === repSlide) return;
      selectDeckSlide(next);
      const btn = $(`#deckFilm button[data-slide="${next}"]`);
      if (btn) btn.focus();
    });
  }
  $$('.mini-row').forEach(r => r.addEventListener('click', () => goJudge(r.dataset.node)));
  bindDeckPanel();
  paintDeckStage();
  paintDeckThumbs();
  wireSendoff();
  if (real) showCurtainCallApplause(real.score, real.dims).then(() => animateViz($('#rbody')));
}


/**
 * 분석이 끝나면 질문 코칭으로 알아서 넘어간다 (2026-08-10 지시).
 *
 * 다 끝난 뒤의 4단계 화면은 사실상 통과 지점이다 — 진행 막대 100%, 타임라인,
 * 체크리스트 전부 ✓ 는 이미 끝난 일의 기록이고, 남는 일은 「질문 코칭
 * 시작하기」를 누르는 것뿐이다. 그 한 번을 사람이 눌러야 할 이유가 없다.
 *
 * 지키는 것 넷.
 * - **실패했으면 안 넘긴다.** 호출부에서 걸러진다. 실패를 스쳐 지나가게 하면
 *   「분석이 됐는데 질문이 이상하다」로 읽힌다 (CLAUDE.md §4).
 * - **리빌이 떠 있으면 기다린다.** 지금 넘기면 route() 가 dismissF11Reveal() 을
 *   불러 30초짜리 분석 연출이 중간에 잘린다. 닫힐 때까지 지켜보다 넘어간다.
 * - **4단계를 보고 있을 때만 넘긴다.** 사용자가 리포트나 다른 데로 옮겨 갔으면
 *   화면을 빼앗지 않는다.
 * - **한 실행에 한 번만.** 재렌더마다 부르지 않게 pipelineStartedAt 으로 잠근다.
 *
 * 검증 로그와 「다른 녹음으로 다시」는 이 화면에만 있는데, #/new 로 돌아오면
 * 그대로 있다 (nf.step 이 4단계로 남는다).
 */
function autoAdvanceToQa() {
  if (!nf || nf._autoAdvancedFor === nf.pipelineStartedAt) return;
  if (!pipelineQaReady()) return;
  nf._autoAdvancedFor = nf.pipelineStartedAt;
  const go = () => {
    // 리빌이 닫힐 때까지 기다린다 — 연출이 끝나야 다음 화면이 의미가 있다
    if (document.getElementById('f11RevealWrap')) return setTimeout(go, 600);
    // 그 사이 다른 화면으로 갔으면 손대지 않는다
    if (!location.hash.startsWith('#/new')) return;
    location.hash = '#/qa';
  };
  // 「끝났어요」를 한 박자 보여주고 넘어간다. 즉시 바꾸면 무슨 일이 일어난 건지
  // 모른 채 화면만 갈린다. 시연은 연출을 더 오래 보여 준다.
  setTimeout(go, isShowcaseDemo() ? 2800 : 1200);
}

/** 파이프라인이 더 돌지 않는 상태인가. 문구와 색이 같은 답을 봐야 해서 한 곳에 둔다. */
function pipelineFinished() {
  return ['done', 'partial', 'error'].includes(nf && nf.pipelinePhase);
}

/** 청중 반응 탭 — 예전엔 요약 탭 맨 아래에 묻혀 있어 찾기 어려웠다. */
function rAudience(host = $('#rbody')) {
  const blocked = audienceBlockReason();
  // '아직 안 왔다' 와 '분석이 실패했다' 는 다른 일이다. 둘 다 빨갛게 칠하면
  // 진짜 실패가 친절한 안내로 읽힌다 (CLAUDE.md §4 "실패하면 실패로 보여준다")
  // 색과 문구가 같은 신호를 봐야 한다. 예전엔 문구는 pipelinePhase 로,
  // 색은 pipelineOut 유무로 갈라서 "아직 …단계예요" 가 빨갛게 떴다
  const notYet = !pipelineFinished();
  host.innerHTML = `
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
  /* 시연·샘플은 브리지 없이 더미 수다로 연다. 실 API 가 있으면 그걸 쓰고,
     실패해도 시연이 막히지 않게 stub 으로 떨어진다. */
  if (rSampleMode || isShowcaseDemo()) {
    chatterPending = Promise.resolve(showcaseChatterStub());
    return;
  }
  chatterPending = window.Chatter.fetchChatter(b.graph, b.alignment, b.flow);
  chatterPending.catch(() => { chatterPending = null; });
}

/* ---------------------------------------------------------------------------
   삐약 청중석 — 리포트 '청중 반응' 탭에서 객석으로 들어간다
   --------------------------------------------------------------------------- */


/**
 * 시연·샘플 리포트용 청중 수다. /api/v1/chatter 없이 객석을 연다.
 * 판정 서사(과잉 매매 ok · 손실 회피 mid · 사전 매도 규칙 missing · 오해와 사실 ct)에 맞춘다.
 */
function showcaseChatterStub() {
  const file = (DATA.session && DATA.session.file) || 'showcase.pdf';
  const slides = (DATA.session && DATA.session.slides) || 15;
  return {
    file_name: file,
    total_slides: slides,
    absent: [],
    speaker_names: { midm: '믿:음', solar: '쏠라', exaone: '엑사원', ax: '엑씨' },
    speaker_models: {
      midm: 'KT 믿:음', solar: 'Upstage Solar',
      exaone: 'LG EXAONE', ax: 'SKT A.X',
    },
    turns: [
      { speaker: 'exaone', mood: 'happy', text: '과잉 매매 원인 설명은 진짜 좋았어. 비용은 확정인데 수익은 불확실하다 — 그 한 줄이 남네.',
        refs: [{ node_id: 'overtrade', source: 'alignment' }] },
      { speaker: 'midm', mood: 'grumpy', text: '근데 11번 상위 그룹 비교는… 표만 비추고 사전 매도 규칙은 말이 없더라. 결론 근거인데.',
        refs: [{ node_id: 'rules', source: 'alignment' }] },
      { speaker: 'solar', mood: 'curious', text: '자료엔 회전율 8.4배, 매도규칙 71% 대 18%가 있는데 발표에선 그 숫자가 안 나왔어.',
        refs: [{ node_id: 'rules', source: 'graph' }] },
      { speaker: 'ax', mood: 'neutral', text: '손실 회피는 짧게만 스쳤고, 오해와 사실 슬라이드에서는 자료랑 다른 결론을 말한 것 같아.',
        refs: [{ node_id: 'lossav', source: 'alignment' }, { node_id: 'myth', source: 'alignment' }] },
      { speaker: 'exaone', mood: 'happy', text: '그래도 과잉 매매→비용으로 이은 멘트는 깔끔했어. 그 호흡으로 11번만 살리면 된다.',
        refs: [{ node_id: 'overtrade', source: 'flow' }, { node_id: 'cost', source: 'flow' }] },
      { speaker: 'midm', mood: 'grumpy', text: '타이밍 실패도 슬라이드에 있었는데 발표에선 거의 안 들렸어. 원인 다섯 개라면서 두 개가 비네.',
        refs: [{ node_id: 'timing', source: 'alignment' }] },
      { speaker: 'ax', mood: 'curious', text: '전체로는 아홉 분쯤? 앞은 길고 결론 근거는 짧았어. 들으면서 숨이 앞쪽에 몰리는 느낌이었어.',
        refs: [] },
    ],
  };
}

function pipelineBundle() {
  const out = reportOut();
  if (out && out.graph && out.alignment && out.flow) return out;
  /* 샘플·시연 리포트는 말하기 탭 때문에 reportOut() 이 null 이다.
     청중석은 graph/alignment/flow 만 있으면 되므로, 방금 만든 stub 또는
     시연 더미를 따로 꺼낸다 — 안 그러면 「리허설을 마치면」 거짓말이 뜬다. */
  if (rSampleMode || isShowcaseDemo()) {
    const live = (nf && nf.pipelineOut) || null;
    if (live && live.graph && live.alignment && live.flow) return live;
    if (typeof showcasePipelineStub === 'function') {
      const stub = showcasePipelineStub();
      if (stub && stub.graph && stub.alignment && stub.flow) return stub;
    }
  }
  return null;
}

/** 청중이 왜 못 오는지 — '리허설을 마치세요'는 이미 마친 사람에게 거짓말이다. */
function audienceBlockReason() {
  if (pipelineBundle()) return null;

  const out = reportOut();
  if (!out) {
    /* 샘플·시연인데도 bundle 이 비면 stub 생성 실패다 — 리허설 미완료로 말하지 않는다 */
    if (rSampleMode || isShowcaseDemo()) {
      return '청중 데이터를 준비하지 못했어요. 화면을 새로고침한 뒤 다시 눌러 주세요.';
    }
    const upl = reportNf();
    return upl && upl.transcriptOk
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
  return `아직 ${stage} 단계예요. 실API 는 슬라이드 12개 기준 7분쯤 걸려요. `
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
      const fetchLive = () => window.Chatter.fetchChatter(
        bundle.graph, bundle.alignment, bundle.flow
      );
      if (rSampleMode || isShowcaseDemo()) {
        chatterCache = await (chatterPending || Promise.resolve(showcaseChatterStub()));
      } else {
        try {
          chatterCache = await (chatterPending || fetchLive());
        } catch (err) {
          /* 실연에서 API 가 죽어도 시연 플래그가 켜져 있으면 stub 으로 살린다 */
          if (isShowcaseDemo()) chatterCache = showcaseChatterStub();
          else throw err;
        }
      }
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
  /* 선택 표시와 함께 탭 정지점(tabindex)도 같이 옮긴다. 안 옮기면 ←→ 로
     넘긴 뒤 탭을 눌렀을 때 «예전에 선택했던 장» 으로 초점이 돌아간다 */
  $$('#deckFilm button').forEach(b => {
    const on = Number(b.dataset.slide) === n;
    b.classList.toggle('on', on);
    b.tabIndex = on ? 0 : -1;
    b.setAttribute('aria-current', on ? 'true' : 'false');
  });
  const cur = $(`#deckFilm button[data-slide="${n}"]`);
  if (cur) cur.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
  animateViz(body);
  bindDeckPanel();
  paintDeckStage(body);   // 다시 그린 무대는 비어 있다 — 원본 렌더를 새로 붙인다
}

function bindDeckPanel() {
  const go = $('#deckJudgeGo');
  if (go) go.addEventListener('click', () => goJudge(go.dataset.node));
}

/* 선택된 슬라이드의 무대 + 그 장에서 있었던 일.
   실데이터 세션에서는 판정 트리·올린 자료만 본다 — DATA.* 샘플은 샘플 모드 전용이다. */
function deckHtml() {
  const live = isLiveReportSession();
  const total = deckTotalSlides();
  const tree = judgeTree();
  /* 기본값(7)은 샘플 23장 기준이라 짧은 자료에서는 범위를 벗어난다.
     범위 밖이면 마지막 장으로 밀지 않고 판정이 걸린 첫 장을 연다 —
     처음 열자마자 「이 장에 걸린 개념 판정이 없어요」를 보여줄 이유가 없다. */
  let n = repSlide;
  if (n < 1 || n > total) {
    const judged = (tree[0] && tree[0].real)
      ? tree.map(x => slideNumber(x.slide)).filter(no => no >= 1 && no <= total).sort((a, b) => a - b)[0]
      : 0;
    n = judged || 1;
  }
  repSlide = n;
  const nodes = slideJudgeNodes(n, tree);          // 실데이터가 없으면 null
  const isReal = !!nodes;
  const node = isReal
    ? (nodes[0] || null)
    : (DATA.slideMainNode[n] ? DATA.tree.find(t => t.id === DATA.slideMainNode[n]) : null);
  const st = isReal ? (node ? node.status : 'om') : (DATA.slideStatus[n - 1] || 'none');
  const title = deckTitle(n, live);
  /* "그 장에서 있었던 일" — 실데이터는 같은 장의 나머지 개념 판정으로 채운다.
     DATA.timeline 은 IMU2CLIP 고정 타임라인이라 실데이터에 대응이 없다. */
  const moments = isReal
    ? nodes.slice(1).map(x => ({ time: x.evTime || '', type: x.status, label: x.label }))
    : (live ? [] : DATA.timeline.filter(e => e.onSlide === n));
  let panel = '';
  if (node && node.real) {
    // 라벨·근거·제안은 모두 LLM 산출물이다 — innerHTML 에 넣기 전에 이스케이프한다
    panel = `
      <div class="dp-top">${chip(node.status, true)}<b>${escapeHtml(node.label)}</b></div>
      <span class="bubble-label" style="margin-top:0">이 슬라이드에서 한 말</span>
      <div class="bubble">${node.ev
        ? escapeHtml(node.ev)
        : '<span class="note">이 개념에 해당하는 발화를 찾지 못했어요.</span>'}${node.evTime ? `<time>${escapeHtml(node.evTime)}</time>` : ''}</div>
      ${node.why ? `<p class="note" style="margin-top:10px">${escapeHtml(node.why)}</p>` : ''}
      ${node.fix ? `<div class="dp-fix"><b>이렇게 말해보세요</b><p>${escapeHtml(node.fix)}</p></div>` : ''}
      <button class="btn btn-tint btn-sm" id="deckJudgeGo" data-node="${escapeHtml(node.id)}">판정 근거 자세히 보기</button>`;
  } else if (node) {
    panel = `
      <div class="dp-top">${chip(node.status, true)}<b>${node.label}</b></div>
      ${node.status === 'ct' ? `
        <span class="bubble-label" style="margin-top:0">자료에 적힌 것</span>
        <div class="bubble">“${node.docSays}”</div>
        <span class="bubble-label">실제로 한 말</span>
        <div class="bubble" style="background:var(--ct-bg)">${node.spokeSays}<time>${node.spokeTime}</time></div>`
      : `
        <span class="bubble-label" style="margin-top:0">이 슬라이드에서 한 말</span>
        <div class="bubble">${node.ev}${node.evTime ? `<time>${node.evTime}</time>` : ''}</div>`}
      <div class="dp-fix"><b>이렇게 말해보세요</b><p>${node.fix}</p></div>
      <button class="btn btn-tint btn-sm" id="deckJudgeGo" data-node="${node.id}">판정 근거 자세히 보기</button>`;
  } else {
    panel = `<p class="dp-none">${live
      ? '이 슬라이드에 걸린 개념 판정이 없어요.'
      : '이 슬라이드는 핵심 개념 판정 대상이 아니에요.'}</p>`;
  }
  if (moments.length) {
    panel += `<div class="dp-moments">${moments.map(m =>
      `<div class="dp-moment"><time class="num">${escapeHtml(m.time)}</time>${chip(m.type, true)}<span>${escapeHtml(m.label)}</span></div>`).join('')}</div>`;
  }
  // PDF 가 있으면 캔버스에 원본을 크게 그리고, 없으면 자리표시자를 쓴다
  const stage = (uploadedPdf && uploadedPdf.pdf)
    ? `<canvas class="deck-canvas" data-stage-page="${n}" role="img" aria-label="${n}번 슬라이드 · ${escapeHtml(title)}"></canvas>`
    : `<img src="${deckImageSrc(n, live)}" alt="${n}번 슬라이드 · ${escapeHtml(title)}">`;
  return `
    <div class="deck-main">
      <figure class="deck-stage st-${st}">
        ${stage}
        <!-- 판정 이름(<em>${'${STATUS[st]}'}</em>)이 여기 또 있었다. 한 패널 안에서
             「언급만 함」이 세 번 나왔다 — 이 자막, 오른쪽 dp-top 의 칩, 그리고
             아래 순간 목록. 무대 테두리가 이미 판정 색(st-*)을 입고 있고, 판정을
             **말로** 하는 건 오른쪽 칩 하나면 된다. 자막은 몇 번째 장인지만 말한다. -->
        <figcaption><span class="num">${n} / ${total}</span>${escapeHtml(title)}</figcaption>
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
  const out = reportOut();
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

/* ─── 개념 전달 한눈에 ────────────────────────────────────────────────────
   이 탭은 판정 5종(설명함·언급만·안 나옴·자료와 모순·정당한 생략)을 **먼저
   배워야** 읽혔다. 필터 칩에 개수가 있긴 했지만 그건 «걸러 보는 도구» 지
   «결론» 이 아니라, 열자마자 「그래서 몇 개를 설명한 건데」에 답하는 게 없었다.

   그 답을 맨 위에 한 줄과 목록으로 놓는다.

   ⚠ 처음엔 가로 100% 누적 막대로 만들었다가 걷어냈다. 판정 5색(초록·갈색·빨강·
   보라·올리브)을 큰 면에 채우니 무지개가 됐고, 화면에서 제일 튀는 게 CTA 도
   결론도 아닌 그 막대가 됐다. 토스 그래픽 가이드가 그대로 짚는 자리다:
   「비슷한 크기의 그래픽이 많아질수록 시선이 분산된다 — 핵심 하나만 쓰고
   나머지는 아이콘으로」, 「그래픽이 텍스트나 CTA보다 튀지 않게」.

   판정 5색은 애초에 점·칩 크기로 쓰라고 정한 불변 색이다(§3-3). 색은 점으로만
   남기고 비율은 숫자로 읽힌다 — 이 탭에서 핵심 그래픽 하나는 아래 개념 목록이다. */
const JUDGE_SPLIT = [
  ['ok', '설명함'], ['mid', '언급만 함'], ['no', '안 나옴'],
  ['ct', '자료와 모순'], ['om', '정당한 생략'],
];

function judgeSplitHtml(tree) {
  const total = tree.length;
  if (!total) return '';
  const n = {};
  tree.forEach(t => { n[t.status] = (n[t.status] || 0) + 1; });
  const rows = JUDGE_SPLIT.filter(([k]) => n[k]);
  /* 짚어야 할 것 = 안 나옴 + 자료와 모순. 「설명함 3개」만 크게 쓰면 잘한 것만
     말하는 리포트가 된다 — 못 한 쪽도 같은 줄에 적는다 (§4) */
  const redo = (n.no || 0) + (n.ct || 0);
  return `
    <div class="card jsplit-card">
      <p class="jsplit-head">
        개념 <b class="num">${total}</b>개 중 <b class="num jsplit-ok">${n.ok || 0}</b>개를 설명했어요${
        redo ? `<span class="jsplit-redo">다시 볼 곳 ${redo}개</span>` : ''}
      </p>
      <div class="jsplit-rows">${rows.map(([k, label]) => `
        <div class="jsplit-row">
          <i class="dot st-${k}"></i>
          <span class="jsplit-name">${label}</span>
          <b class="num">${n[k]}</b>
        </div>`).join('')}</div>
    </div>`;
}

function rJudge() {
  const tree = judgeTree();
  const isReal = !!(tree[0] && tree[0].real);
  if (isLiveReportSession() && !tree.length) {
    $('#rbody').innerHTML = `
      <div class="card">
        <h3 class="section-title">개념 판정이 아직 없어요</h3>
        <p class="note">내 발표 분석(그래프·정합)이 아직 없어 개념 판정을 그리지 못했어요.</p>
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
    ${judgeSplitHtml(tree)}
    <div class="filter-chips" id="jf">
      ${filters.map(f => `<button class="${jFilter === f[0] ? 'on' : ''}" data-f="${f[0]}">${f[1]} ${counts[f[0]] || 0}</button>`).join('')}
    </div>
    <div class="judge-grid">
      <div class="card" style="padding:8px">
        <div class="tree" id="jtree">
          ${items.map(t => `
          <button class="${t.id === jSel ? 'sel' : ''} ${t.depth === 2 ? 'child' : ''}" data-id="${t.id}">
            <span class="dot st-${t.status}"></span>${escapeHtml(t.label)}
            <small>${slideNumber(t.slide)}번</small>
          </button>`).join('')}
        </div>
      </div>
      <div class="card" id="jdetail">${n ? jDetail(n, tree) : '<p class="note">이 상태의 개념이 없어요.</p>'}</div>
    </div>
    <p class="ai-note">${(isReal || isShowcaseDemo())
      ? '판정은 AI 분석 결과예요. 이상하다고 느껴지면 근거 발화를 직접 확인해보세요.'
      : (isLiveReportSession()
        ? '내 발표 분석 결과가 없어 개념 판정을 그리지 못했어요.'
        : '⚠️ 지금 보는 건 <b>샘플 데이터</b>예요. 리허설을 마치면 내 발표 결과로 바뀌어요.')}</p>`;
  paintDeckStage($('#rbody'));   // 판정 화면의 슬라이드도 올린 자료 원본으로 그린다
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
  const live = isLiveReportSession();
  const title = deckTitle(slideNum, live);
  /* 무대(rSummary)와 같은 규율 — PDF 가 있으면 원본을 크게 그리고,
     없으면 자리표시자. 업로드 세션에 샘플 슬라이드 이미지를 끼워 넣지 않는다. */
  const stage = (uploadedPdf && uploadedPdf.pdf)
    ? `<canvas class="deck-canvas" data-stage-page="${slideNum}" role="img" aria-label="${slideNum}번 슬라이드 · ${escapeHtml(title)}"></canvas>`
    : `<img src="${deckImageSrc(slideNum, live)}" alt="${slideNum}번 슬라이드 · ${escapeHtml(title)}">`;
  // 실데이터는 4축을 checks 로, 샘플은 옛 필드명 check 로 준다
  const checks = n.checks || n.check || {};
  return `
    <div class="detail-top">
      <h3>${escapeHtml(n.label)}</h3>${chip(n.status)}
    </div>
    <p class="detail-meta">${slideNum}번 슬라이드 · 중요도 ${Number(n.w || 0).toFixed(2)}${n.depth === 2 ? ` · 상위 개념: ${escapeHtml(tree.find(t => t.id === n.parent)?.label || '—')}` : ''}</p>
    <figure class="judge-slide st-${n.status}">
      ${stage}
      <figcaption><span class="num">${slideNum}번 슬라이드</span>${escapeHtml(title)}</figcaption>
    </figure>
    ${n.conf ? `<div class="confbar">판정 확신도 <span class="fill-bar"><i data-w="${n.conf}%"></i></span><b class="num">${n.conf}%</b></div>` : ''}
    ${Object.keys(checks).length ? `<div class="checks">
      ${Object.entries(checks).map(([k, v]) => `<span class="${v ? 'y' : ''}">${v ? '✓' : '—'} ${escapeHtml(k)}</span>`).join('')}
    </div>` : ''}
    ${n.status === 'ct' && n.docSays ? `
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
  good_link: { type: '매끄러운 연결', good: true },
};

/* ── 탭 진단 블록 ─────────────────────────────────────────────
   "판단은 헤드, 단서는 아래 작은 줄" — 판정 헤드(reportVerdict)와 같은 규율.
   verdict 가 null 이면 블록째 그리지 않는다: 근거 없는 헤드라인은 지어내지 않는다. */
function tabVerdictHtml(v) {
  if (!v || !v.headline) return '';
  return `
  <div class="tab-verdict">
    <h2>${escapeHtml(v.headline)}</h2>
    ${v.action ? `<p class="tv-action">${escapeHtml(v.action)}</p>` : ''}
    ${v.evidence ? `<div class="bubble">“${escapeHtml(v.evidence)}”</div>` : ''}
  </div>`;
}

/* 문제가 여럿이면 이 순서로 "가장 큰 문제" 하나를 고른다 —
   잇는 말이 아예 없는 단절이 순서 점프보다 청중을 먼저 잃는다 */
const FLOW_PRIORITY = ['missing_link', 'order_jump'];

function flowIssueRank(kind) {
  const i = FLOW_PRIORITY.indexOf(kind);
  return i === -1 ? FLOW_PRIORITY.length : i;
}

function flowWhere(slides) {
  if (!slides || !slides.length) return '슬라이드를 넘길 때';
  if (slides.length > 1) return `${slides[0]}번에서 ${slides[slides.length - 1]}번으로 넘어갈 때`;
  return `${slides[0]}번 슬라이드에서`;
}

function flowVerdict(flow) {
  const issues = (flow && flow.issues) || [];
  if (!issues.length) return null;
  const bad = issues.filter(i => flowIssueRank(i.kind) < FLOW_PRIORITY.length)
    .sort((a, b) => flowIssueRank(a.kind) - flowIssueRank(b.kind));
  if (!bad.length) {
    return {
      headline: '연결이 매끄러웠어요 — 이 흐름을 지키세요',
      action: '지금 쓴 연결 멘트를 다음 발표에서도 그대로 쓰면 좋아요.',
    };
  }
  const top = bad[0];
  const where = flowWhere(top.slide_nos);
  if (top.kind === 'missing_link') {
    return {
      headline: `${where} 잇는 말 없이 화제가 바뀌었어요`,
      action: '「그래서」「이걸 확인하려고」처럼 앞 슬라이드와 잇는 한 문장을 넣으면 흐름이 살아나요.',
      evidence: top.cue || '',
    };
  }
  return {
    headline: `${where} 근거보다 결론이 먼저 나왔어요`,
    action: '자료 순서대로 근거를 먼저 말하고 결론으로 넘어가면 따라가기 쉬워요.',
    evidence: top.cue || '',
  };
}

/* ── 숫자 해석 라벨 — 숫자는 유지하고 옆에 판정 말을 붙인다 (§14 숫자는 신성하다) ── */
function tauJudge(pct) {
  if (pct >= 85) return '자료 순서를 잘 따랐어요';
  if (pct >= 60) return '순서가 몇 번 엇갈렸어요';
  return '자료 순서와 많이 달랐어요';
}

const CPM_REC = { min: 300, max: 350 }; // F-17 이 권장을 안 주면 쓰는 화면 기본값(자/분)

/** 00:00 꼴. 막대 안이나 총량 비교처럼 자리수가 고정돼야 읽히는 곳에 쓴다
 *  (fmtSec 의 「9분 24초」는 문장 안에서 읽는 꼴이다) */
function clockSec(sec) {
  const s = Math.max(0, Math.round(sec || 0));
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

/* ── 말 속도를 사람의 말로 ─────────────────────────────────────────────
   「328자/분」은 발표하는 사람이 체감할 수 없는 숫자다. 발표 중에 자기가 몇 자를
   말했는지 아는 사람은 없고, 그래서 이 숫자를 봐도 다음에 무엇을 바꿀지 못 정한다.
   계산은 자/분으로 그대로 하고(권장 범위와 견주려면 필요하다), 화면에는 판정과
   처방만 내놓는다. 원본 값은 title 로만 남긴다 — 물어보면 답할 수 있게. */
const PACE_STEPS = {
  vfast: { label: '매우 빠름', tip: '듣는 사람이 따라가기 어려울 수 있어요' },
  fast: { label: '조금 빠름', tip: '문장 끝에서 한 박자 쉬어 보세요' },
  ok: { label: '적정 속도', tip: '듣기 편한 범위로 말했어요' },
  slow: { label: '조금 느림', tip: '조금만 템포를 올려도 좋아요' },
  vslow: { label: '매우 느림', tip: '핵심 문장만 남기고 템포를 올려 보세요' },
};

/** @returns {{key:string,label:string,tip:string,cpm:number}|null} */
function paceJudge(avg, rec) {
  if (!avg) return null;
  const nums = String(rec || '').match(/\d+/g) || [];
  const lo = Number(nums[0]) || CPM_REC.min;
  const hi = Number(nums[1]) || CPM_REC.max;
  const key = avg > hi * 1.15 ? 'vfast'
    : avg > hi ? 'fast'
      : avg < lo * 0.85 ? 'vslow'
        : avg < lo ? 'slow' : 'ok';
  return { key, ...PACE_STEPS[key], cpm: Math.round(avg) };
}
const paceIsFast = j => !!j && (j.key === 'fast' || j.key === 'vfast');

/** 구간 속도는 절대값이 아니라 «본인 평균의 몇 배» 로 말한다 —
 *  같은 430자/분이 어떤 사람에겐 평소 속도고 어떤 사람에겐 폭주다 */
function paceRatioWord(cpm, avg) {
  if (!cpm || !avg) return '';
  const r = cpm / avg;
  if (Math.abs(r - 1) < 0.1) return '평소와 비슷';
  return `평소의 ${r.toFixed(1)}배 · ${r > 1 ? '빠름' : '천천히'}`;
}

function cpmJudge(avg, rec) {
  if (!avg) return '';
  const nums = String(rec || '').match(/\d+/g) || [];
  const lo = Number(nums[0]) || CPM_REC.min;
  const hi = Number(nums[1]) || CPM_REC.max;
  if (avg > hi * 1.15) return '권장보다 많이 빨라요';
  if (avg > hi) return '권장보다 조금 빨라요';
  if (avg < lo * 0.85) return '권장보다 많이 느려요';
  if (avg < lo) return '권장보다 조금 느려요';
  return '권장 범위예요';
}

/** 분석 단위(자/분)를 사람이 바로 이해하는 말로 바꾼다. 원값은 계산에만 쓴다. */
function humanPaceLabel(avg, rec) {
  const judged = cpmJudge(avg, rec);
  if (judged.includes('많이 빨라요')) return { short: '매우 빠름', detail: '듣는 사람이 따라가기 어려울 수 있어요' };
  if (judged.includes('조금 빨라요')) return { short: '조금 빠름', detail: '문장 끝에서 한 박자 쉬어 보세요' };
  if (judged.includes('많이 느려요')) return { short: '매우 느림', detail: '설명이 늘어지지 않게 호흡을 줄여 보세요' };
  if (judged.includes('조금 느려요')) return { short: '조금 느림', detail: '조금만 템포를 올려도 좋아요' };
  return { short: '적정 속도', detail: '듣기 편한 범위로 말했어요' };
}

function paceRatioText(value, baseline) {
  if (!value || !baseline) return '측정 전';
  const ratio = value / baseline;
  if (ratio >= 1.15) return `평소의 ${ratio.toFixed(1)}배 · 빠름`;
  if (ratio <= .85) return `평소의 ${ratio.toFixed(1)}배 · 천천히`;
  return '평소와 비슷';
}

function timeDiffJudge(targetSec, actualSec) {
  if (!targetSec || !actualSec) return '';
  const d = Math.round(actualSec - targetSec);
  if (Math.abs(d) <= Math.max(15, targetSec * 0.05)) return '목표와 거의 맞았어요';
  return d > 0 ? `목표보다 ${fmtSec(d)} 길었어요` : `목표보다 ${fmtSec(-d)} 짧았어요`;
}

/* 간투어는 어떤 말이 올지 모른다 — 받침에 맞는 조사를 고른다 (「음」을 / 「어」를) */
function josaEulReul(word) {
  const c = String(word).charCodeAt(String(word).length - 1);
  if (c < 0xAC00 || c > 0xD7A3) return '를';
  return (c - 0xAC00) % 28 ? '을' : '를';
}

/* 음성 습관 우선순위: 핵심 장 시간 부족·초과 > 속도 > 간투어.
   voiceEasyBlocks 가 이미 만드는 headline/actions 를 승격해 재사용한다. */
function voiceVerdict(easy, pace) {
  if (!easy) return null;
  if (easy.shortCore.length || easy.longOnes.length) {
    return { headline: easy.headline, action: easy.actions[0] || '' };
  }
  const avg = Math.round((pace && pace.avg_chars_per_min) || 0);
  const speed = paceJudge(avg, pace && pace.recommended_cpm);
  if (speed && speed.key !== 'ok') {
    const isFast = paceIsFast(speed);
    return {
      headline: isFast ? '전체적으로 권장보다 빠르게 말했어요' : '전체적으로 권장보다 천천히 말했어요',
      action: isFast
        ? '문장이 끝날 때 반 박자 쉬어 가면 듣는 사람이 따라와요.'
        : '설명 구간에서 속도를 조금만 올리면 늘어지지 않아요.',
    };
  }
  const totalFillers = easy.fillers.reduce((sum, f) => sum + f.n, 0);
  if (totalFillers >= 3) {
    const topF = easy.fillers[0];
    return {
      headline: `「${topF.text}」${josaEulReul(topF.text)} ${topF.n}번 말했어요 — 간투어를 줄여 보세요`,
      action: easy.actions[0] || '발표 전에 한 번 소리 내어 읽어보면 간투어가 줄어요.',
    };
  }
  // 시간·속도·간투어 모두 무난 — 칭찬으로 마무리하고 유지 처방을 준다
  return {
    headline: '시간·속도·말버릇 모두 안정적이었어요',
    action: '이 페이스를 유지하면서 내용 전달에 집중하면 돼요.',
  };
}

/**
 * 흐름 탭의 주인공 한 칸 (2026-08-12 다시 그림) — 「10번 슬라이드 ✕ 13번 슬라이드」
 * 처럼 텍스트 칩만 있던 자리에 실제 슬라이드 두 장을 나란히 보여준다. 사이가
 * 벌어져 있으면(from·to 가 연속이 아니면) 그 사이 번호를 「건너뜀」으로 짚어서
 * "다리가 비어 있다" 는 말을 그림으로도 보여준다. 나머지(접힌 목록)는 예전
 * 텍스트 칩 카드를 그대로 쓴다 — 주인공 하나만 크게, 나머지는 조용히(dimsHtml
 * 과 같은 원칙). img[data-thumb-page] 는 렌더 뒤 paintDeckThumbs 가 채운다.
 */
function flowFeatureCardHtml({ good, topLabel, from, to, typeLabel, note, quoteHtml }) {
  const fromNo = parseInt(from, 10) || 0;
  const toNo = parseInt(to, 10) || fromNo;
  const skipLabel = toNo - fromNo === 2 ? `${fromNo + 1}번`
    : toNo - fromNo > 2 ? `${fromNo + 1}-${toNo - 1}번` : '';
  return `
  <div class="card flow-feature">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
      ${chip(good ? 'ok' : 'no', true)}
      <span class="note">${topLabel}</span>
    </div>
    <div class="flow-feature-slides">
      <figure class="flow-feature-slide">
        <img data-thumb-page="${fromNo}" src="${deckImageSrc(fromNo)}" alt="${fromNo}번 슬라이드" loading="lazy">
        <figcaption>${fromNo}번 슬라이드</figcaption>
      </figure>
      <div class="flow-feature-gap">
        <em class="${good ? 'good' : ''}">${good ? '✓' : '✕'}</em>
        ${skipLabel ? `<span class="flow-feature-skip">${skipLabel} 건너뜀</span>` : ''}
      </div>
      <figure class="flow-feature-slide">
        <img data-thumb-page="${toNo}" src="${deckImageSrc(toNo)}" alt="${toNo}번 슬라이드" loading="lazy">
        <figcaption>${toNo}번 슬라이드</figcaption>
      </figure>
    </div>
    <p class="logic-note"><b>${typeLabel}</b> — ${note}</p>
    ${quoteHtml ? `<div class="bubble">${quoteHtml}</div>` : ''}
  </div>`;
}

/** 실데이터 흐름 이슈 하나를 flowFeatureCardHtml 입력으로 옮긴다.
 *  주인공 카드와 접힌 목록이 같은 그림(실제 슬라이드 두 장)을 쓰게 한다
 *  (2026-08-12: "나머지도 비슷하게" — 텍스트 칩 카드를 걷어냈다). */
function flowIssueToFeature(i) {
  const kind = FLOW_KIND[i.kind] || { type: escapeHtml(i.kind), good: false };
  const slides = i.slide_nos || [];
  return flowFeatureCardHtml({
    good: kind.good,
    topLabel: kind.type,
    from: slides[0] || 0,
    to: slides.length > 1 ? slides[slides.length - 1] : slides[0] || 0,
    typeLabel: kind.type,
    note: escapeHtml(i.note || ''),
    quoteHtml: i.cue ? `“${escapeHtml(i.cue)}”` : '',
  });
}

function rLogicRealCards(flow) {
  // 가장 큰 문제(진단 블록과 같은 기준)를 맨 앞에 펼치고 나머지는 접는다
  const issues = [...(flow.issues || [])]
    .sort((a, b) => flowIssueRank(a.kind) - flowIssueRank(b.kind));
  const [first, ...rest] = issues;

  const tau = flow.order_tau;
  let tauNote = '';
  if (tau != null) {
    const pct = Math.round(((tau + 1) / 2) * 100);
    tauNote = `<p class="ai-note">자료 순서와 발표 순서 일치도 <b class="num">${pct}%</b> — ${tauJudge(pct)}${
      (flow.ghost_node_ids || []).length
        ? ` · 한 번도 언급되지 않은 개념 ${flow.ghost_node_ids.length}개`
        : ''}</p>`;
  }
  const firstKind = first && (FLOW_KIND[first.kind] || { type: escapeHtml(first.kind), good: false });
  const firstSlides = (first && first.slide_nos) || [];
  return `
    ${tabVerdictHtml(flowVerdict(flow))}
    ${first ? flowFeatureCardHtml({
    good: firstKind.good,
    topLabel: firstKind.type,
    from: firstSlides[0] || 0,
    to: firstSlides.length > 1 ? firstSlides[firstSlides.length - 1] : firstSlides[0] || 0,
    typeLabel: firstKind.type,
    note: escapeHtml(first.note || ''),
    quoteHtml: first.cue ? `“${escapeHtml(first.cue)}”` : '',
  }) : ''}
    ${rest.length ? `<details class="fold"><summary>나머지 ${rest.length}곳 더 보기</summary>
      <div class="fold-body">${rest.map(flowIssueToFeature).join('')}</div></details>` : ''}
    ${tauNote}`;
}

/** 샘플 흐름 이슈 하나를 flowFeatureCardHtml 입력으로 옮긴다 — 위 flowIssueToFeature
 *  와 같은 이유(2026-08-12), 실측 경로가 아니라 DATA.logicBreaks 모양을 받는다. */
function logicBreakToFeature(l) {
  return flowFeatureCardHtml({
    good: l.good,
    topLabel: l.time,
    from: l.from,
    to: l.to,
    typeLabel: l.type,
    note: l.note,
    quoteHtml: l.ev ? `${l.ev}<time>${l.time}</time>` : '',
  });
}

function rLogic() {
  const flow = (reportOut() || {}).flow;
  if (flow && Array.isArray(flow.issues) && flow.issues.length) {
    $('#rbody').innerHTML = rLogicRealCards(flow);
    paintDeckThumbs($('#rbody'));
    return;
  }
  // 샘플 경로도 같은 구조 — 끊긴 곳을 앞으로, 잘된 연결은 접는다 (샘플 배지는 판정 헤드가 단다)
  const breaks = [...DATA.logicBreaks].sort((a, b) => (a.good ? 1 : 0) - (b.good ? 1 : 0));
  const [first, ...rest] = breaks;
  const bad = breaks.filter(l => !l.good);
  const verdict = bad.length ? {
    /* DATA.logicBreaks 의 from·to 는 이미 '5번' 처럼 번을 달고 있다.
       여기서 또 붙여서 「5번번에서 7번번으로」가 나가고 있었다 (샘플 경로).
       "넘어갈 때 논리가 끊겼어요" 는 무엇이 문제인지 말해주지 않는다 —
       두 슬라이드가 어긋난다는 사실 자체를 직접 말한다 (2026-08-12 지적). */
    headline: `${bad[0].from}과 ${bad[0].to}은 논리가 달라요`,
    action: '앞 슬라이드와 잇는 한 문장을 넣으면 흐름이 살아나요. 아래 실제 발화를 확인해 보세요.',
  } : null;
  $('#rbody').innerHTML = `
    ${tabVerdictHtml(verdict)}
    ${first ? flowFeatureCardHtml({
    good: first.good,
    topLabel: first.time,
    from: first.from,
    to: first.to,
    typeLabel: first.type,
    note: first.note,
    quoteHtml: first.ev ? `${first.ev}<time>${first.time}</time>` : '',
  }) : ''}
    ${rest.length ? `<details class="fold"><summary>나머지 ${rest.length}곳 더 보기</summary>
      <div class="fold-body">${rest.map(logicBreakToFeature).join('')}</div></details>` : ''}`;
  paintDeckThumbs($('#rbody'));
}

/* 탭 4 — 말 속도 */
/** F-14/F-17 결과를 말 속도·음성 습관 탭이 쓰는 모양으로. */
function realPace() {
  const p = (reportOut() || {}).pace;
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

/* ─── 시간 분배 (음성 습관) ─────────────────────────────────────────────────
   장마다 막대를 그리면 「각 장이 몇 초였나」는 알 수 있어도 「어디를 줄이고
   어디를 늘려야 하나」는 안 읽힌다 — 33개를 눈으로 빼기 때문이다.

   그래서 줄을 둘로 줄인다: 이상적인 배분 한 줄, 내가 한 발표 한 줄. 둘 다 폭이
   100% 고 같은 구간은 같은 색이라, 눈이 두 줄의 「같은 색 폭 차이」를 그냥 본다.
   파이 차트를 펴서 위아래로 겹쳐 놓은 것과 같다 — 비교가 목적이면 파이보다
   가로 막대가 낫다(각도보다 길이를 정확히 읽는다). */
/* 구간 색 — 브랜드 딥그린 한 색의 계조다.
   처음엔 초록·파랑·자홍·보라를 돌려 썼는데, 초록 하나로 세운 앱에서 무지개는
   그 자리만 다른 제품처럼 보인다. 게다가 인코딩이 틀렸다: 구간은
   「배경 → 동기·구조 → 방법론 → 실험 → 결론」으로 **시간 순서**를 갖는다.
   순서가 있는 값에 순서 없는 범주형 색을 쓰면, 눈이 색에서 순서를 못 읽는다.
   진한 데서 옅은 데로 흐르게 두면 색 자체가 발표의 진행을 말한다.

   판정 5색(--ok/--mid/--no/--ct/--om)과는 겹치지 않는다 — 그 다섯은 뜻이
   박혀 있어서 여기 쓰면 리포트가 거짓말이 된다 (CLAUDE.md §3-3).
   ⚠ 예전엔 7단 고정 목록이었다. 구간이 8개가 되면 `i % 7` 로 돌아 두 구간이
   같은 색이 됐다 — 그래프가 거짓말을 하는 자리다. 지금 파이프라인은 3개까지만
   만들지만(f17 전반·중반·후반) 샘플은 이미 5개고, 백엔드가 늘면 바로 걸린다.
   개수에서 뽑으면 3개든 12개든 늘 고르게 나뉘고 겹치지 않는다. */
const TSPLIT_FROM = [6, 59, 44];     // #063B2C 가장 진한 딥그린
const TSPLIT_TO = [150, 217, 183];   // #96D9B7 연한 민트

/** n 개의 [면색, 글자색]. 글자색은 손으로 짝짓지 않고 면의 밝기에서 정한다 —
 *  단계 수가 바뀌면 손으로 맞춘 짝은 반드시 어긋난다. */
function tsplitRamp(n) {
  return Array.from({ length: n }, (_, i) => {
    const t = n <= 1 ? 0 : i / (n - 1);
    const rgb = TSPLIT_FROM.map((v, k) => Math.round(v + (TSPLIT_TO[k] - v) * t));
    const lum = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255;
    return [`rgb(${rgb.join(',')})`, lum > 0.55 ? '#06301F' : '#fff'];
  });
}

/** 샘플 발표의 목표 시간(10분 모드). 샘플 데이터에는 목표가 없다 */
const SAMPLE_TARGET_SEC = 600;

function timeSplitHtml(rows, totals = {}) {
  const clean = (rows || []).filter(r => r && (r.rec > 0 || r.act > 0));
  if (clean.length < 2) return '';
  const sum = k => clean.reduce((s, r) => s + Math.max(0, r[k] || 0), 0) || 1;
  const recTotal = sum('rec'), actTotal = sum('act');

  const ramp = tsplitRamp(clean.length);
  const bar = (k, total, showTime = false) => `<div class="tsplit-bar">${clean.map((r, i) => {
    const pct = Math.max(0, r[k] || 0) / total * 100;
    if (pct <= 0) return '';
    const [bg, fg] = ramp[i];
    const seconds = Math.max(0, r[k] || 0);
    return `<span class="tsplit-seg" style="width:${pct.toFixed(2)}%;--c:${bg};--tc:${fg}"
                 title="${escapeHtml(r.name)} · ${Math.round(pct)}% · ${fmtMarkSec(seconds)}">${
      /* 좁은 조각에 숫자를 우겨넣으면 글자가 잘려 나온다. 9% 아래는 색만 남기고
         숫자는 범례와 title 이 맡는다 */
      pct >= 9 ? `<b>${Math.round(pct)}%</b>${showTime ? `<small class="tsplit-time">${fmtMarkSec(seconds)}</small>` : ''}` : ''}</span>`;
  }).join('')}</div>`;

  const targetSec = Math.max(1, Number(totals.targetSec) || recTotal);
  const actualSec = Math.max(0, Number(totals.actualSec) || actTotal);
  const scaleMax = Math.max(targetSec, actualSec, 1);
  const targetPct = targetSec / scaleMax * 100;
  const actualPct = actualSec / scaleMax * 100;
  const totalGap = Math.round(actualSec - targetSec);
  const deltaText = totalGap === 0 ? '목표와 같음' : `${totalGap > 0 ? '+' : '−'}${fmtMarkSec(Math.abs(totalGap))}`;

  /* 한 줄 결론. 가장 크게 어긋난 구간 둘만 말한다 — 다섯 구간을 다 늘어놓으면
     그래프를 두 줄로 줄인 뜻이 없다 */
  const gaps = clean.map(r => ({
    name: r.name,
    gap: Math.round((r.act / actTotal * 100) - (r.rec / recTotal * 100)),
  })).filter(g => Math.abs(g.gap) >= 3).sort((a, b) => Math.abs(b.gap) - Math.abs(a.gap));
  const say = gaps.slice(0, 2).map(g => `<b>${escapeHtml(g.name)}</b>에 ${
    g.gap > 0 ? `${g.gap}%p 더` : `${-g.gap}%p 적게`} 썼어요`).join(' · ');

  return `
    <div class="tsplit">
      <div class="tsplit-legend">${clean.map((r, i) => {
        const gap = Math.round((r.act / actTotal * 100) - (r.rec / recTotal * 100));
        const delta = gap === 0 ? '' : `<small class="${gap > 0 ? 'is-more' : 'is-less'}">${gap > 0 ? '+' : '−'}${Math.abs(gap)}%p</small>`;
        return `<span><i style="background:${ramp[i][0]}"></i>${escapeHtml(r.name)}${delta}</span>`;
      }).join('')}</div>
      <div class="tsplit-row">
        <span class="tsplit-lb">이상적인 배분</span>
        ${bar('rec', recTotal)}
      </div>
      <div class="tsplit-row is-mine">
        <span class="tsplit-lb">내가 한 발표</span>
        ${bar('act', actTotal, true)}
      </div>
      <div class="tsplit-total">
        <span class="tsplit-lb">총 발표 길이</span>
        <div>
          <div class="tsplit-total-copy"><span>목표 ${fmtMarkSec(targetSec)}</span><b>실제 ${fmtMarkSec(actualSec)} <em class="tsplit-delta${totalGap < 0 ? ' is-short' : ''}">${deltaText}</em></b></div>
          <div class="tsplit-total-track" aria-label="목표 ${fmtMarkSec(targetSec)}, 실제 ${fmtMarkSec(actualSec)}">
            <span class="tsplit-total-fill" style="width:${actualPct.toFixed(2)}%"></span>
            <i class="tsplit-target-mark" style="left:${targetPct.toFixed(2)}%" aria-hidden="true"></i>
          </div>
        </div>
      </div>
      <p class="note tsplit-say">${say || '이상적인 배분과 거의 같게 썼어요.'}</p>
    </div>`;
}

/** 시간 분배 카드 — 실측이면 pace.sections, 샘플이면 DATA.timeAlloc 을 쓴다. */

function timeSplitCard(pace) {
  const secs = (pace && pace.sections) || [];
  const sampleTargetSec = 600;
  const sampleActualSec = Number(DATA.session && DATA.session.durationSec) || sampleTargetSec;
  const rows = secs.length
    ? secs.map(s => ({ name: s.name, rec: s.recommended_sec || 0, act: s.actual_sec || 0 }))
    : (DATA.timeAlloc || []).map(r => ({
        name: r[0],
        rec: sampleTargetSec * (r[1] || 0) / 100,
        act: sampleActualSec * (r[2] || 0) / 100,
      }));
  const totals = secs.length
    ? { targetSec: pace.target_sec, actualSec: pace.actual_sec }
    : { targetSec: sampleTargetSec, actualSec: sampleActualSec };
  const body = timeSplitHtml(rows, totals);
  if (!body) return '';
  return `
    <div class="card">
      <h3 class="section-title">시간 분배<span class="soft">이상적인 배분과 나란히 놓고 봐요</span></h3>
      ${body}
    </div>`;
}

function rPace(host = $('#rbody')) {
  const livePace = (reportOut() || {}).pace;
  const liveHabits = (reportOut() || {}).habits;
  const liveReport = (reportOut() || {}).report;
  if (livePace && Array.isArray(livePace.slides) && livePace.slides.length && livePace.slides[0].actual_sec != null && typeof voiceTimeChartHtml === 'function') {
    const avg = livePace.avg_chars_per_min || 0;
    const easy = voiceEasyBlocks(livePace, liveHabits, liveReport || {});
    const fillers = easy.fillers || [];
    const repeats = easy.repeats || [];
    // 처방 문구는 진단 블록이 한 번만 말한다 — 예전 voice-tip 과 중복이었다
    const diffLabel = timeDiffJudge(livePace.target_sec, livePace.actual_sec);
    const speedPace = humanPaceLabel(Math.round(avg), livePace.recommended_cpm);
    /* 「짧게 말한 핵심 장」 상자는 뺐다 — 같은 사실을 위 그래프가 이미 말한다
       (핵심 장은 S번호가 파랑, 짧은 장은 막대 색이 다르다). 판정 헤드의 처방과
       상자 제목까지 세 번 반복돼서 화면이 길어지기만 했다. */
    /* 장별 차트(voiceTimeChartHtml)가 여기 있었다. 33장이면 막대가 33개라
       「어디를 줄이나」가 안 읽혔다 — 구간 두 줄로 바꾼다 (timeSplitCard). */
    const splitCard = timeSplitCard(livePace);
    const longCard = `
      <div class="card">
        <h3 class="section-title">길게 말한 장<span class="soft">여기를 줄이면 목표에 더 가까워져요</span></h3>
        <div class="slide-pill-row">${slidePillHtml(easy.longOnes, 'long')}</div>
      </div>`;
    const habitRows = [
      ...fillers.map(f => ({ ...f, tag: '간투어' })),
      ...repeats.map(f => ({ ...f, tag: '반복' })),
    ];
    const fillerCard = `
      <div class="card">
        <h3 class="section-title">자주 쓴 간투어·반복<span class="soft">간투어 ${(liveHabits && liveHabits.filler_cnt) || fillers.length}회 · 같은 말 반복 ${(liveHabits && liveHabits.repeat_cnt) || repeats.length}회 · 긴 쉼 ${(liveHabits && liveHabits.pause_cnt) || 0}회</span></h3>
        <!-- F-18 LoRA 태거(FIL/REP/PAUSE) 결과. 시연은 같은 계약의 stub 을 그린다. -->
        ${habitRows.length ? `<div class="filler-list">${habitRows.map(f => `
          <div class="filler-row"><span><span class="ftag">${f.tag}</span><span class="fsep" aria-hidden="true">|</span>${escapeHtml(f.text)}</span><b class="num">${f.n}회</b></div>`).join('')}</div>`
          : `<p class="note">눈에 띄는 간투어·반복은 거의 없었어요. 좋아요!</p>`}
      </div>`;
    /* 세로 한 줄로 편다. 예전엔 진단에 따라 시간·간투어 중 하나를 접어 뒀는데,
       접힌 쪽은 있는 줄도 모르고 지나갔다 — 둘 다 이 탭의 본문이다. */
    /* 순서가 곧 읽는 순서다. 시간 분배 → 그 판정 → 숫자 → 어디가 문제였나 →
       청중 반응 → 말버릇. 예전엔 판정 상자가 맨 위에 홀로 떠서, 무엇을 보고
       그렇게 판정했는지가 아래에 따로 있었다 — 판정은 근거 바로 옆에 있어야 한다 */
    host.innerHTML = `
      <div class="voice-stack">
        ${splitCard}
        ${tabVerdictHtml(voiceVerdict(easy, livePace))}
        <!-- 카드 세 장이었다. 시간 분배 막대가 바로 위에서 같은 이야기를 그림으로
             하고 있어서, 카드까지 세우면 비슷한 크기의 그래픽이 둘이 된다
             (토스 그래픽 3번). 숫자는 지키고 무게만 뺀다 -->
        <p class="voice-facts">
          <span><i>목표</i>${escapeHtml(easy.target)}</span>
          <span><i>내가 쓴 시간</i>${escapeHtml(easy.actual)}${diffLabel ? `<em>${escapeHtml(diffLabel)}</em>` : ''}</span>
          <span><i>전체 말 속도</i>${escapeHtml(speedPace.short)}<em>${escapeHtml(speedPace.detail)}</em></span>
        </p>
        <div id="dlvAud"></div>
        ${longCard}
        ${fillerCard}
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
    : '상위 그룹 비교 구간이 본인 평균보다 31% 빨라요. 사전 매도 규칙 등 설명이 빠졌다고 판정된 개념과 겹쳐요.';
  // 폴백 경로도 진단→근거→처방 구조를 따른다 — 헤드라인은 이미 계산된 판정에서만 만든다
  const fbVerdict = fastRows.length
    ? { headline: `${fastRows.length}개 구간에서 평균보다 훨씬 빨랐어요`,
        action: '빠른 구간의 개념 판정을 함께 확인하고, 그 슬라이드에서 한 박자 쉬어 보세요.' }
    : { headline: '구간별 말 속도가 고르게 유지됐어요',
        action: '이 속도를 유지하면서 아래 시간 배분만 살펴보세요.' };
  const fbPace = humanPaceLabel(st.avg, st.rec);
  const fastestRatio = st.avg ? st.max / st.avg : 0;
  host.innerHTML = `
    <div class="voice-stack">
      ${real || isShowcaseDemo() ? '' : `<p class="note" style="color:var(--mid);margin-bottom:0">
        ⚠️ <b>샘플 데이터</b>예요. 리허설을 마치면 내 발화로 계산해요.</p>`}
      ${timeSplitCard(null)}
      ${tabVerdictHtml(fbVerdict)}
      <div class="stat-row speech-stat-row">
        <div class="stat-card"><small>전체 말 속도</small><strong class="pace-word">${escapeHtml(fbPace.short)}</strong><p class="note" style="margin-top:4px">${escapeHtml(fbPace.detail)}</p></div>
        <div class="stat-card"><small>가장 빨랐던 구간</small><strong class="num">${fastestRatio.toFixed(1)}</strong><span class="unit">배</span><p class="note" style="margin-top:4px">평소 대비 · ${escapeHtml(String(st.maxSeg))}</p></div>
        <div class="stat-card"><small>빠르게 말한 구간</small><strong class="num">${fastRows.length}</strong><span class="unit">개</span><p class="note" style="margin-top:4px">평소보다 15% 이상 빨랐어요</p></div>
      </div>
      <div class="card">
        <h3 class="section-title">구간별 말 속도<span class="soft">내 평소 속도와 비교해요</span></h3>
        <div class="pace-rows">
          <span class="pace-base" style="left:calc(122px + (100% - 266px) * ${ratio.toFixed(3)})"><em>내 평소 속도</em></span>
          ${rows.map(r => `
          <div class="pace-row ${r[3] ? 'fast' : ''}" title="분석값 ${r[2]}자/분">
            <span class="nm">${escapeHtml(String(r[0]))}</span>
            <div class="fill-bar"><i class="${r[3] ? 'red' : ''}" data-w="${(r[2] / MAX * 100).toFixed(1)}%"></i></div>
            <span class="vl">${paceRatioText(r[2], st.avg)}</span>
          </div>`).join('')}
        </div>
        <p class="note" style="margin-top:14px">${note}</p>
      </div>
      <div id="dlvAud"></div>
    </div>
`;
}

/**
 * 「말하기」 — 음성 습관과 청중 반응을 한 탭으로 합친다.
 *
 * 둘은 같은 질문의 앞뒤다: 어떻게 말했나(속도·시간·말버릇) / 그래서 어떻게
 * 들렸나(객석 반응). 탭을 나눠 두면 「청중 반응」은 이름만 봐서는 무슨 화면인지
 * 알 수 없어 아무도 안 열었다 — 일곱 개 중 하나로 묻히던 자리다.
 *
 * display:contents 로 두 host 를 투명하게 만든다. #rbody 는 격자라, 감싸는
 * div 가 격자 칸을 차지해 버리면 안쪽 카드들이 배치를 못 탄다.
 */
function rDelivery() {
  const body = $('#rbody');
  rPace(body);
  /* 청중석은 시간·속도 해석 뒤의 자리(#dlvAud)에 들어간다.
     먼저 내 발표 사실을 읽고, 그다음 객석 반응을 보는 순서다. */
  const slot = $('#dlvAud');
  if (slot) rAudience(slot);
}

/* 탭 6 — 연습 도구.
   안쪽 세그먼트 메뉴를 없애고 세 도구를 한 번에 세로로 편다. 탭 안에 탭이 있어서
   몇 개가 있는지 모르고 지나가는 사람이 많았다.
   도구마다 host 를 따로 주는 이유: 셋이 다 같은 #toolBody 에 쓰면 서로 지웠다.

   순서는 발표 직전에 손이 가는 차례다 (2026-08-07 지시). 그림 한 장 → 그대로
   말할 문장 → 질문 대비. 「발표 구성」은 지금 당장 쓰는 게 아니라 다음 연습에서
   고칠 것이라, 성격이 달라서 2026-08-12 부터 상위 탭(탭 7)으로 뺐다.

   sub 는 도구마다 꼬리에 달려 있던 설명을 제목 밑으로 올린 것이다 — 무엇에 쓰는
   물건인지 다 읽고 나서야 알려 주면 늦다 (토스 Predictable hint). */
const TOOL_SECTIONS = [
  { label: '발표 직전 챙길 개념도', sub: '이 한 장으로 전체 구조를 훑어요', id: 'toolMap', render: (host) => tMap(host) },
  { label: '펀치라인', sub: '이 문장은 그대로 말해도 좋아요', id: 'toolPunch', render: (host) => tPunch(host) },
  { label: '용어 카드', sub: '질문이 올 개념과 답하는 순서예요', id: 'toolTerms', render: (host) => tTerms(host) },
];

function rTools() {
  $('#rbody').innerHTML = TOOL_SECTIONS.map(s => `
    <section class="tool-sec">
      <h2 class="section-title tool-sec-title">${s.label}</h2>
      <p class="tool-sec-sub">${s.sub}</p>
      <div id="${s.id}"></div>
    </section>`).join('');
  TOOL_SECTIONS.forEach(s => {
    const host = $(`#${s.id}`);
    if (host) s.render(host);
  });
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
/** judgeTree() 의 slide 필드는 개념 그래프·판정 탭이 쓰는 'S03' 코드다.
 *  F-20(발표 구성) 프롬프트에 'S03' 을 그대로 넘기면 LLM 이 그 표기를
 *  그대로 따라 써서 화면에 "S03" 이 나온다 (2026-08-12 지적) — 여기서만
 *  순수 슬라이드 번호로 벗겨서 보낸다. 다른 화면(개념 그래프 등)의 'S03'
 *  표기는 이 함수 밖이라 그대로 둔다. */
function slideNumFromCode(code) {
  const n = parseInt(String(code || '').replace(/^S/i, ''), 10);
  return Number.isFinite(n) ? n : '';
}

function strategyAnalysis() {
  const meta = reportSessionMeta();
  const tree = judgeTree();
  const sections = (((reportOut() || {}).pace) || {}).sections || [];

  const concepts = tree.slice(0, 14).map(n => ({
    label: n.label,
    slide: slideNumFromCode(n.slide),
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
      slide: (s.slide_nos && s.slide_nos.length) ? Math.min(...s.slide_nos) : '',
      label: s.name || '',
      recommended: fmtMarkSec(s.recommended_sec || 0),
      actual: fmtMarkSec(s.actual_sec || 0),
    }))
    // 실데이터 세션인데 구간 배분이 없으면 비운다. 샘플 수치로 위장하지 않는다.
    : (meta.live ? [] : sampleAlloc);

  // 순서표가 짚을 슬라이드 목록. F-17 이 있으면 실제 사용 시간까지 함께 넘긴다.
  const paceSlides = (((reportOut() || {}).pace) || {}).slides || [];
  /* 샘플 리포트에서는 내 자료의 장 제목을 쓰지 않는다 — 여기가 pipelineOut
     밖이라 reportOut() 이 못 막던 자리다 */
  const upl = reportNf();
  const titles = (upl && upl.slideTitles && upl.slideTitles.length)
    ? upl.slideTitles : (meta.live ? [] : DATA.slideTitles);
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

/* 탭 7 — 발표 구성. 2026-08-12 부터 「연습 도구」 안 넷째 자리에서 상위 탭으로
   뺐다 — 지금 당장 쓰는 세 도구(발표 직전 챙길 개념도·펀치라인·용어 카드)와 성격이
   달라서(다음 연습을 위한 것) 한 탭에 같이 있으면 도구 하나로 오해받았다. */
function rStrategy() {
  $('#rbody').innerHTML = `<p class="tool-sec-sub">다음 연습에서 순서를 이렇게 바꿔 봐요</p><div id="toolStrategy"></div>`;
  tStrategy();
}

function tStrategy(host = $('#toolStrategy')) {
  if (!host) return;
  if (!window.ReportStrategy) {
    host.innerHTML = `
      <div class="card"><p class="note">구성 제안 모듈을 불러오지 못했어요.</p></div>`;
    return;
  }
  window.ReportStrategy.render(host, {
    sessionId: strategySessionKey(),
    analysis: strategyAnalysis(),
    // 실데이터면 버튼 없이 바로 제안 (샘플은 눌러야 — 구경만 해도 LLM 이 돌면 안 된다)
    auto: strategySessionKey() !== 'sample',
  });
}

/* ── 연습 도구의 실데이터 도출 ─────────────────────────────────────────────
   발표 직전 챙길 개념도·펀치라인·용어 카드가 데모 고정값(DATA.*)만 보여주던 것을,
   실데이터 세션에서는 개념 그래프(요약·슬라이드)·판정·예상 질문(F-08)에서
   결정적으로 뽑는다. 재료가 없으면 샘플로 위장하지 않고 빈 상태를 말한다. */

function toolEmptyHtml(what) {
  return `<div class="card">
      <h3 class="section-title">${what} 만들 재료가 아직 없어요</h3>
      <p class="note">한 번 연습하면 올린 자료에서 뽑아 채워드려요.</p>
      <div class="step-actions"><a class="btn btn-primary" href="#/new">연습 시작하기</a></div>
    </div>`;
}

/** 그래프 노드 id → 자료 요약. 용어 정의·펀치라인의 원천이다. */
function graphSummaryById() {
  const out = reportOut();
  const by = {};
  ((out && out.graph && out.graph.nodes) || []).forEach((n) => {
    by[n.id] = String(n.summary || '').trim();
  });
  return by;
}

/** 실전 코칭 질문(F-08). 남아 있으면 용어 카드의 예상 질문·답변 프레임이 된다. */
function liveQuestionsByNode() {
  const by = {};
  ((qa && qa.live && qa.live.questions) || []).forEach((q) => { by[q.node_id] = q; });
  return by;
}

function liveMapNodes() {
  const tree = judgeTree();
  if (!(tree[0] && tree[0].real)) return null;
  const meta = reportSessionMeta();
  const tops = tree.filter((n) => !n.parent).slice(0, 3);
  if (!tops.length) return null;
  // SVG 텍스트에 그대로 박히므로 이스케이프한다 (그래프 라벨은 LLM 산출물이다)
  const nodes = [{ id: 'r', label: escapeHtml(String(meta.title || '내 발표').slice(0, 22)), root: true }];
  tops.forEach((t) => {
    nodes.push({ id: t.id, label: escapeHtml(String(t.label).slice(0, 16)), status: t.status, slide: t.slide });
    tree.filter((c) => c.parent === t.id).slice(0, 2).forEach((c) => {
      nodes.push({ id: c.id, label: escapeHtml(String(c.label).slice(0, 14)), status: c.status, slide: c.slide, p: t.id });
    });
  });
  return nodes;
}

function livePunchlines() {
  const tree = judgeTree();
  if (!(tree[0] && tree[0].real)) return null;
  const qs = ((qa && qa.live && qa.live.questions) || []).filter((q) => q.answer_gist);
  if (qs.length) {
    return qs.slice(0, 3).map((q) => ({
      pos: `${(q.slide_nos && q.slide_nos[0]) || 1}번 슬라이드 · ${q.label}`,
      main: q.answer_gist,
      why: '예상 질문의 모범답이에요. 발표에서 먼저 말해 두면 이 질문이 덜 나와요.',
    }));
  }
  const sumBy = graphSummaryById();
  const picked = tree.filter((n) => sumBy[n.id]).slice(0, 3);
  return picked.length ? picked.map((n) => ({
    pos: `${slideNumber(n.slide)}번 슬라이드 · ${n.label}`,
    main: sumBy[n.id],
    why: '자료에서 가장 힘을 실은 개념이에요. 이 한 문장이면 충분해요.',
  })) : null;
}

function liveTerms() {
  const tree = judgeTree();
  if (!(tree[0] && tree[0].real)) return null;
  const sumBy = graphSummaryById();
  const qBy = liveQuestionsByNode();
  const picked = tree.filter((n) => sumBy[n.id]).slice(0, 4);
  return picked.length ? picked.map((n) => {
    const q = qBy[n.id];
    return {
      term: n.label, status: n.status, slide: n.slide, def: sumBy[n.id],
      q: (q && q.question) || `${n.label}, 이 발표에 왜 필요했나요?`,
      frame: (q && q.answer_gist) || `① ${slideNumber(n.slide)}번 슬라이드의 정의 → ② 근거 → ③ 내 주장과 잇기`,
    };
  }) : null;
}

/* ── 개념 지도 판형 ────────────────────────────────────────────────
   좌표를 이름으로 묶어 둔다. 흩어진 매직 넘버로 두면 한 줄을 내릴 때마다
   연결선 세 곳을 손으로 맞춰야 하고, 그 셋 중 하나는 꼭 빠진다. */
const MAP_W = 880, MAP_H = 304;
const MAP_ROW = {
  root: { y: 14, h: 42, min: 184, max: 260 },
  l1: { y: 124, h: 60, min: 154, max: 216 },
  l2: { y: 226, h: 60, min: 112, max: 164 },
};

/** 상자 폭에 안 들어가는 이름은 …로 줄인다. SVG text 는 줄바꿈이 없어서
 *  그냥 두면 「Temperature Parameter」가 상자를 뚫고 옆 노드를 덮는다.
 *  한글은 글자당 약 1em, 라틴·숫자는 약 0.56em 으로 잡는다. */
function fitSvgLabel(text, maxPx, fontPx) {
  const adv = ch => (/[ㄱ-힝]/.test(ch) ? 1 : 0.56) * fontPx;
  const s = String(text || '');
  let used = 0;
  for (let i = 0; i < s.length; i++) {
    used += adv(s[i]);
    if (used > maxPx) return s.slice(0, Math.max(1, i - 1)) + '…';
  }
  return s;
}

function mapSvgString() {
  // 이 SVG는 파일로도 내려받으므로(:root 없음) CSS 토큰 대신 리터럴을 쓴다.
  // 노드 면과 외곽선은 중립으로 통일한다. 상태색은 작은 점과 보조 문구만 맡는다.
  // 면·선·글자를 모두 상태색으로 칠하면 개요보다 AI 생성 다이어그램처럼 보인다.
  const NODE_FILL = '#FFFFFF';
  const NODE_LINE = '#D8E2DD';
  const ACCENT = { ok: '#0A8F68', mid: '#A16207', no: '#C2413A', ct: '#526B61', om: '#6B7684' };
  // 실데이터 세션이면 개념 그래프·판정에서 만든 노드, 아니면 샘플.
  const all = liveMapNodes() || DATA.mapNodes;
  const nodes = all.filter(n => n.root || !mapWeakOnly || n.status !== 'ok');
  // 같은 계층은 최소 폭과 높이를 맞추되 긴 제목만 자연스럽게 늘린다.
  // 모두 내용 폭으로 만들면 트리가 들쭉날쭉하고, 모두 같은 폭이면 짧은 제목이 헐겁다.
  const POS = {};
  const rootNode = all.find(n => n.root);
  const textWidth = (value, px = 13) => Array.from(String(value || '')).reduce(
    (sum, ch) => sum + (/[^\u0000-\u00ff]/.test(ch) ? px : px * .58), 0);
  const nodeWidth = (n, level) => {
    if (n.root) return Math.max(184, Math.min(260, Math.ceil(textWidth(n.label, 14) + 48)));
    const min = level === 1 ? 154 : 112;
    const max = level === 1 ? 216 : 164;
    const meta = `${STATUS[n.status]} · ${slideNumber(n.slide)}번`;
    return Math.max(min, Math.min(max, Math.ceil(Math.max(textWidth(n.label, 13.5), textWidth(meta, 11)) + 38)));
  };
  if (rootNode) POS[rootNode.id] = [440, 30, nodeWidth(rootNode, 0)];
  const row = (list, y, level) => {
    if (!list.length) return;
    const gap = level === 1 ? 32 : 20;
    const widths = list.map(n => nodeWidth(n, level));
    const total = widths.reduce((s, w) => s + w, 0) + gap * (list.length - 1);
    let cursor = (880 - total) / 2;
    list.forEach((n, i) => {
      POS[n.id] = [Math.round(cursor + widths[i] / 2), y, widths[i]];
      cursor += widths[i] + gap;
    });
  };
  row(all.filter(n => !n.root && !n.p), 124, 1);
  row(all.filter(n => n.p), 226, 2);
  const has = id => nodes.some(n => n.id === id);
  let links = '';
  all.filter(n => !n.root).forEach(n => {
    const pid = n.p || (rootNode && rootNode.id);
    if (!POS[pid] || !POS[n.id]) return;
    if (!has(n.id) || !has(pid)) return;
    const [x1, y1] = POS[pid], [x2, y2] = POS[n.id];
    const parent = all.find(x => x.id === pid);
    const fromY = y1 + (parent && parent.root ? 36 : 52);
    const toY = y2 - 8;
    const midY = Math.round((fromY + toY) / 2);
    links += `<path d="M${x1} ${fromY} V${midY} H${x2} V${toY}" fill="none" stroke="#BDD0C6" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>`;
  });
  const boxes = nodes.map(n => {
    const [x, y, w] = POS[n.id];
    if (n.root) return `<g>
      <rect x="${x - w / 2}" y="${y - 6}" width="${w}" height="42" rx="11" fill="url(#mapRoot)"/>
      <text x="${x}" y="${y + 20}" text-anchor="middle" font-size="14.5" font-weight="750" fill="#fff" font-family="Pretendard,sans-serif">${n.label}</text></g>`;
    const meta = `${STATUS[n.status]} · ${slideNumber(n.slide)}번`;
    const metaW = Math.ceil(textWidth(meta, 11));
    return `<g>
      <rect x="${x - w / 2}" y="${y - 8}" width="${w}" height="60" rx="11" fill="${NODE_FILL}" stroke="${NODE_LINE}" stroke-width="1.25"/>
      <text x="${x}" y="${y + 14}" text-anchor="middle" font-size="13.5" font-weight="700" fill="#191F28" font-family="Pretendard,sans-serif">${n.label}</text>
      <circle cx="${x - metaW / 2 - 7}" cy="${y + 34}" r="2.6" fill="${ACCENT[n.status]}"/>
      <text x="${x + 4}" y="${y + 37}" text-anchor="middle" font-size="11" font-weight="650" fill="${ACCENT[n.status]}" font-family="Pretendard,sans-serif">${meta}</text></g>`;
  }).join('');
  return `<svg viewBox="0 0 880 304" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="발표 직전 챙길 개념도">
    <defs>
      <linearGradient id="mapRoot" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#064E3B"/><stop offset="1" stop-color="#0A6B50"/></linearGradient>
    </defs>
    <rect width="880" height="304" fill="#FBFCFB"/>${links}${boxes}</svg>`;
}

function tMap(host = $('#toolMap')) {
  if (!host) return;
  if (isLiveReportSession() && !liveMapNodes()) {
    // 도구 이름은 「발표 직전 챙길 개념도」 하나다. 여기만 다르게 부르면
    // 같은 화면에서 이름이 둘이 된다
    host.innerHTML = toolEmptyHtml('발표 직전 챙길 개념도를');
    return;
  }
  host.innerHTML = `
    <div class="map-tools">
      <button type="button" class="btn btn-primary btn-sm" id="weakOnly" aria-pressed="${mapWeakOnly}">챙길 개념만 보기</button>
      <button class="btn btn-secondary btn-sm" id="dl">이미지로 저장</button>
    </div>
    <div class="map-box">${mapSvgString()}</div>
    <p class="note" style="margin-top:10px">챙길 개념만 보기</p>`;
  $('#weakOnly', host).addEventListener('click', () => { mapWeakOnly = !mapWeakOnly; tMap(host); });
  $('#dl', host).addEventListener('click', () => {
    const blob = new Blob([mapSvgString()], { type: 'image/svg+xml' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${String(reportSessionMeta().title || 'IMU2CLIP').replace(/\s+/g, '_').slice(0, 40)}_발표개요.svg`;
    a.click(); URL.revokeObjectURL(a.href);
  });
}

function tPunch(host = $('#toolPunch')) {
  if (!host) return;
  const live = isLiveReportSession();
  const list = live ? livePunchlines() : DATA.punchlines;
  if (live && (!list || !list.length)) {
    host.innerHTML = toolEmptyHtml('펀치라인을');
    return;
  }
  host.innerHTML = `
    ${list.map(p => `
    <div class="card punch-card">
      <p class="phrase">“${escapeHtml(p.main)}”</p>
      <p class="pos">${escapeHtml([p.time, p.pos].filter(Boolean).join(' · '))}</p>
      <p class="why">${escapeHtml(p.why)}</p>
    </div>`).join('')}
    <p class="note" style="margin-top:10px">${live
      ? '자료의 핵심 문장과 예상 질문의 모범답에서 뽑았어요.'
      : '실제로 한 말의 말투를 살려서 다듬었어요.'}</p>`;
}

function tTerms(host = $('#toolTerms')) {
  if (!host) return;
  const live = isLiveReportSession();
  const list = live ? liveTerms() : DATA.terms;
  if (live && (!list || !list.length)) {
    host.innerHTML = toolEmptyHtml('용어 카드를');
    return;
  }
  host.innerHTML = `
    ${list.map(t => `
    <div class="card">
      <div class="term-top"><h3>${escapeHtml(t.term)}</h3>${chip(t.status, true)}<span class="sl">근거: ${slideNumber(t.slide)}번 슬라이드</span></div>
      <p class="term-def">${escapeHtml(t.def)}</p>
      <p class="term-q"><b>이런 질문이 와요</b> — ${escapeHtml(t.q)}</p>
      <p class="term-f"><b>이 순서로 답해요</b> — ${escapeHtml(t.frame)}</p>
    </div>`).join('')}
    <p class="note" style="margin-top:10px">정의는 올린 자료에 있는 말로만 만들어요.</p>`;
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
  if (qaLiveActive() || qaBuildFailed) return false;
  // 시연 모드: 실전 질문 생성 없이 DATA.qaBeats 목 코칭으로 간다.
  if (isShowcaseDemo()) {
    qa.liveNotice = '';
    return false;
  }
  // 생성이 이미 돌고 있으면 "준비 중" 이 맞다. false 를 돌리면 renderQa 가
  // 데모 질문을 띄우고, 몇 초 뒤 생성이 끝나는 순간 그 대화가 통째로
  // 갈아치워진다 — 화면을 벗어났다 돌아온 경우가 정확히 이 경로였다.
  if (qaBuilding) return true;

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
  qaBuildStartedAt = Date.now();
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
    // 「기다리지 않고 데모 질문으로 진행」을 눌렀으면 늦게 도착한 결과를 버린다.
    // 여기서 안 버리면 데모 질문에 답하던 대화가 통째로 갈아치워진다.
    if (qaBuildFailed) return;
    const questions = (doc && doc.questions) || [];
    if (questions.length) {
      // 어느 자료로 만든 질문인지 같이 새긴다 — 자료가 바뀌면 낡은 것이 된다.
      qa.live = newLiveState(FLAT_QA_SESSION_ID, questions, qaDocKey());
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

/* ══ 질문 준비 중 화면 ═════════════════════════════════════════
   10초 동안 굵은 글씨 한 줄과 흐르는 막대만 있었다. 화면이 비어서가 아니라
   **아무것도 안 알려줘서** 허전했다 — 무엇을 고르는 중인지가 없었다.

   채울 것은 지어낸 연출이 아니라 지금 실제로 후보에 올라 있는 개념이다.
   F-08 은 이 F-11 판정을 그대로 받아 고르므로, 여기 뜨는 이름이 곧 잠시 뒤
   질문이 될 자리다. 판정이 없으면(데모 질문 경로·생성 중 새로고침)
   후보 블록을 아예 안 그린다 — 없는 걸 지어내지 않는다(§4). */
const QA_BUILD_VERDICT_WORD = { contradiction: '자료와 다르게 말했어요', missing: '한 번도 안 나왔어요' };
const QA_BUILD_VERDICT_CLS = { contradiction: 'st-ct', missing: 'st-no' };
/** 화면에 세울 후보 수. 넘는 건 「외 N개」로 접는다 — 목록이 카드를 넘기면 안 된다 */
const QA_BUILD_POOL_MAX = 4;
/** 이 초를 넘으면 문구를 바꾼다. 「10초쯤」이라 해 놓고 침묵하지 않는다 */
const QA_BUILD_OVERRUN_SEC = 25;

/** 질문이 나올 자리 — 안 나온 개념과 자료와 어긋난 개념을 무게순으로 */
function qaBuildCandidates() {
  const out = nf && nf.pipelineOut;
  const al = out && out.alignment;
  const graph = out && out.graph;
  if (!al || !graph) return [];
  const labelOf = {};
  (graph.nodes || []).forEach((n) => { labelOf[n.id] = n.label || ''; });
  // 모순이 먼저다. 안 한 말보다 틀린 말이 질문으로 더 아프다
  const rank = { contradiction: 0, missing: 1 };
  return (al.items || [])
    .filter((i) => i.verdict === 'contradiction' || i.verdict === 'missing')
    .sort((a, b) => (rank[a.verdict] - rank[b.verdict])
      || ((b.doc_weight || 0) - (a.doc_weight || 0)))
    .map((i) => ({ label: labelOf[i.node_id] || '', verdict: i.verdict }))
    .filter((c) => c.label);
}

/**
 * 「지금까지 아는 것」 — 후보 목록이 못 뜰 때 화면이 통째로 비는 걸 메운다.
 *
 * 정합 판정이 없으면(데모 질문 경로·생성 중 새로고침) 위 후보 블록이 안 그려지고,
 * 그러면 굵은 글씨 한 줄과 막대만 남아 10초를 세운다. 그렇다고 없는 후보를
 * 지어낼 수는 없으니, 이미 손에 쥔 실측 숫자를 대신 보여준다 —
 * 값이 없는 항목은 아예 빼서 0 을 늘어놓지 않는다.
 */
function qaBuildFactsHtml() {
  const out = (nf && nf.pipelineOut) || {};
  const facts = [
    ['슬라이드', (out.concepts && (out.concepts.slides || []).length)
      || (nf && nf.slideDocMeta && nf.slideDocMeta.total_slides) || 0, '장'],
    ['찾은 개념', (out.graph && (out.graph.nodes || []).length) || 0, '개'],
    ['옮긴 말', (out.transcript && (out.transcript.words || []).length) || 0, '단어'],
  ].filter(([, n]) => n > 0);
  if (!facts.length) return '';
  return `<div class="qb-facts">${facts.map(([k, n, unit]) => `
    <div><b class="num" data-count="${n}">${n}</b><span>${k} ${unit}</span></div>`).join('')}</div>`;
}

let qaBuildTimer = null;

/** 경과 초. 남은 시간을 지어내지 않고 지난 시간만 정직하게 센다 */
function paintQaBuildElapsed() {
  const el = $('#qbElapsed');
  if (!el) { clearInterval(qaBuildTimer); qaBuildTimer = null; return; }
  const sec = Math.max(0, Math.round((Date.now() - (qaBuildStartedAt || Date.now())) / 1000));
  el.textContent = sec >= QA_BUILD_OVERRUN_SEC
    ? `${sec}초 지났어요 — 예상보다 오래 걸리고 있어요`
    : `${sec}초 지났어요`;
}

function renderQaBuilding() {
  app.className = 'narrow';
  const pool = qaBuildCandidates();
  const shown = pool.slice(0, QA_BUILD_POOL_MAX);
  const rest = pool.length - shown.length;
  app.innerHTML = `
    <div class="coach-nav"><a href="#/">← 저장하고 나가기</a><span>질문 준비 중</span></div>
    <div class="card qa-building" role="status" aria-live="polite">
      <b>내 발표에서 예상 질문을 만들고 있어요</b>
      <p class="note">개념 그래프와 실제 발화를 대조해 치명적인 것부터 골라요. 10초쯤 걸려요.</p>
      <div class="qb-bar"><i></i></div>
      <p class="qb-elapsed" id="qbElapsed">0초 지났어요</p>
      ${qaBuildFactsHtml()}
      ${qaBuildGraphHtml()}
      ${shown.length ? `
      <div class="qb-pool">
        <p class="qb-pool-head">여기서 고르고 있어요<span>${pool.length}개 후보</span></p>
        <ul>${shown.map((c) => `
          <li>
            <b>${escapeHtml(c.label)}</b>
            <span class="chip chip-sm ${QA_BUILD_VERDICT_CLS[c.verdict]}">${QA_BUILD_VERDICT_WORD[c.verdict]}</span>
          </li>`).join('')}</ul>
        ${rest > 0 ? `<p class="qb-pool-more">외 ${rest}개를 더 보고 있어요</p>` : ''}
      </div>` : ''}
      <div class="step-actions qb-actions">
        <button class="btn btn-text" id="qbSkip" type="button">기다리지 않고 데모 질문으로 진행하기</button>
      </div>
    </div>`;
  clearInterval(qaBuildTimer);
  paintQaBuildElapsed();
  qaBuildTimer = setInterval(paintQaBuildElapsed, 1000);
  $$('.qb-facts .num[data-count]').forEach((el) => countUp(el, Number(el.dataset.count) || 0, 600));
  // 개념 지도. 이 화면이 「개념 그래프와 실제 발화를 대조한다」고 말하는 자리라
  // 그 그래프를 여기서 보여주는 게 맞다 (2026-08-10 지시).
  if (typeof window.mountQaBuildGraph === 'function') window.mountQaBuildGraph();
  staggerIn($$('.qa-building > *'));
  const skip = $('#qbSkip');
  if (skip) skip.addEventListener('click', () => {
    // 화면을 떠나면 시계도 멈춘다. 안 멈추면 다음 화면에서 1초마다 죽은
    // 노드를 찾는 타이머가 남는다
    clearInterval(qaBuildTimer); qaBuildTimer = null;
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
/* 생성을 시작한 시각. 경과 초를 화면에 그대로 보여 주려고 둔다.
 * qaBuilding 과 같이 sessionStorage 밖이다 — 새로고침하면 생성도 새로 시작한다. */
let qaBuildStartedAt = 0;
/* 이번 코칭에서 생성이 이미 실패했는지 — 무한 재시도 루프 방지. */
let qaBuildFailed = false;

let qa = loadSession('qa-flow') || {};
function resetQa() {
  qa = {
    aud: '교수님', started: false, ended: false,
    mode: (qa && qa.mode) || '10',
    bi: 0, sub: 'answer', hint: 0,
    turns: [],
    concepts: { lossav: 'wait', timing: 'wait', rules: 'wait' },
    lost: [],
    combo: 0, comboMax: 0, awarded: false, award: null,
    liveNotice: '',
  };
  qaBuildFailed = false;
  // 질문 생성 모듈 폴링 카운터도 새 코칭에서 다시 센다 — 안 그러면 한 번
  // 소진된 뒤로는 새 코칭에서도 재시도 없이 곧장 실패로 떨어진다.
  qaBridgeTries = 0;
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
  if (qa.live.busy) {
    // 판정을 기다리다 새로고침한 것이다. 답변 말풍선(qa.turns)은 전송 즉시
    // 저장되지만 상태(L.turns·priorAnswers)는 응답 후에만 갱신되므로, 그대로
    // 두면 화면에는 내 답이 있는데 판정에는 없는 답이 된다. 말풍선을 걷어
    // 입력창 초안으로 되살린다 — 다시 보내기만 하면 된다.
    while (qa.turns.length && qa.turns[qa.turns.length - 1].who === 'me') {
      const popped = qa.turns.pop();
      qa.live.pendingAnswer = String(popped.text || '')
        .replace(/&quot;/g, '"').replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>').replace(/&amp;/g, '&');
    }
    saveSession('qa-flow', qa);
  }
  qa.live.busy = false;
}
let qaTimerId = null;

/* ── 게임 레이어: 설득력 XP · 연속 방어 · 복습 (localStorage, 다크패턴 없이 정직한 상태값) ── */
const GAME_KEY = 'cheokcheok:game';
function loadGame() { try { return JSON.parse(localStorage.getItem(GAME_KEY)) || defaultGame(); } catch (_) { return defaultGame(); } }
function saveGame(g) { try { localStorage.setItem(GAME_KEY, JSON.stringify(g)); } catch (_) { /* privacy mode */ } }
function isoDay(d) { return d.toISOString().slice(0, 10); }
function defaultGame() {
  /* 처음 온 사람에게는 기록이 없다. 예전엔 xp 80 에 어제·그저께 연습한 것으로
     날짜 두 개를 박아 둬서, 한 번도 안 써 본 사람 화면에 「2일 연속 연습 ·
     레벨 1」이 떴다. 없는 기록을 지어내면 그 화면의 다른 숫자도 못 믿는다
     (CLAUDE.md 4 · 04_screens.md 「홈 첫 화면」과 같은 이유). */
  return { xp: 0, days: [] };
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
  const L = { lossav: '손실 회피', timing: '타이밍 실패', rules: '사전 매도 규칙' };
  const items = [];
  (qa.lost || []).forEach(c => items.push({ label: L[c], when: '지금 복습', due: true }));
  ['lossav', 'timing'].forEach((c, i) => {
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
  ['lossav', 'timing', 'rules'].forEach(c => { const s = qa.concepts[c]; if (s === 'won') base += 20; else if (s === 'review') base += 30; });
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
const CONCEPT_LABELS = { lossav: '손실 회피', timing: '타이밍 실패', rules: '사전 규칙' };
const CONCEPT_FULL = { lossav: '손실 회피', timing: '타이밍 실패', rules: '사전 매도 규칙' };

/* ── QA 시간 모드: 치명도 순으로 질문 범위를 채운다 ──
 * 키는 서버 계약의 track 과 같은 문자열이다. */
const QA_MODES = {
  '1':  { min: 1,  short: '1분 · 핵심만',   desc: '가장 치명적인 개념 하나만 빠르게 확인해요. 복습은 생략해요.',
          scopeLabel: '가장 치명적인 개념 하나', count: 1, demoConcepts: ['lossav'], review: false },
  '5':  { min: 5,  short: '5분 · 핵심+α',  desc: '핵심 개념에 함정 검증과 시차 복습까지 붙여 제대로 코칭해요.',
          scopeLabel: '핵심 개념 + 놓친 개념', count: 3, demoConcepts: ['lossav', 'timing'], review: true },
  '10': { min: 10, short: '10분 · 전체 커버', desc: '아쉬운 개념 전부에, 자료와 모순된 설명까지 대조해요.',
          scopeLabel: '아쉬운 개념 전부 + 모순 대조', count: 7, demoConcepts: ['lossav', 'timing', 'rules'], review: true },
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
/* 실전 트래커(qa_live.js QUEST_WORD)와 같은 낱말을 쓴다 — 한 화면에서 같은 일이 두 이름이면
   무엇이 끝난 건지 사람이 못 맞춘다 */
const TRACK_WORD = { wait: '아직이에요', current: '지금 답하고 있어요', won: '설득했어요', review: '한 번 더 봐요', lost: '다시 설명해요' };
function trackerHTML() {
  const sc = qaScope();
  const order = sc.demoConcepts;
  const won = order.filter(c => qa.concepts[c] === 'won' || qa.concepts[c] === 'review').length;
  const lost = qa.lost.length;
  const total = qaBeatList().length;
  const prog = Math.min(100, Math.round(qa.bi / Math.max(1, total - 1) * 100));
  return `<div class="persuade-track" id="ptrack" style="--p:${prog}%">
    <div class="pt-head"><span>${qa.aud} 설득하기 · ${sc.short}</span>
      <span class="pt-right">${qa.combo >= 2 ? `<span class="combo-live">🔥 ${qa.combo}연속 방어</span>` : ''}<b>${won}<i>/${order.length}</i>${lost ? ` · <em>${lost}개는 다시 설명해요</em>` : ''}</b></span></div>
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
  /* 질문 하나가 닫히는 자리 (qa_live.js finishLiveQuestion).
     표식·총평·모범답을 **아바타 없는 카드 한 장**으로 묶는다. 아바타가 없다는 것
     자체가 «이건 상대의 말이 아니라 정리다» 라는 신호다 — 예전엔 모범답이 상대
     아바타를 달고 맨 끝에 서서 대화가 다시 열린 것처럼 보였다 (2026-08-10 사용자). */
  if (it.who === 'sys' && it.kind === 'done') {
    const cls = { good: 'st-ok', partial: 'st-mid', wrong: 'st-no', unknown: 'st-om', skipped: 'st-om' }[it.outcome] || 'st-om';
    const lost = it.flag === 'lost';
    const foot = it.idx < it.total
      ? `질문 ${it.idx}/${it.total} 마무리 — 다음 질문으로 이어가요`
      : `질문 ${it.idx}/${it.total} 마무리 — 마지막 질문이었어요`;
    return `<div class="qa-done${lost ? ' is-lost' : ''}">
      <div class="qd-head">
        <i aria-hidden="true">${lost ? '✕' : '✓'}</i>
        <b>${it.label}</b>
        <span class="chip chip-sm ${cls}">${it.word}</span>
      </div>
      ${it.gist ? `<div class="qd-sec"><h4>이렇게 답하면 좋았어요</h4><p>${it.gist}</p></div>` : ''}
      ${it.summary ? `<div class="qd-sec"><h4>총평에 적었어요</h4><p>${escapeHtml(it.summary)}</p></div>` : ''}
      <p class="qd-foot">${foot}</p>
    </div>`;
  }
  /* 질문을 다 마친 자리. 결과 화면으로 바로 갈아치우지 않고 여기 서서
     사용자가 「결과 확인하기」를 누를 때까지 기다린다 (qa_live.js enterLiveFinale). */
  if (it.who === 'sys' && it.kind === 'finale') {
    return `<div class="qa-finale"><b>${it.text}</b><p>주고받은 내용을 위로 올려 다시 볼 수 있어요.</p></div>`;
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
  // total 폴백 3: 판정 전 사다리 길이. 옛 세션 턴에는 total 이 없다.
  // auto: 라운드가 올라 코치가 알아서 연 힌트. 안 눌렀는데 열렸으니 왜 열렸는지 말한다.
  if (it.kind === 'hint') {
    /* 장 번호만 부르는 힌트는 힌트가 아니다 — "27, 28장을 떠올려 보세요" 는 그 장에
       뭐가 있는지 아는 사람에게만 힌트다. 그래서 부르는 장을 조그맣게 같이 띄운다.
       slides 는 openNextHint 가 진짜 렌더가 있는 장만 골라 실어 준다. */
    const slides = (it.slides || []).length ? `<div class="hint-slides">${it.slides.map((no) => `
      <figure><img data-thumb-page="${no}" src="${deckImageSrc(no)}" alt="${no}번 슬라이드" loading="lazy"><figcaption>${no}번</figcaption></figure>`).join('')}</div>` : '';
    return `<div class="msg ai hint">${av}<div class="msg-bubble"><b>힌트 ${it.level}/${it.total || 3}${it.auto ? ' · 좁혀 물으면서 같이 열었어요' : ''}</b>${it.text}${slides}</div></div>`;
  }
  if (it.kind === 'react') {
    /* 「모르겠어요」에 온 응답은 판정이 아니다 (f09_judge.coach_stuck 이 점수를
       안 매기고 verdict 자리에 폴백을 넣는다). 판정 칩으로 그리면 솔직하게
       모르겠다고 누른 사람이 **틀린 답과 똑같은 빨간 칩**을 받는다 — 그리고
       다음에 무슨 일이 일어나는지는 어디에도 안 적혀 있었다 (2026-08-10 사용자).
       칩을 빼고, 코치가 지금 무엇을 하려는지를 그 자리에 적는다. */
    if (it.coach) {
      const line = { explain: '답을 같이 풀어 볼게요', clarify: '질문을 다시 풀어 드릴게요' }[it.coach]
        || '더 쉬운 걸로 바꿔 물을게요';
      return `<div class="msg ai react is-coach">${av}<div class="msg-bubble">
        <span class="msg-meta">${line}</span>
        <p>${it.text}</p></div></div>`;
    }
    // 맵 밖 값이면 칩에 문자 그대로 "undefined" 가 그려진다 — 보류 쪽으로 떨어뜨린다.
    const lab = { full: '제대로 설명했어요', partial: '절반쯤', none: '아직' }[it.verdict] || '아직';
    const cls = { full: 'st-ok', partial: 'st-mid', none: 'st-no' }[it.verdict] || 'st-om';
    /* 되묻기가 길어질 때 버티게 하는 것은 격려가 아니라 **오르는 숫자**다.
       62 → 78 은 우리가 이미 재고 있는 값이라 지어낸 점수가 아니다 (§14 숫자는 신성).
       첫 답에는 before 가 0이라 델타를 안 붙인다 — 「+62」는 거짓 진전이다. */
    const d = (it.before > 0 && typeof it.score === 'number') ? it.score - it.before : 0;
    const delta = d ? `<em class="msg-delta ${d > 0 ? 'up' : 'dn'}">${d > 0 ? '+' : ''}${d}</em>` : '';
    const meter = it.score ? `<b class="msg-score num">${it.score}</b><small>완성도</small>${delta}` : '';
    return `<div class="msg ai react">${av}<div class="msg-bubble">
      <span class="react-head"><span class="chip chip-sm ${cls}">${lab}</span>${meter}</span>
      <p>${it.text}</p></div></div>`;
  }
  if (it.kind === 'missing') {
    return `<div class="msg ai miss">${av}<div class="msg-bubble">
      <span class="msg-meta">아직 안 나온 것</span>
      <!-- points 가드: 구버전 저장 세션이 이 필드 없이 복원되면 렌더 전체가 죽는다 -->
      <div class="miss-chips">${(it.points || []).map((p) => `<span class="chip chip-sm st-mid">${p}</span>`).join('')}</div>
    </div></div>`;
  }
  if (it.kind === 'gist') {
    /* mid: 되묻기 도중에 펼친 답(절반만 설득한 자리). 아직 이 질문이 안 끝났는데
       "좋았어요" 라고 하면 지나간 일로 읽혀서 다시 말할 차례라는 게 안 보인다. */
    return `<div class="msg ai gist${it.mid ? ' mid' : ''}">${av}<div class="msg-bubble">
      <span class="msg-meta">${it.mid ? '이렇게 말하면 완성이에요' : '이렇게 답하면 좋았어요'}</span>
      <p>${it.text}</p>
    </div></div>`;
  }
  if (it.kind === 'concede') return `<div class="msg ai">${av}<div class="msg-bubble">${it.text}</div></div>`;
  return '';
}

/* 스트림에 새로 쌓인 줄만 append (기존 줄 재애니메이션 방지) */
function growStream() {
  const s = $('#stream'); if (!s) return;
  /* 「듣고 있어요」 표시는 qa.turns 에 없는 임시 줄이다. 스트림 안에 그대로 두면
     children.length 가 turns.length 보다 커져 **아래 루프가 통째로 안 돈다** —
     새 말풍선이 하나도 안 붙는다. 잠깐 떼었다가 맨 끝에 도로 붙인다. */
  const thinking = s.querySelector('#coachThinking');
  if (thinking) thinking.remove();
  for (let k = s.children.length; k < qa.turns.length; k++) {
    const wrap = document.createElement('div');
    wrap.innerHTML = streamRow(qa.turns[k]);
    const node = wrap.firstElementChild;
    if (node) {
      node.classList.add('enter');
      s.appendChild(node);
      if (node.classList.contains('qa-sum')) typeSummary(node);
      // 힌트에 붙은 슬라이드 자리를 원본 PDF 렌더로 채운다 (업로드 세션일 때만 돈다).
      if (node.querySelector('img[data-thumb-page]')) paintDeckThumbs(node);
    }
  }
  if (thinking) s.appendChild(thinking);
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
    if (!qa.concepts) qa.concepts = { lossav: 'wait', timing: 'wait', rules: 'wait' };
    qa.concepts.lossav = 'current';
    presentQuestion(firstBeat);
  }
  // 새로고침 등으로 중간 상태가 저장돼 있으면 안전한 상태로 되돌림
  if (qa.sub === 'speaking' || qa.sub === 'thinking' || qa.sub === 'committed' || qa.sub === 'typing')
    qa.sub = beat().kind === 'trap' ? 'choice' : 'answer';
  saveSession('qa-flow', qa);
  app.innerHTML = `
    <div class="coach-nav"><a href="#/">← 저장하고 나가기</a><span>자동으로 저장하고 있어요</span></div>
    <div class="qa-shell">
      <aside class="qa-context">
    ${qaNoticeHtml()}
    <div class="qa-top">
      <div>
        <h1 class="page-title">${qa.aud} 질문 코칭</h1>
        <p class="page-sub">${DATA.session.title} · 슬라이드를 사이에 두고 실제처럼 주고받아요</p>
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
    el.innerHTML = `<div class="caption"><span class="cap-live">듣는 중</span><p id="capT"></p>${lim ? `<span class="cap-timer" id="capTimer">⏱ ${lim}</span>` : ''}</div>
      <div class="cap-actions"><button class="btn btn-secondary btn-sm" type="button" id="capStop">답변 끝내기</button></div>`;
    // 말을 마쳤으면 끊을 수 있어야 한다. 대본이 다 흐를 때까지 기다리게 하면
    // 사용자는 화면이 멈춘 줄 안다 (2026-08-07 지적).
    $('#capStop').addEventListener('click', qaStopSpeaking);
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
  streamCaption(b.answer, (spoken, early) => {
    commitAnswer(spoken, early);
    qaThink(() => react(b, b.verdict, b.react));
  });
}

function speakInterrupt(b) {
  const words = b.answer.split(' ');
  const cut = Math.max(1, Math.round(words.length * (b.cutAt || 0.6)));
  let i = 0;
  let ended = false;
  // 끼어들기 구간에서도 끊을 수 있어야 한다 — 버튼은 떠 있는데 안 먹으면
  // 눌러 본 사람은 화면이 멈춘 줄 안다.
  const goOn = () => {
    if (ended) return;
    ended = true;
    qaFinishNow = null;
    if (qaTimerId) { clearInterval(qaTimerId); qaTimerId = null; }
    commitAnswer(words.slice(0, Math.max(1, Math.min(i, cut))).join(' ') + ' …', true);
    qaThink(() => {
      pushTurn({ who: 'ai', kind: 'interject', text: b.interject }); growStream();
      qa.sub = 'speaking'; renderLive();
      streamCaption(b.answerAfter, (spoken, early) => {
        commitAnswer(spoken, early);
        qaThink(() => react(b, b.verdict, b.react));
      });
    });
  };
  qaFinishNow = goOn;
  const step = () => {
    const el = $('#capT'); if (!el) return;
    i++; el.textContent = words.slice(0, i).join(' ') + ' …'; scrollDown();
    if (i < cut) { later(step, 120); return; }
    goOn();
  };
  step();
}

/** 지금 말하는 중인 답변을 끊는 함수. 스트리밍이 도는 동안에만 채워져 있다.
 *
 *  예전엔 「말로 답하기」를 누르면 대본이 다 흐를 때까지 끊을 방법이 없었다.
 *  말을 마쳤는데 화면이 계속 떠드는 걸 지켜봐야 했다 (2026-08-07 지적). */
let qaFinishNow = null;

/** 답변을 지금 확정한다. 화면에 나온 데까지가 그가 한 말이다 — 아직 안 나온
 *  대본까지 확정하면 하지도 않은 말을 기록으로 남기게 된다 (CLAUDE.md §4). */
function qaStopSpeaking() {
  if (qa.sub !== 'speaking') return;
  if (qaFinishNow) qaFinishNow();
}

function streamCaption(text, done) {
  const words = text.split(' ');
  let i = 0;
  let ended = false;
  //: early=true 면 사용자가 끊은 것. 그때까지 나온 낱말만 넘긴다.
  const finish = (early) => {
    if (ended) return;
    ended = true;
    qaFinishNow = null;
    if (qaTimerId) { clearInterval(qaTimerId); qaTimerId = null; }
    const spoken = early ? words.slice(0, Math.max(1, i)).join(' ') : text;
    done(spoken, early);
  };
  qaFinishNow = () => finish(true);
  const tick = () => {
    const el = $('#capT'); if (!el) { finish(false); return; }
    i++; el.textContent = words.slice(0, i).join(' '); scrollDown();
    if (i < words.length) later(tick, 95 + Math.min(130, words[i - 1].length * 20));
    else later(() => finish(false), 950); // 침묵 후 자동 제출
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

/* ── 실패/방어 갈림길 (사전 매도 규칙) ── */
function qaDecide(push) {
  const b = beat();
  if (push) {
    qa.sub = 'speaking'; renderLive();
    streamCaption(b.pushAnswer, () => {
      commitAnswer(b.pushAnswer);
      qaThink(() => {
        qa.concepts.rules = 'won';
        qa.combo = (qa.combo || 0) + 1;
        qa.comboMax = Math.max(qa.comboMax || 0, qa.combo);
        pushTurn({ who: 'ai', kind: 'react', verdict: 'full', text: b.onPush });
        pushTurn({ who: 'sys', kind: 'won', text: '사전 매도 규칙 — 끝까지 밀어붙여 설득했어요' });
        growStream(); updateTracker();
        qa.sub = 'ended'; renderLive();
      });
    });
  } else {
    pushTurn({ who: 'me', kind: 'choice', text: '오늘은 여기까지 할게요' });
    growStream();
    qaThink(() => {
      qa.concepts.rules = 'lost'; qa.lost = ['rules'];
      pushTurn({ who: 'ai', kind: 'concede', text: b.onConcede });
      pushTurn({ who: 'sys', kind: 'lost', text: '사전 매도 규칙 — 오늘은 방어하지 못했어요. 리포트에 남겨둘게요' });
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

/** 코칭 기록을 저장한다. @returns {boolean} 저장 성공 여부 — 종료 화면이
 *  "저장됨"이라고 말해도 되는지 이 값으로 정한다 (실패를 성공으로 표시하지 않기). */
function recordQaHistory() {
  if (!window.QaHistory) return false;
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
        // a 는 「내 답변」 칸이다. summary 는 코치의 총평이라 사용자 발화가 아니다 —
        // 실제로 친 답(r.answer)을 싣고, 총평은 note 줄로 따로 남긴다.
        a: r.answer || '',
        verdict: QA_LOG_VERDICT[r.verdict] || 'partial',
        note: r.summary || '',
        turns: r.turns || 0,
        hint: r.hintLevel || 0,
        skipped: r.verdict === 'skipped' || !!r.revealed,
      };
    });
    /* before/after 를 샘플(DATA.session.qa)의 3/5 로 적으면 실전 기록이
       거짓말을 한다 — 질문이 4개면 「4개 중 5개 늘었어요」도 가능했다.
       실기록에서 센다: 질문 후 = 최종적으로 설명해낸 것(full),
       질문 전 = 그중 힌트·재시도 없이 첫 답에 설명한 것. */
    const fullBeats = beats.filter(b => b.verdict === 'full');
    const firstTryFull = fullBeats.filter(b => !b.hint && (!b.turns || b.turns <= 1));
    return window.QaHistory.save(L.sessionId || 'live', {
      live: true,
      aud: qa.aud || '청중',
      mode: qa.mode || 'full',
      turns: beats.length,
      before: firstTryFull.length, after: fullBeats.length, total: beats.length,
      mastered: beats.filter(b => b.verdict === 'full').map(b => b.label),
      weak: beats.filter(b => b.verdict === 'none').map(b => b.label),
      beats,
    });
  }

  // mock 시나리오 경로
  const played = (DATA.qaBeats || []).filter(b => b.kind === 'ask');
  if (!played.length) return false;
  return window.QaHistory.save('investor', {
    live: false,
    aud: qa.aud || '교수님',
    mode: qa.mode || 'full',
    // qa.turns 는 말풍선 배열이다 — 턴 수 필드에 배열을 넣으면 항상 truthy 라
    // 리포트의 숫자 자리가 깨진다. 실제로 답한 질문 수를 센다.
    turns: played.length,
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
  const historySaved = recordQaHistory();
  const tr = DATA.session.qa.trophy;
  const rulesLost = qa.lost.includes('rules');
  const concepts = [
    { label: '격차의 실재', pre: true },
    { label: '과잉 매매', pre: true },
    { label: '거래 비용', pre: true },
    { label: '손실 회피', pre: false },
    { label: '타이밍 실패', pre: false },
  ];
  const aw = qa.award || { earned: 0, level: 1, streak: 1, xp: 0 };
  app.innerHTML = `
    <div class="coach-nav"><a href="#/">← 내 발표로 나가기</a><span>${historySaved ? '코칭 기록 저장됨' : '기록을 저장하지 못했어요 — 화면을 캡처해 두세요'}</span></div>
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
        <p class="cere-sub ${rulesLost ? 'warn' : 'good'}">${rulesLost
          ? '사전 매도 규칙은 오늘 방어하지 못했어요 — 복습으로 다시 만나요'
          : '자료와 어긋났던 종목 선정 결론도 대화로 바로잡았어요'}</p>
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
        <div class="cere-next"><span>다음 목표</span><b>${rulesLost ? '사전 매도 규칙 다시 방어하기' : '상위 그룹 비교표를 한 문장으로 설명하기'}</b></div>
      </div>

      <div class="cere-actions">
        <a class="btn btn-primary" href="${isShowcaseDemo() ? showcaseReportHref() : '#/report'}">상세 리포트 보기</a>
        <a class="btn btn-text" href="#/">홈으로</a>
        <button class="btn btn-text" id="again">질문 코칭 다시 하기</button>
      </div>
    </div>`;
  $('#again').addEventListener('click', () => { resetQa(); qa.started = true; renderQa(); });
  later(() => { const el = $('#cereXp'); if (el) countUp(el, aw.earned, 700); }, 2100);
  window.scrollTo(0, 0);
}

/* ══ 서비스 정보 ══ */
/* 분석 파이프라인 8단계 — 무엇을 하고 무엇으로 하는지 두 가지만 말한다.
   「확정 / 검증 중 / 후보 테스트 / 준비 중」 상태 칩은 뺐다. 개발 진행 상황은
   우리 사정이지 이 화면을 보는 사람이 궁금한 것이 아니고, 표의 절반을 그
   라벨이 먹고 있었다 (토스 절제 규율 — 한 화면의 주인공은 하나). */
const ABOUT_STEPS = [
  ['발표자료를 슬라이드별 텍스트와 구조로 바꿔요', 'Upstage Document Parse'],
  ['녹음을 단어별 시간과 함께 글로 옮기고, 슬라이드 구간으로 나눠요', 'SKT A.X'],
  ['자료에서 핵심 개념을 뽑아 중요한 순서로 엮어요', '메인 LLM'],
  ['개념마다 실제로 설명했는지 근거 발화와 함께 판정해요', '문장 유사도 검색 + KT 믿:음'],
  ['자료와 발표, 앞선 답변을 보고 질문을 만들어 되물어요', '판정 LLM'],
  ['논리가 끊긴 곳을 최대 다섯 곳까지 찾아요', 'LG EXAONE · SKT A.X'],
  ['발표자에게 맞는 다음 방향을 실제 발화를 인용해 제안해요', 'SKT A.X · LG EXAONE'],
  ['발표 판정과 질문 전후의 이해 변화를 하나로 묶어요', '규칙 계산 + 판정 결과'],
];

function aboutStepsHtml() {
  return `<ol class="about-steps">${ABOUT_STEPS.map(([what, tech], i) => `
    <li>
      <i>${i + 1}</i>
      <div><p>${escapeHtml(what)}</p><span>${escapeHtml(tech)}</span></div>
    </li>`).join('')}</ol>`;
}

function renderAbout() {
  app.className = '';
  app.innerHTML = `
    <h1 class="page-title">척척발표가 판단하는 방식</h1>
    <p class="about-lead">무엇을 보고 무엇은 보지 않는지 그대로 적었어요.</p>

    <div class="card about-sec">
      <h2 class="section-title">발표를 이렇게 읽어요</h2>
      <p class="lead note">올린 자료와 녹음이 리포트가 되기까지 여덟 단계를 거쳐요.</p>
      ${aboutStepsHtml()}
    </div>

    <div class="about-side">
    <div class="card about-sec">
      <h2 class="section-title">판단 원칙</h2>
      <ul class="principles">
        <li><b>모든 판정에 실제로 한 말을 붙여요.</b> 어디를 듣고 그렇게 봤는지 같이 보여줘요. 근거 없는 총평은 하지 않아요.</li>
        <li><b>계산으로 되는 건 AI를 쓰지 않아요.</b> 말 속도와 시간 배분은 수식으로 세니, 같은 녹음이면 결과가 늘 같아요.</li>
        <li><b>사람 판단과 열 번에 여덟 번은 맞아야 내보내요.</b> ‘설명 안 함’ 판정에 두는 기준이에요.</li>
      </ul>
    </div>

    <div class="card about-sec">
      <h2 class="section-title">이건 판단하지 않아요</h2>
      <p class="lead note">못 하는 것도 알고 쓰시는 게 맞다고 봐요.</p>
      <ul class="principles">
        <li><b>목소리가 좋은지는 판단하지 않아요.</b> 반복·간투어·긴 침묵처럼 셀 수 있는 것만 세요.</li>
        <li><b>슬라이드 디자인은 보지 않아요.</b> 글과 구조만 읽어요.</li>
      </ul>
    </div>

    <div class="card about-sec">
      <h2 class="section-title">자료와 녹음은 이렇게 다뤄요</h2>
      <ul class="principles">
        <li><b>분석에만 써요.</b> 다른 곳에 넘기지 않아요.</li>
        <li><b>1년 동안 보관한 뒤 지워요.</b> 그동안은 다시 듣고 지난 발표와 견줘 볼 수 있어요.</li>
      </ul>
    </div>
    </div>

    <div class="about-cta">
      <p>읽어 보니 어떠세요? 이 방식으로 한 번 봐 드릴게요.</p>
      <a class="btn btn-primary" href="#/new" data-fresh-practice>새 발표 연습하기</a>
    </div>`;
  wireFreshPracticeButtons(app);
}

/* ── #/replay — 저장해 둔 발표로 이어서 (개발용) ──────────────────────────
   화면을 고쳐 가며 확인하려면 그때마다 자료를 다시 올리고 발표를 처음부터 다시
   말해야 했다. 그게 실제로 반복 테스트를 막고 있었다 (2026-08-08 사용자).

   브리지가 파싱본(`*.slidedoc.json`)과 받아쓰기(`*.transcript.json`)를
   fixtures/raw 에 남기므로, 그 둘로 4단계(분석)부터 바로 시작한다.
   유료 호출은 STT 만 건너뛴다 — 개념·그래프·정합은 그대로 돈다. 그 결과를
   보려고 들어오는 화면이라 거기까지 아끼면 볼 것이 없다.

   어느 화면에도 링크를 걸지 않는다. 부스 방문객이 흘러 들어오면 남의 발표
   기록을 보게 된다 — 주소를 아는 사람만 들어온다. */

async function renderReplay() {
  app.className = 'narrow';
  app.innerHTML = `<main>
    <h1 class="section-title">저장된 발표로 이어서</h1>
    <p class="sub">저장해 둔 자료 파싱본과 받아쓰기로 분석부터 시작해요. 다시 말하지 않아도 되고, 받아쓰기는 다시 결제되지 않아요.</p>
    <div id="replayList" class="stack">불러오고 있어요…</div>
  </main>`;
  const box = $('#replayList');
  let takes = [];
  try {
    const res = await fetch('/api/v1/cached-takes');
    takes = ((await res.json()) || {}).takes || [];
  } catch (err) {
    // 실패를 성공처럼 보이게 두지 않는다 — 빈 목록과 못 불러온 것은 다른 일이다
    box.innerHTML = `<div class="qa-flag lost"><i>✕</i>목록을 못 불러왔어요: ${escapeHtml(String(err.message || err))}</div>`;
    return;
  }
  if (!takes.length) {
    box.innerHTML = '<p class="sub">아직 저장된 발표가 없어요. 자료를 올리고 한 번 말하면 여기에 쌓여요.</p>';
    return;
  }
  box.innerHTML = takes.map((t) => {
    // 슬라이드만 있고 받아쓰기가 없으면 이어갈 수 없다. 왜 못 쓰는지 줄에 남긴다.
    const ready = t.slides && t.transcript;
    const marks = [
      `<span class="chip chip-sm ${t.slides ? 'st-ok' : 'st-no'}">자료 ${t.slides ? '있어요' : '없어요'}</span>`,
      `<span class="chip chip-sm ${t.transcript ? 'st-ok' : 'st-no'}">받아쓰기 ${t.transcript ? '있어요' : '없어요'}</span>`,
      `<span class="chip chip-sm ${t.preview ? 'st-ok' : 'st-om'}">원본 화면 ${t.preview ? '있어요' : '없어요'}</span>`,
    ].join('');
    return `<div class="qa-sum">
      <b class="qs-name">${escapeHtml(t.stem)}</b>
      <p class="qs-text">${marks}</p>
      <button class="btn ${ready ? 'btn-primary' : 'btn-secondary'}" data-replay="${escapeHtml(t.stem)}"
        ${ready ? '' : 'disabled'} type="button">${ready ? '이 발표로 이어서' : '한 번은 말해야 저장돼요'}</button>
    </div>`;
  }).join('');
  box.querySelectorAll('[data-replay]').forEach((btn) => {
    btn.addEventListener('click', () => startReplay(btn.dataset.replay, btn));
  });
}

/**
 * 저장본으로 4단계(분석)부터 시작한다.
 *
 * 슬라이드 복구는 `ensureSlideDoc()` 이 이미 하는 일이다 — 캐시에서 SlideDoc 을
 * 되살리고 원본 미리보기 PDF 까지 메모리에 올린다. PDF 를 같이 올리는 게 중요한데,
 * 그게 없으면 힌트에 붙는 슬라이드가 회색 자리표시자로 떨어진다 (hasRealSlideImage).
 */
async function startReplay(stem, btn) {
  if (btn) { btn.disabled = true; btn.textContent = '불러오는 중이에요…'; }
  resetNf();
  resetQa();
  nf.fileName = stem;               // ensureSlideDoc 이 이 이름으로 캐시를 찾는다
  const doc = await ensureSlideDoc();
  if (!doc) {
    if (btn) { btn.disabled = false; btn.textContent = '이 발표로 이어서'; }
    const box = $('#replayList');
    if (box) box.insertAdjacentHTML('afterbegin',
      `<div class="qa-flag lost"><i>✕</i>'${escapeHtml(stem)}' 의 자료 파싱본을 못 찾았어요</div>`);
    return;
  }
  applySlideDoc(doc, { keepDemoImages: false });
  nf.fileName = doc.file_name || stem;
  nf.gate = 'done';
  nf.step = 3;                      // [nfStep1, nfStep2, nfStep3, nfStep4][3]
  // 녹음 대신 저장본을 태운다. _blob 이 없어도 reuse 가 서버에서 먼저 걸린다.
  ccLastTake = { marks: [], _blob: null, mimeType: '', fileName: stem, reuse: true };
  saveSession('new-flow', nf);
  // 해시가 이미 #/new 면 hashchange 가 안 떠서 화면이 안 바뀐다 — 직접 그린다.
  if (location.hash === '#/new') route();
  else location.hash = '#/new';
}

/* ── 시작 ── */
route();
