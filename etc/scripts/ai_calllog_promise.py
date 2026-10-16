#!/usr/bin/env python3
"""
국내 AI API 호출 로그 → 제출 정리 폴더 (AI 이름별 폴더 + README + 기능 단위 zip) — 2026-10-17.

    python etc/scripts/ai_calllog_promise.py --dir /data/models/_runs/qa-ensemble/calllog
    python etc/scripts/ai_calllog_promise.py --dir A --dir B --roles roles.json \\
        --evidence LG_EXAONE=/data/models/_runs/qa-ensemble/bench/exaone_gen.md --evidence SKT_A.X=…/peer.json

만드는 것 (기본 ~/project/promise/AI_호출로그_정리/ — git 밖. 가이드 PDF 는 건드리지 않는다):
- AI 이름별 폴더 Upstage_Solar/ · Upstage_Document_Parse/ · Upstage_Embedding/ · SKT_A.X/ · SKT_A.X_STT/ · KT_Midm/ · LG_EXAONE/
  — **실제로 부른 모델만**. 폴더마다
  ① 그 모델이 쓰인 기능별 대표 로그 「기능명.json」 (export 와 같은 형식 · 같은 대표 실행 규칙(끝까지 성공한 가장 최근 실행),
     단 **그 모델의 레코드만** 골라 그 실행 상태를 본다 · 10/14 이후 · 키/개인정보 마스킹)
  ② README.md — 모델 식별값 · 엔드포인트 · 맡은 기능과 역할 · 호출 수/성공/429/오류 · 토큰 합 · 지연 p50/p95 · 기간 · 대표 요청/응답 요약 ·
     「이 모델을 그 역할에 둔 근거(실험 수치)」 (`--evidence 폴더=경로` 로 끼워 넣거나 TODO)
- 최상위 README.md — 가이드 항목별 준수 대조표 · 기능명↔모델↔파일 · 전체 집계 · 마스킹 방식 · 국내 AI 외 호출 0 · 비밀 스캔
- 제출용_AI_API_호출로그.zip — 가이드대로 **기능 단위** 파일(기능명.json)을 모은 zip 하나 (ai_calllog_export.export 그대로)

역할 문장: `--roles JSON` = {"F-08-gen": {"*": "기본 문장", "LG_EXAONE": "이 모델일 때 문장"}, …}. 없으면 기본 초안 + TODO.
기능명은 main/pipeline/ai_calllog_features.json 하나만 고치면 된다 (confirmed 에 없는 이름은 「가칭」 으로 표시).
다시 돌리면 이 스크립트가 만든 폴더 · 파일만 지우고 새로 만든다.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "main")]

from pipeline import _ai_calllog as AC  # noqa: E402


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


EX = _load("ai_calllog_export")
AU = _load("ai_calllog_audit")

DEFAULT_OUT = Path.home() / "project" / "promise" / "AI_호출로그_정리"
ZIP_NAME = "제출용_AI_API_호출로그.zip"
#: (폴더, 이름, 제공사, 고르는 조건(host, kind))
GROUPS = (
    ("Upstage_Solar", "Upstage Solar (LLM)", "Upstage", lambda h, k: h.endswith("upstage.ai") and k == "chat"),
    ("Upstage_Document_Parse", "Upstage Document Parse", "Upstage", lambda h, k: h.endswith("upstage.ai") and k.startswith("docparse")),
    ("Upstage_Embedding", "Upstage Solar Embedding", "Upstage", lambda h, k: h.endswith("upstage.ai") and k == "embedding"),
    ("SKT_A.X", "SKT A.X (LLM)", "SKT", lambda h, k: h.endswith("adot.ai") and k == "chat"),
    ("SKT_A.X_STT", "SKT A.X STT (배치 · 실시간)", "SKT", lambda h, k: h.endswith("adot.ai") and k.startswith("stt")),
    ("KT_Midm", "KT 믿:음 (Mi:dm)", "KT", lambda h, k: h.endswith("kt.com")),
    ("LG_EXAONE", "LG AI연구원 EXAONE (FriendliAI 전용 엔드포인트)", "LG AI연구원", lambda h, k: h.endswith("friendli.ai")),
)
#: 역할 초안 — 사람이 --roles 로 덮는다
DEFAULT_ROLES = {
    "F-01": "발표 자료(PDF · PPTX)를 장 단위 글 · 표 · 제목으로 읽는다",
    "F-05": "발표 녹음을 글로 받아쓴다(낱말 시각 포함 — 장별 말 빠르기 · 정합 판정의 바탕)",
    "F-05-live": "질문 답변을 말로 할 때 실시간으로 받아쓴다(문장 단위 확정)",
    "F-06": "장마다 핵심 개념을 뽑는다",
    "F-07": "개념 사이 관계로 발표 전체의 개념 그래프를 만든다",
    "F-08": "발표 내용에 맞춘 예상 질문을 만든다",
    "F-08-gen": "예상 질문 후보를 만든다 (네 모델이 각자 후보를 낸다)",
    "F-08-peer": "다른 모델이 낸 질문 후보를 서로 평가한다",
    "F-08-pick": "평가를 모아 최종 질문을 고른다",
    "F-08-voice": "발표 음성(받아쓰기)에서 건너뜀 · 흐림 · 자료와 다른 말을 짚어 다음 질문을 정한다",
    "F-08-gist": "질문마다 모범답을 짧게 정리한다",
    "F-09": "답변을 판정하고 꼬리질문을 정한다",
    "F-11": "발표 말과 자료가 맞는지 장마다 판정한다",
    "F-12": "객석 병아리 관객으로 발표에 반응한다 (네 모델이 한 자리씩)",
    "F-14": "39항목 채점표로 발표를 채점한다",
    "F-19": "리포트 코멘트를 쓴다",
    "F-20": "발표 구성(순서 · 시간 배분)을 제안한다",
    "F-24": "개념 그래프에서 논문 검색어를 만든다",
    "F-26": "자료의 주장 문장으로 주장 그래프를 만든다",
}
EXCERPT = 220


def group_of(r: dict) -> str:
    rq = r["request"]
    host = (urlsplit(rq.get("endpoint") or "").hostname or "").lower()
    kind = AC.kind_of(rq.get("method") or "", rq.get("endpoint") or "")
    for folder, _, _, test in GROUPS:
        if test(host, kind):
            return folder
    return f"기타_{host or '알수없음'}"


def _features_meta() -> tuple[dict[str, str], set[str]]:
    try:
        raw = json.loads(AC.FEATURES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    return raw.get("features", {}), set(raw.get("confirmed") or [])


def _name(code: str, feats: dict, confirmed: set) -> str:
    n = feats.get(code, code)
    return n if code in confirmed else f"{n} (가칭)"


def role_of(roles: dict, code: str, folder: str) -> tuple[str, bool]:
    """(문장, 사람이 준 것인가)."""
    r = roles.get(code) or {}
    if isinstance(r, str):
        return r, True
    if r.get(folder) or r.get("*"):
        return r.get(folder) or r["*"], True
    return DEFAULT_ROLES.get(code, "역할 설명 없음"), False


def _endpoint_base(ep: str) -> str:
    sp = urlsplit(ep or "")
    path = EX._UPLOAD_PATH.sub(r"\1***", sp.path)
    if "/document-digitization/requests/" in path:
        path = path.rsplit("/", 1)[0] + "/{request_id}"
    return f"{sp.scheme}://{sp.netloc}{path}"


def _short(text, n: int = EXCERPT) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[:n] + "…"


def excerpt(r: dict, keys: list[str]) -> tuple[str, str]:
    """(요청 요약, 응답 요약) — 마스킹한 사본에서 짧게."""
    m, _ = EX.mask(r, keys)
    rq, rp = m["request"], m["response"]
    body = rq.get("body") if isinstance(rq.get("body"), dict) else {}
    kind = AC.kind_of(rq.get("method") or "", rq.get("endpoint") or "")
    if kind == "chat":
        msgs = body.get("messages") or []
        users = [x for x in msgs if isinstance(x, dict) and x.get("role") == "user"]
        req = f"messages {len(msgs)}개 · 마지막 user: {_short((users or msgs or [{}])[-1].get('content'))}"
    elif kind == "embedding":
        inp = body.get("input")
        req = f"input {len(inp) if isinstance(inp, list) else 1}개 · 첫 항목: {_short(inp[0] if isinstance(inp, list) and inp else inp, 80)}"
    elif kind.startswith("docparse"):
        doc = body.get("document") or {}
        req = f"문서 {doc.get('bytes')}바이트 sha256 {str(doc.get('sha256'))[:12]}… · form {body.get('form')}"
    elif kind == "stt_live":
        a = body.get("audio") or {}
        req = f"create {body.get('create')} · 음성 {a.get('duration_sec')}초 sha256 {str(a.get('sha256'))[:12]}… (원본 음성은 싣지 않음)"
    elif kind == "stt_upload":
        a = body.get("audio") or {}
        req = f"음성 {a.get('bytes')}바이트 sha256 {str(a.get('sha256'))[:12]}… (원본 음성은 싣지 않음)"
    else:
        req = _short(json.dumps(body, ensure_ascii=False) if body else rq.get("endpoint"))
    s = rp.get("summary") or {}
    rb = rp.get("body") if isinstance(rp.get("body"), dict) else {}
    ans = ""
    src = s.get("answer_from") or ""
    if src.startswith("body.choices[0].message"):
        ans = (((rb.get("choices") or [{}])[0] or {}).get("message") or {}).get(src.rsplit(".", 1)[-1])
    elif src.startswith("body.utterances"):
        ans = " ".join(str(u.get("text") or "") for u in rb.get("utterances") or [] if isinstance(u, dict))
    elif src.startswith("body.messages"):
        ans = " ".join(str(u.get("text") or "") for u in rb.get("messages") or [] if isinstance(u, dict))
    elif src.startswith("body.content"):
        ans = (rb.get("content") or {}).get(src.rsplit(".", 1)[-1])
    elif src.startswith("body.data"):
        ans = f"임베딩 {s.get('answer_chars')}개"
    elif src:
        ans = f"{src} 있음"
    resp = (f"status {rp.get('status')} · id {s.get('id') or '(API 미제공)'} · model {s.get('model') or rq.get('model')} · "
            f"usage {json.dumps(s.get('usage'), ensure_ascii=False) if s.get('usage') else '(해당 없음)'} · 답: {_short(ans)}")
    return req, resp


def evidence_block(path: Path | None) -> list[str]:
    if not path:
        return ["> TODO: 이 모델을 이 역할에 둔 근거(실험 수치)를 채워 주세요 — "
                "`--evidence 폴더=문서.md|결과.json` 으로 다시 돌리면 여기에 들어가요.", ""]
    if not path.is_file():
        return [f"> TODO: 근거 파일이 없어요: `{path}`", ""]
    text = path.read_text(encoding="utf-8", errors="replace")
    out = [f"출처: `{path}`", ""]
    if path.suffix == ".json":
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except ValueError:
            pass
        body = text if len(text) <= 6000 else text[:6000] + "\n…(줄임)"
        return out + ["```json", body, "```", ""]
    lines = text.splitlines()
    return out + lines[:120] + (["", "…(줄임)"] if len(lines) > 120 else []) + [""]


def _stat_row(label: str, b: dict) -> str:
    return (f"| {label} | {b['calls']} | {b['ok']} | {b['r429']} | {b['errors']} | {b['retries']} | {b['prompt']:,} | "
            f"{b['completion']:,} | {b['total']:,} | {b['p50']}s | {b['p95']}s |")


STAT_HEAD = ["| 대상 | 호출 | 성공 | 429 | 그 밖 오류 | 재시도 | 입력 토큰 | 출력 토큰 | 토큰 합 | 지연 p50 | p95 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]


def _stats(rs: list[dict]) -> dict:
    b = AU._bucket()
    for r in rs:
        AU._add(b, r)
    return AU._finish(b)


def build(*, dirs: list[Path], out: Path, since: str = "2026-10-14", roles: dict | None = None,
          evidence: dict[str, Path] | None = None, keys: list[str] | None = None, include_unlisted: bool = False) -> dict:
    roles, evidence = roles or {}, evidence or {}
    keys = EX.env_keys() if keys is None else keys
    feats, confirmed = _features_meta()
    recs, _, old = AU.load_all(dirs, since)
    out.mkdir(parents=True, exist_ok=True)
    for folder, *_ in GROUPS:                         # 이 스크립트가 만든 것만 지운다
        shutil.rmtree(out / folder, ignore_errors=True)
    for p in out.glob("기타_*"):
        shutil.rmtree(p, ignore_errors=True)
    for p in (out / "README.md", out / ZIP_NAME):
        p.unlink(missing_ok=True)
    by_group: dict[str, list[dict]] = defaultdict(list)
    skipped: dict[str, int] = defaultdict(int)
    for r in recs:
        code = r.get("feature_code") or AC.UNCLASSIFIED
        if code not in feats and not include_unlisted:      # 벤치 · 실험(F-08-bench 등)은 서비스 기능이 아니다 — 따로 센다
            skipped[code] += 1
            continue
        by_group[group_of(r)].append(r)
    meta = {g[0]: g for g in GROUPS}
    summary: dict = {"groups": {}, "since": since, "records": len(recs), "before_since": old, "skipped": skipped}
    for folder in [g[0] for g in GROUPS] + sorted(k for k in by_group if k not in meta):
        rs = by_group.get(folder)
        if not rs:
            continue
        gdir = out / folder
        gdir.mkdir(parents=True, exist_ok=True)
        grouped = EX.runs_by_feature(rs)
        files, rows, reps = [], [], []
        for code in sorted(grouped, key=lambda c: (c not in feats, c)):
            got = EX.pick(grouped[code])
            if not got:
                rows.append((code, None, "성공 실행 없음", grouped[code]))
                continue
            rid, run = got
            state = EX.run_state(run)
            masked = []
            for r in run:
                m, paths = EX.mask(r, keys)
                m["masked"] = sorted(set((r.get("masked") or []) + paths))
                masked.append(m)
            name = feats.get(code, code)
            doc = {"feature": name, "feature_code": code, "ai": meta.get(folder, (folder, folder))[1], "run_id": rid,
                   "run_state": state, "models": sorted({r["request"].get("model") for r in run if r["request"].get("model")}),
                   "model_labels": {r["request"]["model"]: r["request"].get("model_label") for r in run if r["request"].get("model")},
                   "record_count": len(run), "exported_at": AC.now_kst(), "records": masked}
            fname = f"{name}.json"
            (gdir / fname).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            files.append(fname)
            rows.append((code, fname, state, [r for runs in grouped[code].values() for r in runs]))
            reps.append((code, run[-1] if state == "ok" else next((x for x in reversed(run) if x.get("ok")), run[-1])))
        st = _stats(rs)
        models = sorted({(r["request"].get("model"), r["request"].get("model_label")) for r in rs}, key=str)
        endpoints = sorted({_endpoint_base(r["request"].get("endpoint") or "") for r in rs})
        L = [f"# {meta.get(folder, (folder, folder))[1]}", "",
             f"- 제공사: {meta.get(folder, (0, 0, '국내 AI 목록 밖 — 확인 필요'))[2]}",
             "- 모델 식별값(요청 model): " + " · ".join(f"`{m}`" + (f" ({lab})" if lab and lab != m else "") for m, lab in models),
             "- 엔드포인트: " + " · ".join(f"`{e}`" for e in endpoints),
             f"- 기간: {st['first']} ~ {st['last']} (KST, {since} 이후만)",
             f"- 호출 {st['calls']}건 · 성공 {st['ok']} · 429 {st['r429']} · 그 밖 오류 {st['errors']} · 재시도 {st['retries']} · "
             f"토큰 합 {st['total']:,} (입력 {st['prompt']:,} / 출력 {st['completion']:,})"
             + (f" · {st['pages']}쪽" if st["pages"] else "") + (f" · 음성 {st['audio_sec']}초" if st["audio_sec"] else "")
             + f" · 지연 p50 {st['p50']}s / p95 {st['p95']}s", "",
             "## 맡은 기능과 역할", "", "| 기능 코드 | 기능명(파일) | 역할 | 대표 실행 |", "|---|---|---|---|"]
        todo_roles = []
        for code, fname, state, _all in rows:
            text, given = role_of(roles, code, folder)
            if not given:
                todo_roles.append(code)
            L.append(f"| {code} | {_name(code, feats, confirmed)}{f' → `{fname}`' if fname else ''} | {text}{'' if given else ' *(초안)*'} | {state} |")
        if todo_roles:
            L += ["", f"> TODO: 역할 문장 확인 — {', '.join(todo_roles)} 는 초안이에요 (`--roles` 로 덮어요)."]
        L += ["", "## 기능별 집계", "", *STAT_HEAD]
        L += [_stat_row(code, _stats(a)) for code, _, _, a in rows]
        L += ["", "## 대표 요청 · 응답 요약 (마스킹 · 짧게)", ""]
        for code, r in reps:
            q, a = excerpt(r, keys)
            L += [f"**{code}** · {r['request'].get('time_kst')} → {r['response'].get('time_kst')} · `{_endpoint_base(r['request'].get('endpoint'))}`",
                  f"- 요청: {q}", f"- 응답: {a}", ""]
        L += ["## 이 모델을 그 역할에 둔 근거 (실험 수치)", ""] + evidence_block(evidence.get(folder))
        (gdir / "README.md").write_text("\n".join(L) + "\n", encoding="utf-8")
        summary["groups"][folder] = {"files": files, "stats": st, "models": [m for m, _ in models], "endpoints": endpoints,
                                     "features": [c for c, *_ in rows]}
    # 기능 단위 zip — export 그대로
    zip_path = out / ZIP_NAME
    rep = EX.export(root=dirs[0], since=since, out=zip_path, keys=keys) if len(dirs) == 1 else _export_multi(dirs, since, zip_path, keys)
    audit = AU.audit(dirs, since=since, zips=[zip_path], keys=keys)
    scan_out = {}
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.suffix in (".json", ".md"):
            scan_out = AU._sum(scan_out, AU.scan_text(p.read_text(encoding="utf-8", errors="replace"), keys))
    summary.update(export=rep, audit_missing_cells=audit["missing_required_cells"], scan_folder=scan_out)
    _top_readme(out, summary, audit, rep, feats, confirmed, roles)
    final = {}                                         # README 까지 쓴 뒤 폴더 전체를 다시 훑는다
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.suffix in (".json", ".md"):
            final = AU._sum(final, AU.scan_text(p.read_text(encoding="utf-8", errors="replace"), keys))
    summary["scan_folder"] = final
    return summary


def _export_multi(dirs: list[Path], since: str, zip_path: Path, keys: list[str]) -> dict:
    """로그 폴더가 여럿이면 임시로 한 곳에 모아 export 한다 (같은 record_id 는 한 번)."""
    import tempfile  # noqa: PLC0415

    with tempfile.TemporaryDirectory(prefix="calllog-merge-") as tmp:
        seen, lines = set(), []
        for d in dirs:
            for r in EX.load(d):
                if r.get("record_id") not in seen:
                    seen.add(r.get("record_id"))
                    lines.append(json.dumps(r, ensure_ascii=False))
        (Path(tmp) / "all.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return EX.export(root=Path(tmp), since=since, out=zip_path, keys=keys)


def _top_readme(out: Path, s: dict, audit: dict, rep: dict, feats: dict, confirmed: set, roles: dict) -> None:
    cells = defaultdict(lambda: defaultdict(int))
    for row in audit["items"]:
        for k in AU.REQUIRED:
            for v, n in row[k].items():
                cells[k][v] += n
    names = dict(AU.ITEMS)
    how = {
        "req_time": "request.time_kst — 요청 보내기 직전 KST(+09:00) 밀리초",
        "endpoint": "request.endpoint — https:// · wss:// 도메인 포함 전체 주소",
        "req_model": "request.model (요청 본문의 model · speech_model) + model_label(사람이 읽는 이름) · model_source(출처)",
        "req_body": "request.body — 보낸 JSON 전체(messages 등). 파일 · 음성은 바이트 수 · sha256 지문만",
        "resp_time": "response.time_kst — 응답 받은 뒤 KST(+09:00)",
        "resp_id": "response.body 의 id(대화) · message_id/file_key(STT) · tr_id(실시간) — 위치는 response.summary.id_from",
        "resp_model": "response.body.model — STT 는 API 가 안 돌려줘 요청 모델(summary.model_note)",
        "answer": "response.body 의 답변 — 위치는 response.summary.answer_from",
        "usage": "response.body.usage(토큰) — 문서 파싱은 쪽 수, STT 는 음성 길이(summary.usage)",
    }
    L = ["# 국내 AI API 호출 로그 정리 — 척척발표", "",
         f"만든 시각 {AC.now_kst()} · 로그 {s['records']}건({s['since']} 이후 · 이전이라 뺀 {s['before_since']}건) · 다시 만들기: "
         "`python etc/scripts/ai_calllog_promise.py --dir <로그 폴더>`", "",
         "> **로컬 서빙 모델은 제출 대상이 아니에요.** F-18 음성 습관 분석의 Mi:dm 2.0 + LoRA 어댑터는 팀 서버 GPU 에서 직접 돌리는 "
         "로컬 서빙이라 가이드의 「AI 모델 로컬 서빙 — 호출 로그 제출 대상 아님」 에 해당해요. 웹 검색(논문 검색 OpenAlex 등) 같은 일반 API 도 대상이 아니에요.", "",
         "## 1. 가이드 항목별 준수 대조", "", "| 가이드 항목 | 어디에 남나 | 대조 결과 (전체 레코드) |", "|---|---|---|"]
    for k in AU.REQUIRED:
        c = cells[k]
        res = " · ".join(f"{v} {n}" for v, n in sorted(c.items())) or "—"
        L.append(f"| {names[k]} | {how[k]} | {res} |")
    L += ["| 요청·응답 한 건으로 묶기 | 한 왕복 = JSONL 한 줄(record_id) — 요청 · 응답 · ok · attempt | ✓ |",
          "| 기능 끝날 때까지 누적 | 같은 기능 실행은 run_id 로 묶어 그 실행의 레코드 전부(실패 · 재시도 포함) | ✓ |",
          f"| 10월 14일 이후만 | --since {s['since']} | zip 안 이전 레코드 {audit['zips'][0]['before_since'] if audit['zips'] else '?'}건 |",
          "| 기능별 1회 · 기능 단위 파일 · 파일명 = 기능명 · zip 하나 | " + f"`{ZIP_NAME}` | 파일 {len(rep['files'])}개 · 없는 기능 {rep['missing'] or '없음'} |",
          "| 파일 형식 | json (UTF-8) | ✓ |",
          f"| 민감정보 없음 | 헤더는 아예 안 적음 · 마스킹(아래) | zip 비밀 흔적 {sum(audit['zips'][0]['scan'].get(k, 0) for k in AU.SECRET_FIELDS) if audit['zips'] else '?'}건 |",
          "", "셀 뜻: ✓ 있음 · n/a 그 API 가 주지 않는 항목(예: 임베딩 · 문서 파싱 응답엔 ID 가 없음 — 레코드 summary.*_note) · 실패 = 실패 레코드(오류 본문이 응답).", "",
          "## 2. 기능명 ↔ 모델 ↔ 파일", "", "| 기능 코드 | 기능명 | 모델(AI 폴더) | zip 파일 | 대표 실행 |", "|---|---|---|---|---|"]
    zfiles = {f["code"]: f for f in rep["files"]}
    for code in feats:
        gs = [g for g, v in s["groups"].items() if code in v["features"]]
        zf = zfiles.get(code)
        L.append(f"| {code} | {_name(code, feats, confirmed)} | {', '.join(gs) or '—'} | "
                 f"{('`' + zf['file'] + '`') if zf else '없음'} | {(zf['state'] + ' · ' + str(zf['records']) + '건') if zf else '로그 없음'} |")
    L += ["", "## 3. 전체 집계 (모델별)", "", *STAT_HEAD]
    L += [_stat_row(m, b) for m, b in audit["by_model"].items()]
    L += ["", "AI 폴더별: " + " · ".join(f"{g} {v['stats']['calls']}건" for g, v in s["groups"].items()), "",
          "## 4. 마스킹 방식", "",
          "- 요청 헤더는 기록하지 않아요 (API 키 · 인증 머리글이 처음부터 로그에 없음).",
          "- 파일 · 음성 본문은 원본 대신 바이트 수 · sha256 지문만 (발표 자료 · 목소리 원본이 로그에 없음).",
          "- 값 안의 전화번호 · 이메일 · 주민등록번호 · `Bearer …` · 키 모양 문자열 · 실제 키 값은 그 부분만 `***` — 키 · 자료형 · 배열 길이(구조)는 그대로.",
          "- A.X STT 업로드 토큰(10분 유효 업로드 권한)은 응답 값과 업로드 주소 경로에서 `***`.",
          "- 바뀐 자리는 레코드마다 `masked` 에 경로로 남겨요.", "",
          "## 5. 국내 AI 외 호출 0 확인", "",
          f"- 로그의 제공사: {audit['providers']}",
          f"- 로그의 호스트: {audit['hosts']}",
          f"- 국내 AI 목록(config 의 base URL) 밖 호스트: {audit['outside_hosts'] or '0건'}",
          "- 기록기는 해외 AI 호스트(openai · anthropic · googleapis speech/generative 등)로 가는 요청을 보면 경고하고, 테스트가 서버 코드 · 웹 화면에서 "
          "해외 AI 호스트 · 브라우저 음성인식(Web Speech)이 다시 생기면 실패해요 (etc/tests/test_ai_calllog.py).", "",
          "## 6. 비밀 · 개인정보 스캔 (건수만)", "", "| 항목 | 로그 원본 | 이 폴더(json · md) | zip |", "|---|---:|---:|---:|"]
    zscan = audit["zips"][0]["scan"] if audit["zips"] else {}
    for k in sorted(set(audit["scan_logs"]) | set(s["scan_folder"]) | set(zscan)):
        L.append(f"| {k} | {audit['scan_logs'].get(k, 0)} | {s['scan_folder'].get(k, 0)} | {zscan.get(k, 0)} |")
    L += ["", "로그 원본의 업로드 토큰 · 개인정보 패턴은 내보낼 때 가려요. 이 폴더와 zip 은 전부 0 이어야 해요.", ""]
    (out / "README.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="국내 AI API 호출 로그 → AI 이름별 정리 폴더 + README + 기능 단위 zip")
    ap.add_argument("--dir", type=Path, action="append", default=[], help="로그 폴더 (여러 번 · 기본 AI_CALLLOG_DIR)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--since", default="2026-10-14")
    ap.add_argument("--roles", type=Path, help='역할 문장 JSON {"F-08-gen": {"*": "…", "LG_EXAONE": "…"}}')
    ap.add_argument("--evidence", action="append", default=[], metavar="폴더=경로", help="근거 문서(.md) · 결과(.json)")
    ap.add_argument("--include-unlisted", action="store_true", help="기능 표에 없는 코드(벤치 등)도 AI 폴더에 넣는다")
    a = ap.parse_args(argv)
    roles = json.loads(a.roles.read_text(encoding="utf-8")) if a.roles else {}
    ev = {k: Path(v).expanduser() for k, v in (x.split("=", 1) for x in a.evidence)}
    s = build(dirs=[d.expanduser() for d in a.dir] or [AC.root()], out=a.out.expanduser(), since=a.since, roles=roles, evidence=ev,
              include_unlisted=a.include_unlisted)
    print(f"폴더: {a.out}")
    for g, v in s["groups"].items():
        print(f"  {g:<24} {v['stats']['calls']:>4}건  파일 {len(v['files'])}개  {', '.join(v['models'])}")
    print(f"  zip: {a.out / ZIP_NAME}  기능 파일 {len(s['export']['files'])}개 · 없는 기능 {s['export']['missing'] or '없음'}")
    bad = {k: v for k, v in s["scan_folder"].items() if v and (k in AU.SECRET_FIELDS or k.startswith("pii_"))}
    print(f"  폴더 흔적: {bad or '0'} · 필수 항목 ✗ 셀 {s['audit_missing_cells']}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
