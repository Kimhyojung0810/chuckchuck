"""
F-25 리허설 기억 — 지난 답변 과정(qa_turns)에서 기억을 만들고, 다음 Q&A(순서·질문·판정·코칭)에 잇는다. 네트워크·LLM 없이.
"""

import json

import pytest

from chuckchuck.contracts import (
    ConceptGraph,
    ConceptNode,
    Context,
    MemoryDoc,
    QaTriage,
    Question,
    TriageMark,
    memory_key,
)
from chuckchuck.f08_questions import MEMORY_SYSTEM_ADDENDUM, QUESTION_SYSTEM_PROMPT, _build_question_prompt, _stalled_first, build_questions
from chuckchuck.f09_judge import _build_user_prompt, coach_stuck, judge_answer
from chuckchuck.f25_memory import build_memory, link_memory
from chuckchuck.providers.llm_base import LLMProvider
from demo.session_archive import SessionArchive


def turn(qid, label, verdict, *, at=1.0, score=0, missing=(), give_up=False, hints=(), node_id=""):
    return {
        "at": at, "question_id": qid, "give_up": give_up, "hints_shown": list(hints),
        "question": {"id": qid, "node_id": node_id or qid.split("-", 1)[-1], "label": label, "question": f"{label}?"},
        "answer": "…", "prior_answers": [],
        "judgement": {"verdict": verdict, "score": score, "missing_points": list(missing),
                      "coach_stage": "narrow" if give_up else ""},
    }


def rehearsals():
    return [
        {"session_id": "s1", "at": 100.0, "title": "발표", "turns": [
            turn("q01-notif", "알림의 주의 비용", "wrong", at=101, score=30, missing=["측정 조건"]),
            turn("q01-notif", "알림의 주의 비용", "partial", at=102, score=60, missing=["측정 조건", "통제 집단"]),
            turn("q02-resid", "Attention residue", "unknown", at=103, give_up=True, hints=["h1", "h2"]),
            turn("q03-env", "환경 설계", "good", at=104, score=85),
        ]},
        {"session_id": "s2", "at": 200.0, "title": "발표", "turns": [
            turn("q01-notif", "알림의 주의 비용", "partial", at=201, score=65, missing=["통제 집단"]),
            turn("q02-resid", "Attention residue", "good", at=202, score=90),
        ]},
    ]


def graph():
    return ConceptGraph(file_name="발표.pdf", total_slides=5, nodes=[
        ConceptNode(id="c1", label="환경 설계", slide_nos=[1], weight=1.0),
        ConceptNode(id="c2", label="알림 주의 비용", slide_nos=[2], weight=0.9),      # 「알림의 주의 비용」 과 토큰 겹침
        ConceptNode(id="c3", label="Attention residue", slide_nos=[3], weight=0.8),
        ConceptNode(id="c4", label="표본", slide_nos=[4], weight=0.3),
    ])


# ---------------------------------------------------------------------------
# build_memory
# ---------------------------------------------------------------------------

def test_기억은_기록에서만_세고_최신이_마지막이_된다():
    m = build_memory(rehearsals(), file_name="발표.pdf", learner_key="learner:ab12cd34")
    assert m.learner_key == "learner:ab12cd34" and [s.session_id for s in m.sessions] == ["s2", "s1"]
    notif = m.concept("알림의 주의 비용")
    assert notif.asked == 2 and notif.attempts == 3 and notif.give_ups == 0
    assert notif.verdicts == {"wrong": 1, "partial": 2} and notif.last_verdict == "partial" and notif.best_verdict == "partial"
    assert notif.last_score == 65 and notif.stalled
    assert notif.missing_points == ["통제 집단", "측정 조건"]         # 최신 우선 · 중복 없음
    resid = m.concept("Attention residue")
    assert resid.give_ups == 1 and resid.hints_max == 2 and resid.best_verdict == "good" and not resid.stalled
    env = m.concept("환경 설계")
    assert env.cleared and env.asked == 1
    assert [c.key for c in m.stalled] == [memory_key("알림의 주의 비용")]   # 못 넘긴 개념이 앞
    s2, s1 = m.sessions
    assert (s1.questions, s1.good, s1.partial, s1.wrong, s1.give_ups) == (3, 1, 1, 0, 1)
    assert s1.score_mean == pytest.approx((30 + 60 + 85) / 3, abs=0.1)
    assert (s2.good, s2.partial) == (1, 1)
    again = MemoryDoc.from_dict(json.loads(json.dumps(m.to_dict(), ensure_ascii=False)))
    assert again.concept("알림의 주의 비용").missing_points == notif.missing_points and again.to_dict() == m.to_dict()


def test_기억이_없으면_note_와_빈_목록():
    m = build_memory([])
    assert m.concepts == [] and m.sessions == [] and "없음" in m.note
    assert build_memory([{"session_id": "x", "at": 1.0, "turns": []}]).concepts == []


def test_잇기는_이름이_같은_것_먼저_그다음_토큰_겹침이고_한_기억은_한_노드에만():
    m = build_memory(rehearsals())
    by = link_memory(m, graph())
    assert set(by) == {"c1", "c2", "c3"}
    assert by["c2"].label == "알림의 주의 비용" and by["c3"].label == "Attention residue" and by["c1"].label == "환경 설계"
    assert link_memory(None, graph()) == {} and link_memory(m, None) == {}


# ---------------------------------------------------------------------------
# F-08 — 순서 · 프롬프트
# ---------------------------------------------------------------------------

def marks():
    return [
        TriageMark(node_id="c1", severity=1, rank=1, source="core_weight", doc_weight=1.0),
        TriageMark(node_id="c4", severity=2, rank=2, source="core_weight", doc_weight=0.3),
        TriageMark(node_id="c2", severity=2, rank=3, source="core_weight", doc_weight=0.9),
        TriageMark(node_id="c3", severity=3, rank=4, source="core_weight", doc_weight=0.8),
    ]


def test_지난번에_못_넘긴_개념이_앞으로_오고_나머지_순서는_그대로():
    ordered = _stalled_first(marks(), graph(), build_memory(rehearsals()))
    assert [(m.node_id, m.rank) for m in ordered] == [("c2", 1), ("c1", 2), ("c4", 3), ("c3", 4)]
    assert [m.node_id for m in _stalled_first(marks(), graph(), build_memory([]))] == ["c1", "c4", "c2", "c3"]


class Scripted(LLMProvider):
    name = "scripted"

    def __init__(self):
        self.systems, self.users = [], []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.systems.append(system)
        self.users.append(user)
        return json.dumps({"questions": [
            {"node_id": "c2", "question": "통제 집단은 어떻게 뒀나요?", "why": "w", "hint": "h", "answer_gist": "g"}]}, ensure_ascii=False)


def test_기억이_있으면_개념_줄에_지난_리허설이_붙고_없으면_프롬프트가_예전과_같다():
    g = graph()
    by_id = {n.id: n for n in g.nodes}
    triage = QaTriage(file_name="발표.pdf", total_slides=5, marks=marks()[:3])
    a = _build_question_prompt(g, triage.marks, by_id, None, None, Context())
    b = _build_question_prompt(g, triage.marks, by_id, None, None, Context(), memory_of={})
    assert a == b and "지난 리허설" not in a

    llm = Scripted()
    doc = build_questions(g, triage, track="5", memory=build_memory(rehearsals()), llm=llm)
    user, system = llm.users[0], llm.systems[0]
    assert "지난 리허설: 2번 물음 · 마지막 판정 반쯤 · 빠졌던 점: 통제 집단 / 측정 조건 ← 빠졌던 점을 겨냥해 물어라" in user
    assert "지난 리허설: 1번 물음 · 마지막 판정 통과" in user          # 환경 설계 — 통과한 개념도 알려 준다 (더 깊게 묻도록)
    assert "…" not in user.split("지난 리허설")[1][:200]              # 답변 원문은 싣지 않는다
    assert system == QUESTION_SYSTEM_PROMPT + MEMORY_SYSTEM_ADDENDUM
    assert doc.questions and doc.questions[0].node_id == "c1"          # 순서는 받은 triage 그대로 — 앞세우기는 triage_questions 몫

    llm2 = Scripted()
    build_questions(g, triage, track="5", llm=llm2)
    assert llm2.systems[0] == QUESTION_SYSTEM_PROMPT and "지난 리허설" not in llm2.users[0]


# ---------------------------------------------------------------------------
# F-09 — 판정 프롬프트 · 코칭 단계
# ---------------------------------------------------------------------------

def question(node_id="c2", label="알림 주의 비용"):
    return Question(id=f"q01-{node_id}", node_id=node_id, label=label, question="통제 집단은 어떻게 뒀나요?",
                    why="w", hint="h", answer_gist="통제 집단은 알림을 끈 조건", severity=2)


def test_판정_프롬프트에_지난_리허설_블록이_붙고_없으면_같다():
    m = build_memory(rehearsals())
    cm = m.by_node(graph())["c2"]
    a = _build_user_prompt(question(), "답", [], graph(), None, None, Context())
    b = _build_user_prompt(question(), "답", [], graph(), None, None, Context(), memory_cm=None)
    c = _build_user_prompt(question(), "답", [], graph(), None, None, Context(), memory_cm=cm)
    assert a == b and "지난 리허설" not in a
    assert "## 지난 리허설에서 이 개념" in c and "빠졌던 점: 통제 집단 / 측정 조건" in c and "지난번에 빠졌던 점이 이번 답에 나왔으면" in c
    assert c.index("지난 리허설에서 이 개념") < c.index("## 이번 답변") if "## 이번 답변" in c else True


class JudgeLLM(LLMProvider):
    name = "judge"

    def __init__(self):
        self.users = []

    def complete(self, *, system, user, temperature=0.2, max_tokens=4096, json_mode=False):
        self.users.append(user)
        return json.dumps({"verdict": "good", "score": 85, "react": "좋아요", "summary_sentence": "지난번엔 빠졌던 통제 집단을 이번엔 짚었어요",
                           "missing_points": [], "followup": ""}, ensure_ascii=False)


def test_judge_answer_는_memory_를_받아_프롬프트에_싣는다():
    llm = JudgeLLM()
    j = judge_answer(question(), "통제 집단은 알림을 끈 조건으로 뒀어요", graph=graph(), memory=build_memory(rehearsals()).to_dict(), llm=llm)
    assert j.verdict == "good" and "## 지난 리허설에서 이 개념" in llm.users[0]
    llm2 = JudgeLLM()
    judge_answer(question(), "통제 집단은 알림을 끈 조건으로 뒀어요", graph=graph(), llm=llm2)
    assert "지난 리허설" not in llm2.users[0]


def test_지난번에도_포기한_개념이면_되물음을_건너뛰고_발판에서_시작한다():
    # Attention residue: s1 에서 포기 1번, best good → stalled 아님 → 그대로 narrow
    m = build_memory(rehearsals())
    q_resid = question("c3", "Attention residue")
    assert coach_stuck(q_resid, graph=graph(), memory=m, llm="mock").coach_stage == "narrow"
    # 포기했고 한 번도 good 을 못 받은 개념 → scaffold (발판은 LLM 없이 골자에서 만든다)
    stuck = build_memory([{"session_id": "s9", "at": 300.0, "turns": [
        turn("q01-c2", "알림 주의 비용", "unknown", at=301, give_up=True)]}])
    j = coach_stuck(question(), graph=graph(), memory=stuck, llm="mock")
    assert j.coach_stage == "scaffold" and j.verdict == "unknown"
    # 기억 없으면 narrow
    assert coach_stuck(question(), graph=graph(), llm="mock").coach_stage == "narrow"


# ---------------------------------------------------------------------------
# 보관소 — 같은 사람·같은 파일의 동의한 세션만 잇는다
# ---------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.t = 1_757_500_000.0

    def __call__(self):
        self.t += 60
        return self.t


@pytest.fixture
def archive(tmp_path):
    return SessionArchive(tmp_path / "data", clock=Clock(), code_version="test")


def _open(archive, *, consent, upload=b"%PDF-1.4 same", learner=""):
    sid = archive.new_id()
    import hashlib
    rec = archive.open(sid, consent=consent, file_name="발표.pdf", ext=".pdf", upload=upload,
                       sha256=hashlib.sha256(upload).hexdigest(), title="발표", learner_id=learner)
    assert rec is not None
    return sid


def test_related_sessions_는_같은_learner_id_로만_잇고_동의_없는_세션과_자신은_뺀다(archive):
    a = _open(archive, consent=True, learner="brw_0001")
    archive.append(a, "qa_turns", turn("q01-c2", "알림 주의 비용", "partial", missing=["통제 집단"]))
    b = _open(archive, consent=False, learner="brw_0001")                     # 동의 없음 → 안 잇는다
    c = _open(archive, consent=True, upload=b"%PDF-1.4 other", learner="")    # 다른 파일 · id 없음 → 안 잇는다
    d = _open(archive, consent=True, upload=b"%PDF-1.4 same", learner="brw_9999")   # 같은 파일이어도 남이면 안 잇는다 (보안 점검 2026-09-23)
    me = _open(archive, consent=True, learner="brw_0001")
    rows, key = archive.related_sessions(me)
    assert [r.session_id for r in rows] == [a] and key == "learner:brw_0001"
    assert d not in [r.session_id for r in rows] and b not in [r.session_id for r in rows]
    rehearsals_, key2 = archive.rehearsals_for(me)
    assert key2 == key and [len(r["turns"]) for r in rehearsals_] == [1] and rehearsals_[0]["turns"][0]["question_id"] == "q01-c2"
    # 기억 문서에 실리는 id 는 진짜 session_id 가 아니다 — 진짜 id 는 열람·삭제의 열쇠다
    assert rehearsals_[0]["session_id"] != a and rehearsals_[0]["session_id"].startswith("past-")
    # 파일 이름만 같고 내용·id 가 다르면 못 잇는다
    lonely = _open(archive, consent=True, upload=b"%PDF-1.4 unique", learner="zzzz")
    assert archive.related_sessions(lonely) == ([], "")
    assert archive.safe_learner("ok_id-1") == "ok_id-1" and archive.safe_learner("x") == "" and archive.safe_learner("a b") == ""
    assert archive.manifest(me).learner_id == "brw_0001"


def test_memory_doc_은_동의한_세션의_아티팩트로만_남는다(archive):
    sid = _open(archive, consent=True)
    assert archive.put_artifact(sid, "memory_doc", MemoryDoc(note="x").to_dict())
    assert archive.read_artifact(sid, "memory_doc")["note"] == "x"
    nope = _open(archive, consent=False)
    assert not archive.put_artifact(nope, "memory_doc", MemoryDoc(note="x").to_dict())
    assert archive.read_artifact(nope, "memory_doc") is None


def test_이름_잇기는_조사_하나_차이를_넘고_다른_개념은_안_잇는다():
    from chuckchuck.contracts import memory_similarity
    assert memory_similarity(memory_key("알림의 주의 비용"), memory_key("알림 주의 비용")) >= 0.6
    assert memory_similarity(memory_key("Attention residue"), memory_key("attention residue task")) >= 0.6
    assert memory_similarity(memory_key("환경 설계"), memory_key("환경 요인")) < 0.6
    assert memory_similarity("", "x") == 0.0
