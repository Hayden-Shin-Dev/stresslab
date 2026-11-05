# tests

Azure 없이 토론 한 건이 요청 → 근거 고정 → 발언 → 요약 → 이벤트까지 도는지 검증합니다. 가짜 모델은 입력으로 받은 근거 ID만 인용합니다.

```powershell
python -m pytest services/debate/tests -q
```

| 검증 | 테스트 |
| --- | --- |
| 전체 흐름, 이벤트 순번, 역할 순서 공개 | test_full_debate_flow |
| 역할별 근거 범위 | test_each_role_gets_only_its_evidence |
| 같은 요청 재배달 시 중복 없음 | test_redelivery_is_idempotent |
| 일시 장애 후 재배달로 이어서 완료 | test_transient_error_resumes_without_duplicates |
| 마지막 배달에서 실패 역할 표시 후 종료 | test_final_attempt_marks_role_failed_and_finishes |
| 없는 근거 ID 인용 → 1회 복구 후 실패 | test_unknown_evidence_id_is_rejected_after_one_repair |
| 화면 문장의 내부 ID 노출 차단 | test_internal_id_leak_is_rejected |
| 토론 후 사용자 질문 | test_user_question_after_debate |
| Stress 결과 없음 → 토론 실패 | test_missing_stress_run_fails_debate |
| 잘못된 메시지 dead-letter, 일시 장애 abandon | test_worker_dead_letters_bad_messages_and_abandons_transient |
| PostgreSQL 저장소로 같은 흐름 (`PG_TEST_DSN` 있을 때) | test_postgres_store.py |

fixtures: `stress_run.json`은 tail_reliability_20261103/scenario_examples.json의 환율 +5%·금리 +100bp 6종목, `market_snapshot.json`은 contracts/realtime/mock.json의 합성 스냅샷입니다.
