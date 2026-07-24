"""
실API로 F-01→F-05→F-06을 짧게 태워 보는 스모크 테스트입니다.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chuckchuck.config import load_dotenv

load_dotenv()

from chuckchuck import Context, extract_concepts, parse_document, transcribe
from chuckchuck.contracts import SlideMark
from chuckchuck.providers.llm_impl import SolarLLM, AxLLM
from chuckchuck.providers.stt_impl import AxSTT


def section(title: str):
    print(f"\n{'='*60}\n{title}\n{'='*60}")


def ok(msg: str):
    print(f"  ✅ {msg}")


def fail(msg: str):
    print(f"  ❌ {msg}")


def make_speech_wav(path: Path) -> Path:
    """macOS say 로 짧은 한국어 음성 생성 (없으면 톤 wav)."""
    aiff = path.with_suffix(".aiff")
    try:
        subprocess.run(
            ["say", "-v", "Yuna", "-o", str(aiff), "안녕하세요. 오늘 발표 주제는 자기지도 학습입니다."],
            check=True,
            capture_output=True,
            timeout=30,
        )
        # afconvert to wav 16k mono
        subprocess.run(
            ["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(aiff), str(path)],
            check=True,
            capture_output=True,
            timeout=30,
        )
        aiff.unlink(missing_ok=True)
        return path
    except Exception as e:
        print(f"  (say 실패 → 톤 wav 사용: {e})")
        import math, struct
        with wave.open(str(path), "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            for i in range(16000 * 2):
                val = int(4000 * math.sin(2 * math.pi * 220 * i / 16000))
                w.writeframes(struct.pack("<h", val))
        return path


def main():
    results = []

    # 1) unit
    section("0. 유닛 테스트")
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    print(r.stdout or r.stderr)
    results.append(("unit", r.returncode == 0))

    # 2) Solar
    section("1. Upstage Solar (F-06 LLM)")
    try:
        text = SolarLLM().complete(
            system="JSON만 출력.",
            user='{"ping": true} 형태로만 답해.',
            max_tokens=32,
        )
        ok(f"응답: {text.strip()[:80]}")
        results.append(("solar", True))
    except Exception as e:
        fail(str(e))
        results.append(("solar", False))

    # 3) A.X LLM
    section("2. SKT A.X LLM")
    try:
        text = AxLLM().complete(
            system="한 줄로만.",
            user="ping에 pong이라고만.",
            max_tokens=16,
        )
        ok(f"응답: {text.strip()[:80]}")
        results.append(("ax-llm", True))
    except Exception as e:
        fail(str(e))
        results.append(("ax-llm", False))

    # 4) Document Parse
    section("3. Upstage Document Parse (F-01)")
    pdf = Path("/Users/gimhyojeong/Downloads/팀 연구학점제 관심 주제 발표.pdf")
    if not pdf.exists():
        pdf = Path("/Users/gimhyojeong/Downloads/final_exam_sample_questions.pdf")
    try:
        doc = parse_document(pdf)
        ok(f"{pdf.name} → {doc.total_slides}장")
        for s in doc.slides[:3]:
            print(f"     [{s.slide_no}] {s.title[:40] or '(제목없음)'} | chars={len(s.raw_text)}")
        results.append(("docparse", True))
        slide_doc = doc
    except Exception as e:
        fail(str(e))
        results.append(("docparse", False))
        slide_doc = None

    # 5) F-06 concepts with Solar (use fixture if parse failed / to save pages use first 3 slides)
    section("4. F-06 개념 추출 (Solar)")
    try:
        if slide_doc is None:
            from chuckchuck.contracts import SlideDoc
            slide_doc = SlideDoc.from_dict(
                json.loads((ROOT / "fixtures" / "sample_slidedoc.json").read_text())
            )
            print("  (fixture SlideDoc 사용)")
        else:
            # 비용/시간 절약: 앞 3장만
            slide_doc.slides = slide_doc.slides[:3]
            slide_doc.total_slides = len(slide_doc.slides)

        concepts = extract_concepts(
            slide_doc,
            Context(situation="학회·수업 발표", audience="교수님", duration_min=10),
            llm="solar",
        )
        ok(f"model={concepts.model}, slides={len(concepts.slides)}")
        for s in concepts.slides[:3]:
            print(f"     [{s.slide_no}] topic={s.topic[:50]!r}")
            print(f"          concepts={s.concepts[:2]}")
        results.append(("f06", True))
    except Exception as e:
        fail(str(e))
        results.append(("f06", False))

    # 6) A.X STT
    section("5. SKT A.X STT (F-05)")
    wav = Path(tempfile.gettempdir()) / "chuckchuck_stt_test.wav"
    make_speech_wav(wav)
    ok(f"오디오: {wav} ({wav.stat().st_size} bytes)")
    try:
        engine = AxSTT()
        full, words = engine.transcribe(wav)
        ok(f"text={full[:100]!r}")
        ok(f"words={len(words)}")
        if words:
            print(f"     first word: {words[0].text!r} @ {words[0].start_sec}-{words[0].end_sec}")
        results.append(("stt", bool(full or words)))
    except Exception as e:
        fail(str(e))
        results.append(("stt", False))
        full, words = "", []

    # 7) F-05 split pipeline
    section("6. F-05 STT + 슬라이드 분할")
    try:
        marks = [
            SlideMark(1, 0.0, 3.0, 1),
            SlideMark(2, 3.0, 30.0, 1),
        ]
        t = transcribe(wav, marks, provider="skt-ax")
        ok(f"provider={t.provider}, duration={t.duration_sec:.2f}s")
        for s in t.by_slide:
            print(f"     slide {s.slide_no}: {s.text[:60]!r}")
        results.append(("f05-pipeline", True))
    except Exception as e:
        fail(str(e))
        results.append(("f05-pipeline", False))

    # summary
    section("결과 요약")
    all_ok = True
    for name, passed in results:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
        all_ok = all_ok and passed
    print()
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
