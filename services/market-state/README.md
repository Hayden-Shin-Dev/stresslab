# 시장 상태 API

Fabric의 [실시간 시장 상태 스냅샷](../../contracts/realtime/README.md)과 확정 일별 상태를 구분해서 제공합니다. PostgreSQL 저장과 Web PubSub 시장 분석 결과 전달을 연결합니다. 실시간 snapshot_id와 일별 데이터 버전을 분석 실행에 함께 기록합니다. 장중 지표는 UI와 AI 근거에 사용하고 스트레스 ML은 확정 일별 상태를 사용합니다.

| 폴더 | 내용 |
| --- | --- |
| [src](src/) | 상태 조회, 저장, 갱신 알림 |
| [tests](tests/) | 시각, 지연, 관측 범위 검증 |

## 차트 이력 조회

- `KUSTO_QUERY_URI`에는 Eventhouse KQL 데이터베이스의 Query URI를 사용합니다.
- `CHART_BARS_CONTAINER_URL`이 설정된 환경에서 `CHART_KQL_HISTORY_THROUGH=2026-11-27`을 설정하면, 해당 KST 날짜까지의 확정 일봉·분봉을 `stock_price_bars_1d_latest`와 `stock_price_bars_1m_latest`로 조회합니다. 두 테이블의 적재가 모두 검증된 날짜까지만 지정합니다.
- 이후 날짜는 기존 Blob 스냅샷에서 읽습니다. API의 `history_source`로 실제 조회 경로를 확인할 수 있습니다.
- `GET /market-state/stock-prices`에서 일봉·분봉의 `from_date`와 `to_date`는 KST 기준이며 양쪽 날짜를 포함합니다.
