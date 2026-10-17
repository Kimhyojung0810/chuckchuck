/* 강연장 — 3D 로 지은 밝은 현대식 홀 (10-17 사용자 「자연은 안 어울린다 · Apple 이라면?」 → 「3D 로 지어」).
   Keynote for visionOS 가 실제 극장 · 회의실에서 리허설하게 하듯, 공간은 하나 — 나는 무대 위에 서서 객석을 본다.
   밝은 참나무 · 흰 벽 · 연회색 의자 · 천장의 빛줄, 장식 없음.
   · 준비 · 채점 · 리포트: 객석이 비고 홀 조명이 다 켜져 밝고 조용하다 — 창에 집중
   · 발표 · 질의응답 · 청중석(ENV_OF = 1): 객석에 삐약이 관객이 앉고, 홀이 조금 가라앉아 무대 쪽이 산다
   좌표: 카메라(눈)는 무대 위 (0, EYE, 0), 정면 −z. 객석은 무대 앞 C 를 중심으로 한 계단식 부채꼴. 단위 m */
import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import { useFrame, useThree } from '@react-three/fiber'
import { easing } from 'maath'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'
import { rig } from '../rig.js'
import { ENV_OF, EYE } from '../config.js'

const C = new THREE.Vector3(0, 0, 1.2)   // 객석 부채꼴의 중심 (무대 위, 카메라 조금 뒤)
const ROWS = 13
const R0 = 6.8, ROW_D = 0.98             // 첫 줄 반지름 · 줄 간격
const STAGE_H = 1.05, RISE = 0.34        // 무대 높이 · 줄마다 오르는 높이
const SPREAD = 64                        // 객석 좌우 끝 (°)
const AISLES = [-21, 21]                 // 통로 (°)
const SEAT_W = 0.58
const WALL_R = R0 + ROWS * ROW_D + 2.4
const CEIL = 10.5

const rowR = (i) => R0 + i * ROW_D
const rowY = (i) => -STAGE_H + i * RISE
const D2R = Math.PI / 180

/** 객석 부채꼴 위의 점 — θ(°, 정면 0 · 오른쪽 +), 반지름 r, 높이 y */
const fan = (deg, r, y) => new THREE.Vector3(C.x + Math.sin(deg * D2R) * r, y, C.z - Math.cos(deg * D2R) * r)

/** 고정 난수 — 열 때마다 같은 자리에 같은 삐약이 */
function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296) }

export function hallSeats() {
  const out = []
  for (let i = 0; i < ROWS; i++) {
    const r = rowR(i)
    const step = (SEAT_W / r) / D2R
    for (let a = -SPREAD + step / 2; a <= SPREAD; a += step) {
      if (AISLES.some((x) => Math.abs(a - x) < step * 0.9)) continue
      out.push({ i, a, p: fan(a, r, rowY(i)) })
    }
  }
  return out
}

/* 참나무 결 — 세로 널 · 아주 옅은 결. 캔버스 하나로 */
function woodTexture(repeatX, repeatY, vertical = true) {
  const c = document.createElement('canvas')
  c.width = 512; c.height = 512
  const g = c.getContext('2d')
  g.fillStyle = '#D8C3A2'; g.fillRect(0, 0, 512, 512)
  const rnd = rng(11)
  const slats = 16
  for (let s = 0; s < slats; s++) {
    const x = (s * 512) / slats
    const tone = 0.93 + rnd() * 0.12
    g.fillStyle = `rgb(${Math.round(216 * tone)},${Math.round(195 * tone)},${Math.round(162 * tone)})`
    g.fillRect(x, 0, 512 / slats, 512)
    g.fillStyle = 'rgba(90,60,30,.16)'; g.fillRect(x, 0, 1.5, 512)   // 널 사이 홈
    for (let k = 0; k < 6; k++) {   // 결
      g.strokeStyle = `rgba(120,85,50,${0.04 + rnd() * 0.05})`
      g.lineWidth = 1
      g.beginPath()
      const gx = x + rnd() * (512 / slats)
      g.moveTo(gx, 0)
      for (let y = 0; y <= 512; y += 32) g.lineTo(gx + Math.sin(y / 70 + k) * 2.2, y)
      g.stroke()
    }
  }
  const t = new THREE.CanvasTexture(c)
  t.colorSpace = THREE.SRGBColorSpace
  t.wrapS = t.wrapT = THREE.RepeatWrapping
  t.repeat.set(repeatX, repeatY)
  if (!vertical) t.rotation = Math.PI / 2
  t.anisotropy = 8
  return t
}

/* 의자 하나 — 앞이 +z. 등받이 · 앉는 판 · 다리 판 둘. 둥근 모서리 */
function seatGeometry() {
  const back = new RoundedBoxGeometry(0.52, 0.66, 0.08, 2, 0.035); back.translate(0, 0.78, -0.2)
  const cushion = new RoundedBoxGeometry(0.5, 0.1, 0.44, 2, 0.04); cushion.translate(0, 0.44, 0.02)
  const sideL = new THREE.BoxGeometry(0.05, 0.6, 0.5).toNonIndexed(); sideL.translate(-0.28, 0.3, -0.02)
  const sideR = sideL.clone(); sideR.translate(0.56, 0, 0)
  return mergeGeometries([back, cushion, sideL, sideR])
}

/* 삐약이 관객 — 한 장 아틀라스(4 × 4 얼굴)에서 한 번에. 발표 단계에 「앉으러」 쏙 올라오고, 끝나면 내려간다 */
const NAMES = ['ax', 'exaone', 'midm', 'solar']
const MOODS = ['neutral', 'happy', 'excited', 'curious']
function chickAtlas() {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = 1024
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
  const ctx = canvas.getContext('2d')
  NAMES.forEach((n, i) => MOODS.forEach((m, j) => {
    const img = new Image()
    img.onload = () => { ctx.drawImage(img, j * 256, i * 256, 256, 256); tex.needsUpdate = true }
    img.src = `assets/chick-${n}-${m}.svg`
  }))
  return tex
}
const chickVert = /* glsl */ `
  attribute vec4 aFace;     // 아틀라스 칸 x · y · 뒤집기 · 위상
  uniform float uTime, uShow, uHop;
  varying vec2 vUv;
  void main() {
    vec2 uv = uv;
    if (aFace.z > 0.5) uv.x = 1.0 - uv.x;
    vUv = (vec2(aFace.x, 3.0 - aFace.y) + uv) / 4.0;
    // 앉으러 올라오기 — 저마다 조금씩 늦게(위상), 아래가 기준
    float s = clamp(uShow * 1.6 - fract(aFace.w * 0.159) * 0.6, 0.0, 1.0);
    s = s * s * (3.0 - 2.0 * s);
    vec3 p = position;
    p.y = (p.y + 0.5) * s - 0.5;
    p.x *= mix(0.6, 1.0, s);
    // 숨쉬기 + 목소리에 들썩
    p.y += sin(uTime * 1.6 + aFace.w) * 0.012 + max(0.0, sin(uTime * 7.0 + aFace.w * 3.0)) * uHop * 0.08;
    gl_Position = projectionMatrix * modelViewMatrix * instanceMatrix * vec4(p, 1.0);
  }
`
const chickFrag = /* glsl */ `
  uniform sampler2D uMap;
  varying vec2 vUv;
  void main() {
    vec4 c = texture2D(uMap, vUv);
    if (c.a < 0.5) discard;
    gl_FragColor = vec4(c.rgb, 1.0);
    #include <colorspace_fragment>
  }
`

/** 지금 「공연 중」 정도 0..1 — 다른 장면이 읽는다 */
export const hall = { perform: 0 }

export function Hall({ readLevel }) {
  const gl = useThree((s) => s.gl)
  const scene = useThree((s) => s.scene)
  const seats = useMemo(hallSeats, [])
  const seatMesh = useRef()
  const chickMesh = useRef()
  const house = useRef()
  const cove = useRef([])
  const hop = useRef(0)
  const room = useRef()
  const look = useMemo(() => ({ x: 0, y: 0, bx: 0, by: 0 }), [])
  const seatGeo = useMemo(seatGeometry, [])

  // 부드러운 실내 반사광 — 재질이 납작한 CG 처럼 보이지 않게 (three RoomEnvironment)
  useEffect(() => {
    const pm = new THREE.PMREMGenerator(gl)
    const envTex = pm.fromScene(new RoomEnvironment(), 0.04).texture
    scene.environment = envTex
    scene.environmentIntensity = 0.55
    scene.fog = new THREE.Fog('#EEEAE4', 24, 80)   // 먼 줄이 공기 속으로 — 깊이감
    return () => { scene.environment = null; scene.fog = null; envTex.dispose(); pm.dispose() }
  }, [gl, scene])

  const mats = useMemo(() => ({
    seat: new THREE.MeshStandardMaterial({ color: '#B9AC9B', roughness: 0.85 }),   // 밝은 낙타색 천 — 흰 의자는 빛에 날아가 덩어리로 보였다
    wood: new THREE.MeshStandardMaterial({ map: woodTexture(18, 1), roughness: 0.62, side: THREE.BackSide }),   // 안에서 보는 벽
    floor: new THREE.MeshStandardMaterial({ map: woodTexture(10, 1, false), roughness: 0.55 }),
    tread: new THREE.MeshStandardMaterial({ color: '#8E8780', roughness: 0.97 }),   // 객석 바닥 — 차분한 카펫
    riser: new THREE.MeshStandardMaterial({ color: '#D9D2C8', roughness: 0.9, side: THREE.DoubleSide }),
    white: new THREE.MeshStandardMaterial({ color: '#F4F2EE', roughness: 0.95 }),
    stage: new THREE.MeshStandardMaterial({ map: woodTexture(8, 3, false), roughness: 0.45 }),
  }), [])

  // 계단 · 벽 · 천장 — 한 번만 만든다
  const shell = useMemo(() => {
    const t0 = Math.PI - (SPREAD + 12) * D2R, tl = (SPREAD + 12) * 2 * D2R   // CylinderGeometry 의 θ (x = r sinθ, z = r cosθ)
    const parts = []
    for (let i = 0; i < ROWS; i++) {
      const rIn = rowR(i) - ROW_D * 0.55, rOut = rowR(i) + ROW_D * 0.45
      const tread = new THREE.RingGeometry(rIn, rOut, 96, 1, (90 - SPREAD - 12) * D2R, tl)
      tread.rotateX(-Math.PI / 2)
      tread.translate(C.x, rowY(i), C.z)
      parts.push(['tread', tread])
      const riser = new THREE.CylinderGeometry(rIn, rIn, RISE, 96, 1, true, t0, tl)
      riser.translate(C.x, rowY(i) - RISE / 2, C.z)
      parts.push(['riser', riser])
    }
    // 첫 줄 앞 바닥 (무대 아래)
    const pit = new THREE.RingGeometry(1.5, rowR(0) - ROW_D * 0.55, 96, 1, (90 - SPREAD - 12) * D2R, tl)
    pit.rotateX(-Math.PI / 2); pit.translate(C.x, -STAGE_H, C.z)
    parts.push(['floor', pit])
    // 뒤 · 옆을 감싸는 참나무 벽
    const wall = new THREE.CylinderGeometry(WALL_R, WALL_R, CEIL + STAGE_H + 1, 160, 1, true, Math.PI - 100 * D2R, 200 * D2R)
    wall.translate(C.x, (CEIL - STAGE_H - 1) / 2, C.z)
    parts.push(['wood', wall])
    // 천장
    const ceil = new THREE.CircleGeometry(WALL_R + 0.5, 96)
    ceil.rotateX(Math.PI / 2); ceil.translate(C.x, CEIL, C.z)
    parts.push(['white', ceil])
    return parts
  }, [])

  // 의자 자리 — 부채꼴 중심(무대)을 본다
  useEffect(() => {
    const m = seatMesh.current
    const o = new THREE.Object3D()
    seats.forEach((s, k) => {
      o.position.copy(s.p)
      o.rotation.set(0, Math.atan2(C.x - s.p.x, C.z - s.p.z), 0)
      o.updateMatrix()
      m.setMatrixAt(k, o.matrix)
    })
    m.instanceMatrix.needsUpdate = true
  }, [seats])

  // 삐약이 — 의자의 75% 에 앉는다. 판은 카메라(눈)를 본다
  const audience = useMemo(() => {
    const rnd = rng(7)
    return seats.filter(() => rnd() < 0.75).map((s) => ({ ...s, face: Math.floor(rnd() * 16), flip: rnd() < 0.5, phase: rnd() * Math.PI * 2 }))
  }, [seats])
  const chickMat = useMemo(() => new THREE.ShaderMaterial({
    vertexShader: chickVert, fragmentShader: chickFrag, toneMapped: false,
    uniforms: { uMap: { value: chickAtlas() }, uTime: { value: 0 }, uShow: { value: 0 }, uHop: { value: 0 } },
  }), [])
  const chickGeo = useMemo(() => {
    const g = new THREE.PlaneGeometry(1, 1)
    g.setAttribute('aFace', new THREE.InstancedBufferAttribute(new Float32Array(audience.flatMap((a) => [a.face % 4, Math.floor(a.face / 4), a.flip ? 1 : 0, a.phase])), 4))
    return g
  }, [audience])
  useEffect(() => {
    const m = chickMesh.current
    const o = new THREE.Object3D()
    const eye = new THREE.Vector3(0, EYE, 0)
    const H = 0.54
    audience.forEach((a, k) => {
      const toC = new THREE.Vector3(C.x - a.p.x, 0, C.z - a.p.z).normalize()
      o.position.copy(a.p).addScaledVector(toC, 0.04)   // 앉는 판 위, 등받이 앞
      o.position.y += 0.44 + H / 2 - 0.04
      o.lookAt(eye.x, o.position.y, eye.z)
      o.scale.setScalar(H)
      o.updateMatrix()
      m.setMatrixAt(k, o.matrix)
    })
    m.instanceMatrix.needsUpdate = true
  }, [audience])

  // 그림자는 한 번만 — 의자가 자리 잡은 뒤 굽고, 다음부터는 다시 그리지 않는다(유리 패스가 장면을 두 번 그려도 가볍게)
  useEffect(() => {
    gl.shadowMap.autoUpdate = false
    const id = setTimeout(() => { gl.shadowMap.needsUpdate = true }, 60)
    return () => { clearTimeout(id); gl.shadowMap.autoUpdate = true }
  }, [gl])

  useFrame((state, dt) => {
    // 시선 시차 — 포인터 쪽으로 머리를 살짝 옮긴 것처럼 홀이 반대로 움직인다. 가까운 줄은 많이 · 먼 벽은 적게 → 깊이.
    // 사람이 일으킨 작은 움직임만(최대 30cm · 부드럽게), 움직임 줄이기를 고르면 가만히
    const k = rig.reduced ? 0 : 1
    easing.damp(look, 'x', -rig.px * 0.32 * k, 0.35, dt)
    easing.damp(look, 'y', rig.py * 0.14 * k, 0.35, dt)
    if (room.current) room.current.position.set(look.x, look.y, 0)
    // 홀이 움직였으면 그림자도 다시 굽는다 (그림자 행렬은 구울 때만 갱신된다 — 안 그러면 그림자가 미끄러진다)
    if (Math.abs(look.x - look.bx) + Math.abs(look.y - look.by) > 0.002) { look.bx = look.x; look.by = look.y; gl.shadowMap.needsUpdate = true }
    const perform = ENV_OF[rig.at] === 1 ? 1 : 0
    easing.damp(hall, 'perform', perform, rig.reduced ? 0.0001 : 0.5, dt)
    const u = chickMat.uniforms
    u.uTime.value = state.clock.elapsedTime
    u.uShow.value = hall.perform
    const lv = rig.at === 1 && readLevel && !rig.reduced ? readLevel() : 0
    hop.current += (Math.min(1, lv * 1.6) - hop.current) * Math.min(1, dt * 4)
    u.uHop.value = hop.current
    if (chickMesh.current) chickMesh.current.visible = hall.perform > 0.01
    // 홀 조명 — 준비 · 리포트는 다 켜고, 공연 중엔 조금 가라앉힌다(무대 쪽 · 창이 산다)
    if (house.current) house.current.intensity = 0.9 - 0.25 * hall.perform
    scene.environmentIntensity = 0.5 - 0.12 * hall.perform
    cove.current.forEach((m) => m && m.color.setScalar(1.6 - 0.5 * hall.perform))
  })

  return (
    <group ref={room}>
      {shell.map(([mat, geo], i) => <mesh key={i} geometry={geo} material={mats[mat]} receiveShadow />)}
      {/* 무대 바닥 · 앞 끝의 얇은 빛줄 */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0.4]} material={mats.stage}>
        <planeGeometry args={[40, 6]} />
      </mesh>
      <mesh position={[0, -STAGE_H / 2, -2.6]} material={mats.riser}>
        <boxGeometry args={[40, STAGE_H, 0.02]} />
      </mesh>
      <mesh position={[0, -0.03, -2.6]}>
        <boxGeometry args={[40, 0.02, 0.03]} />
        <meshBasicMaterial ref={(m) => { cove.current[0] = m }} color="#FFF6E6" toneMapped={false} />
      </mesh>
      {/* 벽 위 간접 조명 띠 */}
      <mesh position={[C.x, 7.4, C.z]}>
        <cylinderGeometry args={[WALL_R - 0.05, WALL_R - 0.05, 0.05, 160, 1, true, Math.PI - 100 * D2R, 200 * D2R]} />
        <meshBasicMaterial ref={(m) => { cove.current[1] = m }} color="#FFF4E2" toneMapped={false} side={THREE.BackSide} />
      </mesh>
      <instancedMesh ref={seatMesh} args={[seatGeo, mats.seat, seats.length]} frustumCulled={false} castShadow receiveShadow />
      <instancedMesh ref={chickMesh} args={[chickGeo, chickMat, audience.length]} frustumCulled={false} />
      {/* 홀 조명 — 객석 뒤 오른쪽 위에서. 의자 그림자가 앞줄 바닥으로 떨어져 보인다(입체감). 정적 장면이라 그림자는 한 번만 굽는다 */}
      <directionalLight ref={house} position={[9, 15, -26]} intensity={0.9} color="#FFF8F0" castShadow
        shadow-mapSize={[2048, 2048]} shadow-bias={-0.0004} shadow-normalBias={0.03} shadow-radius={5}
        shadow-camera-left={-24} shadow-camera-right={24} shadow-camera-top={24} shadow-camera-bottom={-24}
        shadow-camera-near={1} shadow-camera-far={70}>
        <object3D attach="target" position={[0, -1, -8]} />
      </directionalLight>
    </group>
  )
}
