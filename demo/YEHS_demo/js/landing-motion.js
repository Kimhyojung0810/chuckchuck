/*
랜딩 전용 모션 헬퍼입니다.
Motion(motion.dev) 라이브러리를 싣지 않으므로 전부 no-op 으로 떨어지고,
등장 효과는 CSS 의 [data-reveal] 트랜지션만으로 동작합니다.
모션 축소 설정이면 라이브러리가 있어도 끕니다.
*/
window.LandingMotion = (function () {
  'use strict';

  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  /* ── Motion(motion.dev) 인핸스먼트 헬퍼 — 라이브러리 부재·모션 축소 설정이면 no-op ── */
  const M = (!reduceMotion && window.Motion) ? window.Motion : null;
  function mIn(els, extra) {
    if (!M) return;
    const list = els instanceof Element ? [els] : Array.from(els || []);
    if (!list.length) return;
    try {
      M.animate(list,
        { opacity: [0, 1], transform: ['translateY(14px) scale(.99)', 'translateY(0px) scale(1)'] },
        Object.assign({ delay: M.stagger(.05), duration: .5, ease: [.22, 1, .36, 1] }, extra || {}));
    } catch (err) {}
  }
  function mPop(el, from) {
    if (!M || !el) return;
    try { M.animate(el, { scale: [from || .95, 1] }, { type: M.spring, stiffness: 380, damping: 24 }); } catch (err) {}
  }
  function mCount(el, to, suffix) {
    if (!el) return;
    const fin = () => { el.textContent = to + (suffix || ''); };
    if (!M) { fin(); return; }
    try {
      M.animate(0, to, { duration: .8, ease: [.16, 1, .3, 1],
        onUpdate: v => { el.textContent = Math.round(v) + (suffix || ''); } }).finished.then(fin);
    } catch (err) { fin(); }
  }

  /* 결정적 파형 생성기 (매 로드 동일한 모양 → 결과 일관성) */
  function buildWave(el, n, base, amp, cls) {
    if (!el || el.childElementCount) return;
    for (let i = 0; i < n; i++) {
      const b = document.createElement('i');
      b.style.height = Math.round(base + Math.abs(Math.sin(i * .74) * Math.cos(i * .31)) * amp) + 'px';
      if (cls && cls(i)) b.classList.add(cls(i));
      el.appendChild(b);
    }
  }

  return { M, mIn, mPop, mCount, buildWave, reduceMotion };
})();
