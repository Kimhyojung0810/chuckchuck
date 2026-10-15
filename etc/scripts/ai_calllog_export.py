#!/usr/bin/env python3
"""
국내 AI API 호출 로그 → 제출용 zip (설계 §6, 전국민 AI 경진대회 국내 AI 트랙 가이드 v1.0).

    python etc/scripts/ai_calllog_export.py --since 2026-10-14 --out ~/meetings/제출/국내AI_API_호출로그_척척발표.zip
    python etc/scripts/ai_calllog_export.py --list                         # 기능마다 실행 목록만 본다
    python etc/scripts/ai_calllog_export.py --run F-08=f-08-20261015T234102-7a1c   # 그 실행을 고른다 (여러 번 줄 수 있다)
    python etc/scripts/ai_calllog_export.py --pin <run_id> ...             # 14일 청소에서 빼 둔다 (pinned/)

1. 기능마다 끝까지 성공(부른 곳마다 마지막 시도 ok)한 실행(run_id) 하나 — 기본은 가장 최근, 없으면 일부 성공한 실행(△).
   그 실행의 레코드를 전부 담는다(실패 · 재시도 레코드도 — 가이드 「기능 끝날 때까지 누적」).
2. 마스킹은 구조를 그대로 두고 값 안의 전화번호 · 이메일 · 주민번호 · Bearer/키 모양 · 실제 키 값만 *** 로. 경로는 레코드 masked 에.
3. 「기능명.json」 = {feature, feature_code, run_id, models, providers, record_count, exported_at, records} — 모아서 zip 하나.
4. 점검표를 찍는다: 표에 있는데 로그가 없는 기능 · --since 이전이라 뺀 레코드 · 국내 AI 목록 밖 호스트 · 마스킹 건수 · zip 안 키 흔적.
키 값은 .env(pipeline.config)에서 코드 안에서만 읽는다 — 화면에 찍지 않는다.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "main")]

from pipeline import _ai_calllog as AC  # noqa: E402

DEFAULT_OUT = Path.home() / "meetings" / "제출" / "국내AI_API_호출로그_척척발표.zip"
_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"\b(?:up|awf|flp|sk|pk)_[A-Za-z0-9]{16,}\b"),          # Upstage · A.X · Friendli 등 키 모양
    re.compile(r"\b\d{6}-[1-4]\d{6}\b"),                                # 주민등록번호
    re.compile(r"\b01[016789][-. ]?\d{3,4}[-. ]?\d{4}\b"),               # 휴대전화
    re.compile(r"\b0\d{1,2}[-. ]\d{3,4}[-. ]\d{4}\b"),                   # 유선 전화
    re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),       # 이메일
)
#: 구조 필드 — 지문 · 식별자는 키 모양 검사에서 뺀다 (sha256 이 「키 같은 문자열」로 잡히지 않게)
_SKIP_KEYS = {"sha256", "record_id", "run_id", "id", "request_id"}


def env_keys() -> list[str]:
    """설정에 있는 실제 키 값들 (출력하지 않는다 — 마스킹 대상으로만)."""
    from pipeline.config import settings  # noqa: PLC0415

    vals = [settings.upstage_api_key, settings.ax_api_key, settings.ax_stt_api_key, settings.midm_api_key,
            settings.exaone_api_key]
    return sorted({v for v in vals if v and len(v) >= 8}, key=len, reverse=True)


def mask(value, keys: list[str], path: str = "") -> tuple[object, list[str]]:
    """값만 바꾸고 구조(키 · 자료형 · 배열 길이)는 그대로. (새 값, 바뀐 경로들)."""
    hits: list[str] = []

    def walk(v, p, key=""):
        if isinstance(v, dict):
            return {k: walk(x, f"{p}.{k}" if p else k, k) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x, f"{p}[{i}]", key) for i, x in enumerate(v)]
        if isinstance(v, str) and key not in _SKIP_KEYS:
            out = v
            for pat in _PATTERNS:          # 「Bearer <키>」 를 통째로 먼저 — 키만 지우면 「Bearer ***」 가 남는다
                out = pat.sub("***", out)
            for k in keys:
                out = out.replace(k, "***")
            if out != v:
                hits.append(p)
            return out
        return v

    return walk(value, path), hits


def shape(v):
    """비교용 구조 — 문자열 값은 지우고 자료형만 남긴다."""
    if isinstance(v, dict):
        return {k: shape(x) for k, x in v.items()}
    if isinstance(v, list):
        return [shape(x) for x in v]
    return type(v).__name__


def load(root: Path) -> list[dict]:
    """날짜 폴더 + pinned/ 의 레코드 전부. 같은 record_id 는 한 번만."""
    seen, out = set(), []
    for p in sorted(root.rglob("*.jsonl")) if root.is_dir() else ():
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("record_id") in seen:
                continue
            seen.add(r.get("record_id"))
            out.append(r)
    return out


def runs_by_feature(records: list[dict]) -> dict[str, dict[str, list[dict]]]:
    out: dict[str, dict[str, list[dict]]] = {}
    for r in records:
        out.setdefault(r.get("feature_code") or AC.UNCLASSIFIED, {}).setdefault(r.get("run_id") or "?", []).append(r)
    for runs in out.values():
        for rs in runs.values():
            rs.sort(key=lambda r: r["request"]["time_kst"])
    return out


def run_state(rs: list[dict]) -> str:
    """실행 하나의 결과 — ok(부른 곳마다 마지막 시도가 성공) · partial(성공한 호출이 있지만 끝내 실패한 곳도 있음, 예: 객석 병아리 넷 중 하나) · fail."""
    last: dict = {}
    for r in rs:
        last[(r["request"].get("method"), r["request"].get("endpoint"), r["request"].get("model"))] = bool(r.get("ok"))
    if last and all(last.values()):
        return "ok"
    return "partial" if any(r.get("ok") for r in rs) else "fail"


def pick(runs: dict[str, list[dict]], want: str | None = None) -> tuple[str, list[dict]] | None:
    """--run 으로 고른 것, 아니면 끝까지 성공한 실행 중 가장 최근, 그게 없으면 일부 성공한 실행 중 가장 최근."""
    if want:
        return (want, runs[want]) if want in runs else None
    for need in ("ok", "partial"):
        good = [(rs[-1]["request"]["time_kst"], rid, rs) for rid, rs in runs.items() if rs and run_state(rs) == need]
        if good:
            _, rid, rs = max(good)
            return rid, rs
    return None


def pin(root: Path, run_ids: list[str]) -> list[Path]:
    """고른 실행을 pinned/<run_id>.jsonl 로 복사한다 — 14일 청소(AC.prune)가 지우지 않는다."""
    keep = set(run_ids)
    (root / "pinned").mkdir(parents=True, exist_ok=True, mode=0o700)
    by: dict[str, list[dict]] = {}
    for r in load(root):
        if r.get("run_id") in keep:
            by.setdefault(r["run_id"], []).append(r)
    out = []
    for rid, rs in by.items():
        p = root / "pinned" / f"{re.sub(r'[^0-9A-Za-z_.-]', '_', rid)}.jsonl"
        p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rs), encoding="utf-8")
        p.chmod(0o600)
        out.append(p)
    return out


def export(*, root: Path, since: str, out: Path, runs: dict[str, str] | None = None,
           keys: list[str] | None = None, features: dict[str, str] | None = None) -> dict:
    features = features if features is not None else AC._features()
    keys = env_keys() if keys is None else keys
    allowed = set(AC.korean_hosts())
    all_recs = load(root)
    old = [r for r in all_recs if r["request"]["time_kst"][:10] < since]
    recs = [r for r in all_recs if r["request"]["time_kst"][:10] >= since]
    grouped = runs_by_feature(recs)
    stamp = AC.now_kst()
    files: dict[str, bytes] = {}
    report = {"files": [], "missing": [], "no_success": [], "before_since": len(old), "outside_hosts": [],
              "masked": 0, "unclassified": len(grouped.get(AC.UNCLASSIFIED, {}))}
    for code, name in features.items():
        fruns = grouped.get(code)
        if not fruns:
            report["missing"].append(code)
            continue
        got = pick(fruns, (runs or {}).get(code))
        if not got:
            report["no_success"].append(code)
            continue
        rid, rs = got
        if run_state(rs) != "ok":
            report.setdefault("partial", []).append(code)
        masked_rs = []
        for r in rs:
            m, paths = mask(r, keys)
            m["masked"] = sorted(set((r.get("masked") or []) + paths))
            report["masked"] += len(paths)
            host = (urlsplit(r["request"]["endpoint"]).hostname or "").lower()
            if allowed and host not in allowed:
                report["outside_hosts"].append(host)
            masked_rs.append(m)
        doc = {
            "feature": name, "feature_code": code, "run_id": rid,
            "models": sorted({r["request"].get("model") for r in rs if r["request"].get("model")}),
            "providers": sorted({r.get("provider") for r in rs if r.get("provider")}),
            "record_count": len(rs), "exported_at": stamp, "records": masked_rs,
        }
        fname = f"{name}.json"
        files[fname] = json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
        report["files"].append({"file": fname, "code": code, "run_id": rid, "records": len(rs), "models": doc["models"],
                                "state": run_state(rs)})
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".part")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for fname, data in files.items():
            z.writestr(fname, data)
    shutil.move(tmp, out)
    blob = b"".join(files.values()).decode("utf-8")
    report["key_traces"] = {"Authorization": blob.count("Authorization"), "X-API-Key": blob.count("X-API-Key"),
                            "env_keys": sum(blob.count(k) for k in keys)}
    report["outside_hosts"] = sorted(set(report["outside_hosts"]))
    return report


def list_runs(root: Path, since: str) -> None:
    grouped = runs_by_feature([r for r in load(root) if r["request"]["time_kst"][:10] >= since])
    feats = AC._features()
    for code in sorted(grouped):
        print(f"{code} {feats.get(code, '(표에 없음)')}")
        for rid, rs in sorted(grouped[code].items(), key=lambda kv: kv[1][-1]["request"]["time_kst"]):
            ok = run_state(rs)
            print(f"   {rid}  {len(rs)}건  {rs[0]['request']['time_kst']}  {ok}  "
                  f"{sorted({r['request'].get('model') for r in rs if r['request'].get('model')})}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="국내 AI API 호출 로그 → 제출용 zip")
    ap.add_argument("--root", type=Path, default=AC.root())
    ap.add_argument("--since", default="2026-10-14", help="이 날(KST) 이후 호출만 (가이드: 10/14 부터 인정)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--run", action="append", default=[], metavar="F-08=<run_id>", help="기능의 실행을 직접 고른다")
    ap.add_argument("--pin", nargs="+", metavar="RUN_ID", help="이 실행들을 14일 청소에서 뺀다")
    ap.add_argument("--list", action="store_true", help="실행 목록만 본다")
    a = ap.parse_args(argv)
    if a.pin:
        for p in pin(a.root, a.pin):
            print(f"고정했어요: {p}")
        return 0
    if a.list:
        list_runs(a.root, a.since)
        return 0
    runs = dict(x.split("=", 1) for x in a.run)
    rep = export(root=a.root, since=a.since, out=a.out.expanduser(), runs=runs)
    print(f"zip: {a.out}  ({datetime.now():%Y-%m-%d %H:%M})")
    for f in rep["files"]:
        mark = "✓" if f["state"] == "ok" else "△"
        print(f"  {mark} {f['file']:<24} {f['code']:<10} {f['records']:>3}건  {', '.join(f['models'])}  ({f['run_id']})")
    print("점검표")
    print(f"  - 기능 표에 있는데 로그가 없는 기능: {rep['missing'] or '없음'}")
    print(f"  - 로그는 있는데 성공한 호출이 하나도 없는 기능: {rep['no_success'] or '없음'}")
    print(f"  - 일부만 성공한 실행을 담은 기능(실패 레코드도 그대로 들어감): {rep.get('partial') or '없음'}")
    print(f"  - {a.since} 이전이라 뺀 레코드: {rep['before_since']}건")
    print(f"  - 국내 AI 목록 밖 호스트: {rep['outside_hosts'] or '없음'}")
    print(f"  - 미분류 실행: {rep['unclassified']}개 (0 이어야 해요)")
    print(f"  - 마스킹: {rep['masked']}곳")
    print(f"  - zip 안 키 흔적: {rep['key_traces']} (전부 0 이어야 해요)")
    bad = any(rep["key_traces"].values())
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
