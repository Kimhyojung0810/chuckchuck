/**
 * Q&A 턴 시각 · 말 끝 판단 (2026-10-17 tune · 음성UX 조사 R1 · R2 · R3) — window.QaTurn
 *
 * 1) 턴 시각 (R1): 질문이 뜸 → 말소리 시작(bos) → 말소리 끝(eos) → 문장 확정 → 말 끝 판단(초읽기 시작) → 미리 판정 → 보내기 →
 *    첫 반응(「…」라고 했죠) → 판정 받음 → 다음 말 첫 글자. 한 턴이 끝나면 window.__qaTurns 에 쌓고 콘솔에 한 줄([qa-turn]) 남긴다.
 *    서버로 보내지 않는다 — 실험실(etc/labs/turn_latency)과 실기기 점검(개발자 도구)이 읽는다.
 * 2) 말 끝 판단 (R2): 받아쓰기(A.X)는 문장이 끝나야 글을 준다. 마지막 문장이 종결어미(-요 · -다 · -죠 · -까요)로 끝나면 짧게,
 *    잇는 말(-고 · -는데 · -서 · -면 · 「그래서」)로 끝나면 길게 기다린다. 기본은 예전처럼 일괄 대기(fixed) — 실기기 확인 전에는
 *    주소 ?qa_eot=ending 이나 ?qa_turn=fast 로만 켠다.
 * 3) 미리 판정 (R3): 말 끝을 짐작한 순간 같은 본문을 speculative 로 보낸다(브리지 server/qa_spec.py). 보내기 때 판정이 이미 돌고 있다.
 *    기본 quiet(초읽기 시작 때) — 더 이르게는 ?qa_spec=final(문장이 종결어미로 확정될 때마다), 끄기 ?qa_spec=off.
 *
 * 순수 판단(설정 읽기 · 어미 판단 · 기다릴 시간 · 턴 요약)은 node 스모크(etc/tests/js/qa_turn.smoke.mjs)가 잡는다.
 */
(function (root) {
  'use strict';

  /** 기본값 — 5단계 그대로(침묵 2.2초 · 초읽기 3초) + 미리 판정은 초읽기 시작 때 */
  const DEFAULTS = Object.freeze({ eot: 'fixed', silenceMs: 2200, sendMs: 3000, spec: 'quiet', finalMs: 900, softMs: 1800, contMs: 3200 });
  /** ?qa_turn=fast — 권고안(실기기 확인 대기): 종결어미 0.9초 · 애매한 끝 1.8초 · 잇는 말 3.2초 + 초읽기 1.2초 + 문장 확정 때 미리 판정 */
  const FAST = Object.freeze({ eot: 'ending', sendMs: 1200, spec: 'final' });
  const MS_MIN = 300;
  const MS_MAX = 8000;

  function num(v, fallback) {
    const n = Number(v);
    return v !== null && v !== '' && Number.isFinite(n) && n >= MS_MIN && n <= MS_MAX ? n : fallback;
  }

  /** 주소 쿼리 → 설정. 모르는 값은 기본값 */
  function config(search) {
    let p;
    try { p = new URLSearchParams(search || ''); } catch (_) { p = new URLSearchParams(''); }
    const base = p.get('qa_turn') === 'fast' ? { ...DEFAULTS, ...FAST } : { ...DEFAULTS };
    const eot = p.get('qa_eot');
    const spec = p.get('qa_spec');
    return {
      eot: eot === 'ending' || eot === 'fixed' ? eot : base.eot,
      silenceMs: num(p.get('qa_silence_ms'), base.silenceMs),
      sendMs: num(p.get('qa_send_ms'), base.sendMs),
      spec: spec === 'off' || spec === 'quiet' || spec === 'final' ? spec : base.spec,
      finalMs: num(p.get('qa_final_ms'), base.finalMs),
      softMs: num(p.get('qa_soft_ms'), base.softMs),
      contMs: num(p.get('qa_cont_ms'), base.contMs),
    };
  }

  /* 한국어 말끝 — 문장 단위 확정 글의 마지막 어절을 본다.
     cont : 잇는 말(-고 · -는데 · -서 · -면 · -지만 · -니까 · 「그래서 · 그리고」) · 망설임(음 · 어 · 그) · 쉼표 — 더 말할 것이다
     soft : 해요체로 끝났지만 이어 말하기 잦은 꼴(-는데요 · -거든요 · -고요 · -서요 · -면요 · -지만요)
     final: 그 밖의 해요체 · 합쇼체 · 평서 · 물음 종결(-요 · -다 · -죠 · -까 · ?) */
  const CONT_WORD_RE = /(?:^|\s)(?:그리고|그래서|그러니까|그런데|근데|그러면|그럼|하지만|그러나|또|또는|및|왜냐하면|예를\s*들면|결국|즉|일단|아무튼|그래도|음+|어+|그+|저+|뭐+|막|약간|이제)\s*[,.…~]*\s*$/;
  const CONT_END_RE = /(?:고|며|면|면서|는데|은데|인데|던데|지만|니까|으니까|라서|이라서|어서|아서|해서|여서|다가|려고|으려고|도록|거나|든지|듯이|만큼|처럼|보다|에서|으로|로|와|과|랑|이랑|하고|의|를|을|는|은|이|가|에|도)\s*[,…~]*\s*$/;
  const SOFT_END_RE = /(?:는데요|은데요|인데요|던데요|거든요|고요|구요|서요|면요|지만요|니까요|해서요|라서요)\s*[.?!…~]*\s*$/;
  const FINAL_END_RE = /(?:요|죠|다|니다|까|나|냐|네|군|래|지|야|음|함|임|듯)\s*[.?!…~]*\s*$|[.?!]\s*$/;

  function endKind(text) {
    const t = String(text || '').replace(/\s+/g, ' ').trim();
    if (!t) return 'none';
    if (/[,，]\s*$/.test(t) || CONT_WORD_RE.test(t)) return 'cont';
    if (SOFT_END_RE.test(t)) return 'soft';
    if (/(?:요|죠|니다|까요?|다)\s*[.?!…~]*\s*$/.test(t)) return 'final';
    if (CONT_END_RE.test(t)) return 'cont';
    return FINAL_END_RE.test(t) ? 'final' : 'unknown';
  }

  /** 마지막 확정 글 뒤 몇 ms 조용하면 말 끝으로 볼까 — fixed 면 silenceMs 하나 */
  function silenceFor(text, cfg) {
    const c = cfg || DEFAULTS;
    if (c.eot !== 'ending') return c.silenceMs;
    const k = endKind(text);
    if (k === 'final') return c.finalMs;
    if (k === 'soft') return c.softMs;
    if (k === 'cont') return c.contMs;
    return c.silenceMs;
  }

  /* ─── 턴 시각 ─────────────────────────────────────────────────────────────────────────────── */
  const ONCE = new Set(['q_shown', 'mic_on', 'speech_on', 'send', 'ack', 'judged', 'next']);
  const KEEP = 60;

  function now() {
    return (root.performance && typeof root.performance.now === 'function') ? root.performance.now() : Date.now();
  }

  /** 한 턴 기록을 요약한다 — 말 끝(마지막 eos, 없으면 마지막 문장 확정)에서 각 지점까지 ms */
  function summarize(turn) {
    const t = (turn && turn.t) || {};
    const end = t.speech_off != null && (t.final == null || t.speech_off <= t.final + 50) ? t.speech_off : t.final;
    const d = (k) => (t[k] != null && end != null ? Math.round(t[k] - end) : null);
    return {
      key: turn && turn.key, eot_to_final: d('final'), eot_to_quiet: d('quiet'), eot_to_spec: d('spec'), eot_to_send: d('send'),
      eot_to_ack: d('ack'), eot_to_judged: d('judged'), eot_to_next: d('next'),
      judge_wait: t.judged != null && t.send != null ? Math.round(t.judged - t.send) : null,
      spec_hit: turn && turn.specHit != null ? turn.specHit : null, cancels: (turn && turn.cancels) || 0,
      finals: (turn && turn.finals) || 0, eot_kind: (turn && turn.eotKind) || '',
    };
  }

  const state = { cur: null, turns: [] };

  function begin(key, extra) {
    if (state.cur && state.cur.key === key) return state.cur;
    if (state.cur) finish('replaced');
    state.cur = { key: String(key || ''), t: { q_shown: now() }, finals: 0, cancels: 0, specs: 0, ...(extra || {}) };
    return state.cur;
  }

  function mark(name, extra) {
    const cur = state.cur;
    if (!cur) return null;
    if (ONCE.has(name) && cur.t[name] != null) return cur;
    cur.t[name] = now();
    if (name === 'final') cur.finals += 1;
    if (name === 'spec') cur.specs += 1;
    if (name === 'cancel') cur.cancels += 1;
    if (extra) Object.assign(cur, extra);
    return cur;
  }

  function finish(reason) {
    const cur = state.cur;
    if (!cur) return null;
    state.cur = null;
    cur.reason = reason || 'next';
    cur.sum = summarize(cur);
    state.turns.push(cur);
    if (state.turns.length > KEEP) state.turns.splice(0, state.turns.length - KEEP);
    try { root.__qaTurns = state.turns; } catch (_) { /* 읽기 전용 창 */ }
    if (root.console && typeof root.console.info === 'function' && cur.t.send != null) {
      root.console.info('[qa-turn]', JSON.stringify(cur.sum));
    }
    return cur;
  }

  let cfgCache = null;
  function cfg() {
    if (!cfgCache) {
      let search = '';
      try { search = (root.location && root.location.search) || ''; } catch (_) { search = ''; }
      cfgCache = config(search);
    }
    return cfgCache;
  }

  root.QaTurn = { DEFAULTS, FAST, config, cfg, endKind, silenceFor, summarize, begin, mark, finish,
    current: () => state.cur, turns: () => state.turns.slice() };
  try { root.__qaTurns = state.turns; } catch (_) { /* 읽기 전용 창 */ }
})(typeof window !== 'undefined' ? window : globalThis);
