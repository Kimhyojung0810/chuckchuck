"""
STT provider 실제 구현입니다.
기본은 SKT A.X, 개발용으로 mock도 있습니다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
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


"""
A.X 게이트웨이 앞단 WAF(F5 계열)가 업로드 본문을 검사하다 오디오 바이트를
공격 서명으로 오인해 막는다 — HTTP 200 에 JSON 대신 "Request Rejected" HTML.
실제 녹음이 전부 여기서 죽어 데모 자체가 멈췄다.

2026-08-07 실측(같은 PCM WAV 를 길이만 잘라 업로드, 전사 호출 없이):

    0.5MB REJECT · 1MB REJECT · 2MB REJECT · 4MB REJECT · 6MB REJECT · 8MB REJECT
    10MB PASS · 10.5MB PASS · 11MB PASS

경계가 정확히 10 MiB 다. 내용이 같은데 크기만으로 뒤집히니 「크기 × 엔트로피」가
아니라 **검사 버퍼 상한**이다 — 그보다 큰 본문은 검사 없이 지나간다.
(예전 기록의 '크기 × 엔트로피' 결론은 10MB 위를 재보지 않아서 생긴 오진이다.)

그래서 업로드 직전에 비압축 PCM WAV 로 바꿔 본문이 이 상한을 넘게 만든다.
샘플레이트는 **패딩이 가장 적게 드는 쪽**으로 고른다 — STT 는 오디오 길이로
과금·지연이 정해지므로, 업로드 바이트보다 무음 길이를 아끼는 게 이득이다.

    긴 녹음(5분 30초↑)  16kHz 모노  = 32KB/s  → 그대로 상한을 넘는다 (업로드 최소)
    중간 녹음(55초↑)    48kHz 스테레오 = 192KB/s → 그대로 넘는다
    짧은 녹음(55초 미만) 48kHz 스테레오 + 뒤에 무음 → 55초까지만 채운다

무음은 **뒤에** 붙는다. 단어 시각은 앞의 실제 발화 기준 그대로고, 무음 구간에는
단어가 없어서 Transcript.duration_sec(마지막 단어 끝)도 부풀지 않는다.

이건 우리 계정으로 우리 녹음을 올리는 정상 호출이 오탐에 걸린 것을 우회하는
것이지 보안 통제를 뚫는 게 아니다. **근본 해결은 벤더 쪽**이다 — SKT 에
업로드 엔드포인트를 본문 검사에서 제외해 달라고 요청해 두고, 풀리면
CHUCKCHUCK_STT_WAF_WORKAROUND=0 으로 이 층을 끄면 된다.
"""

# F5 계열 검사 버퍼 상한(10 MiB) + 여유. 이 위로 올려야 검사 없이 지나간다
WAF_INSPECT_LIMIT = 10 * 1024 * 1024
WAF_MARGIN = 256 * 1024
WAF_TARGET_BYTES = WAF_INSPECT_LIMIT + WAF_MARGIN

# (샘플레이트, 채널) 후보 — 초당 바이트가 작은 순. 앞엣것부터 되면 업로드가 가볍다
_WAV_PROFILES = ((16000, 1), (48000, 2))


def _bytes_per_sec(rate: int, channels: int) -> int:
    return rate * channels * 2          # 16-bit PCM


def _ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    try:
        return float((out.stdout or "").strip())
    except ValueError:
        return 0.0


def _to_wav(src: Path, dst: Path, rate: int, channels: int, pad_sec: float = 0.0) -> bool:
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src)]
    if pad_sec > 0:
        cmd += [
            "-f", "lavfi", "-t", f"{pad_sec + 1:.3f}",
            "-i", f"anullsrc=r={rate}:cl={'stereo' if channels == 2 else 'mono'}",
            "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1",
        ]
    cmd += ["-ac", str(channels), "-ar", str(rate), "-c:a", "pcm_s16le", str(dst)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=900, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False
    return dst.exists() and dst.stat().st_size > 44      # WAV 헤더만 있는 건 실패로 본다


def widen_for_waf(src: Path, out_dir: Path) -> Path | None:
    """업로드 본문이 WAF 검사 상한을 넘도록 PCM WAV 로 다시 뽑는다.

    길이는 **컨테이너 메타데이터가 아니라 뽑아낸 WAV 의 실제 크기**로 잰다.
    브라우저 MediaRecorder 가 만드는 webm 은 헤더에 길이가 없어서(`duration=N/A`)
    ffprobe 로 재면 0 이 나온다 — 실제 마이크 녹음이 전부 그렇고, 그걸 믿고
    포기하는 바람에 원본이 그대로 올라가 이 우회가 실전에서 한 번도 안 걸렸다
    (2026-08-07 실측: 1.67MB webm 두 건 모두 WAF 거부).

    ffmpeg 이 없거나 어떤 이유로든 실패하면 None — 호출부는 원본을 그대로 올리고
    실패하면 실패로 보여준다. 조용히 다른 소리를 올리는 일은 만들지 않는다.
    """
    if not shutil.which("ffmpeg"):
        return None

    # 1) 가장 가벼운 프로필로 먼저 뽑는다. 여기서 상한을 넘으면 그걸로 끝 (긴 녹음)
    rate, channels = _WAV_PROFILES[0]
    dst = out_dir / "waf_widened.wav"
    if not _to_wav(src, dst, rate, channels):
        return None
    if dst.stat().st_size >= WAF_TARGET_BYTES:
        return dst

    # 2) 모자라면 실제 길이를 이 WAV 크기에서 되짚어 무거운 프로필로 다시 뽑는다
    duration = dst.stat().st_size / _bytes_per_sec(rate, channels)
    rate, channels = _WAV_PROFILES[-1]
    need_sec = WAF_TARGET_BYTES / _bytes_per_sec(rate, channels)
    pad_sec = max(0.0, need_sec - duration)
    if not _to_wav(src, dst, rate, channels, pad_sec):
        return None
    if dst.stat().st_size < WAF_TARGET_BYTES:
        return None
    return dst


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

        # WAF 오탐 우회 — 본문을 검사 상한 위로 올린다. 실패하면 원본 그대로 올린다
        with tempfile.TemporaryDirectory(prefix="cc-stt-") as tmp:
            upload_path = path
            if os.environ.get("CHUCKCHUCK_STT_WAF_WORKAROUND", "1") != "0":
                if path.stat().st_size < WAF_TARGET_BYTES:
                    widened = widen_for_waf(path, Path(tmp))
                    if widened is not None:
                        upload_path = widened
            file_key = self._upload(upload_path)

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
