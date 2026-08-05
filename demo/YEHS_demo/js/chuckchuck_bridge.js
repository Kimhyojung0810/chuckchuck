/**
 * 데모 UI와 chuckchuck API/SDK를 연결하는 다리입니다.
 * 파싱·녹음·STT·개념 추출 요청을 여기서 보냅니다.
 */

import {
  RehearsalRecorder,
  formatMarkLog,
  PresentationRecorder,
  SlideMarkTracker,
} from '/sdk/index.js';

const STORE_KEY = 'cheokcheok:chuckchuck-session';

/** sessionStorage 용량을 넘기지 않도록 단어 배열을 뺀 요약본 */
function slimTranscript(t) {
  if (!t || typeof t !== 'object') return t;
  return {
    full_text: t.full_text || '',
    provider: t.provider || '',
    duration_sec: t.duration_sec || 0,
    words: Array.isArray(t.words) ? t.words.map((w) => ({
      text: w.text, start_sec: w.start_sec, end_sec: w.end_sec,
    })) : [],
    by_slide: Array.isArray(t.by_slide) ? t.by_slide.map((s) => ({
      slide_no: s.slide_no,
      visit: s.visit || 1,
      start_sec: s.start_sec,
      end_sec: s.end_sec,
      text: s.text || '',
      // words 는 UI에 필수가 아니라 생략 (용량)
    })) : [],
  };
}

export function saveChuckSession(partial) {
  const prev = loadChuckSession() || {};
  const next = { ...prev, ...partial, updatedAt: Date.now() };
  if (next.transcript) next.transcript = slimTranscript(next.transcript);
  try {
    sessionStorage.setItem(STORE_KEY, JSON.stringify(next));
  } catch (_) {
    // quota — transcript 만 더 줄여 재시도
    try {
      const lean = {
        ...next,
        transcript: next.transcript
          ? { ...next.transcript, words: [], by_slide: (next.transcript.by_slide || []).map((s) => ({
            slide_no: s.slide_no, visit: s.visit, start_sec: s.start_sec, end_sec: s.end_sec, text: s.text,
          })) }
          : null,
      };
      sessionStorage.setItem(STORE_KEY, JSON.stringify(lean));
    } catch (__) { /* ignore */ }
  }
  return next;
}

export function loadChuckSession() {
  try { return JSON.parse(sessionStorage.getItem(STORE_KEY)); }
  catch (_) { return null; }
}

export function attachRehearsalRuntime(nf, hooks = {}) {
  const totalSlides = hooks.totalSlides
    || (nf.slideTitles && nf.slideTitles.length)
    || (window.DATA && DATA.slideTitles && DATA.slideTitles.length)
    || 23;

  if (typeof RehearsalRecorder === 'function') {
    const rec = new RehearsalRecorder({
      totalSlides,
      onTick: (sec) => {
        nf.sec = Math.floor(sec);
        if (typeof hooks.onTick === 'function') hooks.onTick(sec);
      },
      onSlideChange: () => {},
      onLevel: hooks.onLevel || null,
    });

    return {
      recorder: rec,
      marks: null,

      async start(slideNo = 1) {
        rec.currentSlide = slideNo;
        await rec.start();
        nf.mic = 'on';
        nf.sec = 0;
        nf.visits = { [slideNo]: 1 };
        nf.log = [{ txt: `00:00 → ${slideNo}번 슬라이드`, re: false }];
        saveChuckSession({ recording: true, slide: slideNo });
      },

      goTo(slideNo) {
        if (rec.state !== 'recording' && rec.state !== 'paused') return null;
        const before = rec.currentSlide;
        rec.goTo(slideNo);
        if (rec.currentSlide === before) return null;
        const tl = rec.timeline();
        const last = tl[tl.length - 1];
        const entry = last
          ? { txt: last.label, re: !!last.revisit }
          : { txt: `${String(Math.floor(rec.elapsed() / 60)).padStart(2, '0')}:${String(Math.floor(rec.elapsed() % 60)).padStart(2, '0')} → ${slideNo}번 슬라이드`, re: false };
        if (!Array.isArray(nf.log)) nf.log = [];
        const prev = nf.log[nf.log.length - 1];
        if (!prev || prev.txt !== entry.txt) nf.log.push(entry);
        nf.visits = { ...rec._visits };
        return entry;
      },

      async finish() {
        const { audioBlob, marks, durationSec } = await rec.stop();
        const payload = {
          marks,
          mimeType: audioBlob.type,
          durationSec,
          recording: false,
          _blob: audioBlob,
        };
        saveChuckSession({
          marks,
          mimeType: audioBlob.type,
          durationSec,
          recording: false,
        });
        return payload;
      },
    };
  }

  const recorder = new PresentationRecorder({
    onTick: (sec) => {
      nf.sec = Math.floor(sec);
      if (typeof hooks.onTick === 'function') hooks.onTick(sec);
    },
    onState: (s) => {
      if (typeof hooks.onState === 'function') hooks.onState(s);
    },
  });
  const marksTracker = new SlideMarkTracker({
    getElapsedSec: () => recorder.elapsedSec,
  });

  return {
    recorder,
    marks: marksTracker,

    async start(slideNo = 1) {
      await recorder.start();
      marksTracker.start(slideNo);
      nf.mic = 'on';
      nf.sec = 0;
      nf.visits = { [slideNo]: 1 };
      nf.log = [{
        txt: formatMarkLog({ sec: 0, slide: slideNo, visit: 1, back: false }),
        re: false,
      }];
      saveChuckSession({ recording: true, slide: slideNo });
    },

    goTo(slideNo) {
      if (recorder.state !== 'recording') return null;
      marksTracker.goTo(slideNo);
      const last = marksTracker.log[marksTracker.log.length - 1];
      const entry = { txt: formatMarkLog(last), re: !!last.back };
      nf.log.push(entry);
      nf.visits = { ...marksTracker.visits };
      return entry;
    },

    async finish() {
      const markList = marksTracker.finish();
      const { blob, mimeType, durationSec } = await recorder.stop();
      const payload = {
        marks: markList,
        mimeType,
        durationSec,
        recording: false,
        _blob: blob,
      };
      saveChuckSession({
        marks: markList,
        mimeType,
        durationSec,
        recording: false,
      });
      return payload;
    },
  };
}

/** F-01: 파일 업로드 또는 fixture 샘플 → SlideDoc */
export async function parseDocument({ file = null, fixture = false } = {}) {
  let res;
  if (fixture || !file) {
    res = await fetch(apiBase() + '/api/v1/parse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fixture: true }),
    });
  } else {
    const fd = new FormData();
    fd.append('document', file, file.name);
    res = await fetch(apiBase() + '/api/v1/parse', { method: 'POST', body: fd });
  }
  const data = await res.json();
  if (!res.ok || data.error) {
    throw new Error(data.message || data.error || `parse HTTP ${res.status}`);
  }
  saveChuckSession({
    slideDocMeta: {
      file_name: data.file_name,
      total_slides: data.total_slides,
    },
  });
  return data;
}


// 순서가 규칙이다. codecs 파라미터에 opus 가 붙는 'audio/webm;codecs=opus'(우리 녹음기
// 기본 출력)가 ogg 로 새지 않게 컨테이너를 코덱보다 먼저 본다.
const AUDIO_EXT_BY_MIME = [
  [/webm/, '.webm'],
  [/mp4|m4a|aac/, '.m4a'],
  [/mpeg|mp3/, '.mp3'],
  [/wav/, '.wav'],
  [/ogg|opus/, '.ogg'],
];

/**
 * 서버가 임시 파일에 붙일 확장자.
 * 업로드 파일은 이름의 확장자가 가장 정확하고, 없으면 MIME 으로 추정한다.
 * 둘 다 없을 때만 녹음 기본값(.webm)으로 떨어진다 — 확장자가 거짓말하면 STT 가 파일을 못 읽는다.
 */
export function audioExt({ fileName = '', mimeType = '' } = {}) {
  const m = /\.([a-z0-9]{2,5})$/i.exec(String(fileName || ''));
  if (m) return `.${m[1].toLowerCase()}`;
  const mt = String(mimeType || '').toLowerCase();
  for (const [re, ext] of AUDIO_EXT_BY_MIME) {
    if (re.test(mt)) return ext;
  }
  return '.webm';
}


async function readJson(res, label) {
  const text = await res.text();
  if (!text || !String(text).trim()) {
    throw new Error(`${label} 응답이 비어 있어요 (HTTP ${res.status})`);
  }
  try {
    return JSON.parse(text);
  } catch (e) {
    throw new Error(`${label} 응답을 읽지 못했어요 (HTTP ${res.status}): ${String(text).slice(0, 180)}`);
  }
}

/** F-05(+F-06): 녹음 → Transcript, slideDoc 있으면 ConceptDoc */
export async function runPreparePipeline({ marks, blob, mimeType, fileName, slideDoc, context, onProgress }) {
  const report = (phase, detail = '', extra = {}) => {
    if (typeof onProgress === 'function') {
      try { onProgress({ phase, detail, ...extra }); } catch (_) { /* UI hook */ }
    }
  };

  report('encoding', '오디오 준비 중');
  const audio_base64 = blob ? await blobToBase64(blob) : null;
  const ext = audioExt({ fileName, mimeType });

  report('stt', 'A.X STT로 음성을 글로 바꾸는 중');
  const sttRes = await fetch(apiBase() + '/api/v1/transcribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      marks: marks || [],
      audio_base64,
      ext,
    }),
  });
  const transcript = await readJson(sttRes, "STT");
  if (!sttRes.ok || transcript.error) {
    throw new Error(transcript.message || transcript.error || `transcribe HTTP ${sttRes.status}`);
  }
  report('stt_done', `단어 ${(transcript.words || []).length}개 · 슬라이드 구간 ${(transcript.by_slide || []).length}개`, { transcript });

  let concepts = null;
  let conceptsError = null;
  if (slideDoc) {
    report('concepts', '발표자료 개념 추출 중 (F-06)', { transcript });
    try {
      // concepts 요청에는 단어 배열을 빼 본문 크기를 줄인다
      const transcriptForConcepts = slimTranscript(transcript);
      const cRes = await fetch(apiBase() + '/api/v1/concepts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          slide_doc: slideDoc,
          context: context || {},
          transcript: transcriptForConcepts,
        }),
      });
      concepts = await readJson(cRes, "concepts");
      if (!cRes.ok || concepts.error) {
        throw new Error(concepts.message || concepts.error || `concepts HTTP ${cRes.status}`);
      }
      report('concepts_done', `개념 슬라이드 ${(concepts.slides || []).length}장`, { transcript, concepts });
    } catch (err) {
      // STT 성공분은 유지. 개념 실패는 부분 결과로 반환 (전체 throw 하지 않음)
      conceptsError = err.message || String(err);
      concepts = null;
      saveChuckSession({ transcript, concepts: null, conceptsError });
      report('concepts_error', conceptsError, { transcript, concepts: null, conceptsError });
    }
  }

  // F-07 그래프 + F-11 정합 판정 — 실패해도 STT·개념까지는 살린다 (부분 결과)
  let graph = null;
  let alignment = null;
  let graphError = null;
  let alignError = null;
  let flowError = null;
  if (concepts) {
    try {
      report('graph', '개념 그래프 구성 중 (F-07)', { transcript, concepts });
      const gRes = await fetch(apiBase() + '/api/v1/graph', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ concept_doc: concepts, slide_doc: slideDoc, context: context || {} }),
      });
      graph = await readJson(gRes, "graph");
      if (!gRes.ok || graph.error) {
        throw new Error(graph.message || graph.error || `graph HTTP ${gRes.status}`);
      }
      report('graph_done', `개념 ${(graph.nodes || []).length}개 · 연결 ${(graph.edges || []).length}개`, { transcript, concepts, graph });

      report('align', '발표와 자료 대조 중 (F-11)', { transcript, concepts, graph });
      const aRes = await fetch(apiBase() + '/api/v1/alignment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ graph, transcript: slimTranscript(transcript), context: context || {} }),
      });
      alignment = await readJson(aRes, "alignment");
      if (!aRes.ok || alignment.error) {
        throw new Error(alignment.message || alignment.error || `alignment HTTP ${aRes.status}`);
      }
      report('align_done', `정합 판정 ${(alignment.items || []).length}개`, { transcript, concepts, graph, alignment });
    } catch (err) {
      const msg = err.message || String(err);
      if (!graph || graph.error) { graph = null; graphError = msg; }
      else { alignError = msg; }
      alignment = null;
      report('align_error', msg, { transcript, concepts, graph });
    }
  }

  // F-11 파생 흐름 비교 — LLM 없는 결정적 계산이라 실패해도 앞 결과는 그대로 살린다
  let flow = null;
  if (graph && alignment) {
    try {
      report('flow', '자료 흐름과 발표 흐름 대조 중', { transcript, concepts, graph, alignment });
      const fRes = await fetch(apiBase() + '/api/v1/flow', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ graph, alignment }),
      });
      flow = await readJson(fRes, "flow");
      if (!fRes.ok || flow.error) {
        throw new Error(flow.message || flow.error || `flow HTTP ${fRes.status}`);
      }
      report('flow_done', `흐름 판정 ${(flow.issues || []).length}개`, { transcript, concepts, graph, alignment, flow });
    } catch (err) {
      flow = null;
      flowError = err.message || String(err);
      report('flow_error', flowError, { transcript, concepts, graph, alignment });
    }
  }


  // F-13 점수 — LLM 없는 결정적 계산
  let score = null;
  if (alignment) {
    try {
      report('score', '발표 점수 계산 중', { transcript, concepts, graph, alignment, flow });
      const sRes = await fetch(apiBase() + '/api/v1/score', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alignment, flow }),
      });
      score = await readJson(sRes, "score");
      if (!sRes.ok || score.error) {
        throw new Error(score.message || score.error || `score HTTP ${sRes.status}`);
      }
      report('score_done', `${score.score}점 (${score.basis})`,
        { transcript, concepts, graph, alignment, flow, score });
    } catch (err) {
      score = null;
      report('score_error', err.message || String(err), { transcript, concepts, graph, alignment, flow });
    }
  }

  // F-17·18·19 — 음성 습관·시간 배분·종합 리포트 (실패해도 STT까지는 유지)
  // callers: app.js runPreparePipeline onProgress / then; APIs /api/v1/pace|habits|report
  let pace = null;
  let habits = null;
  let voiceReport = null;
  const slim = slimTranscript(transcript);
  try {
    report('pace', '말 속도·시간 배분 계산 중 (F-17)', { transcript, concepts, graph, alignment, flow });
    const pRes = await fetch(apiBase() + '/api/v1/pace', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        transcript: slim,
        context: context || {},
        concept_doc: concepts || null,
      }),
    });
    pace = await readJson(pRes, "pace");
    if (!pRes.ok || pace.error) {
      throw new Error(pace.message || pace.error || `pace HTTP ${pRes.status}`);
    }
    report('pace_done', `배분 ${(pace.slides || []).length}장 · 실제 ${Math.round(pace.actual_sec || 0)}초`, {
      transcript, concepts, graph, alignment, flow, pace,
    });

    report('habits', '음성 습관 신호 추출 중 (F-18)', { transcript, concepts, graph, alignment, flow, pace });
    const hRes = await fetch(apiBase() + '/api/v1/habits', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcript: slim }),
    });
    habits = await readJson(hRes, "habits");
    if (!hRes.ok || habits.error) {
      throw new Error(habits.message || habits.error || `habits HTTP ${hRes.status}`);
    }
    report('habits_done', `REP ${habits.repeat_cnt || 0} · FIL ${habits.filler_cnt || 0} · PAUSE ${habits.pause_cnt || 0}`, {
      transcript, concepts, graph, alignment, flow, pace, habits,
    });

    report('voice_report', '종합 진단 리포트 작성 중 (F-19)', {
      transcript, concepts, graph, alignment, flow, pace, habits,
    });
    const rRes = await fetch(apiBase() + '/api/v1/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pace, habits, context: context || {} }),
    });
    voiceReport = await readJson(rRes, "report");
    if (!rRes.ok || voiceReport.error) {
      throw new Error(voiceReport.message || voiceReport.error || `report HTTP ${rRes.status}`);
    }
    report('voice_report_done', voiceReport.one_liner || `점수 ${voiceReport.score}`, {
      transcript, concepts, graph, alignment, flow, pace, habits, report: voiceReport,
    });
  } catch (err) {
    report('voice_report_error', err.message || String(err), {
      transcript, concepts, graph, alignment, flow, pace, habits,
    });
  }

  // 어디서 멈췄는지 한 줄로. '완료' 라고만 말하면 사용자가 오지 않을 결과를 기다린다.
  const firstFailure =
    (conceptsError && ['F-06 개념 추출', conceptsError])
    || (graphError && ['F-07 개념 그래프', graphError])
    || (alignError && ['F-11 정합 판정', alignError])
    || (flowError && ['흐름 비교', flowError])
    || null;
  const payload = {
    transcript, concepts, conceptsError,
    graph, alignment, flow, score, pace, habits, report: voiceReport,
    graphError, alignError, flowError,
    failedStage: firstFailure ? firstFailure[0] : null,
  };
  report(
    firstFailure ? 'partial' : 'done',
    firstFailure ? `${firstFailure[0]} 실패 — ${firstFailure[1]}` : '준비 완료',
    payload,
  );
  saveChuckSession({ transcript, concepts, conceptsError });
  return payload;
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const s = String(reader.result || '');
      resolve(s.includes(',') ? s.split(',')[1] : s);
    };
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

/* ── F-08/F-09 실전 QA (플랫 질문 생성 + 판정) ──
 * 데모 브리지(demo.bridge)는 /api/v1/questions 와 body.question 폴백 판정을 제공한다.
 * 세션 파이프라인(runQaLivePipeline)은 FastAPI 전용 — 여기선 쓰지 않는다.
 */

/* ── 백엔드 주소 ───────────────────────────────────────────────────────────
 * 프론트를 Netlify 같은 정적 호스팅에 올리면 백엔드는 다른 오리진에 있다.
 * 그때 상대경로로 부르면 정적 호스팅으로 가서 404 가 난다. 모든 API 호출이
 * 이 한 곳을 지나게 해서 배포 환경만 바꿔 끼울 수 있게 한다.
 *
 * 우선순위 (앞이 이긴다):
 *   1. ?api=https://... 쿼리 — 한 번 주면 sessionStorage 에 남는다 (디버깅용)
 *   2. window.CHUCKCHUCK_API_BASE — js/config.js 에서 배포마다 지정
 *   3. 같은 오리진 — 로컬(demo.bridge 가 화면과 API 를 같이 서빙)에서의 기본
 *
 * 백엔드는 https 여야 한다. 프론트가 https 인데 백엔드가 http 면 브라우저가
 * mixed content 로 요청 자체를 막는다.
 */
const QA_API_BASE_KEY = 'cheokcheok:qaApiBase';
const API_FALLBACK = 'http://127.0.0.1:8787';   // demo.bridge 기본 포트

function configuredApiBase() {
  try {
    const v = window.CHUCKCHUCK_API_BASE;
    return typeof v === 'string' && v.trim() ? v.trim().replace(/\/+$/, '') : '';
  } catch (_) { return ''; }
}

function defaultApiBase() {
  try {
    return location.protocol.startsWith('http') ? location.origin : API_FALLBACK;
  } catch (_) { return API_FALLBACK; }
}

/** 모든 /api/v1/* 요청이 붙는 접두사. 끝에 슬래시가 없다. */
export function apiBase() {
  try {
    const q = new URLSearchParams(location.search).get('api');
    if (q) sessionStorage.setItem(QA_API_BASE_KEY, q.replace(/\/+$/, ''));
    return sessionStorage.getItem(QA_API_BASE_KEY) || configuredApiBase() || defaultApiBase();
  } catch (_) { return configuredApiBase() || defaultApiBase(); }
}

/** 예전 이름. QA 전용이었으나 지금은 전체 공통이라 apiBase 와 같다. */
export const qaApiBase = apiBase;

export function setQaApiBase(url) {
  try {
    const v = (url || '').replace(/\/+$/, '');
    // 지우면 config.js / 같은 오리진으로 되돌아간다
    if (v) sessionStorage.setItem(QA_API_BASE_KEY, v);
    else sessionStorage.removeItem(QA_API_BASE_KEY);
  } catch (_) { /* storage unavailable */ }
}

/** 판정 한계 시간. 없으면 「판정 중…」에서 버튼이 전부 잠긴 채 출구가 없다. */
const QA_TIMEOUT_MS = 30000;

/** 질문 생성 한계 시간. 없으면 화면이 영원히 로딩에 갇힌다. */
const QUESTIONS_TIMEOUT_MS = 60000;

/**
 * 타임아웃이 있는 fetch. 응답이 안 오는 경우를 **반드시** 오류로 끝낸다 —
 * 매달린 요청은 화면의 busy 플래그를 영영 안 풀어 준다.
 */
async function fetchWithTimeout(url, opts, timeoutMs, label) {
  const control = new AbortController();
  const timer = setTimeout(() => control.abort(), timeoutMs);
  try {
    return await fetch(url, { ...opts, signal: control.signal });
  } catch (err) {
    if (err && err.name === 'AbortError') {
      throw new Error(`${label}이(가) ${Math.round(timeoutMs / 1000)}초 안에 끝나지 않았어요.`);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

async function qaApi(path, { method = 'GET', json, form, timeoutMs = QA_TIMEOUT_MS } = {}) {
  const opts = { method };
  if (json !== undefined) {
    opts.headers = { 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(json);
  } else if (form) {
    opts.body = form;
  }
  const res = await fetchWithTimeout(qaApiBase() + path, opts, timeoutMs, '요청');
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) {
    const d = data.detail && typeof data.detail === 'object' ? data.detail : data;
    const err = new Error(d.message || d.error || `HTTP ${res.status}`);
    err.code = d.error || '';
    err.status = res.status;
    throw err;
  }
  return data;
}

/**
 * 세션 아티팩트를 브리지에 한 번 등록한다.
 *
 * 등록해 두면 질문 생성·판정이 `session_id` 만 보내면 된다. 판정마다 그래프·발화를
 * 통째로 다시 올리던 것을 없애는 자리다. 브리지를 재시작하면 사라지므로,
 * 호출부는 `session_missing` 을 받으면 다시 등록하고 재시도한다.
 */
export async function registerSessionArtifacts(sessionId, artifacts) {
  if (!sessionId) throw new Error('session_id 가 필요해요.');
  const { graph, alignment, flow, transcript, context } = artifacts || {};
  return qaApi('/api/v1/session/artifacts', {
    method: 'POST',
    json: {
      session_id: sessionId,
      graph: graph || null,
      alignment: alignment || null,
      flow: flow || null,
      transcript: transcript ? slimTranscript(transcript) : null,
      context: context || null,
    },
  });
}

/** F-08: 내 그래프·정합으로 예상 질문을 만든다 (플랫 경로) */
export async function buildQuestions({ graph, alignment, flow, transcript, context, track, sessionId }) {
  // apiBase() 를 빼면 안 된다 — fetchWithTimeout 은 URL 을 그대로 쓴다.
  // 같은 오리진에서는 멀쩡히 돌지만 프론트/백엔드를 나눠 올리면 404 로 죽는다.
  const res = await fetchWithTimeout(apiBase() + '/api/v1/questions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId || null,
      graph,
      alignment,
      flow: flow || null,
      transcript: transcript ? slimTranscript(transcript) : null,
      context: context || {},
      track: track || '10',
    }),
  }, QUESTIONS_TIMEOUT_MS, '질문 생성');
  const doc = await res.json();
  if (!res.ok || doc.error) {
    throw new Error(doc.message || doc.error || `questions HTTP ${res.status}`);
  }
  return doc;
}

/**
 * F-09 답변 판정.
 *
 * question 을 같이 보낸다 — 브리지가 질문 본문으로 판정하기 때문이다.
 * **자료 근거(graph·alignment·transcript)도 반드시 실린다.** 없으면 "자료와 어긋난다"를
 * 대조할 원본이 없고 함정 질문의 핵심 규칙(잘못된 전제를 바로잡았는가)이 짐작이 된다.
 * 평소에는 session_id 로만 보내고, 세션이 날아갔으면(브리지 재시작) 다시 등록하고 재시도한다.
 */
export async function judgeQaAnswer(sessionId, { questionId, answer, history, question, giveUp, artifacts }) {
  const sid = sessionId || 'flat';
  const body = {
    session_id: sid,
    question_id: questionId,
    answer,
    history: history || [],
    question: question || null,
    give_up: !!giveUp,
  };
  const path = `/api/v1/sessions/${sid}/qa/judge`;
  try {
    return await qaApi(path, { method: 'POST', json: body });
  } catch (err) {
    // 세션이 비었을 때만 재등록한다. 아티팩트가 아예 없으면 그대로 올린다 —
    // 근거 없이 조용히 판정하느니 실패가 낫다.
    if (err.code !== 'session_missing' || !artifacts) throw err;
    await registerSessionArtifacts(sid, artifacts);
    return qaApi(path, { method: 'POST', json: body });
  }
}

window.ChuckchuckBridge = {
  attachRehearsalRuntime,
  parseDocument,
  runPreparePipeline,
  audioExt,
  saveChuckSession,
  loadChuckSession,
  qaApiBase,
  setQaApiBase,
  buildQuestions,
  judgeQaAnswer,
  registerSessionArtifacts,
  RehearsalRecorder,
  PresentationRecorder,
  SlideMarkTracker,
  formatMarkLog,
};

console.info('[chuckchuck] SDK bridge ready');
