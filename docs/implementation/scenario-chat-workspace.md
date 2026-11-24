# 시나리오 통합 채팅 구현 기록

2026-11-23. 사용자 승인에 따라 서버와 웹을 Azure에 직접 배포 완료. GitHub 푸시 없음. 사용자 정정에 따라 시나리오 페이지의 그래프·분석 설정·하단 시장 데이터는 기존 구조와 위치로 유지하고, 오른쪽 자료/채팅 영역만 변경했다. 기존 main 작업 파일에서 구현했으며, 기존 미커밋 APIM 변경은 유지했다. 검증된 news_feed 어댑터 변경은 배포 이미지와 로컬 커밋에 포함했다.

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

구현된 서버 계약은 로컬 검증 완료. Azure 서버 3곳의 새 revision 준비와 공통 API 트래픽 100%를 확인했다. 운영 로그인 세션에서 시세·뉴스 조회와 새 UI를 확인했다. 새 토론의 생성부터 완료까지, 공시 원문 선택의 새 실행기 반영까지의 운영 통합 검증은 아직 미수행이다. Worker의 DART_API_KEY가 없으면 공시는 반영 불가로 표시한다. RSS 본문 수집은 지원하지 않는다. 선택 시장 자료는 분석 결과에 고정된 시점과 일치해야 하며 ML 결과를 실시간으로 재계산하지 않는다. iOS 실제 기기 키보드·스크린리더 및 Web PubSub 실서비스 단절 복구는 운영 승인 후 확인해야 한다. WCAG AA 전체 적합성 인증을 의미하지 않는다.

사용자가 운영 배포를 명시적으로 승인했다. **API와 실행기를 먼저 갱신하고 웹을 적용해야 한다.** 구형 실행기는 선택 계약을 지원하지 않는다. DB 스키마 추가는 없다. 사용자가 소스 비공개 Azure 직접 배포를 선택했다. main 푸시를 하지 않고 Cloud Shell에서 기존 배포 스크립트를 실행한다.

되돌릴 경우 이번 기록의 신규 파일과 명시된 수정분만 되돌린다. 기존 APIM/news_feed 등 다른 작업 변경은 보존한다.

## 배포 버전

- 신규 토론 이미지: `acrwhatifdev5dt.azurecr.io/debate:0.8.6-workspace-20261123`.
- 이전 실행기: `debate:0.8.1`, revision `ca-debate-whatif-dev--0000009`.
- 이전 요청 API: `debate:0.8.5`, revision `ca-debateapi-whatif-dev--0000014`.
- 이미지 빌드에는 검증된 RSS httpx 어댑터와 gnews 의존성 제거도 포함한다. APIM 변경 파일은 이번 배포에 포함하지 않는다.

- 공통 API 신규 이미지: `common-api:workspace-20261123-v1`. 이전 버전 `common-api:company-news-f3326d3`, revision `ca-api-whatif-dev--0000015`. 공통 API가 토론 요청 라우트를 직접 재사용하므로 함께 적용한다.

- ACR 빌드 성공: 토론 `de1u`, 공통 API `de1v`.
- 실행기 신규 revision `ca-debate-whatif-dev--0000010`, 요청 API `ca-debateapi-whatif-dev--0000015` 준비 확인.
- 공통 API 신규 revision `ca-api-whatif-dev--0000016`: Healthy / Running 확인.

- 공통 API 최신 Ready revision `ca-api-whatif-dev--0000016`, 최신 revision 트래픽 100% 확인.
- 웹 공개 자산 기준 커밋: `59425cd2a6ec7bf0ecea844dc88084645f377562`. 새 웹 파일 4개와 배포 스크립트/manifest를 Azure Cloud Shell에만 업로드해 기존 빌드 스크립트로 배포. GitHub 푸시 없음.

## 직접 배포 완료 및 운영 확인

- Azure CLI/SWA CLI가 `https://red-field-0b8ece310.1.azurestaticapps.net` production 배포 성공을 반환.
- 로그인된 Chrome에서 새로고침 후 기존 시나리오 그래프와 분석 결과 유지 확인.
- 얼굴 4열·1행, 자료 버튼 아래 목록 펼침/동일 버튼 닫힘, 채팅 입력창 유지 확인.
- 실제 종목 시세와 누적 거래량·체결/수집 시각 수신 확인. 체결이 오래된 값은 기준 시각과 갱신 지연 표시 유지.
- 실제 Google News RSS 기사·출처·발행 시각 목록 수신 확인.
- 토론 전체 운영 E2E 및 문서 근거 반영은 미검증. 로컬 계약/브라우저 테스트 결과와 구분한다.
- 배포 도중 SWA CLI가 상위 폴더의 구형 BOM 설정 파일 탐색 경고를 냈지만, 빌드 산출물의 실제 `site/staticwebapp.config.json`은 BOM 없는 유효 JSON이며 직접 배포 성공.
- GitHub main은 기존 `59425cd2a` 유지. 새 구현은 로컬 커밋 `1f69f8915`와 Azure 배포본에만 존재한다. 향후 기존 main 자동 배포가 실행되면 이번 웹 변경을 덮어쓸 수 있으므로 비공개 배포 소스 관리 경로를 유지해야 한다.

## 공통 자료·대화 패널 직접 배포 — 2026-11-23

- Azure SWA CLI production 배포 성공 확인. GitHub 공개 푸시 없음.
- 배포 파일: index.html, scenario-window.js, scenario-workspace.js/css 및 deploy.py. API·DB 변경 없음.
- Cloud Shell 기존 파일 백업: /tmp/whatif-before-global-workspace.tar.gz (임시 세션 파일).
- 운영 Chrome 강력 새로고침 후 홈의 `자료 · 에이전트` 버튼으로 공통 패널이 열림을 확인. `자료 탐색`과 `에이전트 대화` 분리, 닫기 버튼, 4개 에이전트, 자료 도구와 기존 선택 근거, 입력창을 확인.
- 미실행 상태의 `스트레스테스트 연결 전 · 분석 열기` 표시 확인. 이번 운영 확인에서는 신규 분석/토론이나 보유자산 저장을 실행하지 않음. 연결 완료 상태와 복귀 동작은 로컬 fixture 브라우저 검증 범위.
- 최종 로컬 브라우저 테스트 재통과: 1440/768/390px, 기본 종목20, 저장 예외·재시도, 수치 근거6행, 공통 패널 입력창 영역, 콘솔 오류0.

## 레트로-모던 UX/UI 스킨 — 2026-11-24 (로컬, 미배포)

방향: 2008년 사무실·픽셀아트 컨셉과 Windows 98 창 크롬은 유지하고, 정보 구조·간격·가독성은 현대적으로 맞춘다. 기존 코드는 거의 수정하지 않고 마지막에 로드하는 레이어로 덮어쓴다.

- `whatif-v6/assets/retro-modern.css`: 창 제목 표시줄(남색 그라데이션), Win98 베벨 버튼·눌림 상태, 오목 입력칸, 탭 스트립, 작업 표시줄(시작 칩·상태 트레이·KST 시계), 표 헤더 고정, 모바일 한 줄 작업 표시줄.
- `whatif-v6/assets/retro-fx.js`: 사용자 행동에만 반응하는 기능적 모션. 버튼 픽셀 파편, 충격값 단위(bp/%/pt) 좌우 드래그 조절(실제 `input` 이벤트 발생), 작업 표시줄 → 창 줌 사각형, PLAY 계산 중 블록 진행 표시, 결과 도착 알림, 값이 실제로 바뀐 표 셀만 강조. 모두 `prefers-reduced-motion`에서 생략하거나 정적 표시로 대체한다.
- 폰트: Galmuri11(OFL, `assets/fonts/`)을 실제 로드. 기존 CSS의 `Galmuri` 참조는 파일이 없어 폴백되던 상태였다.
- 로그인(`login.html/css/js`): 기존 스플래시 아트 배경 + Win98 대화상자, 서비스 목적 문구, 콘솔 타이핑 상태(스크린리더에는 전체 문장), 포인터 반응 픽셀 비. 로그인 후 기본 이동 경로를 `/whatif-v6/`로 변경(기존에는 허용 목록에 없어 `/quote-monitor`로 이동).
- 개발자용 노출 문구(“DB 권한 변경 보류”, `text+` placeholder 등)를 사용자 문구로 교체. 동기화·보관소 미지원 상태 자체는 그대로 정확히 안내한다.

| 토큰 | 값 | 용도 |
|---|---|---|
| 픽셀 서체 | Galmuri11 12px / 18–20px, 700 | 창 제목, 버튼, 탭, 라벨, 작업 표시줄 |
| 본문 서체 | Pretendard 14px/22px, 표 13px/20px, 보조 12px/18px | 본문, 수치(tabular-nums), AI 답변 |
| 강조 수치 | PLAY·시계 Galmuri11 22px/30px | 실행 버튼, 분석 시계 |
| 간격 | 창 내부 16px, 기능 영역 사이 16px, 모바일 바깥 12px | 레이아웃 |
| 색 | 면 #ece4cf, 종이 #fffcf3, 글자 #2a2419/#5a4f3c, 제목 #1d3557→#3d6e8e, 금색 #f2c35b→#c8902c(글자 #2e1c04) | 대비 확보 |
| 모션 | 120ms/240ms, `steps()` 이징, 반복 애니메이션 없음 | 픽셀 감성 + 짧은 피드백 |

검증: node 테스트 3종, `handoff_browser`, `content_layout_browser`, `portfolio_layout_browser` 통과(`portfolio_layout`은 변경 전 기준선에서 실패하던 테스트). `workspace_browser`는 변경 전과 같은 111행(PLAY 전 종목 미선택)에서 실패하는 기존 테스트 문제다.

## KRDS 레이아웃·버튼 기준 적용 — 2026-11-24

기준: KRDS 레이아웃(krds.go.kr style_05)과 KRDS-uiux `krds_tokens.css`·`_button.scss`(1rem=10px). 레트로 크롬(제목 표시줄, PLAY, 작업 표시줄 브랜드)은 유지하고 수치만 KRDS에 맞췄다. 모두 `retro-modern.css`의 `--k-*` 토큰으로 관리한다.

| 항목 | 768px 이상 | 767px 이하 |
|---|---|---|
| 화면 마진(창 바깥) | 24px, 작업 표시줄 위 24px | 0(창이 화면을 채움) |
| 창 안 좌우 여백 | 24px | 16px |
| 기능 영역 사이(gap-7) | 24px | 16px |
| 카드 패딩(padding-card) | 24px | 16px |
| 라벨↔입력·버튼 그룹(gap-3) | 8px | 8px |
| 나란한 입력(gap-5) | 16px | 16px |
| 작업 표시줄 | 48px | 56px |

| 버튼 | 높이 / 좌우 패딩 / 글자 / 라운드 | 사용처 |
|---|---|---|
| xsmall | 32 / 10 / 15px / 4 (모바일 40) | 차트 도구, 종목 비교 칩, 표 안 버튼, 제목 표시줄 버튼 |
| small (기본) | 40 / 12 / 15px / 6 | 일반 버튼, 탭, 작업 표시줄, 종목 선택 칩, 추천 질문 |
| large | 56 / 28 / 24px 픽셀 / 8 | PLAY |
| 창 아이콘 | 40×40, 아이콘 20px | 제목 표시줄 창 관리 |

위계: tertiary(종이색 바탕+갈색 테두리, 기본) · secondary(연한 남색+남색 테두리, 선택 상태) · primary(남색 채움, 근거 토론 시작 등 요청 확정) · disabled(회갈색, 그림자·모션 없음). 버튼 글자는 Pretendard로 통일하고 픽셀 서체는 창 제목·PLAY·브랜드에만 남겼다. 홈 버튼은 제목 표시줄 왼쪽에 고정했다(이전에는 제목 표시줄 뒤에 가려져 있었다).

포함하지 않은 것: KRDS 표준형 1200px 최대 폭은 문서형 페이지 기준이라, 좌우 패널을 쓰는 분석 작업공간(유동형)에는 적용하지 않았다.
