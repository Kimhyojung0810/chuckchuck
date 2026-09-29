/* 서버 연결 감시 — 포트 연결이 끊기면 알려 주고, 다시 이어지면 하던 일을 잇는다.

   왜 (2026-09-29 사용자): 원격 서버의 브리지를 VS Code 포트 전달·SSH 터널로 보고 있는데
   전달이 조용히 끊기면 요청이 오류도 없이 매달렸다가 60초 뒤 「판정 실패: 요청이 60초 안에
   끝나지 않았어요」 가 떴다. 서버는 멀쩡했는데(판정 1.1초) 화면은 판정이 고장 난 것처럼 말했다.

   - 요청이 시간 초과·네트워크 오류로 끝나면 chuckchuck_bridge.js 가 probe() 로 서버를 한 번 두드린다.
     안 닿으면 「서버에 연결되지 않았어요」 로 바꿔 말하고 여기 markDown() 을 부른다.
   - 화면이 보이는 동안 15초마다 /api/health 를 가볍게 두드린다. 두 번 연달아 안 닿으면 끊긴 것으로 본다.
   - 끊긴 동안은 3초마다 다시 두드리고, 닿으면 배너를 「다시 연결됐어요」 로 바꾼 뒤
     `chuckchuck:reconnected` 이벤트를 쏜다 — 질문 코칭은 이걸 듣고 실패한 판정을 다시 보낸다.

   브리지가 없는 화면(시연 더미)에서는 아무것도 하지 않는다. */

const CONN_HEARTBEAT_MS = 15000;
const CONN_DOWN_POLL_MS = 3000;
const CONN_PROBE_TIMEOUT_MS = 4000;
const CONN_MISSES_TO_DOWN = 2;
const CONN_BACK_BANNER_MS = 3000;

const connState = { down: false, misses: 0, timer: null, started: false };

function connApiBase() {
  try {
    const b = window.ChuckchuckBridge;
    return b && typeof b.qaApiBase === 'function' ? b.qaApiBase() : null;
  } catch (_) { return null; }
}

/** 서버에 닿는가. 브리지가 없으면 null — 판단하지 않는다 */
async function connProbe() {
  const base = connApiBase();
  if (base === null) return null;
  const control = new AbortController();
  const timer = setTimeout(() => control.abort(), CONN_PROBE_TIMEOUT_MS);
  try {
    const res = await fetch(`${base}/api/health`, { cache: 'no-store', signal: control.signal });
    return res.ok;
  } catch (_) {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

function connBanner() {
  let el = document.getElementById('connBanner');
  if (!el) {
    el = document.createElement('div');
    el.id = 'connBanner';
    el.className = 'conn-banner';
    el.setAttribute('role', 'status');
    el.setAttribute('aria-live', 'polite');
    document.body.appendChild(el);
  }
  return el;
}

function connShowDown() {
  const el = connBanner();
  el.className = 'conn-banner is-down';
  el.innerHTML = `<b>서버와 연결이 끊겼어요</b>
    <span>포트 연결(VS Code Ports·SSH 터널)을 다시 이으면 자동으로 이어서 해요</span>
    <button type="button" class="conn-retry">지금 확인하기</button>`;
  el.querySelector('.conn-retry').addEventListener('click', () => connCheck());
}

function connShowBack() {
  const el = connBanner();
  el.className = 'conn-banner is-back';
  el.innerHTML = '<b>다시 연결됐어요</b>';
  setTimeout(() => { if (!connState.down && el.classList.contains('is-back')) el.remove(); }, CONN_BACK_BANNER_MS);
}

function connSchedule() {
  clearTimeout(connState.timer);
  connState.timer = setTimeout(connCheck, connState.down ? CONN_DOWN_POLL_MS : CONN_HEARTBEAT_MS);
}

/** 끊겼다고 알린다. 이미 끊긴 상태면 배너만 유지한다 */
function connMarkDown() {
  if (!connState.down) {
    connState.down = true;
    connShowDown();
    console.warn('[chuckchuck] 서버 연결 끊김 — 다시 이어지면 알려요');
  }
  connSchedule();
}

function connMarkUp() {
  connState.misses = 0;
  if (connState.down) {
    connState.down = false;
    connShowBack();
    console.info('[chuckchuck] 서버 다시 연결됨');
    window.dispatchEvent(new CustomEvent('chuckchuck:reconnected'));
  }
}

async function connCheck() {
  // 탭이 숨어 있으면 두드리지 않는다 — 돌아오면 visibilitychange 가 바로 다시 본다
  if (document.hidden) return connSchedule();
  const ok = await connProbe();
  if (ok === null) return connSchedule();
  if (ok) connMarkUp();
  else if (connState.down || ++connState.misses >= CONN_MISSES_TO_DOWN) connMarkDown();
  connSchedule();
}

function connStart() {
  if (connState.started) return;
  connState.started = true;
  window.addEventListener('offline', connMarkDown);
  window.addEventListener('online', () => connCheck());
  document.addEventListener('visibilitychange', () => { if (!document.hidden) connCheck(); });
  connSchedule();
}

window.ChuckchuckConn = {
  probe: connProbe,
  markDown: connMarkDown,
  isDown: () => connState.down,
  check: connCheck,
};

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', connStart);
else connStart();
