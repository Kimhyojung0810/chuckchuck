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

같은 통에 triage 말고도 질문 묶음(`questions:`)·시간 배분(`pace:`)·기억(`memory:`)·문헌(`papers:`)·주장(`claims:`)이
키 접두어로 들어온다. 상한은 **종류마다 따로** 센다 (`CACHE_KIND_CAPS`).

서버가 만든 질문은 세션과 따로 **질문 색인**에도 남긴다 (`remember_questions`·`find_questions`).
판정(F-09)이 채점 기준을 클라이언트 본문이 아니라 여기서 찾는다 — 09-30 감사 R4.
"""

from __future__ import annotations

import copy
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

#: 캐시 종류 하나의 기본 항목 수. 자료 하나당 1개면 충분하다.
MAX_TRIAGE = 32

#: 종류별 상한 (09-30 B-05). 예전엔 여섯 종류가 한 통(32개)을 같이 세서, 트랙·입력마다 하나씩 쌓이는 질문 묶음이
#: 방금 /pace 가 남긴 시간 배분과 지난 리허설 기억을 밀어냈다 — 밀리면 다음 질문이 **조용히** pace·기억 없이 만들어진다.
#: 질문 묶음은 세션 × 트랙(1·5·10분)이라 세 배를 준다. 여기 없는 종류는 MAX_TRIAGE(생성자의 max_triage).
CACHE_KIND_CAPS = {"questions": 3 * MAX_SESSIONS}

#: 질문 색인에 들고 있을 세션 수. 세션 등록(32개)과 따로 센다 — 등록이 실패했거나(프론트 .catch) 등록 없이 질문만
#: 만든 세션도 판정이 서버 질문으로 채점되게 하려고 둔다. 질문 요청 하나가 세션 자리를 먹지 않는 것은 그대로다.
MAX_QUESTION_INDEX = 2 * MAX_SESSIONS


def cache_kind(key: str) -> str:
    """캐시 키 → 종류. 접두어("questions:…")가 종류이고, 접두어가 없는 지문은 triage 다."""
    head, sep, _ = str(key).partition(":")
    return head if sep else "triage"


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


def _newest_last(tracks: dict | None, track: str, payload: dict) -> dict:
    """{트랙: 질문 묶음} 에 넣되 **방금 만든 트랙이 맨 뒤** 에 오게 — 순서가 곧 최근성이다 (find_questions 가 뒤에서 읽는다)."""
    out = {k: v for k, v in (tracks or {}).items() if k != track}
    out[track] = payload
    return out


class SessionStore:
    """
    세션별 아티팩트 + 지문별 캐시(종류별 상한) + 세션별 질문 색인. **스레드 안전**하다.

    브리지가 `ThreadingHTTPServer` 라 요청마다 스레드가 다르다 — 락 없이 dict 를
    건드리면 동시 요청에서 조용히 깨진다.
    """

    def __init__(
        self,
        *,
        max_sessions: int = MAX_SESSIONS,
        ttl_sec: float = TTL_SEC,
        max_triage: int = MAX_TRIAGE,
        kind_caps: dict[str, int] | None = None,
        max_question_index: int = MAX_QUESTION_INDEX,
        clock=time.monotonic,
    ) -> None:
        self._max_sessions = max_sessions
        self._ttl = ttl_sec
        self._max_triage = max_triage
        self._kind_caps = dict(CACHE_KIND_CAPS if kind_caps is None else kind_caps)
        self._max_qindex = max_question_index
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = {}      # session_id → {"at": float, "data": {...}}
        self._triage: dict[str, dict] = {}        # fingerprint → {"at": float, "doc": Any, "exp"?: float}
        self._qindex: dict[str, dict] = {}        # session_id → {"at": float, "tracks": {track: payload}}

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

    def put_questions(self, session_id: str, track: str, payload: dict) -> bool:
        """
        이 세션에서 만든 질문(QuestionDoc 직렬화 — 질문마다 basis 포함)을 트랙별로 붙여 둔다 (P1, 2026-09-29).

        "이 질문은 어떤 근거로 나왔나" 를 나중에 코드를 다시 안 돌리고 답하려고 둔다. ARTIFACT_KEYS 에 넣지 않는다 —
        그건 **프론트가 올리는** 키의 계약이고(tests/js 가 프론트가 전부 보내는지 검사한다), 질문은 서버가 만든 것이다.
        등록된 세션에만 붙인다 — 질문 요청 하나로 세션을 새로 만들면 한도(세션 32개)를 질문이 먹는다.
        """
        if not session_id or not isinstance(payload, dict):
            return False
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                return False
            entry["data"]["questions"] = _newest_last(entry["data"].get("questions"), str(track), payload)
            entry["at"] = self._clock()
            return True

    def remember_questions(self, session_id: str, track: str, payload: dict) -> bool:
        """
        서버가 만든 질문을 **질문 색인**에 남긴다 — 세션 등록과 무관하게 (09-30 R4).

        판정이 채점 기준(골자·요소·함정 전제·근거)을 클라이언트 본문에서 읽으면, 본문을 고쳐 보내는 것만으로
        함정 동의 답이 wrong 0 → good 80 이 됐다 (labs/qa_redteam bridge_tamper2). 그래서 판정은 여기서 찾는다.
        put_questions(P1)는 **등록된 세션**에만 붙으므로, 등록이 실패한 채 질문을 받은 세션(프론트는 등록 실패를 삼키고
        진행한다)은 색인이 비어 다시 본문으로 채점됐다 — 색인은 등록과 따로 두고 상한도 따로 센다.
        """
        if not session_id or not isinstance(payload, dict):
            return False
        with self._lock:
            now = self._clock()
            entry = self._qindex.get(session_id) or {"tracks": {}}
            entry["tracks"] = _newest_last(entry["tracks"], str(track), payload)
            entry["at"] = now
            self._qindex[session_id] = entry
            for sid in [s for s, e in self._qindex.items() if now - e["at"] > self._ttl]:
                self._qindex.pop(sid, None)
            while len(self._qindex) > self._max_qindex:
                oldest = min(self._qindex, key=lambda s: self._qindex[s]["at"])
                self._qindex.pop(oldest, None)
            return True

    def find_questions(self, session_id: str, question_id: str) -> list[dict]:
        """
        이 세션에서 서버가 만든 질문 중 id 가 같은 것 (사본) — **최근에 만든 트랙부터**.

        질문 id 는 `q{순위}-{node_id}` 라 트랙(1·5·10분)이 달라도 같은 개념이면 같다 (triage 를 트랙끼리 나눠 쓴다).
        문장·골자는 트랙마다 따로 만들어지므로 후보가 여럿일 수 있다 — 어느 것인지는 판정 쪽이 고른다.
        색인 → 등록된 세션의 질문(P1) 순으로 본다. 없으면 빈 목록.
        """
        if not session_id or not question_id:
            return []
        qid = str(question_id)
        with self._lock:
            now = self._clock()
            out: list[dict] = []
            seen: set[str] = set()
            sources = []
            idx = self._qindex.get(session_id)
            if idx is not None and now - idx["at"] <= self._ttl:
                idx["at"] = now
                sources.append(idx["tracks"])
            entry = self._sessions.get(session_id)
            if entry is not None and now - entry["at"] <= self._ttl:
                entry["at"] = now   # 판정도 세션을 쓰는 것이다 (LRU)
                sources.append(entry["data"].get("questions") or {})
            for tracks in sources:
                for track in reversed(list(tracks)):
                    for q in (tracks[track] or {}).get("questions") or []:
                        if not isinstance(q, dict) or str(q.get("id", "")) != qid:
                            continue
                        mark = json.dumps(q, sort_keys=True, ensure_ascii=False, default=str)
                        if mark not in seen:
                            seen.add(mark)
                            out.append(copy.deepcopy(q))
            return out

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

    def forget(self, session_id: str) -> bool:
        """세션을 지운다 (사용자가 「이 발표 기록 지우기」를 눌렀을 때). 없었으면 False."""
        if not session_id:
            return False
        with self._lock:
            self._qindex.pop(session_id, None)
            return self._sessions.pop(session_id, None) is not None

    # -- triage 캐시 ------------------------------------------------------

    def get_triage(self, key: str):
        """지문에 해당하는 QaTriage. 없으면 None."""
        if not key:
            return None
        with self._lock:
            entry = self._triage.get(key)
            if entry is None:
                return None
            now = self._clock()
            if now - entry["at"] > self._ttl or now > entry.get("exp", now):
                self._triage.pop(key, None)
                return None
            entry["at"] = now
            return entry["doc"]

    def set_triage(self, key: str, doc, *, ttl: float | None = None) -> None:
        """
        지문으로 담는다. 상한은 **종류마다** 센다 (`cache_kind`) — 넘치면 그 종류에서 가장 오래 안 쓴 것부터 버린다.

        ttl 을 주면 그 항목은 **담은 때부터** ttl 초 뒤에 사라진다 (써도 늘어나지 않는다). 폴백 결과(규칙 주장·실패한 문헌·
        그걸로 만든 질문)용이다 — 09-30 B-03: 폴백이 6시간짜리 정상 결과처럼 담겨, LLM·검색이 살아난 뒤에도 같은 세션은
        끝까지 반쪽 질문을 받았다. 짧게 담아 두면 미리 만들기 → 시작 한 쌍은 나눠 쓰고, 그 뒤 요청은 다시 시도한다.
        """
        if not key:
            return
        with self._lock:
            now = self._clock()
            entry = {"at": now, "doc": doc}
            if ttl is not None:
                entry["exp"] = now + max(0.0, float(ttl))
            self._triage[key] = entry
            kind = cache_kind(key)
            cap = self._kind_caps.get(kind, self._max_triage)
            same = [k for k in self._triage if cache_kind(k) == kind]
            while len(same) > cap:
                oldest = min(same, key=lambda k: self._triage[k]["at"])
                self._triage.pop(oldest, None)
                same.remove(oldest)

    # -- 내부 -------------------------------------------------------------

    def _evict_expired(self) -> None:
        now = self._clock()
        for sid in [s for s, e in self._sessions.items() if now - e["at"] > self._ttl]:
            self._sessions.pop(sid, None)

    def _evict_overflow(self) -> None:
        while len(self._sessions) > self._max_sessions:
            oldest = min(self._sessions, key=lambda s: self._sessions[s]["at"])
            self._sessions.pop(oldest, None)
