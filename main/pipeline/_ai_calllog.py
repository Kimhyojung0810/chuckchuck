"""
국내 AI API 호출 로그 자동 기록 (2026-10-15, 전국민 AI 경진대회 국내 AI 트랙 제출용).

설계: ~/meetings/리서치/2026-10-15_AI_API_호출로그_자동기록_설계.md §3–§6 · 내보내기는 etc/scripts/ai_calllog_export.py.

- `requests.Session.send` 한 곳을 감싸 **국내 AI 호스트로 가는 요청만** 한 왕복 = 한 줄(JSONL)로 적는다.
  호스트 목록은 config 의 base URL(Upstage · A.X LLM/STT · Mi:dm · Friendli)에서 만든다. 기능 코드는 그대로 둔다.
- 어느 기능의 호출인지는 호출 스택에서 `pipeline.fNN_*` 모듈(+ 유틸 표 HELPER_FEATURES)을 찾아 붙인다.
- **헤더는 아예 안 적는다**(키 · Authorization). multipart · 바이너리 본문은 {filename, bytes, sha256} 지문만 남긴다.
- 모드 `AI_CALLLOG=team|all|off` (기본 team = 팀 쿠키가 있는 요청만 — 공개 방문자의 자료 · 목소리를 또 쌓지 않는다).
- 브리지 요청 하나가 `begin_request()` 로 범위(contextvar)를 연다. 스레드풀은 contextvars.copy_context().run 으로 넘긴다.
- 저장: ~/.local/state/chuckchuck/ai_calllog/<KST 날짜>/<기능 코드>.jsonl (폴더 0700 · 파일 0600 · fcntl 잠금 · 14일 보관).
기록은 **어떤 경우에도 요청을 깨지 않는다** — 적다가 난 오류는 stderr 한 줄로 끝낸다.
"""
from __future__ import annotations

import contextvars
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
RETENTION_DAYS = 14
UNCLASSIFIED = "미분류"
FEATURES_FILE = Path(__file__).with_name("ai_calllog_features.json")
#: 유틸 모듈이지만 스레드풀 안에서 바로 LLM 을 불러 스택에 fNN 모듈이 없는 곳 (설계 §3)
HELPER_FEATURES = {"_typed_graph": "F-07", "_judge_grounds": "F-09"}
#: 같은 모듈 안에서도 **함수**로 기능을 가르는 표 (2026-10-17 네 모델 Q&A) — 스택에서 이 함수 이름을 만나면 모듈보다 먼저 쓴다.
#: f08_ensemble 의 일 하나가 곧 제출 기능 하나다 (후보 생성 · 서로 평가 · 최종 선택 · 발표 음성 추론 · 모범답 정리).
FUNC_FEATURES = {
    "ens_generate": "F-08-gen",
    "ens_peer_review": "F-08-peer",
    "ens_pick": "F-08-pick",
    "ens_voice": "F-08-voice",
    "polish_gists": "F-08-gist",
    # 꼬리질문 엔진 (2026-10-17 5단계, f09_dialogue) — 판정(F-09)과 따로 센다
    "dialogue_talk": "F-09-talk",
    "dialogue_respeak": "F-09-respeak",
}
_FEATURE_MOD = re.compile(r"^f(\d{2})_[a-z0-9_]+$")
#: 호스트 꼬리 → 제공사 (국내 AI 연계 기업). 실제 기록 대상 호스트는 install() 이 config 의 base URL 에서 정한다
_PROVIDERS = (("upstage.ai", "Upstage"), ("adot.ai", "SKT"), ("kt.com", "KT"),
              ("friendli.ai", "LG AI연구원 EXAONE (FriendliAI 호스팅)"))
#: 해외 AI 로 보이는 호스트 — 보내기는 막지 않고 경고만 한다 (테스트가 0건인지 본다)
_FOREIGN = re.compile(r"(?:^|\.)(?:openai\.com|anthropic\.com|cohere\.(?:ai|com)|mistral\.ai|groq\.com|together\.xyz"
                      r"|deepseek\.com|perplexity\.ai|x\.ai|replicate\.com|elevenlabs\.io|deepgram\.com|assemblyai\.com"
                      r"|openai\.azure\.com|cognitiveservices\.azure\.com|api-inference\.huggingface\.co"
                      r"|(?:generativelanguage|speech|aiplatform|texttospeech|translation|vision|language)\.googleapis\.com)$")
#: 응답에서 이보다 긴 실수 배열(임베딩 벡터)은 길이 · 앞 8개 · sha256 으로 줄인다 — 한 줄이 수 MB 가 된다
_FLOATS_MAX = 64
_TEXT_MAX = 20000
#: 요청 본문에 모델 필드가 없는 단계(A.X STT upload-token · 음성 PUT · Document Parse async 폴링)의 모델 — (호스트, 경로 머리, 모델).
#: install() 이 config 에서 채운다. 가이드 「요청 모델」 칸이 null 로 남지 않게 (10-17 감사: F-05 레코드 3건 중 2건이 null).
_PATH_MODELS: list[tuple[str, str, str]] = []
#: 요청 model 값 → 사람이 읽는 모델 이름. EXAONE(Friendli 전용 엔드포인트)·Mi:dm 은 model 이 엔드포인트 ID 라 따로 붙인다.
_MODEL_LABELS = {
    "solar-pro3": "Upstage Solar Pro 3",
    "solar-pro2": "Upstage Solar Pro 2",
    "solar-mini": "Upstage Solar Mini",
    "document-parse": "Upstage Document Parse",
    "embedding-passage": "Upstage Solar Embedding (passage)",
    "embedding-query": "Upstage Solar Embedding (query)",
    "A.X-K2": "SKT A.X K2",
    "A.X_STT_note_batch": "SKT A.X STT (배치)",
    "A.X_STT_note_streaming": "SKT A.X STT (실시간 스트리밍)",
    "midm-pro-fp8-kaic": "KT 믿:음(Mi:dm) Pro — KT 공식 API",
}

_HOSTS: dict[str, str] = {}
_ORIG_SEND = None
_LOCK = threading.Lock()
_TL = threading.local()
FOREIGN_SEEN: list[str] = []
_NOSCOPE_RUNS: dict[str, dict] = {}
_PROCESS_RUN = datetime.now(KST).strftime("%Y%m%dT%H%M%S") + f"-p{os.getpid()}"


# ─── 모드 · 범위 ─────────────────────────────────────────────────────────────────────────────

def mode() -> str:
    m = (os.environ.get("AI_CALLLOG") or "team").strip().lower()
    return m if m in ("team", "all", "off") else "team"


def root() -> Path:
    raw = (os.environ.get("AI_CALLLOG_DIR") or "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".local" / "state" / "chuckchuck" / "ai_calllog"


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="milliseconds")


@dataclass
class Scope:
    """브리지 요청 하나. 같은 요청 안의 같은 기능 호출은 한 실행(run_id)으로 묶인다 (가이드 절차 4 「기능 끝날 때까지 누적」)."""
    team: bool
    route: str = ""
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    runs: dict = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


_SCOPE: contextvars.ContextVar[Scope | None] = contextvars.ContextVar("ai_calllog_scope", default=None)
#: 스택으로 못 가르는 자리(스레드풀 일꾼 — RoutedLLM 마감 풀 · 네 모델 병렬)를 위한 기능 표지. `carry()` · `feature_scope()` 가 건다.
_FEATURE_HINT: contextvars.ContextVar[str | None] = contextvars.ContextVar("ai_calllog_feature", default=None)


def begin_request(*, team: bool, route: str = "") -> Scope:
    """이 스레드(=브리지 요청 하나)의 범위를 연다. keep-alive 다음 요청이 다시 부르면 갈아 끼운다."""
    s = Scope(team=bool(team), route=route[:120])
    _SCOPE.set(s)
    return s


def start_run() -> None:
    """다음 호출부터 기능마다 새 실행(run_id)으로 묶는다. CLI · 벤치는 프로세스 하나가 기능마다 한 실행이라, 덱 · 문항마다 이걸 부르면
    「기능 1회 = 실행 하나」 로 나뉜다 (가이드 「기능별 1회 로그」 — 10-17 감사: 벤치 프로세스 하나의 F-09 가 26건 한 실행이었다)."""
    global _PROCESS_RUN
    with _LOCK:
        _NOSCOPE_RUNS.clear()
        _PROCESS_RUN = datetime.now(KST).strftime("%Y%m%dT%H%M%S%f")[:-3] + f"-p{os.getpid()}"
    s = _SCOPE.get()
    if s is not None:
        with s.lock:
            s.runs.clear()


def current() -> Scope | None:
    return _SCOPE.get()


def should_record() -> bool:
    m = mode()
    if m == "off":
        return False
    if m == "all":
        return True
    s = _SCOPE.get()
    return bool(s and s.team)


def _run_for(code: str, model: str | None) -> tuple[str, str | None]:
    """(run_id, 이 실행의 모델). 모델 필드가 없는 단계(STT upload-token · 업로드)는 같은 실행의 모델을 이어 받는다."""
    s = _SCOPE.get()
    stamp = datetime.now(KST).strftime("%Y%m%dT%H%M%S")
    if s is None:
        # 브리지 밖(CLI · 실험실 스크립트): 프로세스 하나 = 기능마다 한 실행
        with _LOCK:
            run = _NOSCOPE_RUNS.setdefault(code, {"id": f"{code.lower()}-{_PROCESS_RUN}", "model": None})
    else:
        with s.lock:
            run = s.runs.setdefault(code, {"id": f"{code.lower()}-{stamp}-{s.request_id[:4]}", "model": None})
    if model:
        run["model"] = model
    return run["id"], run["model"]


# ─── 기능 찾기 · 재시도 ───────────────────────────────────────────────────────────────────────

def _stack_feature(frame) -> str:
    """스택을 안쪽부터 올라가며 처음 만난 FUNC_FEATURES 함수 · pipeline.fNN_* 모듈(또는 HELPER_FEATURES)의 기능 코드. 못 찾으면 미분류."""
    f = frame
    while f is not None:          # 함수 표가 먼저 — 그 함수 안쪽의 도우미 프레임(같은 fNN 모듈)이 모듈 규칙으로 먼저 걸리지 않게
        fn = getattr(getattr(f, "f_code", None), "co_name", "")
        if fn in FUNC_FEATURES:
            return FUNC_FEATURES[fn]
        f = f.f_back
    f = frame
    while f is not None:
        last = str(f.f_globals.get("__name__", "")).rsplit(".", 1)[-1]
        m = _FEATURE_MOD.match(last)
        if m:
            return f"F-{m.group(1)}"
        if last in HELPER_FEATURES:
            return HELPER_FEATURES[last]
        f = f.f_back
    return UNCLASSIFIED


def feature_of(frame) -> str:
    """이 호출의 기능 코드 — `feature_scope()` 로 건 표지가 있으면 그것, 없으면 스택(`_stack_feature`), 스택이 미분류면
    스레드를 건너온 표지(`carry()`)."""
    hint = _FEATURE_HINT.get()
    code = _stack_feature(frame)
    if hint and (code == UNCLASSIFIED or hint.startswith(code + "-")):
        return hint
    return code


class feature_scope:
    """`with feature_scope("F-08-gen"):` — 이 안에서 나가는 호출(같은 스레드 · carry 로 넘긴 스레드)은 이 기능으로 적는다.
    스택이 더 좁은 기능(예: 같은 F-08 안의 F-08-peer 함수)을 가리키면 스택이 이긴다."""

    def __init__(self, code: str | None):
        self.code = code
        self._tok = None

    def __enter__(self):
        if self.code:
            self._tok = _FEATURE_HINT.set(self.code)
        return self

    def __exit__(self, *exc):
        if self._tok is not None:
            _FEATURE_HINT.reset(self._tok)
        return False


def carry(fn, feature: str | None = None):
    """스레드풀에 넘길 함수를 감싼다 — 지금 맥락(요청 범위 · 기능 표지)을 복사하고, 표지가 없으면 **부르는 쪽 스택**의 기능을 건다.
    RoutedLLM 마감 풀 · 네 모델 병렬처럼 일꾼 스택에 fNN 모듈이 없는 자리에서 기능 · team 범위가 사라지지 않게 (10-17 실측: 라우팅된
    EXAONE 질문 문장 호출이 미분류였고, team 모드에선 범위가 끊겨 아예 안 적혔다)."""
    code = feature or _FEATURE_HINT.get() or _stack_feature(sys._getframe(1))
    ctx = contextvars.copy_context()

    def run(*a, **kw):
        def inner():
            tok = _FEATURE_HINT.set(code) if code and code != UNCLASSIFIED else None
            try:
                return fn(*a, **kw)
            finally:
                if tok is not None:
                    _FEATURE_HINT.reset(tok)
        return ctx.copy().run(inner)    # 같은 감싼 함수가 여러 일꾼에서 동시에 돌아도 되게 — 부를 때마다 사본

    return run


def _caller(frame):
    """requests · urllib3 · 이 모듈 밖의 첫 프레임 — 같은 프레임이 같은 요청을 또 보내면 재시도다."""
    f = frame
    while f is not None:
        name = str(f.f_globals.get("__name__", ""))
        if not (name.startswith(("requests", "urllib3")) or name == __name__):
            return f
        f = f.f_back
    return None


def _attempt(caller, sig: tuple) -> int:
    """같은 호출 자리 · 같은 요청이 **앞 시도가 실패한 뒤** 또 나가면 attempt+1. 성공한 뒤의 같은 요청(비동기 폴링)은 1부터."""
    key = (id(caller), getattr(caller, "f_code", None), sig)
    last = getattr(_TL, "last", None)
    n = last[1] + 1 if last and last[0] == key and last[2] else 1
    _TL.last = [key, n, False]
    return n


def _mark_failed(failed: bool) -> None:
    last = getattr(_TL, "last", None)
    if last:
        last[2] = failed


# ─── 본문 지문 ────────────────────────────────────────────────────────────────────────────

def _fp(data: bytes, **extra) -> dict:
    return {**extra, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _file_fp(fobj, ctype: str) -> dict:
    """파일 객체 본문(STT 음성 PUT) — 소비하지 않게 경로로 따로 읽어 지문만."""
    h, n = hashlib.sha256(), 0
    path = getattr(fobj, "name", None)
    if isinstance(path, str) and os.path.isfile(path):
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
                n += len(chunk)
    kind = "audio" if ("audio" in ctype or "octet-stream" in ctype) else "file"
    return {kind: {"bytes": n, "sha256": h.hexdigest(), "content_type": ctype or None}}


def _multipart(data: bytes, ctype: str) -> dict:
    m = re.search(r'boundary="?([^";]+)"?', ctype)
    if not m:
        return {"multipart": _fp(data)}
    form: dict = {}
    out: dict = {"form": form}
    for part in data.split(b"--" + m.group(1).encode())[1:]:
        head, _, body = part.partition(b"\r\n\r\n")
        if not _:
            continue
        body = body[:-2] if body.endswith(b"\r\n") else body
        h = head.decode("utf-8", "replace")
        name = re.search(r'name="([^"]*)"', h)
        fname = re.search(r'filename="([^"]*)"', h)
        key = name.group(1) if name else "?"
        if fname:
            out[key] = _fp(body, filename=fname.group(1))
        else:
            form[key] = body.decode("utf-8", "replace")[:_TEXT_MAX]
    return out


def request_body(req) -> object:
    body = req.body
    ctype = str(req.headers.get("Content-Type") or "").lower()
    if body is None:
        return None
    if hasattr(body, "read"):
        return _file_fp(body, ctype)
    if isinstance(body, str):
        body = body.encode("utf-8")
    if not isinstance(body, (bytes, bytearray)):
        return {"stream": True}
    data = bytes(body)
    if "multipart/form-data" in ctype:
        return _multipart(data, ctype)
    if "audio" in ctype or "octet-stream" in ctype:
        return {"audio": _fp(data, content_type=ctype)}
    try:
        return json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return {"raw": _fp(data, content_type=ctype or None)}


def _abridge(v):
    if isinstance(v, list):
        if len(v) > _FLOATS_MAX and all(isinstance(x, float) for x in v[:_FLOATS_MAX]):
            raw = json.dumps(v).encode()
            return {"_floats": len(v), "head": v[:8], "sha256": hashlib.sha256(raw).hexdigest()}
        return [_abridge(x) for x in v]
    if isinstance(v, dict):
        return {k: _abridge(x) for k, x in v.items()}
    return v


def response_body(resp, streamed: bool) -> object:
    if streamed:
        return {"streamed": True}
    data = resp.content or b""
    try:
        return _abridge(json.loads(data))
    except (ValueError, UnicodeDecodeError):
        text = data.decode("utf-8", "replace")
        return {"text": text[:_TEXT_MAX], **({"truncated": True} if len(text) > _TEXT_MAX else {})}


def _model_of(body) -> str | None:
    if isinstance(body, dict):
        for k in ("model", "speech_model"):
            if isinstance(body.get(k), str) and body[k]:
                return body[k]
        form = body.get("form")
        if isinstance(form, dict) and form.get("model"):
            return str(form["model"])
    return None


def endpoint_model(endpoint: str) -> str | None:
    """모델 필드가 없는 단계의 모델 (`_PATH_MODELS`)."""
    sp = urlsplit(endpoint or "")
    host = (sp.hostname or "").lower()
    for h, prefix, model in _PATH_MODELS:
        if host == h and sp.path.startswith(prefix):
            return model
    return None


def model_label(model: str | None, endpoint: str = "") -> str | None:
    """사람이 읽는 모델 이름. Friendli 전용 엔드포인트(EXAONE)는 model 이 엔드포인트 ID 라 EXAONE_MODEL_LABEL 로 이름을 준다."""
    if not model:
        return None
    host = (urlsplit(endpoint or "").hostname or "").lower()
    if host.endswith("friendli.ai"):
        name = (os.environ.get("EXAONE_MODEL_LABEL") or "").strip() or "LG AI연구원 EXAONE"
        return f"{name} (FriendliAI 전용 엔드포인트 {model})"
    if host.endswith("kt.com") and model not in _MODEL_LABELS:
        return f"KT 믿:음(Mi:dm) — 엔드포인트 {model}"
    if model in _MODEL_LABELS:
        return _MODEL_LABELS[model]
    m = re.fullmatch(r"solar-(pro|mini)(\d*)(.*)", model)
    if m and host.endswith("upstage.ai"):          # 표에 없는 새 Solar 판(예: solar-pro4)도 사람이 읽게
        return f"Upstage Solar {m.group(1).capitalize()}{(' ' + m.group(2)) if m.group(2) else ''}{m.group(3)}"
    return model


def _dig(v, *path):
    for p in path:
        if isinstance(p, int):
            v = v[p] if isinstance(v, list) and len(v) > p else None
        else:
            v = v.get(p) if isinstance(v, dict) else None
        if v is None:
            return None
    return v


def kind_of(method: str, endpoint: str) -> str:
    """레코드 종류 — 가이드 항목(응답 ID · 모델명 · 답변 · 토큰)이 본문 어디에 있는지가 종류마다 다르다."""
    sp = urlsplit(endpoint or "")
    path = sp.path.rstrip("/")
    if (method or "").upper() == "WEBSOCKET" or sp.scheme in ("ws", "wss"):
        return "stt_live"
    if path.endswith("/chat/completions"):
        return "chat"
    if path.endswith("/embeddings"):
        return "embedding"
    if path.endswith("/document-digitization/async"):
        return "docparse_async"
    if "/document-digitization/requests" in path:
        return "docparse_poll"
    if path.endswith("/document-digitization"):
        return "docparse"
    if path.endswith("/stt/upload-token"):
        return "stt_token"
    if "/stt/upload/" in path:
        return "stt_upload"
    if path.endswith("/stt/transcript"):
        return "stt_transcript"
    return "other"


def summarize(kind: str, req_body, status, rb) -> dict:
    """가이드 응답 칸(응답 ID · 모델명 · 답변 · 토큰 사용량)이 응답 본문 **어디에** 있는지 — 값은 본문에 그대로 두고 자리만 가리킨다.
    API 가 주지 않는 항목은 null + 까닭(`*_note`). 답변 원문은 되풀이하지 않는다(글자 수만)."""
    b = rb if isinstance(rb, dict) else {}
    s: dict = {"kind": kind, "id": None, "id_from": None, "model": None, "answer_from": None, "answer_chars": 0, "usage": None}

    def ans(path: str, text) -> None:
        if isinstance(text, str) and text.strip():
            s["answer_from"], s["answer_chars"] = path, len(text)

    if kind == "chat":
        s["id"], s["id_from"] = b.get("id"), "body.id"
        s["model"] = b.get("model")
        msg = _dig(b, "choices", 0, "message") or {}
        ans("body.choices[0].message.content", msg.get("content"))
        if not s["answer_from"]:
            ans("body.choices[0].message.reasoning_content", msg.get("reasoning_content") or msg.get("reasoning"))
        s["finish_reason"] = _dig(b, "choices", 0, "finish_reason")
        s["usage"] = b.get("usage")
    elif kind == "embedding":
        s["id_note"] = "Upstage 임베딩 응답에는 ID 필드가 없다"
        s["model"] = b.get("model")
        data = b.get("data") if isinstance(b.get("data"), list) else []
        if data:
            s["answer_from"], s["answer_chars"] = f"body.data[0..{len(data) - 1}].embedding", len(data)
        s["usage"] = b.get("usage")
    elif kind in ("docparse", "docparse_poll"):
        s["id"] = b.get("id") or b.get("request_id")
        s["id_from"] = "body.id" if b.get("id") else ("body.request_id" if b.get("request_id") else None)
        if not s["id"]:
            s["id_note"] = "Document Parse 동기 응답에는 ID 필드가 없다"
        s["model"] = b.get("model")
        ans("body.content.text", _dig(b, "content", "text"))
        if not s["answer_from"]:
            ans("body.content.markdown", _dig(b, "content", "markdown"))
        if not s["answer_from"] and b.get("status"):
            s["answer_from"], s["answer_chars"] = "body.status", len(str(b["status"]))
        s["usage"] = b.get("usage")
    elif kind == "docparse_async":
        s["id"], s["id_from"] = b.get("request_id"), "body.request_id"
        s["model"] = _model_of(req_body)
        s["model_note"] = "접수 응답엔 모델이 없어 요청 form.model"
        if b.get("request_id"):
            s["answer_from"], s["answer_chars"] = "body.request_id", len(str(b["request_id"]))
    elif kind == "stt_token":
        s["id_note"] = "업로드 토큰 발급 단계(응답 ID 없음) — 토큰은 인증정보라 내보내기에서 *** 로 가린다"
        s["model_note"] = "응답에 모델이 없어 request.model(이 단계가 속한 STT 모델 — model_source)"
        if b.get("upload_token"):
            s["answer_from"], s["answer_chars"] = "body.upload_token", len(str(b["upload_token"]))
        s["usage_note"] = "토큰 과금 단계가 아니다"
    elif kind == "stt_upload":
        s["id"], s["id_from"] = b.get("file_key"), "body.file_key"
        s["model_note"] = "응답에 모델이 없어 request.model(이 단계가 속한 STT 모델 — model_source)"
        if b.get("file_key"):
            s["answer_from"], s["answer_chars"] = "body.file_key", len(str(b["file_key"]))
        s["usage_note"] = "음성 업로드 단계 — 요청 body.audio 의 bytes 가 양"
    elif kind == "stt_transcript":
        s["id"], s["id_from"] = b.get("message_id"), "body.message_id"
        s["model"] = _model_of(req_body)
        s["model_note"] = "A.X STT 응답은 모델을 되돌려 주지 않아 요청 speech_model"
        utt = b.get("utterances") if isinstance(b.get("utterances"), list) else []
        text = " ".join(str(u.get("text") or "") for u in utt if isinstance(u, dict)).strip()
        ans(f"body.utterances[0..{max(len(utt) - 1, 0)}].text", text)
        if b.get("audio_duration") is not None:
            s["usage"] = {"audio_duration_ms": b.get("audio_duration"), "utterance_count": b.get("utterance_count")}
            s["usage_note"] = "STT 는 토큰이 아니라 음성 길이로 센다"
    elif kind == "stt_live":
        create = _dig(req_body, "create") or {}
        s["id"], s["id_from"] = create.get("tr_id"), "request.body.create.tr_id"
        s["model"] = create.get("speech_model")
        s["model_note"] = "실시간 STT 는 모델을 되돌려 주지 않아 create.speech_model"
        msgs = b.get("messages") if isinstance(b.get("messages"), list) else []
        text = " ".join(str(m.get("text") or "") for m in msgs if isinstance(m, dict)).strip()
        ans(f"body.messages[0..{max(len(msgs) - 1, 0)}].text", text)
        audio = _dig(req_body, "audio") or {}
        if audio.get("duration_sec") is not None:
            s["usage"] = {"audio_duration_sec": audio.get("duration_sec"), "audio_bytes": audio.get("bytes")}
            s["usage_note"] = "STT 는 토큰이 아니라 음성 길이로 센다"
    if not (isinstance(status, int) and 200 <= status < 300 or status == 101):
        s["error"] = b.get("error") if isinstance(b, dict) and b.get("error") is not None else (b or None)
    return s


# ─── 쓰기 ───────────────────────────────────────────────────────────────────────────────

def _features() -> dict:
    try:
        return json.loads(FEATURES_FILE.read_text(encoding="utf-8")).get("features", {})
    except (OSError, ValueError):
        return {}


def _safe_name(code: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣_-]", "_", code) or UNCLASSIFIED


def write(record: dict) -> Path | None:
    """한 줄을 기능별 JSONL 에 덧붙인다 (fcntl 잠금 — 병렬 스레드 · 프로세스에서도 줄이 안 섞인다)."""
    try:
        base = root()
        day = datetime.now(KST).strftime("%Y-%m-%d")
        folder = base / day
        if not folder.is_dir():
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(base, 0o700)
            prune(base)
        path = folder / f"{_safe_name(record.get('feature_code') or UNCLASSIFIED)}.jsonl"
        line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.write(fd, line)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        return path
    except Exception as e:  # noqa: BLE001 — 기록 실패로 요청을 깨지 않는다
        sys.stderr.write(f"[ai_calllog] 기록 실패: {type(e).__name__}: {str(e)[:160]}\n")
        return None


def prune(base: Path | None = None, *, days: int = RETENTION_DAYS) -> list[str]:
    """보관 기간이 지난 날짜 폴더를 지운다. `pinned/`(내보내기 --pin 으로 고정한 실행)은 남긴다."""
    base = base or root()
    cut = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    gone = []
    for d in base.iterdir() if base.is_dir() else ():
        if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name) and d.name < cut:
            shutil.rmtree(d, ignore_errors=True)
            gone.append(d.name)
    return gone


def provider_of(host: str) -> str:
    for tail, name in _PROVIDERS:
        if host == tail or host.endswith("." + tail):
            return name
    return host


def answer_empty(summary: dict, status) -> bool:
    """200 인데 답이 없다 — 대화: content 가 비었고 사고(reasoning)만 있거나 그마저 max_tokens 에서 잘렸다 ·
    배치 받아쓰기: 글자가 하나도 없다(말소리를 못 찾음 — 화면은 422 「말소리를 찾지 못했어요」). 기능은 이 호출로 답을 못 얻었다."""
    if status != 200 or summary.get("kind") not in ("chat", "stt_transcript"):
        return False
    src = summary.get("answer_from") or ""
    if summary["kind"] == "stt_transcript":
        return not src
    return not src or (src.endswith("reasoning_content") and summary.get("finish_reason") == "length")


def make_record(*, code: str, method: str, endpoint: str, body, t0: str, t1: str, response: dict,
                ok: bool, attempt: int = 1, provider: str | None = None, model: str | None = None, **extra) -> dict:
    """한 왕복 = 한 건. 요청 모델은 (넘긴 값 · 요청 본문) → 단계 표(`_PATH_MODELS`) → 같은 실행의 모델 순으로 채우고 출처를 남긴다.
    `response.summary` 는 가이드 응답 칸(응답 ID · 모델명 · 답변 · 토큰)이 본문 어디에 있는지 가리킨다(값을 되풀이하지 않는다)."""
    own = model or _model_of(body)
    run_id, run_model = _run_for(code, own)
    final, source = own, "request" if own else None
    if not final:
        final = endpoint_model(endpoint)            # 단계 표가 먼저 — 여러 모델이 섞인 실행(F-12 · F-07)의 「같은 실행 모델」은 엉뚱할 수 있다
        source = "endpoint_step" if final else None
    if not final and run_model:
        final, source = run_model, "same_run"
    summary = summarize(kind_of(method, endpoint), body, response.get("status"), response.get("body"))
    if response.get("error"):                 # 연결 실패 · 읽기 시간 초과 — 응답 본문이 없다. 까닭을 summary 에도
        summary["error"] = {"type": response.get("error"), "message": response.get("message")}
    if answer_empty(summary, response.get("status")):
        summary["answer_empty"] = True      # 200 인데 답이 없다(사고만 하다 max_tokens) — 기능은 이 호출로 답을 못 얻었다
        ok = False
    s = _SCOPE.get()
    return {
        "record_id": uuid.uuid4().hex,
        "run_id": run_id,
        "feature": _features().get(code, code),
        "feature_code": code,
        "provider": provider or provider_of(urlsplit(endpoint).hostname or ""),
        "request": {"time_kst": t0, "method": method, "endpoint": endpoint, "model": final,
                    "model_label": model_label(final, endpoint), "model_source": source, "body": body},
        "response": {"time_kst": t1, **response, "summary": summary},
        "attempt": attempt,
        "ok": bool(ok),
        **({"request_scope": {"id": s.request_id, "route": s.route}} if s else {}),
        **extra,
        "masked": [],
    }


def _send(self, request, **kwargs):
    host = (urlsplit(request.url).hostname or "").lower()
    if host not in _HOSTS:
        if host and _FOREIGN.search(host):
            FOREIGN_SEEN.append(host)
            sys.stderr.write(f"[ai_calllog] ⚠ 해외 AI 호스트로 가는 요청 — 국내 AI 트랙 규정 위반일 수 있어요: {host}\n")
        return _ORIG_SEND(self, request, **kwargs)
    if not should_record():
        return _ORIG_SEND(self, request, **kwargs)
    frame = sys._getframe(1)
    try:
        body = request_body(request)
        sig = (request.method, request.url, hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest())
        attempt = _attempt(_caller(frame), sig)
        code = feature_of(frame)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[ai_calllog] 요청 읽기 실패 — 이번 호출은 적지 않아요: {type(e).__name__}\n")
        return _ORIG_SEND(self, request, **kwargs)
    t0 = now_kst()
    try:
        resp = _ORIG_SEND(self, request, **kwargs)
    except Exception as e:
        _mark_failed(True)
        write(make_record(code=code, method=request.method, endpoint=request.url, body=body, t0=t0, t1=now_kst(),
                          response={"error": type(e).__name__, "message": str(e)[:300]}, ok=False,
                          attempt=attempt, provider=_HOSTS[host]))
        raise
    try:
        rb = response_body(resp, bool(kwargs.get("stream")))
        ok = 200 <= resp.status_code < 300 and not (isinstance(rb, dict) and rb.get("text") == "")
        _mark_failed(not ok)
        write(make_record(code=code, method=request.method, endpoint=request.url, body=body, t0=t0, t1=now_kst(),
                          response={"status": resp.status_code, "body": rb}, ok=ok, attempt=attempt, provider=_HOSTS[host]))
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[ai_calllog] 응답 기록 실패: {type(e).__name__}\n")
    return resp


def korean_hosts(cfg=None) -> dict[str, str]:
    """config 의 base URL 들에서 기록 대상 호스트 → 제공사 이름."""
    if cfg is None:
        from .config import settings as cfg  # noqa: PLC0415
    urls = [cfg.docparse_url, cfg.docparse_async_url, cfg.solar_base_url, cfg.ax_base_url, cfg.ax_stt_base_url,
            cfg.midm_base_url, cfg.exaone_base_url, os.environ.get("UPSTAGE_SOLAR_BASE_URL", "")]
    out = {}
    for u in urls:
        h = (urlsplit(u or "").hostname or "").lower()
        if h:
            out[h] = provider_of(h)
    return out


def path_models(cfg=None) -> list[tuple[str, str, str]]:
    """모델 필드가 없는 단계 → 그 단계가 속한 모델 (config 에서)."""
    if cfg is None:
        from .config import settings as cfg  # noqa: PLC0415
    out = []
    stt = (urlsplit(getattr(cfg, "ax_stt_base_url", "") or "").hostname or "").lower()
    if stt:
        out.append((stt, "/v1/stt/upload", getattr(cfg, "ax_stt_batch_model", "") or "A.X_STT_note_batch"))
    dp = urlsplit(getattr(cfg, "docparse_async_url", "") or "")
    if dp.hostname:
        out.append((dp.hostname.lower(), dp.path.rsplit("/async", 1)[0] + "/requests",
                    getattr(cfg, "docparse_model", "") or "document-parse"))
    return out


def install(cfg=None) -> bool:
    """requests.Session.send 를 한 번 감싼다. 이미 감쌌으면 호스트 목록만 다시 읽는다. 모드가 off 여도 감싼다(해외 경고는 늘)."""
    global _ORIG_SEND
    import requests  # noqa: PLC0415

    with _LOCK:
        _HOSTS.clear()
        _HOSTS.update(korean_hosts(cfg))
        _PATH_MODELS[:] = path_models(cfg)
        if _ORIG_SEND is None:
            _ORIG_SEND = requests.Session.send
            requests.Session.send = _send
    try:
        prune()
    except OSError:
        pass
    return True


def uninstall() -> None:
    global _ORIG_SEND
    import requests  # noqa: PLC0415

    with _LOCK:
        if _ORIG_SEND is not None:
            requests.Session.send = _ORIG_SEND
            _ORIG_SEND = None


def record_live_session(*, endpoint: str, model: str, create: dict, audio: dict, transcripts: list, t0: str, t1: str,
                        closed: dict, ok: bool, code: str = "F-05-live") -> Path | None:
    """실시간 받아쓰기 WebSocket 세션 하나 = 한 건 (Session.send 를 안 지나는 길 — 설계 §11)."""
    if not should_record():
        return None
    try:
        rec = make_record(code=code, method="WEBSOCKET", endpoint=endpoint, body={"create": create, "audio": audio},
                          t0=t0, t1=t1, response={"status": 101, "body": {"messages": transcripts, "closed": closed}},
                          ok=ok, provider=provider_of(urlsplit(endpoint).hostname or ""), model=model,
                          transport="websocket")
        return write(rec)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[ai_calllog] 실시간 받아쓰기 기록 실패: {type(e).__name__}\n")
        return None


def audio_digest() -> "_AudioDigest":
    return _AudioDigest()


class _AudioDigest:
    """보낸 PCM 의 길이 · 바이트 · sha256 (음성 원본은 개인정보라 싣지 않는다)."""

    def __init__(self) -> None:
        self._h = hashlib.sha256()
        self.bytes = 0

    def add(self, pcm: bytes) -> None:
        self._h.update(pcm)
        self.bytes += len(pcm)

    def summary(self, rate: int = 16000) -> dict:
        return {"format": "pcm_s16le", "sample_rate": rate, "channels": 1, "bytes": self.bytes,
                "duration_sec": round(self.bytes / (2 * rate), 2), "sha256": self._h.hexdigest()}


__all__ = ["install", "uninstall", "begin_request", "start_run", "current", "should_record", "mode", "root", "record_live_session",
           "audio_digest", "feature_of", "feature_scope", "carry", "prune", "write", "korean_hosts", "FUNC_FEATURES",
           "kind_of", "summarize", "answer_empty", "model_label", "endpoint_model", "path_models"]
