/*
랜딩(#/landing) 진입점 v2 — 2026-08-07 지시로 v1 을 갈아엎은 것.

v1(js/landing.js, 14KB)이 하던 일:
  - initShell(): IntersectionObserver 로 5칸 스크롤 스냅을 몰고 점 인디케이터를 칠했다
  - LandingWorkbench(): 히어로 목업을 애니메이션으로 조립했다
  - LandingMotion 에서 M·mIn·mPop·buildWave 를 끌어다 썼다

셋 다 화면을 가로채는 장치라 v2 에서 버렸다 (CLAUDE.md §3-4 — 스크롤 하이재킹
금지, 한 화면의 주인공은 하나). v2 는 그냥 스크롤되는 문서라서, 여기서 할 일은
조각을 받아 #app 에 넣는 것뿐이다. 붙일 동작이 없으면 붙이지 않는 게 맞다.

v1 파일들(landing.js · landing-motion.js · landing-workbench.js · landing*.css)은
지우지 않고 남겨 뒀다. 되돌릴 일이 생기면 index.html 의 로드만 되돌리면 된다.
*/
(function () {
  'use strict';

  //: 조각을 매번 새로 받지 않게 캐시 버전을 붙인다. 마크업을 고치면 올린다.
  const FRAGMENT = 'landing-v2.html?v=landing2';

  async function renderLanding() {
    const app = document.getElementById('app');
    if (!app) return;

    app.className = 'landing';
    app.innerHTML = '<p class="landing-loading">랜딩을 불러오는 중이에요…</p>';

    try {
      const res = await fetch(FRAGMENT);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      app.innerHTML = await res.text();
    } catch (err) {
      // 실패를 성공처럼 꾸미지 않는다 (CLAUDE.md §4). 대신 나갈 길을 준다 —
      // 나갈 선택지가 없는 화면은 다크패턴이다 (§3-1).
      app.innerHTML = `
        <div class="landing-error">
          <h1>랜딩을 불러오지 못했어요</h1>
          <p>${err.message}</p>
          <a class="btn btn-primary" href="#/">내 발표로 가기</a>
        </div>`;
      return;
    }

    // 라우터가 해시만 바꾸고 스크롤은 그대로 두는 경우가 있다. 랜딩은 맨 위에서
    // 시작해야 첫 문장부터 읽힌다.
    window.scrollTo(0, 0);
  }

  window.renderLanding = renderLanding;
})();
