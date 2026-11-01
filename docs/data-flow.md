# 데이터 연결

| 출발 | 처리 | 도착 |
| --- | --- | --- |
| 키움 REST 및 WebSocket | ingestion/kiwoom | Event Hubs |
| Event Hubs | services/quote-updater | PostgreSQL 현재가, Web PubSub |
| Event Hubs | fabric/realtime | Eventhouse, 장중 위험 및 잠정 상태, Lakehouse 이력 |
| KRX, ECOS, DART | ingestion 및 fabric/batch 파이프라인 | Bronze 원본, Silver 정제, Gold 분석 테이블 |
| Gold와 실시간 분석 결과 | services/market-state | 기준시각이 고정된 상태 스냅샷 |
| 상태, 과거 사건, 사용자 조건, 현재 보유자산 | services/stress-engine 및 analytics | 과거 사건 재현 손익, 기여도, 근거 |
| 웹 및 모바일 | services/api | 시나리오 실행, 저장, 비교, 보고서 |
| API 토론 요청 | Service Bus 및 services/debate | 주장, 반론, 근거가 포함된 최종 요약 |
| 토론 실행기 | services/tools, AI Search, stress-engine | 출처 확인 및 동일 조건 재계산 |

확정 일별 검색은 전일까지 확인된 자료를 사용합니다. 잠정 일별 검색은 현재 가격을 반영한 근사 비교이며 별도의 검증 상태를 가집니다. 과거 일봉과 현재 분봉을 동일 관측으로 취급하지 않습니다.

과거 사건 재현은 같은 사건 기간의 종목별 수익률을 현재 보유금액에 적용합니다. 현재가 변화와 사건 선택 변화가 손익에 미친 영향을 구분합니다. 실시간 변동성이 높다는 이유만으로 과거 손실률을 확대하지 않습니다.

Data Science 실험과 검증 코드는 analytics에서 관리하고 Fabric에서 실행합니다. 승인된 모델이나 분석 패키지만 배포 대상으로 삼습니다. MLflow 기록과 배포 자동화는 구현 예정이며 Azure ML 도입을 전제로 하지 않습니다.

현재 계산 구조는 재검증 중입니다. 기존 조건부 Ridge를 유지하고 동일 상태와 충격으로 과거 사례를 연결하는 방식을 비교합니다. 위 표의 사건 재현은 별도 근거이며 ML 계산을 대체하는 확정 엔진이 아닙니다. 실시간 입력과 최종 Gold 테이블은 검증 후 확정합니다.
