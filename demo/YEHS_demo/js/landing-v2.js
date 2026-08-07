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
/*
  ── 랜딩 화면을 내렸다 (2026-08-07 지시: "이거 다 날려달라니깐") ──

  마케팅 문서 한 장을 먼저 받게 하는 구조 자체를 걷어냈다. 메인화면을 다시
  만드는 중이고, 부스에서 앞에 서는 30초~3분 동안 읽을 것은 제품 설명이
  아니라 제품이다. #/landing 으로 들어와도 곧장 메인화면으로 보낸다.

  마크업(landing-v2.html)과 스타일(css/landing-v2.css)은 지우지 않고 뒀다.
  거기밖에 없는 카피가 있어서, 새 메인화면이 문장을 가져다 쓸 수 있다.
  되살리려면 아래 renderLanding 을 예전 fetch 판으로 되돌리면 된다
  (git show 1cc0f29:demo/YEHS_demo/js/landing-v2.js).
*/
(function () {
  'use strict';

  function renderLanding() {
    // replace 를 쓴다. assign 이면 뒤로 가기가 #/landing 으로 돌아왔다가 다시
    // 튕겨 나가서, 사용자가 뒤로 가기로 화면을 못 빠져나온다.
    location.replace(`${location.pathname}${location.search}#/`);
  }

  window.renderLanding = renderLanding;
})();
