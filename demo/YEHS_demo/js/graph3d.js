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

  /* 열두 개면 **전부** 이름표를 단다. 한때 상위 몇 개만 골라 달았는데, 그건
     노드가 열일곱이라 서로 덮여서 어쩔 수 없던 것이었다 (실측 48쌍 겹침).
     상한이 생기면서 그 군더더기가 사라졌다 — 그래프에 이름 없는 점이 섞여
     있으면 「연결되어 있다」를 읽는 눈이 그 점에서 걸린다. */
  const named = nodes;

  const els = named.map((n) => {
    const el = document.createElement('span');
    el.className = 'g3d-label';
    /* 판정 점 + 이름 + 비중 막대(금색) + 말한 정도 막대(초록). 공 크기로 비중을
       주긴 하지만 3D 는 원근·겹침 때문에 «어느 게 더 큰가」가 눈으로 잘 안
       잡힌다 (2026-08-12 사용자: 가중치 구분이 안 된다) — 이름표에 숫자 그대로
       막대를 하나 더 그려서 크기에 의존하지 않고도 비중이 바로 읽히게 한다. */
    el.innerHTML = `<i style="background:${n.dot || n.color}"></i>${escapeHtml(n.label)}`
      + `<em style="--wt:${Math.round((n.weight || 0) * 100)}%" title="자료가 실은 비중"></em>`
      + (n.verdict ? `<b style="--sp:${Math.round((n.speech || 0) * 100)}%"></b>` : '');
    layer.appendChild(el);
    return el;
  });
  if (compact) layer.classList.add('is-compact');

  let alive = true;
  const tick = () => {
    if (!alive || !stage.isConnected) { alive = false; return; }
    for (let i = 0; i < named.length; i++) {
      const n = named[i];
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

  return (focus) => {
    named.forEach((n, i) => {
      const on = !focus || n.id === focus.id || (focus.kin && focus.kin.has(n.id));
      els[i].classList.toggle('is-dim', !on);
    });
  };
}

/**
 * 지금 세션의 그래프·정합. 없으면 null — 없는 그래프를 지어내지 않는다.
 *
 * 예외: **쇼케이스 모드에서는 예외다.** #/graph 는 부스에서 주소를 직접 쳐서
 * 들어가는 화면이라(§2 사이드바 주석), #/new 연습을 한 번도 안 돌린 첫 방문
 * 이면 pipelineOut 이 비어 있다 — 그러면 그냥 빈 화면이 뜬다(2026-08-12 실측:
 * "아직 보여줄 개념 그래프가 없어요"). SHOWCASE_DEMO 는 애초에 리포트·질문
 * 코칭도 전부 이 더미로 고정해서 보여주므로(app.js showcasePipelineStub), 여기도
 * 같은 더미를 쓰는 게 "없는 그래프를 지어내는" 게 아니라 이미 켜진 쇼케이스를
 * 이 화면에도 켜는 것이다.
 */
function graph3dSource() {
  const src = (typeof nf !== 'undefined' && nf && nf.pipelineOut)
    ? nf : (loadSession('new-flow') || {});
  const out = src.pipelineOut || null;
  if (out && out.graph && Array.isArray(out.graph.nodes) && out.graph.nodes.length) {
    return { graph: out.graph, alignment: out.alignment || null };
  }
  if (typeof isShowcaseDemo === 'function' && isShowcaseDemo()
    && typeof showcasePipelineStub === 'function') {
    const stub = showcasePipelineStub();
    if (stub && stub.graph && Array.isArray(stub.graph.nodes) && stub.graph.nodes.length) {
      return { graph: stub.graph, alignment: stub.alignment || null };
    }
  }
  return null;
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


/** 링크가 이 개념에 닿는가. source/target 은 문자열이거나 노드 객체다. */
function g3dLinkTouches(l, id) {
  const s = typeof l.source === 'object' ? l.source.id : l.source;
  const t = typeof l.target === 'object' ? l.target.id : l.target;
  return s === id || t === id;
}
/** 이 개념의 이웃 집합 (g3dData 가 미리 만들어 둔 것). */
function g3dKinOf(data, id) {
  const n = data.nodes.find((x) => x.id === id);
  return (n && n.kin) || new Set();
}
/** 죽여 둘 색. 지우지 않고 흐리게만 둔다 — 사라지면 «연결이 없다»로 읽힌다. */
function g3dFade(color) {
  const m = /^rgba?\(([^)]+)\)$/.exec(String(color || ''));
  if (m) { const p = m[1].split(',').map((x) => x.trim()); return `rgba(${p[0]},${p[1]},${p[2]},.10)`; }
  const h = String(color || '').replace('#', '');
  if (h.length !== 6) return color;
  const n = parseInt(h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},.10)`;
}

/** 무대에 세울 개념 수 상한. 리빌(MAX_REVEAL_NODES)과 같은 값이다 —
 *  한 자료를 두 화면이 다른 개수로 보여주면 어느 쪽이 맞는지 알 수 없다. */
const G3D_MAX_NODES = 12;

function g3dColor(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

/**
 * 판정색 + 발화량 → rgba.
 *
 * **이 화면이 말해야 할 것은 「자료 vs 발표」다.** 크기(자료가 실은 비중)만
 * 쓰고 speech_weight 를 안 쓰면, 개념 그래프이긴 해도 우리 제품의 발견은
 * 하나도 안 보인다 (2026-08-10 사용자: "정보가 없다").
 *
 * 그래서 진하기로 «실제로 말한 정도»를 싣는다. 크고 흐린 공 = 자료는 힘을
 * 실었는데 말로는 거의 안 나온 개념 — 그게 이 발표에서 제일 먼저 봐야 할 것이다.
 * 아예 0 으로 두지 않는 이유: 안 말한 개념이 사라지면 «빠진 것»이 안 보인다.
 */
function g3dRgba(hex, alpha) {
  const h = String(hex || '').replace('#', '');
  if (h.length !== 6) return hex;
  const n = parseInt(h, 16);
  const a = Math.max(0, Math.min(1, alpha));
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a.toFixed(2)})`;
}

/**
 * 판정 → 이 개념이 화면에서 낼 «소리 크기».
 *
 * 넷을 대등한 채도로 칠했더니 초록·빨강·보라·올리브가 동시에 소리쳐서 어느
 * 것도 안 들렸다 — 강조가 넷이면 강조가 0이다 (2026-08-10 사용자: "색을 어쩌면
 * 좋지").
 *
 * 토스 문서에서 답을 가져왔다. Bubble 은 두 상태를 구분하는 데 색을 둘 쓰지
 * 않는다 — 「blue 는 나, grey 는 상대방」, 즉 의미 있는 쪽만 색을 갖고 나머지는
 * 무채색이다 (TDS.md:2254). 주력 팔레트도 greyOpacity 9단계다.
 *
 * 그래서 **색상은 안 바꾸고 세기만 바꾼다.** 잘한 것(설명함·넘어가도 됨)은
 * 뒤로 물러나고, 봐야 할 것(아직·다르게)만 앞으로 나온다. 색상을 바꾸면
 * 같은 개념이 리포트에서 빨강, 지도에서 회색이 되어 둘 중 하나가 거짓말이
 * 되는데, 세기만 바꾸면 그 일은 안 생긴다.
 *
 * 말한 정도(speech)는 이제 «잘한 쪽»에서만 쓴다. 문제는 얼마나 말했든 문제다.
 */
function g3dStrength(verdict, speech) {
  if (verdict === 'missing' || verdict === 'contradiction') return 0.95;
  // 바닥을 너무 낮게 두면 큰 공도 크림 배경에 묻혀 «크기(=비중)」가 안 읽힌다
  // (2026-08-12 사용자: 가중치 구분이 안 된다). 실루엣이 살 만큼만 올린다.
  if (verdict === 'aligned') return 0.34 + Math.max(0, Math.min(1, speech || 0)) * 0.32;
  if (verdict === 'justified_skip') return 0.30;
  return 0.28;   // 판정 전
}

/**
 * 공이 쓸 색. **두 가지뿐이다** — 괜찮은 것은 브랜드 그린, 봐야 할 것은 빨강.
 *
 * 판정은 넷인데 색을 넷 주면 화면이 넷을 동시에 주장한다. 지도가 할 일은
 * 「어디를 봐야 하나」 하나이고, 「어떤 종류의 문제인가」는 그 다음 질문이다.
 * 그래서 공은 둘로 줄이고, 넷의 구분은 **이름표의 6px 점**이 그대로 들고 있다
 * (점은 작아서 소리치지 않으면서 알려 준다). 눌러서 나오는 카드가 문장으로
 * 다시 말해 주므로 잃는 정보는 없다.
 *
 * 색을 바꿔도 된다는 허락을 받고 고른 답이다 (2026-08-10). 토스의 Bubble 이
 * 두 상태를 blue·grey 로 가르는 것과 같은 구조다 (TDS.md:2254).
 */
function g3dBallHue(verdict) {
  return (verdict === 'missing' || verdict === 'contradiction')
    ? g3dColor('--no', '#DC2626')
    : g3dColor('--brand', '#08B879');
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
      depth: Math.min(Math.max(n.depth || 1, 1), 4),
      verdict: v,
      note: noteOf[n.id] || '',
      speech: speechOf[n.id] || 0,
      color: v ? g3dColor(G3D_VERDICT_VAR[v] || '--om', pending) : pending,
    };
  });
  // 세기 = 지금 봐야 할 정도. 판정 전이면 가장 조용하게 둔다 — 안 잰 것을
  // 앞으로 내밀면 「판정이 끝났다」로 읽힌다.
  nodes.forEach((n) => {
    // 이름표의 점은 **원래 채도 그대로** 둔다. 6px 짜리라 소리치지 않으면서도
    // 「이 개념이 어떤 판정인지」는 알려줘야 하는데, 공과 같이 흐려 놓으면
    // 크림색 칩 위에서 아예 안 보인다.
    n.dot = n.color;                        // 판정 4종 — 이름표의 점이 들고 간다
    n.color = g3dRgba(g3dBallHue(n.verdict), g3dStrength(n.verdict, n.speech));
  });
  /* **자료가 힘을 실은 상위 12개만 그린다.** 열일곱 개에 한글 이름표를 다 붙이면
     서로를 덮어 아무것도 안 읽힌다 (실측 48쌍 겹침). 리빌도 같은 상한을 쓴다.
     열둘이면 이름표를 전부 달 수 있어서 「골라 단다」는 군더더기도 사라진다.
     자른 사실은 화면이 말한다 — 안 그러면 «자료에 개념이 12개뿐» 으로 읽힌다. */
  const shown = [...nodes].sort((a, b) => b.weight - a.weight).slice(0, G3D_MAX_NODES);
  const ids = new Set(shown.map((n) => n.id));
  const weightOf = {};
  shown.forEach((n) => { weightOf[n.id] = n.weight; });
  /* 중요도(imp) — parent(뼈대)는 늘 1. relates 는 두 끝 개념이 자료에서 얼마나
     무거운지의 평균으로 정한다. kind 둘로만 가르면(2026-08-12 이전) relates
     열몇 개가 서로 다 똑같이 보여서 «어떤 연결이 진짜 중요한가」가 안 와닿았다
     (2026-08-12 사용자: 여전히 안 와닿는다) — 무거운 개념 둘을 잇는 선일수록
     굵고 밝아야 한다. */
  const links = (src.graph.edges || [])
    .filter((e) => e && ids.has(e.from) && ids.has(e.to))
    .map((e) => {
      const kind = e.kind || 'parent';
      const imp = kind === 'parent'
        ? 1
        : Math.max(0.1, Math.min(1, ((weightOf[e.from] || 0.5) + (weightOf[e.to] || 0.5)) / 2));
      return { source: e.from, target: e.to, kind, imp };
    });
  // 이웃 표. 누른 개념의 연결을 밝히고 나머지를 죽일 때 쓴다 — 「이어져 있다」를
  // 말로 하지 않고 눈으로 보여주는 유일한 방법이다.
  const kin = {};
  links.forEach((l) => {
    (kin[l.source] || (kin[l.source] = new Set())).add(l.target);
    (kin[l.target] || (kin[l.target] = new Set())).add(l.source);
  });
  shown.forEach((n) => { n.kin = kin[n.id] || new Set(); });
  return { nodes: shown, links, total: nodes.length, totalLinks: (src.graph.edges || []).length };
}


/**
 * 개념 이름 뒤에 붙일 주격 조사. 받침이 있으면 «이», 없으면 «가».
 *
 * 「작업 맥락가」 처럼 나오면 문장이 아니라 템플릿으로 읽힌다. 개념 이름은
 * 자료에서 그대로 오는 값이라 어떤 글자로 끝날지 우리가 못 고른다.
 */
function g3dSubject(word) {
  const ch = String(word || '').trim().slice(-1);
  const code = ch.charCodeAt(0);
  if (Number.isNaN(code) || code < 0xAC00 || code > 0xD7A3) return '가';
  return (code - 0xAC00) % 28 ? '이' : '가';
}

/**
 * 무대가 말하는 한 줄 요약.
 *
 * 그림만 두면 「그래프가 있다」로 끝난다. 이 발표에서 **무엇이 문제인지**는
 * 숫자가 말해야 한다 — 특히 «자료가 힘줬는데 아직 말 안 한 개념»이 몇 개인가.
 * 전부 코드가 세는 값이라 지어낸 숫자가 아니다 (UI_REDESIGN §14).
 */
function g3dSummaryHtml(nodes) {
  const judged = nodes.filter((n) => n.verdict);
  if (!judged.length) return '<span class="g3d-sum-pending">판정은 아직이에요</span>';
  const by = (v) => judged.filter((n) => n.verdict === v).length;
  // 자료가 힘을 실었는데(상위 절반) 아직 안 말한 개념 — 제일 먼저 봐야 할 것
  const heavy = [...judged].sort((a, b) => b.weight - a.weight).slice(0, Math.ceil(judged.length / 2));
  const heavyMissing = heavy.filter((n) => n.verdict === 'missing');
  return `
    <b class="g3d-k ok">설명함 ${by('aligned')}</b>
    <b class="g3d-k no">아직 ${by('missing')}</b>
    ${by('contradiction') ? `<b class="g3d-k ct">다르게 ${by('contradiction')}</b>` : ''}
    ${by('justified_skip') ? `<b class="g3d-k om">넘어가도 됨 ${by('justified_skip')}</b>` : ''}
    ${heavyMissing.length
      ? `<span class="g3d-lead g3d-lead-warn">자료가 힘준 개념 중 <b>${escapeHtml(heavyMissing[0].label)}</b>${
          heavyMissing.length > 1 ? ` 외 ${heavyMissing.length - 1}개가` : g3dSubject(heavyMissing[0].label)
        } 아직 말로 안 나왔어요</span>`
      : '<span class="g3d-lead g3d-lead-ok">자료가 힘준 개념은 모두 말로 나왔어요</span>'}`;
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
  app.innerHTML = `<div class="g3d-wrap">
      <div class="g3d-top">
        <a class="g3d-back" href="#/report">← 리포트로</a>
        <div class="g3d-title">
          <b>내 자료는 이렇게 짜여 있어요</b>
          <span>${data.total > data.nodes.length
            ? `개념 ${data.total}개 중 자료가 힘준 ${data.nodes.length}개 · 그 사이 연결 ${data.links.length}개`
            : `개념 ${data.nodes.length}개 · 연결 ${data.links.length}개`}</span>
        </div>
        <div class="g3d-summary">${g3dSummaryHtml(data.nodes)}</div>
      </div>
      <div class="g3d-stage" id="g3dStage"><p class="g3d-loading">무대를 세우고 있어요…</p></div>
      <div class="g3d-legend">
        <span><i style="background:${g3dRgba(g3dColor('--brand', '#08B879'), 0.4)}"></i>자기 말로 설명했어요</span>
        <span><i style="background:${g3dColor('--no', '#DC2626')}"></i>아직 못 했거나 다르게 말했어요</span>
        <span class="g3d-hint">공 크기와 이름표의 금색 막대가 자료가 실은 비중이에요 · 초록 막대는 실제로 말한 정도예요 · 점이 판정 네 가지를 나눠요 · 개념을 누르면 이어진 것만 남아요</span>
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
  /* **층으로 묶지 않는다.** 한때 depth 로 y 를 고정해 트리처럼 세웠는데,
     이 자료가 말하는 것은 위계가 아니라 «개념들이 서로 얽혀 있다» 이다
     (2026-08-10 지시: 트리 말고 그래프인 걸 보여줘야 한다). 층을 묶으면
     가로줄 몇 개로 보여서 그 얽힘이 통째로 사라진다. force 에 맡기고
     대신 연결을 굵고 밝게 그린다. */
  let focusId = null;
  /** 이름표도 같이 죽인다 — 공만 흐려지고 글자가 또렷하면 초점이 안 생긴다. */
  let layerFocus = () => {};
  return loadForceGraph3D().then(() => {
    stage.innerHTML = '';
    stage.classList.remove('is-ready');
    /* 자리가 잡히기 전 무대(캔버스)는 숨겨 둔다 — 이 로딩 문구만 보인다.
       예전엔 캔버스가 바로 보여서, 흩어진 공이 3초 넘게 스스로 모이는 걸
       그대로 보여줬다(2026-08-12 사용자: 처음 뜰 때부터 이미 꽉 차 있었으면
       좋겠다). 자리가 다 잡힌 뒤에 한 번에 켜면 "자라나는" 인상이 없다. */
    const loadingEl = document.createElement('p');
    loadingEl.className = 'g3d-loading';
    loadingEl.textContent = '무대를 세우고 있어요…';
    stage.appendChild(loadingEl);
    const showCard = (n) => { if (onPick) onPick(n); };

    /* controlType 을 orbit 으로 고정한다. 이 라이브러리의 기본은 trackball 인데
       TrackballControls 에는 autoRotate 가 아예 없어서, 켠 줄 알았던 자동 회전이
       조용히 아무 일도 안 했다 (실측: 5초 동안 이름표가 0.7px 움직였다). */
    const g = ForceGraph3D({ controlType: 'orbit' })(stage)
      .graphData(data)
      /* 캔버스는 투명하게 두고, 무대의 실제 면은 CSS 비네트(g3d-stage 배경)가
         맡는다. 처음엔 어두운 딥그린을 깔았는데, 밝은 화면 한가운데 검은
         판이 박혀서 화면을 뚫어 놓은 것처럼 보였다 (2026-08-10 사용자).
         평평한 단색만 깔면 「무대」가 어디서 시작하고 끝나는지 안 보인다
         (2026-08-12 사용자: 배경이 뭔지 모르겠다) — CSS 쪽에서 중심이 밝고
         가장자리가 살짝 짙어지는 결을 준다. 판정 5색은 밝은 면에서 더 또렷하다. */
      .backgroundColor('rgba(0,0,0,0)')
      .showNavInfo(false)
      /* 위계는 **우리가 직접 층으로 세운다** (아래 fy 고정 참고).
         라이브러리의 dagMode 를 먼저 써 봤는데 relates 간선이 순환을 만들어
         계층 계산이 무너지고, 열일곱 개가 한 줄로 뭉쳐 아무것도 안 읽혔다.
         우리는 f07 이 준 depth 를 이미 들고 있으니 그걸 쓰면 순환과 무관하다. */
      .nodeLabel((n) => n.label)
      .nodeColor((n) => (focusId && n.id !== focusId && !g3dKinOf(data, focusId).has(n.id)
        ? g3dFade(n.color) : n.color))
      // 자료가 힘을 실은 개념일수록 크다. weight 는 0~1 이라 그대로 쓰면 다 비슷해진다.
      /* weight 를 넓게 벌린다. 1.4·60 으로는 가장 무거운 것과 가장 가벼운 것의
         지름 차이가 1.8배 정도라 눈으로 «이게 더 무겁다」를 못 잡았다
         (2026-08-12 사용자: 가중치 구분이 안 된다). 지수·배율을 올려 지름
         차이를 2배 이상으로 벌린다 — 부피는 반지름의 세제곱이라 nodeVal 은
         그보다 훨씬 크게 벌려야 한다. */
      /* 지름 차이를 더 크게 벌린다 (2026-08-12 사용자: 노드도 더 극적으로).
         2.0·170 이면 가장 무거운 것과 가장 가벼운 것의 지름 차이가 눈에
         확 들어온다 — 부피는 반지름의 세제곱이라 nodeVal 은 그보다 크게 벌린다. */
      .nodeVal((n) => 3 + Math.pow(n.weight, 2.0) * 170)
      .nodeOpacity(0.95)
      .nodeResolution(28)
      /* 밝은 면이라 선은 흰색이 아니라 딥그린 계열로 어둡게 — 흰 선은 안 보인다.
         kind 둘로만(parent/relates) 가른 이전 버전은 relates 열몇 개가 서로 다
         똑같아서 «어떤 게 중요한 연결인가」가 안 와닿았다(2026-08-12 사용자) —
         이제 g3dData 가 준 imp(0~1, 두 끝 개념의 비중)로 선마다 다르게 그린다.
         낮은 imp 는 거의 안 보일 만큼 죽이고, 높은 imp 는 굵고 진하게 — 그
         차이 자체가 «중요/안 중요」를 말한다. */
      .linkColor((l) => {
        const on = !focusId || g3dLinkTouches(l, focusId);
        const imp = l.imp == null ? 0.4 : l.imp;
        if (!on) return 'rgba(21,92,70,.05)';
        const a = 0.10 + Math.pow(imp, 1.4) * 0.82;
        return `rgba(21,92,70,${a.toFixed(2)})`;
      })
      .linkWidth((l) => {
        const imp = l.imp == null ? 0.4 : l.imp;
        const w = 0.6 + Math.pow(imp, 1.2) * 4.6;
        return (focusId && g3dLinkTouches(l, focusId)) ? w * 2.2 : w;
      })
      /* 입자도 중요도를 따라간다. 안 중요한 선까지 다 흘리면 화면이 산만해져
         정작 중요한 흐름이 묻힌다 — 중요한 선만 흐르게 두면 «이게 뼈대다» 가
         저절로 보인다. */
      .linkDirectionalParticles((l) => {
        const imp = l.imp == null ? 0.4 : l.imp;
        if (imp < 0.55) return 0;
        return imp >= 0.85 ? 3 : 2;
      })
      .linkDirectionalParticleWidth((l) => 1.8 + (l.imp == null ? 0.4 : l.imp) * 2.4)
      .linkDirectionalParticleSpeed((l) => 0.004 + (l.imp == null ? 0.4 : l.imp) * 0.006)
      .onNodeClick((n) => {
        /* 누른 개념과 **이어진 것만** 남기고 나머지를 죽인다. 이 화면이 하려는
           말이 「개념들이 서로 얽혀 있다」인데, 색색 공이 떠 있는 그림만으로는
           그게 안 읽힌다 — 하나를 누를 때마다 실이 몇 가닥 딸려 나와야 한다.
           같은 개념을 다시 누르면 원래대로 돌아온다. */
        focusId = (focusId === n.id) ? null : n.id;
        g.nodeColor(g.nodeColor()).linkColor(g.linkColor()).linkWidth(g.linkWidth());
        stage.classList.toggle('is-focused', !!focusId);
        if (focusId) layerFocus(n); else layerFocus(null);
        showCard(n);
        // 누른 개념 앞으로 카메라를 옮긴다 — 「눌렀다」가 눈에 보여야 한다
        // 공이 클수록 멀리서 잡는다. 고정 거리로 두면 큰 개념을 눌렀을 때
        // 화면을 꽉 채우다 못해 잘려 나간다 — 이웃을 보여주려던 클릭인데
        // 정작 이웃이 화면 밖으로 밀린다.
        const dist = 150 + n.weight * 260;
        const r = Math.hypot(n.x, n.y, n.z) || 1;
        g.cameraPosition(
          { x: n.x * (1 + dist / r), y: n.y * (1 + dist / r), z: n.z * (1 + dist / r) },
          n, 900,
        );
      });

    // 천천히 도는 무대. 손을 대면 멈춘다 — 보고 있는 걸 계속 돌리면 멀미가 난다.
    /* 아무도 안 건드려도 **스스로 천천히 떠다닌다** (2026-08-10 지시).
       예전엔 손을 대면 회전이 영영 멈췄다 — 한 번 돌려 본 사람에게는 그 뒤로
       죽은 그림이 됐다. 이제 손을 떼고 잠깐 지나면 알아서 다시 돈다.

       속도를 사인으로 흔드는 이유: 일정한 속도로 도는 건 회전판이라 기계처럼
       보인다. 느려졌다 빨라졌다 해야 «떠다닌다»로 읽힌다. 모션을 줄이겠다고
       한 사람에게는 아무것도 안 움직인다 (prefers-reduced-motion). */
    const controls = g.controls();
    if (controls) {
      const wants = !matchMedia('(prefers-reduced-motion: reduce)').matches;
      /* 「돈다」가 눈에 보이되 읽는 걸 방해하지 않는 선.
         작은 카드는 각속도가 같아도 화면에서 움직이는 픽셀이 훨씬 적다 —
         1.1 로 뒀더니 2초에 2.5~4.6px 라 멈춘 것과 구별이 안 됐다. 그래서
         compact 쪽을 오히려 더 빠르게 둔다(한 바퀴 ~20초). 전체 화면은
         그림이 커서 1.6 으로도 충분히 보인다(~40초). */
      const base = compact ? 3.0 : 1.6;
      controls.autoRotate = wants;
      controls.autoRotateSpeed = base;
      let idleAt = 0;
      controls.addEventListener('start', () => { controls.autoRotate = false; idleAt = 0; });
      controls.addEventListener('end', () => { idleAt = performance.now(); });
      const drift = (t) => {
        if (!stage.isConnected) return;
        if (wants) {
          // 손을 뗀 뒤 4초가 지나면 다시 돈다. 바로 돌면 놓자마자 화면이 달아난다.
          if (!controls.autoRotate && idleAt && t - idleAt > 4000) controls.autoRotate = true;
          // 26초 주기로 0.45배~1.55배 사이를 오간다
          controls.autoRotateSpeed = base * (1 + Math.sin(t / 4200) * 0.55);
        }
        requestAnimationFrame(drift);
      };
      requestAnimationFrame(drift);
    }

    const fit = () => {
      g.width(stage.clientWidth);
      g.height(stage.clientHeight);
    };
    fit();
    window.addEventListener('resize', fit);

    /* 형제들을 넓게 민다. 기본 반발력으로는 한 층에 열 개가 서면 공이 겹치고
       이름표가 서로를 덮어 아무것도 안 읽힌다 — 층을 세워 놓고 그 안에서
       뭉개지면 위계를 보여준 보람이 없다.

       **d3ReheatSimulation 은 부르지 않는다**: 이 시점에 시뮬레이션을 다시
       데우면 tick 이 undefined 라 렌더 루프가 통째로 죽는다 — 실제로 그래프가
       한 점으로 뭉쳤다. 힘만 바꾸고 나머지는 라이브러리에 맡긴다. */
    try {
      const charge = g.d3Force('charge');
      if (charge && charge.strength) charge.strength(compact ? -180 : -300);
      const linkF = g.d3Force('link');
      if (linkF && linkF.distance) linkF.distance(compact ? 40 : 55);
    } catch (err) { console.warn('[chuckchuck] graph force', err); }

    /* 자리가 잡힌 뒤에 화면에 맞춘다. 예전엔 0.7초에 맞춰서, 아직 퍼지는 중인
       그래프를 기준으로 잡아 놓고 정작 다 퍼진 뒤엔 화면 한가운데 작게 남았다.
       **애니메이션 없이(0ms) 맞추고 나서야 캔버스를 보여준다** — 800ms 로 맞추면
       캔버스가 보이는 순간부터 다시 카메라가 움직이는 게 보여서 "자라나는" 인상이
       남는다(2026-08-12 사용자: 처음 뜰 때부터 이미 꽉 차 있었으면 좋겠다). */
    let fitted = false;
    const revealFitted = () => {
      if (fitted) return;
      fitted = true;
      g.zoomToFit(0, compact ? 70 : 50);
      requestAnimationFrame(() => {
        stage.classList.add('is-ready');
        loadingEl.remove();
      });
    };
    if (typeof g.onEngineStop === 'function') g.onEngineStop(revealFitted);
    setTimeout(revealFitted, 3200);
    layerFocus = g3dAttachLabels(stage, g, data.nodes, compact) || (() => {});
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
  return mountGraphCard('repGraph');
}

/** 두 자리가 같은 무대를 쓴다. 갈라지면 한쪽만 고쳐져 같은 그래프가 두 얼굴이 된다. */
function mountGraphCard(prefix) {
  const stage = document.getElementById(`${prefix}Stage`);
  if (!stage || stage.dataset.mounted) return;
  const src = graph3dSource();
  if (!src) { stage.innerHTML = '<p class="g3d-loading">개념 그래프가 아직 없어요</p>'; return; }
  const data = g3dData(src);
  const sum = document.getElementById(`${prefix}Summary`);
  if (sum) {
    // 자른 사실을 여기서도 말한다 — 안 그러면 «자료에 개념이 12개뿐» 으로 읽힌다
    const clip = data.total > data.nodes.length
      ? `<span class="g3d-clip">개념 ${data.total}개 중 자료가 힘준 ${data.nodes.length}개예요</span>` : '';
    sum.innerHTML = g3dSummaryHtml(data.nodes) + clip;
  }
  const card = document.getElementById(`${prefix}Card`);
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
/** 질문 생성 대기 화면(#/qa)의 개념 지도. 대기 화면과 같은 무대를 쓴다. */
window.mountQaBuildGraph = () => mountGraphCard('qbGraph');
/** 그래프가 있는가 — 대기 화면이 카드를 그릴지 말지 여기로 묻는다. */
window.hasConceptGraph = () => !!graph3dSource();
