// 흐르는 파형 — ElevenLabs UI 「LiveWaveform」(MIT, github.com/elevenlabs/ui registry/elevenlabs-ui/ui/live-waveform.tsx)의
// scrolling 모드를 옮겼다. 바뀐 점: 마이크를 따로 열지 않고 read()(0~1 음량 · 없으면 null)를 받는다 — 앱이 이미 재는 음량을 쓴다.
// 새 소리가 오른쪽에서 들어와 왼쪽으로 흘러간다(녹음하는 느낌). 신호가 없을 때만 흉내(signal.js pickVolume).
import { useEffect, useRef } from 'react'
import { pickVolume } from './signal.js'

/**
 * @param active   녹음 중인가 — 아니면 파형이 잦아들고 점선만 남는다
 * @param read     () => 0..1 | null
 */
export function Waveform({ active, read, height = 36, barWidth = 3, barGap = 2, barRadius = 1.5, barColor = '#3fd599',
  baseBarHeight = 3, historySize = 120, updateRate = 30, fadeEdges = true, fadeWidth = 24, label = '마이크 파형', className = '' }) {
  const canvasRef = useRef(null)
  const boxRef = useRef(null)
  const history = useRef([])
  const readRef = useRef(read)
  readRef.current = read

  // 캔버스 크기 — 상자를 따라간다
  useEffect(() => {
    const canvas = canvasRef.current, box = boxRef.current
    if (!canvas || !box) return undefined
    const ro = new ResizeObserver(() => {
      const r = box.getBoundingClientRect()
      const dpr = Math.min(2, window.devicePixelRatio || 1)
      canvas.width = Math.round(r.width * dpr)
      canvas.height = Math.round(r.height * dpr)
      canvas.getContext('2d')?.setTransform(dpr, 0, 0, dpr, 0, 0)
    })
    ro.observe(box)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    if (!ctx) return undefined
    let raf = 0
    let last = 0
    let fade = active ? 1 : 0
    const draw = (now) => {
      raf = 0
      const w = canvas.clientWidth, h = canvas.clientHeight
      if (active && now - last > updateRate) {
        last = now
        const real = readRef.current ? readRef.current() : null
        const { volume } = pickVolume(real, 'listening', now)
        history.current.push(Math.min(1, Math.max(0.05, volume)))
        if (history.current.length > historySize) history.current.shift()
      }
      if (!active) { fade = Math.max(0, fade - 0.03); history.current = history.current.map((v) => v * 0.97) }
      ctx.clearRect(0, 0, w, h)
      const step = barWidth + barGap
      const count = Math.floor(w / step)
      const cy = h / 2
      ctx.fillStyle = barColor
      for (let i = 0; i < count && i < history.current.length; i++) {
        const v = history.current[history.current.length - 1 - i] || 0.1
        const x = w - (i + 1) * step
        const bh = Math.max(baseBarHeight, v * h * 0.8)
        ctx.globalAlpha = 0.4 + v * 0.6
        ctx.beginPath()
        if (ctx.roundRect) ctx.roundRect(x, cy - bh / 2, barWidth, bh, barRadius)
        else ctx.rect(x, cy - bh / 2, barWidth, bh)
        ctx.fill()
      }
      ctx.globalAlpha = 1
      if (fadeEdges && w > 0) {
        const g = ctx.createLinearGradient(0, 0, w, 0)
        const f = Math.min(0.3, fadeWidth / w)
        g.addColorStop(0, 'rgba(255,255,255,1)'); g.addColorStop(f, 'rgba(255,255,255,0)')
        g.addColorStop(1 - f, 'rgba(255,255,255,0)'); g.addColorStop(1, 'rgba(255,255,255,1)')
        ctx.globalCompositeOperation = 'destination-out'
        ctx.fillStyle = g
        ctx.fillRect(0, 0, w, h)
        ctx.globalCompositeOperation = 'source-over'
      }
      // 녹음 중이면 계속, 멈췄으면 다 잦아들 때까지만 그린다 — 쉬는 동안 rAF 를 돌리지 않는다
      if ((active || history.current.some((v) => v > 0.01)) && !document.hidden) raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)
    const onVis = () => { if (!document.hidden && !raf) raf = requestAnimationFrame(draw) }
    document.addEventListener('visibilitychange', onVis)
    return () => { cancelAnimationFrame(raf); document.removeEventListener('visibilitychange', onVis) }
  }, [active, barWidth, barGap, barRadius, barColor, baseBarHeight, historySize, updateRate, fadeEdges, fadeWidth])

  return (
    <span ref={boxRef} className={`cv-wave ${className}`} role="img" aria-label={active ? label : `${label} — 쉬는 중`}
      style={{ position: 'relative', display: 'block', height }}>
      {!active && <span aria-hidden="true" style={{ position: 'absolute', left: 0, right: 0, top: '50%', borderTop: '2px dotted currentColor', opacity: 0.25 }} />}
      <canvas ref={canvasRef} aria-hidden="true" style={{ display: 'block', width: '100%', height: '100%' }} />
    </span>
  )
}
