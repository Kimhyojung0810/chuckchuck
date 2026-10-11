/*
 * /hi 부스 랜딩 (2026-10-11, docs/booth-mobile/team-schema.md).
 * 히어로·주 버튼은 HTML 만으로 그려지고, 이 파일은 (1) data/team.json 으로 팀 카드를 그리고 (2) 카드 넘기기를 버튼·점·키보드로도
 * 하게 하고 (3) 인앱 브라우저에서 카메라가 필요한 실제 흐름으로 갈 때만 「Safari/Chrome 으로 열기」 를 안내한다.
 * 카드 수는 members 길이로 정해진다 — 사람이 바뀌면 json 만 고친다. draft 는 화면에 표시하지 않는다(운영자만 json 에서 본다).
 * 데이터는 textContent 로만 넣는다(innerHTML 없음).
 */
(() => {
  'use strict';

  const TEAM_URL = '/data/team.json';
  const FETCH_TIMEOUT_MS = 8000;
  const ID_RE = /^[a-z0-9-]{1,24}$/;
  const PHOTO_RE = /^assets\/team\/[a-z0-9-]+\.(webp|png|jpg)$/;
  const URL_RE = /^https:\/\/[^\s"'<>]+$/;
  const AVATAR_TINTS = ['#E7FBF0', '#FFF1C2', '#F4F4F5', '#D7F5E8'];
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const str = (v) => (typeof v === 'string' ? v.trim() : '');
  // 「F-01~F-06」 같은 기능 번호는 줄이 바뀌며 「F-」 / 「01」 로 갈라지지 않게 한 덩어리로 묶는다
  const CODE_RE = /\(?[A-Z]+-\d+(?:[~·][A-Z]+-\d+)*\)?/g;
  function textWithCodes(node, text) {
    let at = 0;
    for (const m of text.matchAll(CODE_RE)) {
      node.append(text.slice(at, m.index), el('span', 'nowrap', m[0]));
      at = m.index + m[0].length;
    }
    node.append(text.slice(at));
    return node;
  }

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
        did: (Array.isArray(m.did) ? m.did : []).map(str).filter(Boolean).slice(0, 3),
        quote: str(m.quote),
        photo: PHOTO_RE.test(m.photo || '') ? '/' + m.photo : '',
        links: (Array.isArray(m.links) ? m.links : [])
          .filter((l) => l && str(l.label) && URL_RE.test(l.url || '')).slice(0, 3),
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

  // ── 카드 ────────────────────────────────────────────────────────────────
  function avatar(m, i) {
    const box = el('div', 'avatar');
    box.style.setProperty('--av', AVATAR_TINTS[i % AVATAR_TINTS.length]);
    box.setAttribute('aria-hidden', 'true');
    const initial = () => {
      box.textContent = Array.from(m.name)[0] || '';
      const svgNs = 'http://www.w3.org/2000/svg';
      const chick = document.createElementNS(svgNs, 'svg');
      chick.setAttribute('class', 'chick');
      chick.setAttribute('viewBox', '0 0 100 100');
      const use = document.createElementNS(svgNs, 'use');
      use.setAttribute('href', '#chick');
      chick.appendChild(use);
      box.appendChild(chick);
    };
    if (!m.photo) { initial(); return box; }
    const img = el('img');
    Object.assign(img, { src: m.photo, alt: '', width: 64, height: 64, loading: 'lazy', decoding: 'async' });
    img.addEventListener('error', () => { img.remove(); initial(); }, { once: true });
    box.appendChild(img);
    return box;
  }

  function card(m, i, n) {
    const c = el('article', 'card');
    c.id = 'member-' + m.id;
    c.dataset.id = m.id;
    c.setAttribute('role', 'group');
    c.setAttribute('aria-roledescription', '팀원 카드');
    c.setAttribute('aria-label', `${n}명 중 ${i + 1}번째, ${m.name}`);

    const head = el('div', 'card-head');
    const who = el('div', 'who');
    who.append(el('h3', 'name', m.name), el('p', 'role', m.role));
    head.append(avatar(m, i), who);
    c.append(head, el('p', 'headline', m.headline));

    if (m.did.length) {
      const listId = 'did-' + m.id;
      const label = el('p', 'did-label', '척척발표에서 만든 것');
      label.id = listId + '-label';
      const ul = el('ul', 'did');
      ul.setAttribute('aria-labelledby', label.id);
      m.did.forEach((t) => ul.appendChild(textWithCodes(el('li'), t)));
      c.append(label, ul);
    }
    if (m.quote) c.appendChild(el('blockquote', 'quote', m.quote));
    if (m.links.length) {
      const box = el('div', 'links');
      m.links.forEach((l) => {
        const a = el('a', null, l.label);
        Object.assign(a, { href: l.url, target: '_blank', rel: 'noopener noreferrer' });
        box.appendChild(a);
      });
      c.appendChild(box);
    }
    const count = el('p', 'card-count', `${i + 1} / ${n}`);
    count.setAttribute('aria-hidden', 'true');
    c.appendChild(count);
    return c;
  }

  // ── 넘기기 ──────────────────────────────────────────────────────────────
  function carousel(team) {
    const root = document.querySelector('.carousel');
    const track = $('team-track');
    const dotsBox = $('team-dots');
    const prev = $('team-prev');
    const next = $('team-next');
    const status = $('team-status');
    const { members } = team;
    const n = members.length;

    track.replaceChildren(...members.map((m, i) => card(m, i, n)));
    const cards = Array.from(track.children);
    const dots = members.map((m, i) => {
      const d = el('button', 'dot');
      d.type = 'button';
      d.setAttribute('aria-label', `${i + 1}번째, ${m.name}`);
      d.setAttribute('aria-controls', 'team-track');
      d.addEventListener('click', () => go(i, true));
      return d;
    });
    dotsBox.replaceChildren(...dots);
    if (n > 6) dotsBox.dataset.many = '';
    $('team-pager').hidden = n < 2;
    root.dataset.state = 'ready';

    let active = -1;
    const padLeft = () => parseFloat(getComputedStyle(track).scrollPaddingLeft) || 0;

    function mark(i, announce) {
      if (i === active) return;
      active = i;
      cards.forEach((c, k) => c.toggleAttribute('data-active', k === i));
      dots.forEach((d, k) => d.setAttribute('aria-current', k === i ? 'true' : 'false'));
      prev.disabled = i === 0;
      next.textContent = i === n - 1 ? '처음으로' : '다음 사람';
      next.setAttribute('aria-label', i === n - 1 ? `처음 사람 보기, ${members[0].name}` : `다음 사람 보기, ${members[i + 1].name}`);
      if (announce) status.textContent = `${n}명 중 ${i + 1}번째, ${members[i].name}`;
    }

    function go(i, announce) {
      const k = (i + n) % n;
      track.scrollTo({ left: cards[k].offsetLeft - padLeft(), behavior: reduceMotion.matches ? 'auto' : 'smooth' });
      mark(k, announce);
    }

    // 손가락으로 넘긴 것도 따라간다 — 지금 맨 앞에 가장 가까운 카드가 현재 카드
    let raf = 0;
    track.addEventListener('scroll', () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        const x = track.scrollLeft + padLeft();
        let best = 0;
        cards.forEach((c, k) => {
          if (Math.abs(c.offsetLeft - x) < Math.abs(cards[best].offsetLeft - x)) best = k;
        });
        mark(best, true);
      });
    }, { passive: true });

    prev.addEventListener('click', () => go(active - 1, true));
    next.addEventListener('click', () => go(active + 1, true));
    track.addEventListener('keydown', (e) => {
      const to = { ArrowRight: active + 1, ArrowLeft: active - 1, Home: 0, End: n - 1 }[e.key];
      if (to === undefined || e.altKey || e.metaKey || e.ctrlKey) return;
      e.preventDefault();
      if (to >= 0 && to < n) go(to, true);
    });

    mark(0, false);
    return { goTo: (id) => {
      const k = members.findIndex((m) => m.id === id);
      if (k < 0) return false;
      track.scrollTo({ left: cards[k].offsetLeft - padLeft(), behavior: 'auto' });
      mark(k, false);
      return true;
    } };
  }

  /** /hi/<id> 또는 /hi#<id> 로 들어오면 그 사람 카드부터 보여 준다. */
  function wantedId() {
    const fromPath = location.pathname.match(/^\/hi\/([a-z0-9-]{1,24})\/?$/i);
    if (fromPath) return fromPath[1].toLowerCase();
    const h = location.hash.slice(1).toLowerCase();
    return ID_RE.test(h) && h !== 'team' && h !== 'top' && h !== 'what' ? h : '';
  }

  async function loadTeam() {
    const root = document.querySelector('.carousel');
    root.dataset.state = 'loading';
    $('team-error').hidden = true;
    try {
      const team = await fetchTeam();
      if (team.contest) { $('team-contest').textContent = team.contest; $('foot-contest').textContent = team.contest; }
      $('team-lead').textContent = `${team.members.length}명이 함께 만들었어요.`;
      const c = carousel(team);
      const id = wantedId();
      if (id && c.goTo(id)) $('team').scrollIntoView({ block: 'start' });
    } catch (err) {
      root.dataset.state = 'error';
      $('team-error').hidden = false;
      $('team-pager').hidden = true;
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
    const hint = $('inapp-hint');
    // 해시(#)가 든 주소는 Android intent 문법과 부딪힌다 — 브리지가 /rehearsal 을 #/rehearsal 로 보내 준다
    const target = location.origin + '/rehearsal';
    let opener = null;

    $('inapp-app').textContent = INAPP[1];
    if (isKakao) openBtn.textContent = '다른 브라우저로 열기';
    else if (isAndroid) openBtn.textContent = 'Chrome으로 열기';

    const close = () => {
      scrim.hidden = true;
      document.body.style.overflow = '';
      document.removeEventListener('keydown', onKey);
      if (opener) opener.focus();
    };
    const onKey = (e) => {
      if (e.key === 'Escape') { close(); return; }
      if (e.key !== 'Tab') return;
      const f = Array.from(sheet.querySelectorAll('button, a[href]'));
      const first = f[0];
      const last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    const open = (from) => {
      opener = from;
      hint.hidden = true;
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
      copyText(target).then((ok) => {
        hint.textContent = ok
          ? '주소를 복사했어요. Safari를 열고 주소창에 붙여 넣어 주세요.'
          : `복사하지 못했어요. 오른쪽 위 메뉴에서 「다른 브라우저로 열기」를 눌러 주세요.`;
        hint.hidden = false;
      });
    });

    document.querySelectorAll('[data-needs-camera]').forEach((a) => {
      a.addEventListener('click', (e) => { e.preventDefault(); open(a); });
    });
  }

  // ── 시작 ────────────────────────────────────────────────────────────────
  $('team-retry').addEventListener('click', loadTeam);
  loadTeam();
  if (INAPP) inappSheet();
})();
