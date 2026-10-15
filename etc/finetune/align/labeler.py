"""
큰 한국 LLM(Solar · A.X) 라벨러 — 판정기와 **같은 항목 그림(render_user)** 을 보고 판정한다.

파일럿 B v1 규칙(Fine-Tune/alignment-pilot/prompt_B_v1.md)을 한국어 발표·F-11 규칙(건너뛴 말·숫자·방향)에 맞춰 옮겼다.
partial·asr_suspect 같은 보조 속성은 4클래스로 접어 넣는다(파일럿 결론: aligned 로 둔다).
"""

from __future__ import annotations

from common import llm, parse_json

from pipeline._align_lora import evidence_valid, item_sentences, render_user

LABELS = ("aligned", "justified_skip", "missing", "contradiction")

SYSTEM = """당신은 발표 슬라이드와 실제 발화가 맞는지 판정하는 라벨러입니다.
개념 하나에 대해, 발표자가 그 개념을 발화에서 어떻게 다뤘는지 판정하세요. 입력은 한국어나 영어입니다. note 는 한국어로 쓰세요.

# 라벨
- aligned: 발화가 개념의 핵심 뜻을 전달했고 자료와 맞다. 낱말이 달라도 뜻이 같으면 aligned. 앞 장·뒤 장 발화에서 전달했어도 aligned.
  이름은 말했고 매달린 숫자 일부를 안 말했어도 aligned. 받아쓰기로 고유명사·숫자 글자만 깨졌고 뜻이 들리면 aligned.
  예시 번호(「예시 59a」)만 안 말하고 식·절차를 말했으면 aligned.
- contradiction: 발화가 자료와 양립할 수 없다 — 수치(자릿수·값)·단위가 다름, 늘었다/줄었다·높다/낮다·빠르다/느리다가 반대,
  효과가 있다/없다·맞다/아니다가 반대, 비교한 두 쪽(A가 B보다)이 뒤바뀜, 조건·주체가 바뀜. 받아쓰기로 글자만 깨진 것은 아니다.
  「천사백오십」=「1,450」, 「사십 퍼센트」=「40%」 처럼 읽는 법만 다르면 같은 값이다.
- missing: 발화(이 장과 앞뒤 장)에 없고, 빠지면 청중이 발표를 따라가거나 목적을 이루기 어렵다.
  종류가 핵심 주장·주장이고 인사·안내가 아니면 말이 없을 때 missing. 뒤 내용을 이해하는 정의·결과·조건·한계인데 말이 없으면 missing.
  「넘어갈게요·건너뛸게요·생략할게요·시간 관계상·나중에 설명할게요」처럼 넘기거나 미룬 말은 설명이 아니다 — 다른 곳에서 설명하지 않았으면 missing.
  이름만 한 번 스치고 내용(숫자·관계·조건)을 하나도 말하지 않았으면 missing.
- justified_skip: 발화에 없지만 빼도 이해에 지장이 없다 — 저자·발표자 이름·소속·감사·로고·인사·날짜·쪽 번호, 도표 눈금·막대 이름·범례,
  절차 그림의 재료 이름, 같은 목록에서 다른 칸을 말했고 이 칸은 주장이 아닌 경우. 중요도(weight)가 높아도 이런 종류면 justified_skip.

# 절차
1. 개념의 핵심 뜻을 한 문장으로 정합니다.
2. [발화 — 이 개념의 장] 에서 그 뜻을 다룬 문장을 찾습니다. 없으면 [앞 장 발화]·[뒤 장 발화] 만 봅니다.
3. 다룬 문장이 있으면 자료와 견줍니다. 뜻이 같으면 aligned, 양립할 수 없으면 contradiction.
4. 다룬 문장이 없으면 missing 또는 justified_skip.
5. 정말 넷 중 하나를 고를 수 없을 때만 unsure.

# 출력 — JSON 객체 하나
{"label": "aligned | justified_skip | missing | contradiction | unsure",
 "sid": "근거 문장 번호(예: s03-02) 또는 null",
 "note": "판정 이유 한 줄(한국어, 60자 안)",
 "confidence": "high | medium | low"}
aligned·contradiction 은 sid 가 필수입니다(가장 직접적인 한 문장). missing·justified_skip·unsure 는 sid null."""


def label_item(engine: str, item: dict, tag: str = "") -> dict:
    """한 번 판정. 돌려주는 것: {label, sid, evidence, note, confidence, valid}."""
    raw = llm(engine, SYSTEM, render_user(item), temperature=0.0, max_tokens=500, tag=tag)
    d = parse_json(raw)
    label = str(d.get("label", "") or "").strip()
    sid = d.get("sid") or None
    sents = item_sentences(item)
    ev = sents.get(str(sid), "") if sid else ""
    return {
        "label": label if label in LABELS else ("unsure" if label == "unsure" else ""),
        "sid": str(sid) if sid and str(sid) in sents else None,
        "evidence": ev,
        "note": str(d.get("note", "") or "").strip()[:120],
        "confidence": str(d.get("confidence", "") or ""),
        "valid": label not in ("aligned", "contradiction") or evidence_valid(item, str(sid) if sid else None, ev),
    }
