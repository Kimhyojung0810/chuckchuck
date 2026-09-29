"""
자료 줄 읽기 — WP-M 이 남긴 둘 (qa/tidy).

1. 목록 항목의 도식 캡션 조각은 항목 글 **어디에** 있든 뗀다 (`_graph_items.clean_item` → `_evidence.caption_cut`). 09-30 까지 F-07 후처리는
   항목 끝의 물음 낱말만 뗐다 — 「대기 시간 몇 분 기다렸나」 는 물음으로, 「몇 번 불렀나 직원 응대」 는 긴 글로 떨어져 항목이 빠졌고,
   개수 말(「세 가지」)과 항목 수가 안 맞아 목록 전체가 버려졌다. 식 항은 WP-M 에서 이미 같은 규칙이었다.
2. 캡션 물음 줄 **뒤에** 온 「× 항」 줄은 캡션이 아니라 그 앞의 식에 잇는다 (`_evidence.join_formula` — F-08 인용·F-26 주장·F-07 후처리가
   같이 쓴다). 예전엔 「몇 번 치웠는가 × 화장실 거리」 가 되어 물음 줄로 버려지고, 식은 항 하나로 남았다.

**튜닝·held-out·벤치 덱의 낱말을 쓰지 않는다** — 동네 수영장·세탁소·요가원·캠핑장·빵집·반려식물 덱으로 본다.
"""

from __future__ import annotations

import pytest

from chuckchuck import _deck_lines as DL
from chuckchuck import _evidence as E
from chuckchuck import _graph_items as GI
from chuckchuck._claim_quote import slide_lines

# ===========================================================================
# 1. 목록 항목의 캡션 조각 — 어디에 있든
# ===========================================================================


@pytest.mark.parametrize("line,item", [
    ("- 대기 시간 몇 분 기다렸나", "대기 시간"),          # 물음 낱말부터 물음 끝까지가 캡션 — 항목 끝
    ("· 몇 번 불렀나 직원 응대", "직원 응대"),            # 캡션이 항목 **앞**에 붙었다
    ("2. 샤워실 청결 어땠나", "샤워실 청결"),             # 번호 목록
    ("- 탈의실 온도 얼마나", "탈의실 온도"),             # 물음 끝 없이 물음 낱말만
    ("- 강습 시간표 언제 바뀌었나", "강습 시간표"),
    ("| 세제 냄새 왜 남았나 | 12건 |", "세제 냄새"),       # 표 행은 첫 칸이 항목
    ("- 받았는가 수거 시간", "수거 시간"),               # 캡션 꼬리가 앞에 붙었다
])
def test_1_항목_글_어디에_붙은_캡션_조각도_뗀다(line, item):
    assert GI.clean_item(line) == item


@pytest.mark.parametrize("line", ["- 하루에 몇 번", "- 누가 가르쳤나", "- 얼마나 오래", "- 고객은 왜 떠났나", "- 평균 몇 분"])
def test_1_캡션뿐이거나_캡션_절의_머리만_남으면_항목이_아니다(line):
    assert GI.clean_item(line) == ""


@pytest.mark.parametrize("line", ["- 왜곡 보정", "- 몇몇 시설", "- 무엇보다 안전", "- 수질 관리", "- 샤워기 수압"])
def test_1_물음_낱말을_닮은_이름은_그대로_둔다(line):
    assert GI.clean_item(line) == line[2:]


def test_1_캡션_조각이_붙은_목록도_개수_말과_맞아_목록으로_읽힌다():
    raw = "\n".join(["회원이 떠나는 원인 세 가지", "- 대기 시간 몇 분 기다렸나", "- 샤워실 청결 어땠나", "- 몇 번 불렀나 직원 응대"])
    groups = GI.item_groups([(4, raw)])
    assert [(g.kind, g.items) for g in groups] == [("list", ["대기 시간", "샤워실 청결", "직원 응대"])]


def test_1_세탁소_표_목록도_첫_칸의_캡션을_뗀다():
    raw = "\n".join(["세탁소 불만 원인", "| 원인 | 건수 |", "| --- | --- |", "| 세제 냄새 왜 남았나 | 12 |",
                     "| 수거 시간 언제 왔나 | 9 |", "| 단추 파손 | 4 |"])
    groups = GI.item_groups([(2, raw)])
    assert groups and groups[0].items == ["세제 냄새", "수거 시간", "단추 파손"]


# ===========================================================================
# 2. 캡션 물음 뒤의 「× 항」 줄은 캡션이 아니라 식에 잇는다
# ===========================================================================

#: (덱, 파싱본 줄, 기대하는 식 줄)
FORMULAS = [
    ("캠핑장 재예약", ["캠핑장 재예약 = 사이트 청결", "몇 번 치웠는가", "× 화장실 거리"],
     "캠핑장 재예약 = 사이트 청결 × 화장실 거리"),
    # 캡션이 둘, 기호 줄이 둘
    ("빵집 단골", ["단골 정도 = 빵 맛", "무엇이 맛있었나", "얼마나 자주", "× 방문 빈도", "× 계산 속도"],
     "단골 정도 = 빵 맛 × 방문 빈도 × 계산 속도"),
    # 기호만 있는 줄이 캡션 뒤에 오고 항은 다음 줄
    ("반려식물 생장", ["생장 속도 = 햇빛 시간", "하루 몇 시간", "×", "물 주기"],
     "생장 속도 = 햇빛 시간 × 물 주기"),
    # 식이 이미 기호로 끝났으면 기호를 겹쳐 쓰지 않는다
    ("요가원 재등록", ["재등록 = 강사 설명 ×", "누가 가르쳤나", "× 수업 난이도"],
     "재등록 = 강사 설명 × 수업 난이도"),
    # 기호 줄에 붙은 캡션 조각은 걷는다
    ("세탁소 재방문", ["재방문 = 세탁 품질", "어땠나", "× 수거 시간 몇 분", "걸렸나"],
     "재방문 = 세탁 품질 × 수거 시간"),
]
IDS = [f[0] for f in FORMULAS]


@pytest.mark.parametrize("name,lines,want", FORMULAS, ids=IDS)
def test_2_캡션_뒤의_기호_줄은_앞의_식에_잇는다(name, lines, want):
    for got in (E.join_formula(lines), DL.join_formula_lines(lines)):
        assert want in got, got
        # 캡션 물음은 식에 붙지 않았다 — 제 줄로 남거나(물음 줄) 캡션 꼬리로 남는다
        assert not any(E.is_question_line(x) and "×" in x for x in got), got


@pytest.mark.parametrize("name,lines,want", FORMULAS, ids=IDS)
def test_2_질문_인용_주장_그래프가_같은_식을_읽는다(name, lines, want):
    raw = "이번 장의 식\n" + "\n".join(lines)
    assert want in slide_lines(raw)                                            # F-26
    assert want in GI.deck_lines(raw)                                          # F-07 후처리
    assert want in E.slide_units(raw)                                          # F-08 인용 후보 — 닫힌 식이라 인용이 된다
    terms = want.split("=")[1].replace(" ", "").split("×")
    groups = [g for g in GI.item_groups([(1, raw)]) if g.kind == "formula"]
    assert groups and [t.replace(" ", "") for t in groups[0].items] == terms   # 식의 항이 전부 노드 재료가 된다


def test_2_캡션_앞이_식이_아니면_그_줄을_건드리지_않는다():
    got = E.join_formula(["예약 안내", "몇 번 치웠는가", "× 화장실 거리"])
    assert got[0] == "예약 안내"


def test_2_캡션이_없으면_예전처럼_바로_앞_식에_잇는다():
    assert E.join_formula(["캠핑장 재예약 = 사이트 청결", "× 화장실 거리"]) == ["캠핑장 재예약 = 사이트 청결 × 화장실 거리"]
