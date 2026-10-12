/* 음성 구 — shadergradient(MIT, ruucm · stone-skipper) 의 흐르는 그라디언트(waterPlane)를 둥글게 잘라 쓴다. 소리 크기가 세기 · 속도를 바꾼다 (DESIGN_SYSTEM §6-10).
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
        <ShaderGradient control="props" type="waterPlane" animate="on"
          color1="#C9A96E" color2="#E8D2A6" color3="#5B4A2E"
          uStrength={1.2 + k * 2.4} uSpeed={0.18 + k * 0.7} uDensity={1.4} uFrequency={5.5} uAmplitude={0}
          cDistance={2.2} cPolarAngle={90} cAzimuthAngle={180} cameraZoom={1} positionX={0} positionY={0} positionZ={0}
          rotationX={0} rotationY={0} rotationZ={0} lightType="3d" brightness={1.25} grain="off" />
      </ShaderGradientCanvas>
    </div>
  )
}
