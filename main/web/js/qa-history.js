/*
질문 코칭 내역 저장소입니다.

기존 qa 상태는 sessionStorage 의 'qa-flow' 키 하나에만 있어서, 새 코칭을 시작하면
덮어써지고 탭을 닫으면 사라졌습니다. "지난 발표의 QA 내역"이 되려면 발표별로
남아야 하고 탭을 닫아도 살아 있어야 해서 localStorage 에 따로 씁니다.

저장 형태 (세션 id 를 키로)
  { "<세션id>": { at, aud, mode, turns, before, after, total,
                  mastered:[], weak:[],
                  beats:[{ concept, label, slide, q, a, verdict, note }] } }

verdict 는 'full' | 'partial' | 'none' 세 가지입니다.
*/
window.QaHistory = (function () {
  'use strict';

  const KEY = 'cheokcheok:qa-history';
  const MAX_SESSIONS = 30;      // 무한정 쌓이지 않게 상한을 둔다

  function readAll() {
    try {
      const raw = localStorage.getItem(KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (err) {
      console.error('QA 내역을 읽지 못했어요:', err);
      // 손상 원본을 백업으로 옮긴다 — 그대로 두면 다음 save 가 {} 위에
      // 덮어써 30건이 통째로 사라진다. 백업이면 복구 여지가 남는다.
      try {
        const raw = localStorage.getItem(KEY);
        if (raw) {
          localStorage.setItem(KEY + ':corrupt', raw);
          localStorage.removeItem(KEY);
        }
      } catch (_) { /* privacy mode */ }
      return {};
    }
  }

  function writeAll(next) {
    try {
      localStorage.setItem(KEY, JSON.stringify(next));
      return true;
    } catch (err) {
      // 용량 초과가 대부분이다. 가장 오래된 것부터 덜어내고 한 번 더 시도한다.
      console.error('QA 내역을 저장하지 못했어요:', err);
      const ids = Object.keys(next).sort((a, b) => (next[a].at || '').localeCompare(next[b].at || ''));
      if (ids.length > 1) {
        const trimmed = { ...next };
        delete trimmed[ids[0]];
        return writeAll(trimmed);
      }
      return false;
    }
  }

  /** 세션 하나의 코칭 내역을 저장한다. 같은 세션이면 덮어쓴다. */
  function save(sessionId, record) {
    if (!sessionId) {
      console.error('QA 내역 저장에 세션 id 가 필요해요.');
      return false;
    }
    const all = readAll();
    const next = { ...all, [sessionId]: { at: new Date().toISOString(), ...record } };

    // 상한을 넘으면 오래된 것부터 버린다
    const ids = Object.keys(next);
    if (ids.length > MAX_SESSIONS) {
      ids.sort((a, b) => (next[a].at || '').localeCompare(next[b].at || ''))
        .slice(0, ids.length - MAX_SESSIONS)
        .forEach(id => { delete next[id]; });
    }
    return writeAll(next);
  }

  /** 세션 하나의 내역. 없으면 null. */
  function get(sessionId) {
    return readAll()[sessionId] || null;
  }

  /** 최근 순으로 [{ id, ...record }]. */
  function list() {
    const all = readAll();
    return Object.keys(all)
      .map(id => ({ id, ...all[id] }))
      .sort((a, b) => (b.at || '').localeCompare(a.at || ''));
  }

  function clear(sessionId) {
    const all = readAll();
    if (sessionId) {
      const next = { ...all };
      delete next[sessionId];
      return writeAll(next);
    }
    return writeAll({});
  }

  return { save, get, list, clear };
})();
