// 가상 발표 스튜디오 빌드 — src/main.jsx → ../js/studio-app.js (한 파일, 압축). 라이선스 주석은 파일 끝에 남긴다
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
if (watch) { const ctx = await esbuild.context(opts); await ctx.watch() } else { await esbuild.build(opts) }
