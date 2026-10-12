/* 삐약이가 태어나기 전 — 알 · 금 간 알 · 알 깨기(위 껍데기를 들고 빼꼼). 삐약이와 같은 그림체 · 같은 초록 외곽선 (Shell.jsx).
   알은 가끔 혼자 들썩이고(금 간 알은 더 자주 · 더 크게), 누르면 흔들린다.
   알 · 금 간 알은 Live Orb 처럼 (10-13 사용자: 「알일 때 이거 할 수 있겠다」 — 21st.dev live-orb, 커서를 따라가는 캡슐 눈 두 개 달린 구):
   껍데기 너머로 캡슐 눈이 비쳐 커서를 보고, 속에서 노란 빛이 숨 쉬듯 일렁이다가 목소리(readLevel)에 맞춰 밝아지고 볼록해진다.
   알 깨기에서는 틈 사이 점 눈이 커서를 본다 */
import { useEffect, useId, useRef } from 'react'
import { motion, useMotionValue, useSpring, useTransform, useVelocity, useAnimationFrame, useReducedMotion, animate } from 'motion/react'
import { useGaze, Sprout } from './Piyak.jsx'
import { ShellDefs, ShellPiece, EGG } from './Shell.jsx'

const WOBBLE = {
  egg: { every: [4200, 3000], deg: 5 },     // [최소 간격, 더하는 간격(ms)], 기울기(°)
  crack: { every: [1600, 1400], deg: 9 },
  peek: { every: [3200, 2400], deg: 4 },
}
const EYE_SPRING = { stiffness: 260, damping: 20, mass: 0.6 }
/* Live Orb 눈 — 10-13 사용자: 「진짜 live-orb 처럼 적극적으로 눈이 움직여야 귀엽다」.
   크게(ORB_GAZE) · 휙(ORB_SPRING, 살짝 지나쳤다 돌아옴) 움직이고, 빠를수록 캡슐이 옆으로 늘며 납작해지고(SMEAR),
   알 가장자리로 갈수록 구 표면을 돌아가듯 좁아진다(WRAP). 커서가 멈추면 금방 혼자 휙휙 둘러본다(ORB_PACE) */
const ORB_GAZE = 2.6
const ORB_SPRING = { stiffness: 420, damping: 17, mass: 0.5 }
const ORB_PACE = { reach: 0.25, idle: 900, glance: [450, 900], front: 0.2 }
const SMEAR = 90               // 이 속도(단위/초)에서 가장 많이 늘어난다
const WRAP = 0.3               // 가장자리에서 이만큼 좁아진다
const ORB_X = 4.2 * ORB_GAZE   // 눈이 갈 수 있는 끝 (GAZE_X × ORB_GAZE)
/** 금이 가는 길 — crack(0..1) 만큼 그려진다. 눈 아래를 가로지른다 (10-13 사용자: 「눈 아래에서 금 가는 게 좋을듯」) */
const CRACK = 'M21 66l6 4 5-5 6 5 5-5 6 5 5-5 6 5 5-5 6 4 5-3'

/** 목소리 0..1 — 빨리 오르고 천천히 내려온다 */
function useLevel(readLevel) {
  const level = useMotionValue(0)
  const s = useRef(0)
  useAnimationFrame(() => {
    const raw = readLevel ? Math.max(0, Math.min(1, readLevel() || 0)) : 0
    s.current += (raw - s.current) * (raw > s.current ? 0.4 : 0.1)
    if (Math.abs(s.current - level.get()) > 0.002) level.set(s.current)
  })
  return level
}

/**
 * stage: egg · crack · peek
 * readLevel: () => 0..1 목소리 크기 (없으면 숨쉬기만) · crack: 금 간 알의 금 길이 0..1 (없으면 반쯤)
 */
export function Egg({ stage = 'egg', readLevel, crack = 0.45, onPoke, label = '삐약이 알' }) {
  const reduced = useReducedMotion()
  const box = useRef(null)
  const id = `pxe${useId().replace(/:/g, '')}`
  const tilt = useMotionValue(0)
  const hop = useMotionValue(0)
  const lid = useMotionValue(0)        // 위 껍데기가 들린 정도 0..1 (peek) — 위로 11 · 왼쪽으로 14°
  const lidY = useTransform(lid, (v) => v * -11)
  const lidTurn = useTransform(lid, (v) => v * -14)
  const { gx: gazeX, gy: gazeY } = useGaze(box, !reduced, stage === 'peek' ? undefined : ORB_PACE)
  const gx = useSpring(gazeX, EYE_SPRING)
  const gy = useSpring(gazeY, EYE_SPRING)
  const blink = useMotionValue(1)
  // 캡슐 눈 — 크게 · 휙 · 빠르면 늘어나고 · 가장자리는 좁게
  const ox = useSpring(useTransform(gazeX, (v) => v * ORB_GAZE), ORB_SPRING)
  const oy = useSpring(useTransform(gazeY, (v) => v * ORB_GAZE), ORB_SPRING)
  const vx = useVelocity(ox)
  const vy = useVelocity(oy)
  const smear = useTransform([vx, vy], ([a, b]) => Math.min(1, Math.hypot(a, b) / SMEAR))
  const eyeSx = useTransform([smear, ox], ([m, x]) => (1 + 0.45 * m) * (1 - WRAP * Math.min(1, Math.abs(x) / ORB_X)))
  const eyeSy = useTransform([smear, blink], ([m, b]) => (1 - 0.3 * m) * b)
  const lean = useTransform([tilt, ox], ([t, x]) => t + x * 0.5)   // 알도 그쪽으로 살짝 기운다

  // Live Orb — 속빛은 숨 쉬듯(breath) 일렁이고 목소리(level)에 밝아진다. 알은 옆으로만 볼록 (세로로 늘지 않는다)
  const level = useLevel(readLevel)
  const breath = useMotionValue(0)
  useEffect(() => {
    if (reduced) return undefined
    const a = animate(breath, [0, 1, 0], { duration: 3.2, repeat: Infinity, ease: 'easeInOut' })
    return () => a.stop()
  }, [reduced, breath])
  const glowOpacity = useTransform([breath, level], ([b, l]) => 0.3 + 0.18 * b + 0.5 * l)
  const glowScale = useTransform([breath, level], ([b, l]) => 0.86 + 0.08 * b + 0.3 * l)
  const puffX = useTransform(level, (l) => 1 + (reduced ? 0.01 : 0.06) * l)
  const puffY = useTransform(level, (l) => 1 + (reduced ? 0 : 0.01) * l)
  const haloOpacity = useTransform(level, (l) => 0.12 + 0.55 * l)
  const haloScale = useTransform(level, (l) => 0.9 + 0.3 * l)

  /** 들썩 — 좌우로 기울었다 돌아오고 살짝 뜬다 */
  const wobble = (deg) => {
    if (reduced) return
    animate(tilt, [0, -deg, deg * 0.8, -deg * 0.45, deg * 0.2, 0], { duration: 0.7, ease: 'easeInOut' })
    animate(hop, [0, -2.5, 0, -1.2, 0], { duration: 0.7, ease: 'easeInOut' })
  }
  useEffect(() => {
    const w = WOBBLE[stage] || WOBBLE.egg
    let t = 0
    const next = () => { t = setTimeout(() => { wobble(w.deg); next() }, w.every[0] + Math.random() * w.every[1]) }
    next()
    return () => clearTimeout(t)
  }, [stage, reduced])   // wobble 은 매번 같은 일을 한다

  // 눈 깜빡임 (캡슐 눈 · 점 눈 모두), 알 깨기는 위 껍데기가 들렸다 내려앉았다 (빼꼼)
  useEffect(() => {
    let t = 0
    const next = () => { t = setTimeout(() => { animate(blink, [1, 0.12, 1], { duration: 0.22 }); next() }, 2400 + Math.random() * 3200) }
    next()
    if (stage !== 'peek') { lid.set(0); return () => clearTimeout(t) }
    const a = reduced ? (lid.set(1), null) : animate(lid, [0.75, 1, 0.85, 1], { duration: 2.4, repeat: Infinity, ease: 'easeInOut' })
    return () => { a?.stop(); clearTimeout(t) }
  }, [stage, reduced, lid, blink])

  const poke = () => { onPoke?.(); wobble((WOBBLE[stage] || WOBBLE.egg).deg + 4) }
  const peek = stage === 'peek'

  return (
    <button type="button" className="px-chick px-egg-btn" data-stage={stage} aria-label={`${label} — 누르면 흔들려요`} onClick={poke}>
      <svg ref={box} viewBox="-10 -14 120 118" aria-hidden="true" focusable="false">
        <defs>
          <ShellDefs id={id} />
          <radialGradient id={`${id}-glow`}>
            <stop offset="0" stopColor="var(--px-body)" stopOpacity="1" />
            <stop offset=".6" stopColor="var(--px-body)" stopOpacity=".45" />
            <stop offset="1" stopColor="var(--px-body)" stopOpacity="0" />
          </radialGradient>
        </defs>
        {!peek && (
          <motion.ellipse className="px-orb-halo" cx="50" cy="56" rx="44" ry="44" fill={`url(#${id}-glow)`}
            style={{ opacity: haloOpacity, scale: haloScale, originX: 0.5, originY: 0.5 }} />
        )}
        <ellipse className="px-shadow" cx="50" cy="91.5" rx="22" ry="3" />
        <motion.g style={{ y: hop }}>
          <motion.g style={{ rotate: lean, originX: 0.5, originY: 1 }}>
            {peek ? (
              <>
                {/* 안에 있는 삐약이 — 틈 위로 눈만 보인다 */}
                <g clipPath={`url(#${id}-egg)`}>
                  <ellipse className="px-body" cx="50" cy="56" rx="27" ry="26" />
                  <motion.g style={{ x: gx, y: gy }}>
                    <motion.g style={{ scaleY: blink, originX: 0.5, originY: 0.5 }}>
                      <circle className="px-eye-ball" cx="40.5" cy="45.5" r="2.8" />
                      <circle className="px-eye-ball" cx="59.5" cy="45.5" r="2.8" />
                    </motion.g>
                  </motion.g>
                </g>
                <ShellPiece id={id} part="bottom" />
                <motion.g style={{ y: lidY, rotate: lidTurn, originX: 0.25, originY: 0.9 }}>
                  <ShellPiece id={id} part="top" />
                  <Sprout scale={0.8} y={14} />
                </motion.g>
              </>
            ) : (
              <motion.g style={{ scaleX: puffX, scaleY: puffY, originX: 0.5, originY: 1 }}>
                <ShellPiece id={id} part="whole" />
                {/* 껍데기 너머 — 속빛과 캡슐 눈 (알 모양 안에서만) */}
                <g clipPath={`url(#${id}-egg)`}>
                  <motion.ellipse className="px-orb-glow" cx="50" cy="58" rx="26" ry="28" fill={`url(#${id}-glow)`}
                    style={{ opacity: glowOpacity, scale: glowScale, originX: 0.5, originY: 0.5 }} />
                  <motion.g style={{ x: ox, y: oy }}>
                    <motion.g className="px-orb-eyes" style={{ scaleX: eyeSx, scaleY: eyeSy, originX: 0.5, originY: 0.5 }}>
                      <rect x="37.2" y="47" width="5.6" height="11" rx="2.8" />
                      <rect x="57.2" y="47" width="5.6" height="11" rx="2.8" />
                    </motion.g>
                  </motion.g>
                </g>
                <path className="px-egg-line" d={EGG} />
                {stage === 'crack' && (
                  <motion.path className="px-crack" d={CRACK} clipPath={`url(#${id}-egg)`}
                    initial={false} animate={{ pathLength: Math.max(0.12, Math.min(1, crack)) }}
                    transition={{ type: 'spring', stiffness: 60, damping: 14 }} />
                )}
                <Sprout scale={0.8} y={14} />
              </motion.g>
            )}
          </motion.g>
        </motion.g>
      </svg>
    </button>
  )
}
