# web

현재는 [실시간 확인 화면](https://red-field-0b8ece310.1.azurestaticapps.net/)만 배포합니다. 접속하면 자동으로 체결을 받습니다. PoC 화면과 ML 결과는 포함하지 않습니다.

quote-monitor/index.html과 monitor.js가 화면 코드입니다. Azure Function에서 연결 주소를 받고 Web PubSub WebSocket으로 수신합니다. 주기적인 시세 조회는 하지 않습니다.

quote-monitor/deploy.py를 실행하면 기존 swa-whatif-dev에 배포합니다. Azure CLI 로그인과 Node.js가 필요합니다. 배포 토큰은 코드에 저장하지 않습니다.
