/*
 * 부스 퍼널 신호 보내기 — window.ccFunnel(step, { deck }) (2026-10-11, docs/booth-mobile/funnel-events.md).
 *
 * /hi 랜딩(intro.html)·#/tour/* 화면이 단계마다 한 번 부른다. 서버(POST /api/v1/tour/event)는 저장하지 않고 로그 한 줄만 남기고,
 * scripts/booth_funnel.py 가 시간대별 퍼널 표로 센다. 쿠키·식별자·화면 내용은 보내지 않는다 — {step, deck?, t?} 뿐.
 *
 * - 같은 탭에서 같은 단계(+덱)는 한 번만 보낸다 (뒤로 가기·다시 그리기로 줄이 불지 않게). sessionStorage 가 막혀도 페이지 안에서는 한 번.
 * - t = 이 탭에서 처음 신호를 보낸 뒤 지난 초. 랜딩 → 투어로 페이지가 바뀌어도 이어진다.
 * - 429(상한)면 Retry-After(60초 이하) 뒤에 한 번 더 보낸다. 그래도 429 거나 망이 끊기면 「보냈다」 표시를 지워서
 *   다음에 그 단계를 부를 때 다시 간다 — 전에는 응답 전에 표시해서 429 로 떨어진 단계를 그 탭에서 다시 안 보냈다(10-12 점검).
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
  var RETRY_MAX_SEC = 60;

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

  function unmark(key) {
    delete sentHere[key];
    store(function (s) {
      var list = (s.getItem(KEY_SENT) || '').split(',').filter(function (k) { return k && k !== key; });
      s.setItem(KEY_SENT, list.join(','));
    });
  }

  function retryAfterSec(r) {
    var v = r && r.headers && typeof r.headers.get === 'function' ? Number(r.headers.get('Retry-After')) : 0;
    return v > 0 ? v : 0;
  }

  function post(key, body, retried) {
    try {
      fetch(URL_, {
        method: 'POST', keepalive: true, credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      }).then(function (r) {
        if (!r || r.ok) return;
        if (r.status === 429) {
          var wait = retryAfterSec(r);
          if (!retried && wait > 0 && wait <= RETRY_MAX_SEC && typeof setTimeout === 'function') {
            setTimeout(function () { post(key, body, true); }, wait * 1000);
            return;
          }
          unmark(key);
        } else if (r.status >= 500) {
          unmark(key);
        }
        // 400 은 본문이 틀린 것 — 다시 보내도 같으니 표시를 둔다
      }, function () { unmark(key); /* 망 끊김 — 다음에 다시 */ });
    } catch (e) { /* fetch 가 없는 아주 옛 브라우저 */ }
  }

  function ccFunnel(step, opts) {
    if (STEPS.indexOf(step) < 0) return false;
    var deck = opts && typeof opts.deck === 'string' && DECK_RE.test(opts.deck) ? opts.deck : null;
    var key = deck ? step + ':' + deck : step;
    if (alreadySent(key)) return false;
    markSent(key);
    var body = { step: step, t: Math.max(0, Math.min(86400, Math.round((Date.now() - startedAt()) / 1000))) };
    if (deck) body.deck = deck;
    post(key, body, false);
    return true;
  }

  window.ccFunnel = ccFunnel;
  window.ccFunnel.STEPS = STEPS.slice();
})();
