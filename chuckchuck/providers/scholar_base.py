"""
학술 검색(논문 찾기) provider 의 공통 인터페이스입니다.
F-24 문헌 모듈이 이 인터페이스로 OpenAlex 같은 검색 API 를 부릅니다.

LLM provider 와 같은 규율이다 — 벤더 raw 는 구현체 안에서만 살고, 밖으로는
`contracts.PaperRef` 만 나간다 (DEV_POLICY §4-2·§4-3).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ScholarProvider(ABC):
    name: str = "unknown"

    @abstractmethod
    def search(self, query: str, *, limit: int = 5) -> list:
        """
        검색어 → `PaperRef` 목록 (kind="scholar", id 는 비어 있다 — 호출자가 문서 안에서 매긴다).

        결과는 **품질 순**이어야 한다 (관련도 + 피인용 + 최근성). 실패하면
        `contracts.PaperError` 를 던진다 — 빈 목록으로 조용히 넘기지 않는다.
        호출자는 그 예외를 받아 자료 인용(deck)만으로 폴백한다.
        """

    def resolve(self, title: str, doi: str = "") -> list:
        """
        자료가 인용한 문헌 하나를 되찾는다 (DOI 가 있으면 정확히, 없으면 제목으로).
        기본 구현은 제목 검색 1건이다. 구현체가 DOI 조회를 지원하면 덮어쓴다.
        """
        return self.search(title, limit=1) if title else []
