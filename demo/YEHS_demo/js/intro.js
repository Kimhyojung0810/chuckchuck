/*
 * /hi 부스 랜딩 (2026-10-11, docs/booth-mobile/team-schema.md).
 * 히어로·주 버튼은 HTML 만으로 그려지고, 이 파일은 (1) data/team.json 으로 팀 소개를 한 사람 한 줄(이름 · 역할 · 한 줄)로 그리고
 * (2) 인앱 브라우저에서 카메라가 필요한 실제 흐름으로 갈 때만 「Safari/Chrome 으로 열기」 를 안내한다.
 * 줄 수는 members 길이로 정해진다 — 사람이 바뀌면 json 만 고친다. draft 는 화면에 표시하지 않는다(운영자만 json 에서 본다).
 * 10-12 사용자: 카드 넘기기 대신 다섯 줄 간단 소개면 충분하다 — did · quote · links 는 json 에 남지만 화면엔 안 쓴다.
 * 데이터는 textContent 로만 넣는다(innerHTML 없음).
 */
(() => {
  'use strict';

  // ── 부스 퍼널 신호 (js/funnel.js · docs/booth-mobile/funnel-events.md) — 없거나 실패해도 화면은 그대로 ──
  function funnel(step) {
    try { if (typeof window.ccFunnel === 'function') window.ccFunnel(step); } catch (_) { /* 신호는 덤 */ }
  }
  /** 그 칸이 화면에 3할쯤 보였을 때 한 번. IntersectionObserver 가 없는 옛 브라우저면 바로 */
  function whenSeen(node, fn) {
    if (!node) return;
    if (!('IntersectionObserver' in window)) { fn(); return; }
    const io = new IntersectionObserver((es) => {
      if (es.some((e) => e.isIntersecting)) { io.disconnect(); fn(); }
    }, { threshold: 0.3 });
    io.observe(node);
  }

  const TEAM_URL = '/data/team.json';
  const FETCH_TIMEOUT_MS = 8000;
  const ID_RE = /^[a-z0-9-]{1,24}$/;
  const PHOTO_RE = /^assets\/team\/[a-z0-9-]+\.(webp|png|jpg)$/;
  const AVATAR_TINTS = ['#E7FBF0', '#FFF1C2', '#F4F4F5', '#D7F5E8'];

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const str = (v) => (typeof v === 'string' ? v.trim() : '');
  // ── 데이터 ──────────────────────────────────────────────────────────────
  /** 스키마(team.schema.json) 중 화면이 기대는 칸만 다시 본다. 깨진 카드는 빼고, 하나도 없으면 실패. */
  function cleanTeam(raw) {
    if (!raw || raw.schema !== 'chuckchuck.team' || raw.version !== 1 || !Array.isArray(raw.members)) return null;
    const members = raw.members
      .filter((m) => m && ID_RE.test(m.id) && str(m.name) && str(m.role) && str(m.headline))
      .map((m) => ({
        id: m.id,
        name: str(m.name),
        role: str(m.role),
        headline: str(m.headline),
        photo: PHOTO_RE.test(m.photo || '') ? '/' + m.photo : '',
      }));
    if (!members.length) return null;
    return { contest: str(raw.contest), members };
  }

  async function fetchTeam() {
    const ctrl = typeof AbortController === 'function' ? new AbortController() : null;
    const timer = ctrl && setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
    try {
      const res = await fetch(TEAM_URL, { cache: 'no-cache', signal: ctrl && ctrl.signal });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const team = cleanTeam(await res.json());
      if (!team) throw new Error('team.json 형식이 달라요');
      return team;
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  // ── 팀원 줄 ─────────────────────────────────────────────────────────────
  // 병아리 배지는 사진이 있든 없든 같은 자리에 — 줄마다 모양이 같게
  function chickBadge() {
    const svgNs = 'http://www.w3.org/2000/svg';
    const chick = document.createElementNS(svgNs, 'svg');
    chick.setAttribute('class', 'chick');
    chick.setAttribute('viewBox', '0 0 100 100');
    const use = document.createElementNS(svgNs, 'use');
    use.setAttribute('href', '#chick');
    chick.appendChild(use);
    return chick;
  }

  function avatar(m, i) {
    const box = el('div', 'avatar');
    box.style.setProperty('--av', AVATAR_TINTS[i % AVATAR_TINTS.length]);
    box.setAttribute('aria-hidden', 'true');
    const initial = () => document.createTextNode(Array.from(m.name)[0] || '');
    const badge = chickBadge();
    if (!m.photo) { box.append(initial(), badge); return box; }
    const img = el('img');
    Object.assign(img, { src: m.photo, alt: '', width: 44, height: 44, loading: 'lazy', decoding: 'async' });
    img.addEventListener('error', () => img.replaceWith(initial()), { once: true });
    box.append(img, badge);
    return box;
  }

  function row(m, i) {
    const li = el('li', 'team-row');
    li.id = 'member-' + m.id;
    li.dataset.id = m.id;
    const who = el('div', 'who');
    const top = el('p', 'who-top');
    top.append(el('span', 'name', m.name), el('span', 'role', m.role));
    who.append(top, el('p', 'headline', m.headline));
    li.append(avatar(m, i), who);
    return li;
  }

  function teamList(team) {
    const list = $('team-list');
    const rows = team.members.map(row);
    list.replaceChildren(...rows);
    document.querySelector('.team-box').dataset.state = 'ready';
    whenSeen(list, () => funnel('team'));
    // 예전 「마지막 카드까지 넘김」 자리 — 이제는 마지막 줄이 화면에 보였을 때
    if (rows.length > 1) whenSeen(rows[rows.length - 1], () => funnel('team_end'));
    return { goTo: (id) => {
      const r = rows.find((x) => x.dataset.id === id);
      if (!r) return false;
      r.toggleAttribute('data-active', true);
      setTimeout(() => r.removeAttribute('data-active'), 2400);
      return r;
    } };
  }

  /** /hi/<id> 또는 /hi#<id> 로 들어오면 그 사람 줄로 내려가 잠깐 밝힌다. */
  function wantedId() {
    const fromPath = location.pathname.match(/^\/hi\/([a-z0-9-]{1,24})\/?$/i);
    if (fromPath) return fromPath[1].toLowerCase();
    const h = location.hash.slice(1).toLowerCase();
    return ID_RE.test(h) && h !== 'team' && h !== 'top' && h !== 'what' ? h : '';
  }

  async function loadTeam() {
    const root = document.querySelector('.team-box');
    root.dataset.state = 'loading';
    $('team-error').hidden = true;
    try {
      const team = await fetchTeam();
      if (team.contest) { $('team-contest').textContent = team.contest; $('foot-contest').textContent = team.contest; }
      $('team-lead').textContent = `${team.members.length}명이 함께 만들었어요.`;
      const c = teamList(team);
      const id = wantedId();
      const r = id && c.goTo(id);
      if (r) r.scrollIntoView({ block: 'start' });
    } catch (err) {
      root.dataset.state = 'error';
      $('team-error').hidden = false;
    }
  }

  // ── 인앱 브라우저 → 실제 흐름 안내 ─────────────────────────────────────
  const UA = navigator.userAgent || '';
  const INAPP = [
    [/KAKAOTALK/i, '카카오톡'], [/NAVER\(inapp|NAVER\//i, '네이버 앱'], [/Instagram/i, '인스타그램'],
    [/FBAN|FBAV|FB_IAB/i, '페이스북'], [/\bLine\//i, '라인'], [/DaumApps/i, '다음 앱'], [/everytimeApp/i, '에브리타임'],
  ].find(([re]) => re.test(UA));
  const isAndroid = /Android/i.test(UA);
  const isKakao = /KAKAOTALK/i.test(UA);

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(() => true, () => legacyCopy(text));
    }
    return Promise.resolve(legacyCopy(text));
  }
  function legacyCopy(text) {
    const t = el('textarea');
    t.value = text;
    t.setAttribute('readonly', '');
    t.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
    document.body.appendChild(t);
    t.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (_) { ok = false; }
    t.remove();
    return ok;
  }

  function inappSheet() {
    const scrim = $('inapp');
    const sheet = scrim.querySelector('.sheet');
    const openBtn = $('inapp-open');
    const copyBtn = $('inapp-copy');
    const hint = $('inapp-hint');
    const tip = $('inapp-tip');
    // 해시(#)가 든 주소는 Android intent 문법과 부딪힌다 — 브리지가 /rehearsal 을 #/rehearsal 로 보내 준다
    const target = location.origin + '/rehearsal';
    let opener = null;

    $('inapp-app').textContent = INAPP[1];
    // 바깥으로 여는 길이 있으면(카톡 스킴 · 안드로이드 크롬 intent) 주 버튼이 그 길, 주소 복사는 둘째 줄. 없으면(iOS 인앱) 주 버튼이 주소 복사 + 메뉴 안내
    const external = isKakao || isAndroid;
    if (isKakao) openBtn.textContent = '다른 브라우저로 열기';
    else if (isAndroid) openBtn.textContent = 'Chrome으로 열기';
    copyBtn.hidden = !external;
    tip.hidden = external;

    // 시트를 열면 기록을 하나 쌓는다(state.overlay) — 폰 뒤로는 시트만 닫는다. 기록 없이 열었더니 뒤로가 /hi 를 떠났고,
    // QR 로 처음 들어온 방문객이면 앞 기록이 없어 인앱 웹뷰가 통째로 닫혔다 (10-12 2차 layout-touch-a11y-r2-1)
    const hide = () => {
      if (scrim.hidden) return;
      scrim.hidden = true;
      document.body.style.overflow = '';
      document.removeEventListener('keydown', onKey);
      if (opener) opener.focus();
    };
    const close = () => {
      if (history.state && history.state.overlay === 'sheet') history.back();   // popstate 가 hide()
      else hide();
    };
    window.addEventListener('popstate', () => { if (!(history.state && history.state.overlay === 'sheet')) hide(); });
    const onKey = (e) => {
      if (e.key === 'Escape') { close(); return; }
      if (e.key !== 'Tab') return;
      const f = Array.from(sheet.querySelectorAll('button, a[href]')).filter((b) => !b.hidden);
      const first = f[0];
      const last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    const open = (from) => {
      funnel('inapp_notice');
      opener = from;
      hint.hidden = true;
      if (!(history.state && history.state.overlay === 'sheet')) history.pushState(Object.assign({}, history.state || {}, { overlay: 'sheet' }), '');
      scrim.hidden = false;
      document.body.style.overflow = 'hidden';
      document.addEventListener('keydown', onKey);
      sheet.focus();
    };

    $('inapp-close').addEventListener('click', close);
    scrim.addEventListener('click', (e) => { if (e.target === scrim) close(); });
    openBtn.addEventListener('click', () => {
      if (isKakao) { location.href = 'kakaotalk://web/openExternal?url=' + encodeURIComponent(target); return; }
      if (isAndroid) {
        location.href = 'intent://' + target.replace(/^https?:\/\//, '') + '#Intent;scheme=https;package=com.android.chrome;end';
        return;
      }
      copyAddress(openBtn);
    });
    copyBtn.addEventListener('click', () => copyAddress(copyBtn));
    function copyAddress(btn) {
      copyText(target).then((ok) => {
        btn.textContent = ok ? '주소를 복사했어요' : '주소 복사하기';
        hint.textContent = ok
          ? '주소를 복사했어요. Safari나 Chrome을 열고 주소창에 붙여 넣어요.'
          : '복사하지 못했어요. 앱 메뉴(···)에서 Safari로 열기를 골라요.';
        hint.hidden = false;
      });
    }

    document.querySelectorAll('[data-needs-camera]').forEach((a) => {
      a.addEventListener('click', (e) => { e.preventDefault(); open(a); });
    });
    // 「여기서 계속 열기」 — 시트가 쌓은 기록을 리허설로 바꿔 쓴다. 리허설 「나가기」(history.back)가 시트 없는 /hi 로 돌아온다
    $('inapp-anyway').addEventListener('click', (e) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.button > 0) return;
      e.preventDefault();
      markFromHi();
      location.replace($('inapp-anyway').href);
    });
  }

  // ── 리허설 「나가기」 가 돌아올 곳 (js/rehearsal.js rhExitTarget) ─────────────
  // /hi 에서 리허설로 가면 'hi' 를 적는다. /hi 를 열 때마다 지난 표시를 지운다 — 투어에서 리허설에 들렀다 돌아온 방문객이
  // 「바로 내 자료로 해 보기」 로 다시 가면 남은 투어 표시 때문에 나가기가 투어 끝 화면으로 갔다 (10-12 2차 flow-regression-inapp-r2-3)
  const RH_FROM_KEY = 'cheokcheok:rh-from';
  function markFromHi() {
    try { sessionStorage.setItem(RH_FROM_KEY, 'hi'); } catch (_) { /* 사생활 모드 — 나가기는 기록으로만 */ }
  }
  try { sessionStorage.removeItem(RH_FROM_KEY); sessionStorage.removeItem('cheokcheok:from-tour'); } catch (_) { /* 사생활 모드 */ }
  if (!INAPP) document.querySelectorAll('[data-needs-camera]').forEach((a) => a.addEventListener('click', markFromHi));

  // ── 시작 ────────────────────────────────────────────────────────────────
  funnel('hi');
  whenSeen($('what'), () => funnel('intro'));
  const explore = $('explore-btn');
  // 페이지가 #/tour 로 바뀌기 직전 — funnel.js 가 keepalive fetch 라 대개 간다
  // 새로 들어가는 투어는 처음부터 — 같은 탭에 지난 투어의 답 · 판정(cheokcheok:tour)이 남아 있으면 질문 화면에 앞사람 결과가 펼쳐진 채
  // 나왔다(부스 폰 한 대를 여러 방문객에게 건넨다, 10-12 점검). 투어 안에서 새로 고친 이어 보기는 그대로다(이 버튼을 안 거친다)
  if (explore) explore.addEventListener('click', () => {
    funnel('explore');
    try { sessionStorage.removeItem('cheokcheok:tour'); } catch (_) { /* 사생활 모드 — 지울 것도 없다 */ }
  });
  $('team-retry').addEventListener('click', loadTeam);
  loadTeam();
  if (INAPP) inappSheet();
})();
