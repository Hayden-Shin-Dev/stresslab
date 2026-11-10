# 현재가 갱신

Event Hubs를 소비하는 Azure Functions 코드입니다. 종목별 최신 가격을 PostgreSQL에 저장하고 Web PubSub으로 전달합니다. 장중 위험 집계는 Fabric에서 담당합니다. 오래된 이벤트가 최신 가격을 덮어쓰지 않도록 합니다.

## 웹 전달 방식

1. Event Hubs 배치에서 종목별 최신값을 PostgreSQL `quote_latest`에 저장합니다.
2. 1초 주기 Timer가 저장값을 읽고, 변경된 종목의 최신값만 한 묶음으로 PubSub에 보냅니다. 체결 원본을 모두 보내지 않습니다.
3. 웹 첫 접속과 재연결 시 `GET /api/quotes/latest`로 현재가를 먼저 읽습니다. 이후 갱신은 WebSocket을 사용합니다.

Fabric으로 들어가는 원본 체결과 Event Hubs 설정은 유지합니다. 웹 조회 대상은 수집기의 `ingestion/kiwoom/universe.json`을 배포할 때 함께 복사합니다. 현재 20종목이며, 확대 시 같은 목록으로 다시 배포하면 됩니다. 예전에 저장된 다른 종목은 삭제하지 않지만 웹에 노출하지 않습니다.

웹 메시지는 `quote_latest` 조회 결과입니다. DB에 없는 개별 체결량과 날짜 추정 여부는 `null`로 전달합니다. 원본 체결 계약을 변경한 것은 아닙니다. 저장 시각을 현재 체결 시각으로 바꾸지 않습니다.

Timer는 기존 Functions 저장소의 실행 잠금을 사용합니다. 1초는 목표 갱신 주기이며 처리 지연 중에는 늦어질 수 있습니다. 변경이 없으면 전송하지 않고, 실패하면 다음 실행에서 최신값을 재전송합니다. 서버 재시작 시 최신값이 다시 전달될 수 있어 웹에서도 중복을 제거합니다.

## 검증과 배포

`python services/quote-updater/tests/test_latest.py`로 순서 역전, 전송 간격, 실패 후 재시도, 초기 조회를 검증합니다. `deploy.py`는 기존 Function에 코드만 배포하며 리소스, 권한, 환경변수, CORS를 수정하지 않습니다.

| 폴더 | 내용 |
| --- | --- |
| [src](src/) | 현재가 저장과 전달 함수 |
| [tests](tests/) | 중복 수신과 순서 역전 검증 |
