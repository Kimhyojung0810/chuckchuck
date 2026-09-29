"""
녹음 모드 F-08 질문 꼴·배치 수정(qa/f08rec, 09-30 녹음 감사 REC-05·07·11·18·02)을 **처음 보는 덱**으로 재는 합성 덱 둘. 주제는 저장소 어디에도
없던 것이고, 덱마다 R1(틀린 녹음) 하나.

- rec_laundry (기숙사 세탁실 대기) — 수정 뒤 첫 검증 덱. 이 덱의 결과를 보고 대표 고르기를 고쳤다(「그 장이 이름을 부르는 개념」 ·
  여러 장에 걸친 큰 개념은 접지 않음) — **튜닝에 쓴 덱**이다 (truth.group).
- rec_trail (주말 등산로 쓰레기) — 모든 수정을 마친 뒤 만든 덱. 규칙을 맞추는 데 쓰지 않았다 (held-out).

심은 것 (두 덱 같은 꼴, 겉모양은 다르게):
    S1  건너뛴 장(식)   : 식 장을 말로 건너뛴다 — 대표는 식 머리
    S2  건너뛴 장(제목) : 식 없는 장(표·줄글)을 말로 건너뛴다 — 대표는 장 제목의 개념
    N1  수치 모순       : 시범 결과 수치를 다르게 말한다
    A1  자료만 한 말    : 예산 수치 — 발표자는 수를 말하지 않는다 (「…라고 했는데」 의 주인 검사 재료)

    .venv/bin/python labs/qa_bench/corpus/build_rec_fresh.py            # slidedoc.json · recording_r1.txt · transcript.json · truth.json
    PYTHONPATH=<python-pptx 경로> .venv/bin/python labs/qa_bench/corpus/build_pptx.py rec_laundry rec_trail
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from build_corpus import deck, slide, transcript_of

HERE = Path(__file__).resolve().parent
FRESH: dict[str, dict] = {}

LAUNDRY_R1 = [
    (1, 0, 35, "안녕하세요, 생활관 자치회입니다. 오늘은 기숙사 세탁실 대기를 줄이는 방법을 말씀드릴게요. 핵심은 예약제예요."),
    (2, 35, 75, "지금 세탁실에는 세탁기 12대가 있고 학생 480명이 같이 써요. 특히 저녁 9시에서 11시 사이에 이용의 절반이 몰려요."),
    (3, 75, 83, "이 장은 대기 시간 계산식인데요, 시간 관계상 그냥 넘어갈게요."),
    (4, 83, 130, "그래서 예약제를 4주 동안 2개 층에서 시험해 봤어요. 평균 대기가 34분에서 4분으로 줄었고요, "
                 "헛걸음도 주 5회에서 1회로 줄었어요."),
    (5, 130, 136, "알림 기능 부분은 오늘은 건너뛸게요."),
    (6, 136, 170, "비용도 크지 않아요. 세탁기를 한 대 더 들이는 것보다 예약 시스템이 더 싸요."),
    (7, 170, 205, "한계도 있어요. 시범 운영이 2개 층뿐이었고, 시험 기간에는 이용 패턴이 달라질 수 있어요."),
    (8, 205, 235, "정리하면 예약제와 알림을 같이 쓰면 세탁기를 늘리지 않고도 대기를 줄일 수 있어요. 감사합니다."),
]
FRESH["rec_laundry"] = {
    "group": "f08rec_tuned_2026-09-30", "title": "세탁실 발표 녹음 (R1)", "script": LAUNDRY_R1,
    "doc": deck("기숙사_세탁실_예약제_제안.pptx", [
        slide(1, "# 기숙사 세탁실, 기다림을 줄일 수 있을까", "예약제로 바꾸면 대기가 줄어듭니다", "생활관 자치회 개선 제안"),
        slide(2, "# 지금의 세탁실", "세탁기 12대를 학생 480명이 함께 씁니다.", "저녁 9시~11시에 이용의 절반이 몰립니다."),
        slide(3, "# 대기 시간 계산", "평균 대기 시간 =", "대기 인원", "×", "한 번 세탁 시간", "÷", "세탁기 수",
              "몇 명이 줄을 서는가", "한 번 돌리는 데 얼마나", "기계가 몇 대인가"),
        slide(4, "# 예약제 시범 운영", "| 구분 | 평균 대기 | 헛걸음 |", "| 시범 전 | 34분 | 주 5회 |", "| 시범 후 | 9분 | 주 1회 |",
              "4주 동안 2개 층에서 시험했습니다."),
        slide(5, "# 알림 기능", "세탁이 끝나면 앱 알림을 보냅니다.", "알림을 켠 학생은 끝난 세탁물을 평균 6분 안에 꺼냈습니다.",
              "알림을 끈 학생은 평균 21분 걸렸습니다."),
        slide(6, "# 비용", "예약 시스템 운영 비용은 연 180만 원입니다.", "세탁기 1대를 더 들이는 비용(연 250만 원)보다 적습니다."),
        slide(7, "# 한계", "시범 운영은 2개 층에서만 했습니다.", "시험 기간에는 이용 패턴이 달라질 수 있습니다."),
        slide(8, "# 정리", "예약제와 알림을 함께 쓰면 세탁기를 늘리지 않고도 대기를 줄일 수 있습니다.", "감사합니다"),
    ]),
    "planted": [
        {"id": "S1", "kind": "skipped_slide", "slide": 3, "skip_quote": LAUNDRY_R1[2][3], "note": "식 장 — 대표는 식 머리(평균 대기 시간)"},
        {"id": "S2", "kind": "skipped_slide", "slide": 5, "skip_quote": LAUNDRY_R1[4][3], "note": "식 없는 장 — 대표는 장 제목의 개념(알림 기능)"},
        {"id": "N1", "kind": "contradiction_number", "slide": 4, "deck_value": "9분", "speech_value": "4분"},
        {"id": "A1", "kind": "deck_only_statement", "slide": 6, "deck_quote": "예약 시스템 운영 비용은 연 180만 원입니다.",
         "note": "발표자는 수를 말하지 않았다 — 질문이 「…라고 했는데」 로 발표자에게 붙이면 안 된다"}],
    "expect": {"skipped_slides": [3, 5], "contradiction_slides": [4]},
}

TRAIL_R1 = [
    (1, 0, 35, "안녕하세요, 산악회 환경 모임입니다. 오늘은 주말 등산로 쓰레기를 줄이는 방법을 말씀드릴게요. 핵심은 되가져가기 봉투예요."),
    (2, 35, 75, "주말 하루에 등산객이 평균 1200명 정도 와요. 그리고 쉼터 세 곳에서 나오는 쓰레기가 전체의 70퍼센트예요."),
    (3, 75, 82, "이 계산 과정은 오늘은 건너뛰겠습니다."),
    (4, 82, 130, "그래서 입구 두 곳에서 6주 동안 봉투를 나눠 줘 봤어요. 주말 쓰레기는 95kg으로 줄었고요, "
                 "쉼터에 몰래 버리는 것도 주 2건까지 줄었어요."),
    (5, 130, 135, "이 부분은 시간상 생략할게요."),
    (6, 135, 165, "예산도 부담이 크지 않아요. 수거하는 사람을 한 명 더 쓰는 것보다 봉투가 훨씬 싸요."),
    (7, 165, 195, "한계도 있어요. 시범은 가을에만 했고요, 비 오는 주말은 뺐어요."),
    (8, 195, 225, "정리하면 봉투 나눔을 쉼터 정비와 같이 하면 수거 비용을 늘리지 않고도 쓰레기를 줄일 수 있어요. 감사합니다."),
]
FRESH["rec_trail"] = {
    "group": "f08rec_heldout_2026-09-30", "title": "등산로 발표 녹음 (R1)", "script": TRAIL_R1,
    "doc": deck("주말_등산로_쓰레기_줄이기.pptx", [
        slide(1, "# 주말 등산로, 쓰레기를 줄일 수 있을까", "되가져가기 봉투를 나눠 주면 버리는 양이 줄어듭니다", "산악회 환경 모임 제안",
              "1"),
        slide(2, "# 지금의 등산로", "주말 하루 등산객은 평균 1,200명입니다.", "쉼터 3곳에서 나오는 쓰레기가 전체의 70%입니다.", "2"),
        slide(3, "# 수거 비용 계산", "월 수거 비용 =", "수거 횟수", "×", "1회 인건비", "+", "운반 비용",
              "얼마나 자주 치우는가", "한 번에 드는 사람값", "산 아래로 옮기는 값", "3"),
        slide(4, "# 봉투 나눔 시범", "| 구분 | 주말 쓰레기 양 | 쉼터 투기 |", "| 시범 전 | 180kg | 주 12건 |", "| 시범 후 | 95kg | 주 4건 |",
              "6주 동안 입구 2곳에서 봉투를 나눠 주었습니다.", "4"),
        slide(5, "# 안내판 효과", "| 안내판 | 투기 신고 |", "| 없을 때 | 주 9건 |", "| 있을 때 | 주 5건 |",
              "안내판만으로는 효과가 작았습니다.", "5"),
        slide(6, "# 예산", "봉투 제작비는 한 해 320만 원입니다.", "수거 인력 1명을 늘리는 비용(한 해 2,400만 원)보다 적습니다.", "6"),
        slide(7, "# 한계", "시범은 가을에만 했습니다.", "비 오는 주말은 자료에서 뺐습니다.", "7"),
        slide(8, "# 정리", "봉투 나눔을 쉼터 정비와 함께 하면 수거 비용을 늘리지 않고 쓰레기를 줄일 수 있습니다.", "감사합니다", "8"),
    ]),
    "planted": [
        {"id": "S1", "kind": "skipped_slide", "slide": 3, "skip_quote": TRAIL_R1[2][3], "note": "식 장(곱·합) — 대표는 식 머리(월 수거 비용)"},
        {"id": "S2", "kind": "skipped_slide", "slide": 5, "skip_quote": TRAIL_R1[4][3], "note": "표 장 — 대표는 장 제목의 개념(안내판 효과)"},
        {"id": "N1", "kind": "contradiction_number", "slide": 4, "deck_value": "주 4건", "speech_value": "주 2건"},
        {"id": "A1", "kind": "deck_only_statement", "slide": 6, "deck_quote": "봉투 제작비는 한 해 320만 원입니다.",
         "note": "발표자는 수를 말하지 않았다"}],
    "expect": {"skipped_slides": [3, 5], "contradiction_slides": [4]},
}


def clova_txt(title: str, script: list[tuple]) -> str:
    """클로바노트 .txt 꼴 — 제목 · 날짜와 길이 · 화자 · (MM:SS 줄 + 문장 줄) 블록 (감사 도구 `build_audit_decks.clova_txt` 와 같은 꼴)."""
    end = int(script[-1][2])
    head = [title, f"2026.09.30 수 오후 3:12 ・ {end // 60}분 {end % 60}초", "발표자 1", ""]
    body: list[str] = []
    for _no, t0, _t1, text in script:
        t0 = int(t0)
        body.append(f"{t0 // 60:02d}:{t0 % 60:02d}")
        body.extend(s for s in re.split(r"(?<=[.?!])\s+", text) if s.strip())
        body.append("")
    return "\n".join(head + body) + "\n"


def main() -> None:
    for name, spec in FRESH.items():
        d = HERE / name
        d.mkdir(parents=True, exist_ok=True)
        script = spec["script"]
        (d / "slidedoc.json").write_text(json.dumps(spec["doc"], ensure_ascii=False, indent=1), encoding="utf-8")
        (d / "transcript.json").write_text(json.dumps(transcript_of(script), ensure_ascii=False, indent=1), encoding="utf-8")
        (d / "recording_r1.txt").write_text(clova_txt(spec["title"], script), encoding="utf-8")
        truth = {"deck": name, "synthetic": True, "group": spec["group"],
                 "context": {"situation": "school_project", "duration_min": 10}, "total_slides": len(spec["doc"]["slides"]),
                 "recordings": {"r1": {"kind": "flawed", "clova_file": "recording_r1.txt", "transcript_file": "transcript.json",
                                       "planted": spec["planted"],
                                       "slide_segments_truth": [{"slide_no": x[0], "start_sec": x[1], "end_sec": x[2]} for x in script]}},
                 "expect": spec["expect"]}
        (d / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{name}: {len(spec['doc']['slides'])}장 · 녹음 R1 · {spec['group']}")


if __name__ == "__main__":
    main()
