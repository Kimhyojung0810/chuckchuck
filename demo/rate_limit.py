"""
데모 브리지의 **IP당 요청 제한**입니다.

모든 API 가 과금되는 외부 호출(Upstage 파싱 · A.X STT · LLM)을 부릅니다.
브리지에 인증이 없어서, 같은 망에 있는 누구든(또는 잘못 눌린 새로고침 루프가)
크레딧을 태울 수 있었습니다. 팀 규칙(`security.md`) 의 "Rate limiting on all
endpoints" 를 데모 수준에서 지키기 위한 최소 장치입니다.

인증을 대신하지는 않습니다 — 브리지는 로컬(127.0.0.1) 전용이라는 전제가 그대로다.

    limiter = RateLimiter(limit=30, window_sec=60)
    if not limiter.allow("127.0.0.1"):
        ... 429 ...

`limit <= 0` 이면 제한을 끈다 (테스트·오프라인 시연용).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    """고정 창(sliding window) 카운터. 키(보통 클라이언트 IP)마다 따로 센다."""

    def __init__(self, *, limit: int, window_sec: float = 60.0, clock=time.monotonic,
                 max_keys: int = 100_000) -> None:
        self.limit = limit
        self.window = window_sec
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: dict[str, deque] = defaultdict(deque)
        # 키가 끝없이 자라지 않게 (2026-10-05 방패). 세션 칸은 세션 id 로 센다 — id 를 바꿔 가며 두드리면 예전엔
        # 키가 요청 수만큼 쌓이고 지워지지 않았다. 창 하나마다 빈 키·창 밖 키를 걷고, 그래도 max_keys 를 넘으면
        # 가장 오래 조용했던 절반을 버린다 (버려진 키는 0 부터 다시 센다 — 막는 쪽으로 틀리지 않는다).
        self.max_keys = max_keys
        self._next_prune = clock() + window_sec

    def allow(self, key: str) -> bool:
        """이번 요청을 통과시킬지. 통과시키면 카운트한다."""
        if self.limit <= 0:
            return True
        now = self._clock()
        with self._lock:
            if now >= self._next_prune or len(self._hits) > self.max_keys:
                self._prune(now)
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def retry_after(self, key: str) -> int:
        """다음 요청까지 남은 초. 429 응답의 안내 문구에 쓴다."""
        if self.limit <= 0:
            return 0
        with self._lock:
            hits = self._hits.get(key)
            if not hits:
                return 0
            return max(1, int(self.window - (self._clock() - hits[0]) + 0.999))

    def count(self, key: str) -> int:
        """지금 창 안에 든 횟수 (관측용 — 세지 않는다)."""
        now = self._clock()
        with self._lock:
            hits = self._hits.get(key)
            return sum(1 for t in hits if now - t <= self.window) if hits else 0

    def _prune(self, now: float) -> None:
        """창 밖으로 나간 기록만 남은 키를 지운다. 잠금을 쥔 채 부른다 — 키 수만 개라도 수 밀리초다."""
        for key in [k for k, d in self._hits.items() if not d or now - d[-1] > self.window]:
            del self._hits[key]
        if len(self._hits) > self.max_keys:
            keep = sorted(self._hits.items(), key=lambda kv: kv[1][-1], reverse=True)[: self.max_keys // 2]
            self._hits = defaultdict(deque, keep)
        self._next_prune = now + self.window

    def __len__(self) -> int:
        with self._lock:
            return len(self._hits)
