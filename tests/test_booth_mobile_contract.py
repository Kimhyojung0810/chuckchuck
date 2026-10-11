"""
부스 모바일(/hi 팀 소개 · #/tour 체험 투어) 데이터 계약 — docs/booth-mobile/*.schema.json 이 단일 원본이다 (2026-10-11).

- 스키마로 data/team.json · data/tour/*.json 을 검사한다 (jsonschema 의존성을 더하지 않으려고 쓰는 부분만 직접 검사).
- 스키마가 못 말하는 짝 맞춤(장 번호가 덱에 있는가 · 그림 파일이 있고 공개인가 · 시각이 차례인가 · 그래프 끝점)을 따로 본다.
- 공개 허용 목록이 이 파일들을 열고, 다른 data/*.json 은 여전히 팀 전용인지 · 주소창 /hi · /tour/* 가 해시로 가는지.
- 마지막 케이스는 이 검사기가 진짜로 틀린 데이터를 잡는지 스스로 확인한다.
"""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

import pytest

import demo.bridge as bridge
from demo.static_assets import static_access
from tests.test_static_assets import RawHandler

ROOT = Path(__file__).resolve().parents[1]
WEB = bridge.DEMO_DIR
DOCS = ROOT / "docs" / "booth-mobile"
TOUR_SCHEMA = json.loads((DOCS / "tour.schema.json").read_text(encoding="utf-8"))
TEAM_SCHEMA = json.loads((DOCS / "team.schema.json").read_text(encoding="utf-8"))
INDEX_SCHEMA = json.loads((DOCS / "tour-index.schema.json").read_text(encoding="utf-8"))
#: data/tour/index.json 은 투어가 아니라 투어 **목록**이다 (tour-index.schema.json, 10-11 lab/tour-fixtures) — 투어 검사에서 뺀다
INDEX_FILE = WEB / "data" / "tour" / "index.json"
TOUR_FILES = sorted(p for p in (WEB / "data" / "tour").glob("*.json") if p.name != INDEX_FILE.name)
TEAM_FILE = WEB / "data" / "team.json"


# ─── 작은 스키마 검사기 (draft 2020-12 의 쓰는 부분만) ───────────────────────

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}
_KNOWN = {"$schema", "$id", "title", "description", "$defs", "type", "const", "enum", "required", "properties",
          "additionalProperties", "items", "minItems", "maxItems", "minLength", "maxLength", "pattern",
          "minimum", "maximum", "$ref"}


def check(value, schema: dict, root: dict, path: str = "$") -> list[str]:
    unknown = set(schema) - _KNOWN
    assert not unknown, f"{path}: 검사기가 모르는 스키마 낱말 {unknown} — 검사기에 더하거나 스키마에서 뺀다"
    if "$ref" in schema:
        name = schema["$ref"].removeprefix("#/$defs/")
        return check(value, root["$defs"][name], root, path)
    errs: list[str] = []
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPES[t](value) for t in types):
            return [f"{path}: {types} 이어야 하는데 {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        errs.append(f"{path}: {schema['const']!r} 이어야 하는데 {value!r}")
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {schema['enum']} 밖의 값 {value!r}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errs.append(f"{path}: 너무 짧다")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{path}: {schema['maxLength']}자를 넘는다 ({len(value)}자) — 폰 한 줄에 안 들어간다")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(f"{path}: 모양 {schema['pattern']} 에 안 맞는다 — {value!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: {schema['minimum']} 보다 작다")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: {schema['maximum']} 보다 크다")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errs.append(f"{path}: {key} 가 없다")
        props = schema.get("properties", {})
        for key, sub in value.items():
            if key in props:
                errs += check(sub, props[key], root, f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}: 계약에 없는 칸 {key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errs.append(f"{path}: {schema['minItems']}개 이상이어야 한다")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{path}: {schema['maxItems']}개를 넘는다")
        if "items" in schema:
            for i, item in enumerate(value):
                errs += check(item, schema["items"], root, f"{path}[{i}]")
    return errs


# ─── 스키마가 못 말하는 짝 맞춤 ─────────────────────────────────────────────

def _asset_ok(rel: str) -> list[str]:
    errs = []
    if static_access("/" + rel) != "public":
        errs.append(f"{rel}: 공개 허용 목록 밖 — 공개 사이트에서 404")
    if not (WEB / rel).is_file():
        errs.append(f"{rel}: 파일이 없다")
    return errs


def tour_semantics(t: dict, file_id: str | None = None) -> list[str]:
    errs: list[str] = []
    if file_id is not None and t["id"] != file_id:
        errs.append(f"id {t['id']!r} 가 파일 이름 {file_id!r} 와 다르다")
    deck = t["deck"]
    nos = [s["no"] for s in deck["slides"]]
    if nos != list(range(1, len(nos) + 1)):
        errs.append(f"deck.slides 의 no 가 1부터 차례가 아니다: {nos}")
    have = set(nos)
    errs += _asset_ok(deck["cover"])
    for s in deck["slides"]:
        errs += _asset_ok(s["image"])
        if f"deck-slides/{deck['id']}/" not in s["image"]:
            errs.append(f"{s['image']}: deck.id({deck['id']}) 폴더가 아니다")

    def slide_ref(where: str, n) -> None:
        if n is not None and n not in have:
            errs.append(f"{where}: {n}장은 덱에 없다")

    p = t["present"]
    dur = p["duration_sec"]
    prev_end = 0
    for i, s in enumerate(p["slides"]):
        slide_ref(f"present.slides[{i}]", s["slide_no"])
        if not (prev_end <= s["start_sec"] < s["end_sec"] <= dur):
            errs.append(f"present.slides[{i}]: 넘김 시각이 차례가 아니거나 duration 밖")
        prev_end = s["end_sec"]
    for key in ("transcript", "coaching_chips"):
        last = -1
        for i, x in enumerate(p[key]):
            slide_ref(f"present.{key}[{i}]", x["slide_no"])
            at = x.get("start_sec", x.get("at_sec"))
            if at < last or at > dur or x.get("end_sec", at) < at or x.get("end_sec", at) > dur:
                errs.append(f"present.{key}[{i}]: 시각이 차례가 아니거나 duration 밖")
            last = at
    a = t["analysis"]
    for i, s in enumerate(a["slide_times"]):
        slide_ref(f"analysis.slide_times[{i}]", s["slide_no"])
    g = a["claim_graph"]
    ids = [n["id"] for n in g["nodes"]]
    if len(set(ids)) != len(ids):
        errs.append("claim_graph.nodes id 가 겹친다")
    if g["root"] not in ids:
        errs.append(f"claim_graph.root {g['root']!r} 가 nodes 에 없다")
    for i, n in enumerate(g["nodes"]):
        slide_ref(f"claim_graph.nodes[{i}]", n["slide_no"])
    for i, e in enumerate(g["edges"]):
        if e["from"] not in ids or e["to"] not in ids:
            errs.append(f"claim_graph.edges[{i}]: 없는 노드를 잇는다")
    qids = [q["id"] for q in t["qa"]["questions"]]
    if len(set(qids)) != len(qids):
        errs.append("qa.questions id 가 겹친다")
    for q in t["qa"]["questions"]:
        slide_ref(f"qa.{q['id']}", q["slide_no"])
        good, rough = q["answers"]["good"], q["answers"]["rough"]
        if good["verdict"] != "good":
            errs.append(f"qa.{q['id']}: 「잘 답한 답」 의 판정이 good 이 아니다 — 비교가 성립하지 않는다")
        if rough["verdict"] == "good":
            errs.append(f"qa.{q['id']}: 「엉성한 답」 이 good 으로 판정돼 있다")
        for kind, ans in (("good", good), ("rough", rough)):
            for j, gr in enumerate(ans["grounds"]):
                slide_ref(f"qa.{q['id']}.{kind}.grounds[{j}]", gr["slide_no"])
                if not gr["ref"].startswith(f"S{gr['slide_no']}-"):
                    errs.append(f"qa.{q['id']}.{kind}.grounds[{j}]: ref {gr['ref']} 와 slide_no {gr['slide_no']} 가 다르다")
    rids = [x["id"] for x in t["report"]["items"]]
    if len(set(rids)) != len(rids):
        errs.append("report.items id 가 겹친다")
    for i, s in enumerate(t["report"]["next_steps"]):
        slide_ref(f"report.next_steps[{i}]", s["slide_no"])
    return errs


def team_semantics(team: dict) -> list[str]:
    errs: list[str] = []
    ids = [m["id"] for m in team["members"]]
    if len(set(ids)) != len(ids):
        errs.append("members id 가 겹친다")
    for m in team["members"]:
        if m["photo"] is not None:
            errs += _asset_ok(m["photo"])
    return errs


# ─── 실제 파일 ─────────────────────────────────────────────────────────────

def test_투어_예시가_있다():
    assert (WEB / "data" / "tour" / "_example.json") in TOUR_FILES


@pytest.mark.parametrize("path", TOUR_FILES, ids=lambda p: p.name)
def test_투어_파일은_계약을_지킨다(path):
    t = json.loads(path.read_text(encoding="utf-8"))
    assert check(t, TOUR_SCHEMA, TOUR_SCHEMA) == []
    assert tour_semantics(t, path.stem) == []


def test_예시가_아닌_투어는_녹화본이라고_적는다():
    for path in TOUR_FILES:
        t = json.loads(path.read_text(encoding="utf-8"))
        assert (t["source"]["kind"] == "example") == path.stem.startswith("_"), path.name


def test_투어_목록은_계약을_지키고_투어_파일과_맞는다():
    """index.json 이 있으면: 스키마 · 기본 덱 · 각 id 의 투어 파일 · 제목/장 수/길이/질문 수가 투어 파일과 같은지 · 예시는 안 싣는다."""
    if not INDEX_FILE.is_file():
        pytest.skip("data/tour/index.json 이 아직 없다")
    idx = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    assert check(idx, INDEX_SCHEMA, INDEX_SCHEMA) == []
    ids = [row["id"] for row in idx["tours"]]
    assert len(set(ids)) == len(ids)
    assert (idx["default"] in ids) if ids else idx["default"] is None
    recorded = {p.stem for p in TOUR_FILES if not p.stem.startswith("_")}
    assert set(ids) == recorded, "목록과 녹화 투어 파일이 어긋난다 — labs/tour_capture/build.py 로 같이 만든다"
    for row in idx["tours"]:
        t = json.loads((WEB / "data" / "tour" / f"{row['id']}.json").read_text(encoding="utf-8"))
        assert (row["title"], row["subtitle"], row["cover"]) == (t["deck"]["title"], t["deck"].get("subtitle"), t["deck"]["cover"]), row["id"]
        assert row["slides"] == len(t["deck"]["slides"]) and row["questions"] == len(t["qa"]["questions"]), row["id"]
        assert row["duration_sec"] == t["present"]["duration_sec"] and row["recorded_at"] == t["source"]["recorded_at"], row["id"]
        assert _asset_ok(row["cover"]) == []


def test_팀_카드는_계약을_지킨다():
    team = json.loads(TEAM_FILE.read_text(encoding="utf-8"))
    assert check(team, TEAM_SCHEMA, TEAM_SCHEMA) == []
    assert team_semantics(team) == []


def test_팀_카드에_지어낸_한마디가_없다():
    """본인 확인 전(draft)인 카드에 한마디(quote)를 대신 써 넣지 않는다 — 실제 사람의 말로 읽힌다."""
    team = json.loads(TEAM_FILE.read_text(encoding="utf-8"))
    for m in team["members"]:
        if m["draft"]:
            assert m["quote"] is None, m["id"]


#: 방문객에게 안 보일 내부 말 — 모듈 번호(F-07 …) · 「토스 규칙」 (perf-security-copy-r1-6, 8/7 「모듈 코드를 사람 말로」 규칙)
_INTERNAL = re.compile(r"\b[A-Z]{1,3}-\d{1,3}\b|토스")


def team_text_problems(team: dict) -> list[str]:
    errs = []
    for m in team["members"]:
        for where, text in [("role", m["role"]), ("headline", m["headline"]), *((f"did[{i}]", d) for i, d in enumerate(m["did"]))]:
            if _INTERNAL.search(text):
                errs.append(f"{m['id']}.{where}: 내부 말 — {text}")
    return errs


def test_팀_카드에_내부_모듈_번호와_내부_말이_없다():
    assert team_text_problems(json.loads(TEAM_FILE.read_text(encoding="utf-8"))) == []


def test_내부_말_검사기는_모듈_번호를_잡는다():
    team = {"members": [{"id": "a", "role": "개발", "headline": "x", "did": ["자료를 그래프로 바꾸는 F-07", "토스 규칙으로 다시 짜기"]}]}
    assert len(team_text_problems(team)) == 2


@pytest.mark.skipif(os.environ.get("DEMO_RELEASE") != "1", reason="배포 직전(DEMO_RELEASE=1)에만 — 평소엔 팀원이 채우는 중이다")
def test_배포_전에는_모든_팀_카드를_본인이_확인했다():
    """perf-security-copy-r1-5 — 다섯 장 모두 draft:true 인 채로 배포를 막는 장치가 없었다. DEPLOY.md §1 이 DEMO_RELEASE=1 로 부른다."""
    team = json.loads(TEAM_FILE.read_text(encoding="utf-8"))
    assert [m["id"] for m in team["members"] if m["draft"]] == [], "본인 확인 전 카드 — 확인하면 draft 를 false 로"


def test_바깥_브라우저_안내_시트는_hi_와_투어가_같은_말과_순서다():
    """layout-touch-a11y-r1-9 — 한 방문객이 두 시트를 다 본다. 제목 · 「여기서 계속 열기」 · iOS 안내 · 버튼 순서(주 버튼 → 주소 복사 → 계속 열기 → 닫기)."""
    tour_js = (WEB / "js" / "tour.js").read_text(encoding="utf-8")
    intro = (WEB / "intro.html").read_text(encoding="utf-8")
    copy = dict(re.findall(r"^\s+(title|iosTip|here): '([^']+)',$", tour_js[tour_js.index("const INAPP_COPY"):], re.M)[:3])
    assert set(copy) == {"title", "iosTip", "here"}, copy
    sheet = intro[intro.index('id="inapp"'):]
    assert f">{copy['title']}<" in sheet
    assert f">{copy['here']}<" in sheet
    assert copy["iosTip"] in sheet
    order = [sheet.index(x) for x in ('id="inapp-open"', 'id="inapp-copy"', 'id="inapp-anyway"', 'id="inapp-close"')]
    assert order == sorted(order), "주 버튼 → 주소 복사 → 여기서 계속 열기 → 닫기"


def test_투어_주소를_공유해도_미리보기가_뜬다():
    """perf-security-copy-r1-8 — 투어 링크(/index.html#/tour)를 카톡으로 보내면 index.html 에 설명 · 그림이 없어 빈 미리보기였다."""
    index = (WEB / "index.html").read_text(encoding="utf-8")
    intro = (WEB / "intro.html").read_text(encoding="utf-8")
    meta = lambda html, prop: (re.search(rf'<meta (?:property|name)="{re.escape(prop)}" content="([^"]+)"', html) or [None, None])[1]  # noqa: E731
    for prop in ("og:image", "og:site_name", "og:locale"):
        assert meta(index, prop) and meta(index, prop) == meta(intro, prop), prop
    assert meta(index, "description") and meta(index, "og:title") and meta(index, "og:description")
    assert meta(index, "og:image").startswith("https://"), "미리보기 그림은 절대 주소여야 뜬다"


# ─── 공개 허용 목록 · 주소 ──────────────────────────────────────────────────

@pytest.mark.parametrize("url", ["/data/team.json", "/data/tour/delivery-rating.json", "/data/tour/index.json",
                                 "/assets/team/hyojung.webp", "/assets/team/a.jpg"])
def test_부스_모바일_데이터는_공개다(url):
    assert static_access(url) == "public", url


def test_형식_예시_투어는_공개하지_않는다():
    """perf-security-copy-r2-9 (10-12 2차) — 밑줄로 시작하는 투어 파일(_example · 모양을 보이려고 지은 발화 · 판정)은 공개 주소로 안 연다."""
    assert static_access("/data/tour/_example.json") is None


def test_투어는_목록을_못_받아도_형식_예시로_바꿔_보이지_않는다():
    """flow-regression-inapp-r2-4 (10-12 2차) — index.json 이 한 번 실패하면 지은 값(_example)을 녹화처럼 탭 내내 보였다.
    다시 받아 보고, 그래도 안 되면 오류 화면(다시 불러오기)으로 간다."""
    src = (WEB / "js" / "tour.js").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith(("*", "//", "/*")))
    assert "_example" not in code


@pytest.mark.parametrize("url,level", [
    ("/data/voice_report_live.json", "team"),      # 다른 data/*.json 은 여전히 팀 전용
    ("/data/tour/", None), ("/data/tour/x/y.json", None), ("/data/tour/x.md", None),
    ("/assets/team/x.gif", None), ("/assets/team/sub/x.webp", None), ("/data/teams.json", "team"),
])
def test_공개로_연_것_말고는_그대로다(url, level):
    assert static_access(url) == level, url


def test_공개_방문자가_팀_카드와_투어를_받는다(monkeypatch):
    monkeypatch.setattr(bridge, "REQUIRE_ACCESS", False)
    monkeypatch.setattr(bridge, "ALLOWED_HOSTS", set())
    monkeypatch.setattr(bridge, "DEV_ROUTES", False)
    monkeypatch.setattr(bridge, "TEAM_CODE", "")
    for url in ("/data/team.json", "/data/tour/delivery-rating.json"):
        h = RawHandler(url)
        h.do_GET()
        status, _, body = h.response()
        assert status == 200, url
        assert json.loads(body)["version"] == 1, url
    h = RawHandler("/data/voice_report_live.json")
    h.do_GET()
    assert h.response()[0] == 404


@pytest.mark.parametrize("path,expect", [("/tour", "#/tour"), ("/tour/deck", "#/tour/deck"), ("/tour/report", "#/tour/report")])
def test_주소창_tour_는_해시_화면으로_간다(path, expect):
    assert bridge.hash_route_for(path, bridge.STATIC.locate) == expect


@pytest.mark.parametrize("path,expect", [("/hi", "/intro.html"), ("/HI", "/intro.html"), ("/hi/", "/intro.html"),
                                         ("/hi/hyojung", "/intro.html"), ("/hi/a/b", None), ("/hi/x.json", None),
                                         ("/hire", None), ("/tour", None)])
def test_주소창_hi_는_해시_앱이_아니라_랜딩_페이지다(path, expect):
    """/hi 는 app.js 를 안 싣는 가벼운 랜딩(intro.html) — 302 로 #/hi 에 보내지 않고 그 자리에서 준다 (2026-10-11)."""
    assert bridge.standalone_page_for(path) == expect


@pytest.mark.parametrize("url", ["/hi", "/hi/seokhoon"])
def test_공개_방문자가_hi_에서_랜딩을_받는다(monkeypatch, url):
    monkeypatch.setattr(bridge, "REQUIRE_ACCESS", False)
    monkeypatch.setattr(bridge, "ALLOWED_HOSTS", set())
    monkeypatch.setattr(bridge, "DEV_ROUTES", False)
    monkeypatch.setattr(bridge, "TEAM_CODE", "")
    h = RawHandler(url)
    h.do_GET()
    status, _, body = h.response()
    assert status == 200, url
    html = body.decode("utf-8")
    assert "척척발표를 만든 사람들" in html and 'href="/index.html#/tour"' in html
    # 주소가 /hi/<id> 이기도 해서 로컬 참조는 / 로 시작해야 한다 (상대 경로면 /hi/css/… 로 샌다)
    for ref in re.findall(r'(?:href|src)="([^"#]+)"', html):
        if not re.match(r"^(?:https?:)?//", ref):
            assert ref.startswith("/"), ref


# ─── 검사기가 진짜로 잡는가 ───────────────────────────────────────────────

def _example() -> dict:
    return json.loads((WEB / "data" / "tour" / "_example.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("mutate,needle", [
    (lambda t: t.update(version=2), "version"),
    (lambda t: t["analysis"].update(level="great"), "analysis.level"),
    (lambda t: t["qa"]["questions"][0]["answers"].pop("rough"), "rough 가 없다"),
    (lambda t: t["qa"]["questions"][0]["answers"]["good"].update(score=90), "계약에 없는 칸 score"),
    (lambda t: t["present"]["coaching_chips"][0].update(text="아주 긴 코칭 칩 문구는 폰에서 넘친다"), "16자"),
    (lambda t: t["qa"]["questions"][0]["answers"]["good"]["grounds"][0].update(role="supported"), "role"),
    (lambda t: t["deck"].update(cover="/assets/deck-covers/x.webp"), "deck.cover"),
])
def test_검사기는_스키마_위반을_잡는다(mutate, needle):
    t = _example()
    mutate(t)
    errs = check(t, TOUR_SCHEMA, TOUR_SCHEMA)
    assert any(needle in e for e in errs), errs


@pytest.mark.parametrize("mutate,needle", [
    (lambda t: t["qa"]["questions"][1].update(slide_no=9), "9장은 덱에 없다"),
    (lambda t: t["analysis"]["claim_graph"].update(root="nope"), "root"),
    (lambda t: t["qa"]["questions"][0]["answers"]["good"].update(verdict="partial"), "잘 답한 답"),
    (lambda t: t["present"]["slides"][1].update(start_sec=10), "넘김 시각"),
    (lambda t: t["deck"]["slides"][0].update(image="assets/deck-slides/delivery-rating/99.webp"), "파일이 없다"),
])
def test_검사기는_짝이_안_맞는_것을_잡는다(mutate, needle):
    t = copy.deepcopy(_example())
    mutate(t)
    errs = tour_semantics(t)
    assert any(needle in e for e in errs), errs
