"""
질문 코칭(F-08 → F-09)이 얼마나 **이 자료에 특화됐는지** 재는 측정 도구입니다.

**프롬프트를 고치기 전에 재고, 고친 뒤에 같은 표를 다시 뽑습니다.** 이게 없으면
LLM 이 그날 낸 답을 보고 "좋아진 것 같다" 로 끝나고, 다음 사람이 프롬프트를
다시 만질 때 무엇이 나빠졌는지 아무도 모릅니다. `qa_judge_probe.py` 가 판정의
무름을 재는 도구라면, 이 도구는 **질문·판정이 자료를 보고 있는가** 를 잽니다.

재는 것:

    근거 인용률    모범답(answer_gist)의 낱말 중 자료 본문·발화에 실제로 있는 비율.
                   낮으면 모범답이 자료 밖 지식으로 살을 붙인 것이다.
    질문 특이도    질문 문장에 든 **이 자료 고유 낱말** 수 (개념 이름·상투어 제외).
                   0 이면 어느 발표에나 붙일 수 있는 질문이다.
    폴백 비율      LLM 이 빠뜨려 코드가 조립한 질문 비율. 높으면 모델이 지시를 못 따른 것.
    판정 일관성    골자 그대로 → 통과 / 엉뚱한 답 → wrong / 함정에 동의 → wrong /
                   함정을 바로잡음 → 통과. 이 넷이 어긋나면 점수가 거짓말이다.
    말투 위반      '~시', '~시겠어요', '하셨' 같은 금지 높임(CLAUDE.md §3-1) 개수.
    프롬프트 크기  LLM 에 실린 글자 수와 그중 이미지 캡션·HTML 잡음 비율, 지연.
    막힘 코칭      「모르겠어요」를 연달아 눌렀을 때: 단계 순서, 1단이 장 번호를 대는가,
                   선택지를 주는가, 인용이 자료에 실제로 있는가, 해설이 출처를 대는가.

실행 (저장소 루트에서, 실 LLM 을 부른다 — .env 필요):

    python examples/qa_eval.py                       # 질문 5분 트랙 + 판정 4벌
    python examples/qa_eval.py --tag baseline        # 결과 파일 이름에 꼬리표
    python examples/qa_eval.py --no-judge            # 질문만 (F-09 호출 없음, 싸다)
    python examples/qa_eval.py --no-coach            # 막힘 코칭은 건너뛴다
    python examples/qa_eval.py --dump /tmp/qa.json   # 프롬프트·응답 원문까지 남긴다
    python examples/qa_eval.py --rubric              # 회의(09-12 §4) rubric 7항목을 LLM 심사관이 채점 (호출 +1)
    python examples/qa_eval.py --bundle-dir exports/eval_bundles --tag v1
                                                     # 번들 N개 → <시각>_v1.corpus.json (평균·합) 도 같이 남긴다

결과 요약은 exports/qa_eval/<시각>_<tag>.json 에 남는다. 전후 비교는 이 파일 둘을 놓고 본다
(`examples/qa_eval_compare.py --tag 전 --tag 후`). 번들 폴더로 돌렸으면 `.corpus.json` 이 비교 대상이다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from chuckchuck.config import load_dotenv  # noqa: E402

load_dotenv()

from chuckchuck import build_questions, judge_answer, triage_questions  # noqa: E402
from chuckchuck._evidence import clean_slide_text  # noqa: E402
from chuckchuck._json_text import extract_json_object  # noqa: E402
from chuckchuck._match import norm_tokens  # noqa: E402
from chuckchuck.contracts import (  # noqa: E402
    ConceptGraph,
    Context,
    QaTriage,
    Question,
    QuestionDoc,
    SlideDoc,
    Transcript,
)
from chuckchuck.providers.llm_base import LLMProvider  # noqa: E402
from chuckchuck.providers.llm_impl import get_llm  # noqa: E402

#: 그래프·정합·발화·심사가 한 벌로 든 실행 기록. F-06·F-07·F-11 은 다시 돌리지 않는다.
RUN_FIXTURE = ROOT / "fixtures" / "live_qa_run.json"
OUT_DIR = ROOT / "exports" / "qa_eval"

#: 어느 발표에도 안 맞는 답 (qa_judge_probe 와 같은 문장). 이 자료 낱말이 없어야 한다.
UNRELATED_ANSWER = (
    "저희 팀은 지난 분기에 물류 창고 세 곳의 재고 회전율을 비교했고, "
    "동절기 배송 지연이 반품률을 끌어올린다는 결론을 얻었습니다."
)
#: 함정 질문의 잘못된 전제에 그대로 동의하는 답. 규칙상 wrong 이어야 한다.
TRAP_AGREE_ANSWER = "네, 맞습니다. 말씀하신 대로입니다."

#: 질문이 해요체로 끝나는가. "…되는가?" 같은 반말 의문형은 화면 말투와 어긋난다 (f08 규칙 5).
POLITE_END_RE = re.compile(r"(요|까|죠|세요|나요|가요|래요)\s*[?.!]?\s*$")
#: 되물음이 선택형인가 — "A인가요, B인가요?" · "…였나요, 아니었나요?" · "둘 중".
CHOICE_RE = re.compile(r"(인가요|였나요|있었나요|없었나요|맞나요)[^?]*?(인가요|였나요|있었나요|없었나요|아닌가요)|둘 중|중 (어느|하나)")
SLIDE_NO_RE = re.compile(r"\d+\s*장|\bS\d+")
#: CLAUDE.md §3-1 이 금지한 높임. 질문·힌트·반응 문장에서 센다.
HONORIFIC_RE = re.compile(r"[가-힣]*(셨|시겠|십니|십시오|시나요|시는지|계시|여쭈)|께\s")

#: 질문에 있어도 "이 자료" 를 가리키지 않는 상투어. 특이도에서 뺀다.
GENERIC_TOKENS = frozenset(
    "설명 근거 개념 자료 발표 이유 어떻게 무엇 왜 주세요 해요 있나요 인가요 어떤 어느 "
    "관계 핵심 내용 부분 경우 대해 통해 위해 각각 서로 그리고 또는 하는 하고 하면 "
    "말씀 질문 답변 사례 예시 방법 정도 정말 실제 구체 무슨 중에 어디 언제 누가".split()
)
#: 코드가 조립한 폴백 질문의 흔적 (f08 `_fallback_text` · `_fallback_gist`).
FALLBACK_QUESTION_RE = re.compile(r"— 설명해 주세요\.$|이 개념의 핵심과 자료에 넣은 근거를 설명해 주세요\.$")
FALLBACK_GIST_RE = re.compile(r"\(\d+(, \d+)*장 근거\)$")


class RecordingLLM(LLMProvider):
    """실제 제공자를 감싸고 호출마다 프롬프트·응답·지연을 남긴다. 판정은 바꾸지 않는다."""

    def __init__(self, inner: LLMProvider):
        self.inner = inner
        self.name = inner.name
        self.calls: list[dict] = []

    def complete(self, *, system: str, user: str, temperature: float = 0.2,
                 max_tokens: int = 4096, json_mode: bool = False) -> str:
        t0 = time.time()
        out = self.inner.complete(system=system, user=user, temperature=temperature,
                                  max_tokens=max_tokens, json_mode=json_mode)
        task = user.split("\n", 1)[0].replace("[TASK] ", "")
        self.calls.append({
            "task": task, "sec": round(time.time() - t0, 1),
            "system_chars": len(system), "user_chars": len(user),
            # 잡음 = 정제하면 사라지는 글자. 프롬프트에 캡션·태그가 얼마나 실렸나.
            "noise_ratio": round(1 - len(clean_slide_text(user)) / max(1, len(user)), 2),
            "system": system, "user": user, "response": out,
        })
        return out


# ---------------------------------------------------------------------------
# 입력
# ---------------------------------------------------------------------------

def load_artifacts(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"측정 기록이 없어요: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw["session"]["artifacts"] if "session" in raw else raw


def content_tokens(text: str) -> set[str]:
    """대조용 낱말 집합. 한 글자 토큰은 우연히 다 걸리므로 버린다."""
    return {t for t in norm_tokens(text) if len(t) >= 2}


class Corpus:
    """자료 본문(정제)·발화를 장 번호로 찾는 색인. 지표 계산이 전부 여기서 나온다."""

    def __init__(self, slidedoc: SlideDoc, transcript: Transcript | None):
        self.slide_text = {s.slide_no: clean_slide_text(s.raw_text or "") for s in slidedoc.slides}
        self.speech_text = {
            no: (transcript.text_for_slide(no) if transcript else "") for no in self.slide_text
        }
        self.deck_tokens = content_tokens(" ".join(self.slide_text.values()))
        self.deck_tokens |= content_tokens(" ".join(self.speech_text.values()))

    def evidence_tokens(self, slide_nos: list[int]) -> set[str]:
        nos = slide_nos or list(self.slide_text)
        text = " ".join(self.slide_text.get(n, "") + " " + self.speech_text.get(n, "") for n in nos)
        return content_tokens(text)


# ---------------------------------------------------------------------------
# 지표
# ---------------------------------------------------------------------------

def grounding_ratio(gist: str, evidence: set[str]) -> float | None:
    toks = content_tokens(gist)
    if not toks:
        return None
    return round(sum(1 for t in toks if t in evidence) / len(toks), 2)


def specificity(question: Question, corpus: Corpus) -> int:
    """질문에 든 이 자료 고유 낱말 수. 개념 이름과 상투어는 뺀다."""
    toks = content_tokens(question.question) - content_tokens(question.label) - GENERIC_TOKENS
    return sum(1 for t in toks if t in corpus.deck_tokens)


def honorifics(*texts: str) -> int:
    return sum(len(HONORIFIC_RE.findall(t or "")) for t in texts)


def question_row(q: Question, corpus: Corpus) -> dict:
    return {
        "id": q.id, "label": q.label, "trap": q.trap, "severity": q.severity,
        "slide_count": len(q.slide_nos),
        "fallback": bool(FALLBACK_QUESTION_RE.search(q.question) or FALLBACK_GIST_RE.search(q.answer_gist or "")),
        "specificity": specificity(q, corpus),
        "grounding": grounding_ratio(q.answer_gist, corpus.evidence_tokens(q.slide_nos)),
        "honorifics": honorifics(q.question, q.why, q.hint, q.answer_gist),
        "impolite": not POLITE_END_RE.search(q.question or ""),
        "question": q.question, "gist": q.answer_gist,
    }


# ---------------------------------------------------------------------------
# rubric — 회의(2026-09-12 §4) 7항목을 LLM-as-a-Judge 로 잰다. 번들당 호출 1회.
# 특이도·인용률은 "자료를 보고 있는가" 를, 이건 "발표자가 실제로 받을 법한 질문인가" 를 잰다.
# ---------------------------------------------------------------------------

RUBRIC_ITEMS = ("groundedness", "relevance", "coverage", "depth", "answerability", "non_duplication")
RUBRIC_SYSTEM = """당신은 발표 Q&A 품질 심사관이다. 발표자가 실제로 받을 법하고 생각할 가치가 있는 질문인지 잰다.
자료와 발화에 있는 것만 근거로 삼는다. 자료에 없는 내용을 지어내지 마라. 확신이 없으면 낮은 점수를 준다.

각 질문을 항목마다 1~5 로 채점한다.
- groundedness: 질문의 전제가 자료·발화에 그대로 있다(5) ↔ 자료에 없는 사실을 전제로 한다(1)
- relevance: 이 발표의 핵심 주장에 닿는다(5) ↔ 어느 발표에나 붙일 수 있다(1)
- coverage: 설명이 부족했던 지점을 짚는다(5) ↔ 이미 충분히 설명한 것을 되묻는다(1)
- depth: 이유·비교·한계를 묻는다(5) ↔ 단순 사실 확인(1)
- answerability: 자료·발화로 답할 수 있다(5) ↔ 발표자도 답할 수 없다(1)
- non_duplication: 다른 질문과 겹치지 않는다(5) ↔ 같은 걸 말만 바꿔 묻는다(1)
- hallucination: 자료에 없는 내용을 사실처럼 전제하면 true. trap=true 인 질문은 일부러 틀린 전제를 쓰므로 false.
- reason: 근거 한 문장. 장 번호(S3 처럼)를 댄다.

코드펜스·주석·말머리 없이 JSON 객체 하나만 출력한다:
{"scores": [{"id": "q01", "groundedness": 4, "relevance": 5, "coverage": 3, "depth": 4, "answerability": 5, "non_duplication": 5, "hallucination": false, "reason": "S3 의 수치를 그대로 전제로 삼았다"}]}
"""
#: 심사관에게 실을 장별 발췌 상한. 22장 × 600자 ≈ 13k 자 — 판정 프롬프트(1.3k)보다 크지만 호출은 1회다.
RUBRIC_SLIDE_MAX = 600
RUBRIC_SPEECH_MAX = 400


def rubric_user_prompt(questions: list[Question], corpus: Corpus) -> str:
    lines = ["[TASK] qa-rubric", "", "## 자료 (장별 본문)"]
    lines += [f"S{no}: {t[:RUBRIC_SLIDE_MAX]}" for no, t in corpus.slide_text.items() if t.strip()]
    lines += ["", "## 발화 (장별 받아쓰기)"]
    lines += [f"S{no}: {t[:RUBRIC_SPEECH_MAX]}" for no, t in corpus.speech_text.items() if t.strip()]
    lines += ["", "## 질문"]
    lines += [f"- id={q.id} trap={'true' if q.trap else 'false'} 근거장={q.slide_nos}: {q.question}" for q in questions]
    return "\n".join(lines)


def _clamp15(v) -> int | None:
    try:
        return max(1, min(5, int(v)))
    except (TypeError, ValueError):
        return None


def parse_rubric(raw: str, questions: list[Question]) -> list[dict]:
    """심사관 응답 → 질문별 행. 응답에 없는 질문은 missing 으로 남긴다 (0점으로 치지 않는다).
    trap 질문의 hallucination 은 코드가 false 로 못 박는다 — 심사관이 헷갈려도 함정을 벌하지 않는다."""
    data = extract_json_object(raw)
    by_id = {str(s.get("id")): s for s in data.get("scores", []) if isinstance(s, dict)}
    rows = []
    for q in questions:
        s = by_id.get(q.id)
        if s is None:
            rows.append({"question_id": q.id, "missing": True})
            continue
        row = {"question_id": q.id, "missing": False,
               "hallucination": bool(s.get("hallucination")) and not q.trap,
               "reason": str(s.get("reason") or "")[:200]}
        for k in RUBRIC_ITEMS:
            row[k] = _clamp15(s.get(k))
        rows.append(row)
    return rows


def run_rubric(questions: list[Question], corpus: Corpus, llm: LLMProvider) -> list[dict]:
    if not questions:
        return []
    try:
        raw = llm.complete(system=RUBRIC_SYSTEM, user=rubric_user_prompt(questions, corpus),
                           temperature=0.0, max_tokens=2048, json_mode=True)
        rows = parse_rubric(raw, questions)
    except Exception as e:  # noqa: BLE001 — 측정 도구: 심사 실패는 결과에 missing 으로 남기고 계속 간다
        print(f"  rubric 실패: {type(e).__name__}: {str(e)[:120]}")
        return [{"question_id": q.id, "missing": True} for q in questions]
    for r in rows:
        if r["missing"]:
            print(f"    {r['question_id']:<24} (심사관 응답에 없음)")
            continue
        cells = " ".join(f"{k[:5]}{r[k] if r[k] is not None else '-'}" for k in RUBRIC_ITEMS)
        print(f"    {r['question_id']:<24} {cells}{' [환각]' if r['hallucination'] else ''}  {r['reason'][:50]}")
    return rows


def rubric_summary(rrows: list[dict]) -> dict:
    """항목별 평균 + 환각 수 + 종합(환각 질문은 0점). 비교 스크립트의 PRIMARY 가 이 키를 읽는다."""
    scored = [r for r in rrows if not r.get("missing")]
    out: dict = {"n": len(scored), "missing": len(rrows) - len(scored)}
    for k in RUBRIC_ITEMS:
        xs = [r[k] for r in scored if r.get(k) is not None]
        out[f"{k}_mean"] = round(sum(xs) / len(xs), 2) if xs else None
    out["hallucination"] = sum(1 for r in scored if r.get("hallucination"))
    per_q = []
    for r in scored:
        vals = [r[k] for k in RUBRIC_ITEMS if r.get(k) is not None]
        if vals:
            per_q.append(0.0 if r.get("hallucination") else sum(vals) / len(vals))
    out["overall_mean"] = round(sum(per_q) / len(per_q), 2) if per_q else None
    return out


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def make_questions(art: dict, track: str, llm: LLMProvider, fresh_triage: bool) -> QuestionDoc:
    graph = ConceptGraph.from_dict(art["concept_graph"])
    ctx = Context.from_dict(art.get("context") or {})
    if fresh_triage or not art.get("qa_triage"):
        triage = triage_questions(graph, art.get("alignment_doc"), art.get("flow_diff"), ctx,
                                  transcript=art.get("transcript"), llm=llm)
    else:
        triage = QaTriage.from_dict(art["qa_triage"])
    return build_questions(
        graph, triage, track=track, alignment=art.get("alignment_doc"), flow=art.get("flow_diff"),
        transcript=art.get("transcript"), slidedoc=art.get("slide_doc"), context=ctx, llm=llm,
    )


def judge_cases(q: Question) -> list[tuple[str, str, str]]:
    """(경우, 답, 기대). 기대는 passed | wrong."""
    gist = (q.answer_gist or "").strip()
    cases = []
    if gist:
        cases.append(("골자 그대로", gist, "passed"))
    cases.append(("엉뚱한 답", UNRELATED_ANSWER, "wrong"))
    if q.trap:
        cases.append(("함정에 동의", TRAP_AGREE_ANSWER, "wrong"))
        if gist:
            cases.append(("함정을 바로잡음", f"그 전제는 자료와 달라요. {gist}", "passed"))
    return cases


def run_judges(questions: list[Question], art: dict, llm: LLMProvider, limit: int) -> list[dict]:
    rows = []
    for q in questions[:limit]:
        for case, answer, expect in judge_cases(q):
            v = judge_answer(q, answer, graph=art["concept_graph"], alignment=art.get("alignment_doc"),
                             transcript=art.get("transcript"), context=art.get("context"), llm=llm)
            ok = v.passed if expect == "passed" else (v.verdict == "wrong")
            rows.append({
                "question_id": q.id, "case": case, "expect": expect, "ok": ok,
                "verdict": v.verdict, "score": v.score, "passed": v.passed,
                "honorifics": honorifics(v.react, v.followup, *v.hints),
                "react": v.react, "followup": v.followup,
            })
            mark = "✓" if ok else "✗"
            print(f"    {mark} {q.id:<24} {case:<9} → {v.verdict:<8} {v.score:>3}  {v.react[:60]}")
    return rows


def run_coaching(questions: list[Question], art: dict, llm: LLMProvider, corpus: Corpus, limit: int) -> list[dict]:
    """「모르겠어요」를 해설이 나올 때까지 연달아 누른다 (최대 3번)."""
    rows = []
    for q in questions[:limit]:
        history: list[dict] = []
        deck = " ".join(corpus.slide_text.values())
        for step in range(1, 4):
            v = judge_answer(q, "(모르겠어요)", give_up=True, history=history,
                             graph=art["concept_graph"], alignment=art.get("alignment_doc"),
                             transcript=art.get("transcript"), slidedoc=art.get("slide_doc"),
                             context=art.get("context"), llm=llm)
            quote = getattr(v, "evidence_quote", "") or ""
            row = {
                "question_id": q.id, "step": step, "stage": v.coach_stage,
                "cites_slide": bool(SLIDE_NO_RE.search(v.followup + " " + v.react + " " + (v.explanation or ""))),
                "choice_form": bool(CHOICE_RE.search(v.followup or "")) or len(getattr(v, "choices", []) or []) == 2,
                "choices": list(getattr(v, "choices", []) or []),
                "quote_in_deck": (quote in deck) if quote else None,
                "honorifics": honorifics(v.react, v.followup, v.explanation),
                "react": v.react, "followup": v.followup, "explanation": v.explanation or "",
            }
            rows.append(row)
            shown = row["followup"] or row["explanation"]
            print(f"    {q.id:<24} {step}단 {v.coach_stage:<8} 장{'O' if row['cites_slide'] else '-'} "
                  f"선택{'O' if row['choice_form'] else '-'}  {shown[:70]}")
            history.append({"question_id": q.id, "question": q.question, "answer": "(모르겠어요)",
                            "verdict": v.verdict, "gave_up": True})
            if v.coach_stage == "explain":
                break
    return rows


def summarize(qrows: list[dict], jrows: list[dict], calls: list[dict], crows: list[dict] | None = None,
              rrows: list[dict] | None = None) -> dict:
    def mean(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(xs) / len(xs), 2) if xs else None

    def rate(case):
        hit = [r for r in jrows if r["case"] == case]
        return f"{sum(1 for r in hit if r['ok'])}/{len(hit)}" if hit else "-"

    by_task = {}
    for c in calls:
        t = by_task.setdefault(c["task"], {"n": 0, "chars": [], "noise": [], "sec": []})
        t["n"] += 1
        t["chars"].append(c["user_chars"]); t["noise"].append(c["noise_ratio"]); t["sec"].append(c["sec"])
    crows = crows or []
    def crate(step, key):
        hit = [r for r in crows if r["step"] == step and r.get(key) is not None]
        return f"{sum(1 for r in hit if r[key])}/{len(hit)}" if hit else "-"
    stages = {}
    for r in crows:
        stages.setdefault(r["question_id"], []).append(r["stage"])
    rubric = {"rubric": rubric_summary(rrows)} if rrows else {}
    return {
        **rubric,
        "questions": len(qrows),
        "fallback": sum(1 for r in qrows if r["fallback"]),
        "trap": sum(1 for r in qrows if r["trap"]),
        "slide_count_mean": mean([r["slide_count"] for r in qrows]),
        "specificity_mean": mean([r["specificity"] for r in qrows]),
        "grounding_mean": mean([r["grounding"] for r in qrows]),
        "honorifics_questions": sum(r["honorifics"] for r in qrows),
        "impolite_questions": sum(1 for r in qrows if r["impolite"]),
        "honorifics_judge": sum(r["honorifics"] for r in jrows),
        "judge": {
            "gist_passed": rate("골자 그대로"), "unrelated_wrong": rate("엉뚱한 답"),
            "trap_agree_wrong": rate("함정에 동의"), "trap_fixed_passed": rate("함정을 바로잡음"),
        },
        "prompts": {
            k: {"n": v["n"], "user_chars_mean": mean(v["chars"]),
                "noise_ratio_mean": mean(v["noise"]), "sec_mean": mean(v["sec"])}
            for k, v in by_task.items()
        },
        "coach": {
            "stages": stages,
            "step1_cites_slide": crate(1, "cites_slide"), "step1_choice_form": crate(1, "choice_form"),
            "step1_quote_in_deck": crate(1, "quote_in_deck"),
            "explain_cites_slide": f"{sum(1 for r in crows if r['stage'] == 'explain' and r['cites_slide'])}/"
                                   f"{sum(1 for r in crows if r['stage'] == 'explain')}" if crows else "-",
            "honorifics": sum(r["honorifics"] for r in crows),
        },
    }


def print_summary(s: dict, model: str) -> None:
    j, p = s["judge"], s["prompts"]
    print(f"\n{'=' * 72}\n요약  (model={model})\n{'-' * 72}")
    print(f"질문 {s['questions']}개 · 폴백 {s['fallback']} · 함정 {s['trap']} · 근거 장 평균 {s['slide_count_mean']}")
    print(f"질문 특이도 평균 {s['specificity_mean']}  · 근거 인용률 평균 {s['grounding_mean']}")
    print(f"말투 위반: 높임 질문 {s['honorifics_questions']} · 판정 {s['honorifics_judge']} · 반말 질문 {s['impolite_questions']}/{s['questions']}")
    print(f"판정 일관성: 골자→통과 {j['gist_passed']} · 엉뚱→wrong {j['unrelated_wrong']}"
          f" · 함정동의→wrong {j['trap_agree_wrong']} · 함정정정→통과 {j['trap_fixed_passed']}")
    for task, v in p.items():
        print(f"프롬프트 {task:<12} {v['n']}회 · {v['user_chars_mean']}자 · 잡음 {v['noise_ratio_mean']:.0%} · {v['sec_mean']}s")
    r = s.get("rubric")
    if r:
        cells = " · ".join(f"{k[:5]} {r.get(f'{k}_mean')}" for k in RUBRIC_ITEMS)
        print(f"rubric(1~5): 종합 {r['overall_mean']} · 환각 {r['hallucination']} · {cells}"
              + (f" · 누락 {r['missing']}" if r.get("missing") else ""))
    c = s.get("coach") or {}
    if c.get("stages"):
        seqs = " · ".join("→".join(v) for v in c["stages"].values())
        print(f"막힘 코칭: 단계 {seqs}")
        print(f"  1단 장 번호 {c['step1_cites_slide']} · 선택형 {c['step1_choice_form']} · 인용∈자료 {c['step1_quote_in_deck']}"
              f" · 해설 출처 {c['explain_cites_slide']} · 높임 {c['honorifics']}")


def run_bundle(bundle: Path, args) -> dict:
    """번들 하나를 측정하고 요약 dict 를 돌려준다. 결과 파일도 남긴다."""
    art = load_artifacts(bundle)
    corpus = Corpus(SlideDoc.from_dict(art["slide_doc"]),
                    Transcript.from_dict(art["transcript"]) if art.get("transcript") else None)
    llm = RecordingLLM(get_llm(args.llm))
    print(f"자료: {art['concept_graph']['file_name']} · 장 {len(corpus.slide_text)} · 본문(정제) "
          f"{sum(len(t) for t in corpus.slide_text.values())}자 · 발화 {sum(len(t) for t in corpus.speech_text.values())}자")

    t0 = time.time()
    doc = make_questions(art, args.track, llm, args.fresh_triage)
    print(f"\nF-08 track={doc.track} 질문 {len(doc.questions)}개 ({time.time() - t0:.1f}s, model={doc.model})")
    qrows = [question_row(q, corpus) for q in doc.questions]
    for r in qrows:
        flag = (" [폴백]" if r["fallback"] else "") + (" [반말]" if r["impolite"] else "")
        print(f"  - {r['id']:<24}장{r['slide_count']:>2} 특이도{r['specificity']:>2} 인용률{r['grounding'] if r['grounding'] is not None else '-':>5} "
              f"말투{r['honorifics']}{flag}\n      Q: {r['question'][:100]}")

    jrows = []
    if not args.no_judge:
        print("\nF-09 판정")
        jrows = run_judges(doc.questions, art, llm, args.limit)

    crows = []
    if not args.no_judge and not args.no_coach:
        print("\n막힘 코칭 (「모르겠어요」 연타)")
        crows = run_coaching(doc.questions, art, llm, corpus, args.limit)

    rrows = []
    if args.rubric:
        print("\nrubric 심사 (7항목)")
        rrows = run_rubric(doc.questions, corpus, llm)

    summary = summarize(qrows, jrows, llm.calls, crows, rrows)
    print_summary(summary, llm.name)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"{stamp}{'_' + args.tag if args.tag else ''}.json"
    out.write_text(json.dumps({
        "bundle": str(bundle), "track": args.track, "model": llm.name,
        "summary": summary, "questions": qrows, "judgements": jrows, "coaching": crows, "rubric": rrows,
        "calls": [{k: v for k, v in c.items() if k not in ("system", "user", "response")} for c in llm.calls],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n요약 저장: {out.relative_to(ROOT)}")
    if args.dump:
        args.dump.write_text(json.dumps(llm.calls, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"원문 덤프: {args.dump}")
    return summary


#: 코퍼스 요약에서 평균±편차를 낼 숫자 열.
CORPUS_KEYS = ("specificity_mean", "grounding_mean", "fallback", "honorifics_questions",
               "honorifics_judge", "impolite_questions")


def _agg(vals: list):
    """같은 키의 값 N개를 하나로: 숫자는 평균, 'a/b' 는 합, dict 는 재귀, 그 밖(단계 목록)은 버린다."""
    vals = [v for v in vals if v is not None and v != "-"]
    if not vals:
        return None
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
        return round(sum(vals) / len(vals), 2)
    if all(isinstance(v, str) and "/" in v for v in vals):
        parts = [tuple(int(x) for x in v.split("/", 1)) for v in vals]
        return f"{sum(a for a, _ in parts)}/{sum(b for _, b in parts)}"
    if all(isinstance(v, dict) for v in vals):
        keys: list = []
        for d in vals:
            keys += [k for k in d if k not in keys]
        out = {k: _agg([d.get(k) for d in vals]) for k in keys}
        kept = {k: v for k, v in out.items() if v is not None}
        return kept or None          # 단계 목록처럼 전부 버려진 dict 는 통째로 뺀다
    return None


def aggregate_summaries(summaries: list[dict]) -> dict:
    """번들 N개 요약을 단일 요약과 **같은 모양**으로 합친다 — qa_eval_compare 가 그대로 읽는다.
    한 발표에서 좋아진 것이 다른 발표에서 나빠졌으면 평균이 그걸 드러낸다."""
    return _agg(list(summaries)) or {}


def write_corpus(summaries: list[dict], bundles: list[Path], tag: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"{stamp}{'_' + tag if tag else ''}.corpus.json"
    out.write_text(json.dumps({"bundles": [b.stem for b in bundles], "n": len(summaries),
                               "summary": aggregate_summaries(summaries)}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    return out


def print_corpus(summaries: list[dict]) -> None:
    """번들 N개의 평균±편차. 한 발표에서 좋아진 것이 다른 발표에서 나빠졌는지 여기서 보인다."""
    import statistics

    print(f"\n{'=' * 72}\n코퍼스 요약  (번들 {len(summaries)}개)\n{'-' * 72}")
    for key in CORPUS_KEYS:
        xs = [s[key] for s in summaries if s.get(key) is not None]
        if not xs:
            continue
        sd = statistics.pstdev(xs) if len(xs) > 1 else 0.0
        print(f"  {key:<22} {statistics.fmean(xs):>7.2f} ± {sd:<6.2f} (n={len(xs)})")
    for case in ("gist_passed", "unrelated_wrong", "trap_agree_wrong", "trap_fixed_passed"):
        hit = tot = 0
        for s in summaries:
            r = (s.get("judge") or {}).get(case, "-")
            if "/" in r:
                a, b = r.split("/")
                hit += int(a)
                tot += int(b)
        if tot:
            print(f"  judge.{case:<16} {hit}/{tot}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle", type=Path, default=RUN_FIXTURE, help="아티팩트 한 벌 (기본 live_qa_run.json)")
    ap.add_argument("--bundle-dir", type=Path, default=None,
                    help="번들 폴더 전체 (examples/build_eval_bundle.py 출력). 하나씩 재고 평균±편차를 낸다")
    ap.add_argument("--track", default="5")
    ap.add_argument("--llm", default=None, help="REASONING_BACKEND 대신 쓸 백엔드")
    ap.add_argument("--tag", default="", help="결과 파일 꼬리표 (예: baseline)")
    ap.add_argument("--limit", type=int, default=3, help="판정에 넣을 질문 수 (기본 3)")
    ap.add_argument("--no-judge", action="store_true", help="F-09 를 부르지 않는다")
    ap.add_argument("--no-coach", action="store_true", help="「모르겠어요」 코칭을 건너뛴다")
    ap.add_argument("--rubric", action="store_true", help="rubric 7항목을 LLM 심사관이 채점한다 (번들당 호출 +1)")
    ap.add_argument("--fresh-triage", action="store_true", help="저장된 심사 대신 F-08 1차를 다시 돌린다")
    ap.add_argument("--dump", type=Path, default=None, help="프롬프트·응답 원문을 이 파일에 남긴다")
    args = ap.parse_args()

    if args.bundle_dir:
        bundles = sorted(args.bundle_dir.glob("*.json"))
        if not bundles:
            raise SystemExit(f"번들이 없어요: {args.bundle_dir} — 먼저 python examples/build_eval_bundle.py")
        summaries = []
        for i, b in enumerate(bundles, 1):
            print(f"\n### [{i}/{len(bundles)}] {b.stem}")
            summaries.append(run_bundle(b, args))
        print_corpus(summaries)
        out = write_corpus(summaries, bundles, args.tag)
        print(f"\n코퍼스 요약 저장: {out.relative_to(ROOT)}  ← 비교는 이 파일로")
        return 0
    run_bundle(args.bundle, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
