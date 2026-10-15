"""
한국어 합성 발표 — 학습용(시험셋 덱과 주제·자료가 겹치지 않는다).

덱마다 Solar 로
  ① 발표 자료(장별 줄)   ② 그 자료를 충실히 말한 대본(장별 문장)   ③ 결함 판(모순 2 · 누락 2 · 건너뛰기 1 · 이름만 스침 1)
을 만들고, 제품과 같은 F-06/F-07(Solar, 다수결 1)로 개념 그래프를 뽑는다. ③ 은 Solar 가 「바꿀 문장과 새 문장」 만 내고
적용은 코드가 한다 — 무엇을 어떻게 바꿨는지가 기록으로 남아야 「구성으로 아는 라벨」 이 된다.

산출: DATA/ko_synth/<deck_id>/{deck,script,flaws,slide_doc,graph}.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random

from common import DATA, jdump, jload, llm, load_env, parse_json, pmap

OUT = DATA / "ko_synth"
GEN = "solar"

DOMAINS = [
    "도시 교통", "기후·에너지", "식품·영양", "공중보건", "초등 교육", "대학 교육", "청소년 심리", "노동·고용", "부동산·주거",
    "소비자 행동", "모바일 앱 서비스", "인공지능 응용", "반도체 공정", "이차전지", "수질·하천", "해양 생물", "농업 기술",
    "스포츠 과학", "문화·예술 경영", "지역 관광", "공공 행정", "복지 정책", "재무·투자", "스타트업 사업 모델", "제조 품질 관리",
    "물류·유통", "건축·구조", "재난 안전", "의료 기기", "약학 임상", "언어 학습", "역사 연구", "미디어·저널리즘", "게임 디자인",
    "사이버 보안", "데이터 분석 방법", "로봇 공학", "우주 항공", "반려동물", "패션·섬유",
]
SITUATIONS = [
    ("school_project", "같은 반 학생과 담임 선생님", "고등학생 모둠 과제 발표", (5, 8)),
    ("school_project", "교수와 수강생", "대학 전공 수업 팀 과제 발표", (6, 10)),
    ("lab_seminar", "지도교수와 연구실 구성원", "대학원 연구실 세미나", (5, 9)),
    ("conference", "학회 청중", "국내 학회 구두 발표", (7, 12)),
    ("business_report", "팀장과 유관 부서", "사내 분기 업무 보고", (5, 9)),
    ("pitch", "투자 심사역", "스타트업 투자 피칭", (6, 10)),
    ("policy_briefing", "구청 담당 공무원과 주민 대표", "정책 제안 설명회", (6, 10)),
    ("competition", "공모전 심사위원", "대학생 공모전 본선 발표", (6, 10)),
]
STYLES = ["해요체로 친근하게", "합니다체로 단정하게", "해요체와 합니다체를 섞어 자연스럽게", "조금 긴장해서 '음', '어' 같은 말이 가끔 섞이게"]

DECK_SYS = """당신은 한국어 발표 자료를 만드는 사람입니다. 주어진 조건에 맞는 실제 같은 발표 자료(슬라이드 글)를 만드세요.
요건:
- 첫 장은 제목·부제·발표자 이름·소속(가상의 한국 이름).
- 숫자가 든 줄이 여러 장에 걸쳐 8개 이상 — %, 명, 배, 원, 점, 시간, 단위가 있는 값. 표처럼 「항목 | 값 | 값」 줄도 한두 장.
- 비교·방향이 있는 문장(A가 B보다 높다, ~이후 줄었다, ~할수록 늘었다) 4개 이상.
- 용어 정의 한 줄, 방법·조건 목록(3~5칸) 한 장, 결과 한두 장, 한계 2~3개를 적은 장, 결론·제언 장.
- 마지막 장은 감사·참고문헌·문의처 중 하나.
- 장 제목은 내용에 맞게 자연스럽게 짓는다(「비교 및 방향」「한계·제한」처럼 이 요건 낱말을 그대로 제목으로 쓰지 않는다).
- 한 장에 3~7줄, 줄은 짧은 문장이나 구. 사실처럼 그럴듯하되 실제 통계를 흉내 낼 필요는 없다(가상의 조사·실험이라도 된다).
출력 JSON: {"title": "...", "slides": [{"title": "장 제목", "lines": ["줄", ...]}, ...]}"""

SCRIPT_SYS = """당신은 이 발표 자료로 실제 발표를 하는 발표자입니다. 장마다 입으로 하는 말을 적으세요.
요건:
- 자료의 내용 줄(주장·정의·조건·결과 수치·비교·한계·결론)은 빠짐없이, 자료와 같은 뜻·같은 수치로 말한다. 낱말은 자기 말로 바꿔도 된다.
- 숫자는 절반쯤 한국어로 읽듯이 적는다(40% → 사십 퍼센트, 1,450 → 천사백오십).
- 발표자 소속·날짜·쪽 번호·참고문헌 목록 같은 것은 말하지 않아도 된다. 실제 발표처럼 인사·연결 말(「다음은」「보시면」)을 넣는다.
- 장마다 2~8문장. 문장은 한 줄에 하나.
출력 JSON: {"slides": [{"slide_no": 1, "sentences": ["...", ...]}, ...]}"""

FLAW_SYS = """당신은 발표 연습 채점기를 시험하려고 일부러 결함을 심는 사람입니다. 아래 자료와 대본(문장마다 번호)을 보고 결함 5개를 만드세요.
- contradiction_number: 자료의 수치가 든 내용을 말한 문장 하나를 골라, 그 수치만 자료와 다른 값으로 바꾼 새 문장(나머지는 그대로).
- contradiction_flip: 비교·방향 문장 하나를 골라 방향을 반대로(늘었다↔줄었다, 높다↔낮다, A가 B보다↔B가 A보다, 효과가 있다↔없다) 바꾼 새 문장. 수치는 그대로 둔다.
- omission: 주장·조건·결과·한계처럼 꼭 말해야 할 자료 줄 하나를 설명한 문장(들)을 지운다. 대신 내용 없이 얼버무리는 문장 하나를 넣어도 된다(「조건은 다 맞췄습니다」).
- omission: 다른 장에서 또 하나.
- name_only: 자료의 핵심 개념 하나를 이름만 한 번 말하고 내용(수치·관계·조건)은 말하지 않게 그 설명 문장을 바꾼다.
다섯 결함은 서로 다른 문장을, 되도록 서로 다른 장을 건드린다. 제목 장·마지막 장은 고르지 않는다. deck_line 은 그 결함이 걸린 **자료 줄** 원문 그대로(대본 문장이 아니다).
출력 JSON: {"flaws": [{"type": "...", "slide_no": 3, "deck_line": "자료 줄 원문", "sids": ["s03-02"], "new_text": "바꾼 새 문장(지우기만 하면 빈 문자열)"}]}"""


def deck_id(i: int) -> str:
    return f"syn{i:03d}"


def spec(i: int, seed: int) -> dict:
    r = random.Random(seed * 1000 + i)
    sit, aud, what, (lo, hi) = SITUATIONS[i % len(SITUATIONS)]
    return {"domain": DOMAINS[(i * 7 + seed) % len(DOMAINS)], "situation": sit, "audience": aud, "what": what,
            "n_slides": r.randint(lo, hi), "style": r.choice(STYLES), "duration_min": r.choice([5, 7, 10, 15])}


def gen_deck(sp: dict, tag: str) -> dict:
    user = (f"주제 분야: {sp['domain']} — 이 분야 안에서 구체적인 주제 하나를 스스로 정하세요.\n"
            f"자리: {sp['what']} · 청중: {sp['audience']} · 장 수: {sp['n_slides']}장 · 발표 시간 약 {sp['duration_min']}분")
    d = parse_json(llm(GEN, DECK_SYS, user, temperature=0.9, max_tokens=4000, tag=tag))
    slides = [s for s in d.get("slides", []) if isinstance(s, dict) and s.get("lines")]
    if len(slides) < 4:
        raise ValueError("장이 너무 적다")
    return {"title": d.get("title", ""), "slides": [{"title": str(s.get("title", "")),
                                                     "lines": [str(x) for x in s["lines"] if str(x).strip()]}
                                                    for s in slides]}


def deck_text(deck: dict) -> str:
    return "\n\n".join(f"[슬라이드 {i}] {s['title']}\n" + "\n".join(s["lines"]) for i, s in enumerate(deck["slides"], 1))


def gen_script(deck: dict, sp: dict, tag: str) -> dict:
    user = f"말투: {sp['style']}\n자리: {sp['what']} · 청중: {sp['audience']}\n\n{deck_text(deck)}"
    d = parse_json(llm(GEN, SCRIPT_SYS, user, temperature=0.7, max_tokens=5000, tag=tag))
    by = {int(s.get("slide_no", 0)): [str(x).strip() for x in s.get("sentences", []) if str(x).strip()]
          for s in d.get("slides", []) if isinstance(s, dict)}
    n = len(deck["slides"])
    if sum(1 for k in range(1, n + 1) if by.get(k)) < n - 1:
        raise ValueError("대본에 빈 장이 많다")
    return {"slides": [{"slide_no": k, "sentences": by.get(k, [])} for k in range(1, n + 1)]}


def script_text(script: dict) -> str:
    out = []
    for s in script["slides"]:
        out.append(f"### 슬라이드 {s['slide_no']}")
        out += [f"s{s['slide_no']:02d}-{j:02d} {t}" for j, t in enumerate(s["sentences"], 1)]
    return "\n".join(out)


def gen_flaws(deck: dict, script: dict, tag: str) -> list[dict]:
    user = f"## 자료\n{deck_text(deck)}\n\n## 대본\n{script_text(script)}"
    d = parse_json(llm(GEN, FLAW_SYS, user, temperature=0.4, max_tokens=2500, tag=tag))
    valid = {f"s{s['slide_no']:02d}-{j:02d}" for s in script["slides"] for j in range(1, len(s["sentences"]) + 1)}
    out = []
    for f in d.get("flaws", []):
        if not isinstance(f, dict):
            continue
        sids = [x for x in (f.get("sids") or []) if x in valid]
        if f.get("type") != "skip" and not sids:
            continue
        out.append({"type": str(f.get("type", "")), "slide_no": int(f.get("slide_no", 0) or 0),
                    "deck_line": str(f.get("deck_line", "")), "sids": sids, "new_text": str(f.get("new_text", "") or "")})
    return out


def slide_doc(deck: dict, name: str) -> dict:
    from pipeline.contracts import Slide, SlideBlock, SlideDoc

    slides = []
    for i, s in enumerate(deck["slides"], 1):
        blocks = [SlideBlock("heading1", s["title"])] + [
            SlideBlock("table" if "|" in ln else "paragraph", ln) for ln in s["lines"]]
        raw = "\n".join(s["lines"])
        slides.append(Slide(slide_no=i, title=s["title"], blocks=blocks, categories=sorted({b.category for b in blocks}),
                            total_char_count=len(raw), line_count=len(s["lines"]), has_visual=False,
                            text_sparse=len(raw) < 20, image_only=False))
    return SlideDoc(file_name=f"{name}.pptx", total_slides=len(slides), slides=slides).to_dict()


def build_one(i: int, seed: int) -> str:
    did = deck_id(i)
    d = OUT / did
    if (d / "graph.json").exists():
        return f"{did} cached"
    sp = spec(i, seed)
    tag = f"{seed}:{i}"
    deck = jload(d / "deck.json") or gen_deck(sp, tag)
    jdump(d / "deck.json", {**deck, "spec": sp})
    script = jload(d / "script.json") or gen_script(deck, sp, tag)
    jdump(d / "script.json", script)
    flaws = jload(d / "flaws.json") or gen_flaws(deck, script, tag)
    jdump(d / "flaws.json", flaws)
    sd = slide_doc(deck, did)
    jdump(d / "slide_doc.json", sd)

    from pipeline.contracts import Context, SlideDoc
    from pipeline.f06_concepts import extract_concepts
    from pipeline.f07_graph import build_graph

    ctx = Context(situation=sp["situation"], audience=sp["audience"], duration_min=sp["duration_min"])
    doc = SlideDoc.from_dict(sd)
    concepts = extract_concepts(doc, ctx, llm="solar", votes=1)
    graph = build_graph(concepts, ctx, slide_doc=doc, llm="solar")
    jdump(d / "graph.json", graph.to_dict())
    return f"{did} slides={len(deck['slides'])} nodes={len(graph.nodes)} flaws={len(flaws)}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--seed", type=int, default=16)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    load_env()
    import os
    os.environ["CHUCKCHUCK_CONCEPT_MAX_WORKERS"] = "2"
    ids = list(range(args.start, args.start + args.n))
    res = pmap(lambda i: build_one(i, args.seed), ids, workers=args.workers, desc="synth", every=5)
    for i, r in zip(ids, res):
        print(deck_id(i), r if not isinstance(r, Exception) else f"FAIL {type(r).__name__}: {str(r)[:160]}")


if __name__ == "__main__":
    main()
