/**
 * 통화 오버레이 상태 — 한 덩어리 (캠 트랙 P0-3, docs/plan/cam-track.plan.md §4).
 *
 * 왜 따로 두나 — 오버레이(모드·메인 무대·단계·삐약이 기분·자막)가 booth.js 의 setMode/setMain/setPhase
 * 에 흩어져 DOM 을 직접 만졌다. canvas 합성(P1)은 같은 상태를 픽셀로 그려야 하므로 상태를 먼저 한 객체로
 * 모은다. 전이 함수는 순수하다(새 객체를 돌려준다, 받은 것을 고치지 않는다). DOM 은 renderOverlay 만 만진다.
 *
 * 말풍선 기록(bubble)은 아직 여기 없다 — P1 에서 옮긴다.
 * import 의 ?v= 는 booth.js 가 booth_logic.js 를 무는 값과 같아야 한다 (다르면 모듈이 두 벌 올라온다).
 */
import { partnerMood } from './booth_logic.js?v=b8';

/** 단계별 삐약이 이름표 아래 한 줄. 판정이 난 뒤에는 말풍선이 말하므로 비운다 */
export const PHASE_STATUS = {
  present: '듣고 있어요',
  asking: '묻고 있어요',
  hint: '힌트를 줬어요',
  listening: '듣고 있어요',
  judging: '생각하는 중',
  judged: '',
};

/** 통화를 열기 전 — booth.html 의 기본값(data-mode=present · data-main=slides · data-phase=present)과 같다 */
export function createOverlayState() {
  return {
    mode: 'present',     // present | qa
    main: 'slides',      // 프레임을 채우는 무대. 나머지가 오른쪽 아래 작은 창
    phase: 'present',    // present | asking | hint | listening | judging | judged
    question: null,      // { text, tag, scene } — 지금 묻고 있는 질문
    speaker: 'solar',    // 말하는 병아리 (화자 배정은 P2)
    mood: 'neutral',     // chatter.css data-mood
    caption: '',         // 발표 중 흐르는 자막 (꼬리만)
    verdict: '',         // 마지막 판정 (judged 일 때만 뜻이 있다)
    handRaised: false,   // 손 들기 (디렉터 P2)
  };
}

/** 발표 모드 — 자료가 메인. 질문·판정·자막은 새로 시작한다 */
export function enterPresent(s) {
  return { ...s, mode: 'present', main: 'slides', question: null, verdict: '', caption: '' };
}

/** Q&A — 내 모습이 메인 */
export function enterQa(s) {
  return { ...s, mode: 'qa', main: 'self' };
}

/** 메인 무대를 바꾼다. 모르는 값이면 그대로 둔다 */
export function setMainOf(s, which) {
  if (which !== 'slides' && which !== 'self') return s;
  return { ...s, main: which };
}

/** 단계가 바뀌면 삐약이 기분도 같이 바뀐다 (booth_logic.partnerMood 가 규칙) */
export function setPhaseOf(s, phase, verdict = '') {
  return { ...s, phase, verdict: verdict || '', mood: partnerMood(phase, verdict) };
}

export function askQuestion(s, q) {
  const question = q ? { text: String(q.text || ''), tag: q.tag || '', scene: q.scene == null ? null : q.scene } : null;
  return { ...s, question };
}

export function setCaption(s, text) {
  return { ...s, caption: String(text == null ? '' : text) };
}

/**
 * 상태를 DOM 에 옮긴다. el = { call, seat, status, clock, qaCount, autotalk, caption } (없는 칸은 건너뛴다).
 * prev 를 주면 바뀐 칸만 쓴다 — 발표 중 지적(showTell)이 삐약이 표정·이름표를 잠깐 바꿔 둔 사이에
 * 작은 창을 눌러도(setMain) 그 표정을 덮지 않게. prev 가 없으면 전부 쓴다.
 */
export function renderOverlay(s, el, prev = null) {
  const changed = (k) => !prev || prev[k] !== s[k];
  if (el.call) {
    if (changed('mode')) el.call.dataset.mode = s.mode;
    if (changed('main')) el.call.dataset.main = s.main;
    if (changed('phase')) el.call.dataset.phase = s.phase;
  }
  if (changed('mode')) {
    if (el.clock) el.clock.hidden = s.mode !== 'present';
    if (el.qaCount) el.qaCount.hidden = s.mode !== 'qa';
    if (el.autotalk) el.autotalk.hidden = s.mode !== 'qa';
  }
  if (changed('phase') || changed('mood') || changed('verdict')) {
    if (el.seat) el.seat.dataset.mood = s.mood;
    if (el.status) el.status.textContent = PHASE_STATUS[s.phase] || '';
  }
  if (el.caption && changed('caption')) el.caption.textContent = s.caption;
}
