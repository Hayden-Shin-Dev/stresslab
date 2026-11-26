# WHAT IF · 시장 국면 분석 ML 패키지 (v1.0 · 2026-11-24 팀 워크스페이스 구축 완료)

## 저장소 안 위치

아래 문서 본문의 경로는 원래 패키지(`WHATIF_MarketRegime_ML`) 기준입니다. 이 저장소에서는 다음 위치에 있습니다.

| 예전 경로 | 저장소 안 새 경로 |
| --- | --- |
| `fabric/reference/market_regime/v1/` | [`fabric/market-regime/reference/market_regime/v1/`](../../fabric/market-regime/reference/market_regime/v1/) |
| `fabric/notebooks/` | [`fabric/market-regime/notebooks/`](../../fabric/market-regime/notebooks/) |
| `fabric/sql/` | [`fabric/market-regime/sql/`](../../fabric/market-regime/sql/) |
| `api/` | [`services/market-regime/`](../../services/market-regime/) |
| `03_API_계약서.md` | [`contracts/market-regime/api-v1.md`](../../contracts/market-regime/api-v1.md) |
| `00`, `01`, `02`, `05`, `07` 문서 | [`docs/market-regime/`](./) |
| `08_구동현황_및_전체작동_가이드.md`, `09_서비스_작동주기_및_원리.md` | [`docs/market-regime/`](./) |
| `docs/diagrams/` | [`docs/market-regime/diagrams/`](diagrams/) |
| `local_test/` | [`tests/market-regime/`](../../tests/market-regime/) |
| `web/regime-dashboard/sample/regime_snapshot.sample.json` (합성 데이터) | [`services/market-regime/tests/fixtures/regime_snapshot.sample.json`](../../services/market-regime/tests/fixtures/regime_snapshot.sample.json) |
| `04_다음_할일_로드맵.md`, `06_개인워크스페이스_구축_및_이관.md` | 별도 보관, 저장소에 없음 |
| `10`, `11`, `12A`, `12B` 문서 | 별도 보관, 저장소에 없음 |
| `web/` (`web/regime-dashboard/` 포함) | 별도 보관, 저장소에 없음 |

현재 시장이 **상승장 · 횡보장 · 폭락장** 중 어디에 있는지 진단하고, 국면 이력과 현재와 비슷했던 과거 시기를 보여 주는 [시장국면분석ML] 산출물입니다. [스트레스엔진ML]과는 별개 기능이지만, 같은 Gold(`gold_stress_daily` v1.1)를 입력으로 씁니다.

> **구축 현황 (2026-11-24 기준)**
> 팀 워크스페이스 `ws-whatif-dev`의 `MarketRegime` 폴더에 실제 Gold로 구축·실행을 마쳤습니다. 항목은 `LH_MarketRegime`, `NB_R01~R03`, `PL_MarketRegime_Daily`(일정 꺼짐), MLflow 실험 2개, `SM_MarketRegime`, `RPT_MarketRegime`입니다. PostgreSQL 복사, API, 웹 메뉴 연결은 다음 단계입니다. 운영 현황은 `08_구동현황_및_전체작동_가이드.md`, 상세 설명은 `07_시장국면_Fabric_구축_설명서.md`에 있습니다.

> 웹 대시보드의 샘플 JSON(`web/regime-dashboard/sample/`)과 스크린샷 6장은 화면 확인용 **합성(가상) 데이터**입니다. 실제 결과는 Power BI 보고서 `RPT_MarketRegime`과 `LH_MarketRegime`의 스냅샷에서 확인합니다.

## 무엇을 하나

| 단계 | 방법 | 결과 |
|---|---|---|
| 피처 | Gold의 KOSPI·20종목·거시 5종에서 날짜별 시장 상태 지표 생성 (20일 수익률·변동성, 하락 종목 비율, 종목 간 상관, VIX, 환율 등) | `gold_regime_features` |
| 국면 분류 | 가우시안 HMM 3상태, 21거래일마다 그때까지의 자료로만 재학습(walk-forward), 필터링 확률, 5일 확인 후 라벨 전환 | `gold_regime_daily` |
| 비교·검증 | GMM 실루엣 비교, 알려진 하락 구간 포착, 안정성, 실시간 vs 사후 일치율 | `validation.json`, MLflow |
| 유사 시기 | 표준화 피처의 유클리디안 거리 KNN (이후 수익률은 계산하지 않음) | `gold_regime_similar` |
| 게시 | 검사를 통과한 스냅샷 JSON 1개 → PostgreSQL → API → 웹 | `regime.snapshot`, `/api/v1/market-regime/*` |

## 폴더 구성

```
00_README.md                    이 문서
01_Fabric_연동_매뉴얼.md         Fabric 설치·실행 → 파이프라인 → PostgreSQL → API → 웹앱 전달 순서
02_한계점_및_부족자료.md          실제 실행 결과 기준 한계, 없는 자료, 모델 한계, 남은 확인 항목
03_API_계약서.md                 엔드포인트, 응답 구조, 화면 표기 규칙 (웹·백엔드 담당자용)
04_다음_할일_로드맵.md            (작업 기록) 구축 전 단계별 할 일. 최신 다음 단계는 07 설명서 10장
05_시장국면분석ML_기획서_최종본.md  기획서 최종본 (아키텍처·메달리온·파이프라인·알고리즘·검증·StressEngineML 비교)
06_개인워크스페이스_구축_및_이관.md (작업 기록) 개인 워크스페이스 검증 → 팀 워크스페이스 이관 절차
07_시장국면_Fabric_구축_설명서.md  팀 워크스페이스 구축 결과 설명서 (항목별 역할, 모델, 지표, 현재 상태, 담당자별 다음 단계)
08~12 (별도 묶음)                 구동 현황, 작동 주기·원리, Git 업로드, 프론트 메뉴·팝업, 배포(Fabric → PostgreSQL → API → 웹)
docs/diagrams/                   기획서 다이어그램 4종 PNG (Mermaid 원본은 기획서 안에 포함)

fabric/
  reference/market_regime/v1/    Lakehouse Files/reference/market_regime/v1/ 에 올릴 모듈
    regime_core.py               피처·HMM walk-forward·라벨·요약·KNN·검증·스냅샷
    hmm_numpy.py                 numpy 가우시안 HMM (설치 불필요, 결측 지표 처리)
    fabric_io.py                 Gold 인증 스냅샷 읽기, Delta 저장, 원자적 JSON 기록
    manifest.json                sha256 무결성 목록 (노트북이 실행 전에 대조)
  notebooks/                     NB_R01 피처 → NB_R02 학습·검증 → NB_R03 게시 (NB_R00은 개인 워크스페이스 검증용)
  sql/postgres_regime_schema.sql regime 스키마 (snapshot, daily, 최신 뷰)

api/                             FastAPI 라우터 (기존 앱에 include 또는 단독 실행)
  regime_api/                    router.py · service.py · repository.py · app.py
  tests/test_api.py              서비스·저장소·라우터 테스트 28개
  requirements.txt, Dockerfile

web/regime-dashboard/            웹앱 메뉴용 대시보드 (순수 JS·CSS·SVG, 의존성 없음)
  regime-dashboard.js / .css     RegimeDashboard.mount(el, {apiBase})
  index.html                     단독 페이지·iframe 대상
  menu-integration-example.html  메뉴 연동 예시
  sample/                        합성 스냅샷 (개발용)
  screenshots/                   확정 화면 6장

local_test/                      로컬 검증 도구 (운영 불필요)
  make_synthetic_gold.py         Gold와 같은 34컬럼 합성 데이터
  run_local_pipeline.py          전체 파이프라인 로컬 실행 → 샘플 스냅샷
  emulate_fabric.py              노트북 3개를 가짜 Spark·Lakehouse에서 실행 (게시 차단 포함)
  build_notebooks.py             노트북·매니페스트 생성
```

## 빠른 시작

1. `fabric/reference/market_regime/v1/`의 파일 4개를 `LH_MarketRegime` → `Files/reference/market_regime/v1/`에 올립니다(팀 `lh_whatif`의 Gold는 읽기 전용 바로가기 2개로 연결).
2. `fabric/notebooks/` 3개를 `MarketRegime` 폴더로 가져오고, 기본 Lakehouse를 `LH_MarketRegime`으로 연결합니다.
3. NB_R01 → NB_R02 → NB_R03 순서로 실행하고, NB_R02의 검증 결과와 그림을 확인합니다.
4. 파이프라인 `PL_MarketRegime_Daily` 구성(완료) → PostgreSQL DDL과 복사 활동 → 공통 API·APIM 경로 추가 → 웹 메뉴 연결 순서로 진행합니다(07 설명서 10장, 12 배포 가이드).

세부 절차는 `01_Fabric_연동_매뉴얼.md`에 있습니다.

## 이 환경에서 검증한 것

| 항목 | 결과 |
|---|---|
| HMM 구현 | 합성 3상태 복원 정확도 98.8%, 미래 행을 바꿔도 과거 필터링 확률 불변 |
| 전체 파이프라인 (합성 Gold, 2016-01 ~ 2026-11) | 약 50초, 스냅샷 380KB |
| Fabric 노트북 에뮬레이션 | R01→R02→R03 전 셀 실행, 합성 데이터 게시 차단, 정상 게시 시 테이블 8개·스냅샷·포인터 생성 |
| 선택 항목 결측 | 최신일 국고채 3년이 없어도 유사 시기 계산 정상 |
| API | 테스트 28개 통과 (오류 400·503, ETag 304, 해시 위조 차단, 합성 데이터 거부) |
| 대시보드 | Chromium 라이트·다크·모바일 렌더링, 콘솔 오류 없음, 색 조합 색각이상 검증 통과 |
| **실제 Fabric 실행 (2026-11-24)** | 팀 워크스페이스에서 파이프라인 3단계 성공(약 8분), 테이블 10개 생성, 기준일 2026-11-23(팀 Gold 최신일과 일치), Power BI 보고서 4페이지 정상 표시. 팀 기존 항목 43개와 `lh_whatif`는 변경 없음 |

## 이전 산출물과의 관계

- 지난번 `fabric_regime_knn_pipeline.ipynb`(키움 틱 → 일봉 집계 → HMM·KNN 시나리오)는 이 패키지로 **대체**합니다. 팀 Gold에 KRX 공식 일별 자료가 이미 있어 틱 집계가 필요 없고, 범위 조정에 따라 충격 시나리오와 이후 수익률 경로 계산은 뺐습니다.
- `economic_indicators.md`의 지표 중 Gold에 있는 것만 썼습니다. 나머지는 한계점 문서 2절에 정리했습니다.
