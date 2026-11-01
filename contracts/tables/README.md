# Fabric 테이블

컬럼은 [fabric-columns.csv](fabric-columns.csv), 생성문은 [fabric.sql](fabric.sql)을 확인하시면 됩니다. 실제 전달은 Lakehouse Delta 테이블로 하고, CSV는 컬럼 확인용입니다. Spark Notebook에 Lakehouse를 연결한 뒤 SQL 셀에서 생성문을 실행합니다.

| 담당 | 만들 테이블 | 넘길 곳 |
| --- | --- | --- |
| Fabric 1 | instrument_history, trading_calendar, daily_price, macro_observation, disclosure | Fabric 2, 분석 담당 |
| Fabric 1 | market_state, state_member의 confirmed_daily | 분석 담당, 시장 상태 API |
| Fabric 2 | minute_bar | Lakehouse 이력, 분석 담당 |
| Fabric 2 | market_state, state_member의 provisional_daily와 intraday | 시장 상태 API, 분석 담당 |

두 담당자가 같은 테이블을 쓸 때는 state_kind와 snapshot_id를 나누고 전체 덮어쓰기는 하지 않습니다. 실시간 결과는 Eventhouse에서 먼저 조회하고, 같은 컬럼으로 Lakehouse에도 보관합니다. Eventhouse에서는 STRING=string, TIMESTAMP=datetime, DOUBLE=real, INT/BIGINT=long, BOOLEAN=bool로 매핑합니다.

시간은 UTC timestamp, 거래일은 한국 날짜로 저장합니다. 예시의 Z는 UTC라는 뜻입니다. 수익률과 비율은 1%=0.01, 금리 수준은 3.5%=3.5입니다. 금리 충격 100bp는 금리 수준 1.0 차이로 계산합니다.

대상은 KOSPI 보통주입니다. 우선주, ETF, ETN, REIT와 분류 미확인 종목은 포함하지 않습니다. 현재 종목 명단이 아닌 당시 유효한 종목 구성을 사용합니다. 종목 정보 변경은 기존 행을 보존하고 새 버전으로 기록합니다.

NULL은 누락을 뜻하며 0으로 대체하지 않습니다. 거래 정지, 데이터 누락, 장외 시세는 구분합니다. 수정주가나 기업행사 조정이 확인되지 않은 수익률은 review로 두고 정식 재현에서 제외합니다. 정정 데이터도 기존 버전을 보존합니다.

원천의 과거 공개시각을 모르면 available_at은 최초 수집시각으로 기록합니다. 오늘 받은 과거 데이터를 당시에도 알고 있었다고 표시하지 않습니다. 분석 담당이 시점 검증 가능 여부를 따로 판단할 수 있어야 합니다.

컬럼 계약은 v1 초안입니다. 수집과 정제는 이 기준으로 시작하고, 분석 채택 여부는 별도로 검증합니다. 테이블을 만든 뒤 작업 영역, Lakehouse, 테이블명, 갱신 주기, 마지막 성공시각을 담당자에게 전달합니다.

매번 새 스냅샷을 만들고 market_state의 종목 수가 state_member의 포함 여부와 맞는지 검사합니다. 부분 수신은 partial, 계산 불가는 unavailable로 표시합니다. 기존 PoC 필드명과 단위 변환은 분석 담당이 어댑터에서 처리해야 합니다. 이 계약을 기존 엔진이 그대로 읽는 상태는 아직 아닙니다.
