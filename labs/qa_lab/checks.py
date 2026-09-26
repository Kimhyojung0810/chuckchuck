"""
QA 실험대의 **순수 검사** — 질문(Question dict)·판정(QaJudgement dict)·묶음(bundle)을 받아 표식을 돌려준다.

LLM 도 파일도 안 만진다. `tests/test_qa_lab.py` 가 이 함수들을 고정한다.
검사 문구는 f08_questions / f09_judge 의 코드 문구를 그대로 대조한다 — 여기서 어긋나면 그쪽이 바뀐 것이다.
"""

from __future__ import annotations

import re

#: CLAUDE.md §3-1 이 금지한 높임. examples/qa_eval.py 의 식에 f08 `_HONORIFIC_RULES` 가 고치는 문장 가운데 높임(하신·하실·말씀)을 더했다.
HONORIFIC_RE = re.compile(r"[가-힣]*(셨|시겠|십니|십시오|시나요|시는지|계시|여쭈|하시는|하신|되신|하실|주실|주신|주시는|말씀)|(?<=[가-힣])(?<![함저제])께(?!서)\s")
#: 합쇼체 어미. 해요체 규칙(§3-1) 위반. 어절 끝에서만 본다 ("입니다만" 같은 꼴은 안 잡아도 된다).
HAPSYO_RE = re.compile(r"(습니다|습니까|입니다|입니까)(?=[\s.,!?»」)'\"]|$)")
#: 질문이 해요체 물음으로 끝나는가 (f08 `_POLITE_END_RE` 와 같은 식).
POLITE_END_RE = re.compile(r"(요|죠|세요|나요|가요|래요|습니까)\s*[?.!]?\s*$")
#: 자료 인용 «…» · 「…」 — 자료 원문은 합쇼체여도 우리 잘못이 아니라 빼고 본다.
QUOTE_SPAN_RE = re.compile(r"«[^»]*»|「[^」]*」")
#: 코드가 조립한 폴백 질문의 흔적 (f08 `_fallback_text`).
FALLBACK_QUESTION_RE = re.compile(r"— 설명해 주세요\.$|이 개념의 핵심과 자료에 넣은 근거를 설명해 주세요\.$")
#: 「발표자가 인용했다」 는 표현 (f08 `_PRESENTER_CITED_RE` 와 같은 식).
PRESENTER_CITED_RE = re.compile(r"인용(?:했|하셨|하신|하였|한|하고|되었|됐|된)")
#: 「저자 (연도)」 인용 표시.
CITE_RE = re.compile(r"[A-Z][A-Za-z'\-]+(?:\s+et\s+al\.)?\s*\(\d{4}[a-z]?\)")
#: f09 가드가 등급을 뒤집었을 때 쓰는 고정 문구 (f09 `_OFF_TOPIC_REACT` · `_TRAP_AGREED_REACT`).
OFF_TOPIC_LEAD = "질문과 다른 이야기예요."
TRAP_AGREED_LEAD = "질문의 전제부터 확인해 보세요"
#: 코드 폴백 반응 (f09 `_REACT_BY_VERDICT`). 이게 나오면 LLM 의 react 가 비었거나 높임이라 버려진 것.
FALLBACK_REACTS = frozenset({
    "네, 그 설명이면 충분합니다.",
    "요지는 잡았어요. 한 가지만 더 짚어 주세요.",
    "그 부분은 자료와 맞지 않습니다.",
    "지금 답변만으로는 판단하기 어렵습니다.",
})
#: 실 API 가 아닌 제공자 이름.
MOCK_MODELS = frozenset({"", "mock", "mock-llm", "heuristic"})
#: fixtures/sample_slidedoc.json 의 흔적 — 이게 자료로 나오면 mock 이 바꿔치기한 것이다 (CLAUDE.md §2).
SAMPLE_DECK_MARKERS = ("IMU2CLIP", "sample_slidedoc", "sample-investor", "개인투자자 수익률 격차")


def _strip_quotes(text: str) -> str:
    return QUOTE_SPAN_RE.sub("", text or "")


def honorifics(*texts: str) -> int:
    return sum(len(HONORIFIC_RE.findall(_strip_quotes(t))) for t in texts)


def hapsyo(*texts: str) -> int:
    return sum(len(HAPSYO_RE.findall(_strip_quotes(t))) for t in texts)


def is_clipped(text: str) -> bool:
    """f08 `_clip` 이 잘랐으면 끝이 '…' 다. 질문이면 물음이 통째로 사라진 것이다."""
    return (text or "").rstrip().endswith("…")


def node_id_leaked(question: str, node_id: str, label: str) -> bool:
    """질문 문장에 라벨 대신 노드 id(영문 슬러그)가 그대로 나왔는가 — "concept-graph가 …" (09-26 실측)."""
    nid = (node_id or "").strip()
    if not nid or nid == (label or "").strip() or len(nid) < 4:
        return False
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", nid):
        return False
    return nid.lower() in (question or "").lower()


#: 골자·질문 속 숫자 (70~80% · 15% · 3회 · 2024년). 자료에 없는 숫자는 LLM 이 지어낸 것이다.
#: 낱말에 붙은 숫자(개념1 · q01 · B2C)는 이름이라 세지 않는다 — 앞이 글자·숫자가 아닐 때만.
NUMBER_RE = re.compile(r"(?<![가-힣A-Za-z0-9])\d+(?:[.,]\d+)?\s*(?:%|퍼센트|회|배|명|건|초|분|시간|일|주|개월|년|원|달러|점|장)?")
#: 인용 표기 「Boyle et al. (2022)」 의 연도는 문헌 것이라 자료에 없어도 된다.
CITE_YEAR_RE = re.compile(r"\((\d{4})[a-z]?\)")


def numbers_not_in_deck(text: str, deck_texts: list[str]) -> list[str]:
    """text 의 숫자 토큰 중 자료 글 어디에도 없는 것. 인용 연도는 뺀다. deck_texts 가 비면 판단하지 않는다(빈 목록)."""
    if not deck_texts:
        return []
    body = CITE_YEAR_RE.sub("", text or "")
    hay = re.sub(r"\s+", "", " ".join(deck_texts))
    out: list[str] = []
    for m in NUMBER_RE.finditer(body):
        tok = re.sub(r"\s+", "", m.group(0))
        digits = re.match(r"\d+(?:[.,]\d+)?", tok).group(0)
        # 단위 없는 한 자리 수("3")는 어디에나 있어 판단 재료가 못 된다.
        if len(digits) < 2 and digits == tok:
            continue
        if digits not in hay and tok not in out:
            out.append(tok)
    return out


def question_flags(q: dict, papers: dict | None = None, deck_texts: list[str] | None = None) -> list[str]:
    """질문 하나의 표식. 빈 목록이면 걸린 것이 없다. `!` 가 붙은 것은 화면에 그대로 나가면 안 되는 것.
    deck_texts(자료 글)를 주면 골자·질문에 자료에 없는 숫자가 있는지도 본다."""
    text = str(q.get("question", "") or "")
    flags: list[str] = []
    if q.get("trap"):
        flags.append("함정")
    if q.get("paper_ids"):
        flags.append(f"인용{len(q['paper_ids'])}")
    if is_clipped(text):
        flags.append("잘림!")
    elif text and not POLITE_END_RE.search(text):
        flags.append("반말끝!")
    if FALLBACK_QUESTION_RE.search(text):
        flags.append("폴백")
    n = honorifics(text, q.get("why", ""), q.get("hint", ""), q.get("answer_gist", ""))
    if n:
        flags.append(f"높임{n}!")
    # 골자(answer_gist)는 포기했을 때 「정답 요지」 로 화면에 나가므로 같이 본다.
    n = hapsyo(text, q.get("why", ""), q.get("hint", ""), q.get("answer_gist", ""))
    if n:
        flags.append(f"합쇼체{n}")
    if node_id_leaked(text, q.get("node_id", ""), q.get("label", "")):
        flags.append("노드id노출")
    if PRESENTER_CITED_RE.search(text) and CITE_RE.search(text) and not _deck_refs(papers):
        flags.append("인용주장!")
    if not q.get("evidence_quote"):
        flags.append("인용문없음")
    made_up = numbers_not_in_deck(" ".join([text, str(q.get("answer_gist", "") or "")]), deck_texts or [])
    if made_up:
        flags.append("자료밖숫자!" + "·".join(made_up[:3]))
    return flags


def _deck_refs(papers: dict | None) -> list[dict]:
    if not papers:
        return []
    return [r for r in (papers.get("refs") or []) if r.get("kind") == "deck"]


def judgement_flags(j: dict) -> list[str]:
    """판정 하나의 표식. 가드가 등급을 뒤집었는지, 말투가 새는지, 폴백 문구인지."""
    react = str(j.get("react", "") or "")
    flags: list[str] = []
    if react.startswith(OFF_TOPIC_LEAD):
        flags.append("가드:무관")
    if react.startswith(TRAP_AGREED_LEAD):
        flags.append("가드:함정동의")
    if react in FALLBACK_REACTS:
        flags.append("react폴백")
    if j.get("coach_stage"):
        flags.append(f"코칭:{j['coach_stage']}")
    texts = [react, str(j.get("summary_sentence", "") or ""), str(j.get("followup", "") or ""),
             str(j.get("explanation", "") or ""), *[str(h) for h in (j.get("hints") or [])]]
    n = honorifics(*texts)
    if n:
        flags.append(f"높임{n}!")
    n = hapsyo(*texts)
    if n:
        flags.append(f"합쇼체{n}")
    if is_clipped(str(j.get("followup", "") or "")):
        flags.append("되묻기잘림!")
    return flags


def slide_texts(slide_doc: dict | None) -> list[str]:
    """SlideDoc dict 의 글을 전부 모은다 (제목·블록의 문자열 값). 근거 인용이 자료에 실제로 있는지 대조할 원본."""
    out: list[str] = []
    for s in (slide_doc or {}).get("slides") or []:
        if s.get("title"):
            out.append(str(s["title"]))
        for b in s.get("blocks") or []:
            if isinstance(b, dict):
                out.extend(str(v) for v in b.values() if isinstance(v, str))
            elif isinstance(b, str):
                out.append(b)
    return out


def quote_in_deck(quote: str, texts: list[str]) -> bool:
    """인용문이 자료 글에 있는가. 공백을 무시하고 앞 24자만 맞춰 본다 (f08 이 문장을 정리해 옮긴다)."""
    key = re.sub(r"\s+", "", quote or "")[:24]
    if len(key) < 6:
        return False
    hay = re.sub(r"\s+", "", " ".join(texts))
    return key in hay


def real_value_checks(bundle: dict) -> list[tuple[str, str, str]]:
    """
    「데모값이 아니라 실제값인가」 — (등급, 항목, 설명) 목록. 등급은 PASS · WARN · FAIL.

    bundle 키: slide_doc · graph · question_doc · papers · judgements(list) · meta(dict).
    """
    rows: list[tuple[str, str, str]] = []
    sd = bundle.get("slide_doc") or {}
    doc = bundle.get("question_doc") or {}
    papers = bundle.get("papers")
    meta = bundle.get("meta") or {}

    fname = str(sd.get("file_name", "") or "")
    texts = slide_texts(sd)
    joined = " ".join([fname, *texts])
    hit = next((m for m in SAMPLE_DECK_MARKERS if m in joined), None)
    if hit:
        rows.append(("FAIL", "자료", f"샘플 자료 흔적 「{hit}」 — mock 이 바꿔치기한 자료다"))
    elif not texts:
        rows.append(("FAIL", "자료", "슬라이드 글이 하나도 없다"))
    else:
        rows.append(("PASS", "자료", f"{fname or '(이름 없음)'} · {len(sd.get('slides') or [])}장 · 글 {sum(len(t) for t in texts)}자"))

    if meta.get("source"):
        rows.append(("PASS" if meta["source"] != "fixture" else "FAIL", "출처", f"{meta['source']}"))

    for kind, model in (meta.get("models") or {}).items():
        if str(model).lower() in MOCK_MODELS:
            rows.append(("FAIL", f"모델:{kind}", f"'{model}' — 실 LLM 이 아니다"))
    qmodel = str(doc.get("model", "") or "")
    if doc:
        rows.append(("FAIL" if qmodel.lower() in MOCK_MODELS else "PASS", "모델:F-08", qmodel or "(없음)"))

    qs = doc.get("questions") or []
    if doc:
        grounded = sum(1 for q in qs if quote_in_deck(q.get("evidence_quote", ""), texts))
        fb = sum(1 for q in qs if FALLBACK_QUESTION_RE.search(str(q.get("question", "") or "")))
        rows.append(("PASS" if grounded else "FAIL", "질문 근거",
                     f"인용문이 자료에 실제로 있는 질문 {grounded}/{len(qs)}"))
        rows.append(("PASS" if fb < len(qs) else "FAIL", "질문 폴백",
                     f"코드 조립 폴백 {fb}/{len(qs)}" + (" — 전부 폴백이면 LLM 이 지시를 못 따른 것" if fb and fb >= len(qs) else "")))

    if papers is not None:
        prov = str(papers.get("provider", "") or "")
        n = len(papers.get("refs") or [])
        grade = "PASS" if prov and prov != "none" else "WARN"
        rows.append((grade, "문헌 F-24", f"provider={prov or '(없음)'} · {n}편" + (f" · {papers.get('note')}" if papers.get("note") else "")))

    for j in bundle.get("judgements") or []:
        m = str(j.get("model", "") or "")
        if m.lower() in MOCK_MODELS:
            rows.append(("FAIL", "모델:F-09", f"'{m}' — 실 LLM 이 아니다"))
            break
    else:
        if bundle.get("judgements"):
            rows.append(("PASS", "모델:F-09", str(bundle["judgements"][0].get("model", ""))))
    return rows


#: `judge --probe` 의 정답 표 — 어떤 답을 넣으면 어떤 판정이 나와야 하는가 (examples/qa_eval.py 판정 일관성과 같은 넷).
PROBE_UNRELATED = (
    "저희 팀은 지난 분기에 물류 창고 세 곳의 재고 회전율을 비교했고, "
    "동절기 배송 지연이 반품률을 끌어올린다는 결론을 얻었어요."
)
PROBE_AGREE = "네, 맞아요. 질문하신 대로예요. 그 전제가 정확해요."


def probe_plan(q: dict) -> list[tuple[str, str, str]]:
    """질문 하나에 넣어 볼 답 (이름, 답, 기대). 기대는 pass · wrong · coach 중 하나."""
    plan = [
        ("골자그대로", str(q.get("answer_gist", "") or ""), "pass"),
        ("무관한답", PROBE_UNRELATED, "wrong"),
        ("포기", "모르겠어요", "coach"),
    ]
    if q.get("trap"):
        plan.insert(1, ("함정동의", PROBE_AGREE, "wrong"))
    return [p for p in plan if p[1]]


def probe_outcome(j: dict) -> str:
    """판정 dict → pass · wrong · coach · partial. `probe_plan` 의 기대와 대조한다."""
    if j.get("coach_stage"):
        return "coach"
    v = str(j.get("verdict", "") or "")
    try:
        score = int(j.get("score", 0) or 0)
    except (TypeError, ValueError):
        score = 0
    if v == "good" or score >= 70:
        return "pass"
    if v == "wrong":
        return "wrong"
    return "partial"
