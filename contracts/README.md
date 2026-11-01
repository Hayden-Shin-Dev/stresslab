# 공통 데이터 계약

담당자 사이의 데이터 형식을 한 곳에서 관리합니다. 테이블 데이터 자체를 JSON으로 전달하는 구조가 아닙니다. Fabric 테이블은 Delta, API와 이벤트는 각 통신 형식에 맞춥니다. 현재는 폴더만 준비했으며 기존 PoC의 계약을 확정본으로 복사하지 않았습니다. 스키마 확정 시 컬럼 타입, 단위, 시각 기준, 키, 결측 처리와 버전을 함께 정의합니다.

| 폴더 | 내용 |
| --- | --- |
| [tables](tables/) | Lakehouse 및 서비스 DB 테이블 정의와 컬럼 설명 |
| [events](events/) | Event Hubs, Service Bus, Web PubSub 메시지 계약 |
| [api](api/) | 서비스 API의 OpenAPI 정의 |
| [examples](examples/) | 실제 개인정보와 인증정보가 없는 작은 합성 예시 |
