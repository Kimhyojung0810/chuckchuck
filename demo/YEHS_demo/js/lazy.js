/**
 * 첫 화면에 안 쓰는 파일은 쓸 때 받는다.
 *
 * 공개 사이트는 요청 하나에 ~0.2초, 새 연결에 ~1초가 드는 길(Cloudflare → Funnel 도쿄 → DERP 홍콩 → VM)을
 * 탄다 (2026-10-01 실측). 첫 방문의 요청 수와 바이트가 곧 첫 화면이 뜨는 시간이라, 누구나 보는 화면(홈·새 발표·
 * 질문 코칭·리포트)에 필요한 것만 처음에 받고 나머지는 여기서 받는다.
 *
 * 받을 파일은 index.html 의 <template id="lazyAssets"> 에 적는다. <template> 안의 태그는 브라우저가 받지도
 * 실행하지도 않지만, 브리지가 ?v= 를 내용 해시로 바꿔 주고(demo/static_assets.py) scripts/chk bump 도 그대로
 * 올려 준다 — 처음부터 불러오는 파일과 캐시 규칙이 같다.
 *
 *   ccLazy.load('beta')           → Promise<boolean> (다 받았으면 true, 하나라도 못 받으면 false)
 *   ccLazy.loaded('beta')         → 이미 받았나
 *   ccLazy.whenIdle(['motion'])   → 첫 화면이 뜬 뒤 한가할 때 받는다
 */
(function () {
  const pending = new Map();
  const done = new Set();
  const got = new Set(); // 받은 주소 — 다시 받을 때 이미 실행한 스크립트를 두 번 돌리지 않는다 (const 중복 선언)

  function nodesOf(name) {
    const t = document.getElementById('lazyAssets');
    return t ? Array.from(t.content.querySelectorAll(`[data-bundle="${name}"]`)) : [];
  }

  function fetchOne(tpl) {
    const url = tpl.getAttribute('src') || tpl.getAttribute('href');
    if (got.has(url)) return Promise.resolve(true);
    return new Promise((resolve) => {
      let el;
      if (tpl.tagName === 'LINK') {
        el = document.createElement('link');
        el.rel = 'stylesheet';
        el.href = tpl.getAttribute('href');
      } else {
        el = document.createElement('script');
        el.src = tpl.getAttribute('src');
        el.async = false; // 같은 번들 안에서는 적은 순서대로 실행한다 (booth_cv → booth_qa)
      }
      el.onload = () => { got.add(url); resolve(true); };
      el.onerror = () => {
        console.warn('[chuckchuck] 나중에 받는 파일을 못 받았어요:', url);
        el.remove();
        resolve(false);
      };
      (tpl.tagName === 'LINK' ? document.head : document.body).appendChild(el);
    });
  }

  function afterLoad(name) {
    if (name === 'pdf' && window.pdfjsLib) {
      const w = nodesOf('pdf').map((n) => n.getAttribute('data-worker')).find(Boolean);
      if (w) window.pdfjsLib.GlobalWorkerOptions.workerSrc = w;
    }
  }

  function load(name) {
    if (!pending.has(name)) {
      const nodes = nodesOf(name);
      if (!nodes.length) console.warn('[chuckchuck] 모르는 번들:', name);
      pending.set(name, Promise.all(nodes.map(fetchOne)).then((oks) => {
        const ok = oks.every(Boolean);
        if (ok) done.add(name);
        else pending.delete(name); // 망이 잠깐 끊겼던 거면 다음에 다시 받는다
        afterLoad(name);
        return ok;
      }));
    }
    return pending.get(name);
  }

  function whenIdle(names) {
    const go = () => names.forEach(load);
    const idle = () => (window.requestIdleCallback ? requestIdleCallback(go, { timeout: 3000 }) : setTimeout(go, 600));
    if (document.readyState === 'complete') idle();
    else addEventListener('load', idle, { once: true });
  }

  window.ccLazy = {
    load,
    loadAll: (names) => Promise.all(names.map(load)).then((oks) => oks.every(Boolean)),
    loaded: (name) => done.has(name),
    whenIdle,
  };
})();
