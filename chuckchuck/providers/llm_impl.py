"""
LLM provider 실제 구현입니다.
Solar / A.X / 믿음 / 엑사원 / mock을 갈아끼울 수 있습니다.
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests

from ..contracts import ConceptError
from .llm_base import LLMProvider


def _slides_in_prompt(user: str) -> list[tuple[int, str]]:
    """프롬프트의 '### 슬라이드 N: 제목' 줄에서 (번호, 제목)을 주워 온다."""
    found: list[tuple[int, str]] = []
    for line in user.splitlines():
        if not line.startswith("### 슬라이드 "):
            continue
        try:
            no = int(line.split()[2].rstrip(":"))
        except (IndexError, ValueError):
            continue
        title = line.split(":", 1)[-1].strip() if ":" in line else f"슬라이드 {no}"
        found.append((no, title))
    return found


class MockLLM(LLMProvider):
    """키 없이 F-06 / F-07 파이프라인을 검증하기 위한 가짜 LLM."""

    name = "mock"

    def complete(self, *, system: str, user: str, temperature: float = 0.2, max_tokens: int = 4096) -> str:
        if "[TASK] concept-graph" in user:
            return self._mock_graph(user)

        # user 안에 슬라이드 번호가 있으면 최소한의 JSON을 만들어 낸다
        slides = []
        for line in user.splitlines():
            if line.startswith("### 슬라이드 "):
                try:
                    no = int(line.split()[2].rstrip(":"))
                except (IndexError, ValueError):
                    continue
                title = line.split(":", 1)[-1].strip() if ":" in line else f"슬라이드 {no}"
                slides.append({
                    "slide_no": no,
                    "title": title,
                    "topic": title or f"슬라이드 {no} 주제",
                    "keywords": [title] if title else [],
                    "concepts": [f"{title or '개념'}: 슬라이드 핵심 한 줄"],
                    "importance": "core",
                })
        if not slides:
            slides = [{
                "slide_no": 1,
                "title": "샘플",
                "topic": "샘플 주제",
                "keywords": ["샘플"],
                "concepts": ["샘플: 모의 개념"],
                "importance": "core",
            }]
        return json.dumps({"slides": slides}, ensure_ascii=False)

    @staticmethod
    def _mock_graph(user: str) -> str:
        """
        F-07 용 가짜 그래프. 첫 장을 최상위로, 나머지를 그 아래에 매단다.
        두 번째 하위 개념에는 relates 간선도 하나 붙여 그래프 경로를 태운다.

        내용이 그럴듯할 필요는 없다. 후처리·불변식 경로가 도는지만 보면 된다.
        """
        found = _slides_in_prompt(user)
        if not found:
            found = [(1, "샘플")]

        root_no, root_title = found[0]
        root_id = f"s{root_no}"
        nodes = [{
            "id": root_id,
            "label": root_title or f"슬라이드 {root_no}",
            "slide_nos": [root_no],
            "summary": "모의 최상위 개념",
            "importance": "core",
        }]
        edges: list[dict] = []
        for no, title in found[1:]:
            nodes.append({
                "id": f"s{no}",
                "label": title or f"슬라이드 {no}",
                "slide_nos": [no],
                "summary": "모의 하위 개념",
                "importance": "core",
            })
            edges.append({"from": root_id, "to": f"s{no}", "kind": "parent"})

        # 하위 개념이 둘 이상이면 그것들끼리 relates 로 한 번 이어 준다
        children = [f"s{no}" for no, _ in found[1:]]
        if len(children) >= 2:
            edges.append({"from": children[0], "to": children[1], "kind": "relates"})

        sections = [{"name": "표지", "slide_role": "cover", "slide_nos": [root_no]}]
        rest = [no for no, _ in found[1:]]
        if rest:
            sections.append({"name": "본론", "slide_role": "body", "slide_nos": rest})

        return json.dumps(
            {"nodes": nodes, "edges": edges, "sections": sections}, ensure_ascii=False
        )


class OpenAICompatLLM(LLMProvider):
    """OpenAI chat completions 호환 엔드포인트 공통 구현."""

    name = "openai-compat"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        name: str | None = None,
        timeout: int = 180,
        extra_headers: dict[str, str] | None = None,
    ):
        if not api_key:
            raise ConceptError(f"[{name or self.name}] API 키가 없습니다.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.extra_headers = extra_headers or {}
        if name:
            self.name = name

    def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        res = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        if res.status_code != 200:
            raise ConceptError(
                f"[{self.name}] LLM 오류 {res.status_code}: {res.text[:300]}"
            )
        body = res.json()
        try:
            msg = body["choices"][0]["message"]
            content = msg.get("content")
            if not content:
                # 일부 모델은 reasoning 만 채우거나 content=null
                content = msg.get("reasoning_content") or msg.get("reasoning") or ""
            if not content:
                raise KeyError("empty content")
            return content
        except (KeyError, IndexError, TypeError) as e:
            raise ConceptError(f"[{self.name}] 응답 형식 오류: {body}") from e


class SolarLLM(OpenAICompatLLM):
    """Upstage Solar — 기본 추론 백엔드."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        super().__init__(
            api_key=api_key or os.environ.get("UPSTAGE_API_KEY", ""),
            base_url=os.environ.get("UPSTAGE_SOLAR_BASE_URL", "https://api.upstage.ai/v1"),
            model=model or os.environ.get("UPSTAGE_SOLAR_MODEL", "solar-pro3"),
            name="solar",
        )


class AxLLM(OpenAICompatLLM):
    """SKT A.X-K1."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        super().__init__(
            api_key=api_key or os.environ.get("AX_API_KEY", ""),
            base_url=os.environ.get("AX_BASE_URL", "https://awf-gw.adot.ai/v1"),
            model=model or os.environ.get("AX_MODEL", "A.X-K1"),
            name="ax",
        )


class MidmLLM(OpenAICompatLLM):
    """KT 믿음 (Friendli dedicated)."""

    def __init__(self, api_key: str | None = None, endpoint_id: str | None = None):
        eid = endpoint_id or os.environ.get("MIDM_ENDPOINT_ID", "")
        super().__init__(
            api_key=api_key or os.environ.get("MIDM_API_KEY", ""),
            base_url=os.environ.get("MIDM_BASE_URL", "https://api.friendli.ai/dedicated/v1"),
            model=eid,
            name="midm",
        )


class ExaoneLLM(OpenAICompatLLM):
    """LG 엑사원 (Friendli dedicated)."""

    def __init__(self, api_key: str | None = None, endpoint_id: str | None = None):
        eid = endpoint_id or os.environ.get("EXAONE_ENDPOINT_ID", "")
        super().__init__(
            api_key=api_key or os.environ.get("EXAONE_API_KEY", ""),
            base_url=os.environ.get("EXAONE_BASE_URL", "https://api.friendli.ai/dedicated/v1"),
            model=eid,
            name="exaone",
        )


REGISTRY: dict[str, type[LLMProvider]] = {
    "mock": MockLLM,
    "solar": SolarLLM,
    "ax": AxLLM,
    "midm": MidmLLM,
    "exaone": ExaoneLLM,
}


def get_llm(name: str | None = None, **kwargs) -> LLMProvider:
    """
    LLM 제공자 생성.

    name 생략 시 REASONING_BACKEND 환경변수(기본 solar)를 따른다.
    """
    backend = (name or os.environ.get("REASONING_BACKEND") or "solar").lower()
    if backend not in REGISTRY:
        raise ConceptError(
            f"모르는 LLM: {backend}. 가능한 값: {', '.join(REGISTRY)}"
        )
    return REGISTRY[backend](**kwargs)


def health_check() -> str:
    """네 모델이 다 살아 있는지 한 번에 확인."""
    lines = ["LLM 연결 확인", "-" * 52]
    for key in ("solar", "ax", "midm", "exaone"):
        try:
            llm = get_llm(key)
            out = llm.complete(
                system="한 단어로만.",
                user="OK 라고만 답하세요.",
                max_tokens=10,
            ).strip()
            lines.append(f"  {key:<8} 응답: {out[:40]}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"  {key:<8} 실패: {str(exc)[:70]}")
    return "\n".join(lines)
