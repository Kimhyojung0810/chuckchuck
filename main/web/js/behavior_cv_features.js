/**
 * 발표 태도(베타) 카메라 특징 뽑기 — 프레임 한 장 → 숫자 한 줄. 워커(js/behavior_cv_worker.js)와 노드 벤치가 같이 쓴다.
 *
 * 고전 OpenCV 만 쓴다 (계획 §1-3 「구성 AI 100% 국내」 — 학습 신경망 · MediaPipe · YuNet 없음):
 *  - 얼굴: Haar 정면 캐스케이드(Viola-Jones 2001, OpenCV 동봉) + 옆얼굴 캐스케이드(좌우 뒤집어 양쪽)
 *  - 눈: Haar 눈 캐스케이드 — 얼굴 상자 위쪽 안에서만. 두 눈 → 기울기(roll) · 얼굴 안 눈 높이(숙임 대용) · 눈 가운데 x(돌림 대용)
 *  - 검출이 끊긴 프레임: 마지막 얼굴 조각으로 템플릿 맞추기(정규화 상관)로 메운다 — 짧게만(TRACK_MAX_MS)
 *  - 움직임: 80px 로 줄인 흑백 두 장의 Farneback 광학 흐름(2003) — 몸(얼굴 아래) · 손 자리(좌우 · 몸 앞)로 나눠 잰다
 *  - 품질: 평균 밝기 · 라플라시안 분산(흐림) · 얼굴 크기 · 얼굴 수
 * 영상은 이 함수 밖으로 나가지 않는다 — 돌려주는 것은 숫자뿐이다.
 *
 * 순서가 있는 판단(평활 · 상태 · 구간 · 장별 집계)은 하지 않는다 — 그건 js/behavior_cv_logic.js(순수 함수)의 일이다.
 * 여기 문턱은 「검출이 됐다고 칠 최소 근거」 뿐이고, 각각 출처나 「설계값 · 검증 전」 을 적었다.
 */
(function (root) {
  'use strict';

  const FX = {
    // ── 얼굴 찾기 ──
    scale: 1.15,          // detectMultiScale 배율 — 1.1 보다 40% 빠르고 320px 에선 놓침이 거의 같았다 (노드 벤치 10-17, 설계값)
    neighbors: 3,         // 정면 얼굴 최소 이웃 수 — booth_cv 는 4. 3 은 덜 놓치는 대신 헛잡음이 늘어 logic 의 평활이 거른다 (설계값 · 검증 전)
    profNeighbors: 4,     // 옆얼굴은 헛잡음이 더 많아서 한 단 높인다 (설계값 · 검증 전)
    minFaceFrac: 0.08,    // 화면 폭의 이 비율보다 작은 얼굴은 찾지 않는다 — 320px 에서 26px (Haar 학습 창 24px 바로 위)
    fullScanEvery: 5,     // 이 프레임마다 한 번은 화면 전체를 본다 — 나머지는 지난 얼굴 둘레만 (속도). 두 번째 사람 · 자리 옮김을 1초 안에 안다
    roiPad: 0.9,          // 지난 얼굴 둘레 찾기 창 — 얼굴 폭의 이만큼씩 사방으로 넓힌다 (5fps 에서 고개를 빨리 돌려도 들어온다)
    // ── 이어 붙이기(템플릿) ──
    trackMaxMs: 2000,     // 검출이 끊겨도 이만큼은 템플릿으로 얼굴 자리를 잇는다 — 넘으면 「없음」. Haar 가 멀쩡한 정면도 몇 장씩 놓친다 (booth_cv 실측)
    trackMinCorr: 0.55,   // 정규화 상관이 이보다 낮으면 잇지 않는다 (설계값 · 검증 전)
    // ── 눈 ──
    eyeTop: 0.12, eyeBottom: 0.58,   // 얼굴 상자 세로 이 구간에서만 눈을 찾는다 — 콧구멍 · 입을 눈으로 잡지 않게
    eyeMinFrac: 0.14, eyeMaxFrac: 0.42, // 눈 상자 폭 = 얼굴 폭의 이 사이 (Haar 눈 캐스케이드 학습 비율 근처, 설계값)
    eyeFaceW: 150,        // 눈 찾기 전에 얼굴 폭을 이만큼(px)으로 키운다 — 눈이 학습 창 20px 를 넘게
    // ── 움직임 ──
    flowW: 80,            // 광학 흐름용 축소 폭 — 80x60 이면 Farneback 이 2ms 안팎
    moveThr: 0.8,         // 80px 기준 이 화소 이상 움직인 점만 「움직였다」로 센다 (센서 잡음 · 압축 잡음 위, 설계값 · 검증 전)
    darkMean: 38,         // 평균 밝기 이 아래면 흐름을 재지 않는다 — booth_cv 와 같은 값(어두운 방 센서 잡음이 움직임으로 보였다, 10-02)
  };

  /** 피부색 대략 — YCrCb 경계 (Chai & Ngan 1999, 「Face segmentation using skin-color map」). 손 자리의 움직임이 손인지 참고만 한다 */
  function isSkin(r, g, b) {
    const y = 0.299 * r + 0.587 * g + 0.114 * b;
    const cr = (r - y) * 0.713 + 128;
    const cb = (b - y) * 0.564 + 128;
    return cr >= 133 && cr <= 173 && cb >= 77 && cb <= 127;
  }

  const r3 = (v) => Math.round(v * 1000) / 1000;
  const r1 = (v) => Math.round(v * 10) / 10;

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
    const frontal = load(files.frontal);
    if (!frontal) throw new Error('정면 얼굴 분류기를 읽지 못했어요');
    const profile = load(files.profile);
    const eye = load(files.eye);

    let M = null;
    let key = '';
    const st = { n: 0, last: null, lastAt: -Infinity, tmpl: null, prevSmall: false };

    function ensure(w, h) {
      const k = `${w}x${h}`;
      if (M && key === k) return M;
      freeMats();
      key = k;
      const fh = Math.max(1, Math.round((cfg.flowW * h) / w));
      M = {
        gray: new cv.Mat(), eq: new cv.Mat(), flip: new cv.Mat(), lap: new cv.Mat(),
        small: new cv.Mat(), prev: new cv.Mat(), flow: new cv.Mat(), smallRgba: new cv.Mat(),
        mean: new cv.Mat(), std: new cv.Mat(), match: new cv.Mat(), eyeBand: new cv.Mat(), half: new cv.Mat(),
        rects: new cv.RectVector(), nums: new cv.IntVector(), eyes: new cv.RectVector(),
        fw: cfg.flowW, fh,
      };
      st.prevSmall = false;
      return M;
    }

    function freeMats() {
      if (!M) return;
      Object.values(M).forEach((m) => { if (m && typeof m.delete === 'function') { try { m.delete(); } catch (_) { /* 이미 지움 */ } } });
      M = null;
      if (st.tmpl) { try { st.tmpl.delete(); } catch (_) { /* 이미 지움 */ } st.tmpl = null; }
    }

    /** 정면 찾기 — 지난 얼굴 둘레(roi) 또는 전체. 돌려주는 상자는 전체 좌표 */
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

    /** 옆얼굴 — 그대로 한 번, 좌우 뒤집어 한 번. side: 이 캐스케이드가 찾는 방향 그대로면 +1, 뒤집어 찾았으면 -1 */
    function findProfile(img, roi, minSide, maxSide) {
      if (!profile) return null;
      const W = img.cols;
      const sub = roi ? img.roi(new cv.Rect(roi.x, roi.y, roi.width, roi.height)) : img;
      let best = null;
      try {
        const run = (mat, side) => {
          profile.detectMultiScale2(mat, M.rects, M.nums, cfg.scale, cfg.profNeighbors, 0,
            new cv.Size(minSide, minSide), new cv.Size(maxSide, maxSide));
          for (let i = 0; i < M.rects.size(); i += 1) {
            const r = M.rects.get(i);
            const n = M.nums.get(i) || 0;
            let x = r.x;
            if (side < 0) x = mat.cols - r.x - r.width;   // 뒤집은 좌표를 되돌린다
            const cand = { x: x + (roi ? roi.x : 0), y: r.y + (roi ? roi.y : 0), w: r.width, h: r.height, n, side };
            if (!best || cand.n > best.n || (cand.n === best.n && cand.w > best.w)) best = cand;
          }
        };
        run(sub, 1);
        cv.flip(sub, M.flip, 1);
        run(M.flip, -1);
      } finally { if (roi) sub.delete(); }
      if (best && (best.x < 0 || best.x + best.w > W)) best = null;
      return best;
    }

    /** 전체 화면 옆얼굴 찾기 — 반 크기에서 찾고 좌표만 되돌린다 */
    function findProfileHalf(minSide) {
      if (!profile) return null;
      cv.resize(M.eq, M.half, new cv.Size(Math.round(M.eq.cols / 2), Math.round(M.eq.rows / 2)), 0, 0, cv.INTER_AREA);
      const p = findProfile(M.half, null, Math.max(20, Math.round(minSide / 2)), Math.min(M.half.cols, M.half.rows));
      return p ? { ...p, x: p.x * 2, y: p.y * 2, w: p.w * 2, h: p.h * 2 } : null;
    }

    function keepTemplate(box) {
      const r = clampRect(box.x, box.y, box.w, box.h, M.eq.cols, M.eq.rows);
      if (r.width < 8 || r.height < 8) return;
      const view = M.eq.roi(new cv.Rect(r.x, r.y, r.width, r.height));
      if (st.tmpl) st.tmpl.delete();
      st.tmpl = view.clone();
      view.delete();
    }

    /** 템플릿으로 잇기 — 지난 상자 둘레에서 가장 닮은 자리. 상관이 낮으면 null */
    function track(prev) {
      if (!st.tmpl) return null;
      const tw = st.tmpl.cols; const th = st.tmpl.rows;
      const pad = Math.round(tw * 0.6);
      const area = clampRect(prev.x - pad, prev.y - pad, prev.w + 2 * pad, prev.h + 2 * pad, M.eq.cols, M.eq.rows);
      if (area.width <= tw || area.height <= th) return null;
      const sub = M.eq.roi(new cv.Rect(area.x, area.y, area.width, area.height));
      let res;
      try {
        cv.matchTemplate(sub, st.tmpl, M.match, cv.TM_CCOEFF_NORMED);
        res = cv.minMaxLoc(M.match);
      } finally { sub.delete(); }
      if (!res || !(res.maxVal >= cfg.trackMinCorr)) return { corr: res ? res.maxVal : 0, box: null };
      return { corr: res.maxVal, box: { x: area.x + res.maxLoc.x, y: area.y + res.maxLoc.y, w: tw, h: th } };
    }

    /**
     * 두 눈 — 얼굴 상자 위쪽에서. 왼쪽 반 · 오른쪽 반에 하나씩 있을 때만 「두 눈」.
     * 320px 화면의 얼굴은 폭 40~70px 라 눈이 10px 남짓이다 — Haar 눈 캐스케이드의 학습 창(20px)보다 작아 그대로는 못 잡는다
     * (노드 벤치 10-17: 모나리자 47px 얼굴에서 0/30). 그래서 눈 띠만 얼굴 폭 eyeFaceW 가 되게 키운 뒤 찾는다.
     */
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
      return {
        n: 2,
        roll: (Math.atan2(dy, dx) * 180) / Math.PI,                     // + 면 화면에서 오른쪽 눈이 낮다
        ey: ((left.y + right.y) / 2 - box.y) / box.h,                    // 얼굴 상자 안 눈 높이 (0 위 ~ 1 아래)
        ex: ((left.x + right.x) / 2 - box.x) / box.w - 0.5,              // 눈 가운데가 상자 가운데에서 비낀 정도 (-0.5~0.5)
        sep: dx / box.w,                                                 // 두 눈 사이 / 얼굴 폭 — 고개를 돌리면 줄어든다
      };
    }

    /** 흐림 — 라플라시안 분산 (Pech-Pacheco 2000). 얼굴이 있으면 얼굴 안, 없으면 화면 가운데 */
    function blurOf(box) {
      const W = M.gray.cols; const H = M.gray.rows;
      const r = box ? clampRect(box.x, box.y, box.w, box.h, W, H) : clampRect(W * 0.25, H * 0.2, W * 0.5, H * 0.6, W, H);
      if (r.width < 8 || r.height < 8) return null;
      const sub = M.gray.roi(new cv.Rect(r.x, r.y, r.width, r.height));
      try {
        cv.Laplacian(sub, M.lap, cv.CV_16S, 1, 1, 0, cv.BORDER_DEFAULT);
        cv.meanStdDev(M.lap, M.mean, M.std);
      } finally { sub.delete(); }
      const sd = M.std.data64F ? M.std.data64F[0] : 0;
      return sd * sd;
    }

    /**
     * 몸 · 손 자리 움직임 — Farneback 흐름(80px). 얼굴 상자(화면 비율)가 있으면 영역을 나눈다:
     *  몸 = 얼굴 아래, 얼굴 가운데 ±1.3 얼굴 폭 · 손 = 그 바깥 좌우(얼굴 높이부터 아래) + 몸 앞의 「몸과 따로 움직인」 점
     * 몸 전체가 흔들린 것(흔들림 · 카메라 흔들림)은 손짓으로 세지 않게 영역마다 가운데 흐름(중앙값)을 빼고 센다.
     */
    function motionOf(rgba, face, dark) {
      cv.resize(M.gray, M.small, new cv.Size(M.fw, M.fh), 0, 0, cv.INTER_AREA);
      cv.GaussianBlur(M.small, M.small, new cv.Size(3, 3), 0);
      let out = null;
      if (!dark && st.prevSmall) {
        cv.calcOpticalFlowFarneback(M.prev, M.small, M.flow, 0.5, 2, 9, 2, 5, 1.1, 0);
        cv.resize(rgba, M.smallRgba, new cv.Size(M.fw, M.fh), 0, 0, cv.INTER_AREA);
        out = splitFlow(M.flow.data32F, M.smallRgba.data, M.fw, M.fh, face);
      }
      M.small.copyTo(M.prev);
      st.prevSmall = true;
      return out;
    }

    function median(arr) {
      if (!arr.length) return 0;
      const a = arr.slice().sort((p, q) => p - q);
      return a[a.length >> 1];
    }

    function splitFlow(flow, px, W, H, face) {
      const thr = cfg.moveThr;
      let all = 0; let allN = 0;
      if (!face) {
        for (let i = 0; i < W * H; i += 1) { all += Math.hypot(flow[2 * i], flow[2 * i + 1]); allN += 1; }
        return { all: all / Math.max(1, allN), body: null, hl: null, hr: null, hf: null, skin: null };
      }
      const fx0 = face.x * W; const fy0 = face.y * H; const fw = face.w * W; const fh = face.h * H;
      const cx = fx0 + fw / 2;
      const colL = cx - 1.3 * fw; const colR = cx + 1.3 * fw;
      const bodyTop = fy0 + fh * 1.15;
      const fxa = fx0 - 0.25 * fw; const fxb = fx0 + 1.25 * fw; const fya = fy0 - 0.25 * fh; const fyb = fy0 + 1.25 * fh;
      const bodyDx = []; const bodyDy = []; const sideDx = []; const sideDy = [];
      const idxBody = []; const idxL = []; const idxR = [];
      for (let y = 0; y < H; y += 1) {
        for (let x = 0; x < W; x += 1) {
          const i = y * W + x;
          const dx = flow[2 * i]; const dy = flow[2 * i + 1];
          all += Math.hypot(dx, dy); allN += 1;
          if (x >= fxa && x <= fxb && y >= fya && y <= fyb) continue;   // 얼굴(조금 넓게)은 뺀다 — 고개 움직임은 손짓이 아니다
          if (x >= colL && x <= colR) {
            if (y >= bodyTop) { idxBody.push(i); bodyDx.push(dx); bodyDy.push(dy); }
          } else if (y >= fy0) {
            (x < colL ? idxL : idxR).push(i); sideDx.push(dx); sideDy.push(dy);
          }
        }
      }
      // 기준 흐름 = 몸(몸통) 가운데 흐름. 몸이 화면에 없으면 손 자리 가운데 흐름
      const bmx = bodyDx.length >= 20 ? median(bodyDx) : median(sideDx);
      const bmy = bodyDy.length >= 20 ? median(bodyDy) : median(sideDy);
      let body = 0;
      let skinMove = 0; let moveN = 0;
      /* 「손이 움직였다」 = 그 점이 움직였고(배경은 0) · 몸통과 다르게 움직였다(몸 흔들림 · 카메라 흔들림은 몸통과 같이 움직인다).
         둘 중 하나만 보면 흔들림이 손짓으로 셌다 — 몸통 중앙값만 빼면 정지한 배경이 「거꾸로 움직인 점」 이 됐고(노드 벤치 sway 0.30),
         크기만 보면 몸통 가장자리가 셌다 */
      const frac = (idx) => {
        if (!idx.length) return null;
        let k = 0;
        for (const i of idx) {
          const dx = flow[2 * i]; const dy = flow[2 * i + 1];
          if (Math.hypot(dx, dy) >= thr && Math.hypot(dx - bmx, dy - bmy) >= thr) {
            k += 1; moveN += 1;
            if (isSkin(px[4 * i], px[4 * i + 1], px[4 * i + 2])) skinMove += 1;
          }
        }
        return k / idx.length;
      };
      for (const i of idxBody) body += Math.hypot(flow[2 * i], flow[2 * i + 1]);
      const hf = frac(idxBody);
      const hl = frac(idxL);
      const hr = frac(idxR);
      return {
        all: all / Math.max(1, allN),
        body: idxBody.length >= 20 ? body / idxBody.length : null,   // 몸 영역이 화면에 거의 없으면(얼굴만 크게) 재지 않는다
        hl, hr, hf: idxBody.length >= 20 ? hf : null,
        skin: moveN >= 6 ? skinMove / moveN : null,
      };
    }

    /**
     * frame: { data: Uint8ClampedArray|ArrayBuffer (RGBA), w, h, t(ms) }
     * row: 숫자만 — logic 이 읽는 모양 (behavior_cv_logic.js ROW 설명)
     */
    function process(frame) {
      const t0 = Date.now();
      const { w, h } = frame;
      ensure(w, h);
      const data = frame.data instanceof Uint8ClampedArray ? frame.data : new Uint8ClampedArray(frame.data);
      const rgba = cv.matFromImageData({ data, width: w, height: h });
      try {
        cv.cvtColor(rgba, M.gray, cv.COLOR_RGBA2GRAY);
        const bright = cv.mean(M.gray)[0];
        cv.equalizeHist(M.gray, M.eq);
        st.n += 1;
        const t = Number(frame.t) || 0;
        const minSide = Math.max(24, Math.round(w * cfg.minFaceFrac));
        const prev = st.last && t - st.lastAt <= cfg.trackMaxMs ? st.last : null;
        const full = !prev || st.n % cfg.fullScanEvery === 1;
        let roi = null; let minS = minSide; let maxS = Math.min(w, h);
        if (!full) {
          const p = prev.w * cfg.roiPad;
          roi = clampRect(prev.x - p, prev.y - p, prev.w + 2 * p, prev.h + 2 * p, w, h);
          minS = Math.max(minSide, Math.round(prev.w * 0.6));
          maxS = Math.min(Math.min(roi.width, roi.height), Math.round(prev.w * 1.6));
          if (maxS <= minS) { roi = null; minS = minSide; maxS = Math.min(w, h); }
        }
        const faces = findFrontal(M.eq, roi, minS, maxS);
        // 얼굴이 여럿이면 지난 얼굴과 가장 가까운 것, 처음이면 가장 큰 것 (뒤로 지나가는 사람보다 발표자)
        let face = null;
        faces.forEach((f) => {
          if (!face) { face = f; return; }
          if (prev) {
            const d = (q) => Math.hypot(q.x + q.w / 2 - (prev.x + prev.w / 2), q.y + q.h / 2 - (prev.y + prev.h / 2));
            if (d(f) < d(face)) face = f;
          } else if (f.w * f.h > face.w * face.h) face = f;
        });
        let src = ''; let side = 0; let fn = 0; let corr = null;
        if (face) { src = 'F'; fn = face.n; }
        if (!face) {
          // 옆얼굴은 정면이 없을 때만 — 지난 얼굴 둘레면 그대로, 전체를 볼 때는 반 크기로 (전체 320px 두 번이면 110ms 였다, 노드 벤치 10-17)
          const p = roi ? findProfile(M.eq, roi, minS, maxS) : findProfileHalf(minSide);
          if (p) { face = p; src = 'P'; side = p.side; fn = p.n; }
        }
        if (!face && prev) {
          const tr = track(prev);
          if (tr) corr = tr.corr;
          if (tr && tr.box) { face = tr.box; src = 'T'; }
        }
        if (face && src !== 'T') keepTemplate(face);
        if (face) { st.last = face; if (src !== 'T') st.lastAt = t; } else { st.last = null; }
        const eyes = face && src !== 'P' ? findEyes(face) : { n: 0 };
        const blur = blurOf(face);
        const box = face ? { x: face.x / w, y: face.y / h, w: face.w / w, h: face.h / h } : null;
        const mv = motionOf(rgba, box, bright < cfg.darkMean);
        const row = {
          t: Math.round(t),
          src, side, fn, full: full ? 1 : 0,
          nf: full ? faces.length : -1,
          box: box ? [r3(box.x), r3(box.y), r3(box.w), r3(box.h)] : null,
          eyes: eyes.n,
          br: r1(bright),
          bl: blur === null ? null : r1(blur),
        };
        if (corr !== null) row.corr = r3(corr);
        if (eyes.n === 2) { row.roll = r1(eyes.roll); row.ey = r3(eyes.ey); row.ex = r3(eyes.ex); row.sep = r3(eyes.sep); }
        if (mv) {
          row.mv = r3(mv.all);
          if (mv.body !== null) row.body = r3(mv.body);
          if (mv.hl !== null) row.hl = r3(mv.hl);
          if (mv.hr !== null) row.hr = r3(mv.hr);
          if (mv.hf !== null) row.hf = r3(mv.hf);
          if (mv.skin !== null) row.skin = r3(mv.skin);
        }
        row.ms = Date.now() - t0;
        return row;
      } finally {
        rgba.delete();
      }
    }

    function reset() {
      st.n = 0; st.last = null; st.lastAt = -Infinity; st.prevSmall = false;
      if (st.tmpl) { st.tmpl.delete(); st.tmpl = null; }
    }

    function dispose() {
      freeMats();
      [frontal, profile, eye].forEach((c) => { if (c) { try { c.delete(); } catch (_) { /* 이미 지움 */ } } });
    }

    return { process, reset, dispose, info: { profile: !!profile, eye: !!eye }, cfg };
  }

  const api = { FX, createExtractor, isSkin };
  root.BehaviorCvFeatures = api;
  if (typeof module === 'object' && module.exports) module.exports = api;
})(typeof self !== 'undefined' ? self : (typeof window !== 'undefined' ? window : globalThis));
