/**
 * 리포트 2.0 「Q&A 돌아보기」 (10-17 리포트 개편 설계 §3) — 질문마다 한 화면: 무엇을 물었나(주제) · 내가 뭐라고 답했나(턴마다) ·
 * 판정과 근거(자료 장 · 줄) · 빠진 점 · 「이렇게 답하면 좋아요」 30초 뼈대 · 꼬리질문 사슬. 홈의 요약 카드도 여기서 그린다.
 *
 * 새 판정 · 새 문장을 만들지 않는다. 뼈대는 그래프의 주장 문장 · 자료 원문 줄 · 판정 근거 줄 · 예상 질문의 모범답 · 내 답 원문만 잇는다
 * (js/report_graph.js qaBetter). 데이터가 없는 칸은 숨긴다 — 옛 저장본(턴 답 · 근거 줄 없음)도 깨지지 않게.
 *
 * window.ReportV2Qa.screens(ctx) → { qa(id), card(), entryLine() }
 *   ctx = { esc, I, asset, V: () => 뷰모델, D: () => 입력, QB: () => 판 뷰모델 | null, QBS: 판 화면 | null, slideTag(n, cls), EMBED }
 */
(function () {
  /* 판정 묶음 — qa_live.js liveBucket · 결과 화면과 같은 말. 색은 판정 5색 중 ok · mid 와 회색만 */
  const BUCKET = {
    self: { word: '스스로 설명했어요', short: '스스로 설명', tone: 'ok', icon: 'check' },
    helped: { word: '도움 받아 닫았어요', short: '도움 받아', tone: 'mid', icon: 'bang' },
    retold: { word: '답 보고 다시 말했어요', short: '다시 말함', tone: 'mid', icon: 'redo' },
    skipped: { word: '넘겼어요', short: '넘김', tone: 'na', icon: 'q' },
    unasked: { word: '묻지 않았어요', short: '안 물음', tone: 'na', icon: 'q' },
  };
  const ASIDE = { concept: '다른 주제로 넘겼어요', skip: '건너뛰었어요', perspective: '관점을 바꿔 다시 받았어요' };
  const LAYER = { thesis: '핵심 주장', claim: '주장', concept: '개념' };
  const TURN = { good: ['설득했어요', 'ok'], partial: ['절반쯤 짚었어요', 'mid'], wrong: ['다시 짚을 곳이 있어요', 'no'], unknown: ['판정을 미뤘어요', 'na'] };
  /* 꼬리질문이 어떤 수였나 — contracts DIALOGUE_MOVES */
  const MOVE = { connect: '이어 묻기', clarify: '되묻기', challenge: '반박', explore: '넓혀 묻기', recite: '다시 말해 보기', hint: '힌트',
    deepen: '파고들기', refocus: '질문으로 돌아가기', explain: '짚어 주기' };
  const ROLE = { covered: '짚은 줄', missing: '빠진 줄', conflict: '다시 볼 줄' };
  const PATTERN_FALLBACK = { P1: '핵심 주장', P2: '근거 충분성', P3: '빈 고리', P4: '결론을 좌우하는 조건', P5: '주장 잇기', P6: '방법 선택',
    P7: '한계 · 반례', P8: '개념의 역할', P9: '함정', P10: '옮겨 쓰기', voice: '발표를 듣고' };
  /** 띄어쓰기 · 문장부호를 뺀 비교용 글 */
  const squash = (t) => String(t || '').replace(/[\s.,!?·…「」『』"'“”‘’()\[\]~\-]/g, '');
  /** claim 이 text 안 어디인지 [시작, 끝] — 띄어쓰기 · 문장부호를 무시하고 찾는다(4글자 미만 · 못 찾으면 null) */
  function claimAt(text, claim) {
    const t = String(text || ''); const c = squash(claim);
    if (c.length < 4) return null;
    const at = t.indexOf(String(claim || '').trim());
    if (at >= 0 && String(claim).trim()) return [at, at + String(claim).trim().length];
    const pos = []; let flat = '';
    for (let k = 0; k < t.length; k += 1) { const ch = squash(t[k]); if (ch) { flat += ch; pos.push(k); } }
    const f = flat.indexOf(c);
    return f < 0 ? null : [pos[f], pos[f + c.length - 1] + 1];
  }
  const plainDeck = (t) => String(t || '').replace(/\|\s*-{3,}\s*/g, ' ').replace(/^\s*\|\s*|\s*\|\s*$/g, '').replace(/\s*\|\s*/g, ' · ')
    .replace(/(?:·\s*){2,}/g, '· ').replace(/\s{2,}/g, ' ').trim();

  function screens(ctx) {
    const { esc, I } = ctx;
    const pattern = (p) => ((window.ReportQaBoard && window.ReportQaBoard.PATTERN) || PATTERN_FALLBACK)[p] || '';
    const model = (m) => (((window.ReportQaBoard && window.ReportQaBoard.MODELS) || {})[m] || {}).name || '';
    const B = (q) => BUCKET[q.bucket] || BUCKET.unasked;
    const chip = (q) => { const b = B(q); return `<span class="rq-verdict t-${b.tone}"><i>${I[b.icon] || ''}</i>${esc(b.short)}</span>`; };
    const layerChip = (q) => (q.topic && LAYER[q.topic.layer] ? `<span class="rq-layer k-${esc(q.topic.layer)}">${LAYER[q.topic.layer]}</span>` : '');
    /** 판정 묶음 곁말 — 「왜 그 묶음인가」 한 줄 (결과 화면 liveResultRowBase 와 같은 말) */
    function meta(q) {
      const r = q.result || {};
      if (q.bucket === 'self') return (r.turns || 0) <= 1 ? '첫 답에 설명했어요' : `${r.turns}번 만에 설명했어요`;
      if (q.bucket === 'helped') {
        const why = [];
        if (r.closeReason === 'explained') why.push('같이 풀고 닫았어요');
        else if (r.closeReason === 'guard') why.push('자료와 다시 맞춰 볼 곳이 남았어요');
        else if (r.closeReason === 'rounds' || r.closeReason === '') why.push('세 번째 답에서 닫혔어요');
        if (r.viaCoach && r.closeReason !== 'explained') why.push('보기 · 빈칸 도움으로 닫았어요');
        if ((r.hintLevel || 0) >= 3) why.push(`힌트 ${r.hintLevel}칸까지 봤어요`);
        return why.slice(0, 2).join(' · ');
      }
      if (q.bucket === 'retold') return '답을 보고 내 말로 다시 말했어요';
      if (r.setAside) return ASIDE[r.setAside] || '건너뛰었어요';
      return q.result ? '답하지 않고 넘겼어요' : '';
    }
    /** 근거 칩 — 칩(장 · 줄 · 역할)은 늘 보이고, 줄 글 · 까닭은 눌러야 펼친다 (기조 R4) */
    function groundChips(q) {
      const r = q.result || {};
      // 닫는 판정에 근거 줄이 없으면(마지막 답이 되묻기 · 코칭 턴) 근거 줄이 있는 가장 최근 답의 줄을, 몇 번째 답의 줄인지 밝히고 보인다
      const at = r.grounds && r.grounds.length ? -1 : q.steps.map((s) => (s.grounds || []).length > 0).lastIndexOf(true);
      const gs = (at < 0 ? r.grounds : q.steps[at].grounds) || [];
      if (gs.length) {
        const from = at >= 0 && at < q.steps.length - 1 ? `<p class="rq-src">내 답 ${at + 1}을 판정한 근거 줄이에요</p>` : '';
        return `${from}<div class="rq-grounds">${gs.map((g) => {
          const line = /^S\d+-(\d+)/.exec(g.ref || '');
          const where = `${g.slide_no ? `자료 ${g.slide_no}장` : '자료'}${line ? ` · ${line[1]}번째 줄` : ''}`;
          return `<details class="rq-ground r-${esc(g.role)}"><summary><span>${esc(where)}</span><b>${esc(ROLE[g.role] || '근거')}</b></summary>
            <blockquote>${esc(plainDeck(g.quote))}</blockquote>${g.note ? `<p>${esc(g.note)}</p>` : ''}</details>`;
        }).join('')}</div>`;
      }
      const look = (r.lookSlides || []).filter((n) => Number(n) > 0);
      if (look.length) {
        return `<div class="rq-grounds">${look.map((n) => `<details class="rq-ground r-missing"><summary><span>자료 ${esc(n)}장</span><b>다시 볼 장</b></summary>
          ${ctx.slideTag(n, 'nv-thumb rq-thumb')}<p>판정이 이 장의 줄을 근거로 봤어요.</p></details>`).join('')}</div>`;
      }
      return '';
    }

    /** 홈 요약 카드 — 질문 수 · 판정 3단계 분포 · 질문마다 한 줄 · 고른 과정 입구. Q&A 를 안 했으면 Result 한 칸 (기조 R17) */
    function card() {
      const V = ctx.V();
      const qs = V.qa.filter((q) => q.result);
      if (!qs.length) {
        return `<section class="rq-card is-empty" aria-label="Q&A 돌아보기"><h3 class="hm-sec">Q&A 돌아보기</h3>
          <div class="rq-empty"><span class="nv-ico i-green">${I.chat}</span><div><b>Q&A를 하면 질문별 복기가 여기에 생겨요</b>
          <p>질문마다 내 답 · 판정 근거 · 더 나은 답의 뼈대를 보여 줘요.</p></div></div>
          <div class="rq-foot"><button type="button" class="nv-link" data-href="index.html#/rehearsal/qa">Q&A 연습하기</button></div></section>`;
      }
      const n = { self: 0, helped: 0, skipped: 0 };
      qs.forEach((q) => { n[q.bucket === 'retold' ? 'helped' : q.bucket === 'unasked' ? 'skipped' : q.bucket] += 1; });
      // 가장 아쉬운 질문 — 넘김 > 도움 받아(핵심 주장 먼저) > 없음. 스스로 설명한 질문은 표시하지 않는다
      const rank = (q) => (q.bucket === 'skipped' ? 3 : q.bucket === 'helped' || q.bucket === 'retold' ? 2 : 0) + (q.topic && q.topic.layer === 'thesis' ? 0.5 : 0);
      const worst = qs.slice().sort((a, b) => rank(b) - rank(a))[0];
      const flag = worst && rank(worst) >= 2 ? worst.id : '';
      const QB = ctx.QB();
      return `<section class="rq-card" aria-label="Q&A 돌아보기">
        <div class="hm-sechead"><h3 class="hm-sec">Q&A 돌아보기</h3><span class="hm-count">질문 <b>${qs.length}</b>개</span></div>
        <ul class="rq-dist" aria-label="판정 나눔">
          <li class="t-ok${n.self ? '' : ' is-zero'}"><i>${I.check}</i>스스로 설명 <b>${n.self}</b></li>
          <li class="t-mid${n.helped ? '' : ' is-zero'}"><i>${I.bang}</i>도움 받아 <b>${n.helped}</b></li>
          <li class="t-na${n.skipped ? '' : ' is-zero'}"><i>${I.q}</i>넘김 <b>${n.skipped}</b></li>
        </ul>
        <div class="nv-group rq-rows">${qs.map((q, k) => `<button type="button" class="nv-row rq-row" data-push="qa:${esc(q.id)}">
            <span class="rq-n">${k + 1}</span>
            <span class="nv-row-main"><span class="rq-tags">${layerChip(q)}${q.id === flag ? '<span class="rq-flag">먼저 볼 질문</span>' : ''}${chip(q)}</span>
              <b>${esc(q.text)}</b><small>${esc(meta(q))}</small></span>
            <i class="nv-chev">${I.chev}</i></button>`).join('')}
          ${ctx.QBS && QB ? ctx.QBS.entry() : ''}</div>
      </section>`;
    }

    /** 질문 하나 */
    function qa(qid) {
      const V = ctx.V();
      const all = V.qa.filter((x) => x.result);
      const q = V.qa.find((x) => x.id === qid);
      if (!q) return { title: 'Q&A', short: '질문', html: '<p class="nv-empty">이 질문의 기록이 없어요.</p>' };
      const k = all.indexOf(q);
      const r = q.result || {};
      const b = B(q);
      const t = q.topic || {};
      const bt = q.better || {};
      // 판정이 붙잡은 말(claim)에 밑줄 — 서버는 띄어쓰기 · 문장부호를 빼고 원문에 있는지 본다(f09 _answer_claim). 화면도 그렇게 찾고, 못 찾으면 밑줄 · 곁말 없이
      const hl = (text, claim) => { const at = claimAt(text, claim); return at ? `${esc(text.slice(0, at[0]))}<mark>${esc(text.slice(at[0], at[1]))}</mark>${esc(text.slice(at[1]))}` : esc(text); };
      const why = (s) => (s.answer && claimAt(s.answer, s.claim) ? '<p class="rq-why">밑줄은 판정이 붙잡은 내 말이에요</p>' : '');
      // 꼬리질문이 비었거나 처음 질문 그대로면(판정이 꼬리질문을 안 줘 같은 질문에 다시 답한 턴) 말풍선 · 수 이름 없이 한 줄만
      const sameQ = (t) => !String(t || '').trim() || squash(t) === squash(q.text);
      const tags = [layerChip(q), t.slide ? `<span class="rq-tag">자료 ${esc(t.slide)}장</span>` : '',
        pattern(t.pattern) ? `<span class="rq-tag">묻는 방식 · ${esc(pattern(t.pattern))}</span>` : '',
        model(t.by) ? `<span class="rq-tag">${esc(model(t.by))}가 물었어요</span>` : '',
        t.auto ? '<span class="rq-tag is-dim">자동으로 만든 질문이에요</span>' : ''].filter(Boolean).join('');

      // 주고받은 말 — 질문 → 내 답 → (꼬리질문 · 수) → 내 답 …
      const turns = q.steps.map((s, i) => {
        const fu = i === 0 ? '' : q.steps[i - 1].followup;
        const ask = i === 0 ? '' : sameQ(fu) ? '<li class="rq-t ai is-again"><p class="rq-who">같은 질문에 다시 답했어요</p></li>'
          : `<li class="rq-t ai"><p class="rq-who">꼬리질문${q.steps[i - 1].move && MOVE[q.steps[i - 1].move] ? ` · ${MOVE[q.steps[i - 1].move]}` : ''}</p><p class="rq-bub">${esc(fu)}</p></li>`;
        const said = s.answer ? hl(s.answer, s.claim) : s.claim ? `<mark>${esc(s.claim)}</mark>` : '';
        const tv = TURN[s.verdict];
        const last = i === q.steps.length - 1 && q.steps.length > 1;
        return `${ask}<li class="rq-t me${last ? ' is-last' : ''}"><p class="rq-who">내 답${q.steps.length > 1 ? ` ${i + 1}` : ''}${last ? ' · 마지막 답' : ''}${tv ? ` · <span class="v-${tv[1]}">${tv[0]}</span>` : ''}</p>
          <p class="rq-bub">${said || '<span class="rq-dim">이 답은 저장되지 않았어요</span>'}</p>${why(s)}</li>`;
      }).join('');
      const tail = q.steps.length && !sameQ(q.steps[q.steps.length - 1].followup)
        ? `<li class="rq-t ai"><p class="rq-who">꼬리질문</p><p class="rq-bub">${esc(q.steps[q.steps.length - 1].followup)}</p></li>` : '';

      // 30초 뼈대 — 있는 값만. 셋 다 비면 칸을 안 그린다
      const g = bt.ground;
      const step1 = bt.conclusion ? `<li><span class="rq-k">1</span><div><b>결론 먼저</b><p>「${esc(bt.conclusion)}」</p><p class="rq-src">${bt.conclusionKind === 'thesis' ? '발표의 핵심 주장이에요' : bt.conclusionKind === 'claim' ? '이 질문이 겨눈 주장이에요' : '이 질문이 겨눈 개념이에요'} · 첫 문장으로 말해요</p></div></li>` : '';
      const step2 = g ? `<li><span class="rq-k">2</span><div><b>근거 하나</b><p class="rq-src">자료 ${esc(g.slide || '')}장${g.line ? ` · ${g.line}번째 줄` : ''}</p><blockquote>${esc(plainDeck(g.quote))}</blockquote></div></li>` : '';
      const step3 = bt.goodAsIs
        ? '<li><span class="rq-k">3</span><div><b>잇기</b><p>이 답 그대로 좋아요. 결론 문장만 먼저 말해요.</p></div></li>'
        : bt.gist ? `<li><span class="rq-k">3</span><div><b>잇기</b><p>${esc(bt.gist)}</p>${bt.polished ? '<p class="rq-src">자료 줄로 확인한 모범답이에요</p>' : '<p class="rq-src">예상 질문의 모범답이에요</p>'}</div></li>` : '';
      const better = step1 || step2 || step3 ? `<h3 class="nv-sec">이렇게 답하면 좋아요<small>30초 뼈대</small></h3>
        <article class="rq-better"><ol>${step1}${step2}${step3}</ol>
          ${bt.keep && !bt.goodAsIs ? `<p class="rq-keep"><b>내 답에서 살릴 말</b>「${esc(bt.keep)}」</p>` : ''}
          <p class="rq-note">새로 지은 문장이 아니에요. 그래프의 주장 문장 · 자료 원문 · 예상 질문의 모범답에서 가져왔어요.</p></article>` : '';
      const others = all.filter((x) => x !== q);
      // 답 하나는 한 곳에만 — 꼬리질문이 있으면 사슬 안에서(마지막 답 표시), 없으면 「내 답」 한 칸 (10-17 검토)
      const chain = q.steps.length > 1 || !!tail;
      const ls = [...q.steps].reverse().find((s) => s.answer || s.claim);
      const lastSaid = ls ? `<p class="rq-bub">${ls.answer ? hl(ls.answer, ls.claim) : `<mark>${esc(ls.claim)}</mark>`}</p>${why(ls)}`
        : (r.answer ? `<p class="rq-bub">${esc(r.answer)}</p>` : '');
      // 발표 태도(베타) 사실 한 줄 — 이 질문에 8초 넘게 답했고 화면 쪽 시간을 잴 수 있었을 때만 (js/behavior_report.js qaFact). 판정과 무관한 곁말
      let fact = null;
      try {
        const BR = window.BehaviorReport; const Dn = ctx.D && ctx.D();
        if (BR && typeof BR.qaFact === 'function' && Dn && Dn.behavior) fact = BR.qaFact(Dn.behavior, V.qa.indexOf(q) + 1);
      } catch (_) { fact = null; }
      const factLine = fact ? `<button type="button" class="rq-beh" data-push="attitude"><span class="rq-beh-i">${I.cam || ''}</span><span class="rq-beh-t">${esc(fact.text)}</span><em>베타</em><i class="nv-chev">${I.chev}</i></button>` : '';
      return {
        title: q.text, short: '질문', size: 'md', eyebrow: `Q&A 돌아보기 · 질문 ${k + 1} / ${all.length}`,
        html: `
        ${tags ? `<div class="rq-tags is-top">${tags}</div>` : ''}
        ${t.node && t.node !== q.text ? `<p class="rq-aim">겨눈 곳 · ${esc(t.node)}</p>` : ''}
        ${chain ? `<h3 class="nv-sec">내 답과 꼬리질문<small>질문 → 내 답 → 꼬리질문</small></h3><ol class="rq-turns">${turns}${tail}</ol>`
          : lastSaid ? `<h3 class="nv-sec">내 답</h3><ol class="rq-turns"><li class="rq-t me">${lastSaid}</li></ol>` : ''}
        ${factLine}
        <section class="nv-card rq-judge">
          <div class="rq-judge-head"><span class="nv-badge t-${b.tone}">${I[b.icon] || ''}</span><div><b>${esc(b.word)}</b>${meta(q) ? `<small>${esc(meta(q))}</small>` : ''}</div></div>
          ${r.summary ? `<p class="rq-summary">${esc(r.summary)}</p><p class="rq-src">AI 판정이 남긴 한 문장이에요</p>` : ''}
          ${groundChips(q)}
        </section>
        ${(bt.missing || []).length ? `<h3 class="nv-sec">이번 답에서 빠진 것</h3><ul class="nv-card rq-miss">${bt.missing.map((m) => `<li>${esc(m)}</li>`).join('')}</ul><p class="nv-note">AI 판정이 짚은 점이에요.</p>` : ''}
        ${better}
        ${ctx.QBS ? ctx.QBS.link(q.text) : ''}
        ${others.length ? `<h3 class="nv-sec">다른 질문</h3><div class="nv-group">${others.map((x) => `<button type="button" class="nv-row" data-push="qa:${esc(x.id)}"><span class="nv-row-main"><b>${esc(x.text)}</b></span>${chip(x)}<i class="nv-chev">${I.chev}</i></button>`).join('')}</div>` : ''}`,
        cta: ctx.EMBED ? null : { label: '질문 다시 받아 보기', attr: 'data-href="index.html#/rehearsal/qa"', icon: I.redo },
      };
    }

    return { qa, card, BUCKET, meta };
  }

  if (typeof window !== 'undefined') window.ReportV2Qa = { screens, BUCKET, plainDeck, claimAt };
})();
