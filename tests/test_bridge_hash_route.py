"""주소창 화면 주소 → 앱 해시 주소 자동 리다이렉트 (demo/bridge.py hash_route_for).

2026-10-01: /booth/call 을 만들고 브리지 고정 표에 넣었지만 8799 가 재시작 전이라 404 가 났다.
그래서 고정 표를 없애고 「파일이 아닌 주소면 해시로」 로 바꿨다 — 새 화면마다 브리지를 고치지 않게.
"""
from demo.bridge import STATIC, hash_route_for


def _nothing(_path):
    return None


def test_screen_paths_go_to_hash_routes():
    assert hash_route_for("/booth/call", _nothing) == "#/booth/call"
    assert hash_route_for("/booth/qa", _nothing) == "#/booth/qa"
    assert hash_route_for("/temp", _nothing) == "#/temp"
    assert hash_route_for("/vision/", _nothing) == "#/vision"


def test_case_is_folded_like_the_old_table():
    assert hash_route_for("/test/QA", _nothing) == "#/test/qa"


def test_files_api_and_auth_are_left_alone():
    for path in ("/", "", "/index.html", "/js/app.js", "/favicon.ico",
                 "/api/v1/team", "/api/health", "/auth", "/auth/", "/sdk/chuckchuck_bridge.js",
                 "/%00", "/a%0d%0aSet-Cookie:x", "/../etc", "/booth/%EC%BD%9C"):
        assert hash_route_for(path, _nothing) is None, path


def test_real_files_and_folders_are_served_not_redirected():
    # 실제로 있는 폴더(css/)는 정적 서빙이 맡는다
    assert STATIC.locate("/css") is not None
    assert hash_route_for("/css", STATIC.locate) is None
    # 없는 화면 주소는 실제 마운트에서도 해시로 간다
    assert hash_route_for("/booth/call", STATIC.locate) == "#/booth/call"
