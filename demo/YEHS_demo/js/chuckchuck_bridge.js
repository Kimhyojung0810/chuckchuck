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
    res = await fetch('/api/v1/parse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fixture: true }),
    });
  } else {
    const fd = new FormData();
    fd.append('document', file, file.name);
    res = await fetch('/api/v1/parse', { method: 'POST', body: fd });
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

/** F-05(+F-06): 녹음 → Transcript, slideDoc 있으면 ConceptDoc */
export async function runPreparePipeline({ marks, blob, mimeType, slideDoc, context, onProgress }) {
  const report = (phase, detail = '', extra = {}) => {
    if (typeof onProgress === 'function') {
      try { onProgress({ phase, detail, ...extra }); } catch (_) { /* UI hook */ }
    }
  };

  report('encoding', '오디오 준비 중');
  const audio_base64 = blob ? await blobToBase64(blob) : null;
  const ext = (mimeType || '').includes('mp4') ? '.m4a' : '.webm';

  report('stt', 'A.X STT로 음성을 글로 바꾸는 중');
  const sttRes = await fetch('/api/v1/transcribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      marks: marks || [],
      audio_base64,
      ext,
    }),
  });
  const transcript = await sttRes.json();
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
      const cRes = await fetch('/api/v1/concepts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          slide_doc: slideDoc,
          context: context || {},
          transcript: transcriptForConcepts,
        }),
      });
      concepts = await cRes.json();
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
  if (concepts) {
    try {
      report('graph', '개념 그래프 구성 중 (F-07)', { transcript, concepts });
      const gRes = await fetch('/api/v1/graph', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ concept_doc: concepts, slide_doc: slideDoc, context: context || {} }),
      });
      graph = await gRes.json();
      if (!gRes.ok || graph.error) {
        throw new Error(graph.message || graph.error || `graph HTTP ${gRes.status}`);
      }
      report('graph_done', `개념 ${(graph.nodes || []).length}개 · 연결 ${(graph.edges || []).length}개`, { transcript, concepts, graph });

      report('align', '발표와 자료 대조 중 (F-11)', { transcript, concepts, graph });
      const aRes = await fetch('/api/v1/alignment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ graph, transcript: slimTranscript(transcript), context: context || {} }),
      });
      alignment = await aRes.json();
      if (!aRes.ok || alignment.error) {
        throw new Error(alignment.message || alignment.error || `alignment HTTP ${aRes.status}`);
      }
      report('align_done', `정합 판정 ${(alignment.items || []).length}개`, { transcript, concepts, graph, alignment });
    } catch (err) {
      if (graph && graph.error) graph = null;
      alignment = null;
      report('align_error', err.message || String(err), { transcript, concepts, graph });
    }
  }

  // F-11 파생 흐름 비교 — LLM 없는 결정적 계산이라 실패해도 앞 결과는 그대로 살린다
  let flow = null;
  if (graph && alignment) {
    try {
      report('flow', '자료 흐름과 발표 흐름 대조 중', { transcript, concepts, graph, alignment });
      const fRes = await fetch('/api/v1/flow', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ graph, alignment }),
      });
      flow = await fRes.json();
      if (!fRes.ok || flow.error) {
        throw new Error(flow.message || flow.error || `flow HTTP ${fRes.status}`);
      }
      report('flow_done', `흐름 판정 ${(flow.issues || []).length}개`, { transcript, concepts, graph, alignment, flow });
    } catch (err) {
      flow = null;
      report('flow_error', err.message || String(err), { transcript, concepts, graph, alignment });
    }
  }

  report('done', conceptsError ? 'STT 완료 · 개념 추출 실패' : '준비 완료', {
    transcript,
    concepts,
    conceptsError,
    graph,
    alignment,
    flow,
  });
  saveChuckSession({ transcript, concepts, conceptsError });
  return { transcript, concepts, conceptsError, graph, alignment, flow };
}

/* ── server-test(v0.2 · 세션·잡 API) 연동 — QA 실전 모드 ──
 * 문서 업로드(또는 임의 녹음 파일) → parse → stt → concepts → graph → questions
 * 판정(judge)은 대화형이라 동기 호출.
 */

const QA_API_BASE_KEY = 'cheokcheok:qaApiBase';
// 실전 QA 는 세션 라우트(/api/v1/sessions/...)가 필요하므로 FastAPI 서버(python -m server)를
// 가리킨다. 세션 없는 데모 브리지(python -m demo.bridge, 8787)로는 이 흐름이 돌지 않는다.
const QA_API_DEFAULT = 'http://localhost:8000';

export function qaApiBase() {
  try {
    const q = new URLSearchParams(location.search).get('api');
    if (q) sessionStorage.setItem(QA_API_BASE_KEY, q.replace(/\/+$/, ''));
    return sessionStorage.getItem(QA_API_BASE_KEY) || QA_API_DEFAULT;
  } catch (_) { return QA_API_DEFAULT; }
}

export function setQaApiBase(url) {
  try { sessionStorage.setItem(QA_API_BASE_KEY, (url || '').replace(/\/+$/, '') || QA_API_DEFAULT); }
  catch (_) { /* storage unavailable */ }
}

async function qaApi(path, { method = 'GET', json, form } = {}) {
  const opts = { method };
  if (json !== undefined) {
    opts.headers = { 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(json);
  } else if (form) {
    opts.body = form;
  }
  const res = await fetch(qaApiBase() + path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) {
    const d = data.detail && typeof data.detail === 'object' ? data.detail : data;
    throw new Error(d.message || d.error || `HTTP ${res.status}`);
  }
  return data;
}

async function qaPollJob(jobId, onDetail, { intervalMs = 1500, timeoutMs = 420000 } = {}) {
  const t0 = Date.now();
  for (;;) {
    const job = await qaApi(`/api/v1/jobs/${jobId}`);
    const detail = (job.progress && job.progress.detail) || '';
    if (typeof onDetail === 'function' && detail) onDetail(detail);
    // 계약의 정본은 서버다 — server/store.py Job.status = queued|running|succeeded|failed
    if (job.status === 'succeeded') return job.result;
    if (job.status === 'failed') {
      const e = job.error || {};
      throw new Error(e.message || e.error || '작업이 실패했어요.');
    }
    if (Date.now() - t0 > timeoutMs) throw new Error('작업이 너무 오래 걸려요. 잠시 후 다시 시도해 주세요.');
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

/** 업로드한 녹음 파일 길이(초). 못 읽으면 0. */
export function audioDuration(file) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const a = new Audio();
    const done = (sec) => { URL.revokeObjectURL(url); resolve(sec); };
    a.addEventListener('loadedmetadata', () => done(Number.isFinite(a.duration) ? a.duration : 0));
    a.addEventListener('error', () => done(0));
    a.src = url;
  });
}

/* 임의 파일에는 슬라이드 마크가 없으니 길이를 슬라이드 수로 균등 분할 */
function evenMarks(totalSlides, durationSec) {
  const n = Math.max(1, Math.floor(totalSlides) || 1);
  const dur = Math.max(1, durationSec || 60);
  const step = dur / n;
  return Array.from({ length: n }, (_, i) => ({
    slide_no: i + 1,
    start_sec: Math.round(i * step * 10) / 10,
    end_sec: Math.round((i + 1) * step * 10) / 10,
    visit: 1,
  }));
}

/** 실전 QA 준비 파이프라인: 자료(+선택 녹음 파일) → 예상 질문 세트 */
export async function runQaLivePipeline({ documentFile, audioFile, mode = '10', onProgress }) {
  const report = (text) => {
    if (typeof onProgress === 'function') { try { onProgress(text); } catch (_) { /* UI hook */ } }
  };

  report('세션 만드는 중');
  const session = await qaApi('/api/v1/sessions', { method: 'POST', json: {} });
  const sid = session.id;

  report('발표자료 파싱 중 (F-01)');
  const fd = new FormData();
  fd.append('document', documentFile, documentFile.name);
  const parseJob = await qaApi(`/api/v1/sessions/${sid}/document`, { method: 'POST', form: fd });
  const slideDoc = await qaPollJob(parseJob.job_id, report);

  if (audioFile) {
    report('녹음을 글로 바꾸는 중 (F-05)');
    const durationSec = await audioDuration(audioFile);
    const marks = evenMarks((slideDoc && slideDoc.total_slides) || 1, durationSec);
    const af = new FormData();
    af.append('audio', audioFile, audioFile.name);
    af.append('marks', JSON.stringify(marks));
    const sttJob = await qaApi(`/api/v1/sessions/${sid}/rehearsal`, { method: 'POST', form: af });
    await qaPollJob(sttJob.job_id, report);
  }

  report('개념 추출 중 (F-06)');
  const cJob = await qaApi(`/api/v1/sessions/${sid}/concepts`, { method: 'POST', json: {} });
  await qaPollJob(cJob.job_id, report);

  report('개념 그래프 만드는 중 (F-07)');
  const gJob = await qaApi(`/api/v1/sessions/${sid}/graph`, { method: 'POST', json: {} });
  await qaPollJob(gJob.job_id, report);

  if (audioFile) {
    report('발화-자료 정합 판정 중 (F-11)');
    try {
      const aJob = await qaApi(`/api/v1/sessions/${sid}/alignment`, { method: 'POST', json: {} });
      await qaPollJob(aJob.job_id, report);
    } catch (err) {
      // 질문 생성은 그래프만으로도 가능 — 정합 실패는 건너뛴다
      report(`정합 판정 생략: ${err.message || err}`);
    }
  }

  report('예상 질문 만드는 중 (F-08)');
  // 서버 계약의 이름은 track 이다 (contracts.py QA_TRACKS). mode 는 화면 쪽 이름.
  const qJob = await qaApi(`/api/v1/sessions/${sid}/questions`, { method: 'POST', json: { track: mode } });
  const questionDoc = await qaPollJob(qJob.job_id, report);

  const questions = (questionDoc && questionDoc.questions) || [];
  report(`질문 ${questions.length}개 준비 완료`);
  return { sessionId: sid, questionDoc };
}

/**
 * F-09 답변 판정 (동기 — 잡이 아니라 응답 바디를 바로 읽는다).
 *
 * question 을 같이 보낸다. 서버 저장소가 인메모리라 재시작하면 세션이 날아가는데,
 * 질문 세트는 이 브라우저에 남아 있다. 세션이 사라졌을 때 서버는 이 값으로 판정한다
 * — 없으면 저장된 질문으로 답할 때마다 전부 '판정 실패' 가 된다.
 */
export async function judgeQaAnswer(sessionId, { questionId, answer, history, question }) {
  return qaApi(`/api/v1/sessions/${sessionId}/qa/judge`, {
    method: 'POST',
    json: { question_id: questionId, answer, history: history || [], question: question || null },
  });
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

window.ChuckchuckBridge = {
  attachRehearsalRuntime,
  parseDocument,
  runPreparePipeline,
  saveChuckSession,
  loadChuckSession,
  qaApiBase,
  setQaApiBase,
  audioDuration,
  runQaLivePipeline,
  judgeQaAnswer,
  RehearsalRecorder,
  PresentationRecorder,
  SlideMarkTracker,
  formatMarkLog,
};

console.info('[chuckchuck] SDK bridge ready');
