/**
 * 비전 리허설 (#/vision · 주소창 /vision).
 *
 * 발표 리허설(nfStep3)의 다른 배치다. 녹화·슬라이드 이동은 그대로 쓰고,
 * 화면만 바꾼다 — 카메라가 바탕이고 그 앞에 발표 자료와 삐약이가 크게 선다.
 * 말하는 속도·크기는 vision_cue.js 가 고르고, 삐약이 표정으로 보여 준다.
 * 판단에 서버를 쓰지 않는다. 받아쓰기는 브라우저 음성 인식이다.
 *
 * 클래식 스크립트라 app.js 전역(nf · $ · moveSlide · paintRehearsalSlide …)을
 * 호출 시점에 찾는다. 켜짐은 탭 단위(sessionStorage).
 */

const VISION_FLOW_KEY = 'cheokcheok:vision-flow';
const VISION_EXIT = new Set(['', 'landing', 'about', 'replay', 'test', 'graph']);

const visionCam = { stream: null, opening: null, error: '', off: false };
const visionCoach = {
  timer: 0,
  dictation: null,
  audio: null,
  ac: null,
  analyser: null,
  buf: null,
  meter: null,
  final: '',
  interim: '',
  note: '',
};

function visionFlowOn() {
  try { return sessionStorage.getItem(VISION_FLOW_KEY) === '1'; } catch (_) { return false; }
}

function visionFlowSet(on) {
  try {
    if (on) sessionStorage.setItem(VISION_FLOW_KEY, '1');
    else sessionStorage.removeItem(VISION_FLOW_KEY);
  } catch (_) { /* 사생활 모드 — 이번 화면만 */ }
}

function visionHasDeck() {
  return !!(typeof nf !== 'undefined' && nf && (
    nf.fileName || (nf.slideTitles && nf.slideTitles.length) || (typeof uploadedPdf !== 'undefined' && uploadedPdf)
  ));
}

/** #/vision — 자료가 있으면 그 발표의 리허설로, 없으면 새 연습으로. */
function renderVisionEntry(opts = {}) {
  // 통화 흐름은 끄지 않는다 — 발표는 이 배치(nfStep3 이 vision 을 먼저 본다)로 하고, 질문 코칭은
  // 부스 통화 배치(qa_live.js 가 callFlowOn 을 본다)로 이어져야 한다 (09-29 사용자: 「QA 에서 부스까지 자동 연결이 안 됨」).
  if (typeof callFlowSet === 'function') callFlowSet(true);
  visionFlowSet(true);
  const keep = !!(opts && opts.keepDeck) || visionHasDeck();
  if (!keep) {
    resetNf();
    resetQa();
    try { sessionStorage.removeItem('cheokcheok:chuckchuck-session'); } catch (_) { /* ignore */ }
  } else if ((Number(nf.step) || 0) < 2) {
    nf.step = 2;
    saveSession('new-flow', nf);
  }
  if (location.hash === '#/new' || location.hash === '#/new/') route();
  else location.replace('#/new');
}

function visionFlowOnRoute(key) {
  if (VISION_EXIT.has(key)) visionFlowSet(false);
  const keepCam = visionFlowOn() && key === 'new';
  visionFlowUnmount({ keepCam });
}

function visionCamErrorText(err) {
  const name = (err && err.name) || '';
  if (window.isSecureContext === false) return '카메라는 https 주소나 이 컴퓨터(127.0.0.1)에서만 열려요.';
  if (name === 'NotAllowedError' || name === 'SecurityError') return '카메라 권한이 막혀 있어요. 주소창 왼쪽 권한에서 카메라를 허용하면 내 모습이 보여요.';
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return '연결된 카메라가 없어요. 카메라를 꽂고 「카메라 켜기」를 눌러요.';
  if (name === 'NotReadableError' || name === 'AbortError') return '다른 앱이 카메라를 쓰고 있어요. 그 앱을 닫고 「카메라 켜기」를 눌러요.';
  return '카메라를 열지 못했어요. 「카메라 켜기」를 한 번 더 눌러요.';
}

async function visionCamEnsure() {
  if (visionCam.off) return null;
  if (visionCam.stream && visionCam.stream.getVideoTracks().some((t) => t.readyState === 'live')) return visionCam.stream;
  if (visionCam.opening) return visionCam.opening;
  if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) {
    visionCam.error = visionCamErrorText(null);
    visionCamPaint();
    return null;
  }
  visionCam.opening = navigator.mediaDevices.getUserMedia({
    video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } },
    audio: false,
  }).then((s) => {
    visionCam.stream = s;
    visionCam.error = '';
    return s;
  }).catch((err) => {
    visionCam.stream = null;
    visionCam.error = visionCamErrorText(err);
    return null;
  }).finally(() => {
    visionCam.opening = null;
    visionCamPaint();
  });
  return visionCam.opening;
}

function visionCamStop() {
  if (visionCam.stream) visionCam.stream.getTracks().forEach((t) => t.stop());
  visionCam.stream = null;
}

function visionCamPaint() {
  const video = $('#vrSelfVideo');
  const self = $('#vrSelf');
  const note = $('#vrSelfNote');
  const btn = $('#vrCamToggle');
  const live = !!visionCam.stream && !visionCam.off;
  if (video && video.srcObject !== (live ? visionCam.stream : null)) {
    video.srcObject = live ? visionCam.stream : null;
    if (live) video.play().catch(() => {});
  }
  if (self) self.dataset.camera = live ? 'on' : 'off';
  if (note) {
    note.textContent = visionCam.off
      ? '카메라를 껐어요. 켜면 내 모습 앞에 자료와 삐약이가 보여요.'
      : (visionCam.error || (visionCam.opening ? '카메라를 여는 중이에요' : ''));
  }
  if (btn) {
    btn.textContent = visionCam.off || !live ? '카메라 켜기' : '카메라 끄기';
    btn.setAttribute('aria-pressed', String(live));
  }
}

function visionCamToggle() {
  if (visionCam.stream && !visionCam.off) {
    visionCam.off = true;
    visionCamStop();
    visionCamPaint();
    return;
  }
  visionCam.off = false;
  visionCam.error = '';
  visionCamPaint();
  visionCamEnsure();
}

function visionCoachStop() {
  if (visionCoach.timer) clearInterval(visionCoach.timer);
  visionCoach.timer = 0;
  if (visionCoach.dictation) {
    try { visionCoach.dictation.stop(); } catch (_) { /* 이미 멈춤 */ }
  }
  visionCoach.dictation = null;
  if (visionCoach.audio) visionCoach.audio.getTracks().forEach((t) => t.stop());
  visionCoach.audio = null;
  if (visionCoach.ac && visionCoach.ac.state !== 'closed') visionCoach.ac.close().catch(() => {});
  visionCoach.ac = null;
  visionCoach.analyser = null;
  visionCoach.buf = null;
  visionCoach.meter = null;
  visionCoach.final = '';
  visionCoach.interim = '';
  visionCoach.note = '';
  if (visionCoach.reaction) {
    visionEnsureReactions();
    visionReactions.push(visionCoach.reaction);
    visionCoach.reaction = null;
    visionPersistCues();
  }
}

function visionFlowUnmount({ keepCam = false } = {}) {
  visionCoachStop();
  if (visionDockWatch) { visionDockWatch.disconnect(); visionDockWatch = null; }
  const layer = document.getElementById('vrCall');
  if (layer) layer.remove();
  document.body.classList.remove('vr-open');
  if (!keepCam) visionCamStop();
}

function visionCueText(cue) {
  const copy = (window.VisionCue && window.VisionCue.CUE_COPY) || {};
  return copy[cue] || '';
}

const VISION_REACTS = new Set(['fast', 'slow', 'quiet', 'loud']);
let visionReactions = [];
let visionReactionsReady = false;

function visionRecSec() {
  if (typeof nf !== 'undefined' && nf && nf.mic === 'on') return Math.round((Number(nf.sec) || 0) * 10) / 10;
  if (visionCoach.startedAt) return Math.round((performance.now() - visionCoach.startedAt) / 100) / 10;
  return 0;
}

function visionEnsureReactions() {
  if (visionReactionsReady) return;
  visionReactionsReady = true;
  if (typeof nf !== 'undefined' && nf && Array.isArray(nf.visionCues)) visionReactions = nf.visionCues.slice();
}

function visionPersistCues() {
  const list = visionReactions.slice();
  if (visionCoach.reaction) list.push(visionCoach.reaction);
  if (typeof nf === 'undefined' || !nf) return;
  nf.visionCues = list.slice(-80);
  nf.visionSeen = true;
  if (typeof saveSession === 'function') saveSession('new-flow', nf);
}

function visionResetReactions() {
  visionReactions = [];
  visionReactionsReady = true;
  visionCoach.reaction = null;
  if (typeof nf !== 'undefined' && nf) {
    nf.visionCues = [];
    if (typeof saveSession === 'function') saveSession('new-flow', nf);
  }
}

/** 표정이 바뀐 순간만 남긴다. 그 순간의 말 끝을 같이 적어, 리포트가 「이 말에서 귀가 아팠다」고 보여 주게 한다. */
function visionNoteReaction(cue) {
  visionEnsureReactions();
  const slide = (typeof nf !== 'undefined' && nf && Number(nf.slide)) || 1;
  const react = VISION_REACTS.has(cue);
  const open = visionCoach.reaction;
  if (open && open.cue === cue && open.slide_no === slide) return;
  if (open) visionReactions.push(open);
  const heard = visionCoachText().slice(-48).trim();
  visionCoach.reaction = react ? { slide_no: slide, sec: visionRecSec(), cue, text: heard } : null;
  visionPersistCues();
}

function visionPaintCue(cue) {
  const bird = $('#vrBird');
  const line = $('#vrLine');
  const status = $('#vrStatus');
  const text = visionCueText(cue);
  const react = VISION_REACTS.has(cue);
  if (bird) {
    bird.dataset.cue = cue || 'idle';
    bird.setAttribute('aria-label', react ? `삐약이, ${text}` : '삐약이');
  }
  if (line) {
    line.hidden = !react;
    line.textContent = react ? text : '';
  }
  if (status) {
    status.textContent = cue === 'listen' ? '잘 듣고 있어요' : (react ? text : '말하면 반응해요');
  }
  visionNoteReaction(cue || 'idle');
}

function visionPaintHear() {
  const el = $('#vrHear');
  if (!el) return;
  el.hidden = !visionCoach.note;
  el.textContent = visionCoach.note || '';
}

function visionArmEar() {
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return;
  if (!visionCoach.ac || visionCoach.ac.state === 'closed') visionCoach.ac = new AC();
  if (visionCoach.ac.state !== 'running') visionCoach.ac.resume().catch(() => {});
}

function visionReadLevel() {
  const s = visionCoach;
  if (!s.analyser || !s.buf) return null;
  if (s.ac && s.ac.state !== 'running') {
    s.ac.resume().catch(() => {});
    return null;
  }
  s.analyser.getFloatTimeDomainData(s.buf);
  let sum = 0;
  for (let i = 0; i < s.buf.length; i++) sum += s.buf[i] * s.buf[i];
  return Math.sqrt(sum / s.buf.length);
}

function visionCoachText() {
  return `${visionCoach.final} ${visionCoach.interim}`.replace(/\s+/g, ' ').trim();
}

function visionCoachSample() {
  const Cue = window.VisionCue;
  if (!Cue || !visionCoach.meter) return;
  const sample = { now: performance.now(), chars: Cue.countSpeechChars(visionCoachText()) };
  const level = visionReadLevel();
  if (level !== null) sample.level = level;
  const r = Cue.observeVision(visionCoach.meter, sample);
  visionCoach.meter = r.meter;
  visionPaintCue(r.cue);
  const cap = $('#vrCaption');
  if (cap) {
    const heard = visionCoachText();
    cap.textContent = heard ? heard.slice(-42) : '';
  }
}

async function visionOpenLevel() {
  if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) return;
  visionArmEar();
  try {
    const audio = await navigator.mediaDevices.getUserMedia({ audio: true });
    if (!document.getElementById('vrCall')) {
      audio.getTracks().forEach((t) => t.stop());
      return;
    }
    const ac = visionCoach.ac;
    if (!ac) return;
    if (visionCoach.audio) visionCoach.audio.getTracks().forEach((t) => t.stop());
    const analyser = ac.createAnalyser();
    analyser.fftSize = 1024;
    ac.createMediaStreamSource(audio).connect(analyser);
    visionCoach.audio = audio;
    visionCoach.analyser = analyser;
    visionCoach.buf = new Float32Array(analyser.fftSize);
    if (ac.state !== 'running') ac.resume().catch(() => {});
    visionCoach.note = '';
    visionPaintHear();
  } catch (_) {
    visionCoach.note = '마이크를 열지 못해서 삐약이가 말을 못 봐요. 「다시 듣기」를 눌러요.';
    visionPaintHear();
  }
}

function visionCoachStart() {
  visionCoachStop();
  const Cue = window.VisionCue;
  if (!Cue) {
    visionCoach.note = '반응 규칙을 불러오지 못했어요.';
    visionPaintHear();
    return;
  }
  visionArmEar();
  visionCoach.meter = Cue.createVisionMeter(performance.now());
  visionCoach.startedAt = performance.now();
  visionEnsureReactions();
  if (typeof nf !== 'undefined' && nf) {
    nf.visionSeen = true;
    if (typeof saveSession === 'function') saveSession('new-flow', nf);
  }
  visionPaintCue('idle');
  const bridge = window.ChuckchuckBridge;
  if (bridge && bridge.hasLiveDictation && bridge.hasLiveDictation()) {
    try {
      visionCoach.dictation = bridge.startLiveDictation({
        onText: ({ final, interim }) => {
          visionCoach.final = final || '';
          visionCoach.interim = interim || '';
          visionCoachSample();
        },
        onError: () => { visionCoach.dictation = null; },
      });
    } catch (_) { /* 받아쓰기가 없어도 마이크 파동으로 속도를 본다 */ }
  }
  visionOpenLevel();
  visionCoach.timer = setInterval(visionCoachSample, 40);
}

function visionPaws() {
  return `
    <svg class="vr-paws" viewBox="0 0 100 100" aria-hidden="true">
      <g class="vr-paw vr-paw-l">
        <path d="M14 28c-5 3-6 11-2 14 3 2 7 0 8-4" fill="var(--chick-body)" stroke="var(--chick-line)" stroke-width="2" stroke-linejoin="round"/>
        <ellipse cx="20" cy="34" rx="7" ry="5.4" fill="var(--chick-body)" stroke="var(--chick-line)" stroke-width="2"/>
      </g>
      <g class="vr-paw vr-paw-r">
        <path d="M86 28c5 3 6 11 2 14-3 2-7 0-8-4" fill="var(--chick-body)" stroke="var(--chick-line)" stroke-width="2" stroke-linejoin="round"/>
        <ellipse cx="80" cy="34" rx="7" ry="5.4" fill="var(--chick-body)" stroke="var(--chick-line)" stroke-width="2"/>
      </g>
    </svg>`;
}

function visionBirdHtml() {
  const chick = (window.Chatter && window.Chatter.chickSvg) ? window.Chatter.chickSvg('solar') : '';
  return `
    <div class="vr-bird" id="vrBird" data-cue="idle" aria-label="삐약이">
      <p class="vr-line" id="vrLine" hidden></p>
      <div class="vr-chickbox">
        <div class="ch-seat seated" data-mood="neutral">${chick}</div>
        ${visionPaws()}
      </div>
      <p class="vr-name">삐약이</p>
      <p class="vr-status" id="vrStatus">말하면 반응해요</p>
      <button type="button" class="btn vr-ear" id="vrEar">다시 듣기</button>
    </div>`;
}

const VISION_SLIDE_KEY = 'cheokcheok:vision-slide';
const visionSlide = { custom: false, portrait: false, x: 0, y: 0, w: 0, h: 0, opacity: 0.78 };

function visionSlideLoad() {
  try {
    const raw = sessionStorage.getItem(VISION_SLIDE_KEY);
    if (!raw) return;
    const data = JSON.parse(raw);
    if (typeof data.opacity === 'number') visionSlide.opacity = Math.min(1, Math.max(0.25, data.opacity));
    if (data.custom && [data.x, data.y, data.w, data.h].every((n) => typeof n === 'number')) {
      visionSlide.custom = true;
      visionSlide.portrait = !!data.portrait;
      visionSlide.x = data.x;
      visionSlide.y = data.y;
      visionSlide.w = data.w;
      visionSlide.h = data.h;
    }
  } catch (_) { /* 저장이 없으면 왼쪽 기본 자리 */ }
}

function visionSlideSave() {
  try {
    sessionStorage.setItem(VISION_SLIDE_KEY, JSON.stringify({
      custom: visionSlide.custom,
      x: visionSlide.x,
      y: visionSlide.y,
      w: visionSlide.w,
      h: visionSlide.h,
      portrait: !!visionSlide.portrait,
      opacity: visionSlide.opacity,
    }));
  } catch (_) { /* 사생활 모드 — 이번 화면만 */ }
}

/**
 * 자료 창이 떠 있는 층 — 비전 리허설(#vrCall), 아니면 리허설 흐름의 질문 화상판(#bqStage[data-flow="rehearsal"], js/rehearsal.js).
 * 화상판에서는 답 칸(.bc-dock)이 조작줄 자리다. 둘 다 창 전체를 덮는 층이라 저장한 자리(px)를 그대로 쓴다.
 */
function visionSlideHost() {
  return document.getElementById('vrCall') || document.querySelector('#bqStage[data-flow="rehearsal"]');
}

/**
 * 자료 창이 갈 수 있는 곳. 옮기기(⠿)·크기(◢) 손잡이가 창 **아래 왼쪽·오른쪽**에 있으므로
 * 창 아래 끝은 조작줄 위에, 왼쪽 끝은 화면 안에 둔다 — 예전엔 창 높이 −48px 까지 내려가
 * 손잡이가 조작줄 밑으로 숨어서 다시 못 잡았다 (09-30 labs/vision_flow).
 */
function visionSlideClamp(box) {
  const host = visionSlideHost();
  const width = host ? host.clientWidth : window.innerWidth;
  const height = host ? host.clientHeight : window.innerHeight;
  const dock = host && host.querySelector('.vr-dock, .bc-dock');
  let bottom = dock && host
    ? dock.getBoundingClientRect().top - host.getBoundingClientRect().top - 8
    : height - 8;
  // 화상판은 답 칸 위에 진행 칩이 한 줄 더 있다 — 그 위에서 멈춘다
  const prog = host && host.id === 'bqStage' && host.querySelector('.bc-prog .bq-prog');
  if (prog && prog.offsetParent) bottom = Math.min(bottom, prog.getBoundingClientRect().top - host.getBoundingClientRect().top - 8);
  // 화상판(리허설 질문)에서는 위 질문 카드 · 카메라 알약 줄 아래, 화면 안쪽에만 — 발표 때 위쪽에 둔 자리가 질문을 덮었다 (10-03 labs/rehearsal_flow)
  const onCall = !!host && host.id === 'bqStage';
  let top = 8;
  if (onCall) {
    const hostTop = host.getBoundingClientRect().top;
    // 사생활 알약도 — 알약이 창의 손잡이(불투명도 · 크기)를 덮어 눌리지 않았다 (10-03 점검 V2). 숨은 알약(폰 폭 · 카메라 꺼짐)은 상자가 없다
    const marks = [...host.querySelectorAll('.bc-ask:not([hidden]), .bc-side-row, .bq-top, .bc-privacy')]
      .filter((el) => el.getClientRects().length).map((el) => el.getBoundingClientRect().bottom - hostTop);
    top = Math.max(8, ...marks) + 8;
  }
  const w = Math.max(240, Math.min(box.w, width - 16));
  const x = onCall ? Math.min(Math.max(box.x, 8), width - w - 8) : Math.min(Math.max(box.x, 0), width - 72);
  // 비전 리허설 — 위 띠의 단추(카메라 · 나가기 …)와 가로로 겹치는 자리면 그 아래에서 멈춘다. 예전엔 y=8 까지 올라가
  // 단추들이 창 윗변을 덮었다 (10-03 점검 V6). 단추가 없는 가운데 위쪽은 그대로 쓸 수 있다
  if (host && host.id === 'vrCall') {
    const hr = host.getBoundingClientRect();
    [...host.querySelectorAll('.vr-top > :not(.vr-top-fill), .vr-top-fill > *')].forEach((el) => {
      const r = el.getBoundingClientRect();
      if (!r.width || r.right - hr.left <= x || r.left - hr.left >= x + w) return;
      top = Math.max(top, r.bottom - hr.top + 8);
    });
  }
  const h = Math.max(180, Math.min(box.h, bottom - top));
  const y = Math.min(Math.max(box.y, top), Math.max(top, bottom - h));
  return { x, y, w, h };
}

/** 세로 화면(아이패드 세로 · 폰)인가 — 가로에서 옮겨 둔 자리 · 크기를 세로에 그대로 쓰면 대화 · 자료를 덮는다 */
function visionSlidePortrait() {
  const host = visionSlideHost();
  const w = host ? host.clientWidth : window.innerWidth;
  const h = host ? host.clientHeight : window.innerHeight;
  return h > w;
}

function visionSlideRead(slide) {
  const host = visionSlideHost();
  const sr = slide.getBoundingClientRect();
  const hr = host ? host.getBoundingClientRect() : { left: 0, top: 0 };
  return { x: sr.left - hr.left, y: sr.top - hr.top, w: sr.width, h: sr.height };
}

function visionSlideApply(slide) {
  if (!slide) return;
  slide.style.setProperty('--vr-slide-alpha', String(visionSlide.opacity));
  const range = slide.querySelector('#vrSlideAlpha');
  if (range && document.activeElement !== range) range.value = String(Math.round(visionSlide.opacity * 100));
  // 옮겨 둔 자리는 그 자리를 정한 방향(가로 · 세로)에서만 쓴다 — 가로에서 옮긴 큰 창이 세로 화상판의 대화 말풍선을 덮었다 (10-03 점검 V6).
  // 다른 방향이면 그 화면의 기본 자리(작은 창)에 선다. 저장은 그대로라 원래 방향으로 돌아가면 옮긴 자리로 돌아간다
  if (visionSlide.custom && !!visionSlide.portrait === visionSlidePortrait()) {
    const box = visionSlideClamp(visionSlide);
    slide.style.left = `${box.x}px`;
    slide.style.top = `${box.y}px`;
    slide.style.width = `${box.w}px`;
    slide.style.height = `${box.h}px`;
    return;
  }
  const host = visionSlideHost();
  const slot = host && host.querySelector('.vr-slide-slot');
  if (!slot || !host) return;
  const sr = slot.getBoundingClientRect();
  const hr = host.getBoundingClientRect();
  if (sr.width < 8 || sr.height < 8) return;
  let height = sr.height;
  // 세로 비전 리허설의 기본 칸은 좁고 긴 기둥이다 — 창을 칸 높이대로 세우면 장(16:9)은 가운데 1/3 이고 나머지는 빈 흐림이 얼굴을 덮었다 (V6).
  // 장 비율만큼만 세우고 칸 위에 붙인다
  if (host.id === 'vrCall' && visionSlidePortrait()) {
    const cap = slide.querySelector('.vr-slide-cap');
    height = Math.min(sr.height, Math.round(sr.width * 9 / 16) + (cap ? cap.offsetHeight : 48) + 16);
  }
  slide.style.left = `${sr.left - hr.left}px`;
  slide.style.top = `${sr.top - hr.top}px`;
  slide.style.width = `${sr.width}px`;
  slide.style.height = `${height}px`;
}

/** 크기가 바뀐 뒤 장을 다시 그린다 — 비전 리허설은 지금 장, 화상판은 그쪽이 넘긴 함수 (visionSlideBind opts.repaint) */
let visionSlideRepaint = null;
function visionSlideRedraw() {
  if (visionSlideRepaint) { visionSlideRepaint(); return; }
  if (typeof paintRehearsalSlide === 'function' && typeof nf !== 'undefined') paintRehearsalSlide(nf.slide);
}

function visionSlideCommit(slide, box, { repaint = false } = {}) {
  const next = visionSlideClamp(box);
  visionSlide.custom = true;
  visionSlide.portrait = visionSlidePortrait();
  visionSlide.x = next.x;
  visionSlide.y = next.y;
  visionSlide.w = next.w;
  visionSlide.h = next.h;
  visionSlideApply(slide);
  visionSlideSave();
  if (repaint) visionSlideRedraw();
}

function visionSlideBind(layer, { repaint = null } = {}) {
  visionSlideRepaint = repaint;
  visionSlideLoad();
  const slide = layer.querySelector('#vrSlide');
  if (!slide) return;
  visionSlideApply(slide);
  const grip = slide.querySelector('#vrSlideDrag');
  const resize = slide.querySelector('#vrSlideResize');
  const alpha = slide.querySelector('#vrSlideAlpha');

  const track = (e, mode) => {
    if (e.button != null && e.button !== 0) return;
    const start = visionSlideRead(slide);
    const px = e.clientX;
    const py = e.clientY;
    slide.classList.add(mode === 'move' ? 'is-drag' : 'is-resize');
    const move = (ev) => {
      const dx = ev.clientX - px;
      const dy = ev.clientY - py;
      const next = mode === 'move'
        ? { x: start.x + dx, y: start.y + dy, w: start.w, h: start.h }
        : { x: start.x, y: start.y, w: start.w + dx, h: start.h + dy };
      const box = visionSlideClamp(next);
      visionSlide.custom = true;
      visionSlide.portrait = visionSlidePortrait();
      visionSlide.x = box.x;
      visionSlide.y = box.y;
      visionSlide.w = box.w;
      visionSlide.h = box.h;
      visionSlideApply(slide);
    };
    const up = () => {
      slide.classList.remove('is-drag', 'is-resize');
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      visionSlideSave();
      if (mode === 'resize') visionSlideRedraw();
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  if (grip) {
    grip.addEventListener('pointerdown', (e) => track(e, 'move'));
    grip.addEventListener('dblclick', () => {
      visionSlide.custom = false;
      visionSlideSave();
      visionSlideApply(slide);
      visionSlideRedraw();
    });
    grip.addEventListener('keydown', (e) => {
      const step = e.shiftKey ? 48 : 16;
      if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
      e.preventDefault();
      const start = visionSlideRead(slide);
      if (e.key === 'ArrowLeft') start.x -= step;
      if (e.key === 'ArrowRight') start.x += step;
      if (e.key === 'ArrowUp') start.y -= step;
      if (e.key === 'ArrowDown') start.y += step;
      visionSlideCommit(slide, start);
    });
  }
  if (resize) {
    resize.addEventListener('pointerdown', (e) => track(e, 'resize'));
    resize.addEventListener('keydown', (e) => {
      const step = e.shiftKey ? 48 : 16;
      if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
      e.preventDefault();
      const start = visionSlideRead(slide);
      if (e.key === 'ArrowLeft') start.w -= step;
      if (e.key === 'ArrowRight') start.w += step;
      if (e.key === 'ArrowUp') start.h -= step;
      if (e.key === 'ArrowDown') start.h += step;
      visionSlideCommit(slide, start, { repaint: true });
    });
  }
  if (alpha) {
    alpha.addEventListener('input', () => {
      const n = Number(alpha.value);
      if (!Number.isFinite(n)) return;
      visionSlide.opacity = Math.min(1, Math.max(0.25, n / 100));
      slide.style.setProperty('--vr-slide-alpha', String(visionSlide.opacity));
    });
    alpha.addEventListener('change', visionSlideSave);
  }
}

window.addEventListener('resize', () => {
  const host = visionSlideHost();
  const slide = host && host.querySelector('#vrSlide');
  if (slide) visionSlideApply(slide);
});

/* 조작줄 높이는 녹음 상태·창 폭에 따라 바뀐다(폰에서는 두 줄). 잰 값을 --vr-dock 에 넣어야
   앞 층(자료·삐약이)이 조작줄 밑으로 들어가지 않는다 — 고정 76px 이면 폰에서 「다시 듣기」가 가려졌다 */
let visionDockWatch = null;
function visionWatchDock(layer) {
  if (visionDockWatch) { visionDockWatch.disconnect(); visionDockWatch = null; }
  const dock = layer.querySelector('.vr-dock');
  if (!dock || !window.ResizeObserver) return;
  visionDockWatch = new ResizeObserver(() => {
    layer.style.setProperty('--vr-dock', `${Math.round(dock.getBoundingClientRect().height)}px`);
    const slide = layer.querySelector('#vrSlide');
    if (slide) visionSlideApply(slide);
  });
  visionDockWatch.observe(dock);
}

/** 녹음 중에 나가기로 했으면 이번 테이크를 멈춘다 — 안 그러면 홈에서도 녹음기 · 마이크가 돌았다 (10-03 점검 perf-1). resetNf 가 하는 멈춤과 같다 */
function visionStopTake() {
  if (typeof stopLiveRehearsal === 'function') stopLiveRehearsal();
  if (typeof clearTimers === 'function') clearTimers();
  if (typeof nf === 'undefined' || !nf) return;
  nf.mic = 'idle';
  nf.sec = 0;
  if (typeof saveSession === 'function') saveSession('new-flow', nf);
}

function visionFlowLeaveClassic() {
  visionFlowSet(false);
  visionFlowUnmount({ keepCam: false });
  if (location.hash === '#/new' || location.hash === '#/new/') route();
  else location.hash = '#/new';
}

function nfStep3Vision() {
  if (!uploadedPdf && (nf.previewPdf || nf.fileName) && !nf._previewLoading) {
    nf._previewLoading = true;
    ensurePreviewPdf(nfSlideDoc).then((pdf) => {
      nf._previewLoading = false;
      if (pdf && nf.step === 2 && visionFlowOn()) nfStep3Vision();
    }).catch(() => { nf._previewLoading = false; });
  }
  const nPages = rehearsalCount();
  if (!nf.slide || nf.slide < 1) nf.slide = 1;
  if (nf.slide > nPages) nf.slide = nPages;
  const titles = activeTitles();
  const titleAt = (i) => titles[i] || `${i + 1}번 슬라이드`;
  const bodies = activeBodies();
  const stageInner = uploadedPdf
    ? `<canvas id="slidePdfCanvas" class="vr-slide-canvas" aria-label="원본 PDF 슬라이드"></canvas>
       <div id="slideCardWrap" class="vr-slide-doc" style="display:none"></div>`
    : (bodies && bodies.length
      ? `<div id="slideCardWrap" class="vr-slide-doc">${slideCardHtml(nf.slide, titleAt(nf.slide - 1), bodies[nf.slide - 1])}</div>`
      : `<img id="slideImage" class="vr-slide-img" src="${activeImages()[nf.slide - 1] || ''}" alt="">`);

  // 리허설 흐름(#/rehearsal)에는 일반 앱으로 빠지는 「일반 리허설」 이 없다 — 눌렀다가 리허설 표시만 켜진 채 일반 #/new 에 떨어졌다 (10-03 점검 V3 · F2)
  const rehearsalTab = typeof rehearsalFlowOn === 'function' && rehearsalFlowOn();
  visionFlowUnmount({ keepCam: true });
  app.className = '';
  app.innerHTML = '';
  const layer = document.createElement('div');
  layer.id = 'vrCall';
  layer.className = 'vr-call';
  layer.innerHTML = `
    <div class="vr-self" id="vrSelf" data-camera="off">
      <video id="vrSelfVideo" autoplay muted playsinline></video>
      <p class="vr-self-note" id="vrSelfNote"></p>
    </div>
    <div class="vr-fore">
      <div class="vr-slide-slot" aria-hidden="true"></div>
      <div class="vr-gap" aria-hidden="true"></div>
      ${visionBirdHtml()}
    </div>
    <section class="vr-slide" id="vrSlide" aria-label="발표 자료">
      <div class="vr-slide-stage">
        ${stageInner}
        <button type="button" class="vr-side vr-side-prev" data-slide-nav="-1" aria-label="이전 슬라이드">‹</button>
        <button type="button" class="vr-side vr-side-next" data-slide-nav="1" aria-label="다음 슬라이드">›</button>
      </div>
      <footer class="vr-slide-cap">
        <button type="button" class="vr-drag" id="vrSlideDrag" aria-label="발표 자료 옮기기" title="끌어서 옮기기. 두 번 누르면 원래 자리">⠿</button>
        <strong id="slideTitle">${escapeHtml(titleAt(nf.slide - 1))}</strong>
        <span id="slideNo" class="num">${nf.slide} / ${nPages}</span>
        <label class="vr-alpha">
          <span>불투명도</span>
          <input id="vrSlideAlpha" type="range" min="25" max="100" value="78" aria-label="발표 자료 불투명도">
        </label>
      </footer>
      <p class="vr-caption" id="vrCaption" aria-live="off"></p>
      <button type="button" class="vr-resize" id="vrSlideResize" aria-label="발표 자료 크기 조절"></button>
    </section>
    <header class="vr-top">
      <span class="vr-pill vr-glass">비전 리허설</span>
      <span class="vr-top-fill">${precomputeNoteHtml()}</span>
      <button class="btn vr-glass" id="vrCamToggle" type="button">카메라 켜기</button>
      ${rehearsalTab ? '' : '<button class="btn vr-glass" id="vrClassic" type="button">일반 리허설</button>'}
      <a class="btn vr-glass" href="#/" id="vrLeave">나가기</a>
    </header>
    <p class="vr-hear vr-glass" id="vrHear" hidden></p>
    <div class="vr-dock vr-glass">
      <button type="button" class="btn vr-nav" data-slide-nav="-1">이전</button>
      <div class="vr-rec" id="recPanel"></div>
      <button type="button" class="btn vr-nav" data-slide-nav="1">다음</button>
    </div>`;
  document.body.appendChild(layer);
  document.body.classList.add('vr-open');
  visionWatchDock(layer);
  visionSlideBind(layer);

  const leave = $('#vrLeave');
  if (leave) leave.addEventListener('click', (e) => {
    // 리허설 흐름은 브라우저 확인 창(확인/취소) 대신 화면 안 시트(닫기 / 녹음 멈추고 나가기) — js/rehearsal.js
    if (rehearsalTab && typeof rehearsalVisionLeave === 'function') { e.preventDefault(); rehearsalVisionLeave(layer); return; }
    if (nf.mic !== 'on') return;
    if (!window.confirm('발표를 녹음하고 있어요. 나가면 이번 녹음은 남지 않아요. 나갈까요?')) { e.preventDefault(); return; }
    visionStopTake();
  });
  const classic = $('#vrClassic');
  if (classic) classic.addEventListener('click', () => {
    if (nf.mic === 'on' && !window.confirm('발표를 녹음하고 있어요. 일반 화면으로 바꿔도 녹음은 이어져요. 바꿀까요?')) return;
    visionFlowLeaveClassic();
  });
  const cam = $('#vrCamToggle');
  if (cam) cam.addEventListener('click', () => { visionArmEar(); visionCamToggle(); });
  const ear = $('#vrEar');
  if (ear) ear.addEventListener('click', () => { visionArmEar(); visionCoachStart(); });
  layer.addEventListener('pointerdown', visionArmEar);

  visionCamPaint();
  visionCamEnsure();
  renderRecPanel();
  // 리허설 흐름(#/rehearsal)이면 「발표 마치고 질문 준비하기」 옆에 「녹음본을 넣어서 발표 마치기」 (js/rehearsal.js)
  if (typeof rehearsalFlowOn === 'function' && rehearsalFlowOn() && typeof rehearsalVisionDock === 'function') rehearsalVisionDock(layer);
  bindRehearsalNav();
  syncRehearsalNav();
  paintRehearsalSlide(nf.slide);
  startPrecomputeNoteTimer();
  if (nf.mic === 'on' && !ccRuntime) startRecClock();
  visionCoachStart();
}
