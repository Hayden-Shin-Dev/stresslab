# 토론 계약

기준은 [services/debate/src/contracts.py](../../services/debate/src/contracts.py)이고, 이 폴더의 JSON 스키마는 `python services/debate/src/export_contracts.py`로 생성합니다. 직접 고치지 마세요.

| 파일 | 누가 쓰고 누가 읽나 |
| --- | --- |
| request.schema.json | FastAPI(유저 요청), Functions 타이머(정시 회의) → `debate-requests` 큐 → 토론 실행기 |
| persona_output.<role>.schema.json | 페르소나 모델 출력. Azure OpenAI structured outputs(strict)에 그대로 사용 |
| summary_output.schema.json | 요약 모델 출력 |
| event.schema.json | 토론 실행기 → Web PubSub `debate` 허브 → 웹앱 |

## 큐 메시지 보내는 법

- 큐: `debate-requests` (세션 사용, 중복 검색 사용)
- `SessionId` = `debate_id`, `MessageId` = `request_id`. 둘이 본문과 다르면 dead-letter 됩니다.
- 토론 시작은 `type=debate_start`, 진행 중·후 질문은 같은 `debate_id`로 `type=user_question`.

## Web PubSub

- 허브 `debate`, 그룹 `debate-{debate_id}`. 클라이언트 토큰은 그 그룹만 넣고 역할(roles)은 주지 않습니다.
- 이벤트는 `seq`가 1부터 빠짐없이 증가합니다. 끊겼다 다시 붙으면 마지막으로 받은 `seq` 이후를 DB(`debate_event`)에서 다시 받고, 같은 `event_id`는 한 번만 표시합니다.

| type | payload 주요 필드 |
| --- | --- |
| debate.accepted | trigger, run_id |
| debate.evidence_ready | run_id, snapshot_id, evidence_bundle_id, state_date, omitted_assets |
| message.created | message_id, role, name, title, phase, round_id, question_id, reference_message_id, summary_text, display_text, view_status, response_status, claims, uncertainty, questions_to_roles, ui_requests, persona_data, structured_source_ids, rag_source_ids |
| message.failed | message_id, role, name, title, phase, reason |
| debate.summary | message_id, status, summary_text, agreements, disagreements, next_checks |
| debate.completed | published, failed_roles |
| debate.failed | reason |

## 단위

충격 입력: 환율 `%`, 미국 10년 금리 `bp`, WTI `%`, VIX `pt`. 수익률 `%`, 차이 `%p`, 금액 `KRW`.
