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
    delete slim.slideDoc;
    delete slim.transcript;
    delete slim.concepts;
    delete slim._pipelineStarted;
    if (slim.slideDocMeta == null && value.slideDoc) {
      slim.slideDocMeta = {
        file_name: value.slideDoc.file_name,
        total_slides: value.slideDoc.total_slides,
      };
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
      <stop offset="0" stop-color="#3182F6" stop-opacity=".20"/>
      <stop offset="1" stop-color="#3182F6" stop-opacity="0"/>
    </linearGradient></defs>
    <path class="growth-area" d="${area}" fill="url(#growthFill)"/>
    <path class="growth-line" style="--len:${len.toFixed(0)}" d="${line}" fill="none" stroke="var(--blue)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
    ${dots}
    <circle class="growth-dot-last" cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="5.5" fill="var(--blue)" stroke="#fff" stroke-width="2.5"/>
    <text class="growth-val" x="${last[0].toFixed(1)}" y="${(last[1] - 12).toFixed(1)}" text-anchor="middle">${vals[n - 1]}</text>
  </svg>`;
}

/* ══ 라우팅 ══ */
const routes = { '': renderHome, 'new': renderNew, 'report': renderReport, 'qa': renderQa, 'about': renderAbout };

/** 진행 중 세션을 버리고 새 연습 시작 */
function startFreshPractice() {
  resetNf();
  try { sessionStorage.removeItem('cheokcheok:chuckchuck-session'); } catch (_) {}
  if (location.hash === '#/new' || location.hash === '#/new/') {
    route();
  } else {
    location.hash = '#/new';
  }
}

function route() {
  clearTimers();
  unbindRehearsalNav();
  const parts = location.hash.replace(/^#\/?/, '').split('/');
  const key = parts[0];
  // #/new/reset 또는 completed 후 #/new → 초기화
  if (key === 'new' && (parts[1] === 'reset' || nf.completed)) resetNf();
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
  app.className = '';
  const g = DATA.growth.scores;
  const totalUp = g[g.length - 1] - g[0];
  const qaActive = qa.started && !qa.ended;
  const nfActive = !nf.completed && (nf.step > 0 || nf.gate);
  const resume = qaActive
    ? {href:'#/qa', eyebrow:'질문 코칭 진행 중', title:`${qa.aud || '교수님'}${josa(qa.aud || '교수님','과','와')} 하던 질문 코칭을 이어서 할까요?`, sub:'지금까지 주고받은 대화를 이 브라우저에 저장했어요.'}
    : nfActive
      ? {href:'#/new', eyebrow:'발표 연습 진행 중', title:`${NF_STEPS[nf.step]}부터 이어서 할까요?`, sub:`${nf.slide || 1}번 슬라이드와 입력한 발표 정보를 저장했어요.`}
      : null;
  app.innerHTML = `
    <div class="page-head"><div><h1 class="page-title">내 발표</h1><p class="page-sub">발표와 질문 코칭 결과를 이어서 확인해요.</p></div><a class="btn btn-primary btn-sm" href="#/new" data-fresh-practice>새 발표 연습</a></div>
    ${resume ? `<div class="resume-row"><a class="resume-card" href="${resume.href}"><span>${resume.eyebrow}</span><strong>${resume.title}</strong><p>${resume.sub}</p><i>이어하기 →</i></a><a class="btn btn-secondary btn-sm" href="#/new" data-fresh-practice>처음부터 다시</a></div>` : ''}
    <div class="card home-hero">
      <div class="hero-gauge">
        ${ringSvg(DATA.session.score, 128, 11, `<strong class="num" data-count="${DATA.session.score}">0</strong><span>점</span>`)}
        <div class="hg-cap"><b>최근 발표 완성도</b><span class="chip chip-sm chip-up">지난 연습보다 +${DATA.session.score - DATA.session.prevScore}</span></div>
      </div>
      <div class="hero-growth">
        <div class="hg-head"><span>최근 5회 완성도</span><b class="num">${g[0]} → ${g[g.length - 1]}</b></div>
        ${areaChartSvg(g, 360, 132)}
        <div class="hg-foot">
          <div><strong class="num">+${totalUp}</strong><small>5회 성장</small></div>
          <div><strong class="num">4 → 1</strong><small>설명 누락</small></div>
        </div>
      </div>
    </div>
    ${gameStripHtml()}
    <div class="card" style="padding:12px 12px">
      <div style="display:flex;align-items:center;justify-content:space-between;padding:10px 12px 6px">
        <h2 class="section-title" style="margin:0">내 발표</h2>
        <a class="btn btn-tint btn-sm" href="#/new" data-fresh-practice>새 발표 연습</a>
      </div>
      ${DATA.sessions.map(s => `
      <div class="sess-row" data-go="#/report/${s.id}">
        <div class="sess-main">
          <b>${s.title}</b>
          <span>${s.occasion}${s.slides ? ` · ${s.slides}장` : ''} · ${s.date} · ${s.nth}번째 연습 · ${s.note}</span>
        </div>
        <div class="sess-score">
          <strong class="num">${s.score}<small>점</small></strong>
          <span class="up">+${s.diff}</span>
        </div>
        <span class="chev">›</span>
      </div>`).join('')}
    </div>
    <a class="about-link" href="#/about">척척발표가 판단하는 방식 →</a>`;
  $$('.sess-row').forEach(r => r.addEventListener('click', () => location.hash = r.dataset.go));
  animateViz();
}

/* ══ 새 발표 연습 ══ */
let nf = loadSession('new-flow') || {};
/** F-01 결과 (sessionStorage 밖, 메모리만) */
let nfSlideDoc = null;
/** F-03/F-04 마지막 테이크 */
let ccRuntime = null;
let ccLastTake = null;

/** 업로드한 PDF 원본 (메모리). 리허설 화면에 페이지 렌더용 */
let uploadedPdf = null; // { file, pdf, pageCount }
let pdfRenderToken = 0;
let pdfRenderTask = null;
let rehearsalNavBound = false;

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
         _pipelineTickStarted: false };
  nfSlideDoc = null;
  ccRuntime = null;
  ccLastTake = null;
  uploadedPdf = null;
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
function nfSteps() {
  return `<div class="flow-toolbar">
    <div class="steps">${NF_STEPS.map((n, i) =>
      `<span class="${i < nf.step ? 'done' : i === nf.step ? 'cur' : ''}"><i>${i < nf.step ? '✓' : i + 1}</i>${n}</span>`).join('')}</div>
    <div class="flow-save"><span>자동 저장됨</span><a href="#/new" data-fresh-practice>처음부터</a><a href="#/">나가기</a></div>
  </div>`;
}

async function loadUploadedPdf(file) {
  uploadedPdf = null;
  if (!file || !/\.pdf$/i.test(file.name || '')) return null;
  if (!window.pdfjsLib) {
    console.warn('[chuckchuck] pdf.js 미로드');
    return null;
  }
  const data = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data }).promise;
  uploadedPdf = { file, pdf, pageCount: pdf.numPages };
  return uploadedPdf;
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
    <p class="pipe-map-lead">핵심: <b>몇 번 슬라이드를 보고 있을 때</b> 무엇을 말했는지 (F-04 marks × F-05 STT)</p>
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
  nf.slideTitles = (doc.slides || []).map((s) => s.title || `${s.slide_no}번 슬라이드`);
  nf.slideBodies = (doc.slides || []).map(slideBodyFromSlide);
  nf.sparseSlides = (doc.slides || []).filter((s) => s.text_sparse).map((s) => s.slide_no);
  // 썸네일용: 본문 일부 넣은 SVG (필름/게이트용). 발표 본화면은 HTML 카드 사용.
  nf.slideImages = nf.slideTitles.map((t, i) => {
    if (keepDemoImages && DATA.slideImages[i]) return DATA.slideImages[i];
    return slidePlaceholder(i + 1, t, nf.slideBodies[i]);
  });
  nf.slide = 1;
  nf.visits = { 1: 1 };
  nf.log = [];
}
function slidePlaceholder(n, title, body) {
  const safe = escapeHtml(String(title || `${n}번`).slice(0, 40));
  const preview = escapeHtml(String(body || '').replace(/\s+/g, ' ').slice(0, 90));
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
    <rect width="960" height="540" fill="#f5f7fb"/>
    <rect x="40" y="36" width="880" height="468" rx="14" fill="#fff" stroke="#dbe4f0"/>
    <text x="72" y="100" font-family="Pretendard,sans-serif" font-size="26" fill="#8b95a1">${n}</text>
    <text x="72" y="160" font-family="Pretendard,sans-serif" font-size="34" font-weight="700" fill="#191f28">${safe}</text>
    <foreignObject x="72" y="200" width="800" height="260">
      <div xmlns="http://www.w3.org/1999/xhtml" style="font:500 20px/1.45 Pretendard,sans-serif;color:#4e5968;white-space:pre-wrap">${preview || '텍스트 없음'}</div>
    </foreignObject>
  </svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

function renderNew() {
  saveSession('new-flow', nf);
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
          <button class="btn btn-text" id="sample">샘플 자료로 체험하기</button>
        </div>
        <input type="file" id="file" accept=".pdf,.pptx" hidden>
      </div>
      <div class="step-actions">
        <button class="btn btn-primary" disabled>다음: 발표 정보 입력</button>
      </div>`;
    const dz = $('#dz');
    $('#pick').addEventListener('click', () => $('#file').click());
    $('#sample').addEventListener('click', async () => {
      // 실API 모드에서는 fixture 금지 — PDF 업로드로 유도
      try {
        const h = await fetch('/api/health').then((r) => r.json());
        if (h && h.mock === false) {
          failParse('실API 모드입니다. PDF/PPTX를 「파일 선택」으로 올려주세요. (샘플 fixture 비활성)');
          return;
        }
      } catch (_) { /* health 실패 시에도 파일 업로드 유도 */ }
      startParse({ fixture: true });
    });
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
        <p class="note" style="margin-top:2px">Upstage Document Parse로 슬라이드 구조를 만드는 중 (F-01)</p>
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
      <div class="fail-box">${nf.parseError || 'PDF나 PPTX 파일만 분석할 수 있어요. 다른 파일로 올려주세요.'}</div>
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
          <div class="thumb ${sparse.has(i + 1) ? 'warn' : ''}"><img src="${images[i]}" alt="${i + 1}번 슬라이드"><span><b>${i + 1}</b>${t}</span></div>`).join('')}
        </div>
        <div class="warn-note">${warnNote}</div>
      </div>
      <div class="step-actions">
        <button class="btn btn-primary" id="next">다음: 발표 정보 입력</button>
      </div>`;
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
    if (file && /\.pdf$/i.test(file.name || '')) {
      try { await loadUploadedPdf(file); }
      catch (e) { console.warn('[chuckchuck] pdf load', e); }
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
function nfStep2() {
  const occs = ['사내 보고', '학회·수업 발표', '대회·IR 피칭', '범용'];
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
          ${occs.map(o => `<button class="${nf.occ === o ? 'on' : ''}">${o}</button>`).join('')}
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
          <div class="stepper">
            <button id="minus" aria-label="이전 시간">−</button><b id="min">${nf.min}분</b><button id="plus" aria-label="다음 시간">＋</button>
          </div>
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
    nf.occ = b.textContent;
    $$('#occ button').forEach(x => x.classList.toggle('on', x === b));
    saveSession('new-flow', nf);
  });
  $('#ctx').addEventListener('input', e => { nf.ctx = e.target.value; saveSession('new-flow', nf); });
  $('#timePresets').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    nf.min = Number(b.dataset.min); nfStep2(); saveSession('new-flow', nf);
  });
  const moveTime = d => {
    const exact = times.indexOf(nf.min);
    const pos = exact >= 0 ? exact : times.reduce((best, t, i) => Math.abs(t - nf.min) < Math.abs(times[best] - nf.min) ? i : best, 0);
    nf.min = times[Math.min(times.length - 1, Math.max(0, pos + d))];
    nfStep2(); saveSession('new-flow', nf);
  };
  $('#minus').addEventListener('click', () => moveTime(-1));
  $('#plus').addEventListener('click', () => moveTime(1));
  $('#go').addEventListener('click', () => { nf.step = 2; renderNew(); });
  $('#skip').addEventListener('click', () => { nf.occ = '범용'; nf.step = 2; renderNew(); });
}

/* 스텝 3 — 리허설 녹음 */
function rehearsalCount() {
  const fromPdf = uploadedPdf && uploadedPdf.pageCount ? uploadedPdf.pageCount : 0;
  const fromTitles = activeTitles().length;
  return Math.max(fromPdf, fromTitles, 1);
}

function nfStep3() {
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

  const film = Array.from({ length: nPages }, (_, i) => {
    const on = i + 1 === nf.slide ? 'on' : '';
    return `<button type="button" class="${on}" data-slide="${i + 1}" aria-label="${i + 1}번 슬라이드"><span class="film-no">${i + 1}</span><span class="film-title">${escapeHtml(String(titleAt(i)).slice(0, 28))}</span></button>`;
  }).join('');

  app.className = '';
  app.innerHTML = `${nfSteps()}
    <div class="rehearsal-head">
      <div><span class="mode-label">발표 모드</span><h1>슬라이드를 보며 실제처럼 발표해보세요</h1></div>
      <p>← → 키 · 좌우 버튼 · 아래 필름으로 넘길 수 있어요${usePdf ? ' · 업로드한 PDF 원본' : ''}</p>
    </div>
    <div class="rehearsal-shell">
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
        <div class="slide-film slide-film-text" id="slideFilm">${film}</div>
      </div>
      <div class="card rehearsal-control" id="recPanel"></div>
    </div>
    <p class="privacy-note">녹음은 발표 분석에만 사용돼요.</p>`;
  renderRecPanel();
  bindRehearsalNav();
  paintRehearsalSlide(nf.slide);
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
      <p class="note" id="recUploadNote">m4a · mp3 · wav · webm · 최대 ${MAX_AUDIO_MB}MB. 슬라이드 구간은 길이를 균등 분할해 채웁니다.</p>
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
  if (nf.mic === 'idle') {
    p.innerHTML = `
      <div class="rec-copy"><span>준비되면 시작하세요</span><p>발표하면서 넘긴 슬라이드와 말한 내용을 함께 기록해요.</p></div>
      <button class="btn btn-primary" id="recStart">발표 시작하기</button>
      ${recUploadHtml()}`;
    $('#recStart').addEventListener('click', startRec);
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
  }
}

/* chuckchuck SDK 런타임 (F-03/F-04). bridge 모듈 로드 전엔 null. */

function startRec() {
  const bridge = window.ChuckchuckBridge;
  if (bridge) {
    ccRuntime = bridge.attachRehearsalRuntime(nf, {
      totalSlides: rehearsalCount(),
      onTick: (sec) => {
        nf.sec = Math.floor(sec);
        const c = $('#clock'); if (c) c.textContent = fmt(nf.sec);
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
    saveSession('new-flow', nf);
  }, 1000);
}

async function finishRecAndPrepare() {
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
  if (nfSlideDoc) return nfSlideDoc;
  const hint = nf.fileName || '';
  try {
    const res = await fetch(`/api/v1/cached-slidedoc?file=${encodeURIComponent(hint)}`);
    if (!res.ok) return null;
    const doc = await res.json();
    if (!doc || doc.error || !Array.isArray(doc.slides)) return null;
    nfSlideDoc = doc;
    console.info('[chuckchuck] SlideDoc 캐시 복구', doc.file_name, doc.total_slides);
    return nfSlideDoc;
  } catch (err) {
    console.warn('[chuckchuck] cached-slidedoc', err);
    return null;
  }
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

/* F-11 분석 리빌 — 리허설 종료 → 질문 준비 사이에 전체 화면으로 재생.
   뒤에서는 파이프라인이 돌고, CTA(질문 코치 시작하기)를 누르면 걷힌다. */
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
  // 파이프라인이 F-07/F-11 결과를 내면 iframe 에 실데이터를 넘긴다
  const feed = setInterval(() => {
    if (!document.getElementById('f11RevealWrap')) { clearInterval(feed); return; }
    const out = nf.pipelineOut;
    const iframe = wrap.querySelector('iframe');
    if (!iframe || !iframe.contentWindow) return;
    // 대기 화면이 몇 %인지 알 수 있게 매 틱 진행률을 넘긴다 (실데이터 도착 전에도)
    const phase = nf.pipelinePhase || 'queued';
    iframe.contentWindow.postMessage({
      type: 'f11Progress',
      phase,
      label: pipelinePhaseLabel(phase),
      detail: nf.pipelineDetail || '',
      percent: pipelinePercent(phase, phaseElapsedSec()),
    }, location.origin);
    if (out && out.graph && out.alignment) {
      clearInterval(feed);
      iframe.contentWindow.postMessage(
        { type: 'f11Data', graph: out.graph, alignment: out.alignment, flow: out.flow || null,
          transcript: out.transcript || null }, location.origin);
    }
  }, 500);
  const onMsg = (e) => {
    if (e.data && e.data.type === 'f11RevealDone') {
      window.removeEventListener('message', onMsg);
      wrap.style.opacity = '0';
      setTimeout(() => {
        wrap.remove();
        // 파이프라인이 끝났으면 질문 코치로 바로, 아니면 준비 화면에서 대기
        if ((nf.pipelinePhase || '') === 'done') location.hash = '#/qa';
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
const PIPELINE_MARKS = {
  queued: [0, 4],
  encoding: [4, 10],
  stt: [10, 45],
  stt_done: [45, 48],
  concepts: [48, 70],
  concepts_done: [70, 72],
  concepts_error: [70, 72],
  graph: [72, 82],
  graph_done: [82, 84],
  align: [84, 95],
  align_done: [95, 96],
  align_error: [95, 96],
  flow: [96, 99],
  flow_done: [99, 100],
  done: [100, 100],
  error: [100, 100],
};
/** 이 초 수쯤 지나면 구간 천장의 63% 지점에 닿는다 */
const PIPELINE_CREEP_TAU_SEC = 25;

function pipelinePercent(phase, phaseElapsedSec) {
  const [base, ceil] = PIPELINE_MARKS[phase] || PIPELINE_MARKS.queued;
  if (ceil <= base) return ceil;
  const k = 1 - Math.exp(-Math.max(0, Number(phaseElapsedSec) || 0) / PIPELINE_CREEP_TAU_SEC);
  return Math.round(Math.min(ceil, base + (ceil - base) * k));
}

/** 지금 단계가 시작된 뒤 흐른 초 */
function phaseElapsedSec() {
  const t = nf._phaseStartedAt || nf.pipelineStartedAt || Date.now();
  return Math.max(0, (Date.now() - t) / 1000);
}

function pipelinePhaseLabel(phase) {
  const map = {
    queued: '대기 중',
    encoding: '오디오 인코딩',
    stt: 'F-05 STT 변환',
    stt_done: 'F-05 완료',
    concepts: 'F-06 개념 추출',
    concepts_done: 'F-06 완료',
    concepts_error: 'F-06 실패',
    graph: 'F-07 개념 그래프',
    graph_done: 'F-07 완료',
    align: 'F-11 발표·자료 대조',
    align_done: 'F-11 완료',
    align_error: 'F-11 실패',
    flow: '흐름 비교',
    flow_done: '흐름 비교 완료',
    flow_error: '흐름 비교 실패',
    done: '완료',
    error: '오류',
  };
  return map[phase] || phase || '진행 중';
}

/** 체크리스트 진행도 0..4 — 실제 파이프라인 phase 기준 */
function pipelineChecklistDone() {
  const phase = nf.pipelinePhase || 'queued';
  if (nf.conceptsOk || phase === 'concepts_done') return 4;
  if (phase === 'done' && !nf.pipelineOut?.conceptsError) return 4;
  if (['concepts', 'concepts_error', 'done'].includes(phase) || nf.transcriptOk) {
    if (phase === 'concepts_error' || (phase === 'done' && nf.pipelineOut?.conceptsError)) return 3;
    if (phase === 'concepts') return 2;
    if (nf.transcriptOk || phase === 'stt_done' || phase === 'done') return 2;
  }
  if (phase === 'stt_done') return 2;
  if (phase === 'stt' || phase === 'encoding') return 1;
  return Math.min(nf.done || 0, 1);
}

function pipelineLoadingHtml(kind) {
  const phase = nf.pipelinePhase || 'queued';
  const detail = nf.pipelineDetail || '';
  const started = nf.pipelineStartedAt || Date.now();
  const elapsed = Math.max(0, Math.floor((Date.now() - started) / 1000));

  if (kind === 'stt') {
    if (['stt_done', 'concepts', 'concepts_done', 'concepts_error', 'done', 'error'].includes(phase)) return '';
  }
  if (kind === 'concepts') {
    if (!['stt_done', 'concepts'].includes(phase)) return '';
  }

  const hint = kind === 'stt'
    ? '실API STT는 녹음 길이에 따라 수십 초~수 분 걸릴 수 있어요.'
    : '슬라이드 수에 따라 개념 추출에 시간이 더 걸릴 수 있어요.';

  return `<div class="pipe-loading" data-pipe-kind="${kind}">
    <div class="progress indeterminate"><i></i></div>
    <p class="parse-meta">
      <span class="pipe-phase">${escapeHtml(pipelinePhaseLabel(phase))}</span>
      · 경과 <b class="pipe-elapsed">${elapsed}</b>초
      ${detail ? `<br><span class="pipe-detail">${escapeHtml(detail)}</span>` : ''}
      <br>${hint}
    </p>
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

  const markRows = marks.length
    ? marks.map((m, i) => {
      const next = marks[i + 1];
      const end = m.end_sec != null ? m.end_sec : (next ? next.start_sec : m.start_sec);
      return `<tr>
        <td>${i + 1}</td>
        <td>${fmtMarkSec(m.start_sec)} – ${fmtMarkSec(end)}</td>
        <td><b>${m.slide_no}</b>번</td>
        <td>${m.visit || 1}번째</td>
      </tr>`;
    }).join('')
    : '<tr><td colspan="4">아직 전환 기록이 없어요. 리허설에서 슬라이드를 넘겨 보세요.</td></tr>';

  const uiLog = (nf.log || []).map((l) =>
    `<li class="${l.re ? 're' : ''}">${escapeHtml(l.txt)}</li>`
  ).join('') || '<li>UI 로그 없음</li>';

  // 업로드본은 전환 기록이 없어 marks 를 합성했다. 측정값처럼 읽히면 안 된다.
  const up = nf.uploadedTake;
  const uploadedNote = up
    ? `<p class="note" style="color:#f59e0b">업로드한 녹음 <b>${escapeHtml(up.name)}</b>
       (${fmtMarkSec(up.durationSec)})으로 돌렸어요. 아래 marks 는 <b>실제 전환 기록이 아니라
       길이를 ${marks.length}등분한 합성값</b>이라, 슬라이드별 발화 분할과 F-11 정합 판정은
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
    speechHtml = `<p class="note" style="color:#f04452">STT까지 도달하지 못했어요: ${escapeHtml(nf.pipelineError)}</p>`;
  } else {
    speechHtml = pipelineLoadingHtml('stt') || '<p class="note">STT 결과 대기 중…</p>';
  }

  let conceptHtml = '';
  if (concepts && !concepts.error && Array.isArray(concepts.slides)) {
    conceptHtml = `<details class="pipe-block" open><summary>F-06 개념 추출 (${concepts.slides.length}장)</summary>
      <ul class="pipe-concepts">${concepts.slides.slice(0, 12).map((s) =>
        `<li><b>${s.slide_no}.</b> ${escapeHtml(s.topic || s.title || '')}
         <span>${escapeHtml((s.concepts || []).slice(0, 3).join(' · '))}</span></li>`
      ).join('')}</ul></details>`;
  } else if (conceptsError) {
    conceptHtml = `<details class="pipe-block" open><summary>F-06 개념 추출 (실패)</summary>
      <p class="note" style="color:#f04452">${escapeHtml(conceptsError)}</p>
      <p class="note">STT 결과는 위에 그대로 남아 있어요.</p>
    </details>`;
  } else if (nfSlideDoc || ['stt_done', 'concepts', 'queued', 'encoding', 'stt'].includes(phase)) {
    const loading = pipelineLoadingHtml('concepts');
    if (loading || ['stt_done', 'concepts'].includes(phase)) {
      conceptHtml = `<details class="pipe-block" open><summary>F-06 개념 추출</summary>${loading || '<p class="note">STT 이후 개념 추출을 시작해요.</p>'}</details>`;
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
      <p class="note">화살표·하단 필름으로 넘긴 기록이 F-04 marks / F-05 분할에 들어갔는지 여기서 확인하세요.</p>
      ${uploadedNote}
      <details class="pipe-block" open>
        <summary>F-04 슬라이드 구간 marks (${marks.length})</summary>
        <div class="table-wrap"><table class="pipe-table">
          <thead><tr><th>#</th><th>시간</th><th>슬라이드</th><th>방문</th></tr></thead>
          <tbody>${markRows}</tbody>
        </table></div>
      </details>
      <details class="pipe-block">
        <summary>화면 전환 로그 (${(nf.log || []).length})</summary>
        <ul class="pipe-uilog">${uiLog}</ul>
      </details>
      <details class="pipe-block" open>
        <summary>F-05 슬라이드 ↔ 발화 매핑 (${(transcript && Array.isArray(transcript.by_slide)) ? transcript.by_slide.length : 0}구간)</summary>
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

function startPipelineElapsedTimer() {
  if (nf._pipelineTickStarted) return;
  nf._pipelineTickStarted = true;
  every(() => {
    if (!nf.pipelineStartedAt || ['done', 'error', 'concepts_error'].includes(nf.pipelinePhase)) {
      return;
    }
    const elapsed = Math.max(0, Math.floor((Date.now() - nf.pipelineStartedAt) / 1000));
    $$('.pipe-elapsed').forEach((el) => { el.textContent = String(elapsed); });
  }, 1000);
}

function nfStep4() {
  app.className = 'narrow';
  const items = [
    '음성을 글로 바꿨어요 (단어별 시간 포함)',
    '슬라이드별로 발화를 나눴어요',
    '발표자료의 개념과 실제 발화를 대조했어요',
    '먼저 확인할 질문을 만들었어요',
  ];
  // 가짜 타이머 대신 실제 파이프라인 진행도로 체크리스트 표시
  const doneN = Math.max(nf.done || 0, pipelineChecklistDone());
  nf.done = doneN;
  const conceptsError = (nf.pipelineOut && nf.pipelineOut.conceptsError) || null;
  const pipeErr = conceptsError
    ? `<p class="note" style="color:#f04452;margin-bottom:12px">개념 추출 실패 (STT는 성공): ${escapeHtml(conceptsError)}</p>`
    : (nf.pipelineError
      ? `<p class="note" style="color:#f04452;margin-bottom:12px">연동 오류: ${escapeHtml(nf.pipelineError)}</p>`
      : '');
  app.innerHTML = `${nfSteps()}
    <div class="card">
      <h3 class="section-title">발표를 듣고 질문을 준비하고 있어요</h3>
      <p class="note" style="margin-bottom:14px">최종 분석 전에, 설명이 비어 있던 개념을 질문으로 함께 확인해요.</p>
      ${pipeErr}
      <ul class="checklist">
        ${items.map((t, i) => {
          const st = i < doneN ? 'done' : i === doneN ? 'doing' : 'todo';
          return `<li class="${st}"><i>${i < doneN ? '✓' : i + 1}</i>${t}</li>`;
        }).join('')}
      </ul>
      ${pipelineInspectHtml()}
      <div class="step-actions">
        <button class="btn btn-secondary" type="button" data-fresh-practice>처음부터 다시</button>
        <button class="btn btn-secondary btn-sm" type="button" id="againTake">다른 녹음으로 다시</button>
        <a class="btn btn-text btn-sm skip-qa" href="#/report">질문코치 건너뛰고 상세 리포트</a>
        ${nf.conceptsOk && doneN >= items.length
          ? `<span style="font-weight:700">질문 준비가 끝났어요</span>
             <a class="btn btn-primary" href="#/qa">질문 코칭 시작하기</a>`
          : (nf.transcriptOk && conceptsError
            ? `<span class="note">STT까지는 성공했어요. 개념 추출만 실패했습니다.</span>`
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
    nf.step = 2;
    saveSession('new-flow', nf);
    renderNew();
  });

  if (ccLastTake && window.ChuckchuckBridge && !nf._pipelineStarted) {
    nf._pipelineStarted = true;
    nf.pipelineError = null;
    nf.pipelinePhase = 'queued';
    nf.pipelineDetail = '파이프라인 시작';
    nf.pipelineStartedAt = Date.now();
    nf.transcriptOk = false;
    nf.conceptsOk = false;
    refreshPipelineInspect();

    // slideDoc 이 없으면 F-06 이후가 통째로 안 돈다. 캐시에서 먼저 되살린다.
    ensureSlideDoc().then((slideDoc) => window.ChuckchuckBridge.runPreparePipeline({
      marks: ccLastTake.marks,
      blob: ccLastTake._blob,
      mimeType: ccLastTake.mimeType,
      fileName: ccLastTake.fileName || '',
      slideDoc,
      context: {
        situation: nf.occ || '',
        audience: nf.ctx || '',
        duration_min: nf.min,
      },
      onProgress: ({ phase, detail, transcript, concepts, conceptsError: cErr, graph, alignment, flow }) => {
        if (phase !== nf.pipelinePhase) nf._phaseStartedAt = Date.now();
        nf.pipelinePhase = phase;
        nf.pipelineDetail = detail || '';
        if (transcript || concepts || cErr || graph || alignment || flow) {
          nf.pipelineOut = {
            ...(nf.pipelineOut || {}),
            ...(transcript ? { transcript } : {}),
            ...(concepts ? { concepts } : {}),
            ...(cErr ? { conceptsError: cErr } : {}),
            ...(graph ? { graph } : {}),
            ...(alignment ? { alignment } : {}),
            ...(flow ? { flow } : {}),
          };
        }
        if (transcript && !transcript.error) nf.transcriptOk = true;
        // STT 완료 직후 전체 화면을 다시 그려 발화 블록이 확실히 보이게
        if (phase === 'stt_done' || phase === 'concepts_error' || phase === 'concepts_done') {
          nf.done = pipelineChecklistDone();
          nfStep4();
        } else {
          refreshPipelineInspect();
        }
      },
    })).then((out) => {
      nf.pipelineOut = out;
      nf.pipelinePhase = out && out.conceptsError ? 'concepts_error' : 'done';
      nf.pipelineDetail = out && out.conceptsError ? out.conceptsError : '준비 완료';
      nf.transcriptOk = !!(out && out.transcript && !out.transcript.error);
      nf.conceptsOk = !!(out && out.concepts && !out.concepts.error && !out.conceptsError);
      if (out && out.conceptsError) {
        nf.pipelineError = null; // STT 성공분 유지 — 상단은 conceptsError 로 표시
      }
      console.info('[chuckchuck] pipeline ok', out);
      nf.done = pipelineChecklistDone();
      nfStep4();
    }).catch((err) => {
      console.warn('[chuckchuck] prepare pipeline', err);
      nf.pipelineError = err.message || String(err);
      nf.pipelinePhase = 'error';
      nf.pipelineDetail = nf.pipelineError;
      // 부분 결과가 있으면 유지
      nf.done = pipelineChecklistDone();
      nfStep4();
    });
  }
}

/* ══ 리포트 ══ */
let rTab = 0, jSel = 'contrast', jFilter = 'all', toolSeg = 0, mapWeakOnly = false, repSlide = 7;

function renderReport() {
  const reportId = location.hash.replace(/^#\/?/, '').split('/')[1] || 'imu2clip';
  if (reportId !== 'imu2clip' && DATA.reportProfiles[reportId]) {
    renderProfileReport(DATA.reportProfiles[reportId]);
    return;
  }
  app.className = 'wide';
  const s = DATA.session;
  const tabs = ['요약', '개념별 판정', '논리 흐름', '말 속도', '연습 도구'];
  app.innerHTML = `
    <div class="report-head">
      <span class="final-label">발표 + 질문 코칭 최종 분석</span>
      <h1 class="page-title">${s.title}</h1>
      <p class="report-meta">${s.occasion} · ${s.slides}장 · ${s.duration} · ${s.nth}번째 연습</p>
    </div>
    <div class="tabs" id="rtabs">
      ${tabs.map((t, i) => `<button class="${i === rTab ? 'on' : ''}">${t}</button>`).join('')}
    </div>
    <div id="rbody"></div>`;
  $('#rtabs').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    rTab = $$('#rtabs button').indexOf(b);
    renderReport();
  });
  [rSummary, rJudge, rLogic, rPace, rTools][rTab]();
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
function rSummary() {
  const s = DATA.session;
  const prio = DATA.priorities[s.occasion];
  const D = s.durationSec;
  const tr = s.qa.trophy;
  $('#rbody').innerHTML = `
    <div class="card hero-card final-score-card">
      ${ringSvg(s.score, 132, 11, `<strong class="num" data-count="${s.score}">0</strong><span>점</span>`)}
      <div class="hero-body">
        <span class="chip chip-sm chip-up">지난 연습보다 +${s.score - s.prevScore}점</span>
        <h2>${s.oneLiner}</h2>
        <div class="dims">
          ${s.dims.map(d => `
          <div class="dim-row">
            <span class="lb">${d[0]}</span>
            <div class="fill-bar"><i data-w="${d[1]}%"></i></div>
            <span class="vl num">${d[1]}</span>
          </div>`).join('')}
        </div>
      </div>
    </div>

    <button class="card trophy-strip" id="trophyStrip">
      <span class="ts-label">오늘 만든 문장</span>
      <p class="ts-quote">“${tr.after}”</p>
      <i class="ts-go">${tr.slide}번 슬라이드에서 보기 →</i>
    </button>

    <div class="card rep-deck">
      <h3 class="section-title">슬라이드로 보는 발표<span class="soft">장을 누르면 그 장에서 있었던 일을 보여줘요</span></h3>
      <div id="deckBody">${deckHtml()}</div>
      <div class="deck-film" id="deckFilm">
        ${DATA.slideStatus.map((st, i) => {
          const n = i + 1;
          return `<button class="slidethumb st-${st} has ${n === repSlide ? 'on' : ''}" data-slide="${n}" title="${n}. ${DATA.slideTitles[i]} · ${STATUS[st]}">
            <img src="${DATA.slideImages[i]}" alt="${n}번 슬라이드" loading="lazy">
            <span class="stnum">${n}</span>
          </button>`;
        }).join('')}
      </div>
      <div class="legend">
        <span><i class="dot st-ok"></i>설명함</span>
        <span><i class="dot st-mid"></i>언급만 함</span>
        <span><i class="dot st-no"></i>안 나옴</span>
        <span><i class="dot st-ct"></i>자료와 모순</span>
        <span><i class="dot st-om"></i>정당한 생략</span>
      </div>
    </div>

    <h2 class="section-title" style="margin:26px 0 12px">이것부터 고치면 돼요<span class="soft">효과가 가장 큰 한 가지</span></h2>
    ${prioCard(prio[0], 1)}
    <details class="fold">
      <summary>보완 2가지 더 보기</summary>
      <div class="fold-body">${prio.slice(1).map((p, i) => prioCard(p, i + 2)).join('')}</div>
    </details>

    <div class="card next-card">
      <h3>다음 연습은 ‘IMU Encoder’ 설명부터 시작해요</h3>
      <p>Q&A로 두 개념은 설명할 수 있게 됐어요. 발표에서 통째로 빠진 Encoder 구조를 다음 리허설 목표로 가져가세요.</p>
      <div class="step-actions">
        <a class="btn btn-primary" href="#/new">새 발표 연습</a>
        <a class="btn btn-tint" href="#/qa" style="background:#fff">질문 연습 다시 하기</a>
      </div>
    </div>

    <details class="fold">
      <summary>개념별 판정 전체 보기</summary>
      <div class="fold-body">
        ${DATA.tree.map(n => `
        <div class="mini-row" data-node="${n.id}">
          <span class="dot st-${n.status}"></span>
          <span class="lbl" style="${n.depth === 2 ? 'padding-left:16px' : ''}">${n.label}</span>
          <span class="sl">${slideNumber(n.slide)}번 슬라이드</span>
          ${chip(n.status, true)}
        </div>`).join('')}
      </div>
    </details>`;
  $('#trophyStrip').addEventListener('click', () => {
    selectDeckSlide(DATA.session.qa.trophy.slide);
    $('.rep-deck').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  $('#deckFilm').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    selectDeckSlide(Number(b.dataset.slide));
  });
  $$('.mini-row').forEach(r => r.addEventListener('click', () => goJudge(r.dataset.node)));
  bindDeckPanel();
  mountAudienceCard();
}

/* ---------------------------------------------------------------------------
   삐약 청중석 — 리포트 요약 탭 맨 아래에서 객석으로 들어간다
   --------------------------------------------------------------------------- */

let chatterCache = null;   // 한 번 받은 수다는 '다시 듣기'에서 재사용한다

function mountAudienceCard() {
  if (!window.Chatter) return;
  const body = $('#rbody');
  if (!body || $('#audCard')) return;
  body.insertAdjacentHTML('beforeend', window.Chatter.entryCardHtml());
  $('#audCard').addEventListener('click', openAudience);
}

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
  const phase = pipelinePhaseLabel(nf.pipelinePhase);
  const stepName = { graph: 'F-07 개념 그래프', alignment: 'F-11 정합 판정', flow: '흐름 비교' };
  return `분석이 ${stepName[missing[0]]}까지 못 갔어요 (지금 ${phase}). `
    + '청중은 판정 결과를 놓고 수군거리는 거라, 거기까지 끝나야 열려요.';
}

async function openAudience() {
  const card = $('#audCard');
  const bundle = pipelineBundle();
  if (!bundle) {
    const reason = audienceBlockReason();
    if (card && reason) card.querySelector('p').textContent = reason;
    return;
  }

  // 근거 배지에 슬라이드 번호를 쓰려면 node → slide 매핑이 필요하다
  const nodeSlides = {};
  (bundle.graph.nodes || []).forEach(n => {
    if (n.slide_nos && n.slide_nos.length) nodeSlides[n.id] = Math.min(...n.slide_nos);
  });

  if (card) card.querySelector('p').textContent = '객석에서 수군거리는 중...';
  try {
    if (!chatterCache) {
      chatterCache = await window.Chatter.fetchChatter(
        bundle.graph, bundle.alignment, bundle.flow
      );
    }
    window.Chatter.show(chatterCache, { nodeSlides: nodeSlides, onRef: goJudge });
    if (card) card.querySelector('p').textContent =
      '발표 끝나고 객석에 남은 네 청중이 뭐라고 하는지 엿들어 볼까요?';
  } catch (err) {
    if (card) card.querySelector('p').textContent =
      (err && err.message) || '청중들이 아직 도착 안 했어요. 잠시 후 다시 시도해 주세요.';
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

/** 실데이터가 있으면 그것, 없으면 샘플. real 플래그로 화면이 구분해 표시한다. */
function judgeTree() {
  return realJudgeTree() || DATA.tree.map(n => ({ ...n, real: false }));
}

function rJudge() {
  const tree = judgeTree();
  const isReal = !!(tree[0] && tree[0].real);
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
      : '⚠️ 지금 보시는 건 <b>샘플 데이터</b>예요. 리허설을 마쳐 F-11 정합 판정까지 끝나면 실제 발표 결과로 바뀝니다.'}</p>`;
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
function rPace() {
  const MAX = 460, st = DATA.paceStats;
  const ratio = (st.avg / MAX);
  $('#rbody').innerHTML = `
    <div class="stat-row">
      <div class="stat-card"><small>내 평균</small><strong class="num" data-count="${st.avg}">0</strong><span class="unit">자/분</span></div>
      <div class="stat-card"><small>가장 빨랐던 구간</small><strong class="num">${st.max}</strong><span class="unit">자/분</span><p class="note" style="margin-top:4px">${st.maxSeg}</p></div>
      <div class="stat-card"><small>발표 권장 속도</small><strong class="num">${st.rec}</strong><span class="unit">자/분</span></div>
    </div>
    <div class="card">
      <h3 class="section-title">구간별 말 속도<span class="soft">점선이 내 평균이에요</span></h3>
      <div class="pace-rows">
        <span class="pace-base" style="left:calc(122px + (100% - 226px) * ${ratio.toFixed(3)})"><em>내 평균 ${st.avg}</em></span>
        ${DATA.pace.map(p => `
        <div class="pace-row ${p[3] ? 'fast' : ''}">
          <span class="nm">${p[0]}</span>
          <div class="fill-bar"><i class="${p[3] ? 'red' : ''}" data-w="${(p[2] / MAX * 100).toFixed(1)}%"></i></div>
          <span class="vl">${p[2]}자/분${p[3] ? ' · 빠름' : ''}</span>
        </div>`).join('')}
      </div>
      <p class="note" style="margin-top:14px">수식 설명 구간이 본인 평균보다 24% 빨라요. Temperature Parameter와 loss 모두 설명이 부족하다고 판정된 개념과 겹쳐요.</p>
    </div>
    <div class="card">
      <h3 class="section-title">시간 배분<span class="soft">보조 분석 · 권장 대비 실제</span></h3>
      <div class="alloc-lgd">
        <span><i style="background:#C6CCD3"></i>권장</span>
        <span><i style="background:var(--blue)"></i>실제</span>
      </div>
      ${DATA.timeAlloc.map(r => `
      <div class="alloc-row">
        <span class="nm">${r[0]}</span>
        <div class="alloc-bars">
          <div class="fill-bar"><i class="gray" data-w="${(r[1] / 35 * 100).toFixed(0)}%"></i></div>
          <div class="fill-bar"><i class="${r[3] === '적절' ? '' : 'red'}" data-w="${(r[2] / 35 * 100).toFixed(0)}%"></i></div>
        </div>
        <span class="alloc-st ${r[3] === '적절' ? 'fine' : 'warn'}">${r[3]}</span>
      </div>`).join('')}
      <p class="note" style="margin-top:12px">방법론 구간에 권장 시간보다 적게 썼어요. 배경을 조금 줄이고 7~12번 슬라이드의 원리 설명에 시간을 옮겨보세요.</p>
    </div>`;
}

/* 탭 5 — 연습 도구 */
function rTools() {
  const segs = ['개요 이미지', '펀치라인', '용어 카드'];
  $('#rbody').innerHTML = `
    <div class="seg-ctl" id="seg">
      ${segs.map((t, i) => `<button class="${i === toolSeg ? 'on' : ''}">${t}</button>`).join('')}
    </div>
    <div id="toolBody"></div>`;
  $('#seg').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    toolSeg = $$('#seg button').indexOf(b); rTools();
  });
  [tMap, tPunch, tTerms][toolSeg]();
}

function mapSvgString() {
  const FILL = { ok: '#EBF2FF', mid: '#FFF4E5', no: '#FDEDED', ct: '#FAE8FF' };
  const LINE = { ok: '#1B64DA', mid: '#B25E09', no: '#D93A3A', ct: '#A21CAF' };
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
let qa = loadSession('qa-flow') || {};
function resetQa() {
  qa = {
    aud: '교수님', started: false, ended: false,
    bi: 0, sub: 'answer', hint: 0,
    turns: [],
    concepts: { joint: 'wait', temp: 'wait', aria: 'wait' },
    lost: [],
    combo: 0, comboMax: 0, awarded: false, award: null,
  };
  saveSession('qa-flow', qa);
}
if (!Array.isArray(qa.turns)) resetQa();
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
const persona = () => PERSONAS[qa.aud] || PERSONAS['교수님'];
const audInit = () => persona().init;
/* 받침 유무에 따라 한국어 조사 선택 (과/와, 이/가, 을/를) */
const hasBatchim = w => { const c = (w || '').charCodeAt((w || '').length - 1); return c >= 0xAC00 && c <= 0xD7A3 ? (c - 0xAC00) % 28 !== 0 : true; };
const josa = (w, withB, noB) => hasBatchim(w) ? withB : noB;
/* 상대별 대사/행동 오버레이(by)를 기본 비트 위에 병합 */
const beat = () => {
  const b = DATA.qaBeats[qa.bi];
  const ov = b.by && b.by[qa.aud];
  return ov ? { ...b, ...ov } : b;
};
const qText = b => (b.q && (b.q[qa.aud] || b.q['공통'])) || '';

function pushTurn(item) { qa.turns.push(item); saveSession('qa-flow', qa); }
function scrollDown() { window.scrollTo({ top: document.body.scrollHeight, behavior: 'auto' }); }

/* ── 설득 트래커 ── */
const TRACK_ICON = { wait: '', current: '', won: '✓', review: '✓', lost: '✕' };
const TRACK_WORD = { wait: '아직', current: '설득 중', won: '설득 완료', review: '두 번 확인', lost: '미방어' };
function trackerHTML() {
  const order = ['joint', 'temp', 'aria'];
  const won = order.filter(c => qa.concepts[c] === 'won' || qa.concepts[c] === 'review').length;
  const lost = qa.lost.length;
  const prog = Math.min(100, Math.round(qa.bi / (DATA.qaBeats.length - 1) * 100));
  return `<div class="persuade-track" id="ptrack" style="--p:${prog}%">
    <div class="pt-head"><span>${qa.aud} 설득하기</span>
      <span class="pt-right">${qa.combo >= 2 ? `<span class="combo-live">🔥 ${qa.combo}연속 방어</span>` : ''}<b>${won}<i>/3 설득</i>${lost ? ` · <em>${lost} 미방어</em>` : ''}</b></span></div>
    <div class="pt-items">${order.map(c => {
      const s = qa.concepts[c];
      return `<div class="pt ${s}"><i>${TRACK_ICON[s]}</i><span>${CONCEPT_LABELS[c]}</span><small>${TRACK_WORD[s]}</small></div>`;
    }).join('')}</div></div>`;
}
function updateTracker() { const el = $('#ptrack'); if (el) el.outerHTML = trackerHTML(); }

/* ── 스트림 한 줄 렌더 ── */
function streamRow(it) {
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
    if (node) { node.classList.add('enter'); s.appendChild(node); }
  }
  scrollDown();
}

/* ── 화면 ── */
function renderQa() {
  app.className = 'narrow';
  if (qa.ended) return qaEnd();
  qa.started = true;
  // 첫 진입: 첫 질문을 스레드에 올림
  if (!qa.turns.length) { qa.concepts.joint = 'current'; presentQuestion(DATA.qaBeats[0]); }
  // 새로고침 등으로 중간 상태가 저장돼 있으면 안전한 상태로 되돌림
  if (qa.sub === 'speaking' || qa.sub === 'thinking' || qa.sub === 'committed')
    qa.sub = beat().kind === 'trap' ? 'choice' : 'answer';
  saveSession('qa-flow', qa);
  app.innerHTML = `
    <div class="coach-nav"><a href="#/">← 저장하고 나가기</a><span>자동 저장됨</span></div>
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
    <div class="qa-stream" id="stream">${qa.turns.map(streamRow).join('')}</div>
    <div class="qa-live" id="live"></div>`;
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
  if (qa.bi >= DATA.qaBeats.length - 1) { qa.sub = 'ended'; renderLive(); return; }
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
function qaEnd() {
  if (!qa.awarded) { qa.award = awardGame(); qa.awarded = true; }
  saveSession('qa-flow', qa);
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
          <tr><td>F-01</td><td>발표자료(PPT·PDF)를 슬라이드별 텍스트·구조로 변환</td><td>Upstage Document Parse</td><td><span class="chip chip-sm st-ok">확정</span></td></tr>
          <tr><td>F-05</td><td>녹음을 단어별 시간과 함께 글로 변환, 슬라이드 구간으로 분할</td><td>SKT A.X 계열</td><td><span class="chip chip-sm chip-plain">검증 중</span></td></tr>
          <tr><td>F-06·07</td><td>핵심 개념 추출과 중요도 순 개념 트리 구성</td><td>메인 LLM</td><td><span class="chip chip-sm chip-plain">후보 테스트</span></td></tr>
          <tr><td>F-08~10</td><td>자료·발표 STT·앞선 답변 기반 질문 생성과 소크라테스식 코칭</td><td>판정 LLM</td><td><span class="chip chip-sm chip-plain">후보 테스트</span></td></tr>
          <tr><td>F-11</td><td>개념별 설명 여부 판정 (근거 발화 포함)</td><td>문장 유사도 검색 + KT 믿:음</td><td><span class="chip chip-sm chip-plain">후보 테스트</span></td></tr>
          <tr><td>F-12</td><td>논리가 끊긴 곳 탐지 (최대 5곳)</td><td>LG EXAONE / SKT A.X</td><td><span class="chip chip-sm chip-plain">후보 테스트</span></td></tr>
          <tr><td>F-13</td><td>발표자 맞춤 방향 제안 (실제 발화 인용 필수)</td><td>SKT A.X / LG EXAONE</td><td><span class="chip chip-sm chip-plain">후보 테스트</span></td></tr>
          <tr><td>최종 분석</td><td>발표 판정과 Q&A 전후 이해 변화를 하나의 결과로 통합</td><td>규칙 계산 + 판정 결과 결합</td><td><span class="chip chip-sm chip-plain">mock</span></td></tr>
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
