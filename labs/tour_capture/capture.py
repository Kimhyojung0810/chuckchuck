"""
투어 녹화 — 부스 덱 한 벌을 **실제 브리지 · 실 API** 로 한 번 태워 응답을 남긴다 (2026-10-11, docs/booth-mobile/tour-schema.md).

    # 녹화 (과금) — 브리지를 8983 에 띄우고 덱마다 한 흐름: 파싱 → 녹음 받아쓰기 → 개념 · 그래프 · 정합 · 흐름 → 속도 · 습관 · 채점 · 리포트
    #               → 질문(5분 코칭) → 질문마다 「잘 답한 답」 · 「엉성한 답」 판정 두 번
    /home/yehschuck/project/chuckchuck/.venv/bin/python labs/tour_capture/capture.py --decks 배달앱별점인플레이션A
    # 녹화본 → 투어 파일 (과금 없음, 브리지 없음)
    /home/yehschuck/project/chuckchuck/.venv/bin/python labs/tour_capture/build.py

브라우저를 띄우지 않고 화면 코드(chuckchuck_bridge.js runPreparePipeline · buildQuestions · judgeOnce)가 보내는 그대로를 HTTP 로 보낸다 —
투어에 필요한 건 응답이지 화면이 아니다. 「정답 보기」 · 「대충 답해 보기」 글은 qa_live.js 원본 함수로 만든다(answers.mjs).

비용을 줄이는 두 겹
- **응답 캐시(내용 해시)** — 요청 본문(세션 id 를 뺀 것, 녹음 · 자료는 바이트의 sha256)의 sha256 이 열쇠다. 같은 덱을 다시 돌리면
  브리지에 안 묻는다. 바뀐 단계부터만 다시 부른다(앞 단계 응답이 같으면 뒤 단계 요청도 같다). --fresh 로 끈다.
- 브리지 자체의 단계 캐시(out/bridge_data/stage_cache) — 파싱 · 받아쓰기 · 개념 · 그래프가 내용 해시로 남는다.

지키는 것: 8799 · 8800 은 띄우지 않는다 · 포트가 물려 있으면 띄우지 않는다 · 끌 때는 우리가 띄운 Popen 하나만(pkill 없음) ·
mock 금지(MOCK_EXTERNAL_APIS=false) · 미리 파싱(DEMO_WARM_DECK_GROUPS) 끔 · LLM 호출은 labs/qa_verify 의 세는 겉감으로 세고 예산에서 끊는다.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "out"
CACHE = OUT / "cache"
BRIDGE_DATA = OUT / "bridge_data"

#: 부스 덱(ppt/decks.json group "booth") 폴더 → 투어 덱 id(= assets/deck-slides/<id>). 녹음 한 벌(A)만 — 투어는 덱마다 한 흐름이다.
BOOTH_DECKS = {
    "배달앱별점인플레이션A": "delivery-rating",
    "급속충전배터리열화A": "battery-fastcharge",
    "미세플라스틱물벼룩번식A": "microplastic-daphnia",
}
PRIMARY = "배달앱별점인플레이션A"
PORTS = (8983, 8984, 8985)          # 이 일에 배정된 포트
FORBIDDEN_PORTS = {8799, 8800}      # 공개 서비스 · 팀 개발 브리지
QA_TRACK = "5"                       # 리허설 화상판 · 부스와 같은 5분 코칭 (rehearsal.js REHEARSAL_QA_TRACK)
#: F-23 상황 key → 계약 문자열 (app.js OCC_BY_KEY 와 같은 값)
OCC_BY_KEY = {
    "school_project": "학교 프로젝트 (교수 대상)",
    "product_launch": "신제품 설명 (대중 대상)",
    "work_report": "업무 보고 (상사 대상)",
    "casual_pr": "동료 간 캐주얼 PR",
}
DEFAULT_SITUATION = "학교 프로젝트 (교수 대상)"
READY_TIMEOUT = 90
TIMEOUTS = {"parse": 300, "transcribe": 300, "questions": 300}
DEFAULT_TIMEOUT = 240


def note(msg: str) -> None:
    print(msg, flush=True)


# ─── 내용 해시 응답 캐시 ─────────────────────────────────────────────────────

def _strip(value):
    """캐시 열쇠에서 뺄 것 — 세션 id(실행마다 다르다)와 큰 바이트(녹음은 sha256 으로 바꿔 넣는다)."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == "session_id":
                continue
            if k == "audio_base64" and isinstance(v, str):
                out[k] = "sha256:" + hashlib.sha256(v.encode("ascii")).hexdigest()
                continue
            out[k] = _strip(v)
        return out
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def cache_key(stage: str, path_template: str, body) -> str:
    raw = json.dumps({"stage": stage, "path": path_template, "body": _strip(body)}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cache_read(key: str) -> dict | None:
    f = CACHE / f"{key}.json"
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None   # 깨진 캐시는 없는 것으로 — 다시 부른다


def cache_write(key: str, entry: dict) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / f"{key}.json").write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")


# ─── 브리지 ────────────────────────────────────────────────────────────────

def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


class Bridge:
    """실 API 브리지 하나 — 우리가 띄우고, 우리 Popen 만 끈다."""

    def __init__(self, port: int, run_dir: Path, budget: int):
        if port in FORBIDDEN_PORTS:
            raise SystemExit(f"{port} 는 공개 · 팀 브리지 자리예요")
        self.port, self.run_dir, self.budget = port, run_dir, budget
        self.base = f"http://127.0.0.1:{port}"
        self.calls = run_dir / "llm_calls.jsonl"
        self.log = run_dir / "bridge.log"
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        if port_busy(self.port):
            raise SystemExit(f"포트 {self.port} 가 이미 물려 있어요 — --port 로 {PORTS} 중 다른 포트를 고르세요 (남의 브리지를 끄지 않는다)")
        env = dict(os.environ)
        env.update({
            "DEMO_HOST": "127.0.0.1", "DEMO_PORT": str(self.port), "DEMO_DEV_ROUTES": "1",
            "MOCK_EXTERNAL_APIS": "false", "HABIT_PROVIDER": env.get("HABIT_PROVIDER", "heuristic"),
            "DEMO_RATE_LIMIT_PER_MIN": "0", "DEMO_WARM_DECK_GROUPS": "", "DEMO_DATA_DIR": str(BRIDGE_DATA),
            "QA_VERIFY_REPO": str(ROOT), "QA_VERIFY_CALLS": str(self.calls), "QA_VERIFY_BUDGET": str(self.budget),
            "PATH": f"{Path.home() / '.local' / 'bin'}:{env.get('PATH', '')}", "PYTHONDONTWRITEBYTECODE": "1",
        })
        self.run_dir.mkdir(parents=True, exist_ok=True)
        fh = self.log.open("w", encoding="utf-8")
        self.proc = subprocess.Popen([sys.executable, str(ROOT / "labs/qa_verify/bridge_wrap.py")], cwd=str(ROOT), env=env,
                                     stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
        t0 = time.time()
        while time.time() - t0 < READY_TIMEOUT:
            if self.proc.poll() is not None:
                raise SystemExit(f"브리지가 바로 죽었어요 (rc={self.proc.returncode}) — {self.log}")
            try:
                with urllib.request.urlopen(f"{self.base}/index.html", timeout=3) as r:
                    if r.status == 200:
                        note(f"   브리지 준비 {time.time() - t0:.0f}s · pid {self.proc.pid} · {self.base}")
                        return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(1)
        self.stop()
        raise SystemExit(f"브리지가 {READY_TIMEOUT}초 안에 안 떴어요 — {self.log}")

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        self.proc.terminate()   # 우리가 띄운 프로세스 하나 — 이름 패턴으로 찾지 않는다
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        note(f"   브리지 pid {self.proc.pid} 를 껐어요")

    def llm_calls(self) -> int:
        if not self.calls.exists():
            return 0
        return sum(1 for line in self.calls.read_text(encoding="utf-8").splitlines() if line.strip())


# ─── 기록하는 HTTP ──────────────────────────────────────────────────────────

class Recorder:
    """단계마다 응답을 raw/NN_<단계>.json 으로 남기고, calls.jsonl 에 (단계 · 캐시 적중 · 상태 · 초) 를 적는다."""

    def __init__(self, base: str | None, raw_dir: Path, calls: Path, *, use_cache: bool):
        self.base, self.raw_dir, self.calls, self.use_cache = base, raw_dir, calls, use_cache
        self.n = 0
        self.http_calls = 0
        raw_dir.mkdir(parents=True, exist_ok=True)

    def _send(self, path: str, data: bytes, ctype: str, timeout: int) -> tuple[int, dict]:
        if self.base is None:
            raise RuntimeError("캐시에 없는 요청이에요 — 브리지 없이(--offline) 는 녹화한 응답만 쓸 수 있어요")
        req = urllib.request.Request(self.base + path, data=data, method="POST", headers={"Content-Type": ctype})
        self.http_calls += 1
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except json.JSONDecodeError:
                return e.code, {"error": f"http_{e.code}"}

    def call(self, stage: str, path: str, body: dict | None = None, *, path_template: str | None = None,
             multipart: tuple[str, bytes] | None = None) -> dict:
        key_body = body if multipart is None else {"file_name": multipart[0], "sha256": hashlib.sha256(multipart[1]).hexdigest()}
        key = cache_key(stage, path_template or path, key_body)
        hit = cache_read(key) if self.use_cache else None
        t0 = time.time()
        if hit is not None:
            status, resp = hit["status"], hit["body"]
        else:
            if multipart is not None:
                name, blob = multipart
                boundary = "tourcap-" + hashlib.sha256(blob).hexdigest()[:16]
                data = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{name}\"\r\n"
                        "Content-Type: application/octet-stream\r\n\r\n").encode() + blob + f"\r\n--{boundary}--\r\n".encode()
                status, resp = self._send(path, data, f"multipart/form-data; boundary={boundary}", TIMEOUTS.get(stage, DEFAULT_TIMEOUT))
            else:
                data = json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
                status, resp = self._send(path, data, "application/json", TIMEOUTS.get(stage, DEFAULT_TIMEOUT))
            if status == 200 and not (isinstance(resp, dict) and resp.get("error")):
                cache_write(key, {"stage": stage, "status": status, "body": resp})
        sec = round(time.time() - t0, 2)
        self.n += 1
        (self.raw_dir / f"{self.n:02d}_{stage}.json").write_text(json.dumps(resp, ensure_ascii=False, indent=1), encoding="utf-8")
        with self.calls.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"stage": stage, "cached": hit is not None, "status": status, "sec": sec}, ensure_ascii=False) + "\n")
        note(f"   {stage:<22} {'캐시' if hit is not None else 'API '} {status} {sec:6.1f}s")
        if status != 200 or (isinstance(resp, dict) and resp.get("error")):
            raise RuntimeError(f"{stage} 실패 HTTP {status}: {str(resp)[:300]}")
        return resp


# ─── 한 덱 흐름 ─────────────────────────────────────────────────────────────

def slim(t: dict | None) -> dict | None:
    """chuckchuck_bridge.js slimTranscript 와 같은 모양."""
    if not isinstance(t, dict):
        return t
    return {
        "full_text": t.get("full_text") or "", "provider": t.get("provider") or "", "duration_sec": t.get("duration_sec") or 0,
        "words": [{"text": w.get("text"), "start_sec": w.get("start_sec"), "end_sec": w.get("end_sec")} for w in t.get("words") or []],
        "by_slide": [{"slide_no": s.get("slide_no"), "visit": s.get("visit") or 1, "start_sec": s.get("start_sec"),
                      "end_sec": s.get("end_sec"), "text": s.get("text") or ""} for s in t.get("by_slide") or []],
    }


def ppt_root() -> Path:
    """덱 원본(PPTX · 녹음)은 git 에 없다 — 이 작업 폴더에 없으면 주 작업 폴더(git common dir 의 부모)의 ppt/ 를 읽는다."""
    here = ROOT / "ppt"
    if any(here.glob("*/*.pptx")):
        return here
    common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout.strip()
    return Path(common).parent / "ppt"


def deck_files(key: str, root: Path) -> tuple[Path, Path]:
    folder = root / key
    pptx = sorted(folder.glob("*.pptx")) + sorted(folder.glob("*.pdf"))
    audio = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".m4a", ".mp3", ".wav"))
    if not pptx or not audio:
        raise SystemExit(f"{folder} 에 자료(.pptx) 와 녹음이 다 있어야 해요")
    return pptx[0], audio[0]


def answer_texts(questions: list[dict]) -> dict[str, dict]:
    """qa_live.js 원본으로 「정답 보기」 · 「대충 답해 보기」 글 (answers.mjs)."""
    res = subprocess.run(["node", str(HERE / "answers.mjs")], input=json.dumps(questions, ensure_ascii=False),
                         capture_output=True, text=True, cwd=str(ROOT), check=True)
    return {row["id"]: row for row in json.loads(res.stdout)}


def judge_body(sid: str, q: dict, answer: str) -> dict:
    """chuckchuck_bridge.js judgeOnce 의 첫 답 — 되묻기 전 한 번."""
    return {"session_id": sid, "question_id": q.get("id"), "answer": answer, "history": [], "question": q,
            "give_up": False, "prior_answers": [], "hints_shown": []}


def run_deck(rec: Recorder, key: str, root: Path, max_questions: int) -> dict:
    pptx, audio = deck_files(key, root)
    doc = rec.call("parse", "/api/v1/parse", multipart=(pptx.name, pptx.read_bytes()))
    sid = doc.get("session_id") or "flat"
    sug = rec.call("suggest_context", "/api/v1/suggest-context", {"slide_doc": doc})
    situation = OCC_BY_KEY.get(str(sug.get("situation") or ""), "") or str(sug.get("situation") or "") or DEFAULT_SITUATION
    audio_b64 = base64.b64encode(audio.read_bytes()).decode("ascii")
    tr = rec.call("transcribe", "/api/v1/transcribe", {
        "session_id": sid, "marks": [], "audio_base64": audio_b64, "ext": audio.suffix.lower(), "reuse": False,
        "file_name": audio.name, "slidedoc": doc, "marks_source": "even"})
    dur_min = max(1, math.ceil(float(tr.get("duration_sec") or 60) / 60))
    context = {"situation": situation, "audience": "", "duration_min": dur_min}
    st = slim(tr)
    concepts = rec.call("concepts", "/api/v1/concepts", {"session_id": sid, "slide_doc": doc, "context": context, "transcript": st})
    graph = rec.call("graph", "/api/v1/graph", {"session_id": sid, "concept_doc": concepts, "slide_doc": doc, "context": context})
    align = rec.call("alignment", "/api/v1/alignment", {"session_id": sid, "graph": graph, "transcript": st, "context": context})
    flow = rec.call("flow", "/api/v1/flow", {"session_id": sid, "graph": graph, "alignment": align})
    pace = rec.call("pace", "/api/v1/pace", {"session_id": sid, "transcript": st, "context": context,
                                             "concept_doc": concepts, "alignment": align})
    habits = rec.call("habits", "/api/v1/habits", {"session_id": sid, "transcript": st})
    rubric = rec.call("rubric", "/api/v1/rubric", {"session_id": sid, "situation": situation, "context": context, "slides": doc,
                                                   "concepts": concepts, "graph": graph, "transcript": st, "alignment": align,
                                                   "flow": flow, "pace": pace, "habits": habits})
    report = rec.call("report", "/api/v1/report", {"session_id": sid, "pace": pace, "habits": habits, "rubric": rubric,
                                                   "alignment": align, "context": context})
    # 판정이 세션 아티팩트(그래프 · 정합 · 발화)를 근거로 쓴다 — 화면처럼 먼저 등록한다 (과금 없음 · 캐시하지 않는다: 브리지 메모리에 올려야 한다)
    rec.use_cache, keep = False, rec.use_cache
    rec.call("session_artifacts", "/api/v1/session/artifacts", {"session_id": sid, "graph": graph, "alignment": align, "flow": flow,
                                                                "transcript": st, "context": context})
    rec.use_cache = keep
    qdoc = rec.call("questions", "/api/v1/questions", {"session_id": sid, "graph": graph, "alignment": align, "flow": flow,
                                                       "transcript": st, "context": context, "track": QA_TRACK,
                                                       "prefetch": False, "fresh": False})
    questions = list(qdoc.get("questions") or [])[:max_questions]
    texts = answer_texts(questions)
    jpath = f"/api/v1/sessions/{sid}/qa/judge"
    judged = []
    for q in questions:
        t = texts.get(q.get("id"), {})
        model = t.get("model") or ""
        if not model:   # 함정 · 골자를 숨긴 질문 — 화면처럼 서버에 정답을 물어 온다 (liveFetchReveal)
            rv = rec.call("reveal", jpath, {"session_id": sid, "question_id": q.get("id"), "question": q, "answer": "", "reveal": True},
                          path_template="/api/v1/sessions/{sid}/qa/judge")
            model = str(rv.get("answer_gist") or "")
        row = {"question": q, "good_text": model, "rough_text": t.get("weak") or "", "good": None, "rough": None}
        if model:
            row["good"] = rec.call("judge_good", jpath, judge_body(sid, q, model), path_template="/api/v1/sessions/{sid}/qa/judge")
        if row["rough_text"]:
            row["rough"] = rec.call("judge_rough", jpath, judge_body(sid, q, row["rough_text"]),
                                    path_template="/api/v1/sessions/{sid}/qa/judge")
        judged.append(row)
    return {"deck_key": key, "tour_deck_id": BOOTH_DECKS[key], "situation": situation, "context": context,
            "pptx": pptx.name, "audio": audio.name, "slide_doc": doc, "transcript": tr, "concepts": concepts, "graph": graph,
            "alignment": align, "flow": flow, "pace": pace, "habits": habits, "rubric": rubric, "report": report,
            "questions_doc": {k: v for k, v in qdoc.items() if k != "questions"}, "judged": judged}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="투어 녹화 — 부스 덱을 실 API 브리지로 한 번 태워 응답을 남긴다")
    ap.add_argument("--decks", nargs="+", default=[PRIMARY], choices=sorted(BOOTH_DECKS), help="ppt/ 폴더 이름 (부스 A 덱)")
    ap.add_argument("--port", type=int, default=PORTS[0])
    ap.add_argument("--budget", type=int, default=120, help="LLM 논리 호출 상한 (이 실행 전체) — 넘으면 그 요청이 실패한다")
    ap.add_argument("--max-questions", type=int, default=5)
    ap.add_argument("--fresh", action="store_true", help="응답 캐시를 안 쓴다 (브리지 단계 캐시는 그대로)")
    ap.add_argument("--offline", action="store_true", help="브리지를 안 띄우고 캐시에 있는 응답만으로 녹화본을 다시 만든다 (과금 0)")
    args = ap.parse_args(argv)
    if args.port not in PORTS:
        raise SystemExit(f"이 녹화는 배정된 포트 {PORTS} 만 써요")
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    run_dir = OUT / "runs" / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    root = ppt_root()
    bridge = None if args.offline else Bridge(args.port, run_dir, args.budget)
    summary = {"stamp": stamp, "port": args.port, "decks": {}, "ppt_root": "ppt/"}
    try:
        if bridge:
            bridge.start()
        for key in args.decks:
            note(f"── {key}")
            rec = Recorder(bridge.base if bridge else None, run_dir / key / "raw", run_dir / key / "calls.jsonl",
                           use_cache=not args.fresh)
            t0 = time.time()
            try:
                bundle = run_deck(rec, key, root, args.max_questions)
            except RuntimeError as e:
                note(f"   ✗ {e}")
                summary["decks"][key] = {"ok": False, "error": str(e)[:300], "http_calls": rec.http_calls}
                continue
            bundle["recorded_at"] = datetime.now().strftime("%Y-%m-%d")
            dest = OUT / "recordings" / f"{BOOTH_DECKS[key]}.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")
            summary["decks"][key] = {"ok": True, "http_calls": rec.http_calls, "steps": rec.n, "sec": round(time.time() - t0, 1),
                                     "recording": str(dest.relative_to(ROOT))}
            note(f"   → {dest.relative_to(ROOT)} (브리지 호출 {rec.http_calls} · 단계 {rec.n})")
    finally:
        if bridge:
            summary["llm_calls"] = bridge.llm_calls()
            bridge.stop()
        (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        note(f"요약 {run_dir.relative_to(ROOT)}/summary.json · LLM 호출 {summary.get('llm_calls', 0)}")
    return 0 if all(d.get("ok") for d in summary["decks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
