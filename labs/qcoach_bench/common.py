"""질문 코치 벤치가 같이 쓰는 것 — 경로 · .env · 얼린 입력 · 핵심 개념 · 결과 태그."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from textrules import squash

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "out"
FIX = OUT / "fixtures"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))      # chuckchuck 패키지 — 스크립트로 돌면 이 폴더만 경로에 있다
#: worktree 에는 .gitignore 대상(.env · 파싱본)이 없다 — 본 체크아웃(../chuckchuck)의 것으로 물러선다
MAIN_CHECKOUT = ROOT.parent / "chuckchuck"
#: 시나리오 — A 는 첫 세션만, 나머지는 첫 질문에 답한 뒤 다음 리허설(session2)까지 돈다
FOLLOW_UPS = ("B", "C", "D", "E")


def first_existing(rel: str) -> Path:
    """이 저장소에 있으면 그것, 없으면 본 체크아웃의 것 (둘 다 없으면 이 저장소 경로 — 읽는 쪽이 없다고 알린다)."""
    return next((p for p in (ROOT / rel, MAIN_CHECKOUT / rel) if p.exists()), ROOT / rel)


def load_env() -> None:
    """API 키를 환경에 싣는다. 값은 출력하지 않는다."""
    from dotenv import load_dotenv
    path = first_existing(".env")
    if path.exists():
        load_dotenv(path)


def load_fixtures() -> dict:
    """prepare.py 가 얼린 입력 — graph · slidedoc · claims · context."""
    return {name: json.loads((FIX / f"{name}.json").read_text()) for name in ("graph", "slidedoc", "claims", "context")}


def load_keys() -> dict:
    return json.loads((HERE / "key_concepts.json").read_text())


def misquoted_evidence(keys: dict, slides: dict[int, str]) -> list[str]:
    """핵심 개념의 원문 근거 가운데 그 장 본문에 글자 그대로(공백 무시) 없는 것 — 「K1 S5 «…»」. 비면 전부 원문 그대로다."""
    return [f"{c['id']} S{e['slide']} «{e['quote']}»" for c in keys["concepts"] for e in c["evidence"]
            if squash(e["quote"]) not in squash(slides.get(e["slide"], ""))]


def keys_of(label: str, keys: dict) -> set[str]:
    """대상 노드 이름(공백 뺀 것)에 별칭 조각이 든 핵심 개념 id 들."""
    lab = squash(label)
    return {c["id"] for c in keys["concepts"] if any(a.lower() in lab for a in c["aliases"])}


def key_of(label: str, keys: dict) -> str:
    """질문 하나 = 핵심 개념 하나 — 걸린 것 가운데 번호가 앞선 것."""
    ks = keys_of(label, keys)
    return min(ks) if ks else ""


def load_tag(tag: str) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((OUT / tag).glob("rep*.json"))]
