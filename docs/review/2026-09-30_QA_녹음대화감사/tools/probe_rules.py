"""
보고서의 근본 원인 주장을 **LLM 없이** 되풀이한다 — 제품 규칙 함수(_deck_claims · _spoken · _align_checks)를 실제 Upstage 파싱본
(labs/qa_bench/corpus/audit_*/slidedoc_parsed_upstage.json)과 심은 문장에 그대로 돌린다. 제품 코드는 고치지 않는다.

    .venv/bin/python "docs/review/2026-09-30_QA_녹음대화감사/tools/probe_rules.py" > "docs/review/2026-09-30_QA_녹음대화감사/evidence/offline_probes.txt"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from chuckchuck import _align_checks as A  # noqa: E402
from chuckchuck._deck_claims import _than_sides, conflicts, deck_from_slidedoc, direction, directions, negated, numbers  # noqa: E402
from chuckchuck._spoken import skip_cue, spoken_numbers, utterances  # noqa: E402
from chuckchuck.contracts import ConceptNode, SlideDoc, Transcript  # noqa: E402

CORPUS = ROOT / "labs" / "qa_bench" / "corpus"
EVID = Path(__file__).resolve().parent.parent / "evidence"


def deck(name: str):
    return deck_from_slidedoc(SlideDoc.from_dict(json.loads((CORPUS / name / "slidedoc_parsed_upstage.json").read_text(encoding="utf-8"))))


def show(title: str, dk, text: str, question: str = "") -> None:
    cs = conflicts(spoken_numbers(text), dk, question)
    got = "; ".join(f"{c.kind}@{c.slide_no}장 ↔ «{c.deck_line[:40]}»" for c in cs) or "(어긋남 없음)"
    print(f"- [{title}] «{text}» → {got}")


def main() -> None:
    co2, kio, bun = deck("audit_co2"), deck("audit_kiosk"), deck("audit_bunt")
    print("## 1. R1 에 심은 모순 — 발화 문장 그대로 (F-11 contradictions 가 쓰는 conflicts)")
    show("co2 N1 수치", co2, "평균 농도가 60퍼센트나 낮아진 거예요.")
    show("kiosk N1 수치 (전→후 짝)", kio, "혼자 주문 성공률이 교육 전 31퍼센트에서 교육 후 88퍼센트까지 올라갔어요.")
    show("kiosk N1 대조: 뒤 값만", kio, "교육 후 혼자 주문 성공률이 88퍼센트까지 올라갔어요.")
    show("bunt N1 수치 (어림 「정도」)", bun, "우리 리그 번트 성공률이 72퍼센트 정도 되는데요, 프로 리그가 81퍼센트니까 생각보다 차이가 크진 않아요.")
    show("bunt N1 대조: 「정도」 뺌", bun, "우리 리그 번트 성공률이 72퍼센트인데요, 프로 리그가 81퍼센트니까 생각보다 차이가 크진 않아요.")
    show("co2 D1 방향 (주어 맞바꿈)", co2, "의외로 한쪽 창문만 열었을 때가 맞통풍보다 두 배 빨리 떨어졌어요.")
    show("kiosk D1 방향 (반의어)", kio, "사실 큰 글씨 모드만 켠 매장이 교육한 매장보다 성공률이 더 많이 올랐어요.")
    show("bunt D1 방향 (수 없음)", bun, "무사 1루에서는 번트를 했을 때가 강공보다 그 이닝 득점 확률이 더 높게 나왔어요.")
    show("bunt D1 가장 단순한 꼴", bun, "무사 1루에서는 번트가 강공보다 그 이닝 득점 확률이 더 높았어요.")
    print("\n## 2. 방향 낱말·비교 양쪽 (위 방향 모순을 못 잡는 까닭)")
    for w in ["떨어졌습니다", "떨어졌어요", "떨어진", "내려갔어요", "떨어지는", "올랐어요", "작았습니다"]:
        print(f"- direction({w!r}) = {direction(w)!r}")
    for line in ["큰 글씨 모드만 켠 매장은 교육을 한 매장보다 주문 성공률 상승 폭이 작았습니다.",
                 "무사 1루에서 강공은 번트보다 그 이닝 득점 확률이 1.3배 높았습니다.",
                 "무사 1루에서는 번트가 강공보다 그 이닝 득점 확률이 더 높았어요.",
                 "앞문과 뒤 창문을 함께 여는 맞통풍은 한쪽 창문만 열 때보다 농도가 2배 빨리 떨어졌습니다."]:
        print(f"- directions={sorted(directions(line))} _than_sides={_than_sides(line)} «{line}»")
    print("\n## 3. 바른 녹음(R2)·자료에 없는 주장(U1)이 모순이 되는가")
    show("bunt R2 「이 할도 안 되는」(=2할 미만)", bun, "그리고 타율이 이 할도 안 되는 타자라면 번트가 나아요.")
    show("변형: 숫자로", bun, "타율이 2할도 안 되는 타자라면 번트가 나아요.")
    show("변형: 「2할이 안 되는」", bun, "타율 2할이 안 되는 타자는 번트가 나아요.")
    show("대조: 「2할 미만인」", bun, "타율이 2할 미만인 타자라면 번트가 나아요.")
    print(f"- negated('타율이 2할도 안 되는 타자라면') = {negated('타율이 2할도 안 되는 타자라면')}")
    show("bunt R2 1.3배 ↔ 「삼십 퍼센트 더」", bun, "강공이 번트보다 삼십 퍼센트 정도 더 높았던 거예요.")
    show("kiosk R2 「두 배 반」「일 분 사 초」", kio, "두 배 반 정도로 늘어난 거죠. 평균 주문 시간도 백십 초에서 일 분 사 초로 줄었어요.")
    show("kiosk R1 「72분」(사람 세는 분)", kio, "결과는 참여하신 72분 기준이에요.")
    show("kiosk U1", kio, "그리고 교육을 들은 어르신 열 명 중 아홉 명은 한 달 뒤에도 혼자 주문하셨어요.")
    show("co2 U1", co2, "실제로 환기를 잘한 반은 기말고사 평균도 5점 정도 높았다고 해요.")
    show("bunt U1", bun, "메이저리그에서도 번트가 10년 사이에 절반으로 줄었다고 하죠.")
    print("\n## 4. 모순 질문의 답을 판정 가드(conflicts)가 어떻게 읽나 — co2 Q1")
    q = "평균 농도가 60퍼센트나 낮아졌다고 했는데 자료 5장과 수치가 다른가요?"
    show("바른 답(자료 쪽)", co2, "다시 보니 자료가 맞아요. 5장 표에서 1,450ppm이 870ppm으로 내려갔으니 40% 낮아진 거예요. 발표에서 잘못 말했어요.", q)
    show("틀린 값 고집", co2, "60퍼센트가 맞다고 생각해요. 제가 직접 측정했어요.", q)
    print(f"- numbers('1,450ppm이 870ppm으로') = {[(n.value, n.unit) for n in numbers('1,450ppm이 870ppm으로')]} (ppm·kg·km 는 단위가 아니다)")
    print("\n## 5. 건너뛰는 말 (skip_cue)")
    for s in ["음 여기는 환기량 계산하는 공식인데요, 이건 좀 복잡해서 오늘은 생략하고 바로 결과로 갈게요.",
              "이 장은 주문 시간을 계산한 건데요, 시간이 없어서 패스하겠습니다.",
              "예외인 경우는 오늘은 빼고 바로 결론으로 가겠습니다.", "여기는 제외하고 결론만 말씀드릴게요.",
              "이 부분은 오늘 다루지 않을게요.", "이 장은 오늘은 안 볼게요."]:
        print(f"- {skip_cue(s)!s:5s} «{s}»")
    print("\n## 6. 지어낸 인용이 정합 근거로 남는가 (resolve_evidence) — co2 R1 맞통풍")
    summ = json.loads((EVID / "co2_r1_audio_t10" / "pipeline_summary.json").read_text(encoding="utf-8"))
    segs = [dict(b, visit=1, words=[]) for b in summ["transcript_by_slide"]]
    tr = Transcript.from_dict({"full_text": " ".join(b["text"] for b in segs), "words": [], "by_slide": segs,
                               "provider": "clova-txt", "duration_sec": segs[-1]["end_sec"]})
    node = ConceptNode(id="cross-ventilation", label="맞통풍", slide_nos=[6])
    ev = "앞문까지 다 열 필요는 없다는 거죠. 맞통풍은 한쪽 환기보다 농도가 2배 빨리 떨어집니다."
    kept = A.resolve_evidence(ev, node, utterances(tr))
    print(f"- LLM 인용 «{ev}»\n  → resolve_evidence 결과 «{kept}» (뒤 문장은 녹음에 없다 — 발표자는 반대로 말했다)")


if __name__ == "__main__":
    main()
