/* ──────────────────────────────────────────────────────────────────────────
   #/graph — 개념 그래프 3D 무대

   왜 만들었나: 심사에서 「우와」가 제일 중요하다는 판단 (2026-08-09 지시).
   자료를 읽어 개념 그래프를 만든다는 게 이 제품의 핵심인데, 그동안 그 그래프는
   리빌 2번째 씬에서 잠깐 지나가는 게 전부였다.

   왜 따로 화면인가: 데모 경로(#/new → #/qa → #/report)에 얹지 않는다. 여기가
   깨져도 시연은 그대로 돈다 — 마감 당일에 three.js 를 들이는 값이다.

   왜 vendoring 인가: 부스에서 CDN 을 믿을 수 없다. gsap 과 같은 자리에 둔다.

   판정 색 5종은 CSS 변수에서 읽어 온다. 여기에 hex 를 다시 적으면 리포트와
   무대가 다른 색으로 같은 판정을 말하게 된다 (CLAUDE.md §3-3 — 판정 색은 불변).
   ────────────────────────────────────────────────────────────────────────── */

/** 라이브러리는 이 화면에 처음 들어올 때만 받는다 — 700KB 를 홈에서 물지 않는다. */
let graph3dLibP = null;
function loadForceGraph3D() {
  if (typeof ForceGraph3D === 'function') return Promise.resolve();
  if (graph3dLibP) return graph3dLibP;
  graph3dLibP = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = 'js/vendor/3d-force-graph.min.js';
    s.onload = resolve;
    s.onerror = () => reject(new Error('3D 라이브러리를 못 불러왔어요'));
    document.head.appendChild(s);
  });
  return graph3dLibP;
}

/**
 * 노드 이름표를 **HTML 로** 얹는다 (3D 스프라이트가 아니라).
 *
 * three-spritetext 로 가려다 접었다. 그건 자기 three 를 import 하는데
 * 3d-force-graph 는 자기 three 를 품고 있어서, 한 화면에 three 가 두 벌 뜬다 —
 * 다른 인스턴스로 만든 객체는 씬에 넣어도 안 그려질 수 있다 (실제로 안 나왔다).
 *
 * HTML 이면 그 위험이 아예 없고, Pretendard 를 그대로 써서 작은 카드에서도
 * 또렷하다. 좌표는 라이브러리가 주는 graph2ScreenCoords 로 매 프레임 옮긴다.
 */
function g3dAttachLabels(stage, g, nodes, compact) {
  const layer = document.createElement('div');
  layer.className = 'g3d-labels';
  stage.appendChild(layer);
  const els = nodes.map((n) => {
    const el = document.createElement('span');
    el.className = 'g3d-label';
    el.textContent = n.label;
    layer.appendChild(el);
    return el;
  });
  if (compact) layer.classList.add('is-compact');

  let alive = true;
  const tick = () => {
    if (!alive || !stage.isConnected) { alive = false; return; }
    for (let i = 0; i < nodes.length; i++) {
      const n = nodes[i];
      const el = els[i];
      if (n.x == null) { el.style.opacity = '0'; continue; }
      const p = g.graph2ScreenCoords(n.x, n.y, n.z);
      // 화면 밖이면 감춘다 — 가장자리에 눌어붙은 이름표는 그래프를 지저분하게 만든다
      if (!p || p.x < -40 || p.y < -20 || p.x > stage.clientWidth + 40 || p.y > stage.clientHeight + 20) {
        el.style.opacity = '0';
      } else {
        el.style.opacity = '1';
        el.style.transform = `translate(-50%, 0) translate(${p.x}px, ${p.y}px)`;
      }
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

/** 지금 세션의 그래프·정합. 없으면 null — 없는 그래프를 지어내지 않는다. */
function graph3dSource() {
  const src = (typeof nf !== 'undefined' && nf && nf.pipelineOut)
    ? nf : (loadSession('new-flow') || {});
  const out = src.pipelineOut || null;
  if (!out || !out.graph || !Array.isArray(out.graph.nodes) || !out.graph.nodes.length) return null;
  return { graph: out.graph, alignment: out.alignment || null };
}

/**
 * 판정 → CSS 변수 이름.
 *
 * **app.js:5294 의 표를 그대로 옮긴 것이다** (`aligned: 'ok', missing: 'no',
 * contradiction: 'ct', justified_skip: 'om'`). 처음엔 색 이름만 보고 짐작해서
 * missing 을 올리브, contradiction 을 빨강으로 뒀는데 리포트와 정반대였다 —
 * 같은 개념이 리포트에서 빨강, 무대에서 보라로 보이면 둘 중 하나는 거짓말이다.
 * 판정 색은 의미가 붙어 있어 바꾸지 않는다 (CLAUDE.md §3-3).
 */
const G3D_VERDICT_VAR = {
  aligned: '--ok',
  missing: '--no',
  contradiction: '--ct',
  justified_skip: '--om',
};
const G3D_VERDICT_WORD = {
  aligned: '자기 말로 설명했어요',
  justified_skip: '넘어가도 되는 개념이에요',
  missing: '아직 설명하지 않았어요',
  contradiction: '자료와 다르게 말했어요',
};

function g3dColor(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

/**
 * 그래프 + 정합을 3D 무대가 먹는 모양으로 바꾼다.
 *
 * 판정이 아직 없으면 색을 주지 않는다 — 정합 전에 판정색을 칠하면
 * 「판정이 끝났다」는 거짓말이 된다 (f11_reveal 이 같은 규율을 지킨다).
 */
function g3dData(src) {
  const verdictOf = {};
  const noteOf = {};
  const speechOf = {};
  ((src.alignment && src.alignment.items) || []).forEach((it) => {
    if (!it || !it.node_id) return;
    verdictOf[it.node_id] = it.verdict || '';
    noteOf[it.node_id] = it.note || it.evidence || '';
    speechOf[it.node_id] = it.speech_weight || 0;
  });
  const pending = g3dColor('--text-3', '#8b9a93');
  const nodes = src.graph.nodes.map((n) => {
    const v = verdictOf[n.id] || '';
    return {
      id: n.id,
      label: n.label || n.id,
      summary: n.summary || '',
      slides: n.slide_nos || [],
      weight: n.weight || 0,
      verdict: v,
      note: noteOf[n.id] || '',
      speech: speechOf[n.id] || 0,
      color: v ? g3dColor(G3D_VERDICT_VAR[v] || '--om', pending) : pending,
    };
  });
  const ids = new Set(nodes.map((n) => n.id));
  const links = (src.graph.edges || [])
    .filter((e) => e && ids.has(e.from) && ids.has(e.to))
    .map((e) => ({ source: e.from, target: e.to, kind: e.kind || 'parent' }));
  return { nodes, links };
}

/** 무대 위 개념 카드. 클릭한 개념의 사실만 싣는다 — 없는 값은 줄을 안 만든다. */
function g3dCardHtml(n) {
  const word = G3D_VERDICT_WORD[n.verdict] || '아직 판정 전이에요';
  const slides = (n.slides || []).length
    ? `<p class="g3d-slides">${n.slides.slice(0, 6).join(', ')}장에 나와요</p>` : '';
  const note = n.note ? `<p class="g3d-note">${escapeHtml(n.note)}</p>` : '';
  const summary = n.summary ? `<p class="g3d-sum">${escapeHtml(n.summary)}</p>` : '';
  return `<button class="g3d-close" id="g3dClose" type="button" aria-label="닫기">✕</button>
    <span class="g3d-verdict" style="color:${n.color}">${word}</span>
    <h3>${escapeHtml(n.label)}</h3>
    ${summary}${note}${slides}`;
}

function renderGraph3D() {
  app.className = '';
  const src = graph3dSource();
  if (!src) {
    // 분석 결과가 없으면 없다고 말한다. 샘플 그래프로 위장하지 않는다 (CLAUDE.md §4).
    app.innerHTML = `<main class="narrow"><div class="card">
      <h3 class="section-title">아직 보여줄 개념 그래프가 없어요</h3>
      <p class="note">자료를 올리고 발표를 한 번 분석하면 여기에 그려져요.</p>
      <div class="step-actions"><a class="btn btn-primary" href="#/new">발표 연습 시작하기</a></div>
    </div></main>`;
    return;
  }

  const data = g3dData(src);
  const judged = data.nodes.filter((n) => n.verdict).length;
  app.innerHTML = `<div class="g3d-wrap">
      <div class="g3d-top">
        <a class="g3d-back" href="#/report">← 리포트로</a>
        <div class="g3d-title">
          <b>내 자료는 이렇게 짜여 있어요</b>
          <span>개념 ${data.nodes.length}개 · 연결 ${data.links.length}개${
            judged ? ` · 판정 ${judged}개` : ' · 판정은 아직이에요'}</span>
        </div>
      </div>
      <div class="g3d-stage" id="g3dStage"><p class="g3d-loading">무대를 세우고 있어요…</p></div>
      <div class="g3d-legend">
        <span><i style="background:${g3dColor('--ok', '#0A8F68')}"></i>설명했어요</span>
        <span><i style="background:${g3dColor('--no', '#DC2626')}"></i>아직 설명 안 했어요</span>
        <span><i style="background:${g3dColor('--ct', '#9333EA')}"></i>자료와 다르게 말했어요</span>
        <span><i style="background:${g3dColor('--om', '#8A6A15')}"></i>넘어가도 돼요</span>
        <span class="g3d-hint">개념을 누르면 자세히 보여줘요 · 끌어서 돌려볼 수 있어요</span>
      </div>
      <aside class="g3d-card" id="g3dCard" hidden></aside>
    </div>`;

  mountGraph3D($('#g3dStage'), data, { onPick: (n) => {
    const card = $('#g3dCard');
    card.innerHTML = g3dCardHtml(n);
    card.hidden = false;
    const close = $('#g3dClose');
    if (close) close.addEventListener('click', () => { card.hidden = true; });
  } });
}

/**
 * 무대를 아무 칸에나 세운다.
 *
 * 전용 화면(#/graph)과 리포트 안의 카드가 **같은 함수를 쓴다** — 둘이 갈라지면
 * 한쪽만 고쳐져서 같은 그래프가 두 얼굴이 된다. compact 는 리포트용으로
 * 회전을 늦추고 이름표를 조금 줄인다.
 */
function mountGraph3D(stage, data, { onPick = null, compact = false } = {}) {
  if (!stage) return;
  return loadForceGraph3D().then(() => {
    stage.innerHTML = '';
    const showCard = (n) => { if (onPick) onPick(n); };

    const g = ForceGraph3D()(stage)
      .graphData(data)
      .backgroundColor('#0A1F17')          // 딥그린 계열 어두운 면 — 무대라 밝게 두지 않는다
      .showNavInfo(false)
      .nodeLabel((n) => n.label)
      .nodeColor((n) => n.color)
      // 자료가 힘을 실은 개념일수록 크다. weight 는 0~1 이라 그대로 쓰면 다 비슷해진다.
      .nodeVal((n) => 1 + n.weight * 14)
      .nodeOpacity(0.92)
      .nodeResolution(16)
      .linkColor((l) => (l.kind === 'relates' ? 'rgba(255,255,255,.22)' : 'rgba(255,255,255,.45)'))
      .linkWidth((l) => (l.kind === 'relates' ? 0.4 : 1.1))
      // parent 간선에만 입자를 흘린다 — 자료의 뼈대가 어디로 흐르는지가 보인다
      .linkDirectionalParticles((l) => (l.kind === 'relates' ? 0 : 2))
      .linkDirectionalParticleWidth(1.6)
      .linkDirectionalParticleSpeed(0.006)
      .onNodeClick((n) => {
        showCard(n);
        // 누른 개념 앞으로 카메라를 옮긴다 — 「눌렀다」가 눈에 보여야 한다
        const dist = 130;
        const r = Math.hypot(n.x, n.y, n.z) || 1;
        g.cameraPosition(
          { x: n.x * (1 + dist / r), y: n.y * (1 + dist / r), z: n.z * (1 + dist / r) },
          n, 900,
        );
      });

    // 천천히 도는 무대. 손을 대면 멈춘다 — 보고 있는 걸 계속 돌리면 멀미가 난다.
    const controls = g.controls();
    if (controls) {
      controls.autoRotate = !matchMedia('(prefers-reduced-motion: reduce)').matches;
      controls.autoRotateSpeed = compact ? 0.35 : 0.55;
      controls.addEventListener('start', () => { controls.autoRotate = false; });
    }

    const fit = () => {
      g.width(stage.clientWidth);
      g.height(stage.clientHeight);
    };
    fit();
    window.addEventListener('resize', fit);
    setTimeout(() => g.zoomToFit(900, compact ? 90 : 60), 700);
    g3dAttachLabels(stage, g, data.nodes, compact);
    return g;
  }).catch((err) => {
    // 못 불러왔으면 빈 무대를 두지 않고 이유를 적는다
    stage.innerHTML = `<p class="g3d-loading">3D 무대를 못 띄웠어요 — ${escapeHtml(String(err.message || err))}</p>`;
  });
}

/**
 * 리포트 안의 개념 지도. **전용 화면이 아니라 여기가 제자리다** — 리포트는
 * 개념마다 판정을 늘어놓는 화면이고, 이 그래프는 그 판정들의 지도다
 * (2026-08-10 사용자: "서비스 내부에 자연스럽게 삽입되면 좋겠다").
 *
 * 무거운 것을 리포트를 열자마자 물지 않는다. 카드가 화면에 들어올 때 세운다.
 */
function mountReportGraph() {
  const stage = document.getElementById('repGraphStage');
  if (!stage || stage.dataset.mounted) return;
  const src = graph3dSource();
  if (!src) { stage.innerHTML = '<p class="g3d-loading">개념 그래프가 아직 없어요</p>'; return; }
  const data = g3dData(src);
  const card = document.getElementById('repGraphCard');
  const start = () => {
    if (stage.dataset.mounted) return;
    stage.dataset.mounted = '1';
    mountGraph3D(stage, data, {
      compact: true,
      onPick: (n) => {
        if (!card) return;
        card.innerHTML = g3dCardHtml(n);
        card.hidden = false;
        const close = document.getElementById('g3dClose');
        if (close) close.addEventListener('click', () => { card.hidden = true; });
      },
    });
  };
  if (typeof IntersectionObserver === 'function') {
    const io = new IntersectionObserver((es) => {
      if (es.some((e) => e.isIntersecting)) { io.disconnect(); start(); }
    }, { rootMargin: '200px' });
    io.observe(stage);
  } else {
    start();
  }
}

window.renderGraph3D = renderGraph3D;
window.mountReportGraph = mountReportGraph;
