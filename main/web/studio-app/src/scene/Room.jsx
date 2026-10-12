/* 둥근 공간 — 사용자를 둘러싼 원통 배경 · 둥근 바닥 · 한 바퀴 이어지는 빛 띠 (SPACE v3 §2, 10-13 사용자: 정사각형 방 · 네 벽 분할 없이)
   모서리가 없어 창이 곡선을 따라 미끄러질 때 배경이 끊기지 않는다. 배경은 움직이지 않는다 */
import { MeshReflectorMaterial } from '@react-three/drei'
import * as THREE from 'three'

export const BACK_R = 9      // 배경 원통 반지름
const BACK_H = 7

export function Room({ coveRef, quality }) {
  return (
    <group>
      {/* 배경 원통 — 안쪽 면 */}
      <mesh position={[0, BACK_H / 2 - 0.4, 0]}>
        <cylinderGeometry args={[BACK_R, BACK_R, BACK_H, 128, 1, true]} />
        <meshStandardMaterial color="#3E3A34" roughness={0.97} side={THREE.BackSide} />
      </mesh>
      {/* 한 바퀴 이어지는 빛 띠 — 눈높이 위, 곡선을 따라 끊기지 않는 지평선 단서 */}
      <mesh position={[0, 3.6, 0]}>
        <cylinderGeometry args={[BACK_R - 0.05, BACK_R - 0.05, 0.02, 128, 1, true]} />
        <meshBasicMaterial ref={(m) => { if (m) coveRef.current[0] = m }} color="#F2E6CF" side={THREE.BackSide} toneMapped={false} />
      </mesh>
      {/* 바닥과 배경이 만나는 그늘 띠 */}
      <mesh position={[0, 0.08, 0]}>
        <cylinderGeometry args={[BACK_R - 0.02, BACK_R - 0.02, 0.16, 128, 1, true]} />
        <meshStandardMaterial color="#141311" roughness={1} side={THREE.BackSide} />
      </mesh>
      {/* 둥근 바닥 — 어둡게 광택, 약하게 비친다 */}
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[BACK_R, 96]} />
        {quality > 0 ? (
          <MeshReflectorMaterial resolution={512} blur={[300, 90]} mixBlur={0.8} mixStrength={0.38}
            roughness={0.85} depthScale={1} minDepthThreshold={0.4} maxDepthThreshold={1.2}
            color="#121110" metalness={0.35} mirror={0} />
        ) : <meshStandardMaterial color="#121110" roughness={0.8} />}
      </mesh>
    </group>
  )
}
