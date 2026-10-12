/* 시점은 고정 (SPACE v3 §1) — 카메라는 (0, 눈높이, 0) 에서 정면만 본다. 움직이는 건 곡선 위치 f 뿐 */
import { useEffect } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { easing } from 'maath'
import { EYE, SLIDE } from '../config.js'
import { rig } from '../rig.js'

export function CameraRig() {
  const camera = useThree((s) => s.camera)
  useEffect(() => { camera.position.set(0, EYE, 0); camera.rotation.set(0, 0, 0) }, [camera])
  useFrame((_, dt) => {
    const target = rig.at + rig.drag
    if (rig.reduced) { rig.f = target; rig.motion = 0; return }
    // 움직이는 정도 — 남은 거리 · 끌기. 빨리 올라가고(.08s) 천천히 내려와(.32s) 다 도착한 뒤에 창이 다가온다
    const want = rig.dragging ? 1 : Math.min(1, Math.abs(target - rig.f) * 2.2)
    easing.damp(rig, 'motion', want, want > rig.motion ? 0.08 : 0.32, Math.min(dt, 0.05))
    if (rig.dragging) easing.damp(rig, 'f', target, 0.05, Math.min(dt, 0.05))   // 끌 때는 손가락을 바로 따른다
    else easing.damp(rig, 'f', target, SLIDE, Math.min(dt, 0.05))
  })
  return null
}
