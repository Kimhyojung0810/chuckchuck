/* 정거장별 조명 — 같은 방에 빛만 바뀐다 (SPACE §3). 카메라와 같은 스프링으로 따라간다 */
import { useRef, useMemo } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { easing } from 'maath'
import { LIGHT, CEIL, ROOM, DIST, toward, stationAngle } from '../config.js'
import { rig } from '../rig.js'

export function Lights({ coveRef }) {
  const amb = useRef()
  const spots = useRef([])
  const scene = useThree((s) => s.scene)
  const cur = useMemo(() => ({ color: new THREE.Color(LIGHT[0].color), amb: LIGHT[0].amb, cove: LIGHT[0].cove, fog: LIGHT[0].fog, k: [1, 0, 0, 0] }), [])
  const targets = useMemo(() => [0, 1, 2, 3].map((k) => {
    const o = new THREE.Object3D()
    // 카메라 정거장(② ③)은 큰 카메라 화면을, 나머지는 창 뒤 벽을 비춘다
    const [x, z] = toward(stationAngle(k), k === 1 || k === 2 ? DIST + 0.2 : ROOM)
    o.position.set(x, 1.5, z)
    return o
  }), [])
  if (!scene.fog) scene.fog = new THREE.Fog('#050504', 9, LIGHT[0].fog)

  useFrame((_, dt) => {
    const L = LIGHT[rig.at]
    const st = rig.reduced ? 0.0001 : 0.7
    easing.dampC(cur.color, L.color, st, dt)
    easing.damp(cur, 'amb', L.amb, st, dt)
    easing.damp(cur, 'cove', L.cove, st, dt)
    easing.damp(cur, 'fog', L.fog, st, dt)
    for (let k = 0; k < 4; k++) easing.damp(cur.k, k, k === rig.at ? 1 : 0, st, dt)
    if (amb.current) { amb.current.intensity = cur.amb * 0.9; amb.current.color.copy(cur.color) }
    spots.current.forEach((s, k) => {
      if (!s) return
      s.color.copy(cur.color)
      s.intensity = 18 + cur.k[k] * L.spot
      s.angle = THREE.MathUtils.lerp(0.6, L.angle, cur.k[k])
    })
    coveRef.current.forEach((m) => m && m.color.setRGB(0.5 * cur.cove + 0.04, 0.46 * cur.cove + 0.04, 0.38 * cur.cove + 0.03))
    scene.fog.far = cur.fog
  })

  return (
    <>
      <ambientLight ref={amb} intensity={0.5} />
      <hemisphereLight args={['#7a7266', '#1e1b17', 1.2]} />
      {[0, 1, 2, 3].map((k) => {
        const [x, z] = toward(stationAngle(k), 2.2)
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
