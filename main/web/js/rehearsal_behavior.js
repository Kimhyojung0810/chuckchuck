/**
 * 리허설(#/rehearsal) 카메라 분석 붙이기 — 「발표 태도 · 베타」 (js/behavior_cv.js 엔진 · js/behavior_report.js 카드).
 *
 *   비전 리허설에서 녹음하는 동안(nf.mic === 'on') → 이미 연 카메라(#vrSelfVideo)를 조용히 본다. 장 = nf.slide, 말소리 = 마이크 크기
 *   발표를 마치면(app.js finishRecAndPrepare) → nf.behavior.present (화면용 묶음 + summary). 채점(F-14) 본문에 summary 가 실린다
 *   글라스 화상판 Q&A 동안 → 넘겨받은 카메라(bq.video)를 본다. 질문 = qa.live.qi
 *   리포트로 갈 때(rehearsalTeardown) → nf.behavior.qa, 숫자 요약은 /api/v1/behavior 로 보관소에
 *
 * 카메라 권한을 묻는 때 · 녹음 · 부스 정면 알약은 건드리지 않는다. 무엇이 실패해도 발표 · Q&A 를 막지 않는다 —
 * 리포트에는 「카메라 분석 없음」 과 까닭만 남는다. 클래식 스크립트라 app.js · vision_rehearsal.js · rehearsal.js 의 전역을 부를 때 찾는다.
 */

const RH_BEH_PREV_KEY = 'cheokcheok:behavior-prev';   // 덱마다 지난 회차 숫자 — 「지난번보다」 (근거조사 §0-1: 절대 띠보다 본인 변화가 먼저)
const rhBeh = { timer: 0, presentOn: false, qaOn: false };

function rhBehOn() {
  return typeof rehearsalFlowOn === 'function' && rehearsalFlowOn() && !!window.BehaviorCV && !!window.BehaviorCvLogic;
}

function rhBehSave() {
  if (typeof saveSession === 'function' && typeof nf !== 'undefined' && nf) saveSession('new-flow', nf);
}

/** 비전 리허설 카메라 영상 — 꺼 뒀거나 아직 안 열렸으면 null */
function rhBehVisionVideo() {
  if (typeof visionCam !== 'undefined' && (visionCam.off || !visionCam.stream)) return null;
  const v = document.getElementById('vrSelfVideo');
  return v && v.srcObject ? v : null;
}

/** vision_rehearsal.js nfStep3Vision 이 리허설 탭에서 부른다 — 녹음이 켜지면 기록을 시작하는 작은 시계(0.4초). 층이 사라지면 스스로 멈춘다 */
function rhBehaviorVisionMount() {
  if (!rhBehOn()) return;
  if (window.BehaviorCV.status() === 'idle') window.BehaviorCV.load();   // 녹음 전에 받아 둔다 (워커 안 · 화면은 안 언다)
  if (rhBeh.timer) return;
  rhBeh.timer = setInterval(() => {
    const layer = document.getElementById('vrCall');
    const live = typeof nf !== 'undefined' && nf && nf.mic === 'on';
    if (live && layer && !rhBeh.presentOn) {
      rhBeh.presentOn = true;
      window.BehaviorCV.start('present', {
        video: rhBehVisionVideo,
        seg: () => `s${(typeof nf !== 'undefined' && nf && Number(nf.slide)) || 1}`,
        level: () => (typeof visionReadLevel === 'function' ? visionReadLevel() : null),
        active: () => typeof nf !== 'undefined' && !!nf && nf.mic === 'on',
      });
    }
    // 녹음을 마치지 않고 나갔다(나가기 · 다시 발표) — 이 기록은 어느 발표의 것도 아니다
    if (rhBeh.presentOn && !live && !layer) { window.BehaviorCV.discard('present'); rhBeh.presentOn = false; }
    if (!layer && !rhBeh.presentOn) { clearInterval(rhBeh.timer); rhBeh.timer = 0; }
  }, 400);
}

/** 카메라 분석이 없던 까닭 — 사용자가 고칠 수 있는 말로 */
function rhBehWhyNone() {
  if (typeof visionCam !== 'undefined' && visionCam.off) return '카메라를 꺼 두고 발표해서 카메라 분석은 없어요';
  if (typeof visionCam !== 'undefined' && visionCam.error) return '카메라가 열리지 않아서 카메라 분석은 없어요';
  return '';
}

/** 지난 회차(같은 덱) 숫자를 붙이고 이번 숫자를 남긴다 */
function rhBehPrev(view) {
  const key = (nf && nf.rehearsalDeck && (nf.rehearsalDeck.key || nf.rehearsalDeck.title)) || (nf && nf.fileName) || '';
  if (!key || !view || view.status !== 'ok') return;
  let all = {};
  try { all = JSON.parse(localStorage.getItem(RH_BEH_PREV_KEY) || '{}') || {}; } catch (_) { all = {}; }
  if (all[key]) view.prev = all[key];
  const metrics = {};
  Object.entries(view.metrics || {}).forEach(([k, m]) => { if (m && m.ok && Number.isFinite(m.value)) metrics[k] = m.value; });
  all[key] = { at: Date.now(), metrics };
  const keys = Object.keys(all).sort((a, b) => (all[b].at || 0) - (all[a].at || 0)).slice(0, 12);
  try { localStorage.setItem(RH_BEH_PREV_KEY, JSON.stringify(Object.fromEntries(keys.map((k) => [k, all[k]])))); } catch (_) { /* 넘치면 이번만 */ }
}

/** app.js finishRecAndPrepare 가 녹음을 닫기 전에 부른다. 리허설 탭이 아니면 아무것도 안 한다 */
function rhBehaviorFinishPresent() {
  if (!rhBehOn() || typeof nf === 'undefined' || !nf) return;
  try {
    const view = window.BehaviorCV.finish('present', { why: rhBehWhyNone() })
      || window.BehaviorCvLogic.none(rhBehWhyNone() || '카메라 분석을 하지 못했어요');
    if (!view.summary) view.summary = window.BehaviorCvLogic.summaryOf(view);
    rhBehPrev(view);
    nf.behavior = { present: view, qa: null };
  } catch (err) {
    console.warn('[chuckchuck] 발표 태도 요약', err);
    nf.behavior = { present: window.BehaviorCvLogic.none('카메라 기록을 정리하다 멈췄어요'), qa: null };
  }
  rhBeh.presentOn = false;
  rhBehSave();
}

/** 녹음 파일로 발표를 대신했다(app.js useUploadedRecording) — 라이브 카메라 기록은 그 녹음의 것이 아니다 */
function rhBehaviorDiscardPresent(why) {
  if (!rhBehOn() || typeof nf === 'undefined' || !nf) return;
  window.BehaviorCV.discard('present');
  rhBeh.presentOn = false;
  nf.behavior = { present: window.BehaviorCvLogic.none(why || '녹음 파일로 발표를 대신해서 카메라 분석은 없어요'), qa: null };
  nf.behavior.present.summary = window.BehaviorCvLogic.summaryOf(nf.behavior.present);
  rhBehSave();
}

/** 다시 발표(app.js discardTakeKeepDeck) — 지난 테이크의 태도를 버린다 */
function rhBehaviorReset() {
  if (window.BehaviorCV) window.BehaviorCV.discard('');
  rhBeh.presentOn = false; rhBeh.qaOn = false;
  if (typeof nf !== 'undefined' && nf) nf.behavior = null;
}

/** 채점 본문에 싣는 숫자 요약 (chuckchuck_bridge.js runPreparePipeline 이 채점 직전에 부른다) */
function rhBehaviorPayload() {
  const p = typeof nf !== 'undefined' && nf && nf.behavior && nf.behavior.present;
  return p ? (p.summary || null) : null;
}

/** rehearsal.js renderQaLiveRehearsal — 화상판에 넘겨받은 카메라로 Q&A 기록을 시작한다 */
function rhBehaviorQaMount() {
  if (!rhBehOn() || rhBeh.qaOn || typeof bq === 'undefined') return;
  rhBeh.qaOn = true;
  window.BehaviorCV.start('qa', {
    video: () => (bq.cam && bq.cam.stream && !bq.cam.off && bq.video && bq.video.srcObject ? bq.video : null),
    seg: () => {
      const L = typeof qa !== 'undefined' && qa && qa.live;
      return L && Array.isArray(L.questions) && L.qi < L.questions.length ? `q${(Number(L.qi) || 0) + 1}` : '';
    },
    active: () => {
      const L = typeof qa !== 'undefined' && qa && qa.live;
      return !!(L && Array.isArray(L.questions) && L.questions.length && L.qi < L.questions.length);
    },
  });
}

/** rehearsal.js rehearsalTeardown — Q&A 기록을 닫아 nf.behavior.qa 에 두고, 숫자 요약을 보관소로 */
function rhBehaviorQaFinish() {
  if (!rhBeh.qaOn || !window.BehaviorCV) return;
  rhBeh.qaOn = false;
  if (typeof nf === 'undefined' || !nf) { window.BehaviorCV.discard('qa'); return; }
  let view = null;
  try {
    const off = typeof bq !== 'undefined' && bq.cam && bq.cam.off;
    view = window.BehaviorCV.finish('qa', { why: off ? 'Q&A 동안 카메라를 꺼 둬서 카메라 분석은 없어요' : '' });
  } catch (err) { console.warn('[chuckchuck] Q&A 태도 요약', err); }
  if (!view) return;
  nf.behavior = { ...(nf.behavior || { present: null }), qa: view };
  rhBehSave();
  const sid = nf.sessionId;
  if (sid && view.summary && view.summary.status !== 'none') {
    fetch('/api/v1/behavior', {
      method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sid, behavior: view.summary }),
    }).catch(() => { /* 보관은 편의 — 리포트는 이 탭의 값으로 그린다 */ });
  }
}

/** 리허설을 떠날 때 워커(≈60MB)를 내린다 */
function rhBehaviorDispose() {
  if (window.BehaviorCV && !window.BehaviorCV.running()) window.BehaviorCV.dispose();
}
