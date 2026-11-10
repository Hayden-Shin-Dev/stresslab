# src

| 파일 | 내용 |
| --- | --- |
| worker.py | Service Bus 세션 수신, 잠금 연장, complete/abandon/dead-letter. 실행 진입점 |
| api.py | 토론 요청 API(FastAPI): 토론 시작·질문을 큐에 넣기, Web PubSub 토큰, 놓친 이벤트 조회. `uvicorn api:app` |
| schedule.py | 정시 회의 요청. Container Apps 예약 작업이 `python schedule.py 0830`처럼 실행 |
| orchestrator.py | 토론 순서(근거 고정 → 초기 발언 → 쟁점 반론 → 요약), 사용자 질문, 재처리 |
| evidence.py | Stress Engine 결과·시장 상태 스냅샷 → 역할별 D/S 근거 묶음 |
| validate.py | 모델 출력 검증과 출처 배열 정규화 |
| llm.py | Azure OpenAI 호출(structured outputs), 프롬프트 로딩, 동시 호출 제한 |
| store.py | PostgreSQL 저장소와 테스트용 메모리 저장소 |
| publisher.py | 저장된 이벤트를 Web PubSub 그룹으로 발행 |
| sources.py | Stress Engine, 시장 상태 API 조회 |
| contracts.py | 큐 메시지·출력 스키마·이벤트 정의 (기준) |
| export_contracts.py | contracts.py → contracts/debate/*.schema.json 생성 |
