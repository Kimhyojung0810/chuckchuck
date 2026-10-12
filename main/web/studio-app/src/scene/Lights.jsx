/* 정거장별 조명 — 같은 방에 빛만 바뀐다 (SPACE §3). 초록기 도는 흰빛만 (10-13 사용자: 금빛 → 초록) */
import { useRef, useMemo } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { easing } from 'maath'
import { LIGHT, CEIL, toward, stationAngle } from '../config.js'
import { BACK_R } from './Room.jsx'
import { rig } from '../rig.js'

export function Lights({ coveRef }) {
  const amb = useRef()
  const spots = useRef([])
  const scene = useThree((s) => s.scene)
  const cur = useMemo(() => ({ color: new THREE.Color(LIGHT[0].color), amb: LIGHT[0].amb, cove: LIGHT[0].cove, fog: LIGHT[0].fog, k: [1, 0, 0, 0] }), [])
  const targets = useMemo(() => [0, 1, 2, 3].map((k) => {
    const o = new THREE.Object3D()
    // 카메라 정거장(② ③)은 큰 카메라 화면을, 나머지는 창 뒤 벽을 비춘다
    const [x, z] = toward(stationAngle(k), BACK_R)
    o.position.set(x, 1.5, z)
    return o
  }), [])
  if (!scene.fog) scene.fog = new THREE.Fog('#040605', 9, LIGHT[0].fog)

  useFrame((_, dt) => {
    const L = LIGHT[rig.at]
    const st = rig.reduced ? 0.0001 : 0.45
    easing.dampC(cur.color, L.color, st, dt)
    easing.damp(cur, 'amb', L.amb, st, dt)
    easing.damp(cur, 'cove', L.cove, st, dt)
    easing.damp(cur, 'fog', L.fog, st, dt)
    for (let k = 0; k < 4; k++) easing.damp(cur.k, k, k === 0 ? 1 : 0, st, dt)   // 시점 고정 — 비추는 건 언제나 정면 벽, 단계마다 색 · 세기만
    // 움직이는 동안(rig.motion → 1)은 공간이 조금 밝아져 곡선 전체가 보이고, 멈추면 가라앉아 지금 창에 집중한다
    const focus = 0.72 + 0.28 * rig.motion
    if (amb.current) { amb.current.intensity = cur.amb * 0.9 * focus; amb.current.color.copy(cur.color) }
    spots.current.forEach((s, k) => {
      if (!s) return
      s.color.copy(cur.color)
      s.intensity = (18 + cur.k[k] * L.spot) * (k === 0 ? 1 : focus)
      s.angle = THREE.MathUtils.lerp(0.6, L.angle, cur.k[k])
    })
    const cv = cur.cove * (0.6 + 0.4 * rig.motion)
    coveRef.current.forEach((m) => m && m.color.setRGB(0.42 * cv + 0.03, 0.5 * cv + 0.04, 0.45 * cv + 0.035))
    scene.fog.far = cur.fog
  })

  return (
    <>
      <ambientLight ref={amb} intensity={0.5} />
      <hemisphereLight args={['#6d7a72', '#151b18', 1.2]} />
      {[0, 1, 2, 3].map((k) => {
        const [x, z] = toward(stationAngle(k), 2.4)
        return (
          <group key={k}>
            <primitive object={targets[k]} />
            <spotLight ref={(s) => { spots.current[k] = s }} position={[x, CEIL - 0.1, z]} target={targets[k]}
              angle={0.6} penumbra={0.85} decay={1.6} distance={14} intensity={4} />
          </group>
        )
      })}
    </>
  )
}
