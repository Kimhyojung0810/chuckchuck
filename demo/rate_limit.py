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

    def __init__(self, *, limit: int, window_sec: float = 60.0, clock=time.monotonic) -> None:
        self.limit = limit
        self.window = window_sec
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """이번 요청을 통과시킬지. 통과시키면 카운트한다."""
        if self.limit <= 0:
            return True
        now = self._clock()
        with self._lock:
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
