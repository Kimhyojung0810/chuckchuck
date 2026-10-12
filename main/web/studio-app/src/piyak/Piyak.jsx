/* 삐약이 — 객석 발표새(js/chatter.js chickSvg, 쏠라 · 겹친 슬라이드)와 같은 그림을 React + Motion 으로 움직인다.
   실루엣 · 초록 외곽선 · 노란 몸 · 얼굴은 그대로 두고, 몸통 · 날개 · 머리 · 눈을 따로 묶어 움직일 수 있게 나눴다.
   움직임: 숨쉬기 · 흔들기(CSS) · 커서 쪽으로 눈이 먼저, 몸이 뒤따라 돌아섬 · 커서가 없으면 두리번거림 ·
   누르면 찌그러졌다 통 튐 · 마이크 소리에 몸이 늘고 날개가 든다 · 표정 5종.
   10-13 사용자: 「훨씬 더 적극적으로」 → 크게 키운 판(lively), 이어서 「귀엽지 않다」 → 작고 탄력 있게 자주(cute, 기본). 크기는 PRESETS 한곳에
   표정을 무엇으로 할지는 쓰는 쪽이 정한다 (PiyakStage) — 이 파일은 그림과 몸짓만 안다. 색은 css/studio-app.css 의 .px- 블록 */
import { useEffect, useId, useRef } from 'react'
import { motion, useMotionValue, useMotionValueEvent, useSpring, useTransform, useAnimationFrame, useReducedMotion, animate } from 'motion/react'
import { gaze, voiceK, voiceLift, GAZE_X, GAZE_Y } from './logic.js'
import { ShellDefs, ShellPants, ShellCap } from './Shell.jsx'

/**
 * 움직임 크기 — 단위는 viewBox(100). turn 은 -1(왼쪽)..1(오른쪽), pitch 는 -1(위)..1(아래) 에 곱한다.
 * cute(기본): 작고 탄력 있게, 자주 — 고개를 돌릴 때 깡충, 가만히 있으면 가끔 통통 · 발 까딱, 눈은 늘 온전히 보인다.
 *   10-13 사용자: 「길쭉해지면 안 귀엽다, 동글동글이 귀엽다」 — 세로로는 늘이지 않고(maxTall), 힘을 받으면 옆으로 퍼진다(떡 · 젤리처럼).
 *   돌아설 때도 몸을 좁히지 않는다(narrow 0) — 좁아지면 길쭉해 보인다.
 * lively: 크게 돌아선다 — 얼굴이 몸 가장자리까지 미끄러진다 (10-13 「훨씬 더 적극적으로」 판, 「귀엽지 않다」 로 기본에서 내림)
 */
const PRESETS = {
  cute: {
    face: 8, blush: 6.5, belly: 5, prop: 5, tuft: 4, legs: 3, tail: -4, wing: 3,
    faceY: 3.2, bellyY: 1.4, tuftY: 1.8,
    narrow: 0, farEye: 0.1, farWing: 0.3, nearWing: 0.06,
    lean: 4,
    pokeSquash: 0.8, pokeWide: 1.15, pokeHop: 12, pokeFlap: 30,
    voicePuffX: 0.07, voicePuffY: -0.02, voiceHop: 4, voiceWing: 34,   // 말소리에 볼록 퍼진다
    maxTall: 1.01, minWide: 0.99,                                       // 이보다 길쭉해지지 않는다
    lookHop: 4.5, idleHop: true,
    turnSpring: { stiffness: 170, damping: 11, mass: 0.8 },   // 빠르게 따라가 살짝 출렁 — 「보잉」
  },
  lively: {
    face: 15, blush: 12, belly: 10, prop: 8, tuft: 7, legs: 5, tail: -7, wing: 5,
    faceY: 5, bellyY: 2.2, tuftY: 2.4,
    narrow: 0.1, farEye: 0.35, farWing: 0.6, nearWing: 0.12,
    lean: 8,
    pokeSquash: 0.76, pokeWide: 1.16, pokeHop: 16, pokeFlap: 38,
    voicePuffX: -0.05, voicePuffY: 0.14, voiceHop: 5, voiceWing: 40,
    maxTall: 2, minWide: 0,
    lookHop: 0, idleHop: false,
    turnSpring: { stiffness: 90, damping: 13, mass: 0.9 },
  },
}
const LOOK_HOP_GAP_MS = 550       // 고개 돌릴 때 깡충은 이만큼 띄워서 (연달아 콩콩대지 않게)
const IDLE_HOP_MIN_MS = 3600
const IDLE_HOP_SPAN_MS = 3400

const EYE_SPRING = { stiffness: 260, damping: 20, mass: 0.6 }
const SOFT_SPRING = { stiffness: 140, damping: 14 }
const BOUNCE = { type: 'spring', stiffness: 480, damping: 10 }   // 누른 뒤 제자리로 — 두어 번 출렁이고 멈춘다
const GAZE_IDLE_MS = 2200        // 커서가 이만큼 멈춰 있으면(또는 손가락을 떼면) 혼자 두리번거리기 시작한다
const GLANCE_MIN_MS = 1400
const GLANCE_SPAN_MS = 2200
const BLINK_MIN_MS = 2600
const BLINK_SPAN_MS = 3800

/* 10-13 사용자: 「모양을 바꿔도 된다」 → 큰 눈 동그란 몸 시안은 「이상하다」 → 사용자 레퍼런스(카와이 병아리 이모지 · 병아리 스티커)대로:
   머리 · 몸이 한 덩어리인 방울 떡(옆으로 조금 넓고 바닥이 평평), 하이라이트 없는 작은 점 눈을 멀리 · 낮게, 작은 둥근 부리, 작은 볼,
   배 무늬 · 꼬리 없이 날개 · 발은 살짝만. 초록 외곽선 · 노란 몸 · 새싹 · 쏠라의 슬라이드는 그대로. 옛 달걀 모양은 js/chatter.js chickSvg */
const TORSO = 'M50 18C27 18 11 34 11 56c0 19 13 30 39 30s39-11 39-30C89 34 73 18 50 18z'
const EYE = { cy: 56, r: 3.1 }

/** 눈 한 짝 — 작은 점. 표정 곡선(기쁨 ∩ · 아쉬움 ∪)은 mood 가 켠다 */
function Eye({ cx, gx, gy, sx }) {
  const { cy, r } = EYE
  return (
    <motion.g className="px-eye" style={{ scaleX: sx, originX: 0.5, originY: 0.5 }}>
      <motion.g style={{ x: gx, y: gy }}>
        <circle className="px-eye-ball" cx={cx} cy={cy} r={r} />
      </motion.g>
      <path className="px-eye-line px-eye-happy" d={`M${cx - 3.8} ${cy + 1.2}q3.8 -4.8 7.6 0`} />
      <path className="px-eye-line px-eye-grumpy" d={`M${cx - 3.8} ${cy - 1.2}q3.8 4.4 7.6 0`} />
    </motion.g>
  )
}

/** 새싹 — 삐약이 머리 위 (알일 때는 알 꼭대기). y: 줄기 밑동 */
export function Sprout({ y = 18, scale = 1 }) {
  return (
    <g className="px-tuft" transform={`translate(50 ${y}) scale(${scale}) translate(-50 -18)`}>
      <path d="M50 18V14" fill="none" strokeWidth="1.8" strokeLinecap="round" />
      <path className="px-mint" d="M50 14.4c-.9-2.8-3.4-3.9-5.6-3 .5 2.4 2.7 3.6 5.6 3z" />
      <path className="px-mint" d="M50 14.4c.9-2.8 3.4-3.9 5.6-3-.5 2.4-2.7 3.6-5.6 3z" />
    </g>
  )
}

/** 커서를 본다. 커서가 멈추거나(마우스) 손가락을 떼면(터치) 혼자 이쪽저쪽 두리번거린다 */
export function useGaze(target, wander) {
  const gx = useMotionValue(0)
  const gy = useMotionValue(0)
  useEffect(() => {
    let idle = 0
    let glance = 0
    let frame = 0
    let last = null
    const look = () => {
      frame = 0
      const el = target.current
      if (!el || !last) return
      const r = el.getBoundingClientRect()
      if (!r.width) return
      const g = gaze(last.x, last.y, r.left + r.width / 2, r.top + r.height * 0.59, r.width * 0.45)
      gx.set(g.x); gy.set(g.y)
    }
    /** 혼자 있을 때 — 세 번에 한 번은 앞을, 나머지는 옆 · 위아래를 본다 */
    const roam = () => {
      const front = Math.random() < 0.33
      gx.set(front ? 0 : (Math.random() < 0.5 ? -1 : 1) * (0.55 + Math.random() * 0.45) * GAZE_X)
      gy.set(front ? 0 : (Math.random() * 1.1 - 0.6) * GAZE_Y)
      glance = setTimeout(roam, GLANCE_MIN_MS + Math.random() * GLANCE_SPAN_MS)
    }
    const rest = () => { if (wander) roam(); else { gx.set(0); gy.set(0) } }
    const on = (e) => {
      last = { x: e.clientX, y: e.clientY }
      clearTimeout(glance); clearTimeout(idle)
      if (!frame) frame = requestAnimationFrame(look)
      idle = setTimeout(rest, e.pointerType === 'touch' ? 1200 : GAZE_IDLE_MS)
    }
    const leave = (e) => { if (!e.relatedTarget) { clearTimeout(idle); clearTimeout(glance); rest() } }
    addEventListener('pointermove', on, { passive: true })
    addEventListener('pointerdown', on, { passive: true })
    document.addEventListener('pointerout', leave)
    idle = setTimeout(rest, 900)
    return () => {
      removeEventListener('pointermove', on); removeEventListener('pointerdown', on)
      document.removeEventListener('pointerout', leave)
      clearTimeout(idle); clearTimeout(glance); cancelAnimationFrame(frame)
    }
  }, [target, gx, gy, wander])
  return { gx, gy }
}

/** 가끔 눈을 깜빡인다 — 사람보다 조금 느리게, 간격은 들쭉날쭉 */
function useBlink(enabled) {
  const blink = useMotionValue(1)
  useEffect(() => {
    if (!enabled) { blink.set(1); return undefined }
    let t = 0
    const next = () => {
      t = setTimeout(() => {
        animate(blink, [1, 0.12, 1], { duration: 0.22, times: [0, 0.45, 1], ease: 'easeInOut' })
        next()
      }, BLINK_MIN_MS + Math.random() * BLINK_SPAN_MS)
    }
    next()
    return () => clearTimeout(t)
  }, [enabled, blink])
  return blink
}

/** 마이크 소리 → 0..1. 빨리 올라가고 천천히 내려온다(말끝에 뚝 끊기지 않게) */
function useVoice(levelRef, listening) {
  const lift = useMotionValue(0)
  const smooth = useRef(0)
  useAnimationFrame(() => {
    const k = listening ? voiceK(levelRef?.current || 0) : 0
    const s = smooth.current
    smooth.current = s + (k - s) * (k > s ? 0.4 : 0.12)
    const v = voiceLift(smooth.current)
    if (Math.abs(v - lift.get()) > 0.002) lift.set(v)
  })
  return lift
}

/**
 * 넷의 소품 — 그 병아리가 파이프라인에서 실제로 한 일 (etc/bench/results/chicks/README.md).
 * 쏠라 겹친 슬라이드(자료 통독) · 엑씨 헤드폰(발표를 귀로) · 믿음 형광펜(자료와 발화 대조) · 엑사원 별 로제트(잘 맞은 대목 인정)
 */
export const WHO = ['solar', 'ax', 'midm', 'exaone']
function HeldProp({ who }) {
  if (who === 'midm') {
    return (
      <g className="px-prop" transform="translate(85 56) rotate(28)">
        <rect x="0" y="0" width="8.5" height="17" rx="3.4" fill="#FFE14D" />
        <rect x="0" y="0" width="8.5" height="5.6" rx="2.8" className="px-cap" />
        <path className="px-tip" d="M.9 17h6.7l-3.35 4.6z" />
      </g>
    )
  }
  if (who === 'exaone') {
    return (
      <g className="px-prop px-rosette" transform="translate(0 3.5)">
        <path className="px-ribbon" d="M46.6 77.5l-2.4 5 3.4-.8 1.6 3 2-5.3z" />
        <path className="px-ribbon" d="M53.4 77.5l2.4 5-3.4-.8-1.6 3-2-5.3z" />
        <circle cx="50" cy="71.5" r="7" className="px-medal" />
        <circle cx="50" cy="71.5" r="4.4" fill="#FFFFFF" stroke="none" />
        <path className="px-star" d="M50 68.3l1.05 2.1 2.35.35-1.7 1.65.4 2.35-2.1-1.1-2.1 1.1.4-2.35-1.7-1.65 2.35-.35z" />
      </g>
    )
  }
  if (who === 'ax') return null   // 헤드폰은 머리에 — 아래 HeadProp
  return (
    <g className="px-prop" transform="translate(84 66) rotate(12)">
      <rect x="0" y="0" width="15" height="11" rx="2.2" fill="#F2FBF6" />
      <rect x="-2.6" y="2.6" width="15" height="11" rx="2.2" fill="#FFFFFF" />
      <rect x="-.4" y="4.8" width="4.8" height="2.8" rx=".9" className="px-mint" stroke="none" />
    </g>
  )
}
/** 엑씨의 헤드폰 — 머리띠가 새싹 뒤로 지나고, 컵이 몸 밖으로 나와 어두운 무대에서도 엑씨로 읽힌다 */
function HeadProp({ who }) {
  if (who !== 'ax') return null
  return (
    <g className="px-prop px-phones">
      <path className="px-band" d="M13.5 50a36.5 39 0 0 1 73 0" />
      <rect x="6.5" y="42" width="12" height="17" rx="5.5" className="px-cup" />
      <rect x="81.5" y="42" width="12" height="17" rx="5.5" className="px-cup" />
    </g>
  )
}

/**
 * who: solar(기본) · ax · midm · exaone — 소품만 다르고 몸은 하나
 * form: chick(기본) · hen(다 자란 닭 — 크림색 몸 · 빨간 볏 · 꼬리깃 · 소품 없음)
 * shell: 없음 · pants(아래 껍데기를 입은 갓 깬 병아리) · cap(위 껍데기를 쓴 병아리) — 알 단계는 Egg.jsx
 * mood: neutral · happy · curious · excited · grumpy
 * levelRef: 마이크 RMS 를 담은 ref (media.js useMicLevel 의 level) · listening: 마이크가 켜져 있는가
 * onPoke: 눌렀을 때 · onHover(bool): 커서가 올라갔을 때
 */
export function Piyak({ who = 'solar', form = 'chick', shell, mood = 'neutral', levelRef, listening = false, onPoke, onHover, label = '삐약이', preset = 'cute' }) {
  const AMP = PRESETS[preset] || PRESETS.cute
  const reduced = useReducedMotion()
  const box = useRef(null)
  const ids = useId().replace(/:/g, '')
  const glowId = `pxg${ids}`
  const clipId = `pxc${ids}`
  const shellId = `pxs${ids}`
  const hen = form === 'hen'

  const { gx: gazeX, gy: gazeY } = useGaze(box, !reduced)
  const gx = useSpring(gazeX, EYE_SPRING)
  const gy = useSpring(gazeY, EYE_SPRING)

  // 몸 돌리기 (10-13 사용자: 「몸이 진짜로 회전하는 게 중요」) — 반쯤 입체: 앞에 있는 것일수록 더 옆으로 밀리고,
  // 얼굴 · 배는 몸 윤곽 안에서만 보여서 옆으로 돌면 윤곽 너머로 넘어간다. 먼 쪽 눈 · 볼 · 날개는 좁아지고, 몸이 그쪽으로 기운다
  const turn = useTransform(useSpring(gazeX, AMP.turnSpring), (v) => v / GAZE_X)
  const pitch = useTransform(useSpring(gazeY, AMP.turnSpring), (v) => v / GAZE_Y)
  const by = (k) => (t) => t * AMP[k]
  const far = (k, sign) => (t) => 1 - AMP[k] * Math.max(0, sign * t)
  const faceX = useTransform(turn, by('face'))
  const faceY = useTransform(pitch, by('faceY'))
  const blushX = useTransform(turn, by('blush'))
  const bellyY = useTransform(pitch, by('bellyY'))
  const propX = useTransform(turn, by('prop'))
  const tuftX = useTransform(turn, by('tuft'))
  const tuftY = useTransform(pitch, by('tuftY'))
  const legX = useTransform(turn, by('legs'))
  const wingX = useTransform(turn, by('wing'))
  const torsoSx = useTransform(turn, (t) => 1 - AMP.narrow * Math.abs(t))
  const eyeLSx = useTransform(turn, far('farEye', -1))
  const eyeRSx = useTransform(turn, far('farEye', 1))
  const blushLSx = useTransform(turn, far('farEye', -1))
  const blushRSx = useTransform(turn, far('farEye', 1))
  const wingLS = useTransform(turn, (t) => (t < 0 ? 1 + AMP.farWing * t : 1 + AMP.nearWing * t))
  const wingRS = useTransform(turn, (t) => (t > 0 ? 1 - AMP.farWing * t : 1 - AMP.nearWing * t))
  const blink = useBlink(mood !== 'happy' && mood !== 'grumpy')

  const lift = useVoice(levelRef, listening)
  const pokeSx = useMotionValue(1)
  const pokeSy = useMotionValue(1)
  const hop = useMotionValue(0)
  const flap = useMotionValue(0)
  const sx = useTransform([pokeSx, lift], ([p, l]) => Math.max(AMP.minWide, p * (1 + (reduced ? 0.02 : AMP.voicePuffX) * l)))
  const sy = useTransform([pokeSy, lift], ([p, l]) => Math.min(AMP.maxTall, p * (1 + (reduced ? 0 : AMP.voicePuffY) * l)))
  const bodyY = useTransform([hop, lift], ([h, l]) => h - (reduced ? 0 : AMP.voiceHop * l))
  const shadowS = useTransform(bodyY, (y) => Math.max(0.55, 1 + y / 30))

  // 표정에 따라 — 날개를 들고(excited · happy) · 고개를 갸웃한다(curious)
  const wingMood = useMotionValue(0)
  const tiltMood = useMotionValue(0)
  const wingBase = useSpring(wingMood, SOFT_SPRING)
  const tilt = useSpring(tiltMood, SOFT_SPRING)
  useEffect(() => {
    wingMood.set(mood === 'excited' ? 28 : mood === 'happy' ? 12 : 0)
    tiltMood.set(reduced ? 0 : mood === 'curious' ? -10 : 0)
    // 신나면 제자리에서 두 번 깡충
    if (mood === 'excited' && !reduced) animate(hop, [0, -9, 0, -6, 0], { duration: 0.7, ease: 'easeInOut' })
  }, [mood, reduced, wingMood, tiltMood, hop])
  const lean = useTransform([tilt, turn], ([a, t]) => a + t * AMP.lean)
  const wingL = useTransform([wingBase, lift, flap], ([b, l, f]) => -(b + AMP.voiceWing * l + f))
  const wingR = useTransform([wingBase, lift, flap], ([b, l, f]) => b + AMP.voiceWing * l + f)

  const glowOpacity = useTransform(lift, (l) => (listening ? 0.25 + 0.6 * l : 0.14))
  const glowScale = useTransform(lift, (l) => 0.9 + 0.28 * l)

  /** 누르면 — 아래로 납작 찌그러졌다가 날개를 퍼덕이며 위로 통 튀고, 출렁이며 제자리 */
  const poke = () => {
    onPoke?.()
    if (reduced) {
      animate(pokeSy, [1, 0.94, 1], { duration: 0.28 })
      return
    }
    animate(pokeSy, AMP.pokeSquash, { duration: 0.1, ease: 'easeOut' }).then(() => animate(pokeSy, 1, BOUNCE))
    animate(pokeSx, AMP.pokeWide, { duration: 0.1, ease: 'easeOut' }).then(() => animate(pokeSx, 1, BOUNCE))
    animate(hop, [0, -AMP.pokeHop, 0], { duration: 0.56, delay: 0.1, times: [0, 0.42, 1], ease: ['easeOut', 'easeIn'] })
    animate(flap, [0, AMP.pokeFlap, 4, AMP.pokeFlap * 0.7, 0], { duration: 0.6, delay: 0.08, ease: 'easeInOut' })
  }

  /** 작게 깡충 — 옆으로 퍼지며 웅크렸다가 동그란 채로 떠오르고, 내려앉으며 한 번 더 퍼진다 (고개 돌릴 때 · 가만히 있을 때) */
  const bounce = (height, twice = false) => {
    if (reduced || !height) return
    const times = [0, 0.2, 0.5, 0.78, 1]
    animate(pokeSy, [1, 0.9, 1, 0.94, 1], { duration: 0.46, times, ease: 'easeInOut' })
    animate(pokeSx, [1, 1.09, 1, 1.05, 1], { duration: 0.46, times, ease: 'easeInOut' })
    animate(hop, twice ? [0, 0, -height, 0, -height * 0.5, 0] : [0, 0, -height, 0],
      { duration: twice ? 0.7 : 0.42, times: twice ? [0, 0.12, 0.38, 0.62, 0.8, 1] : [0, 0.22, 0.6, 1], ease: 'easeInOut' })
  }
  // 고개를 반대쪽으로 크게 돌리면 깡충
  const lastSide = useRef(0)
  const lastHop = useRef(0)
  useMotionValueEvent(gazeX, 'change', (v) => {
    const side = Math.abs(v) < GAZE_X * 0.45 ? 0 : Math.sign(v)
    if (!side || side === lastSide.current) return
    lastSide.current = side
    const now = performance.now()
    if (now - lastHop.current < LOOK_HOP_GAP_MS) return
    lastHop.current = now
    bounce(AMP.lookHop)
  })
  // 가만히 있으면 가끔 제자리에서 통통
  useEffect(() => {
    if (!AMP.idleHop || reduced) return undefined
    let t = 0
    const next = () => { t = setTimeout(() => { bounce(3.5, Math.random() < 0.5); next() }, IDLE_HOP_MIN_MS + Math.random() * IDLE_HOP_SPAN_MS) }
    next()
    return () => clearTimeout(t)
  }, [AMP.idleHop, reduced])

  return (
    <button type="button" className="px-chick" data-preset={preset} data-mood={mood} data-form={form} data-listening={listening ? '1' : undefined}
      style={hen ? { '--px-body': 'var(--px-hen)' } : undefined}
      aria-label={`${label} — 누르면 인사해요`} onClick={poke}
      onPointerEnter={(e) => { if (e.pointerType === 'mouse') onHover?.(true) }}
      onPointerLeave={() => onHover?.(false)}>
      <svg ref={box} viewBox="-10 -14 120 118" aria-hidden="true" focusable="false">
        <defs>
          <radialGradient id={glowId}>
            <stop offset="0" stopColor="var(--px-body)" stopOpacity=".9" />
            <stop offset=".55" stopColor="var(--px-body)" stopOpacity=".28" />
            <stop offset="1" stopColor="var(--px-body)" stopOpacity="0" />
          </radialGradient>
          {/* 얼굴 · 배가 보이는 곳 = 몸 윤곽 — 옆으로 돌면 윤곽 너머로 넘어간다 */}
          <clipPath id={clipId}><path d={TORSO} /></clipPath>
          {shell && <ShellDefs id={shellId} />}
        </defs>
        <motion.circle className="px-glow" cx="50" cy="52" r="58" fill={`url(#${glowId})`}
          style={{ opacity: glowOpacity, scale: glowScale, originX: 0.5, originY: 0.5 }} />
        <motion.ellipse className="px-shadow" cx="50" cy="91.5" rx="28" ry="3" style={{ scaleX: shadowS, originX: 0.5, originY: 0.5 }} />

        <motion.g style={{ y: bodyY }}>
          <motion.g style={{ rotate: lean, originX: 0.5, originY: 1 }}>
            <motion.g style={{ scaleX: sx, scaleY: sy, originX: 0.5, originY: 1 }}>
              <g className="px-breath">
                <motion.g className="px-legs" style={{ x: legX }}>
                  {hen ? (
                    <path className="px-hen-feet" d="M37 90.4h8M41 86.5v3.9M55 90.4h8M59 86.5v3.9" />
                  ) : (
                    <>
                      <ellipse className="px-leg-l" cx="41" cy="88.6" rx="3.4" ry="2" />
                      <ellipse className="px-leg-r" cx="59" cy="88.6" rx="3.4" ry="2" />
                    </>
                  )}
                </motion.g>
                {/* 닭 꼬리깃 — 몸 뒤 오른쪽 */}
                {hen && <path className="px-fill px-w24" d="M85 50c6-8 14-8 16-3-3 1-5 3-6 6 4-1 7 1 7 4-4 0-7 2-9 5z" />}

                <motion.g style={{ scaleX: torsoSx, originX: 0.5, originY: 0.5 }}>
                  <path className="px-body" d={TORSO} />
                  <g clipPath={`url(#${clipId})`}>
                    <motion.g style={{ x: blushX, y: faceY }}>
                      <motion.ellipse className="px-blush" cx="31.5" cy="62.5" rx="4.8" ry="2.8" style={{ scaleX: blushLSx, originX: 0.5, originY: 0.5 }} />
                      <motion.ellipse className="px-blush" cx="68.5" cy="62.5" rx="4.8" ry="2.8" style={{ scaleX: blushRSx, originX: 0.5, originY: 0.5 }} />
                    </motion.g>
                    <motion.g style={{ x: faceX, y: faceY }}>
                      <motion.g className="px-eyes" style={{ scaleY: blink, originX: 0.5, originY: 0.5 }}>
                        <Eye cx={37.5} gx={gx} gy={gy} sx={eyeLSx} />
                        <Eye cx={62.5} gx={gx} gy={gy} sx={eyeRSx} />
                      </motion.g>
                      <path className="px-beak" d="M50 58.2c1.9 0 3 .8 3 1.8 0 1.3-1.3 2.3-3 2.3s-3-1-3-2.3c0-1 1.1-1.8 3-1.8z" />
                    </motion.g>
                  </g>
                  {/* 외곽선은 맨 위에 한 번 더 — 얼굴이 윤곽 밑으로 미끄러져 들어가 보인다 */}
                  <path className="px-outline" d={TORSO} />
                </motion.g>

                <motion.path className="px-fill px-w24" d="M12.6 58.5c-5.4.4-8.4 4.4-7.6 8.6 4.4.8 8-1.2 9.2-4.4z"
                  style={{ x: wingX, rotate: wingL, scale: wingLS, originX: 1, originY: 0 }} />
                <motion.path className="px-fill px-w24" d="M87.4 58.5c5.4.4 8.4 4.4 7.6 8.6-4.4.8-8-1.2-9.2-4.4z"
                  style={{ x: wingX, rotate: wingR, scale: wingRS, originX: 0, originY: 0 }} />
                {/* 갓 깬 병아리 — 아래 껍데기를 바지처럼 입었다 */}
                {shell === 'pants' && <ShellPants id={shellId} />}

                <motion.g style={{ x: tuftX, y: tuftY }}>
                  {/* 닭은 새싹 자리에 빨간 볏, 껍데기 모자를 쓰면 새싹은 모자 밑 */}
                  {hen ? <path className="px-comb" d="M38 19c-2-6 3-10 7-7 1-6 9-6 10 0 4-3 9 1 7 7-6 2-18 2-24 0z" />
                    : shell !== 'cap' && <Sprout />}
                  {shell === 'cap' && <ShellCap id={shellId} />}
                </motion.g>

                {/* 들고 있는 소품 — 몸 옆에 끼거나(슬라이드 · 형광펜) 가슴에 단다(로제트). 얼굴 · 볼을 가리지 않는다 */}
                {!hen && (
                  <>
                    <motion.g style={{ x: propX, y: bellyY }}>
                      <HeldProp who={who} />
                    </motion.g>
                    <motion.g style={{ x: tuftX, y: tuftY }}>
                      <HeadProp who={who} />
                    </motion.g>
                  </>
                )}

                <g className="px-emote" transform="translate(3 4)">
                  <path className="px-heart" d="M78 13c2-3 6-1 6 2 0 3-4 5-6 7-2-2-6-4-6-7 0-3 4-5 6-2z" />
                  {/* 물음표는 글자가 아니라 선 — 바깥 font-size 를 물려받아 상자가 커지면 몸의 회전 기준점이 틀어진다 */}
                  <g className="px-mark">
                    <path d="M76.5 9.6c0-2.9 2.3-4.6 4.8-4.6s4.8 1.7 4.8 4.4c0 3.3-4.4 3.5-4.4 7" />
                    <circle cx="81.7" cy="21" r="1.6" />
                  </g>
                  <g className="px-spark">
                    <path d="M86 24l1.1 2.9 2.9 1.1-2.9 1.1-1.1 2.9-1.1-2.9-2.9-1.1 2.9-1.1z" />
                    <path d="M14 22l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z" />
                  </g>
                </g>
              </g>
            </motion.g>
          </motion.g>
        </motion.g>
      </svg>
    </button>
  )
}
