"""
데모 브리지의 **메모리 세션 저장소**입니다.

브리지가 무상태라서 프론트가 요청마다 graph·alignment·transcript 를 통째로 다시
올려야 했고(판정 요청 하나가 수 MB), 같은 입력으로 LLM 이 다시 돌았습니다.
여기서 아티팩트를 한 번 받아 두고 이후 요청은 `session_id` 만 주고받습니다.

프로세스 메모리라 브리지를 재시작하면 사라집니다 — 클라이언트는 `session_missing`
응답을 받으면 다시 등록하고 재시도하면 됩니다. 데모에 파일·DB 를 끌어들이지 않는 것이
의도입니다 (`DEV_POLICY.md` 계층표의 '저장소' 는 프로덕션 서버 몫).

    store = SessionStore()
    store.put_artifacts("abc", {"graph": {...}, "alignment": {...}})
    store.artifacts("abc")["graph"]

triage 캐시는 세션과 별도로 **입력 지문(fingerprint)** 으로 건다. 트랙(1/5/10분)이
바뀌어도 그래프·정합·흐름이 같으면 F-08 1차 심사를 재사용하기 위해서다
(`f08_questions` 는 "triage 는 트랙과 무관하니 세션에 한 번만" 을 전제로 쓰여 있다).
"""

from __future__ import annotations

import hashlib
import json
import threading
import time

#: 세션에 보관하는 아티팩트 키. 이 밖의 키는 저장하지 않는다 —
#: 프론트가 실수로 큰 객체(SlideDoc·오디오)를 밀어 넣어도 메모리가 새지 않게 한다.
ARTIFACT_KEYS = ("graph", "alignment", "flow", "transcript", "context")

#: 동시에 들고 있을 세션 수. 넘으면 가장 오래 안 쓴 것부터 버린다.
MAX_SESSIONS = 32

#: 세션 수명(초). 데모 한 번이 이보다 길 이유가 없다.
TTL_SEC = 6 * 3600

#: triage 캐시 항목 수. 자료 하나당 1개면 충분하다.
MAX_TRIAGE = 32


def fingerprint(*parts: object) -> str:
    """
    입력 지문. 같은 입력이면 언제나 같은 문자열이 나온다.

    `sort_keys=True` 라 dict 순서가 흔들려도 지문이 바뀌지 않는다 —
    프론트가 키 순서를 보장하지 않기 때문이다.
    """
    h = hashlib.sha1()
    for part in parts:
        h.update(json.dumps(part, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


class SessionStore:
    """
    세션별 아티팩트 + 지문별 triage 캐시. **스레드 안전**하다.

    브리지가 `ThreadingHTTPServer` 라 요청마다 스레드가 다르다 — 락 없이 dict 를
    건드리면 동시 요청에서 조용히 깨진다.
    """

    def __init__(
        self,
        *,
        max_sessions: int = MAX_SESSIONS,
        ttl_sec: float = TTL_SEC,
        max_triage: int = MAX_TRIAGE,
        clock=time.monotonic,
    ) -> None:
        self._max_sessions = max_sessions
        self._ttl = ttl_sec
        self._max_triage = max_triage
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = {}      # session_id → {"at": float, "data": {...}}
        self._triage: dict[str, dict] = {}        # fingerprint → {"at": float, "doc": Any}

    # -- 아티팩트 ---------------------------------------------------------

    def put_artifacts(self, session_id: str, artifacts: dict) -> list[str]:
        """
        아티팩트를 등록하고 실제로 저장한 키를 돌려준다.

        - 본문에 없는 키는 그대로 둔다 — 부분 재등록이 이미 등록된 근거를 지우면
          판정이 근거를 잃는다.
        - **명시적 None 은 지운다.** "이번 발표에는 이게 없다" 는 선언이다.
          예전엔 None 도 건너뛰었는데, 세션 키가 'flat' 하나뿐인 데모에서
          발표 A 의 flow 가 발표 B 의 질문·판정 근거로 섞여 들어갔다 —
          프론트는 현재 발표의 전체 진실(flow: null 포함)을 항상 같이 보낸다.
        """
        if not session_id:
            return []
        stored: list[str] = []
        with self._lock:
            self._evict_expired()
            entry = self._sessions.get(session_id) or {"data": {}}
            data = entry["data"]
            for key in ARTIFACT_KEYS:
                if key not in artifacts:
                    continue
                value = artifacts.get(key)
                if value is None:
                    data.pop(key, None)
                    continue
                data[key] = value
                stored.append(key)
            entry["at"] = self._clock()
            entry["data"] = data
            self._sessions[session_id] = entry
            self._evict_overflow()
        return stored

    def artifacts(self, session_id: str) -> dict:
        """세션에 등록된 아티팩트 사본. 없으면 빈 dict."""
        if not session_id:
            return {}
        with self._lock:
            self._evict_expired()
            entry = self._sessions.get(session_id)
            if entry is None:
                return {}
            entry["at"] = self._clock()   # 쓰이는 세션은 살려 둔다 (LRU)
            return dict(entry["data"])

    # -- triage 캐시 ------------------------------------------------------

    def get_triage(self, key: str):
        """지문에 해당하는 QaTriage. 없으면 None."""
        if not key:
            return None
        with self._lock:
            entry = self._triage.get(key)
            if entry is None:
                return None
            if self._clock() - entry["at"] > self._ttl:
                self._triage.pop(key, None)
                return None
            entry["at"] = self._clock()
            return entry["doc"]

    def set_triage(self, key: str, doc) -> None:
        if not key:
            return
        with self._lock:
            self._triage[key] = {"at": self._clock(), "doc": doc}
            while len(self._triage) > self._max_triage:
                oldest = min(self._triage, key=lambda k: self._triage[k]["at"])
                self._triage.pop(oldest, None)

    # -- 내부 -------------------------------------------------------------

    def _evict_expired(self) -> None:
        now = self._clock()
        for sid in [s for s, e in self._sessions.items() if now - e["at"] > self._ttl]:
            self._sessions.pop(sid, None)

    def _evict_overflow(self) -> None:
        while len(self._sessions) > self._max_sessions:
            oldest = min(self._sessions, key=lambda s: self._sessions[s]["at"])
            self._sessions.pop(oldest, None)
