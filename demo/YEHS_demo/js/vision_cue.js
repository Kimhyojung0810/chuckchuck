/**
 * 비전 리허설 — 삐약이가 고르는 반응. 브라우저·마이크·네트워크가 없다.
 *
 * 말하는 속도(자/분)와 목소리 크기(RMS)만 본다. 부스 발표 코치(booth_logic)와
 * 같은 빠르기 배수(권장 300~350자/분 × 1.15 · 0.85)를 쓰고, 음량은 그 화면의
 * 「보통 말소리 0.05~0.2」 바깥이다.
 *
 * 한 몸에 표정이 하나라 겹치면 큰 소리 > 작은 소리 > 빠름 > 느림 순이다.
 * 말이 없는데 방이 조용한 것은 「잘 안 들려」가 아니다.
 */
(function () {
  'use strict';

  const VISION = {
    fastCpm: 350 * 1.15,
    slowCpm: 300 * 0.85,
    quietLevel: 0.03,
    loudLevel: 0.14,
    fastPerSec: 3.6,
    slowPerSec: 2.05,
    windowMs: 8000,
    paceMs: 3200,
    levelMs: 700,
    gapMs: 2000,
    minChars: 12,
    minSpeakMs: 2200,
    minLevelN: 3,
    quietGrow: 6,
    sustainMs: 280,
    loudSustainMs: 180,
    holdMs: 1100,
    keepMs: 12000,
  };

  const CUE_COPY = {
    idle: '',
    listen: '듣고 있어요',
    fast: '우웅?',
    slow: '하암~',
    quiet: '잘 안 들려',
    loud: '귀가 아파',
  };

  const REACTS = new Set(['fast', 'slow', 'quiet', 'loud']);

  function countSpeechChars(text) {
    return ((text || '').match(/[가-힣A-Za-z0-9]/g) || []).length;
  }

  function avg(xs) {
    return xs.reduce((a, b) => a + b, 0) / xs.length;
  }

  function createVisionMeter(now = 0) {
    return { events: [], cue: 'idle', cueAt: now, pending: 'idle', pendingAt: now };
  }

  /** 글자가 늘어난 시점만 말한 시간으로 센다. 긴 쉼이 「느려요」로 새지 않게 한 간격은 gapMs 까지. */
  function speakingRate(events, now, cfg) {
    const win = events.filter((e) => now - e.t <= cfg.windowMs && e.chars !== undefined);
    if (win.length < 2) return null;
    const grow = [];
    let maxChars = win[0].chars;
    for (let i = 1; i < win.length; i++) {
      if (win[i].chars > maxChars) {
        maxChars = win[i].chars;
        grow.push(win[i].t);
      }
    }
    if (grow.length < 2) return null;
    let speakMs = 0;
    for (let i = 1; i < grow.length; i++) speakMs += Math.min(grow[i] - grow[i - 1], cfg.gapMs);
    const chars = win[win.length - 1].chars - win[0].chars;
    if (chars < cfg.minChars || speakMs < cfg.minSpeakMs) return null;
    return { chars, sec: speakMs / 1000, cpm: chars / (speakMs / 60000) };
  }

  function charsGrew(events, now, cfg) {
    const win = events.filter((e) => now - e.t <= cfg.levelMs && e.chars !== undefined);
    if (win.length < 2) return false;
    return win[win.length - 1].chars - win[0].chars >= cfg.quietGrow;
  }

  function levelNow(events, now, cfg) {
    const lv = events.filter((e) => now - e.t <= cfg.levelMs && e.level !== undefined);
    if (lv.length < cfg.minLevelN) return null;
    return avg(lv.map((e) => e.level));
  }

  /**
   * 받아쓰기 없이 마이크 파동만으로 말 빠르기를 본다.
   * 음량이 바닥과 봉우리 사이를 오르면 한 박(말 한 토막)으로 센다.
   * 파동이 없으면 null — 조용한 방을 느린 말로 보지 않는다.
   */
  function syllablePace(events, now, cfg) {
    const win = events.filter((e) => now - e.t <= cfg.paceMs && e.level !== undefined);
    if (win.length < 6) return null;
    const xs = win.map((e) => e.level).sort((a, b) => a - b);
    const floor = xs[Math.floor(xs.length * 0.2)];
    const peak = xs[Math.floor(xs.length * 0.9)];
    if (peak < floor + 0.008 && peak < 0.02) return null;
    const span = win[win.length - 1].t - win[0].t;
    if (span < 700) return null;
    const rise = peak - floor;
    const hiCut = floor + rise * 0.55;
    const loCut = floor + rise * 0.35;
    let onsets = 0;
    let armed = true;
    for (let i = 0; i < win.length; i++) {
      const lv = win[i].level;
      if (lv >= hiCut && armed) { onsets += 1; armed = false; }
      else if (lv < loCut) armed = true;
    }
    if (onsets < 2) return null;
    return { onsets, perSec: onsets / (span / 1000), mean: avg(win.map((e) => e.level)) };
  }

  function desiredCue(events, now, cfg = VISION) {
    const rate = speakingRate(events, now, cfg);
    const vol = levelNow(events, now, cfg);
    const grew = charsGrew(events, now, cfg);
    const syl = rate ? null : syllablePace(events, now, cfg);
    if (vol !== null && vol >= cfg.loudLevel) return 'loud';
    if (vol !== null && vol < cfg.quietLevel && (grew || syl)) return 'quiet';
    if (rate && rate.cpm > cfg.fastCpm) return 'fast';
    if (syl && syl.perSec >= cfg.fastPerSec) return 'fast';
    if (rate && rate.cpm < cfg.slowCpm) return 'slow';
    if (syl && syl.perSec <= cfg.slowPerSec) return 'slow';
    if (rate || grew || syl) return 'listen';
    return 'idle';
  }

  function observeVision(meter, sample, cfg = VISION) {
    const now = sample.now;
    const e = { t: now };
    if (sample.chars !== undefined) e.chars = sample.chars;
    if (sample.level !== undefined) e.level = sample.level;
    const events = meter.events.filter((x) => now - x.t <= cfg.keepMs);
    events.push(e);
    const desired = desiredCue(events, now, cfg);
    let { cue, cueAt, pending, pendingAt } = meter;
    if (desired === cue) {
      pending = desired;
      pendingAt = now;
    } else if (pending === desired) {
      const wait = desired === 'loud' ? cfg.loudSustainMs : (REACTS.has(desired) ? cfg.sustainMs : 200);
      const held = REACTS.has(cue) && now - cueAt < cfg.holdMs;
      if (!held && now - pendingAt >= wait) {
        cue = desired;
        cueAt = now;
      }
    } else {
      pending = desired;
      pendingAt = now;
    }
    return { meter: { events, cue, cueAt, pending, pendingAt }, cue };
  }

  window.VisionCue = {
    VISION, CUE_COPY, countSpeechChars, createVisionMeter, desiredCue, observeVision, speakingRate,
  };
})();
