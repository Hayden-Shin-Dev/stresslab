# 현재가 갱신

Event Hubs를 소비하는 Azure Functions 코드입니다. 종목별 최신 가격을 PostgreSQL에 저장하고 Web PubSub으로 전달합니다. 장중 위험 집계는 Fabric에서 담당합니다. 오래된 이벤트가 최신 가격을 덮어쓰지 않도록 합니다.

| 폴더 | 내용 |
| --- | --- |
| [src](src/) | 현재가 저장과 전달 함수 |
| [tests](tests/) | 중복 수신과 순서 역전 검증 |
