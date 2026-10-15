/*
 * /hi 부스 랜딩 (2026-10-11, docs/booth-mobile/team-schema.md).
 * 히어로·주 버튼은 HTML 만으로 그려지고, 이 파일은 (1) data/team.json 으로 팀 소개를 한 사람 한 줄(이름 · 역할 · 한 줄)로 그리고
 * (2) 인앱 브라우저에서 카메라가 필요한 실제 흐름으로 갈 때만 「Safari/Chrome 으로 열기」 를 안내한다.
 * 줄 수는 members 길이로 정해진다 — 사람이 바뀌면 json 만 고친다. draft 는 화면에 표시하지 않는다(운영자만 json 에서 본다).
 * 10-12 사용자: 카드 넘기기 대신 다섯 줄 간단 소개면 충분하다 — did · quote · links 는 json 에 남지만 화면엔 안 쓴다.
 * 10-15 팀 포스터 기조: 한 사람 한 장(삐약이 · 이름 · 역할 · 학과 · YEHS 직함 · 연락처). 연락처는 git 밖 파일(js/team-contacts.js)에만 있다.
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
  const CHICK_RE = /^assets\/chick-team-[a-z0-9-]+\.svg$/;
  // 연락처 — 서버 폴더에만 두는 파일(.gitignore). 없으면 404 이고 연락처 줄만 안 나온다
  const CONTACTS_URL = '/js/team-contacts.js';
  const TEL_RE = /^0\d{1,2}-\d{3,4}-\d{4}$/;
  const EMAIL_RE = /^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,120}\.[A-Za-z]{2,24}$/;
  // 결선 첫날(KINTEX 11.3–11.5) — 배지의 D-day. 날짜는 한국 시간 기준
  const FINAL_START = Date.UTC(2026, 10, 3);
  const FINAL_DAYS = 3;

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
        school: str(m.school),
        yehs: str(m.yehs),
        photo: PHOTO_RE.test(m.photo || '') ? '/' + m.photo : '',
        chick: CHICK_RE.test(m.chick || '') ? '/' + m.chick : '',
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

  // ── 팀원 카드 ───────────────────────────────────────────────────────────
  // 아바타는 사진 → 그 사람의 삐약이(10-15) → 이름 첫 글자 순서로
  function avatar(m) {
    const box = el('div', 'avatar');
    box.setAttribute('aria-hidden', 'true');
    const initial = () => document.createTextNode(Array.from(m.name).slice(-2).join('') || '');
    const src = m.photo || m.chick;
    if (!src) { box.append(initial()); return box; }
    const img = el('img', m.photo ? 'photo' : '');
    Object.assign(img, { src, alt: '', width: 56, height: 56, loading: 'lazy', decoding: 'async' });
    img.addEventListener('error', () => img.replaceWith(initial()), { once: true });
    box.append(img);
    return box;
  }

  const ICONS = {
    tel: 'M6.6 10.8a15.1 15.1 0 0 0 6.6 6.6l2.2-2.2a1 1 0 0 1 1-.25 11.4 11.4 0 0 0 3.6.57 1 1 0 0 1 1 1V20a1 1 0 0 1-1 1A17 17 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1c0 1.25.2 2.45.57 3.57a1 1 0 0 1-.25 1z',
    email: 'M4 5h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zm0 2v.4l8 5 8-5V7zm16 2.75-7.47 4.67a1 1 0 0 1-1.06 0L4 9.75V17h16z',
  };
  function contactLink(kind, value, name) {
    const a = el('a', 'ct');
    a.href = kind === 'tel' ? 'tel:' + value.replace(/-/g, '') : 'mailto:' + value;
    a.setAttribute('aria-label', `${name}에게 ${kind === 'tel' ? '전화하기' : '메일 보내기'} ${value}`);
    const svgNs = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNs, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS(svgNs, 'path');
    path.setAttribute('d', ICONS[kind]);
    path.setAttribute('fill', 'currentColor');
    svg.appendChild(path);
    a.append(svg, document.createTextNode(value));
    return a;
  }
  /** 카드마다 연락처 줄 — 형식이 맞는 값만, textContent 로 */
  function renderContacts(rows, members) {
    const book = window.CC_TEAM_CONTACTS;
    if (!book || typeof book !== 'object') return;
    rows.forEach((li, i) => {
      const m = members[i];
      const c = book[m.id];
      if (!c || li.querySelector('.contacts')) return;
      const box = el('div', 'contacts');
      if (TEL_RE.test(str(c.tel))) box.append(contactLink('tel', str(c.tel), m.name));
      if (EMAIL_RE.test(str(c.email))) box.append(contactLink('email', str(c.email), m.name));
      if (box.childNodes.length) li.append(box);
    });
  }
  function loadContacts(onReady) {
    if (window.CC_TEAM_CONTACTS) { onReady(); return; }
    const sc = document.createElement('script');
    sc.src = CONTACTS_URL;
    sc.async = true;
    sc.onload = onReady;
    sc.onerror = () => sc.remove();   // 파일이 없는 서버 — 연락처 없이 그대로
    document.head.appendChild(sc);
  }

  function row(m) {
    const li = el('li', 'team-row');
    li.id = 'member-' + m.id;
    li.dataset.id = m.id;
    const who = el('div', 'who');
    const top = el('p', 'who-top');
    top.append(el('span', 'name', m.name), el('span', 'role', m.role));
    who.append(top);
    if (m.school) who.append(el('p', 'school', m.school));
    if (m.yehs) who.append(el('p', 'yehs', m.yehs));
    if (!m.school && !m.yehs) who.append(el('p', 'headline', m.headline));
    li.append(avatar(m), who);
    return li;
  }

  function teamList(team) {
    const list = $('team-list');
    const rows = team.members.map(row);
    const yehs = $('team-yehs');   // 마지막 칸(NAEK YEHS)은 HTML 에 고정 — 사람 카드 뒤에 다시 붙인다
    list.replaceChildren(...rows, ...(yehs ? [yehs] : []));
    loadContacts(() => renderContacts(rows, team.members));
    list.setAttribute('aria-busy', 'false');
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
    $('team-list').setAttribute('aria-busy', 'true');
    $('team-error').hidden = true;
    try {
      const team = await fetchTeam();
      if (team.contest) { ['team-contest', 'foot-contest', 'hero-contest'].forEach((id) => { if ($(id)) $(id).textContent = team.contest; }); }
      // /hi/stage 는 아직 옛 머리말(「함께 만든 사람들을…」) — 사람 수로 바꿔 준다. /hi 는 포스터 문구 그대로
      const lead = $('team-lead');
      if (lead && !lead.querySelector('b')) lead.textContent = `${team.members.length}명이 함께 만들었어요.`;
      const c = teamList(team);
      const id = wantedId();
      const r = id && c.goTo(id);
      if (r) r.scrollIntoView({ block: 'start' });
    } catch (err) {
      root.dataset.state = 'error';
      $('team-list').setAttribute('aria-busy', 'false');
      $('team-error').hidden = false;   // role="alert" — 보이는 순간 읽어 준다
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
    // 시트가 떠 있는 동안 뒤 화면(건너뛰기 링크 · 본문 · 아래 고정 버튼)은 inert — Tab · 화면 읽기가 시트 밖으로 못 나간다(직접 짠 Tab 가두기 대신, 10-13)
    const behind = () => Array.from(document.body.children).filter((n) => n !== scrim && n.tagName !== 'SCRIPT');
    const hide = () => {
      if (scrim.hidden) return;
      scrim.hidden = true;
      behind().forEach((n) => { n.inert = false; });
      document.body.style.overflow = '';
      document.removeEventListener('keydown', onKey);
      if (opener) opener.focus();
    };
    const close = () => {
      if (history.state && history.state.overlay === 'sheet') history.back();   // popstate 가 hide()
      else hide();
    };
    window.addEventListener('popstate', () => { if (!(history.state && history.state.overlay === 'sheet')) hide(); });
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    const open = (from) => {
      funnel('inapp_notice');
      opener = from;
      hint.textContent = '';   // role="status" 는 늘 문서에 두고 글만 바꾼다(:empty 면 안 보임) — hidden 을 풀며 넣은 글은 읽지 않는 화면 읽기가 있다
      if (!(history.state && history.state.overlay === 'sheet')) history.pushState(Object.assign({}, history.state || {}, { overlay: 'sheet' }), '');
      scrim.hidden = false;
      behind().forEach((n) => { n.inert = true; });
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

  // ── 스크롤에 맞춰 한 번 떠오르기 (.rv) ─────────────────────────────────
  // 화면 아래 12% 선을 넘으면 .in 을 붙인다. 위로 건너뛴 칸(/hi/<id> · 건너뛰기 링크 · 빠른 스크롤)도 같이 켠다 —
  // IntersectionObserver 는 건너뛴 칸에 알려 주지 않아서 스크롤 위치로 직접 본다. 지금 화면 안의 칸은 숨기기 전에 먼저 켠다(깜박임 없음).
  // 움직임 줄이기 · 옛 브라우저면 아무것도 숨기지 않는다.
  function reveal() {
    const reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce || !('requestAnimationFrame' in window)) return;
    let pending = Array.from(document.querySelectorAll('.rv'));
    const check = () => {
      const line = innerHeight * 0.88;
      pending = pending.filter((n) => {
        if (n.getBoundingClientRect().top < line) { n.classList.add('in'); return false; }
        return true;
      });
      if (!pending.length) { removeEventListener('scroll', onScroll); removeEventListener('resize', onScroll); }
    };
    let queued = false;
    const onScroll = () => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => { queued = false; check(); });
    };
    check();
    document.documentElement.classList.add('rv-on');
    addEventListener('scroll', onScroll, { passive: true });
    addEventListener('resize', onScroll, { passive: true });
  }

  // ── 결선 D-day (배지) ───────────────────────────────────────────────────
  // 한국 날짜로 결선 첫날까지 며칠인지. 결선 사흘 동안은 「결선 중」, 끝나면 비운다(빈칸이면 CSS 가 숨긴다)
  function contestCountdown() {
    const box = $('contest-dday');
    if (!box) return;
    const kst = new Date(Date.now() + 9 * 3600 * 1000);
    const today = Date.UTC(kst.getUTCFullYear(), kst.getUTCMonth(), kst.getUTCDate());
    const days = Math.round((FINAL_START - today) / 86400000);
    if (days > 0) box.textContent = 'D-' + days;
    else if (days > -FINAL_DAYS) box.textContent = '결선 중';
  }

  // ── 아래 고정 버튼 띠 색 ─────────────────────────────────────────────────
  // 버튼 아래로 밝은 종이 구역이 지나가면 띠도 종이색으로 — 초록 띠가 흰 카드를 가로질러 탁하게 보였다
  function dockZone() {
    const paper = $('paper');
    if (!paper) return;
    let queued = false;
    const check = () => {
      queued = false;
      const on = paper.getBoundingClientRect().top < innerHeight - 40;
      document.documentElement.toggleAttribute('data-dock', on);
      if (on) document.documentElement.dataset.dock = 'paper';
    };
    const onScroll = () => { if (!queued) { queued = true; requestAnimationFrame(check); } };
    addEventListener('scroll', onScroll, { passive: true });
    addEventListener('resize', onScroll, { passive: true });
    check();
  }

  // ── 투어 첫 화면 미리 받기 ───────────────────────────────────────────────
  // 「척척발표 살펴보기」 를 누르면 index.html 이 app.css · app.js · 투어 묶음을 처음부터 받았다. /hi 를 다 그린 뒤 한가할 때 미리 받아 둔다.
  // 주소는 intro.html <template id="tour-prefetch"> 에서 읽는다 — HTML 안이라 브리지가 ?v= 를 index.html 과 같은 내용 해시로 바꿔 준다
  // (JS 문자열은 안 바꿔 줘서 캐시가 어긋난다). 데이터 절약 · 2G 면 받지 않는다
  function prefetchTour() {
    const tpl = $('tour-prefetch');
    const conn = navigator.connection;
    if (!tpl || !tpl.content || (conn && (conn.saveData || /(^|-)2g$/.test(conn.effectiveType || '')))) return;
    tpl.content.querySelectorAll('[href], [src]').forEach((n) => {
      const l = document.createElement('link');
      l.rel = 'prefetch';
      l.href = n.getAttribute('href') || n.getAttribute('src');
      document.head.appendChild(l);
    });
  }
  const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 1200));
  if (document.readyState === 'complete') idle(prefetchTour, { timeout: 4000 });
  else addEventListener('load', () => idle(prefetchTour, { timeout: 4000 }), { once: true });

  // ── 시작 ────────────────────────────────────────────────────────────────
  reveal();
  contestCountdown();
  dockZone();
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
