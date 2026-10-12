// 빌드 — 라이선스 주석은 파일 끝에 남긴다
//  src/main.jsx         → ../js/studio-app.js (가상 발표 스튜디오)
//  src/voice/driver.jsx → ../js/voice-viz.js  (음성 시각화 window.ChuckVoice — 비전 리허설 · 글라스 화상판, index.html lazyAssets beta)
import * as esbuild from 'esbuild'
const watch = process.argv.includes('--watch')
const opts = {
  entryPoints: ['src/main.jsx'],
  outfile: '../js/studio-app.js',
  bundle: true,
  minify: !watch,
  format: 'iife',
  target: ['es2020'],
  jsx: 'automatic',
  legalComments: 'eof',
  define: { 'process.env.NODE_ENV': watch ? '"development"' : '"production"' },
  logLevel: 'info',
}
const voice = { ...opts, entryPoints: ['src/voice/driver.jsx'], outfile: '../js/voice-viz.js' }
for (const o of [opts, voice]) {
  if (watch) { const ctx = await esbuild.context(o); await ctx.watch() } else { await esbuild.build(o) }
}
