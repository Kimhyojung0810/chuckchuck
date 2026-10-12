/* 카메라 화면 — 카메라를 쓰는 정거장의 주인공 (SPACE §6). 내 모습을 거울처럼 크게.
   이 시제품 안에서만 쓰는 새 코드다 — 지금 앱의 카메라 코드는 건드리지 않는다. */
import { useEffect, useMemo } from 'react'
import * as THREE from 'three'
import { useWorldPerPx } from './Station.jsx'

export function CameraScreen({ video, widthPx, heightPx }) {
  const world = useWorldPerPx()
  const tex = useMemo(() => {
    if (!video) return null
    const t = new THREE.VideoTexture(video)
    t.colorSpace = THREE.SRGBColorSpace
    t.wrapS = THREE.RepeatWrapping
    t.repeat.x = -1          // 거울처럼 좌우 반전
    t.offset.x = 1
    return t
  }, [video])
  useEffect(() => () => tex && tex.dispose(), [tex])
  const w = widthPx * world, h = heightPx * world
  return (
    <group position={[0, 0, -0.05]}>
      {/* 화면 테두리 — 빛을 받는 얇은 틀 */}
      {/* 화면 테두리 — 은은하게 빛나는 얇은 틀이라 꺼져 있어도 「화면」 으로 읽힌다 */}
      <mesh position={[0, 0, -0.01]}>
        <planeGeometry args={[w + 0.05, h + 0.05]} />
        <meshBasicMaterial color="#3a3428" toneMapped={false} />
      </mesh>
      <mesh>
        <planeGeometry args={[w, h]} />
        {tex ? <meshBasicMaterial map={tex} toneMapped={false} /> : <meshBasicMaterial color="#141310" toneMapped={false} />}
      </mesh>
    </group>
  )
}
