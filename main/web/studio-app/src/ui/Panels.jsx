/* 정거장 창 내용 — ds.css 부품 (DESIGN_SYSTEM §6). 시제품 자리표시 내용이고, 3차에서 지금 앱 화면으로 바뀐다 */
import { useEffect, useRef } from 'react'
import { VoiceOrb } from './VoiceOrb.jsx'

const Arrow = () => <span className="ds-btn__arrow">→</span>

export function UploadWindow({ onNext }) {
  return (
    <div className="ds-window sx-fill">
      <div className="ds-window__head"><span className="ds-window__no">01</span><span className="ds-window__name">자료 올리기</span></div>
      <div className="ds-window__body">
        <h1 className="ds-title" id="t-upload" tabIndex={-1}>발표 자료를 올려 주세요</h1>
        <p className="ds-lede">자료를 넘기며 카메라 앞에서 발표하면, 말한 내용과 자료를 맞대어 빠뜨린 곳을 찾고 예상 질문을 준비해요.</p>
        <div className="ds-drop">
          <button className="ds-btn" type="button">발표 자료 고르기</button>
          <div className="ds-file"><span className="ds-file__name">수면발표.pdf</span><span className="ds-mono">PDF · 12장 · 4.2MB</span></div>
        </div>
        <dl className="ds-meta">
          <dt>발표 시간</dt><dd>5분 <span className="ds-mono">/ 장당 약 25초</span></dd>
          <dt>질문</dt><dd>3개 <span className="ds-mono">/ 답까지 마치면 리포트</span></dd>
        </dl>
        <label className="ds-check"><input type="checkbox" defaultChecked /> <span>이 자료와 발표 기록을 척척발표가 나아지는 데 써도 좋아요</span></label>
      </div>
      <div className="ds-window__foot">
        <span className="ds-mono">자료를 읽었어요 · 12장</span>
        <span className="ds-window__end"><button className="ds-btn ds-btn--primary" type="button" onClick={onNext}>발표하러 가기 <Arrow /></button></span>
      </div>
    </div>
  )
}

/** 내 모습 — 창 안의 <video>, 거울처럼 좌우 반전 */
function Mirror({ stream }) {
  const v = useRef(null)
  useEffect(() => {
    const el = v.current
    if (!el) return
    el.srcObject = stream || null
    if (stream) el.play().catch(() => {})
  }, [stream])
  return <video ref={v} className="sx-mirror" autoPlay muted playsInline aria-label="내 모습" />
}

/** ② ③ 카메라 창 — 카메라가 중심 (SPACE v3 §6). 영상 위 작은 창은 CSS 유리 */
export function CameraStage({ mode, cam, mic, onNext }) {
  if (cam.state !== 'on') return <CameraPrompt cam={cam} titleId={mode === 'present' ? 't-present' : 't-qa'} />
  return (
    <div className="sx-stage">
      <Mirror stream={cam.stream} />
      {mode === 'present' ? (
        <>
          <h2 className="ds-sr" id="t-present" tabIndex={-1}>발표하고 있어요</h2>
          <div className="sx-float sx-float--slide"><SlideWindow /></div>
          <div className="sx-float sx-float--bar"><PresentBar mic={mic} onNext={onNext} /></div>
        </>
      ) : (
        <>
          <div className="sx-float sx-float--q"><QuestionWindow /></div>
          <div className="sx-float sx-float--a"><AnswerWindow mic={mic} onNext={onNext} /></div>
        </>
      )}
    </div>
  )
}

/** 카메라를 켜기 전 — 그 자리에 무엇이 오는지 말하고, 버튼을 눌러야 묻는다 */
export function CameraPrompt({ cam, titleId }) {
  return (
    <div className="ds-window sx-fill sx-center">
      <div className="ds-window__body" style={{ alignContent: 'center', justifyItems: 'center', textAlign: 'center' }}>
        <h2 className="ds-h2" id={titleId} tabIndex={-1}>카메라를 켜면 여기에 내 모습이 크게 보여요</h2>
        <p className="ds-lede">발표하는 내 모습이 화면 한가운데 와요. 영상은 이 브라우저 밖으로 나가지 않아요.</p>
        {cam.state === 'denied'
          ? <p className="ds-field__error">카메라를 쓸 수 없어요. 브라우저 주소창의 카메라 권한을 켜면 다시 할 수 있어요.</p>
          : <button className="ds-btn ds-btn--primary" type="button" onClick={cam.start} disabled={cam.state === 'asking'}>{cam.state === 'asking' ? '권한을 기다리고 있어요' : '카메라 켜기'} <Arrow /></button>}
      </div>
    </div>
  )
}

export function SlideWindow() {
  return (
    <div className="ds-window sx-fill">
      <div className="ds-window__head"><span className="ds-window__no">p.03</span><span className="ds-window__name">자료</span>
        <span className="ds-window__end"><span className="ds-pager"><button type="button" aria-label="이전 장">‹</button><span className="ds-mono">3 / 12</span><button type="button" aria-label="다음 장">›</button></span></span></div>
      <div className="ds-window__body ds-window__body--fill" style={{ padding: 14 }}>
        <div className="sx-slide">
          <div className="sx-slide__title">수면이 부족하면 판단력은 어떻게 흐려질까</div>
          <div className="sx-slide__line" style={{ width: '82%' }} />
          <div className="sx-slide__line" style={{ width: '64%' }} />
          <div className="sx-slide__line" style={{ width: '71%' }} />
        </div>
      </div>
    </div>
  )
}

export function PresentBar({ mic, onNext }) {
  return (
    <div className="sx-bar">
      <VoiceOrb levelRef={mic.level} size={52} />
      <div className="sx-bar__state">
        {mic.on ? <span className="ds-status ds-status--rec">말하는 소리를 듣고 있어요</span> : <span className="ds-status ds-status--off">마이크가 꺼져 있어요</span>}
        <span className="ds-mono">시제품 — 녹음은 저장하지 않아요</span>
      </div>
      <span className="ds-window__end">
        {!mic.on && <button className="ds-btn" type="button" onClick={mic.start}>마이크 켜기</button>}
        <button className="ds-btn ds-btn--primary" type="button" onClick={onNext}>발표 끝내고 질문 받기 <Arrow /></button>
      </span>
    </div>
  )
}

export function QuestionWindow() {
  return (
    <div className="ds-window sx-fill">
      <div className="ds-window__head"><span className="ds-window__no">Q1</span><span className="ds-window__name">심사위원 · 자료 7장</span>
        <span className="ds-window__end"><span className="ds-dots" role="img" aria-label="질문 1 / 3"><span className="is-now" /><span /><span /></span></span></div>
      <div className="ds-window__body" style={{ paddingTop: 16, paddingBottom: 16 }}>
        <h2 className="ds-card__text" id="t-qa" tabIndex={-1}>7장에서 「수면이 6시간 아래면 판단 실수가 두 배」 라고 했는데, 이 수치는 어떤 연구에서 나왔나요?</h2>
      </div>
    </div>
  )
}

export function AnswerWindow({ mic, onNext }) {
  return (
    <div className="sx-answer">
      <VoiceOrb levelRef={mic.level} size={88} />
      <div className="sx-answer__main">
        <span className="ds-label">{mic.on ? '듣고 있어요 — 말로 답해 보세요' : '말로 답하거나 글로 적어요'}</span>
        <textarea className="ds-textarea" aria-label="내 답" placeholder="여기에 적어도 돼요" rows={2} />
      </div>
      <div className="sx-answer__actions">
        {!mic.on && <button className="ds-btn" type="button" onClick={mic.start}>말로 답하기</button>}
        <button className="ds-btn ds-btn--quiet" type="button">힌트 보기</button>
        <button className="ds-btn ds-btn--primary" type="button" onClick={onNext}>답 보내고 리포트 보기 <Arrow /></button>
      </div>
    </div>
  )
}

/** ④ 리포트 — 지금 앱의 리포트 화면을 그대로 (사용자 10-13). 같은 출처 iframe 이라 앱의 세션 데이터를 그대로 읽는다.
 *  앱 파일은 고치지 않는다 — 메뉴 · 상단바만 바깥에서 스타일로 감추고, 리포트 밖으로 나가는 주소는 스튜디오의 「새 리허설」 로 돌린다 */
const FRAME_CSS = `
  :root { --nav-w: 0px !important; }
  .sidenav, .topbar { display: none !important; }
  html, body { background: transparent !important; }
  body { padding-left: 0 !important; }
`
/** 이 탭의 리포트가 없으면 지금 앱이 저장해 둔 마지막 리포트(#/report/last — localStorage, 탭이 달라도 남는다)를 연다 */
function reportUrl() {
  try { if (JSON.parse(localStorage.getItem('cheokcheok:last-report') || 'null')) return '/index.html#/report/last' } catch (_) { /* 사생활 모드 */ }
  return '/index.html#/report'
}

export function ReportWindow({ onNext, load }) {
  const frame = useRef(null)
  const onLoad = () => {
    const win = frame.current?.contentWindow
    const doc = frame.current?.contentDocument
    if (!win || !doc) return
    const st = doc.createElement('style')
    st.textContent = FRAME_CSS
    doc.head.appendChild(st)
    // 앱은 데스크톱 판(1336×1024)을 창 높이에 맞춰 줄인다 — 창 안에서는 글자가 너무 작아져서, 폭에만 맞춘다(리포트는 스크롤)
    const fit = doc.createElement('style')
    const refit = () => {
      const k = Math.min(1, win.innerWidth / 1336)
      // 판 높이를 틀 높이에 맞춘다(판 단위) — 넘치면 위아래가 잘리던 것을 막고, 안쪽 스크롤로 읽는다
      fit.textContent = `:root { --artboard-scale: ${k.toFixed(3)} !important; --artboard-h: ${Math.round(win.innerHeight / k)}px !important; }`
    }
    refit(); doc.head.appendChild(fit); win.addEventListener('resize', refit)
    win.addEventListener('hashchange', () => {
      if (!/^#\/?report(\/|$)/.test(win.location.hash)) {   // 「홈으로」 「새 발표 연습」 … → 스튜디오가 처음 정거장으로
        win.location.replace(reportUrl().replace('/index.html', ''))
        onNext()
      }
    })
  }
  return (
    <div className="ds-window ds-window--paper sx-fill">
      <div className="ds-window__head"><span className="ds-window__no">04</span><span className="ds-window__name" id="t-report" tabIndex={-1}>리포트</span>
        <span className="ds-window__end"><span className="ds-mono">지금 앱의 리포트 화면</span></span></div>
      <div className="sx-frame-wrap">
        {load
          ? <iframe ref={frame} className="sx-frame" src={reportUrl()} title="발표 리포트" onLoad={onLoad} />
          : <p className="ds-lede" style={{ padding: 32 }}>리포트를 불러오고 있어요</p>}
      </div>
      <div className="ds-window__foot">
        <span className="ds-mono">리포트 안에서 스크롤해요</span>
        <span className="ds-window__end"><button className="ds-btn ds-btn--primary" type="button" onClick={onNext}>새 리허설 시작하기 <Arrow /></button></span>
      </div>
    </div>
  )
}
