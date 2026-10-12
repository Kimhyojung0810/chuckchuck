/**
 * Q&A 「생각 엮기」 — 리허설 글라스 화상판(#bqStage[data-flow="rehearsal"][data-screen="qa"]) 위 한 겹 (2026-10-13 사용자 브리프).
 * 설계: design/QA_WEAVE.md
 *
 * 웹캠이 무대다 — 이 층은 화면 가장자리와 위 · 아래 띠에만 선다. 얼굴 가운데는 비운다.
 *   위 가운데     삐약이(목소리 구) + 지금 질문 카드 — 이름표 줄(개념 · 꼬리질문 몇 번째) · 방금 반응 한 줄
 *   그 아래       「내 발언」 칩 → 빛줄기 → 삐약이 (꼬리질문이 이 발언에서 나왔다)
 *   왼쪽 가장자리  생각의 흔적 — 질문마다 마디, 같은 개념이면 실이 이어지고 개념이 바뀌면 새 실
 *   아래 가운데   마이크 · 받아쓰기 · 보내기(그대로) + 그 위 상태 한 줄
 *   오른쪽 아래   「다른 주제로」 — A 다른 핵심 개념 · B 같은 주제 다른 관점 · C 건너뛰기 (qa_live.js liveSwitch*)
 *   왼쪽 아래     「도움 · 기록」 — 주고받은 말 전체 · 힌트 · 판정 근거(기존 대화 기둥)를 접어 둔다
 *
 * 정직 규칙 — 데이터는 qa.live 그대로다. 내 발언은 서버가 답 원문에서 확인한 구절(claim)만, 비면 칩을 안 그린다.
 * 꼬리질문의 출처는 「같은 질문 안에서 마지막 채점 답의 claim → 그 판정의 followup」 하나뿐이다(코칭 되물음 · 다시 말하기는 잇지 않는다).
 * 「이해 완료」 같은 확인하지 않은 말은 쓰지 않는다.
 *
 * booth_call.js bcSync 가 스트림이 자랄 때마다 qwSync() 를 부른다. 같은 id(#bcAsk · #bcCount · #bqJudgeSay)를 옮겨 쓸 뿐 로직은 새로 만들지 않는다.
 */

/** 관점 — 서버 f09_reframe.PERSPECTIVES 와 같은 키 (서버가 다시 확인한다) */
const QW_PERSPECTIVES = [['example', '실제 사례'], ['evidence', '근거'], ['counter', '반례'], ['cause', '원인'], ['effect', '결과']];
/** 새 질문이 열릴 때 주제 이름이 머무는 시간 — 0.5~1초 (브리프) */
const QW_TOPIC_MS = 900;
/** 이전 마디에서 보여 줄 발언 수 */
const QW_TRACE_CLAIMS = 2;

const qw = { qi: -1, claimKey: '', menu: false, sub: '', help: false, topicTimer: 0, beamRaf: 0 };

/* ─── 순수 — 흔적 모형 (etc/tests/js/qa_weave.smoke.mjs) ─────────────────────────────── */

/** 질문 하나를 결과 묶음으로 — qa_live.js liveBucket 이 없으면(시험) 넘김 */
function qwState(r) {
  if (!r) return 'skipped';
  if (r.setAside) return 'aside';
  return typeof liveBucket === 'function' ? liveBucket(r) : 'skipped';
}

/**
 * 흔적 모형 — 지난 질문은 마디(그때 내 발언 몇 개), 지금 질문은 큰 마디(이번 질문에서 한 발언).
 * joined: 앞 마디와 같은 개념이면 실이 이어진다(같은 주제 다른 관점). claim: 지금 꼬리질문이 나온 내 발언(없으면 null).
 */
function qwModel(L) {
  if (!L || !Array.isArray(L.questions)) return null;
  const knots = [];
  const upto = Math.min(L.qi, L.questions.length);
  for (let i = 0; i < upto; i += 1) {
    const q = L.questions[i] || {};
    const r = (L.results || [])[i] || null;
    knots.push({
      i, node: q.node_id || q.concept || '', label: q.label || `질문 ${i + 1}`, question: q.question || '',
      perspective: q.perspectiveName || '', state: qwState(r), now: false,
      claims: ((r && r.trail) || []).map((t) => t.claim).filter(Boolean),
    });
  }
  const live = !L.awaitEnd && L.qi < L.questions.length;
  const scored = live ? (L.turns || []).filter((t) => !t.gaveUp && !t.clarify) : [];
  if (live) {
    const q = L.questions[L.qi] || {};
    knots.push({
      i: L.qi, node: q.node_id || q.concept || '', label: q.label || `질문 ${L.qi + 1}`, question: q.question || '',
      perspective: q.perspectiveName || '', state: 'now', now: true, claims: scored.map((t) => t.claim).filter(Boolean),
    });
  }
  knots.forEach((k, j) => { k.joined = j > 0 && !!k.node && k.node === knots[j - 1].node; });
  const last = scored[scored.length - 1];
  const j = L.lastJudgement;
  const followed = !!(last && last.claim && j && j.followup && !j.coach_stage && !L.retell);
  return {
    knots,
    claim: followed ? { text: last.claim, round: scored.length } : null,
    follow: live ? (L.turns || []).filter((t) => !t.clarify).length : 0,
  };
}

/** 새 질문이 열릴 때 잠깐 뜨는 주제 이름 — 앞 질문을 어떻게 닫았는지에 따라 */
function qwTopicText(L) {
  if (!L || L.qi < 1 || L.qi >= L.questions.length) return '';
  const q = L.questions[L.qi] || {};
  const prev = (L.results || [])[L.qi - 1] || {};
  const label = q.label || '';
  if (prev.setAside === 'perspective') return `같은 주제 · ${q.perspectiveName || '다른'} 관점`;
  if (prev.setAside === 'concept') return `다른 개념 · ${label}`;
  if (prev.setAside === 'skip') return `건너뛰고 · ${label}`;
  return `다음 개념 · ${label}`;
}

/** 지금 질문 카드의 이름표 줄 — 개념 · 꼬리질문 몇 번째 · 관점 */
function qwAskMeta(model, L) {
  const cur = model && model.knots[model.knots.length - 1];
  if (!cur || !cur.now) return '';
  const bits = [cur.label];
  if (cur.perspective) bits.push(`${cur.perspective} 관점`);
  if (model.follow > 0 && !(L && L.retell)) bits.push(`꼬리질문 ${model.follow}`);
  return bits.join(' · ');
}

/* ─── 화면 ─────────────────────────────────────────────────────────────── */

function qwLayer() {
  const st = document.getElementById('bqStage');
  return st && st.dataset.flow === 'rehearsal' && st.dataset.screen === 'qa' ? st : null;
}

function qwEsc(s) {
  return typeof escapeHtml === 'function' ? escapeHtml(s) : String(s || '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

/** 한 번만 — 층을 세우고 이름표 · 상태 줄을 옮겨 단다 */
function qwMount(layer, call) {
  layer.dataset.qw = '1';
  call.insertAdjacentHTML('beforeend', `
    <nav class="qw-thread" aria-label="생각의 흔적"><p class="qw-thread-h">생각의 흔적</p><ol id="qwKnots"></ol></nav>
    <svg class="qw-beam" id="qwBeam" aria-hidden="true" focusable="false">
      <defs><linearGradient id="qwBeamG" x1="0" y1="1" x2="0" y2="0">
        <stop offset="0" stop-color="var(--qw-green)" stop-opacity=".15"/><stop offset="1" stop-color="var(--qw-green)" stop-opacity=".95"/>
      </linearGradient></defs>
      <path class="qw-beam-glow" d=""/><path class="qw-beam-path" d=""/><circle class="qw-beam-dot" r="3.5"><animateMotion dur="1.8s" repeatCount="indefinite" path="M0 0"/></circle>
    </svg>
    <p class="qw-claim" id="qwClaim" hidden><span class="qw-claim-k">내 발언</span><q id="qwClaimQ"></q><small>여기서 꼬리질문이 나왔어요</small></p>
    <p class="qw-topic" id="qwTopic" aria-hidden="true" hidden></p>
    <div class="qw-state" id="qwState"></div>
    <div class="qw-switch">
      <div class="qw-menu bc-glass" id="qwMenu" hidden role="group" aria-label="다른 주제로">
        <button type="button" class="qw-opt" data-qw="concept"><b>다른 핵심 개념으로</b><small id="qwConceptSub">아직 안 다룬 개념으로 가요</small></button>
        <button type="button" class="qw-opt" data-qw="perspective" aria-expanded="false" aria-controls="qwPersp"><b>같은 주제, 다른 관점</b><small id="qwPerspSub">사례 · 근거 · 반례 · 원인 · 결과로 다시 물어요</small></button>
        <div class="qw-persp" id="qwPersp" hidden>${QW_PERSPECTIVES.map(([k, name]) => `<button type="button" class="qw-chip" data-qw-p="${k}">${name}</button>`).join('')}</div>
        <button type="button" class="qw-opt" data-qw="skip"><b>이 질문 건너뛰기</b><small>기록에는 남고 실패로 세지 않아요</small></button>
        <button type="button" class="qw-close" data-qw="close">닫기</button>
      </div>
      <button type="button" class="qw-switch-btn" id="qwSwitch" aria-expanded="false" aria-controls="qwMenu">다른 주제로</button>
    </div>
    <button type="button" class="qw-help-btn" id="qwHelp" aria-expanded="false" aria-controls="stream">도움 · 기록</button>`);
  const ask = document.getElementById('bcAsk');
  if (ask && !document.getElementById('qwAskMeta')) {
    ask.insertAdjacentHTML('afterbegin', '<p class="qw-ask-meta"><span id="qwAskMeta"></span></p>');
    ask.insertAdjacentHTML('beforeend', '<p class="qw-whisper" id="qwWhisper" hidden></p>');
    const count = document.getElementById('bcCount');
    if (count) ask.querySelector('.qw-ask-meta').prepend(count);
  }
  const state = document.getElementById('qwState');
  ['bqJudgeSay', 'bcSendCancel'].forEach((id) => { const el = document.getElementById(id); if (el && state) state.appendChild(el); });
  qwWire(layer);
  qw.qi = -1; qw.claimKey = ''; qw.menu = false; qw.sub = ''; qw.help = false;
}

function qwWire(layer) {
  document.getElementById('qwSwitch').addEventListener('click', () => qwMenuOpen(!qw.menu));
  document.getElementById('qwHelp').addEventListener('click', () => {
    qw.help = !qw.help;
    layer.dataset.qwHelp = qw.help ? 'open' : '';
    document.getElementById('qwHelp').setAttribute('aria-expanded', String(qw.help));
    if (qw.help && typeof bcStickBottom === 'function') bcStickBottom(document.getElementById('stream'));
  });
  const menu = document.getElementById('qwMenu');
  menu.addEventListener('click', (e) => {
    const p = e.target.closest('[data-qw-p]');
    if (p) return qwRun(() => liveSwitchPerspective(p.dataset.qwP));
    const opt = e.target.closest('[data-qw]');
    if (!opt) return;
    const what = opt.dataset.qw;
    if (what === 'close') return qwMenuOpen(false, true);
    if (what === 'skip') return qwRun(() => liveSkipQuestion());
    if (what === 'concept') return qwRun(() => liveSwitchConcept());
    if (what === 'perspective') {
      qw.sub = qw.sub === 'perspective' ? '' : 'perspective';
      qwPaintMenu();
      if (qw.sub) { const first = menu.querySelector('.qw-chip:not(:disabled)'); if (first) first.focus(); }
    }
  });
  layer.addEventListener('keydown', (e) => { if (e.key === 'Escape' && qw.menu) { e.stopPropagation(); qwMenuOpen(false, true); } }, true);
  document.addEventListener('pointerdown', qwOutside, true);
  document.getElementById('qwKnots').addEventListener('click', (e) => {
    const k = e.target.closest('.qw-knot-btn');
    if (!k) return;
    const li = k.closest('li');
    const open = li.classList.toggle('is-open');
    k.setAttribute('aria-expanded', String(open));
  });
}

function qwOutside(e) {
  if (!qw.menu) return;
  if (!document.getElementById('qwMenu')) { document.removeEventListener('pointerdown', qwOutside, true); return; }
  if (e.target.closest && e.target.closest('.qw-switch')) return;
  qwMenuOpen(false);
}

function qwMenuOpen(on, refocus = false) {
  qw.menu = !!on && typeof liveCanSwitch === 'function' && liveCanSwitch();
  if (!qw.menu) qw.sub = '';
  // 메뉴를 여는 순간 다른 개념 묶음을 받아 둔다 — 고를 때 덜 기다리게 (브리지 캐시)
  if (qw.menu && typeof liveWarmConceptPool === 'function') {
    const p = liveWarmConceptPool();
    if (p && p.then) p.then(() => { if (qw.menu) qwPaintMenu(); });
  }
  qwPaintMenu();
  const btn = document.getElementById('qwSwitch');
  if (qw.menu) { const first = document.querySelector('#qwMenu .qw-opt'); if (first) first.focus(); }
  else if (refocus && btn) btn.focus();
}

function qwPaintMenu() {
  const menu = document.getElementById('qwMenu');
  const btn = document.getElementById('qwSwitch');
  if (!menu || !btn) return;
  menu.hidden = !qw.menu;
  btn.setAttribute('aria-expanded', String(qw.menu));
  if (!qw.menu) return;
  const L = qa.live;
  const q = L && L.questions[L.qi];
  const pick = typeof livePickConcept === 'function' ? livePickConcept() : null;
  const sub = document.getElementById('qwConceptSub');
  if (sub) sub.textContent = pick ? `아직 안 다룬 「${pick.label || '개념'}」 로 가요` : '아직 안 다룬 개념을 찾아서 가요';
  const trap = !!(q && q.trap);
  const pBtn = menu.querySelector('[data-qw="perspective"]');
  pBtn.disabled = trap;
  pBtn.setAttribute('aria-expanded', String(qw.sub === 'perspective'));
  document.getElementById('qwPerspSub').textContent = trap ? '이 질문은 관점을 바꿀 수 없어요' : '사례 · 근거 · 반례 · 원인 · 결과로 다시 물어요';
  document.getElementById('qwPersp').hidden = qw.sub !== 'perspective' || trap;
  menu.querySelectorAll('button').forEach((b) => { if (b !== pBtn) b.disabled = false; });
}

/** 메뉴에서 고른 일을 한다 — 메뉴를 닫고, 기다리는 동안은 단추를 잠근다 */
async function qwRun(work) {
  qwMenuOpen(false);
  const btn = document.getElementById('qwSwitch');
  if (btn) btn.disabled = true;
  try { await work(); } finally {
    if (btn && btn.isConnected) btn.disabled = false;
    qwSync();
  }
}

/** 흔적 마디 — 지난 질문은 작게(발언 두 개까지), 지금 질문은 크게 */
function qwKnotHtml(k) {
  const claims = k.now ? k.claims : k.claims.slice(-QW_TRACE_CLAIMS);
  const said = claims.map((c) => `<li>「${qwEsc(c)}」</li>`).join('');
  const word = { self: '스스로 설명', helped: '도움 받아 닫음', retold: '답 보고 다시 말함', skipped: '넘김', aside: '다른 주제로', now: '지금' }[k.state] || '';
  return `<li class="qw-knot is-${k.state}${k.now ? ' is-now' : ''}${k.joined ? ' is-joined' : ''}">
    <button type="button" class="qw-knot-btn" aria-expanded="false">
      <i class="qw-dot" aria-hidden="true"></i>
      <span class="qw-knot-label">${qwEsc(k.label)}${k.perspective ? ` <em>· ${qwEsc(k.perspective)}</em>` : ''}</span>
      <span class="bq-sr"> — ${word}</span>
    </button>
    ${said ? `<ul class="qw-said">${said}</ul>` : ''}
    <p class="qw-knot-q">${qwEsc(k.question)}</p>
  </li>`;
}

/** 방금 삐약이 반응 · 열린 힌트 — 지금 질문의 첫 물음 뒤 마지막 것 하나씩. 대화 기둥은 접혀 있어도 이건 보인다 */
function qwWhisper(stream) {
  const kids = stream ? [...stream.children] : [];
  let lead = -1;
  kids.forEach((el, i) => { if (el.matches('.msg.ai.q') && el.dataset.lead === '1') lead = i; });
  let react = null;
  let hint = null;
  let answered = false;
  kids.slice(lead + 1).forEach((el) => {
    if (el.matches('.msg.me')) answered = true;
    if (el.matches('.msg.me')) { react = null; hint = null; }
    else if (el.matches('.msg.ai.react')) react = el;
    else if (el.matches('.msg.ai.hint, .msg.ai.gist')) hint = el;
  });
  const text = (el, drop) => {
    if (!el) return '';
    const b = el.querySelector('.msg-bubble');
    if (!b) return '';
    const c = b.cloneNode(true);
    c.querySelectorAll(drop).forEach((x) => x.remove());
    return c.textContent.replace(/\s+/g, ' ').trim();
  };
  let said = text(react, '.react-head, .qa-grounds, .msg-claim, .hint-slides, .qa-evidence, .msg-meta, [class*="feedback"], .fb, button');
  // 새 질문에 아직 답하기 전 — 대화 기둥이 접혀 있어 앞 질문이 어떻게 닫혔는지(마무리 카드 · 주제 바꿈)가 안 보인다. 그 한 줄을 대신 싣는다
  if (!said && !answered && lead > 0) {
    const prev = kids.slice(0, lead).reverse().find((el) => el.matches('.qa-done, .qa-switch-line'));
    if (prev && prev.matches('.qa-done')) {
      const label = (prev.querySelector('.qd-head b') || {}).textContent || '';
      const word = (prev.querySelector('.qd-head .chip') || {}).textContent || '';
      said = label && word ? `앞 질문 「${label.trim()}」 — ${word.trim()}` : '';
    } else if (prev) said = prev.textContent.replace(/\s+/g, ' ').trim();
  }
  // 펼친 절반(gist)은 머리말(「이렇게 말하면 완성이에요」)을 붙여 — 내 말이 아니라 삐약이가 보여 준 답이라는 걸 같이
  const gistLead = hint && hint.matches('.gist') ? ((hint.querySelector('.msg-meta') || {}).textContent || '').trim() : '';
  const hintText = text(hint, '.hint-slides, .msg-meta, button');
  return { react: said, hint: gistLead && hintText ? `${gistLead}: ${hintText}` : hintText };
}

/** bcSync 끝에서 — 흔적 · 이름표 · 반응 · 내 발언 · 빛줄기 · 주제 바뀜을 qa.live 에 맞춘다 */
function qwSync() {
  const layer = qwLayer();
  const call = layer && layer.querySelector('.bc-call');
  if (!call || !qa.live) return;
  if (layer.dataset.qw !== '1' || !document.getElementById('qwKnots')) qwMount(layer, call);
  const L = qa.live;
  const model = qwModel(L);
  if (!model) return;

  const knots = document.getElementById('qwKnots');
  const html = model.knots.map(qwKnotHtml).join('');
  if (knots.dataset.html !== html) {
    // 펼쳐 둔 마디는 다시 그려도 펼친 채로
    const open = new Set([...knots.querySelectorAll('li.is-open')].map((li) => [...knots.children].indexOf(li)));
    knots.innerHTML = html;
    knots.dataset.html = html;
    [...knots.children].forEach((li, i) => { if (open.has(i)) { li.classList.add('is-open'); li.querySelector('.qw-knot-btn').setAttribute('aria-expanded', 'true'); } });
  }

  const meta = document.getElementById('qwAskMeta');
  if (meta && typeof bqSet === 'function') bqSet(meta, 'textContent', qwAskMeta(model, L));

  const w = qwWhisper(document.getElementById('stream'));
  const whisper = document.getElementById('qwWhisper');
  if (whisper) {
    const line = [w.react, w.hint].filter(Boolean).join('  ·  ');
    if (whisper.textContent !== line) whisper.textContent = line;
    whisper.hidden = !line;
  }

  // 새 질문 — 주제 이름이 잠깐(0.5~1초) 질문 카드 자리에 서고, 흔적이 한 번 접힌다. 웹캠은 그대로
  if (L.qi !== qw.qi) {
    const first = qw.qi < 0;
    qw.qi = L.qi;
    qw.claimKey = '';
    if (!first) qwTopic(layer, qwTopicText(L));
  }

  const claim = document.getElementById('qwClaim');
  const key = model.claim ? `${L.qi}|${model.claim.round}|${model.claim.text}` : '';
  if (claim && claim.hidden !== !model.claim) claim.hidden = !model.claim;   // 질문이 바뀌면 지난 발언 칩은 걷는다
  if (claim && key !== qw.claimKey) {
    qw.claimKey = key;
    if (model.claim) {
      const cq = document.getElementById('qwClaimQ');
      cq.textContent = model.claim.text;
      cq.title = model.claim.text;   // 한 줄로 줄인 칩 — 전문은 흔적 마디를 펼쳐도 보인다
      claim.classList.remove('is-in'); void claim.offsetWidth; claim.classList.add('is-in');
      layer.dataset.qwFresh = '1';
      setTimeout(() => { if (layer.dataset.qwFresh === '1') layer.dataset.qwFresh = ''; }, 1600);
    }
  }
  qwBeam();

  const btn = document.getElementById('qwSwitch');
  const can = typeof liveCanSwitch === 'function' && liveCanSwitch();
  if (btn && !btn.matches(':disabled') !== can) btn.disabled = !can;
  if (qw.menu && !can) qwMenuOpen(false);
  const switching = !!L.switching;
  if ((layer.dataset.qwBusy || '') !== (switching ? '1' : '')) layer.dataset.qwBusy = switching ? '1' : '';
}

function qwTopic(layer, text) {
  const el = document.getElementById('qwTopic');
  if (!el || !text) return;
  el.textContent = text;
  el.hidden = false;
  layer.dataset.qwTopic = '1';
  clearTimeout(qw.topicTimer);
  qw.topicTimer = setTimeout(() => {
    layer.dataset.qwTopic = '';
    el.hidden = true;
  }, QW_TOPIC_MS);
}

/** 빛줄기 — 내 발언 칩 왼쪽 끝에서 삐약이(질문 카드 왼쪽)로. 칩이 없으면 지운다. 크기가 바뀌면 다음 맞춤 때 다시 잰다 */
function qwBeam() {
  cancelAnimationFrame(qw.beamRaf);
  qw.beamRaf = requestAnimationFrame(() => {
    const svg = document.getElementById('qwBeam');
    const claim = document.getElementById('qwClaim');
    const ask = document.getElementById('bcAsk');
    if (!svg) return;
    const path = svg.querySelector('.qw-beam-path');
    const glow = svg.querySelector('.qw-beam-glow');
    if (!claim || claim.hidden || !ask || ask.hidden) { path.setAttribute('d', ''); glow.setAttribute('d', ''); svg.dataset.on = ''; return; }
    const box = svg.getBoundingClientRect();
    const c = claim.getBoundingClientRect();
    const a = ask.getBoundingClientRect();
    const bird = document.querySelector('#bcHost .bc-host-bird');
    const b = bird ? bird.getBoundingClientRect() : { left: a.left + 16, width: 64 };
    const x0 = c.left - box.left - 4;
    const y0 = c.top - box.top + c.height / 2;
    const x1 = b.left - box.left + b.width / 2;
    const y1 = a.bottom - box.top - 6;
    const d = `M ${x0.toFixed(1)} ${y0.toFixed(1)} C ${(x1 + 8).toFixed(1)} ${y0.toFixed(1)}, ${x1.toFixed(1)} ${(y0 - 4).toFixed(1)}, ${x1.toFixed(1)} ${y1.toFixed(1)}`;
    if (path.getAttribute('d') !== d) {
      path.setAttribute('d', d);
      glow.setAttribute('d', d);
      const motion = svg.querySelector('animateMotion');
      if (motion) motion.setAttribute('path', d);
      const len = Math.ceil(path.getTotalLength ? path.getTotalLength() : 200);
      svg.style.setProperty('--qw-len', String(len));
    }
    svg.dataset.on = '1';
  });
}

window.addEventListener('resize', () => { if (document.getElementById('qwBeam')) qwBeam(); });
