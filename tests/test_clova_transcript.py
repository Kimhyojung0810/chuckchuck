"""개발용 클로바 전사 → 녹음 대용 (demo/clova_transcript.py)."""

from demo import clova_transcript as ct

CLOVA = """﻿척척발표 데모용 발표 녹음
2026.08.04 화 오후 3:09 ・ 8분 15초
발표자


00:01
여러분 안녕하세요. 오늘은 수면 이야기를 합니다.

01:20
핵심은 수면의 질입니다.


clovanote.naver.com
"""


def test_클로바_전사를_찾고_길이를_머리말에서_읽는다(tmp_path):
    (tmp_path / "memo.txt").write_text("그냥 메모", encoding="utf-8")
    clova = tmp_path / "녹음.txt"
    clova.write_text(CLOVA, encoding="utf-8")
    assert ct.find_clova_txt(sorted(tmp_path.iterdir())) == clova
    assert ct.duration_of(clova) == 495.0


def test_전사는_구간_안에서_시각을_나누고_주소는_뺀다(tmp_path):
    clova = tmp_path / "녹음.txt"
    clova.write_text(CLOVA, encoding="utf-8")
    t = ct.transcript_dict(clova)
    assert t["full_text"].startswith("여러분 안녕하세요.") and "clovanote" not in t["full_text"]
    starts = [w["start_sec"] for w in t["words"]]
    assert starts == sorted(starts) and starts[0] == 1.0
    assert next(w for w in t["words"] if w["text"] == "핵심은")["start_sec"] == 80.0
    assert t["duration_sec"] == 495.0 and t["by_slide"] == []


def test_무음_wav_의_표식으로_덱을_되찾는다():
    for key in ("수면발표", "deck1"):                  # 홀수·짝수 바이트 길이 둘 다
        wav = ct.marked_silence(key, 3)
        assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
        assert ct.marked_deck_key(wav) == key
    assert ct.marked_deck_key(b"RIFF....WAVEfmt ") is None
    assert ct.marked_deck_key(b"\x00" * 64) is None
