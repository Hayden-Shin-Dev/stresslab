# prompts

토론 실행기가 실행할 때 `common.md` + `roles/<role>.md`를 이어 붙여 각 페르소나의 시스템 프롬프트로 씁니다. `moderator.md`는 요약 담당 프롬프트입니다. 파일 내용의 해시가 `prompt_version`으로 발언마다 저장됩니다.

| 파일 | 내용 | 담당 |
| --- | --- | --- |
| common.md | 네 역할 공통 정책 (기획서 V1.3 공통부 그대로) | 페르소나 프롬프트 담당 |
| roles/macro.md, roles/risk.md | 기획서 V1.3 역할부 (팀 코드 대응 문장만 새 역할 코드로 수정) | 페르소나 프롬프트 담당 |
| roles/market.md, roles/portfolio.md | **초안**. 시장흐름→장중 시장상태, 자산배분→포트폴리오 역할 변경에 맞춰 작성 | 페르소나 프롬프트 담당이 다듬기 |
| moderator.md | 요약 담당 | 토론 실행기 |

## 프롬프트를 고칠 때 지킬 것

- 역할 코드는 `macro`, `market`, `risk`, `portfolio`입니다. (기존 flow, allocation은 쓰지 않습니다.)
- `[역할 전용 persona_data]`의 키는 `contracts/debate/persona_output.<role>.schema.json`과 같아야 합니다. 키를 바꾸려면 `services/debate/src/contracts.py`를 함께 고칩니다.
- 출력 형식은 Azure OpenAI structured outputs(strict)로 강제됩니다. 프롬프트의 출력 설명과 스키마가 다르면 스키마가 이깁니다.
- `ui_requests`는 스키마상 `{type, refs, role, reason}` 고정 형태입니다. (기획서의 payload 객체 대신)
- 모델 입력의 D_sources는 실행기가 Stress Engine 결과와 시장 상태 스냅샷에서 만듭니다. 사용 가능한 `metric_id` 목록은 `services/debate/src/evidence.py`에 있습니다.
- 아직 고칠 곳: common.md의 도구 이름(`get_daily_result` 등)과 R1/M17 표현은 현재 구조(요청별 run_id, snapshot_id)에 맞게 다듬어야 합니다. macro.md의 `[다른 페르소나와 토론]`은 옛 역할(수급, 자산배분)을 언급합니다.
