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

  /* 이름 끝 글자의 받침으로 은/는을 고른다. "엑사원은(는)" 은 빈 좌석 앞에서
     유독 눈에 띈다 — 못 온 자리의 문구는 더더욱 사람 말이어야 한다 */
  function topicParticle(name) {
    const ch = String(name || '').trim().slice(-1);
    const code = ch.charCodeAt(0);
    if (code >= 0xac00 && code <= 0xd7a3) return (code - 0xac00) % 28 ? '은' : '는';
    return '은(는)';
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
      /* 헤드폰 — 발표를 귀로 들은 유일한 청중 (F-05 STT).
         컵이 몸 밖으로 나와야 어두운 무대 실루엣에서도 엑씨로 읽힌다 (01_character §6-1) */
      return `
  <g class="ch-prop ch-prop-phones">
    <path d="M18.5 35a31.5 31.5 0 0 1 63 0" fill="none" stroke="var(--chick-line)"
          stroke-width="3.6" stroke-linecap="round"/>
    <rect x="11.5" y="29" width="12" height="17" rx="5.5"
          fill="var(--chick-mint)" stroke="var(--chick-line)" stroke-width="2"/>
    <rect x="76.5" y="29" width="12" height="17" rx="5.5"
          fill="var(--chick-mint)" stroke="var(--chick-line)" stroke-width="2"/>
  </g>`;
    }
    if (speaker === 'solar') {
      /* 슬라이드 몇 장 — 자료를 통독한 유일한 청중 (F-01/06/07).
         겹친 두 장이어야 '자료 묶음'으로 읽힌다. 한 장이면 그냥 종이다 */
      return `
  <g class="ch-prop ch-prop-script" transform="translate(4 -2) rotate(-8 76 68)">
    <rect x="71.5" y="56.5" width="17" height="12.5" rx="2.5"
          fill="#F2FBF6" stroke="var(--chick-line)" stroke-width="2"/>
    <rect x="68.5" y="59.5" width="17" height="12.5" rx="2.5"
          fill="#FFFFFF" stroke="var(--chick-line)" stroke-width="2"/>
    <rect x="71" y="62" width="5.5" height="3.2" rx="1" fill="var(--chick-mint)"/>
    <path d="M71 67.5h12M71 69.8h8.5" stroke="#BFD9CB" stroke-width="1.4" stroke-linecap="round"/>
  </g>`;
    }
    if (speaker === 'midm') {
      /* 형광펜 — 자료와 발화를 대조하며 표시한다 (F-11).
         ch-pen-stroke 는 방금 그은 밑줄. 어긋난 걸 찾았을 때만 나타난다 */
      return `
  <g class="ch-prop ch-prop-pen">
    <path class="ch-pen-stroke" d="M72 90h22" stroke="#FFE14D" stroke-width="6"
          stroke-linecap="round" opacity="0"/>
    <g transform="translate(3 -1) rotate(34 79 68)">
      <rect x="75" y="56" width="8.5" height="18" rx="3.5"
            fill="#FFE14D" stroke="var(--chick-line)" stroke-width="2"/>
      <rect x="75" y="56" width="8.5" height="6" rx="3"
            fill="var(--chick-beak)" stroke="var(--chick-line)" stroke-width="2"/>
      <path d="M75.8 74h7l-3.5 5z" fill="#F7E9B8" stroke="var(--chick-line)" stroke-width="1.6"
            stroke-linejoin="round"/>
    </g>
  </g>`;
    }
    /* 엑사원 — 가슴의 별 로제트. 전문가의 인정 담당 (aligned).
       로제트는 몸 안이라 실루엣에서 사라진다 — 어깨 밖에 뜬 별이 실루엣 표식이다 */
    return `
  <g class="ch-prop ch-prop-badge">
    <path d="M46.4 78.2l-2.6 5.2 3.6-.9 1.7 3.1 2.2-5.6z" fill="var(--chick-mint)"
          stroke="var(--chick-line)" stroke-width="1.4" stroke-linejoin="round"/>
    <path d="M53.6 78.2l2.6 5.2-3.6-.9-1.7 3.1-2.2-5.6z" fill="var(--chick-mint)"
          stroke="var(--chick-line)" stroke-width="1.4" stroke-linejoin="round"/>
    <circle cx="50" cy="71" r="8" fill="var(--chick-mint)"
            stroke="var(--chick-line)" stroke-width="2"/>
    <circle cx="50" cy="71" r="5" fill="#FFFFFF"/>
    <path d="M50 67.4l1.2 2.4 2.7.4-2 1.9.5 2.7-2.4-1.3-2.4 1.3.5-2.7-2-1.9 2.7-.4z"
          fill="var(--chick-body, #FFD96A)" stroke="var(--chick-line)" stroke-width=".8"/>
    <g class="ch-sparkle" fill="#FFF2C4" stroke="var(--chick-line)" stroke-width=".9">
      <path d="M90.5 43.5l1.1 2.9 2.9 1.1-2.9 1.1-1.1 2.9-1.1-2.9-2.9-1.1 2.9-1.1z"/>
    </g>
  </g>`;
  }

  /** 눈 한 짝. 크고 또렷한 눈동자 + 하이라이트 2개, 표정 곡선은 mood 가 켠다 (§10) */
  function eye(cx) {
    return `
    <g class="ch-eye">
      <ellipse class="ch-eye-ball" cx="${cx}" cy="42" rx="5.2" ry="5.8" fill="#2F3B33"/>
      <circle class="ch-eye-hi" cx="${cx + 1.8}" cy="39.6" r="2" fill="#fff"/>
      <circle class="ch-eye-hi" cx="${cx - 2}" cy="44.2" r="1" fill="#fff" opacity=".75"/>
      <path class="ch-eye-line ch-eye-happy" d="M${cx - 5.5} 40q5.5 7.5 11 0"/>
      <path class="ch-eye-line ch-eye-grumpy" d="M${cx - 5.5} 45.5q5.5 -7.5 11 0"/>
    </g>`;
  }

  /**
   * 발표새 한 마리 — "말랑한 발표새" (docs/design_improvement/01_character.md).
   *
   * 머리+몸이 한 덩어리 달걀 블롭이다 (얼굴 영역이 전체의 ~64%). 갈라 그리면
   * 외곽선이 교차해서 지저분해진다. 외곽선은 검정이 아니라 브랜드 초록
   * (--chick-line) — 이게 부드러움의 핵심이다.
   *
   * 클래스 구조는 옛 병아리와 같다. mood CSS·keyframes 27종·렌더 지점 9곳이
   * 전부 이 클래스에 걸려 있어서, 이름을 지키면 연출이 그대로 산다.
   */
  function chickSvg(speaker) {
    const body = `var(--chick-${speaker}, #FFD96A)`;
    return `
<svg class="ch-chick" viewBox="0 0 100 100" role="img"
     aria-label="${esc(FALLBACK_NAMES[speaker] || speaker)} 병아리"
     style="--ch-sway:${SWAY[speaker] || '2.4s'};--ch-breath-delay:${BREATH[speaker] || '0s'}">
  <g class="ch-figure">
    <g class="ch-legs" fill="var(--chick-beak)" stroke="var(--chick-line)"
       stroke-width="1.8" stroke-linejoin="round">
      <path d="M41 85.5c-2.8 3.2-1.6 6.5 1.6 6.5 2.6 0 4.4-1.8 4.2-5.4z"/>
      <path d="M59 85.5c2.8 3.2 1.6 6.5-1.6 6.5-2.6 0-4.4-1.8-4.2-5.4z"/>
    </g>
    <path class="ch-tailfeather" d="M20 62c-5.5-1-9 1.5-9.5 5.5 4 1.2 7.5.3 10-1.8z"
          fill="${body}" stroke="var(--chick-line)" stroke-width="2.4" stroke-linejoin="round"/>
    <path class="ch-torso" d="M50 9C30 9 16 24 16 45c0 13 5 22 9 28 5 7 14 13 25 13s20-6 25-13c4-6 9-15 9-28C84 24 70 9 50 9z"
          fill="${body}" stroke="var(--chick-line)" stroke-width="3" stroke-linejoin="round"/>
    <ellipse class="ch-belly" cx="50" cy="72" rx="13" ry="9.5" fill="var(--chick-belly)"/>
    <path class="ch-wing" d="M17 50c-5 .8-8 4.4-7.4 9 4.4 1 8.6-.7 11-4z"
          fill="${body}" stroke="var(--chick-line)" stroke-width="2.4" stroke-linejoin="round"/>
    <path class="ch-wing" d="M83 50c5 .8 8 4.4 7.4 9-4.4 1-8.6-.7-11-4z"
          fill="${body}" stroke="var(--chick-line)" stroke-width="2.4" stroke-linejoin="round"/>
    <g class="ch-head">
      <g class="ch-tuft">
        <path d="M50 9V4.5" fill="none" stroke="var(--chick-line)" stroke-width="2"
              stroke-linecap="round"/>
        <path d="M50 5C49 1.8 46.2.6 43.8 1.6c.5 2.7 3 4 6.2 3.4z" fill="var(--chick-mint)"
              stroke="var(--chick-line)" stroke-width="1.6" stroke-linejoin="round"/>
        <path d="M50 5c1-3.2 3.8-4.4 6.2-3.4-.5 2.7-3 4-6.2 3.4z" fill="var(--chick-mint)"
              stroke="var(--chick-line)" stroke-width="1.6" stroke-linejoin="round"/>
      </g>
      <ellipse class="ch-blush" cx="29.5" cy="50" rx="4.6" ry="2.7" fill="var(--chick-blush)"/>
      <ellipse class="ch-blush" cx="70.5" cy="50" rx="4.6" ry="2.7" fill="var(--chick-blush)"/>
      <g class="ch-eyes">${eye(38.5)}${eye(61.5)}</g>
      <path class="ch-beak" d="M50 47c2.7 0 4.3 1.3 4.3 2.8 0 1.8-1.9 3.2-4.3 3.2s-4.3-1.4-4.3-3.2c0-1.5 1.6-2.8 4.3-2.8z"
            fill="var(--chick-beak)" stroke="var(--chick-line)" stroke-width="1.6"/>
    </g>
${props(speaker)}
    <g class="ch-emote">
      <path class="ch-heart" d="M78 13c2-3 6-1 6 2 0 3-4 5-6 7-2-2-6-4-6-7 0-3 4-5 6-2z"
            fill="#FF8FA3"/>
      <text class="ch-mark" x="75" y="17" font-size="19" font-weight="800"
            fill="#4C8A74">?</text>
    </g>
  </g>
</svg>`;
  }

  /* ------------------------------------------------------------------ */
  /* 객석 만들기                                                          */
  /* ------------------------------------------------------------------ */

  /**
   * 좌석 하나.
   *
   * 결석은 doc.absent 로만 판단한다 (§12). 예전엔 "refs 가 빈 대사 한 줄뿐이면
   * 결석"으로 추측했는데 그건 틀린 규칙이다 — 엑씨의 애드립·발표 시간 사실은
   * 원래 node_ids 가 비어서, 멀쩡히 일한 병아리가 조는 걸로 그려졌다.
   * 못 온 자리는 재우지 않고 비운다: 빈 좌석 + 명패 + "오늘 못 왔어요".
   */
  function seatHtml(speaker, doc, index) {
    const name = (doc.speaker_names || {})[speaker] || FALLBACK_NAMES[speaker] || speaker;
    const badge = (doc.speaker_models || {})[speaker] || FALLBACK_BADGES[speaker] || '';
    /* 좌석이 줄의 왼쪽인지 오른쪽인지 — 말풍선 꼬리가 부리 쪽으로 기운다 (§7-4) */
    const side = index < SEATS.length / 2 ? 'left' : 'right';
    const absent = (doc.absent || []).indexOf(speaker) >= 0;
    return `
      <div class="ch-seat" data-speaker="${esc(speaker)}" data-mood="neutral"
           data-side="${side}"${absent ? ' data-absent="1"' : ''}>
        <div class="ch-bubbles" data-bubbles></div>
        ${absent
          ? `<p class="ch-empty">${esc(name)}${topicParticle(name)}<br>오늘 못 왔어요</p>`
          : chickSvg(speaker)}
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

    /* 들어온 그 문으로 나간다 (§7-6 수미상응). 문이 닫히며 웅성거림이 멀어진다.
       리포트로 복귀는 애니메이션과 무관하게 즉시 overflow 를 풀고, 실패해도 DOM 을 제거한다. */
    function close(reason) {
      if (closed) return;
      closed = true;
      skipped = true;
      document.removeEventListener('keydown', onKey);
      stopParallax();
      document.body.style.overflow = '';
      if (door && !REDUCED) {
        door.classList.remove('gone', 'open');
        door.classList.add('leaving');
      }
      wrap.classList.add('is-leaving');
      const wait = REDUCED ? 0 : 420;
      setTimeout(() => wrap.classList.remove('on'), Math.min(wait, 120));
      setTimeout(() => {
        if (wrap.parentNode) wrap.remove();
        document.body.style.overflow = '';
        try { if (typeof opts.onClose === 'function') opts.onClose(reason || 'close'); } catch (_) { /* ignore */ }
      }, wait);
    }
    function onKey(e) { if (e.key === 'Escape') close('escape'); }
    document.addEventListener('keydown', onKey);

    // 위임 클릭이 막혀도 나가기·리포트 복귀가 되도록 버튼에 직접 묶는다
    wrap.querySelectorAll('[data-close]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        close(btn.classList.contains('ch-btn-primary') ? 'report' : 'exit');
      });
    });

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
      const el = e.target && e.target.nodeType === 3 ? e.target.parentElement : e.target;
      if (!el || !el.closest) return;
      const ref = el.closest('.ch-ref');
      if (ref) {
        const node = ref.dataset.node;
        close('ref');
        if (opts.onRef) opts.onRef(node);
        return;
      }
      if (el.closest('[data-close]')) { close('exit'); return; }
      if (el.closest('[data-replay]')) { run(true); return; }

      /* 문을 누르면 즉시 입장. 데모 시연은 시간이 생명이다 */
      if (el.closest('[data-door]')) {
        openDoor();
        skipped = true;
        return;
      }

      const chick = el.closest('.ch-chick');
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
      const cut = () => closed || skipped;    // 배경을 누르면 바로 본론으로 (§14)
      house.classList.add('caught');          // 뚝 — 정적
      await sleep(500);
      if (cut()) return endCaught();
      house.classList.add('spotted');         // 여덟 개의 눈이 이쪽을 본다
      await sleep(700);
      if (cut()) return endCaught();
      const ax = seats.ax;
      if (ax) {
        ax.dataset.mood = 'curious';
        ax.classList.add('waving');
        pushBubble(ax, `<div class="ch-bubble"><span class="ch-whisper">삐약</span>`
          + `<span class="ch-bubble-body">아! …다 들으셨어요?</span></div>`);
      }
      await sleep(1100);
      if (cut()) return endCaught();
      house.classList.add('giggling');        // 킥킥, 다시 수다가 이어진다
      await sleep(600);
      endCaught();
    }

    /** 어느 지점에서 잘려도 객석을 평상 상태로 되돌린다. */
    function endCaught() {
      house.classList.remove('caught', 'spotted', 'giggling');
      const ax = seats.ax;
      if (!ax) return;
      ax.classList.remove('waving');
      ax.dataset.mood = 'neutral';
      ax.querySelector('[data-bubbles]').innerHTML = '';
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
        seats[s].classList.remove('seated', 'talking', 'waving');
        seats[s].dataset.mood = 'neutral';
      });
      skipped = false;
      const away = doc.absent || [];

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
      // 연출 중에도 나가기·리포트 복귀는 바로 누를 수 있게
      actions.classList.add('on');
      startParallax();

      /* 2단계 — 청중이 하나씩 자리에 앉는다 */
      for (const s of SEATS) {
        seats[s].classList.add('seated');
        if (!skipped && !quick) await sleep(220);
      }

      /* 못 온 병아리의 대타 대사는 재생하지 않는다 — 빈 좌석이 이미 사실을 말한다 */
      const turns = (doc.turns || []).filter(t => away.indexOf(t.speaker) < 0);

      /* 3단계 — 들켰다. 첫 입장에서만. 엑씨가 결석이면 비트를 건너뛴다 */
      if (!quick && !skipped && away.indexOf('ax') < 0) {
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

  /**
   * 좌석마다 붙는 한 줄. 소품이 곧 그 모델이 파이프라인에서 실제로 한 일이다
   * (UI_REDESIGN §9 실루엣 테스트). 46px 로는 소품이 안 보여서 넷이 '색만 다른
   * 병아리'로 읽혔다 — 크기를 키우고 이름·역할을 같은 칸에 붙인다.
   */
  const SEAT_ROLE = {
    midm: '대조 담당',
    solar: '자료 담당',
    exaone: '인정 담당',
    ax: '듣기 담당',
  };

  /* 카드 안 한 줄은 판정이 아니라 역할 소개다 — 판정은 객석을 열어야 나온다.
     고정 카피고 LLM 이 아니다 (03_components.md §4) */
  const SEAT_LINE = {
    midm: '자료랑 발표를 나란히 봤어요!',
    solar: '슬라이드를 처음부터 끝까지 읽었어요!',
    exaone: '잘 설명한 개념에 도장을 찍었어요!',
    ax: '한마디도 놓치지 않고 들었어요!',
  };

  /** 리포트 '청중 반응' 탭에 넣을 진입 카드. */
  function entryCardHtml() {
    return `
      <div class="card aud-card" id="audCard">
        <p class="aud-status">발표 끝나고 객석에 남은 네 청중이 뭐라고 하는지 엿들어 볼까요?</p>
        <ul class="aud-seats">
          ${SEATS.map(s => `
            <li class="aud-seat" data-speaker="${esc(s)}">
              <span class="aud-chick">${chickSvg(s)}</span>
              <span class="aud-line">${esc(SEAT_LINE[s])}</span>
              <span class="aud-id">
                <b class="aud-name">${esc(FALLBACK_NAMES[s])}</b>
                <span class="aud-role-pill">${esc(SEAT_ROLE[s])}</span>
              </span>
              <span class="aud-model">${esc(FALLBACK_BADGES[s])}</span>
            </li>`).join('')}
        </ul>
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
