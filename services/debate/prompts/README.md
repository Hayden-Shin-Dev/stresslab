# prompts

`roles/<role>.md`는 공통 정책과 역할 지침이 모두 들어 있는 **독립형** 시스템 프롬프트입니다 (페르소나 프롬프트 V1.5를 토론 실행기에 맞게 고친 수정본). 실행기는 파일 하나를 그대로 씁니다 — 다른 파일을 이어 붙이지 않습니다. `moderator.md`는 요약 담당 프롬프트입니다. 파일 내용의 해시가 `prompt_version`으로 발언마다 저장됩니다.

| 파일 | 내용 | 담당 |
| --- | --- | --- |
| roles/macro.md | 김진우 거시경제 | 페르소나 프롬프트 담당 |
| roles/market.md | 윤서연 장중 시장상태 (V1.5의 intraday) | 페르소나 프롬프트 담당 |
| roles/risk.md | 신강호 리스크 | 페르소나 프롬프트 담당 |
| roles/portfolio.md | 강유나 포트폴리오 | 페르소나 프롬프트 담당 |
| moderator.md | 요약 담당 | 토론 실행기 |

## 프롬프트를 고칠 때 지킬 것

- 역할 코드는 `macro`, `market`, `risk`, `portfolio`입니다. (`intraday`는 쓰지 않습니다.)
- `## 05`의 persona_data 키는 `contracts/debate/persona_output.<role>.schema.json`과 같아야 합니다. 키를 바꾸려면 `services/debate/src/contracts.py`를 함께 고치고 `python src/export_contracts.py`로 스키마를 다시 만듭니다.
- 출력 형식은 Azure OpenAI structured outputs(strict)로 강제됩니다. 프롬프트의 출력 설명과 스키마가 다르면 스키마가 이깁니다. 그래서 `news_source_ids` 같은 스키마에 없는 키는 쓸 수 없습니다.
- `ui_requests`는 `{type, refs, role, reason}` 고정이고 type은 OPEN_SOURCE_PANEL, SUGGEST_ROLE_TARGET, REQUIRE_CURRENT_DATA 셋뿐입니다.
- 역할별 입력은 `role_payload`가 아니라 D_sources/S_sources로 옵니다. 사용 가능한 `metric_id`와 역할별 범위는 `services/debate/src/evidence.py`에 있습니다.
- 화면 문장의 단위 붙은 숫자(%, %p, bp, pt, 원)는 D_sources 값과 대조됩니다. 프롬프트에 고정 수치를 넣고 "답변에 쓰라"고 하면 발언이 거절됩니다.
- 메모장 BOM은 괜찮습니다(읽을 때 제거). 저장은 UTF-8로 합니다.
- `tests/test_prompts.py`가 역할 코드, persona_data 키, 없어진 용어(N_sources 등)를 확인합니다.

수정본을 만든 스크립트와 V1.5 대비 변경 내역은 `CHANGES_V1.5.md`에 있습니다.
