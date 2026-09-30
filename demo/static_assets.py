"""
정적 파일을 오래 캐시해도 옛 파일이 안 남게 — 브리지가 HTML·ES 모듈을 내줄 때 참조 주소에 내용 해시를 넣는다.

왜 — 공개 경로(Cloudflare → Tailscale Funnel 도쿄 → DERP 홍콩 → VM)는 새 연결 하나에 ~1초, 요청 하나에
~0.2초가 든다 (2026-10-01 실측). 예전엔 모든 응답이 `no-store` 라 첫 화면의 파일 30여 개를 방문할 때마다
그 길로 새로 받았다. `no-store` 는 "고쳤는데 옛 app.js 가 뜬다" 사고를 막으려던 것인데, 그 사고의 원인은
캐시가 아니라 내용이 바뀌어도 주소가 그대로인 것이다. 주소에 내용의 해시를 넣으면 둘 다 풀린다.

- HTML 의 `href="x?v=…"`·`src="x?v=…"` 는 실제 파일이 있으면 `?v=h<해시 10자리>` 로 바꾼다.
  손으로 올리는 `?v=` 규칙(CLAUDE.md §2, scripts/chk bump)은 브리지 밖 정적 호스팅을 위해 그대로 둔다.
- ES 모듈(줄 머리에 import/export 가 있는 .js)의 `import … from './x.js'` 도 같은 식으로 바꾼다. 모듈의 해시는
  바꿔 쓴 뒤의 내용으로 매기므로 import 하는 파일이 바뀌면 부모의 해시도 따라 바뀐다 (SDK 사슬 4단이 캐시된다).
- 요청의 `v` 가 지금 내줄 내용의 해시와 같을 때만 1년 `immutable` 로 캐시한다 — 브라우저도 Cloudflare 도.
  다르거나 없으면 `no-cache`(ETag 로 재검증, 안 바뀌었으면 304)라 옛 내용이 남을 수 없다.
- 글자 파일은 gzip 으로 줄여 보낸다 (Funnel 로 바로 오는 방문자는 압축 없이 1.5MB 를 받았다).
"""

from __future__ import annotations

import gzip
import hashlib
import posixpath
import re
import threading
from pathlib import Path
from urllib.parse import unquote

IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"
COMPRESSIBLE = frozenset({".js", ".mjs", ".css", ".html", ".json", ".svg", ".txt", ".map", ".md", ".ico"})
MIN_GZIP_BYTES = 1024
HASH_PREFIX = "h"

# href="css/app.css?v=ql9" · src="js/app.js?v=ql23" — 값은 따옴표나 & 앞에서 끊는다
_ATTR_V = re.compile(r'(\b(?:href|src)=")([^"?#]+)\?v=([^"&#]*)')
# 줄 머리의 정적 import/export … from '…' · import '…' (여러 줄에 걸친 { a, b } 도)
_MODULE_LINE = re.compile(r"^\s*(?:import|export)\b", re.M)
_IMPORT = re.compile(r"""^(\s*(?:import|export)\b[^;'"]*?)(['"])([^'"?#]+)(?:\?v=[^'"&#]*)?\2""", re.M)
_EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//)", re.I)


def content_digest(data: bytes) -> str:
    return HASH_PREFIX + hashlib.sha1(data).hexdigest()[:10]


class AssetCache:
    """
    URL 경로 → 파일, 그리고 그 파일을 «내줄 때의» 본문·해시. mounts 는 {URL 접두사: 폴더}, 긴 접두사가 먼저다.
    원본 해시·gzip 은 (경로, mtime, 크기) 로 기억한다. 바꿔 쓰는 HTML·모듈은 작아서 요청마다 다시 만든다 —
    import 한 파일이 바뀌었는지까지 기억으로 따지는 것보다 싸고 틀릴 일이 없다.
    """

    def __init__(self, mounts: dict[str, Path]) -> None:
        self.mounts = sorted(((p if p.endswith("/") else p + "/", Path(d).resolve()) for p, d in mounts.items()),
                             key=lambda m: -len(m[0]))
        self._lock = threading.Lock()
        self._raw: dict[tuple, str] = {}
        self._gz: dict[tuple, bytes] = {}

    # ── 주소 ─────────────────────────────────────────────────────────────────
    def locate(self, url_path: str) -> Path | None:
        """URL 경로(쿼리 없이) → 마운트 안의 실제 경로(파일·폴더). 밖으로 나가거나 없으면 None."""
        if "\x00" in url_path:
            return None
        norm = posixpath.normpath("/" + unquote(url_path).lstrip("/"))
        for prefix, root in self.mounts:
            if norm == prefix.rstrip("/") or norm.startswith(prefix) or prefix == "/":
                rel = norm[len(prefix):] if norm.startswith(prefix) else ""
                try:
                    p = (root / rel).resolve() if rel else root
                except OSError:
                    return None
                if p != root and root not in p.parents:
                    return None
                return p if p.exists() else None
        return None

    @staticmethod
    def join(base_url_dir: str, ref: str) -> str | None:
        if not ref or _EXTERNAL.match(ref):
            return None
        return posixpath.normpath(ref if ref.startswith("/") else posixpath.join(base_url_dir, ref))

    # ── 해시 ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _key(path: Path) -> tuple | None:
        try:
            st = path.stat()
        except OSError:
            return None
        return (str(path), st.st_mtime_ns, st.st_size)

    def _raw_digest(self, path: Path) -> str | None:
        key = self._key(path)
        if key is None or not path.is_file():
            return None
        with self._lock:
            hit = self._raw.get(key)
        if hit:
            return hit
        d = content_digest(path.read_bytes())
        with self._lock:
            self._raw[key] = d
        return d

    @staticmethod
    def rewrites(path: Path, text: str | None = None) -> str:
        """이 파일이 참조 주소를 바꿔 쓰는 종류인가 — 'html' · 'module' · ''."""
        suffix = path.suffix.lower()
        if suffix == ".html":
            return "html"
        if suffix in (".js", ".mjs"):
            if text is None:
                text = path.read_text(encoding="utf-8", errors="replace")
            return "module" if _MODULE_LINE.search(text) else ""
        return ""

    def served(self, url_path: str, _stack: frozenset = frozenset()) -> tuple[bytes, str] | None:
        """내줄 본문과 그 해시. 파일이 아니면 None."""
        path = self.locate(url_path)
        if path is None or not path.is_file():
            return None
        raw = path.read_bytes()
        if path.suffix.lower() not in (".html", ".js", ".mjs"):
            return raw, self._raw_digest(path) or content_digest(raw)
        text = raw.decode("utf-8", errors="replace")
        kind = self.rewrites(path, text)
        if not kind:
            return raw, self._raw_digest(path) or content_digest(raw)
        base = posixpath.dirname(posixpath.normpath("/" + unquote(url_path).lstrip("/")))
        stack = _stack | {url_path}

        def digest_of(ref: str) -> str | None:
            target = self.join(base, ref)
            if not target or target in stack:  # 서로 import 하는 고리는 원본 해시로 끊는다
                p = self.locate(target) if target else None
                return self._raw_digest(p) if p and p.is_file() else None
            got = self.served(target, stack)
            return got[1] if got else None

        if kind == "html":
            out = _ATTR_V.sub(lambda m: (f"{m.group(1)}{m.group(2)}?v={d}" if (d := digest_of(m.group(2)))
                                         else m.group(0)), text)
        else:
            out = _IMPORT.sub(lambda m: (f"{m.group(1)}{m.group(2)}{m.group(3)}?v={d}{m.group(2)}"
                                         if (d := digest_of(m.group(3))) else m.group(0)), text)
        body = out.encode("utf-8")
        return body, content_digest(body)

    # ── 압축 ─────────────────────────────────────────────────────────────────
    def gzipped(self, path: Path, data: bytes) -> bytes:
        key = (self._key(path), content_digest(data))
        with self._lock:
            hit = self._gz.get(key)
        if hit is not None:
            return hit
        gz = gzip.compress(data, compresslevel=6, mtime=0)
        with self._lock:
            if len(self._gz) > 512:  # 오래 켜 둔 개발 브리지가 옛 판을 끝없이 쥐지 않게
                self._gz.clear()
            self._gz[key] = gz
        return gz


def accepts_gzip(accept_encoding: str) -> bool:
    for part in (accept_encoding or "").lower().split(","):
        name, _, params = part.strip().partition(";")
        if name.strip() not in ("gzip", "*"):
            continue
        q = params.replace(" ", "").partition("q=")[2]
        try:
            return float(q) > 0 if q else True
        except ValueError:
            return True
    return False


def etag_matches(if_none_match: str, etag: str) -> bool:
    if not if_none_match:
        return False
    if if_none_match.strip() == "*":
        return True
    bare = etag.removeprefix("W/")
    return any(t.strip().removeprefix("W/") == bare for t in if_none_match.split(","))
