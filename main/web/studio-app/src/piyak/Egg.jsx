/* 삐약이가 태어나기 전 — 알 · 금 간 알 · 알 깨기(위 껍데기를 들고 빼꼼). 삐약이와 같은 그림체 · 같은 초록 외곽선 (Shell.jsx).
   알은 가끔 혼자 들썩이고(금 간 알은 더 자주 · 더 크게), 누르면 흔들린다. 알 깨기에서는 틈 사이 눈이 커서를 본다 */
import { useEffect, useId, useRef } from 'react'
import { motion, useMotionValue, useSpring, useTransform, useReducedMotion, animate } from 'motion/react'
import { useGaze, Sprout } from './Piyak.jsx'
import { ShellDefs, ShellPiece } from './Shell.jsx'

const WOBBLE = {
  egg: { every: [4200, 3000], deg: 5 },     // [최소 간격, 더하는 간격(ms)], 기울기(°)
  crack: { every: [1600, 1400], deg: 9 },
  peek: { every: [3200, 2400], deg: 4 },
}
const EYE_SPRING = { stiffness: 260, damping: 20, mass: 0.6 }

/** stage: egg · crack · peek */
export function Egg({ stage = 'egg', onPoke, label = '삐약이 알' }) {
  const reduced = useReducedMotion()
  const box = useRef(null)
  const id = `pxe${useId().replace(/:/g, '')}`
  const tilt = useMotionValue(0)
  const hop = useMotionValue(0)
  const lid = useMotionValue(0)        // 위 껍데기가 들린 정도 0..1 (peek) — 위로 11 · 왼쪽으로 14°
  const lidY = useTransform(lid, (v) => v * -11)
  const lidTurn = useTransform(lid, (v) => v * -14)
  const { gx: gazeX, gy: gazeY } = useGaze(box, !reduced)
  const gx = useSpring(gazeX, EYE_SPRING)
  const gy = useSpring(gazeY, EYE_SPRING)
  const blink = useMotionValue(1)

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

  // 알 깨기 — 위 껍데기가 들렸다 내려앉았다 (빼꼼), 틈 사이 눈은 가끔 깜빡
  useEffect(() => {
    if (stage !== 'peek') { lid.set(0); return undefined }
    const a = reduced ? (lid.set(1), null) : animate(lid, [0.75, 1, 0.85, 1], { duration: 2.4, repeat: Infinity, ease: 'easeInOut' })
    let t = 0
    const next = () => { t = setTimeout(() => { animate(blink, [1, 0.12, 1], { duration: 0.22 }); next() }, 2200 + Math.random() * 3000) }
    next()
    return () => { a?.stop(); clearTimeout(t) }
  }, [stage, reduced, lid, blink])

  const poke = () => { onPoke?.(); wobble((WOBBLE[stage] || WOBBLE.egg).deg + 4) }
  const peek = stage === 'peek'

  return (
    <button type="button" className="px-chick px-egg-btn" data-stage={stage} aria-label={`${label} — 누르면 흔들려요`} onClick={poke}>
      <svg ref={box} viewBox="-10 -14 120 118" aria-hidden="true" focusable="false">
        <defs><ShellDefs id={id} /></defs>
        <ellipse className="px-shadow" cx="50" cy="91.5" rx="22" ry="3" />
        <motion.g style={{ y: hop }}>
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
              <>
                <ShellPiece id={id} part="whole" crack={stage === 'crack'} />
                <Sprout scale={0.8} y={14} />
              </>
            )}
          </motion.g>
        </motion.g>
      </svg>
    </button>
  )
}
