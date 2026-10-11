/*
 * 부스 퍼널 신호 보내기 — window.ccFunnel(step, { deck }) (2026-10-11, docs/booth-mobile/funnel-events.md).
 *
 * /hi 랜딩(intro.html)·#/tour/* 화면이 단계마다 한 번 부른다. 서버(POST /api/v1/tour/event)는 저장하지 않고 로그 한 줄만 남기고,
 * scripts/booth_funnel.py 가 시간대별 퍼널 표로 센다. 쿠키·식별자·화면 내용은 보내지 않는다 — {step, deck?, t?} 뿐.
 *
 * - 같은 탭에서 같은 단계(+덱)는 한 번만 보낸다 (뒤로 가기·다시 그리기로 줄이 불지 않게). sessionStorage 가 막혀도 페이지 안에서는 한 번.
 * - t = 이 탭에서 처음 신호를 보낸 뒤 지난 초. 랜딩 → 투어로 페이지가 바뀌어도 이어진다.
 * - 실패해도 화면에는 아무 일 없다 — 신호는 덤이다. fetch keepalive 라 버튼을 누르고 바로 페이지가 바뀌어도 대개 간다.
 *   (sendBeacon 은 쓰지 않는다 — application/json Blob 을 막는 브라우저가 있고, 서버는 JSON 만 받는다)
 * - 인앱 브라우저(카카오톡·네이버·인스타)에서도 같은 출처 fetch 라 그대로 돈다.
 */
(function () {
  'use strict';
  var URL_ = '/api/v1/tour/event';
  var STEPS = ['hi', 'intro', 'team', 'team_end', 'explore', 'tour_deck', 'tour_present', 'tour_analysis',
    'tour_qa', 'tour_report', 'try_real', 'inapp_notice', 'back_team'];
  var DECK_RE = /^_?[a-z0-9][a-z0-9-]{0,39}$/;
  var KEY_T0 = 'cc_funnel_t0';
  var KEY_SENT = 'cc_funnel_sent';
  var sentHere = {};

  function store(fn) {
    try { return fn(window.sessionStorage); } catch (e) { return null; }
  }

  function startedAt() {
    var t0 = Number(store(function (s) { return s.getItem(KEY_T0); }));
    if (t0 > 0) return t0;
    var now = Date.now();
    store(function (s) { s.setItem(KEY_T0, String(now)); });
    return now;
  }

  function alreadySent(key) {
    if (sentHere[key]) return true;
    var list = store(function (s) { return (s.getItem(KEY_SENT) || '').split(','); }) || [];
    return list.indexOf(key) >= 0;
  }

  function markSent(key) {
    sentHere[key] = true;
    store(function (s) {
      var list = (s.getItem(KEY_SENT) || '').split(',').filter(Boolean);
      if (list.indexOf(key) < 0) list.push(key);
      s.setItem(KEY_SENT, list.slice(-40).join(','));
    });
  }

  function ccFunnel(step, opts) {
    if (STEPS.indexOf(step) < 0) return false;
    var deck = opts && typeof opts.deck === 'string' && DECK_RE.test(opts.deck) ? opts.deck : null;
    var key = deck ? step + ':' + deck : step;
    if (alreadySent(key)) return false;
    markSent(key);
    var body = { step: step, t: Math.max(0, Math.min(86400, Math.round((Date.now() - startedAt()) / 1000))) };
    if (deck) body.deck = deck;
    try {
      fetch(URL_, {
        method: 'POST', keepalive: true, credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      }).catch(function () { /* 신호는 덤 — 조용히 넘긴다 */ });
    } catch (e) { /* fetch 가 없는 아주 옛 브라우저 */ }
    return true;
  }

  window.ccFunnel = ccFunnel;
  window.ccFunnel.STEPS = STEPS.slice();
})();
