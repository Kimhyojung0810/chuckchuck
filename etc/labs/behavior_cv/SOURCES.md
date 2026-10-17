# 행동 추적 실험실 — 쓴 자료 · 출처 · 라이선스

이 실험실은 **자료를 git 에 넣지 않는다.** 스크립트가 처음 돌 때 아래 주소에서 받아
`/data/models/_runs/behavior-cv/lab/assets/` 에 둔다 (render_heads.py `fetch_assets()`, gen.py).
만든 영상 · 정답(`lab/clips/`)도 git 밖이다.

| 자료 | 어디에 쓰나 | 출처 URL | 라이선스 | 바꾼 것 |
|---|---|---|---|---|
| **Lee Perry-Smith 3D 머리 스캔** (`LeePerrySmith.glb`, `Map-COL.jpg`, `Infinite-Level_02_Tangent_SmoothUV.jpg`, `LeePerrySmith_License.txt`) | 같은 사람의 정면 · 3/4 · 옆 · 숙임 · 기울임을 각도 정답과 함께 그린다 (아틀라스 3,552장) | https://github.com/mrdoob/three.js/tree/r160/examples/models/gltf/LeePerrySmith (원작: Infinite-Realities, http://www.ir-ltd.net/ · triplegangers.com 작업 기반) | **CC BY 3.0 Unported** — 「Infinite, 3D Head Scan by Lee Perry-Smith is licensed under a Creative Commons Attribution 3.0 Unported License. Based on a work at www.triplegangers.com.」 | 스캔은 눈을 감고 찍혀 있어 **뜬 눈 · 반쯤 뜬 눈을 텍스처에 그려 넣었고**, 스캔 표식(빨간 점 2개)을 지웠다. **안경 테**를 그려 넣은 판을 따로 만들었다. 피부 톤은 색 배수(중간 · 짙음)로 바꿔 쓴다. 흉상 아래에 셔츠 · 몸통을 그려 붙였다. (CC BY 3.0 §4(b) 변경 표시) |
| **three.js r160** (`three.module.js`, `GLTFLoader.js`, `BufferGeometryUtils.js`) | 헤드리스 크롬 WebGL 로 머리를 그린다 | https://cdn.jsdelivr.net/npm/three@0.160.0/ | MIT | 없음 |
| **모나리자** (`mona-lisa.png`, OpenCV 시험 자료) | s12_poster — 벽에 걸린 실사 얼굴 포스터(헛얼굴 방해물) | https://raw.githubusercontent.com/opencv/opencv_extra/4.x/testdata/cv/cascadeandhog/images/mona-lisa.png (원작: 레오나르도 다빈치, 1503–1519) | **퍼블릭 도메인** (원작 저작권 만료). opencv_extra 저장소는 Apache-2.0 / BSD — 이 파일은 PD 작품 복제 | 흑백 · 크기 조절 · 액자 |
| **OpenCV Haar 캐스케이드** (`haarcascade_frontalface_default.xml` · `_alt2` · `profileface` · `eye`) | 참조 엔진 · 아틀라스 검증 | opencv-python-headless 4.10.0.84 에 들어 있는 `cv2.data.haarcascades` | Intel License Agreement (BSD 3조항 형식) — 파일 머리에 적힘 | 없음 |
| 방 · 책장 · 창 · 화분 · 손 · 팔 · 셔츠 | 배경 · 손짓 | gen.py 가 OpenCV 도형으로 그림 | (자체 생성) | — |

## 왜 사진 대신 3D 스캔인가
- 같은 사람의 **여러 각도 사진**(정면 · 좌우 옆 · 아래)을 자유 라이선스로 각도 정답까지 얻기 어렵다.
  위키미디어 공용의 옛 범죄자 기록 사진(정면+옆 쌍, PD)은 있지만 아래 보기 · 연속 회전 · 3/4 각도가 없다.
- 실제 사람 스캔(사진 텍스처)을 그리면 Haar 가 실제로 얼굴로 잡는다 — `lab/atlas_validation.md` 에서
  정면 캐스케이드는 |yaw| ≤ 30°(대체로 45°까지 일부), 옆얼굴 캐스케이드는 15~60° 를 잡고 75° 넘으면 둘 다 놓친다.
  OpenCV 문서 · 근거조사(2026-10-17 §3)의 「정면 ±45°」 와 같은 모양이라 합성 얼굴이 쓸 만하다고 봤다.
- 한계: 한 사람(성인 남성 · 민머리)뿐이고 눈은 그린 것이다 → README 「한계」.
