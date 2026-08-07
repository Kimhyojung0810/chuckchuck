"""
LLM provider 실제 구현입니다.
Solar / A.X / 믿음 / 엑사원 / mock을 갈아끼울 수 있습니다.
"""

from __future__ import annotations

import json
import os
import re
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


def _ids_in_prompt(user: str) -> list[str]:
    """
    프롬프트의 '- (id) ...' 줄에서 후보 id 를 주워 온다.

    F-11·F-08 프롬프트가 공통으로 쓰는 꼴이다. 조인 키를 지어내지 않고
    실제 후보 안에서만 고르므로, 어댑터의 '후보 밖 id 는 버린다' 경로도 같이 탄다.
    """
    ids = []
    for line in user.splitlines():
        if line.startswith("- (") and ")" in line:
            ids.append(line[3:line.index(")")])
    return ids


class MockLLM(LLMProvider):
    """키 없이 F-06 / F-07 파이프라인을 검증하기 위한 가짜 LLM."""

    name = "mock"

    def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> str:
        # 가짜 LLM 은 늘 JSON 만 낸다 — json_mode 는 받기만 하고 무시한다
        if "[TASK] concept-graph" in user:
            return self._mock_graph(user)
        if "[TASK] audience-chatter" in user:
            return self._mock_chatter(user)
        if "[TASK] speech-alignment" in user:
            return self._mock_alignment(user)
        if "[TASK] qa-triage" in user:
            return self._mock_triage(user)
        if "[TASK] qa-questions" in user:
            return self._mock_questions(user)
        if "[TASK] qa-judge" in user:
            return self._mock_judge(user)
        if "[TASK] presentation-strategy" in user:
            return self._mock_strategy(user)
        if "[TASK] rubric-score" in user:
            return self._mock_rubric(user)

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
    def _mock_rubric(user: str) -> str:
        """
        F-14 용 가짜 채점. 프롬프트의 '- (번호) 항목명: 설명' 줄에서 번호를 주워
        요청받은 항목만 매긴다.

        점수는 번호로 정하는 결정값이다 — 랜덤을 쓰면 같은 발표인데 데모를 돌릴 때마다
        점수가 달라져서 부스에서 설명할 수 없다. 근거(evidence)는 반드시 채운다.
        f14 의 정규화가 근거 없는 항목을 버리므로, 비우면 mock 모드에서 전부
        '못 쟀다' 가 되어 화면이 텅 빈다.
        """
        nos = [int(x) for x in _ids_in_prompt(user) if x.isdigit()]
        if not nos:
            return json.dumps({"items": []}, ensure_ascii=False)
        return json.dumps(
            {
                "items": [
                    {
                        "no": no,
                        # 42~93 을 번호로 훑는다. 좁은 구간(65~85)을 쓰면 클러스터
                        # 평균이 전부 70 언저리로 뭉개져서, 발표 상황을 바꿔도 최종
                        # 점수가 안 움직인다 — 가중치가 붙어 있는데도 안 붙은 것처럼
                        # 보인다. 부스에서 상황을 바꿔 보여 주려면 벌어져 있어야 한다.
                        "score": 42 + (no * 23) % 52,
                        "evidence": f"모의 근거 — {no}번 항목을 판단한 발화 인용",
                        "note": "모의 채점이라 실제 발표 내용을 보지 않았어요",
                    }
                    for no in nos
                ]
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _mock_alignment(user: str) -> str:
        """
        F-11 용 가짜 판정. 프롬프트의 '- (id) ...' 줄에서 노드 id 를 주워,
        마지막 하나만 missing, 나머지는 aligned 로 판정한다.
        노드가 둘 이상이면 앞의 둘을 speech_edge 로 잇고, 추가 개념을 하나 낸다.

        내용이 그럴듯할 필요는 없다. 후처리·불변식 경로가 도는지만 보면 된다.
        """
        ids = _ids_in_prompt(user) or ["n1"]

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
    def _mock_triage(user: str) -> str:
        """
        F-08 1차용 가짜 심사. 후보 id 를 주워 앞에서부터 치명 → 보통 → 가벼움을 돌려 준다.
        홀수 번째 후보에는 함정을 세워 트랙별 함정 상한 경로도 태운다.

        내용이 그럴듯할 필요는 없다. 후처리·불변식 경로가 도는지만 보면 된다.
        """
        ids = _ids_in_prompt(user) or ["n1"]
        marks = [
            {
                "node_id": nid,
                "severity": (i % 3) + 1,
                "trap": i % 2 == 0,
                "angle": f"{nid} 를 그렇게 설계한 근거",
            }
            for i, nid in enumerate(ids)
        ]
        return json.dumps({"marks": marks}, ensure_ascii=False)

    @staticmethod
    def _mock_questions(user: str) -> str:
        """F-08 2차용 가짜 질문. 대상 id 마다 문장 넷을 하나씩 채운다."""
        ids = _ids_in_prompt(user) or ["n1"]
        questions = [
            {
                "node_id": nid,
                "question": f"{nid} 개념을 자기 말로 설명해 주시겠어요?",
                "why": "모의 근거 — 자료가 비중을 둔 개념이에요",
                "hint": "근거 슬라이드를 떠올려 보세요",
                "answer_gist": f"모의 골자 — {nid} 는 이런 이유로 이렇게 동작한다",
            }
            for nid in ids
        ]
        return json.dumps({"questions": questions}, ensure_ascii=False)

    @staticmethod
    def _mock_judge(user: str) -> str:
        """
        F-09 용 가짜 판정. 답변 길이로 verdict 를 가른다 —
        길게 답하면 good, 짧으면 partial. score 는 일부러 비워 폴백 경로를 태운다.
        """
        answer = user.split("## 이번 답변 — 이것을 판정하라", 1)[-1].strip()
        verdict = "good" if len(answer) >= 20 else "partial"
        return json.dumps(
            {
                "verdict": verdict,
                "react": "모의 반응 — 그렇게 설명하시면 됩니다.",
                "summary_sentence": "모의 총평 한 문장",
                "missing_points": [] if verdict == "good" else ["모의 누락 포인트"],
                # 짧게 답하면(partial) 되묻는 경로를 타야 한다. good 이면 후처리가 비운다.
                "followup": (
                    "" if verdict == "good"
                    else "모의 후속 질문 — 근거를 하나만 더 들어 주시겠어요?"
                ),
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _mock_strategy(user: str) -> str:
        """
        F-20 용 가짜 구성 제안. 프롬프트의 「슬라이드별 시간」 첫 줄에서
        권장 대 실제를 읽어, 도입을 초과했으면 결론 선행형을 아니면 축 고정형을 고른다.

        keep.quote 는 프롬프트의 「실제 발화」 첫 줄을 그대로 옮긴다 —
        지어낸 인용을 버리는 검증을 실제로 통과해 봐야 왕복이 확인된다.
        """
        def _amount(raw: str) -> int:
            """'2:24' 도 '18%' 도 크기 비교만 되면 된다. 못 읽으면 -1."""
            raw = raw.strip().rstrip("%")
            parts = raw.split(":")
            try:
                if len(parts) == 2:
                    return int(parts[0]) * 60 + int(parts[1])
                return int(float(raw))
            except ValueError:
                return -1

        slide, recommended, actual = "S01", -1, -1
        for line in user.split("슬라이드별 시간", 1)[-1].splitlines():
            m = re.search(r"(\S+)\s+.*·\s*권장\s*(\S+)\s*·\s*실제\s*(\S+)", line)
            if m:
                slide = m.group(1)
                recommended, actual = _amount(m.group(2)), _amount(m.group(3))
                break

        quote, at = "", ""
        for line in user.split("실제 발화", 1)[-1].splitlines():
            m = re.match(r"\s*\[(\d+:\d+)\]\s*(.+)", line)
            if m:
                at, quote = m.group(1), m.group(2).strip()
                break

        # 슬라이드 목록에서 실제 번호를 주워 구간에 나눠 담는다.
        # 지어낸 번호는 검증이 지우므로, 목도 실재하는 번호만 써야 화면이 빈다.
        nos = [int(m.group(1))
               for m in re.finditer(r"^\s*(\d+)번\s",
                                    user.split("슬라이드 목록", 1)[-1].split("개념별 판정")[0],
                                    re.M)]
        half = max(1, len(nos) // 2)
        overran = actual > recommended >= 0
        chosen = {
            "type": "베이조스식 결론 선행형" if overran else "잡스식 축 고정형",
            "why": (
                f"모의 근거 — {slide} 에 권장보다 오래 머물렀어요."
                if overran else "모의 근거 — 주장 하나로 묶을 여지가 있어요."
            ),
            "outline": [
                {"role": "한 문장 선언", "from": "0:00", "to": "0:40",
                 "slides": [], "new": True,
                 "what": "모의 구간 — 결론을 먼저 못박아요.",
                 "add": "모의 보완 — 마지막 장의 결론을 여기로 끌어와 주세요."},
                {"role": "근거", "from": "0:40", "to": "3:00",
                 "slides": nos[:half],
                 "what": "모의 구간 — 앞부분을 줄이고 근거만 남겨요.",
                 "add": ""},
                {"role": "마무리", "from": "3:00", "to": "5:00",
                 "slides": nos[half:],
                 "what": "모의 구간 — 처음 던진 결론으로 되돌아와요.",
                 "add": "모의 보완 — 수치 하나를 덧붙여 주세요."},
            ],
        }
        if quote:
            chosen["keep"] = {"quote": quote, "at": at}
        return json.dumps(
            {
                "chosen": chosen,
                "alternatives": [
                    {"type": "머스크식 전제 축적형", "one_line": "모의 대안 — 수치부터 쌓아요."},
                    {"type": "저커버그식 사용자 서사형", "one_line": "모의 대안 — 한 장면에서 시작해요."},
                ],
            },
            ensure_ascii=False,
        )

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


#: 한 번의 LLM 호출을 기다리는 최대 시간(초).
#: 실측에서 12장짜리 발표자료의 F-07 그래프 호출이 180초를 넘긴 적이 있다 —
#: 자료가 크거나 모델이 붐빌 때 늘릴 수 있게 환경변수로 뺐다.
DEFAULT_TIMEOUT_SEC = int(os.environ.get("LLM_TIMEOUT_SEC", "180"))


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
        self.timeout = DEFAULT_TIMEOUT_SEC if timeout is None else timeout
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
        json_mode: bool = False,
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
        if json_mode:
            # 프롬프트 지시만으로는 모델이 한 줄 JSON 안에 이스케이프 안 된 따옴표를
            # 넣어 파싱이 깨진다. OpenAI 호환 제공자는 이 필드로 구조를 강제한다.
            payload["response_format"] = {"type": "json_object"}
            # Upstage 는 여기에 더해 messages 안에 'json' 이라는 낱말이 실제로 있기를
            # 요구한다. 없으면 400 이다 — 출력 형식을 프롬프트에 안 적은 호출자는
            # 실행해 보기 전까지 모르는 지뢰를 밟는다 (F-09 「모르겠어요」가 그랬다).
            if "json" not in f"{system}\n{user}".lower():
                payload["messages"][0]["content"] += "\n\n출력은 JSON 객체 하나로만 한다."
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
