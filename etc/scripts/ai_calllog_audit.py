#!/usr/bin/env python3
"""
국내 AI API 호출 로그 감사 — 제출 가이드 v1.0 항목 대조표 · 집계 · 비밀/개인정보 흔적 검사 (2026-10-17).

    python etc/scripts/ai_calllog_audit.py --dir /data/models/_runs/qa-ensemble/calllog
    python etc/scripts/ai_calllog_audit.py --dir A --dir B --zip out.zip --out audit.md      # 로그 폴더 여럿 + 내보낸 zip
    python etc/scripts/ai_calllog_audit.py --json > audit.json                                # 기계용
    python etc/scripts/ai_calllog_audit.py --prices prices.json                               # 추정 단가(출처 명시)로 대략 비용

- 레코드를 **내보내기와 같은 눈**(ai_calllog_export.enrich — 빈 모델 칸을 같은 실행/단계 표로 채운 사본)으로 본다.
  원본에서 빈 칸이었다가 채워진 수도 따로 센다.
- 대조 항목: 요청 시각(KST +09:00) · 엔드포인트(도메인) · 요청 모델 · 요청 내용 · 응답 시각(KST) · 응답 ID · 응답 모델명 · 답변 ·
  토큰 사용량 · ok/상태 · attempt. 셀은 ✓(전부 있음) · n/a(그 API 가 주지 않는 항목 — 까닭은 summary.*_note) · ✗k/n(빠짐).
  실패 레코드는 응답 칸을 「실패」로 따로 센다(오류 본문이 곧 응답).
- 집계: 모델별 · 기능별 호출 수 · 성공 · 429 · 그 밖 오류 · 토큰 합 · 지연 p50/p95(요청-응답 시각 차) · 실행(run) 수와 대표 실행.
- 비용: 단가를 모르면 토큰 합만. `--prices` JSON({모델: {input_per_1m, output_per_1m, currency, source}})을 주면 그 가정으로 계산하고 출처를 같이 찍는다.
- 흔적 검사(값은 절대 찍지 않고 건수만): .env 실제 키 값 · `Bearer …` · Authorization/X-API-Key 낱말 · 키 모양 · 업로드 토큰 · 전화/이메일/주민번호.
  로그 원본과 zip 을 따로 센다. zip 은 전부 0 이어야 한다.
종료 코드: zip 에 비밀 흔적이 있거나 zip 레코드에 필수 항목 ✗ 가 있으면 1.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "main")]

from pipeline import _ai_calllog as AC  # noqa: E402


def _export_mod():
    spec = importlib.util.spec_from_file_location("ai_calllog_export", Path(__file__).with_name("ai_calllog_export.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


EX = _export_mod()

ITEMS = (
    ("req_time", "요청 시각"), ("endpoint", "엔드포인트"), ("req_model", "요청 모델"), ("req_body", "요청 내용"),
    ("resp_time", "응답 시각"), ("resp_id", "응답 ID"), ("resp_model", "응답 모델명"), ("answer", "답변"),
    ("usage", "토큰 사용량"), ("status", "ok/상태"), ("attempt", "attempt"),
)
#: 가이드 필수 9항목 (ok/상태 · attempt 는 우리가 더한 칸)
REQUIRED = ("req_time", "endpoint", "req_model", "req_body", "resp_time", "resp_id", "resp_model", "answer", "usage")
RESP_ITEMS = ("resp_id", "resp_model", "answer", "usage")
_KST = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+09:00$")
#: API 가 주지 않는 응답 항목 (종류별) — n/a 로 표시하고 까닭은 summary 의 *_note
_NA = {
    "embedding": {"resp_id"},
    "docparse": {"resp_id"},
    "docparse_async": {"resp_model", "usage"},
    "docparse_poll": set(),
    "stt_token": {"resp_id", "resp_model", "usage"},
    "stt_upload": {"resp_model", "usage"},
    "stt_transcript": {"resp_model"},
    "stt_live": {"resp_model"},
}
KEY_SHAPE = re.compile(r"\b(?:up|awf|flp|sk|pk)_[A-Za-z0-9]{16,}\b")
BEARER = re.compile(r"Bearer\s+[A-Za-z0-9._\-]{8,}")
PII = {
    "주민번호": EX._PATTERNS[2],
    "휴대전화": EX._PATTERNS[3],
    "유선전화": EX._PATTERNS[4],
    "이메일": EX._PATTERNS[5],
}


# ─── 레코드 하나 대조 ──────────────────────────────────────────────────────────────────────

def _messages_ok(body) -> bool:
    msgs = body.get("messages") if isinstance(body, dict) else None
    return bool(isinstance(msgs, list) and msgs and all(
        isinstance(m, dict) and m.get("role") and (m.get("content") not in (None, "")) for m in msgs))


def _req_body_ok(kind: str, method: str, body) -> bool:
    b = body if isinstance(body, dict) else {}
    if kind == "chat":
        return _messages_ok(b)
    if kind == "embedding":
        return bool(b.get("input"))
    if kind in ("docparse", "docparse_async"):
        return bool(isinstance(b.get("document"), dict) and b["document"].get("sha256") and (b.get("form") or {}).get("model"))
    if kind in ("docparse_poll", "stt_token"):
        return method == "GET"          # 요청 내용은 주소(요청 ID · fileSize)뿐
    if kind == "stt_upload":
        return bool((b.get("audio") or b.get("file") or {}).get("sha256"))
    if kind == "stt_transcript":
        return bool(b.get("audio_file_key") and b.get("speech_model"))
    if kind == "stt_live":
        return bool(b.get("create") and (b.get("audio") or {}).get("sha256"))
    return body is not None


def _usage_ok(kind: str, s: dict) -> bool:
    u = s.get("usage")
    if not isinstance(u, dict):
        return False
    if kind in ("chat", "embedding"):
        return any(isinstance(u.get(k), int) for k in ("total_tokens", "prompt_tokens"))
    return bool(u)


def check(r: dict) -> dict[str, str]:
    """항목 → '✓' · 'n/a' · '✗' · '실패'(실패 레코드의 응답 칸)."""
    rq, rp = r["request"], r["response"]
    kind = AC.kind_of(rq.get("method") or "", rq.get("endpoint") or "")
    s = rp.get("summary") or AC.summarize(kind, rq.get("body"), rp.get("status"), rp.get("body"))
    sp = urlsplit(rq.get("endpoint") or "")
    out = {
        "req_time": "✓" if _KST.match(str(rq.get("time_kst") or "")) else "✗",
        "endpoint": "✓" if sp.scheme in ("https", "wss") and sp.hostname and "." in sp.hostname else "✗",
        "req_model": "✓" if rq.get("model") else "✗",
        "req_body": "✓" if _req_body_ok(kind, rq.get("method") or "", rq.get("body")) else "✗",
        "resp_time": "✓" if _KST.match(str(rp.get("time_kst") or "")) and str(rp.get("time_kst")) >= str(rq.get("time_kst")) else "✗",
        "status": "✓" if ("status" in rp or "error" in rp) and isinstance(r.get("ok"), bool) else "✗",
        "attempt": "✓" if isinstance(r.get("attempt"), int) and r["attempt"] >= 1 else "✗",
    }
    if not r.get("ok"):
        for k in RESP_ITEMS:
            out[k] = "실패"
        return out
    na = _NA.get(kind, set())
    body = rp.get("body") if isinstance(rp.get("body"), dict) else {}
    got = {
        "resp_id": bool(s.get("id")),
        "resp_model": bool(s.get("model") if kind not in ("chat", "embedding", "docparse") else body.get("model")),
        "answer": bool(s.get("answer_from")),
        "usage": _usage_ok(kind, s),
    }
    for k in RESP_ITEMS:
        out[k] = "✓" if got[k] else ("n/a" if k in na else "✗")
    return out


# ─── 집계 ────────────────────────────────────────────────────────────────────────────────

def _ts(v: str) -> datetime | None:
    try:
        return datetime.fromisoformat(v)
    except (TypeError, ValueError):
        return None


def latency(r: dict) -> float | None:
    a, b = _ts(r["request"].get("time_kst")), _ts(r["response"].get("time_kst"))
    return (b - a).total_seconds() if a and b else None


def pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    i = min(len(xs) - 1, max(0, round(p / 100 * (len(xs) - 1))))
    return round(xs[i], 2)


def outcome(r: dict) -> str:
    rp = r["response"]
    st = rp.get("status")
    if r.get("ok"):
        return "ok"
    if st == 429:
        return "429"
    if (rp.get("summary") or {}).get("answer_empty"):
        return "빈답"
    if isinstance(st, int) and st >= 500:
        return "5xx"
    if isinstance(st, int) and st >= 400:
        return "4xx"
    if st is None:
        return "연결오류"
    return "그밖"


def tokens(r: dict) -> dict[str, int]:
    u = (r["response"].get("body") or {}).get("usage") if isinstance(r["response"].get("body"), dict) else None
    out = {"prompt": 0, "completion": 0, "total": 0, "pages": 0}
    if isinstance(u, dict):
        for k, dst in (("prompt_tokens", "prompt"), ("completion_tokens", "completion"), ("total_tokens", "total"),
                       ("pages", "pages")):
            if isinstance(u.get(k), int):
                out[dst] = u[k]
        if not out["total"] and (out["prompt"] or out["completion"]):
            out["total"] = out["prompt"] + out["completion"]
    s = r["response"].get("summary") or {}
    su = s.get("usage") if isinstance(s.get("usage"), dict) else {}
    out["audio_sec"] = float(su.get("audio_duration_sec") or (su.get("audio_duration_ms") or 0) / 1000 or 0)
    return out


def _bucket() -> dict:
    return {"calls": 0, "outcomes": Counter(), "prompt": 0, "completion": 0, "total": 0, "pages": 0, "audio_sec": 0.0,
            "lat": [], "retries": 0, "first": None, "last": None}


def _add(b: dict, r: dict) -> None:
    b["calls"] += 1
    b["outcomes"][outcome(r)] += 1
    for k, v in tokens(r).items():
        b[k] += v
    lt = latency(r)
    if lt is not None:
        b["lat"].append(lt)
    if (r.get("attempt") or 1) > 1:
        b["retries"] += 1
    t = r["request"].get("time_kst")
    b["first"] = min(filter(None, [b["first"], t])) if t else b["first"]
    b["last"] = max(filter(None, [b["last"], t])) if t else b["last"]


def _finish(b: dict) -> dict:
    lat = b.pop("lat")
    o = b.pop("outcomes")
    return {**b, "ok": o.get("ok", 0), "r429": o.get("429", 0),
            "errors": sum(v for k, v in o.items() if k not in ("ok", "429")), "outcomes": dict(o),
            "p50": pct(lat, 50), "p95": pct(lat, 95), "audio_sec": round(b["audio_sec"], 1)}


def model_key(r: dict) -> str:
    m = r["request"].get("model") or "(없음)"
    lab = r["request"].get("model_label")
    return f"{m} — {lab}" if lab and lab != m else m


# ─── 흔적 검사 ────────────────────────────────────────────────────────────────────────────

def scan_text(text: str, keys: list[str]) -> dict[str, int]:
    """값은 돌려주지 않는다 — 건수만."""
    out = {
        "env_key_values": sum(text.count(k) for k in keys),
        "bearer": len(BEARER.findall(text)),
        "authorization_word": text.count("Authorization"),
        "x_api_key_word": text.count("X-API-Key"),
        "key_shape": len(KEY_SHAPE.findall(text)),
        "upload_token_value": len(re.findall(r'"upload_token":\s*"(?!\*\*\*")[^"]+"', text))
        + len(re.findall(r"/v1/stt/upload/(?!\*\*\*)[^\"/?#\s]+", text)),
    }
    for name, pat in PII.items():
        out[f"pii_{name}"] = len(pat.findall(text))
    return out


def _sum(a: dict, b: dict) -> dict:
    return {k: a.get(k, 0) + b.get(k, 0) for k in set(a) | set(b)}


def scan_dirs(dirs: list[Path], keys: list[str]) -> dict[str, int]:
    tot: dict[str, int] = {}
    for d in dirs:
        for p in sorted(d.rglob("*.jsonl")) if d.is_dir() else ():
            tot = _sum(tot, scan_text(p.read_text(encoding="utf-8", errors="replace"), keys))
    return tot


SECRET_FIELDS = ("env_key_values", "bearer", "authorization_word", "x_api_key_word", "key_shape", "upload_token_value")


def audit_zip(path: Path, keys: list[str], features: dict[str, str], since: str) -> dict:
    out: dict = {"path": str(path), "files": [], "scan": {}, "missing_files": [], "extra_files": [], "bad_records": 0,
                 "before_since": 0, "not_ok_runs": [], "items": {}}
    if not path.is_file():
        out["error"] = "zip 이 없어요"
        return out
    names = set(features.values())
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            data = z.read(n).decode("utf-8", errors="replace")
            out["scan"] = _sum(out["scan"], scan_text(data, keys))
            stem = n.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            if stem not in names:
                out["extra_files"].append(n)
            try:
                doc = json.loads(data)
            except ValueError:
                out["files"].append({"file": n, "error": "JSON 아님"})
                continue
            recs = doc.get("records") or []
            state = EX.run_state(recs) if recs else "empty"
            if state != "ok":
                out["not_ok_runs"].append(n)
            item_bad = Counter()
            for r in recs:
                if str(r["request"].get("time_kst", ""))[:10] < since:
                    out["before_since"] += 1
                c = check(r)
                bad = [k for k in REQUIRED if c[k] == "✗"]
                for k in bad:
                    item_bad[k] += 1
                out["bad_records"] += bool(bad)
            out["files"].append({"file": n, "feature_code": doc.get("feature_code"), "run_id": doc.get("run_id"),
                                 "records": len(recs), "state": state, "models": doc.get("models"),
                                 "missing_items": dict(item_bad)})
    have = {f["file"].rsplit("/", 1)[-1].rsplit(".", 1)[0] for f in out["files"]}
    out["missing_files"] = sorted(names - have)
    return out


# ─── 본체 ────────────────────────────────────────────────────────────────────────────────

def load_all(dirs: list[Path], since: str) -> tuple[list[dict], list[dict], int]:
    """(10/14 이후 레코드 enrich 사본, 원본, 이전이라 뺀 수). 같은 record_id 는 한 번만."""
    seen, raw = set(), []
    for d in dirs:
        for r in EX.load(d):
            if r.get("record_id") in seen:
                continue
            seen.add(r.get("record_id"))
            raw.append(r)
    rm = EX.run_models(raw)
    old = sum(1 for r in raw if str(r["request"].get("time_kst", ""))[:10] < since)
    keep = [r for r in raw if str(r["request"].get("time_kst", ""))[:10] >= since]
    return [EX.enrich(r, rm) for r in keep], keep, old


def audit(dirs: list[Path], *, since: str = "2026-10-14", zips: list[Path] | None = None,
          prices: dict | None = None, keys: list[str] | None = None, features: dict[str, str] | None = None) -> dict:
    features = AC._features() if features is None else features
    keys = EX.env_keys() if keys is None else keys
    recs, raw, old = load_all(dirs, since)
    allowed = set(AC.korean_hosts())
    rows: dict[tuple, dict] = {}
    by_model: dict[str, dict] = defaultdict(_bucket)
    by_feat: dict[str, dict] = defaultdict(_bucket)
    by_fm: dict[tuple, dict] = defaultdict(_bucket)
    hosts = Counter()
    for r in recs:
        rq = r["request"]
        kind = AC.kind_of(rq.get("method") or "", rq.get("endpoint") or "")
        key = (r.get("feature_code") or AC.UNCLASSIFIED, r.get("provider") or "?", rq.get("model") or "(없음)", kind)
        row = rows.setdefault(key, {"n": 0, **{k: Counter() for k, _ in ITEMS}})
        row["n"] += 1
        for k, v in check(r).items():
            row[k][v] += 1
        _add(by_model[model_key(r)], r)
        _add(by_feat[key[0]], r)
        _add(by_fm[(key[0], model_key(r))], r)
        hosts[(urlsplit(rq.get("endpoint") or "").hostname or "").lower()] += 1
    raw_gaps = Counter()
    for r in raw:
        if not r["request"].get("model"):
            raw_gaps["req_model_null"] += 1
        if "summary" not in r["response"]:
            raw_gaps["no_summary"] += 1
        if (r["response"].get("body") or {}) == {"streamed": True}:
            raw_gaps["streamed_body"] += 1
    grouped = EX.runs_by_feature(recs)
    runs = {}
    for code in sorted(set(grouped) | set(features)):
        fr = grouped.get(code, {})
        states = Counter(EX.run_state(rs) for rs in fr.values())
        got = EX.pick(fr) if fr else None
        runs[code] = {"name": features.get(code, "(기능 표에 없음)"), "runs": len(fr), "states": dict(states),
                      "records": sum(len(v) for v in fr.values()),
                      "representative": ({"run_id": got[0], "state": EX.run_state(got[1]), "records": len(got[1])}
                                         if got else None)}
    cost = None
    if prices:
        cost = {}
        for m, b in by_model.items():
            p = prices.get(m.split(" — ")[0])
            if p:
                cost[m] = {"estimate": round(b["prompt"] / 1e6 * p.get("input_per_1m", 0)
                                             + b["completion"] / 1e6 * p.get("output_per_1m", 0), 4),
                           "currency": p.get("currency", "?"), "source": p.get("source", "출처 미기재")}
    rep = {
        "generated_kst": AC.now_kst(), "dirs": [str(d) for d in dirs], "since": since,
        "records": len(recs), "before_since": old, "raw_gaps": dict(raw_gaps),
        "items": [{"feature": k[0], "provider": k[1], "model": k[2], "kind": k[3], "n": v["n"],
                   **{i: dict(v[i]) for i, _ in ITEMS}} for k, v in sorted(rows.items())],
        "by_model": {k: _finish(v) for k, v in sorted(by_model.items())},
        "by_feature": {k: _finish(v) for k, v in sorted(by_feat.items())},
        "by_feature_model": {f"{k[0]} · {k[1]}": _finish(v) for k, v in sorted(by_fm.items())},
        "runs": runs,
        "missing_features": sorted(c for c in features if c not in grouped),
        "unclassified_records": sum(len(v) for v in grouped.get(AC.UNCLASSIFIED, {}).values()),
        "hosts": dict(hosts), "outside_hosts": sorted(h for h in hosts if allowed and h not in allowed),
        "providers": sorted({r.get("provider") or "?" for r in recs}),
        "foreign_seen_this_process": sorted(set(AC.FOREIGN_SEEN)),
        "scan_logs": scan_dirs(dirs, keys),
        "zips": [audit_zip(z, keys, features, since) for z in (zips or [])],
        "cost": cost,
    }
    rep["missing_required_cells"] = sum(v.get("✗", 0) for row in rep["items"] for k, v in row.items()
                                        if k in REQUIRED and isinstance(v, dict))
    return rep


def _cell(c: dict) -> str:
    n = sum(c.values())
    if not n:
        return "—"
    bad = c.get("✗", 0)
    if bad:
        return f"✗{bad}/{n}"
    parts = []
    if c.get("✓"):
        parts.append("✓" if c["✓"] == n else f"✓{c['✓']}")
    if c.get("n/a"):
        parts.append("n/a" if c["n/a"] == n else f"n/a{c['n/a']}")
    if c.get("실패"):
        parts.append(f"실패{c['실패']}")
    return " ".join(parts)


def _fmt_bucket_table(title: str, d: dict) -> list[str]:
    out = [f"### {title}", "", "| 대상 | 호출 | 성공 | 429 | 그 밖 오류 | 재시도 | 입력 토큰 | 출력 토큰 | 토큰 합 | 쪽/음성초 | 지연 p50 | p95 |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for k, b in d.items():
        extra = " / ".join(x for x in (f"{b['pages']}쪽" if b["pages"] else "", f"{b['audio_sec']}초" if b["audio_sec"] else "") if x) or "—"
        out.append(f"| {k} | {b['calls']} | {b['ok']} | {b['r429']} | {b['errors']} | {b['retries']} | {b['prompt']:,} | "
                   f"{b['completion']:,} | {b['total']:,} | {extra} | {b['p50']}s | {b['p95']}s |")
    return out + [""]


def to_markdown(rep: dict) -> str:
    L = [f"# 국내 AI API 호출 로그 감사 — {rep['generated_kst']}", "",
         f"- 로그 폴더: {', '.join(rep['dirs'])}", f"- 기간: {rep['since']} 이후 {rep['records']}건 (이전이라 뺀 {rep['before_since']}건)",
         f"- 원본에서 빈 칸이었다가 내보내기가 채우는 것: {rep['raw_gaps'] or '없음'}",
         f"- 필수 항목 ✗ 셀 합: **{rep['missing_required_cells']}**", "",
         "## 1. 가이드 항목 대조표", "",
         "셀: ✓ 있음 · n/a 그 API 가 주지 않음(summary.*_note 에 까닭) · ✗k/n 빠짐 · 실패k 실패 레코드(오류 본문이 응답)", "",
         "| 기능 | 제공사 | 모델 | 종류 | 건 | " + " | ".join(n for _, n in ITEMS) + " |",
         "|---|---|---|---|---:|" + "---|" * len(ITEMS)]
    for row in rep["items"]:
        L.append(f"| {row['feature']} | {row['provider']} | {row['model']} | {row['kind']} | {row['n']} | "
                 + " | ".join(_cell(row[k]) for k, _ in ITEMS) + " |")
    L += ["", "## 2. 집계", ""]
    L += _fmt_bucket_table("모델별", rep["by_model"])
    L += _fmt_bucket_table("기능별", rep["by_feature"])
    L += _fmt_bucket_table("기능 × 모델", rep["by_feature_model"])
    if rep["cost"]:
        L += ["### 대략 비용 (주어진 단가 가정)", "", "| 모델 | 추정 | 통화 | 단가 출처 |", "|---|---:|---|---|"]
        L += [f"| {m} | {c['estimate']} | {c['currency']} | {c['source']} |" for m, c in rep["cost"].items()]
        L.append("")
    else:
        L += ["비용: 단가 자료가 없어 **토큰 합만** 적었어요 (`--prices` 로 출처 있는 단가를 주면 계산해요).", ""]
    L += ["## 3. 기능별 실행", "", "| 기능 | 이름 | 실행 | 건 | 상태 | 대표 실행 |", "|---|---|---:|---:|---|---|"]
    for code, v in rep["runs"].items():
        rp = v["representative"]
        L.append(f"| {code} | {v['name']} | {v['runs']} | {v['records']} | {v['states'] or '로그 없음'} | "
                 + (f"{rp['run_id']} ({rp['state']}, {rp['records']}건)" if rp else "—") + " |")
    L += ["", f"- 로그가 없는 기능: {rep['missing_features'] or '없음'}",
          f"- 미분류 레코드: {rep['unclassified_records']}", f"- 제공사: {rep['providers']}",
          f"- 호스트: {rep['hosts']}", f"- 국내 AI 목록 밖 호스트: {rep['outside_hosts'] or '없음'}", "",
          "## 4. 흔적 검사 (건수만 — 값은 찍지 않아요)", "",
          "| " + " | ".join(["항목", "로그 원본", *(Path(z["path"]).name for z in rep["zips"])]) + " |",
          "|---|---:|" + "---:|" * len(rep["zips"])]
    keys = sorted(set(rep["scan_logs"]) | {k for z in rep["zips"] for k in z.get("scan", {})})
    for k in keys:
        L.append("| " + " | ".join([k, str(rep["scan_logs"].get(k, 0)), *(str(z.get("scan", {}).get(k, 0)) for z in rep["zips"])]) + " |")
    L += ["", "로그 원본의 업로드 토큰 · 개인정보 패턴은 내보내기에서 *** 로 가린다 (원본은 0600 · 14일 보관). "
          "zip 의 비밀 항목은 전부 0 이어야 해요.", ""]
    for z in rep["zips"]:
        L += [f"### zip {z['path']}", ""]
        if z.get("error"):
            L += [f"- {z['error']}", ""]
            continue
        L += ["| 파일 | 기능 | 건 | 상태 | 모델 | 빠진 필수 항목 |", "|---|---|---:|---|---|---|"]
        L += [f"| {f['file']} | {f.get('feature_code')} | {f.get('records')} | {f.get('state')} | {', '.join(f.get('models') or [])} | "
              f"{f.get('missing_items') or '없음'} |" for f in z["files"]]
        L += ["", f"- 기능 표에 있는데 zip 에 없는 파일: {z['missing_files'] or '없음'}",
              f"- 기능 표에 없는 파일: {z['extra_files'] or '없음'}",
              f"- 끝까지 성공 아닌 대표 실행: {z['not_ok_runs'] or '없음'}",
              f"- 필수 항목이 빠진 레코드: {z['bad_records']} · {rep['since']} 이전 레코드: {z['before_since']}", ""]
    return "\n".join(L)


def failed(rep: dict) -> bool:
    for z in rep["zips"]:
        if z.get("error") or z["bad_records"] or any(z["scan"].get(k) for k in SECRET_FIELDS):
            return True
        if any(z["scan"].get(k) for k in z["scan"] if k.startswith("pii_")):
            return True
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="국내 AI API 호출 로그 감사 (가이드 항목 대조 · 집계 · 흔적 검사)")
    ap.add_argument("--dir", type=Path, action="append", default=[], help="로그 폴더 (여러 번 · 기본 AI_CALLLOG_DIR)")
    ap.add_argument("--since", default="2026-10-14")
    ap.add_argument("--zip", type=Path, action="append", default=[], help="내보낸 zip 도 검사 (여러 번)")
    ap.add_argument("--prices", type=Path, help="추정 단가 JSON {모델: {input_per_1m, output_per_1m, currency, source}}")
    ap.add_argument("--json", action="store_true", help="JSON 으로 찍는다")
    ap.add_argument("--out", type=Path, help="마크다운(또는 --json 이면 JSON)을 이 파일에도 쓴다")
    a = ap.parse_args(argv)
    dirs = [d.expanduser() for d in a.dir] or [AC.root()]
    prices = json.loads(a.prices.read_text(encoding="utf-8")) if a.prices else None
    rep = audit(dirs, since=a.since, zips=[z.expanduser() for z in a.zip], prices=prices)
    text = json.dumps(rep, ensure_ascii=False, indent=2) if a.json else to_markdown(rep)
    print(text)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text + "\n", encoding="utf-8")
    return 1 if failed(rep) else 0


if __name__ == "__main__":
    raise SystemExit(main())
