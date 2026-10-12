/* 카메라 · 마이크 — 버튼을 눌렀을 때만 묻는다 (SPACE §6). 이 시제품에서만 쓰는 새 코드 — 지금 앱의 카메라 코드는 건드리지 않는다.
   녹음은 저장하지 않는다 — 음성 구가 소리 크기만 본다. */
import { useCallback, useEffect, useRef, useState } from 'react'

export function useCamera() {
  const [video, setVideo] = useState(null)
  const [state, setState] = useState('off')   // off · asking · on · denied
  const stream = useRef(null)
  const start = useCallback(async () => {
    if (stream.current) return
    setState('asking')
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' }, audio: false })
      stream.current = s
      const v = document.createElement('video')
      v.muted = true; v.playsInline = true; v.autoplay = true; v.srcObject = s
      await v.play().catch(() => {})
      setVideo(v); setState('on')
    } catch (e) {
      setState('denied')
    }
  }, [])
  const stop = useCallback(() => {
    stream.current?.getTracks().forEach((t) => t.stop())
    stream.current = null; setVideo(null); setState('off')
  }, [])
  useEffect(() => stop, [stop])
  return { video, state, start, stop }
}

export function useMicLevel() {
  const level = useRef(0)
  const [on, setOn] = useState(false)
  const ctx = useRef(null)
  const stream = useRef(null)
  const start = useCallback(async () => {
    if (stream.current) return true
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: false })
      stream.current = s
      const ac = new (window.AudioContext || window.webkitAudioContext)()
      const an = ac.createAnalyser(); an.fftSize = 1024
      ac.createMediaStreamSource(s).connect(an)
      const buf = new Float32Array(an.fftSize)
      ctx.current = ac
      const tick = () => {
        if (!stream.current) return
        an.getFloatTimeDomainData(buf)
        let sum = 0; for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i]
        level.current = Math.sqrt(sum / buf.length)
        requestAnimationFrame(tick)
      }
      tick(); setOn(true)
      return true
    } catch (e) { return false }
  }, [])
  const stop = useCallback(() => {
    stream.current?.getTracks().forEach((t) => t.stop()); stream.current = null
    ctx.current?.close(); ctx.current = null; level.current = 0; setOn(false)
  }, [])
  useEffect(() => stop, [stop])
  return { level, on, start, stop }
}
