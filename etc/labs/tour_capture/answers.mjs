/**
 * 투어 녹화용 「잘 답한 답」 · 「엉성한 답」 글 만들기 — 부스 체험 줄(qa_live.js 「정답 보기」 · 「대충 답해 보기」)과 **같은 함수**를 쓴다.
 *
 *   echo '[{질문}, …]' | node etc/labs/tour_capture/answers.mjs
 *   → [{ id, model: "정답 보기 글(골자)", weak: "대충 답해 보기 글", trap: bool }, …]
 *
 * 손으로 베낀 사본을 두지 않는다 — qa_live.js 를 vm 에 통째로 올려 원본 함수를 부른다(etc/tests/js/qa_live.smoke.mjs 와 같은 방법).
 * 원본이 바뀌면 녹화도 그 규칙을 따른다. 함정 질문(골자를 숨긴 것)은 model 이 비어 있다 — 서버 reveal 로 받아 오는 건 capture.py 몫.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const SRC = readFileSync(path.join(ROOT, 'main/web/js/qa_live.js'), 'utf8');
const EXPORT = ';globalThis.__api = { liveWeakAnswer, liveWholeSentences, liveTryIsTrap };';

const ctx = vm.createContext({ console });
vm.runInContext(SRC + EXPORT, ctx, { filename: 'qa_live.js' });
const api = ctx.__api;

const questions = JSON.parse(readFileSync(0, 'utf8') || '[]');
const out = questions.map((q) => {
  const trap = !!api.liveTryIsTrap(q);
  const gist = api.liveWholeSentences(String(q.answer_gist || ''));
  return { id: q.id, trap, model: trap || q.gist_withheld ? '' : gist, weak: api.liveWeakAnswer(q) };
});
process.stdout.write(JSON.stringify(out));
