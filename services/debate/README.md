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

프롬프트는 `prompts/roles/<role>.md` 독립형 파일입니다(페르소나 프롬프트 V1.5 수정본). [prompts/README.md](prompts/README.md)

| 역할 코드 | 인물 | 근거 |
| --- | --- | --- |
| macro | 김진우 거시경제 | 시나리오 충격, 무충격 대비 차이, 충격별 모델 기여, 시장 공통 입력 상태 |
| market | 윤서연 장중 시장상태 | 시장 상태 스냅샷(하락 비율, 업종, 상관, 동반 하락, 신호) |
| risk | 신강호 리스크 | 분위수, 보수적 하방 참고선, 학습 범위 밖 충격, 과거 관측 사례 |
| portfolio | 강유나 포트폴리오 | 전체 보유 금액·예상 손익(없으면 종목 합), 종목별 보유 비중·손익 몫(서버 계산), 충격 기여, 장중 상관·동반 하락. VaR/ES는 받지 않음 |

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
| `GET /me` | 로그인 사용자 `{user_id, provider, name}` |
| `GET /me/holdings` | 내 보유 종목 `{holdings[{asset_id, amount_krw, updated_at}], count, total_krw}` |
| `PUT /me/holdings` | 내 보유 종목 전체 저장 `{holdings[{asset_id, amount_krw}]}`. 목록을 통째로 바꿉니다 |
| `GET /healthz` | 상태 확인 |

- 모든 경로는 `/api` 접두사로도 열립니다(`/api/debates` 등). 웹앱은 `/api/...`로 부릅니다.
- 사용자: Static Web Apps 로그인 뒤 SWA가 넘기는 `X-MS-CLIENT-PRINCIPAL`에서 `{공급자}:{userId}`를 씁니다(예: `aad:1a2b…`). `ALLOW_DEV_USER_HEADER=true`일 때만 `X-User-Id` 헤더도 받습니다(SWA 연결 전 테스트용, 운영에서는 끔). 로그인 정보가 없으면 401, 다른 사용자의 토론은 404입니다.
- 보유 종목 검사: 종목코드 6자리(숫자·대문자), 금액 > 0, 중복 없음, 최대 `HOLDINGS_MAX`(기본 200)개. `ALLOWED_ASSETS`(쉼표 구분)를 주면 그 종목만 저장할 수 있습니다(예: ML 지원 종목).
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

- 대상: ① 보유 종목을 저장한 사용자(`user_holding`), ② 최근 `SCHEDULE_ACTIVE_DAYS`(기본 7)일 안에 직접 토론을 연 사용자 순서입니다. Stress Engine이 연결되기 전까지 ①은 `DEFAULT_RUN_ID`, ②는 그 사용자의 마지막 `run_id`로 토론합니다. 응답의 `holding_users`가 ①의 수입니다.
- 비용 상한: 시간대마다 최대 `SCHEDULE_MAX_USERS`(기본 50)명. 넘으면 응답의 `capped`가 true입니다.
- 같은 날·시간대·사용자는 같은 `debate_id`(`s-날짜-시간대-…`)라 작업이 재시도돼도 사용자마다 하나입니다.
- `SCHEDULER_KEY`는 API와 작업 모두 Container Apps 비밀로 둡니다.
- 휴장일 판단은 아직 없습니다. DART 공시와 웹 뉴스는 아래처럼 근거에 들어갑니다.

## 로그인과 보유 종목 (Static Web Apps Standard + API 연결)

웹앱(swa-whatif-dev)의 `/api/*`를 이 토론 API로 연결하고, SWA 기본 로그인(Microsoft 계정)을 씁니다. 연결된 컨테이너 앱은 SWA를 거친 요청만 받으므로 사용자가 로그인 정보를 꾸밀 수 없습니다. 웹 화면은 [apps/web/quote-monitor/holdings.html](../../apps/web/quote-monitor/holdings.html)입니다.

1. DB: `sql/debate_tables.sql`의 `user_holding` 테이블과 권한(`GRANT SELECT, INSERT, UPDATE, DELETE ON user_holding`)을 Entra 관리자로 한 번 실행합니다.
2. 이미지 배포: 실행기와 토론 요청 API 모두 새 이미지로 바꿉니다. 연결 전 테스트 동안만 API에 `ALLOW_DEV_USER_HEADER=true`.
3. SWA 요금제를 Standard로 올리고, **API → 프로덕션 → 연결 → Container App → ca-debateapi-whatif-dev**로 연결합니다.
4. 연결하면 컨테이너 앱에 인증(Azure Static Web Apps (Linked))이 생겨 직접 호출이 막힙니다. 예약 작업은 API를 직접 부르므로 `/scheduled-debates`, `/healthz`를 인증 예외 경로로 둡니다(스케줄러 키로 보호).
5. 웹 배포 후 `/holdings.html`에서 로그인·저장을 확인하고, API의 `ALLOW_DEV_USER_HEADER`를 끕니다.

## 공시 근거 (DART)

근거 묶음을 처음 만들 때 실행기가 OpenDART에서 묶음 종목(보유 금액 큰 순 최대 20개)의 최근 공시를 조회해 S 근거로 넣습니다(`src/disclosures.py`).

- 내용: 공시 제목, 접수일, 제출인, DART 원문 링크. 본문은 넣지 않습니다. 시장·리스크·포트폴리오 역할에게만 보입니다.
- 기간·개수: 토론 시각(KST) 기준 최근 `DART_LOOKBACK_DAYS`(기본 7)일, 종목당 `DART_MAX_PER_ASSET`(기본 5)건.
- 근거 고정: 묶음은 한 번 만들면 바뀌지 않으므로 재배달·사용자 질문에서는 DART를 다시 부르지 않습니다.
- 중복 호출 방지: 같은 종목은 `DART_CACHE_MINUTES`(기본 30)분 동안 실행기 프로세스 안에서 재사용합니다. 정시 회의에서 여러 사용자가 같은 종목을 가져도 종목당 한 번입니다.
- 실패해도 토론은 진행합니다. 묶음의 `disclosure_status`(ok, partial, failed, disabled)와 `debate.evidence_ready` 이벤트의 `disclosure_status`, `disclosure_count`로 확인합니다.
- 주요사항보고서(유상증자, 전환사채, 자기주식, 합병·분할, 감자, 소송 등)는 같은 키로 종류별 상세 API를 한 번 더 불러 금액·주식 수를 D 근거(`dart_detail`, 단위 `mixed`)로 붙입니다. 목록에 그 종류가 있을 때만 부릅니다. 실제 응답을 확인한 종류(자기주식 취득·처분)는 한국어 항목명과 단위로 바꿔 넣고(`DETAIL_LABELS`), 나머지 종류는 DART 원본 항목명 그대로 둡니다. 새 종류가 실제로 나오면 응답을 보고 `DETAIL_LABELS`에 추가합니다. 상세 API 이름 일부는 미확인이라 틀리면 해당 공시만 `detail_error`로 남습니다(`DETAIL_ENDPOINTS`).
- 인증키: `DART_API_KEY`를 Container Apps 비밀로 넣습니다. 없으면 공시 없이 진행합니다(`disabled`). 키는 URL 쿼리로 가므로 오류 문구와 httpx 로그에서 가립니다. 팀이 같은 키를 쓰면 하루 한도(약 20,000건)도 함께 씁니다.

```bash
az containerapp secret set -n ca-debate-whatif-dev -g $rg --secrets dart-api-key=<키>
az containerapp update -n ca-debate-whatif-dev -g $rg --set-env-vars DART_API_KEY=secretref:dart-api-key
```

## 뉴스 근거 (웹 검색)

Azure OpenAI Responses API의 `web_search` 도구로 묶음 종목 중 보유 금액 큰 순 `NEWS_MAX_ASSETS`(기본 3)개의 최근 `NEWS_LOOKBACK_DAYS`(기본 7)일 뉴스를 찾아 S 근거(`kind: web_news`)로 넣습니다(`src/news.py`). 토론과 같은 Azure OpenAI 리소스·관리 ID를 쓰고, 별도 Bing 리소스나 Foundry 에이전트는 만들지 않습니다.

- 내용: 종목마다 `- YYYY-MM-DD: 요약` 최대 3줄, 인용 링크(제목·URL), 실행된 검색어. 기사 본문은 저장하지 않습니다.
- 기간 거르기: `web_search`에는 기간 옵션이 없어, 줄 앞 날짜가 기간 밖이거나 없는 줄을 지우고 그 줄의 인용도 뺍니다. 남은 줄이나 인용이 없으면 그 종목은 뉴스 없음입니다.
- 검색 횟수: 추론형 모델은 여러 번 다시 검색합니다(첫 배포에서 5종목에 Bing 41건). `max_tool_calls`(`NEWS_MAX_SEARCHES`, 기본 2)와 `reasoning.effort`(`NEWS_REASONING_EFFORT`, 기본 low)로 줄이고, 모델이 이 옵션을 거부하면 빼고 다시 부릅니다(로그 `... 옵션 거부`).
- 캐시: 같은 종목은 같은 날(KST) 한 번만 검색합니다(`NEWS_CACHE_MINUTES`, 기본 1440). 08:30 정시 회의 결과를 13:00·15:40 회의와 사용자 토론이 같이 씁니다. 실행기를 재시작하면 캐시와 하루 사용량이 초기화됩니다.
- 하루 상한: `NEWS_DAILY_REQUEST_LIMIT`(기본 300건)을 넘으면 그날 남은 토론은 뉴스 없이 진행합니다(`news_status: budget_exceeded`, 일부만 건너뛰면 `partial`).
- 역할: 시장·리스크·포트폴리오. 프롬프트는 AI 요약이라 틀릴 수 있고 "보도됐다"로 말하며, D 근거·공시와 다르면 그쪽을 따르게 합니다.
- **화면 표시 의무**: 웹 검색은 내부적으로 Grounding with Bing을 쓰고, 이용 조건상 출처 URL과 Bing 검색어 URL을 사용자에게 보여줘야 합니다. `debate.evidence_ready`의 `web_news[]`(`citations`, `search_query_urls`)를 회의록 화면에 표시하세요.
- 비용: Bing 요청 1,000건당 약 $14(모델 토큰 별도). 실행기 로그 `웹 뉴스: N종목, 뉴스 있음 K, Bing 요청 M건 (오늘 누적 T건)`으로 확인합니다.
- 데이터 경계: 검색어(종목명)가 Azure 규정 준수 경계 밖 Bing으로 갑니다. 사용자 정보는 검색어에 넣지 않습니다.
- 실패해도 토론은 진행합니다. 묶음 `news_status`와 이벤트 `news_status`로 확인합니다.
- 켜기: 기본은 꺼짐입니다. `NEWS_ENABLED=true`. 검색용 배포를 따로 쓰려면 `NEWS_DEPLOYMENT`. 토큰 범위는 `NEWS_TOKEN_SCOPE`(기본 `https://ai.azure.com/.default`, 401이면 `https://cognitiveservices.azure.com/.default`).

```bash
az containerapp update -n ca-debate-whatif-dev -g $rg --set-env-vars NEWS_ENABLED=true
```

## 현재 배포 (dev)

| 항목 | 값 |
| --- | --- |
| Container App | `ca-debate-whatif-dev` (cae-whatif-dev, ingress 없음, 복제본 1) |
| 이미지 | `acrwhatifdev5dt.azurecr.io/debate:0.4.3` (실행기·토론 요청 API 같은 이미지, 2026-11-10) |
| 관리 ID | `id-debate-whatif-dev` |
| 토론 요청 API | `ca-debateapi-whatif-dev` (외부 ingress 8000). swa-whatif-dev(Standard)의 API 백엔드로 연결돼 직접 호출은 막힘. 인증 예외 `/scheduled-debates`, `/healthz`. `ALLOW_DEV_USER_HEADER=false` |
| 정시 회의 | `job-debate-0830`, `job-debate-1300`, `job-debate-1540` |
| 모델 | `aoai-whatif-dev` 배포 `gpt-5.4-mini`, api-version 2024-10-21. 웹 뉴스는 같은 리소스의 Responses API `web_search` |
| 비밀 | `dart-api-key`(실행기), `scheduler-key`(API·작업) |

이력: 2026-11-05 `debate:0.1` 토론 완료 확인. 2026-11-10 `debate:0.4.3`으로 프롬프트 V1.5 수정본·포트폴리오 근거·DART·웹 뉴스를 넣은 4인 토론이 재시도 없이 통과. 2026-11-11 SWA 로그인(aad)으로 보유 종목 저장 확인.

## 로컬에서 확인하기

- `python services/debate/src/run_local.py`: Service Bus·DB 없이 실제 모델로 토론 1건 (`az login` 계정, OpenAI User 역할 필요)
- `python services/debate/src/dev_tools.py apply-sql | send | events`: 테이블 생성, 큐에 메시지 보내기, 저장된 이벤트 보기
- Windows에서 `worker.py`를 직접 실행할 수 있습니다(Selector 이벤트 루프 자동 사용).

## 아직 연결되지 않은 것

- Stress Engine `GET /runs/{run_id}`: stress-engine 구현 전에는 `STRESS_RUN_DIR`의 `{run_id}.json`을 읽습니다. 형식은 [tests/fixtures/stress_run.json](tests/fixtures/stress_run.json)과 같습니다.
- 포트폴리오 블록: ML에서 `portfolio.holding_value_krw`, `portfolio.center_pnl_krw` 두 값만 받습니다. 없으면 종목 값을 더해 만듭니다. VaR95/ES95·ES 기여도·분산 효과는 받지 않기로 했고 프롬프트도 '제공되지 않음' 기준입니다. 나중에 받게 되면 `evidence._add_portfolio`와 프롬프트 15절을 함께 고칩니다.
- AI Search 문서 근거(S): 지금은 스트레스 결과 해석 기준과 시장 상태 한계 문장만 S로 넣습니다.
- 보유 종목 → Stress Engine: `user_holding`을 `positions[{asset_id, value_krw}]`로 넘겨 받은 run_id로 정시 회의를 여는 부분(`api._schedule_targets`의 TODO). 그전까지 뉴스·공시·토론 종목은 run 파일 기준입니다.
