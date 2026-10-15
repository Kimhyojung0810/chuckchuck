"""
같은 첫 질문에 성질이 다른 답(A~F)을 넣어 — 판정 · 반응 · 꼬리질문 · claim 이 실제로 답에 따라 달라지는지 잰다 (2026-10-13 대화 재설계 1단계).

  python etc/labs/dialogue_probe/run.py --base http://127.0.0.1:8810 --session <리허설 세션 id> --qid <질문 id>

실 API(판정 LLM)를 부른다 — 답 하나에 1콜. 결과는 out/<시각>.json 과 화면 표.
"""
import argparse, json, time, urllib.request, concurrent.futures as cf
from pathlib import Path

ANSWERS = {
    "A 정확·충분": "25도 항온조에서 방전심도 100%로 매번 끝까지 충방전한 가속 조건, 그리고 군마다 셀 4개라는 조건에서 나온 값이에요. 같은 2C라도 45도로 올리면 유지율이 더 떨어졌으니 온도에 따라 달라지고, 실사용과는 다를 수 있어요.",
    "B 일부만": "온도를 25도로 맞췄을 때 나온 결과예요.",
    "C 모호": "음… 실험실에서 한 거라서 상황마다 좀 다를 것 같아요.",
    "D 틀린 전제": "45도처럼 높은 온도에서만 측정했을 때 나온 결과라서, 상온에서는 거의 안 깎여요.",
    "E1 모르겠어요(말)": "잘 모르겠어요.",
    "E2 모르겠어요(버튼)": "",
    "G 반대 의견": "저는 그 조건이 중요하지 않다고 봐요. 2C면 어떤 조건이든 열이 나서 결국 비슷하게 깎일 거예요.",
}

def post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t = time.time()
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read()), round(time.time() - t, 1)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8810")
    ap.add_argument("--session", required=True)
    ap.add_argument("--qid", required=True)
    ap.add_argument("--question", default="")
    a = ap.parse_args()
    path = f"/api/v1/sessions/{a.session}/qa/judge"
    def one(item):
        k, ans = item
        body = {"session_id": a.session, "question_id": a.qid, "answer": ans, "history": [], "give_up": k.startswith("E2")}
        if a.question:
            body["question"] = {"id": a.qid, "question": a.question}
        try:
            j, sec = post(a.base, path, body)
        except Exception as e:  # noqa: BLE001 — 실험 기록
            return k, {"error": str(e)}, 0
        return k, j, sec
    rows = {}
    with cf.ThreadPoolExecutor(4) as ex:
        for k, j, sec in ex.map(one, ANSWERS.items()):
            rows[k] = {"answer": ANSWERS[k], "sec": sec, **{f: j.get(f) for f in ("verdict", "score", "passed", "mastered", "react", "followup", "claim", "missing_points", "coach_stage", "error")}}
    # 관점 바꾸기 (F — 주제 전환)
    try:
        j, sec = post(a.base, f"/api/v1/sessions/{a.session}/qa/reframe", {"session_id": a.session, "question_id": a.qid, "perspective": "counter"})
        rows["F 관점 바꾸기(반례)"] = {"sec": sec, "question": (j.get("question") or {}).get("question") if isinstance(j.get("question"), dict) else j}
    except Exception as e:  # noqa: BLE001
        rows["F 관점 바꾸기(반례)"] = {"error": str(e)}
    out = Path(__file__).parent / "out"; out.mkdir(exist_ok=True)
    f = out / time.strftime("%Y%m%dT%H%M%S.json")
    f.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    for k, r in rows.items():
        print(f"\n■ {k}  ({r.get('sec')}s)  verdict={r.get('verdict')} score={r.get('score')} mastered={r.get('mastered')} stage={r.get('coach_stage')!r}")
        for f_ in ("answer", "react", "claim", "followup", "missing_points", "question", "error"):
            if r.get(f_):
                print(f"   {f_:9s} {r[f_]}")
    print("\n→", f)

if __name__ == "__main__":
    main()
