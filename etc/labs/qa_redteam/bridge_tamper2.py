import json, time, secrets, urllib.request
from common import OUT, rj, wj
B = "http://127.0.0.1:8799"
def post(path, body):
    req = urllib.request.Request(B + path, data=json.dumps(body, ensure_ascii=False).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
d = OUT / "decks" / "yield_gap"
sid = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_" + secrets.token_hex(4)
print(post("/api/v1/session/artifacts", {"session_id": sid, "graph": rj(d / "graph.json"), "alignment": None, "flow": None, "transcript": None, "context": rj(d / "context.json")}))
q = rj(d / "questions_t10.json")["questions"][1]  # yield Q2 trap (-0.3)
ans = "거래 비용 -0.3은 다섯 요인 중에 가장 작은 값이라 비용 부담이 크지 않다는 걸 보여 줘요."
strip = {**q, "trap": False, "trap_premise": None, "answer_gist": "거래 비용 -0.3은 다섯 요인 중 가장 작은 값으로, 비용 부담이 상대적으로 작다는 것을 보여 줘요.", "basis": {}}
rows = []
for name, qq in (("honest_trap", q), ("trap_stripped", strip)):
    code, j = post(f"/api/v1/sessions/{sid}/qa/judge", {"session_id": sid, "question_id": qq["id"], "answer": ans, "history": [], "question": qq,
                                                         "give_up": False, "prior_answers": [], "hints_shown": []})
    rows.append({"name": name, "code": code, "verdict": j.get("verdict"), "score": j.get("score"), "passed": j.get("passed"), "react": j.get("react")})
    print(name, code, j.get("verdict"), j.get("score"), j.get("passed"), j.get("react"))
wj(OUT / "bridge_tamper2.json", {"sid": sid, "rows": rows})
