/* 삐약이가 자라는 이야기 — 알 → 금 간 알 → 알 깨기 → 껍데기 바지 → 껍데기 모자 → 병아리 → 닭 (10-13 사용자).
   단계 하나를 그리거나(stage), 「처음부터 보기」로 차례로 넘긴다(play). 단계가 바뀔 때 통 튀며 바뀐다 */
import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { Piyak } from './Piyak.jsx'
import { Egg } from './Egg.jsx'

export const STAGES = [
  { key: 'egg', name: '알', line: '알 속에서 꿈틀대요', hold: 1800 },
  { key: 'crack', name: '금 간 알', line: '지지직 — 금이 가요', hold: 3800 },
  { key: 'peek', name: '알 깨기', line: '빼꼼, 밖이 궁금해요', hold: 2600 },
  { key: 'pants', name: '껍데기 바지', line: '삐약! 나왔어요', hold: 2200, piyak: { shell: 'pants', mood: 'excited' } },
  { key: 'cap', name: '껍데기 모자', line: '껍데기는 모자로 써요', hold: 2200, piyak: { shell: 'cap', mood: 'happy' } },
  { key: 'chick', name: '병아리', line: '안녕하세요, 삐약이예요', hold: 2000, piyak: {} },
  { key: 'hen', name: '닭', line: '발표 연습을 많이 하면 닭이 돼요', hold: 0, piyak: { form: 'hen' } },
]
const POP = { type: 'spring', stiffness: 420, damping: 18 }
const POKE_MS = 1200

/**
 * stage: STAGES 의 key · play: true 면 지금 단계부터 끝까지 넘긴다 · onStage(key): 단계가 바뀔 때
 * line: 단계 문구 대신 쓸 말 · egg: 알 단계에 넘길 것(readLevel · crack) · piyak: 병아리 단계에 넘길 것(levelRef · listening …)
 */
export function Hatch({ stage = 'egg', play = false, onStage, onDone, line, egg, piyak }) {
  const reduced = useReducedMotion()
  const [poked, setPoked] = useState(false)
  const timer = useRef(0)
  const i = Math.max(0, STAGES.findIndex((s) => s.key === stage))
  const s = STAGES[i]

  useEffect(() => {
    if (!play) return undefined
    if (!s.hold || i >= STAGES.length - 1) { onDone?.(); return undefined }
    const t = setTimeout(() => onStage?.(STAGES[i + 1].key), s.hold)
    return () => clearTimeout(t)
  }, [play, i, s.hold, onStage, onDone])
  useEffect(() => () => clearTimeout(timer.current), [])

  const onPoke = () => {
    setPoked(true)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setPoked(false), POKE_MS)
  }
  const mood = poked ? 'happy' : s.piyak?.mood

  return (
    <div className="px-stage px-hatch">
      <div className="px-hatch__art">
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.div key={s.key} className="px-hatch__frame"
            initial={reduced ? { opacity: 0 } : { opacity: 0, scale: 0.82, y: 6 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={reduced ? { opacity: 0 } : { opacity: 0, scale: 1.08 }}
            transition={reduced ? { duration: 0.2 } : POP}>
            {s.piyak
              ? <Piyak {...piyak} {...s.piyak} mood={mood} onPoke={onPoke} label={s.name} />
              : <Egg {...egg} stage={s.key} onPoke={onPoke} label={s.name} />}
          </motion.div>
        </AnimatePresence>
      </div>
      <p className="px-line" aria-live="polite">{line || s.line}</p>
    </div>
  )
}
