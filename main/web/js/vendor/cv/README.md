# 카메라 판단용 Haar 캐스케이드 (발표 태도 · 베타)

`js/behavior_cv_worker.js` 가 받는 고전 OpenCV 검출기 파일이다. **학습 신경망이 아니다** — Viola-Jones(2001) 방식의
부스팅 캐스케이드로, OpenCV 저장소에 2000년대부터 들어 있는 파일을 바꾸지 않고 그대로 둔다.

| 파일 | 원본 | 라이선스 |
|---|---|---|
| `haarcascade_frontalface_default.xml` | opencv/opencv@4.10.0 `data/haarcascades/` | Intel License Agreement (BSD 계열, 파일 머리말 그대로 보존) |
| `haarcascade_profileface.xml` | 같은 곳 (David Bradley, Princeton) | Intel License Agreement |
| `haarcascade_eye.xml` | 같은 곳 (Shameem Hameed) | Intel License Agreement |

sha256 (2026-10-17 받음):

```
0f7d4527844eb514d4a4948e822da90fbb16a34a0bbbbc6adc6498747a5aafb0  haarcascade_frontalface_default.xml
b39a4a3be45539db146a7fc1d3e761a292c196eb88421185e6a615b3055e612d  haarcascade_profileface.xml
71cc64fc305a355dc60067880f6fbbd43dd155bd63ee3844661a1bda34b2fd8c  haarcascade_eye.xml
```

OpenCV.js 본체(`js/vendor/opencv.js`, Apache-2.0, 10MB)는 git 에 없다 — `etc/scripts/get_opencv.sh` 로 받는다.
로컬 사본이 없으면 워커가 jsDelivr(`@techstark/opencv-js@4.10.0-release.1`)로 간다. 캐스케이드도 이 폴더에 없으면 jsDelivr 의 같은 판으로 간다.

고르기 (노드 벤치 2026-10-17, 320px · 모나리자 합성 프레임): 정면 `default` + 눈 `eye` 가 `alt2` + `eye_tree_eyeglasses` 보다
두 눈 검출이 많고(26/30 대 2/30) 빨랐다(17ms 대 29ms). 옆얼굴 캐스케이드는 코가 **화면 왼쪽**인 얼굴을 찾는다 —
Getty 「Portrait Head of Julia Titi」 left/right profile 사진으로 확인. 오른쪽은 좌우를 뒤집어 찾는다.
