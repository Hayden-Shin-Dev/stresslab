# 시장 상태 API

Fabric의 [실시간 시장 상태 스냅샷](../../contracts/realtime/README.md)과 확정 일별 상태를 구분해서 제공합니다. PostgreSQL 저장과 Web PubSub 시장 분석 결과 전달을 연결합니다. 실시간 snapshot_id와 일별 데이터 버전을 분석 실행에 함께 기록합니다. 장중 지표는 UI와 AI 근거에 사용하고 스트레스 ML은 확정 일별 상태를 사용합니다.

| 폴더 | 내용 |
| --- | --- |
| [src](src/) | 상태 조회, 저장, 갱신 알림 |
| [tests](tests/) | 시각, 지연, 관측 범위 검증 |
