"""
[F-18 내부] Mi:dm LoRA 태거 — 반복(REP) 어댑터와 간투어(FIL) 어댑터(3시드 앙상블)를 한 베이스 모델에 얹어 돌린다.

호출: f18_habits.extract_habits(provider="lora") → tag_habits()
API: POST /api/v1/habits (HABIT_PROVIDER=lora 일 때)
스키마: HabitSpan {kind,text,start_sec,end_sec,slide_no}

왜 두 갈래인가 (AI Hub 공적말하기 640건, 원고 그룹 분할 held-out 62건 — 옛 docs/DATA_PIPELINE.md §3):
  · REP — 통합 태거(tagger_seed42) 를 무보정 greedy(repetition_penalty=1.0) 로. F1 0.686±0.027.
    반복이 정답이라 페널티를 걸면 정답 생성 자체가 막힌다.
  · FIL — 간투어 전용 태거 3시드(fil_seed42/43/44) 를 repetition_penalty=1.2 로 돌리고 min 방식(세 시드가 모두
    찾은 것만) 으로 합친다. P 0.9927 / R 0.7253 / F1 0.838. 페널티 없이 greedy 로 돌리면 긴 발화에서 같은 줄을
    되풀이하는 생성 붕괴(62건 중 48건) 가 난다 — 그래서 REP 와 같은 패스로 못 뽑고 따로 돌린다.

이 파일은 설정·프롬프트·파싱·시간 위치 찾기·투표만 맡는다 (torch 없이 테스트된다).
모델을 올리고 생성하는 일은 _lora_runtime.py 가 맡는다.

환경변수 (전부 없어도 된다 — 기본 위치를 찾아 본다):
  CHUCKCHUCK_LORA_BASE            베이스 모델 폴더나 HF id (기본: /data/models/Midm-2.0-Base-Instruct 가 있으면 그것)
  CHUCKCHUCK_LORA_REP_PATH        REP 어댑터 폴더 (옛 이름 CHUCKCHUCK_LORA_PATH 도 받는다)
  CHUCKCHUCK_LORA_FIL_PATHS       FIL 어댑터 폴더들, 쉼표로 (기본: <루트>/fil_seed{42,43,44}/final 중 있는 것)
  CHUCKCHUCK_LORA_FIL_MIN_VOTES   몇 시드가 찾아야 인정하나 (기본: FIL 어댑터 수 = min 방식)
  CHUCKCHUCK_LORA_FIL_RP          FIL repetition_penalty (기본 1.2)
  CHUCKCHUCK_LORA_FIL_PROMPT      fil(기본: 간투어 전용 프롬프트) | unified(REP/FIL/WR 통합 프롬프트로 학습한 어댑터일 때)
  CHUCKCHUCK_LORA_KINDS           REP 어댑터 출력에서 받을 태그 (기본 REP — 옛 설정). FIL 어댑터가 있으면 FIL 은 늘 그쪽에서
  CHUCKCHUCK_LORA_CHUNK_CHARS     전사문을 이 글자 수 안팎으로 잘라 따로 태깅 (기본 1600 — 학습 전사문 길이)
  CHUCKCHUCK_LORA_MAX_BATCH       한 번에 생성할 행 수 (기본 8, 1 이면 학습 평가와 똑같이 한 줄씩)
어댑터 폴더에 chuckchuck_task.json(etc/habits_lora/train.py 가 쓴다)이 있으면 그 프롬프트·디코딩 설정이 우선이다.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .contracts import HabitSpan, Transcript

MODEL_ID = "K-intelligence/Midm-2.0-Base-Instruct"
LOCAL_BASE = Path("/data/models/Midm-2.0-Base-Instruct")
#: 학습 산출물·팀이 건네준 어댑터를 두는 곳 (루트 디스크가 작아 /data 아래).
RUNS_ROOT = Path("/data/models/_runs/habits-lora")
#: 팀 GPU 서버의 옛 기본 경로 — 그 서버에서 띄울 때를 위해 후보로 남긴다.
LEGACY_REP = Path("/home/ubuntu/workspace/20_AIHub_data/runs/tagger_seed42/final")
DEFAULT_ADAPTER = LEGACY_REP  # 옛 이름 (doctor·문서가 참조)
FIL_SEEDS = (42, 43, 44)
MAX_NEW_TOKENS = 512
DEFAULT_CHUNK_CHARS = 1600
DEFAULT_MAX_BATCH = 8
TASK_FILE = "chuckchuck_task.json"

SYSTEM_PROMPT = (
    "너는 한국어 공적 말하기 전사문에서 발화 오류 구간을 찾아내는 전문 주석기다.\n"
    "다음 세 가지만 찾는다.\n"
    "REP: 같은 말을 더듬거나 되풀이한 구간 (예: '지도 지도력은')\n"
    "FIL: 의미 없는 간투어 (예: '어', '음')\n"
    "WR: 잘못 발음했거나 잘못 쓴 낱말 (예: '지속성')\n"
    "출력은 '태그<TAB>원문구간' 형식의 줄 목록이며 REP, FIL, WR 순서로 적는다.\n"
    "해당하는 구간이 없으면 NONE 한 줄만 출력한다."
)
USER_TEMPLATE = "다음 발표 전사문에서 REP/FIL/WR 구간을 모두 찾아라.\n\n{stt_text}"

# 태그 하나짜리 프롬프트 — etc/habits_lora/train.py 가 같은 상수로 학습 데이터를 만든다.
TASK_PROMPTS: dict[str, tuple[str, str]] = {
    "REP": (
        "너는 한국어 공적 말하기 전사문에서 발화 오류 구간을 찾아내는 전문 주석기다.\n"
        "REP: 같은 말을 더듬거나 되풀이한 구간 (예: '지도 지도력은') 만 찾는다.\n"
        "출력은 'REP<TAB>원문구간' 형식의 줄 목록이며 전사문에 나온 순서대로 적는다.\n"
        "해당하는 구간이 없으면 NONE 한 줄만 출력한다.",
        "다음 발표 전사문에서 REP 구간을 모두 찾아라.\n\n{stt_text}",
    ),
    "FIL": (
        "너는 한국어 공적 말하기 전사문에서 발화 오류 구간을 찾아내는 전문 주석기다.\n"
        "FIL: 의미 없는 간투어 (예: '어', '음') 만 찾는다.\n"
        "출력은 'FIL<TAB>원문구간' 형식의 줄 목록이며 전사문에 나온 순서대로 적는다.\n"
        "해당하는 구간이 없으면 NONE 한 줄만 출력한다.",
        "다음 발표 전사문에서 FIL 구간을 모두 찾아라.\n\n{stt_text}",
    ),
}
TAGS = ("REP", "FIL", "WR")
_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w가-힣]+", re.UNICODE)


class LoraNotReady(RuntimeError):
    """미리 올리기(preload) 가 아직 끝나지 않았다 — 호출측은 규칙으로 대신한다."""


# ─── 설정 ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TaskSpec:
    system_prompt: str
    user_template: str
    repetition_penalty: float = 1.0
    max_new_tokens: int = MAX_NEW_TOKENS


@dataclass(frozen=True)
class AdapterSpec:
    name: str                 # PEFT 안의 어댑터 이름 (rep · fil0 · fil1 …)
    path: Path
    role: str                 # REP | FIL
    take: frozenset[str]      # 이 어댑터 출력에서 받을 태그
    task: TaskSpec


@dataclass(frozen=True)
class TaggerConfig:
    base: str
    rep: AdapterSpec | None
    fil: tuple[AdapterSpec, ...] = ()
    fil_min_votes: int = 1
    chunk_chars: int = DEFAULT_CHUNK_CHARS
    max_batch: int = DEFAULT_MAX_BATCH
    missing: tuple[str, ...] = ()   # 설정했는데 adapter_config.json 이 없는 경로

    @property
    def adapters(self) -> tuple[AdapterSpec, ...]:
        return ((self.rep,) if self.rep else ()) + self.fil

    def key(self) -> tuple:
        return (self.base,) + tuple((a.name, str(a.path)) for a in self.adapters)


def _is_adapter(p: Path) -> bool:
    return p.is_dir() and (p / "adapter_config.json").is_file()


def _read_task(path: Path, default: TaskSpec) -> TaskSpec:
    f = path / TASK_FILE
    if not f.is_file():
        return default
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    return TaskSpec(
        system_prompt=str(d.get("system_prompt") or default.system_prompt),
        user_template=str(d.get("user_template") or default.user_template),
        repetition_penalty=float(d.get("repetition_penalty", default.repetition_penalty)),
        max_new_tokens=int(d.get("max_new_tokens", default.max_new_tokens)),
    )


def _split_paths(raw: str) -> list[Path]:
    parts = re.split(r"[,\n" + re.escape(os.pathsep) + r"]", raw or "")
    return [Path(p.strip()).expanduser() for p in parts if p.strip()]


def _env_int(env, name: str, default: int, lo: int = 1) -> int:
    try:
        return max(lo, int(str(env.get(name, "")).strip() or default))
    except ValueError:
        return default


def _base(env) -> str:
    raw = str(env.get("CHUCKCHUCK_LORA_BASE", "")).strip()
    if raw:
        return raw
    return str(LOCAL_BASE) if (LOCAL_BASE / "config.json").is_file() else MODEL_ID


def _rep_spec(env, fil_on: bool, missing: list[str]) -> AdapterSpec | None:
    raw = str(env.get("CHUCKCHUCK_LORA_REP_PATH") or env.get("CHUCKCHUCK_LORA_PATH") or "").strip()
    # 설정한 경로가 없으면(.env 의 자리표시 /path/to/... 등) 기본 위치를 이어서 찾는다 — 경로는 missing 에 남긴다
    if raw and not _is_adapter(Path(raw).expanduser()):
        missing.append(raw)
    cands = ([Path(raw).expanduser()] if raw else []) + [RUNS_ROOT / "rep_seed42" / "final", LEGACY_REP]
    path = next((p for p in cands if _is_adapter(p)), None)
    if path is None:
        return None
    kinds = {k.strip() for k in str(env.get("CHUCKCHUCK_LORA_KINDS", "REP")).upper().split(",") if k.strip()}
    take = (kinds & {"REP", "FIL"}) or {"REP"}
    if fil_on:
        take.discard("FIL")   # FIL 은 전용 어댑터가 맡는다 — 통합 태거의 FIL 은 퇴행했다(0.519)
    task = _read_task(path, TaskSpec(SYSTEM_PROMPT, USER_TEMPLATE, 1.0))
    return AdapterSpec("rep", path, "REP", frozenset(take), task)


def _fil_specs(env, missing: list[str]) -> tuple[AdapterSpec, ...]:
    raw = str(env.get("CHUCKCHUCK_LORA_FIL_PATHS", "")).strip()
    if raw.lower() in ("off", "none", "0"):
        return ()
    given = _split_paths(raw)
    missing.extend(str(p) for p in given if not _is_adapter(p))
    paths = [p for p in given if _is_adapter(p)]
    if not paths:  # 설정이 없거나 설정한 경로가 하나도 없으면 기본 위치
        paths = [p for p in (RUNS_ROOT / f"fil_seed{s}" / "final" for s in FIL_SEEDS) if _is_adapter(p)]
    try:
        rp = float(str(env.get("CHUCKCHUCK_LORA_FIL_RP", "")).strip() or 1.2)
    except ValueError:
        rp = 1.2
    unified = str(env.get("CHUCKCHUCK_LORA_FIL_PROMPT", "fil")).strip().lower() == "unified"
    sys_p, user_t = (SYSTEM_PROMPT, USER_TEMPLATE) if unified else TASK_PROMPTS["FIL"]
    default = TaskSpec(sys_p, user_t, rp)
    return tuple(
        AdapterSpec(f"fil{i}", p, "FIL", frozenset({"FIL"}), _read_task(p, default))
        for i, p in enumerate(paths)
    )


def load_config(env=None) -> TaggerConfig:
    """환경변수 → TaggerConfig. 어댑터가 하나도 없으면 rep=None·fil=() 이다."""
    env = os.environ if env is None else env
    missing: list[str] = []
    fil = _fil_specs(env, missing)
    rep = _rep_spec(env, bool(fil), missing)
    votes = _env_int(env, "CHUCKCHUCK_LORA_FIL_MIN_VOTES", len(fil) or 1)
    return TaggerConfig(
        base=_base(env),
        rep=rep,
        fil=fil,
        fil_min_votes=min(votes, len(fil)) if fil else 1,
        chunk_chars=_env_int(env, "CHUCKCHUCK_LORA_CHUNK_CHARS", DEFAULT_CHUNK_CHARS, lo=200),
        max_batch=_env_int(env, "CHUCKCHUCK_LORA_MAX_BATCH", DEFAULT_MAX_BATCH),
        missing=tuple(missing),
    )


def default_adapter_path() -> Path:
    """옛 API — REP 어댑터 경로 (없으면 옛 기본값)."""
    cfg = load_config()
    return cfg.rep.path if cfg.rep else DEFAULT_ADAPTER


def adapter_available(path: Path | None = None) -> bool:
    """어댑터가 하나라도 있으면 True. path 를 주면 그 폴더만 본다 (옛 API)."""
    if path is not None:
        return _is_adapter(Path(path))
    return bool(load_config().adapters)


# ─── 파싱 · 위치 찾기 · 투표 ───────────────────────────────────────────────────

def _normalize(text: str) -> str:
    return _WS.sub(" ", (text or "").strip())


def _tok(text: str) -> str:
    return _PUNCT.sub("", (text or "").strip().lower())


def parse_tag_lines(raw: str) -> list[tuple[str, str]]:
    """모델 출력 → [(TAG, text), ...]."""
    out: list[tuple[str, str]] = []
    for line in (raw or "").strip().splitlines():
        line = line.strip()
        if not line or line == "NONE":
            continue
        tag, sep, body = line.partition("\t")
        if not sep:
            tag, sep, body = line.partition(" ")
        tag = tag.strip().upper()
        body = _normalize(body)
        if tag in TAGS and body:
            out.append((tag, body))
    return out


def _words(transcript: Transcript) -> list:
    words = list(transcript.words)
    if not words:
        for sp in transcript.by_slide:
            words.extend(sp.words)
    return words


def chunk_words(words: list, max_chars: int) -> list[tuple[int, int]]:
    """단어열을 글자 수 max_chars 안팎으로 자른 [start, end) 구간들. 단어 중간에서 자르지 않는다."""
    chunks: list[tuple[int, int]] = []
    start, size = 0, 0
    for i, w in enumerate(words):
        n = len(w.text) + 1
        if size and size + n > max_chars:
            chunks.append((start, i))
            start, size = i, 0
        size += n
    if start < len(words):
        chunks.append((start, len(words)))
    return chunks


def _match_at(toks: list[str], i: int, want: str) -> int | None:
    """toks[i:] 의 앞쪽 몇 단어를 이어 붙인 것이 want 와 같으면 끝 위치(배타)."""
    joined = ""
    for j in range(i, len(toks)):
        joined += toks[j]
        if joined == want:
            return j + 1
        if len(joined) >= len(want) or not want.startswith(joined):
            return None
    return None


def locate_ordered(spans: list[str], toks: list[str]) -> list[tuple[int, int] | None]:
    """
    스팬 텍스트들을 단어열(정규화 토큰) 위의 [i, j) 구간으로. 모델은 전사문에 나온 순서대로 적으므로
    커서를 앞으로만 옮긴다 — 같은 「어」 가 열 번 나와도 k번째 줄이 k번째 「어」 에 붙는다.
    앞쪽에서 못 찾으면 아직 안 쓴 앞부분에서 다시 찾고, 그래도 없으면 None (지어낸 스팬일 수 있어 버린다).
    """
    used: set[int] = set()
    cursor = 0
    out: list[tuple[int, int] | None] = []
    for span in spans:
        want = "".join(_tok(t) for t in span.split())
        hit = None
        if want:
            for lo, hi in ((cursor, len(toks)), (0, cursor)):
                for i in range(lo, hi):
                    if i in used or not toks[i] or not want.startswith(toks[i]):
                        continue
                    end = _match_at(toks, i, want)
                    if end is not None and not used.intersection(range(i, end)):
                        hit = (i, end)
                        break
                if hit:
                    break
        if hit:
            used.update(range(*hit))
            cursor = hit[1]
        out.append(hit)
    return out


def vote_positions(per_seed: list[list[tuple[int, int]]], min_votes: int) -> list[tuple[int, int]]:
    """시드마다 찾은 구간 → min_votes 시드 이상이 같은 구간을 찾은 것만. 순서 매핑과 합치면 「min 방식」 카운트와 같다."""
    c = Counter(pos for seed in per_seed for pos in set(seed))
    return sorted(pos for pos, n in c.items() if n >= min_votes)


# ─── 태깅 ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GenRequest:
    adapter: str
    system_prompt: str
    user_text: str
    repetition_penalty: float
    max_new_tokens: int


@dataclass
class TagResult:
    spans: list[HabitSpan]
    covered: dict[str, str]                  # 태그 → 탐지기 이름 (lora · lora-ensemble×3)
    stats: dict = field(default_factory=dict)


def _slide_at(transcript: Transcript, t: float) -> int | None:
    for sp in transcript.by_slide:
        if sp.start_sec <= t < sp.end_sec:
            return sp.slide_no
        if sp.words and sp.words[0].start_sec <= t <= sp.words[-1].end_sec:
            return sp.slide_no
    return None


def _span(kind: str, words: list, i: int, j: int, transcript: Transcript) -> HabitSpan:
    start = words[i].start_sec
    return HabitSpan(
        kind=kind,
        text=" ".join(w.text for w in words[i:j]),
        start_sec=start,
        end_sec=words[j - 1].end_sec,
        slide_no=_slide_at(transcript, start),
    )


def build_requests(cfg: TaggerConfig, words: list) -> tuple[list[tuple[int, int]], list[GenRequest]]:
    chunks = chunk_words(words, cfg.chunk_chars)
    reqs: list[GenRequest] = []
    for a, b in chunks:
        text = " ".join(w.text for w in words[a:b])
        for ad in cfg.adapters:
            reqs.append(GenRequest(
                adapter=ad.name,
                system_prompt=ad.task.system_prompt,
                user_text=ad.task.user_template.replace("{stt_text}", text),
                repetition_penalty=ad.task.repetition_penalty,
                max_new_tokens=ad.task.max_new_tokens,
            ))
    return chunks, reqs


def covered_kinds(cfg: TaggerConfig) -> dict[str, str]:
    out: dict[str, str] = {}
    if cfg.rep:
        for k in sorted(cfg.rep.take):
            out[k] = "lora"
    if cfg.fil:
        out["FIL"] = "lora" if len(cfg.fil) == 1 else f"lora-ensemble×{len(cfg.fil)}"
    return out


def tag_habits(transcript: Transcript, *, config: TaggerConfig | None = None, runner=None) -> TagResult:
    """
    Transcript → TagResult. runner 는 generate_batch(list[GenRequest]) -> list[str] 를 가진 객체
    (기본: _lora_runtime 의 공유 러너 — 베이스 모델 한 벌에 어댑터 여럿).
    REP 어댑터는 rp 1.0, FIL 어댑터들은 rp 1.2 로, 같은 배치 안에서 행마다 따로 적용된다.
    """
    cfg = config or load_config()
    if not cfg.adapters:
        raise FileNotFoundError("LoRA adapter not found (REP·FIL 둘 다 없음)")
    words = _words(transcript)
    covered = covered_kinds(cfg)
    if not words:
        return TagResult([], covered, {"chunks": 0})
    if runner is None:
        from . import _lora_runtime
        runner = _lora_runtime.get_runner(cfg)

    chunks, reqs = build_requests(cfg, words)
    outs = runner.generate_batch(reqs)
    if len(outs) != len(reqs):
        raise RuntimeError(f"runner returned {len(outs)} outputs for {len(reqs)} requests")

    n_ad = len(cfg.adapters)
    spans: list[HabitSpan] = []
    unlocated: Counter = Counter()
    raw_fil: list[int] = []
    for ci, (a, b) in enumerate(chunks):
        cw = words[a:b]
        toks = [_tok(w.text) for w in cw]
        row = outs[ci * n_ad:(ci + 1) * n_ad]
        fil_seeds: list[list[tuple[int, int]]] = []
        for ad, raw in zip(cfg.adapters, row):
            tags = [(t, s) for t, s in parse_tag_lines(raw) if t in ad.take]
            for kind in sorted({t for t, _ in tags}):
                texts = [s for t, s in tags if t == kind]
                locs = locate_ordered(texts, toks)
                miss = sum(1 for x in locs if x is None)
                if miss:
                    unlocated[kind] += miss
                hits = [x for x in locs if x is not None]
                if ad.role == "FIL":
                    fil_seeds.append(hits)
                    raw_fil.append(len(hits))
                else:
                    spans.extend(_span(kind, cw, i, j, transcript) for i, j in hits)
            if ad.role == "FIL" and not tags:
                fil_seeds.append([])
                raw_fil.append(0)
        if cfg.fil:
            for i, j in vote_positions(fil_seeds, cfg.fil_min_votes):
                spans.append(_span("FIL", cw, i, j, transcript))

    spans.sort(key=lambda s: (s.start_sec, s.kind))
    stats = {
        "chunks": len(chunks),
        "rows": len(reqs),
        "unlocated": dict(unlocated),
        "fil_per_seed": raw_fil,
        "fil_min_votes": cfg.fil_min_votes if cfg.fil else None,
    }
    return TagResult(spans, covered, stats)


def tag_spans(transcript: Transcript, adapter: str | Path | None = None) -> list[HabitSpan]:
    """옛 API — HabitSpan 목록만. adapter 를 주면 그 폴더를 REP 어댑터로 쓴다."""
    cfg = load_config()
    if adapter is not None:
        p = Path(adapter)
        if not _is_adapter(p):
            raise FileNotFoundError(f"LoRA adapter not found: {p}")
        rep = AdapterSpec("rep", p, "REP", cfg.rep.take if cfg.rep else frozenset({"REP"}),
                          _read_task(p, TaskSpec(SYSTEM_PROMPT, USER_TEMPLATE, 1.0)))
        cfg = TaggerConfig(cfg.base, rep, cfg.fil, cfg.fil_min_votes, cfg.chunk_chars, cfg.max_batch)
    return tag_habits(transcript, config=cfg).spans
