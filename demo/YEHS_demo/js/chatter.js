/**
 * 삐약 청중석 — 발표가 끝난 객석을 엿보는 화면입니다.
 *
 * 백엔드(f12_chatter)가 만든 ChatterDoc 을 받아 '발표장 객석'으로 재생합니다.
 * 채팅앱이 아니라 공연장이라는 점이 이 화면의 전부입니다 — 어두운 객석,
 * 무대에서 흘러드는 빛, 좌석 등받이, 좌석마다 붙은 명패(모델명).
 *
 * 병아리는 '처음 생긴 관객'입니다 (UI_REDESIGN §0). 심사위원이 아니라 관객이라
 * 또렷한 눈으로 이쪽을 봐 주고, 2.5등신으로 서 있고, 늘 숨을 쉽니다. 예전의
 * '몽총한' 반쯤 감긴 눈은 버렸습니다 — 멍청해 보이면 들어준 것처럼 안 보입니다.
 *
 * 소품은 장식이 아니라 그 모델이 파이프라인에서 실제로 한 일입니다 (§9):
 * 엑씨=헤드폰(F-05 STT) · 쏠라=대본(F-01/06/07) · 믿:음=형광펜(F-11) ·
 * 엑사원=반짝 배지(aligned). 어두운 객석에서 실루엣만 보고도 넷이 구분돼야 합니다.
 *
 * window.Chatter 로 노출합니다 (app.js 는 모듈이 아니라 전역으로 붙입니다).
 */

(function () {
  'use strict';

  const REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* 좌석 순서 = 백엔드 발화 순서. 명패 순서도 이걸 따른다 */
  const SEATS = ['midm', 'solar', 'exaone', 'ax'];

  /* 백엔드 CHATTER_NAMES 와 같은 이름. 서버 응답에 speaker_names 가 없을 때만 쓴다 */
  const FALLBACK_NAMES = { midm: '믿:음', solar: '쏠라', exaone: '엑사원', ax: '엑씨' };
  const FALLBACK_BADGES = {
    midm: 'KT 믿:음', solar: 'Upstage Solar',
    exaone: 'LG EXAONE', ax: 'SKT A.X',
  };

  /* 흔들림 주기를 마리마다 다르게 — 같이 흔들리면 기계처럼 보인다 */
  const SWAY = { midm: '2.4s', solar: '2.2s', exaone: '2.7s', ax: '2.0s' };

  /* 숨쉬기 위상. 주기는 같아도 시작점이 어긋나야 살아 있는 넷으로 읽힌다 (§10) */
  const BREATH = { midm: '-0.3s', solar: '-1.7s', exaone: '-2.4s', ax: '-1.1s' };

  /* 콕 찌르면 나오는 고정 한마디. LLM 아님 — 관객이 들킨 순간의 이스터에그 */
  const POKES = {
    midm: ['왜. 나 확인하는 중이야.', '거기, 표시해 뒀어.', '흥. 잠깐만.'],
    solar: ['오홍? 대본 어디까지 봤더라.', '잠깐, 이 장 다시 볼래.', '응? 나 불렀어?'],
    exaone: ['히히. 간지러워.', '아까 그 대목 좋았어.', '어? 나 봤어?'],
    ax: ['헐 깜짝이야.', '나 다 듣고 있었어. 진짜야.', '어? 어어? 뭐?'],
  };

  /* 이 객석에 몇 번째로 들어왔나. 두 번째부터는 빨리 가고 싶은 게 정상이다 (§14) */
  const VISIT_KEY = 'cheokcheok:house-visits';
  function visits() {
    try { return Number(localStorage.getItem(VISIT_KEY)) || 0; }
    catch (_) { return 0; }   // 시크릿 모드 등 — 연출을 못 건너뛸 뿐 동작엔 지장 없다
  }
  function countVisit() {
    try { localStorage.setItem(VISIT_KEY, String(visits() + 1)); }
    catch (_) { /* ignore */ }
  }

  const sleep = ms => new Promise(r => setTimeout(r, REDUCED ? 0 : ms));
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  /* ------------------------------------------------------------------ */
  /* 병아리 SVG — 공통 형태 + speaker 별 소품                            */
  /* ------------------------------------------------------------------ */

  /**
   * 소품 = 그 모델이 파이프라인에서 실제로 한 일 (§9 실루엣 테스트).
   *
   * 하나하나 class 를 달아 두는 건 장식이 아니라서다 — 반응 연기(§2·§7-5)는
   * 소품이 수행한다. 쏠라는 대본을 넘기고 믿:음은 형광펜을 긋는다.
   */
  function props(speaker) {
    if (speaker === 'ax') {
      /* 헤드폰 — 발표를 귀로 들은 유일한 청중 (F-05 STT) */
      return `
  <g class="ch-prop ch-prop-phones">
    <path d="M31 27a19 19 0 0 1 38 0" fill="none" stroke="#59617a" stroke-width="3.6"
          stroke-linecap="round"/>
    <rect x="26" y="24" width="8.5" height="14" rx="4.25" fill="#59617a"/>
    <rect x="65.5" y="24" width="8.5" height="14" rx="4.25" fill="#59617a"/>
  </g>`;
    }
    if (speaker === 'solar') {
      /* 펼쳐 든 대본 — 자료를 통독한 유일한 청중 (F-01/06/07).
         위아래로 말린 끝이 보여야 '두루마리'로 읽힌다. 원통만 그리면 물병이 된다 */
      return `
  <g class="ch-prop ch-prop-script">
    <g transform="rotate(-10 74 66)">
      <rect x="66" y="54" width="16" height="24" fill="#f4ecd6"/>
      <path d="M66 54h16a3.2 3.2 0 0 0 0-6.4H66a3.2 3.2 0 0 1 0 6.4z" fill="#e0d2ae"/>
      <path d="M66 78h16a3.2 3.2 0 0 1 0 6.4H66a3.2 3.2 0 0 0 0-6.4z" fill="#e0d2ae"/>
      <path d="M69 60.5h10M69 66h10M69 71.5h7" stroke="#bfb192" stroke-width="1.3"
            stroke-linecap="round"/>
    </g>
  </g>`;
    }
    if (speaker === 'midm') {
      /* 형광펜 — 자료와 발화를 대조하며 표시한다 (F-11).
         ch-pen-stroke 는 방금 그은 밑줄. 어긋난 걸 찾았을 때만 나타난다 */
      return `
  <g class="ch-prop ch-prop-pen">
    <path class="ch-pen-stroke" d="M73 85h23" stroke="#ffe14d" stroke-width="6"
          stroke-linecap="round" opacity="0"/>
    <g transform="rotate(26 77 66)">
      <rect x="73" y="53" width="8" height="19" rx="2.4" fill="#ffe14d"/>
      <rect x="73" y="53" width="8" height="5.5" rx="2.4" fill="#efb01f"/>
      <path d="M73 72h8l-4 5.5z" fill="#e4dcc7"/>
    </g>
  </g>`;
    }
    /* 엑사원 — 가슴에 단 반짝 배지. 전문가의 인정 담당 (aligned) */
    return `
  <g class="ch-prop ch-prop-badge">
    <circle cx="50" cy="70" r="7.4" fill="#f2d47c" stroke="#d6ab38" stroke-width="1.5"/>
    <path d="M50 65.2l1.7 3.5 3.9.5-2.8 2.7.7 3.8-3.5-1.8-3.5 1.8.7-3.8-2.8-2.7 3.9-.5z"
          fill="#fff7dd"/>
    <g class="ch-sparkle" fill="#fff2c4">
      <path d="M61 59l1 2.6 2.6 1-2.6 1-1 2.6-1-2.6-2.6-1 2.6-1z"/>
    </g>
  </g>`;
  }

  /** 눈 한 짝. 또렷한 눈동자 + 하이라이트 2개, 표정 곡선은 mood 가 켠다 (§10) */
  function eye(cx) {
    return `
    <g class="ch-eye">
      <ellipse class="ch-eye-ball" cx="${cx}" cy="30" rx="4.3" ry="4.9" fill="#2b2f3a"/>
      <circle class="ch-eye-hi" cx="${cx + 1.5}" cy="28.2" r="1.6" fill="#fff"/>
      <circle class="ch-eye-hi" cx="${cx - 1.7}" cy="31.7" r=".85" fill="#fff" opacity=".75"/>
      <path class="ch-eye-line ch-eye-happy" d="M${cx - 5} 27.5q5 7.5 10 0"/>
      <path class="ch-eye-line ch-eye-grumpy" d="M${cx - 5} 32.5q5 -7.5 10 0"/>
      <path class="ch-eye-line ch-eye-shut" d="M${cx - 5} 30q5 3.4 10 0"/>
    </g>`;
  }

  /**
   * 병아리 한 마리.
   *
   * 2.5등신 — 머리 지름 36 / 전체 높이 ~90. 2등신이면 아기라 '들어주는 관객'
   * 으로 안 읽히고, 3등신을 넘기면 심사위원처럼 보인다.
   *
   * 몸통은 머리보다 좁은 달걀꼴이다. 몸이 머리보다 넓어지는 순간 눈사람이 된다.
   * 날개는 몸통 옆선 밖으로 나와 있어야 어두운 객석의 실루엣에서도 보인다 (§9).
   */
  function chickSvg(speaker) {
    const body = `var(--chick-${speaker}, #ffd76e)`;
    return `
<svg class="ch-chick" viewBox="0 0 100 100" role="img"
     aria-label="${esc(FALLBACK_NAMES[speaker] || speaker)} 병아리"
     style="--ch-sway:${SWAY[speaker] || '2.4s'};--ch-breath-delay:${BREATH[speaker] || '0s'}">
  <g class="ch-figure">
    <g class="ch-legs" stroke="var(--chick-beak)" stroke-width="2.4" stroke-linecap="round"
       fill="none">
      <path d="M45 89v5"/><path d="M41 95h7.5"/>
      <path d="M55 89v5"/><path d="M51.5 95H59"/>
    </g>
    <path class="ch-tailfeather" d="M33 74c-9 .5-13.5 3.5-15 7.5 5 .5 9.5-.5 15-2.5z"
          fill="${body}"/>
    <ellipse class="ch-torso" cx="50" cy="69" rx="19.5" ry="22" fill="${body}"/>
    <ellipse class="ch-wing" cx="29.5" cy="69" rx="5.5" ry="10.5" fill="${body}"/>
    <ellipse class="ch-wing" cx="70.5" cy="69" rx="5.5" ry="10.5" fill="${body}"/>
    <g class="ch-head">
      <path class="ch-tuft" d="M50 12.5c-1.4-5 2.6-8 5.6-6-3 2-3.2 4.2-2.2 7"
            fill="none" stroke="${body}" stroke-width="3.2" stroke-linecap="round"/>
      <circle cx="50" cy="30" r="18" fill="${body}"/>
      <ellipse class="ch-blush" cx="36.5" cy="36" rx="4.8" ry="3" fill="var(--chick-blush)"/>
      <ellipse class="ch-blush" cx="63.5" cy="36" rx="4.8" ry="3" fill="var(--chick-blush)"/>
      <g class="ch-eyes">${eye(42)}${eye(58)}</g>
      <path class="ch-beak" d="M46 38.5h8l-4 6z" fill="var(--chick-beak)"/>
    </g>
${props(speaker)}
    <g class="ch-emote">
      <path class="ch-heart" d="M74 14c2-3 6-1 6 2 0 3-4 5-6 7-2-2-6-4-6-7 0-3 4-5 6-2z"
            fill="#ff7b8a"/>
      <text class="ch-mark" x="72" y="17" font-size="19" font-weight="800"
            fill="#ffe9b8">?</text>
    </g>
  </g>
</svg>`;
  }

  /* ------------------------------------------------------------------ */
  /* 객석 만들기                                                          */
  /* ------------------------------------------------------------------ */

  function seatHtml(speaker, doc, index) {
    const name = (doc.speaker_names || {})[speaker] || FALLBACK_NAMES[speaker] || speaker;
    const badge = (doc.speaker_models || {})[speaker] || FALLBACK_BADGES[speaker] || '';
    /* 좌석이 줄의 왼쪽인지 오른쪽인지 — 말풍선 꼬리가 부리 쪽으로 기운다 (§7-4) */
    const side = index < SEATS.length / 2 ? 'left' : 'right';
    return `
      <div class="ch-seat" data-speaker="${esc(speaker)}" data-mood="neutral"
           data-side="${side}">
        <div class="ch-bubbles" data-bubbles></div>
        ${chickSvg(speaker)}
        <div class="ch-seatback">
          <div class="ch-plate"><b>${esc(name)}</b><span>${esc(badge)}</span></div>
        </div>
      </div>`;
  }

  /**
   * 객석 = 이 제품의 성(城) (§7). 다른 화면의 두 배를 투자하는 자리다.
   *
   * 3겹 디오라마로 깊이를 만든다 — 후경(무대 가장자리·비상구), 중경(병아리 넷),
   * 전경(좌석 등받이). 소품은 팸플릿과 비상구 표지 둘까지다 (§7-3 Staging).
   */
  function overlayHtml(doc) {
    const dust = Array.from({ length: 5 }, (_, i) =>
      `<span class="ch-dust" style="--d:${i}"></span>`).join('');
    return `
      <div class="ch-top">
        <span class="ch-stage-tag"><i></i>무대 쪽 · 발표 방금 끝남</span>
        <button class="ch-close" type="button" data-close>객석 나가기</button>
      </div>
      <div class="ch-house">
        <div class="ch-far" data-layer="far" aria-hidden="true">
          <div class="ch-stage-edge"></div>
          <div class="ch-exit"><i></i><b>비상구</b></div>
        </div>
        <div class="ch-shaft" data-layer="far" aria-hidden="true">${dust}</div>
        <div class="ch-row" data-layer="mid">
          ${SEATS.map((s, i) => seatHtml(s, doc, i)).join('')}
        </div>
        <div class="ch-frontrow" data-layer="near" aria-hidden="true">
          <i></i><i></i><i class="has-pamphlet"><span class="ch-pamphlet"></span></i><i></i><i></i>
        </div>
      </div>
      <div class="ch-actions">
        <button class="ch-btn ch-btn-ghost" type="button" data-replay>다시 듣기</button>
        <button class="ch-btn ch-btn-primary" type="button" data-close>리포트에서 자세히 보기</button>
      </div>
      <div class="ch-door" data-door>
        <div class="ch-door-frame">
          <i class="ch-door-leaf ch-door-l"></i>
          <i class="ch-door-leaf ch-door-r"></i>
          <span class="ch-door-slit"></span>
        </div>
        <b>무대 뒤 복도</b>
        <span>문틈으로 웅성거리는 소리가 새어 나온다</span>
      </div>`;
  }

  /* ------------------------------------------------------------------ */
  /* 연출                                                                 */
  /* ------------------------------------------------------------------ */

  /* 큰따옴표로 감싼 조각 = 발표자가 실제로 한 말. 곧은 따옴표와 둥근 따옴표 둘 다 온다 */
  const QUOTE_RE = /["“]([^"”]{2,80})["”]/;

  /**
   * 대사 본문. 발표자의 실제 발화 인용은 '대본 조각' 카드로 떼어 낸다 (§7-4).
   *
   * "내 말이 저기 있다" 는 순간이 이 화면의 보석이라, 인용을 그냥 따옴표로
   * 흘려보내지 않는다.
   */
  function bodyHtml(text) {
    const m = QUOTE_RE.exec(String(text || ''));
    if (!m) return esc(text);
    const before = text.slice(0, m.index).trim();
    const after = text.slice(m.index + m[0].length).trim();
    return `${before ? `${esc(before)} ` : ''}`
      + `<span class="ch-quote">${esc(m[1])}</span>`
      + `${after ? ` ${esc(after)}` : ''}`;
  }

  function bubbleHtml(turn, nodeSlides) {
    /* 근거 배지 = 풍선에 끈으로 매달린 수하물 태그 (§7-4) */
    const refs = (turn.refs || []).map(r => {
      const slide = nodeSlides ? nodeSlides[r.node_id] : null;
      const label = slide ? `슬라이드 ${slide}` : '리포트에서 보기';
      return `<button class="ch-ref" type="button" data-node="${esc(r.node_id)}">${esc(label)}</button>`;
    }).join('');
    return `
      <div class="ch-bubble">
        <span class="ch-whisper">소곤</span>
        <span class="ch-bubble-body">${bodyHtml(turn.text)}</span>
        ${refs ? `<span class="ch-tags">${refs}</span>` : ''}
      </div>`;
  }

  function pushBubble(seat, html) {
    const box = seat.querySelector('[data-bubbles]');
    box.insertAdjacentHTML('beforeend', html);
    /* 한 자리에 두 개까지만 남긴다 — 객석이라 말풍선이 쌓이면 지저분하다 */
    while (box.children.length > 2) box.removeChild(box.firstChild);
    Array.from(box.children).forEach((el, i, all) => {
      el.classList.toggle('faded', i < all.length - 1);
    });
  }

  function showTyping(seat) {
    const box = seat.querySelector('[data-bubbles]');
    box.insertAdjacentHTML('beforeend',
      '<div class="ch-typing" data-typing><i></i><i></i><i></i></div>');
    return () => {
      const t = box.querySelector('[data-typing]');
      if (t) t.remove();
    };
  }

  /**
   * ChatterDoc 을 객석 화면으로 재생한다.
   *
   * opts.nodeSlides  { node_id: slide_no } — 근거 배지에 슬라이드 번호를 쓴다
   * opts.onRef(id)   근거 배지를 눌렀을 때. 보통 오버레이를 닫고 리포트로 보낸다
   */
  function show(doc, opts) {
    opts = opts || {};
    doc = doc || {};
    const wrap = document.createElement('div');
    wrap.className = 'ch-overlay';
    wrap.innerHTML = overlayHtml(doc);
    document.body.appendChild(wrap);
    document.body.style.overflow = 'hidden';

    const seats = {};
    SEATS.forEach(s => { seats[s] = wrap.querySelector(`.ch-seat[data-speaker="${s}"]`); });

    const door = wrap.querySelector('[data-door]');
    const house = wrap.querySelector('.ch-house');

    /* 문이 사라지면 카메라도 제자리로. 둘을 같이 풀어야 '들어갔다'가 완성된다 */
    function openDoor() {
      door.classList.add('gone');
      wrap.classList.remove('at-door');
    }

    let skipped = false;
    let closed = false;

    /* 들어온 그 문으로 나간다 (§7-6 수미상응). 문이 닫히며 웅성거림이 멀어진다 */
    function close() {
      if (closed) return;
      closed = true;
      document.removeEventListener('keydown', onKey);
      stopParallax();
      if (door && !REDUCED) {
        door.classList.remove('gone', 'open');
        door.classList.add('leaving');
      }
      const wait = REDUCED ? 0 : 760;
      setTimeout(() => wrap.classList.remove('on'), wait);
      setTimeout(() => {
        wrap.remove();
        document.body.style.overflow = '';
      }, wait + (REDUCED ? 0 : 380));
    }
    function onKey(e) { if (e.key === 'Escape') close(); }
    document.addEventListener('keydown', onKey);

    /* 마우스를 따라 겹마다 2~4px. 시차가 깊이를 만든다 (§7-3) */
    let onMove = null;
    function startParallax() {
      if (REDUCED) return;
      const depth = { far: -4, mid: -1.5, near: 3 };
      onMove = (e) => {
        const dx = (e.clientX / window.innerWidth - .5) * 2;
        const dy = (e.clientY / window.innerHeight - .5) * 2;
        wrap.querySelectorAll('[data-layer]').forEach((el) => {
          const k = depth[el.dataset.layer] || 0;
          el.style.setProperty('--px', `${(dx * k).toFixed(2)}px`);
          el.style.setProperty('--py', `${(dy * k * .5).toFixed(2)}px`);
        });
      };
      wrap.addEventListener('mousemove', onMove);
    }
    function stopParallax() {
      if (onMove) wrap.removeEventListener('mousemove', onMove);
      onMove = null;
    }

    wrap.addEventListener('click', e => {
      const ref = e.target.closest('.ch-ref');
      if (ref) {
        const node = ref.dataset.node;
        close();
        if (opts.onRef) opts.onRef(node);
        return;
      }
      if (e.target.closest('[data-close]')) { close(); return; }
      if (e.target.closest('[data-replay]')) { run(true); return; }

      /* 문을 누르면 즉시 입장. 데모 시연은 시간이 생명이다 */
      if (e.target.closest('[data-door]')) {
        openDoor();
        skipped = true;
        return;
      }

      const chick = e.target.closest('.ch-chick');
      if (chick) {
        const seat = chick.closest('.ch-seat');
        const lines = POKES[seat.dataset.speaker] || ['삐약!'];
        const next = ((Number(seat.dataset.pokes) || 0) + 1) % lines.length;
        seat.dataset.pokes = String(next);
        seat.dataset.mood = 'curious';
        pushBubble(seat,
          `<div class="ch-bubble"><span class="ch-whisper">삐약</span>`
          + `<span class="ch-bubble-body">${esc(lines[next])}</span></div>`);
        return;
      }
      /* 그 외 배경을 누르면 연출을 건너뛴다 */
      skipped = true;
    });

    /**
     * "들켰다!" — 입장 비트 (§7-2).
     *
     * 몰래 엿듣던 발표자가 들킨 게 아니라 수다 떨던 관객이 들킨 것이다.
     * 권력이 뒤집히는 이 2초가 화면 전체의 톤을 정한다.
     */
    async function caughtBeat() {
      house.classList.add('caught');          // 뚝 — 정적
      await sleep(500);
      if (closed) return;
      house.classList.add('spotted');         // 여덟 개의 눈이 이쪽을 본다
      await sleep(700);
      if (closed) return;
      const ax = seats.ax;
      if (ax) {
        ax.dataset.mood = 'curious';
        ax.classList.add('waving');
        pushBubble(ax, `<div class="ch-bubble"><span class="ch-whisper">삐약</span>`
          + `<span class="ch-bubble-body">아! …다 들으셨어요?</span></div>`);
      }
      await sleep(1100);
      if (closed) return;
      house.classList.add('giggling');        // 킥킥, 다시 수다가 이어진다
      await sleep(600);
      house.classList.remove('caught', 'spotted', 'giggling');
      if (ax) {
        ax.classList.remove('waving');
        ax.dataset.mood = 'neutral';
        ax.querySelector('[data-bubbles]').innerHTML = '';
      }
    }

    /**
     * 서로 듣는 연기 (§7-5). 픽사 규칙: 캐릭터는 서로에게 반응한다.
     *
     * 리액션은 미동까지만이다 — 말풍선과 시선을 경쟁하면 화면이 시끄러워진다.
     */
    function listenTo(speaker, mood) {
      const at = SEATS.indexOf(speaker);
      SEATS.forEach((s, i) => {
        const seat = seats[s];
        if (!seat || s === speaker) return;
        seat.dataset.listening = i < at ? 'right' : 'left';   // 화자 쪽으로 고개
        // 엑사원이 칭찬하면 다들 같이 짝짝, 믿:음이 지적하면 쏠라가 대본을 뒤적인다
        seat.classList.toggle('applauding', speaker === 'exaone' && mood === 'happy');
        seat.classList.toggle('checking',
          speaker === 'midm' && mood === 'grumpy' && s === 'solar');
      });
    }
    function stopListening() {
      SEATS.forEach(s => {
        const seat = seats[s];
        if (!seat) return;
        delete seat.dataset.listening;
        seat.classList.remove('applauding', 'checking');
      });
    }

    async function run(isReplay) {
      const actions = wrap.querySelector('.ch-actions');
      actions.classList.remove('on');
      house.classList.remove('caught', 'spotted', 'giggling', 'settled');
      stopListening();
      SEATS.forEach(s => {
        seats[s].querySelector('[data-bubbles]').innerHTML = '';
        seats[s].classList.remove('seated', 'talking', 'dozing', 'waving');
        seats[s].dataset.mood = 'neutral';
      });
      skipped = false;

      /* 1단계 — 문지방 (§7-1). 세계에 '들어가는' 감각은 컷이 아니라 문에서 나온다.
         2회차부터는 즉시 입장한다 (§14 모든 연출 스킵 가능) */
      const quick = isReplay || REDUCED || visits() > 1;
      if (quick) {
        openDoor();
      } else {
        wrap.classList.add('at-door');
        door.classList.add('open');
        await sleep(1200);
        openDoor();
      }
      if (closed) return;
      startParallax();

      /* 2단계 — 청중이 하나씩 자리에 앉는다 */
      for (const s of SEATS) {
        seats[s].classList.add('seated');
        if (!skipped && !quick) await sleep(220);
      }

      /* 결석한 청중(근거 없는 대타 한 마디뿐인 자리)은 조는 자세로 둔다 */
      const turns = doc.turns || [];
      SEATS.forEach(s => {
        const mine = turns.filter(t => t.speaker === s);
        if (mine.length === 1 && (!mine[0].refs || !mine[0].refs.length)) {
          seats[s].classList.add('dozing');
        }
      });

      /* 3단계 — 들켰다. 첫 입장에서만, 조는 엑씨는 깨우지 않는다 */
      if (!quick && !skipped && !seats.ax.classList.contains('dozing')) {
        await caughtBeat();
        if (closed) return;
      }

      /* 4단계 — 소곤거림 */
      for (const turn of turns) {
        if (closed) return;
        const seat = seats[turn.speaker];
        if (!seat) continue;

        seat.classList.add('talking');
        listenTo(turn.speaker, turn.mood);
        if (!skipped) {
          const stop = showTyping(seat);
          await sleep(600 + Math.floor(Math.random() * 300));
          stop();
        }
        seat.dataset.mood = turn.mood || 'neutral';
        pushBubble(seat, bubbleHtml(turn, opts.nodeSlides));
        if (!skipped) await sleep(1100);
        seat.classList.remove('talking');
      }
      stopListening();

      /* 5단계 — 퇴장 (§7-6). 조명이 살짝 내려가고 넷이 편히 기대앉는다 */
      if (closed) return;
      house.classList.add('settled');
      actions.classList.add('on');
    }

    requestAnimationFrame(() => wrap.classList.add('on'));
    countVisit();
    run(false);
    return { close: close, replay: function () { return run(true); } };
  }

  /* ------------------------------------------------------------------ */
  /* API                                                                  */
  /* ------------------------------------------------------------------ */

  async function fetchChatter(graph, alignment, flow) {
    let res;
    try {
      res = await fetch('/api/v1/chatter', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ graph: graph, alignment: alignment, flow: flow }),
      });
    } catch (err) {
      // fetch 자체가 터진 것 = 서버가 없다. 정적 배포(GitHub Pages)에는 /api 가 없다.
      throw new Error(
        '데모 서버에 연결하지 못했어요. `python -m demo.bridge` 로 브리지를 띄운 주소에서 열어주세요. '
        + '(정적 배포 페이지에는 /api 가 없습니다)'
      );
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.message || `청중석을 여는 데 실패했어요 (${res.status})`);
    }
    return res.json();
  }

  /** 리포트 요약 탭에 넣을 진입 카드. */
  function entryCardHtml() {
    return `
      <div class="card aud-card" id="audCard">
        <div class="aud-head">
          <h3>청중 반응 몰래 보기</h3>
          <p>발표 끝나고 객석에 남은 네 청중이 뭐라고 하는지 엿들어 볼까요?</p>
        </div>
        <div class="aud-peek">${SEATS.map(chickSvg).join('')}</div>
        <div class="aud-models">
          ${SEATS.map(s => `<span>${esc(FALLBACK_BADGES[s])}</span>`).join('')}
        </div>
      </div>`;
  }

  window.Chatter = {
    show: show,
    fetchChatter: fetchChatter,
    entryCardHtml: entryCardHtml,
    chickSvg: chickSvg,
    SEATS: SEATS,
  };
})();
