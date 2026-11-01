# 실시간 시장 분석

Fabric 담당 2의 작업 폴더입니다. Event Hubs의 시세를 Eventstream으로 받아 Eventhouse에 적재합니다. KQL로 장중 위험과 잠정 일별 상태를 계산합니다. 결과는 시장 상태 서비스에 전달하고, 재현에 필요한 이력은 Lakehouse에 보존합니다. 확정 일별 상태와 잠정 상태를 구분하며, 늦게 도착한 시세와 종목 관측 비율을 함께 기록합니다.

| 폴더 | 내용 |
| --- | --- |
| [eventstreams](eventstreams/) | Event Hubs 입력, 필드 매핑, Eventhouse 출력 정의 |
| [kql](kql/) | 가격, 하락 비율, 동반 하락, 거래량 및 상태 스냅샷 계산 |
| [notebooks](notebooks/) | 실시간 이력을 Lakehouse 분석용 테이블로 정리하는 작업 |
