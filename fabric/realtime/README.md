# Fabric 실시간 담당

키움 시세를 Event Hubs에서 받아 현재 시장 위험을 계산합니다. [실시간 계약과 예시](../../contracts/realtime/README.md)를 기준으로 수집 담당과 서비스 담당을 연결하세요.

| 폴더 | 작업 |
| --- | --- |
| eventstreams | quote_event 수신, 원문 보관, Eventhouse 적재 |
| kql | 완료된 분봉으로 수익률, 변동성, 하락 비율, 업종별 위험 계산 |
| notebooks | 장중 원자료와 분석 이력을 Lakehouse에 보관 |

결과는 market_risk_snapshot으로 시장 상태 API에 전달합니다. 현재 위험 표시와 AI 근거에 사용하며, 장중 지표를 확정 일별 ML 입력에 넣지 않습니다. 일별 확정과 ML용 Gold는 Fabric 일별 담당이 맡습니다.

관측 종목 수, 유효 종목 수, 공급자 시각과 수신시각을 보존하세요. 수집되지 않은 값을 0으로 채우거나 일부 종목을 코스피 전체로 표시하지 않습니다.
