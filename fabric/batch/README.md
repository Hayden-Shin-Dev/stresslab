# Fabric 1

여기서는 과거 데이터와 확정 일별 상태를 만들면 돼.

| 폴더 | 할 일 |
| --- | --- |
| pipelines | ingestion의 KRX, ECOS, DART 수집 실행과 재시도 |
| notebooks | Bronze 원본 보관, Silver 정제, Gold 테이블 생성 |
| quality | 중복, 누락, 기업행사, 공개시각, 종목 구성 검사 |

넘길 테이블은 instrument_history, trading_calendar, daily_price, macro_observation, disclosure야. market_state와 state_member에는 confirmed_daily 결과를 넣어.

[컬럼 목록](../../contracts/tables/fabric-columns.csv), [생성 SQL](../../contracts/tables/fabric.sql), [산식](../../contracts/tables/metrics.csv)을 기준으로 만들어. 실제 전달은 Lakehouse Delta 테이블이야. Fabric 2와 분석 담당이 읽어.

과거 당시 종목 구성과 데이터 버전을 남겨. 원본에 없는 과거 발표시각이나 수정주가는 임의로 채우지 마. 값이 없으면 NULL과 사유를 넘겨.
