export const meta = {
  name: 'improve-qa',
  description: 'Q&A 프롬프트 가설을 벤치마크로 하나씩 시험해 좋아진 것만 남긴다 (실 LLM 호출 · 과금)',
  whenToUse: 'Q&A 질문 생성(F-08)·판정(F-09) 프롬프트를 자율적으로 개선할 때. args: {stamp(필수), maxVariants=3, rubric=true, judge=false, limit=2, focus="", push=false}',
  phases: [
    { title: 'Baseline', detail: '현재 프롬프트로 벤치마크 1회 (기준선)' },
    { title: 'Hypotheses', detail: '기준선 결과·프롬프트·장부를 읽고 가설 목록' },
    { title: 'Variants', detail: '가설마다: 고치기 → 문지기 → 벤치마크 → 채택/되돌리기' },
    { title: 'Report', detail: '작업 일지에 무엇을 시험했고 무엇이 남았는지' },
  ],
}

// ---- 설정 --------------------------------------------------------------
// 스크립트 안에서는 시각을 만들 수 없다(재개 호환). 호출자가 stamp 를 준다: "20260912-1130".
const cfg = Object.assign({ maxVariants: 3, judge: false, rubric: true, limit: 2, focus: '', push: false }, args || {})
if (!cfg.stamp || !/^\d{8}-\d{4}$/.test(String(cfg.stamp))) {
  throw new Error('args.stamp 가 필요해요 (YYYYMMDD-HHMM). 예: {"stamp":"20260912-1130"}')
}
cfg.maxVariants = Math.min(Number(cfg.maxVariants) || 3, 5)   // 과금 상한: 한 번에 최대 5변형
const benchFlags = `${cfg.rubric ? '--rubric ' : ''}${cfg.judge ? '--judge ' : ''}--limit ${cfg.limit}`
const EDITABLE = ['chuckchuck/f08_questions.py', 'chuckchuck/f09_judge.py']
const EDITABLE_STR = EDITABLE.join(' ')

const BENCH = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['IMPROVED', 'REGRESSED', 'NOISE', 'BASELINE', 'ERROR'] },
    tag: { type: 'string' }, summary: { type: 'string' }, reportPath: { type: 'string' }, detail: { type: 'string' },
  },
  required: ['verdict', 'tag', 'summary'],
}
const GUARD = {
  type: 'object',
  properties: { ok: { type: 'boolean' }, pytest: { type: 'string' }, secrets: { type: 'boolean' }, detail: { type: 'string' } },
  required: ['ok', 'detail'],
}
const HYP = {
  type: 'object',
  properties: {
    hypotheses: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' }, title: { type: 'string' },
          file: { type: 'string', enum: EDITABLE },
          change: { type: 'string' }, expected: { type: 'string' },
        },
        required: ['id', 'title', 'file', 'change', 'expected'],
      },
    },
  },
  required: ['hypotheses'],
}
const APPLY = {
  type: 'object',
  properties: { applied: { type: 'boolean' }, files: { type: 'array', items: { type: 'string' } }, note: { type: 'string' } },
  required: ['applied', 'note'],
}
const DONE = { type: 'object', properties: { ok: { type: 'boolean' }, detail: { type: 'string' } }, required: ['ok', 'detail'] }

// ---- 1. 기준선 -----------------------------------------------------------
phase('Baseline')
const baseTag = `base-${cfg.stamp}`
const base = await agent(
`.claude/agents/qa-bench-runner.md 를 먼저 읽고 그대로 따른다.

1. \`git status --short ${EDITABLE_STR}\` 가 비어 있는지 확인한다. 비어 있지 않으면 verdict 'ERROR' 로 돌려주고 멈춘다
   — 손대다 만 프롬프트 위에 기준선을 잡으면 이후 비교가 전부 거짓말이 된다.
2. \`scripts/qa_bench.sh --tag ${baseTag} ${benchFlags}\` 를 돌린다 (비교 없음). 마지막 줄이 VERDICT: BASELINE 이어야 한다.
3. verdict 는 'BASELINE', tag 는 '${baseTag}', summary 에 핵심 숫자를 적는다.`,
  { phase: 'Baseline', label: 'bench:baseline', schema: BENCH, effort: 'low' })
if (!base || base.verdict !== 'BASELINE') {
  return { error: '기준선을 잡지 못했어요', base }
}
log(`기준선 ${baseTag}: ${base.summary}`)

// ---- 2. 가설 -------------------------------------------------------------
phase('Hypotheses')
const hyp = await agent(
`너는 Q&A 프롬프트 개선 가설을 세우는 담당이다. 고치지 않는다 — 목록만 돌려준다.

읽을 것:
- 기준선 결과: exports/qa_eval/*_${baseTag}.json 의 summary 와 questions[] (생성된 질문 원문)
- 프롬프트 원본: ${EDITABLE_STR} (SYSTEM_PROMPT 와 컨텍스트 조립 함수)
- 설계 원칙: docs/PROMPT_DESIGN.md §1
- 장부: docs/QA_BENCH_LEDGER.md (있으면) — REGRESSED 로 끝난 가설을 되풀이하지 않는다
- 채점 기준: .claude/agents/qa-question-judge.md 의 rubric 표 (Groundedness·Relevance·Coverage·Depth·Answerability·Non-duplication·Hallucination)

기준선 질문을 rubric 으로 읽고, 가장 약한 항목을 고칠 가설을 최대 ${cfg.maxVariants}개 만든다. 효과가 클 것 같은 순서로.
${cfg.focus ? `이번 초점: ${cfg.focus}\n` : ''}
가설 하나의 조건:
- 변수 하나만 바꾼다 (프롬프트 문장 하나 추가/수정, 발췌 길이 상수 하나, few-shot 하나).
- file 은 ${EDITABLE_STR} 중 하나.
- change 는 qa-prompt-tuner 가 그대로 적용할 수 있게 구체적으로 (어느 상수/문단을, 무엇으로).
- expected 는 어느 벤치마크 지표가 어느 방향으로 움직여야 하는지 (예: "grounding_mean ↑, fallback 그대로").
- "자료에 없는 내용을 지어내지 마라" 문장 삭제, JSON 스키마 삭제, 모델 교체, fixtures 수정은 가설이 아니다.`,
  { phase: 'Hypotheses', label: 'hypotheses', schema: HYP })
const hyps = (hyp && hyp.hypotheses || []).slice(0, cfg.maxVariants)
if (!hyps.length) return { baseline: baseTag, accepted: baseTag, variants: [], note: '가설이 나오지 않았어요' }
log(`가설 ${hyps.length}개: ${hyps.map(h => h.title).join(' / ')}`)

// ---- 3. 변형 (순차 — 같은 파일을 고치므로 병렬 불가) ----------------------
phase('Variants')
let accepted = baseTag
const ledger = []
for (let i = 0; i < hyps.length; i++) {
  const h = hyps[i]
  const tag = `v${i + 1}-${cfg.stamp}`
  const revert = () => agent(
    `저장소 루트에서 \`git checkout -- ${EDITABLE_STR}\` 를 실행하고, \`git status --short ${EDITABLE_STR}\` 가 비어 있는지 확인해 ok 로 돌려준다. 다른 파일은 건드리지 않는다.`,
    { phase: 'Variants', label: `revert:${h.id}`, schema: DONE, effort: 'low' })

  const applied = await agent(
`.claude/agents/qa-prompt-tuner.md 를 먼저 읽고 그대로 따른다.

가설 ${h.id} — ${h.title}
파일: ${h.file}
바꿀 것: ${h.change}
기대 효과: ${h.expected}

이 한 가지만 적용한다. 절차 4(pytest)까지 끝내고 applied / files / note 를 돌려준다.`,
    { phase: 'Variants', label: `apply:${h.id}`, schema: APPLY })
  if (!applied || !applied.applied) {
    await revert()
    ledger.push({ ...h, tag, verdict: 'SKIPPED', note: applied ? applied.note : '에이전트 실패' })
    log(`${h.id} 건너뜀: ${applied ? applied.note : '에이전트 실패'}`)
    continue
  }

  const guard = await agent(
`.claude/agents/regression-guard.md 를 먼저 읽고 그대로 따른다.
허용된 파일 목록: ${EDITABLE_STR}. 검사 1·4·5 를 한다 (프론트는 안 바뀌었으니 2·3 은 생략).`,
    { phase: 'Variants', label: `guard:${h.id}`, schema: GUARD, effort: 'low' })
  if (!guard || !guard.ok) {
    await revert()
    ledger.push({ ...h, tag, verdict: 'GUARD_FAIL', note: guard ? guard.detail : '에이전트 실패' })
    log(`${h.id} 문지기 실패: ${guard ? guard.detail.slice(0, 120) : '에이전트 실패'}`)
    continue
  }

  const bench = await agent(
`.claude/agents/qa-bench-runner.md 를 먼저 읽고 그대로 따른다.
\`scripts/qa_bench.sh --tag ${tag} --compare ${accepted} --note "${h.id} ${h.title.replace(/"/g, "'")}" ${benchFlags}\` 를 돌리고
마지막 줄 VERDICT 와 리포트 경로, 핵심 숫자를 돌려준다.`,
    { phase: 'Variants', label: `bench:${h.id}`, schema: BENCH, effort: 'low' })
  const verdict = bench ? bench.verdict : 'ERROR'

  if (verdict === 'IMPROVED') {
    const commit = await agent(
`저장소 루트에서 ${EDITABLE_STR} 만 스테이징하고 커밋한다. 다른 파일은 절대 넣지 않는다.
커밋 메시지(왜 를 적는다):

feat(qa-prompt): ${h.title}

벤치마크 ${accepted} → ${tag}: ${bench.summary}
가설: ${h.change}
리포트: ${bench.reportPath || 'exports/qa_eval/reports/'}

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
${cfg.push ? '커밋 뒤 `git push origin HEAD` 까지 한다.' : '푸시는 하지 않는다 (사람이 장부를 보고 민다).'}
끝나면 \`git log --oneline -1\` 을 detail 에 넣고 ok 로 돌려준다.`,
      { phase: 'Variants', label: `commit:${h.id}`, schema: DONE, effort: 'low' })
    accepted = tag
    ledger.push({ ...h, tag, verdict, note: bench.summary, commit: commit ? commit.detail : '커밋 실패' })
    log(`${h.id} 채택 → 새 기준 ${tag}`)
  } else {
    await revert()
    ledger.push({ ...h, tag, verdict, note: bench ? (bench.summary || bench.detail) : '에이전트 실패' })
    log(`${h.id} ${verdict} → 되돌림`)
  }
}

// ---- 4. 보고 -------------------------------------------------------------
phase('Report')
const report = await agent(
`docs/WORKLOG.md 맨 위(작성 규칙 주석 아래, 첫 "## " 절 위)에 이번 루프 기록을 한 절 추가한다. 한다체.
제목: "## ${cfg.stamp.slice(0, 4)}-${cfg.stamp.slice(4, 6)}-${cfg.stamp.slice(6, 8)} — Q&A 프롬프트 자율 루프 (improve-qa, ${cfg.stamp})"
내용: 기준선 ${baseTag} 숫자 한 줄 → 표(가설 id · 제목 · 판정 · 핵심 델타) → 채택된 것이 있으면 커밋 해시,
없으면 "채택 없음 — 다음에 볼 가설" 한 줄. 장부 docs/QA_BENCH_LEDGER.md 와 리포트 폴더를 링크한다.
자료: ${JSON.stringify({ baseline: base.summary, accepted, variants: ledger })}
WORKLOG.md 만 고치고, 커밋은 하지 않는다. 끝나면 ok 와 추가한 절의 첫 줄을 돌려준다.`,
  { phase: 'Report', label: 'worklog', schema: DONE, effort: 'low' })

return { baseline: baseTag, accepted, variants: ledger, worklog: report ? report.detail : null }
