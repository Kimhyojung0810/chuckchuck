"""
부스 덱 질문 점검 (2026-10-06) — 받아쓰기 오류를 발표자 탓으로 돌린 질문 · 주장 문장 뒤에 조사를 붙인 비문 질문.
"""
import re

from chuckchuck import f08_questions as F
from chuckchuck._align_checks import stt_digit_echo
from chuckchuck.contracts import ConceptNode, TriageMark
from chuckchuck.f11_align import stt_variant


def test_받아쓰기가_숫자를_겹쳐_적은_것은_모순이_아니다():
    assert stt_digit_echo("0.334점", "0.34점")          # 「영 점 삼 사」 의 삼이 두 번
    assert not stt_digit_echo("0.34점", "0.4점")         # 겹친 숫자 없는 차이 — 진짜 틀린 말
    assert not stt_digit_echo("1100명", "110명")         # 겹쳤어도 열 배 차이는 그대로 잡는다
    assert not stt_digit_echo("0.1mg", "1mg")


def _vocab(text):
    w = re.findall(r"[가-힣A-Za-z0-9]+", text)
    w += [re.sub(r"(?:은|는|이|가|을|를|의|로|으로|에|에서|도|와|과)$", "", x) for x in w if len(x) > 2]
    return w + [a + b for a, b in zip(w, w[1:])]


def test_자료_낱말을_비슷한_소리로_받아쓴_것은_발표에만_나온_개념이_아니다():
    v = _vocab("같은 기간 재주문율은 +0.6%p로 사실상 변화가 없었다 리뷰 이벤트")
    assert stt_variant("잼 주문율", v) and stt_variant("제주문율", v)
    assert not stt_variant("재방문율", v) and not stt_variant("쿠폰 할인", v)


def _q(label, source, kind="claim"):
    n = ConceptNode(id="x", label=label, kind=kind, slide_nos=[3])
    return F._fallback_question(n, TriageMark(node_id="x", severity=2, trap=False, angle="", source=source, rank=1,
                                              doc_weight=.5), None, [3])


def test_주장_문장은_따옴표로_감싸_조사를_맞추고_근거를_묻는다():
    q = _q("4.7은 품질이 아니라 리뷰 수집 방식의 결과다", "under_spoken")
    assert q.startswith("「4.7은 품질이 아니라 리뷰 수집 방식의 결과다」는 ") and "핵심을 한 문장으로" not in q and "근거" in q
    q = _q("평균 별점 대신 … 따로 표시해야 한다", "core_weight")
    assert "표시해야 한다」를" in q and "한다를" not in q.replace("」를", "")
    assert _q("온도", "under_spoken", kind="concept").startswith("온도는 ")   # 개념 이름은 예전 그대로


def test_static_hides_team_docs(tmp_path):
    """화면 폴더의 팀 문서(.md) · 손으로 둔 sample-deck.pdf 는 공개 사이트에서 404 (10-02 서비스 플로우 정리안)"""
    from demo.bridge import _static_hidden

    for name, hidden in [("MVP_SPEC.md", True), ("sample-deck.pdf", True), (".env", True),
                         ("index.html", False), ("app.js", False), ("voice_report_live.json", False)]:
        p = tmp_path / name
        p.write_text("x")
        assert _static_hidden(p) is hidden, name
    assert _static_hidden(tmp_path) is False


def test_letter_spaced_line_is_not_gist():
    from chuckchuck.f08_questions import _letter_spaced

    assert _letter_spaced("경 영 정 보 학 과 서 비 스 데 이 터 연 구 실")
    assert not _letter_spaced("배달앱 리뷰 12만 건으로 본 평점 인플레이션의 원인")


def test_deck_audio_by_name_only_public_booth_decks(monkeypatch):
    """받아쓰기가 이름으로 부르는 덱 녹음 — 공개(팀 아님)에서는 부스 덱만, 경로 탈출은 None"""
    import demo.bridge as bridge

    monkeypatch.setattr(bridge, "_dev_open", lambda: False)
    h = bridge.Handler.__new__(bridge.Handler)
    assert h._deck_audio_bytes("../../.env") is None
    assert h._deck_audio_bytes("") is None
    booth = [r["key"] for r in h._deck_entries() if h._public_deck(r["key"]) and r.get("audio")]
    held = [r["key"] for r in h._deck_entries() if not h._public_deck(r["key"]) and r.get("audio")]
    if booth:
        assert h._deck_audio_bytes(booth[0])
    if held:
        assert h._deck_audio_bytes(held[0]) is None
