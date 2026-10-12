// 음성 시각화 부품 — 내 목소리는 orb-ui(MIT) Bars, 삐약이의 생각 · 말은 GradientOrb(UI Capsule, MIT — 10-13 사용자: Cloud 대신). 신호는 adapter 로 받아 부모를 다시 그리지 않는다.
import { Orb } from 'orb-ui'
import { GradientOrb } from './GradientOrb.jsx'

// 초록 계열 (app.css: --brand #0E8850 · --cyan #3fd599 · --mint #aeefd5 · --navy #064E3B)
const BAR_COLORS = {
  idle: '#7d8a83',
  connecting: '#aeefd5',
  listening: '#3fd599',
  thinking: '#aeefd5',
  speaking: '#aeefd5',
  error: '#ff8a7a',
}

export const BARS_THEME = {
  name: 'bars',
  preset: 'balanced',
  appearance: { colors: BAR_COLORS },
  // 하단 막대줄(높이 20~28px)에 맞게 — 막대를 굵고 키 크게
  geometry: { barWidthRatio: 0.11, gapRatio: 0.07, minHeightRatio: 0.12, maxHeightRatio: 0.92, borderRadiusRatio: 0.06 },
  motion: { responseExponent: 0.8, activityRiseMs: 60, activityFallMs: 140 },
}

// 밝은 유리 판(리허설 흐름의 하단 독) 위 — 민트는 흰 바탕에서 안 보여서 브랜드 초록 (흰 바탕 4.5:1)
export const BARS_THEME_LIGHT = {
  ...BARS_THEME,
  appearance: { colors: { ...BAR_COLORS, idle: '#9aa59f', listening: '#0e8850', thinking: '#0a6e48', speaking: '#0a6e48' } },
}

/** 내 목소리 — 마이크 음량에 따라 다섯 막대. tone: 'dark'(어두운 판) | 'light'(밝은 판) */
export function VoiceBars({ adapter, size = 40, tone = 'dark', label = '마이크 입력' }) {
  return <Orb adapter={adapter} theme={tone === 'light' ? BARS_THEME_LIGHT : BARS_THEME} size={size} interactive={false} aria-label={label} className="cv-orb cv-orb--bars" />
}

/** view: 'bars' | 'orb' | null — null 이면 아무것도 그리지 않는다(구의 WebGL 을 내린다) */
export function VoiceViz({ view, adapter, barsSize, orbSize, tone, label }) {
  if (view === 'bars') return <VoiceBars adapter={adapter} size={barsSize} tone={tone} label={label} />
  if (view === 'orb') return <GradientOrb adapter={adapter} size={orbSize} label={label} />
  return null
}
