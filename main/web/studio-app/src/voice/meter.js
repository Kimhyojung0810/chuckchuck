// 음량 재기 — 브라우저 오디오. 앱의 녹음 · 받아쓰기 · 카메라는 건드리지 않고, 재기 전용 마이크를 따로 열고 따로 닫는다.

/** iPhone · iPad 는 마이크를 두 번 열면 먼저 연 쪽(녹음 · 받아쓰기)이 끊길 수 있다 — 거기서는 재기용 마이크를 열지 않는다 */
export function canOpenSecondMic() {
  if (typeof navigator === 'undefined' || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return false
  const ua = navigator.userAgent || ''
  const iOS = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
  return !iOS
}

function rmsOf(analyser, buf) {
  analyser.getFloatTimeDomainData(buf)
  let sum = 0
  for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i]
  return Math.sqrt(sum / buf.length)
}

/** 재기 전용 마이크 — open() 은 실패해도 던지지 않는다(read() 가 null 이면 신호 없음) */
export function createMicMeter() {
  let ac = null
  let stream = null
  let analyser = null
  let buf = null
  let opening = null
  let closed = false
  let failed = false // 한 번 막혔으면 이번 말하기 동안은 다시 묻지 않는다(close 가 풀어 준다)

  async function open() {
    if (opening || analyser || failed || !canOpenSecondMic()) return opening
    closed = false
    opening = (async () => {
      try {
        const s = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
        if (closed) { s.getTracks().forEach((t) => t.stop()); return }
        const Ctx = window.AudioContext || window.webkitAudioContext
        ac = new Ctx()
        analyser = ac.createAnalyser()
        analyser.fftSize = 1024
        ac.createMediaStreamSource(s).connect(analyser)
        buf = new Float32Array(analyser.fftSize)
        stream = s
        if (ac.state !== 'running') ac.resume().catch(() => {})
      } catch (_) {
        analyser = null // 권한 막힘 · 마이크 없음 — 흉내로 떨어진다
        failed = true
      } finally {
        opening = null
      }
    })()
    return opening
  }

  function read() {
    if (!analyser || !ac || ac.state !== 'running') return null
    return rmsOf(analyser, buf)
  }

  function close() {
    closed = true
    failed = false
    if (!stream && !ac) return
    if (stream) stream.getTracks().forEach((t) => t.stop())
    if (ac) ac.close().catch(() => {})
    ac = null; stream = null; analyser = null; buf = null
  }

  return { open, read, close }
}

/**
 * AI 목소리(TTS)가 <audio> 로 나올 때 그 소리의 RMS — 나중에 TTS 를 붙이면 ChuckVoice.outputFrom(audioEl) 로 연결한다.
 * createMediaElementSource 는 소리를 가로채므로 스피커(destination)로 다시 잇는다.
 */
export function createOutputMeter(mediaEl) {
  const Ctx = window.AudioContext || window.webkitAudioContext
  const ac = new Ctx()
  const src = ac.createMediaElementSource(mediaEl)
  const analyser = ac.createAnalyser()
  analyser.fftSize = 1024
  src.connect(analyser)
  analyser.connect(ac.destination)
  const buf = new Float32Array(analyser.fftSize)
  return {
    read() {
      if (ac.state !== 'running') ac.resume().catch(() => {})
      if (mediaEl.paused || mediaEl.ended) return null
      return rmsOf(analyser, buf)
    },
    playing() { return !mediaEl.paused && !mediaEl.ended },
  }
}
