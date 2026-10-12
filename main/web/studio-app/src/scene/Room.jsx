/* 방 — 벽 넷 · 걸레받이 · 천장 띠(코브) · 반사 바닥 · 천장 (SPACE §1). 장식 없음 */
import { MeshReflectorMaterial } from '@react-three/drei'
import { ROOM, CEIL } from '../config.js'

const WALL = '#46423B'

export function Room({ coveRef, quality }) {
  const walls = [0, 1, 2, 3]
  return (
    <group>
      {walls.map((k) => {
        const a = -k * Math.PI / 2   // 벽 k 는 정거장 k 방향(오른쪽으로 90°씩)
        return (
          <group key={k} rotation={[0, a, 0]}>
            {/* 벽 */}
            <mesh position={[0, CEIL / 2, -ROOM]} receiveShadow>
              <planeGeometry args={[ROOM * 2, CEIL]} />
              <meshStandardMaterial color={WALL} roughness={0.95} metalness={0} />
            </mesh>
            {/* 걸레받이 그늘 */}
            <mesh position={[0, 0.06, -ROOM + 0.012]}>
              <planeGeometry args={[ROOM * 2, 0.12]} />
              <meshStandardMaterial color="#141311" roughness={1} />
            </mesh>
            {/* 천장 바로 밑을 도는 간접 조명 띠 — 네 벽이 이어져 보여 「같은 방」 */}
            <mesh position={[0, CEIL - 0.22, -ROOM + 0.02]}>
              <planeGeometry args={[ROOM * 2, 0.018]} />
              <meshBasicMaterial ref={(m) => { if (m) coveRef.current[k] = m }} color="#F2E6CF" toneMapped={false} />
            </mesh>
          </group>
        )
      })}
      {/* 천장 */}
      <mesh position={[0, CEIL, 0]} rotation={[Math.PI / 2, 0, 0]}>
        <planeGeometry args={[ROOM * 2, ROOM * 2]} />
        <meshStandardMaterial color="#121110" roughness={1} />
      </mesh>
      {/* 바닥 — 어둡게 광택 있는 콘크리트, 약하게 비친다 */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[ROOM * 2, ROOM * 2]} />
        {quality > 0 ? (
          <MeshReflectorMaterial
            resolution={512} blur={[400, 120]} mixBlur={1} mixStrength={0.55}
            roughness={0.85} depthScale={1} minDepthThreshold={0.4} maxDepthThreshold={1.2}
            color="#121110" metalness={0.35} mirror={0}
          />
        ) : (
          <meshStandardMaterial color="#121110" roughness={0.8} />
        )}
      </mesh>
    </group>
  )
}
