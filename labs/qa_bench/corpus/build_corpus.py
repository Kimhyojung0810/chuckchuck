"""
QA 일반화 벤치의 **합성 자료** 원본 — 이 파일이 `corpus/<deck>/slidedoc.json`·`truth.json`(·`transcript.json`)을 만든다.

실제 덱처럼 줄 구조를 살렸다: 제목, 짧은 글 상자, 칸마다 나뉜 식(「A =」「B」「×」「C」), 표(|), 설문 보기, 쪽 번호(「03 / 08」).
덱마다 **심어 둔 정답(ground truth)** 이 있다 — 어느 장에 무엇을 심었고, 파이프라인이 어떤 주장·탐침으로 찾아야 하는지.

    .venv/bin/python labs/qa_bench/corpus/build_corpus.py      # JSON 다시 쓰기 (LLM 없음)

truth.json 모양:
    planted: [{id, kind, expect, slides, labels_any, quote_any, note}]
        kind   = 탐침 종류(tension·unsolved·unsupported_cause·absolute_boundary) 또는 음성 대조군
                 (supported_cause — unsupported_cause 가 나오면 안 된다 · hedged — absolute_boundary 가 나오면 안 된다)
        expect = "probe" (이 종류 탐침이 나와야 한다) | "no_probe" (이 대상에 그 종류가 나오면 오탐)
        labels_any = 탐침 대상 개념(node_ids[0]) 라벨이 이 말 중 하나를 품으면 맞힌 것 (공백 무시)
        quote_any  = 또는 탐침 근거 인용이 이 말 중 하나를 품으면 맞힌 것
    claims: [{kind, slide, quote_any}]  — 심은 주장 (주장 재현율)
    control_tension: true 면 긴장이 하나도 없어야 한다
    noise_lines: 힌트 인용으로 나오면 안 되는 조각 (설문 보기·쪽 번호)
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def slide(no: int, *lines: str, title: str = "") -> dict:
    """줄 머리 「# 」 = heading1, 「| 」 = table, 나머지 paragraph. 한 줄 = 한 글 상자."""
    blocks = []
    for ln in lines:
        if ln.startswith("# "):
            blocks.append({"category": "heading1", "text": ln[2:]})
        elif ln.startswith("| "):
            blocks.append({"category": "table", "text": ln})
        else:
            blocks.append({"category": "paragraph", "text": ln})
    head = next((b["text"] for b in blocks if b["category"] == "heading1"), "")
    return {"slide_no": no, "title": title or head, "blocks": blocks}


def deck(file_name: str, slides: list[dict]) -> dict:
    return {"file_name": file_name, "total_slides": len(slides), "slides": slides}


DECKS: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# 1. 스타트업 IR — 긴장 · 풀리지 않은 문제 · 근거 없는 인과 / 근거 있는 인과 · 단정 / 유보
# ---------------------------------------------------------------------------
DECKS["ir_banchan"] = {
    "context": {"situation": "competition", "duration_min": 7},
    "doc": deck("한끼곳간_IR_시드라운드.pptx", [
        slide(1, "01 / 08", "한끼곳간", "# 동네 반찬 정기구독", "구독자 수보다 중요한 월 반복 매출",
              "시드 라운드 투자 제안 | 2026.09"),
        slide(2, "02 / 08", "# 왜 지금 반찬 구독인가", "1인 가구 증가가 반찬 구독 수요를 늘립니다.",
              "퇴근 후 요리할 시간이 없는 직장인", "장을 봐도 재료가 남는 1인 가구"),
        slide(3, "03 / 08", "# 우리가 보는 숫자", "월 반복 매출 =", "구독자 수", "×", "객단가", "×", "유지율",
              "몇 명이 구독하는가", "한 번에 얼마를 내는가", "다음 달에도 남는가"),
        slide(4, "04 / 08", "# 수익성을 가로막는 세 가지 문제", "① 높은 배송비", "② 반찬 폐기 손실", "③ 첫 달 이탈",
              "세 문제가 모두 공헌이익을 깎습니다."),
        slide(5, "05 / 08", "# 해결책", "권역 묶음 배송 — 같은 아파트 단지 주문을 한 번에 배송해 배송비를 낮춥니다.",
              "수요 예측 주문 마감 — 전날 18시에 주문을 마감해 폐기 손실을 줄입니다.",
              "주문 마감 후 남는 반찬은 반드시 0개가 됩니다."),
        slide(6, "06 / 08", "# 파일럿 결과 (성수동 3개 단지, 12주)",
              "| 지표 | 도입 전 | 도입 후 |", "| 건당 배송비 | 3,200원 | 1,900원 |", "| 폐기율 | 14% | 6% |",
              "묶음 배송 도입 후 건당 배송비가 3,200원에서 1,900원으로 41% 줄었습니다."),
        slide(7, "07 / 08", "# 고객 반응", "대부분의 고객은 첫 달 안에 구독을 유지할지 결정하는 경향이 있습니다.",
              "재구독 고객의 평균 객단가 32,000원"),
        slide(8, "08 / 08", "# 투자 요청", "5억 원 · 18개월 런웨이", "권역 3곳 → 12곳 확장", "감사합니다"),
    ]),
    "truth": {
        "control_tension": False,
        "planted": [
            {"id": "T1", "kind": "tension", "expect": "probe", "slides": [1, 3],
             "labels_any": ["월 반복 매출", "반복 매출", "MRR"], "quote_any": ["구독자 수보다 중요한", "월 반복 매출 ="],
             "note": "구독자 수보다 중요하다면서 구독자 수가 월 반복 매출의 요소"},
            {"id": "U1", "kind": "unsolved", "expect": "probe", "slides": [4, 5],
             "labels_any": ["첫 달 이탈", "이탈"], "quote_any": ["첫 달 이탈"],
             "note": "해결책이 배송비·폐기만 다루고 첫 달 이탈은 비어 있다"},
            {"id": "C1", "kind": "unsupported_cause", "expect": "probe", "slides": [2],
             "labels_any": ["1인 가구"], "quote_any": ["1인 가구 증가가"],
             "note": "2장에 수치·출처 없음"},
            {"id": "C2", "kind": "supported_cause", "expect": "no_probe", "slides": [6],
             "labels_any": ["묶음 배송", "권역 묶음"], "quote_any": ["41% 줄었"],
             "note": "수치가 있는 인과 — unsupported_cause 가 나오면 오탐"},
            {"id": "A1", "kind": "absolute_boundary", "expect": "probe", "slides": [5],
             "labels_any": ["주문 마감", "수요 예측", "폐기"], "quote_any": ["반드시 0개"],
             "note": "단정"},
            {"id": "H1", "kind": "hedged", "expect": "no_probe", "slides": [7],
             "labels_any": ["고객 반응", "유지"], "quote_any": ["경향이 있습니다"],
             "note": "유보 표현 — absolute_boundary 가 나오면 오탐"},
        ],
        "claims": [
            {"kind": "compare", "slide": 1, "quote_any": ["구독자 수보다 중요한"]},
            {"kind": "compose", "slide": 3, "quote_any": ["월 반복 매출 ="]},
            {"kind": "compose", "slide": 4, "quote_any": ["높은 배송비", "세 가지 문제", "첫 달 이탈", "반찬 폐기"]},
            {"kind": "solve", "slide": 5, "quote_any": ["권역 묶음 배송"]},
            {"kind": "solve", "slide": 5, "quote_any": ["수요 예측 주문 마감"]},
            {"kind": "cause", "slide": 2, "quote_any": ["1인 가구 증가가"]},
            {"kind": "absolute", "slide": 5, "quote_any": ["반드시 0개"]},
        ],
        "noise_lines": ["01 / 08", "02 / 08", "03 / 08", "04 / 08", "05 / 08", "06 / 08", "07 / 08", "08 / 08"],
    },
}

# ---------------------------------------------------------------------------
# 2. 과학 탐구 — 대조군: 긴장·단정 없음. 식과 비교가 있지만 서로 안 부딪친다.
# ---------------------------------------------------------------------------
DECKS["sci_led"] = {
    "context": {"situation": "school_project", "duration_min": 5},
    "doc": deck("LED광원_상추생장_탐구보고.pptx", [
        slide(1, "# LED 광원 색에 따른 상추 생장 비교", "과학탐구 2모둠", "1 / 7"),
        slide(2, "# 탐구 질문", "빛의 색이 달라지면 상추의 생장도 달라질까?",
              "가설: 적색광 비율이 높을수록 잎 면적이 넓어진다."),
        slide(3, "# 실험 설계", "| 조건 | 광원 | 광량(μmol) | 개체 수 |", "| A | 적색 LED | 200 | 12 |",
              "| B | 청색 LED | 200 | 12 |", "| C | 백색 LED | 200 | 12 |",
              "온도 22℃ · 광주기 16시간 · 4주 재배", "3 / 7"),
        slide(4, "# 측정 방법", "생장 지수 =", "잎 면적", "×", "생체중", "잎 면적은 사진 분석, 생체중은 전자저울로 측정"),
        slide(5, "# 결과", "| 조건 | 잎 면적(cm²) | 생체중(g) |", "| A | 182 | 21.4 |", "| B | 131 | 17.9 |",
              "| C | 158 | 19.6 |", "적색광 조건의 잎 면적이 청색광보다 39% 넓었습니다.", "5 / 7"),
        slide(6, "# 해석", "적색광은 청색광보다 잎 면적 확장에 효과적인 것으로 보입니다.",
              "다만 이 결과는 온도와 품종에 따라 달라질 수 있습니다.",
              "청색광 조건은 줄기가 짧고 잎이 두꺼웠습니다."),
        slide(7, "# 한계와 다음 탐구", "개체 수가 조건당 12개로 적습니다.", "다음에는 적색·청색 혼합 비율을 바꿔 보려고 합니다.",
              "7 / 7"),
    ]),
    "truth": {
        "control_tension": True,
        "planted": [
            {"id": "C2", "kind": "supported_cause", "expect": "no_probe", "slides": [5, 6],
             "labels_any": ["적색광", "적색 LED"], "quote_any": ["39% 넓었"],
             "note": "수치가 있는 인과(5장) — 6장의 해석에 cause 가 잡혀도 그 장엔 수치가 없어 경계 사례"},
            {"id": "H1", "kind": "hedged", "expect": "no_probe", "slides": [6],
             "labels_any": ["온도", "품종", "해석"], "quote_any": ["달라질 수 있습니다"],
             "note": "유보 표현 — absolute_boundary 가 나오면 오탐"},
        ],
        "claims": [
            {"kind": "compose", "slide": 4, "quote_any": ["생장 지수 ="]},
            {"kind": "compare", "slide": 6, "quote_any": ["청색광보다 잎 면적", "청색광보다"]},
        ],
        "noise_lines": ["1 / 7", "3 / 7", "5 / 7", "7 / 7"],
    },
}

# ---------------------------------------------------------------------------
# 3. 정책 제안 — 긴장 · 풀리지 않은 문제 · 단정 · 유보 · 근거 없는 인과
# ---------------------------------------------------------------------------
DECKS["policy_jeonse"] = {
    "context": {"situation": "competition", "duration_min": 7},
    "doc": deck("대학가_전세사기_예방정책_제안.pptx", [
        slide(1, "# 대학가 전세사기, 사후 구제에서 사전 예방으로", "처벌 강화보다 중요한 예방 체계",
              "2026 청년정책 제안 공모전 · 도시행정학과 3팀"),
        slide(2, "# 피해는 왜 대학가에 몰리나", "신축 빌라 시세 정보가 부족해서 깡통전세가 늘어납니다.",
              "첫 자취를 시작하는 학생은 등기부등본을 읽어 본 적이 없습니다."),
        slide(3, "# 예방 체계의 구조", "예방 체계 =", "정보 공개", "×", "보증 가입", "×", "처벌 강화",
              "계약 전에 알고, 계약할 때 지키고, 어기면 책임지게"),
        slide(4, "# 해결해야 할 세 가지 문제", "| 문제 | 현황 |", "| 정보 비대칭 | 시세·선순위 채권을 계약 전에 알기 어렵다 |",
              "| 보증 가입 장벽 | 보증료 부담으로 가입을 미룬다 |", "| 피해 회복 지연 | 보증금 반환까지 평균 1년 이상 |"),
        slide(5, "# 정책 제안 ①", "대학가 전세 시세 지도 — 학교 반경 2km 안 빌라의 실거래가와 선순위 채권을 한 화면에 공개합니다.",
              "정보 비대칭을 해소합니다."),
        slide(6, "# 정책 제안 ②", "청년 보증료 전액 지원 — 만 29세 이하 첫 전세 계약의 보증료를 지자체가 냅니다.",
              "보증 가입 장벽을 없앱니다."),
        slide(7, "# 기대 효과", "이 제도가 도입되면 대학가 전세사기는 완전히 사라집니다.",
              "피해 규모는 지역마다 다를 수 있어 시범 지역부터 시작합니다."),
        slide(8, "# 재원과 일정", "| 항목 | 연간 예산 |", "| 시세 지도 구축 | 4억 원 |", "| 보증료 지원 | 21억 원 |",
              "2027년 상반기 시범 운영"),
    ]),
    "truth": {
        "control_tension": False,
        "planted": [
            {"id": "T1", "kind": "tension", "expect": "probe", "slides": [1, 3],
             "labels_any": ["예방 체계", "사전 예방", "예방"], "quote_any": ["처벌 강화보다 중요한", "예방 체계 ="],
             "note": "처벌 강화보다 중요하다면서 처벌 강화가 예방 체계의 요소"},
            {"id": "U1", "kind": "unsolved", "expect": "probe", "slides": [4, 5, 6],
             "labels_any": ["피해 회복", "회복 지연"], "quote_any": ["피해 회복 지연"],
             "note": "제안 ①② 가 정보 비대칭·보증 장벽만 다루고 피해 회복 지연은 비어 있다"},
            {"id": "C1", "kind": "unsupported_cause", "expect": "probe", "slides": [2],
             "labels_any": ["시세 정보", "깡통전세", "정보"], "quote_any": ["시세 정보가 부족해서"],
             "note": "2장에 수치·출처 없음"},
            {"id": "A1", "kind": "absolute_boundary", "expect": "probe", "slides": [7],
             "labels_any": ["기대 효과", "전세사기", "제도"], "quote_any": ["완전히 사라집니다"],
             "note": "단정"},
            {"id": "H1", "kind": "hedged", "expect": "no_probe", "slides": [7],
             "labels_any": ["피해 규모", "시범"], "quote_any": ["다를 수 있어"],
             "note": "유보 — absolute_boundary 의 인용이 이 문장이면 오탐"},
        ],
        "claims": [
            {"kind": "compare", "slide": 1, "quote_any": ["처벌 강화보다 중요한"]},
            {"kind": "compose", "slide": 3, "quote_any": ["예방 체계 ="]},
            {"kind": "compose", "slide": 4, "quote_any": ["정보 비대칭", "세 가지 문제", "피해 회복 지연", "보증 가입 장벽"]},
            {"kind": "solve", "slide": 5, "quote_any": ["시세 지도", "정보 비대칭을 해소"]},
            {"kind": "solve", "slide": 6, "quote_any": ["보증료 전액 지원", "보증 가입 장벽을 없앱"]},
            {"kind": "cause", "slide": 2, "quote_any": ["시세 정보가 부족해서"]},
            {"kind": "absolute", "slide": 7, "quote_any": ["완전히 사라집니다"]},
        ],
        "noise_lines": [],
    },
}

# ---------------------------------------------------------------------------
# 4. 인문 조별과제 — 긴장 · 단정 · 유보 · 근거 없는 인과 · 설문 보기(잡음)
# ---------------------------------------------------------------------------
DECKS["hum_novel"] = {
    "context": {"situation": "school_project", "duration_min": 10},
    "doc": deck("조선후기_한글소설의_확산_조별발표.pptx", [
        slide(1, "# 조선 후기 한글 소설은 어떻게 퍼졌나", "필사본보다 중요한 세책 문화", "한국문학사 2조 | 01"),
        slide(2, "# 여러분은 춘향전을 끝까지 읽어 본 적 있나요?", "① 있다", "② 없다", "③ 줄거리만 안다", "02"),
        slide(3, "# 시대 배경", "상업 발달이 한글 소설 독자층을 넓혔습니다.", "장시와 포구를 따라 사람과 물건이 오갔습니다.", "03"),
        slide(4, "# 세책 문화란", "세책 문화 =", "필사본", "×", "대여 제도", "×", "여성 독자",
              "책을 베껴 쓰고, 돈을 받고 빌려주고, 규방에서 돌려 읽었다", "04"),
        slide(5, "# 방각본과의 비교", "| 구분 | 세책본 | 방각본 |", "| 제작 | 손으로 필사 | 목판 인쇄 |",
              "| 분량 | 수십 권 장편 | 20~30장 축약 |", "일부 연구자는 방각본이 더 큰 역할을 했다고 보기도 합니다.", "05"),
        slide(6, "# 서사의 특징", "한글 소설은 항상 권선징악으로 끝납니다.", "주인공의 고난 → 조력자 → 신분 회복", "06"),
        slide(7, "# 우리 조의 결론", "소설을 퍼뜨린 것은 작가가 아니라 빌려 읽는 독자였다.", "07"),
    ]),
    "truth": {
        "control_tension": False,
        "planted": [
            {"id": "T1", "kind": "tension", "expect": "probe", "slides": [1, 4],
             "labels_any": ["세책 문화", "세책"], "quote_any": ["필사본보다 중요한", "세책 문화 ="],
             "note": "필사본보다 중요하다면서 필사본이 세책 문화의 요소"},
            {"id": "C1", "kind": "unsupported_cause", "expect": "probe", "slides": [3],
             "labels_any": ["상업 발달", "상업"], "quote_any": ["상업 발달이"],
             "note": "3장에 수치·출처 없음"},
            {"id": "A1", "kind": "absolute_boundary", "expect": "probe", "slides": [6],
             "labels_any": ["권선징악", "서사", "한글 소설"], "quote_any": ["항상 권선징악"],
             "note": "단정"},
            {"id": "H1", "kind": "hedged", "expect": "no_probe", "slides": [5],
             "labels_any": ["방각본"], "quote_any": ["보기도 합니다"],
             "note": "유보 — absolute_boundary 가 나오면 오탐"},
        ],
        "claims": [
            {"kind": "compare", "slide": 1, "quote_any": ["필사본보다 중요한"]},
            {"kind": "compose", "slide": 4, "quote_any": ["세책 문화 ="]},
            {"kind": "cause", "slide": 3, "quote_any": ["상업 발달이"]},
            {"kind": "absolute", "slide": 6, "quote_any": ["항상 권선징악"]},
            {"kind": "contrast", "slide": 7, "quote_any": ["작가가 아니라"]},
        ],
        "noise_lines": ["① 있다", "② 없다", "③ 줄거리만 안다", "01", "02", "03", "04", "05", "06", "07"],
    },
}

# ---------------------------------------------------------------------------
# 5. 제품 기획 — 대조군(긴장 없음) · 풀리지 않은 문제 · 근거 있는/없는 인과 · 단정(설계 규칙) · 유보
# ---------------------------------------------------------------------------
DECKS["prod_tumsae"] = {
    "context": {"situation": "competition", "duration_min": 5},
    "doc": deck("틈새_공강매칭앱_기획안.pptx", [
        slide(1, "# 틈새", "공강 시간에 같이 밥 먹을 사람을 찾아 주는 앱", "캡스톤디자인 · 1 / 7"),
        slide(2, "# 사용자 문제", "공강 시간이 길수록 학교 만족도가 떨어집니다.", "혼자 보내는 90분이 가장 길게 느껴집니다.", "2 / 7"),
        slide(3, "# 매칭이 실패하는 세 가지 이유", "시간표 불일치", "낯선 사람에 대한 부담", "약속 당일 취소", "3 / 7"),
        slide(4, "# 핵심 기능", "시간표 자동 연동 — 에브리타임 시간표를 불러와 공강이 겹치는 사람만 보여 줍니다.",
              "학과·동아리 인증 배지 — 같은 학과·동아리 인증으로 낯선 사람에 대한 부담을 줄입니다.", "4 / 7"),
        slide(5, "# 베타 테스트 결과", "| 그룹 | 인원 | 매칭 성공률 |", "| 시간표 연동 켬 | 64명 | 42% |",
              "| 시간표 연동 끔 | 56명 | 20% |", "시간표 연동을 켠 사용자의 매칭 성공률이 2.1배 높았습니다.", "5 / 7"),
        slide(6, "# 알림 원칙", "알림은 절대 하루 3번을 넘지 않습니다.", "사용자에 따라 선호 시간대가 다를 수 있어 알림 시각은 직접 고릅니다.",
              "6 / 7"),
        slide(7, "# 로드맵", "11월 교내 출시 → 1학기 3개 대학 확장", "7 / 7"),
    ]),
    "truth": {
        "control_tension": True,
        "planted": [
            {"id": "U1", "kind": "unsolved", "expect": "probe", "slides": [3, 4],
             "labels_any": ["당일 취소", "약속 취소", "취소"], "quote_any": ["약속 당일 취소"],
             "note": "기능이 시간표 불일치·낯선 부담만 다루고 당일 취소는 비어 있다"},
            {"id": "C1", "kind": "unsupported_cause", "expect": "probe", "slides": [2],
             "labels_any": ["공강 시간", "학교 만족도", "공강"], "quote_any": ["공강 시간이 길수록"],
             "note": "2장 「90분」 은 수치라 has_support 가 참이 될 수 있다 — 경계 사례로 따로 본다"},
            {"id": "C2", "kind": "supported_cause", "expect": "no_probe", "slides": [5],
             "labels_any": ["시간표 연동", "시간표 자동 연동"], "quote_any": ["2.1배"],
             "note": "수치가 있는 인과 — unsupported_cause 가 나오면 오탐"},
            {"id": "A1", "kind": "absolute_boundary", "expect": "probe", "slides": [6],
             "labels_any": ["알림"], "quote_any": ["절대 하루 3번"],
             "note": "단정(설계 규칙)"},
            {"id": "H1", "kind": "hedged", "expect": "no_probe", "slides": [6],
             "labels_any": ["선호 시간대", "알림 시각"], "quote_any": ["다를 수 있어"],
             "note": "유보"},
        ],
        "claims": [
            {"kind": "compose", "slide": 3, "quote_any": ["시간표 불일치", "세 가지 이유", "약속 당일 취소", "낯선 사람"]},
            {"kind": "solve", "slide": 4, "quote_any": ["시간표 자동 연동"]},
            {"kind": "solve", "slide": 4, "quote_any": ["인증 배지", "낯선 사람에 대한 부담을 줄입니다"]},
            {"kind": "cause", "slide": 2, "quote_any": ["공강 시간이 길수록"]},
            {"kind": "absolute", "slide": 6, "quote_any": ["절대 하루 3번"]},
        ],
        "noise_lines": ["1 / 7", "2 / 7", "3 / 7", "4 / 7", "5 / 7", "6 / 7", "7 / 7"],
    },
}

# ---------------------------------------------------------------------------
# 6. 의료·건강 교양 — 긴장(식에 ÷) · 풀리지 않은 문제 · 근거 없는/있는 인과 · 단정 · 유보 · 설문 · 녹음(핵심 장 덜 말함)
# ---------------------------------------------------------------------------
DECKS["health_glucose"] = {
    "context": {"situation": "school_project", "duration_min": 5},
    "doc": deck("혈당스파이크와_식사순서_교양발표.pptx", [
        slide(1, "01 / 08", "# 밥 먹고 졸린 이유", "탄수화물 양보다 중요한 혈당 부하", "“점심 먹고 가장 졸린 시간은?”",
              "1시", "2시", "3시 이후"),
        slide(2, "02 / 08", "# 혈당 스파이크란", "식후 혈당이 짧은 시간에 급하게 올랐다가 떨어지는 현상입니다."),
        slide(3, "03 / 08", "# 혈당 부하 계산", "혈당 부하 =", "혈당 지수", "×", "탄수화물 양", "÷ 100",
              "얼마나 빨리 오르는 음식인가", "얼마나 먹었는가"),
        slide(4, "04 / 08", "# 스파이크가 만드는 세 가지 문제", "식후 졸림", "잦은 허기", "야간 폭식"),
        slide(5, "05 / 08", "# 식사 순서 바꾸기", "채소 → 단백질 → 탄수화물 순서로 먹으면 식후 졸림을 줄일 수 있습니다.",
              "식이섬유를 먼저 먹으면 포만감이 오래가서 잦은 허기를 막습니다.",
              "식사 순서만 바꾸면 혈당 스파이크는 완전히 막을 수 있습니다."),
        slide(6, "06 / 08", "# 연구로 본 효과", "채소를 먼저 먹은 그룹은 식후 혈당 최고치가 평균 29% 낮았습니다 (Shukla 외, 2015).",
              "| 순서 | 30분 혈당 | 60분 혈당 |", "| 탄수화물 먼저 | 172 | 180 |", "| 채소 먼저 | 122 | 128 |"),
        slide(7, "07 / 08", "# 생활 속 팁", "야식이 다음 날 아침 공복 혈당을 높입니다.", "개인에 따라 반응이 다를 수 있으니 무리하지 마세요."),
        slide(8, "08 / 08", "# 정리", "무엇을 먹느냐만큼 어떤 순서로 먹느냐도 중요합니다.", "감사합니다"),
    ]),
    "truth": {
        "control_tension": False,
        "planted": [
            {"id": "T1", "kind": "tension", "expect": "probe", "slides": [1, 3],
             "labels_any": ["혈당 부하"], "quote_any": ["탄수화물 양보다 중요한", "혈당 부하 ="],
             "note": "탄수화물 양보다 중요하다면서 탄수화물 양이 혈당 부하의 요소 (식에 ÷ 100 이 붙어 있다)"},
            {"id": "U1", "kind": "unsolved", "expect": "probe", "slides": [4, 5],
             "labels_any": ["야간 폭식", "폭식"], "quote_any": ["야간 폭식"],
             "note": "식사 순서가 졸림·허기만 다루고 야간 폭식은 비어 있다"},
            {"id": "C1", "kind": "unsupported_cause", "expect": "probe", "slides": [7],
             "labels_any": ["야식", "공복 혈당"], "quote_any": ["야식이 다음 날"],
             "note": "7장에 수치·출처 없음"},
            {"id": "C2", "kind": "supported_cause", "expect": "no_probe", "slides": [6],
             "labels_any": ["채소", "식사 순서"], "quote_any": ["29% 낮았"],
             "note": "수치·출처가 있는 인과"},
            {"id": "A1", "kind": "absolute_boundary", "expect": "probe", "slides": [5],
             "labels_any": ["식사 순서", "혈당 스파이크"], "quote_any": ["완전히 막을 수"],
             "note": "단정"},
            {"id": "H1", "kind": "hedged", "expect": "no_probe", "slides": [7],
             "labels_any": ["개인차", "반응"], "quote_any": ["다를 수 있으니"],
             "note": "유보"},
        ],
        "claims": [
            {"kind": "compare", "slide": 1, "quote_any": ["탄수화물 양보다 중요한"]},
            {"kind": "compose", "slide": 3, "quote_any": ["혈당 부하 ="]},
            {"kind": "compose", "slide": 4, "quote_any": ["식후 졸림", "세 가지 문제", "야간 폭식", "잦은 허기"]},
            {"kind": "solve", "slide": 5, "quote_any": ["채소 → 단백질", "식후 졸림을 줄일"]},
            {"kind": "solve", "slide": 5, "quote_any": ["식이섬유를 먼저", "잦은 허기를 막"]},
            {"kind": "cause", "slide": 7, "quote_any": ["야식이 다음 날"]},
            {"kind": "absolute", "slide": 5, "quote_any": ["완전히 막을 수"]},
        ],
        "noise_lines": ["1시", "2시", "3시 이후", "01 / 08", "02 / 08", "03 / 08", "04 / 08", "05 / 08",
                        "06 / 08", "07 / 08", "08 / 08"],
        # 녹음 경로: 핵심 장(3장 혈당 부하 식)을 6초 만에 넘긴다 — under_spoken/missing 이 3장 개념에 붙어야 한다
        "under_spoken_slides": [3],
        "under_spoken_labels_any": ["혈당 부하", "혈당 지수"],
    },
    "transcript_script": [
        (1, 0.0, 28.0, "점심 먹고 두 시쯤 되면 너무 졸리잖아요. 오늘은 왜 그런지, 그리고 탄수화물 양보다 혈당 부하가 왜 더 중요한지 이야기해 볼게요."),
        (2, 28.0, 55.0, "혈당 스파이크는 밥을 먹은 뒤에 혈당이 짧은 시간에 확 올랐다가 뚝 떨어지는 현상이에요. 이게 떨어질 때 졸리고 기운이 빠져요."),
        (3, 55.0, 61.0, "이건 계산식인데 넘어갈게요."),
        (4, 61.0, 90.0, "스파이크가 반복되면 식후에 졸리고, 금방 또 배가 고프고, 밤에 폭식하게 돼요. 이 세 가지가 문제예요."),
        (5, 90.0, 132.0, "그래서 식사 순서를 바꾸자는 거예요. 채소를 먼저, 그다음 고기나 두부 같은 단백질, 마지막에 밥을 먹으면 졸림이 줄어요. 식이섬유가 먼저 들어가면 배도 오래 불러요."),
        (6, 132.0, 170.0, "실제로 채소를 먼저 먹은 그룹은 혈당 최고치가 평균 29퍼센트 낮았다는 연구가 있어요. 표를 보면 30분, 60분 혈당이 다 낮아요."),
        (7, 170.0, 190.0, "야식을 먹으면 다음 날 아침 혈당도 높아져요. 다만 사람마다 반응이 다르니까 무리하지는 마세요."),
        (8, 190.0, 205.0, "무엇을 먹느냐만큼 어떤 순서로 먹느냐도 중요해요. 감사합니다."),
    ],
}


def transcript_of(script: list[tuple[int, float, float, str]]) -> dict:
    """(장, 시작, 끝, 말) → Transcript dict. 낱말 시각은 구간 안에 고르게 나눈다 (합성)."""
    by_slide, words_all = [], []
    for no, t0, t1, text in script:
        toks = text.split()
        step = (t1 - t0) / max(1, len(toks))
        words = [{"text": w, "start_sec": round(t0 + i * step, 2), "end_sec": round(t0 + (i + 1) * step, 2)}
                 for i, w in enumerate(toks)]
        words_all.extend(words)
        by_slide.append({"slide_no": no, "visit": 1, "start_sec": t0, "end_sec": t1, "text": text, "words": words})
    return {"full_text": " ".join(s[3] for s in script), "words": words_all, "by_slide": by_slide,
            "provider": "synthetic", "duration_sec": script[-1][2] if script else 0.0}


def main() -> None:
    for name, spec in DECKS.items():
        d = HERE / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "slidedoc.json").write_text(json.dumps(spec["doc"], ensure_ascii=False, indent=1), encoding="utf-8")
        truth = {"deck": name, "synthetic": True, "context": spec["context"], **spec["truth"]}
        (d / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
        if spec.get("transcript_script"):
            (d / "transcript.json").write_text(
                json.dumps(transcript_of(spec["transcript_script"]), ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{name}: {len(spec['doc']['slides'])}장 · 심은 것 {len(spec['truth']['planted'])} · 주장 {len(spec['truth']['claims'])}"
              + (" · 녹음" if spec.get("transcript_script") else ""))


if __name__ == "__main__":
    main()
