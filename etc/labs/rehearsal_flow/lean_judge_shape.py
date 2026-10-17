"""바퀴 6 — 가벼운 판정(QA_JUDGE_LEAN=1)에서 Q&A 돌아보기가 받는 판정 응답 모양을 실 코드로 만든다 (네트워크 · 과금 0).

판정 LLM 은 LEAN 지시대로 쓴 가짜 출력(react · followup "" · note 30자 안 · claim 25자 안), 꼬리질문 엔진은 가짜 말하기 LLM.
judge_answer(엔진 켬) → DLG.apply → client_judgement 를 그대로 돌려 화면이 받는 JSON 을 남긴다.

  cd <wt>/main && python ../etc/labs/rehearsal_flow/lean_judge_shape.py > out.json
경우: ok(엔진 말하기 통과) · fail(말하기 실패 → 다시 말하기 꺼짐 → 코드 틀) · judgeonly(엔진도 틀도 못 씀 → 판정 그대로 = LEAN 이면 빈 꼬리질문) · mastered(닫힘)
"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())
os.environ.setdefault("QA_JUDGE_LEAN", "1")
os.environ["QA_DIALOGUE_RESPEAK"] = "0"

from pipeline import f09_dialogue as DLG  # noqa: E402
from pipeline import f09_judge as J  # noqa: E402
from pipeline._client_payload import client_judgement  # noqa: E402
from pipeline.contracts import Question, Slide, SlideBlock, SlideDoc  # noqa: E402
from pipeline.providers.llm_base import LLMProvider  # noqa: E402


class Fake(LLMProvider):
    def __init__(self, name, payload):
        self.name, self.payload, self.systems = name, payload, []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.systems.append(system)
        if isinstance(self.payload, Exception):
            raise self.payload
        return json.dumps(self.payload, ensure_ascii=False)


Q = Question(id="q01-c1", node_id="c1", label="2C 충전 열화", question="2C 충전이 용량을 깎았다는 주장이 충분한가요?",
             answer_gist="속도와 온도만 바꿨으니 속도 효과로 읽을 수 있지만 셀이 적어 단정은 어려워요.", severity=1, evidence_slide_no=2)
ANSWER = "2C 충전은 실험실에서 한 거라서 상황마다 좀 다를 것 같아요. 셀 수도 적어서 용량이 깎였다고 단정하긴 어려워요."
DECK = SlideDoc(file_name="bat.pdf", total_slides=3, slides=[
    Slide(slide_no=1, title="1장", blocks=[SlideBlock(category="paragraph", text="배터리 충전 속도와 수명")]),
    Slide(slide_no=2, title="2장", blocks=[SlideBlock(category="paragraph", text="2C 충전 셀은 500회 뒤 용량 82%, 0.5C 충전 셀은 91%")]),
    Slide(slide_no=3, title="3장", blocks=[SlideBlock(category="paragraph", text="셀 4개로 시험했고 온도는 25도로 같았다")])])
LEAN_JUDGE = {"verdict": "partial", "score": 55, "react": "", "followup": "",
              "summary_sentence": "조건 차이는 짚었지만 속도 효과로 읽을 근거는 아직 빠졌어요.",
              "missing_points": ["충전 속도만 바꾼 비교라는 점"], "covered_parts": ["셀 수가 적다"],
              "claim": "셀 수도 적어서", "premise_corrected": False,
              "grounds": [{"slide_no": 2, "quote": "2C 충전 셀은 500회 뒤 용량 82%, 0.5C 충전 셀은 91%", "role": "missing", "note": "속도 효과를 보이는 줄이에요", "ref": "S2-1"},
                          {"slide_no": 3, "quote": "셀 4개로 시험했고 온도는 25도로 같았다", "role": "covered", "note": "셀 수 한계를 짚은 근거예요", "ref": "S3-1"}]}
TALK_OK = {"idea": "실험실에서 한 거라서", "vague": "", "conflict": "", "conflict_slide": 0, "disagree": "", "recite": False, "unknown": False,
           "skipped": "왜 속도 탓인지", "move": "connect", "anchor": "실험실에서 한 거라서",
           "react": "「실험실에서 한 거라서」라고 했죠. 속도 탓인 까닭은 아직 빠졌어요.", "ask": "그 차이가 왜 속도 때문이에요?"}


def run(case: str) -> dict:
    J.clear_judge_cache()
    judge = dict(LEAN_JUDGE)
    if case == "mastered":
        judge.update(verdict="good", score=86, missing_points=[])
    talk = Fake("talk", RuntimeError("429") if case in ("fail", "judgeonly") else TALK_OK)
    DLG._llm = lambda name=None: talk  # noqa: SLF001 — 실험 고정
    if case == "judgeonly":
        DLG.template_turn = lambda move, anchor, ti, seed="": ("", "")   # 코드 틀도 못 쓰는 드문 판 (0.4%)
    jl = Fake("judge", judge)
    j = J.judge_answer(Q, ANSWER, llm=jl, dialogue=True, slidedoc=DECK)
    out = client_judgement(Q, j)
    keep = {k: out.get(k) for k in ("verdict", "score", "passed", "mastered", "summary_sentence", "missing_points", "claim", "grounds",
                                    "move", "react", "followup", "coach_stage")}
    keep["_lean_in_system"] = "출력 줄이기" in jl.systems[-1]
    keep["_source"] = (getattr(j, "dialogue", None) or {}).get("source")
    return keep


if __name__ == "__main__":
    print(json.dumps({c: run(c) for c in ("ok", "fail", "judgeonly", "mastered")}, ensure_ascii=False, indent=1))
