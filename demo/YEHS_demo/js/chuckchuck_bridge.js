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
  // 단계별 실패를 따로 들고 간다. 예전엔 전부 삼키고 마지막에 'done' 만 보고해서,
  // F-07 이 타임아웃으로 죽어도 화면엔 "완료" 로 떠 사용자가 하염없이 기다렸다.
  let graphError = null;
  let alignError = null;
  let flowError = null;
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
      const msg = err.message || String(err);
      if (graph && graph.error) graph = null;
      // 그래프까지 못 만들었는지, 그래프는 됐는데 판정에서 죽었는지를 구분한다
      if (!graph) graphError = msg; else alignError = msg;
      alignment = null;
      report('align_error', msg, { transcript, concepts, graph });
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
      flowError = err.message || String(err);
      report('flow_error', flowError, { transcript, concepts, graph, alignment });
    }
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
    graph, alignment, flow,
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

window.ChuckchuckBridge = {
  attachRehearsalRuntime,
  parseDocument,
  runPreparePipeline,
  audioExt,
  saveChuckSession,
  loadChuckSession,
  RehearsalRecorder,
  PresentationRecorder,
  SlideMarkTracker,
  formatMarkLog,
};

console.info('[chuckchuck] SDK bridge ready');
