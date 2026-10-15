/* 삐약이가 태어나기 전 — 알 · 금 간 알 · 알 깨기(위 껍데기를 들고 빼꼼). 삐약이와 같은 그림체 · 같은 초록 외곽선 (Shell.jsx).
   알은 가끔 혼자 들썩이고(금 간 알은 더 자주 · 더 크게), 누르면 흔들린다.
   알 · 금 간 알은 Live Orb 처럼 (10-13 사용자: 「알일 때 이거 할 수 있겠다」 — 21st.dev live-orb, 커서를 따라가는 캡슐 눈 두 개 달린 구):
   껍데기 너머로 캡슐 눈이 비쳐 커서를 보고, 속에서 노란 빛이 숨 쉬듯 일렁이다가 목소리(readLevel)에 맞춰 밝아지고 볼록해진다.
   알 깨기에서는 틈 사이 점 눈이 커서를 본다 */
import { useEffect, useId, useRef, useState } from 'react'
import { motion, useMotionValue, useSpring, useTransform, useAnimationFrame, useReducedMotion, animate } from 'motion/react'
import { useGaze, Sprout } from './Piyak.jsx'
import { ShellDefs, ShellPiece, EGG } from './Shell.jsx'

const WOBBLE = {
  egg: { every: [4200, 3000], deg: 5 },     // [최소 간격, 더하는 간격(ms)], 기울기(°)
  crack: { every: [1600, 1400], deg: 9 },
  peek: { every: [3200, 2400], deg: 4 },
}
const EYE_SPRING = { stiffness: 260, damping: 20, mass: 0.6 }
/* Live Orb 눈 — 10-13 사용자: 「live-orb 처럼 적극적으로」 → 「아직 마우스 따라가는 눈이 이상해」.
   마우스가 화면 안에 있으면 멈춰 있어도 계속 커서를 본다(stay) — 혼자 두리번은 마우스가 나갔거나 손가락을 뗐을 때만.
   크게(ORB_GAZE) 움직이되 출렁이지 않고 부드럽게 붙어 따라간다(ORB_SPRING, 지나치지 않음).
   알 가장자리로 갈수록 구 표면을 돌아가듯 좁아진다(WRAP). 속도로 늘이기 · 알 기울이기는 출렁여 보여서 뺐다 */
const ORB_GAZE = 2.6
const ORB_SPRING = { stiffness: 320, damping: 34, mass: 0.6 }
const ORB_PACE = { reach: 0.25, idle: 900, glance: [700, 1100], front: 0.25, stay: true }
const WRAP = 0.3               // 가장자리에서 이만큼 좁아진다
const ORB_X = 4.2 * ORB_GAZE   // 눈이 갈 수 있는 끝 (GAZE_X × ORB_GAZE)
/* 금 — 눈 아래를 가로지르는 지그재그 (10-13 사용자: 「눈 아래에서」 · 「진짜 지지직」 · 「테두리랑 닿아 있어야 자연스럽다」).
   알 테두리 바깥(x 11)에서 시작해 알 모양으로 잘라 그리니, 금이 테두리에서 시작하고 끝까지 가면 반대쪽 테두리에 닿는다.
   crack(0..1) 을 마디 수로 바꿔 한 마디씩 끊어지며 간다 — 새 마디가 생길 때마다 알이 파르르, 끝이 번쩍, 부스러기가 튄다.
   가만히 있어도 가끔 지직거린다(CRACKLE). 마디 몇 곳에서 잔금이 갈라진다(TWIGS) */
const CRACK_Y = [64, 69, 63.5, 68.5, 63, 68, 64, 69, 63.5, 68, 64, 68.5, 63.5, 67.5]
const CRACK_PTS = CRACK_Y.map((y, i) => [11 + i * 6.2, y])
const CRACK_N = CRACK_PTS.length - 1
const TWIGS = { 4: [2.2, -5], 8: [1.4, 5.2], 11: [2.4, -4.6] }   // 마디 번호 → 잔금 방향
const CRACKLE = [1300, 1700]
const crackPath = (k) => 'M' + CRACK_PTS.slice(0, k + 1).map(([x, y]) => `${x} ${y}`).join('L')
const segPath = (k) => { const [a, b] = [CRACK_PTS[k - 1], CRACK_PTS[k]]; return `M${a[0]} ${a[1]}L${b[0]} ${b[1]}` }

/** 금 간 알의 금 — 지지직. onTick(): 알을 파르르 떨게 한다 */
function Crack({ id, amount, reduced, onTick }) {
  const k = Math.max(1, Math.min(CRACK_N, Math.round(amount * CRACK_N)))
  const [ticks, setTicks] = useState([])     // 번쩍 · 부스러기 — 지직할 때마다 하나
  const seq = useRef(0)
  const prevK = useRef(k)
  const tick = (at) => {
    onTick?.()
    if (reduced) return
    const n = ++seq.current
    setTicks((t) => [...t.slice(-3), { n, at }])
    setTimeout(() => setTicks((t) => t.filter((x) => x.n !== n)), 650)
  }
  // 새 마디가 생기면 지직
  useEffect(() => { if (k > prevK.current) tick(k); prevK.current = k }, [k])
  // 가만히 있어도 가끔 지직 (끝에서)
  useEffect(() => {
    let t = 0
    const next = () => { t = setTimeout(() => { tick(prevK.current); next() }, CRACKLE[0] + Math.random() * CRACKLE[1]) }
    next()
    return () => clearTimeout(t)
  }, [reduced])
  const line = { fill: 'none', stroke: 'var(--px-line)', strokeLinecap: 'round', strokeLinejoin: 'round' }
  return (
    <g clipPath={`url(#${id}-egg)`}>
      <path d={crackPath(k)} {...line} strokeWidth="2.2" />
      {Object.entries(TWIGS).filter(([v]) => Number(v) <= k).map(([v, [dx, dy]]) => {
        const [x, y] = CRACK_PTS[v]
        return <motion.path key={v} d={`M${x} ${y}l${dx} ${dy}`} {...line} strokeWidth="1.5"
          initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.18 }} />
      })}
      {ticks.map(({ n, at }) => {
        const [x, y] = CRACK_PTS[at]
        return (
          <g key={n}>
            {/* 끝이 번쩍 — 방금 갈라진 마디가 굵었다 가늘어진다 */}
            <motion.path d={segPath(at)} {...line} initial={{ strokeWidth: 4.2, opacity: 1 }} animate={{ strokeWidth: 2.2, opacity: 0 }}
              transition={{ duration: 0.35, ease: 'easeOut' }} />
            {/* 부스러기 셋 — 끝에서 튀어 나갔다 사라진다 */}
            {[[-4, -6, 1.1], [3, -7.5, 0.9], [5, -3, 0.8]].map(([dx, dy, r], j) => (
              <motion.circle key={j} cx={x} cy={y} r={r} fill="var(--px-egg)" stroke="var(--px-line)" strokeWidth=".7"
                initial={{ x: 0, y: 0, opacity: 1 }} animate={{ x: dx, y: dy, opacity: 0 }}
                transition={{ duration: 0.5, ease: 'easeOut', delay: j * 0.03 }} />
            ))}
          </g>
        )
      })}
    </g>
  )
}

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
  const eyeSx = useTransform(ox, (x) => 1 - WRAP * Math.min(1, Math.abs(x) / ORB_X))

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

  /** 들썩 — 좌우로 기울었다 돌아온다 (뛰지는 않는다 — 10-13 사용자 「알에서는 점프 모션 없어도 될듯」) */
  const wobble = (deg) => {
    if (reduced) return
    animate(tilt, [0, -deg, deg * 0.8, -deg * 0.45, deg * 0.2, 0], { duration: 0.7, ease: 'easeInOut' })
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

  /** 지직 — 알이 짧게 파르르 */
  const shiver = () => {
    if (reduced) return
    animate(tilt, [tilt.get(), -1.6, 1.4, -0.9, 0.5, 0], { duration: 0.2, ease: 'linear' })
  }

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
        <g>
          <motion.g style={{ rotate: tilt, originX: 0.5, originY: 1 }}>
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
                    <motion.g className="px-orb-eyes" style={{ scaleX: eyeSx, scaleY: blink, originX: 0.5, originY: 0.5 }}>
                      <rect x="37.2" y="47" width="5.6" height="11" rx="2.8" />
                      <rect x="57.2" y="47" width="5.6" height="11" rx="2.8" />
                    </motion.g>
                  </motion.g>
                </g>
                <path className="px-egg-line" d={EGG} />
                {stage === 'crack' && <Crack id={id} amount={crack} reduced={reduced} onTick={shiver} />}
                <Sprout scale={0.8} y={14} />
              </motion.g>
            )}
          </motion.g>
        </g>
      </svg>
    </button>
  )
}
