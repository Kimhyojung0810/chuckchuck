/**
 * 삐약 청중석 — 발표가 끝난 객석을 엿보는 화면입니다.
 *
 * 백엔드(f12_chatter)가 만든 ChatterDoc 을 받아 '발표장 객석'으로 재생합니다.
 * 채팅앱이 아니라 공연장이라는 점이 이 화면의 전부입니다 — 어두운 객석,
 * 무대에서 흘러드는 빛, 좌석 등받이, 좌석마다 붙은 명패(모델명).
 *
 * 병아리는 '몽총하게' 그립니다. 머리가 몸보다 크고(2등신), 눈이 멀찍이 떨어져
 * 반쯤 감겨 있고, 움직임이 느립니다. 똑똑해 보이면 콘셉트가 깨집니다.
 *
 * window.Chatter 로 노출합니다 (app.js 는 모듈이 아니라 전역으로 붙입니다).
 */

(function () {
  'use strict';

  const REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* 좌석 순서 = 백엔드 발화 순서. 명패 순서도 이걸 따른다 */
  const SEATS = ['midm', 'solar', 'exaone', 'ax'];

  const FALLBACK_NAMES = { midm: '믿음이', solar: '쏠라', exaone: '엑사', ax: '엑씨' };
  const FALLBACK_BADGES = {
    midm: 'KT 믿:음', solar: 'Upstage Solar',
    exaone: 'LG EXAONE', ax: 'SKT A.X',
  };

  /* 흔들림 주기를 마리마다 다르게 — 같이 흔들리면 기계처럼 보인다 */
  const SWAY = { midm: '3.4s', solar: '2.9s', exaone: '3.8s', ax: '2.6s' };

  /* 콕 찌르면 나오는 고정 한마디. LLM 아님 — 몽총함 담당 이스터에그 */
  const POKES = {
    midm: ['왜. 나 지금 생각 중이야.', '...뭐였더라.', '흥. 건드리지 마.'],
    solar: ['오홍? 어디까지 읽었더라.', '잠깐, 유인물 어디 갔지.', '응? 나 불렀어?'],
    exaone: ['으응... 나 잠깐 졸았나.', '히히. 간지러워.', '어? 벌써 끝났어?'],
    ax: ['헐 깜짝이야.', '어? 어어? 뭐?', '나 듣고 있었어. 진짜야.'],
  };

  const sleep = ms => new Promise(r => setTimeout(r, REDUCED ? 0 : ms));
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  /* ------------------------------------------------------------------ */
  /* 병아리 SVG — 공통 형태 + speaker 별 소품                            */
  /* ------------------------------------------------------------------ */

  function props(speaker) {
    if (speaker === 'solar') {
      /* 자료를 읽은 청중이라 안경을 썼다 */
      return `
        <g stroke="#4a4f63" stroke-width="2.4" fill="none" opacity=".85">
          <circle cx="35" cy="48" r="10"/><circle cx="65" cy="48" r="10"/>
          <path d="M45 48h10"/>
        </g>`;
    }
    if (speaker === 'ax') {
      /* 발표를 귀로 들은 청중이라 헤드셋을 꼈다 */
      return `
        <g fill="#5b6480">
          <path d="M23 36a27 27 0 0 1 54 0" fill="none" stroke="#5b6480" stroke-width="4.5"
                stroke-linecap="round"/>
          <rect x="15" y="38" width="11" height="17" rx="5"/>
          <rect x="74" y="38" width="11" height="17" rx="5"/>
        </g>`;
    }
    if (speaker === 'exaone') {
      /* 전문가 AI 라 박사모자를 썼다 */
      return `
        <g>
          <path d="M50 8 78 19 50 30 22 19z" fill="#3c4257"/>
          <rect x="45" y="24" width="10" height="7" rx="2" fill="#3c4257"/>
          <path d="M78 19v12" stroke="#c8a34a" stroke-width="2.2" stroke-linecap="round"/>
          <circle cx="78" cy="33" r="3.2" fill="#c8a34a"/>
        </g>`;
    }
    /* 믿음이 — 머리깃 한 가닥이 힘없이 꺾여 있다 (몽총함 담당) */
    return `<path d="M50 14c0-6 6-8 9-4-4 1-5 4-4 8"
                  fill="none" stroke="#e0a92f" stroke-width="3.4" stroke-linecap="round"/>`;
  }

  function chickSvg(speaker) {
    const body = `var(--chick-${speaker}, #ffd76e)`;
    return `
<svg class="ch-chick" viewBox="0 0 100 100" role="img"
     aria-label="${esc(FALLBACK_NAMES[speaker] || speaker)} 병아리"
     style="--ch-sway:${SWAY[speaker] || '3.2s'}">
  <ellipse cx="50" cy="78" rx="27" ry="20" fill="${body}"/>
  <ellipse cx="24" cy="76" rx="7" ry="11" fill="${body}" opacity=".85"/>
  <circle cx="50" cy="45" r="28" fill="${body}"/>
  ${props(speaker)}
  <g class="ch-eyes">
    <ellipse class="ch-lid" cx="35" cy="48" rx="5.4" ry="6" fill="#2b2f3a"/>
    <ellipse class="ch-lid" cx="65" cy="48" rx="5.4" ry="6" fill="#2b2f3a"/>
  </g>
  <g class="ch-brow" stroke="#2b2f3a" stroke-width="2.4" stroke-linecap="round" opacity=".8">
    <path d="M28 34l10 2"/><path d="M72 34l-10 2"/>
  </g>
  <ellipse cx="24" cy="58" rx="6.5" ry="4" fill="var(--chick-blush)" opacity=".45"/>
  <ellipse cx="76" cy="58" rx="6.5" ry="4" fill="var(--chick-blush)" opacity=".45"/>
  <path d="M44 59h12l-6 7z" fill="var(--chick-beak)"/>
  <path class="ch-heart" d="M78 20c2-3 6-1 6 2 0 3-4 5-6 7-2-2-6-4-6-7 0-3 4-5 6-2z"
        fill="#ff7b8a"/>
  <text class="ch-mark" x="76" y="22" font-size="20" font-weight="800"
        fill="#ffe9b8">?</text>
</svg>`;
  }

  /* ------------------------------------------------------------------ */
  /* 객석 만들기                                                          */
  /* ------------------------------------------------------------------ */

  function seatHtml(speaker, doc) {
    const name = (doc.speaker_names || {})[speaker] || FALLBACK_NAMES[speaker] || speaker;
    const badge = (doc.speaker_models || {})[speaker] || FALLBACK_BADGES[speaker] || '';
    return `
      <div class="ch-seat" data-speaker="${esc(speaker)}" data-mood="neutral">
        <div class="ch-bubbles" data-bubbles></div>
        ${chickSvg(speaker)}
        <div class="ch-seatback">
          <div class="ch-plate"><b>${esc(name)}</b><span>${esc(badge)}</span></div>
        </div>
      </div>`;
  }

  function overlayHtml(doc) {
    return `
      <div class="ch-top">
        <span class="ch-stage-tag"><i></i>무대 쪽 · 발표 방금 끝남</span>
        <button class="ch-close" type="button" data-close>객석 나가기</button>
      </div>
      <div class="ch-house">
        <div class="ch-row">${SEATS.map(s => seatHtml(s, doc)).join('')}</div>
        <div class="ch-frontrow"><i></i><i></i><i></i><i></i><i></i></div>
      </div>
      <div class="ch-actions">
        <button class="ch-btn ch-btn-ghost" type="button" data-replay>다시 듣기</button>
        <button class="ch-btn ch-btn-primary" type="button" data-close>리포트에서 자세히 보기</button>
      </div>
      <div class="ch-caption">
        <div class="ch-doorlight"></div>
        <b>발표가 끝났습니다</b>
        <span>객석에서 뭔가 수군거리는 소리가 들린다...</span>
      </div>`;
  }

  /* ------------------------------------------------------------------ */
  /* 연출                                                                 */
  /* ------------------------------------------------------------------ */

  function bubbleHtml(turn, nodeSlides) {
    const refs = (turn.refs || []).map(r => {
      const slide = nodeSlides ? nodeSlides[r.node_id] : null;
      const label = slide ? `슬라이드 ${slide}` : '리포트에서 보기';
      return `<button class="ch-ref" type="button" data-node="${esc(r.node_id)}">${esc(label)}</button>`;
    }).join(' ');
    return `
      <div class="ch-bubble">
        <span class="ch-whisper">소곤</span>
        ${esc(turn.text)}
        ${refs}
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

    let skipped = false;
    let closed = false;

    function close() {
      if (closed) return;
      closed = true;
      wrap.classList.remove('on');
      document.removeEventListener('keydown', onKey);
      setTimeout(() => {
        wrap.remove();
        document.body.style.overflow = '';
      }, REDUCED ? 0 : 380);
    }
    function onKey(e) { if (e.key === 'Escape') close(); }
    document.addEventListener('keydown', onKey);

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

      const chick = e.target.closest('.ch-chick');
      if (chick) {
        const seat = chick.closest('.ch-seat');
        const lines = POKES[seat.dataset.speaker] || ['삐약!'];
        const next = ((Number(seat.dataset.pokes) || 0) + 1) % lines.length;
        seat.dataset.pokes = String(next);
        seat.dataset.mood = 'curious';
        pushBubble(seat,
          `<div class="ch-bubble"><span class="ch-whisper">삐약</span>${esc(lines[next])}</div>`);
        return;
      }
      /* 그 외 배경을 누르면 연출을 건너뛴다 */
      skipped = true;
    });

    async function run(isReplay) {
      const caption = wrap.querySelector('.ch-caption');
      const actions = wrap.querySelector('.ch-actions');
      actions.classList.remove('on');
      SEATS.forEach(s => {
        seats[s].querySelector('[data-bubbles]').innerHTML = '';
        seats[s].classList.remove('seated', 'talking', 'dozing');
        seats[s].dataset.mood = 'neutral';
      });
      skipped = false;

      /* 1단계 — 암전. 다시 듣기일 땐 생략한다 */
      if (isReplay) {
        caption.classList.add('gone');
      } else {
        caption.classList.remove('gone');
        await sleep(1500);
        caption.classList.add('gone');
      }
      if (closed) return;

      /* 2단계 — 청중이 하나씩 자리에 앉는다 */
      for (const s of SEATS) {
        seats[s].classList.add('seated');
        if (!skipped) await sleep(220);
      }

      /* 결석한 청중(근거 없는 대타 한 마디뿐인 자리)은 조는 자세로 둔다 */
      const turns = doc.turns || [];
      SEATS.forEach(s => {
        const mine = turns.filter(t => t.speaker === s);
        if (mine.length === 1 && (!mine[0].refs || !mine[0].refs.length)) {
          seats[s].classList.add('dozing');
        }
      });

      /* 3단계 — 소곤거림 */
      for (const turn of turns) {
        if (closed) return;
        const seat = seats[turn.speaker];
        if (!seat) continue;

        seat.classList.add('talking');
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

      /* 4단계 — 엔딩 */
      if (closed) return;
      actions.classList.add('on');
    }

    requestAnimationFrame(() => wrap.classList.add('on'));
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
