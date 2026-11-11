# web

현재는 [실시간 확인 화면](https://red-field-0b8ece310.1.azurestaticapps.net/)만 배포합니다. 접속하면 자동으로 체결을 받습니다. PoC 화면과 ML 결과는 포함하지 않습니다.

quote-monitor/index.html과 monitor.js가 화면 코드입니다. Azure Function에서 연결 주소를 받고 Web PubSub WebSocket으로 수신합니다. 주기적인 시세 조회는 하지 않습니다.

quote-monitor/deploy.py를 실행하면 기존 swa-whatif-dev에 배포합니다. Azure CLI 로그인과 Node.js가 필요합니다. 배포 토큰은 코드에 저장하지 않습니다.

## 내 보유 종목 (로그인 필요)

`/holdings.html`은 Static Web Apps 로그인(Microsoft 계정) 뒤에만 열립니다. 종목(코스피 시가총액 상위 20종목 드롭다운, `holdings.js`의 `ASSETS`)과 보유 금액(원)을 저장하면 토론 API의 `PUT /api/me/holdings`로 `user_holding` 테이블에 들어갑니다. 정시 회의 대상과 (Stress Engine 연결 후) 스트레스 분석 입력이 여기서 나옵니다.

- 전제: swa-whatif-dev가 Standard 요금제이고, 토론 API(ca-debateapi-whatif-dev)가 SWA의 API 백엔드로 연결돼 있어야 합니다. 그래야 `/api/*`가 토론 API로 전달되고 SWA가 로그인 정보(`X-MS-CLIENT-PRINCIPAL`)를 넘깁니다.
- 저장하면 첫 화면(`/`)으로 돌아갑니다(`AFTER_SAVE`). 대상 종목이 바뀌면 `ASSETS`와 API의 `ALLOWED_ASSETS`를 같이 바꿉니다.
- `staticwebapp.config.json`: `/holdings.html`과 `/api/*`는 로그인 사용자만 허용합니다. 실시간 확인 화면(`/`)은 그대로 공개입니다.
- 로그인 `/.auth/login/aad`, 로그아웃 `/.auth/logout`, 내 정보 `/.auth/me`.
