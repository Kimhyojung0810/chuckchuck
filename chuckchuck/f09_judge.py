"""
[F-09] 예상 질문에 대한 답변을 판정하는 모듈입니다.
Question + 답변(+선택 history·ConceptGraph·AlignmentDoc) → QaJudgement.

F-08 과 짝입니다. F-08 이 "무엇을 물을지" 를 결정적으로 정했다면,
여기서는 "그 답이 개념을 실제로 방어했는가" 를 4-class 로 판정합니다.

    from chuckchuck.f09_judge import judge_answer
    judgement = judge_answer(question, "제 답변은...", history=turns, llm="solar")

판정 자체는 LLM 이 하지만 **계약은 코드가 지킵니다** — verdict 는 enum 안,
score 는 0~100, node_id 는 질문에서 승계, react·summary_sentence 는 항상 채워집니다.
프론트가 이 넷으로 말풍선을 그리기 때문에 비어 있으면 화면이 빕니다.

판정은 무엇을 근거로 하나 (2026-09-29 개정)
--------------------------------------------
**정답의 원본은 자료 본문이고, F-08 의 골자(answer_gist)는 그 요약일 뿐입니다.**

09-29 두 덱 기준선(docs/review/2026-09-29_QA_근거검증/baseline.md)에서 판정은 골자를 채점 기준으로 삼았습니다.
골자가 자료에 없는 서열·다른 대상에 붙인 숫자를 담아도 그 골자를 옮긴 답이 good 85 를 받았고, 자료대로 한 정답은
골자와 다르다고 깎였습니다. 그래서 순서를 바꿨습니다.

1. 자료 본문 — 근거 장 본문(`_slide_block`)과, 답의 절마다 가장 가까운 자료 줄(`_deck_line_block`, 근거 장 밖 포함).
2. 골자 — 자료로 받쳐질 때만 「채점 기준」 이라고 싣습니다. 낱말·숫자가 자료에 없거나 자료와 어긋나는 짝이 있으면
   「참고 — 자료와 다르면 자료가 맞다」 로 싣고, 받쳐지지 않는 골자 요소는 체크리스트(`answer_gist_parts`)에서 뺍니다.
3. 코드 가드 (LLM 판정 뒤, 순서대로):
   - `_enforce_good` — 요소 미달 good → partial ≤ 79
   - `_enforce_trap` — **함정 표시만 보고 내리지 않습니다.** 답이 전제에 동의했을 때만(「네, 맞아요」·질문에만 있는
     숫자를 되풀이·LLM 이 바로잡지 않았다고 했는데 기대 답의 사실도 안 말함) wrong ≤ 35. 09-29 에 전제가 없는
     질문에 붙은 함정 표시 때문에 골자 그대로·자료대로 한 정답이 4/4 wrong 35 였습니다.
     질문이 코드가 만든 전제(`Question.trap_premise`, qa/trap)를 들고 있으면 그 단서로 정합니다 — 틀린 값·순서·방향을
     되뇌거나 「네」 로 받으면 동의, 자료의 값을 말하거나 전제를 반박하면 바로잡음(`_traps.premise_stance`).
   - `_enforce_deck` — 답이 자료와 **수치·표 서열·방향·부정**이 어긋나면 partial ≤ 55 · 칭찬 react 금지
     (`_deck_claims.conflicts`, 규칙은 구조로만 — 어느 발표에나 같은 규칙).
   - `_enforce_on_topic` — 자료와 무관 → wrong ≤ 35, 이 질문만 벗어남 → partial ≤ 65.
"""

from __future__ import annotations

import os
import re
from dataclasses import replace

from ._deck_claims import (
    Conflict,
    Deck,
    conflicts,
    content_stems,
    deck_from_slidedoc,
    echoes_unsupported_number,
    explicit_agreement,
    gist_corrects_premise,
    nearest_lines,
    opposes,
    states_reference,
    support,
    without_lines,
)
from ._probe_stance import (
    RESTATE_FOLLOWUP,
    RESTATE_POINT,
    RESTATE_REACT,
    probe_brief,
    probed_quotes,
    restates_probe,
)
from . import _reason as RS
from ._evidence import _noun_like, _stem as _ev_stem, anchor_slides, clean_slide_text, mask_gist, neighbor_lines, term_in
from ._judge_post import _has as _stem_in
from ._judge_post import (
    beyond_deck_terms,
    cap_length,
    clean_points,
    content_word_count,
    keep_sentences,
    point_covered,
    praise_ungrounded,
    real_either_or,
    same_kind,
    says_not_in_deck,
    scrub,
    talks_notation,
    to_noun_phrase,
    trim_missing_talk,
)
from ._traps import leaks_fact, premise_stance, trap_narrow, without_premise
from ._match import norm_tokens
from ._speech import plain_to_haeyo, to_haeyo
from ._json_text import extract_json_object
from .contracts import (
    ClaimQuote,
    ConceptMemory,
    MemoryDoc,
    QA_COACH_STAGES,
    QA_EXPLAIN_MAX,
    QA_MAX_ROUNDS,
    QA_TEXT_MAX,
    QA_VERDICT_FALLBACK,
    QA_VERDICT_SCORES,
    QA_VERDICTS,
    AlignmentDoc,
    ConceptGraph,
    Context,
    JudgeError,
    QaJudgement,
    QaTurn,
    Question,
    SlideDoc,
    Transcript,
    qa_mastered,
    qa_passed,
    qa_probe_tier,
)
from .f08_questions import build_hint_ladder
from .providers.llm_base import LLMProvider
from .providers.llm_impl import get_llm

MAX_TOKENS = int(os.environ.get("CHUCKCHUCK_JUDGE_MAX_TOKENS", "2048"))

#: history 를 몇 턴까지 프롬프트에 실을지. 앞 턴은 판정에 거의 기여하지 않는데
#: 토큰만 먹는다 — 최근 대화만 맥락으로 준다.
HISTORY_TURNS = int(os.environ.get("CHUCKCHUCK_JUDGE_HISTORY_TURNS", "6"))

#: 같은 질문에 대해 앞서 낸 답변을 몇 개까지 판정 대상에 실을지.
#: 되묻기는 턴 상한이 없어 무한정 쌓일 수 있는데, 프롬프트가 길어지면 정작
#: 마지막 답변이 묻힌다. 최근 것부터 이만큼만 싣는다.
PRIOR_ANSWERS_MAX = int(os.environ.get("CHUCKCHUCK_JUDGE_PRIOR_ANSWERS", "5"))

#: 프롬프트에 실을 발화 발췌 길이. 이 개념의 근거 장 발화만 붙인다.
SPEECH_EXCERPT_MAX = int(os.environ.get("CHUCKCHUCK_JUDGE_SPEECH_EXCERPT_MAX", "500"))

#: 판정에 실을 **자료 근거 장 본문** 총 글자 수. 0 이면 끈다.
#: 2026-09-10 까지 판정은 자료 본문을 아예 못 봤다 — summary 한 줄과 발화 300자로
#: "자료와 어긋나는가" 를 판정했으니 함정에 동의한 답이 60점을 받았다.
SLIDE_BODY_MAX = int(os.environ.get("CHUCKCHUCK_JUDGE_SLIDE_BODY_MAX", "1200"))

#: 개념 하나에 붙여 보여 줄 이웃 개념 수.
NEIGHBOR_MAX = 5

#: CLAUDE.md §3-1 이 금지한 높임. 프롬프트가 해요체를 시켜도 실 LLM 이 「좋아요」 판정에
#: "정확히 짚으셨습니다" 를 냈다 (2026-09-13 Solar A/B, 2문장). 코칭 경로의 _COACH_PRAISE_RE 와
#: 같은 규율 — 문장은 LLM, 말투 계약은 코드. 걸리면 그 등급의 결정적 문구로 바꾼다.
#: examples/qa_eval.py 의 HONORIFIC_RE 와 같은 낱말이라 하네스가 세는 것과 코드가 막는 것이 일치한다.
#: 09-29 두 덱 기준선: 「추정하신」「정량화하신」「찾고 계신」「설명해 주실 수 있나요」 가 빠져나갔다 — 관형형 ~신·~실 과
#: 「계신」 을 못 잡았다. 명사 속에서 안 나오는 꼴(하신·계신·주실…)만 둔다 — 「자신」「혁신」 을 잡으면 안 된다.
_HONORIFIC_RE = re.compile(
    # 「마시면·마시는지」(마시다) · 「함께」 는 높임이 아니다 — 09-30 레드팀: 이런 낱말이 good react 를 폴백으로 갈았다.
    r"셨|셔서|시겠|십니|십시오|(?<!마)시나요|(?<!마)시는지|계시|여쭈|(?<!함)께\s|께서|하신|하실|계신|계실|주신|주실|되신|되실|"
    r"보신|보실|(?<!마)시면|"
    r"주셔|주시|"             # 「확인해 주셔서」「말해 주시면」 (09-30 대화 감사 §9)
    r"(?<![다])님(?=[,.!?\s은는이가을를의께])"   # 「발표자님,」「교수님은」 — 부르는 말 높임 (09-29 실측 코칭 react) · 「다님」 은 아니다
)
#: 문장 가운데 높임을 평이한 말로 푼다 — 문장을 버리기 전에 한 번 살린다. 그래도 남으면 결정적 문구로 바꾼다.
_PLAIN_RULES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"하셨"), "했"), (re.compile(r"되셨"), "됐"), (re.compile(r"하시는"), "하는"),
    (re.compile(r"하신"), "한"), (re.compile(r"되신"), "된"), (re.compile(r"하실"), "할"),
    (re.compile(r"계신"), "있는"), (re.compile(r"계셨"), "있었"), (re.compile(r"주실\s*수"), "줄 수"),
    (re.compile(r"주신"), "준"), (re.compile(r"보신"), "본"), (re.compile(r"보실"), "볼"), (re.compile(r"말씀"), "말"),
    (re.compile(r"(하|주|되|보)시면"), r"\1면"),
    (re.compile(r"겠습니다(?=$|[\s.,!?])"), "겠어요"),   # to_haeyo 표에 없는 꼴 (09-29: 「좋겠습니다」「짚어보겠습니다」)
    # 09-30 대화 감사 §9·§10 — 「주셔서」「주시면」 높임 2건, 그리고 「짚으셨어요」 류 때문에 good react 28/37 이 폴백 문구로 갈렸다.
    (re.compile(r"주셔서"), "줘서"), (re.compile(r"주셨"), "줬"), (re.compile(r"주시겠어요"), "줄래요"),
    (re.compile(r"주시고"), "주고"), (re.compile(r"주시는"), "주는"), (re.compile(r"주시(?=[면며지네죠나겠])"), "주"),
    (re.compile(r"(하|보|되|주)시겠"), r"\1겠"),
)


def _past_of(m: re.Match) -> str:
    """「짚으셨」→「짚었」·「잡으셨」→「잡았」·「쓰셨」→「썼」·「나누셨」→「나눴」 — 높임 과거를 평이한 과거로 (모음 조화)."""
    ch = m.group(1)
    code = ord(ch) - 0xAC00
    lead, vowel, final = code // 588, (code % 588) // 28, code % 28
    if m.group(2):                                     # 받침 어간 + 으셨 → 어간 + 았/었
        return ch + ("았" if vowel in (0, 8) else "었")
    joined = {0: 0, 4: 4, 8: 9, 13: 14, 18: 4, 20: 6, 1: 1, 5: 5, 11: 10}.get(vowel)
    if joined is None or final:
        return ch + "었"
    return chr(0xAC00 + lead * 588 + joined * 28 + 20)    # ㅆ 받침(20)


_HON_PAST_RE = re.compile(r"([가-힣])(으)?셨")


def _plain(text: str) -> str:
    """높임을 풀어 본다(결정적·멱등). 못 푸는 꼴은 그대로 두고 _HONORIFIC_RE 가 잡는다."""
    out = text or ""
    for pat, rep in _PLAIN_RULES:
        out = pat.sub(rep, out)
    return _HON_PAST_RE.sub(_past_of, out)


def _drop_honorific(text: str) -> str:
    """풀고도 높임이 남은 **문장만** 뺀다. 예전엔 한 글자만 걸려도 react 전체를 폴백 문구로 갈았다 (09-30 §10: good react 28/37)."""
    return keep_sentences(_plain(text), lambda s: bool(_HONORIFIC_RE.search(s)))

#: react 가 비어 돌아왔을 때 채워 넣는 결정적 문구.
#: 프론트가 이걸로 말풍선을 그리므로 비워 둘 수 없다.
_REACT_BY_VERDICT = {
    "good": "네, 그 설명이면 충분해요.",
    # '절반' 은 요지를 맞힌 사람에게 과소평가로 읽힌다. 되묻기의 목적은 채점이 아니라
    # 한 걸음 더 끌어내는 것이라, 인정할 것은 인정하고 남은 하나를 가리킨다.
    "partial": "요지는 잡았어요. 한 가지만 더 짚어 주세요.",
    "wrong": "그 부분은 자료와 맞지 않아요.",
    "unknown": "지금 답변만으로는 판단하기 어려워요.",
}

#: summary_sentence 가 비어 돌아왔을 때. 리포트 총평 줄에 그대로 남는다.
_SUMMARY_BY_VERDICT = {
    "good": "{label} — 자기 말로 방어했어요.",
    "partial": "{label} — 방향은 맞지만 근거가 얕아요.",
    "wrong": "{label} — 자료와 어긋나게 설명했어요. 다시 보세요.",
    "unknown": "{label} — 판정을 보류했어요. 다시 답해 보세요.",
}

#: 답변이 비었을 때의 반응. LLM 을 부르지 않고 여기서 끝낸다.
EMPTY_ANSWER_REACT = "아직 답변이 없어요. 짧아도 좋으니 자기 말로 말해 보세요."

#: followup 이 비어 돌아왔을 때 쓰는 결정적 문장. 실전 코칭은 턴 상한이 없어서
#: 되묻기가 멈추면 사용자가 갇힌다 — LLM 이 빠뜨려도 질문은 반드시 나와야 한다.
#: 빠진 포인트가 있으면 그것을 겨냥하고, 없으면 개념 이름으로 좁힌다.
#: 조사를 붙이지 않는 모양으로 둔다 — "인지 자원 를" 처럼 띄어 붙은 조사가 화면에
#: 그대로 나갔다. '~시겠어요' 는 CLAUDE.md §3-1 이 금지한 높임이다.
_FOLLOWUP_BY_POINT = "{point} — 이 부분은 어떻게 봐요?"
_FOLLOWUP_GENERIC = "{label} — 이걸 뒷받침할 근거를 하나만 더 들어 주세요."
#: 답변이 질문·자료와 아무 낱말도 안 겹칠 때. LLM 의 react 는 자료 본문을 답변으로
#: 착각한 문장("…까지는 정확합니다")이라 쓰지 않는다.
_OFF_TOPIC_REACT = "질문과 다른 이야기예요. {label}에 대해 자료에 있는 대로 말해 보세요."
#: 함정 질문의 잘못된 전제를 그대로 받아들였을 때.
_TRAP_AGREED_REACT = "질문의 전제부터 확인해 보세요 — 자료는 그렇게 말하지 않아요."
#: 두 가드가 내리는 점수 상한. 규칙 8 의 wrong 구간(39 이하) 안이다.
OFF_TOPIC_SCORE_MAX = 35
#: 이보다 근거 낱말이 적으면 무관 판정을 하지 않는다 — 실사용은 골자+자료 본문으로
#: 언제나 수백 개다. 질문 한 줄만 있는 호출(테스트·근거 없는 flat 판정)은 건드리지 않는다.
ON_TOPIC_MIN_EVIDENCE_TOKENS = 30
#: 질문·골자·개념(=이 질문이 묻는 것)과 대조할 때의 최소 낱말 수. 상투어를 뺀 뒤 센다.
ON_TOPIC_MIN_FOCUS_TOKENS = 12
#: 이보다 짧은 답("빠진 개념을 찾아 주는 거예요")은 이 대조를 걸지 않는다 — 짧은 바꿔 말하기는 LLM 판정에 맡긴다.
#: 이 가드가 잡는 것은 **길게 잘 말했는데 다른 개념 이야기**인 답이다 (09-26 실측 답은 내용 낱말 12개).
ON_TOPIC_FOCUS_MIN_ANSWER_TOKENS = 8
#: 「이 질문」 을 벗어난 답은 wrong 이 아니라 **통과 못 하는 partial** 이다 — 낱말 대조만으로 "자료와 달라요" 라고 못 박지 않는다.
#: 바꿔 말한 정답이 걸렸을 때의 피해를 되묻기 한 바퀴로 줄인다. 통과선(70) 아래.
FOCUS_MISS_SCORE_MAX = 65
_FOCUS_MISS_REACT = "{label}에 대한 답으로는 조금 멀어요. 질문이 묻는 것에 맞춰 다시 말해 보세요."
#: 근거를 묻는 질문에 배경(현상이 있다는 말)만 되풀이한 답 (qa/reason). 틀린 말은 아니라 wrong 이 아니라 통과 못 하는 partial.
REASON_MISS_SCORE_MAX = 65
_REASON_MISS_REACT = "현상이 있다는 점은 맞아요. 질문은 그렇게 결론 낸 이유를 물어요 — 자료 {no}장의 근거를 짚어 보세요."
_REASON_MISS_FOLLOWUP = "그 결론을 받치는 이유는 자료 {no}장 어디에 있나요?"
#: 이 발표 어디에나 있는 상투어 — 이것만 겹치는 답은 「이 질문」 에 답한 것이 아니다.
#: 2026-09-26 실험대 실측: 개념 그래프 질문에 타깃 시장 이야기가 partial 75 로 통과했다 — 자료 본문과 「발표」 한 낱말이 겹쳐서.
_GENERIC_TOKENS = (
    "발표", "자료", "질문", "설명", "개념", "근거", "이유", "핵심", "내용", "부분", "경우", "방법", "방식", "정도",
    "이것", "그것", "저희", "우리", "이후", "계획", "생각", "때문", "그래서", "하지만", "그리고", "위해", "통해", "대해",
    "관해", "무엇", "어떤", "어느", "어떻게", "있어요", "없어요", "같아요", "거예요", "이에요", "예요", "해요", "됩니다",
    "있습니다", "없습니다", "합니다", "입니다", "했어요", "했습니다", "서비스", "프로젝트", "사용자", "기능",
)
TRAP_AGREED_SCORE_MAX = 35
#: 자료와 어긋난 주장이 있는 답의 점수 상한. 통과선(70) 아래, 「방향만 겨우 맞다」 구간(40~59) 안이다.
#: wrong 까지 내리지 않는 것은 결정적 대조가 틀릴 수 있어서다 — 되묻기 한 바퀴로 피해를 줄인다.
DECK_CONFLICT_SCORE_MAX = 55
#: 어긋남이 잡혔을 때의 react·후속 질문. 무엇이 맞는지는 말하지 않는다(정답을 흘리지 않게) — 볼 장과 볼 곳만.
_DECK_CONFLICT_REACT = "자료 {no}장과 어긋나는 부분이 있어요. 다시 볼 곳: {what}."
_DECK_CONFLICT_FOLLOWUP = "자료 {no}장을 다시 보면, {what} — 방금 말한 것과 같나요?"
_DECK_CONFLICT_SUMMARY = "{label} — 자료 {no}장과 어긋나게 설명한 부분이 있었어요."
#: 판정이 답과 반대 명제를 「빠진 점」·react 로 들고 있을 때 — 통과선 아래로, 어느 쪽이 맞는지는 말하지 않는다.
SELF_OPPOSED_SCORE_MAX = 60
#: 탐침이 따지는 자료 줄을 되풀이·수긍만 한 답 (`_probe_stance.restates_probe`) — 통과 못 하는 partial.
#: 09-29 P5 최종 평가: 단정 「완전히 막을 수 있다」 를 그대로 말한 오답이 good 85 였다. 틀린 말이라기보다 **묻는 것에 안 닿은**
#: 답이라 wrong 이 아니라 partial 로 두고 되묻기를 남긴다.
PROBE_RESTATE_SCORE_MAX = 55
_SELF_OPPOSED_REACT = "방금 답에 자료와 방향이 거꾸로인 부분이 있어요. 늘고 주는 쪽, 맞다·아니다 쪽을 다시 확인해 보세요."
#: 등급이 wrong 인데 LLM react 가 틀린 주장을 인정하는 말. 09-29 실측: 3장과 정반대인 답에 「…부분은 정확해요」.
_PRAISE_RE = re.compile(r"정확해요|정확합니다|맞아요|맞습니다|잘 짚|훌륭|좋은 답")

#: 되묻기 단계별 지시. **질문의 넓이는 코드가 정하고 LLM 은 그 넓이의 문장만 쓴다.**
#: 단계가 안 좁혀지면 사용자는 같은 벽을 세 번 만나고, 세 번째에 창을 닫는다.
_PROBE_TIER_BRIEF = {
    "probe": (
        "1라운드다. 빠진 지점 하나를 **열린 질문**으로 짚어라. "
        "발표자가 자기 말로 한 문단을 더 붙일 여지를 남겨 둔다."
    ),
    "focus": (
        "2라운드다. 같은 넓이로 또 물으면 안 된다. followup 은 **예/아니오나 둘 중 "
        "하나, 혹은 한 단어**로 답할 수 있어야 한다. **선택지를 질문 안에 넣어라.**\n"
        "  쓸 수 있는 모양: \"(자료의 낱말) 쪽인가요, (다른 낱말) 쪽인가요?\" · \"자료에 있었나요, 없었나요?\" · "
        "\"한 단어로 말하면 무엇인가요?\"\n"
        "  쓰면 안 되는 모양: \"왜 …인가요?\" · \"…는 무엇인가요?\" · \"설명해 주시겠어요?\"\n"
        "  — 이건 1라운드의 넓이다. 좁혀 준다고 해 놓고 같은 벽을 다시 세우는 셈이다.\n"
        "  발표자가 첫 발을 떼는 것이 목적이지 완결된 답을 받는 것이 목적이 아니다."
    ),
    "converge": (
        "3라운드 이상이다. 여기서도 막히면 발표자는 지친다. followup 은 **답을 거의 "
        "품은 확인 질문**이어야 한다 — 고개만 끄덕이면 되게 마지막 한 걸음만 남겨라.\n"
        "  쓸 수 있는 모양: \"…때문이라고 보면 될까요?\" · \"…라고 이해하면 맞을까요?\"\n"
        "  쓰면 안 되는 모양: 열린 질문 전부. 정답 문장을 그대로 읽어 주지도 마라."
    ),
}

#: 단계별 결정적 폴백 질문. LLM 이 followup 을 빠뜨려도 되묻기는 반드시 나와야 한다 —
#: 실전 코칭은 턴 상한이 없어서, 질문이 멈추면 사용자가 그 자리에 갇힌다.
_FOLLOWUP_BY_TIER = {
    "focus": "{point} — 이건 자료에 있었나요, 없었나요?",
    "converge": "{point} 때문이라고 보면 될까요?",
}

#: 열린 질문의 표지. focus·converge 인데 이게 보이면 **단계를 안 지킨 문장**이다.
#: 실측(2026-08-08, solar-pro3): 단계 지시를 user 꼬리에 붙여도, system 으로 올려도
#: 2라운드에 "…어떤 점에서 더 유리한가요?" 처럼 1라운드와 같은 넓이로 되물었다.
#: 프롬프트로 부탁만 해서는 사다리가 안 좁혀진다.
_OPEN_QUESTION_RE = re.compile(r"왜\s|무엇|어떤\s|어떻게\s|설명해|말씀해\s*주|이유는")


def _is_narrow(text: str) -> bool:
    """
    좁힌 질문인가 — 예/아니오·둘 중 하나·한 단어로 답할 수 있는 모양인가.

    "한 단어로 말하면 무엇인가요?" 는 «무엇» 을 품지만 좁은 질문이다.
    이 한 가지만 예외로 두고, 나머지는 열린 표지가 없으면 좁은 것으로 본다.
    """
    if "한 단어" in text:
        return True
    return not _OPEN_QUESTION_RE.search(text)

SYSTEM_PROMPT = """당신은 발표 심사위원이다.
방금 던진 질문에 발표자가 답했다. 그 답이 개념을 **실제로 방어했는지** 판정한다.

되묻기로 여러 번에 나눠 답했다면 **그 답변들을 합쳐서** 본다.
앞 턴에서 이미 말한 것을 다시 빠졌다고 하지 마라 — 마지막 한 마디만 채점하면
좁혀 물은 쪽이 손해를 본다.

**아래는 누적 답변이 있을 때(2턴 이상)만 적용한다.**
여러 턴에 나눠서 골자의 요소를 **전부** 말했으면 good 이다. 한 턴에 다 담지
못했다고 깎지 마라 — 되묻기의 목적은 발표자가 스스로 나머지를 꺼내게 하는
것이고, 꺼냈으면 성공한 것이다. 끝내 good 을 못 받으면 아무리 답해도 못 이기는
대화가 되고, 그러면 다음부터 시도하지 않는다.

**첫 턴에는 이 규칙이 없다.** 아직 나눠 말한 것이 없으므로 평소대로 엄격히
매겨라 — 첫 답에 무르면 되묻기가 시작조차 안 된다. 누적이든 아니든 골자의
요소가 하나라도 안 나왔으면 partial 이다.

verdict 는 다음 넷 중 하나다:
- "good" (설득 완료): 개념을 자기 말로 정확히 설명했다. 근거도 댔다.
- "partial" (부분 인정): 방향은 맞지만 핵심 근거가 빠졌거나 얕다.
- "wrong" (미방어): 자료와 어긋나게 설명했거나 질문을 빗나갔다.
- "unknown" (판정 보류): 무슨 말인지 알 수 없어 내용으로 판정할 수 없다.
  **짧다는 이유로 고르지 마라** — 질문이 요구한 것을 담았는지로만 정한다.

규칙:
1. **내용만 본다.** 말투·문장력·길이로 깎지 마라. 짧아도 맞으면 good 이다.
1-1. **답변에 있는 것만 답변이다.** 아래 '자료 근거 장 본문'·'기대하는 답의 골자' 는
   대조 원본이지 발표자가 말한 것이 아니다. 답변 본문에 없는 내용을 답변이 말한
   것으로 치지 마라. 답변이 질문·자료와 무관한 이야기면 wrong 이다.
2. **선택형 질문(둘 중 하나·예/아니오)은 맞는 쪽을 고른 것 자체가 완전한 답이다.**
   "X 쪽인가요, Y 쪽인가요?" 에 "X 쪽이요" 라고만 답해도,
   그 선택이 맞으면 근거가 없어도 good 이다.
3. **정답의 원본은 '자료 근거 장 본문'·'답변과 맞닿은 자료 줄' 이다.** '기대하는 답의 골자' 는
   그 자료를 요약한 참고 답이다. 골자와 자료가 어긋나거나 골자에 자료에 없는 말이 있으면
   **자료 편을 든다** — 자료대로 답했으면 골자와 달라도 정답이고, 골자대로 답했어도 자료와
   어긋나면 정답이 아니다. 표현·용어가 달라도 뜻이 같으면 정답으로 본다.
   골자의 문장을 react·followup 에 그대로 옮겨 정답을 흘리지 마라.
4. '함정 표시' 는 질문을 만든 쪽이 붙인 표시라 **틀릴 수 있다.** 질문 문장에 자료와 어긋난
   주장(자료에 없는 수치·뒤집힌 방향·자료가 부정한 것)이 **실제로 있을 때만** 함정으로 본다.
   - 그런 주장이 있으면: 발표자가 그 전제를 **바로잡았을 때** good 이고, 그대로 동의했으면
     wrong 이다. premise_corrected 를 **반드시** 적는다 — 지적·정정했으면 true, 받아들였으면 false.
   - 그런 주장이 없으면: 평소 질문처럼 채점하고 premise_corrected 는 null 로 둔다.
     자료대로 답한 사람을 「전제를 안 바로잡았다」 고 깎지 마라.
   이 값은 코드가 등급에 반영한다.
5. react 는 심사위원이 그 자리에서 할 한 마디다. 존댓말, 한 문장.
   **답변 안에서 맞힌 것을 먼저 이름 붙이고 나서** 남은 것을 가리켜라 — "…까지는 정확합니다.
   그럼 …은요?" 처럼. 틀린 데부터 말하면 발표자는 다음 답을 시도하지 않는다.
   앞 턴보다 나아졌으면 그 진전을 짚어라. 빈말 칭찬은 하지 마라.
6. summary_sentence 는 이 개념에 대한 총평 한 문장이다. 리포트에 남는다.
7. missing_points 에는 **통과를 막는 결정적 결손 하나만** 적는다.
   "있으면 더 좋을" 수준은 적지 마라. 부족한 데가 없으면 빈 배열이다.
   여러 개를 늘어놓으면 발표자는 뭘 고쳐야 할지 도리어 모른다.
8. score 는 0~100. **70점 이상이면 통과로 처리된다.**
   - good: 80 이상
   - partial 중 **요지는 맞고 근거만 얕다**: 70~79 — 통과 구간이다
   - partial 중 방향만 겨우 맞다: 40~59
   - wrong: 39 이하
   표현이나 용어가 자료와 달라도 **요지가 같으면 70~79 를 줘라.**
   완벽한 문장을 받아내는 것이 목적이 아니다.
   **단, 자료와 어긋난 주장이 하나라도 있으면 70 이상을 주지 마라** — 수치를 다른 항목에
   붙였거나, 자료의 크기·순서(더 크다·가장)를 뒤집었거나, 방향(늘다/줄다)이나
   긍정·부정을 거꾸로 말한 경우다. 요지가 맞아 보여도 틀린 사실을 통과시키면 발표장에서
   그대로 말한다. 그 주장을 react 에서 「정확해요」「맞아요」 로 인정하지 마라.
9. followup 은 **이어서 던질 질문 한 문장**이다. verdict 가 good 이 아니면
   **반드시 쓴다.** 요지를 맞힌 답에도 쓴다 — 절반 맞힌 사람을 거기서 놓아 주면
   스스로 깨우칠 기회를 뺏는 것이다. good 일 때만 빈 문자열이다.
   - 원래 질문을 **다시 말하지 마라.** 빠진 지점 하나를 콕 집어 물어라.
   - 발표자를 몰아세우지 말고, 답할 수 있게 좁혀 주는 질문이어야 한다.
   - **[되묻기 단계] 가 주어지면 그 단계의 넓이로 물어라.** 같은 넓이로 세 번
     물으면 압박이 아니라 반복이다. 단계마다 한 칸씩 좁혀 답에 다가가게 한다.
10. 반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.

출력 스키마 — **아래 값은 자리 표시자다. 그대로 베끼지 말고 이번 답변을 보고 새로 써라.**
{
  "verdict": "good | partial | wrong | unknown 중 하나",
  "score": 0,
  "react": "<심사위원이 그 자리에서 할 한 마디>",
  "summary_sentence": "<이 개념에 대한 총평 한 문장>",
  "missing_points": ["<답변에서 빠진 포인트>"],
  "followup": "<빠진 지점을 겨냥한 후속 질문 한 문장. 충분하면 빈 문자열>",
  "covered_parts": [true, false],
  "premise_corrected": true
}

premise_corrected 는 함정 질문일 때만 쓴다 (아니면 빼거나 null).

covered_parts 는 '골자의 요소' 가 주어졌을 때만 쓴다 (없으면 빈 배열).
요소와 **같은 순서·같은 개수**로 참/거짓만 적는다. 개수가 어긋나면 통째로 버려진다.
"""

#: 응답이 복구 불가능한 JSON 일 때 한 번 더 물어볼 때 덧붙이는 말.
JSON_RETRY_NUDGE = """
[재요청] 직전 응답이 완전한 JSON 객체가 아니어서 버렸다.
코드펜스·주석·말머리·말끝 문장 없이, 출력 스키마 그대로의 JSON 객체 하나만 다시 출력하라.
"""


# ---------------------------------------------------------------------------
# 프롬프트
# ---------------------------------------------------------------------------

def _concept_block(question: Question, graph: ConceptGraph | None) -> list[str]:
    """
    자료가 말하는 이 개념 + 그래프에서의 위치.

    edges 가 진실이다. 경로는 parent 간선만 따라간 트리 뷰, 연결은 relates 까지 포함한
    그래프 뷰다. 답변이 "옆 개념과의 관계" 를 짚었는지 보려면 이게 있어야 한다.
    """
    node = graph.node(question.node_id) if graph is not None else None
    if node is None:
        return []

    lines = ["", "## 자료가 말하는 이 개념"]
    if node.summary:
        lines.append(f"{node.label}: {node.summary}")
    path = [n.label for n in graph.path_of(node.id)]
    if len(path) > 1:
        lines.append("경로(위계): " + " > ".join(path))
    # 무거운 이웃부터. id 로 동률을 깨 같은 그래프면 같은 줄이 나온다 (f08 과 같은 규칙)
    ranked = sorted(graph.neighbors_of(node.id), key=lambda n: (-n.weight, n.id))
    if ranked:
        shown = ", ".join(n.label for n in ranked[:NEIGHBOR_MAX])
        if len(ranked) > NEIGHBOR_MAX:
            shown += f" 외 {len(ranked) - NEIGHBOR_MAX}개"
        lines.append("연결된 개념: " + shown)
        # 이웃의 요약·간선 종류. 이름만으로는 "옆 개념과의 관계를 짚었는가" 를 못 본다.
        for ln in neighbor_lines(node, graph):
            lines.append(f"  - {ln}")
    return lines if len(lines) > 2 else []


def _slide_block(
    question: Question, slidedoc: SlideDoc | None, graph: ConceptGraph | None
) -> list[str]:
    """
    질문의 근거 장 **자료 본문** — 판정이 "자료와 어긋난다" 를 대조할 원본이다.

    F-08 이 만든 질문은 slide_nos 가 이미 anchor(최대 3장)다. 옛 세션의 질문은
    12장을 들고 올 수 있어 여기서 다시 좁힌다. 장마다 예산을 나눠 싣는다.
    """
    if slidedoc is None or SLIDE_BODY_MAX <= 0 or not question.slide_nos:
        return []
    texts = {s.slide_no: clean_slide_text(s.raw_text or "") for s in slidedoc.slides}
    node = graph.node(question.node_id) if graph is not None else None
    nos = anchor_slides(
        question.label, node.summary if node else "", list(question.slide_nos), texts
    )
    nos = [n for n in nos if texts.get(n)]
    if not nos:
        return []
    per_slide = max(80, SLIDE_BODY_MAX // len(nos))
    lines = ["", "## 자료 근거 장 본문 (판정의 대조 원본 — 발표자가 말한 것이 아니다)"]
    for no in nos:
        text = texts[no]
        if len(text) > per_slide:
            text = text[: per_slide - 1].rstrip() + "…"
        lines.append(f"[S{no}] {text}")
    return lines


def _speech_block(question: Question, transcript: Transcript | None) -> list[str]:
    """근거 장에서 실제로 한 말. Transcript.by_slide 를 slide_no 로 조인한다."""
    if transcript is None or not question.slide_nos:
        return []
    said = " ".join(
        text
        for text in (transcript.text_for_slide(no).strip() for no in question.slide_nos)
        if text
    )
    if not said:
        return []
    if len(said) > SPEECH_EXCERPT_MAX:
        said = said[: SPEECH_EXCERPT_MAX - 1].rstrip() + "…"
    return ["", "## 발표 때 이 개념의 근거 장에서 한 말", said]


def _build_user_prompt(
    question: Question,
    answer: str,
    history: list[QaTurn],
    graph: ConceptGraph | None,
    alignment: AlignmentDoc | None,
    transcript: Transcript | None,
    ctx: Context,
    prior_answers: list[str] | None = None,
    slidedoc: SlideDoc | None = None,
    memory_cm: ConceptMemory | None = None,
) -> str:
    """
    질문 → 자료 근거 → 지난 대화 → 지난 리허설 기억 → 이번 답변 순.

    판정 대상(질문)을 맨 앞에 두는 것은 F-07·F-11 에서 확인한 배치다 —
    앞에 둬야 모델이 답변을 질문에 비추어 보지, 답변만 따로 요약하지 않는다.
    """
    parts = [
        "[TASK] qa-judge",
        ctx.to_prompt_block(),
        "",
        "## 던진 질문",
        f"개념: {question.label} (id={question.node_id})",
        f"질문: {question.question}",
        f"함정 질문인가: {'예' if question.trap else '아니오'}",
    ]
    tp = question.trap_premise if question.trap else None
    if tp is not None:
        # 코드가 자료 줄 하나를 뒤집어 만든 전제다 (qa/trap) — 판정이 「질문에 전제가 있나」 를 짐작하지 않게 그대로 준다.
        where = f"자료 {tp.slide_no}장" if tp.slide_no else "자료"
        parts += [f"질문에 얹은 틀린 전제: «{tp.premise}»", f"{where}의 사실: «{tp.fact}»",
                  "이 질문은 함정이다 — 전제를 바로잡으면 good, 전제를 받아들이면 wrong 이다. premise_corrected 를 반드시 적어라."]
    if question.why:
        parts.append(f"이 질문을 던진 이유: {question.why}")

    parts += _concept_block(question, graph)
    parts += _slide_block(question, slidedoc, graph)

    item = None
    if alignment is not None:
        item = next((i for i in alignment.items if i.node_id == question.node_id), None)
    if item is not None and item.evidence.strip():
        parts += [
            "",
            "## 발표 때 이 개념에 대해 한 말 (정합 판정 근거)",
            f"({item.verdict}) {item.evidence}",
        ]
    parts += _speech_block(question, transcript)

    recent = history[-HISTORY_TURNS:] if history else []
    if recent:
        parts += ["", "## 지금까지 주고받은 대화"]
        for turn in recent:
            parts.append(f"- Q: {turn.question}")
            parts.append(f"  A: {turn.answer}  → {turn.verdict}")

    parts += _memory_block(memory_cm)
    parts += _answer_block(answer, prior_answers)
    return "\n".join(parts)


def _memory_concept(question: Question, memory: MemoryDoc | dict | None, graph: ConceptGraph | None) -> ConceptMemory | None:
    """이 질문의 개념에 붙은 기억. 그래프가 있으면 node_id 로, 없으면 질문의 label 로 잇는다."""
    if memory is None:
        return None
    if isinstance(memory, dict):
        memory = MemoryDoc.from_dict(memory)
    if graph is not None:
        cm = memory.by_node(graph).get(question.node_id)
        if cm is not None:
            return cm
    return memory.concept(question.label)


def _memory_block(cm: ConceptMemory | None) -> list[str]:
    """F-25 지난 리허설 기억. 없으면 빈 목록 — 프롬프트가 예전과 같다."""
    if cm is None or cm.attempts <= 0:
        return []
    lines = ["", "## 지난 리허설에서 이 개념 (같은 발표자 · 사실만)", cm.prompt_line]
    if cm.missing_points:
        lines.append(
            "지난번에 빠졌던 점이 이번 답에 나왔으면 summary_sentence 에서 그 진전을 알아봐 주고("
            "예: \"지난번엔 빠졌던 조건을 이번엔 짚었어요\"), 또 빠졌으면 missing_points 에 같은 말로 적어라."
        )
    return lines


def _gist_parts_block(question: Question) -> str:
    """
    요소별 채점 체크리스트. 요소가 없는 질문에서는 빈 문자열이라 프롬프트가 안 는다.

    **결정은 코드가 한다** (`_enforce_good`). 여기서 받는 것은 요소마다
    「나왔는가」 하나뿐이고, good 을 줄지 말지는 그 답을 보고 코드가 정한다.
    체크리스트를 안 주고 판정만 맡기면 둘 중 하나만 답해도 good 이 나온다.
    """
    parts = question.answer_gist_parts
    if not parts:
        return ""
    lines = [
        "",
        "",
        "## 골자의 요소 — 이 질문은 둘 이상을 묻는다",
        "누적 답변 전체를 합쳐, 요소마다 나왔는지 본다.",
    ]
    lines += [f"{i}. {part}" for i, part in enumerate(parts, start=1)]
    lines += [
        f"covered_parts 에 이 {len(parts)}개의 참/거짓을 **같은 순서로** 적어라.",
        "표현이 달라도 뜻이 같으면 나온 것이다 (규칙 3).",
        "**하나라도 안 나왔으면 good 이 아니다.**",
    ]
    return "\n".join(lines)


def _answer_block(answer: str, prior_answers: list[str] | None) -> list[str]:
    """
    판정 대상 블록. 되묻기로 나눠 말한 답변을 **합쳐서** 판정하게 한다.

    후속 질문 규칙(SYSTEM_PROMPT 7)은 "빠진 지점 하나를 콕 집어" 물어 발표자를
    증분 답변으로 유도한다. 그런데 마지막 증분만 채점하면 1턴에 A, 2턴에 B 를 말한
    사람이 A+B 를 다 말하고도 B 만으로 평가된다 — 좁혀 물은 쪽이 손해를 본다.

    앞 답변이 없으면 예전과 같은 한 줄짜리 블록이다. 빈 문자열은 버린다.
    """
    prior = [text.strip() for text in (prior_answers or []) if (text or "").strip()]
    if not prior:
        return ["", "## 이번 답변 — 이것을 판정하라", answer.strip()]

    prior = prior[-PRIOR_ANSWERS_MAX:]
    lines = ["", "## 이 질문에 대한 답변 (누적) — 전체를 합쳐서 판정하라"]
    for turn_no, text in enumerate(prior, start=1):
        lines.append(f"{turn_no}턴: {text}")
    lines.append(f"{len(prior) + 1}턴 (이번): {answer.strip()}")
    return lines


# ---------------------------------------------------------------------------
# 후처리 — LLM 판정을 계약 안으로 밀어 넣는다
# ---------------------------------------------------------------------------

def _clamp_score(raw: object, verdict: str) -> int:
    """score 를 못 읽으면 verdict 기본값, 읽히면 0~100 으로 자른다."""
    try:
        score = int(raw)
    except (TypeError, ValueError):
        return QA_VERDICT_SCORES[verdict]
    return max(0, min(100, score))


#: 'good' 으로 인정하는 최저 점수 (SYSTEM_PROMPT 규칙 8 과 같은 값).
GOOD_SCORE_MIN = 80

#: good 을 막을 때 남기는 최고 점수. **통과선(QA_PASS_SCORE=70) 위, good 선 아래**다.
#: 70 밑으로 떨어뜨리면 `qa_mastered` 의 3라운드 출구까지 닫혀서 그 질문에 갇힌다 —
#: 우리가 막으려는 것은 «무른 통과» 지 «출구» 가 아니다.
GIST_MISS_SCORE_MAX = GOOD_SCORE_MIN - 1


def _uncovered_parts(data: dict, question: Question) -> list[str]:
    """
    판정이 보고한 요소별 커버리지에서 **안 나온 요소**만 추린다.

    `covered_parts` 는 요소와 **같은 순서·같은 개수**의 참/거짓 배열이다.
    길이가 어긋나면 어느 요소를 가리키는지 알 수 없으므로 통째로 버린다 —
    짐작해서 맞추면 엉뚱한 요소를 빠졌다고 말하게 된다.
    """
    parts = question.answer_gist_parts
    raw = data.get("covered_parts")
    if not parts or not isinstance(raw, (list, tuple)) or len(raw) != len(parts):
        return []
    return [part for part, covered in zip(parts, raw) if not bool(covered)]


def _enforce_good(
    data: dict,
    question: Question,
    verdict: str,
    score: int,
    points: list[str],
    said: str = "",
) -> tuple[str, int, list[str]]:
    """
    good 을 **코드가** 막는다. 골자의 요소가 남았으면 통과시키지 않는다.

    SYSTEM_PROMPT 는 이미 "골자의 요소가 하나라도 안 나왔으면 partial 이다" 라고
    적어 두었는데, 실 LLM 이 지키지 않는 것이 이번에 지적받은 무른 통과다.
    프롬프트로 부탁만 해서는 안 지켜지는 것을 코드가 받는 자리는 이 모듈에 이미
    있다 — `_followup` 이 단계에 안 맞는 문장을 버리는 것과 같은 규율이다.

    두 가지를 본다.

    1. **요소 미달** — `answer_gist_parts` 가 있으면 판정에 `covered_parts`
       (요소 순서대로 true/false)를 함께 받아, 하나라도 false 면 good 을 막는다.
       개수가 안 맞거나 아예 없으면 **판단 근거가 없는 것**이라 손대지 않는다 —
       근거 없이 깎으면 맞힌 사람이 이유 없이 진다.
       LLM 이 안 나왔다고 한 요소라도 누적 답(said)에 낱말 60% 이상이 있으면 나온 것이다 (09-30 §5 — `point_covered`).
    2. **자기모순** — good 인데 missing_points 를 적어 왔다. 규칙 7 이 거기에는
       "통과를 막는 결정적 결손" 만 적으라고 했으므로 둘이 동시에 참일 수 없다.
       결손은 이미 자료 지지·누적 답으로 걸러진 것만 온다 (`_judge_post.clean_points`).

    **둘 다 요소 목록이 있는 질문에만 건다.** 2번을 모든 질문에 걸어 봤는데,
    그건 코드로 검증할 수 없는 «모델 습관» 에 걸린 규칙이었다 — 실 LLM 이 멀쩡한
    답에도 「있으면 더 좋을」 결손을 적으면 모든 질문이 3라운드까지 가서 대화
    호흡이 늘어진다. 요소를 못박은 질문 안에서는 규칙 7 위반이 분명하지만,
    밖에서는 그게 위반인지 조언인지 코드가 가릴 수 없다. 무른 통과를 막으려다
    대화를 망치지 않는다.

    막을 때도 점수는 GIST_MISS_SCORE_MAX 로만 내린다. 되묻기를 한 바퀴 더 돌리는
    것이 목적이고, 3라운드에 닿으면 통과 수준에서 닫힌다 (`qa_mastered`).
    """
    if verdict != "good" or not question.answer_gist_parts:
        return verdict, score, points

    uncovered = [p for p in _uncovered_parts(data, question) if not (said and point_covered(p, said))]
    if not uncovered and not points:
        return verdict, score, points

    # 빠진 요소를 결손 목록 맨 앞에 세운다 — `_followup` 이 물을 지점이 되고,
    # 힌트 사다리 4단(`_hint_close`)이 "아직 안 나온 것" 으로 열어 준다.
    merged = uncovered + [p for p in points if p not in uncovered]
    return "partial", min(score, GIST_MISS_SCORE_MAX), merged


#: 한 칸 더 좁힌 단계. 발표자가 스스로 «이건 모르겠다» 고 밝힌 조각을 그 단계의
#: 넓이로 다시 물으면, 좁혀 주겠다고 해 놓고 같은 벽을 세우는 셈이다.
_TIER_NARROWER = {"probe": "focus", "focus": "converge", "converge": "converge"}


def _content_tokens(text: str) -> list[str]:
    return [t for t in norm_tokens(text or "") if len(t) >= 2]


def _is_generic(token: str) -> bool:
    return any(token.startswith(g) for g in _GENERIC_TOKENS)


def _overlap_count(answer: str, evidence: str, *, drop_generic: bool = False) -> tuple[int, int, int]:
    """
    (답의 **서로 다른** 낱말 가운데 근거와 겹친 수, 답의 낱말 수, 근거의 낱말 수). 조사가 붙은 토큰("알림을"·"알림")은
    앞머리 일치로 같은 낱말로 본다. drop_generic 이면 상투어(_GENERIC_TOKENS)를 양쪽에서 뺀다.
    """
    # 조사를 뗀 줄기로 견준다(`_deck_claims.content_stems`) — 「복구에서」 와 「복구하는」 은 같은 낱말이다 (09-30: 한 줄기만 겹친다고
    # 초점 가드에 걸리던 바꿔 말하기). 세 글자 이상끼리는 앞 두 글자가 같으면 같은 낱말로 본다(`_judge_post._has`).
    a_tokens = list(dict.fromkeys(content_stems(answer)))
    e_all = content_stems(evidence)
    if drop_generic:
        a_tokens = [t for t in a_tokens if not _is_generic(t)]
        e_all = [t for t in e_all if not _is_generic(t)]
    e_tokens = list(dict.fromkeys(e_all))
    hit = sum(1 for a in a_tokens if _stem_in(e_tokens, a))
    # 근거의 크기는 겹친 낱말까지 센다 — 「근거가 얇은가」 는 글의 길이 문제다
    return hit, len(a_tokens), len(e_all)


def _shares_vocabulary(
    answer: str, evidence: str, min_tokens: int = ON_TOPIC_MIN_EVIDENCE_TOKENS, *, drop_generic: bool = False,
    need: int = 1,
) -> bool:
    """
    답변과 근거가 낱말을 need 개 이상 공유하는가(답의 낱말이 그보다 적으면 답의 낱말 수만큼). 둘 중 하나가 비거나
    근거가 얇으면(자료 본문·발화 없이 질문 한 줄뿐) 판단할 수 없어 True 다.
    """
    hit, n_answer, n_evidence = _overlap_count(answer, evidence, drop_generic=drop_generic)
    if not n_answer or n_evidence < min_tokens:
        return True
    return hit >= min(need, n_answer)


#: 「이 질문」 과 겹쳐야 하는 **서로 다른** 내용 낱말 수. 09-30 대화 감사 §3: 「주말엔 보통 친구들이랑 놀러 나가요」 가
#: 「주말」 한 낱말로 초점 가드를 비켜 partial 75 로 통과했다 — 한 낱말은 우연히 겹친다.
ON_TOPIC_FOCUS_NEED = 2


def _enforce_on_topic(
    answer: str, evidence: str, question: Question, verdict: str, score: int, focus: str = ""
) -> tuple[str, int, str]:
    """
    **질문·자료와 아무 낱말도 안 겹치는 답은 wrong 이다.** 코드가 막는다.

    2026-09-10 실측: 물류 창고 재고 회전율 이야기(이 발표와 무관)에 partial 65~75 가
    나왔다. react 는 "스마트폰 시야 밖 두기·메일 닫기까지는 정확합니다" — 답변이
    아니라 프롬프트에 실린 **자료 본문을 답변으로 착각**한 것이다. 자료를 더 실을수록
    이 착각은 커지므로, 규칙 1-1 로 부탁하고 여기서 받는다.

    2026-09-26 실측(실험대): 개념 그래프 질문에 **타깃 시장 이야기**(이 발표의 다른 개념)가 partial 75 — 자료 본문 전체와
    「발표」 가 겹쳐 위 검사를 비켜 갔다. 그래서 `focus`(질문·골자·이 개념의 그래프 자리)와도 대조한다. 이쪽은 wrong 이 아니라
    **통과 못 하는 partial** 로만 내린다 — 낱말 대조는 «다른 이야기» 는 알아도 «틀린 이야기» 는 모른다.

    09-30 대화 감사 §3: 초점 대조는 **서로 다른 내용 낱말 둘 이상**이 겹쳐야 통과다(답의 낱말이 하나면 그 하나). 예전엔 한 낱말만
    겹쳐도 넘어갔고 8토큰 미만 답은 아예 건너뛰어, 한 단어·딴 얘기 답이 통과선을 넘었다. 이제 짧은 답에도 건다.

    마지막 값은 어느 가드가 걸렸는지다 — "" · "off_topic"(자료와도 무관 → wrong) · "focus_miss"(이 질문만 벗어남 → partial ≤ 65).
    결손(missing_points)은 건드리지 않는다 — 가드 사유는 `guard_reason` 으로 따로 간다 (§6).
    """
    if not _shares_vocabulary(answer, evidence):
        return "wrong", min(score, OFF_TOPIC_SCORE_MAX), "off_topic"
    if focus and not _shares_vocabulary(answer, focus, ON_TOPIC_MIN_FOCUS_TOKENS, drop_generic=True,
                                        need=ON_TOPIC_FOCUS_NEED):
        demoted = "partial" if verdict in ("good", "partial") else verdict
        return demoted, min(score, FOCUS_MISS_SCORE_MAX), "focus_miss"
    return verdict, score, ""


def _trap_agreed(data: dict, question: Question, answer: str, deck: Deck | None) -> bool:
    """
    함정 질문에 **전제를 받아들였는가.** 함정 표시(`question.trap`)만으로는 정하지 않는다.

    09-29 두 덱 기준선: F-08 이 두 덱의 주제 질문(5분 트랙)에 매번 trap=True 를 붙였는데 질문 문장에 거짓 전제가
    있는 경우는 0건이었다. LLM 은 「바로잡은 전제가 없다」 며 premise_corrected=false 를 줬고, 예전 가드는 그 값만 보고
    골자를 그대로 옮긴 답 4/4 와 자료대로 한 정답(수익률 d)까지 wrong 35 로 내렸다. 사용자는 바로잡을 전제가 없는
    질문에 「질문의 전제부터 확인해 보세요」 를 받았다. F-08 이 표시를 고쳐도 판정은 표시가 틀린 경우를 견뎌야 한다.

    동의로 보는 것 (하나라도):
    1. 「네, 맞아요」「질문한 대로예요」 처럼 **받아들인다고 말함** — 바로잡는 말이 없을 때. premise_corrected 가 없어도
       본다 (09-29 수익률 rec: LLM 이 값을 안 줘서 함정 가드를 건너뛰고 무관 문구가 나갔다).
    2. 질문에만 있고 자료·기대 답에는 없는 **숫자를 되풀이** — 거짓 전제의 숫자를 받아들인 것이다.
    3. LLM 이 premise_corrected=false 라고 했고, **골자가 전제를 바로잡는 답이며**(`gist_corrects_premise` — 아니면
       거짓 전제가 없는 질문이다), 답이 그 기대 답(골자·자료 인용)의 사실을 말하지도 않았다
       (기대 답의 낱말·숫자를 충분히 말한 답은 자료대로 답한 것이다 — `states_reference`).
    """
    if not question.trap:
        return False
    tp = question.trap_premise
    if tp is not None:
        # 전제를 코드가 만들었으면(qa/trap) 무엇이 틀린 말이고 무엇이 자료의 사실인지 안다 — 짐작하지 않고 단서로 본다.
        stance = premise_stance(answer, tp)
        if stance:
            return stance == "agree"
        # 단서도 반박도 동의도 없는 답: 질문·전제·자료 사실과 낱말이 하나도 안 겹치면 딴 이야기다 — 무관 가드 몫으로 넘긴다.
        # 낱말이 아예 없는 답(숫자뿐)도 동의로 짐작하지 않는다 — 09-30 실측: 「8.7」 이 낱말 0개라 「겹친다」 로 읽혀 함정 동의 30.
        hit, n_answer, _ = _overlap_count(answer, " ".join([question.question, tp.premise, tp.fact, question.label or ""]))
        if not n_answer or not hit:
            return False
        corrected = data.get("premise_corrected")
        return corrected is not None and not bool(corrected)
    reference = " ".join([question.answer_gist or "", question.evidence_quote or "", *question.answer_gist_parts])
    if explicit_agreement(answer):
        return True
    if deck is not None and echoes_unsupported_number(answer, question.question, deck, reference):
        return True
    corrected = data.get("premise_corrected")
    if corrected is None or bool(corrected):
        return False
    # 골자가 전제를 바로잡지 않는다 = 질문에 거짓 전제가 없다(함정 표시가 틀렸다). 바로잡을 것이 없으니 흠이 아니다.
    # 09-29 벤치 held-out: 판정 불일치 10건 중 5건이 이 경우였다.
    if not gist_corrects_premise(question.answer_gist, question.question):
        return False
    return not states_reference(answer, question.question, reference)


def _enforce_trap(
    data: dict, question: Question, verdict: str, score: int,
    answer: str = "", deck: Deck | None = None,
) -> tuple[str, int, bool]:
    """
    함정 질문에 **전제를 받아들인 답은 통과하지 못한다.** 코드가 막는다.

    규칙 4 는 처음부터 "동의했으면 wrong" 이었는데 실 LLM 은 "네, 맞습니다" 에
    partial 60~70 을 줬다 (2026-09-10 실측). 무엇을 동의로 보는지는 `_trap_agreed` —
    함정 표시만 보고 내리지 않는다 (09-29 기준선).
    """
    if not _trap_agreed(data, question, answer, deck):
        return verdict, score, False
    return "wrong", min(score, TRAP_AGREED_SCORE_MAX), True


def _enforce_deck(
    answer: str, deck: Deck | None, verdict: str, score: int, question: str = ""
) -> tuple[str, int, Conflict | None]:
    """
    **자료와 수치·표 서열·방향·부정이 어긋난 답은 통과하지 못한다.** 코드가 막는다.

    09-29 두 덱 기준선: 그럴듯한 오답 6건 중 3건이 통과했다 — 요인별 %p 를 서로 바꿔 붙인 답(partial 75),
    자료 표에서 더 낮은 쪽을 「더 높다」 고 한 답(partial 70, react 「…부분은 정확해요」), 자료 6장과 정반대인 답.
    규칙 8 은 「요지는 맞고 근거만 얕다」 에 70~79 를 주라 하고 통과선이 70 이라, 같은 주제의 낱말로 틀린 사실을
    말하면 통과했다. 무관 가드는 낱말이 **겹치면** 비켜 간다.

    어긋남은 `_deck_claims.conflicts` 가 **구조로만** 잡는다(숫자 짝·단일 값 표의 서열·강한 줄 일치에서의 방향/부정).
    잘못 잡으면 맞힌 사람이 진다 — 그래서 wrong 이 아니라 **통과 못 하는 partial** 까지만 내리고 되묻기를 남긴다.
    LLM 이 이미 wrong 이면 그대로 둔다. 3라운드까지 가드만 막고 있으면 질문은 닫힌다 (`qa_mastered` guard_blocked).
    """
    if deck is None or deck.empty or verdict == "unknown":
        return verdict, score, None
    found = conflicts(answer, deck, question)
    if not found:
        return verdict, score, None
    first = found[0]
    demoted = "partial" if verdict in ("good", "partial") else verdict
    return demoted, min(score, DECK_CONFLICT_SCORE_MAX), first


#: 3라운드에서 **가드만** 통과를 막고 있을 때 여는 출구에 드는 가드 — 글자 대조라 틀릴 수 있는 것들.
#: 함정 동의·무관(off_topic)은 들지 않는다 — 그건 답이 질문에 답하지 않은 것이라 출구가 「답 보기」 다.
_ESCAPABLE_GUARDS = ("deck", "self_opposed", "focus_miss", "restated", "reason")
#: 한 단어 답의 상한 (§3). 통과선(70) 아래 — 「규칙」「연속성」 한 낱말이 good 80 으로 질문을 닫았다.
SHORT_ANSWER_WORDS = 3
SHORT_ANSWER_SCORE_MAX = 65
#: 「모르겠어요」 되물음(둘 중 하나·빈칸)에 고른 답의 상한 — 원래 질문의 답이 아니라 되물음의 답이다 (§3). 칩 「항목」 이 good 85 로 닫았다.
CHOICE_ANSWER_SCORE_MAX = 69
#: 함정 전제를 **코드 단서로** 바로잡은 답이 LLM 에게 wrong 을 받았을 때 끌어올리는 점수 (§2 — 「끊는」「8.7」 이 wrong 30).
TRAP_CORRECTED_SCORE_MIN = 60
_TRAP_CORRECTED_REACT = "전제를 바로잡은 방향은 맞아요. 자료의 어느 부분에서 그렇게 말하는지 한 문장만 더 붙여 보세요."
_TRAP_NEUTRAL_REACT = "질문이 말한 내용이 자료와 같은지부터 확인해 보세요."
_SHORT_REACT = "한 단어로는 판단하기 어려워요. 자료의 말로 한 문장만 이어서 말해 보세요."
_CHOICE_REACT = "고른 쪽은 자료와 맞아요. 이제 원래 질문에 자기 말로 한 문장 답해 보세요."
_ABSENT_GOOD_REACT = "자료에 없다는 걸 짚은 게 맞아요. 자료가 말하는 범위 안에서 잘 답했어요."
_ABSENT_SHORT_REACT = "자료에 없다는 건 맞아요. 자료가 말하는 범위에서 한 문장만 더 붙여 보세요."
#: 3라운드 출구 — 진짜 설득과 구분해서 말한다 (§2·§10).
_ROUNDS_CLOSE_REACT = "요지는 잡았어요. 세 번째 답이라 이 질문은 여기서 마무리할게요."
_GUARD_CLOSE_REACT = "세 번째 답이라 여기서 마무리할게요. {where}과 한 번 더 맞춰 볼 부분은 결과에 다시 볼 곳으로 남겨 둘게요."
_GUARD_CLOSE_SUMMARY = "{label} — 자료와 맞춰 볼 곳을 남기고 넘어갔어요."
_PASS_REACT = "네, 그 설명이면 충분해요."


#: 문장으로 안 닫힌 짧은 react — 09-30 실측: LLM react 가 「답변에서」 네 글자로 와서 그대로 말풍선이 됐다.
_REACT_FRAGMENT_MAX = 15
_SENTENCE_CLOSED_RE = re.compile(r"(?:요|다|죠|네|[.!?…»」”'\"])\s*$")
#: react 문장이 골자 낱말을 이만큼 담았고 발표자는 그 절반도 말하지 않았다면 **정답을 읽어 준** 것이다 (규칙 3 — 09-30 실측
#: 수익률 Q2: 절반 답에 react 가 골자 문장을 그대로 옮겼다).
GIST_ECHO_MIN = 0.7


def _gist_echo(sentence: str, gist: str, said: str) -> bool:
    g = [x for x in dict.fromkeys(content_stems(gist))]
    if len(g) < 4:
        return False
    s_stems = content_stems(sentence)
    in_sentence = [x for x in g if _stem_in(s_stems, x)]
    if len(in_sentence) < GIST_ECHO_MIN * len(g):
        return False
    said_stems = content_stems(said)
    return sum(1 for x in in_sentence if _stem_in(said_stems, x)) < 0.5 * len(in_sentence)


def _clean_react(react: str, said: str, gist: str = "") -> str:
    """LLM react 를 다듬는다 — 내부 표기·3인칭(scrub) → 높임 문장 빼기 → 표기 지적 빼기 → 말하지 않은 것 칭찬 빼기 →
    골자 읽어 주기 빼기 (§3·§7·§9). 문장으로 안 닫힌 짧은 조각이 남으면 버린다."""
    out = _drop_honorific(scrub(react))
    out = keep_sentences(out, talks_notation)
    out = keep_sentences(out, lambda s: praise_ungrounded(s, said))
    if gist:
        out = keep_sentences(out, lambda s: _gist_echo(s, gist, said))
    if len(out) <= _REACT_FRAGMENT_MAX and not _SENTENCE_CLOSED_RE.search(out):
        return ""
    return out


def _clean_summary(summary: str, deck: Deck | None, question: Question, tp=None, leak_guard: bool = False) -> str:
    """총평을 다듬는다. 높임·표기 지적·자료와 어긋난 주장·(안 풀린 함정의) 정답 누설이 든 문장은 뺀다 (§7·§9)."""
    out = _drop_honorific(scrub(summary))
    out = keep_sentences(out, talks_notation)
    if deck is not None and not deck.empty:
        out = keep_sentences(out, lambda s: bool(conflicts(s, deck, question.question)))
    if leak_guard and tp is not None:
        out = keep_sentences(out, lambda s: leaks_fact(s, tp))
    return out


def _answered_coach(question: Question, turns: list[QaTurn]) -> bool:
    """
    이번 답이 「모르겠어요」 코칭(둘 중 하나·빈칸)에 대한 답인가 — 이 질문의 **바로 앞 턴이 포기**였다.
    프론트는 선택지 칩을 누르면 그 낱말을 답칸에 넣어 보낼 뿐이라 서버는 칩인지 모른다. 앞 턴이 포기였으면 코칭이 방금 되물었다.
    """
    asked_id = (question.id or "").strip()
    mine = [t for t in turns if (t.question_id or "").strip() == asked_id] if asked_id else list(turns)
    return bool(mine) and bool(mine[-1].gave_up)


def _normalize(
    data: dict,
    question: Question,
    model: str,
    round_no: int = 1,
    *,
    followup_tier: str = "",
    forced_point: str = "",
    answer: str = "",
    evidence: str = "",
    focus: str = "",
    deck: Deck | None = None,
    probed: tuple[str, ...] | list[str] = (),
    prior_answers: list[str] | tuple[str, ...] = (),
    answered_coach: bool = False,
    anchor_text: str = "",
) -> QaJudgement:
    """
    - verdict 가 enum 밖이면 QA_VERDICT_FALLBACK ('unknown')
    - score 없으면 verdict 기본값, 있으면 clamp
    - node_id 는 **질문에서 승계** — LLM 이 다른 값을 줘도 무시한다
      (조인 키가 흔들리면 리포트가 엉뚱한 개념에 총평을 붙인다)
    - react·summary_sentence 는 비면 결정적 문구로 채운다
    - round_no·probe_tier 는 **코드가 정한다** — LLM 이 보낸 값은 읽지 않는다.
      대화의 출구(mastered)가 여기 달려 있어서, 모델이 흔들면 루프가 흔들린다.

    09-30 대화 감사로 더한 것 (전부 구조 규칙 — `_judge_post`):
    - 결손: 명사구로 다듬고, 자료로 안 받쳐지는 것(§4)·누적 답에 이미 나온 것(§5)·표기 지적·근거 장에 없는 인용(§7)은 뺀다.
      가드 사유는 결손에 끼우지 않고 `guard_reason` 으로 (§6).
    - 한 단어 답은 65, 「모르겠어요」 되물음에 고른 답은 69 상한 (§3). 코드 단서로 함정을 바로잡은 답은 wrong 에서 끌어올린다 (§2).
    - 자료 밖을 묻는 질문에 「자료에 없다」 고 밝히고 범위 안에서 답했으면 받아 준다 (§4).
    - 안 풀린 함정 질문의 react·되물음·결손·총평에서 정답 단서가 새면 막는다 (§7).
    - 3라운드에 가드만 막고 있으면 닫는다 — `guard_blocked` (§2). 닫힌 질문은 결손을 비우고 「다만…」 을 떼거나 결정적 문구로 (§5).
    """
    # 표기 정규화 — "Good"·" partial " 을 그대로 enum 대조하면 unknown 으로
    # 떨어지는데 score 는 살아 있어 '판정 보류' 배지를 달고 통과하는 모순이 된다.
    verdict = str(data.get("verdict", "") or "").strip().lower()
    if verdict not in QA_VERDICTS:
        verdict = QA_VERDICT_FALLBACK

    raw_score = data.get("score")
    score = QA_VERDICT_SCORES[verdict] if raw_score is None else _clamp_score(raw_score, verdict)
    llm_verdict, llm_score = verdict, score
    prior = [p for p in (prior_answers or []) if (p or "").strip()]
    said = " ".join([*prior, answer or ""]).strip()

    raw_points = [str(p).strip() for p in (data.get("missing_points") or []) if str(p).strip()]
    points, unsupported = clean_points(raw_points, deck=deck, said=said, anchor_text=anchor_text,
                                       question=question.question)
    # 스스로 «이건 모르겠다» 고 밝힌 조각은 **반드시** 결손 목록에 오른다.
    # 여기 없으면 힌트 사다리 4단이 그걸 열어 주지 못해서, 모른다고 말한 보람이
    # 없는 대화가 된다. LLM 이 알아서 적었으면 그 자리를 맨 앞으로 올리기만 한다.
    if forced_point:
        points = [forced_point] + [p for p in points if p != forced_point]

    # 무른 통과는 여기서 잘린다. **등급·점수·결손만** 코드가 되돌린다 —
    # 문장은 LLM, 계약은 코드 (모듈 원칙). react·summary 폴백보다 앞에 둬야
    # 등급이 뒤집힌 판정에 "충분합니다" 라는 good 폴백이 붙지 않는다.
    verdict, score, points = _enforce_good(data, question, verdict, score, points, said=said)
    tp = question.trap_premise if question.trap else None
    # 코드가 만든 전제면 답이 어느 쪽 단서를 말했는지 안다 — 누적 답으로 본다(앞 턴에 동의했다가 이번에 바로잡은 답도 바로잡은 것이다).
    stance = premise_stance(said, tp) if tp is not None else ""
    # 함정 동의가 먼저다 — "네, 맞아요" 는 질문에 답한 것이라 무관 가드가 볼 일이 아니다 (09-26 실측: 무관 문구가 먼저 붙었다).
    verdict, score, trap_agreed = _enforce_trap(data, question, verdict, score, answer, deck)
    guard, guard_reason = ("trap", "질문의 전제가 자료와 다르다는 점") if trap_agreed else ("", "")
    conflict: Conflict | None = None
    reason_missed = False
    # 함정 전제를 되뇌며 바로잡은 답(「82%가 아니라 41%예요」)의 전제 절은 자료 대조·자기모순 검사에서 뺀다 — 그 숫자는
    # 답의 주장이 아니라 질문을 옮긴 것이다.
    claimed = without_premise(answer, tp) if tp is not None else answer
    # 탐침이 따지는 자료 줄을 되풀이·수긍만 한 답 (09-29 P5 최종 평가 문제 1) — 자료와 어긋난 곳이 없어서 아래 가드는 못 잡는다.
    restated = "" if trap_agreed else restates_probe(answer, question)
    if restated:
        guard, guard_reason = "restated", f"질문이 묻는 것: {RESTATE_POINT[restated]}"
        if verdict in ("good", "partial"):
            verdict = "partial"
        score = min(score, PROBE_RESTATE_SCORE_MAX)
        data = {**data, "followup": RESTATE_FOLLOWUP[restated]}
    if not trap_agreed and not restated:
        # 자료와 어긋난 답은 이미 「이 질문」 에 답한 것이다 — 무관 가드보다 먼저 보고, 걸리면 무관 가드는 건너뛴다.
        verdict, score, conflict = _enforce_deck(claimed, deck, verdict, score, question.question)
        if conflict is not None:
            guard, guard_reason = "deck", f"자료 {conflict.slide_no}장과 어긋난 곳: {conflict.what}"
        elif stance != "correct" and (missed := _reason_missed(answer, question)) is not None:
            # 근거 질문에 **같은 장의 배경**만 댄 답 (qa/reason) — 질문을 벗어난 게 아니라 이유를 안 댄 것이다. 무관 가드보다
            # 먼저 본다: 초점 가드가 먼저 걸리면 「질문에서 멀어요」 가 나가는데, 그 사람에게 필요한 말은 「이유를 대 보세요」 다
            # (09-30 qa/int3 합류 — qa/convo 가 초점 가드를 낱말 2개로 조이자 배경 답이 무관으로 떨어졌다).
            # 사유는 결손 목록이 아니라 guard_reason 으로 보낸다 (qa/convo §6).
            verdict = "partial" if verdict == "good" else verdict
            score, reason_missed = min(score, REASON_MISS_SCORE_MAX), True
            guard, guard_reason = "reason", f"질문이 묻는 것: 결론을 받치는 이유 (자료 {missed.slide_no}장)"
            data = {**data, "followup": _REASON_MISS_FOLLOWUP.format(no=missed.slide_no)}
        elif stance != "correct":
            # 코드 단서로 전제를 바로잡은 답은 「이 질문」 에 답한 것이다 — 한 단어(「끊는」)여도 초점 가드가 볼 일이 아니다.
            verdict, score, topic = _enforce_on_topic(answer, evidence, question, verdict, score, focus)
            if topic:
                guard, guard_reason = topic, f"질문이 묻는 것: {question.label or question.node_id}"
    # 판정이 스스로 「답과 반대 명제」 를 정답으로 들고 있으면서 통과를 준 자기모순 (09-29 벤치 held-out 오답 2건).
    # 탐침이 따지는 줄을 뒤집은 절은 빼고 본다 — 판정 react 가 그 줄을 되풀이해도 그건 정답이 아니다 (09-29 P5 health 골자 60).
    if not guard and qa_passed(verdict, score) and claimed:
        # 다듬기 전 결손으로 본다 — 「…를 줄인다는 근거가 빠져」 는 답이 「늘린다」 고 한 것과 반대 명제를 판정이 들고 있다는 증거다.
        said_by_judge = " ".join([*raw_points, *points, str(data.get("react", "") or "")])
        if opposes(claimed, said_by_judge, exempt=tuple(probed)):
            verdict, score, guard = "partial", min(score, SELF_OPPOSED_SCORE_MAX), "self_opposed"

    # 코드 단서로 바로잡은 함정 답을 LLM 이 wrong 으로 둔 경우 (§2) — 바로잡았으니 틀린 답이 아니다. 통과 여부는 LLM·상한이 정한다.
    trap_lifted = False
    if stance == "correct" and not guard and verdict in ("wrong", "unknown"):
        verdict, score, trap_lifted = "partial", max(score, TRAP_CORRECTED_SCORE_MIN), True

    # 질문이 자료 밖을 묻는데(측정 방법·순위…) 「자료에 없다」 고 밝히고 범위 안에서 답했다 (§4). 남은 결손이 없을 때만.
    absent = ""
    if (not guard and not points and tp is None and says_not_in_deck(said)
            and (unsupported or says_not_in_deck(question.answer_gist)
                 or beyond_deck_terms(question.question, deck, question.label))):
        if content_word_count(said) >= SHORT_ANSWER_WORDS:
            verdict, score, absent = "good", max(score, GOOD_SCORE_MIN), "good"
        else:
            verdict, score, absent = "partial", max(min(score, SHORT_ANSWER_SCORE_MAX), 55), "short"

    # 한 단어 답·되물음에 고른 답은 질문을 닫지 못한다 (§3).
    capped = ""
    if not absent and verdict in ("good", "partial") and content_word_count(said) < SHORT_ANSWER_WORDS:
        if verdict == "good" or score > SHORT_ANSWER_SCORE_MAX:
            capped = "short"
        verdict, score = "partial", min(score, SHORT_ANSWER_SCORE_MAX)
    if (not absent and answered_coach and not prior and verdict in ("good", "partial")
            and score > CHOICE_ANSWER_SCORE_MAX):
        verdict, score, capped = "partial", CHOICE_ANSWER_SCORE_MAX, "choice"

    # 안 풀린 함정 질문 — 정답 단서가 react·결손·되물음·총평으로 새면 안 된다 (§7). 바로잡았거나 통과했으면 볼 일이 없다.
    leak_guard = tp is not None and stance != "correct" and not qa_passed(verdict, score)
    if leak_guard:
        points = [p for p in points if not leaks_fact(p, tp)]

    react = _clean_react(str(data.get("react", "") or ""), said, question.answer_gist) or _REACT_BY_VERDICT[verdict]
    # 가드가 등급을 뒤집었으면 LLM 의 react 는 그 등급과 어긋난 문장이다 — 코드 문구로.
    if trap_agreed:
        react = _TRAP_AGREED_REACT
    elif restated:
        react = RESTATE_REACT[restated]
    elif conflict is not None:
        react = _DECK_CONFLICT_REACT.format(no=conflict.slide_no, what=conflict.what)
    elif guard == "self_opposed":
        react = _SELF_OPPOSED_REACT
    elif reason_missed:
        react = _REASON_MISS_REACT.format(no=(question.basis.reason[0].slide_no if question.basis else 0))
    elif guard == "off_topic":
        react = _OFF_TOPIC_REACT.format(label=question.label or "이 개념")
    elif guard == "focus_miss":
        react = _FOCUS_MISS_REACT.format(label=question.label or "이 개념")
    elif trap_lifted:
        react = _TRAP_CORRECTED_REACT
    elif absent:
        react = _ABSENT_GOOD_REACT if absent == "good" else _ABSENT_SHORT_REACT
    elif capped == "short":
        react = _SHORT_REACT
    elif capped == "choice":
        react = _CHOICE_REACT
    elif verdict == "wrong" and _PRAISE_RE.search(react):
        react = _REACT_BY_VERDICT[verdict]
    if leak_guard and leaks_fact(react, tp):
        react = _TRAP_AGREED_REACT if trap_agreed else _TRAP_NEUTRAL_REACT

    summary = _clean_summary(str(data.get("summary_sentence", "") or ""), deck, question, tp, leak_guard)
    if conflict is not None:
        summary = _DECK_CONFLICT_SUMMARY.format(label=question.label or "이 개념", no=conflict.slide_no)
        # LLM 의 후속 질문은 틀린 주장을 받아들인 채 다음을 묻는다 — 어긋난 곳을 되묻는 코드 문장으로.
        data = {**data, "followup": _DECK_CONFLICT_FOLLOWUP.format(no=conflict.slide_no, what=conflict.what)}

    round_no = max(1, int(round_no or 1))
    # 3라운드에 **가드만** 막고 있다(LLM 은 통과였다) — 글자 대조가 틀렸을 수 있어 질문을 가둬 두지 않는다 (§2).
    guard_blocked = (round_no >= QA_MAX_ROUNDS and guard in _ESCAPABLE_GUARDS
                     and qa_passed(llm_verdict, llm_score) and not qa_passed(verdict, score))
    mastered = qa_mastered(verdict, score, round_no, guard_blocked)
    if mastered:
        # 닫힌 질문에 「빠진 것」 을 달면 「부분 인정 ✓」 옆에서 또 요구하는 화면이 된다 (§5).
        points = []
        if guard_blocked:
            no = conflict.slide_no if conflict is not None else question.evidence_slide_no
            react = _GUARD_CLOSE_REACT.format(where=f"자료 {no}장" if no else "자료")
            summary = _GUARD_CLOSE_SUMMARY.format(label=question.label or "이 개념")
        elif verdict != "good":
            react = _ROUNDS_CLOSE_REACT
            summary = trim_missing_talk(summary)
        else:
            react = trim_missing_talk(react) or _PASS_REACT
            summary = trim_missing_talk(summary) or summary
    if not summary:
        summary = _SUMMARY_BY_VERDICT[verdict].format(
            label=question.label or question.node_id or "이 개념"
        )

    judgement = QaJudgement(
        question_id=question.id,
        node_id=question.node_id,
        verdict=verdict,
        score=score,
        react=cap_length(react),
        summary_sentence=summary,
        missing_points=points,
        model=model,
        round_no=round_no,
        # 정복했으면 되물을 일이 없다. 단계를 남겨 두면 화면이 「3차 확인」 이라고
        # 써 놓고 다음 질문으로 넘어가는 모순이 된다.
        # probe_tier 는 **라운드 그대로** 둔다 — 화면이 「2차 확인」 을 세는 축이다.
        # 좁히는 것은 followup 의 모양뿐이라 그 인자만 따로 받는다.
        probe_tier="" if mastered else qa_probe_tier(round_no),
        followup=_followup(
            data, question, points, mastered,
            followup_tier or qa_probe_tier(round_no),
            verdict=verdict, guard=guard, tp=tp, leak_guard=leak_guard,
        ),
        guard_reason=guard_reason,
        guard_blocked=guard_blocked,
    )
    # 힌트는 판정을 보고 만든다 — 사용자가 실제로 빠뜨린 것에 반응해야 하기 때문이다.
    # 판정에 함께 실어 보내면 프론트가 추가 왕복 없이 즉시 보여 줄 수 있다.
    judgement.hints = build_hint_ladder(question, judgement)
    return judgement


_HAEYO_FIELDS = ("react", "summary_sentence", "followup", "explanation")


def _haeyo_data(data: dict) -> dict:
    """LLM 응답의 문장 필드를 해요체로 푼다(_speech.to_haeyo). 2026-09-26 실측: 총평·해설이 매번 「~했습니다」 였다.
    09-30 대화 감사 §9: 해라체 총평(「…설명했다.」) 7건 — `plain_to_haeyo` 로 문장 끝 해라체도 푼다.
    새 dict 를 돌려준다 — 원본은 건드리지 않는다."""
    out = dict(data)
    for k in _HAEYO_FIELDS:
        v = out.get(k)
        if isinstance(v, str) and v:
            # 합쇼체 끝 어미는 to_haeyo, 문장 가운데 높임(「추정하신」「찾고 계신」)은 _plain 이 푼다 (09-29 기준선).
            out[k] = plain_to_haeyo(to_haeyo(_plain(v)))      # 높임을 먼저 푼다 — 「말씀하셨습니다」 → 「말했습니다」 → 「말했어요」
    return out


def _clip(text: str) -> str:
    """QA_TEXT_MAX 로 자른다 (f08_questions 와 같은 규칙)."""
    stripped = (text or "").strip()
    if len(stripped) <= QA_TEXT_MAX:
        return stripped
    return stripped[: QA_TEXT_MAX - 1].rstrip() + "…"


def _where_slide(question: Question) -> str:
    """「자료 N장을」 — 근거 장이 없으면 「자료를」."""
    no = question.evidence_slide_no or (question.slide_nos[0] if question.slide_nos else 0)
    return f"자료 {no}장을" if no else "자료를"


#: 결손이 없는데 되물어야 할 때 — 근거 장을 가리킨다. 09-30 §6: 틀린 답에 「환경 — 이걸 뒷받침할 근거를 하나만 더 들어 주세요」
#: (틀린 답을 뒷받침하라는 말)가 나갔다. 좁힌 단계에서도 쓸 수 있게 열린 물음 낱말(무엇·어떻게)을 안 쓴다.
_FOLLOWUP_SLIDE = "{where} 다시 보면, {label}에 대해 뭐라고 하나요? 한 문장으로 말해 볼래요?"
#: 초점·무관 가드가 걸렸을 때 — 질문이 무엇을 묻는지 다시 세운다 (가드 사유를 되물음 틀에 끼우지 않는다, §6).
_FOLLOWUP_FOCUS = "{label}에 대한 질문이에요. {where} 다시 보고, 그 장이 {label}에 대해 하는 말을 한 문장으로 말해 볼래요?"
_FOLLOWUP_TRAP = "질문이 말한 내용이 {where} 적힌 것과 같은지부터 짚어 볼래요?"


def _followup(
    data: dict,
    question: Question,
    points: list[str],
    mastered: bool,
    tier: str,
    *,
    verdict: str = "",
    guard: str = "",
    tp=None,
    leak_guard: bool = False,
) -> str:
    """
    되물을 후속 질문. **정복(mastered)했을 때만 비운다.**

    예전에는 `qa_passed` 로 잘랐다. 그런데 판정 규칙 8 이 "요지는 맞고 근거만
    얕다" 를 70~79 로 매기게 하고 그 구간이 곧 통과라, **가장 흔한 답변이
    되묻기를 통째로 건너뛰었다.** 절반 맞힌 사람에게 한 걸음 더 묻는 것이
    이 서비스의 핵심 로직인데 그 로직이 실행되지 않고 있었던 것이다.

    정복한 답에까지 질문을 남기면 반대 방향의 모순이 된다 — "설득 완료" 라고
    해 놓고 또 묻는 화면. 그래서 자르는 기준을 없앤 게 아니라 옮겼다.

    폴백도 단계를 따른다. LLM 이 빠뜨렸다고 1라운드짜리 열린 질문을 3라운드에
    내면, 좁혀 주겠다고 해 놓고 같은 벽을 다시 세우는 셈이다.

    그리고 **LLM 이 쓴 문장도 단계에 안 맞으면 버린다.** 프롬프트로 부탁만
    해서는 안 좁혀지는 것을 실측으로 확인했다 (_OPEN_QUESTION_RE 주석 참고).
    무엇을 물을지는 코드가 정하고 LLM 은 문장만 쓴다 — 문장이 계약을 안 지키면
    코드가 쓴다. 이 모듈이 verdict·score 에 하는 것과 같은 일이다.

    09-30 대화 감사 §6·§7: 가드가 걸린 답(함정 동의·초점·무관)은 가드의 되물음이 먼저다 — 가드 사유 문자열을 틀에 넣지 않는다.
    결손이 없으면(틀린 답 포함) 근거 장을 가리킨다. 안 풀린 함정에서 정답 단서가 든 LLM 문장은 버린다.
    """
    if mastered:
        return ""

    label = question.label or "이 개념"
    where = _where_slide(question)
    if guard == "trap":
        no = question.evidence_slide_no or (question.slide_nos[0] if question.slide_nos else 0)
        return _clip(trap_narrow(tp) if tp is not None else _FOLLOWUP_TRAP.format(where=f"자료 {no}장에" if no else "자료에"))
    if guard in ("off_topic", "focus_miss"):
        return _clip(_FOLLOWUP_FOCUS.format(label=label, where=where))

    point = points[0] if points else ""
    written = _clip(scrub(str(data.get("followup", "") or "")))
    if _HONORIFIC_RE.search(written) or _PLACEHOLDER_RE.search(written) or talks_notation(written):
        written = ""
    if written and leak_guard and tp is not None and leaks_fact(written, tp):
        written = ""
    # probe(1라운드)는 열린 질문이 맞는 모양이라 그대로 쓴다.
    if written and (tier == "probe" or _is_narrow(written)):
        return written
    if leak_guard and tp is not None:
        return _clip(trap_narrow(tp))
    if not point:
        return _clip(_FOLLOWUP_SLIDE.format(where=where, label=label))

    shaped = _FOLLOWUP_BY_TIER.get(tier)
    if shaped:
        return _clip(shaped.format(point=point))
    return _clip(_FOLLOWUP_BY_POINT.format(point=point))


# ---------------------------------------------------------------------------
# 막힘 코칭 — "모르겠어요" 에 응한다
#
# 판정과 별도의 경로다. 포기한 사람에게 점수를 매기는 것은 의미가 없고,
# 되묻기만 반복하면 같은 질문에 갇힌다. 대신 한 단계 끌어주고, 그래도 막히면
# 해설하고 넘어간다.
# ---------------------------------------------------------------------------

#: 포기로 볼 답변의 최대 길이. 짧을수록 안전하다 — 놓쳐도 사용자에게는
#: 「모르겠어요」 버튼이라는 명시적 출구가 있지만, 오탐하면 진짜 답변이 묻힌다.
GIVE_UP_MAX_CHARS = 15

#: 포기 표현.
_GIVE_UP_RE = re.compile(
    # 「패스·pass·skip」 은 낱말째일 때만 — 09-30 레드팀: 「패스트푸드」「pass rate」 가 포기로 읽혔다.
    r"모르겠|모름|잘\s*몰라|생각\s*안\s*나|기억\s*안\s*나|패스(?=$|[\s.!?요할])|스킵|\bpass\b(?!\s*rate)|\bskip\b",
    re.I,
)

#: 시도한 흔적. 하나라도 있으면 포기가 아니다 —
#: "잘 모르겠는데 지연 시간 아닐까요?" 는 답변이지 포기가 아니다.
_ATTEMPT_RE = re.compile(r"지만|는데|근데|그런데|다만|아닐까|같아요|같습니다|듯")


def looks_stuck(answer: str | None) -> bool:
    """
    '모르겠다' 류의 포기 의사인지. **규칙은 코드가 정한다** — 이 모듈의 원칙대로
    의도 판별을 LLM 에 맡기지 않는다 (왕복 비용도, 비결정성도 늘기 때문이다).

    짧고 · 시도한 흔적이 없고 · 포기 표현이 있을 때만 참이다.
    빈 답변은 _empty_answer 가 따로 다루므로 여기서 가로채지 않는다.
    """
    text = (answer or "").strip()
    if not text or len(text) > GIVE_UP_MAX_CHARS:
        return False
    if _ATTEMPT_RE.search(text):
        return False
    return bool(_GIVE_UP_RE.search(text))


#: 부분 포기 절을 가르는 구분자. 한국어 답변은 «X는 모르겠고, Y는 …» 처럼
#: 연결어미로 이어 붙는다 — 문장 부호만 보면 한 덩어리로 뭉쳐서 못 가른다.
_CLAUSE_SPLIT_RE = re.compile(
    r"(?<=[고요다지만은])\s*[,·]\s*|\s*[.?!]\s+|\n+|(?<=는데)\s+|(?<=지만)\s+"
)

#: 포기 절을 뺀 나머지가 이만큼은 돼야 «부분» 포기다. 이보다 짧으면 답한 것이
#: 없다는 뜻이라 통째 포기와 같다 — 그쪽은 「모르겠어요」 버튼과 코칭 경로가 받는다.
GIVE_UP_REMAINDER_MIN = 8

#: 과녁이 될 수 없는 지시어. 「이건」 을 결손 목록에 올리면 화면이 «아직 안 나온 것:
#: 이건» 이라고 쓴다 — 무엇을 열어 주는지 아무도 모르는 힌트가 된다.
_VAGUE_TOPICS = frozenset({
    "이건", "그건", "저건", "이거", "그거", "저거", "이것", "그것", "저것",
    "이 부분", "그 부분", "나머지", "뒤", "앞", "거기",
})

#: 포기 표현에서 **주제만** 남기기 위해 걷어 내는 꼬리.
_GIVE_UP_TAIL_RE = re.compile(
    # 긴 조사부터. 짧은 「는」 이 먼저 걸리면 "…에 대해서" 가 주제에 남는다.
    r"(에\s*대해서?는?|에\s*대한|쪽은|부분은|까지는|은|는|이|가|을|를)?\s*"
    r"(잘\s*)?(모르겠|모름|몰라|생각\s*안\s*나|기억\s*안\s*나)[가-힣\s]*$"
)


def partial_giveup_topic(answer: str | None) -> str:
    """
    '**X 는 모르겠고** Y 는 …' 에서 스스로 모른다고 밝힌 **X** 를 뽑는다. 없으면 "".

    `looks_stuck` 은 통째로 포기한 짧은 답만 잡는다. 그런데 실제 답변은 «한쪽은
    모르겠고 한쪽은 이렇다» 로 온다 — 그러면 판정 경로로 가서, 판정은 발표자가
    이미 모른다고 밝힌 것을 **또 비슷하게 되묻는다.** 그게 이번에 지적받은 자리다.

    **규칙은 코드가 정한다** (이 모듈의 원칙). 절로 갈라서, 포기 표현이 있고
    시도한 흔적이 없는 절만 포기로 보고 그 절의 주제를 남긴다. 나머지 절은
    그대로 채점 대상이다 — 모른다고 밝혔다는 이유로 답한 부분까지 버리지 않는다.

    통째 포기(`looks_stuck`)는 여기서 잡지 않는다. 그쪽은 코칭 경로가 이미 받는다.
    """
    text = (answer or "").strip()
    if not text or looks_stuck(text):
        return ""

    clauses = [c.strip(" ,·") for c in _CLAUSE_SPLIT_RE.split(text) if c and c.strip(" ,·")]
    # 절이 하나뿐이면 «나머지» 가 없다 — 부분 포기가 아니라 통째 포기이거나 답변이다.
    if len(clauses) < 2:
        return ""

    given_up = [c for c in clauses if _GIVE_UP_RE.search(c)]
    # 남은 절이 답변 구실을 못 하면 «부분» 이 아니라 통째 포기다. 그걸 여기서
    # 잡으면 채점할 것도 없는 답에 과녁만 세우게 된다.
    remainder = " ".join(c for c in clauses if c not in given_up)
    if not given_up or len(remainder) < GIVE_UP_REMAINDER_MIN:
        return ""

    for clause in given_up:
        topic = _GIVE_UP_TAIL_RE.sub("", clause).strip(" ,·")
        # 주제를 못 건지거나 지시어뿐이면 «무엇을» 모르는지 알 수 없다. 그때는
        # 안 잡는 편이 낫다 — 빈 과녁을 세우면 되묻기가 도리어 막연해진다.
        if topic and topic != clause and topic not in _VAGUE_TOPICS:
            return _clip(topic)
    return ""


def _giveup_block(topic: str) -> str:
    """부분 포기가 있을 때 판정 프롬프트에 붙는 블록."""
    if not topic:
        return ""
    return (
        "\n\n## 발표자가 스스로 모른다고 밝힌 부분\n"
        f"「{topic}」\n"
        "- **이걸 그대로 되묻지 마라.** 이미 모른다고 했다. 같은 걸 또 물으면 대화가 멈춘다.\n"
        "- 나머지 답변은 평소대로 채점하라. 솔직히 밝힌 것 자체로 깎지 마라.\n"
        "- react 는 답한 쪽을 먼저 인정하고, 모른다고 한 쪽은 방향을 짚어 준다.\n"
        f"- missing_points 에는 「{topic}」 를 적어라 — 화면이 그걸로 힌트를 열어 준다."
    )


#: 되물음의 표지 — **질문 자체**를 못 알아들었다는 말. 답의 내용이 아니라
#: 질문에 대해 말하고 있는 모양만 잡는다.
_ASKS_BACK_RE = re.compile(
    r"무슨\s*(뜻|말|의미|말씀)|어떤\s*(뜻|의미)|"
    r"질문(이|을)?\s*(무엇|뭐|무슨|이해|잘|다시)|"
    # 부탁하는 꼴일 때만 — 09-30 레드팀: 답의 첫머리 「다시 설명하면…」 이 되물음으로 읽혀 채점을 건너뛰었다.
    r"다시\s*(한\s*번\s*)?(말씀|설명|여쭤|물어|얘기|이야기|짚어)\s*(해\s*)?(주|줄|달|부탁|좀|요\b|\?)|"
    r"(뭘|무엇을|어떤\s*걸)\s*(물어|묻는|여쭤)|"
    r"이해(가|를)?\s*(잘\s*)?(안|못)"
)

#: 되물음으로 볼 답변의 최대 길이. 이보다 길면 «답하면서 덧붙여 물은 것» 이라
#: 채점할 내용이 들어 있다. **놓치는 쪽이 안전하다** — 오탐하면 맞는 답을
#: 채점하지 않고 질문만 다시 쓴다 (_ATTEMPT_RE 가 지키던 경계와 같은 규율).
ASKS_BACK_MAX_CHARS = 40


def asks_back(answer: str | None) -> bool:
    """
    답이 아니라 **질문 자체를 되묻는** 말인가. 규칙은 코드가 정한다.

    "깊은 수면 아닐까요?" 는 자신 없는 **답**이지 되물음이 아니다 — 물음표가
    아니라 «질문에 대해 말하고 있는가» 로 가른다. 되물음이면 채점하지 않고
    같은 질문을 더 쉬운 말로 다시 쓴다 (coach_stuck 의 clarify 단계).
    """
    text = (answer or "").strip()
    if not text or len(text) > ASKS_BACK_MAX_CHARS:
        return False
    return bool(_ASKS_BACK_RE.search(text))


def _coach_stage(question: Question, turns: list[QaTurn]) -> str:
    """
    이번 막힘에 몇 번째로 응할지. **프론트가 보내지 않는다** — 저장된 옛 세션에는
    그 필드가 없고, 질문이 바뀔 때 초기화하는 것도 빠뜨리기 쉽다. 이 질문에 대한
    앞선 포기 횟수만 세면 상태 없이 같은 답이 나온다.

    history 전체를 본다 (HISTORY_TURNS 로 자르기 전) — 앞 단계를 잊으면
    같은 되물음을 반복하게 된다.
    """
    # 조인 키는 question_id 다. 문면으로 세면 안 된다 — 프론트가 2턴째부터
    # 원래 질문이 아니라 직전 후속 질문을 그 턴의 question 으로 적기 때문에
    # (app.js submitLiveAnswer), 한 번 답을 시도한 뒤 막힌 사람은 prior 가
    # 영영 0 이 되어 되물음만 무한히 받는다.
    # id 를 안 보내는 옛 클라이언트만 문면 비교(strip)로 폴백한다.
    asked_id = (question.id or "").strip()
    asked = question.question.strip()

    def _same_question(turn: QaTurn) -> bool:
        turn_id = (turn.question_id or "").strip()
        if asked_id and turn_id:
            return turn_id == asked_id
        return turn.question.strip() == asked

    # 포기는 **의사**다. 답변 글에서 역추정(looks_stuck)만 하면 뭔가 써 놓고
    # 「모르겠어요」를 누른 턴을 놓쳐 explain 단계로 못 올라간다.
    prior = sum(
        1 for t in turns
        if _same_question(t) and (t.gave_up or looks_stuck(t.answer))
    )
    # 0: 위치(자료 인용 + 둘 중 하나) · 1: 발판(빈칸, LLM 없음) · 2+: 해설.
    # 답 공개까지 간접 힌트 두 번 — MVP_SPEC §5.3 "세 번째에 자기 말로".
    if prior >= 2:
        return "explain"
    return "scaffold" if prior == 1 else "narrow"


COACH_SYSTEM_PROMPT = """당신은 발표 코치다. 발표자가 방금 막혔다.

절대 나무라지 마라. 한 문장으로 안심시키고 바로 도움으로 넘어간다.
react 는 **막힌 상황에 맞는 말**이다 — 발표자는 답을 못 했다. "핵심을 잘 짚었다"
같은 빈말 칭찬은 쓰지 마라. 안심과 다음 발걸음만 말한다.

[단계=narrow] 답을 알려 주지 마라. '자료 인용' 이 주어지면 **그 문장에 대해** 둘 중
하나를 고르게 하는 되물음 하나를 쓴다 — 두 선택지를 **실제 낱말로** 문장 안에 넣은
「…쪽인가요, …쪽인가요?」 꼴이다. 자리 표시 글자(A·B)를 쓰지 마라 — 그런 문장은 버려진다.
choices 에 그 두 선택지를 각각 20자 이내의 **자료에 나오는 낱말**로 적는다: 하나는 자료가
말하는 쪽, 하나는 같은 자료의 다른 항목(그럴듯한 반대쪽).
인용이 없으면 근거 슬라이드에서 출발해 예/아니오로 답할 수 있을 만큼 좁힌다.
발표자가 스스로 첫 발을 떼게 하는 것이 목적이다.

[단계=explain] 이제 알려 준다. '기대하는 답의 골자' 와 근거 슬라이드, 그리고
발표 때 실제로 한 말을 엮어 "이렇게 답했으면 됐다" 를 설명한다. 자료에 없는
사실을 지어내지 마라. 다음 질문으로 넘어갈 것이므로 되물음은 쓰지 않는다.

[단계=clarify] 발표자는 **포기한 것이 아니라 질문을 못 알아들었다.** 답을 알려
주지 말고, **같은 것을 묻는 같은 질문**을 더 쉬운 말로 다시 써라.
- 묻는 대상을 바꾸지 마라. 쉬운 질문으로 갈아타는 것이 아니라 같은 질문을 푸는 것이다.
- 전문 용어와 겹문장을 걷어내고, 자료의 어느 대목 이야기인지 한 마디로 짚어 준다.
- react 는 "제가 어렵게 물었어요" 쪽이다. 발표자 탓으로 돌리지 마라.

반드시 완전한 JSON 객체만 출력하라. 코드펜스·주석·말머리 금지.

출력 스키마 (단계에 해당하는 키만 채운다):
{
  "react": "안심시키는 한 마디",
  "followup": "narrow 단계에서 쓸 둘 중 하나 되물음 · clarify 단계에서 쓸 다시 쓴 질문 한 문장",
  "choices": ["<narrow 단계의 첫 선택지>", "<둘째 선택지>"],
  "explanation": "explain 단계에서 쓸 해설 두세 문장"
}"""


def _clip_explain(text: str) -> str:
    stripped = (text or "").strip()
    if len(stripped) <= QA_EXPLAIN_MAX:
        return stripped
    return stripped[: QA_EXPLAIN_MAX - 1].rstrip() + "…"


_COACH_REACT_FALLBACK = "괜찮아요. 여기서 같이 짚어 볼게요."
#: 포기한 사람에게 나올 수 없는 말. 프롬프트가 금지해도 실 LLM 이 "핵심을 잘 짚으셨어요" 를
#: 냈다 (2026-09-10). 높임 '~셨' 도 여기서 같이 걸린다 (CLAUDE.md §3-1).
_COACH_PRAISE_RE = re.compile(r"잘 짚|정확합니다|정확해요|맞습니다|맞아요|훌륭|잘 하셨|셨어요|셨습니다")


def coach_stuck(
    question: Question | dict,
    *,
    graph: ConceptGraph | dict | None = None,
    alignment: AlignmentDoc | dict | None = None,
    transcript: Transcript | dict | None = None,
    history: list[QaTurn] | list[dict] | None = None,
    context: Context | dict | None = None,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
    stage: str = "",
    slidedoc: SlideDoc | dict | None = None,
    memory: MemoryDoc | dict | None = None,
) -> QaJudgement:
    """
    막힌 발표자에게 응한다. 1차는 쉬운 되물음(narrow), 2차는 해설(explain).

    memory(F-25) 가 「이 개념에서 지난번에도 포기했다」 고 하면 1차 되물음(narrow)을 건너뛰고 발판(scaffold)에서
    시작한다 — 지난번에 안 통한 되물음을 같은 넓이로 다시 하지 않는다.

    판정이 아니므로 verdict 는 항상 'unknown' · score 0 이고 passed 는 거짓이다.
    단계는 history 로 서버가 정한다 (_coach_stage).

    `stage` 를 주면 그 단계로 고정한다. 되물음(clarify)이 그 경우다 — 포기가
    아니라 질문을 못 알아들은 것이라, 앞선 포기 횟수로 셀 수 있는 상태가 아니다.
    """
    if isinstance(question, dict):
        question = Question.from_dict(question)
    if isinstance(graph, dict):
        graph = ConceptGraph.from_dict(graph)
    if isinstance(alignment, dict):
        alignment = AlignmentDoc.from_dict(alignment)
    if isinstance(transcript, dict):
        transcript = Transcript.from_dict(transcript)
    if isinstance(slidedoc, dict):
        slidedoc = SlideDoc.from_dict(slidedoc)

    turns = [t if isinstance(t, QaTurn) else QaTurn.from_dict(t) for t in (history or [])]
    ctx = Context() if context is None else (
        Context.from_dict(context) if isinstance(context, dict) else context
    )
    stage = stage if stage in QA_COACH_STAGES and stage else _coach_stage(question, turns)
    memory_cm = _memory_concept(question, memory, graph)
    if stage == "narrow" and memory_cm is not None and memory_cm.stalled and memory_cm.give_ups >= 1:
        stage = "scaffold"
    # 발판 단계는 LLM 을 부르지 않는다 — 골자에서 낱말 하나를 가린 빈칸이 전부다.
    # 재료가 없으면(골자 없음) 이 단을 건너뛰고 해설로 간다.
    deck_text = _deck_text(slidedoc)
    # 함정 질문은 1·2단에서 자료의 사실을 보여 주지 않는다 — 장만 가리킨다 (09-29 P5 최종 평가 문제 6).
    # 사실 줄은 3단(해설)에서 연다. 힌트 사다리가 함정이면 사실 줄을 뒤로 미루는 것(f08 build_hint_ladder)과 같은 규율이다.
    trap_tp = question.trap_premise if question.trap else None
    if stage == "scaffold":
        scaffold = _scaffold_judgement(question, graph, deck_text)
        if scaffold is not None:
            return replace(scaffold, evidence_quote="") if trap_tp is not None else scaffold
        stage = "explain"
    said = "(질문을 못 알아들어 되물었다)" if stage == "clarify" else "(모르겠다고 했다)"

    engine = llm if isinstance(llm, LLMProvider) else get_llm(llm, **(llm_kwargs or {}))
    user = "\n".join([
        f"[단계] {stage}",
        _build_user_prompt(
            question, said, turns, graph, alignment, transcript, ctx, slidedoc=slidedoc
        ),
        *_quote_lines(question),
        "",
        f"기대하는 답의 골자: {question.answer_gist or '(없음)'}",
    ])

    try:
        data = _call_coach(engine, user)
    except JudgeError:
        data = _call_coach(engine, user, extra_system=JSON_RETRY_NUDGE)
    data = _haeyo_data(data)

    react = _clip(scrub(str(data.get("react", "") or ""))) or _COACH_REACT_FALLBACK
    if _COACH_PRAISE_RE.search(react) or _HONORIFIC_RE.search(react):
        react = _COACH_REACT_FALLBACK
    choices: list[str] = []
    # 폴백은 F-08 이 이미 만들어 둔 것을 쓴다 — 코칭이 빈손으로 끝나면 안 된다
    if stage == "explain":
        followup = ""
        explanation = _clip_explain(scrub(str(data.get("explanation", "") or ""))) or _clip_explain(
            question.answer_gist or f"{question.label or '이 개념'} 은 자료의 근거 장을 다시 보면 좋아요."
        )
        explanation = _with_citation(explanation, question)
    elif stage == "clarify":
        # 폴백은 **원래 질문 그대로**다. 여기서 힌트로 갈아타면 묻는 대상이 바뀌어,
        # 못 알아들었다고 말한 사람이 다른 질문을 받게 된다.
        followup = _clip(str(data.get("followup", "") or ""))
        if _HONORIFIC_RE.search(followup) or _PLACEHOLDER_RE.search(followup):
            followup = ""
        followup = followup or _clip(question.question)
        explanation = ""
    elif trap_tp is not None:
        followup, choices, explanation = trap_narrow(trap_tp), [], ""
        if leaks_fact(react, trap_tp):
            react = _COACH_REACT_FALLBACK
    else:
        followup, choices = _narrow_followup(data, question, graph, deck_text)
        explanation = ""
        react = _with_quote(react, question)

    label = question.label or "이 개념"
    summary = (
        f"{label} — 질문을 다시 풀어 드렸어요."
        if stage == "clarify"
        else f"{label} — 막힌 지점을 같이 짚었어요."
    )
    return QaJudgement(
        question_id=question.id,
        node_id=question.node_id,
        verdict=QA_VERDICT_FALLBACK,   # 판정이 아니다 — 점수를 매기지 않는다
        score=0,
        react=react,
        summary_sentence=_clip(summary),
        model=engine.name,
        followup=followup,
        hints=build_hint_ladder(question, None),
        coach_stage=stage if stage in QA_COACH_STAGES else "narrow",
        explanation=explanation,
        choices=choices,
        # 함정의 인용은 사실 줄이다 — 화면이 인용 카드로 그리므로 해설 전에는 싣지 않는다(장 번호는 둔다 — 장 그림으로 가리킨다).
        evidence_quote="" if (trap_tp is not None and stage != "explain") else question.evidence_quote,
        evidence_slide_no=question.evidence_slide_no,
    )


#: 선택형 되물음의 모양. 이게 아니면 LLM 이 넓게 물은 것이라 결정적 문장으로 간다.
_CHOICE_FORM_RE = re.compile(r"(인가요|였나요|있었나요|없었나요|맞나요)[^?]*?(인가요|였나요|있었나요|없었나요|아닌가요)|둘 중")
#: 프롬프트의 자리 표시자를 베낀 문장. 09-29 수면 1번: 「…무엇인가요? A인가요, B인가요? (자료 1장)」 이
#: 선택형 모양 검사를 통과해 화면에 나갔다. 모양만 보면 통과하므로 자리 표시자를 따로 잡는다.
_PLACEHOLDER_RE = re.compile(r"(?<![A-Za-z0-9])[AB](?![A-Za-z0-9])\s*(?:인가요|쪽|이요|요\b)|\((?:자료의|다른)\s*낱말\)|선택지\s*[AB12]")
#: 선택지 하나의 최대 길이. 프롬프트는 20자를 부탁한다 — 문장 통째(09-29: 40자 넘는 골자 문장)는 선택지가 아니다.
CHOICE_MAX_CHARS = 24


def _quote_lines(question: Question) -> list[str]:
    """코치 프롬프트에 싣는 자료 인용·발화 인용. 없으면 빈 목록."""
    lines: list[str] = []
    if question.evidence_quote:
        where = f"자료 {question.evidence_slide_no}장" if question.evidence_slide_no else "자료"
        lines += ["", f"자료 인용: {where} — «{question.evidence_quote}»"]
    if question.speech_quote:
        lines.append(f"발표 때 한 말: «{question.speech_quote}»")
    return lines


def _slide_tag(question: Question) -> str:
    return f" (자료 {question.evidence_slide_no}장)" if question.evidence_slide_no else ""


def _distractor_pool(question: Question, graph: ConceptGraph | None) -> list[str]:
    """
    오답 선택지 재료 — **이웃 개념 이름**이 먼저, 요약은 그 뒤. 이름은 정답(골자의 명사)과 같은 종류의 말이다.
    09-29 기준선: 요약에서 「가장 긴 낱말」 을 뽑아 '중요함'·'차지해' 같은 활용형이 오답이 됐다.
    """
    if graph is None:
        return []
    ranked = sorted(graph.neighbors_of(question.node_id), key=lambda n: (-n.weight, n.id))
    return [n.label for n in ranked if n.label] + [n.summary for n in ranked if n.summary]


def _deck_text(slidedoc: SlideDoc | None) -> str:
    if slidedoc is None:
        return ""
    return " ".join(clean_slide_text(s.raw_text or "") for s in slidedoc.slides)


def _in_deck(choice: str, source: str) -> bool:
    """
    선택지가 자료에 나오는 말인가 — 선택지의 내용 낱말이 **전부** 자료에 낱말로 있어야 한다(뒤에 조사 허용).
    09-29 기준선: LLM 선택지 '중요함' 은 자료의 「중요한」 과 앞 두 글자만 같았다 — 활용형은 자료의 말이 아니다.
    """
    words = [w for w in re.findall(r"[가-힣]{2,}|[A-Za-z]{3,}|\d+(?:\.\d+)?%?", choice or "") if not _is_generic(w)]
    return bool(words) and all(term_in(w, source) or term_in(re.sub(r"(은|는|이|가|을|를|의|도|에|와|과|로)$", "", w), source)
                               for w in words)


def _choice_noun(choice: str, source: str) -> bool:
    """선택지의 끝 낱말이 명사 줄기인가 — 「제시하지」「좋아지」 같은 활용형은 보기가 못 된다 (09-30 대화 감사 §8)."""
    words = re.findall(r"[가-힣A-Za-z0-9%.]+", choice or "")
    if not words:
        return False
    last = words[-1]
    stem = _ev_stem(last) or last
    return _noun_like(stem, source)


def _llm_choice_ok(followup: str, choices: list[str], source: str) -> bool:
    """
    LLM 이 쓴 선택형 되물음을 그대로 써도 되는가. 자료(source)가 없으면 모양만 본다.

    09-30 대화 감사 §8: 「…수면 시간은 어떤 요소인가요, 연속성은 어떤 요소인가요?」 가 선택형 모양(인가요…인가요)만으로
    통과했다. 이제 **두 선택지 사이의 진짜 양자택일**(`real_either_or`)이고, 두 선택지가 같은 종류의 말이며(`same_kind`),
    자료에 나오는 명사여야 한다.
    """
    if len(choices) != 2 or not followup or not _CHOICE_FORM_RE.search(followup):
        return False
    if _PLACEHOLDER_RE.search(followup) or any(_PLACEHOLDER_RE.search(c) or re.fullmatch(r"[AB]", c.strip()) for c in choices):
        return False
    if any(len(c) > CHOICE_MAX_CHARS for c in choices) or _HONORIFIC_RE.search(followup):
        return False
    if not real_either_or(followup, choices) or not same_kind(choices[0], choices[1]):
        return False
    return not source or all(_in_deck(c, source) and _choice_noun(c, source) for c in choices)


def _narrow_followup(
    data: dict, question: Question, graph: ConceptGraph | None, deck_text: str = ""
) -> tuple[str, list[str]]:
    """
    위치 단계의 되물음. **둘 중 하나 모양이 아니면 코드 문장으로 간다.**

    LLM 이 choices 2개와 선택형 followup 을 다 줬으면 그것. 하나라도 빠지면 골자를
    가린 빈칸에서 정답·오답을 뽑아 "자료 N장은 «…» 라고 해요. 이 장이 말하는 건
    A 쪽인가요, B 쪽인가요?" 를 만든다. 그것도 안 되면 예전 폴백(F-08 힌트)이다.
    장 번호를 문장에 남긴다 — 화면이 그 번호로 장 그림을 붙인다.
    """
    followup = _clip(str(data.get("followup", "") or ""))
    choices = [_clip(str(c)) for c in (data.get("choices") or []) if str(c).strip()][:2]
    # 자료가 스스로 세운 대비가 먼저다 (qa/reason) — F-08 이 주장 그래프(대비 주장)·근거 장의 대비 줄에서 고른 [세운 쪽, 부정한 쪽].
    # 09-29 부스: 인용의 낱말에서 뽑은 보기가 「'가지' 쪽인가요, '종목' 쪽인가요?」 로 둘 다 틀렸다. LLM 보기보다 앞에 두는 까닭:
    # LLM 보기는 모양·자료 낱말만 검사할 수 있어 어느 쪽이 맞는지는 모른다 — 대비 쌍은 줄의 문법이 정답 쪽을 안다.
    pair = _contrast_of(question)
    if pair is not None:
        (a, b), cq = pair
        where = f"자료 {cq.slide_no}장은" if cq.slide_no else "자료는"
        shown = sorted([a, b])
        return _clip(f"{where} «{cq.quote}» 라고 해요. 이 장이 말하는 건 '{shown[0]}' 쪽인가요, '{shown[1]}' 쪽인가요?"), shown
    if not question.evidence_quote:
        # 인용이 없는 옛 질문 — 선택형을 강제할 재료가 없다. 예전 그대로 LLM 되물음이고,
        # 선택지는 둘 다 왔을 때만 싣는다.
        fallback = _clip(question.hint or f"{question.label or '이 개념'} 이 왜 필요했는지부터 떠올려 볼까요?")
        if _PLACEHOLDER_RE.search(followup) or _HONORIFIC_RE.search(followup):
            return fallback, []
        return (followup or fallback), (choices if len(choices) == 2 and followup else [])
    # 모양(둘 중 하나)만 보면 프롬프트 예시를 베낀 문장·자료에 없는 선택지가 통과한다 (09-29 기준선) — _llm_choice_ok.
    if _llm_choice_ok(followup, choices, f"{deck_text} {question.evidence_quote}".strip() if deck_text else ""):
        if question.evidence_slide_no and "장" not in followup:
            followup = _clip(followup + _slide_tag(question))
        return followup, choices
    _, answer, distractor = mask_gist(
        question.answer_gist, question.label, _distractor_pool(question, graph),
        quote=question.evidence_quote, deck_text=deck_text,
    )
    if answer and distractor and question.evidence_quote:
        where = f"자료 {question.evidence_slide_no}장은" if question.evidence_slide_no else "자료는"
        pair = sorted([answer, distractor])
        text = f"{where} «{question.evidence_quote}» 라고 해요. 이 장이 말하는 건 '{pair[0]}' 쪽인가요, '{pair[1]}' 쪽인가요?"
        return _clip(text), pair
    fallback = _clip(question.hint or f"{question.label or '이 개념'} 이 왜 필요했는지부터 떠올려 볼까요?")
    return fallback, []


def _contrast_of(question: Question) -> tuple[tuple[str, str], ClaimQuote] | None:
    """F-08 이 근거 묶음에 실어 둔 대비 쌍과 그 자료 줄. 옛 세션·대비 없는 질문은 None."""
    b = question.basis
    if b is None or len(b.contrast) != 2 or not all(x.strip() for x in b.contrast):
        return None
    cq = b.contrast_quote or ClaimQuote(question.evidence_slide_no, question.evidence_quote)
    if not cq.quote or len(cq.quote) > CONTRAST_QUOTE_MAX:
        return None
    return (b.contrast[0], b.contrast[1]), cq


#: 대비 되물음에 싣는 자료 줄 상한 — 되물음 문장 전체가 QA_TEXT_MAX 안에 들어가야 보기가 잘리지 않는다.
CONTRAST_QUOTE_MAX = 110


def _with_quote(react: str, question: Question) -> str:
    """안심 한 마디 뒤에 자료 인용을 붙인다 — 상한 안에 들어갈 때만."""
    if not question.evidence_quote:
        return react
    where = f"자료 {question.evidence_slide_no}장은" if question.evidence_slide_no else "자료는"
    joined = f"{react} {where} 이렇게 말해요: «{question.evidence_quote}»"
    return joined if len(joined) <= QA_TEXT_MAX else react


def _with_citation(explanation: str, question: Question) -> str:
    """해설 끝에 출처를 **반드시** 단다: 자료 N장 인용, 발표 때 한 말. 상한 안에서."""
    parts: list[str] = []
    if question.evidence_quote and question.evidence_quote not in explanation:
        where = f"자료 {question.evidence_slide_no}장" if question.evidence_slide_no else "자료"
        parts.append(f"{where}: «{question.evidence_quote}»")
    if question.speech_quote and question.speech_quote not in explanation:
        parts.append(f"발표에서는 «{question.speech_quote}» 라고 말했어요.")
    if not parts:
        return explanation
    tail = " — " + " ".join(parts)
    room = QA_EXPLAIN_MAX - len(tail)
    if room < 40:
        return explanation
    body = explanation if len(explanation) <= room else explanation[: room - 1].rstrip() + "…"
    return body + tail


def _scaffold_judgement(question: Question, graph: ConceptGraph | None, deck_text: str = "") -> QaJudgement | None:
    """
    발판 단계 — LLM 없이. 골자에서 낱말 하나를 가린 빈칸과 선택지 둘.
    골자가 없어 빈칸을 못 만들면 None (호출자가 해설로 넘긴다).
    """
    pair = _contrast_of(question)
    masked, answer, distractor = mask_gist(
        question.answer_gist, question.label, _distractor_pool(question, graph),
        quote=question.evidence_quote, deck_text=deck_text, pair=list(pair[0]) if pair else None,
    )
    if not masked:
        return None
    choices = sorted([answer, distractor]) if distractor else []
    followup = f"빈칸을 채워 보세요: {masked}"
    if choices:
        followup += f" — '{choices[0]}' 인가요, '{choices[1]}' 인가요?"
    followup += _slide_tag(question)
    return QaJudgement(
        question_id=question.id,
        node_id=question.node_id,
        verdict=QA_VERDICT_FALLBACK,
        score=0,
        react="괜찮아요. 한 칸만 채우면 돼요.",
        summary_sentence=_clip(f"{question.label or '이 개념'} — 빈칸으로 발판을 놓았어요."),
        model="",
        followup=_clip(followup),
        hints=build_hint_ladder(question, None),
        coach_stage="scaffold",
        choices=choices,
        evidence_quote=question.evidence_quote,
        evidence_slide_no=question.evidence_slide_no,
    )


def _empty_answer(question: Question, round_no: int = 1) -> QaJudgement:
    """
    빈 답변은 LLM 을 부르지 않는다. 판정할 내용이 없는데 비용을 태울 이유가 없다.

    그래도 followup·hints 는 채워 나간다 — 첫 마디를 못 뗀 사람이야말로
    되묻기와 힌트가 필요한 사람이기 때문이다. 폴백이 유일한 공급원이다.
    """
    return _normalize(
        {"verdict": QA_VERDICT_FALLBACK, "react": EMPTY_ANSWER_REACT},
        question,
        model="",
        round_no=round_no,
    )


def _round_no(prior_answers: list[str] | None) -> int:
    """
    이번이 이 질문의 몇 번째 답변인지 (1부터).

    프론트가 보내 주는 '앞서 낸 답들' 을 세면 상태 없이 같은 답이 나온다
    (`_coach_stage` 와 같은 규율). 포기 턴의 자리 표시자는 프론트가 이미
    걸러서 보내지만, 빈 문자열은 여기서도 한 번 더 버린다.
    """
    return 1 + sum(1 for text in (prior_answers or []) if (text or "").strip())


# ---------------------------------------------------------------------------
# LLM 호출
# ---------------------------------------------------------------------------

def _complete_json(engine: LLMProvider, system: str, user: str) -> dict:
    raw = engine.complete(
        system=system,
        user=user,
        temperature=0.2,
        max_tokens=MAX_TOKENS,
        json_mode=True
    )
    try:
        return extract_json_object(raw)
    except ValueError as e:
        raise JudgeError(f"LLM 응답에서 판정 JSON 을 찾지 못했습니다: {e}") from e


def _call(engine: LLMProvider, user: str, *, extra_system: str = "") -> dict:
    """판정 호출. system 은 판정 스키마 하나뿐이다."""
    return _complete_json(engine, SYSTEM_PROMPT + extra_system, user)


def _call_coach(engine: LLMProvider, user: str, *, extra_system: str = "") -> dict:
    """
    막힘 코칭 호출. **판정 시스템 프롬프트를 이고 가지 않는다.**

    둘을 붙이면 system 에 출력 스키마가 두 개(verdict/score · react/followup/explanation)
    실려 모델이 어느 쪽으로 답할지 모호해진다. 판정 스키마로 답해 오면 코칭 문장이
    전부 비어 조용히 F-08 폴백으로 대체되고, 화면은 멀쩡해 보여서 알아채기 어렵다.
    """
    return _complete_json(engine, COACH_SYSTEM_PROMPT + extra_system, user)


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------

def judge_answer(
    question: Question | dict,
    answer: str,
    *,
    graph: ConceptGraph | dict | None = None,
    alignment: AlignmentDoc | dict | None = None,
    transcript: Transcript | dict | None = None,
    history: list[QaTurn] | list[dict] | None = None,
    context: Context | dict | None = None,
    give_up: bool = False,
    prior_answers: list[str] | None = None,
    hints_shown: list[str] | None = None,
    llm: str | LLMProvider | None = None,
    llm_kwargs: dict | None = None,
    slidedoc: SlideDoc | dict | None = None,
    memory: MemoryDoc | dict | None = None,
) -> QaJudgement:
    """
    Question + 답변 (+선택 ConceptGraph·AlignmentDoc·Transcript·history·Context·MemoryDoc)
    → QaJudgement.

    memory(F-25) 를 주면 이 개념의 지난 리허설 기억(판정·빠진 점)이 판정 프롬프트에 실려, 지난번에 빠졌던 점이
    이번엔 나왔는지 알아본다. 포기하면 코칭 시작 단계도 기억이 정한다 (coach_stuck). 안 주면 예전과 같다.

    give_up=True 이거나 답변이 포기로 보이면(looks_stuck) 판정하지 않고
    coach_stuck() 으로 넘긴다 — 모르겠다는 사람에게 점수를 매길 이유가 없다.

    판정은 LLM 이 하지만 계약은 코드가 지킨다: verdict 는 4-class 안,
    score 는 0~100, node_id 는 질문에서 승계, react·summary_sentence 는 항상 채워진다.
    빈 답변은 LLM 없이 'unknown' 으로 즉시 돌려준다.

    graph 를 주면 개념의 parent 경로(트리 뷰)와 relates 이웃(그래프 뷰)이 함께 실려,
    "옆 개념과의 관계를 짚었는가" 까지 볼 수 있다. transcript 를 주면 근거 장의
    실제 발화가 붙어 "발표 때와 지금 답이 다른가" 를 대조할 수 있다.

    history 는 프론트가 보내는 한글 키({질문, 답변, 판정})와 영문 키 둘 다 받는다.
    """
    if isinstance(question, dict):
        question = Question.from_dict(question)
    if not question.question.strip():
        raise JudgeError("판정할 질문이 비어 있습니다. F-08 결과를 먼저 확인하세요.")

    # 이 질문의 몇 번째 답변인가. 되묻기 단계와 대화의 출구(mastered)가 여기 달렸다.
    round_no = _round_no(prior_answers)

    # 「모르겠어요」 버튼은 답이 비어 있어도 코칭으로 간다 — 빈 답 검사가 먼저면
    # 버튼을 누른 사람이 "아직 답변이 없습니다" 를 받는다 (2026-09-10 실측).
    if not give_up and not (answer or "").strip():
        return _empty_answer(question, round_no)

    # 포기는 판정하지 않는다. 버튼(give_up)이든 타이핑(looks_stuck)이든 같은 곳으로 간다.
    # 되물음도 판정하지 않는다 — 「질문이 무슨 뜻인가요?」 를 채점하면 못 알아들었다고
    # 말한 사람이 오답으로 기록되고, 화면은 답을 안 준 채 되묻기만 한 칸 더 간다.
    # **버튼(give_up)이 먼저다.** 누른 사람의 의사가 글에서 읽은 짐작보다 세다.
    if give_up or looks_stuck(answer):
        return coach_stuck(
            question,
            graph=graph,
            alignment=alignment,
            transcript=transcript,
            history=history,
            context=context,
            llm=llm,
            llm_kwargs=llm_kwargs,
            slidedoc=slidedoc,
            memory=memory,
        )
    if asks_back(answer):
        return coach_stuck(
            question,
            graph=graph,
            alignment=alignment,
            transcript=transcript,
            history=history,
            context=context,
            llm=llm,
            llm_kwargs=llm_kwargs,
            stage="clarify",
            slidedoc=slidedoc,
        )

    if isinstance(graph, dict):
        graph = ConceptGraph.from_dict(graph)
    if isinstance(alignment, dict):
        alignment = AlignmentDoc.from_dict(alignment)
    if isinstance(transcript, dict):
        transcript = Transcript.from_dict(transcript)
    if isinstance(slidedoc, dict):
        slidedoc = SlideDoc.from_dict(slidedoc)

    turns = [
        t if isinstance(t, QaTurn) else QaTurn.from_dict(t)
        for t in (history or [])
    ]

    if context is None:
        ctx = Context()
    elif isinstance(context, dict):
        ctx = Context.from_dict(context)
    else:
        ctx = context

    engine = llm if isinstance(llm, LLMProvider) else get_llm(llm, **(llm_kwargs or {}))
    # 자료 본문이 정답의 원본이다 (모듈 머리 「판정은 무엇을 근거로 하나」). 자료가 없는 호출(옛 세션·flat 판정)은
    # 예전 그대로 골자가 기준이다.
    deck = deck_from_slidedoc(slidedoc)
    # 탐침 질문이 **따져 묻는** 자료 줄은 채점 원본이 아니다 (09-29 P5 최종 평가 문제 1 · `_probe_stance`).
    # 단정·근거 없는 인과·긴장의 모범답은 그 줄을 부정하거나 보탠다 — 그 줄과 어긋난다고 깎으면 거꾸로 채점한다.
    probed = probed_quotes(question)
    judge_deck = without_lines(deck, probed) if probed else deck
    question, gist_grounded = _ground_gist(question, deck, judge_deck)
    user = _build_user_prompt(
        question, answer, turns, graph, alignment, transcript, ctx, prior_answers,
        slidedoc=slidedoc, memory_cm=_memory_concept(question, memory, graph),
    )
    user += _deck_line_block(answer, prior_answers, judge_deck)
    user += probe_brief(question)
    user += _reason_block(question)
    # 정답 골자는 판정에도 싣는다 (규칙 3 의 참고 답). 코칭(coach_stuck)만 갖고
    # 있으면 이지선다 질문에 정답 단답이 와도 모델이 자료 발췌에서 확신을 못 얻어
    # unknown 으로 도망간다 — 이지선다 단답이 '너무 짧다' 로 거부된 실측(2026-08-07).
    # _build_user_prompt 안에 넣지 않는 것은 coach_stuck 이 같은 함수를 쓰면서
    # 골자를 따로 붙이기 때문이다 — 두 번 실리면 안 된다.
    gist = (question.answer_gist or "").strip()
    if gist and gist_grounded:
        user += f"\n\n## 기대하는 답의 골자 (채점 기준 — 발표자에게는 보이지 않는다)\n{gist}"
    elif gist:
        user += (
            "\n\n## 기대하는 답의 골자 (참고만 — 일부가 자료 본문에서 확인되지 않는다. 자료와 다르면 자료가 맞다."
            " 발표자에게는 보이지 않는다)\n" + gist
        )
    user += _gist_parts_block(question)

    # 부분 포기 — «X 는 모르겠고 Y 는 …». 판정은 그대로 하되, 스스로 모른다고
    # 밝힌 조각을 또 비슷하게 되묻지 않게 과녁과 넓이를 코드가 정한다.
    giveup_topic = partial_giveup_topic(answer)
    user += _giveup_block(giveup_topic)

    # 「모르겠어요」 코칭이 방금 둘 중 하나·빈칸으로 되물었다 — 이번 답은 **그 되물음의 답**이다 (09-30 대화 감사 §3:
    # 칩 「항목」 이 원래 질문의 답으로 채점돼 good 85 로 닫혔다).
    answered_coach = _answered_coach(question, turns)
    if answered_coach:
        user += (
            "\n\n## 이번 답은 「모르겠어요」 뒤의 되물음(둘 중 하나·빈칸)에 대한 답이다\n"
            "고른 쪽·채운 낱말이 자료와 맞는지만 보고 react 를 써라. 원래 질문 전체에 답한 것으로 치지 마라 — "
            "맞았어도 원래 질문에서 아직 안 나온 것 하나를 missing_points 에 남기고 followup 으로 그것을 물어라."
        )
    # 질문이 자료에 없는 것을 물을 수 있다 (09-30 §4: 「어떻게 측정했나요」「가장 큰 영향」 — 자료에 측정·순위가 없다).
    beyond = beyond_deck_terms(question.question, deck, question.label)
    if beyond:
        user += (
            "\n\n## 질문의 이 낱말은 자료에 없다: " + ", ".join(beyond[:4]) + "\n"
            "질문이 자료 밖을 묻는 것이면, 발표자가 「자료에 없다」 고 밝히고 자료가 말하는 범위 안에서 답한 것이 정답이다. "
            "자료에 없는 것을 missing_points 로 요구하지 마라."
        )

    # 힌트는 화면에만 뜨고 판정이 모르면, 힌트를 따라온 답에 코치가 맥락 없이
    # 반응한다 — 화면은 대화처럼 보이는데 판정은 일방향이 된다 (2026-08-07 사용자).
    shown = [str(h).strip() for h in (hints_shown or []) if str(h).strip()]
    if shown:
        user += (
            "\n\n## 발표자에게 보여준 힌트\n"
            + "\n".join(f"- {h}" for h in shown)
            + "\n힌트를 따라온 답이면 그 진전을 인정하고, react 는 힌트와 이어지는 말로 하라."
        )

    # 되묻기 단계. 라운드가 오를수록 질문이 좁아져야 스스로 답에 닿는다 —
    # 같은 넓이로 세 번 물으면 압박이 아니라 반복이고, 사용자는 세 번째에 창을 닫는다.
    #
    # **system 에 싣는다.** 처음엔 user 프롬프트 꼬리에 붙였는데 실 LLM(solar-pro3)이
    # 무시했다 — 2라운드 followup 이 "…유리한 점은 무엇인가요?" 로 나와 1라운드보다
    # 오히려 넓어졌다(2026-08-08 실측). 규칙 9 가 system 에서 "빠진 지점 하나를 콕
    # 집어" 라고 말하는데 단계 지시는 user 꼬리에 있으니, 같은 층위로 안 읽힌 것이다.
    # 모른다고 밝힌 조각은 **한 칸 더 좁혀** 묻는다. 같은 넓이로 다시 물으면
    # 발표자가 방금 못 넘은 벽을 그대로 다시 세우는 것이다.
    tier = qa_probe_tier(round_no)
    if giveup_topic:
        tier = _TIER_NARROWER[tier]
    tier_brief = (
        f"\n\n[되묻기 단계 — {tier}] ({round_no}번째 답변 / 최대 {QA_MAX_ROUNDS}라운드)\n"
        + ("발표자가 일부를 «모르겠다» 고 밝혀서 한 칸 더 좁혔다. 라운드 번호가 아니라"
           " 아래 넓이를 따르라.\n" if giveup_topic else "")
        + f"{_PROBE_TIER_BRIEF[tier]}\n"
        + "이 단계 지시는 규칙 9 보다 우선한다. followup 의 넓이는 여기서 정한다."
    )

    try:
        data = _call(engine, user, extra_system=tier_brief)
    except JudgeError:
        # 파싱 실패는 대부분 그 실행의 출력 문제다. 한 번은 다시 묻고, 또 깨지면 실패로 둔다
        data = _call(engine, user, extra_system=tier_brief + JSON_RETRY_NUDGE)

    # 이 질문이 묻는 것 — 질문·골자·개념의 그래프 자리. 무관 가드가 자료 본문 전체가 아니라 이것과도 대조한다.
    focus_lines = [question.question, question.answer_gist, *question.answer_gist_parts, *_concept_block(question, graph)]
    return _normalize(
        _haeyo_data(data), question, engine.name, round_no,
        followup_tier=tier,
        forced_point=giveup_topic,
        answer=answer,
        # 가드가 대조할 근거 — 프롬프트에 실린 것과 같은 자료·발화·골자.
        evidence="\n".join([
            *focus_lines, *_slide_block(question, slidedoc, graph),
            *_speech_block(question, transcript),
        ]),
        focus="\n".join(focus_lines),
        deck=judge_deck,
        probed=tuple(probed),
        prior_answers=list(prior_answers or [])[-PRIOR_ANSWERS_MAX:],
        answered_coach=answered_coach,
        anchor_text=_anchor_text(question, slidedoc),
    )


def _reason_block(question: Question) -> str:
    """
    근거·이유를 묻는 질문의 채점 기준 블록 (qa/reason) — F-08 이 근거 묶음에 실은 이유 줄·배경 줄. 없으면 "".

    09-30 부스 실측: 「…라고 결론지은 근거」 에 현상의 규모(배경)만 말한 답과 이유를 말한 답을 가를 원본이 판정에 없었다 —
    골자가 두 절을 섞었고, 자료 본문도 두 절을 나란히 싣는다. 이유 줄을 채점 기준으로, 배경 줄은 「이유가 아니다」 로 따로 싣는다.
    """
    b = question.basis
    if b is None or not b.reason:
        return ""
    reasons = "\n".join(f"- {q.slide_no}장: {q.quote[:160]}" for q in b.reason)
    background = "\n".join(f"- {q.slide_no}장: {q.quote[:160]}" for q in b.background)
    return (
        "\n\n## 이 질문의 근거 줄 (결론을 받치는 이유 — 채점 기준, 자료 원문)\n" + reasons
        + ("\n\n## 배경 줄 (현상이 있다는 말 — 이유가 아니다)\n" + background if background else "")
        + "\n근거·이유를 묻는 질문이다. 근거 줄의 이유를 하나 이상 자기 말로 대면 good 이 될 수 있다."
          " 배경 줄(현상·규모)만 되풀이하고 이유를 대지 않은 답은 partial 이다."
    )


def _reason_missed(answer: str, question: Question) -> ClaimQuote | None:
    """
    근거 질문에 **이유 낱말이 하나도 없고 배경만 되풀이한** 답이면 가장 곧은 이유 줄, 아니면 None.

    이유 줄의 낱말 가운데 배경 줄·질문에도 있는 낱말은 뺀다 — 둘 다 같은 주제어(개념 이름)를 쓰므로 그걸로는 이유를 말했는지
    알 수 없다. 남은 이유 낱말이 답에 하나도 없고 배경 줄과는 둘 이상 겹칠 때만 — 바꿔 말한 답(「자주 사고팔수록 …」)은
    이유 낱말 하나로 통과한다. 낱말 대조는 «이유를 댔는가» 만 알지 «맞는 이유인가» 는 모른다 — 그건 LLM·자료 대조 몫이다.
    """
    b = question.basis
    if b is None or not b.reason or not b.background or not (answer or "").strip():
        return None
    back = RS.tokens(" ".join(q.quote for q in b.background))
    asked = RS.tokens(question.question)
    reason_only = {t for t in RS.tokens(" ".join(q.quote for q in b.reason))
                   if not RS.overlap({t}, back) and not RS.overlap({t}, asked)}
    said = RS.tokens(answer)
    if not reason_only or RS.overlap(reason_only, said) >= 1:
        return None
    return b.reason[0] if RS.overlap(said, back) >= 2 else None


def _anchor_text(question: Question, slidedoc: SlideDoc | None) -> str:
    """이 질문의 근거 장 본문(정리한 글). 결손이 인용한 조각이 여기 없으면 자료의 글자가 아니다 (09-30 §7)."""
    if slidedoc is None:
        return ""
    nos = set(question.slide_nos) | ({question.evidence_slide_no} if question.evidence_slide_no else set())
    return " ".join(clean_slide_text(s.raw_text or "") for s in slidedoc.slides if s.slide_no in nos)


def _ground_gist(question: Question, deck: Deck, against: Deck | None = None) -> tuple[Question, bool]:
    """
    골자가 자료로 받쳐지는가 — 그리고 받쳐지지 않는 **골자 요소**를 체크리스트에서 뺀 질문 사본.

    09-29 기준선: 골자 요소 「문헌의 구조적 설명과 발표의 행동적 설명 비교」(관련 없는 논문에서 온 말)가 채점 기준이 돼,
    자료대로 한 정답이 「빠진 점」 으로 partial 75 를 받았다. 자료에 없는 요소를 요구하면 자료대로 답한 사람이 진다.
    원본은 바꾸지 않는다(dataclasses.replace) — 요소가 하나만 남으면 Question 이 빈 목록으로 접는다.
    자료가 비면 판단 근거가 없는 것이라 그대로 둔다.
    """
    if deck.empty:
        return question, True
    # 어긋남은 against(탐침이 따지는 줄을 뺀 덱)로 본다 — 단정의 경계를 말한 골자가 그 단정과 어긋난다고 「참고만」 이 되지 않게.
    grounded = support(question.answer_gist or "", deck, question.question, against).grounded
    parts = [p for p in question.answer_gist_parts if support(p, deck, question.question, against).grounded]
    if parts != list(question.answer_gist_parts):
        question = replace(question, answer_gist_parts=parts)
    return question, grounded


def _deck_line_block(answer: str, prior_answers: list[str] | None, deck: Deck) -> str:
    """
    답의 절마다 가장 가까운 **자료 줄** (근거 장 밖 포함). 판정이 「자료와 어긋나는가」 를 대조할 원본을 넓힌다.
    09-29 실측: 오답을 반박하는 줄이 근거 장(anchor) 밖에 있어 프롬프트에 없었고, 판정이 「맞아요」 partial 75 를 줬다.
    """
    if deck.empty:
        return ""
    said = " ".join([*(prior_answers or [])[-PRIOR_ANSWERS_MAX:], answer or ""])
    lines = nearest_lines(said, deck)
    if not lines:
        return ""
    body = "\n".join(f"- {ln.slide_no}장: {ln.text[:160]}" for ln in lines)
    return (
        "\n\n## 답변과 맞닿은 자료 줄 (근거 장 밖 포함 — 대조 원본, 발표자가 말한 것이 아니다)\n"
        + body
        + "\n답변의 수치·크기 순서·방향·긍정/부정이 이 줄들과 어긋나면 규칙 8 의 단서를 따른다."
    )
