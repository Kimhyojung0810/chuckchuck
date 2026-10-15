"""
제안 — 「대화 한 수」(dialogue move) 시험 프롬프트. 판정(채점)은 그대로 두고, 그 결과와 사용자 답 원문으로
reaction · referenced_user_idea · dialogue_strategy · follow_up_question · source_slide 를 따로 만든다 (2026-10-13 대화 재설계 1단계).
앱 코드가 아니다 — 같은 첫 질문에 다른 답(A~G)을 넣었을 때 다음 질문이 실제로 달라지는지 재는 실험.

  python etc/labs/dialogue_probe/move.py --probe etc/labs/dialogue_probe/out/<판정 결과>.json --session <id>
"""
import argparse, json, re, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "main"))
from pipeline.config import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")
from pipeline.providers.llm_impl import get_llm  # noqa: E402
from server.session_archive import SessionArchive  # noqa: E402

SYSTEM = """너는 발표 연습 상대 「삐약이」다. 발표자가 자기 발표 자료에 대해 질문을 받고 답했다.
너의 일은 채점이 아니라 **대화의 다음 한 수**다 — 발표자가 방금 한 말을 붙잡아, 스스로 한 걸음 더 생각하게 만드는 질문 하나.

입력: 질문 · 발표자의 답 원문 · 채점 결과(verdict · 빠진 것 · 자료와 어긋남) · 관련 자료 줄.

1) 전략을 하나 고른다 (아래 규칙 그대로):
 - deepen   : verdict 가 good. 맞힌 내용에서 한 단계 더 — 원리 · 이유 · 적용 · 한계로 넓힌다.
 - connect  : 방향은 맞는데 연결고리가 빠졌다. 발표자가 말한 것에서 출발해 빠진 고리를 묻는다.
 - clarify  : 답에 흐릿한 말(「좀 다를 것 같다」「그런 것 같다」 등)이 있다. 그 말이 정확히 무엇을 뜻하는지, 무엇을 근거로 하는지 묻는다.
 - challenge: 답에 자료와 어긋난 전제 · 사실이 있다. 정답을 말하지 말고, 발표자 말과 자료가 부딪히는 지점을 보여 주고 직접 확인하게 한다.
 - explore  : 발표자가 자료의 결론에 반대하거나 다른 관점을 냈다. 그 관점의 이유를 묻고, 자료의 무엇과 견줘 볼지 묻는다.
 - hint     : 「모르겠어요」 · 빈 답. 정답을 주지 말고 아주 작은 발판 하나(어느 장 · 어떤 축을 볼지)를 주고 쉬운 질문 하나.
2) referenced_user_idea: 발표자 답 **원문에서 낱말 그대로** 옮긴 짧은 구절(40자 안). 고치거나 자료 말로 바꾸지 마라. hint 이고 답이 비었으면 빈 문자열.
3) reaction: 한 문장, 짧게(35자 안팎). 발표자가 한 말의 **그 부분**을 짚는다. 빈 칭찬 · 답 되풀이 · 「좋은 답이에요」 금지.
   틀린 말을 맞다고 하지 마라. 자료의 정답 내용을 여기서 말하지 마라.
4) follow_up_question: 한 문장 질문. **referenced_user_idea 에서 출발**해야 한다 — 그 낱말이나 그 생각을 질문 안에서 가리켜라.
   원래 질문을 되풀이하지 마라. 자료의 수치 · 정답 문장을 질문에 넣어 흘리지 마라(challenge 는 「자료 3장 표의 25°C 줄」처럼 **볼 곳**만 가리킨다).
5) source_slide: 이 질문이 기대는 자료 장 번호(정수). 없으면 0.
6) 존댓말 해요체. 「~시」 존칭 금지.

JSON 하나만: {"dialogue_strategy": "...", "referenced_user_idea": "...", "reaction": "...", "follow_up_question": "...", "source_slide": 0}"""

def deck_lines(doc, nos):
    out = []
    for s in (doc or {}).get("slides", []):
        if s.get("slide_no") in nos:
            for b in s.get("blocks", []):
                t = re.sub(r"!\[image\]\([^)]*\)", "", str(b.get("text", ""))).strip()
                if t:
                    out.append(f"[{s['slide_no']}장] {t[:500]}")
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", required=True)
    ap.add_argument("--session", required=True)
    ap.add_argument("--question", default="2C 충전은 500 사이클에서 용량의 4분의 1을 깎았다 라는 결과가 어떤 조건에서만 성립하는지 설명해 주세요.")
    ap.add_argument("--slides", default="2,3,4")
    a = ap.parse_args()
    probe = json.loads(Path(a.probe).read_text())
    doc = SessionArchive(ROOT / "var" / "data").read_artifact(a.session, "slide_doc")
    lines = deck_lines(doc, {int(x) for x in a.slides.split(",")})
    llm = get_llm()
    rows = {}
    for k, r in probe.items():
        if "answer" not in r:
            continue
        user = "\n".join([
            f"질문: {a.question}",
            f"발표자 답 원문: <answer>{r['answer'] or '(빈 답 — 「모르겠어요」 를 눌렀다)'}</answer>",
            f"채점: verdict={r.get('verdict')} score={r.get('score')} 빠진 것={r.get('missing_points') or []}",
            "관련 자료 줄:", *lines,
        ])
        t = time.time()
        raw = llm.complete(system=SYSTEM, user=user, temperature=0.4, max_tokens=600, json_mode=True)
        try:
            mv = json.loads(raw if isinstance(raw, str) else json.dumps(raw))
        except Exception:  # noqa: BLE001
            mv = {"raw": str(raw)[:400]}
        idea = str(mv.get("referenced_user_idea") or "")
        mv["idea_verbatim"] = bool(idea) and idea in (r["answer"] or "")
        mv["sec"] = round(time.time() - t, 1)
        rows[k] = {"answer": r["answer"], "now": {"react": r.get("react"), "followup": r.get("followup")}, "move": mv}
        print(f"\n■ {k}  ({mv['sec']}s)  strategy={mv.get('dialogue_strategy')}  idea원문={mv['idea_verbatim']}")
        print(f"   답        {r['answer']}")
        print(f"   지금 반응  {r.get('react')}")
        print(f"   지금 꼬리  {r.get('followup')}")
        print(f"   제안 반응  {mv.get('reaction')}")
        print(f"   제안 생각  {idea}")
        print(f"   제안 꼬리  {mv.get('follow_up_question')}  (자료 {mv.get('source_slide')}장)")
    out = Path(a.probe).with_name(Path(a.probe).stem + "_move.json")
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print("\n→", out)

if __name__ == "__main__":
    main()
