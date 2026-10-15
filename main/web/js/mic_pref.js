/**
 * 마이크 · 카메라는 컴퓨터 것으로 — 10-13 사용자: 「폰 쓰지 말고 그냥 컴퓨터 마이크 쓰게 해 줘. Mac 에서 자꾸 폰을 찾는다」,
 * 같은 날 다시 「녹음할 때 폰 연결」.
 * macOS 연속성(Continuity)이 가까운 iPhone · iPad 마이크 · 카메라를 입력으로 잡는다. 앱 · 스튜디오가 기기를 여는 곳은 여럿이라
 * (녹음 · 비전 리허설 카메라 · 음량 · 음성 시각화 · 삐약이), getUserMedia 한 곳을 감싸 **기기를 따로 고르지 않은 요청**에만
 * 폰 아닌 기기를 넣는다. 카메라를 쓰는지 · 크기 · 해상도는 그대로다 — 어느 기기냐만 바꾼다.
 *  1) 열기 전: 기기 이름이 보이면 폰을 피해 고른다(마이크는 기본이 폰일 때만 — 꽂은 외장 마이크 존중).
 *  2) 연 뒤: 이름이 안 보이던 첫 허락 때처럼 그래도 폰이 열렸으면, 폰 아닌 기기로 다시 열고 폰 트랙은 닫는다.
 * 받아쓰기(SpeechRecognition)는 브라우저가 시스템 기본 입력을 써서 여기서 못 바꾼다 — 시스템 설정 › 사운드 › 입력에서 MacBook 마이크로.
 */
(function () {
  const PHONE = /iphone|ipad|continuity|연속성/i;
  const BUILTIN = /macbook|built-?in|내장|facetime/i;
  const VIRTUAL = /^(default|communications)$/;

  /** 그 종류의 폰 아닌 기기 — 내장 먼저, 없으면 목록 순서대로 첫 기기 (없으면 null) */
  function nonPhone(devices, kind) {
    const usable = (devices || []).filter((d) => d.kind === kind && d.label && !PHONE.test(d.label) && !VIRTUAL.test(d.deviceId));
    if (!usable.length) return null;
    return (usable.find((d) => BUILTIN.test(d.label)) || usable[0]).deviceId;
  }

  /** 오디오 입력 목록 → 쓸 deviceId (없으면 null = 그대로) */
  function pickMic(devices) {
    const mics = (devices || []).filter((d) => d.kind === 'audioinput' && d.label);
    if (!mics.length) return null;
    const def = mics.find((d) => d.deviceId === 'default');
    // 기본이 이미 폰이 아니면 건드리지 않는다 — 사용자가 꽂은 외장 마이크 등을 존중
    if (def && !PHONE.test(def.label)) return null;
    return nonPhone(mics, 'audioinput');
  }

  /** 카메라 목록 → 쓸 deviceId. 카메라엔 「기본」 항목이 없어 브라우저가 무엇을 열지 모른다 — 폰 카메라가 보이면 미리 피한다 */
  function pickCam(devices) {
    const cams = (devices || []).filter((d) => d.kind === 'videoinput' && d.label);
    if (!cams.some((d) => PHONE.test(d.label))) return null;
    return nonPhone(cams, 'videoinput');
  }

  const isFree = (v) => v === true || (!!v && typeof v === 'object' && !v.deviceId);
  const withId = (v, id) => ({ ...(v === true ? {} : v), deviceId: { exact: id } });

  const md = typeof navigator !== 'undefined' && navigator.mediaDevices;
  if (md && typeof md.getUserMedia === 'function' && !md.__ccMicPref) {
    const orig = md.getUserMedia.bind(md);
    const list = async () => { try { return await md.enumerateDevices(); } catch (_) { return []; } };

    md.getUserMedia = async function (constraints) {
      const c = constraints || {};
      const freeA = isFree(c.audio);
      const freeV = isFree(c.video);
      if (!freeA && !freeV) return orig(constraints);

      // 1) 열기 전
      const before = await list();
      const a0 = freeA ? pickMic(before) : null;
      const v0 = freeV ? pickCam(before) : null;
      let stream = null;
      let ask = c;
      if (a0 || v0) {
        ask = { ...c, ...(a0 ? { audio: withId(c.audio, a0) } : {}), ...(v0 ? { video: withId(c.video, v0) } : {}) };
        try { stream = await orig(ask); } catch (_) { ask = c; }   // 고른 기기가 막 빠졌으면 원래 요청대로
      }
      if (!stream) stream = await orig(c);

      // 2) 연 뒤 — 그래도 폰이 열렸으면 바꿔 연다
      const phoneA = isFree(ask.audio) && stream.getAudioTracks().some((t) => PHONE.test(t.label));
      const phoneV = isFree(ask.video) && stream.getVideoTracks().some((t) => PHONE.test(t.label));
      if (!phoneA && !phoneV) return stream;
      const after = await list();
      const a1 = phoneA ? nonPhone(after, 'audioinput') : null;
      const v1 = phoneV ? nonPhone(after, 'videoinput') : null;
      if (!a1 && !v1) return stream;   // 폰밖에 없으면 그대로
      try {
        const next = await orig({ ...ask, ...(a1 ? { audio: withId(c.audio, a1) } : {}), ...(v1 ? { video: withId(c.video, v1) } : {}) });
        stream.getTracks().forEach((t) => t.stop());
        return next;
      } catch (_) {
        return stream;
      }
    };
    md.__ccMicPref = true;
  }
  if (typeof window !== 'undefined') window.CcMicPref = { pickMic, pickCam };
})();
