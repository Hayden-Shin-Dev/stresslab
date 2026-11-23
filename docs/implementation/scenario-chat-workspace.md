# 시나리오 통합 채팅 구현 기록

2026-11-23. 사용자 운영 배포 승인 후 적용 진행 중. 사용자 정정에 따라 시나리오 페이지의 그래프·분석 설정·하단 시장 데이터는 기존 구조와 위치로 유지하고, 오른쪽 자료/채팅 영역만 변경했다. 기존 main 작업 파일에서 구현했으며, 기존 미커밋 APIM/news_feed 변경은 수정하지 않았다.

## 변경 파일

- `apps/web/quote-monitor/site/whatif-v6/assets/scenario-workspace.js`: 기존 화면 렌더러의 오른쪽 `.fig-data-chat-group`만 교체. 그래프, 분석 설정, 하단 시장 표, 홈 버튼, 확대 그래프는 원래 DOM을 그대로 유지. 실시간 시세·뉴스·공시는 도구 버튼 바로 아래의 접이식 목록, 선택 근거는 채팅 상단 칩으로 표시.
- `assets/scenario-workspace.css` (동일 디렉터리): 기존 시나리오 프레임과 오른쪽 617px 열을 유지하고, 기존 크림·세이지 색과 캐릭터 유지. 기존 Pretendard 파일 사용. 입력창 고정, 44px 조작 영역, 감소 모션 지원.
- `assets/scenario-window.js`: 공시 팝업의 토론 근거 선택 액션.
- `index.html`: 공통 질문, 역할 선택, 근거 선택, 새 토론, 이벤트 순서·중복 제거·복구, 출처 표시, 스크롤 및 초안 보존.
- `apps/web/quote-monitor/deploy-manifest.json`: 신규 JS/CSS 포함.
- `services/debate/src/contracts.py`, `contracts/debate/request.schema.json`: 초기 토론의 `target_roles`, `selected_sources` 계약. 미지정 시 기존 4인 기본 동작.
- `services/debate/src/api.py`: 검증한 선택 계약을 기존 Service Bus 요청에 전달.
- `services/debate/src/orchestrator.py`: 선택 역할만 초기/후속 라운드 실행, 선택 자료 서버 조회, 근거 공개 이벤트에 실제 자료 연결.
- `services/debate/src/selected_evidence.py`: 서버 뉴스 목록 재확인, OpenDART 원문 발췌 조회, 시장 스냅샷 일치 검사.
- `services/debate/src/evidence.py`: 선택 자료를 기존 D/S 근거와 함께 해시/고정. 계산식과 출력값은 변경하지 않음.
- `services/debate/tests/test_workspace.py`: 역할 제한, 계약 검증, 출처 확인, 시점 불일치/실패, 근거 불변성 테스트.
- `apps/web/quote-monitor/tests/workspace_browser.py`: 테스트 응답을 이용한 실제 Chromium 브라우저 흐름 검증.

## 화면 구조

왼쪽: 기존 스트레스테스트 구분·모델·기간·변수·그래프, 하단 시장 데이터와 포트폴리오 목록을 유지. 오른쪽만: 자료와 대화 타이틀 → 분석 조건 요약 → 참여 에이전트 얼굴 4열·1행 → 자료 도구·새 토론 → 펼침 목록 → 선택 근거 → 단일 대화 목록 → 질문 대상·입력창.

자료 버튼에 호버 피드백을 제공하고 클릭하면 바로 아래 목록을 펼친다. 같은 버튼 재클릭·목록 닫기·Escape로 접으며 채팅 입력창은 계속 표시한다. 에이전트 이름·역할은 얼굴의 툴팁과 접근성 이름으로 제공한다. 실시간 시세는 기존 `/api/quotes/latest`의 종목·현재가·누적 거래량·체결/수집/수신 시각을 카드 목록으로 표시한다. 뉴스 검색·주제·기업별 3개월·언론사 필터, 공시 회사 검색·기간·상세·원문·재무정보, 시장 표·자산 추가 기능을 재사용한다. 자료 탐색을 닫으면 대화 스크롤과 질문 초안을 보존한다.

## 실제 API 연결

| 동작 | 연결 | 의미 |
| --- | --- | --- |
| 스트레스테스트 | `POST /api/stress/analyze` | 기존 positions/model/shocks, analysis_id와 ai_handoff 확인 |
| 새 토론 | `POST /api/debates` | run_id, target_roles, selected_sources, Idempotency-Key |
| 질문 | `POST /api/debates/{id}/questions` | 전송 시 고정한 target_roles, 사용자 질문 |
| 이벤트 | Web PubSub 알림 + `events?after_seq=` | 서버 저장 이벤트를 seq 순으로 적용, event_id 중복 제거 |
| 재접속 | `GET /api/debates/{id}/negotiate` | 토큰 재발급, HTTP 이벤트 복구 병행 |
| 뉴스 선택 | 기존 latest/company 조회 + 실행기에서 재조회 | 제목·언론사·발행 시각·URL만. 기사 본문 분석 아님 |
| 공시 선택 | 기존 preview + 실행기의 OpenDART 조회 | 서버 조회 본문 최대 8,000자 발췌. 전체 문서 분석 아님 |
| 시장 선택 | 기존 market-state + 고정 분석 스냅샷 | 선택 ID와 분석 시점 ID가 같아야 포함. 불일치 시 재분석 안내 |

새 자료를 기존 토론에 소급 적용하지 않는다. 새 토론 ID를 생성하고 이전 발언·출처는 보존한다. `debate.evidence_ready`가 확인한 자료만 반영됨으로 표시한다. 실패한 자료는 사유를 표시하고 해당 본문을 근거에 넣지 않는다. 발언 출처는 실제 서버의 D/S ID로 연결하되, 화면에는 자료명·값·단위·링크를 보여준다. Web PubSub 토큰은 영구 저장하지 않는다.

## 검증 결과

- Debate 테스트: 104 통과, PostgreSQL 실제 연결 테스트 1개 건너뜀(접속 설정 없음).
- 공통 API 테스트: 22 통과.
- 기존 스트레스 그래프 테스트: 10 통과. 단위·합계·구간·미래 경로 생성 금지 검증 유지.
- Chromium 로컬 테스트: 역할 일부 선택 및 최소 1명 유지, 뉴스·공시 선택, 초기 토론 요청, 발언 출처, 개별 질문 대상, 새로고침 후 대화 복구 확인.
- 데스크톱 1440×1000, 태블릿 768×1024, 모바일 390×844. 오른쪽 채팅 및 펼침 목록 가로 넘침 검사. 얼굴 4개 동일 행, 목록이 도구 아래에 배치됨, 동일 버튼으로 닫힘, 시세 API 필드 표시 확인. 전체 페이지는 기존 프레임 축소 방식 유지. 작은 모바일 화면의 글자 가독성은 별도 개선 대상이며, 페이지 전체 재구성은 이번 범위에서 제외. 테스트 응답 기반이며 실제 Azure AI 응답 검증이 아님.
- JS 문법 검사 및 배포 build-only 성공.
- 로컬 캡처: `/tmp/workspace-quotes-desktop.png`, `/tmp/workspace-desktop.png`, `/tmp/workspace-mobile.png`, `/tmp/workspace-news-390.png`. 표시 데이터는 테스트용.

## 지원 범위와 남은 운영 확인

구현된 서버 계약은 로컬 검증 완료. 실제 Azure의 API/실행기/Web PubSub/DB 및 외부 DART·뉴스 제공처를 통한 통합 검증은 미수행이다. Worker의 DART_API_KEY가 없으면 공시는 반영 불가로 표시한다. RSS 본문 수집은 지원하지 않는다. 선택 시장 자료는 분석 결과에 고정된 시점과 일치해야 하며 ML 결과를 실시간으로 재계산하지 않는다. iOS 실제 기기 키보드·스크린리더 및 Web PubSub 실서비스 단절 복구는 운영 승인 후 확인해야 한다. WCAG AA 전체 적합성 인증을 의미하지 않는다.

사용자가 운영 배포를 명시적으로 승인했다. **API와 실행기를 먼저 갱신하고 웹을 적용해야 한다.** 구형 실행기는 선택 계약을 지원하지 않는다. DB 스키마 추가는 없다. 토론 서버 준비 상태 확인 후 main 푸시로 웹을 배포한다.

되돌릴 경우 이번 기록의 신규 파일과 명시된 수정분만 되돌린다. 기존 APIM/news_feed 등 다른 작업 변경은 보존한다.

## 배포 버전

- 신규 토론 이미지: `acrwhatifdev5dt.azurecr.io/debate:0.8.6-workspace-20261123`.
- 이전 실행기: `debate:0.8.1`, revision `ca-debate-whatif-dev--0000009`.
- 이전 요청 API: `debate:0.8.5`, revision `ca-debateapi-whatif-dev--0000014`.
- 이미지 빌드에는 검증된 RSS httpx 어댑터와 gnews 의존성 제거도 포함한다. APIM 변경 파일은 이번 배포에 포함하지 않는다.
