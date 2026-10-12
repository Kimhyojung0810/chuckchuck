/* 곡선 위치 f 를 목표 단계로 미끄러뜨린다 — 시점(카메라)은 건드리지 않는다 (SPACE v3 §2 · §2-1)
   10-13: 스프링 → easeInOutSine (천천히 출발해 천천히 멈춘다, 한 칸 1.5초). motion = sin(π·진행) — 한가운데에서 가장 물러난다 */
import { useEffect } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { easing } from 'maath'
import { rig } from '../rig.js'
import { EYE, slideSeconds, easeInOutSine } from '../config.js'

export function CameraRig() {
  // 시점은 고정 (SPACE v3 §1) — R3F 기본 카메라는 원점을 내려다보므로 정면으로 돌려 둔다
  const camera = useThree((s) => s.camera)
  useEffect(() => { camera.position.set(0, EYE, 0); camera.rotation.set(0, 0, 0) }, [camera])
  useFrame((state, dt) => {
    const now = state.clock.elapsedTime
    if (window.studioDebug) window.studioDebug.three = state   // 실험실 — 장면 · 카메라를 읽는다
    const target = rig.at + rig.drag
    if (rig.reduced) { rig.f = target; rig.motion = 0; rig.tween = null; rig.settled = !rig.dragging; return }
    // 끌기 — 손가락을 그대로 따른다(직접 조작), 곡선은 살짝 물러나 있다
    if (rig.dragging) {
      rig.tween = null
      rig.settled = false
      easing.damp(rig, 'f', target, 0.05, Math.min(dt, 0.05))
      easing.damp(rig, 'motion', 1, 0.12, Math.min(dt, 0.05))
      return
    }
    // 목표가 바뀌었거나 끌기를 놓았으면 지금 자리에서 새 곡선을 시작한다
    if (!rig.tween ? Math.abs(target - rig.f) > 1e-4 : rig.tween.to !== target) {
      const from = rig.f
      rig.tween = { from, to: target, t0: now, dur: slideSeconds(target - from), m0: rig.motion }
      rig.settled = false
    }
    const tw = rig.tween
    if (!tw) { rig.motion = 0; rig.settled = true; return }
    const p = Math.min(1, (now - tw.t0) / tw.dur)
    rig.f = tw.from + (tw.to - tw.from) * easeInOutSine(p)
    // 짧은 곡선(놓아서 돌아오기)은 덜 물러난다. 끌기에서 이어지면 그 물러남에서 부드럽게 내려온다
    const depth = Math.min(1, Math.abs(tw.to - tw.from))
    rig.motion = Math.max(Math.sin(Math.PI * p) * depth, tw.m0 * (1 - easeInOutSine(p)))
    if (p >= 1) { rig.f = tw.to; rig.tween = null; rig.motion = 0; rig.settled = true }
  })
  return null
}
