"""
제안 2판 — 전략은 LLM 이 고르지 않는다. ① 읽기(LLM): 답에서 핵심 구절 · 흐린 말 · 자료와 어긋난 말 · 반대 의견을 **원문 구절로** 뽑는다
② 정책(코드): 채점 + 읽기 신호로 전략을 정한다 ③ 쓰기(LLM): 그 전략 하나의 꼴로 반응 · 꼬리질문 ④ 검사(코드): 원문 구절 · 수치 흘림 · 구절 연결.
1판(move.py)은 LLM 에게 전략까지 맡겼더니 7개 중 4개가 deepen 이었고 자료 수치를 흘렸다 (2026-10-13 실측).
"""
import argparse, json, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "main"))
from pipeline.config import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")
from pipeline.providers.llm_impl import get_llm  # noqa: E402
from server.session_archive import SessionArchive  # noqa: E402
sys.path.insert(0, str(Path(__file__).parent))
from move import deck_lines  # noqa: E402
from pipeline.f09_judge import _answer_claim  # noqa: E402

READ = """발표자의 답을 **읽기만** 한다. 판정하지 말고, 답 원문에서 구절을 낱말 그대로 뽑아라(고치지 마라, 없으면 빈 문자열).
- idea: 발표자가 내세운 핵심 생각 한 구절(40자 안).
- vague: 뜻이 흐린 말(「좀 다를 것 같다」「그런 것 같다」「상황마다」 같은)이 핵심을 대신하고 있으면 그 구절.
- conflict: 자료 줄과 **사실이 어긋나는** 말(조건 · 수치 · 방향 · 범위)이 있으면 그 구절, conflict_slide 에 어긋나는 자료 장 번호.
- disagree: 발표자가 자료의 결론 · 질문의 전제에 **반대하는 의견**을 냈으면 그 구절.
- unknown: 모르겠다 · 기억 안 난다는 말뿐이면 true.
JSON: {"idea":"","vague":"","conflict":"","conflict_slide":0,"disagree":"","unknown":false}"""

SHAPE = {
    "deepen": "맞힌 내용에서 한 단계 더 — 그 생각이 **왜** 그런지(원리) 또는 **어디까지** 통하는지(적용 · 한계)를 묻는다.",
    "connect": "발표자가 말한 것은 살리고, 그 말과 질문 사이에 **빠진 고리 하나**를 묻는다. 빠진 것의 내용을 말해 주지 마라.",
    "clarify": "흐린 말이 정확히 무엇을 뜻하는지 묻는다 — 「(흐린 말)이라고 했는데, 무엇이 어떻게 다르다는 뜻이에요?」 꼴. 구체적인 조건 하나를 떠올리게 한다.",
    "challenge": "어긋난 말과 자료가 부딪히는 지점을 보여 주고 직접 확인하게 한다 — 「(그 말)이라고 했는데, 자료 N장의 (볼 곳)은 어떻게 돼 있어요?」 꼴. 정답 값은 말하지 마라.",
    "explore": "반대 의견을 존중하고 그 이유를 묻는다. 그리고 자료의 어느 결과와 견줘 볼지 묻는다 — 정답을 들이밀지 마라.",
    "hint": "정답은 말하지 말고 볼 곳 하나(자료 몇 장의 무엇)만 가리킨 뒤, 예/아니오로도 답할 수 있는 아주 쉬운 질문 하나.",
}

WRITE = """너는 발표 연습 상대 「삐약이」다. 전략은 이미 정해졌다: {strategy} — {shape}
- reaction: 한 문장(30자 안팎). 발표자가 한 **그 말**을 가리킨다. 빈 칭찬 · 「좋은 답」 · 답 되풀이 금지. 틀린 말을 맞다고 하지 마라.
- follow_up_question: 한 문장 질문. 아래 「붙잡을 구절」을 질문 안에서 직접 가리켜야 한다(그 낱말을 쓰거나 「~라고 했는데」로 받는다).
- 자료의 수치 · 퍼센트 · 정답 문장을 reaction · 질문에 쓰지 마라. 발표자가 먼저 말한 수치만 써도 된다.
- 해요체, 「~시」 존칭 금지. 원래 질문을 되풀이하지 마라.
JSON: {{"reaction":"","follow_up_question":"","source_slide":0}}"""

UNKNOWN_RE = re.compile(r"모르겠|기억이 안|잘 몰라|모름")

def policy(verdict: str, read: dict, answer: str, give_up: bool) -> str:
    """전략 — 채점과 읽기 신호에서. 순서가 곧 우선순위다"""
    if give_up or not answer.strip() or (read.get("unknown") and len(answer) < 30) or (UNKNOWN_RE.search(answer) and len(answer) < 20):
        return "hint"
    if read.get("disagree"):
        return "explore"
    if read.get("conflict"):
        return "challenge"
    if verdict == "good":
        return "deepen"
    if read.get("vague"):
        return "clarify"
    return "connect"

NUM_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%p|%|°C|도|사이클|개|점)")

def check(answer: str, idea: str, mv: dict, question: str = "") -> list[str]:
    bad = []
    q = mv.get("follow_up_question", "")
    leaked = [n for n in NUM_RE.findall(q + " " + mv.get("reaction", "")) if n.replace(" ", "") not in (answer + question).replace(" ", "")]
    if leaked:
        bad.append(f"수치 흘림 {leaked}")
    if idea:
        words = [w for w in re.findall(r"[가-힣A-Za-z0-9°]{2,}", idea) if w not in ("에서", "있어요", "거예요", "같아요")]
        if not any(w[:2] in q for w in words):
            bad.append("붙잡은 구절과 질문이 안 이어짐")
    return bad

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", required=True)
    ap.add_argument("--session", required=True)
    ap.add_argument("--llm", default="")
    ap.add_argument("--question", default="2C 충전은 500 사이클에서 용량의 4분의 1을 깎았다 라는 결과가 어떤 조건에서만 성립하는지 설명해 주세요.")
    a = ap.parse_args()
    probe = json.loads(Path(a.probe).read_text())
    doc = SessionArchive(ROOT / "var" / "data").read_artifact(a.session, "slide_doc")
    lines = "\n".join(deck_lines(doc, {2, 3, 4}))
    llm = get_llm(a.llm or None)
    rows = {}
    for k, r in probe.items():
        if "answer" not in r:
            continue
        ans = r["answer"] or ""
        t = time.time()
        rd = json.loads(llm.complete(system=READ, user=f"질문: {a.question}\n<answer>{ans or '(빈 답)'}</answer>\n자료 줄:\n{lines}", temperature=0.1, max_tokens=400, json_mode=True))
        for f in ("idea", "vague", "conflict", "disagree"):   # 원문 구절만 — 고쳐 썼으면 가장 닮은 원문 구절(판정 claim 과 같은 규칙)
            if rd.get(f) and rd[f] not in ans:
                rd[f] = _answer_claim(rd[f], ans)
        strat = policy(r.get("verdict") or "", rd, ans, k.startswith("E2"))
        anchor = rd.get("conflict") or rd.get("disagree") or rd.get("vague") or rd.get("idea") or ""
        user = f"원래 질문: {a.question}\n발표자 답: <answer>{ans or '(빈 답)'}</answer>\n붙잡을 구절: 「{anchor}」\n" + \
               (f"어긋나는 자료 장: {rd.get('conflict_slide')}장\n" if strat == "challenge" else "") + \
               f"채점에서 빠진 것(내용을 말해 주지 마라): {r.get('missing_points') or []}\n자료 줄(볼 곳을 가리킬 때만):\n{lines}"
        mv = json.loads(llm.complete(system=WRITE.format(strategy=strat, shape=SHAPE[strat]), user=user, temperature=0.4, max_tokens=500, json_mode=True))
        sec = round(time.time() - t, 1)
        bad = check(ans, anchor, mv, a.question)
        rows[k] = {"answer": ans, "read": rd, "strategy": strat, "anchor": anchor, "move": mv, "problems": bad, "sec": sec,
                   "now": {"react": r.get("react"), "followup": r.get("followup")}}
        print(f"\n■ {k}  ({sec}s, LLM 2콜)  전략={strat}  {'⚠ ' + ', '.join(bad) if bad else '검사 통과'}")
        print(f"   답      {ans or '(빈 답)'}")
        print(f"   붙잡음  「{anchor}」")
        print(f"   반응    {mv.get('reaction')}")
        print(f"   꼬리    {mv.get('follow_up_question')}  (자료 {mv.get('source_slide')}장)")
    out = Path(a.probe).with_name(Path(a.probe).stem + f"_move2_{a.llm or 'default'}.json")
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print("\n→", out)

if __name__ == "__main__":
    main()
