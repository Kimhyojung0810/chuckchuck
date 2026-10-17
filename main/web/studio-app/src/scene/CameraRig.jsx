/* 단계 전환 — 시점(카메라)은 고정, 창은 제자리에서 겹쳐 바뀐다 (10-17 사용자 「화면 전환 토 나와 · 1번에서 5번 갈 때 막 넘어가서 어지럽다」).
   예전엔 곡선 위 창들이 목표까지 줄지어 미끄러지고 공간이 줌 아웃됐다 — 큰 화면이 시야를 가로지르는 움직임은 멀미를 부른다
   (visionOS HIG: 사람이 일으키지 않은 큰 움직임 · 시야 전체의 흐름을 피하고, 바뀜은 제자리 페이드로).
   그래서: 단계가 바뀌면 지금 창이 살짝 물러나며 흐려지고, 새 창이 제자리에서 떠오른다(0.42초). 몇 칸을 건너뛰어도 똑같다.
   곡선이 움직이는 건 사람이 빈 곳을 끌어 둘러볼 때뿐 — 손가락을 그대로 따르고, 놓으면 짧게 돌아온다. */
import { useEffect } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { easing } from 'maath'
import { rig } from '../rig.js'
import { EYE, FADE_SEC, easeInOutSine } from '../config.js'

export function CameraRig() {
  const camera = useThree((s) => s.camera)
  useEffect(() => { camera.position.set(0, EYE, 0); camera.rotation.set(0, 0, 0) }, [camera])
  useFrame((state, dt) => {
    const now = state.clock.elapsedTime
    if (window.studioDebug) window.studioDebug.three = state   // 실험실 — 장면 · 카메라를 읽는다
    // 단계가 바뀌었다 → 제자리 겹쳐 바꾸기. 곡선 위치는 바로 새 단계로(이웃 창은 함께 페이드로 드러난다)
    if (rig.shown !== rig.at) {
      const from = rig.shown ?? rig.at
      rig.shown = rig.at
      rig.f = rig.at + rig.drag
      rig.tween = null
      rig.fade = rig.reduced || from === rig.at ? null : { from, to: rig.at, t0: now, p: 0 }
      rig.settled = !rig.fade
    }
    if (rig.fade) {
      const fd = rig.fade
      fd.p = Math.min(1, (now - fd.t0) / FADE_SEC)
      rig.motion = 0
      if (fd.p >= 1) { rig.fade = null; rig.settled = !rig.dragging }
      return
    }
    const target = rig.at + rig.drag
    if (rig.reduced) { rig.f = target; rig.motion = 0; rig.settled = !rig.dragging; return }
    // 끌기 — 사람이 일으킨 움직임만 곡선을 움직인다. 공간은 아주 조금만 물러난다
    if (rig.dragging) {
      rig.tween = null
      rig.settled = false
      easing.damp(rig, 'f', target, 0.05, Math.min(dt, 0.05))
      easing.damp(rig, 'motion', 0.35, 0.12, Math.min(dt, 0.05))
      return
    }
    // 놓으면 지금 창으로 짧게 돌아온다 (0.35초, 한 칸 미만)
    if (!rig.tween ? Math.abs(target - rig.f) > 1e-4 : rig.tween.to !== target) {
      rig.tween = { from: rig.f, to: target, t0: now, dur: 0.35, m0: rig.motion }
      rig.settled = false
    }
    const tw = rig.tween
    if (!tw) { rig.motion = 0; rig.settled = true; return }
    const p = Math.min(1, (now - tw.t0) / tw.dur)
    rig.f = tw.from + (tw.to - tw.from) * easeInOutSine(p)
    rig.motion = tw.m0 * (1 - easeInOutSine(p))
    if (p >= 1) { rig.f = tw.to; rig.tween = null; rig.motion = 0; rig.settled = true }
  })
  return null
}
