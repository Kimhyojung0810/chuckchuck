/* 정거장마다 자라는 삐약이 — 리허설 흐름을 따라 큰다 (10-13 사용자: 「studio 에 반영 · 그 flow 따라서 성장」).
   ① 자료 올리기 = 알 (Live Orb — 캡슐 눈이 커서를 보고, 말을 걸면 빛난다)
   ② 발표 = 금 간 알 (앱이 재는 발표 음량에 빛나고, 말할수록 금이 길어진다)
   ③ 질의응답 = 들어오면 알을 깨고 나와 껍데기 바지
   ④ 리포트 = 껍데기 모자를 쓰고 기뻐한다. 발표까지 마친 리허설이 HEN_AFTER 번이면 닭
   정거장 넷이 곡선 위에 같이 떠 있어서, 미끄러지는 동안 옆 창에 지난 · 다음 모습이 비친다 */
import { useEffect, useRef, useState } from 'react'
import { Hatch } from './Hatch.jsx'
import { voiceK } from './logic.js'

export const HEN_AFTER = 3
const GROWN_KEY = 'cheokcheok:piyak-grown'     // 발표까지 마치고 리포트에 온 횟수 (이 브라우저)
const HATCH_MS = 1700                          // ③ 에 들어와 빼꼼하는 시간 — 그다음 껍데기 바지로
const CRACK_PER_SEC = 0.004                    // 말이 없어도 조금씩 (4분이면 끝까지)
const CRACK_PER_VOICE = 0.03                   // 말소리가 크면 더 빨리

let presented = false   // 이번 페이지에서 ② 발표를 지났는가 — 리포트만 다시 열어선 자라지 않게

function readGrown() {
  try { return Number(localStorage.getItem(GROWN_KEY)) || 0 } catch (_) { return 0 }   // 사생활 모드
}
function bumpGrown() {
  const n = readGrown() + 1
  try { localStorage.setItem(GROWN_KEY, String(n)) } catch (_) { /* 사생활 모드 — 이번만 */ }
  return n
}

const LINES = {
  egg: '자료를 올리면 알이 깨어날 준비를 해요',
  listen: '듣고 있어요 — 말하면 알이 빛나요',
  crack: '발표할수록 금이 가요',
  peek: '빼꼼…',
  pants: '삐약! 이제 질문할게요',
  cap: '다 했어요! 리포트를 봐요',
  hen: '연습을 많이 해서 닭이 됐어요',
}

/**
 * k: 정거장(0..3) · active: 지금 정거장인가
 * mic: media.js useMicLevel() — ① 에서 말 걸기 · readAppLevel: () => 0..1 앱 발표 음량 (② 에서)
 */
export function Companion({ k, active, mic, readAppLevel }) {
  const first = k === 0 ? 'egg' : k === 1 ? 'crack' : k === 2 ? 'pants' : (readGrown() >= HEN_AFTER ? 'hen' : 'cap')
  const [stage, setStage] = useState(first)
  const [crack, setCrack] = useState(0.15)
  const [micError, setMicError] = useState(false)
  const crackRef = useRef(0.15)

  const readLevel = k === 0
    ? () => (mic?.on ? voiceK(mic.level.current) : 0)
    : k === 1 ? () => readAppLevel?.() || 0 : undefined

  // ② 발표하는 동안 금이 길어진다
  useEffect(() => {
    if (k !== 1 || !active) return undefined
    presented = true
    let last = performance.now()
    const id = setInterval(() => {
      const now = performance.now()
      const dt = (now - last) / 1000
      last = now
      crackRef.current = Math.min(1, crackRef.current + dt * (CRACK_PER_SEC + CRACK_PER_VOICE * (readLevel?.() || 0)))
      setCrack(crackRef.current)
    }, 400)
    return () => clearInterval(id)
  }, [k, active])   // readLevel 은 같은 일을 한다

  // ③ 들어오면 알을 깨고 나온다
  useEffect(() => {
    if (k !== 2 || !active) return undefined
    setStage('peek')
    const t = setTimeout(() => setStage('pants'), HATCH_MS)
    return () => clearTimeout(t)
  }, [k, active])

  // ④ 발표까지 마치고 왔으면 한 번 센다 → HEN_AFTER 번째부터 닭
  useEffect(() => {
    if (k !== 3 || !active || !presented) return
    presented = false
    setStage(bumpGrown() >= HEN_AFTER ? 'hen' : 'cap')
  }, [k, active])

  const toggleMic = async () => {
    if (mic.on) { mic.stop(); return }
    setMicError(false)
    if (!(await mic.start())) setMicError(true)
  }
  const line = stage === 'egg' && mic?.on ? LINES.listen : LINES[stage]

  return (
    <div className="px-companion">
      <Hatch stage={stage} line={line} egg={{ readLevel, crack }} />
      {k === 0 && mic && (
        <div className="px-mic">
          <button className="ds-btn ds-btn--sm" type="button" onClick={toggleMic} aria-pressed={mic.on}>
            {mic.on ? '마이크 끄기' : '알에게 말 걸기'}
          </button>
          {micError
            ? <span className="px-mic__note px-mic__note--error">마이크를 쓸 수 없어요. 주소창에서 마이크 권한을 켜면 다시 할 수 있어요.</span>
            : mic.on && <span className="px-mic__note ds-mono">소리 크기만 봐요 · 녹음하지 않아요</span>}
        </div>
      )}
    </div>
  )
}
