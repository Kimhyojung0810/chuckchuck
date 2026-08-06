"""
STT provider 실제 구현입니다.
기본은 SKT A.X, 개발용으로 mock도 있습니다.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import requests

from ..contracts import STTError, Word
from .stt_base import STTProvider


class MockSTT(STTProvider):
    """API 키 없이 파이프라인 전체를 돌려보기 위한 가짜 제공자."""

    name = "mock"
    SUPPORTS_WORD_TIMESTAMPS = True
    VERIFIED = "가짜 데이터"

    DEFAULT_SCRIPT = (
        "안녕하세요 오늘 발표할 주제는 IMU2CLIP 논문 리뷰입니다 "
        "먼저 self supervised learning 부터 설명드리겠습니다 "
        "라벨을 직접 만들지 않고 pretext task 로 표현을 먼저 학습합니다 "
        "다음은 contrastive learning 입니다 "
        "같은 데이터는 가깝게 다른 데이터는 멀게 만드는 방식입니다 "
        "비디오 IMU 텍스트를 joint space 에 정렬합니다"
    )

    def __init__(
        self,
        script: str | None = None,
        wpm: float = 150.0,
        script_file: str | Path | None = None,
    ):
        if script_file:
            script = Path(script_file).read_text(encoding="utf-8")
        self.script = script or self.DEFAULT_SCRIPT
        self.wpm = wpm

    def transcribe(self, audio_path: str | Path) -> tuple[str, list[Word]]:
        tokens = self.script.split()
        sec_per_word = 60.0 / self.wpm
        words: list[Word] = []
        t = 0.0
        for tok in tokens:
            words.append(Word(
                text=tok,
                start_sec=round(t, 3),
                end_sec=round(t + sec_per_word, 3),
            ))
            t += sec_per_word
        return " ".join(tokens), words


class AxSTT(STTProvider):
    """
    SKT A.X STT (Batch).

    문서: https://portal.adot.ai/docs/stt-api-guide

    흐름:
        1) GET  /v1/stt/upload-token?fileSize=N  → upload_token
        2) PUT  /v1/stt/upload/{upload_token}    → file_key
        3) POST /v1/stt/transcript               → utterances / words

    인증은 LLM과 달리 X-API-Key 헤더를 쓴다.
    단어 시각 필드: start_time, end_time (초).
    """

    name = "skt-ax"
    SUPPORTS_WORD_TIMESTAMPS = True
    VERIFIED = "확인됨 — portal.adot.ai STT 가이드 + 실호출"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        keywords: list[str] | None = None,
        timeout: int = 300,
    ):
        self.api_key = (
            api_key
            or os.environ.get("AX_STT_API_KEY")
            or os.environ.get("AX_API_KEY")
            or ""
        )
        if not self.api_key:
            raise STTError("AX_STT_API_KEY (또는 AX_API_KEY) 환경변수가 필요합니다.")

        raw = (base_url or os.environ.get("AX_STT_BASE_URL") or "https://awf-gw.adot.ai").rstrip("/")
        self.base_url = raw
        self.model = (
            model
            or os.environ.get("AX_STT_BATCH_MODEL")
            or "A.X_STT_note_batch"
        )
        self.keywords = keywords or []
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        # User-Agent 를 안 주면 requests 가 "python-requests/2.x" 를 보낸다.
        # A.X 게이트웨이 앞단의 WAF(F5 BIG-IP)가 그걸 보고 업로드를 막았다 —
        # HTTP 200 에 JSON 대신 "Request Rejected" HTML 을 돌려준다.
        # 우리 앱 이름을 밝히는 게 정상적인 API 클라이언트 동작이다.
        return {"X-API-Key": self.api_key, "User-Agent": "chuckchuck/1.0"}

    @staticmethod
    def _response_json(res: requests.Response, step: str) -> dict:
        """빈 본문·HTML 응답을 JSONDecodeError 대신 읽기 쉬운 STTError 로 바꾼다."""
        text = (res.text or "").strip()
        if not text:
            raise STTError(
                f"A.X STT {step} 응답이 비어 있어요 (HTTP {res.status_code}). "
                "잠시 후 다시 녹음·업로드해 주세요."
            )
        try:
            data = res.json()
        except ValueError as e:
            raise STTError(
                f"A.X STT {step} 응답을 읽지 못했어요 (HTTP {res.status_code}): "
                f"{text[:240]}"
            ) from e
        if not isinstance(data, dict):
            raise STTError(f"A.X STT {step} 응답 형식이 이상해요: {text[:240]}")
        return data

    def _upload(self, audio_path: Path) -> str:
        size = audio_path.stat().st_size
        last_err: Exception | None = None
        # 간헐적 빈 200 응답이 있어 한 번 더 시도한다
        for attempt in range(1, 3):
            try:
                tok_res = requests.get(
                    f"{self.base_url}/v1/stt/upload-token",
                    params={"fileSize": size},
                    headers=self._headers(),
                    timeout=30,
                )
                if tok_res.status_code != 200:
                    raise STTError(
                        f"A.X STT upload-token 실패 {tok_res.status_code}: {tok_res.text[:300]}"
                    )
                upload_token = self._response_json(tok_res, "upload-token").get("upload_token")
                if not upload_token:
                    raise STTError(f"upload_token 없음: {(tok_res.text or '')[:300]}")

                with audio_path.open("rb") as f:
                    up_res = requests.put(
                        f"{self.base_url}/v1/stt/upload/{upload_token}",
                        headers={
                            **self._headers(),
                            "Content-Type": "application/octet-stream",
                            "Content-Length": str(size),
                        },
                        data=f,
                        timeout=self.timeout,
                    )
                if up_res.status_code != 200:
                    raise STTError(
                        f"A.X STT upload 실패 {up_res.status_code}: {up_res.text[:300]}"
                    )
                file_key = self._response_json(up_res, "upload").get("file_key")
                if not file_key:
                    raise STTError(f"file_key 없음: {(up_res.text or '')[:300]}")
                return file_key
            except STTError as e:
                last_err = e
                if attempt >= 2:
                    break
                # 빈 응답/일시 오류만 재시도
                msg = str(e)
                if "비어" not in msg and "읽지 못" not in msg and "실패 5" not in msg:
                    raise
        assert last_err is not None
        raise last_err

    def transcribe(self, audio_path: str | Path) -> tuple[str, list[Word]]:
        path = Path(audio_path)
        if not path.exists():
            raise STTError(f"오디오 파일이 없습니다: {path}")

        file_key = self._upload(path)
        payload: dict = {
            "message_id": f"chuckchuck-{uuid.uuid4().hex[:12]}",
            "speech_model": self.model,
            "audio_file_key": file_key,
        }
        if self.keywords:
            payload["keywords"] = self.keywords

        res = requests.post(
            f"{self.base_url}/v1/stt/transcript",
            headers={**self._headers(), "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
        )
        if res.status_code != 200:
            raise STTError(f"A.X STT transcript 실패 {res.status_code}: {res.text[:300]}")

        return self._parse(self._response_json(res, "transcript"))

    @staticmethod
    def _parse(body: dict) -> tuple[str, list[Word]]:
        words: list[Word] = []
        texts: list[str] = []

        for utt in body.get("utterances") or []:
            msg = (utt.get("text") or utt.get("msg") or "").strip()
            if msg:
                texts.append(msg)

            utt_words = utt.get("words") or []
            if utt_words:
                for w in utt_words:
                    text = (w.get("text") or "").strip()
                    if not text:
                        continue
                    start = float(w.get("start_time", w.get("start", 0.0)))
                    end = float(w.get("end_time", w.get("end", start)))
                    words.append(Word(text=text, start_sec=start, end_sec=end))
            elif msg:
                # 단어가 없으면 발화 단위로 근사 (F-17 정밀도는 떨어짐)
                start = float(utt.get("start_time", utt.get("start", 0.0)))
                end = float(utt.get("end_time", utt.get("end", start)))
                words.append(Word(text=msg, start_sec=start, end_sec=end))

        # top-level words fallback
        if not words:
            for w in body.get("words") or []:
                text = (w.get("text") or "").strip()
                if not text:
                    continue
                start = float(w.get("start_time", w.get("start", 0.0)))
                end = float(w.get("end_time", w.get("end", start)))
                words.append(Word(text=text, start_sec=start, end_sec=end))

        full = " ".join(texts) if texts else " ".join(w.text for w in words)
        return full, words


# 하위 호환 별칭
SKTAxSTT = AxSTT


REGISTRY: dict[str, type[STTProvider]] = {
    "mock": MockSTT,
    "skt-ax": AxSTT,
    "ax": AxSTT,
}


def get_provider(name: str, **kwargs) -> STTProvider:
    """이름으로 제공자를 만든다. 벤더 교체는 이 문자열 하나만 바꾸면 끝."""
    if name not in REGISTRY:
        raise STTError(
            f"모르는 STT 제공자: {name}. 가능한 값: {', '.join(REGISTRY)}"
        )
    return REGISTRY[name](**kwargs)


def compare_table() -> str:
    lines = ["STT 제공자 비교 (단어별 시각이 1순위 조건)", "-" * 58]
    for key, cls in REGISTRY.items():
        ts = "O" if cls.SUPPORTS_WORD_TIMESTAMPS else "X"
        lines.append(f"  {key:<12} 단어별시각 {ts}   {cls.VERIFIED}")
    return "\n".join(lines)
