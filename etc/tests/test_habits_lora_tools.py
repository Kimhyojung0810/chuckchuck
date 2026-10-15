"""etc/habits_lora 재현 도구 — AI Hub 라벨 → JSONL 빌더와 평가 채점식 (GPU·원본 데이터 없이)."""

from __future__ import annotations

import json
import zipfile
from collections import Counter

from habits_lora import aihub
from habits_lora.evaluate import _key, doc_transcript, score


def _label(stt: str, script: str, tags: list[tuple[int, str]]) -> dict:
    # 실제 라벨은 감싸는 층이 판마다 다를 수 있다 — 한 층 감싸 둔다
    return {"dataSet": {"presentation": {"presen_script": script},
                        "script": {"script_stt_txt": stt},
                        "taglist": [{"tag_id": i, "tag_type": t, "tag_keyword": k} for i, (t, k) in enumerate(tags)]}}


def test_parse_label_drops_pause_and_keeps_order():
    r = aihub.parse_label(_label("어 지도 지도력은 음 중요합니다", "원고", [(1, "어"), (3, ""), (2, "지도 지도력은"), (1, "음"), (4, "중요")]), "a1")
    assert r["tags"] == [("FIL", "어"), ("REP", "지도 지도력은"), ("FIL", "음"), ("WR", "중요")]
    assert aihub.target_text(r["tags"], aihub.TASK_TAGS["unified"]) == "REP\t지도 지도력은\nFIL\t어\nFIL\t음\nWR\t중요"
    assert aihub.target_text(r["tags"], ("FIL",)) == "FIL\t어\nFIL\t음"
    assert aihub.target_text([], ("REP",)) == "NONE"
    assert aihub.parse_label({"nothing": 1}, "x") is None


def test_build_groups_same_script_into_one_split(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    with zipfile.ZipFile(src / "TL_1.zip", "w") as z:
        for i in range(40):
            z.writestr(f"d/{i:03d}.json", json.dumps(_label(f"어 발표 {i}", f"원고{i % 10}", [(1, "어")]), ensure_ascii=False))
    (src / "extra.json").write_text(json.dumps(_label("음 끝", "원고0", [(1, "음")]), ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    assert aihub.main(["--src", str(src), "--out", str(out)]) == 0
    split = json.loads((out / "split.json").read_text(encoding="utf-8"))
    assert sum(len(v) for v in split.values()) == 41
    rows = {p: [json.loads(x) for x in (out / "FIL" / f"{p}.jsonl").read_text(encoding="utf-8").splitlines()]
            for p in ("train", "val", "test")}
    shas = {p: {r["script_sha1"] for r in rs} for p, rs in rows.items()}
    assert not (shas["train"] & shas["test"]) and not (shas["train"] & shas["val"])   # 원고 누수 없음
    assert all(r["target"].startswith("FIL\t") for rs in rows.values() for r in rs)


def test_score_is_multiset_micro():
    pred = [Counter({"어": 3, "음": 1}), Counter()]
    gold = [Counter({"어": 2, "음": 2}), Counter({"어": 1})]
    s = score(pred, gold)
    assert (s["tp"], s["pred"], s["gold"]) == (3, 4, 5)
    assert s["precision"] == 0.75 and s["recall"] == 0.6 and s["count_mae"] == 0.5
    assert _key("지도  지도력은,") == "지도지도력은"
    assert [w.text for w in doc_transcript("어 음  발표").words] == ["어", "음", "발표"]
