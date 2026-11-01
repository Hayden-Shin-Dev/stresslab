# Fabric 2

시세 수신과 장중 위험 및 잠정 일별 상태 계산을 담당합니다.

| 폴더 | 할 일 |
| --- | --- |
| eventstreams | Event Hubs 메시지를 Eventhouse로 적재 |
| kql | 1~5분 주기 시장 상태 계산 |
| notebooks | 분봉과 상태 이력을 Lakehouse에 보관 |

입력은 [키움 이벤트](../../contracts/events/README.md)와 Fabric 1의 종목 정보, 거래일, 일별 시세입니다. 출력은 minute_bar, market_state, state_member입니다. 상태는 시장 상태 API에 제공하고 동일 컬럼의 Delta 이력도 보관합니다.

[컬럼 목록](../../contracts/tables/fabric-columns.csv)과 [산식](../../contracts/tables/metrics.csv)을 기준으로 작성합니다. 장중 상태는 intraday, 현재가로 갱신한 일별 근사 상태는 provisional_daily로 구분합니다.

120초 넘게 오래된 시세, 날짜 추정 시세, 정규장 여부 미확인 시세는 지표에서 제외하고 사유를 기록합니다. 수신시각이 최근이라는 이유로 최신 체결로 처리하지 않습니다. 일부 종목만 관측했으면 전체 시장이라고 표시하지 않습니다.

같은 시각의 과거 거래량이 20일 쌓이기 전에는 거래량 급증 비율을 NULL로 저장합니다. 일봉 거래량을 분봉 기준값으로 사용하지 않습니다. 잠정 상태는 experimental로 넘기고 손실률을 직접 보정하지 않습니다.
