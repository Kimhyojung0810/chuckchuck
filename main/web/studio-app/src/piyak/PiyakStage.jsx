/* 삐약이 자리 — 표정을 고르고, 지금 무엇을 하는지 한 줄로 말하고, 마이크를 켜고 끈다.
   어느 창에도 묶이지 않는다: ① 창 안이든 정거장 세트든 <PiyakStage mic={useMicLevel()} /> 하나로 놓는다.
   mic 이 없으면 마이크 버튼 없이 숨 · 눈 · 누르기만 한다. 녹음은 하지 않는다 — 소리 크기만 본다 (media.js) */
import { useEffect, useRef, useState } from 'react'
import { Piyak } from './Piyak.jsx'
import { pickMood, voiceK } from './logic.js'

const POKE_MS = 1300          // 누른 뒤 기뻐하는 시간
const LOUD_ON = 0.55          // 이만큼 크게 …
const LOUD_HOLD_MS = 280      // … 이만큼 이어 말하면 신난다
const LOUD_OFF = 0.3
const LOUD_REST_MS = 900

const LINES = {
  neutral: '안녕하세요, 삐약이예요. 자료를 올리면 같이 볼게요',
  happy: '삐약! 반가워요',
  curious: '무슨 발표인지 궁금해요',
  listening: '듣고 있어요 — 말하면 따라 움직여요',
  excited: '잘 들려요!',
  grumpy: '조금 더 연습해 볼까요',
}

/** 크게 말하는지 — 잠깐 튄 소리는 넘기고, 이어서 크게 말할 때만 */
function useLoud(levelRef, on) {
  const [loud, setLoud] = useState(false)
  useEffect(() => {
    if (!on) { setLoud(false); return undefined }
    let since = 0
    let state = false
    const id = setInterval(() => {
      const k = voiceK(levelRef?.current || 0)
      const want = state ? k > LOUD_OFF : k > LOUD_ON
      const now = performance.now()
      if (want === state) { since = 0; return }
      if (!since) since = now
      if (now - since >= (state ? LOUD_REST_MS : LOUD_HOLD_MS)) { state = want; since = 0; setLoud(want) }
    }, 90)
    return () => clearInterval(id)
  }, [levelRef, on])
  return loud
}

export function PiyakStage({ mic, mood: fixed, className = '', preset }) {
  const [poked, setPoked] = useState(false)
  const [hovered, setHovered] = useState(false)
  const [micError, setMicError] = useState(false)
  const timer = useRef(0)
  const listening = !!mic?.on
  const loud = useLoud(mic?.level, listening)
  const mood = pickMood({ fixed, poked, loud, listening, hovered })
  useEffect(() => () => clearTimeout(timer.current), [])

  const onPoke = () => {
    setPoked(true)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setPoked(false), POKE_MS)
  }
  const toggleMic = async () => {
    if (mic.on) { mic.stop(); return }
    setMicError(false)
    const ok = await mic.start()
    if (!ok) setMicError(true)
  }
  const line = mood === 'curious' && listening ? LINES.listening : LINES[mood]

  return (
    <div className={`px-stage ${className}`}>
      <Piyak mood={mood} levelRef={mic?.level} listening={listening} onPoke={onPoke} onHover={setHovered} preset={preset} />
      <p className="px-line" aria-live="polite">{line}</p>
      {mic && (
        <div className="px-mic">
          <button className="ds-btn ds-btn--sm" type="button" onClick={toggleMic} aria-pressed={listening}>
            {listening ? '마이크 끄기' : '삐약이에게 말 걸기'}
          </button>
          {micError
            ? <span className="px-mic__note px-mic__note--error">마이크를 쓸 수 없어요. 주소창에서 마이크 권한을 켜면 다시 할 수 있어요.</span>
            : listening && <span className="px-mic__note ds-mono">소리 크기만 봐요 · 녹음하지 않아요</span>}
        </div>
      )}
    </div>
  )
}
