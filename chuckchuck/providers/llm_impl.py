"""
LLM provider 실제 구현입니다.
Solar / A.X / 믿음 / 엑사원 / mock을 갈아끼울 수 있습니다.
"""

from __future__ import annotations

import json
import os
import sys
import time
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
        # F-07 프롬프트는 "제목 — 주제" 꼴 — label 은 제목만 쓴다 (중복 방지)
        title = title.split("—")[0].strip()
        found.append((no, title))
    return found


#: LLM 응답을 기다리는 시간(초). 넉넉하게 잡는다.
#:
#: 실측(2026-07-30, 같은 12장 PPTX·같은 발화·실 Solar)에서 F-07 이
#: 160초 → 180초 초과(사망) → 442초로 흔들렸다. 2.8배 편차다.
#: 생성 시간은 예측이 안 되므로 여기서 끊는 건 의미가 없다 — 30분을 준다.
LLM_TIMEOUT_SEC = int(os.environ.get("CHUCKCHUCK_LLM_TIMEOUT_SEC", "1800"))

#: 연결(TCP+TLS)까지만 기다리는 시간(초). 이건 짧아야 한다.
#:
#: 타임아웃을 통째로 없애면 안 된다 — 끊긴 연결은 영원히 안 돌아와서
#: 데모가 아무 피드백 없이 멈춘다. 그래서 둘을 나눈다:
#: 서버가 죽었으면 10초 안에 알고, 살아서 생성 중이면 30분을 기다린다.
LLM_CONNECT_TIMEOUT_SEC = int(os.environ.get("CHUCKCHUCK_LLM_CONNECT_TIMEOUT_SEC", "10"))


#: 호출별 소요·토큰을 stderr 에 남긴다. 끄려면 CHUCKCHUCK_LLM_LOG=0
LLM_LOG = os.environ.get("CHUCKCHUCK_LLM_LOG", "1") not in ("0", "false", "False")


def _log_call(name: str, model: str, elapsed: float, res) -> None:
    """
    '왜 느린가' 는 추측으로 답할 게 아니다.

    F-07 이 같은 입력에 160초 → 442초로 흔들렸는데, 그게 재시도 때문인지
    출력이 길어서인지 서버가 느려서인지 코드가 아무것도 안 남겨 알 수 없었다.
    호출 한 번마다 소요·입출력 토큰·생성 속도를 찍는다.
    """
    if not LLM_LOG:
        return
    inp = out = None
    try:
        usage = res.json().get("usage") or {}
        inp = usage.get("prompt_tokens")
        out = usage.get("completion_tokens")
    except Exception:  # noqa: BLE001 — 로깅이 본 흐름을 막으면 안 된다
        pass
    rate = f" ({out / elapsed:.1f} tok/s)" if out and elapsed > 0 else ""
    tok = f" in={inp} out={out}" if inp is not None else ""
    sys.stderr.write(f"[llm] {name}/{model} {elapsed:.1f}s{tok}{rate}\n")


class MockLLM(LLMProvider):
    """키 없이 F-06 / F-07 파이프라인을 검증하기 위한 가짜 LLM."""

    name = "mock"

    def complete(self, *, system: str, user: str, temperature: float = 0.2, max_tokens: int = 4096) -> str:
        if "[TASK] concept-graph" in user:
            return self._mock_graph(user)
        if "[TASK] speech-alignment" in user:
            return self._mock_alignment(user)
        if "[TASK] audience-chatter" in user:
            return self._mock_chatter(user)

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
    def _mock_alignment(user: str) -> str:
        """
        F-11 용 가짜 판정. 프롬프트의 '- (id) ...' 줄에서 노드 id 를 주워,
        마지막 하나만 missing, 나머지는 aligned 로 판정한다.
        노드가 둘 이상이면 앞의 둘을 speech_edge 로 잇고, 추가 개념을 하나 낸다.

        내용이 그럴듯할 필요는 없다. 후처리·불변식 경로가 도는지만 보면 된다.
        """
        ids = []
        for line in user.splitlines():
            if line.startswith("- (") and ")" in line:
                ids.append(line[3:line.index(")")])
        if not ids:
            ids = ["n1"]

        items = [
            {
                "node_id": nid,
                "verdict": "aligned",
                "evidence": "모의 근거 발화 인용",
                "note": "모의 판정",
            }
            for nid in ids[:-1]
        ]
        items.append({"node_id": ids[-1], "verdict": "missing", "evidence": "", "note": ""})

        edges = []
        if len(ids) >= 2:
            edges.append({"from": ids[0], "to": ids[1], "cue": "그래서 이어서 설명하면"})

        extras = [{"label": "모의 추가 개념", "quote": "자료에 없는 보충 설명", "slide_no": 1}]
        return json.dumps(
            {"items": items, "speech_edges": edges, "extra_concepts": extras},
            ensure_ascii=False,
        )

    @staticmethod
    def _mock_chatter(user: str) -> str:
        """
        삐약 청중석용 가짜 수다. 프롬프트의 '발화자:' 줄에서 누구인지 알아내고,
        '- (id) ...' 사실 줄에서 첫 node_id 를 주워 근거로 단다.

        대사는 몽총한 톤의 고정 대본이다 — 키 없이 데모를 돌릴 때 그대로 화면에
        나가므로, 후처리 경로 검증뿐 아니라 톤 확인용으로도 쓰인다.
        """
        speaker = "midm"
        ids: list[str] = []
        for line in user.splitlines():
            if line.startswith("발화자:"):
                speaker = line.split(":", 1)[-1].strip() or speaker
            elif line.startswith("- (") and ")" in line:
                ids.append(line[3:line.index(")")])

        # 라운드마다 같은 대사를 주면 화면에 똑같은 말풍선이 두 개 뜬다.
        # 히스토리가 비어 있는 첫 라운드인지 보고 대본을 갈아 끼운다.
        first_round = "아직 아무도 입을 열지 않았다" in user
        scripts = {
            "midm": [
                [("어... 아 맞다. 그거 얘기 안 했잖아. 흥, 나 계속 기다렸는데.", "grumpy"),
                 ("뭐였더라, 아까 그 개념... 아무튼 안 나왔어. 흥.", "grumpy")],
                [("아니 근데 그거 진짜 중요한 거였는데... 흥. 나만 신경 쓰였나.", "grumpy"),
                 ("...뭐, 나머지는 그럭저럭. 흥.", "neutral")],
            ],
            "solar": [
                [("오홍, 나 자료 다 읽었는데 순서가 좀... 어? 뭐였지.", "curious"),
                 ("아 맞다, 그 부분 앞뒤가 바뀐 것 같았어. 오홍.", "curious")],
                [("근데 그 두 개를 이어서 말했으면 더 좋았을 텐데. 오홍.", "curious"),
                 ("내가 유인물을 잘못 봤나? 아닌 것 같은데.", "neutral")],
            ],
            "exaone": [
                [("그거 설명할 때 되게 좋았어... 히히. 나 고개 끄덕였잖아.", "happy"),
                 ("전문가로서 말하자면... 음. 좋았어. 히히.", "happy")],
                [("아 그리고 그 부분도 괜찮았어. 뭐더라... 아무튼 좋았어. 히히.", "happy"),
                 ("나 박수 칠 뻔했잖아. 히히.", "happy")],
            ],
            "ax": [
                [("헐 나 그거 들었어. 자료에 없던 거 아니야? 아닌가?", "excited"),
                 ("헐, 근데 내가 무슨 얘기 하고 있었지.", "curious")],
                [("아 맞다, 그건 한 번도 안 나왔어. 내가 다 들었는데. 헐.", "excited"),
                 ("시간은 딱 맞았던 것 같아... 아마도?", "neutral")],
            ],
        }
        pair = scripts.get(speaker, scripts["midm"])[0 if first_round else 1]
        refs = [ids[0]] if ids else []
        turns = [
            {"text": pair[0][0], "mood": pair[0][1], "ref_node_ids": refs},
            {"text": pair[1][0], "mood": pair[1][1], "ref_node_ids": []},
        ]
        return json.dumps({"turns": turns}, ensure_ascii=False)

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
        timeout: int | None = None,
        extra_headers: dict[str, str] | None = None,
    ):
        if not api_key:
            raise ConceptError(f"[{name or self.name}] API 키가 없습니다.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = LLM_TIMEOUT_SEC if timeout is None else timeout
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
        # (연결, 읽기) — 죽은 서버는 빨리 포기하고, 살아서 생성 중이면 오래 기다린다
        t0 = time.monotonic()
        res = requests.post(
            url, headers=headers, json=payload,
            timeout=(LLM_CONNECT_TIMEOUT_SEC, self.timeout),
        )
        _log_call(self.name, self.model, time.monotonic() - t0, res)
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
