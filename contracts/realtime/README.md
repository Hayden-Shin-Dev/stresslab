# 실시간 담당 작업

[schema.json](schema.json)에 입력과 출력 두 종류가 있습니다. [mock.json](mock.json)의 첫 항목은 시세 입력, 두 번째는 Fabric 분석 출력입니다. 배열 전체를 한 메시지로 보내는 예시는 아닙니다.

| 구분 | 보내는 쪽 | 받는 쪽 | 형식 |
| --- | --- | --- | --- |
| quote_event | 키움 수집기 | Event Hubs의 운영 소비자 / Fabric Eventstream | 한 종목 관측값을 JSON 한 건으로 전달 |
| market_risk_snapshot | Fabric 실시간 분석 | 시장 상태 API, PostgreSQL, Web PubSub | 한 기준시각의 위험 지표를 JSON 한 건으로 전달 |

Fabric 내부 Eventhouse와 Lakehouse 테이블은 담당자가 설계합니다. 이 계약은 앞뒤 담당자가 주고받는 형식입니다. JSON 시각은 UTC의 Z 표기로 통일하고 한국 장 운영 판단은 Asia/Seoul을 사용합니다.

## 처리 순서

1. 시세 원문을 저장하고 event_id로 중복을 제거합니다. 같은 관측값을 재전송하면 같은 ID를 유지합니다.
2. event_time으로 분봉을 만듭니다. 늦게 도착한 자료도 보존하되 최신 가격을 과거 값으로 덮어쓰지 않습니다.
3. 완료된 분봉으로 위험 지표를 계산하고 스냅샷을 만듭니다. 우선 5분마다 갱신하며 feature_version에 계산 기준을 고정합니다.
4. 시장 상태 API가 저장하고 웹과 AI에 전달합니다. 이 값으로 확정 일별 ML 입력을 덮어쓰지 않습니다.

## 계산 기준

- 가격은 원, 거래량은 주입니다. 지수 가격은 지수 단위입니다. cumulative_volume은 누적량, trade_volume은 해당 체결량입니다. REST의 trade_volume은 NULL입니다.
- event_time은 공급자 관측시각, received_at은 수신시각입니다. 날짜를 추정했으면 date_inferred=true로 표시하고 미확인 거래소·세션은 UNKNOWN/unknown으로 둡니다.
- 5분 수익률은 완료된 분봉 가격으로 `100 × (현재 분 종가 / 5분 전 종가 - 1)`을 계산합니다.
- 30분 변동성은 유효한 연속 31개 종가로 만든 30개 1분 로그수익률의 표본 표준편차(ddof=1)입니다. % 단위이며 연율화하지 않습니다. 자료가 모자라면 NULL입니다.
- 하락 비율은 유효한 5분 수익률이 음수인 종목 수 / 유효 종목 수입니다. 분모가 0이면 NULL입니다. 업종별로도 같은 기준을 사용합니다.
- expected_asset_count는 설정된 관측 종목 수입니다. valid_asset_count는 그 이하여야 하며, declining_asset_count는 valid_asset_count 이하여야 합니다. 일부 종목을 코스피 전체로 표시하지 않습니다.
- 같은 시각의 과거 거래량 비교가 검증되지 않았다면 volume_vs_same_time_ratio는 NULL입니다. 당일 누적량을 과거 하루 전체와 나누지 않습니다.
- 실제 수신 지연과 장 운영 시간을 함께 확인합니다. 초기 허용 지연은 120초이며 연결 끊김은 stale, 휴장은 market_closed로 표시합니다. 세션·날짜 미확인은 unverified로 표시합니다. age=0만으로 정상 판정하지 않습니다.
- as_of는 집계 기준시각이며 computed_at보다 늦을 수 없습니다. daily_state_date는 한국시간 기준 분석일보다 이전의 확정 거래일입니다. 동일 snapshot_id의 내용은 변경하지 않습니다.

합성 예시는 모두 is_mock=true입니다. 실제 운영에서는 제외하세요. 실제 가격과 수량의 손익 환산은 서비스 담당이 하고, Fabric은 시장 위험 지표를 전달합니다.
