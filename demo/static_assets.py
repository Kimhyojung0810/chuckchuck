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
- 공개 서비스에서는 JS·CSS 의 주석·공백을 esbuild 로 걷는다 (Minifier). 이 코드는 한국어 주석이 많아
  압축 뒤 크기의 절반 가까이가 주석이었다 (첫 화면 JS·CSS gzip 539KB → 301KB). 이름·문법은 건드리지 않는다.
"""

from __future__ import annotations

import gzip
import hashlib
import posixpath
import re
import subprocess
import sys
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
        self._raw: dict[tuple, tuple[str, str]] = {}  # (원본 해시, 'html'·'module'·'')
        self._gz: dict[tuple, bytes] = {}

    # ── 주소 ─────────────────────────────────────────────────────────────────
    def locate(self, url_path: str) -> Path | None:
        """URL 경로(쿼리 없이) → 마운트 안의 실제 경로(파일·폴더). 밖으로 나가거나 없으면 None."""
        decoded = unquote(url_path)
        if "\x00" in decoded or "\x00" in url_path:
            return None
        norm = posixpath.normpath("/" + decoded.lstrip("/"))
        for prefix, root in self.mounts:
            if norm == prefix.rstrip("/") or norm.startswith(prefix) or prefix == "/":
                rel = norm[len(prefix):] if norm.startswith(prefix) else ""
                try:
                    p = (root / rel).resolve() if rel else root
                except (OSError, ValueError):
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

    def _info(self, path: Path) -> tuple[str, str] | None:
        """(원본 해시, 종류). 파일 상태(mtime·크기)로 기억해서 HTML 을 낼 때마다 참조 파일을 다시 읽지 않는다."""
        key = self._key(path)
        if key is None or not path.is_file():
            return None
        with self._lock:
            hit = self._raw.get(key)
        if hit:
            return hit
        raw = path.read_bytes()
        kind = self.rewrites(path, raw.decode("utf-8", errors="replace")) if self._maybe_rewrites(path) else ""
        info = (content_digest(raw), kind)
        with self._lock:
            if len(self._raw) > 4096:
                self._raw.clear()
            self._raw[key] = info
        return info

    @staticmethod
    def _maybe_rewrites(path: Path) -> bool:
        return path.suffix.lower() in (".html", ".js", ".mjs")

    def _imports(self, url_path: str) -> list[str]:
        """모듈이 정적으로 import 하는 URL 들 (고리 찾기용 — 원본 글에서 읽는다)."""
        path = self.locate(url_path)
        if path is None or not path.is_file() or path.suffix.lower() not in (".js", ".mjs"):
            return []
        text = path.read_text(encoding="utf-8", errors="replace")
        if not _MODULE_LINE.search(text):
            return []
        base = posixpath.dirname(posixpath.normpath("/" + unquote(url_path).lstrip("/")))
        return [t for m in _IMPORT.finditer(text) if (t := self.join(base, m.group(3)))]

    def in_cycle(self, url_path: str) -> bool:
        """이 모듈에서 import 를 따라가면 자기에게 돌아오는가. 고리 안의 모듈은 어느 쪽에서 들어오느냐에 따라
        해시가 달라져 같은 모듈이 두 주소로 두 번 실행되므로, 고리에는 해시를 넣지 않는다 (예전 주소 그대로)."""
        seen: set[str] = set()
        todo = list(self._imports(url_path))
        while todo:
            u = todo.pop()
            if u == url_path:
                return True
            if u in seen or len(seen) > 200:
                continue
            seen.add(u)
            todo.extend(self._imports(u))
        return False

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
        # 해시는 방금 읽은 바이트로 매긴다 — 읽는 사이 파일이 바뀌어도 내보내는 본문과 해시가 어긋나지 않게
        if not self._maybe_rewrites(path):
            return raw, content_digest(raw)
        text = raw.decode("utf-8", errors="replace")
        kind = self.rewrites(path, text)
        if not kind or (kind == "module" and self.in_cycle(url_path)):
            return raw, content_digest(raw)
        base = posixpath.dirname(posixpath.normpath("/" + unquote(url_path).lstrip("/")))
        stack = _stack | {url_path}

        def digest_of(ref: str) -> str | None:
            target = self.join(base, ref)
            p = self.locate(target) if target else None
            info = self._info(p) if p is not None else None
            if not info:
                return None
            if not info[1]:
                return info[0]  # 바꿔 쓰지 않는 파일 — 기억한 원본 해시 (다시 읽지 않는다)
            if target in stack or (info[1] == "module" and self.in_cycle(target)):
                return None  # 고리 — 주소를 건드리지 않는다
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


class Minifier:
    """
    esbuild 로 주석·공백만 걷는다 (--minify-whitespace — 이름 바꾸기·문법 줄이기는 안 한다, 한글은 그대로 utf-8).
    바이너리가 없거나 실패하면 원본을 그대로 돌려준다 — 줄이지 못해도 화면은 돈다.
    결과는 입력 내용의 해시로 기억한다.
    """

    def __init__(self, binary: str | None) -> None:
        self.binary = binary
        self._lock = threading.Lock()
        self._memo: dict[tuple[str, str], bytes] = {}
        self._warned = False

    @property
    def enabled(self) -> bool:
        return bool(self.binary)

    def __call__(self, data: bytes, loader: str, name: str = "") -> bytes:
        if not self.binary or loader not in ("js", "css") or name.endswith(".min.js"):
            return data
        key = (loader, hashlib.sha1(data).hexdigest())
        with self._lock:
            hit = self._memo.get(key)
        if hit is not None:
            return hit
        try:
            r = subprocess.run([self.binary, f"--loader={loader}", "--minify-whitespace", "--legal-comments=none",
                                "--charset=utf8", "--log-level=error"], input=data, capture_output=True, timeout=20)
            out = r.stdout if r.returncode == 0 and r.stdout else data
            if out is data:
                self._warn(f"{name}: {r.stderr.decode('utf-8', 'replace')[:200]}")
        except (OSError, subprocess.SubprocessError) as e:
            out = data
            self._warn(f"{name}: {e}")
        with self._lock:
            if len(self._memo) > 256:
                self._memo.clear()
            self._memo[key] = out
        return out

    def _warn(self, msg: str) -> None:
        sys.stderr.write(f"[bridge] 주석·공백을 못 걷고 원본을 보내요 — {msg}\n")

