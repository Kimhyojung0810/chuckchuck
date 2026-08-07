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
/**
 * F-06 개념 추출 한 번. 녹음 중 선분석과 파이프라인이 같은 함수를 쓴다.
 *
 * `transcript` 는 선택이다 — F-06 은 글자가 거의 없는 슬라이드에서만 speech_hint 로 쓴다.
 * 선분석은 녹음이 끝나기 전에 도는 경로라 transcript 없이 부른다. 공짜는 아니다:
 * 글자 없는 슬라이드의 topic 추정이 그만큼 약해진다.
 */
export async function extractConcepts({ slideDoc, context, transcript = null }) {
  const res = await fetch(apiBase() + '/api/v1/concepts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      slide_doc: slideDoc,
      context: context || {},
      transcript: transcript ? slimTranscript(transcript) : null,
    }),
  });
  const concepts = await readJson(res, '개념 추출');
  if (!res.ok || concepts.error) {
    throw new Error(concepts.message || concepts.error || `concepts HTTP ${res.status}`);
  }
  return concepts;
}

/** F-07 개념 그래프 한 번. Transcript 를 받지 않는다 (f07_graph.py 계약) */
export async function buildGraph({ concepts, slideDoc, context }) {
  const res = await fetch(apiBase() + '/api/v1/graph', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ concept_doc: concepts, slide_doc: slideDoc, context: context || {} }),
  });
  const graph = await readJson(res, '개념 그래프');
  if (!res.ok || graph.error) {
    throw new Error(graph.message || graph.error || `graph HTTP ${res.status}`);
  }
  return graph;
}

/**
 * @param {object} [precomputed] 녹음 중에 미리 걸어 둔 `{ conceptsP, graphP }` promise.
 *   캐시가 아니라 promise 다 — 짧은 녹음이면 아직 도는 중이고, 그때 캐시를 조회했다면
 *   "없음"으로 읽고 같은 호출을 한 번 더 결제했을 것이다. await 하면 진행 중인 호출에 붙는다.
 *   reject 되면 조용히 원래 경로로 되돌아간다.
 */
export async function runPreparePipeline({ marks, blob, mimeType, fileName, slideDoc, context, onProgress, precomputed = null }) {
  const report = (phase, detail = '', extra = {}) => {
    if (typeof onProgress === 'function') {
      try { onProgress({ phase, detail, ...extra }); } catch (_) { /* UI hook */ }
    }
  };

  report('encoding', '오디오 준비 중');
  const audio_base64 = blob ? await blobToBase64(blob) : null;
  const ext = audioExt({ fileName, mimeType });

  report('stt', 'A.X 모델로 음성을 글로 바꾸는 중');
  const sttRes = await fetch(apiBase() + '/api/v1/transcribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      marks: marks || [],
      audio_base64,
      ext,
      // 자료를 같이 보내면 서버가 발화 내용으로 슬라이드 구간을 되짚는다 (F-04 파생).
      // 업로드본은 전환 기록이 없어 marks 가 균등 분할이라, 그대로 두면 어긋난다.
      slidedoc: slideDoc || null,
    }),
  });
  const transcript = await readJson(sttRes, '받아쓰기');
  if (!sttRes.ok || transcript.error) {
    throw new Error(transcript.message || transcript.error || `transcribe HTTP ${sttRes.status}`);
  }
  /* 추정값인지 균등 분할인지 숨기지 않는다 — 진행 로그에 그대로 남긴다 */
  const markNote = transcript.marks_reason ? ` · ${transcript.marks_reason}` : '';
  report('stt_done', `단어 ${(transcript.words || []).length}개 · 슬라이드 구간 ${(transcript.by_slide || []).length}개${markNote}`, { transcript });

  const pre = precomputed || {};
  let usedPreConcepts = false;
  let concepts = null;
  let conceptsError = null;
  if (slideDoc) {
    report(
      'concepts',
      pre.conceptsP ? '발표하는 동안 미리 읽어 둔 개념을 가져오는 중' : '발표자료 개념 추출 중',
      { transcript },
    );
    try {
      // 선분석이 걸려 있으면 그 promise 에 붙는다. 실패했으면 조용히 원래 경로로 되돌아간다
      if (pre.conceptsP) {
        concepts = await pre.conceptsP.catch(() => null);
        usedPreConcepts = !!concepts;
      }
      if (!concepts) {
        concepts = await extractConcepts({ slideDoc, context, transcript });
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
      report(
        'graph',
        pre.graphP && usedPreConcepts ? '미리 만들어 둔 개념 그래프를 가져오는 중' : '개념 그래프 구성 중',
        { transcript, concepts },
      );
      /* 선분석 그래프는 선분석 개념 위에 세워졌다. 개념이 폴백으로 다시 뽑혔으면
         그 그래프는 다른 개념의 그래프라 쓰면 안 된다 — node.id 가 어긋나면 F-11 정합이
         통째로 거짓말이 된다. */
      if (pre.graphP && usedPreConcepts) {
        graph = await pre.graphP.catch(() => null);
      }
      if (!graph) {
        graph = await buildGraph({ concepts, slideDoc, context });
      }
      report('graph_done', `개념 ${(graph.nodes || []).length}개 · 연결 ${(graph.edges || []).length}개`, { transcript, concepts, graph });

      report('align', '발표와 자료 대조 중', { transcript, concepts, graph });
      const aRes = await fetch(apiBase() + '/api/v1/alignment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ graph, transcript: slimTranscript(transcript), context: context || {} }),
      });
      alignment = await readJson(aRes, '정합 판정');
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
      flow = await readJson(fRes, '흐름 비교');
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


  // 점수는 F-14 채점표가 매긴다. 말 속도·습관까지 있어야 39개 항목이 다 채워지므로
  // F-17·18 뒤로 옮겼다 (아래 참조).
  let score = null;

  // F-17·18·19 — 음성 습관·시간 배분·종합 리포트 (실패해도 STT까지는 유지)
  // callers: app.js runPreparePipeline onProgress / then; APIs /api/v1/pace|habits|report
  let pace = null;
  let habits = null;
  let voiceReport = null;
  const slim = slimTranscript(transcript);
  try {
    report('pace', '말 속도·시간 배분 계산 중', { transcript, concepts, graph, alignment, flow });
    const pRes = await fetch(apiBase() + '/api/v1/pace', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        transcript: slim,
        context: context || {},
        concept_doc: concepts || null,
      }),
    });
    pace = await readJson(pRes, '말 속도');
    if (!pRes.ok || pace.error) {
      throw new Error(pace.message || pace.error || `pace HTTP ${pRes.status}`);
    }
    report('pace_done', `배분 ${(pace.slides || []).length}장 · 실제 ${Math.round(pace.actual_sec || 0)}초`, {
      transcript, concepts, graph, alignment, flow, pace,
    });

    report('habits', '음성 습관 신호 추출 중', { transcript, concepts, graph, alignment, flow, pace });
    const hRes = await fetch(apiBase() + '/api/v1/habits', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcript: slim }),
    });
    habits = await readJson(hRes, '말버릇 분석');
    if (!hRes.ok || habits.error) {
      throw new Error(habits.message || habits.error || `habits HTTP ${hRes.status}`);
    }
    report('habits_done', `REP ${habits.repeat_cnt || 0} · FIL ${habits.filler_cnt || 0} · PAUSE ${habits.pause_cnt || 0}`, {
      transcript, concepts, graph, alignment, flow, pace, habits,
    });

    // F-14 채점표 v3 — 39개 항목·7개 클러스터를 발표 상황 가중치로 묶는다.
    // 앞 단계가 일부 실패해도 부른다. 없는 자료에 기대는 항목만 '못 쟀다'가 되고
    // 나머지는 정상 채점되므로, 여기서 미리 막으면 오히려 점수가 안 뜬다.
    try {
      report('score', '채점표로 점수 매기는 중', {
        transcript, concepts, graph, alignment, flow, pace, habits,
      });
      const sRes = await fetch(apiBase() + '/api/v1/rubric', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          situation: (context || {}).situation || '',
          context: context || {},
          slides: slideDoc || null,
          concepts, graph, transcript: slim, alignment, flow, pace, habits,
        }),
      });
      score = await readJson(sRes, '채점');
      if (!sRes.ok || score.error) {
        throw new Error(score.message || score.error || `rubric HTTP ${sRes.status}`);
      }
      report('score_done', `${score.score}점 · ${score.situation_label}`, {
        transcript, concepts, graph, alignment, flow, pace, habits, score,
      });
    } catch (err) {
      // 점수가 없어도 나머지 화면은 살린다 — 치명적이지 않다
      score = null;
      report('score_error', err.message || String(err), {
        transcript, concepts, graph, alignment, flow, pace, habits,
      });
    }

    report('voice_report', '종합 진단 리포트 작성 중', {
      transcript, concepts, graph, alignment, flow, pace, habits, score,
    });
    const rRes = await fetch(apiBase() + '/api/v1/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // 점수는 채점표가 진실이다 — F-19 가 두 번째 점수를 만들지 않게 같이 보낸다
      body: JSON.stringify({ pace, habits, rubric: score, context: context || {} }),
    });
    voiceReport = await readJson(rRes, '리포트');
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
    (conceptsError && ['개념 추출', conceptsError])
    || (graphError && ['개념 그래프', graphError])
    || (alignError && ['정합 판정', alignError])
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
/* 판정은 따로 늘린다. F-09 는 LLM 응답 JSON 이 깨지면 한 번 더 부르므로(재시도)
   느린 날은 2회 왕복이다 — 공용 30초면 멀쩡히 진행 중인 판정이 실패로 떨어진다. */
const JUDGE_TIMEOUT_MS = 60000;

/** 질문 생성 한계 시간. 없으면 화면이 영원히 로딩에 갇힌다. */
const QUESTIONS_TIMEOUT_MS = 60000;

/** 받아쓰기 한계 시간. 없으면 마이크 버튼이 「받아쓰는 중…」에 갇힌다. */
const TRANSCRIBE_TIMEOUT_MS = 60000;

/**
 * 답변 녹음 최대 길이. 답변 하나는 원래 짧다 — 무한정 녹음하다 업로드 한도(30MB)에
 * 부딪혀 413 으로 죽는 것보다, 스스로 끊고 받아쓰는 편이 낫다.
 */
const ANSWER_RECORD_MAX_MS = 90000;

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
export async function judgeQaAnswer(sessionId, { questionId, answer, history, question, giveUp, priorAnswers, hintsShown, artifacts }) {
  const sid = sessionId || 'flat';
  const body = {
    session_id: sid,
    question_id: questionId,
    answer,
    history: history || [],
    question: question || null,
    give_up: !!giveUp,
    // 이 질문에 앞서 낸 답들. 안 실으면 되묻기에 증분으로 답한 사용자가
    // 그 조각만으로 판정받는다 (f09 는 누적 전체를 합쳐 본다).
    prior_answers: priorAnswers || [],
    // 보여준 힌트 — 코치가 힌트와 이어지는 말로 반응한다 (일방향 힌트 방지)
    hints_shown: hintsShown || [],
  };
  const path = `/api/v1/sessions/${sid}/qa/judge`;
  try {
    return await qaApi(path, { method: 'POST', json: body, timeoutMs: JUDGE_TIMEOUT_MS });
  } catch (err) {
    // 세션이 비었을 때만 재등록한다. 아티팩트가 아예 없으면 그대로 올린다 —
    // 근거 없이 조용히 판정하느니 실패가 낫다.
    if (err.code !== 'session_missing' || !artifacts) throw err;
    await registerSessionArtifacts(sid, artifacts);
    return qaApi(path, { method: 'POST', json: body, timeoutMs: JUDGE_TIMEOUT_MS });
  }
}

/** 실시간 받아쓰기 언어. 발표는 한국어라 고정한다. */
const DICTATION_LANG = 'ko-KR';

/** Web Speech API 오류 코드 → 사람 말. 코드를 그대로 보여 주면 뭘 하라는 건지 모른다. */
const DICTATION_ERRORS = {
  'not-allowed': '마이크 권한이 없어요.',
  'service-not-allowed': '브라우저가 받아쓰기를 막았어요.',
  'audio-capture': '마이크를 찾지 못했어요.',
  network: '받아쓰기 서버에 닿지 못했어요.',
};

/** 브라우저가 실시간 받아쓰기를 해 주는가. Chrome·Edge 는 되고 Safari·Firefox 는 안 된다. */
export function hasLiveDictation() {
  return typeof (window.SpeechRecognition || window.webkitSpeechRecognition) === 'function';
}

/**
 * 말하는 대로 글자가 나오는 실시간 받아쓰기 (Web Speech API).
 *
 * `startAnswerRecording` 은 다 말한 뒤 파일을 통째로 올려 STT 를 돌리므로 구조상
 * 실시간이 안 된다. 이쪽은 브라우저가 확정 전 조각(interim)까지 흘려 주므로
 * 말하는 중에 글자가 뜬다.
 *
 * **대신 브라우저 기능이라 지원이 갈리고, 크롬은 음성을 구글 서버로 보낸다.**
 * 못 쓰는 브라우저에서는 호출부가 녹음 + 자체 STT 로 되돌아간다.
 *
 * @param {{ onText: (parts: {final: string, interim: string}) => void,
 *           onError: (message: string) => void }} handlers
 * @returns {{ stop: () => string }} stop 은 확정된 전문을 준다
 */
export function startLiveDictation({ onText, onError }) {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (typeof Recognition !== 'function') {
    throw new Error('이 브라우저는 실시간 받아쓰기를 지원하지 않아요.');
  }
  const rec = new Recognition();
  rec.lang = DICTATION_LANG;
  rec.continuous = true;       // 한 문장 끝났다고 멈추지 않는다
  rec.interimResults = true;   // 확정 전 글자도 준다 — 이게 「실시간」의 핵심이다

  let stopped = false;
  let settled = '';

  rec.onresult = (e) => {
    let interim = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const chunk = e.results[i][0].transcript;
      if (e.results[i].isFinal) settled += chunk;
      else interim += chunk;
    }
    onText({ final: settled, interim });
  };
  rec.onerror = (e) => {
    // no-speech·aborted 는 알릴 일이 아니다 — 잠깐 말이 없었을 뿐, 곧 이어서 말한다.
    if (e.error === 'no-speech' || e.error === 'aborted') return;
    // 나머지(권한 거부·마이크 없음·네트워크)는 다시 시작해도 같은 오류가 난다.
    // **여기서 안 끊으면** 크롬이 onerror 뒤에 onend 를 쏘고, onend 가 다시
    // start() 를 불러 onerror 로 돌아오는 고리가 끝없이 돈다.
    stopped = true;
    onError(DICTATION_ERRORS[e.error] || `받아쓰기 오류: ${e.error}`);
  };
  rec.onend = () => {
    // 크롬은 조용하면 제풀에 끊는다. 사용자가 멈춘 게 아니면 다시 잇는다.
    if (stopped) return;
    try { rec.start(); } catch (_) { /* 이미 도는 중 */ }
  };
  rec.start();

  return {
    stop() {
      stopped = true;
      try { rec.stop(); } catch (_) { /* 이미 멈춤 */ }
      return settled.trim();
    },
  };
}

/**
 * QA 답변용 마이크 녹음. 리허설 녹음과 달리 슬라이드 구간이 없다 — 짧은 음성
 * 한 덩이만 받으므로 `RehearsalRecorder` 는 포맷 고르기만 물려 쓴다.
 *
 * 반환한 `stop()` 은 녹음이 실제로 끝난 뒤의 Blob 을 준다. `MediaRecorder.stop()`
 * 은 비동기라 바로 chunks 를 읽으면 마지막 조각이 빠진다.
 *
 * @param {{ onAutoStop?: () => void }} [opts]
 * @returns {Promise<{ maxMs: number, stop: () => Promise<Blob> }>}
 */
export async function startAnswerRecording({ onAutoStop } = {}) {
  if (!navigator.mediaDevices || typeof window.MediaRecorder !== 'function') {
    throw new Error('이 브라우저는 녹음을 지원하지 않아요.');
  }
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const mimeType = (typeof RehearsalRecorder === 'function' && RehearsalRecorder.pickMimeType)
    ? RehearsalRecorder.pickMimeType()
    : '';
  const rec = new window.MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  const chunks = [];
  rec.addEventListener('dataavailable', (e) => {
    if (e.data && e.data.size) chunks.push(e.data);
  });

  let settle = null;
  const done = new Promise((resolve) => { settle = resolve; });
  rec.addEventListener('stop', () => {
    // 트랙을 안 끄면 탭의 「녹음 중」 표시가 계속 켜져 있다
    stream.getTracks().forEach((t) => t.stop());
    settle(new Blob(chunks, { type: rec.mimeType || mimeType || 'audio/webm' }));
  });
  rec.start();

  const halt = () => {
    if (rec.state !== 'inactive') {
      try { rec.stop(); } catch (_) { /* 이미 멈춘 뒤 */ }
    }
  };
  const auto = setTimeout(() => {
    halt();
    if (typeof onAutoStop === 'function') onAutoStop();
  }, ANSWER_RECORD_MAX_MS);

  return {
    maxMs: ANSWER_RECORD_MAX_MS,
    stop() {
      clearTimeout(auto);
      halt();
      return done;
    },
  };
}

/**
 * 답변 녹음 한 덩이 → 텍스트 (F-05). 슬라이드 마크 없이 전문만 쓴다.
 *
 * **여기서 답을 보내지 않는다.** 잘못 알아들은 문장을 고칠 틈 없이 판정으로
 * 넘어가면, 마이크가 타이핑보다 못한 입력이 된다.
 */
export async function transcribeAnswer(blob) {
  if (!blob || !blob.size) throw new Error('녹음된 소리가 없어요.');
  const res = await fetchWithTimeout(apiBase() + '/api/v1/transcribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      marks: [],
      audio_base64: await blobToBase64(blob),
      ext: audioExt({ mimeType: blob.type }),
    }),
  }, TRANSCRIBE_TIMEOUT_MS, '받아쓰기');
  const t = await readJson(res, '받아쓰기');
  if (!res.ok || t.error) {
    throw new Error(t.message || t.error || `transcribe HTTP ${res.status}`);
  }
  return String(t.full_text || '').trim();
}

window.ChuckchuckBridge = {
  attachRehearsalRuntime,
  startAnswerRecording,
  transcribeAnswer,
  hasLiveDictation,
  startLiveDictation,
  parseDocument,
  runPreparePipeline,
  extractConcepts,
  buildGraph,
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
