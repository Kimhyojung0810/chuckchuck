/**
 * 마이크는 컴퓨터 것으로 — 10-13 사용자: 「폰 쓰지 말고 그냥 컴퓨터 마이크 쓰게 해 줘. Mac 에서 자꾸 폰을 찾는다」.
 * macOS 연속성(Continuity)이 가까운 iPhone · iPad 마이크를 기본 입력으로 잡는다. 앱 · 스튜디오가 마이크를 여는 곳은 여럿이라
 * (녹음 · 비전 리허설 음량 · 음성 시각화 · 삐약이), getUserMedia 한 곳을 감싸 **기기를 따로 고르지 않은 오디오 요청**에만
 * 컴퓨터 마이크(내장 → 그 밖의 폰 아닌 마이크)를 넣는다. 카메라(video) 요청은 손대지 않는다.
 * 기기 이름은 마이크를 한 번 허락한 뒤에야 보여서, 첫 요청은 그대로 두고 그다음부터 고른다.
 * 받아쓰기(SpeechRecognition)는 브라우저가 시스템 기본 입력을 써서 여기서 못 바꾼다 — 시스템 설정 › 사운드 › 입력에서 MacBook 마이크로.
 */
(function () {
  const PHONE = /iphone|ipad|continuity|연속성/i;
  const BUILTIN = /macbook|built-?in|내장/i;

  /** 오디오 입력 목록 → 쓸 deviceId (없으면 null = 그대로) */
  function pickMic(devices) {
    const mics = (devices || []).filter((d) => d.kind === 'audioinput' && d.label);
    if (!mics.length) return null;
    const usable = mics.filter((d) => !PHONE.test(d.label) && d.deviceId !== 'default' && d.deviceId !== 'communications');
    if (!usable.length) return null;
    const def = mics.find((d) => d.deviceId === 'default');
    // 기본이 이미 폰이 아니면 건드리지 않는다 — 사용자가 꽂은 외장 마이크 등을 존중
    if (def && !PHONE.test(def.label)) return null;
    const builtin = usable.find((d) => BUILTIN.test(d.label));
    return (builtin || usable[0]).deviceId;
  }

  const md = typeof navigator !== 'undefined' && navigator.mediaDevices;
  if (md && typeof md.getUserMedia === 'function' && !md.__ccMicPref) {
    const orig = md.getUserMedia.bind(md);
    md.getUserMedia = async function (constraints) {
      const c = constraints || {};
      const audio = c.audio;
      const free = audio === true || (audio && typeof audio === 'object' && !audio.deviceId);
      if (!free) return orig(constraints);
      let id = null;
      try { id = pickMic(await md.enumerateDevices()); } catch (_) { /* 목록을 못 읽으면 그대로 */ }
      if (!id) return orig(constraints);
      const a = audio === true ? {} : { ...audio };
      a.deviceId = { exact: id };
      try {
        return await orig({ ...c, audio: a });
      } catch (_) {
        return orig(constraints);   // 고른 마이크가 막 빠졌으면 원래 요청대로
      }
    };
    md.__ccMicPref = true;
  }
  if (typeof window !== 'undefined') window.CcMicPref = { pickMic };
})();
