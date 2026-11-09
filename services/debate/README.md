# AI 토론 실행기

Service Bus `debate-requests` 큐의 토론 요청을 받아, Stress Engine 결과와 시장 상태 스냅샷으로 근거 묶음을 고정하고 네 페르소나의 토론을 진행합니다. 발언은 검증을 통과한 것만 PostgreSQL에 저장한 뒤 Web PubSub `debate` 허브로 보냅니다. 모델은 Azure OpenAI를 관리 ID로 호출합니다.

| 폴더 | 내용 |
| --- | --- |
| [src](src/) | 큐 수신, 근거 묶음, 토론 진행, 출력 검증, 저장과 발행 |
| [prompts](prompts/) | 페르소나 공통·역할 프롬프트와 요약 프롬프트 |
| [sql](sql/) | 토론 테이블 |
| [tests](tests/) | Azure 없이 도는 전체 흐름 테스트 |

같은 이미지로 **토론 요청 API**(`src/api.py`)도 띄웁니다. 웹앱이 이 API로 토론을 시작하고 질문하며, 화면은 받은 토큰으로 Web PubSub에 접속합니다.

계약(큐 메시지, 페르소나 출력 스키마, 이벤트)은 [contracts/debate](../../contracts/debate/)에 있습니다.

## 페르소나

| 역할 코드 | 인물 | 근거 |
| --- | --- | --- |
| macro | 김진우 거시경제 | 시나리오 충격, 무충격 대비 차이, 충격별 모델 기여, 시장 공통 입력 상태 |
| market | 윤서연 장중 시장상태 | 시장 상태 스냅샷(하락 비율, 업종, 상관, 동반 하락, 신호) |
| risk | 신강호 리스크 | 분위수, 보수적 하방 참고선, 학습 범위 밖 충격, 과거 관측 사례 |
| portfolio | 강유나 포트폴리오 | 보유 금액, 종목별 손익, 포트폴리오 VaR/ES·ES 기여도(ML 추가 예정) |

## 토론 순서

1. **근거 고정**: `run_id`의 Stress Engine 결과와 `snapshot_id`(없으면 접수 시점 최신) 스냅샷으로 근거 묶음을 만들고 ID(D1, S1 …)를 붙여 저장합니다. 같은 토론의 모든 발언이 이 묶음만 봅니다. 숫자는 계산하지 않고 원본을 옮깁니다.
2. **초기 발언**: 네 역할을 병렬로 생성하고, 검증을 통과하면 역할 순서(macro, market, risk, portfolio)대로 저장·공개합니다.
3. **쟁점 반론**: 초기 발언의 `questions_to_roles`에서 최대 2개를 골라, 질문받은 역할이 한 번 답합니다.
4. **요약**: 사회자 프롬프트가 합의와 이견을 발언 ID와 함께 정리합니다.
5. **사용자 질문**: 같은 세션으로 들어온 `user_question`은 선택한 역할들이 같은 근거 묶음으로 답합니다.

## 검증 (통과한 발언만 공개)

- 스키마(structured outputs strict + 서버 재검증), role·context_version 일치, 단계에 맞는 intent
- 이 역할에게 준 근거에 없는 ID 인용 금지
- 화면·음성 문장에 내부 ID(D1, S2) 노출 금지
- 화면 문장의 숫자(%, %p, bp, pt, 원)는 이 역할에게 준 근거 값을 반올림한 것이어야 합니다. 크기만 비교하고(부호는 "하락/상승"으로 바꿔 말할 수 있음), 0~1 비율은 %로, % 값은 bp로 바꿔 말해도 통과합니다. 근거 값끼리 더하거나 나눈 새 숫자는 막힙니다. "하위 10%", "VaR 95%" 같은 지표 이름 속 숫자는 검사하지 않습니다.
- 근거 항목마다 `label`(한국어 지표 이름)이 있습니다. 본문에서는 ID 대신 이 이름으로 말합니다.
- 실패하면 같은 입력에 오류 목록을 붙여 한 번만 다시 요청하고, 그래도 실패하면 그 역할은 `message.failed`로 남깁니다.

## 장애와 재처리

- 세션 = `debate_id`라 같은 토론은 한 실행기가 순서대로 처리합니다. 처리 중 잠금은 자동 연장합니다(최대 15분).
- 모델·조회 장애는 메시지를 abandon합니다. 재배달되면 이미 저장된 발언은 건너뛰고 이어서 진행합니다(`message_id`가 토론·라운드·역할·단계로 정해짐).
- 마지막 배달(`MAX_DELIVERY`)에서는 실패한 역할을 실패로 저장하고 토론을 마칩니다.
- 이벤트는 발언과 같은 트랜잭션에 저장(outbox)한 뒤 보냅니다. 발행이 실패해도 DB에 남아 다음에 다시 보내고, 화면은 `after_seq`로 다시 받을 수 있습니다.

## 배포

```powershell
az acr build -r acrwhatifdev5dt -t debate:<버전> -f services/debate/Dockerfile .
```

이미지 태그는 버전 번호(0.1, 0.2 …)를 씁니다. 같은 태그를 다시 쓰지 않고, 올린 이미지 버전을 커밋 메시지에 적습니다. 실행기와 토론 요청 API는 같은 이미지를 씁니다.

Container Apps(ingress 없음)에 사용자 할당 관리 ID로 배포합니다. 환경변수는 [src/worker.py](src/worker.py) 상단에 있습니다. 관리 ID에 필요한 권한:

| 리소스 | 역할 |
| --- | --- |
| sb-whatif-dev (debate-requests) | Azure Service Bus Data Receiver (실행기), Azure Service Bus Data Sender (토론 요청 API) |
| Azure OpenAI | Cognitive Services OpenAI User |
| wps-whatif-dev | Web PubSub Service Owner |
| psql-whatif-dev | Entra 역할 생성 후 debate 테이블 SELECT/INSERT/UPDATE |

## 토론 요청 API

| 엔드포인트 | 하는 일 |
| --- | --- |
| `POST /debates` | 토론 시작. 큐에 `debate_start`를 넣고 `202 {debate_id, request_id, pubsub: {url, group}}` |
| `GET /debates` | 내 토론 목록(최신순). 회의록 화면 |
| `POST /scheduled-debates` | 정시 회의 `{slot}`. 스케줄러 전용(`X-Scheduler-Key`) |
| `POST /debates/{id}/questions` | 사용자 질문 `{text, target_roles, reference_message_id?}`. 본인 토론만, 실패한 토론은 409 |
| `GET /debates/{id}` | 토론 상태 |
| `GET /debates/{id}/negotiate` | Web PubSub 재접속 URL (`debate-{id}` 그룹 자동 참가, 받기 전용) |
| `GET /debates/{id}/events?after_seq=N` | 놓친 이벤트. Web PubSub 메시지와 같은 모양 |
| `GET /healthz` | 상태 확인 |

- 사용자: `X-User-Id` 헤더(웹앱 로그인 방식이 정해지면 교체). 다른 사용자의 토론은 404입니다.
- 중복: `Idempotency-Key` 헤더가 같으면 같은 `debate_id`·`request_id`가 되어 Service Bus 중복 감지가 막습니다.
- 토론 행은 실행기가 메시지를 받을 때 만듭니다. 시작 직후 1~2초 동안 질문·상태 조회는 409(접수 처리 중)일 수 있습니다. 화면은 `POST /debates` 응답의 URL로 바로 접속하면 됩니다.
- 화면 흐름: `POST /debates` → `pubsub.url`로 WebSocket 접속 → 이벤트를 `seq` 순으로 표시(`event_id`로 중복 제거) → 끊기면 `negotiate`로 다시 접속하고 `events?after_seq=마지막 seq`로 빈 곳을 채움.

배포: 같은 이미지, ingress 외부 8000, 명령 `uvicorn`, 인수 `api:app --host 0.0.0.0 --port 8000`. 실행기와 같은 관리 ID(`id-debate-whatif-dev`)를 쓰고 Service Bus에 **Azure Service Bus Data Sender** 역할만 더 줍니다. 환경변수는 `src/api.py` 상단에 있습니다.

## 정시 회의

정시 회의는 **사용자별**입니다. 시간대마다 사용자 각자의 보유 종목 결과로 토론을 하나씩 열고, 본인만 조회합니다.

Container Apps 예약 작업 3개가 같은 이미지로 `python schedule.py <시간대>`를 실행하고, 이 스크립트가 토론 요청 API의 `POST /scheduled-debates`를 한 번 부릅니다. 예약 시각은 UTC입니다.

| 작업 | KST | cron (UTC) | 인수 |
| --- | --- | --- | --- |
| `job-debate-0830` | 평일 08:30 | `30 23 * * 0-4` (전날 23:30) | `schedule.py 0830` |
| `job-debate-1300` | 평일 13:00 | `0 4 * * 1-5` | `schedule.py 1300` |
| `job-debate-1540` | 평일 15:40 | `40 6 * * 1-5` | `schedule.py 1540` |

- 대상: 최근 `SCHEDULE_ACTIVE_DAYS`(기본 7)일 안에 직접 토론을 연 사용자. 각 사용자의 마지막 `run_id`로 토론합니다. 포트폴리오 저장소가 생기면 대상과 `run_id`를 그쪽에서 가져오도록 바꿉니다.
- 비용 상한: 시간대마다 최대 `SCHEDULE_MAX_USERS`(기본 50)명. 넘으면 응답의 `capped`가 true입니다.
- 같은 날·시간대·사용자는 같은 `debate_id`(`s-날짜-시간대-…`)라 작업이 재시도돼도 사용자마다 하나입니다.
- `SCHEDULER_KEY`는 API와 작업 모두 Container Apps 비밀로 둡니다.
- 휴장일 판단과 뉴스 근거는 아직 없습니다.

## 현재 배포 (dev)

| 항목 | 값 |
| --- | --- |
| Container App | `ca-debate-whatif-dev` (cae-whatif-dev, ingress 없음, 복제본 1) |
| 이미지 | `acrwhatifdev5dt.azurecr.io/debate:0.1` |
| 관리 ID | `id-debate-whatif-dev` |
| 토론 요청 API | `ca-debateapi-whatif-dev` (같은 이미지, 외부 ingress 8000) |
| 모델 | `aoai-whatif-dev` 배포 `gpt-5.4-mini`, api-version 2024-10-21 |

2026-11-05 컨테이너로 토론 완료(test-002, test-003). test-002는 429(분당 토큰 한도)가 나와 SDK 재시도로 통과했고, TPM을 올린 뒤 test-003은 429 없이 약 30초에 끝났습니다.

이미지 `debate:0.1`로 실행기 토론 완료(test-005, 초기 4명·반론 2개·요약)와 토론 요청 API(`POST /debates` → 토론 완료, 질문 답변)를 2026-11-05에 확인했습니다.

## 로컬에서 확인하기

- `python services/debate/src/run_local.py`: Service Bus·DB 없이 실제 모델로 토론 1건 (`az login` 계정, OpenAI User 역할 필요)
- `python services/debate/src/dev_tools.py apply-sql | send | events`: 테이블 생성, 큐에 메시지 보내기, 저장된 이벤트 보기
- Windows에서 `worker.py`를 직접 실행할 수 있습니다(Selector 이벤트 루프 자동 사용).

## 아직 연결되지 않은 것

- Stress Engine `GET /runs/{run_id}`: stress-engine 구현 전에는 `STRESS_RUN_DIR`의 `{run_id}.json`을 읽습니다. 형식은 [tests/fixtures/stress_run.json](tests/fixtures/stress_run.json)과 같습니다.
- 포트폴리오 블록(VaR95/ES95, ES 기여도, 분산 효과): ML 출력에 추가되면 근거에 자동으로 들어갑니다. 필드 이름은 [src/evidence.py](src/evidence.py)의 제안 이름입니다.
- AI Search 문서 근거(S): 지금은 스트레스 결과 해석 기준과 시장 상태 한계 문장만 S로 넣습니다.
- 웹앱 로그인: 지금은 `X-User-Id` 헤더를 그대로 믿습니다.
