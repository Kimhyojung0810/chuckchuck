// 그라디언트 구 — UI Capsule 「Gradient Orb」(MIT, © 2023 Kaiyu Hsu, github.com/kyh/uicapsule content/gradient-orb)의 셰이더를
// three · R3F 없이 맨 WebGL 로 옮겼다(작은 구 하나에 three 번들을 싣지 않는다). 바뀐 점:
//  - 바탕을 투명하게(유리 카드 위에 얹는다) · 세 색을 uniform 으로(척척 초록)
//  - 신호(adapter)에 반응: thinking 은 천천히 숨쉬고, speaking 은 음량만큼 빨라지고 부푼다
//  - 화면 밖 · 탭 숨김 · 움직임 줄이기면 그리기를 멈춘다
import { useEffect, useRef } from 'react'

const VERT = `
attribute vec2 a_pos;
varying vec2 vUv;
void main() {
  vUv = a_pos * 0.5 + 0.5;
  gl_Position = vec4(a_pos, 0.0, 1.0);
}`

const FRAG = `
precision highp float;
uniform float iTime;
uniform vec3 iResolution;
uniform float rot;
uniform float noiseScale;
uniform float innerRadius;
uniform float level;
uniform vec3 baseColor0;
uniform vec3 baseColor1;
uniform vec3 baseColor2;
varying vec2 vUv;

vec3 hash33(vec3 p3) {
  p3 = fract(p3 * vec3(0.1031, 0.11369, 0.13787));
  p3 += dot(p3, p3.yxz + 19.19);
  return -1.0 + 2.0 * fract(vec3(p3.x + p3.y, p3.x + p3.z, p3.y + p3.z) * p3.zyx);
}

float snoise3(vec3 p) {
  const float K1 = 0.333333333;
  const float K2 = 0.166666667;
  vec3 i = floor(p + (p.x + p.y + p.z) * K1);
  vec3 d0 = p - (i - (i.x + i.y + i.z) * K2);
  vec3 e = step(vec3(0.0), d0 - d0.yzx);
  vec3 i1 = e * (1.0 - e.zxy);
  vec3 i2 = 1.0 - e.zxy * (1.0 - e);
  vec3 d1 = d0 - (i1 - K2);
  vec3 d2 = d0 - (i2 - K1);
  vec3 d3 = d0 - 0.5;
  vec4 h = max(0.6 - vec4(dot(d0, d0), dot(d1, d1), dot(d2, d2), dot(d3, d3)), 0.0);
  vec4 n = h * h * h * h * vec4(dot(d0, hash33(i)), dot(d1, hash33(i + i1)), dot(d2, hash33(i + i2)), dot(d3, hash33(i + 1.0)));
  return dot(vec4(31.316), n);
}

vec4 extractAlpha(vec3 c) {
  float a = max(max(c.r, c.g), c.b);
  return vec4(c.rgb / (a + 1e-5), a);
}

float light1(float intensity, float attenuation, float dist) { return intensity / (1.0 + dist * attenuation); }
float light2(float intensity, float attenuation, float dist) { return intensity / (1.0 + dist * dist * attenuation); }

vec4 draw(vec2 uv) {
  vec3 color3 = vec3(0.0);
  float len = length(uv);
  float invLen = len > 0.0 ? 1.0 / len : 0.0;
  float pulse = sin(iTime * 1.5) * 0.02 + level * 0.06;
  float n0 = snoise3(vec3(uv * noiseScale, iTime * 0.5)) * 0.5 + 0.5;
  float r0 = mix(mix(innerRadius + pulse, 1.0, 0.4), mix(innerRadius + pulse, 1.0, 0.6), n0);
  float d0 = distance(uv, (r0 * invLen) * uv);
  float v0 = light1(1.0, 10.0, d0);
  v0 *= smoothstep(r0 * 1.05, r0, len);
  float cl = cos(atan(uv.y, uv.x) + iTime * 2.0) * 0.5 + 0.5;
  float a = iTime * -1.0;
  vec2 pos = vec2(cos(a), sin(a)) * r0;
  float d = distance(uv, pos);
  float v1 = light2(1.5 + level, 5.0, d);
  v1 *= light1(1.0, 50.0, d0);
  float v2 = smoothstep(1.0, mix(innerRadius, 1.0, n0 * 0.5), len);
  float v3 = smoothstep(innerRadius, mix(innerRadius, 1.0, 0.5), len);
  vec3 col = mix(baseColor1, baseColor2, cl);
  col = mix(col, baseColor0, n0);
  col = mix(color3, col, v0);
  col = (col + v1) * v2 * v3;
  col = clamp(col, 0.0, 1.0);
  return extractAlpha(col);
}

void main() {
  vec2 center = iResolution.xy * 0.5;
  float size = min(iResolution.x, iResolution.y);
  vec2 uv = (vUv * iResolution.xy - center) / size * 2.0;
  uv /= 0.9 + level * 0.14;
  float s = sin(rot);
  float c = cos(rot);
  uv = vec2(c * uv.x - s * uv.y, s * uv.x + c * uv.y);
  vec4 col = draw(uv);
  gl_FragColor = vec4(col.rgb * col.a, col.a);
}`

function hexRgb(hex) {
  const h = hex.replace('#', '')
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
}

// 척척 v3 — 차분한 에메랄드 · 깊은 세이지 · 따뜻한 아이보리 (원본은 파랑 · 보라 · 주황)
export const ORB_COLORS = ['#6FB59A', '#344A40', '#E6E2D6']

function compile(gl, type, src) {
  const sh = gl.createShader(type)
  gl.shaderSource(sh, src)
  gl.compileShader(sh)
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) { gl.deleteShader(sh); return null }
  return sh
}

/** 맨 WebGL 그리개 — 실패하면 null(그때는 CSS 그라디언트 원이 대신한다) */
function createOrbRenderer(canvas, colors, noiseScale, innerRadius) {
  const gl = canvas.getContext('webgl', { alpha: true, antialias: true, premultipliedAlpha: true })
  if (!gl) return null
  const vs = compile(gl, gl.VERTEX_SHADER, VERT)
  const fs = compile(gl, gl.FRAGMENT_SHADER, FRAG)
  if (!vs || !fs) return null
  const prog = gl.createProgram()
  gl.attachShader(prog, vs)
  gl.attachShader(prog, fs)
  gl.linkProgram(prog)
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return null
  gl.useProgram(prog)
  const buf = gl.createBuffer()
  gl.bindBuffer(gl.ARRAY_BUFFER, buf)
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW)
  const loc = gl.getAttribLocation(prog, 'a_pos')
  gl.enableVertexAttribArray(loc)
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0)
  const u = (n) => gl.getUniformLocation(prog, n)
  const U = { time: u('iTime'), res: u('iResolution'), rot: u('rot'), level: u('level') }
  gl.uniform1f(u('noiseScale'), noiseScale)
  gl.uniform1f(u('innerRadius'), innerRadius)
  colors.forEach((c, i) => gl.uniform3fv(u(`baseColor${i}`), hexRgb(c)))
  gl.clearColor(0, 0, 0, 0)
  return {
    draw(t, r, lv) {
      gl.viewport(0, 0, canvas.width, canvas.height)
      gl.clear(gl.COLOR_BUFFER_BIT)
      gl.uniform1f(U.time, t)
      gl.uniform1f(U.rot, r)
      gl.uniform1f(U.level, lv)
      gl.uniform3f(U.res, canvas.width, canvas.height, 1)
      gl.drawArrays(gl.TRIANGLES, 0, 3)
    },
    destroy() {
      gl.deleteBuffer(buf); gl.deleteProgram(prog); gl.deleteShader(vs); gl.deleteShader(fs)
      const lose = gl.getExtension('WEBGL_lose_context')
      if (lose) lose.loseContext()
    },
  }
}

// 상태별 흐름 속도(시간 배속) — 원본은 1. 생각은 느긋하게, 말은 음량만큼 빨라진다
const SPEED = { thinking: 0.55, speaking: 1.0, listening: 0.8, connecting: 0.55, idle: 0.3, error: 0.3 }

/**
 * @param adapter  orb-ui 와 같은 신호 adapter — subscribe(({state, outputVolume, inputVolume}) => …)
 * @param size     px
 */
export function GradientOrb({ adapter, size = 64, colors = ORB_COLORS, rotationSpeed = 0.3, noiseScale = 0.65, innerRadius = 0.1, label = '삐약이 목소리' }) {
  const canvasRef = useRef(null)
  const sig = useRef({ state: 'thinking', volume: 0 })

  useEffect(() => {
    if (!adapter) return undefined
    return adapter.subscribe((s) => {
      sig.current = { state: s.state, volume: s.state === 'listening' ? (s.inputVolume || 0) : (s.outputVolume || 0) }
    })
  }, [adapter])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return undefined
    const dpr = Math.min(2, window.devicePixelRatio || 1)
    canvas.width = Math.round(size * dpr)
    canvas.height = Math.round(size * dpr)
    const r = createOrbRenderer(canvas, colors, noiseScale, innerRadius)
    if (!r) { canvas.dataset.fallback = '1'; return undefined }
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)')
    let raf = 0
    let last = performance.now()
    let t = 0
    let rot = 0
    let lv = 0
    let onScreen = true
    const io = 'IntersectionObserver' in window
      ? new IntersectionObserver((es) => { onScreen = es.some((e) => e.isIntersecting); if (onScreen) kick() })
      : null
    if (io) io.observe(canvas)
    const frame = (now) => {
      raf = 0
      const dt = Math.min(0.05, (now - last) / 1000)
      last = now
      const { state, volume } = sig.current
      // 음량은 오를 땐 빠르게(80ms) · 내릴 땐 천천히(260ms) 따라간다 — 깜빡이지 않게
      const k = 1 - Math.exp(-dt / (volume > lv ? 0.08 : 0.26))
      lv += (volume - lv) * k
      if (!reduce.matches) {
        t += dt * ((SPEED[state] ?? 1) + (state === 'speaking' ? lv * 1.2 : 0))
        rot += dt * rotationSpeed
      }
      r.draw(t, rot, reduce.matches ? 0 : lv)
      if (onScreen && !document.hidden && !reduce.matches) raf = requestAnimationFrame(frame)
    }
    const kick = () => { if (!raf) { last = performance.now(); raf = requestAnimationFrame(frame) } }
    const onVis = () => { if (!document.hidden) kick() }
    document.addEventListener('visibilitychange', onVis)
    reduce.addEventListener?.('change', kick)
    kick()
    return () => {
      cancelAnimationFrame(raf)
      if (io) io.disconnect()
      document.removeEventListener('visibilitychange', onVis)
      reduce.removeEventListener?.('change', kick)
      r.destroy()
    }
  }, [size, colors, rotationSpeed, noiseScale, innerRadius])

  return (
    <span className="cv-orb cv-orb--gradient" role="img" aria-label={label} style={{ width: size, height: size }}>
      <canvas ref={canvasRef} style={{ width: size, height: size }} />
    </span>
  )
}
