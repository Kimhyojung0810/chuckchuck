/**
 * 발표 태도(베타) 카메라 특징 뽑기 — 프레임 한 장 → 숫자 한 줄. 워커(js/behavior_cv_worker.js)와 노드 벤치가 같이 쓴다.
 *
 * 고전 OpenCV 만 쓴다 (계획 §1-3 「구성 AI 100% 국내」 — 신경망 · MediaPipe · YuNet · Facemark 없음):
 *  - 얼굴: Haar 정면 캐스케이드 **alt2** + 옆얼굴 캐스케이드(좌우 뒤집어 양쪽). Haar 는 신경망이 아니라 AdaBoost 로 학습한 부스팅
 *    캐스케이드다(Viola-Jones 2001 · Lienhart 2002, OpenCV 동봉) — 「학습 모델이 아니다」 라고만 쓰면 반만 맞다 (근거조사 10-17 §4).
 *    default → alt2: 정답 실험실(etc/labs/behavior_cv, 10-17) 참조 엔진에서 방향 82.3% → 95.2%, 책장 · 포스터 헛얼굴 · 흐림 · 역광 · 깊은 숙임에 강했다.
 *    옆얼굴은 정면을 놓쳤을 때만, 지난 얼굴 둘레에서만 돈다 — 양쪽 전체면 한 장 82ms (근거조사 §2-7).
 *  - 검출용 평활은 전역 equalizeHist 가 아니라 **CLAHE(2.0, 4×4)** — 짙은 피부 + 단색 배경에서 전역 평활은 정면 검출 0% 였다 (실험실 아틀라스 검증)
 *  - 발표자 얼굴 고르기: 크기 × 가운데, 지난 얼굴 가까이만(먼 얼굴로 안 갈아탐), **꼼짝 않는 헛얼굴(포스터 · 책장) 거르기**,
 *    더 크고 살아 있는 얼굴이 1초 넘게 보이면 갈아타기
 *  - 검출이 끊긴 동안(옆모습 90° · 깊은 숙임): 얼굴색 CamShift 로 머리 자리를 잇는다(최대 6초) — 빼면 긴 이탈 재현율 .61 → .37 (실험실)
 *  - 눈: Haar 눈 캐스케이드(눈 띠를 키워서) — 보조 단서만. 안경 · 짙은 톤에서 거의 못 잡는다
 *  - 움직임 양: 160px 프레임 차분(MEA) · 전체 밝기 변화를 빼고 잡음 바닥 위만
 *  - 손짓: 160px Farneback 흐름에서 **몸통 가운데 흐름을 뺀** 상대 움직임 ∧ 피부(이 사람 얼굴색 역투영) ∧ 얼굴 · 목 밖 ∧ **오래 그 자리에 있는
 *    피부색(화분 · 나무 = 배경 피부) 빼기** ∧ 손 크기 덩어리(얼굴 넓이의 0.025~1.2) — 손 없는 영상의 손짓 오탐 13.6% → 0.7% (실험실 참조 엔진).
 *    바퀴 3: 열기 없앰 · 배경 피부 문턱 0.3 · 흐름 문턱을 처리 간격에 비례 · 어두운 방은 밝기 배율로 (손짓 재현율 .49 → 표는 계획 문서 「바퀴 3」)
 *  - 품질: 평균 밝기 · 얼굴 밝기(역광) · 라플라시안 분산(흐림) · 얼굴 크기 · 얼굴 수
 *  - 캐스케이드 없는 예비 모드(opts.mode = 'nocascade'): 가운데에서 시작 → 얼굴색 CamShift + 차분. 방향은 재지 않는다
 * 영상은 이 함수 밖으로 나가지 않는다 — 돌려주는 것은 숫자뿐이다. 순서가 있는 판단은 js/behavior_cv_logic.js 의 일이다.
 */
(function (root) {
  'use strict';

  const FX = {
    // ── 얼굴 찾기 ──
    scale: 1.1,           // detectMultiScale 배율 — 실험실 참조 엔진 값
    neighbors: 3,         // alt2 최소 이웃 수 (실험실 권고 1)
    profNeighbors: 4,     // 옆얼굴은 헛잡음이 더 많아서 한 단 높인다 (설계값 · 검증 전)
    minFaceFrac: 0.06,    // 화면 폭의 이 비율보다 작은 얼굴은 찾지 않는다 — 320px 에서 19px. 0.08 아래는 logic 이 「너무 멀어요」 로 게이트
    fullScanEvery: 5,     // 이 프레임마다 한 번은 화면 전체를 본다 — 나머지는 지난 얼굴 둘레만 (속도). 두 번째 사람 · 갈아타기를 1초 안에 안다
    roiPad: 0.9,          // 지난 얼굴 둘레 찾기 창 — 얼굴 폭의 이만큼씩 사방으로
    claheClip: 2.0,       // CLAHE — 실험실 권고 7
    // ── 고르기 ──
    keepMs: 2000,         // 지난 얼굴을 이만큼 안에 봤으면 그 가까이(1.6 얼굴 폭 · 크기 0.55~1.8배)에서만 고른다
    staticMs: 3000,       // 이만큼 넘게 중심이 얼굴 폭 1% 도 안 움직이고 · 상자 안 화소도 거의 안 바뀐 얼굴은 헛얼굴(포스터 · 책장) — 실험실 권고 2
    staticStd: 0.01,
    staticChange: 0.004,  // 상자 안 바뀐 점 비율 평균이 이 아래면 「살아 있지 않음」 (깜빡임 · 숨 · 센서 잡음 바닥 위, 설계값 · 검증 전)
    switchMs: 1000,       // 더 크고 살아 있는 얼굴이 이만큼 이어 보이면 갈아탄다
    // ── 이어 붙이기(CamShift) ──
    trackMaxMs: 6000,     // 검출이 끊겨도 이만큼은 얼굴색 CamShift 로 머리 자리를 잇는다 (실험실 참조 엔진 track_max_s)
    trackMass: 25,        // 역투영 창 안 평균이 이 아래면 잇지 않는다 (0~255)
    // ── 눈(보조) ──
    eyeTop: 0.12, eyeBottom: 0.58,
    eyeMinFrac: 0.14, eyeMaxFrac: 0.42,
    eyeFaceW: 150,        // 눈 찾기 전에 얼굴 폭을 이만큼(px)으로 키운다 — 눈이 학습 창 20px 를 넘게
    // ── 움직임 · 손짓 ──
    flowW: 160,           // 손짓 흐름 폭 — 실험실 참조 엔진(160×90 Farneback ≈ 4.6ms)
    gestFlow: 0.6,        // 몸통과 다르게 움직인 크기(160px 기준 화소/장) — 실험실 gest_flow
    gestFacePad: 0.6, gestNeck: 1.0,   // 얼굴 상자 좌우 0.6 · 아래 1.0 얼굴 폭(목 · 깃)은 손 자리에서 뺀다
    gestRefMs: 200, gestDtMin: 0.6, gestDtMax: 2.5,     // gestFlow 는 0.2초(5fps 한 장) 사이 기준 — 처리 간격에 비례해 늘린다(3fps 면 ×1.67)
    // 움직인 피부 마스크 다듬기 — 'none' | 'open'(3×3 열기, 바퀴 2). 열기는 160px 에서 손가락 · 흐린 손 가장자리를 다 지워 작은 얼굴(d7)
    // 손짓 재현율 .12 였다 → none (덩어리 크기 거르기만으로 손 없는 영상 오탐 0.5% 유지). 닫고 열기 · 넓혀 묶기는 잡음 영상(d4) 정밀도가 .64 로 떨어져 버렸다 (실험실 바퀴 3)
    gestMorph: 'none',
    // 피부 자리 지수 평균이 bgSkinOn 넘으면 배경 피부(화분 · 나무 · 분홍 벽)로 빼낸다. 0.6 → 0.3: 역투영이 문턱 언저리에서 깜빡이는 분홍 벽은
    // 평균이 0.4~0.6 에 머물러 배경으로 안 빠졌고, 어깨 가장자리 흐름과 겹쳐 손 없는 영상 손짓 오탐을 만들었다 (실험실 바퀴 3, s12 5.5% → 1.5%)
    bgSkinEma: 0.05, bgSkinOn: 0.3, bgWarm: 10,
    blobMin: 0.025, blobMax: 1.2,      // 손 크기 덩어리 = 얼굴 넓이의 0.025~1.2배 (0.04 → 0.025: 흐림 · 압축 · 작은 얼굴에서 손이 조각나 걸러졌다, 바퀴 3)
    darkMean: 38,         // 평균 밝기 이 아래면 어두운 방 — booth_cv 와 같은 값
    gestDark: 'gain', darkTarget: 100, darkGainMax: 4, darkFlowK: 1.5,   // 어두운 방 손짓: 'gain' = 밝기 배율로 끌어올려 재기(문턱 ×1.5) · 'off' = 재지 않음
    meaW: 160, meaNoise: 12,
    skinEvery: 15, skinBp: 40,
    // ── 예비 모드 ──
    mode: 'cascade',
    nocFace: [0.4, 0.14, 0.2, 0.27],
  };

  /** 피부색 대략 — YCrCb 경계 (Chai & Ngan 1999). 이 사람 얼굴색 히스토그램을 아직 못 떴을 때만 쓰는 예비 (피부색 치우침이 있다) */
  function isSkin(r, g, b) {
    const y = 0.299 * r + 0.587 * g + 0.114 * b;
    const cr = (r - y) * 0.713 + 128;
    const cb = (b - y) * 0.564 + 128;
    return cr >= 133 && cr <= 173 && cb >= 77 && cb <= 127;
  }

  const r3 = (v) => Math.round(v * 1000) / 1000;
  const r1 = (v) => Math.round(v * 10) / 10;
  const median = (a) => { if (!a.length) return 0; const s = a.slice().sort((p, q) => p - q); return s[s.length >> 1]; };

  function clampRect(x, y, w, h, W, H) {
    const x0 = Math.max(0, Math.floor(x));
    const y0 = Math.max(0, Math.floor(y));
    const x1 = Math.min(W, Math.ceil(x + w));
    const y1 = Math.min(H, Math.ceil(y + h));
    return { x: x0, y: y0, width: Math.max(0, x1 - x0), height: Math.max(0, y1 - y0) };
  }

  /**
   * cv: 다 뜬 OpenCV.js · files: { frontal, profile, eye } — cv.FS 에 이미 올린 캐스케이드 파일 이름 (eye · profile 은 없어도 된다)
   * 돌려주는 것: { process(frame) → row, reset(), dispose(), info }
   */
  function createExtractor(cv, files, opts = {}) {
    const cfg = { ...FX, ...(opts || {}) };
    const load = (name) => {
      if (!name) return null;
      const c = new cv.CascadeClassifier();
      if (!c.load(name)) { c.delete(); return null; }
      return c;
    };
    const noc = cfg.mode === 'nocascade';
    const frontal = noc ? null : load(files.frontal);
    if (!noc && !frontal) throw new Error('정면 얼굴 분류기를 읽지 못했어요');
    const profile = noc ? null : load(files.profile);
    const eye = noc ? null : load(files.eye);
    const clahe = new cv.CLAHE(cfg.claheClip, new cv.Size(4, 4));

    let M = null;
    let key = '';
    const st = {};
    function resetState() {
      Object.assign(st, {
        n: 0, last: null, lastSeenAt: -Infinity, lastAnyAt: -Infinity, spots: [], cand: null,
        trackOk: false, trackWin: null, skin: false, frontN: 0,
        prevFlow: false, prevFlowT: null, prevDark: false, prevMea: false, diff: null, skinEma: null, camLost: 0,
      });
    }
    resetState();

    function ensure(w, h) {
      const k = `${w}x${h}`;
      if (M && key === k) return M;
      freeMats();
      key = k;
      M = {
        gray: new cv.Mat(), eq: new cv.Mat(), flip: new cv.Mat(), lap: new cv.Mat(),
        small: new cv.Mat(), prev: new cv.Mat(), flow: new cv.Mat(), smallRgba: new cv.Mat(),
        mean: new cv.Mat(), std: new cv.Mat(), eyeBand: new cv.Mat(),
        mea: new cv.Mat(), meaPrev: new cv.Mat(), rgb: new cv.Mat(), hsv: new cv.Mat(), smallRgb: new cv.Mat(), smallHsv: new cv.Mat(),
        fullRgb: new cv.Mat(), fullHsv: new cv.Mat(), tmask: new cv.Mat(), lo: new cv.Mat(), hi: new cv.Mat(),
        hist: new cv.Mat(), thist: new cv.Mat(), bp: new cv.Mat(), bpFull: new cv.Mat(), none: new cv.Mat(),
        gmask: new cv.Mat(), labels: new cv.Mat(), stats: new cv.Mat(), cents: new cv.Mat(),
        kern: cv.getStructuringElement(cv.MORPH_RECT, new cv.Size(3, 3)),
        rects: new cv.RectVector(), nums: new cv.IntVector(), eyes: new cv.RectVector(),
        fw: cfg.flowW, fh: Math.max(1, Math.round((cfg.flowW * h) / w)),
        meaW: cfg.meaW, meaH: Math.max(1, Math.round((cfg.meaW * h) / w)),
      };
      st.prevFlow = false; st.prevMea = false; st.skin = false; st.trackOk = false; st.skinEma = null;
      return M;
    }

    function freeMats() {
      if (!M) return;
      Object.values(M).forEach((m) => { if (m && typeof m.delete === 'function') { try { m.delete(); } catch (_) { /* 이미 지움 */ } } });
      M = null;
    }

    /* ── 검출 ───────────────────────────────────────────────────────────── */

    function findFrontal(img, roi, minSide, maxSide) {
      const sub = roi ? img.roi(new cv.Rect(roi.x, roi.y, roi.width, roi.height)) : img;
      try {
        frontal.detectMultiScale2(sub, M.rects, M.nums, cfg.scale, cfg.neighbors, 0,
          new cv.Size(minSide, minSide), new cv.Size(maxSide, maxSide));
      } finally { if (roi) sub.delete(); }
      const out = [];
      for (let i = 0; i < M.rects.size(); i += 1) {
        const r = M.rects.get(i);
        out.push({ x: r.x + (roi ? roi.x : 0), y: r.y + (roi ? roi.y : 0), w: r.width, h: r.height, n: M.nums.get(i) || 0 });
      }
      return out;
    }

    /** 옆얼굴 — 그대로 한 번, 좌우 뒤집어 한 번. side: +1 코가 화면 왼쪽(캐스케이드 그대로) · -1 뒤집어 찾음 */
    function findProfile(img, roi, minSide, maxSide) {
      if (!profile) return null;
      const W = img.cols;
      const sub = img.roi(new cv.Rect(roi.x, roi.y, roi.width, roi.height));
      let best = null;
      try {
        const run = (mat, side) => {
          profile.detectMultiScale2(mat, M.rects, M.nums, cfg.scale, cfg.profNeighbors, 0,
            new cv.Size(minSide, minSide), new cv.Size(maxSide, maxSide));
          for (let i = 0; i < M.rects.size(); i += 1) {
            const r = M.rects.get(i);
            const n = M.nums.get(i) || 0;
            const x = side < 0 ? mat.cols - r.x - r.width : r.x;   // 뒤집은 좌표를 되돌린다
            const cand = { x: x + roi.x, y: r.y + roi.y, w: r.width, h: r.height, n, side };
            if (!best || cand.n > best.n || (cand.n === best.n && cand.w > best.w)) best = cand;
          }
        };
        run(sub, 1);
        cv.flip(sub, M.flip, 1);
        run(M.flip, -1);
      } finally { sub.delete(); }
      if (best && (best.x < 0 || best.x + best.w > W)) best = null;
      return best;
    }

    /* ── 발표자 고르기 ───────────────────────────────────────────────────── */

    /** 상자 안 바뀐 점 비율 (지난 프레임 차분, 160px) — 포스터 · 책장은 0 에 가깝다 */
    function changeIn(box, W, H) {
      if (!st.diff) return null;
      const sx = M.meaW / W; const sy = M.meaH / H;
      const r = clampRect(box.x * sx, box.y * sy, box.w * sx, box.h * sy, M.meaW, M.meaH);
      if (r.width < 2 || r.height < 2) return null;
      let k = 0;
      for (let y = r.y; y < r.y + r.height; y += 1) for (let x = r.x; x < r.x + r.width; x += 1) k += st.diff[y * M.meaW + x];
      return k / (r.width * r.height);
    }

    /** 최근 staticMs 넘게 거의 같은 자리 · 같은 크기에 있었고 안의 화소도 거의 안 바뀐 상자인가 */
    function isStatic(f, t) {
      const cx = f.x + f.w / 2; const cy = f.y + f.h / 2;
      const near = st.spots.filter((s) => Math.abs(s.cx - cx) < 0.5 * f.w && Math.abs(s.cy - cy) < 0.5 * f.w && Math.abs(s.w - f.w) < 0.3 * f.w);
      if (near.length < 10 || t - near[0].t < cfg.staticMs) return false;
      const sd = (k) => { const m = near.reduce((a, s) => a + s[k], 0) / near.length; return Math.sqrt(near.reduce((a, s) => a + (s[k] - m) ** 2, 0) / near.length); };
      if (Math.max(sd('cx'), sd('cy')) >= cfg.staticStd * f.w) return false;
      const ch = near.map((s) => s.ch).filter((v) => v !== null);
      return !ch.length || ch.reduce((a, b) => a + b, 0) / ch.length < cfg.staticChange;
    }

    function pick(faces, t, W, H, full) {
      faces.forEach((f) => { f.ch = changeIn(f, W, H); st.spots.push({ t, cx: f.x + f.w / 2, cy: f.y + f.h / 2, w: f.w, ch: f.ch }); });
      st.spots = st.spots.filter((s) => s.t > t - 6000);
      faces.forEach((f) => { f.dead = isStatic(f, t); });
      const live = faces.filter((f) => !f.dead);
      const prev = st.last && t - st.lastSeenAt < cfg.keepMs ? st.last : null;
      if (prev) {
        const lc = { x: prev.x + prev.w / 2, y: prev.y + prev.h / 2 };
        const dist = (f) => Math.hypot(f.x + f.w / 2 - lc.x, f.y + f.h / 2 - lc.y) / Math.max(1, prev.w);
        const near = live.filter((f) => dist(f) < 1.6 && f.w / prev.w > 0.55 && f.w / prev.w < 1.8).sort((a, b) => dist(a) - dist(b));
        // 갈아타기 — 전체를 본 장에서 지난 얼굴보다 1.2배 넘게 큰 · 살아 있는 · 먼 얼굴이 switchMs 넘게 이어 보이면
        const big = full ? live.filter((f) => dist(f) >= 1.6 && f.w > 1.2 * prev.w).sort((a, b) => b.w - a.w)[0] : null;
        if (big) {
          if (st.cand && Math.hypot(st.cand.x - big.x, st.cand.y - big.y) < 0.6 * big.w) {
            if (t - st.cand.since >= cfg.switchMs) { st.cand = null; return { face: big, switched: true }; }
          } else st.cand = { x: big.x, y: big.y, since: t };
        } else if (full) st.cand = null;
        // 지난 얼굴이 헛얼굴로 드러났으면 놓는다 — 다음 장부터 처음처럼 고른다
        const deadNear = faces.some((f) => f.dead && dist(f) < 0.5);
        if (deadNear && !near.length) { st.last = null; return { face: null, dropped: true }; }
        return { face: near[0] || null };
      }
      st.cand = null;
      if (!live.length) return { face: null };
      return { face: live.reduce((b, f) => (score(f, W) > score(b, W) ? f : b)) };
    }
    const score = (f, W) => f.w * (1.2 - Math.abs(f.x + f.w / 2 - W / 2) / W);

    /* ── 피부 · CamShift ─────────────────────────────────────────────────── */

    function hsvOf(src, rgbOut, hsvOut) {
      cv.cvtColor(src, rgbOut, cv.COLOR_RGBA2RGB);
      cv.cvtColor(rgbOut, hsvOut, cv.COLOR_RGB2HSV);
    }

    /** 이 사람 얼굴색 히스토그램(색상 30 × 채도 32) — 얼굴 상자 안쪽 아래(볼 · 코)에서. 손 피부 역투영용 */
    function updateSkinHist(rgba, box) {
      const r = clampRect(box.x + box.w * 0.25, box.y + box.h * 0.45, box.w * 0.5, box.h * 0.4, rgba.cols, rgba.rows);
      if (r.width < 4 || r.height < 4) return;
      const sub = rgba.roi(new cv.Rect(r.x, r.y, r.width, r.height));
      const vec = new cv.MatVector();
      try {
        hsvOf(sub, M.rgb, M.hsv);
        vec.push_back(M.hsv);
        cv.calcHist(vec, [0, 1], M.none, M.hist, [30, 32], [0, 180, 0, 256], false);
        cv.normalize(M.hist, M.hist, 0, 255, cv.NORM_MINMAX);
        st.skin = true;
      } finally { sub.delete(); vec.delete(); }
    }

    /** 머리 따라가기 히스토그램(색상 24 × 채도 16) — 얼굴 상자 전체, 채도 · 밝기 40 아래는 뺀다 (Bradski 1998) */
    function initTrack(rgba, box) {
      const r = clampRect(box.x, box.y, box.w, box.h, rgba.cols, rgba.rows);
      if (r.width < 4 || r.height < 4) return;
      const src = rgba.roi(new cv.Rect(r.x, r.y, r.width, r.height));
      hsvOf(src, M.rgb, M.hsv);
      src.delete();
      const sub = M.hsv;
      const lo = new cv.Mat(sub.rows, sub.cols, sub.type(), new cv.Scalar(0, 40, 40, 0));
      const hi = new cv.Mat(sub.rows, sub.cols, sub.type(), new cv.Scalar(180, 255, 255, 0));
      const vec = new cv.MatVector();
      try {
        cv.inRange(sub, lo, hi, M.tmask);
        vec.push_back(sub);
        cv.calcHist(vec, [0, 1], M.tmask, M.thist, [24, 16], [0, 180, 0, 256], false);
        cv.normalize(M.thist, M.thist, 0, 255, cv.NORM_MINMAX);
        st.trackOk = true;
        st.trackWin = { x: r.x, y: r.y, w: r.width, h: r.height };
      } finally { lo.delete(); hi.delete(); vec.delete(); }
    }

    /** CamShift 한 걸음 — 머리 자리(정사각 · 지난 얼굴 폭). 덩어리가 엷거나 크기가 어긋나면 null */
    function trackHead(rgba, lw) {
      if (!st.trackOk || !st.trackWin) return null;
      hsvOf(rgba, M.fullRgb, M.fullHsv);   // 머리를 따라갈 때만 화면 전체 HSV
      const vec = new cv.MatVector();
      let res;
      try {
        vec.push_back(M.fullHsv);
        cv.calcBackProject(vec, [0, 1], M.thist, M.bpFull, [0, 180, 0, 256], 1);
        const w0 = st.trackWin;
        res = cv.CamShift(M.bpFull, new cv.Rect(w0.x, w0.y, Math.max(4, w0.w), Math.max(4, w0.h)),
          new cv.TermCriteria(cv.TermCriteria_EPS | cv.TermCriteria_COUNT, 10, 1));
      } finally { vec.delete(); }
      const win = res && res[1];
      if (!win || win.width < 4 || win.height < 4) return null;
      const r = clampRect(win.x, win.y, win.width, win.height, M.bpFull.cols, M.bpFull.rows);
      const sub = M.bpFull.roi(new cv.Rect(r.x, r.y, r.width, r.height));
      const mass = cv.mean(sub)[0];
      sub.delete();
      if (mass < cfg.trackMass || !(win.width > 0.4 * lw && win.width < 2.5 * lw)) return null;
      st.trackWin = { x: r.x, y: r.y, w: r.width, h: r.height };
      const c = res[0].center;
      return { x: Math.round(c.x - lw / 2), y: Math.round(c.y - lw / 2), w: Math.round(lw), h: Math.round(lw) };
    }

    /* 예비 모드 — 가운데 시작 상자의 색으로 CamShift */
    function camshiftNoc(rgba) {
      const W = rgba.cols; const H = rgba.rows;
      const init = () => ({ x: Math.round(cfg.nocFace[0] * W), y: Math.round(cfg.nocFace[1] * H), w: Math.round(cfg.nocFace[2] * W), h: Math.round(cfg.nocFace[3] * H) });
      if (!st.trackOk) { initTrack(rgba, init()); updateSkinHist(rgba, init()); }
      const lw = cfg.nocFace[2] * W;
      const b = trackHead(rgba, lw);
      if (!b) { st.camLost += 1; if (st.camLost > 10) { st.trackOk = false; st.camLost = 0; } return null; }
      st.camLost = 0;
      return b;
    }

    /* ── 눈 · 흐림 · 밝기 ────────────────────────────────────────────────── */

    function findEyes(box) {
      if (!eye) return { n: 0 };
      const y0 = box.y + box.h * cfg.eyeTop;
      const r = clampRect(box.x, y0, box.w, box.h * (cfg.eyeBottom - cfg.eyeTop), M.gray.cols, M.gray.rows);
      if (r.width < 16 || r.height < 8) return { n: 0 };
      const k = Math.max(1, cfg.eyeFaceW / box.w);
      const sub = M.gray.roi(new cv.Rect(r.x, r.y, r.width, r.height));
      try {
        cv.resize(sub, M.eyeBand, new cv.Size(Math.round(r.width * k), Math.round(r.height * k)), 0, 0, cv.INTER_LINEAR);
      } finally { sub.delete(); }
      cv.equalizeHist(M.eyeBand, M.eyeBand);
      const fw = box.w * k;
      const minS = Math.max(20, Math.round(fw * cfg.eyeMinFrac));
      const maxS = Math.max(minS + 1, Math.round(fw * cfg.eyeMaxFrac));
      eye.detectMultiScale(M.eyeBand, M.eyes, 1.1, 3, 0, new cv.Size(minS, minS), new cv.Size(maxS, maxS));
      const mid = box.x + box.w / 2;
      let left = null; let right = null;
      for (let i = 0; i < M.eyes.size(); i += 1) {
        const e = M.eyes.get(i);
        const c = { x: r.x + (e.x + e.width / 2) / k, y: r.y + (e.y + e.height / 2) / k, s: e.width };
        if (c.x < mid) { if (!left || c.s > left.s) left = c; } else if (!right || c.s > right.s) right = c;
      }
      const n = (left ? 1 : 0) + (right ? 1 : 0);
      if (n < 2) return { n };
      const dx = right.x - left.x; const dy = right.y - left.y;
      return { n: 2, roll: (Math.atan2(dy, dx) * 180) / Math.PI, ey: ((left.y + right.y) / 2 - box.y) / box.h, ex: ((left.x + right.x) / 2 - box.x) / box.w - 0.5, sep: dx / box.w };
    }

    function blurOf(box) {
      const W = M.gray.cols; const H = M.gray.rows;
      const r = box ? clampRect(box.x, box.y, box.w, box.h, W, H) : clampRect(W * 0.25, H * 0.2, W * 0.5, H * 0.6, W, H);
      if (r.width < 8 || r.height < 8) return null;
      const sub = M.gray.roi(new cv.Rect(r.x, r.y, r.width, r.height));
      let fb;
      try {
        cv.Laplacian(sub, M.lap, cv.CV_16S, 1, 1, 0, cv.BORDER_DEFAULT);
        cv.meanStdDev(M.lap, M.mean, M.std);
        fb = cv.mean(sub)[0];
      } finally { sub.delete(); }
      const sd = M.std.data64F ? M.std.data64F[0] : 0;
      return { bl: sd * sd, fb };
    }

    /* ── 움직임 (MEA) · 손짓 (흐름) ──────────────────────────────────────── */

    /** 160px 차분 — 전체 밝기 변화를 빼고 잡음 바닥 위만. st.diff(0/1) 를 남겨 상자 안 바뀜 · 장면 바뀜을 본다 */
    function meaOf(face) {
      cv.resize(M.gray, M.mea, new cv.Size(M.meaW, M.meaH), 0, 0, cv.INTER_AREA);
      let out = null;
      if (st.prevMea) {
        const a = M.mea.data; const b = M.meaPrev.data; const n = a.length;
        let mean = 0;
        for (let i = 0; i < n; i += 1) mean += a[i] - b[i];
        mean /= n;
        if (!st.diff || st.diff.length !== n) st.diff = new Uint8Array(n);
        const W = M.meaW; const H = M.meaH;
        let all = 0; let body = 0; let bodyN = 0;
        const bx0 = face ? (face.x + face.w / 2 - 1.3 * face.w) * W : 0; const bx1 = face ? (face.x + face.w / 2 + 1.3 * face.w) * W : 0;
        const by0 = face ? (face.y + face.h * 1.15) * H : H;
        for (let y = 0; y < H; y += 1) {
          const inBodyRow = face && y >= by0;
          for (let x = 0; x < W; x += 1) {
            const i = y * W + x;
            const on = Math.abs(a[i] - b[i] - mean) > cfg.meaNoise ? 1 : 0;
            st.diff[i] = on;
            all += on;
            if (inBodyRow && x >= bx0 && x <= bx1) { bodyN += 1; body += on; }
          }
        }
        out = { all: all / n, body: bodyN >= 60 ? body / bodyN : null };
      } else st.diff = null;
      M.mea.copyTo(M.meaPrev);
      st.prevMea = true;
      return out;
    }

    /**
     * 손짓 점수 = 손 크기 덩어리의 「움직인 피부」 넓이 / 얼굴 넓이 (160px). 실험실 참조 엔진 v2 와 같은 순서:
     * 피부(얼굴색 역투영, 없으면 YCrCb) ∧ 몸통 가운데 흐름과 다르게 > gestFlow(처리 간격 비례) ∧ 얼굴 · 목 · 얼굴 위 밖 ∧ 배경 피부 아님 → 덩어리 크기.
     * 어두운 방(평균 밝기 < darkMean)은 흐름을 끄지 않고 밝기 배율을 올려 문턱 ×1.5 로 잰다 (d2 손짓 재현율 0 → 바퀴 3)
     * 몸 = 얼굴 아래 ±2.2 얼굴 폭 흐름 평균(얼굴 폭/초 환산은 logic)
     */
    function gestureOf(rgba, face, dark, t) {
      cv.resize(M.gray, M.small, new cv.Size(M.fw, M.fh), 0, 0, cv.INTER_AREA);
      // 어두운 방 — 흐름을 끄는 대신 밝기를 한 배율로 끌어올려(장마다 같은 규칙이라 깜빡이지 않는다) 재고, 잡음이 커진 만큼 문턱을 높인다
      const lowLight = dark && cfg.gestDark === 'gain';
      if (lowLight) {
        const mean = cv.mean(M.small)[0];
        cv.convertScaleAbs(M.small, M.small, Math.min(cfg.darkGainMax, cfg.darkTarget / Math.max(1, mean)), 0);
      }
      let out = null;
      if ((!dark || lowLight) && st.prevFlow && st.prevDark === lowLight) {
        cv.calcOpticalFlowFarneback(M.prev, M.small, M.flow, 0.5, 2, 9, 2, 5, 1.1, 0);
        const W = M.fw; const H = M.fh; const fl = M.flow.data32F;
        let all = 0;
        for (let i = 0; i < W * H; i += 1) all += Math.hypot(fl[2 * i], fl[2 * i + 1]);
        out = { all: all / (W * H), body: null, gs: null, skin: null };
        if (face) {
          cv.resize(rgba, M.smallRgba, new cv.Size(W, H), 0, 0, cv.INTER_AREA);
          let bp = null;
          if (st.skin) {
            hsvOf(M.smallRgba, M.smallRgb, M.smallHsv);
            const vec = new cv.MatVector();
            try { vec.push_back(M.smallHsv); cv.calcBackProject(vec, [0, 1], M.hist, M.bp, [0, 180, 0, 256], 1); } finally { vec.delete(); }
            bp = M.bp.data;
          }
          const px = M.smallRgba.data;
          const x = face.x * W; const y = face.y * H; const w = face.w * W; const h = face.h * H;
          const fwk = Math.max(4, w);
          // 몸 움직임 — 얼굴 아래 0.3 폭부터, 가운데 ±2.2 폭
          const by0 = Math.min(H - 1, Math.floor(y + h + 0.3 * fwk)); const bx0 = Math.max(0, Math.floor(x + w / 2 - 2.2 * fwk)); const bx1 = Math.min(W, Math.ceil(x + w / 2 + 2.2 * fwk));
          let bs = 0; let bn = 0;
          for (let yy = by0; yy < H; yy += 1) for (let xx = bx0; xx < bx1; xx += 1) { const i = yy * W + xx; bs += Math.hypot(fl[2 * i], fl[2 * i + 1]); bn += 1; }
          out.body = bn >= 20 ? bs / bn : null;
          // 몸통 가운데 흐름 (얼굴 아래 0.9 폭부터 ±0.9 폭)
          const ty0 = Math.min(H - 1, Math.floor(y + h + 0.9 * fwk)); const tx0 = Math.max(0, Math.floor(x + w / 2 - 0.9 * fwk)); const tx1 = Math.min(W, Math.ceil(x + w / 2 + 0.9 * fwk));
          const tdx = []; const tdy = [];
          for (let yy = ty0; yy < H; yy += 1) for (let xx = tx0; xx < tx1; xx += 1) { const i = yy * W + xx; tdx.push(fl[2 * i]); tdy.push(fl[2 * i + 1]); }
          const mx = median(tdx); const my = median(tdy);
          if (!st.skinEma || st.skinEma.length !== W * H) { st.skinEma = new Float32Array(W * H); st.emaN = 0; }
          st.emaN += 1;
          const m = new Uint8Array(W * H);
          const fx0 = x - cfg.gestFacePad * w; const fx1 = x + (1 + cfg.gestFacePad) * w; const neckY = y + h + cfg.gestNeck * fwk;
          // 흐름 문턱(장 사이 움직인 화소)을 처리 간격에 맞춘다 — 같은 손 빠르기면 3fps 에서 5/3 배 크게 움직인다 (기기 속도에 손짓 값이 흔들리지 않게)
          const dtK = Math.min(cfg.gestDtMax, Math.max(cfg.gestDtMin, (st.prevFlowT === null ? cfg.gestRefMs : t - st.prevFlowT) / cfg.gestRefMs));
          const thr = cfg.gestFlow * dtK * (lowLight ? cfg.darkFlowK : 1);
          let skinN = 0; let mvN = 0;
          for (let yy = 0; yy < H; yy += 1) {
            for (let xx = 0; xx < W; xx += 1) {
              const i = yy * W + xx;
              // 피부 = 얼굴색 역투영(없을 때만 YCrCb). YCrCb 를 합치면 손 없는 영상 오탐이 0.7% → 9.2% 로 늘었다 (실험실 r2b)
              const sk = bp ? bp[i] >= cfg.skinBp : isSkin(px[4 * i], px[4 * i + 1], px[4 * i + 2]);
              st.skinEma[i] = (1 - cfg.bgSkinEma) * st.skinEma[i] + cfg.bgSkinEma * (sk ? 1 : 0);
              if (!sk || st.skinEma[i] >= cfg.bgSkinOn) continue;           // 배경 피부(오래 그 자리 피부색)
              if (yy < y) continue;                                          // 얼굴 위
              if (yy < neckY && xx >= fx0 && xx <= fx1) continue;            // 얼굴 · 목
              skinN += 1;
              const dx = fl[2 * i] - mx; const dy = fl[2 * i + 1] - my;
              if (Math.hypot(dx, dy) <= thr) continue;
              m[i] = 1; mvN += 1;
            }
          }
          let gs = 0; let po = 0; let nb = 0;
          if (mvN) {
            M.gmask.delete();
            M.gmask = cv.matFromArray(H, W, cv.CV_8UC1, m);
            if (cfg.gestMorph === 'open') cv.morphologyEx(M.gmask, M.gmask, cv.MORPH_OPEN, M.kern);
            const n = cv.connectedComponentsWithStats(M.gmask, M.labels, M.stats, M.cents, 8, cv.CV_32S);
            const S = M.stats.data32S; const A = fwk * fwk;
            for (let k = 1; k < n; k += 1) {
              const area = S[k * 5 + 4];
              po += area;
              if (area >= cfg.blobMin * A && area <= cfg.blobMax * A) { gs += area; nb += 1; }
            }
            gs /= A;
          }
          // 배경 피부 평균이 아직 덜 찼으면(처음 bgWarm 장 ≈ 2초) 못 잼 — 시작하자마자 벽 · 옷의 피부색이 다 「움직인 피부」 로 셌다 (d2 · t3 첫 3초 오탐, 바퀴 3)
          out.gs = st.emaN > cfg.bgWarm ? gs : null;
          out.skin = skinN;
          if (cfg.debug) out.gd = [skinN, mvN, po, nb, Math.round(fwk * 10) / 10];   // 실험실용(node_engine --debug): 피부 · 움직인 피부 · 다듬은 뒤 · 덩어리 수 · 얼굴 폭
        }
      }
      M.small.copyTo(M.prev);
      st.prevFlow = true;
      st.prevFlowT = t;
      st.prevDark = lowLight;
      return out;
    }

    /* ── 한 장 ──────────────────────────────────────────────────────────── */

    function process(frame) {
      const t0 = Date.now();
      const { w, h } = frame;
      ensure(w, h);
      const data = frame.data instanceof Uint8ClampedArray ? frame.data : new Uint8ClampedArray(frame.data);
      const rgba = cv.matFromImageData({ data, width: w, height: h });
      try {
        cv.cvtColor(rgba, M.gray, cv.COLOR_RGBA2GRAY);
        const bright = cv.mean(M.gray)[0];
        st.n += 1;
        const t = Number(frame.t) || 0;
        const dark = bright < cfg.darkMean;
        if (noc) return processNoCascade(rgba, t, t0, bright, dark, w, h);
        clahe.apply(M.gray, M.eq);
        const minSide = Math.max(20, Math.round(w * cfg.minFaceFrac));
        const prev = st.last && t - st.lastSeenAt < cfg.keepMs ? st.last : null;
        const full = !prev || st.n % cfg.fullScanEvery === 1;
        let roi = null; let minS = minSide; let maxS = Math.min(w, h);
        if (!full) {
          const p = prev.w * cfg.roiPad;
          roi = clampRect(prev.x - p, prev.y - p, prev.w + 2 * p, prev.h + 2 * p, w, h);
          minS = Math.max(minSide, Math.round(prev.w * 0.6));
          maxS = Math.min(Math.min(roi.width, roi.height), Math.round(prev.w * 1.6));
          if (maxS <= minS) { roi = null; minS = minSide; maxS = Math.min(w, h); }
        } else if (prev) {
          // 얼굴을 잡고 있는 동안의 전체 보기는 갈아탈 후보 · 헛얼굴 확인용이라 지난 얼굴의 반 크기 넘는 것만 — 320px 전체 alt2 는 한 장 40~57ms 다 (노드 10-17)
          minS = Math.max(minSide, Math.round(prev.w * 0.5));
        }
        // 차분을 먼저 — 고르기가 상자 안 바뀜(살아 있음)을 본다. 몸 영역은 지난 얼굴 기준
        const lastBox = st.last ? { x: st.last.x / w, y: st.last.y / h, w: st.last.w / w, h: st.last.h / h } : null;
        const mea = meaOf(lastBox);
        const faces = findFrontal(M.eq, roi, minS, maxS);
        const picked = pick(faces, t, w, h, full);
        let face = picked.face;
        let src = ''; let side = 0; let fn = 0;
        if (face) { src = 'F'; fn = face.n; }
        const anchor = st.last && t - st.lastAnyAt < cfg.trackMaxMs ? st.last : null;
        if (!face && anchor && !picked.dropped && t - st.lastSeenAt < cfg.keepMs) {
          // 옆얼굴은 정면을 놓쳤을 때만 · 지난 얼굴 둘레에서만 (근거조사 §2-7)
          const pp = anchor.w * cfg.roiPad;
          const proi = clampRect(anchor.x - pp, anchor.y - pp, anchor.w + 2 * pp, anchor.h + 2 * pp, w, h);
          const pmin = Math.max(minSide, Math.round(anchor.w * 0.6));
          const pmax = Math.max(pmin + 1, Math.min(Math.min(proi.width, proi.height), Math.round(anchor.w * 1.6)));
          const p = proi.width > pmin && proi.height > pmin ? findProfile(M.eq, proi, pmin, pmax) : null;
          if (p) { face = p; src = 'P'; side = p.side; fn = p.n; }
        }
        if (!face && anchor && !picked.dropped && t - st.lastSeenAt < cfg.trackMaxMs) {
          const tb = trackHead(rgba, anchor.w);
          if (tb) { face = tb; src = 'T'; }
        }
        if (face) {
          if (src === 'F' || src === 'P') { st.lastSeenAt = t; }
          st.lastAnyAt = t;
          st.last = { x: face.x, y: face.y, w: face.w, h: face.h };
          if (src === 'F') {
            initTrack(rgba, face);
            if (!st.skin || ++st.frontN % cfg.skinEvery === 0) updateSkinHist(rgba, face);
          }
        } else if (!anchor || picked.dropped) {
          st.last = null;
        }
        const eyes = face && src === 'F' ? findEyes(face) : { n: 0 };
        const q = blurOf(face && src !== 'T' ? face : null);
        const box = face ? { x: face.x / w, y: face.y / h, w: face.w / w, h: face.h / h } : null;
        const g = gestureOf(rgba, box, dark, t);
        const row = {
          t: Math.round(t), src, side, fn, full: full ? 1 : 0,
          nf: full ? faces.length : -1,
          box: box ? [r3(box.x), r3(box.y), r3(box.w), r3(box.h)] : null,
          eyes: eyes.n, br: r1(bright), bl: q ? r1(q.bl) : null,
        };
        if (q && face && src !== 'T') row.fb = r1(q.fb);
        if (picked.switched) row.sw = 1;
        if (faces.some((f) => f.dead)) row.dead = faces.filter((f) => f.dead).length;
        if (eyes.n === 2) { row.roll = r1(eyes.roll); row.ey = r3(eyes.ey); row.ex = r3(eyes.ex); row.sep = r3(eyes.sep); }
        addMotion(row, mea, g);
        row.ms = Date.now() - t0;
        return row;
      } finally {
        rgba.delete();
      }
    }

    function addMotion(row, mea, g) {
      if (mea) { row.mea = r3(mea.all); if (mea.body !== null) row.meb = r3(mea.body); }
      if (g) {
        row.mv = r3(g.all);
        if (g.body !== null) row.body = r3(g.body);
        if (g.gs !== null) row.gs = r3(g.gs);
        if (g.gd) row.gd = g.gd;
      }
    }

    function processNoCascade(rgba, t, t0, bright, dark, w, h) {
      const face = camshiftNoc(rgba);
      const box = face ? { x: face.x / w, y: face.y / h, w: face.w / w, h: face.h / h } : null;
      const q = blurOf(face);
      const mea = meaOf(box);
      const g = gestureOf(rgba, box, dark, t);
      const row = { t: Math.round(t), src: face ? 'C' : '', side: 0, fn: 0, full: 0, nf: -1,
        box: box ? [r3(box.x), r3(box.y), r3(box.w), r3(box.h)] : null, eyes: 0, br: r1(bright), bl: q ? r1(q.bl) : null, mode: 'noc' };
      addMotion(row, mea, g);
      row.ms = Date.now() - t0;
      return row;
    }

    function reset() { resetState(); }

    function dispose() {
      freeMats();
      try { clahe.delete(); } catch (_) { /* 이미 지움 */ }
      [frontal, profile, eye].forEach((c) => { if (c) { try { c.delete(); } catch (_) { /* 이미 지움 */ } } });
    }

    return { process, reset, dispose, info: { mode: noc ? 'nocascade' : 'cascade', profile: !!profile, eye: !!eye }, cfg };
  }

  const api = { FX, createExtractor, isSkin };
  root.BehaviorCvFeatures = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof self !== 'undefined' ? self : (typeof window !== 'undefined' ? window : globalThis));
