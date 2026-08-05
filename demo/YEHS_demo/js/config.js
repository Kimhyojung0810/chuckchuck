/**
 * 배포 환경 설정입니다. 빌드 도구가 없는 정적 데모라, 환경마다 이 파일 한 줄만 바꿉니다.
 *
 * 비워 두면(기본) 화면과 같은 오리진을 백엔드로 씁니다 —
 * 로컬에서 `python -m demo.bridge` 로 띄우면 화면과 API 를 한 프로세스가 같이
 * 서빙하므로 이대로 동작합니다.
 *
 * 프론트만 Netlify 같은 정적 호스팅에 올릴 때는 백엔드 주소를 여기 적습니다:
 *
 *     window.CHUCKCHUCK_API_BASE = 'https://api.example.com';
 *
 * 주의할 것 두 가지
 * 1) 반드시 https 여야 합니다. 프론트가 https 인데 백엔드가 http 면 브라우저가
 *    mixed content 로 요청을 막습니다.
 * 2) 백엔드에 CORS 가 열려 있어야 합니다. demo/bridge.py 는 이미 보냅니다
 *    (Access-Control-Allow-Origin). server/ 는 app.py 의 allow_origins 를 확인하세요.
 *
 * `?api=https://...` 쿼리로 임시 지정하면 이 값보다 우선합니다 (디버깅용).
 */
window.CHUCKCHUCK_API_BASE = '';
