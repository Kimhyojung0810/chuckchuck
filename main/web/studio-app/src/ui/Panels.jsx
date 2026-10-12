/* 정거장 창 내용 — ds.css 부품 (DESIGN_SYSTEM §6). 시제품 자리표시 내용이고, 3차에서 지금 앱 화면으로 바뀐다 */
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

export function ReportWindow({ onNext }) {
  return (
    <div className="ds-window ds-window--paper sx-fill">
      <div className="ds-window__head"><span className="ds-window__no">04</span><span className="ds-window__name">리포트</span><span className="ds-window__end"><span className="ds-mono">수면발표.pdf · 4분 52초</span></span></div>
      <div className="ds-window__body">
        <div className="sx-report">
          <div className="ds-score"><span className="ds-label">발표 준비도</span><span className="ds-score__num">78</span><span className="ds-mono">100점 만점</span></div>
          <div>
            <h2 className="ds-h2" id="t-report" tabIndex={-1} style={{ fontSize: 22, marginBottom: 14 }}>자료는 잘 따라갔고, 근거 두 군데를 말로 빠뜨렸어요</h2>
            <div className="ds-rows">
              <div className="ds-row"><span className="ds-mono">p.03</span><span>수면 부족과 판단력</span><span className="ds-verdict ds-verdict--ok">맞아요</span></div>
              <div className="ds-row"><span className="ds-mono">p.07</span><span>6시간 기준의 출처</span><span className="ds-verdict ds-verdict--om">빠뜨렸어요</span></div>
              <div className="ds-row"><span className="ds-mono">p.09</span><span>실험 설계의 한계</span><span className="ds-verdict ds-verdict--mid">일부만</span></div>
              <div className="ds-row"><span className="ds-mono">Q1</span><span>수치의 출처를 묻는 질문</span><span className="ds-verdict ds-verdict--no">다시 답해 봐요</span></div>
            </div>
          </div>
        </div>
      </div>
      <div className="ds-window__foot">
        <span className="ds-mono">질문 3개 중 2개 답함</span>
        <span className="ds-window__end"><button className="ds-btn ds-btn--primary" type="button" onClick={onNext}>새 리허설 시작하기 <Arrow /></button></span>
      </div>
    </div>
  )
}
