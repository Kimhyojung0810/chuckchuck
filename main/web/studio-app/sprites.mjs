// 세트 병아리 그림 — Piyak 컴포넌트(src/piyak)를 그대로 정지 SVG 로 뽑는다 → ../assets/chick-{who}-{mood}.svg (16장)
// 3D 세트(src/scene/Sets.jsx)가 이 파일을 캔버스에 그려 텍스처로 쓴다. 삐약이 모양 · 소품을 고치면 다시 돌린다:  npm run sprites
// 손으로 그리지 않는 이유: 화면의 삐약이(Piyak)와 세트 병아리가 따로 놀지 않게 원본을 하나로 둔다
import * as esbuild from 'esbuild'
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createRequire } from 'node:module'

const WHO = ['ax', 'exaone', 'midm', 'solar']
const MOODS = ['neutral', 'happy', 'curious', 'excited']
const NAMES = { ax: '엑씨', exaone: '엑사원', midm: '믿음', solar: '쏠라' }
const VIEWBOX = '-10 -18 120 120'    // 정사각형 — 발이 아래쪽에 오게 (Sets.jsx 가 발 위치에 맞춰 세운다)

// 화면용 CSS 의 삐약이 블록을 그대로 싣는다 — 색 · 표정 규칙이 하나로 남게
const css = readFileSync('../css/studio-app.css', 'utf8')
const start = css.indexOf('/* ── 삐약이 (studio-app/src/piyak)')
const end = css.indexOf('@media (prefers-reduced-motion: reduce)', start)
if (start < 0 || end < 0) throw new Error('css/studio-app.css 에서 삐약이 블록을 못 찾았어요')
const block = css.slice(start, end)
  .replace(/\.px-stage \{[^}]*\}/, '')               // 칸 배치 · 크기는 그림에 필요 없다
  .replace(/\.px-chick \{[^}]*\}/, '')               // 버튼 모양(둥근 모서리 · 크기)도 — 그림 가장자리가 잘린다
  .replaceAll('.px-chick svg :is', '.px-chick :is')  // 그림에서는 svg 자신이 .px-chick
const vars = '--px-body:#FFD96A;--px-line:#356B59;--px-mint:#9ADBC0;--px-beak:#F0A93C;--px-blush:#F7B6A8;'
const style = `svg.px-chick{${vars}}${block}*{animation:none!important;transition:none!important}.px-glow{display:none}`

const dir = mkdtempSync(join(tmpdir(), 'px-sprites-'))
const entry = join(dir, 'entry.jsx')
writeFileSync(entry, `
import { renderToStaticMarkup } from 'react-dom/server'
import { Piyak } from ${JSON.stringify(join(process.cwd(), 'src/piyak/Piyak.jsx'))}
export const render = (who, mood) => renderToStaticMarkup(<Piyak who={who} mood={mood} />)
`)
const out = join(dir, 'entry.cjs')   // react-dom/server 가 CommonJS 라 cjs 로 묶어 require 한다
await esbuild.build({ entryPoints: [entry], outfile: out, bundle: true, format: 'cjs', platform: 'node', jsx: 'automatic',
  nodePaths: [join(process.cwd(), 'node_modules')], define: { 'process.env.NODE_ENV': '"production"' }, logLevel: 'warning' })
const { render } = createRequire(import.meta.url)(out)

for (const who of WHO) {
  for (const mood of MOODS) {
    const html = render(who, mood)
    const inner = html.slice(html.indexOf('<svg'), html.lastIndexOf('</svg>') + 6)
      .replace(/^<svg[^>]*>/, '')
      .replace(/<\/svg>$/, '')
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" class="px-chick" data-preset="cute" data-mood="${mood}" viewBox="${VIEWBOX}" width="1024" height="1024" role="img" aria-label="${NAMES[who]} 병아리"><style>${style}</style>${inner}</svg>\n`
    writeFileSync(`../assets/chick-${who}-${mood}.svg`, svg)
  }
}
rmSync(dir, { recursive: true, force: true })
console.log(`assets/chick-*.svg ${WHO.length * MOODS.length}장`)
