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

  const stage = $('#g3dStage');
  loadForceGraph3D().then(() => {
    stage.innerHTML = '';
    const card = $('#g3dCard');
    const showCard = (n) => {
      card.innerHTML = g3dCardHtml(n);
      card.hidden = false;
      const close = $('#g3dClose');
      if (close) close.addEventListener('click', () => { card.hidden = true; });
    };

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
      controls.autoRotateSpeed = 0.55;
      controls.addEventListener('start', () => { controls.autoRotate = false; });
    }

    const fit = () => {
      g.width(stage.clientWidth);
      g.height(stage.clientHeight);
    };
    fit();
    window.addEventListener('resize', fit);
    setTimeout(() => g.zoomToFit(900, 60), 700);
  }).catch((err) => {
    // 못 불러왔으면 빈 무대를 두지 않고 이유를 적는다
    stage.innerHTML = `<p class="g3d-loading">3D 무대를 못 띄웠어요 — ${escapeHtml(String(err.message || err))}</p>`;
  });
}

window.renderGraph3D = renderGraph3D;
