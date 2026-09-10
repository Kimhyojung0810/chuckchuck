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

결과 요약은 exports/qa_eval/<시각>_<tag>.json 에 남는다. 전후 비교는 이 파일 둘을 놓고 본다.
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


def summarize(qrows: list[dict], jrows: list[dict], calls: list[dict], crows: list[dict] | None = None) -> dict:
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
    return {
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
    c = s.get("coach") or {}
    if c.get("stages"):
        seqs = " · ".join("→".join(v) for v in c["stages"].values())
        print(f"막힘 코칭: 단계 {seqs}")
        print(f"  1단 장 번호 {c['step1_cites_slide']} · 선택형 {c['step1_choice_form']} · 인용∈자료 {c['step1_quote_in_deck']}"
              f" · 해설 출처 {c['explain_cites_slide']} · 높임 {c['honorifics']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle", type=Path, default=RUN_FIXTURE, help="아티팩트 한 벌 (기본 live_qa_run.json)")
    ap.add_argument("--track", default="5")
    ap.add_argument("--llm", default=None, help="REASONING_BACKEND 대신 쓸 백엔드")
    ap.add_argument("--tag", default="", help="결과 파일 꼬리표 (예: baseline)")
    ap.add_argument("--limit", type=int, default=3, help="판정에 넣을 질문 수 (기본 3)")
    ap.add_argument("--no-judge", action="store_true", help="F-09 를 부르지 않는다")
    ap.add_argument("--no-coach", action="store_true", help="「모르겠어요」 코칭을 건너뛴다")
    ap.add_argument("--fresh-triage", action="store_true", help="저장된 심사 대신 F-08 1차를 다시 돌린다")
    ap.add_argument("--dump", type=Path, default=None, help="프롬프트·응답 원문을 이 파일에 남긴다")
    args = ap.parse_args()

    art = load_artifacts(args.bundle)
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

    summary = summarize(qrows, jrows, llm.calls, crows)
    print_summary(summary, llm.name)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / f"{stamp}{'_' + args.tag if args.tag else ''}.json"
    out.write_text(json.dumps({
        "bundle": str(args.bundle), "track": args.track, "model": llm.name,
        "summary": summary, "questions": qrows, "judgements": jrows, "coaching": crows,
        "calls": [{k: v for k, v in c.items() if k not in ("system", "user", "response")} for c in llm.calls],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n요약 저장: {out.relative_to(ROOT)}")
    if args.dump:
        args.dump.write_text(json.dumps(llm.calls, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"원문 덤프: {args.dump}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
