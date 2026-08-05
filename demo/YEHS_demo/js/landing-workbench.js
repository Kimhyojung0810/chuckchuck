/*
랜딩 안의 인터랙티브 시연 구역입니다.
- judgeSec: 개념 판정 워크벤치 (레일 · 근거 · 판정 · 타임라인)
- demoSec: 다음 연습 도구 (레일 · 캔버스 · 인스펙터) + 리포트 탭 + Q&A + 업로드 시뮬
전부 인라인 상수로 동작하는 시연이며 DATA 나 bridge 를 읽지 않습니다.
*/
window.LandingWorkbench = (function () {
  'use strict';

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const { M, mIn, mPop, mCount, reduceMotion } = window.LandingMotion;

  /* 판정 코드 → 라벨. 판정 워크벤치와 연습 도구(개요 이미지)가 함께 쓴다. */
  const J_STATUS = { ok: '설명함', mid: '설명 부족', no: '누락', om: '정당한 생략', ct: '모순' };

  /* 원본은 assets/demo_recording.m4a 를 재생하지만 저장소에 그 파일이 없다.
     null 로 두면 아래 플레이어가 시뮬레이션 재생으로 떨어진다. */
  const demoAudio = null;

  /* 판정 워크벤치가 참조하는 개념 트리 — 랜딩 시연용 인라인 상수 */
  const TREE = [
    { id: 'root', label: '분명 잤는데 왜 피곤할까 — 수면의 질', root: true },
    { id: 'quality', label: '수면의 질 3요소', w: .96, slide: 'S04', st: 'mid', stName: '설명 부족 △', depth: 1,
      ev: '“여기서는 수면의 질을 시간, 연속성, 규칙성으로 나누어 볼 수 있습니다.” · 04:33',
      why: '발표의 중심 주장인데 세 요소의 이름만 읽고, 관계와 왜 답이 되는지는 설명하지 않았어요.' },
    { id: 'cycle', label: '수면 주기', w: .92, slide: 'S02', st: 'ok', stName: '설명함 O', depth: 1,
      ev: '“이 하나의 주기는 보통 약 90분에서 110분 정도로 설명이 됩니다.” · 02:37',
      why: '단계 구성 → 주기 반복 → 끊김의 영향까지 흐름대로 설명됐어요.' },
    { id: 'fix', label: '개선 방법', w: .84, slide: 'S07', st: 'ok', stName: '설명함 O', depth: 1,
      ev: '“앞에서 말한 세 가지 기준에 맞춰서 생각해 보면 됩니다.” · 06:07',
      why: '세 기준별 해결책이 예시와 함께 충분히 설명됐어요.' },
    { id: 'stages', label: '깊은 수면·REM 역할', w: .78, slide: 'S03', st: 'ok', stName: '설명함 O', depth: 2, parent: '수면 주기',
      ev: '“깊은 수면은 주로 신체적인 회복… 렘수면은 기억 정리나 감정 처리와 더 관련이 있습니다.” · 03:26',
      why: '역할 대비와 초반·후반 분포 경향까지 설명했어요.' },
    { id: 'rep45', label: '밤사이 4–5회 반복', w: .55, slide: 'S02', st: 'no', stName: '나오지 않음 X', depth: 2, parent: '수면 주기',
      ev: '관련 발화 없음 — “여러 번 반복됩니다”로만 말해 슬라이드의 수치가 빠졌어요.',
      why: '주기 개념을 수치로 완성하는 근거예요.' },
    { id: 'cont', label: '수면 연속성', w: .72, slide: 'S05', st: 'mid', stName: '설명 부족 △', depth: 2, parent: '수면의 질 3요소',
      ev: '“공통점은 수면의 연속성을 끊을 수 있다는 점입니다.” · 05:26',
      why: '원인 나열은 충분하지만 각 원인이 주기를 끊는 기전 설명이 없어요. Q&A에서는 정확히 보완됨.' },
    { id: 'jetlag', label: '사회적 시차', w: .66, slide: 'S06', st: 'mid', stName: '언급만 함 △', depth: 2, parent: '수면의 질 3요소',
      ev: '“이런 차이를 사회적 시차라고 부르기도 합니다.” · 05:51 — 용어·예시만 발화됨.',
      why: '생체리듬과 월요일 피로의 연결 설명이 없어요. Q&A 3회 상한 도달로 이해 부족 확정.' },
    { id: 'wake', label: '기상 시간 고정', w: .62, slide: 'S07', st: 'ok', stName: '설명함 O', depth: 2, parent: '개선 방법',
      ev: '“먼저 기상 시간을 일정하게 유지하는 것이 실천하기 쉽습니다.” · 06:47',
      why: '취침 고정 대비 실천 용이성이라는 이유까지 설명됐어요.' },
    { id: 'src', label: '출처·수치 표기', w: .3, slide: 'S08', st: 'om', stName: '정당한 생략', depth: 2, parent: '(보조)', aux: true,
      ev: '발화 없음 — 8분 교양 발표 맥락에서 구두 생략이 합리적이라 감점하지 않았어요.',
      why: '발표 맥락을 반영해 생략 허용.' }
  ];

  function initReportTabs() {
    /* ── ⑤-3 랜딩 리포트 탭 ──────────────────────────────────── */
    const REPORT_TABS = [
      { score: 82, title: '핵심은 이해했지만,<br>두 개념이 얕게 설명됐어요.', desc: '핵심 개념 12개 중 9개 설명, 2개 설명 부족, 1개 정당한 생략',
        rows: [
          ['네트워크 효과의 원리를 한 문장 더', '‘효과가 있다’는 결과만 말했어요. 사용자 증가 → 데이터 축적 → 정확도 향상의 인과를 설명해보세요.', '02:18', ''],
          ['이탈률 근거를 결론 앞에 복원하기', '월 이탈률 3.2%는 수익성 결론의 핵심 근거인데 발표에서 빠졌어요.', '04:41', ''],
          ['부록 설문 문항은 정당한 생략', '10분 발표 범위와 제한 시간을 고려하면 생략해도 흐름에 문제가 없어요.', '—', 'positive']
        ] },
      { score: 76, title: '결론은 분명하지만,<br>근거 하나를 건너뛰었어요.', desc: '슬라이드 4에서 네트워크 효과를 언급한 뒤 수익성 결론으로 곧바로 이동했어요.',
        rows: [
          ['근거 없는 결론 점프', '이탈률 데이터 없이 ‘그래서 수익성이 있다’는 결론으로 이동했어요.', '02:42', ''],
          ['슬라이드 5 재방문 구간 정리', '앞 슬라이드로 돌아간 설명이 길어 핵심 흐름이 한 번 끊겼어요.', '04:10', ''],
          ['마지막 요약은 명확해요', '‘매달 다시 선택받는 서비스’라는 결론이 도입의 문제 제기와 잘 연결됩니다.', '07:58', 'positive']
        ] },
      { score: 88, title: '전체 시간은 적절하지만,<br>핵심 구간이 너무 빨랐어요.', desc: '네트워크 효과와 임계 규모 구간에서 권장 시간보다 41초 짧게 발표했어요.',
        rows: [
          ['핵심 구간에 41초 더 배정', '네트워크 효과와 임계 규모는 전체 발표의 핵심이지만 가장 빠르게 지나갔어요.', '02:05', ''],
          ['도입을 18초 줄이기', '문제 제기 문장이 반복됩니다. 한 문장을 덜어 핵심 설명 시간을 확보하세요.', '00:36', ''],
          ['결론 속도는 안정적이에요', '분당 305자로 청중이 따라가기 좋은 속도입니다.', '07:41', 'positive']
        ] }
    ];
    function renderReportTab(idx) {
      const d = REPORT_TABS[idx];
      mCount($('#rbScore'), d.score);
      $('#rbTitle').innerHTML = d.title;
      $('#rbDesc').textContent = d.desc;
      $('#rbBar').style.width = d.score + '%';
      $('#rbList').innerHTML = d.rows.map((r, i) =>
        `<button class="priority-row ${r[3]}"><span class="priority-num">0${i + 1}</span><div><b>${r[0]}</b><p>${r[1]}</p></div><span class="time-chip">${r[2]}</span></button>`).join('');
      mIn($$('#rbList .priority-row'), M ? { delay: M.stagger(.06) } : null);
    }
    if ($('#rbList')) renderReportTab(0);
    const rtEl = $('#reportTabs');
    if (rtEl) rtEl.addEventListener('click', e => {
      const btn = e.target.closest('button'); if (!btn) return;
      const idx = $$('#reportTabs button').indexOf(btn);
      $$('#reportTabs button').forEach((b, i) => { b.classList.toggle('active', i === idx); b.setAttribute('aria-selected', String(i === idx)); });
      renderReportTab(idx);
    });
  }

  function initQaDemo() {
    /* ── ⑤-5 랜딩 Q&A: 가상 청중 + 소크라테스식 3단계 힌트 ───── */
    const AUDIENCES = [
      { name: '교수님',   q: '수면의 질 세 요소가 서로 어떻게 영향을 주는지 설명해볼까요?' },
      { name: '심사위원', q: '수면 시간이 아니라 질이 문제라는 주장의 근거 데이터는 무엇인가요?' },
      { name: '회사 상사', q: '이 내용을 팀의 컨디션 관리에 적용한다면 무엇부터 바꾸겠어요?' },
      { name: '일반 청중', q: '사회적 시차를 일상 경험으로 쉽게 설명해줄 수 있나요?' }
    ];
    const HINTS = [
      '평일과 주말의 기상 시간 차이를 먼저 숫자로 만들어보세요.',
      '몸의 시계는 주말에도 평일 리듬을 기억해요 — 시차가 있는 여행과 비슷한 상태가 됩니다.',
      '5시간 늦게 자고 일어나는 주말은 몸에게는 해외여행과 같아요 — 월요일 아침은 귀국 첫날인 셈이죠.'
    ];
    let lqHint = 0;
    const alEl = $('#audienceList');
    if (alEl) alEl.addEventListener('click', e => {
      const btn = e.target.closest('button'); if (!btn) return;
      const idx = $$('#audienceList button').indexOf(btn);
      $$('#audienceList button').forEach((b, i) => b.classList.toggle('active', i === idx));
      $('#lqAud').textContent = AUDIENCES[idx].name;
      $('#lqQuestion').textContent = AUDIENCES[idx].q;
      lqHint = 0; $('#lqHintBox').innerHTML = '';
      $('#lqHintLabel').textContent = '막혔나요?';
      $('#lqHintBtn').textContent = '힌트 한 단계 보기';
    });
    const lqBtn = $('#lqHintBtn');
    if (lqBtn) lqBtn.addEventListener('click', () => {
      if (lqHint >= 3) {           /* 힌트 닫기 */
        lqHint = 0; $('#lqHintBox').innerHTML = '';
        $('#lqHintLabel').textContent = '막혔나요?';
        $('#lqHintBtn').textContent = '힌트 한 단계 보기';
        return;
      }
      lqHint++;
      $('#lqHintBox').innerHTML =
        `<div class="hint-card level-${lqHint}"><span>힌트 ${lqHint}/3</span><p>${HINTS[lqHint - 1]}</p></div>`;
      $('#lqHintLabel').textContent = lqHint < 3 ? '한 단계 더 구체적으로 볼까요?' : '이제 다시 답해보세요.';
      $('#lqHintBtn').textContent = lqHint < 3 ? '힌트 한 단계 보기' : '힌트 닫기';
    });
  }

  function initStartUpload() {
    /* ── ⑤-7 시작하기 업로드 3단계 시뮬레이션 ────────────────── */
    const uploadCard = $('#uploadCard');
    let uploadTimer = null;
    function uploadStage(stage) {
      const steps = $$('.upload-steps span', uploadCard);
      steps.forEach((s, i) => s.classList.toggle('active', i <= stage));
    }
    $('#uploadStart').addEventListener('click', () => {
      uploadStage(1);
      $('.upload-drop', uploadCard).outerHTML = `
        <div class="upload-progress">
          <div class="upload-file"><span class="file-icon">P</span><div><b>수면의질_왜피곤할까.pptx</b><small>실제 데모 · 14.4 MB · 8 slides</small></div><em>완료</em></div>
          <h3 id="upMsg">업로드하고 있어요</h3>
          <p id="upSub">파일을 안전한 분석 공간으로 옮기는 중입니다.</p>
          <span class="progress-track"><i></i></span>
          <button type="button" id="uploadFinish">분석 완료 보기</button>
        </div>`;
      const msgs = [
        ['핵심 개념을 읽고 있어요', '텍스트, 표, 도식의 관계를 분석합니다.'],
        ['개념 트리를 만들고 있어요', '중요도 순서로 부모-자식 관계를 정리합니다.'],
        ['예상 질문을 준비하고 있어요', '자료 근거 문장에서 질문을 만듭니다.']
      ];
      let m = 0;
      uploadTimer = setInterval(() => {
        if (m < msgs.length) { $('#upMsg').textContent = msgs[m][0]; $('#upSub').textContent = msgs[m][1]; m++; }
        else clearInterval(uploadTimer);
      }, 1400);
      $('#uploadFinish').addEventListener('click', () => {
        clearInterval(uploadTimer);
        uploadStage(2);
        $('.upload-progress', uploadCard).outerHTML = `
          <div class="upload-done">
            <div class="done-check">✓</div>
            <h3>자료 분석을 마쳤어요</h3>
            <p>핵심 개념 10개와 예상 질문 후보 6개를 찾았습니다.</p>
            <a href="#/practice">발표 연습으로 이어가기 ${arrowSvg}</a>
          </div>`;
      });
    });
  }

  function initJudgeBench() {
    /* ═══ ⑭ S04 개념 판정 워크벤치 — rail · evidence · judgement · timeline ═══ */
    const JUDGE = {
      quality: {
        bullets: ['수면의 질 = 시간 × 연속성 × 규칙성', '얼마나 잤는가 · 끊기지 않았는가 · 언제 잤는가', '이 슬라이드가 발표 전체의 중심 주장'],
        ev: [
          { t: '여기서는 수면의 질을 시간, 연속성, 규칙성으로 나누어 볼 수 있습니다', time: '04:33', pick: true },
          { t: '즉 침대에 오래 누워 있었다고 해서 실제로 회복한 시간이 반드시 같은 것은 아닙니다', time: '04:52' },
          { t: '그래서 수면의 질을 볼 때는 이 세 가지를 함께 생각해야 합니다', time: '04:58', warn: true }
        ],
        check: { 정의: true, 원리: false, 관계: false, 이유: false }, conf: 84,
        why: '세 요소의 이름과 정의는 읽었지만, 요소들이 어떻게 함께 작동하는지·왜 1번 질문의 답이 되는지는 설명하지 않았어요. 중심 주장인데 발화 39초로 압축됐어요.',
        fix: '“세 가지 중 하나만 무너져도 회복감은 떨어집니다 — 예를 들어 7시간을 자도 중간에 세 번 깨면, 시간은 채웠지만 연속성이 무너진 밤입니다.”' },
      cycle: {
        bullets: ['얕은 수면 → 깊은 수면 → REM 반복', '한 주기 약 90–110분', '중간 각성은 주기를 끊는다'],
        ev: [
          { t: '이 하나의 주기는 보통 약 90분에서 110분 정도로 설명이 됩니다', time: '02:37', pick: true },
          { t: '중간에 자주 깨면 수면 주기가 끊기고 깊은 수면이나 렘수면까지 충분히 이어지지 못할 수도 있는 것이죠', time: '03:05' }
        ],
        check: { 정의: true, 원리: true, 관계: true, 이유: true }, conf: 93,
        why: '단계 구성과 주기 길이, 끊김의 결과까지 자료 흐름 그대로 설명됐어요.',
        fix: '유지하세요 — 이 구간의 설명 밀도가 발표의 기준점이에요.' },
      fix: {
        bullets: ['시간 부족 → 필요한 수면 시간 확보', '연속성 저하 → 카페인·음주·빛·소음 줄이기', '규칙성 저하 → 일정한 기상 시간'],
        ev: [
          { t: '앞에서 말한 세 가지 기준에 맞춰서 생각해 보면 됩니다', time: '06:07', pick: true },
          { t: '자기 전에는 강한 조명과 스마트폰 자극을 줄이고 침실을 어둡고 조용하게 유지하는 것이 도움이 됩니다', time: '06:55' }
        ],
        check: { 정의: true, 원리: true, 관계: true, 이유: false }, conf: 88,
        why: '해결책은 충분했지만, S04를 짧게 말한 탓에 “세 가지 기준”의 근거 회수가 약하게 들려요.',
        fix: '“지금 말씀드린 해결책은 아까 4번 슬라이드의 세 문제 — 시간·연속성·규칙성 — 에 하나씩 대응합니다”를 명시적으로 발화하세요.' },
      stages: {
        bullets: ['깊은 수면 = 신체 회복 · 피로 회복', 'REM = 기억 정리 · 감정 처리', '초반은 깊은 수면, 후반은 REM 경향'],
        ev: [
          { t: '깊은 수면은 주로 신체적인 회복과 관련이 있습니다', time: '03:26', pick: true },
          { t: '렘수면은 기억 정리나 감정 처리와 더 관련이 있습니다', time: '03:40' },
          { t: '깊은 수면은 수면 초반에 상대적으로 많고, 렘수면은 아침에 가까워질수록 길어지는 경향이 있습니다', time: '04:05' }
        ],
        check: { 정의: true, 원리: true, 관계: true, 이유: true }, conf: 91,
        why: '두 단계의 역할 대비와 시간대 분포까지 정확히 설명됐어요.',
        fix: '유지하세요.' },
      rep45: {
        bullets: ['밤사이 4–5회 정도 반복 (슬라이드 02)', '주기 반복 횟수는 연속성 판단의 기준'],
        ev: [{ t: '관련 발화 없음 — “밤사이에는 이런 주기가 여러 번 반복됩니다”로만 발화', time: '02:52', none: true, pick: true }],
        check: { 정의: false, 원리: false, 관계: false, 이유: false }, conf: 90,
        why: '슬라이드의 “4–5회” 수치가 발화에 등장하지 않았어요 — “여러 번”으로 뭉개졌어요.',
        fix: '“하룻밤에 보통 4–5번 반복됩니다 — 그래서 한 번의 각성이 전체의 20%를 무너뜨릴 수 있어요.”' },
      cont: {
        bullets: ['카페인 · 음주 · 스트레스 · 빛·소음·온도', '공통점: 수면 주기를 끊는다'],
        ev: [
          { t: '공통점은 수면의 연속성을 끊을 수 있다는 점입니다', time: '05:26', pick: true },
          { t: '늦은 시간에 마신 카페인, 음주, 스트레스, 그리고 침실의 빛이나 소음, 높은 온도 같은 환경 요인이 대표적입니다', time: '05:12', warn: true }
        ],
        check: { 정의: true, 원리: false, 관계: true, 이유: false }, conf: 81,
        why: '원인 나열은 충분하지만 각 원인이 어떤 기전으로 주기를 끊는지는 설명하지 않았어요.',
        fix: '“예를 들어 카페인은 몸에서 절반이 빠지는 데 5~6시간이 걸려서, 오후 늦게 마신 한 잔이 새벽 각성으로 이어질 수 있습니다.”' },
      jetlag: {
        bullets: ['평일 07:00 기상 ↔ 주말 12:00 기상', '사회적 시차 = 평일·주말 수면 시간대 차이로 생기는 리듬 차이'],
        ev: [
          { t: '이런 차이를 사회적 시차라고 부르기도 합니다', time: '05:51', pick: true },
          { t: '그래서 주말에는 오래 자더라도 월요일에 다시 피곤해질 수도 있는 것이죠', time: '05:57', warn: true }
        ],
        check: { 정의: true, 원리: false, 관계: false, 이유: false }, conf: 83,
        why: '용어와 결과는 말했지만 생체리듬이 왜 어긋나는지, 그것이 왜 월요일 피로로 이어지는지 기전이 빠졌어요. Q&A에서도 3회 상한으로 이해 부족이 확정됐어요.',
        fix: '“주말의 5시간 차이는 몸에게는 시차 5시간짜리 해외여행과 같습니다 — 월요일 아침은 귀국 첫날인 셈이에요.”' },
      wake: {
        bullets: ['일정한 기상 시간 유지', '취침 고정보다 실천이 쉽다'],
        ev: [{ t: '그래서 먼저 기상 시간을 일정하게 유지하는 것이 실천하기 쉽습니다', time: '06:47', pick: true }],
        check: { 정의: true, 원리: true, 관계: true, 이유: true }, conf: 87,
        why: '취침 시간 고정의 어려움 → 기상 시간 고정이라는 대안 논리가 명확했어요.',
        fix: '유지하세요.' },
      src: {
        bullets: ['NIH · CDC · Sleep Foundation 출처 표기 (슬라이드 하단)'],
        ev: [{ t: '발화 없음 — 맥락상 생략 허용', time: '—', none: true, pick: true }],
        check: { 정의: false, 원리: false, 관계: false, 이유: true }, conf: 92,
        why: '8분 교양 발표에서 출처의 구두 낭독은 생략이 합리적이에요 — 감점하지 않았어요.',
        fix: 'Q&A에서 “근거가 뭐죠?”가 나오면 슬라이드 하단 출처를 짚어주세요.' }
    };
    let jSel = 'quality', jFilter = 'all';

    function renderJudgeRail() {
      const rail = $('#judgeRail'); if (!rail) return;
      const items = TREE.filter(n => !n.root && (jFilter === 'all' || n.st === jFilter));
      rail.innerHTML = items.map(n => `
        <button class="jnode ${n.id === jSel ? 'sel' : ''} ${n.depth === 2 ? 'child' : ''}" data-j="${n.id}">
          <span class="dot ${n.st}"></span>
          <span class="jl"><b>${n.label}</b><small>${n.slide} · ${n.stName}</small></span>
        </button>`).join('') || '<p class="jempty">이 상태의 개념이 없어요.</p>';
      $$('#judgeRail [data-j]').forEach(btn => btn.addEventListener('click', () => { jSel = btn.dataset.j; renderJudgeAll(); }));
    }
    function renderJudgeCanvas(pick, anim) {
      const n = TREE.find(t => t.id === jSel), d = JUDGE[jSel];
      $('#judgeCanvas').innerHTML = `
        <div class="jslide">
          <div class="jslide-top"><span>발표자료 원문</span><b>SLIDE ${n.slide.slice(1)} / 09</b></div>
          <h3>${n.label}</h3>
          <ul>${d.bullets.map(x => `<li>${x}</li>`).join('')}</ul>
        </div>
        <div class="jev-head"><b>근거 발화</b><span>문장 의미 유사도 상위 ${d.ev.length}개 — 눌러서 판정 근거로 선택</span></div>
        <div class="jev-list">${d.ev.map((e, i) => `
          <button class="jev ${e.none ? 'none' : ''} ${e.warn ? 'warn' : ''} ${i === pick ? 'pick' : ''}" data-e="${i}">
            <time>${e.time}</time><span>${e.none ? e.t : '“' + e.t + '”'}</span>
          </button>`).join('')}</div>`;
      if (anim) mIn($$('#judgeCanvas .jslide, #judgeCanvas .jev-head, #judgeCanvas .jev'), M ? { delay: M.stagger(.04) } : null);
      $$('#judgeCanvas [data-e]').forEach(btn => btn.addEventListener('click', () => {
        renderJudgeCanvas(Number(btn.dataset.e)); renderJudgeInspector(Number(btn.dataset.e));
      }));
    }
    function renderJudgeInspector(pick, anim) {
      const n = TREE.find(t => t.id === jSel), d = JUDGE[jSel];
      const e = d.ev[pick] || d.ev[0];
      $('#judgeInspector').innerHTML = `
        <small class="ins-title">판정 및 보완</small>
        <div class="jstatus st-${n.st}">${n.stName}</div>
        <div class="jconf"><span>판정 confidence</span><div class="jconf-bar"><i style="width:${d.conf}%"></i></div><b>${d.conf}%</b></div>
        <div class="jcheck">
          ${Object.entries(d.check).map(([k, v]) => `
            <span class="${v ? 'y' : 'n'}"><svg viewBox="0 0 20 20"><use href="#${v ? 'icCheck' : 'icX'}"/></svg>${k}</span>`).join('')}
        </div>
        <p class="jwhy"><b>판정 근거</b> — ${d.why}</p>
        <p class="jpick"><b>선택한 발화</b> — ${e.none ? e.t : '“' + e.t + '” · ' + e.time}</p>
        <div class="jfix"><b>보완 문장</b><p>${d.fix}</p></div>
        ${jSel === 'cont' ? '<div class="jqa"><b>Q&A에서 보완</b><p>Q&A에서는 “각성 시 주기가 재시작되어 깊은 단계에 도달하지 못한다”로 정확히 설명했어요 — 이 답변을 S05 발화에 15초 분량으로 통합해보세요.</p></div>' : ''}
        <a class="jgo" href="#/qa">이 개념으로 질문 연습 →</a>`;
      if (anim) mIn($$('#judgeInspector > *'), M ? { delay: M.stagger(.035, { startDelay: .06 }), duration: .4 } : null);
    }
    function renderJudgeTimeline() {
      const segs = [['S01', 29, ''], ['S02', 12, ''], ['S03', 13, ''], ['S04', 8, ''], ['S05', 6, ''], ['S06', 6, ''], ['S07', 19, ''], ['S08', 7, '']];
      const n = TREE.find(t => t.id === jSel);
      $('#judgeTimeline').innerHTML = segs.map(s => {
        const cur = s[0].startsWith('S0' + n.slide.slice(2)) && !s[2];
        return `<span class="${s[2]} ${cur ? 'cur st-' + n.st : ''}" style="flex:${s[1]}"><i>${s[0]}</i></span>`;
      }).join('');
    }
    let jLast = null;
    function renderJudgeAll() {
      const anim = jLast !== null && jLast !== jSel; jLast = jSel;
      renderJudgeRail();
      renderJudgeCanvas(JUDGE[jSel].ev.findIndex(e => e.pick), anim);
      renderJudgeInspector(JUDGE[jSel].ev.findIndex(e => e.pick), anim);
      renderJudgeTimeline();
    }
    if ($('#judgeRail')) {
      renderJudgeAll();
      $('#judgeFilter').addEventListener('click', e => {
        const btn = e.target.closest('button'); if (!btn) return;
        $$('#judgeFilter button').forEach(b => b.classList.toggle('active', b === btn));
        jFilter = btn.dataset.f;
        const vis = TREE.filter(n => !n.root && (jFilter === 'all' || n.st === jFilter));
        if (vis.length && !vis.some(v => v.id === jSel)) jSel = vis[0].id;
        renderJudgeAll();
      });
    }
  }

  function initToolsBench() {
    /* ═══ ⑮ S05 다음 연습 도구 워크스페이스 — rail · canvas · inspector ═══ */
    const TOOL_DEFS = [
      { id: 'map',     ic: 'icMap',    name: '개요 이미지',   sub: '발표 직전 복습' },
      { id: 'punch',   ic: 'icQuote',  name: '펀치라인',      sub: '내 말투 한마디' },
      { id: 'terms',   ic: 'icCards',  name: '핵심 용어 카드', sub: 'Q&A 대비' },
      { id: 'pace',    ic: 'icPace',   name: '말 속도',       sub: '구간별 속도' },
      { id: 'summary', ic: 'icReport', name: '종합 리포트',   sub: '우선순위 3' },
      { id: 'play',    ic: 'icPlay',   name: '다시 듣기',     sub: '타임라인 동기' }
    ];
    let toolSel = 'map', mapWeakOnly = false, mapSlideNo = true, termIdx = 0, termFlip = {}, termDone = {}, playT = null, playP = 0;

    const MAP_NODES = [
      { id: 'r', x: 430, y: 46,  w: 210, label: '분명 잤는데 왜 피곤할까', root: true },
      { id: 'a', x: 150, y: 150, w: 122, label: '수면 주기',     st: 'ok',  s: 'S02' },
      { id: 'b', x: 430, y: 150, w: 150, label: '수면의 질 3요소', st: 'mid', s: 'S04' },
      { id: 'c', x: 716, y: 150, w: 122, label: '개선 방법',     st: 'ok',  s: 'S07' },
      { id: 'a1', x: 74,  y: 262, w: 130, label: '깊은 수면·REM', st: 'ok',  s: 'S03', p: 'a' },
      { id: 'a2', x: 228, y: 262, w: 128, label: '4–5회 반복',   st: 'no',  s: 'S02', p: 'a' },
      { id: 'b1', x: 372, y: 262, w: 122, label: '수면 연속성',   st: 'mid', s: 'S05', p: 'b' },
      { id: 'b2', x: 516, y: 262, w: 118, label: '사회적 시차',   st: 'mid', s: 'S06', p: 'b' },
      { id: 'c1', x: 664, y: 262, w: 132, label: '기상 시간 고정', st: 'ok',  s: 'S07', p: 'c' },
      { id: 'c2', x: 812, y: 262, w: 96,  label: '자극 줄이기',   st: 'ok',  s: 'S07', p: 'c' }
    ];
    const MAP_FILL = { ok: '#e9f7ef', mid: '#fdf6e3', no: '#fdf0ef' };
    const MAP_LINE = { ok: '#12a173', mid: '#e9a10e', no: '#dc2626' };

    function mapSvg() {
      const nodes = MAP_NODES.filter(n => n.root || !mapWeakOnly || n.st !== 'ok');
      const has = id => nodes.some(n => n.id === id);
      let links = '';
      MAP_NODES.filter(n => !n.root).forEach(n => {
        const from = n.p ? MAP_NODES.find(m => m.id === n.p) : MAP_NODES[0];
        if (!has(n.id) || !has(from.id)) return;
        links += `<path d="M${from.x} ${from.y + 26} C ${from.x} ${(from.y + n.y) / 2 + 20}, ${n.x} ${(from.y + n.y) / 2}, ${n.x} ${n.y - 4}" fill="none" stroke="#c3d0c5" stroke-width="1.6"/>`;
      });
      const boxes = nodes.map(n => {
        const fill = n.root ? '#12362d' : MAP_FILL[n.st];
        const line = n.root ? '#12362d' : MAP_LINE[n.st];
        const txt = n.root ? '#ffffff' : '#16211c';
        return `<g>
          <rect x="${n.x - n.w / 2}" y="${n.y - 4}" width="${n.w}" height="${n.root ? 40 : 52}" rx="11" fill="${fill}" stroke="${line}" stroke-width="1.6"/>
          <text x="${n.x}" y="${n.y + (n.root ? 21 : 16)}" text-anchor="middle" font-size="${n.root ? 15 : 13.5}" font-weight="700" fill="${txt}" font-family="Pretendard,sans-serif">${n.label}</text>
          ${n.root ? '' : `<text x="${n.x}" y="${n.y + 34}" text-anchor="middle" font-size="10.5" font-weight="700" fill="${MAP_LINE[n.st]}" font-family="Pretendard,sans-serif">${J_STATUS[n.st]}${mapSlideNo ? ' · ' + n.s : ''}</text>`}
        </g>`;
      }).join('');
      return `<svg id="mapSvg" viewBox="0 0 880 340" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="발표 개념 지도">
        <rect width="880" height="340" fill="#fbfaf8"/>${links}${boxes}</svg>`;
    }
    function exportMap() {
      const blob = new Blob([mapSvg()], { type: 'image/svg+xml' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = '수면의질_발표개요.svg';
      a.click(); URL.revokeObjectURL(a.href);
    }

    const TERMS = [
      { term: '수면의 질 3요소', st: 'mid', stName: '설명 부족', def: '수면의 질 = 시간 × 연속성 × 규칙성 — 하나만 무너져도 회복감이 떨어진다.', why: '발표의 중심 주장인데 관계 설명이 빠졌어요.', q: '세 요소 중 하나만 무너져도 피곤한 이유는?', slide: 'S04', frame: '① 세 요소 정의 → ② 곱으로 작동하는 관계 → ③ 7시간 자도 피곤한 예시' },
      { term: '사회적 시차', st: 'no', stName: '이해 부족 확정', def: '평일과 주말의 수면 시간대 차이로 생기는 생체리듬 어긋남.', why: 'Q&A 3회 상한 도달 — 최우선 보완 개념.', q: '주말에 몰아 자도 월요일에 피곤한 이유는?', slide: 'S06', frame: '① 평일·주말 기상 시간 차 → ② 생체리듬은 여행 시차처럼 반응 → ③ 월요일 = 귀국 첫날' },
      { term: '수면 연속성', st: 'mid', stName: '설명 부족 → Q&A 보완', def: '수면 주기가 끊기지 않고 이어지는 정도 — 각성이 잦으면 깊은 수면·REM에 도달하지 못한다.', why: 'Q&A에서 정확히 설명 — S05 발화에 통합 대기.', q: '연속성이 끊기면 수면 단계에 어떤 일이 생기나요?', slide: 'S05', frame: '① 주기 진행 → ② 각성 시 재시작 → ③ 깊은 단계 미도달' },
      { term: '밤사이 4–5회 반복', st: 'no', stName: '누락', def: '90–110분 주기가 하룻밤 4–5회 반복된다 — 연속성 판단의 수치 기준.', why: '슬라이드 수치가 발화에서 “여러 번”으로 뭉개졌어요.', q: '한 번의 각성은 하룻밤의 몇 %를 무너뜨리나요?', slide: 'S02', frame: '① 4–5회 제시 → ② 한 주기의 비중 → ③ 각성의 영향' },
      { term: '깊은 수면·REM 역할', st: 'ok', stName: '설명함', def: '깊은 수면은 신체 회복, REM은 기억 정리·감정 처리 — 회복은 둘 다 필요하다.', why: '잘 설명된 개념 — Q&A 대비 참고용.', q: '둘 중 하나만 충분하면 어떤 상태가 되나요?', slide: 'S03', frame: '① 역할 대비 → ② 초반·후반 분포 → ③ 한쪽 부족 시 증상' }
    ];

    const PUNCH = [
      { time: '04:58', pos: 'SLIDE 04 뒤 · 질의 3요소 직후', main: '결국 좋은 잠은, 시간이 아니라 이어짐인 것이죠.', alt: '오래 잔 밤이 아니라, 끊기지 않은 밤이 좋은 밤입니다.', why: '설명 부족 판정 구간 직후의 강조 지점 — 실제 발화의 ‘~인 것이죠’ 문장 패턴을 반영했어요' },
      { time: '07:39', pos: '결론 앞 · 개선 방법 마무리', main: '몇 시간 잤는지 대신, 어떻게 잤는지를 물어보세요.', alt: '내일의 컨디션은 오늘 밤의 연속성이 정합니다.', why: '도입의 손들기 질문과 수미상관 — 빨라지는 결론 구간의 속도를 잡아주는 역할도 해요' }
    ];
    const PACE_SEGS = [
      ['S01 도입', 29, 276, '여러분 본격적으로 시작하기 전에 어젯밤에 몇 시간 정도 주무셨는지…'],
      ['S02 수면 주기', 12, 261, '이 하나의 주기는 보통 약 90분에서 110분 정도로 설명이 됩니다.'],
      ['S03 깊은·REM', 13, 249, '깊은 수면과 렘수면은 역할이 다릅니다.'],
      ['S04 3요소', 8, 270, '수면의 질을 시간, 연속성, 규칙성으로 나누어 볼 수 있습니다.'],
      ['S05 각성 원인', 6, 268, '늦은 시간에 마신 카페인, 음주, 스트레스…'],
      ['S06 사회적 시차', 6, 267, '이런 차이를 사회적 시차라고 부르기도 합니다.'],
      ['S07 개선 방법', 19, 273, '먼저 기상 시간을 일정하게 유지하는 것이 실천하기 쉽습니다.'],
      ['S08 결론', 7, 322, '오늘 내용을 정리하면 좋은 잠에는 세 가지 조건이 필요합니다.', 1]
    ];
    const PLAY_STEPS = [
      { at: 0,   slide: 'S02 · 수면 주기', line: '이 하나의 주기는 보통 약 90분에서 110분 정도로 설명이 됩니다' },
      { at: .3,  slide: 'S04 · 질의 3요소', line: '수면의 질을 시간, 연속성, 규칙성으로 나누어 볼 수 있습니다', mark: '설명 부족' },
      { at: .62, slide: 'S06 · 사회적 시차', line: '이런 차이를 사회적 시차라고 부르기도 합니다', mark: '언급만' },
      { at: .88, slide: 'S08 · 결론', line: '오늘 내용을 정리하면 좋은 잠에는 세 가지 조건이 필요합니다', mark: '20% 빠름' }
    ];

    function renderToolRail() {
      const rail = $('#toolRail');
      rail.innerHTML = '<small class="ws-rail-title">연습 도구</small>' + TOOL_DEFS.map(t => `
        <button class="jnode tool ${t.id === toolSel ? 'sel' : ''}" data-t="${t.id}">
          <span class="tico"><svg viewBox="0 0 20 20"><use href="#${t.ic}"/></svg></span>
          <span class="jl"><b>${t.name}</b><small>${t.sub}</small></span>
        </button>`).join('');
      $$('#toolRail [data-t]').forEach(b => b.addEventListener('click', () => {
        toolSel = b.dataset.t; stopPlay(); renderTool();
      }));
    }
    function inspectorNote(items) {
      return items.map(i => `<div class="ins-row ${i[2] || ''}"><b>${i[0]}</b><span>${i[1]}</span></div>`).join('');
    }
    function renderTool() {
      const toolSwitched = renderTool._last !== undefined && renderTool._last !== toolSel;
      renderTool._last = toolSel;
      const def = TOOL_DEFS.find(t => t.id === toolSel);
      $('#toolTitle').textContent = def.name;
      renderToolRail();
      const canvas = $('#toolCanvas'), ins = $('#toolInspector');

      if (toolSel === 'map') {
        canvas.innerHTML = `<div class="map-wrap">${mapSvg()}</div>
          <p class="canvas-note">발표 직전 5초 복습용 — 초록은 설명함, 노랑은 설명 부족, 빨강은 누락이에요.</p>`;
        ins.innerHTML = `<small class="ins-title">보기 설정</small>
          <label class="ins-toggle"><input type="checkbox" id="mapWeak" ${mapWeakOnly ? 'checked' : ''}> 부족·누락만 보기</label>
          <label class="ins-toggle"><input type="checkbox" id="mapNo" ${mapSlideNo ? 'checked' : ''}> 슬라이드 번호 표시</label>
          ${inspectorNote([['개념 수', '10개 · 2단계 구조'], ['최우선', '선순환 구조 · 이해 부족 확정', 'warn'], ['근거', '개념 판정 + Q&A 결과']])}
          <button class="ins-cta" id="mapExport">SVG로 내보내기</button>`;
        $('#mapWeak').addEventListener('change', e => { mapWeakOnly = e.target.checked; renderTool(); });
        $('#mapNo').addEventListener('change', e => { mapSlideNo = e.target.checked; renderTool(); });
        $('#mapExport').addEventListener('click', exportMap);
      }

      if (toolSel === 'terms') {
        const view = [termIdx, termIdx + 1, termIdx + 2].filter(i => i < TERMS.length);
        canvas.innerHTML = `<div class="tcards">${view.map(i => {
          const c = TERMS[i], fl = termFlip[i];
          return `<article class="tcard ${fl ? 'flip' : ''} ${termDone[i] ? 'done' : ''}">
            <div class="tc-top"><span class="st ${c.st}">${c.stName}</span><b>${c.slide}</b></div>
            ${fl
              ? `<small class="tc-k">예상 질문</small><h4>“${c.q}”</h4>
                 <small class="tc-k">답변 골격</small><p>${c.frame}</p>`
              : `<h4>${c.term}</h4><p class="tc-def">${c.def}</p>
                 <small class="tc-k">왜 중요한가</small><p>${c.why}</p>`}
            <div class="tc-actions">
              <button class="tc-flip" data-flip="${i}" aria-pressed="${!!fl}">${fl ? '← 정의 보기' : '예상 질문 보기 →'}</button>
              <button class="tc-done" data-done="${i}">${termDone[i] ? '<svg class="ic-i" viewBox="0 0 24 24" aria-hidden="true"><use href="#icCheck"/></svg> 이해함' : '이해함으로 표시'}</button>
            </div>
          </article>`;
        }).join('')}</div>`;
        ins.innerHTML = `<small class="ins-title">학습 진행</small>
          <div class="ins-prog"><b>${Object.keys(termDone).length} / ${TERMS.length}</b><span>이해함으로 표시</span></div>
          <div class="ins-nav">
            <button id="termPrev" ${termIdx === 0 ? 'disabled' : ''}>← 이전</button>
            <span>${termIdx + 1}–${Math.min(termIdx + 3, TERMS.length)} / ${TERMS.length}</span>
            <button id="termNext" ${termIdx + 3 >= TERMS.length ? 'disabled' : ''}>다음 →</button>
          </div>
          ${inspectorNote([['카드 재료', '발표자료 원문만 사용'], ['근거 규칙', '근거 슬라이드 번호 필수'], ['출처', '개념 판정 + Q&A 결과']])}
          <a class="ins-cta" href="#/qa">이 카드로 질문 연습 →</a>`;
        $$('#toolCanvas [data-flip]').forEach(b => b.addEventListener('click', () => { const i = Number(b.dataset.flip); termFlip[i] = !termFlip[i]; renderTool(); }));
        $$('#toolCanvas [data-done]').forEach(b => b.addEventListener('click', () => { const i = Number(b.dataset.done); termDone[i] ? delete termDone[i] : termDone[i] = 1; renderTool(); }));
        const pv = $('#termPrev'), nx = $('#termNext');
        if (pv) pv.addEventListener('click', () => { termIdx = Math.max(0, termIdx - 1); renderTool(); });
        if (nx) nx.addEventListener('click', () => { termIdx = Math.min(TERMS.length - 3, termIdx + 1); renderTool(); });
      }

      if (toolSel === 'punch') {
        canvas.innerHTML = `<div class="punch-timeline">
            ${PACE_SEGS.map(s => `<span style="flex:${s[1]}"><i>${s[0].split(' ')[0]}</i></span>`).join('')}
            <em class="pmark" style="left:31%" data-l="02:42"></em><em class="pmark" style="left:92%" data-l="07:58"></em>
          </div>
          ${PUNCH.map((p, i) => `<div class="punch-item">
            <div class="punch-head"><b>${p.time}</b><span>${p.pos}</span></div>
            <blockquote contenteditable="false" id="punchQ${i}">“${p.main}”</blockquote>
            <p class="punch-alt">대안 — “${p.alt}”</p>
            <p class="punch-why">${p.why}</p>
            <div class="tc-actions">
              <button class="tc-done" data-adopt="${i}">이 문장 채택</button>
              <button class="tc-flip" data-edit="${i}">직접 편집</button>
            </div>
          </div>`).join('')}`;
        ins.innerHTML = `<small class="ins-title">생성 조건</small>
          ${inspectorNote([['말투 예시', '실제 발화 5문장 반영'], ['위치 선정', '논리 점검이 찾은 강조 지점'], ['금지 규칙', '평소 안 쓸 어휘 제외'], ['개수', '흐름 유지를 위해 최대 3개']])}`;
        $$('#toolCanvas [data-edit]').forEach(b => b.addEventListener('click', () => {
          const q = $('#punchQ' + b.dataset.edit);
          const on = q.contentEditable === 'true';
          q.contentEditable = String(!on); if (!on) q.focus();
          b.textContent = on ? '직접 편집' : '편집 완료';
        }));
        $$('#toolCanvas [data-adopt]').forEach(b => b.addEventListener('click', () => {
          b.innerHTML = '<svg class="ic-i" viewBox="0 0 24 24" aria-hidden="true"><use href="#icCheck"/></svg> 대본 메모에 추가됨'; b.disabled = true;
        }));
      }

      if (toolSel === 'pace') {
        const max = 430;
        canvas.innerHTML = `<div class="pace-full">
            ${PACE_SEGS.map((s, i) => `<button class="pcol ${s[4] ? 'fast' : ''}" data-p="${i}" style="flex:${s[1]}">
              <i style="height:${Math.round(s[2] / max * 100)}%"></i><b>${s[2]}</b><span>${s[0]}</span>
            </button>`).join('')}
          </div>
          <div class="pace-line"><span>본인 평균 328자/분</span></div>
          <div class="pace-say" id="paceSay">구간을 누르면 해당 구간의 발화가 여기 표시돼요.</div>`;
        ins.innerHTML = `<small class="ins-title">계산 방식</small>
          ${inspectorNote([['방식', 'AI 미사용 · 단어별 타임스탬프 계산'], ['기준', '본인 평균 대비 (328자/분)'], ['제외', '‘어’, ‘음’, 침묵 구간'], ['빠른 구간', 'S04·S05 — 설명 부족 개념과 겹침', 'warn']])}`;
        $$('#toolCanvas [data-p]').forEach(b => b.addEventListener('click', () => {
          const s = PACE_SEGS[Number(b.dataset.p)];
          $$('#toolCanvas .pcol').forEach(x => x.classList.toggle('sel', x === b));
          $('#paceSay').innerHTML = `<b>${s[0]} · ${s[2]}자/분</b> — “${s[3]}”`;
        }));
      }

      if (toolSel === 'summary') {
        const rows = [
          ['이탈률 3.2% 근거를 결론 앞에 복원', '누락 · S06 — 교수님 모드 1순위', '04:41'],
          ['네트워크 효과의 선순환 한 문장 보강', '설명 부족 · S04 — Q&A 이해 부족과 동일 지점', '02:18'],
          ['구독료 인상 모순 해소', '모순 · S07 — 자료·발화 불일치', '06:12']
        ];
        canvas.innerHTML = `<div class="sum-rows">${rows.map((r, i) => `
          <label class="sum-row"><input type="checkbox" data-s="${i}">
            <span class="sn">0${i + 1}</span>
            <span class="sl2"><b>${r[0]}</b><small>${r[1]}</small></span><time>${r[2]}</time>
          </label>`).join('')}</div>
          <div class="sum-next"><b>다음 연습 목표</b><p>‘선순환 구조’를 사례와 함께 설명하기 — 완료 후 Q&A로 재검증하세요.</p>
          <a class="ins-cta" href="#/practice">이 목표로 다시 연습 →</a></div>`;
        ins.innerHTML = `<small class="ins-title">이번 세션</small>
          ${inspectorNote([['완성도', '82점 (+9)'], ['판정', '설명 9 · 부족 2 · 누락 3 · 모순 1'], ['Q&A', '통과 4/5 · 이해 부족 1'], ['구성', '판정·속도 산출물 조합 · 별도 AI 미사용']])}
          <a class="ins-cta" href="#/report">전체 리포트 열기 →</a>`;
      }

      if (toolSel === 'play') {
        canvas.innerHTML = `<div class="play-grid">
            <div class="pl-slide"><small>SLIDE</small><b id="plSlide">S03 · 시장 데이터</b><div class="jslide-lines"><i></i><i></i><i></i></div></div>
            <div class="pl-script" id="plScript">${PLAY_STEPS.map((s, i) =>
              `<p data-l="${i}">${s.line}${s.mark ? ` <em>${s.mark}</em>` : ''}</p>`).join('')}</div>
            <div class="pl-wave">
              <div class="pl-wavebars" data-wave></div>
              <div class="pl-track"><i id="plHead"></i></div>
              <div class="pl-time"><span id="plNow">0:00</span><b>08:15</b></div>
            </div>
          </div>`;
        ins.innerHTML = `<small class="ins-title">재생</small>
          <button class="ins-cta" id="plBtn"><svg class="ic-i" viewBox="0 0 24 24" aria-hidden="true"><use href="#icPlaySolid"/></svg> 데모 재생</button>
          ${inspectorNote([['동기화', '슬라이드 · 전사문 · 파형 동시 이동'], ['재료', '단어별 시간 기록 + 전환 시각'], ['상태', '후속 기능 — 오디오는 백엔드 연동 필요', 'warn']])}`;
        buildWave($('#toolCanvas [data-wave]'), 46, 10, 30);
        $('#plBtn').addEventListener('click', () => { playT ? stopPlay() : startPlay(); });
        renderPlayState();
      }
      if (toolSwitched) {
        mIn($$('#toolCanvas > *'), M ? { delay: M.stagger(.06) } : null);
        mIn($$('#toolInspector > *'), M ? { delay: M.stagger(.04, { startDelay: .08 }), duration: .4 } : null);
      }
    }
    function renderPlayState() {
      const st = [...PLAY_STEPS].reverse().find(s => playP >= s.at) || PLAY_STEPS[0];
      const sl = $('#plSlide'); if (!sl) return;
      sl.textContent = st.slide;
      $$('#plScript p').forEach((p, i) => p.classList.toggle('cur', PLAY_STEPS[i] === st));
      $('#plHead').style.left = (playP * 100) + '%';
      const sec = Math.round(playP * 495);
      $('#plNow').textContent = Math.floor(sec / 60) + ':' + String(sec % 60).padStart(2, '0');
    }
    function startPlay() {
      $('#plBtn').textContent = '일시정지';
      if (demoAudio && !audioFail) { demoAudio.currentTime = playP * 495; demoAudio.play().catch(() => { audioFail = true; }); }
      playT = setInterval(() => {
        if (demoAudio && !audioFail && !demoAudio.paused) playP = demoAudio.currentTime / 495;
        else playP += .012;
        if (playP >= 1) { playP = 0; stopPlay(); return; }
        renderPlayState();
      }, 90);
    }
    function stopPlay() {
      clearInterval(playT); playT = null;
      if (demoAudio && !demoAudio.paused) demoAudio.pause();
      const b = $('#plBtn'); if (b) b.innerHTML = '<svg class="ic-i" viewBox="0 0 24 24" aria-hidden="true"><use href="#icPlaySolid"/></svg> 데모 재생';
    }
    if ($('#toolRail')) renderTool();
  }

  function initJudgeStamp() {
    /* ═══ B⑤ 판정 레일 스탬프 — 첫 노출 시 1회 ═══ */
    const judgeSecEl = document.getElementById('judgeSec');
    if (judgeSecEl && !reduceMotion) {
      const jio = new IntersectionObserver(es => es.forEach(e => {
        if (!e.isIntersecting) return;
        jio.disconnect();
        mIn($$('#judgeRail .jnode'), M ? { delay: M.stagger(.05), duration: .45 } : null);
      }), { threshold: .25 });
      jio.observe(judgeSecEl);
    }
  }

  return function initWorkbench() {
    initReportTabs();
    initQaDemo();
    initStartUpload();
    initJudgeBench();
    initToolsBench();
    initJudgeStamp();
  };
})();
