/* 음성 구 — shadergradient(MIT, ruucm · stone-skipper) 의 sphere. 소리 크기가 세기 · 속도를 바꾼다 (DESIGN_SYSTEM §6-10).
   색은 금빛 계열만 — 판정 색과 섞이지 않게. 낱말을 꼭 같이 둔다 */
import { useEffect, useState } from 'react'
import { ShaderGradientCanvas, ShaderGradient } from '@shadergradient/react'
import { rig } from '../rig.js'

export function VoiceOrb({ levelRef, size = 96, speaking = false }) {
  const [amp, setAmp] = useState(0)
  useEffect(() => {
    const id = setInterval(() => {
      const raw = speaking ? 0.06 + 0.04 * Math.sin(performance.now() / 260) : (levelRef?.current || 0)
      setAmp((a) => a + (raw - a) * 0.5)
    }, 100)
    return () => clearInterval(id)
  }, [levelRef, speaking])
  const k = Math.min(1, amp * 7)
  if (rig.reduced) {
    return <div className="sx-orb sx-orb--still" style={{ width: size, height: size, '--k': k }} aria-hidden="true" />
  }
  return (
    <div className="sx-orb" style={{ width: size, height: size }} aria-hidden="true">
      <ShaderGradientCanvas style={{ position: 'absolute', inset: 0 }} pixelDensity={1} fov={40} lazyLoad={false} pointerEvents="none">
        <ShaderGradient control="props" type="sphere" animate="on"
          color1="#C9A96E" color2="#E8D2A6" color3="#5B4A2E"
          uStrength={0.25 + k * 0.95} uSpeed={0.2 + k * 0.6} uDensity={1.3} uFrequency={5.5} uAmplitude={1.4}
          cDistance={3.4} cPolarAngle={90} cAzimuthAngle={180} lightType="3d" brightness={1.25} grain="off" />
      </ShaderGradientCanvas>
    </div>
  )
}
