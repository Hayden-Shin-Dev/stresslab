# KQL

완료된 분봉으로 장 시작 이후 누적 흐름과 최근 구간의 시장 상태를 계산합니다. 최근 5분 가격 등락률, 변동성, 거래량, 업종 등락, 하락 확산, 동조화와 위험 신호를 market_state_snapshot v2로 전달합니다.

[지표별 쉬운 설명](../README.md#지표별-의미)을 먼저 확인하세요. [계산 참조](../reference/)와 같은 입력으로 결과를 대조하세요. 누락을 0으로 채우지 말고 관측 범위와 계산 가능 여부를 함께 전달합니다.

## 구성 (eventhouse_whatif)

| 이름 | 종류 | 내용 |
| --- | --- | --- |
| quote_events | 테이블 | Eventstream이 적재하는 quote_event 원문. 보존 30일 |
| bars_1m | 테이블 | 1분봉과 정정 이력. 보존 400일 |
| market_state_history | 테이블 | 매분 스냅샷. 보존 90일 |
| universe_assets | 테이블 | 20종목 목록 |
| previous_close, asset_sector | 테이블 | 전일 확정 종가와 업종. 2026-11-03 현재 비어 있음 |
| market_state_v2() | 함수 | [market_state_v2.kql](market_state_v2.kql). 인자가 없으면 실시간, as_of_in을 주면 재계산 |
| market_state_latest(), market_state_current() | 함수 | history 조회. 시장 상태 API가 latest를 사용 |

## Fabric 파이프라인 pl_realtime_session

매분 실행하며 [조건](regular_session_condition.txt)으로 평일 09:01~15:21 KST에만 활동을 실행합니다.

| 활동 | 쿼리 |
| --- | --- |
| snapshot_save | [snapshot_save.kql](snapshot_save.kql) |
| bars_1m_append | [bars_1m_append.kql](bars_1m_append.kql) |

market_state_v2는 bars_1m이 아니라 quote_events에서 직접 분봉을 만듭니다(qe_bars). 두 활동의 순서는 계산에 영향이 없습니다.

## Fabric 파이프라인 pl_realtime_close

평일 16:10 KST에 노트북 `nb_realtime_close_handoff`를 실행해 그날의 quote_events, bars_1m, market_state_history를 검사하고 batch용 마감 자료를 게시합니다. 쿼리와 게시 형식은 [notebooks](../notebooks/README.md)에 있습니다.

## 2026-11-03 수정

- 실행이 9초 넘게 늦게 시작하면 as_of가 한 분 건너뛰고 다음 실행에서 같은 분을 다시 만들었습니다(10:17, 11:19, 11:20, 11:33 KST 누락). 기준 시각을 `bin(now() - 10s, 1m)`에서 `bin(now() - 30s, 1m)`로 바꿨습니다. 평소 실행의 as_of와 지연은 같습니다.
- snapshot_save에 같은 as_of 중복 저장 방지를 추가했습니다.
- 누락된 4분은 재계산하지 않았습니다. 재계산하면 connection_status가 unknown입니다.

## 전일 종가와 업종

batch의 gold_stress_daily가 생기면 KQL DB에 OneLake 바로가기로 연결하고, 매 거래일 장 시작 전 한 번 적재합니다. 매분 Gold를 직접 읽지 않습니다.

```kusto
.set-or-replace previous_close <|
    external_table('gold_stress_daily')
    | where instrument_kind == "stock" and is_mock == false and quality_status == "valid"
    | where trading_date < startofday(now() + 9h)
    | summarize arg_max(trading_date, close, dataset_version) by asset_id
    | project asset_id, trade_date = todatetime(trading_date), close, source = dataset_version
```

previous_close 테이블의 열은 `asset_id, trade_date, close, source`이므로 데이터 버전을 `source`에 넣습니다. 적재한 trade_date가 직전 거래일인지 확인하세요. 어제 수집한 분봉의 마지막 가격은 종가 단일가 이전 가격이므로 전일 종가로 쓰지 않습니다.

## 데이터베이스 정의

테이블, 매핑, 보존 정책과 함수 전체(qe_clean, qe_bars, qe_session, qe_baseline, qe_breadth, qe_health, qe_input_quality, bars_1m_latest, bars_1m_corrections, market_state_latest, market_state_current 등)는 [database_schema.kql](database_schema.kql)에 있습니다. 2026-11-04에 내보냈고, KQL을 고친 뒤에는 `.show database schema as csl script`로 다시 내보내 이 파일을 바꿉니다.
