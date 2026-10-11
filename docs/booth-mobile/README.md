# 부스 모바일 — /hi 팀 소개 · #/tour 체험 투어 (2026-10-11 ~)

결선 부스(11/3~5)에서 방문객이 QR 을 찍으면 **폰에서** 이렇게 흐른다.

```
/hi  ─ 척척발표 소개 ─ 팀원 카드(한 명씩) ─ 「척척발표 살펴보기」
  └▶ #/tour/deck ▶ #/tour/present ▶ #/tour/analysis ▶ #/tour/qa ▶ #/tour/report
        └▶ 「내 자료로 직접 해 보기」(#/rehearsal, 실제 흐름) · 「팀 소개로 돌아가기」(#/hi)
```

왜 투어인가: 10/7 QR 실측 64명 → 덱 선택 14 → 리허설 8 → 분석 3 → 답변 2. 폰 방문객 97% 가 실제 흐름에서 빠졌다.
투어는 **녹화된 응답만 재생**한다 — API 호출 0, 카메라·마이크 권한 없음, 인앱 브라우저(카카오톡·네이버·인스타)에서도 끝까지 돈다.

## 계약 (단일 원본)

| 경계 | 원본(기계 검사) | 사람용 설명 | 데이터 파일 | 쓰는 쪽 |
|---|---|---|---|---|
| 투어 녹화 데이터 | [`tour.schema.json`](tour.schema.json) | [`tour-schema.md`](tour-schema.md) | `demo/YEHS_demo/data/tour/<id>.json` (`_example.json` = 형식 예시) | `#/tour/*` 화면 |
| 팀 카드 | [`team.schema.json`](team.schema.json) | [`team-schema.md`](team-schema.md) | `demo/YEHS_demo/data/team.json` | `/hi` 화면 |

- **스키마가 원본이다.** 문서·예시·화면 코드가 스키마와 어긋나면 스키마를 기준으로 고친다.
- 검사: `python -m pytest tests/test_booth_mobile_contract.py -q` — 스키마 + 짝 맞춤(장 번호·그림 파일·공개 여부·시각 차례·그래프 끝점·「잘 답한 답」=good).
  `data/tour/` 에 파일을 넣으면 따로 등록하지 않아도 이 테스트가 집어 검사한다.
- 공개 서빙: `demo/static_assets.py` `_PUBLIC_PATH` 에 `data/team.json` · `data/tour/<이름>.json` · `assets/team/<이름>.(webp|png|jpg)` 을 열었다.
  다른 `data/*.json` 은 그대로 팀 전용이다. 새 종류의 파일을 쓰면 여기부터 연다(안 열면 공개 사이트에서 404).
- 주소: 브리지 `hash_route_for` 가 `/hi` → `/index.html#/hi`, `/tour/deck` → `#/tour/deck` 로 보낸다(서버 수정 없음). 앱 `route()` 에 `hi` · `tour` 를 더하는 건 화면 담당.

## 바꾸는 순서 (contract-first)

1. 필요한 칸·값을 말한다(어느 화면이 무엇을 그리려고).
2. **스키마부터** 고친다 → 사람용 문서 → `_example.json` → 테스트 초록.
3. 그다음 화면 코드를 고친다. 깨지는 변경이면 `version` 을 올리고, 화면은 모르는 버전을 「체험을 불러오지 못했어요」 로 처리한다.

## 공통 규칙

- 평가는 숫자 대신 **3단계 말**: `good`=「좋아요」 · `fair`=「보통」 · `practice`=「더 연습」. 화면 글자는 이 셋으로 고정.
- 판정 낱말은 새로 짓지 않는다 — 그래프 상태는 정합 판정 enum(`aligned|justified_skip|missing|contradiction`), 답 판정은 F-09 enum(`good|partial|wrong|unknown`), 근거 역할은 `covered|missing|conflict`. 판정 색 5종과 짝이다.
- **정직 표시**: `source.kind=example` 이면 화면에 예시라고 적는다. 녹화본도 「미리 녹화한 체험이에요」 를 남긴다(CLAUDE.md §3-4 「샘플 표시는 정직하게」).
- 팀 카드의 `did` 는 저장소 이력 등 확인할 수 있는 사실만, `quote` 는 본인이 준 말만. 모르면 `draft:true`.
