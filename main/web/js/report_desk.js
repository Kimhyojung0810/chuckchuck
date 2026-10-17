/**
 * 리포트 데스크 — /VRShow 리포트 정거장 다섯(05 결과 · 06 다시 보기 · 07 청중석 · 08 코칭 · 09 연습)을 저마다 한 화면으로
 * (10-17 사용자: 「#/rehearsal 리포트는 정보는 좋았는데 복잡해 보였다 — 나눠서 잘 보여 주는 게 핵심. 화면에 맞게, 뭘 말하는지 알게」).
 *
 * 원칙
 *  - 정거장 하나 = 질문 하나. 맨 위 큰 문장이 그 답이다(「그래서 어땠나 · 장마다 무슨 말을 했나 · 어떻게 들렸나 · 무엇을 고치나 · 다음엔 뭘 하나」).
 *  - 창 하나에 다 들어간다 — 바깥 스크롤 없음. 긴 목록만 제 칸 안에서 스크롤.
 *  - 정보는 옛 리포트(app.js R_TAB_VIEWS)와 같은 분석 결과 · 같은 판정. 새로 지어내지 않는다. 다 못 담은 건 「자세히」 로 옛 탭을 그대로 연다.
 *  - 판정 색 다섯(설명함 · 안 나옴 · 모순 · 정당한 생략 · 판정 안 함)은 그대로.
 *
 * report_v2.js 의 탭 모드(스튜디오)에서 뿌리 화면 다섯을 이것으로 바꾼다: ReportDesk.routes(ctx) → { home, replay, audience, coach, practice }
 * 각 화면은 { title, short, desk: true, html, wire(el), onTime(now) } — renderScreen 이 막대 · 큰 제목 없이 창을 채운다.
 */
(function () {
  const VERDICT = {
    aligned: { w: '설명함', t: 'ok' }, missing: { w: '안 나옴', t: 'no' }, contradiction: { w: '자료와 모순', t: 'ct' },
    justified_skip: { w: '정당한 생략', t: 'om' }, unjudged: { w: '판정 안 함', t: 'na' },
  };
  const STATION_OF = { time: 'audience', delivery: 'audience', logic: 'replay', content: 'coach', visual: 'coach', clarity: 'coach', audience: 'audience' };
  const STATION_NAME = { home: '05 결과', replay: '06 다시 보기', audience: '07 청중석', coach: '08 코칭', practice: '09 연습' };

  function routes(c) {
    const { D, V, esc, fmt, grade, I, asset, tone, CRIT, EV } = c;
    const nodes = (D.graph && D.graph.nodes) || [];
    const nodeById = new Map(nodes.map((n) => [n.id, n]));
    const items = (D.alignment && D.alignment.items) || [];
    /** 개념 하나의 판정 — 분석이 대체값으로 끝났으면 「판정 안 함」 (옛 리포트와 같은 규칙) */
    const verdictOf = (it) => VERDICT[it.decided_by === 'fallback' ? 'unjudged' : it.verdict] || VERDICT.unjudged;
    const concepts = items.map((it) => {
      const n = nodeById.get(it.node_id) || {};
      return { id: it.node_id, label: n.label || it.node_id, slides: n.slide_nos || [], weight: n.weight || it.doc_weight || 0,
        importance: n.importance || '', v: verdictOf(it), quote: it.evidence || '', note: it.note || '' };
    });
    const counts = concepts.reduce((m, x) => { m[x.v.t] = (m[x.v.t] || 0) + 1; return m; }, {});
    const judged = concepts.filter((x) => x.v.t !== 'na').length;
    const pace = D.pace || null;
    const habits = D.habits || null;
    const slides = V.slides || [];
    const slideSec = (s) => s.spans.reduce((n, sp) => n + Math.max(0, sp.end - sp.start), 0);
    const paceOf = (no) => (pace && pace.slides || []).find((p) => p.slide_no === no) || null;
    const conceptsOn = (no) => concepts.filter((x) => x.slides.includes(no)).sort((a, b) => b.weight - a.weight);
    const uttsOn = (no) => (V.utterances || []).filter((u) => u.slide_no === no);
    /** 장 하나의 가장 나쁜 판정 — 썸네일 점 색 */
    const worstOn = (no) => { const order = ['no', 'ct', 'mid', 'na', 'om', 'ok']; const ts = conceptsOn(no).map((x) => x.v.t); return order.find((t) => ts.includes(t)) || ''; };
    const eyebrow = (key) => `${STATION_NAME[key]}${D.sample ? ' · 샘플' : ''} · ${D.deck.title || ''}`;
    // 머리 — 큰 문장은 「무슨 일이 있었고 그래서 어떻다」 (판단), 숫자는 그 아래 작은 줄(lead)로 (10-17 「2장에 93초 · 1장엔 12초 — 이딴 멘트는 직관적으로 이해 못 함」)
    const head = (key, title, side = '', lead = '') => `<header class="dk-head"><div><p class="dk-eyebrow">${esc(eyebrow(key))}</p><h1 class="dk-title" tabindex="-1">${esc(title)}</h1>${lead ? `<p class="dk-lead">${esc(lead)}</p>` : ''}</div>${side}</header>`;
    /** 사람 말 시간 — 600 → 10분, 140 → 2분 20초, 35 → 35초 */
    const human = (sec) => { const t = Math.max(0, Math.round(sec || 0)); const m = Math.floor(t / 60); const r = t % 60; return m ? (r ? `${m}분 ${r}초` : `${m}분`) : `${r}초`; };
    /** 받침에 따라 조사 — 「가설 A」가 · 「평점」이. 끝 글자가 영문 · 숫자면 읽는 소리로 */
    const josa = (word, withB, withoutB) => {
      const ch = String(word).trim().slice(-1);
      const code = ch.charCodeAt(0) - 0xAC00;
      let b;
      if (code >= 0 && code <= 11171) b = code % 28 !== 0;
      else if (/[0-9]/.test(ch)) b = '013678'.includes(ch);
      else if (/[a-z]/i.test(ch)) b = 'lmnr'.includes(ch.toLowerCase());
      else b = false;
      return b ? withB : withoutB;
    };
    const sampleTag = D.sample ? '<span class="dk-tag">미리 돌린 샘플 리포트예요</span>' : '';
    const more = (k, label) => (c.hasLegacy ? `<button type="button" class="dk-more" data-push="legacy:${k}">${esc(label)} <i>${I.chev}</i></button>` : '');
    const go = (key, label) => `<button type="button" class="dk-go" data-root="${esc(key)}">${esc(label)} <i>${I.chev}</i></button>`;
    // 출처 줄 — 내 발표일 때만(「방금 한 발표 · 녹음이 없어요」 같은 안내). 샘플은 머리의 「샘플」 표시로 대신한다(샘플의 출처 줄은 개발 기록이라 방문자에게 뜻이 없다)
    const foot = () => (D.sample ? '' : `<footer class="dk-foot">${Object.values(D.provenance || {}).map((t) => `<span>${esc(t)}</span>`).join('')}</footer>`);
    const wireRoots = (el) => el.querySelectorAll('[data-root]').forEach((b) => b.addEventListener('click', (e) => { e.stopPropagation(); c.goRoot(b.dataset.root); }));

    /* ══ 05 결과 — 그래서 이번 발표는 어땠나 ══ */
    function home() {
      const sc = V.score; const val = sc ? sc.value : null;
      const C = 2 * Math.PI * 52;
      const top = V.issues.slice(0, 3);
      const fillers = habits ? (habits.filler_cnt || 0) + (habits.repeat_cnt || 0) : null;
      const kpis = [
        judged ? { k: '개념 전달', v: `${counts.ok || 0}`, u: `/ ${judged}개`, sub: counts.no ? `안 나온 개념 ${counts.no}개` : '판정한 개념을 다 설명했어요', t: (counts.ok || 0) / judged >= 0.8 ? 'ok' : 'mid', go: 'coach' } : null,
        pace ? { k: '발표 시간', v: fmt(pace.actual_sec), u: `/ ${fmt(pace.target_sec)}`, sub: pace.actual_sec < pace.target_sec * 0.8 ? '목표보다 많이 짧아요' : pace.actual_sec > pace.target_sec * 1.15 ? '목표보다 길어요' : '목표에 맞췄어요', t: Math.abs(pace.actual_sec / pace.target_sec - 1) <= 0.2 ? 'ok' : 'mid', bar: Math.min(1, pace.actual_sec / pace.target_sec), go: 'audience' } : null,
        pace ? (() => { const [lo, hi] = String(pace.recommended_cpm || '').split('~').map(Number); const v = pace.avg_chars_per_min;
          const word = lo && v < lo ? '권장보다 조금 느려요' : hi && v > hi ? '권장보다 빨라요' : '듣기 편한 속도예요';
          return { k: '말 속도', v: `${Math.round(v)}`, u: '자/분', sub: `${word} (권장 ${pace.recommended_cpm})`, t: word === '듣기 편한 속도예요' ? 'ok' : 'mid', go: 'audience' }; })() : null,
        habits ? { k: '말버릇', v: `${fillers}`, u: '번', sub: fillers ? '간투어 · 반복이 있었어요' : '간투어 · 반복이 거의 없어요', t: fillers <= 3 ? 'ok' : 'mid', go: 'audience' } : null,
      ].filter(Boolean);
      return {
        title: '결과', short: '결과', desk: true,
        html: `<div class="dk dk-home">
          ${head('home', V.headline || (top[0] ? top[0].title : '분석 결과를 정리했어요'), sampleTag)}
          <div class="dk-body">
            <section class="dk-col dk-score">
              <div class="dk-card dk-ring">
                ${val != null ? `<div class="dk-ringbox"><svg viewBox="0 0 120 120" aria-hidden="true"><circle cx="60" cy="60" r="52" class="bg"/><circle cx="60" cy="60" r="52" class="fg" style="--c:${C.toFixed(1)};--off:${(C * (1 - Math.max(0, Math.min(100, val)) / 100)).toFixed(1)}"/></svg>
                  <div><b>${esc(grade(val))}</b><span>${esc(val)}점</span></div></div>` : ''}
                <div class="dk-ringtxt"><p class="dk-cap">발표 완성도</p><p class="dk-strong">${esc(sc && sc.situation ? `${sc.situation} 기준` : '종합')}</p>
                  <p class="dk-cap">${fmt(V.duration_sec)} 발표 · ${slides.length}장</p>${sc ? `<button type="button" class="dk-link" data-push="scores">기준별 점수 <i>${I.chev}</i></button>` : ''}</div>
              </div>
              <div class="dk-kpis">${kpis.map((x) => `<button type="button" class="dk-kpi" data-root="${x.go}">
                <span class="dk-cap">${esc(x.k)}</span><span class="dk-num t-${x.t}">${esc(x.v)}<small>${esc(x.u)}</small></span>
                ${x.bar != null ? `<span class="dk-bar"><i style="width:${(x.bar * 100).toFixed(1)}%"></i></span>` : ''}<span class="dk-sub">${esc(x.sub)}</span></button>`).join('')}</div>
            </section>
            <section class="dk-col dk-fix">
              <h2 class="dk-h">먼저 고칠 것</h2>
              <div class="dk-fixlist">${top.map((x, k) => `<article class="dk-card dk-fixcard" data-push="issue:${esc(x.id)}" role="button" tabindex="0">
                  <span class="dk-n t-${tone(x)}">${k + 1}</span>
                  <div class="dk-fixmain"><b>${esc(x.title)}</b><p>${esc(x.why || '')}</p></div>
                  ${go(STATION_OF[x.criterion] || 'coach', STATION_NAME[STATION_OF[x.criterion] || 'coach'])}
                </article>`).join('') || '<p class="dk-empty">근거가 있는 문제를 찾지 못했어요.</p>'}</div>
              ${V.strengths.length ? `<div class="dk-good"><span class="dk-cap">잘한 점</span>${V.strengths.slice(0, 2).map((x) => `<button type="button" class="dk-chip t-ok" data-push="issue:${esc(x.id)}">${I.check}<span>${esc(x.title)}</span></button>`).join('')}</div>` : ''}
            </section>
          </div>
          ${foot()}
        </div>`,
        wire(el) {
          wireRoots(el);
          el.querySelectorAll('.dk-fixcard').forEach((a) => a.addEventListener('keydown', (e) => { if (e.key === 'Enter') a.click(); }));
        },
      };
    }

    /* ══ 06 다시 보기 — 장마다 무슨 말을 했나 (옛 「슬라이드로 보는 발표」 + 「흐름」 + 녹음) ══ */
    function replay() {
      const dur = V.duration_sec || 0;
      // 큰 문장: 어느 장을 서둘렀나 + 어느 장에서 무엇이 빠졌나 — 판단만. 초 단위 숫자는 lead 로
      const rushed = slides.filter((sl) => { const p = paceOf(sl.no); return p && p.status === 'short' && p.actual_sec < p.recommended_sec * 0.5; });
      const miss = concepts.filter((x) => x.v.t === 'no' || x.v.t === 'ct').sort((a, b) => b.weight - a.weight)[0];
      const partA = rushed.length && rushed.length === slides.length ? '모든 장을 너무 빨리 넘어갔' : rushed.length ? `${rushed.map((sl) => sl.no).join('·')}장은 너무 빨리 넘어갔` : '';
      const partB = miss ? `${miss.slides[0] ? `${miss.slides[0]}장에선 ` : ''}「${miss.label}」${josa(miss.label, '이', '가')} ${miss.v.t === 'ct' ? '자료와 다르게 나왔' : '빠졌'}` : '';
      const title = partA && partB ? `${partA}고, ${partB}어요` : partA ? `${partA}어요` : partB ? `${partB}어요` : '장마다 자료대로 잘 전했어요';
      const recs = ((pace && pace.slides) || []).map((p) => p.recommended_sec);
      const sameRec = recs.length && recs.every((r) => Math.abs(r - recs[0]) < 1);
      const lead = slides.map((sl) => `${sl.no}장 ${human(slideSec(sl))}`).join(' · ') + (sameRec ? ` — 장마다 권장 ${human(recs[0])}` : '');
      const links = ((D.flow && D.flow.issues) || []);
      const linkOn = (no) => links.filter((f) => (f.slide_nos || []).includes(no));
      let cur = (slides[0] || {}).no || 1;
      const pct = (s) => `${(100 * s / (dur || 1)).toFixed(3)}%`;
      const panel = (no) => {
        const cs = conceptsOn(no); const us = uttsOn(no); const p = paceOf(no); const sp = (slides.find((s) => s.no === no) || {}).spans || [];
        const a = sp.length ? sp[0].start : null; const b = sp.length ? sp[sp.length - 1].end : null;
        return `
          <div class="dk-slidehead"><b>${esc(no)}장</b><span>${esc((slides.find((s) => s.no === no) || {}).title || '')}</span>
            ${p ? `<span class="dk-pill t-${p.status === 'ok' ? 'ok' : 'mid'}">${Math.round(p.actual_sec)}초 · 권장 ${Math.round(p.recommended_sec)}초</span>` : ''}</div>
          ${a != null ? c.playBtn(`s${no}`, a, b, `이 장 듣기 ${fmt(a)}–${fmt(b)}`) : ''}
          <h3 class="dk-h3">이 장의 개념</h3>
          <div class="dk-concepts">${cs.length ? cs.map((x) => `<div class="dk-concept"><span class="dk-v t-${x.v.t}">${esc(x.v.w)}</span><span>${esc(x.label)}</span></div>`).join('') : '<p class="dk-empty">이 장에 판정할 개념이 없어요.</p>'}</div>
          <h3 class="dk-h3">이 장에서 한 말</h3>
          <div class="dk-said">${us.length ? us.map((u) => `<button type="button" class="dk-utt" data-s="${u.start}" data-u="${esc(u.id)}"><time>${fmt(u.start)}</time><span>${esc(u.text)}</span></button>`).join('') : '<p class="dk-empty">이 장에서 한 말이 받아쓰기에 없어요.</p>'}</div>
          ${linkOn(no).map((f) => `<div class="dk-flow t-${f.kind === 'good_link' ? 'ok' : 'mid'}"><b>${f.kind === 'good_link' ? '매끄럽게 이었어요' : '연결이 끊겼어요'}</b><p>“${esc(f.cue || '')}”</p></div>`).join('')}`;
      };
      return {
        title: '다시 보기', short: '다시 보기', desk: true,
        html: `<div class="dk dk-replay">
          ${head('replay', title, `<div class="dk-headacts">${more(0, '장별 판정 전체')}${more(3, '흐름 자세히')}</div>`, lead)}
          <div class="dk-body">
            <nav class="dk-strip" aria-label="장 고르기">${slides.map((s) => `<button type="button" class="dk-thumb${s.no === cur ? ' is-on' : ''}" data-slide-pick="${s.no}">
              ${c.slideTag(s.no, 'dk-thumbimg')}<span class="dk-thumbmeta"><b>${s.no}장</b><small>${Math.round(slideSec(s))}초</small>${worstOn(s.no) ? `<i class="dk-dot t-${worstOn(s.no)}"></i>` : ''}</span></button>`).join('')}</nav>
            <section class="dk-stage">
              <div class="dk-slidebox">${c.slideTag(cur, 'dk-bigslide')}</div>
              <div class="dk-card dk-player">
                <button type="button" class="dk-bigplay" data-play="all" data-a="0" data-b="" ${c.audio() ? '' : 'disabled'} aria-label="처음부터 듣기"><span class="nv-pi">${I.play}</span></button>
                <div class="dk-track" aria-label="발표 시간축">
                  ${slides.flatMap((s) => s.spans.map((sp) => `<span class="dk-band${s.no === cur ? ' is-on' : ''}" data-band="${s.no}" style="left:${pct(sp.start)};width:${pct(sp.end - sp.start)}"><em>${s.no}장</em></span>`)).join('')}
                  <i class="dk-head-mark"></i>
                </div>
                <small class="dk-clock">0:00 / ${fmt(dur)}</small>
              </div>
              ${c.audio() ? '' : '<p class="dk-cap">녹음이 저장되지 않아 들을 수 없어요. 글로만 봐요.</p>'}
            </section>
            <aside class="dk-card dk-side">${panel(cur)}</aside>
          </div>
        </div>`,
        onTime(now) {
          const el = c.top();
          const h = el.querySelector('.dk-head-mark'); if (h) h.style.left = pct(now);
          const k = el.querySelector('.dk-clock'); if (k) k.textContent = `${fmt(now)} / ${fmt(dur)}`;
          el.querySelectorAll('.dk-utt.is-now').forEach((x) => x.classList.remove('is-now'));
          const u = (V.utterances || []).find((x) => x.start <= now && x.end >= now);
          if (u) { const b = el.querySelector(`.dk-utt[data-u="${u.id}"]`); if (b) b.classList.add('is-now'); }
          const s = slides.find((sl) => sl.spans.some((sp) => now >= sp.start && now < sp.end));
          if (s && s.no !== cur && el._pick) el._pick(s.no);
        },
        wire(el) {
          wireRoots(el);
          const side = el.querySelector('.dk-side'); const box = el.querySelector('.dk-slidebox');
          // 처음 그린 옆 칸은 renderScreen 이 이미 단추를 이어 줬다 — 다시 그릴 때만 잇는다(두 번 이으면 재생이 켜졌다 바로 꺼진다)
          const bindSide = (fresh) => {
            side.querySelectorAll('.dk-utt').forEach((b) => b.addEventListener('click', () => c.play(+b.dataset.s, null, `u${b.dataset.u}`)));
            if (fresh) c.wire(side);
          };
          el._pick = (no) => {
            cur = no;
            el.querySelectorAll('.dk-thumb').forEach((t) => t.classList.toggle('is-on', +t.dataset.slidePick === no));
            el.querySelectorAll('.dk-band').forEach((t) => t.classList.toggle('is-on', +t.dataset.band === no));
            box.innerHTML = c.slideTag(no, 'dk-bigslide');
            side.innerHTML = panel(no); bindSide(true);
          };
          el.querySelectorAll('[data-slide-pick]').forEach((b) => b.addEventListener('click', () => el._pick(+b.dataset.slidePick)));
          const tr = el.querySelector('.dk-track');
          tr.addEventListener('click', (e) => { const r = tr.getBoundingClientRect(); c.play(((e.clientX - r.left) / r.width) * dur, null, 'scrub'); });
          bindSide(false);
        },
      };
    }

    /* ══ 07 청중석 — 듣는 사람에게는 어떻게 들렸나 (옛 「말하기」 + 삐약이 청중석) ══ */
    function audience() {
      const evs = V.evaluators || [];
      const short = pace && pace.actual_sec < pace.target_sec * 0.8;
      const clean = habits && (habits.filler_cnt || 0) + (habits.repeat_cnt || 0) <= 3;
      const title = short && clean ? '말은 깔끔했지만, 목표보다 훨씬 일찍 끝났어요'
        : short ? '목표보다 훨씬 일찍 끝났어요' : clean ? '말버릇 없이 깔끔하게 들렸어요' : '듣는 사람 입장에서 다시 들어 봐요';
      const maxSec = Math.max(1, ...((pace && pace.slides) || []).map((p) => Math.max(p.actual_sec, p.recommended_sec)));
      const cpm = pace ? Math.round(pace.avg_chars_per_min) : null;
      const rec = pace ? String(pace.recommended_cpm || '').split('~').map(Number) : [];
      const lo = 150, hi = 450; const at = (v) => `${Math.max(0, Math.min(100, (100 * (v - lo)) / (hi - lo))).toFixed(1)}%`;
      const spans = (habits && habits.spans) || [];
      const line = (e) => (e.remarks.find((r) => !r.filler) || {}).text || '';
      const moodOf = (e) => (e.remarks.find((r) => !r.filler) || {}).mood || 'neutral';
      const M = { happy: 'happy', curious: 'curious', excited: 'excited', grumpy: 'neutral', neutral: 'neutral' };
      return {
        title: '청중석', short: '청중석', desk: true,
        html: `<div class="dk dk-aud">
          ${head('audience', title, `<div class="dk-headacts">${more(1, '말하기 자세히')}</div>`, pace ? `${human(pace.target_sec)} 발표를 ${human(pace.actual_sec)} 만에 끝냈어요${habits ? ` · 간투어 ${habits.filler_cnt || 0}번 · 같은 말 반복 ${habits.repeat_cnt || 0}번` : ''}` : '')}
          <div class="dk-body">
            <section class="dk-theater"><i class="dk-spot"></i>
              <div class="dk-seats">${evs.map((e, k) => `<button type="button" class="dk-seat${e.absent ? ' is-off' : ''}" data-push="chick:${esc(e.key)}" style="--k:${k}">
                ${!e.absent && line(e) ? `<p class="dk-bubble"><span>${esc(line(e))}</span></p>` : `<p class="dk-bubble is-off">${e.absent ? '이번엔 못 왔어요' : '이번엔 할 말이 없대요'}</p>`}
                <img src="${esc(asset(`assets/chick-${e.key}-${e.absent ? 'neutral' : M[moodOf(e)] || 'neutral'}.svg`))}" alt="">
                <b>${esc(e.name)}</b><small>${esc(e.lane)}</small></button>`).join('') || '<p class="dk-empty">청중 반응을 불러오고 있어요.</p>'}</div>
              <p class="dk-theater-note">점수를 매기는 심사위원이 아니에요. 넷이 저마다 맡은 것만 보고 한마디씩 해요.</p>
            </section>
            <section class="dk-metrics">
              ${pace ? `<div class="dk-card dk-m">
                <h3 class="dk-h3">장마다 쓴 시간 <small>회색 = 권장</small></h3>
                <div class="dk-bars">${pace.slides.map((p) => `<div class="dk-barrow"><span>${p.slide_no}장</span>
                  <div class="dk-bartrack"><i class="rec" style="width:${(100 * p.recommended_sec / maxSec).toFixed(1)}%"></i><i class="act t-${p.status === 'ok' ? 'ok' : 'mid'}" style="width:${(100 * p.actual_sec / maxSec).toFixed(1)}%"></i></div>
                  <b>${Math.round(p.actual_sec)}초</b></div>`).join('')}</div>
                <p class="dk-sub">${esc((pace.tips || [])[0] || '')}</p></div>` : ''}
              ${pace ? `<div class="dk-card dk-m">
                <h3 class="dk-h3">말 속도</h3>
                <p class="dk-num">${cpm}<small>자/분</small></p>
                <div class="dk-gauge">${rec.length === 2 ? `<i class="band" style="left:${at(rec[0])};width:calc(${at(rec[1])} - ${at(rec[0])})"></i>` : ''}<i class="me" style="left:${at(cpm)}"></i></div>
                <div class="dk-gaugelab"><span>느림</span><span>권장 ${esc(pace.recommended_cpm)}</span><span>빠름</span></div>
                <p class="dk-sub">${cpm < (rec[0] || 0) ? '조금 느린 편이에요. 서두르지 않은 건 좋아요.' : cpm > (rec[1] || 1e9) ? '빠른 편이에요. 핵심 장에서 숨을 한 번 고르세요.' : '듣기 편한 속도예요.'}</p></div>` : ''}
              ${habits ? `<div class="dk-card dk-m">
                <h3 class="dk-h3">말버릇</h3>
                <div class="dk-habits"><span><b>${habits.filler_cnt || 0}</b>간투어</span><span><b>${habits.repeat_cnt || 0}</b>같은 말 반복</span><span><b>${habits.pause_cnt || 0}</b>긴 멈춤</span></div>
                <div class="dk-spans">${spans.slice(0, 4).map((s, k) => `<div class="dk-spanrow"><span>“${esc(s.text)}”</span><small>${esc(s.slide_no)}장 · ${fmt(s.start_sec)}</small>${c.playBtn(`h${k}`, s.start_sec - 1.5, s.end_sec + 1, '듣기')}</div>`).join('') || `<p class="dk-sub">${esc((habits.tips || [])[0] || '눈에 띄는 말버릇이 없어요.')}</p>`}</div></div>` : ''}
            </section>
          </div>
        </div>`,
        wire(el) { wireRoots(el); },
      };
    }

    /* ══ 08 코칭 — 무엇을 어떻게 고치나 (옛 「개념 전달」 + 「채점 근거」 + 코칭) ══ */
    function coach() {
      const list = [...V.issues, ...V.unknown];
      const misses = concepts.filter((x) => x.v.t === 'no' || x.v.t === 'ct').filter((x) => !list.some((y) => (y.concepts || []).some((cc) => cc.id === `C:${x.id}` || cc.label === x.label)));
      let pick = list[0] ? list[0].id : '';
      const first = list[0];
      const firstConcept = first && (first.concepts || [])[0];
      const title = !first ? '근거가 있는 고칠 곳을 찾지 못했어요'
        : first.criterion === 'time' ? '가장 급한 건 발표 시간이에요 — 장마다 할 말을 더 채워야 해요'
        : first.criterion === 'content' && firstConcept ? `가장 급한 건 「${firstConcept.label}」${josa(firstConcept.label, '을', '를')} 말로 전하지 않은 거예요`
        : `가장 먼저 고칠 것 — ${first.title}`;
      const lead = list.length ? `고칠 곳은 모두 ${list.length}개예요. 왼쪽에서 하나씩 골라 무엇을 어떻게 바꿀지 봐요.` : '';
      const detail = (id) => {
        const x = list.find((y) => y.id === id); if (!x) return '';
        const said = x.proofs.find((p) => p.kind === 'said' && p.status === 'supported');
        const deckP = x.proofs.find((p) => p.kind === 'deck');
        const acts = x.actions.filter((a) => a.text);
        const slide = (deckP && deckP.anchor.slide_no) || (x.anchor && x.anchor.slide_no);
        return `
          <p class="dk-eyebrow">${esc(CRIT[x.criterion] || '종합')} · ${esc(EV[x.evidence] || '')}</p>
          <h2 class="dk-dtitle">${esc(x.title)}</h2>
          <div class="dk-steps">
            <div class="dk-step"><span class="dk-stepn">1</span><div><h3 class="dk-h3">지금은</h3>
              ${said ? `<blockquote>${esc(said.text)}</blockquote>${said.anchor.start_sec != null ? c.playBtn('cs', said.anchor.start_sec, said.anchor.end_sec, `${fmt(said.anchor.start_sec)} 들어 보기`) : ''}` : `<p>${esc(x.why || '분석이 까닭을 남기지 않았어요.')}</p>`}</div></div>
            ${said && x.why ? `<div class="dk-step"><span class="dk-stepn">2</span><div><h3 class="dk-h3">왜 문제인가요</h3><p>${esc(x.why)}</p></div></div>` : ''}
            <div class="dk-step is-accent"><span class="dk-stepn">${said && x.why ? 3 : 2}</span><div><h3 class="dk-h3">이렇게 해 봐요</h3>
              ${acts.length ? `<ul>${acts.slice(0, 3).map((a) => `<li>${esc(a.text)}</li>`).join('')}</ul>` : '<p>자료 원문을 보며 이 부분을 말로 다시 설명해 봐요.</p>'}</div></div>
          </div>
          ${slide ? `<div class="dk-ref">${c.slideTag(slide, 'dk-refimg')}<p class="dk-cap">자료 ${esc(slide)}장 · ${esc(((D.deck.slides || []).find((s) => s.slide_no === slide) || {}).title || '')}</p></div>` : ''}`;
      };
      return {
        title: '코칭', short: '코칭', desk: true,
        html: `<div class="dk dk-coach">
          ${head('coach', title, `<div class="dk-headacts">${more(2, '개념 전달 전체')}${more(4, '채점 근거')}</div>`, lead)}
          <div class="dk-body">
            <nav class="dk-card dk-list" aria-label="고칠 곳">
              ${list.map((x, k) => `<button type="button" class="dk-item${x.id === pick ? ' is-on' : ''}" data-pick="${esc(x.id)}"><span class="dk-n t-${tone(x)}">${k + 1}</span><span><b>${esc(x.title)}</b><small>${esc(CRIT[x.criterion] || '종합')}</small></span></button>`).join('')}
              ${misses.length ? `<p class="dk-listcap">말로 안 나온 개념</p>${misses.map((x) => `<div class="dk-concept"><span class="dk-v t-${x.v.t}">${esc(x.v.w)}</span><span>${esc(x.label)}</span></div>`).join('')}` : ''}
              <p class="dk-listcap">개념 ${judged}개 판정</p>
              <div class="dk-tally">${['ok', 'no', 'ct', 'om', 'na'].filter((t) => counts[t]).map((t) => `<span class="dk-v t-${t}">${esc(Object.values(VERDICT).find((v) => v.t === t).w)} ${counts[t]}</span>`).join('')}</div>
            </nav>
            <section class="dk-card dk-detail">${detail(pick)}</section>
          </div>
        </div>`,
        wire(el) {
          wireRoots(el);
          const box = el.querySelector('.dk-detail');
          el.querySelectorAll('[data-pick]').forEach((b) => b.addEventListener('click', () => {
            pick = b.dataset.pick;
            el.querySelectorAll('[data-pick]').forEach((y) => y.classList.toggle('is-on', y === b));
            box.innerHTML = detail(pick); c.wire(box);
          }));
        },
      };
    }

    /* ══ 09 연습 — 다음 연습은 이렇게 (옛 「연습 도구」 + 「발표 구성」 + Q&A 돌아보기) ══ */
    function practice() {
      const x = V.issues[0];
      const targets = [];
      V.issues.forEach((y) => y.actions.forEach((a) => { if (a.practice && !targets.some((p) => p.label === a.practice.label)) targets.push(a.practice); }));
      const punch = concepts.filter((y) => y.v.t === 'ok' && y.quote).sort((a, b) => b.weight - a.weight).filter((y, k, arr) => !arr.slice(0, k).some((z) => z.quote.includes(y.quote) || y.quote.includes(z.quote))).slice(0, 3);   // 같은(겹치는) 구절이 여러 개념의 근거면 한 번만
      const weak = concepts.filter((y) => y.v.t === 'no' || y.v.t === 'ct' || y.v.t === 'na').sort((a, b) => (a.v.t === 'na') - (b.v.t === 'na') || b.weight - a.weight).slice(0, 3);   // 안 나옴 · 모순이 먼저, 판정 안 함은 뒤
      const state = (r) => (r.setAside === 'concept' ? '다른 개념으로 넘김' : r.setAside === 'skip' ? '건너뜀' : r.setAside === 'perspective' ? '관점 바꿈' : r.verdict === 'good' ? '스스로 설명함' : r.verdict ? '도움 받아 설명함' : '안 물음');
      const qt = (r) => (r.verdict === 'good' ? 'ok' : r.setAside ? 'na' : r.verdict ? 'mid' : 'na');
      const href = (route) => `index.html${route}`;
      return {
        title: '연습', short: '연습', desk: true,
        html: `<div class="dk dk-prac">
          ${head('practice', weak.length ? `다음엔 「${weak[0].label}」부터 말로 채워 봐요` : '고칠 장만 골라 다시 해 봐요', `<div class="dk-headacts">${more(5, '연습 도구 전체')}${more(6, '발표 구성 다시 짜기')}</div>`, weak.length && weak[0].slides.length ? `${weak[0].slides.join('·')}장에 있는 개념이에요. 그 장부터 다시 말해 보면 돼요.` : '')}
          <div class="dk-body">
            <section class="dk-card dk-pcol">
              <h3 class="dk-h3">다시 연습</h3>
              <div class="dk-rows">${targets.slice(0, 4).map((p) => `<button type="button" class="dk-row" data-href="${esc(href(p.route))}"><span class="dk-ico">${I.redo}</span><span><b>${esc(p.label)}</b><small>${p.kind === 'qa' ? 'Q&A 에서 이 개념 질문을 다시 받아요' : '그 장부터 다시 말해요'}</small></span></button>`).join('')}
                <button type="button" class="dk-row is-main" data-href="${esc(href('#/rehearsal'))}"><span class="dk-ico">${I.redo}</span><span><b>처음부터 다시 발표하기</b><small>리허설을 새로 시작해요</small></span></button></div>
              ${weak.length ? `<h3 class="dk-h3">채울 개념</h3><div class="dk-concepts">${weak.map((y) => `<div class="dk-concept"><span class="dk-v t-${y.v.t}">${esc(y.v.w)}</span><span>${esc(y.label)}</span><small>${esc(y.slides.join(' · '))}장</small></div>`).join('')}</div>` : ''}
            </section>
            <section class="dk-card dk-pcol">
              <h3 class="dk-h3">그대로 써도 좋은 문장</h3>
              <p class="dk-sub">자료대로 잘 전한 말이에요. 다음 발표에서도 이대로 말해요.</p>
              <div class="dk-punch">${punch.map((y) => `<figure><blockquote>“${esc(y.quote)}”</blockquote><figcaption>${esc(y.label)} · ${esc(y.slides.join(' · '))}장</figcaption></figure>`).join('') || '<p class="dk-empty">아직 고를 문장이 없어요.</p>'}</div>
            </section>
            <section class="dk-card dk-pcol">
              <h3 class="dk-h3">Q&A 돌아보기</h3>
              <div class="dk-rows">${V.qa.length ? V.qa.map((q) => `<button type="button" class="dk-row" data-push="qa:${esc(q.id)}"><span class="dk-v t-${qt(q.result || {})}">${esc(state(q.result || {}))}</span><span><b>${esc(q.text)}</b></span></button>`).join('') : '<p class="dk-empty">이 리포트엔 Q&A 기록이 없어요.</p>'}</div>
              ${c.qaEntry()}
            </section>
          </div>
        </div>`,
        wire(el) { wireRoots(el); },
      };
    }

    return { home, replay, audience, coach, practice };
  }

  window.ReportDesk = { routes };
})();
