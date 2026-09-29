"""
탐침 질문(단정의 경계 · 근거 없는 인과 · 긴장 · 형제 우선순위)에 대한 답을 판정(F-09)이 **거꾸로 채점하지 않게** 하는
결정적 헬퍼입니다. LLM 을 부르지 않습니다. `_deck_claims`·`_traps` 와 같은 자리의 유틸이라 F-09 가 import 해도
정책 위반이 아닙니다 (DEV_POLICY §4-1).

왜 따로 두나 (2026-09-29 P5 최종 평가, docs/review/2026-09-29_QA_근거검증/final_report.md §남은 문제 1):
- 5d1fbf5 이후 판정은 **자료 본문을 정답의 원본**으로 쓴다. 그런데 탐침 질문은 자료 줄 **자체를 따져 보라는** 질문이다 —
  「완전히 막을 수 있다고 했는데, 들어맞지 않는 경우는?」 의 모범답은 그 줄을 부정한다.
- 그래서 단정을 반박한 골자는 「자료와 방향이 거꾸로」 partial 60, 단정에 동의한 오답은 good 85 를 받았다(health).
  근거 없는 인과 질문도 같았다: 「수치·출처가 제시되지 않았다」 가 60, 「수치와 출처가 명확」 오답이 75 통과(hum).
- 고친 것: ① 탐침 근거 줄은 판정의 대조 원본에서 뺀다(`probed_quotes` → `_deck_claims.without_lines`),
  ② 그 줄을 **되풀이하거나 그대로 받아들이기만 한** 답은 통과시키지 않는다(`restates_probe`),
  ③ 판정 프롬프트에 이 질문이 무엇을 따지는지 적는다(`probe_brief`).

**규칙은 구조로만 짠다** — 단정 표지(`_claim_rules.absolute_marker`), 부정·예외·조건 표지, 수치·출처 낱말, 자료 줄과의
낱말 겹침. 특정 발표의 낱말을 넣지 않는다: 부스에서는 처음 보는 자료가 들어온다. 놓치는 쪽이 안전하다 — 애매하면
LLM 판정에 맡긴다(여기서 잘못 잡으면 맞게 답한 사람이 진다).
"""

from __future__ import annotations

import re

from . import _claim_rules as R
from ._deck_claims import _has, content_stems, direction, numbers

#: 자료 줄 자체를 따져 묻는 탐침 — 이 종류의 근거 줄은 채점 원본이 아니다.
PROBED_LINE_KINDS = frozenset({"absolute_boundary", "unsupported_cause", "tension", "sibling_priority"})

#: 답이 자료 줄을 「되풀이」 했다고 볼 겹침 — 그 줄 낱말(방향 낱말 빼고)의 60% 이상 · 둘 이상.
RESTATE_RATIO = 0.6
RESTATE_MIN = 2
#: 질문·탐침 줄에 없는 새 낱말이 이만큼 있으면 「되풀이만」 이 아니다 (근거 없는 인과·긴장).
NOVEL_MIN = 2

#: 단정의 경계를 말하는 표지 — 부정·예외·조건·한정·유보. 어느 발표에나 쓰는 한국어 문법 낱말만 둔다.
_BOUNDARY_RE = re.compile(
    r"경우|예외|때는|때에는|때엔|조건|한계|다만|하지만|그러나|반면|아니|않|없|못|어렵|힘들|수도\s|따라(?!서)|마다|달라|다를|다르|"
    r"차이|만으로는|제외|일부|대부분|보장|과장|지나치|틀리|틀렸|틀린|무리|단정"
)
#: 근거를 댄다고 볼 표지 — 출처·측정 낱말.
_SOURCE_RE = re.compile(r"연구|조사|통계|설문|실험|측정|데이터|보고서|논문|문헌|기록|사례|응답|표본|비교군|대조군")
#: 근거가 비었음을 인정하거나 보강을 말하는 표지. 「없이」 는 인정이 아니다 — 「추가 근거 없이도 충분히 입증」 (loop2 실측).
_GAP_RE = re.compile(r"없(?!이)|않|못|부족|필요|보완|보강|검증|확인|한계|어렵|아직|약하|약해|빈약|모자라")
#: 근거를 대지 않고 **입증됐다고 못 박는** 말 — 출처 낱말(「여러 문헌」)을 곁들여도 수치·인정이 없으면 근거를 댄 것이 아니다.
_PROOF_CLAIM_RE = re.compile(r"명확|분명|충분히|확실|입증|증명|이미\s*[^.]{0,20}사실")
#: 답의 새 낱말로 세지 않는 말 — 「자료에 그렇게 나와 있어요」 의 뼈대. 어느 발표에나 쓰는 말.
_FILLER = ("그렇", "이렇", "저렇", "나와", "나온", "나옵", "적혀", "적힌", "말해", "말했", "했어", "해요", "있어", "없어",
           "돼요", "되어", "보면", "봐요", "거예", "것이")
#: 「근거가 있다·명확하다」 고 **주장만** 하는 말.
#: 「그 줄이 곧 근거 원문이에요」「…라고 기재되어 있어요」 — 인과 줄 자체를 근거로 드는 말도 같다 (loop2 dry-run 골자).
_SUPPORT_CLAIM_RE = re.compile(
    r"명확|분명|충분|확실|입증|증명|뒷받침|제시되어|제시돼|나와\s*있|나타나\s*있|밝혀져|확인되|근거\s*원문|기재되어|명시되어|적혀\s*있")
#: 두 말을 잇는 표지 — 긴장 질문에 「어떻게 함께 성립하는가」 를 말한 답.
_RECONCILE_RE = re.compile(r"동시에|함께|이면서|지만|반면|뜻|의미|구분|차이|측면|관점|수준|범위|아니라|대신|전제|조건")


def probe_of(question):
    """질문이 탐침에서 나왔으면 그 Probe, 아니면 None."""
    basis = getattr(question, "basis", None)
    return getattr(basis, "probe", None) if basis is not None else None


def probed_quotes(question) -> list[str]:
    """이 질문이 **따져 묻는** 자료 줄 (탐침 근거 인용). 그런 탐침이 아니면 빈 목록."""
    probe = probe_of(question)
    if probe is None or probe.kind not in PROBED_LINE_KINDS:
        return []
    return [e.quote for e in probe.evidence if (e.quote or "").strip()]


def _short(quote: str, limit: int = 60) -> str:
    q = " ".join((quote or "").split()).rstrip(" .")
    return q if len(q) <= limit else q[: limit - 1].rstrip() + "…"


def probe_brief(question) -> str:
    """
    판정 프롬프트에 붙일 「이 질문이 따지는 것」 블록. 탐침 질문이 아니면 "".
    자료 본문에 그 줄이 그대로 실려 있어서, 말하지 않으면 LLM 은 그 줄을 정답으로 읽는다 (09-29 P5: 단정에 동의한 답 good 85).
    """
    quotes = probed_quotes(question)
    if not quotes:
        return ""
    probe = probe_of(question)
    first = _short(quotes[0])
    if probe.kind == "absolute_boundary":
        body = (f"이 질문은 자료의 단정 「{first}」의 예외·경계를 묻는다 — 단정을 되풀이하거나 그대로 받아들이는 답은 답이 아니다"
                " (통과 아님). 그 말이 들어맞지 않는 경우·조건·한계를 든 답이 정답 쪽이다.")
    elif probe.kind == "unsupported_cause":
        body = (f"이 질문은 자료의 인과 「{first}」를 받치는 근거(수치·출처·사례)를 묻는다 — 자료의 그 줄에는 근거가 없다."
                " 인과를 되풀이하거나 「근거가 명확하다」 고만 하는 답은 답이 아니다 (통과 아님). 근거를 대거나,"
                " 자료에 근거가 없음을 인정하고 어떻게 보강할지 말한 답이 정답 쪽이다.")
    elif probe.kind == "tension":
        pair = " / ".join(f"「{_short(q, 40)}」" for q in quotes[:2])
        body = (f"이 질문은 자료의 두 말 {pair}이 어떻게 함께 성립하는지 묻는다 — 한쪽을 되풀이하기만 하는 답은 답이 아니다"
                " (통과 아님). 두 말을 잇는 뜻(범위·조건·수준의 차이 등)을 말한 답이 정답 쪽이다.")
    else:
        body = (f"이 질문은 「{first}」의 요소 사이 우선순위를 묻는다. 자료가 우선순위를 정하지 않았으면"
                " 「둘 다 필요하다」 와 그 이유도 정답이다.")
    return ("\n\n## 이 질문이 따지는 자료 줄 (채점 기준이 아니라 따져 묻는 대상 — 발표자에게는 보이지 않는다)\n"
            + body + "\n자료 본문에 이 줄이 있어도 그 줄과 **반대로** 말한 답을 「자료와 어긋난다」 고 깎지 마라.")


def _stems(text: str) -> list[str]:
    return [s for s in content_stems(text) if not direction(s)]


def _restates(clause_stems: list[str], quote: str) -> bool:
    line = {s for s in _stems(quote)}
    if len(line) < RESTATE_MIN:
        return False
    hit = sum(1 for s in line if _has(clause_stems, s))
    return hit >= RESTATE_MIN and hit >= RESTATE_RATIO * len(line)


def _near(a: str, b: str) -> bool:
    """두 줄기가 같은 낱말인가 — 앞 두 글자가 같으면(「중요한」·「중요해요」 · 「만족」·「만족도」) 같다고 본다."""
    return len(a) >= 2 and len(b) >= 2 and a[:2] == b[:2]


def _clauses(text: str) -> list[str]:
    from ._deck_claims import clauses
    return clauses(text) or [text]


def _novel(answer: str, question_text: str, quotes: list[str]) -> list[str]:
    """질문·탐침 줄에 없는 답의 낱말 — 되풀이 말고 무엇을 **보탰는가**."""
    known = content_stems(" ".join([question_text, *quotes]))
    return [s for s in dict.fromkeys(content_stems(answer)) if not _has(known, s) and not s.startswith(_FILLER)]


def _new_number(answer: str, question_text: str, quotes: list[str]) -> bool:
    known = numbers(" ".join([question_text, *quotes]))
    return any(not any(n.same_value(k) for k in known) for n in numbers(answer))


def restates_probe(answer: str, question) -> str:
    """Question 을 받는 판정용 입구 — 탐침·질문 문장을 꺼내 `restates_line` 에 넘긴다."""
    probe = probe_of(question)
    if probe is None:
        return ""
    return restates_line(answer, probe, getattr(question, "question", "") or "")


def restates_line(answer: str, probe, q_text: str = "") -> str:
    """
    답이 탐침이 따지는 자료 줄을 **되풀이하거나 그대로 받아들이기만** 했는가 — 그렇다면 탐침 종류, 아니면 "".

    - 단정의 경계: 단정 줄을 거의 그대로 말하면서 단정 표지를 부정하지 않았고(`absolute_marker`), 경계·예외·조건 표지가 없다.
    - 근거 없는 인과: 근거를 댄 흔적(새 숫자·출처 낱말)도, 근거가 비었다는 인정도 없이 ① 인과 줄을 되풀이만 했거나
      (새 낱말 NOVEL_MIN 미만) ② 「근거가 명확하다·제시되어 있다」 고 주장만 했다.
    - 긴장: 두 줄 중 하나만 되풀이하고, 다른 줄의 낱말도 잇는 표지도 새 낱말도 없다.
    - 형제 우선순위는 보지 않는다(「둘 다 필요」 도 정답이라 되풀이와 가르기 어렵다 — 대조 원본에서 빼는 것만 한다).
    """
    if probe is None or probe.kind not in PROBED_LINE_KINDS:
        return ""
    quotes = [e.quote for e in probe.evidence if (e.quote or "").strip()]
    text = (answer or "").strip()
    if not quotes or not text:
        return ""
    kind = probe.kind
    pieces = [(c, _stems(c)) for c in _clauses(text)]
    if kind == "absolute_boundary":
        if _BOUNDARY_RE.search(text):
            return ""
        for clause, stems in pieces:
            if any(_restates(stems, q) for q in quotes) and R.absolute_marker(clause):
                return kind
        return ""
    if kind == "unsupported_cause":
        if _new_number(text, q_text, quotes) or _GAP_RE.search(text):
            return ""
        if _PROOF_CLAIM_RE.search(text):
            return kind          # 수치도 인정도 없이 「입증됐다·명확하다」 — 근거를 댄 것이 아니라 주장한 것이다
        if _SOURCE_RE.search(text):
            return ""
        said = _stems(text)
        if any(_restates(said, q) for q in quotes) and len(_novel(text, q_text, quotes)) < NOVEL_MIN:
            return kind
        return kind if _SUPPORT_CLAIM_RE.search(text) else ""
    if kind == "tension" and len(quotes) >= 2:
        if _RECONCILE_RE.search(text) or len(_novel(text, q_text, quotes)) >= NOVEL_MIN:
            return ""
        said = _stems(text)
        if not any(_restates(said, q) for q in quotes):
            return ""
        # 두 줄은 같은 개념 이름을 나눠 가져서 「한쪽만」 을 겹침으로는 못 가른다 — 각 줄에만 있는 낱말을 본다.
        # 한 줄의 고유 낱말을 하나도 안 말했으면 그 줄(= 부딪히는 다른 쪽)을 빼놓고 한쪽만 되풀이한 것이다.
        for i, q in enumerate(quotes[:2]):
            other = quotes[1 - i]
            own = [x for x in _stems(q) if not any(_near(x, y) for y in _stems(other))]
            if own and not any(_near(x, y) for x in own for y in said):
                return kind
        return ""
    return ""


#: 되풀이 답에 줄 react·되묻기 — 등급을 뒤집은 가드라 LLM 문장 대신 코드 문장이다. 칭찬도 꾸중도 아닌 말.
RESTATE_REACT = {
    "absolute_boundary": "자료의 단정을 다시 말했어요. 질문은 그 말이 들어맞지 않는 경우를 묻고 있어요.",
    "unsupported_cause": "자료의 인과를 다시 말했어요. 질문은 그렇게 볼 수 있는 근거를 묻고 있어요.",
    "tension": "자료의 한쪽 말만 다시 했어요. 질문은 두 말이 어떻게 함께 성립하는지 묻고 있어요.",
}
RESTATE_FOLLOWUP = {
    "absolute_boundary": "그 말이 통하지 않는 경우나 조건을 하나만 들어 볼래요?",
    "unsupported_cause": "그 인과를 받치는 수치나 출처가 자료에 있나요? 없다면 어떻게 보강할지 말해 볼래요?",
    "tension": "두 말이 함께 맞으려면 무엇이 달라야 하는지 한 문장으로 이어 볼래요?",
}
RESTATE_POINT = {
    "absolute_boundary": "단정이 들어맞지 않는 경우·조건",
    "unsupported_cause": "인과를 받치는 근거(수치·출처) 또는 근거가 없다는 점",
    "tension": "두 말이 함께 성립하는 뜻",
}


#: 탐침 질문의 결정적 골자 — LLM 골자가 따져 묻는 줄을 **되풀이**했을 때 쓴다 (화면의 「정답 요지」 이자 판정의 채점 기준).
#: 09-29 loop2 dry-run: 단정 탐침의 LLM 골자가 「연장 개방을 하면 퇴근 후 이용자는 반드시 늘어나요」(단정 그대로),
#: 근거 없는 인과 탐침의 골자가 프롬프트의 「S3 «…»」 꼴을 베낀 인용 한 줄이었다. 되풀이를 정답으로 가르치면 판정과 모순이다.
def probe_gist(probe) -> str:
    quotes = [e for e in probe.evidence if (e.quote or "").strip()]
    if not quotes:
        return ""
    first = _short(quotes[0].quote, 70)
    where = f"자료 {quotes[0].slide_no}장" if quotes[0].slide_no else "자료"
    if probe.kind == "absolute_boundary":
        return (f"{where}의 「{first}」는 모든 경우에 맞는다고 단정할 수 없어요 — 들어맞지 않는 경우나 조건을 하나 들고,"
                " 자료가 보여 준 범위까지만 말하는 게 답이에요.")
    if probe.kind == "unsupported_cause":
        return (f"{where}의 「{first}」에는 수치나 출처가 없어요 — 근거가 아직 없다는 점을 인정하고,"
                " 어떤 자료(설문·통계·비교)로 보강할지 말하는 게 답이에요.")
    if probe.kind == "tension" and len(quotes) >= 2:
        second = _short(quotes[1].quote, 50)
        return (f"「{_short(quotes[0].quote, 50)}」와 「{second}」는 함께 성립할 수 있어요 — 두 말이 가리키는 범위·조건이"
                " 어떻게 다른지 이어서 설명하는 게 답이에요.")
    return ""


#: LLM 골자가 프롬프트의 근거 원문 꼴(「S3 «…»」)을 베꼈는가 — 답이 아니라 인용 표시다.
_PROMPT_QUOTE_RE = re.compile(r"(?<![A-Za-z0-9])S\d{1,3}\s*«")


def gist_needs_rebuild(gist: str, probe, q_text: str = "") -> bool:
    """탐침 질문의 골자가 따져 묻는 줄을 되풀이했거나 프롬프트 인용 꼴을 베꼈다 — 결정적 골자로 바꿔야 한다."""
    if probe is None or probe.kind not in ("absolute_boundary", "unsupported_cause", "tension"):
        return False
    # F-08 이 자료 줄로 조립한 골자(「자료는 이렇게 말해요 — …」)는 따져 묻는 줄을 옮긴 것일 뿐 이 질문의 답이 아니다.
    if (gist or "").startswith(EVIDENCE_GIST_LEAD):
        return True
    return bool(_PROMPT_QUOTE_RE.search(gist or "")) or bool(restates_line(gist, probe, q_text))


#: f08 `_evidence_gist` 가 여는 말 — 같은 문자열이어야 한다 (f08 을 import 하지 않으려고 여기 둔다).
EVIDENCE_GIST_LEAD = "자료는 이렇게 말해요 — "
