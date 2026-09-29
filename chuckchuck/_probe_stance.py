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
from ._contra import CONTRA, contra_prompt, contra_stance
from ._deck_claims import _has, content_stems, direction, numbers
from ._speech import josa_of
from .contracts import PROBE_STANCES, QA_TEXT_MAX, ProbeStance

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

#: 단정을 **더 세게** 받아들이는 말 — 「어떤 경우에도·항상·예외 없이」. 「경우·예외」 가 들어 있지만 경계가 아니라 동의다.
#: 09-30 레드팀 J3: 「어떤 경우에도 식사 순서만 바꾸면 … 완전히 막을 수 있어서 걱정하지 않아도 돼요」 가 「경우」「않」 하나로
#: 단정 가드를 꺼서 wrong 0 대신 LLM 판정에 맡겨졌다(이번엔 LLM 이 막았지만 운이다).
_UNIVERSAL_RE = re.compile(
    r"어떤\s*경우(?:에도|든|라도)|어느\s*경우(?:에도|든|라도)|모든\s*경우(?:에|에도)?|언제(?:나|든)|항상|무조건|"
    r"예외\s*(?:없이|가\s*없|는\s*없)|반드시|절대(?:로)?|100\s*%"
)
#: 경계 표지를 앞뒤 절까지 넓혀 볼 대조 어미 — 「…막을 수 있다고 했지만, 탄수화물이 많으면 아니에요」.
_CONTRAST_END_RE = re.compile(r"(?:지만|는데|은데|으나|다만)[^가-힣A-Za-z0-9]*$")
#: 근거가 **비었다고 밝힌** 말 — 근거를 가리키는 낱말 + 없음·부족. 「추가 확인이 필요해요」 같은 막연한 유보는 아니다.
_EVIDENCE_GAP_RE = re.compile(
    r"(?:근거|수치|출처|자료|데이터|통계|연구|실험|증거|사례|숫자)[^.?!\n]{0,14}"
    r"(?:없|부족|모자라|빠져|안\s*나와|안\s*나오|제시되지\s*않|제시하지\s*않|확인되지\s*않|밝혀지지\s*않|달지\s*않|안\s*달)"
)
#: 해결 방법이 **비었다고 밝힌** 말 — 빈칸 탐침(unsolved)의 절반 답 (「개선 방법은 자료에 없어요」).
_REMEDY_GAP_RE = re.compile(
    r"(?:방법|방안|해결책|해결\s*방법|대책|개선책)[^.?!\n]{0,14}(?:없|부족|안\s*나와|안\s*나오|제시되지\s*않|다루지\s*않|못\s*했|아직)")


#: 해결책이 빈 문제를 **앞으로 어떻게 채울지** 말하는 꼴 — 「보완할게요」「다음 발표에 더해 볼게요」「개선할 계획이에요」.
_REMEDY_PLAN_RE = re.compile(r"(?:보완|보강|개선|해결|더해|추가|채우|마련)\S*\s*(?:할게|하겠|할\s*거|해\s*볼|볼게|할\s*예정|할\s*계획|하려고)")


def answers_gap(answer: str, kind: str) -> bool:
    """
    빈틈 탐침(근거 없는 인과·해결 방법 없음)에 **답한** 말인가 — 빈틈을 인정했거나(「수치나 출처가 없어요」) 어떻게 채울지 말했다
    (「설문·통계로 보강할게요」「좌석은 예약제로 보완할게요」). 그런 답은 자료 낱말을 안 써도 이 질문에 답한 것이라 무관 가드가 볼 일이
    아니다 (09-30 WP-J2, standard 실측: 「그리고 어떤 자료(설문·통계·비교)로 보강할지…」 가 「질문과 다른 이야기」 35).
    """
    if kind not in ("unsupported_cause", "unsolved"):
        return False
    t = answer or ""
    if acknowledges_gap(t):
        return True
    if any(_SOURCE_RE.search(x) and _PLAN_VERB_RE.search(x) for x in _sentences(t)):
        return True
    return bool(_REMEDY_PLAN_RE.search(t))


#: 채우는 **행동** — 보강·보완·더하기·도입·모으기. 계획 문장의 동사다.
_PLAN_ACT_RE = re.compile(r"보완|보강|개선|해결|더하|더해|더할|추가|채우|채워|채울|마련|넣|도입|만들|모으|모아|모을|조사|수집|찾아")
#: 하겠다는 **다짐** — 「…할게요」「…해 볼 거예요」「…할 계획이에요」. 「어떻게 보강할지 말하는 게 답이에요」 는 다짐이 아니다.
_COMMIT_RE = re.compile(r"게요|겠어요|겠습니다|거예요|거에요|예정|계획|려고|하려|해\s*볼|볼\s*거")


def plans_gap(text: str) -> bool:
    """
    빈틈을 **어떻게 채울지** 다짐했는가 — 「설문이나 통계로 보강할게요」「다음 발표에서 좌석 예약제를 더해 볼 거예요」.
    빈틈 탐침의 모범답은 「빈틈 인정 + 채울 계획」 이다 — 인정만 한 답과 계획까지 말한 답을 코드가 가른다 (09-30 WP-J3).
    한 문장 안에 채우는 행동과 다짐이 같이 있어야 한다 — 「어떤 자료로 보강할지 말하는 게 답이에요」 는 계획이 아니라 말에 대한 말이다.
    """
    t = text or ""
    if any(_PLAN_ACT_RE.search(x) and _COMMIT_RE.search(x) for x in _sentences(t)):
        return True
    return bool(_REMEDY_PLAN_RE.search(t))


def acknowledges_gap(text: str) -> bool:
    """답이 자료의 **빈틈을 인정**했는가 — 근거(수치·출처)가 없다 · 해결 방법이 없다. 빈틈 탐침의 되물음을 「어떻게 보강할래요?」 로
    좁힐지 정할 때 쓴다 (09-30 WP-J2). 막연한 「추가 확인이 필요해요」 는 인정이 아니다(`_EVIDENCE_GAP_RE` 와 같은 규율)."""
    t = text or ""
    return bool(_EVIDENCE_GAP_RE.search(t) or _REMEDY_GAP_RE.search(t))


#: 근거를 **어떻게 보강할지** 말하는 동사 — 출처 낱말(설문·통계…)과 같은 문장에 있을 때만 보강 계획이다.
_PLAN_VERB_RE = re.compile(r"보강|보완|조사|모으|모아|측정|비교|찾아|구해|확인|검증|받아|받으|수집|분석|추적|물어")
#: 필요·당위 — 「연구가 필요해요」 는 출처를 댄 말이 아니라 유보다.
_NEED_RE = re.compile(r"필요|해야|돼야|되어야|아직|확인|검증|보완|보강|없|부족")
#: 새 낱말로 세지 않는 유보·강조·지시어 — 「이건 추가 확인이 필요해요」 는 아무것도 보태지 않는다.
_HEDGE_STEMS = ("추가", "확인", "필요", "검증", "보완", "보강", "아직", "조금", "정확", "확실", "더욱", "계속", "나중",
                "이건", "그건", "저건", "이거", "그거", "여기", "거기")
_SENT_SPLIT_RE = re.compile(r"(?<=[.?!])\s+|\n+")
#: 따옴표로 묶은 인용 — '…' "…" 「…」 «…» ‘…’ “…”.
_QUOTED_SPAN_RE = re.compile(r"'[^'\n]{2,120}'|\"[^\"\n]{2,120}\"|「[^」]{2,120}」|«[^»]{2,120}»|‘[^’\n]{2,120}’|“[^”\n]{2,120}”")


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
        # 「예외·경계」 라는 말은 쓰지 않는다 — 판정 LLM 이 그 낱말을 react 로 옮겨 「예외를 짚었어요」 같은 분석 말이 화면에 샜다
        # (09-30 WP-P2 지적). 모범답(F-08 `_absolute_gist`)처럼 **조건**으로 말한다.
        body = (f"이 질문은 자료의 단정 「{first}」이 어떤 조건에서만 맞는지 묻는다 — 단정을 되풀이하거나 그대로 받아들이는 답은"
                " 답이 아니다 (통과 아님). 그 말에 붙는 조건(누구에게·언제·어떤 상황에서)을 든 답, 또는 자료에 그 조건이 아직 없다고"
                " 밝히고 어떻게 보완할지 말한 답이 정답 쪽이다.")
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
    """질문·탐침 줄에 없는 답의 낱말 — 되풀이 말고 무엇을 **보탰는가**. 유보어(「추가 확인이 필요해요」)는 보탠 것이 아니다."""
    known = content_stems(" ".join([question_text, *quotes]))
    # 방향 낱말(「커지니까요」)은 인과 줄의 서술어를 활용만 바꿔 되풀이한 것이다 — 보탠 낱말이 아니다.
    return [s for s in dict.fromkeys(content_stems(answer))
            if not _has(known, s) and not s.startswith(_FILLER) and not s.startswith(_HEDGE_STEMS) and not direction(s)]


#: 인용·보고 어미 — 「…막을 수 있다고 | 단정할 수는 없어요」 처럼 절 나누기가 인용절과 그 절을 받는 서술어를 가른다.
#: 받는 서술어(「단정할 수는 없어요」「보기는 어려워요」)가 그 인용절의 경계 표지다 (09-30 WP-J3).
_QUOTATIVE_END_RE = re.compile(r"(?:다고|라고|냐고|자고|다는|라는|다며|라며)[^가-힣A-Za-z0-9]*$")


def _scope(clauses_: list[str], i: int) -> str:
    """
    i 번째 절과, 대조 어미로 이어진 앞·뒤 절 — 단정을 옮긴 절에 붙은 경계 표지를 볼 범위.
    「…막을 수 있다고」 + 「했지만」 처럼 절 나누기가 떼어 낸 짧은 보고·보조 절(두 어절 이하)은 앞 절에 붙여 본다.
    인용 어미(「…있다고」)로 끝난 절은 그 절을 받는 다음 절까지 본다 — 「…있다고 단정할 수는 없어요」 의 「없」 이 경계다.
    """
    j, text = i, clauses_[i]
    while j + 1 < len(clauses_) and len(clauses_[j + 1].split()) <= 2 and not _CONTRAST_END_RE.search(text):
        j += 1
        text = f"{text} {clauses_[j]}"
    if (_CONTRAST_END_RE.search(text) or _QUOTATIVE_END_RE.search(text)) and j + 1 < len(clauses_):
        text = f"{text} {clauses_[j + 1]}"
    if i > 0 and _CONTRAST_END_RE.search(clauses_[i - 1]):
        text = f"{clauses_[i - 1]} {text}"
    return text


def _sentences(text: str) -> list[str]:
    return [x.strip() for x in _SENT_SPLIT_RE.split(text or "") if x.strip()]


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
    if kind == "absolute_boundary":
        # 경계 표지는 **단정을 옮긴 절**(과 대조 어미로 이어진 앞뒤 절)에 있어야 센다 (09-30 레드팀 J3). 예전엔 답 어디에든
        # 「경우·없·않·다르·일부」 하나만 있으면 가드가 꺼졌다 — 「걱정하지 않아도 돼요」 의 「않」 이 단정을 풀어 준 셈이었다.
        # 단정 줄 **자체에** 든 표지(「절대 하루 3번을 넘지 **않**습니다」 의 않)는 경계가 아니라 옮긴 말이다 — 줄에 없던 표지만 센다.
        quoted_marks = [m for q in quotes for m in _BOUNDARY_RE.findall(q)]
        # 따옴표로 **인용한** 단정(「자료 5장의 '…하나도 없다'는 문장이 이를 명시해요」)은 출처를 댄 것이지 단정을 되풀이한 게
        # 아니다 — 인용 부분을 빼고 본다 (09-30 verify 하네스: 좋은 답이 이 인용 때문에 되풀이 55 를 받았다).
        # 인용을 **절을 가르기 전에** 뺀다 (09-30 WP-J3 standard 실측): 절 나누기가 인용 안의 「때마다」「…하고」 에서 갈라
        # 「「매매할 때마다 | 수수료·세금은 반드시 발생」은 …」 의 두 조각이 어느 쪽도 인용 꼴이 아니게 됐고, 우리 골자를 그대로 말한 답이
        # 「자료의 단정을 다시 말했어요」 55 를 받았다.
        parts = _clauses(_QUOTED_SPAN_RE.sub(" ※ ", text))
        for i, clause in enumerate(parts):
            stems = _stems(clause)
            if not (any(_restates(stems, q) for q in quotes) and R.absolute_marker(clause)):
                continue
            marks = _BOUNDARY_RE.findall(_UNIVERSAL_RE.sub(" ", _scope(parts, i)))
            for m in quoted_marks:
                if m in marks:
                    marks.remove(m)
            if not marks:
                return kind
        return ""
    if kind == "unsupported_cause":
        if _new_number(text, q_text, quotes):
            return ""
        # 인과는 연결 어미(「발달해서」)에서 절이 갈리므로 **문장**이 되풀이의 단위다. 근거가 비었다는 인정은 ① 인과를 옮긴 문장 안의
        # 유보 표지이거나 ② 근거 낱말 + 없음(「출처는 없어요」)이어야 한다 — 따로 떨어진 「추가 확인이 필요해요」 는 아니다 (J3).
        sents = _sentences(text) or [text]
        restating = [x for x in sents if any(_restates(_stems(x), q) for q in quotes)]
        # 인과 줄 **자체에** 든 유보 낱말(「주소 **검증**을 붙이면」 의 검증)은 인정이 아니라 옮긴 말이다 — 줄에 없던 표지만 센다.
        line_gaps = [m for q in quotes for m in _GAP_RE.findall(q)]

        def own_gap(sentence: str) -> bool:
            found = _GAP_RE.findall(sentence)
            for m in line_gaps:
                if m in found:
                    found.remove(m)
            return bool(found)

        acknowledged = any(_EVIDENCE_GAP_RE.search(x) for x in sents) or any(own_gap(x) for x in restating)
        planned = any(_SOURCE_RE.search(x) and _PLAN_VERB_RE.search(x) for x in sents)
        if acknowledged or planned:
            return ""
        if _PROOF_CLAIM_RE.search(text):
            return kind          # 수치도 인정도 없이 「입증됐다·명확하다」 — 근거를 댄 것이 아니라 주장한 것이다
        # 출처를 **댄** 말(「조사에 따르면」)만 근거다 — 「연구가 필요해요」 처럼 필요·당위와 같이 온 출처 낱말은 유보다.
        if any(_SOURCE_RE.search(x) and not _NEED_RE.search(x) for x in sents):
            return ""
        said = _stems(text)
        # 보탠 낱말은 유보 문장(「연구가 필요해요」 — 인과를 옮기지도, 근거가 없다고 밝히지도 않은 필요·당위 문장) 밖에서만 센다.
        core = " ".join(x for x in sents if x in restating or not _NEED_RE.search(_QUOTED_SPAN_RE.sub(" ", x)))
        if any(_restates(said, q) for q in quotes) and len(_novel(core, q_text, quotes)) < NOVEL_MIN:
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


#: 탐침 질문의 결정적 골자 — LLM 골자가 따져 묻는 줄을 **되풀이**했을 때 쓴다 (화면의 「정답 요지」 이자 판정의 참고 답).
#: 09-29 loop2 dry-run: 단정 탐침의 LLM 골자가 「연장 개방을 하면 퇴근 후 이용자는 반드시 늘어나요」(단정 그대로),
#: 근거 없는 인과 탐침의 골자가 프롬프트의 「S3 «…»」 꼴을 베낀 인용 한 줄이었다. 되풀이를 정답으로 가르치면 판정과 모순이다.
#: **발표자가 그대로 말할 모범답**으로 쓴다 (09-30 WP-J2) — F-08 `_probes.probe_code_gist` 가 못 지을 때(요소 이름·해결 줄이
#: 없을 때)의 폴백이라 같은 목소리여야 한다. 예전엔 「…점을 인정하고, …말하는 게 답이에요」 채점 지시라 「이렇게 말하면 완성이에요」
#: 칸에 지시문이 떴고(09-30 standard), 판정 하네스의 좋은 답이 그 지시문을 입말로 옮겼다. 첫 절에 탐침의 열쇠 말(「단정」·「수치」)을 둔다.
def probe_gist(probe) -> str:
    quotes = [e for e in probe.evidence if (e.quote or "").strip()]
    if not quotes:
        return ""
    first = _short(quotes[0].quote, 70)
    where = f"자료 {quotes[0].slide_no}장" if quotes[0].slide_no else "자료"
    if probe.kind == "absolute_boundary":
        # 예전 「…는 모든 경우에 그렇다고 단정할 수는 없어요. 자료가 보여 준 범위 안에서만…」 은 조건을 하나도 말하지 않아 그대로
        # 답하면 단정 줄을 다시 말한 것과 같았다 (09-30 standard · WP-P2 지적). 폴백은 자료를 못 보니 「조건이 아직 없다 → 보완」 꼴이다.
        return (f"「{first}」{josa_of(first, '이라고', '라고')} 단정할 수는 없어요 — {where}에는 이 말이 들어맞는 조건이 아직 없어요."
                " 누구에게, 언제, 어떤 조건에서 그런지 정해서 보완할게요.")
    if probe.kind == "unsupported_cause":
        return f"{where}의 「{first}」에는 아직 수치나 출처가 없어요. 설문이나 통계, 비교 자료로 보강할게요."
    if probe.kind == "tension" and len(quotes) >= 2:
        one, two = _short(quotes[0].quote, 50), _short(quotes[1].quote, 50)
        return (f"「{one}」{josa_of(one, '과', '와')} 「{two}」{josa_of(two, '은', '는')} 함께 성립해요."
                " 두 말은 가리키는 범위와 조건이 달라서 둘 다 맞아요.")
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

#: 코드가 자리만 채운 골자 — F-08 이 LLM 골자를 못 써서 틀 문장으로 둔 것. 모범답이 아니라 자리 표시라 **가리지도, 보기로 쪼개지도,
#: 채점 바닥으로도 쓰지 않는다** (09-30 standard e2e703b · WP-J3). 두 사다리(F-08 힌트 · F-09 「모르겠어요」)와 판정이 같은 잣대를 쓴다.
TEMPLATE_GIST_CHECKS = frozenset({"gist_template", "fallback_template"})
#: 틀 자리에 코드가 **모범답을 다시 지었다**는 표시 — 탐침 코드 골자·탐침 폴백 골자·함정 바로잡음 골자는 자리 표시가 아니다.
GIST_REBUILT_CHECKS = frozenset({"gist_probe_code", "gist_probe_rebuilt", "gist_rebuilt_trap"})


def template_gist(question) -> bool:
    """골자가 코드 틀 자리 표시인가 — gist_template·fallback_template 이고, 그 자리에 코드가 모범답을 다시 짓지 않았다."""
    basis = getattr(question, "basis", None)
    checks = set(getattr(basis, "checks", None) or []) if basis is not None else set()
    return bool(TEMPLATE_GIST_CHECKS & checks) and not (GIST_REBUILT_CHECKS & checks)


def evidence_gist(question) -> bool:
    """골자가 자료 줄을 이어 붙인 꼴(「자료는 이렇게 말해요 — A · B (1, 5장)」)인가 — 머리말·장 목록째 가리면 발판이 아니다."""
    return (getattr(question, "answer_gist", "") or "").startswith(EVIDENCE_GIST_LEAD)


# ---------------------------------------------------------------------------
# 입장 둘 중 하나 — 「모르겠어요」 첫 단계(F-09) · 칩 답 판정(F-09) (09-30 WP-J3 · contracts.PROBE_STANCES)
# ---------------------------------------------------------------------------

#: 입장 물음 앞에 싣는 자료 줄의 상한 — 물음 전체가 QA_TEXT_MAX 안에 들어가야 칩 글이 잘리지 않는다.
STANCE_QUOTE_MAX = 110
#: 긴장 탐침의 비교 줄 — 「A보다 중요한 B」. 긴장 물음 앞에는 이 줄을 싣는다(식 줄은 답을 보여 준다).
_THAN_RE = re.compile(r"보다")


#: 보기가 **질문마다 다른** 입장을 더할 자리 — 종류 이름 → (질문 → ProbeStance | None). 예: 모순 질문의 (자료 값, 발화 값)은 표에 고정 글로
#: 둘 수 없다 — 여기에 보기를 짓는 함수를 더하면 사다리(F-08 힌트·F-09 「모르겠어요」)와 칩 판정(F-09 `stance_pick`)이 그대로 쓴다.
#: 종류 이름은 탐침 종류, 탐침이 아닌 질문은 질문 출처(`Question.source` — 「contradiction」 따위)다.
STANCE_RESOLVERS: dict = {
    # 모순 질문 — (자료 값, 발표 값) 칩, 값을 모르면 표의 「자료 쪽 / 발표 쪽」 (09-30 WP-CONTRA · 녹음 감사 REC-08)
    CONTRA: contra_stance,
}


def stance_kind(question) -> str:
    """입장 표를 찾는 이름 — 탐침 질문은 탐침 종류, 아니면 질문 출처."""
    probe = probe_of(question)
    return probe.kind if probe is not None else (getattr(question, "source", "") or "")


def stance_of(question) -> ProbeStance | None:
    """
    이 질문의 입장 둘 중 하나 (contracts.PROBE_STANCES · STANCE_RESOLVERS), 설 수 없으면 None.

    탐침 종류가 표에 없으면(형제 우선순위 — 자료가 어느 쪽에 순위를 뒀는지 코드가 모른다) None 이다. 단정·근거 없는 인과는 따지는
    자료 줄이, 긴장은 비교 줄과 구성 줄 둘이 탐침 근거에 있어야 한다 — 그 줄이 「이 말」 이 가리키는 것이다.
    """
    kind = stance_kind(question)
    if kind in STANCE_RESOLVERS:
        return STANCE_RESOLVERS[kind](question)
    probe = probe_of(question)
    if probe is None:
        return None
    st = PROBE_STANCES.get(probe.kind)
    if st is None:
        return None
    quotes = [e for e in probe.evidence if (e.quote or "").strip()]
    if probe.kind in ("absolute_boundary", "unsupported_cause") and not quotes:
        return None
    if probe.kind == "tension" and len(quotes) < 2:
        return None
    return st


def _stance_quote(probe):
    quotes = [e for e in probe.evidence if (e.quote or "").strip()]
    if not quotes:
        return None
    if probe.kind == "tension":
        return next((e for e in quotes if _THAN_RE.search(e.quote)), quotes[0])
    return quotes[0]


def stance_prompt(question) -> tuple[str, list[str]] | None:
    """
    「모르겠어요」 첫 단계의 입장 물음과 칩 둘 — 「자료 5장은 «…» 라고 해요. 이 말은 늘 맞는 말인가요, 조건이 붙는 말인가요?」.
    빈칸 탐침은 줄 대신 개념 이름으로 받는다(「피해 회복 지연 이야기예요.」 — 탐침 근거 줄은 문제 목록 제목·다른 요소의 해결 줄이다).
    칩은 표의 글 그대로다 — 자료 낱말 보기가 아니라서 LLM 보기 검사(`f09._llm_choice_ok`)를 거치지 않는다. 설 수 없으면 None.
    """
    st = stance_of(question)
    if st is None:
        return None
    probe = probe_of(question)
    label = (getattr(question, "label", "") or "").strip()
    if stance_kind(question) == CONTRA:
        # 모순 질문 — 근거 인용(자료 쪽 줄)이 곧 답이다. 발표 쪽 인용과 장 번호만 싣는다 (09-30 WP-CONTRA · 녹음 감사 REC-08)
        text = contra_prompt(question, st)
        return (text if len(text) <= QA_TEXT_MAX else st.ask), list(st.choices)
    if probe is None:
        # 표 밖 종류(STANCE_RESOLVERS) — 근거 인용이 있으면 그 줄, 없으면 개념 이름으로 받는다
        quote = " ".join((getattr(question, "evidence_quote", "") or "").split())
        no = getattr(question, "evidence_slide_no", 0) or 0
        lead = (f"자료 {no}장은 «{quote}» 라고 해요." if no else f"자료는 «{quote}» 라고 해요.") if quote and len(quote) <= STANCE_QUOTE_MAX \
            else (f"{label} 이야기예요." if label else "")
    elif probe.kind == "unsolved":
        lead = f"{label} 이야기예요." if label else ""
    else:
        q = _stance_quote(probe)
        quote = " ".join((q.quote or "").split())
        if len(quote) <= STANCE_QUOTE_MAX:
            lead = f"자료 {q.slide_no}장은 «{quote}» 라고 해요." if q.slide_no else f"자료는 «{quote}» 라고 해요."
        else:
            lead = f"자료 {q.slide_no}장의 그 말 이야기예요." if q.slide_no else ""
    text = f"{lead} {st.ask}".strip()
    return (text if len(text) <= QA_TEXT_MAX else st.ask), list(st.choices)


def _letters(text: str) -> str:
    return re.sub(r"[^가-힣A-Za-z0-9]", "", text or "")


#: 칩 글 앞뒤에 붙어도 칩 답으로 보는 말 길이 — 「네 조건이 붙어요」「음, 아직 비어 있었어요.」.
STANCE_PICK_SLACK = 4


def stance_pick(answer: str, question) -> str:
    """
    답이 입장 칩 하나를 고른 말인가 — "correct" · "wrong" · "". 화면은 칩을 누르면 그 글을 답칸에 넣어 보낸다(서버는 칩인지 모른다).
    칩 글과 같거나(문장부호 무시) 앞뒤로 네 글자 안쪽만 붙은 말이고 다른 칩 글은 없을 때만 — 긴 답은 평소 판정으로 간다.
    """
    st = stance_of(question)
    a = _letters(answer)
    if st is None or not a:
        return ""
    for c in st.choices:
        c_sq, other = _letters(c), _letters(st.wrong if c == st.correct else st.correct)
        if c_sq and c_sq in a and len(a) - len(c_sq) <= STANCE_PICK_SLACK and other not in a:
            return "correct" if c == st.correct else "wrong"
    return ""


# ---------------------------------------------------------------------------
# 빈틈 탐침 — 골자가 「자료에 없다」 고 정한 것을 요구하는 말 (09-30 WP-J3 · standard 실측)
# ---------------------------------------------------------------------------

#: 빈틈 탐침이 **자료에 없다고 정한 것**의 이름 — 근거 없는 인과는 수치·출처·사례, 빈칸은 해결 방법. 어느 발표에나 쓰는 낱말만 둔다.
_GAP_THING_RE = {
    "unsupported_cause": re.compile(r"수치|숫자|데이터|통계|연구|실험|조사|출처|증거|근거|비율|퍼센트|\d+\s*%|표본|사례|비교\s*자료"),
    "unsolved": re.compile(r"방법|방안|대책|해결책|해결\s*방법|개선책|조치|전략|절차|대안"),
}
#: 그 빈틈을 **인정하라는** 말 — 요구가 아니라 인정이다(「근거가 없다는 점」). 결손으로 남는다(이미 말했으면 §5 가 뺀다).
_GAP_ACK_RE = re.compile(r"없|않|부족|비어|빠져|빠진|모자라|아직")
#: 빈틈을 **어떻게 채울지**(보강 계획)를 묻는 말 — 골자의 둘째 절이라 요구해도 된다.
_GAP_PLAN_RE = re.compile(r"보강|보완|채우|채울|앞으로|계획|찾아|모으|모을|수집|더하|더할")


def demands_gap(text: str, question, others: tuple[str, ...] | list[str] = ()) -> bool:
    """
    결손·되물음·react 문장이 빈틈 탐침의 **빈 것 자체**를 내놓으라는 말인가 (09-30 WP-J3).

    09-30 standard 실측(빈칸 탐침): 「자료에는 그 내용이 나와 있지 않아요 … 보강할게요」 에 결손 「피해 회복 지연을 개선하기 위한 구체적
    방안」 — 골자가 **자료에 없다**고 한 바로 그것이 「아직 안 나온 것」 칩에 떴고, 판정의 자기모순 가드는 그 결손을 답과 반대 명제로 읽어
    정직한 답을 60 으로 내렸다. 근거 없는 인과에 「구체적인 사례나 비교 자료」 도 같다.
    빈 것을 **인정하라는** 말(「근거가 없다는 점」)·**채울 계획**을 묻는 말(「어떻게 보강할지」)은 요구가 아니다. 빈칸 탐침에서 해결책이
    붙은 **다른 요소**(others — 탐침의 다른 개념 이름)만 부르는 말도 자료에 있는 것이다.
    """
    probe = probe_of(question)
    if probe is None or probe.kind not in _GAP_THING_RE:
        return False
    t = text or ""
    if not _GAP_THING_RE[probe.kind].search(t) or _GAP_ACK_RE.search(t) or _GAP_PLAN_RE.search(t):
        return False
    if probe.kind == "unsolved" and others:
        target = content_stems(getattr(question, "label", "") or "")
        said = content_stems(t)
        names_other = any(o and all(_has(said, s) for s in content_stems(o)) for o in others)
        if names_other and not (target and all(_has(said, s) for s in target)):
            return False
    return True


# ---------------------------------------------------------------------------
# 되물음이 따지는 단정을 전제로 까는가 (09-30 WP-J3 · standard 실측)
# ---------------------------------------------------------------------------

#: 단정을 **풀거나 따지는** 말 — 이 말이 같은 절에 있으면 단정 표지를 써도 전제가 아니다(「완전히 막을 수 없는 경우」).
_LOOSEN_RE = re.compile(r"없|않|못|아니|어렵|힘들|다를|달라|예외|한계|경우에\s*따라|과장|지나치")
#: 단정을 **말로 따지는** 꼴 — 「…완전히 막을 수 있다는 말이 늘 맞을까요?」 의 「다는 말」.
_REPORTED_RE = re.compile(r"(?:다는|라는|다고|라고)\s*(?:말|주장|단정|표현|문장|설명)?")


def presupposes_claim(text: str, question) -> bool:
    """
    되물음이 질문이 따지는 **단정을 전제로 깐** 말인가 (단정의 경계 탐침).

    09-30 standard 실측: 「…완전히 막을 수 있다」 의 경계를 묻는 질문에서 LLM 되물음이 「식사 순서 외에 혈당 스파이크를 완전히 막기 위해
    고려해야 할 다른 조건은 무엇인가요?」 — 따져 보라던 「완전히」 를 되물음이 사실로 받았다. 단정 표지(탐침 줄의 「완전히·반드시·항상」)가
    되물음에 있고, 그 절에 부정·유보가 없고, 그 단정을 말로 따지는 꼴(「…다는 말이」)도 아니면 전제로 깐 것이다. 인용(「…」) 안은 옮긴 말이다.
    """
    probe = probe_of(question)
    if probe is None or probe.kind != "absolute_boundary":
        return False
    marks = {R.absolute_marker(e.quote) for e in probe.evidence if (e.quote or "").strip()} - {""}
    if not marks or not (text or "").strip():
        return False
    for clause in _clauses(_QUOTED_SPAN_RE.sub(" ※ ", text)):
        for m in marks:
            at = clause.find(m)
            if at < 0:
                continue
            tail = clause[at + len(m):]
            if _LOOSEN_RE.search(clause) or _REPORTED_RE.search(tail):
                continue
            return True
    return False


# ---------------------------------------------------------------------------
# 빈칸 — 질문이 이미 보여 준 낱말은 가리지 않는다 (두 사다리 공용, 09-30 WP-J3)
# ---------------------------------------------------------------------------

def blank_exclusions(question) -> str:
    """
    빈칸으로 가리지 않을 글 — 개념 이름 · **질문 문장** · 탐침이 따지는 자료 줄. `_evidence.mask_gist` 의 label 자리에 넘긴다
    (그 자리의 낱말·글자는 빈칸도 오답도 되지 않는다).

    09-30 standard 실측: 빈칸 탐침의 힌트 「빈칸을 채워 보세요: ___을 개선하는 방법은 아직 자료에 없어요」 가 질문이 이미 부른 개념 이름을
    가렸고, 단정 탐침의 발판은 질문이 따지는 자료 줄의 「완전히」 를 가렸다 — 보이는 말을 다시 채우는 칸은 배울 것이 없다. 벤치 캐시 140문항
    가운데 64문항의 발판 빈칸이 질문에 있는 낱말이었다.
    """
    return " ".join(x for x in (getattr(question, "label", "") or "", getattr(question, "question", "") or "",
                                *probed_quotes(question)) if x)


def shown_in_question(word: str, question, *, quotes: bool = True) -> bool:
    """
    가린 낱말이 질문 문장(·개념 이름·따지는 줄)에 이미 보이는가 — 글자 그대로(띄어쓰기 무시) 또는 같은 줄기.
    quotes=False 면 따지는 자료 줄은 빼고 본다 — 그 줄 **안의** 한 칸을 가리는 발판(식의 나머지 요소)이 그 줄에 있는 것은 당연하다.
    """
    w = _letters(word)
    if not w:
        return False
    hay = blank_exclusions(question) if quotes else " ".join(
        x for x in (getattr(question, "label", "") or "", getattr(question, "question", "") or "") if x)
    if w in _letters(hay):
        return True
    stems = content_stems(word)
    shown = content_stems(hay)
    return bool(stems) and all(_has(shown, s) for s in stems)


#: 자료가 스스로 단 **제한 조건** 줄 — 「개인에 따라 …」「지역마다 다를 수 있어」「경우에 따라」. 어느 분야에나 쓰는 유보 말.
_LIMIT_LINE_RE = re.compile(r"다를\s*수|달라질\s*수|경우에\s*따라|에\s*따라\s*(?:다르|달라|차이)|마다\s*(?:다르|달라|차이)|"
                            r"않을\s*수\s*있|아닐\s*수\s*있|조건에서|조건이\s*(?:맞|갖춰)")
#: 제한 조건 줄에서 **조건 낱말** — 「개인에 따라」 의 개인, 「지역마다」 의 지역.
_CONDITION_WORD_RE = re.compile(r"([가-힣A-Za-z0-9]{2,10})(?:에\s*따라서?|마다|별로)")


def limit_line(texts: list[str], question) -> str:
    """단정 탐침의 **제한 조건** 줄 — texts(골자가 인용한 줄·자료 줄) 가운데 유보 말이 있고 따지는 단정 줄이 아닌 첫 줄. 없으면 ""."""
    probed = {_letters(q) for q in probed_quotes(question)}
    for t in texts:
        s = " ".join((t or "").split())
        if s and _letters(s) not in probed and _LIMIT_LINE_RE.search(s) and not R.absolute_marker(s, strong_only=True):
            return s
    return ""


#: 골자가 조건 절 앞에 다는 머리 — 「자료 7장에 적었듯 …」「자료 7장에도 …」「자료 7장처럼 …」. 떼고 조건 절만 받는다.
_CLAUSE_HEAD_RE = re.compile(
    r"자료\s*(\d+)\s*장(?:에서도|에서|에도|에는|에)?\s*(?:적었듯(?:이)?|말했듯(?:이)?|적은\s*대로|처럼|따르면|보면)?\s*,?\s*")
#: 인용 앞 「자료 N장…」 — 인용 바로 앞 머리(「자료 7장에도 「…」」「자료 7장에 적었듯 「…」」)에서 장 번호를 읽는다.
_QUOTE_HEAD_RE = re.compile(r"자료\s*(\d+)\s*장[^「«.!?]{0,14}[「«]\s*$")


def limit_of(question) -> tuple[int, str, bool]:
    """
    단정 탐침 골자의 **제한 조건** — (장, 글, 자료 인용인가). 없으면 (0, "", False).

    골자가 「」 로 인용한 자료 줄이 먼저다(「자료 7장에도 「개인에 따라 반응이 다를 수 있으니 무리하지 마세요」라고 적었어요」).
    없으면 골자가 해요체로 옮긴 조건 절(09-30 WP-P2 골자 「… — 자료 7장에 적었듯 개인에 따라 반응이 다를 수 있어요.」) — 이 글은
    자료 원문이 아니라 골자의 말이라, 쓰는 쪽이 「」 로 싸서 자료 인용처럼 보이면 안 된다(quoted=False).
    """
    gist = getattr(question, "answer_gist", "") or ""
    line = limit_line(quoted_spans(gist), question)
    if line:
        at = gist.find(line)
        m = _QUOTE_HEAD_RE.search(gist[:max(0, at)]) if at > 0 else None
        return (int(m.group(1)) if m else 0), line, True
    bare = re.sub(r"「[^」]*」|«[^»]*»", " ", gist)
    for seg in re.split(r"(?<=[.!?])\s+|\s+[—–]\s+", bare):
        seg = seg.strip()
        # 보완 다짐(「어떤 조건에서 그런지 정해서 보완할게요」)은 조건이 아니라 조건이 **없다**는 골자의 꼬리다
        if not seg or not _LIMIT_LINE_RE.search(seg) or R.absolute_marker(seg, strong_only=True) or plans_gap(seg):
            continue
        m = _CLAUSE_HEAD_RE.match(seg)
        clause = (seg[m.end():] if m else seg).strip()
        if clause and _LIMIT_LINE_RE.search(clause):
            return (int(m.group(1)) if m else 0), clause, False
    return 0, "", False


def condition_word(line: str, question) -> str:
    """제한 조건 줄의 조건 낱말(「개인」「지역」) — 질문에 이미 보이는 낱말이면 ""."""
    for m in _CONDITION_WORD_RE.finditer(line or ""):
        w = m.group(1)
        if not shown_in_question(w, question):
            return w
    return ""


def quoted_spans(text: str) -> list[str]:
    """글 속 「…」·«…» 인용(나온 순서) — 골자가 인용한 자료 줄을 꺼낼 때."""
    return [m.group(1) or m.group(2) for m in re.finditer(r"「([^」]{4,160})」|«([^»]{4,160})»", text or "")]


# ---------------------------------------------------------------------------
# 탐침 발판 — 두 사다리(F-08 힌트 · F-09 「모르겠어요」 둘째 단계)가 같이 쓰는 빈칸 (09-30 WP-J3)
# ---------------------------------------------------------------------------

#: 식 줄 — 「A = B × C × D」. 긴장 탐침의 구성 줄이 식이면 그 **나머지 요소**가 발판의 빈칸이다(전체가 무엇으로 이뤄졌나).
_FORMULA_SPLIT_RE = re.compile(r"\s*[×xX*·+/÷,]\s*")
#: 입장 빈칸의 틀 — 빈칸 자리에 입장 칩(contracts.PROBE_STANCES)이 그대로 들어가는 문장. 「…」 안은 자료 원문 그대로다.
_STANCE_FRAME = {
    "absolute_boundary": "{where}의 「{line}」{topic} ___",
    "unsupported_cause": "{where}의 「{line}」에 붙은 수치나 출처는 ___",
    "unsolved": "자료에서 {target} 푸는 방법은 ___",
    "tension": "{where}의 「{line}」{topic} ___",
}
#: 입장 틀에 싣는 자료 줄 상한 — 보기 둘과 장 표기까지 말풍선 한 칸(QA_TEXT_MAX)에 들어가게.
STANCE_FRAME_QUOTE_MAX = 60


def _formula_blank(question) -> tuple[str, str]:
    """긴장 탐침의 구성 식 줄에서 질문에 없는 요소 하나를 가린 (빈칸 글, 가린 요소). 식이 아니거나 남는 요소가 없으면 ("", "")."""
    probe = probe_of(question)
    for e in probe.evidence:
        line = " ".join((e.quote or "").split())
        if "=" not in line:
            continue
        rhs = line.split("=", 1)[1]
        for part in _FORMULA_SPLIT_RE.split(rhs):
            item = part.strip(" ()[]")
            if len(_letters(item)) < 2 or re.fullmatch(r"[\d.%\s]+", item) or shown_in_question(item, question, quotes=False):
                continue
            masked = line.replace(item, "___", 1)
            where = f"자료 {e.slide_no}장은" if e.slide_no else "자료는"
            return f"{where} 「{masked}」{josa_of(line, '이라고', '라고')} 해요.", item
    return "", ""


def _limit_blank_text(question) -> tuple[str, str]:
    """
    단정 탐침 — 골자의 **제한 조건**(`limit_of`)에서 조건 낱말을 가린 (빈칸 글, 가린 말). 없으면 ("", "").
    자료 인용이면 「」 안 원문 그대로(「자료 7장은 「___에 따라 반응이 다를 수 있으니 …」이라고 해요.」), 골자가 옮긴 조건 절이면
    골자의 말 그대로(「자료 7장에 적었듯 ___에 따라 반응이 다를 수 있어요.」) — 따지는 단정 줄의 말(「완전히」)은 가리지 않는다.
    """
    no, line, quoted = limit_of(question)
    word = condition_word(line, question) if line else ""
    if not word or word not in line:
        return "", ""
    masked = line.replace(word, "___", 1)
    if quoted:
        where = f"자료 {no}장은" if no else "자료는"
        return f"{where} 「{masked}」{josa_of(line, '이라고', '라고')} 해요.", word
    return (f"자료 {no}장에 적었듯 {masked}" if no else masked), word


def _stance_frame(question) -> str:
    """입장 칩이 빈칸에 들어가는 틀 문장 — 「자료 6장의 「…」은 ___」 (칩: 늘 맞아요 / 조건이 붙어요). 설 수 없으면 ""."""
    st = stance_of(question)
    probe = probe_of(question)
    if st is None or probe is None or probe.kind not in _STANCE_FRAME:
        return ""
    label = (getattr(question, "label", "") or "").strip()
    if probe.kind == "unsolved":
        return _STANCE_FRAME["unsolved"].format(target=f"{label}{josa_of(label, '을', '를')}") if label else ""
    q = _stance_quote(probe)
    line = _short(q.quote, STANCE_FRAME_QUOTE_MAX)
    where = f"자료 {q.slide_no}장" if q.slide_no else "자료"
    return _STANCE_FRAME[probe.kind].format(where=where, line=line, topic=josa_of(line, "은", "는"))


def probe_scaffold(question) -> tuple[str, str, list[str]]:
    """
    탐침 질문의 발판 빈칸 — (빈칸 글, 가린 말, 입장 보기 — 입장 빈칸일 때만). 탐침이 아니거나 설 수 없으면 ("", "", []).

    **질문이 이미 보여 준 말은 가리지 않는다** — 탐침은 질문이 자료 줄을 옮겨 따지므로 골자 낱말을 가리면 대개 질문의 말이었다
    (09-30 standard: 빈칸 탐침 힌트 「___을 개선하는 방법은 아직 자료에 없어요」 가 질문이 부른 개념 이름을, 단정 탐침 발판이 따지는 줄의
    「완전히」 를 가렸다). 대신 탐침마다 배울 것이 있는 자리를 가린다:
    - 단정의 경계 → 골자가 인용한 **제한 조건** 줄의 조건 낱말(「___에 따라 반응이 다를 수 있으니」).
    - 긴장 → 구성 식의 **나머지 요소**(전체가 무엇으로 이뤄졌나) — 질문에 없는 요소가 있을 때.
    - 그 밖·재료가 없으면 → **입장** 빈칸: 입장 칩(contracts.PROBE_STANCES)이 들어가는 틀 문장(「…에 붙은 수치나 출처는 ___」).
    형제 우선순위는 입장이 없어 ("", "", []) 이다 — 가린 낱말 쌍을 만들지 않는다.
    """
    probe = probe_of(question)
    if probe is None:
        return "", "", []
    if probe.kind == "absolute_boundary":
        text, word = _limit_blank_text(question)
        if text:
            return text, word, []
    if probe.kind == "tension":
        text, word = _formula_blank(question)
        if text:
            return text, word, []
    frame = _stance_frame(question)
    st = stance_of(question)
    if frame and st is not None:
        return frame, st.correct, list(st.choices)
    return "", "", []
