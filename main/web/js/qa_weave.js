/**
 * Q&A 「생각 엮기」 모형 — 순수 함수만 (2026-10-13). 화면은 js/qa_stage.js(띠 · 틀 · 레일)가 그린다.
 * 처음엔 이 파일이 웹캠 위 흔적 기둥 · 내 발언 칩 · 빛줄기를 그렸다 — 같은 날 Q&A 재설계(design/qa_stage/prototype.html)에서
 * 웹캠 위에 아무것도 얹지 않기로 하고 화면 층을 내렸다. 규칙은 그대로 쓴다.
 *
 * 정직 규칙 — 데이터는 qa.live 그대로다. 내 발언은 서버가 답 원문에서 확인한 구절(claim)만, 비면 없다.
 * 꼬리질문의 출처는 「같은 질문 안에서 마지막 채점 답의 claim → 그 판정의 followup」 하나뿐이다(코칭 되물음 · 다시 말하기는 잇지 않는다).
 */

/** 관점 — 서버 f09_reframe.PERSPECTIVES 와 같은 키 (서버가 다시 확인한다) */
const QW_PERSPECTIVES = [['example', '실제 사례'], ['evidence', '근거'], ['counter', '반례'], ['cause', '원인'], ['effect', '결과']];

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
