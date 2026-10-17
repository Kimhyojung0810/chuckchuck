/* 사진 환경 — visionOS 의 「환경」처럼 사용자를 둘러싼 실사 공간 (10-17 사용자 「비전프로처럼 사진 배경 3D」).
   정거장마다 어울리는 곳: 차분한 산 들판(준비 · 채점 · 리포트), 객석이 보이는 극장(발표 · 질의응답 · 청중석).
   단계가 바뀌면 곡선이 미끄러지는 동안 두 사진이 천천히 겹쳐 바뀐다. 배경은 움직이지 않는다(SPACE v3 — 시점 고정).
   사진은 Poly Haven CC0 360° 의 정면 200° × 100° 만 잘라 둔 것 (etc/scripts/make_studio_env.py — ENV_YAW · ENV_PITCH 가 같아야 한다). */
import { useEffect, useMemo } from 'react'
import * as THREE from 'three'
import { useFrame, useThree } from '@react-three/fiber'
import { easing } from 'maath'
import { rig } from '../rig.js'
import { ENV_OF, EYE, slideSeconds } from '../config.js'

export const ENV_YAW = 200
export const ENV_PITCH = 100
/** 지금 겹침 상태 — 극장 객석의 삐약이(Audience)가 극장 사진과 함께 드러나게 읽는다 */
export const env = { mix: 0, readyB: 0 }
export const ENV_NAMES = ['alps', 'theater']
const R = 40

const vert = /* glsl */ `
  varying vec3 vDir;
  void main() { vDir = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
`
// 방향 → 잘라 둔 사진의 좌표. 앞(-z)이 가운데, 오른쪽(+x)이 오른쪽. 범위 밖(한 번도 안 보이는 뒤 · 발밑)은 가장자리 색으로 늘인다
const frag = /* glsl */ `
  uniform sampler2D uA, uB;
  uniform float uMix, uReadyA, uReadyB, uBright;
  uniform vec3 uBase;
  varying vec3 vDir;
  const float PI = 3.14159265;
  void main() {
    vec3 d = normalize(vDir);
    float yaw = atan(d.x, -d.z);
    float pitch = asin(clamp(d.y, -1.0, 1.0));
    vec2 uv = vec2(yaw / radians(${ENV_YAW.toFixed(1)}) + 0.5, pitch / radians(${ENV_PITCH.toFixed(1)}) + 0.5);
    uv = clamp(uv, vec2(0.0005), vec2(0.9995));
    vec3 a = mix(uBase, texture2D(uA, uv).rgb, uReadyA);
    vec3 b = mix(uBase, texture2D(uB, uv).rgb, uReadyB);
    gl_FragColor = vec4(mix(a, b, uMix) * uBright, 1.0);
    #include <colorspace_fragment>
  }
`

export function Environment({ small = false }) {
  const gl = useThree((s) => s.gl)
  const mat = useMemo(() => new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, side: THREE.BackSide, depthWrite: false, fog: false, toneMapped: false,
    uniforms: {
      uA: { value: null }, uB: { value: null }, uMix: { value: ENV_OF[rig.at] === 1 ? 1 : 0 },
      uReadyA: { value: 0 }, uReadyB: { value: 0 }, uBright: { value: 1 }, uBase: { value: new THREE.Color('#F3F3F6') },
    },
  }), [])

  // 사진 둘 — 정면에 보일 것부터. 다 받을 때까지는 지금 바탕색, 받으면 천천히 드러난다
  useEffect(() => {
    const loader = new THREE.TextureLoader()
    const first = ENV_OF[rig.at] || 0
    const order = first === 1 ? [1, 0] : [0, 1]
    let dead = false
    const got = []
    order.forEach((i) => {
      loader.load(`assets/env/${ENV_NAMES[i]}${small ? '-sm' : ''}.webp`, (tex) => {
        if (dead) { tex.dispose(); return }
        tex.colorSpace = THREE.SRGBColorSpace
        tex.anisotropy = Math.min(8, gl.capabilities.getMaxAnisotropy())
        tex.generateMipmaps = true
        tex.minFilter = THREE.LinearMipmapLinearFilter
        mat.uniforms[i === 0 ? 'uA' : 'uB'].value = tex
        got.push(tex)
      }, undefined, () => { /* 못 받으면 바탕색 그대로 — 화면은 돈다 */ })
    })
    return () => { dead = true; got.forEach((t) => t.dispose()) }
  }, [small, gl, mat])

  useFrame((_, dt) => {
    const u = mat.uniforms
    const st = rig.reduced ? 0.0001 : 0.4
    easing.damp(u.uReadyA, 'value', u.uA.value ? 1 : 0, st, dt)
    easing.damp(u.uReadyB, 'value', u.uB.value ? 1 : 0, st, dt)
    // 미끄러지는 시간 안에 겹쳐 바뀐다 — 한 칸 1.5초 곡선의 절반쯤
    easing.damp(u.uMix, 'value', ENV_OF[rig.at] === 1 ? 1 : 0, rig.reduced ? 0.0001 : slideSeconds(1) * 0.3, dt)
    // 움직이는 동안 공간이 조금 밝아지고, 멈추면 살짝 가라앉아 창에 집중한다 (Lights 와 같은 리듬)
    u.uBright.value = 0.94 + 0.06 * rig.motion
    env.mix = u.uMix.value
    env.readyB = u.uReadyB.value
  })

  return (
    <mesh material={mat} position={[0, EYE, 0]} renderOrder={-2} frustumCulled={false}>
      <sphereGeometry args={[R, 96, 48]} />
    </mesh>
  )
}
