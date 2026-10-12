/* 카메라 리그 — 스프링으로 목표 각도를 따라가고, 돌 때 한 걸음 물러섰다 다가간다 (SPACE §2 · §7) */
import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { easing } from 'maath'
import { EYE, SMOOTH, STEP_BACK, LOOK, deg } from '../config.js'
import { rig } from '../rig.js'

export function CameraRig() {
  const s = useRef({ yaw: rig.yawTarget, back: 0, pitch: 0, lx: 0, ly: 0, walk: 0 })
  useFrame((state, dt) => {
    const c = s.current
    const cam = state.camera
    const red = rig.reduced
    const d = Math.min(dt, 0.05)
    // 마우스 시선 — 아주 살짝, 부드럽게
    easing.damp(c, 'lx', red ? 0 : rig.lookX, 0.35, d)
    easing.damp(c, 'ly', red ? 0 : rig.lookY, 0.35, d)
    if (rig.freeze != null) { c.yaw = rig.freeze; c.back = Math.min(1, Math.abs(rig.yawTarget - c.yaw) / 90) * STEP_BACK }   // 헤드리스: 이 각도로 멈춰 찍기
    const target = rig.freeze != null ? rig.freeze : rig.yawTarget + rig.peek
    if (red) c.yaw = target
    else easing.damp(c, 'yaw', target, rig.peek ? 0.18 : SMOOTH, d)
    rig.yaw = c.yaw
    // 남은 각도 → 물러섬 · 고개 · 걸음
    const left = Math.min(1, Math.abs(rig.yawTarget - c.yaw) / 90)
    easing.damp(c, 'back', red ? 0 : left * STEP_BACK, 0.45, d)
    easing.damp(c, 'pitch', red ? 0 : -left * 1.5, 0.45, d)
    c.walk += Math.abs(target - c.yaw) * d * 0.25
    const bob = red ? 0 : Math.sin(c.walk) * 0.008 * left
    const yaw = c.yaw + c.lx * LOOK.yaw
    const fx = Math.sin(deg(yaw)), fz = -Math.cos(deg(yaw))
    cam.position.set(-fx * c.back, EYE + bob, -fz * c.back)
    cam.rotation.set(deg(c.pitch - c.ly * LOOK.pitch), -deg(yaw), 0, 'YXZ')
  })
  return null
}
