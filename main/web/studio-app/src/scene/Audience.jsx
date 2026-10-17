/* 극장 객석의 삐약이 관객 — 사진 속 빈 의자 줄마다 삐약이가 앉는다 (10-17 사용자 「발표할 때는 관객이 있는 것처럼」).
   의자 자리는 잘라 둔 theater.webp(4096×2048) 좌표로 잰 줄 모형(ROWS)에서 나온다 — 시점이 고정이라 방향(가로각 · 세로각)만 맞으면
   사진의 의자 위에 정확히 앉는다. 발표 중 목소리가 커지면 들썩인다(앱이 이미 재는 음량 — 마이크를 더 열지 않는다).
   극장 사진이 보일 때만(env.mix) 드러난다. 삐약이 열여섯 얼굴은 한 장의 아틀라스(캔버스)에 그려 한 번에 그린다. */
import { useEffect, useMemo, useRef } from 'react'
import * as THREE from 'three'
import { useFrame } from '@react-three/fiber'
import { EYE } from '../config.js'
import { rig } from '../rig.js'
import { env, ENV_YAW, ENV_PITCH } from './Environment.jsx'

const IMG_W = 4096, IMG_H = 2048
//: 줄마다 가운데 의자 등받이 윗선 y · 가운데 의자 폭 (theater.webp 화소). 0 · 1번(앞 두 줄)은 앉히지 않는다 — 얼굴이 너무 커서 무대 앞줄 삐약이(Sets)와 크기가 어긋났다
const ROWS = [[1460, 330], [1325, 270], [1220, 190], [1157, 147], [1117, 117], [1092, 97], [1074, 82], [1062, 70], [1052, 60], [1045, 52], [1039, 46], [1034, 41]]
const CX = 1990            // 줄이 가장 낮은 곳 (객석이 무대를 둘러싼 그릇 모양)
const X_MIN = 900, X_MAX = 3200
const D = 20               // 삐약이를 놓을 거리(m) — 방향만 맞으면 된다
const NAMES = ['ax', 'exaone', 'midm', 'solar']
const MOODS = ['neutral', 'happy', 'excited', 'curious']

const yAt = (r, x) => ROWS[r][0] - ROWS[r][1] * 3.4e-7 * (x - CX) ** 2
const wAt = (r, x) => { const d = (x - CX) / 1000; return ROWS[r][1] * (1 - 0.22 * d * d) }

/** 작은 고정 난수 — 새로 열어도 같은 자리에 같은 삐약이 */
function rng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296) }

export function audienceSeats() {
  const rnd = rng(7)
  const out = []
  for (let r = 2; r < ROWS.length; r++) {
    const xs = [CX + 5]
    for (const side of [1, -1]) {
      let x = CX + 5
      for (;;) { x += side * wAt(r, x); if (x <= X_MIN || x >= X_MAX) break; xs.push(x) }
    }
    xs.sort((a, b) => a - b).forEach((x) => {
      if (rnd() < 0.2) return                                     // 빈자리도 조금
      const w = wAt(r, x), h = w * 0.78
      // 발밑 = 바로 앞줄 등받이 윗선 — 앞 의자 뒤에 앉은 것처럼
      out.push({ r, x, yc: yAt(r - 1, x) - h * 0.43, h, face: Math.floor(rnd() * 16), flip: rnd() < 0.5, phase: rnd() * Math.PI * 2 })
    })
  }
  return out
}

/** 화소 → 방향(카메라 기준 단위 벡터) — Environment 셰이더의 역 */
function dirOf(x, y) {
  const yaw = THREE.MathUtils.degToRad((x / IMG_W - 0.5) * ENV_YAW)
  const pitch = THREE.MathUtils.degToRad((0.5 - y / IMG_H) * ENV_PITCH)
  return new THREE.Vector3(Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), -Math.cos(yaw) * Math.cos(pitch))
}

function atlas() {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = 1024
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  const ctx = canvas.getContext('2d')
  NAMES.forEach((n, i) => MOODS.forEach((m, j) => {
    const img = new Image()
    img.onload = () => { ctx.drawImage(img, j * 256, i * 256, 256, 256); tex.needsUpdate = true }
    img.src = `assets/chick-${n}-${m}.svg`
  }))
  return tex
}

const vert = /* glsl */ `
  attribute vec4 aFace;     // 아틀라스 칸 x, y · 뒤집기 · 위상
  uniform float uTime, uHop;
  varying vec2 vUv;
  void main() {
    vec2 uv = uv;
    if (aFace.z > 0.5) uv.x = 1.0 - uv.x;
    vUv = (vec2(aFace.x, 3.0 - aFace.y) + uv) / 4.0;
    // 숨쉬기 + 목소리에 들썩 — 저마다 다른 박자
    float bob = sin(uTime * 1.6 + aFace.w) * 0.012 + max(0.0, sin(uTime * 7.0 + aFace.w * 3.0)) * uHop * 0.09;
    vec3 p = position + vec3(0.0, bob, 0.0);
    gl_Position = projectionMatrix * modelViewMatrix * instanceMatrix * vec4(p, 1.0);
  }
`
const frag = /* glsl */ `
  uniform sampler2D uMap;
  uniform float uOpacity;
  varying vec2 vUv;
  void main() {
    vec4 c = texture2D(uMap, vUv);
    if (c.a < 0.04) discard;
    gl_FragColor = vec4(c.rgb * 0.94, c.a * uOpacity);   // 극장 조명 아래 — 아주 조금 가라앉힌다
    #include <colorspace_fragment>
  }
`

export function Audience({ readLevel }) {
  const seats = useMemo(audienceSeats, [])
  const mesh = useRef()
  const hop = useRef(0)
  const mat = useMemo(() => new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, transparent: true, depthWrite: false, toneMapped: false,
    uniforms: { uMap: { value: atlas() }, uOpacity: { value: 0 }, uTime: { value: 0 }, uHop: { value: 0 } },
  }), [])
  const geo = useMemo(() => {
    const g = new THREE.PlaneGeometry(1, 1)
    g.setAttribute('aFace', new THREE.InstancedBufferAttribute(new Float32Array(seats.flatMap((s) => [s.face % 4, Math.floor(s.face / 4), s.flip ? 1 : 0, s.phase])), 4))
    return g
  }, [seats])

  // 자리 · 크기 · 방향 — 한 번만. 판은 카메라를 본다(시점 고정이라 돌릴 일이 없다)
  useEffect(() => {
    const m = mesh.current
    if (!m) return
    const o = new THREE.Object3D()
    const eye = new THREE.Vector3(0, EYE, 0)
    const perPx = THREE.MathUtils.degToRad(ENV_PITCH / IMG_H) * D
    seats.forEach((s, i) => {
      o.position.copy(dirOf(s.x, s.yc)).multiplyScalar(D).add(eye)
      o.lookAt(eye)
      o.scale.setScalar(s.h * perPx)
      o.updateMatrix()
      m.setMatrixAt(i, o.matrix)
    })
    m.instanceMatrix.needsUpdate = true
  }, [seats])

  useFrame((state, dt) => {
    const u = mat.uniforms
    u.uTime.value = state.clock.elapsedTime
    u.uOpacity.value = env.mix * env.readyB
    // 발표 중 음량 → 들썩임 (부드럽게 오르내린다). 움직임 줄이기를 고르면 가만히 앉아 있다
    const lv = rig.at === 1 && readLevel && !rig.reduced ? readLevel() : 0
    hop.current += (Math.min(1, lv * 1.6) - hop.current) * Math.min(1, dt * 4)
    u.uHop.value = hop.current
    if (mesh.current) mesh.current.visible = u.uOpacity.value > 0.01
  })

  return <instancedMesh ref={mesh} args={[geo, mat, seats.length]} renderOrder={-1} frustumCulled={false} />
}
