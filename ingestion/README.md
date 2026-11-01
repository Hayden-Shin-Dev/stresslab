# 데이터 수집

키움 수집기는 실시간 시세를 Event Hubs로 전달합니다. KRX, ECOS, DART 수집 코드는 Fabric 배치 파이프라인에서 호출할 수 있게 구성합니다. 수집 시각과 공급자 시각을 보존하고 재시도, 연속조회, 중복 방지를 처리합니다.

| 폴더 | 내용 |
| --- | --- |
| [kiwoom](kiwoom/) | REST 조회와 WebSocket 수신. 주문 및 계좌 거래 제외 |
| [krx](krx/) | 종목 정보, 일별 시세, 시장 구성 이력 수집 |
| [ecos](ecos/) | 금리와 환율 등 거시 지표 수집 |
| [dart](dart/) | 공시 및 기업 정보 수집. 공개 시점 보존 |

키움 입력 형식은 [quote_event 계약](../contracts/realtime/README.md)을 사용합니다. REST 조회와 실제 WebSocket 체결을 구분해서 전달하세요.
