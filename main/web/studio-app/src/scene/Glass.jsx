/* 유리 — liquid-glass-js(MIT, Armagan Amcalar, github.com/dashersw/liquid-glass-js)의 굴절 셰이더를 three 재질로 옮긴 것.
   원본은 html2canvas 로 찍은 페이지 사진을 굴절시키지만 3D 변환 · <video> 를 못 찍는다 → 여기서는 매 프레임 그린
   「유리를 뺀 장면(방 + 카메라 화면)」 을 화면 좌표로 굴절시킨다 (design/SPACE.md §8).
   옮기며 바꾼 것: 배경 = 장면 텍스처(반 해상도), 색 막 = 우리 토큰(어두운/종이), 원본의 「배경 색 표본 그라디언트」(60×11×3 표본)는
   매 프레임 하기엔 무거워 세로 그라디언트 막으로 대신했다. 가장자리 · 테두리 · 바탕 굴절 · 모서리 강조 · 물결 · 13×13 흐림은 원본 그대로. */
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import { useFrame, useThree } from '@react-three/fiber'
import { useFBO } from '@react-three/drei'

export const glassMeshes = new Set()
const shared = { fbo: null }

/** 매 프레임 유리를 뺀 장면을 반 해상도 텍스처에 그린다 — 유리 재질이 이걸 굴절시킨다 */
export function GlassPass() {
  const size = useThree((s) => s.size)
  const dpr = useThree((s) => s.viewport.dpr)
  const fbo = useFBO(Math.max(2, Math.round(size.width * dpr / 2)), Math.max(2, Math.round(size.height * dpr / 2)), { samples: 0, depthBuffer: true })
  shared.fbo = fbo
  useFrame(({ gl, scene, camera }) => {
    if (!glassMeshes.size) return
    glassMeshes.forEach((m) => { m.userData.wasVisible = m.visible; m.visible = false })
    gl.setRenderTarget(fbo)
    gl.clear()
    gl.render(scene, camera)
    gl.setRenderTarget(null)
    glassMeshes.forEach((m) => { m.visible = m.userData.wasVisible })
  })
  return null
}

const vert = /* glsl */ `
  varying vec2 vUv;
  void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
`
const frag = /* glsl */ `
  uniform sampler2D uScene;
  uniform vec2 uRes;          // 그리는 판 크기(물리 화소)
  uniform vec2 uTexel;        // 장면 텍스처 한 칸
  uniform vec2 uSize;         // 창 크기(CSS px) — 모양 · 거리 계산
  uniform float uRadius;
  uniform vec3 uTint;
  uniform float uTintOpacity;
  uniform float uOpacity;
  uniform float uBlur;
  uniform float uEdgeIntensity, uRimIntensity, uBaseIntensity, uEdgeDistance, uRimDistance, uBaseDistance, uCornerBoost, uRipple;
  varying vec2 vUv;

  float roundedRectDistance(vec2 coord, vec2 size, float radius) {
    vec2 center = size * 0.5;
    vec2 pixelCoord = coord * size;
    vec2 toCorner = abs(pixelCoord - center) - (center - radius);
    float outsideCorner = length(max(toCorner, 0.0));
    float insideCorner = min(max(toCorner.x, toCorner.y), 0.0);
    return (outsideCorner + insideCorner - radius);
  }

  void main() {
    vec2 coord = vec2(vUv.x, 1.0 - vUv.y);                 // 원본처럼 왼쪽 위가 (0,0)
    float sd = roundedRectDistance(coord, uSize, uRadius);
    if (sd > 0.0) discard;
    float aa = clamp(-sd, 0.0, 1.0);                       // 가장자리 1px 부드럽게

    float distFromEdgeShape = max(-sd, 0.0);
    vec2 shapeNormal = normalize(coord - vec2(0.5) + 1e-5);
    float normalizedDistance = distFromEdgeShape;
    float baseIntensity = 1.0 - exp(-normalizedDistance * uBaseDistance);
    float edgeIntensity = exp(-normalizedDistance * uEdgeDistance);
    float rimIntensity = exp(-normalizedDistance * uRimDistance);
    float totalIntensity = baseIntensity * uBaseIntensity + edgeIntensity * uEdgeIntensity + rimIntensity * uRimIntensity;
    vec2 baseRefraction = shapeNormal * totalIntensity;

    float cornerProximityX = min(coord.x, 1.0 - coord.x);
    float cornerProximityY = min(coord.y, 1.0 - coord.y);
    float cornerNormalized = max(cornerProximityX, cornerProximityY) * min(uSize.x, uSize.y);
    vec2 cornerRefraction = shapeNormal * exp(-cornerNormalized * 0.3) * uCornerBoost;

    vec2 perpendicular = vec2(-shapeNormal.y, shapeNormal.x);
    float distFromEdge = distFromEdgeShape / min(uSize.x, uSize.y);
    vec2 textureRefraction = perpendicular * sin(distFromEdge * 25.0) * uRipple * rimIntensity;

    vec2 refr = baseRefraction + cornerRefraction + textureRefraction;
    refr.y = -refr.y;                                      // 창 좌표(아래로 +)를 화면 좌표(위로 +)로
    vec2 uv = clamp(gl_FragCoord.xy / uRes + refr, vec2(0.001), vec2(0.999));   // 화면 밖을 읽어 가장자리가 늘어지지 않게

    // 13×13 가우스 흐림 (원본 그대로)
    vec4 color = vec4(0.0);
    float sigma = uBlur / 2.0;
    vec2 blurStep = uTexel * sigma;
    float totalWeight = 0.0;
    for (float i = -6.0; i <= 6.0; i += 1.0) {
      for (float j = -6.0; j <= 6.0; j += 1.0) {
        float dist = length(vec2(i, j));
        if (dist > 6.0) continue;
        float w = exp(-(dist * dist) / (2.0 * sigma * sigma));
        color += texture2D(uScene, uv + vec2(i, j) * blurStep) * w;
        totalWeight += w;
      }
    }
    color /= totalWeight;

    // 색 막 — 위가 조금 밝고 아래로 가라앉는 세로 그라디언트 (원본의 흰→회색 막 자리)
    vec3 tint = mix(uTint * 1.25, uTint * 0.85, coord.y);
    vec3 col = mix(color.rgb, tint, uTintOpacity);
    // 테두리 빛줄 — 유리 가장자리가 빛을 받는다
    col += vec3(1.0, 0.97, 0.92) * rimIntensity * 0.08;
    col += vec3(1.0) * 0.05 * (1.0 - smoothstep(0.0, 0.38, coord.y));   // 위쪽 빛 반사 (v3-2 sheen)
    gl_FragColor = vec4(col, uOpacity * aa);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`

/** 창 크기의 유리 판. widthPx/heightPx 는 CSS px, world 는 화면 1px 의 세계 길이 */
export function GlassPanel({ widthPx, heightPx, radius = 24, world, paper = false, tint, opacityRef, position = [0, 0, 0] }) {
  const mesh = useRef()
  const gl = useThree((s) => s.gl)
  const size = useThree((s) => s.size)
  const mat = useMemo(() => new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, transparent: true, depthWrite: false, toneMapped: true,
    uniforms: {
      uScene: { value: null }, uRes: { value: new THREE.Vector2(1, 1) }, uTexel: { value: new THREE.Vector2(1, 1) },
      uSize: { value: new THREE.Vector2(widthPx, heightPx) }, uRadius: { value: radius },
      uTint: { value: new THREE.Color(paper ? '#F4F0E8' : '#222724') }, uTintOpacity: { value: tint ?? (paper ? 0.8 : 0.72) },
      uOpacity: { value: 1 }, uBlur: { value: 7 },
      uEdgeIntensity: { value: 0.008 }, uRimIntensity: { value: 0.05 }, uBaseIntensity: { value: 0.006 },
      uEdgeDistance: { value: 0.15 }, uRimDistance: { value: 0.8 }, uBaseDistance: { value: 0.1 },
      uCornerBoost: { value: 0.02 }, uRipple: { value: 0.03 },
    },
  }), [widthPx, heightPx, radius, paper, tint])

  useFrame(() => {
    if (!mesh.current) return
    const u = mat.uniforms
    u.uScene.value = shared.fbo ? shared.fbo.texture : null
    const dpr = gl.getPixelRatio()
    u.uRes.value.set(size.width * dpr, size.height * dpr)
    if (shared.fbo) u.uTexel.value.set(1 / shared.fbo.width, 1 / shared.fbo.height)
    u.uOpacity.value = opacityRef ? opacityRef.current : 1
    mesh.current.visible = u.uOpacity.value > 0.01 && !!shared.fbo
  })

  return (
    <mesh ref={(m) => { if (m) { mesh.current = m; glassMeshes.add(m) } else if (mesh.current) glassMeshes.delete(mesh.current) }}
      position={position} material={mat} renderOrder={2}>
      <planeGeometry args={[widthPx * world, heightPx * world]} />
    </mesh>
  )
}
