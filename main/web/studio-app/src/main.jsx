import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import { APP_START } from './ui/Frame.jsx'

// 스튜디오가 iframe 안에 실렸으면(정면 창이 잘못 /studio 를 열었을 때) 스튜디오를 또 그리지 않고 앱으로 — 화면이 겹쳐 보였다 (10-13)
if (window.self !== window.top) location.replace(APP_START)
else createRoot(document.getElementById('studio-root')).render(<App />)
