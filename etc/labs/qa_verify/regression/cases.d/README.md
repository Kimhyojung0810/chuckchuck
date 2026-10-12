# 회귀 사례 조각 (cases.d)

작업 묶음마다 `<묶음>.json` 을 하나 두고 `{"cases": [...]}` 꼴로 사례를 적는다. `regress.load_cases` 가
`../cases.json` 뒤에 파일 이름 순으로 붙여 읽는다. id 가 겹치면 quick 이 바로 멈춘다 — 여러 묶음이
한 cases.json 끝에 동시에 덧붙여 합칠 때마다 JSON 충돌이 나서 나눴다 (09-30).
