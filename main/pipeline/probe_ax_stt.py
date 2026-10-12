"""
A.X STT가 잘 붙는지 확인하는 점검용 스크립트입니다.
키·업로드·전사 흐름을 빠르게 테스트할 때 씁니다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .config import settings
from .providers.stt_impl import AxSTT

SEP = "─" * 64
TIME_KEYS = {
    "start", "end", "start_time", "end_time",
    "start_at", "end_at", "begin", "startTime", "endTime",
}


def _flatten_words(body: dict) -> tuple[list, str]:
    if isinstance(body.get("words"), list) and body["words"]:
        return body["words"], "words[]"

    for utt in body.get("utterances") or []:
        if isinstance(utt.get("words"), list) and utt["words"]:
            return utt["words"], "utterances[].words[]"

    if body.get("utterances"):
        return body["utterances"], "utterances[] (발화 단위)"

    results = body.get("results") or {}
    utts = results.get("utterances") or []
    if utts:
        if isinstance(utts[0].get("words"), list) and utts[0]["words"]:
            return utts[0]["words"], "results.utterances[].words[]"
        return utts, "results.utterances[] (발화 단위)"

    return [], ""


def inspect(body: dict) -> str:
    print(f"\n{SEP}\n[2] 응답 구조\n{SEP}")
    print(f"  최상위 키: {list(body)}")
    print(f"  utterance_count: {body.get('utterance_count')}")
    print(f"  audio_duration: {body.get('audio_duration')}")
    print(f"  transcript_duration: {body.get('transcript_duration')}")

    word_like, where = _flatten_words(body)
    print(f"\n{SEP}\n[3] 판정 — F-17(말 속도) 가능 여부\n{SEP}")

    verdict = "none"
    if not word_like:
        print("  ✗ 시각 정보를 못 찾았습니다.")
        verdict = "none"
    else:
        sample = word_like[0]
        print(f"  위치: {where}")
        print(f"  샘플: {json.dumps(sample, ensure_ascii=False)[:220]}")
        keys = set(sample) if isinstance(sample, dict) else set()
        has_time = bool(keys & TIME_KEYS)
        token = ""
        if isinstance(sample, dict):
            token = sample.get("word") or sample.get("text") or sample.get("msg") or ""
        is_word = len(str(token).split()) <= 2
        in_words_path = "words" in where

        print()
        if has_time and is_word and in_words_path:
            print("  ✓ 단어별 timestamp 있음 → F-17 그대로 진행 가능")
            print("    AxSTT.SUPPORTS_WORD_TIMESTAMPS = True 유지")
            verdict = "word"
        elif has_time:
            print("  △ 시각은 있으나 문장/발화 단위에 가깝습니다.")
            print("    F-17 은 문장 단위 근사로 낮추고 완성 기준을 재합의하세요.")
            verdict = "utterance"
        else:
            print("  ✗ 시각 정보가 없습니다. F-17 을 만들 수 없습니다.")
            verdict = "none"

    print(f"\n{SEP}\n[4] 원본 응답 (앞 2500자)\n{SEP}")
    print(json.dumps(body, ensure_ascii=False, indent=2)[:2500])
    return verdict


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    audio = Path(sys.argv[1])
    if not audio.exists():
        print(f"파일이 없습니다: {audio}")
        return 1
    if not settings.ax_stt_api_key:
        print("AX_STT_API_KEY 가 비어 있습니다. .env 를 확인하세요.")
        return 1

    print(f"\n{SEP}\n[1] A.X STT batch 호출\n{SEP}")
    print(f"  base   {settings.ax_stt_base_url}")
    print(f"  model  {settings.ax_stt_batch_model}")
    print(f"  auth   X-API-Key {settings.ax_stt_api_key[:8]}…")
    print("  flow   upload-token → upload → transcript")
    print(f"  file   {audio} ({audio.stat().st_size} bytes)")

    engine = AxSTT(
        api_key=settings.ax_stt_api_key,
        base_url=settings.ax_stt_base_url,
        model=settings.ax_stt_batch_model,
    )

    # 내부 호출을 재현하면서 원본 JSON 도 받기 위해 직접 단계 실행
    file_key = engine._upload(audio)
    print(f"  file_key={file_key}")

    import uuid
    import requests

    payload = {
        "message_id": f"probe-{uuid.uuid4().hex[:10]}",
        "speech_model": engine.model,
        "audio_file_key": file_key,
    }
    res = requests.post(
        f"{engine.base_url}/v1/stt/transcript",
        headers={**engine._headers(), "Content-Type": "application/json"},
        json=payload,
        timeout=engine.timeout,
    )
    print(f"  transcript HTTP {res.status_code}")
    if res.status_code != 200:
        print(res.text[:400])
        return 1

    body = res.json()
    full, words = AxSTT._parse(body)
    print(f"  parsed text={full[:120]!r}")
    print(f"  parsed words={len(words)}")
    if words:
        w = words[0]
        print(f"  first={w.text!r} {w.start_sec}-{w.end_sec}")

    verdict = inspect(body)
    print(f"\n{SEP}\n결과: verdict={verdict}\n{SEP}")
    return 0 if verdict in {"word", "utterance"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
