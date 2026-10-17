/**
 * 발표를 들으며 3번+ 질문을 준비한다 (2026-10-17, docs/qa-ensemble/LIVE_REPORT.md) — 비전 리허설이 부른다.
 *
 * 발표하는 동안 A.X 실시간 받아쓰기로 확정된 문장을 **그때 보던 장**에 붙여 두었다가, 장을 넘길 때마다 그 장의 발화 전체를
 * 브리지 /api/v1/qa/live 로 보낸다(talk_id = 이 발표 한 번). 서버는 다 들은 장의 새 신호로 3번+ 음성 후보를 뒤에서 만든다.
 * 발표를 마치면 final, 분석(정합)이 끝나면 alignment 를 한 번 더 보낸다. 1·2번은 언제나 자료 묶음이라 여기와 상관없다.
 *
 * 순수 함수(qaListenDelta · qaListenReduce)는 etc/tests/js/qa_listen.smoke.mjs 가 브라우저 없이 본다.
 * 실패해도 발표 · 녹음은 그대로 간다 — 보내기는 모두 조용히 넘어간다.
 */

/* ─── 순수 함수 ─────────────────────────────────────────────────────────────── */

/** 받아쓰기의 누적 확정문(final)이 앞보다 늘어난 부분. 줄었거나 앞부분이 바뀌었으면(받아쓰기를 새로 열었음) 전체가 새것 */
function qaListenDelta(prev, final) {
  const p = String(prev || '');
  const f = String(final || '');
  if (!f) return '';
  if (f.startsWith(p)) return f.slice(p.length).trim();
  return f.trim();
}

/**
 * 상태 하나 → 다음 상태 (부작용 없음). ev: {type:'text', final, slide} · {type:'turn', from, to} · {type:'end'}
 * 돌려주는 send 는 보낼 것 [{slide_no, text, closed, final}] — 장을 떠날 때(turn) · 마칠 때(end)만.
 */
function qaListenReduce(state, ev) {
  const s = state || { slides: {}, lastFinal: '', cur: 0, sent: {} };
  const slides = { ...s.slides };
  const send = [];
  if (ev.type === 'text') {
    const add = qaListenDelta(s.lastFinal, ev.final);
    const no = Number(ev.slide) || s.cur || 1;
    if (add) slides[no] = `${slides[no] ? `${slides[no]} ` : ''}${add}`.slice(-4000);
    return { state: { ...s, slides, lastFinal: String(ev.final || ''), cur: no }, send };
  }
  if (ev.type === 'turn') {
    const from = Number(ev.from) || s.cur;
    // 떠난 장은 늘 보낸다(말이 없었어도 「다 들었다」 는 표시가 신호 계산에 필요하다 — 여러 장에 걸친 노드)
    if (from) send.push({ slide_no: from, text: slides[from] || '', closed: true });
    const sent = { ...s.sent, ...(from ? { [from]: slides[from] || '' } : {}) };
    return { state: { ...s, slides, cur: Number(ev.to) || s.cur, sent }, send };
  }
  if (ev.type === 'end') {
    const cur = s.cur;
    send.push({ slide_no: cur || 0, text: cur ? (slides[cur] || '') : null, closed: !!cur, final: true });
    return { state: { ...s, slides, sent: { ...s.sent, ...(cur ? { [cur]: slides[cur] || '' } : {}) }, done: true }, send };
  }
  return { state: s, send };
}

/* ─── 화면 쪽 (비전 리허설) ──────────────────────────────────────────────────── */

const qaListen = { on: false, off: false, sid: '', talk: '', state: null, baseFinal: '', pool: { sid: '', early: false, at: 0 } };

/** 발표하는 동안 1·2번 자료 묶음이 준비됐는지 미리 본다 — 발표를 마치는 순간 기다림 화면이 서버에 다시 묻지 않고 바로 Q&A 를 연다 */
function qaListenPeekPool() {
  const bridge = window.ChuckchuckBridge;
  if (!bridge || typeof bridge.qaPoolStatus !== 'function' || !qaListen.sid) return;
  if (qaListen.pool.sid === qaListen.sid && (qaListen.pool.early || Date.now() - qaListen.pool.at < 4000)) return;
  const sid = qaListen.sid;
  qaListen.pool = { sid, early: false, at: Date.now() };
  bridge.qaPoolStatus(sid).then((r) => {
    if (qaListen.pool.sid !== sid) return;
    qaListen.pool.early = !!(r && r.early);
    // 서버가 네 모델 Q&A · 발표 중 준비를 안 켰으면 장마다 보내지 않는다(공개 서비스 기본값이 꺼짐일 수 있다)
    if (r && (r.ensemble === false || r.live === false)) qaListen.off = true;
  }).catch(() => {});
}

/** 기다림 화면(js/rehearsal.js)이 묻는다 — 이 세션의 묶음이 발표 중에 준비됐다고 들었나 */
function qaListenPoolEarly(sessionId) {
  return !!(sessionId && qaListen.pool.sid === String(sessionId) && qaListen.pool.early);
}

/** 녹음이 시작된 뒤 처음 받은 확정문 — 이번 발표의 시작. 그 전에 쌓인 확정문(녹음 전 말)은 빼고 센다 */
function qaListenBegin(sessionId, finalSoFar = '') {
  const bridge = window.ChuckchuckBridge;
  if (!bridge || typeof bridge.talkRunId !== 'function' || !sessionId) return false;
  qaListen.on = true;
  qaListen.sid = String(sessionId);
  qaListen.talk = bridge.talkRunId(sessionId, { fresh: true });
  qaListen.state = { slides: {}, lastFinal: String(finalSoFar || ''), cur: Number((typeof nf !== 'undefined' && nf && nf.slide) || 1), sent: {} };
  qaListen.off = false;
  qaListenPeekPool();       // 켜져 있는지 · 묶음이 준비됐는지 발표 시작 때 한 번
  return true;
}

/** 보내기는 차례대로 — 같은 장을 다시 들러 두 번 보내면 늦게 도착한 옛 글이 새 글을 덮었다(10-17 검토) */
let qaListenQueue = Promise.resolve();
function qaListenPost(items) {
  const bridge = window.ChuckchuckBridge;
  if (!bridge || typeof bridge.qaLiveFeed !== 'function' || !qaListen.talk || qaListen.off) return;
  const sid = qaListen.sid;
  const talk = qaListen.talk;
  items.forEach((it) => {
    qaListenQueue = qaListenQueue.then(() => bridge.qaLiveFeed(sid, talk, it)).catch(() => {});
  });
}

function qaListenStep(ev) {
  if (!qaListen.on || !qaListen.state) return;
  const { state, send } = qaListenReduce(qaListen.state, ev);
  qaListen.state = state;
  if (send.length) qaListenPost(send);
}

/** 비전 리허설 받아쓰기 onText · 장 넘김 · 녹음 상태를 한 곳에서 본다 (visionCoachSample 이 40ms 마다 부른다) */
function qaListenTick(final, slide, recording, sessionId) {
  if (recording && !qaListen.on) {
    if (!qaListenBegin(sessionId, final)) return;
  }
  if (!qaListen.on) return;
  if (!recording) { qaListenEnd(); return; }
  if (qaListen.state && final !== qaListen.state.lastFinal) qaListenStep({ type: 'text', final, slide });
}

function qaListenTurn(to, from) {
  if (!qaListen.on) return;
  qaListenStep({ type: 'turn', from, to });
  qaListenPeekPool();
}

function qaListenEnd() {
  if (!qaListen.on) return;
  qaListenStep({ type: 'end' });
  qaListenPeekPool();
  qaListen.on = false;          // talk 은 남긴다 — 질문 요청 · 다음 질문이 talk_id 로 이 발표를 찾는다
}

/** 녹음 파일로 대신했다 — 라이브로 말한 발화는 이 녹음의 것이 아니다. 발표를 새로(빈 talk) 시작한 것으로 친다 */
function qaListenDrop(sessionId) {
  const bridge = window.ChuckchuckBridge;
  qaListen.on = false;
  qaListen.state = null;
  if (bridge && typeof bridge.talkRunId === 'function' && sessionId) {
    qaListen.sid = String(sessionId);
    qaListen.talk = bridge.talkRunId(sessionId, { fresh: true });
  }
}

/**
 * 분석이 끝났다 — 일괄 받아쓰기 · 정합을 이 발표(talk)에 붙인다. 발표 중 신호에 흐림 · 어긋남이 더해지고, Q&A 를 일찍 시작했으면
 * 3번+ 고르기가 발표 전체 받아쓰기를 쓴다. Q&A 가 이미 돌고 있으면 세션 아티팩트도 다시 건다(판정 근거).
 */
function qaListenAfterAnalysis(out) {
  const bridge = window.ChuckchuckBridge;
  const sid = (typeof nf !== 'undefined' && nf && nf.sessionId) || qaListen.sid;
  if (!bridge || !out || !sid || typeof bridge.qaLiveFeed !== 'function') return;
  if (!qaListen.talk || qaListen.sid !== String(sid)) {
    qaListen.sid = String(sid);
    qaListen.talk = bridge.talkRunId(sid) || bridge.talkRunId(sid, { fresh: true });
  }
  if (out.alignment || out.transcript) {
    bridge.qaLiveFeed(qaListen.sid, qaListen.talk, { alignment: out.alignment || null, transcript: out.transcript || null, final: true })
      .catch(() => {});
  }
  if (typeof qaLiveActive === 'function' && qaLiveActive() && typeof liveArtifacts === 'function' && bridge.registerSessionArtifacts) {
    const art = liveArtifacts();
    if (art) bridge.registerSessionArtifacts(sid, art).catch(() => {});
  }
}

if (typeof module !== 'undefined') module.exports = { qaListenDelta, qaListenReduce };
