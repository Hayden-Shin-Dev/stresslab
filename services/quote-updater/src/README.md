# src

`function_app.py`는 체결 배치 저장, 최신값 조회 API, 1초 전송 Timer를 담당합니다.

`live_push.py`는 변경된 최신값의 PubSub 전송과 접속 토큰 발급을 담당합니다.

`quote_universe.json`은 배포 시 수집기의 종목 목록에서 복사합니다. 별도로 종목을 정하지 않습니다.
