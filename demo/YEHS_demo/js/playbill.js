/**
 * 기억하는 객석 — 지난 공연의 기록 (UI_REDESIGN §13, 3막).
 *
 * 홈은 극장 앞이고, 지난 공연들은 벽에 붙은 포스터다. 회차마다 티켓이 한 장씩
 * 남고, 병아리는 **diff 가 증명할 때만** 지난번을 회상한다.
 *
 * 이 파일의 규칙 두 줄:
 *
 * 1. **데이터가 증명 못 하는 회상 대사 금지** (§13, 하지 말아야 할 것).
 *    "지난번보다 나아졌어요" 같은 말은 지난 회차에 비었던 개념이 이번에 실제로
 *    채워졌을 때만 나온다. 차집합이 비면 아무 말도 하지 않는다.
 * 2. **id 가 아니라 label 을 저장한다.** node_id 는 자료를 다시 파싱하면
 *    바뀐다. 회차 간 비교의 유일한 안정 키는 사람이 읽는 개념 이름이다.
 *
 * nf(진행 중 세션)는 sessionStorage 지만 이 기록은 localStorage 다 —
 * 탭을 닫아도 남아야 '지난 공연'이 된다.
 *
 * window.Playbill 로 노출합니다 (app.js 는 모듈이 아니라 전역으로 붙입니다).
 */

(function () {
  'use strict';

  const KEY = 'cheokcheok:playbill';
  const VERSION = 1;
  const MAX_SHOWS = 12;          // 포스터 벽이 감당하는 만큼만. 오래된 건 떨어진다

  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  /* 채점표 클러스터 ↔ 병아리. app.js 의 SCORE_CHICK 과 같은 배정이다 (§6·§9) */
  const STAMP_OWNER = {
    content: 'midm', logic: 'midm',
    audience: 'ax', clarity: 'ax',
    delivery: 'solar', time: 'solar',
    visual: 'exaone',
  };
  const SEAT_ORDER = ['midm', 'solar', 'exaone', 'ax'];
  const NAMES = { midm: '믿:음', solar: '쏠라', exaone: '엑사원', ax: '엑씨' };
  /* 도장 잉크. 판정 색이 아니라 자유 색이라 새 팔레트를 따라간다
     (docs/design_improvement/04_screens.md §6) */
  const STAMP_COLOR = {
    happy: '#08B879', neutral: '#8AA295', curious: '#F0A93C', grumpy: '#D1584F',
  };

  /* ------------------------------------------------------------------ */
  /* 저장소                                                              */
  /* ------------------------------------------------------------------ */

  function load() {
    try {
      const raw = JSON.parse(localStorage.getItem(KEY));
      if (!raw || raw.version !== VERSION || !Array.isArray(raw.shows)) return [];
      return raw.shows;
    } catch (_) {
      return [];   // 시크릿 모드·손상된 기록 — 기억이 없을 뿐 앱은 돈다
    }
  }

  function save(shows) {
    try {
      localStorage.setItem(KEY, JSON.stringify({
        version: VERSION,
        shows: shows.slice(-MAX_SHOWS),
      }));
    } catch (_) { /* ignore */ }
  }

  /** 오늘 날짜. 회상 대사가 상대 표현("지난번")을 쓰므로 절대값으로 박아 둔다. */
  function today() {
    const d = new Date();
    const p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }

  /**
   * 파이프라인 결과에서 한 회차 기록을 뽑는다.
   *
   * 없는 값은 지어내지 않고 비운다 — 빈 칸은 티켓에서 그대로 빈 도장이 된다.
   */
  function extract(out, meta) {
    out = out || {};
    meta = meta || {};
    const labelOf = {};
    ((out.graph && out.graph.nodes) || []).forEach((n) => { labelOf[n.id] = n.label; });

    const items = (out.alignment && out.alignment.items) || [];
    const gaps = items
      .filter(i => i.verdict === 'missing' || i.verdict === 'contradiction')
      .map(i => labelOf[i.node_id])
      .filter(Boolean);

    const sc = out.score || null;
    const stamps = {};
    // 채점표는 0~100 이다 (예전 F-13 은 0~1 이었다). 병아리 하나가 클러스터 둘을
    // 맡으므로 더 낮은 쪽이 이긴다 — 한쪽이 나쁜데 웃는 도장이 찍히면 안 된다.
    ((sc && sc.clusters) || []).forEach((c) => {
      const who = STAMP_OWNER[c.key];
      if (!who || c.status !== 'scored') return;
      const avg = Number(c.average) || 0;
      const mood = avg >= 75 ? 'happy'
        : avg >= 50 ? 'neutral'
          : avg >= 25 ? 'curious' : 'grumpy';
      const rank = { grumpy: 0, curious: 1, neutral: 2, happy: 3 };
      if (!(who in stamps) || rank[mood] < rank[stamps[who]]) stamps[who] = mood;
    });

    return {
      // 회차를 가르는 키는 날짜·제목이 아니라 '테이크'다. 발표 전날 같은 자료로
      // 하루에 세 번 연습하는 게 이 제품의 정상 사용이고, 그때도 1회차 → 2회차의
      // diff 가 살아 있어야 회상 대사가 나온다 (§0 "재방문은 N회차 공연")
      takeId: String(meta.takeId || ''),
      at: today(),
      title: meta.title || '',
      slides: Number(meta.slides) || 0,
      durationSec: Math.round(Number(meta.durationSec) || 0),
      score: sc && typeof sc.score === 'number' ? sc.score : null,
      trophy: meta.trophy || '',
      gaps: Array.from(new Set(gaps)),
      stamps,
      absent: Array.isArray(meta.absent) ? meta.absent : [],
    };
  }

  /** 회차 하나를 벽에 붙인다. 같은 테이크면 갱신, 아니면 새 회차다. */
  function record(show) {
    if (!show) return load();
    const shows = load();
    // 같은 테이크를 다시 기록하는 건 갱신이다 (객석을 열어 absent 가 확정될 때 등)
    const at = shows.findIndex(s => s.takeId && s.takeId === show.takeId);
    if (at >= 0) shows[at] = show;
    else shows.push(show);
    save(shows);
    return shows;
  }

  /* ------------------------------------------------------------------ */
  /* 회상 — diff 가 증명할 때만                                           */
  /* ------------------------------------------------------------------ */

  /**
   * 직전 회차에서 비었던 개념 중 이번에 채워진 것.
   *
   * 이게 비면 회상 대사는 아예 나오지 않는다. "지난번보다 좋아졌어요" 같은
   * 두루뭉술한 칭찬을 지어내지 않기 위해서다 (§13).
   */
  function filledSinceLast(current) {
    if (!current) return null;
    // 이번 테이크는 이미 기록돼 있을 수 있으니 비교에서 뺀다
    const prior = load().filter(s => !(s.takeId && s.takeId === current.takeId));
    const prev = prior[prior.length - 1];
    if (!prev || !prev.gaps || !prev.gaps.length) return null;
    const nowGaps = new Set(current.gaps || []);
    const filled = prev.gaps.filter(l => !nowGaps.has(l));
    if (!filled.length) return null;
    return { labels: filled, since: prev.at, nth: prior.length };
  }

  /** 회상 대사 한 줄. 증명된 게 없으면 null. */
  function recallLine(current) {
    const d = filledSinceLast(current);
    if (!d) return null;
    const head = d.labels[0];
    const more = d.labels.length > 1 ? ` 외 ${d.labels.length - 1}개도` : '';
    return {
      who: 'ax',   // 발표를 귀로 들은 병아리라 '들었다'를 말할 자격이 있다
      text: `지난번에 안 했던 '${head}',${more} 오늘은 들었어요!!`,
      labels: d.labels,
    };
  }

  /* ------------------------------------------------------------------ */
  /* 티켓 — canvas 한 장                                                  */
  /* ------------------------------------------------------------------ */

  function clip(g, text, max) {
    const full = String(text);
    let t = full;
    while (t.length > 3 && g.measureText(t).width > max) t = t.slice(0, -1);
    return t.length < full.length ? `${t.slice(0, -1)}…` : t;
  }

  function mmss(sec) {
    const m = Math.floor(sec / 60);
    return m ? `${m}분 ${sec % 60}초` : `${sec}초`;
  }

  /**
   * 회차 티켓. 도장 4개는 그 병아리가 맡은 채점표 클러스터 평균에서 나온다.
   * @returns {HTMLCanvasElement}
   */
  function ticketCanvas(show, { width = 300, scale = 2 } = {}) {
    const H = 132;
    const cv = document.createElement('canvas');
    cv.width = width * scale;
    cv.height = H * scale;
    cv.style.width = `${width}px`;
    cv.style.height = `${H}px`;
    const g = cv.getContext('2d');
    g.scale(scale, scale);

    g.fillStyle = '#fdf6e4';                     // 크림색 종이
    g.fillRect(0, 0, width, H);
    g.strokeStyle = '#e0d2ae';
    g.lineWidth = 1;
    g.strokeRect(.5, .5, width - 1, H - 1);

    const cut = width - 76;                      // 절취선 — 오른쪽이 스텁
    g.setLineDash([3, 4]);
    g.strokeStyle = '#cbb98f';
    g.beginPath();
    g.moveTo(cut, 8);
    g.lineTo(cut, H - 8);
    g.stroke();
    g.setLineDash([]);

    g.fillStyle = '#8b7b5c';
    g.font = '700 10px Pretendard, system-ui, sans-serif';
    g.fillText('척척극장 · 리허설 티켓', 14, 22);

    g.fillStyle = '#3b2f23';
    g.font = '800 15px Pretendard, system-ui, sans-serif';
    g.fillText(clip(g, show.title || '제목 없는 공연', cut - 28), 14, 44);

    g.fillStyle = '#8b7b5c';
    g.font = '600 11px Pretendard, system-ui, sans-serif';
    const bits = [show.at];
    if (show.slides) bits.push(`${show.slides}장`);
    if (show.durationSec) bits.push(mmss(show.durationSec));
    g.fillText(bits.join('  ·  '), 14, 62);

    SEAT_ORDER.forEach((who, i) => {             // 도장 4개
      const x = 22 + i * 34;
      const y = 96;
      const away = (show.absent || []).indexOf(who) >= 0;
      const mood = show.stamps && show.stamps[who];
      g.beginPath();
      g.arc(x, y, 13, 0, Math.PI * 2);
      if (away || !mood) {
        // 못 왔거나 지표가 없으면 빈 도장 자리로 둔다. 채워 넣지 않는다
        g.setLineDash([2, 3]);
        g.strokeStyle = '#cbb98f';
        g.lineWidth = 1.4;
        g.stroke();
        g.setLineDash([]);
      } else {
        g.strokeStyle = STAMP_COLOR[mood] || STAMP_COLOR.neutral;
        g.lineWidth = 2;
        g.stroke();
        g.fillStyle = `${STAMP_COLOR[mood] || STAMP_COLOR.neutral}22`;
        g.fill();
      }
      g.fillStyle = away || !mood ? '#b8a98a' : (STAMP_COLOR[mood] || STAMP_COLOR.neutral);
      g.font = '800 9px Pretendard, system-ui, sans-serif';
      const n = NAMES[who] || who;
      g.fillText(n, x - g.measureText(n).width / 2, y + 3);
    });

    g.fillStyle = '#8b7b5c';                     // 스텁 — 점수
    g.font = '700 9px Pretendard, system-ui, sans-serif';
    g.fillText('완성도', cut + 22, 44);
    g.fillStyle = '#3b2f23';
    g.font = '800 30px Pretendard, system-ui, sans-serif';
    const s = show.score == null ? '—' : String(show.score);
    g.fillText(s, cut + 38 - g.measureText(s).width / 2, 76);
    return cv;
  }

  /* ------------------------------------------------------------------ */
  /* 포스터 벽 — 홈 = 극장 앞                                             */
  /* ------------------------------------------------------------------ */

  /**
   * 지난 공연 포스터 벽. 첫 방문이면 '개관 공연' 현수막이 걸린다.
   *
   * 개관 프레임이 중요한 이유: 서로 처음이라는 사실이 첫 사용의 수행 압박을
   * 지운다. 병아리들도 오늘이 첫 출근이다 (§13).
   */
  function wallHtml() {
    const shows = load().slice().reverse();
    if (!shows.length) {
      /* 캐릭터는 얹는 층이라, Chatter 가 아직 안 붙었으면 문구만 나온다 */
      const bird = (window.Chatter && Chatter.chickSvg)
        ? `<span class="pb-bird ch-seat" data-mood="curious" aria-hidden="true">${Chatter.chickSvg('exaone')}</span>`
        : '';
      return `
        <section class="card pb-wall pb-empty">
          ${bird}
          <div class="pb-banner">오늘 개관!</div>
          <p class="pb-openline">첫 발표를 연습하면 포스터가 한 장 붙어요.<br>
             병아리 넷도 오늘이 첫 출근이라 두리번거리고 있어요.</p>
        </section>`;
    }
    return `
      <section class="card pb-wall">
        <h2 class="section-title pb-head">지난 발표<span class="soft">연습할 때마다 기록이 한 장씩 쌓여요</span></h2>
        <div class="pb-strip">
          ${shows.map((s, i) => `
            <div class="pb-ticket" data-show="${shows.length - 1 - i}"
                 role="img" aria-label="${esc(s.title || '공연')} ${esc(s.at)} ${
                   s.score == null ? '점수 없음' : `${s.score}점`}"></div>`).join('')}
        </div>
      </section>`;
  }

  /** wallHtml() 을 붙인 뒤 호출한다. 티켓 canvas 를 실제로 그려 넣는다. */
  function paintWall(root) {
    const shows = load();
    (root || document).querySelectorAll('.pb-ticket').forEach((el) => {
      if (el.dataset.painted === '1') return;
      const show = shows[Number(el.dataset.show)];
      if (!show) return;
      el.dataset.painted = '1';
      el.appendChild(ticketCanvas(show));
    });
  }

  window.Playbill = {
    load, record, extract, recallLine, filledSinceLast,
    wallHtml, paintWall, ticketCanvas, today,
  };
})();
