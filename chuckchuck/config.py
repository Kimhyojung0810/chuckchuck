"""
환경설정(.env)을 읽어 오는 파일입니다.
API 키·모델 이름 같은 설정을 한곳에서 관리하고,
코드 안에 비밀키를 직접 적지 않게 합니다.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def load_dotenv(path: str | Path | None = None) -> Path | None:
    """python-dotenv 없이도 동작하는 최소 .env 로더. 이미 있는 키는 덮지 않음."""
    candidates = []
    if path:
        candidates.append(Path(path))
    else:
        here = Path(__file__).resolve().parent
        candidates.extend([
            Path.cwd() / ".env",
            here.parent / ".env",
        ])
    for p in candidates:
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, val)
        return p
    return None


def _bool(key: str, default: bool = False) -> bool:
    return os.environ.get(key, str(default)).strip().lower() in ("1", "true", "yes")


def _int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _list(key: str, default: list[str]) -> list[str]:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else default
    except json.JSONDecodeError:
        return [s.strip() for s in raw.split(",") if s.strip()]


@dataclass
class Settings:
    app_env: str = "development"
    log_level: str = "INFO"
    mock_external: bool = False

    upstage_api_key: str = ""
    docparse_url: str = "https://api.upstage.ai/v1/document-digitization"
    docparse_async_url: str = "https://api.upstage.ai/v1/document-digitization/async"
    docparse_model: str = "document-parse"
    docparse_mode: str = "auto"
    docparse_ocr: str = "auto"
    docparse_output_formats: list[str] = field(
        default_factory=lambda: ["html", "markdown", "text"]
    )
    docparse_async_threshold_pages: int = 10

    solar_base_url: str = "https://api.upstage.ai/v1"
    solar_model: str = "solar-pro3"

    ax_api_key: str = ""
    ax_base_url: str = "https://awf-gw.adot.ai/v1"
    ax_model: str = "A.X-K1"

    # LLM=Bearer, STT=X-API-Key (같은 awf_ 키라도 헤더가 다름)
    ax_stt_api_key: str = ""
    ax_stt_base_url: str = "https://awf-gw.adot.ai"
    ax_stt_batch_model: str = "A.X_STT_note_batch"
    ax_stt_streaming_model: str = "A.X_STT_note_streaming"

    midm_api_key: str = ""
    midm_base_url: str = "https://api.friendli.ai/dedicated/v1"
    midm_endpoint_id: str = ""

    exaone_api_key: str = ""
    exaone_base_url: str = "https://api.friendli.ai/dedicated/v1"
    exaone_endpoint_id: str = ""

    stt_provider: str = "skt-ax"
    reasoning_backend: str = "solar"

    demo_host: str = "127.0.0.1"
    demo_port: int = 8787

    @classmethod
    def load(cls, dotenv: str | Path | None = None) -> "Settings":
        load_dotenv(dotenv)
        e = os.environ.get
        return cls(
            app_env=e("APP_ENV", "development"),
            log_level=e("LOG_LEVEL", "INFO"),
            mock_external=_bool("MOCK_EXTERNAL_APIS"),

            upstage_api_key=e("UPSTAGE_API_KEY", ""),
            docparse_url=e("UPSTAGE_DOCPARSE_URL", cls.docparse_url),
            docparse_async_url=e("UPSTAGE_DOCPARSE_ASYNC_URL", cls.docparse_async_url),
            docparse_model=e("UPSTAGE_DOCPARSE_MODEL", "document-parse"),
            docparse_mode=e("UPSTAGE_DOCPARSE_MODE", "auto"),
            docparse_ocr=e("UPSTAGE_DOCPARSE_OCR", "auto"),
            docparse_output_formats=_list(
                "UPSTAGE_DOCPARSE_OUTPUT_FORMATS",
                ["html", "markdown", "text"],
            ),
            docparse_async_threshold_pages=_int(
                "UPSTAGE_DOCPARSE_USE_ASYNC_THRESHOLD_PAGES", 10
            ),

            solar_base_url=e("UPSTAGE_SOLAR_BASE_URL", cls.solar_base_url),
            solar_model=e("UPSTAGE_SOLAR_MODEL", "solar-pro3"),

            ax_api_key=e("AX_API_KEY", ""),
            ax_base_url=e("AX_BASE_URL", cls.ax_base_url),
            ax_model=e("AX_MODEL", "A.X-K1"),

            ax_stt_api_key=e("AX_STT_API_KEY", "") or e("AX_API_KEY", ""),
            ax_stt_base_url=e("AX_STT_BASE_URL", cls.ax_stt_base_url),
            ax_stt_batch_model=e("AX_STT_BATCH_MODEL", "A.X_STT_note_batch"),
            ax_stt_streaming_model=e(
                "AX_STT_STREAMING_MODEL", "A.X_STT_note_streaming"
            ),

            midm_api_key=e("MIDM_API_KEY", ""),
            midm_base_url=e("MIDM_BASE_URL", cls.midm_base_url),
            midm_endpoint_id=e("MIDM_ENDPOINT_ID", ""),

            exaone_api_key=e("EXAONE_API_KEY", ""),
            exaone_base_url=e("EXAONE_BASE_URL", cls.exaone_base_url),
            exaone_endpoint_id=e("EXAONE_ENDPOINT_ID", ""),

            stt_provider=e("STT_PROVIDER", "skt-ax"),
            reasoning_backend=e("REASONING_BACKEND", "solar"),

            demo_host=e("DEMO_HOST", "127.0.0.1"),
            demo_port=_int("DEMO_PORT", 8787),
        )

    def masked(self) -> str:
        def m(v: str) -> str:
            if not v:
                return "(없음)"
            return f"{v[:6]}…{v[-4:]}" if len(v) > 12 else "설정됨"

        return "\n".join([
            f"  env            {self.app_env}  mock={self.mock_external}",
            f"  upstage        {m(self.upstage_api_key)}  model={self.solar_model}",
            f"  a.x llm        {m(self.ax_api_key)}  model={self.ax_model}",
            f"  a.x stt        {m(self.ax_stt_api_key)}  model={self.ax_stt_batch_model}",
            f"  kt 믿음         {m(self.midm_api_key)}  ep={self.midm_endpoint_id or '(없음)'}",
            f"  lg 엑사원       {m(self.exaone_api_key)}  ep={self.exaone_endpoint_id or '(없음)'}",
            f"  stt provider   {self.stt_provider}",
            f"  f-06 backend   {self.reasoning_backend}",
        ])


settings = Settings.load()
