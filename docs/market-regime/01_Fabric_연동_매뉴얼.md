# Fabric 연동 · 구축 · 웹앱 전달 매뉴얼 — [시장국면분석ML]

> **구축 현황 (2026-11-24 기준)**
> 팀 워크스페이스 `ws-whatif-dev`의 `MarketRegime` 폴더에 실제 Gold로 구축·실행을 마쳤습니다. 항목은 `LH_MarketRegime`, `NB_R01~R03`, `PL_MarketRegime_Daily`(일정 꺼짐), MLflow 실험 2개, `SM_MarketRegime`, `RPT_MarketRegime`입니다. PostgreSQL 복사, API, 웹 메뉴 연결은 다음 단계입니다. 1~4절과 6절(복사 활동 제외)은 이 상태로 구축되어 있습니다. 운영 현황은 `08_구동현황_및_전체작동_가이드.md`, 상세 설명은 `07_시장국면_Fabric_구축_설명서.md`에 있습니다.

이 문서대로 진행하면 Fabric에서 국면 분석을 돌려 스냅샷을 만들고, PostgreSQL과 API를 거쳐 웹앱 메뉴에 표시할 수 있습니다. 순서는 다음과 같습니다.

```
gold_stress_daily (기존, 스트레스엔진ML과 공유)
  → NB_R01 피처 → NB_R02 HMM 학습·검증 → NB_R03 스냅샷 게시
  → Copy 작업 → PostgreSQL regime.snapshot
  → Market Regime API (/api/v1/market-regime/*)
  → 웹앱 "시장 국면" 메뉴 (regime-dashboard.js)
```

Bronze·Silver·Gold는 새로 만들지 않습니다. 팀이 이미 운영 중인 `gold_stress_daily` v1.1과 그 인증 스냅샷(`Files/gold_evidence/gold_stock_market_daily_v11/`)만 읽습니다. 스트레스엔진ML의 테이블·노트북·파이프라인은 건드리지 않고, 국면 분석 결과는 모두 `gold_regime_*`, `regime_pg_*`, `Files/regime/` 이름으로 따로 저장합니다.

---

## 1. 준비물 확인

| 항목 | 확인 방법 |
|---|---|
| 작업 영역 | `ws-whatif-dev` |
| 기본 Lakehouse | `LH_MarketRegime` (결과 전용). 팀 `lh_whatif`의 Gold는 읽기 전용 바로가기 `Files/gold_evidence`, `Tables/gold_stress_daily`로 읽음 |
| Gold 상태 | `Files/gold_evidence/gold_stock_market_daily_v11/health.json`의 `status`가 `ready` |
| Gold 인증 스냅샷 | 같은 폴더의 `latest.json`과, 그 `path` 아래 `gold.parquet`, `input_eligibility.parquet`, `certificate.json` |
| Gold 기간 | 사용 가능한 거래일이 **1,002일 이상**(첫 학습 750일 + 실시간 판정 252일). 10년치면 충분 |
| PostgreSQL | 스트레스엔진 파이프라인(`PL_StressLab_Research_Feature_to_PG`)이 쓰는 Azure PostgreSQL 연결을 재사용 |

> 추가 설치는 필요 없습니다. HMM을 numpy로 직접 구현해서 `hmmlearn`이 없어도 되고, 파이프라인에서 `%pip install`을 쓰지 않습니다. pandas·numpy·scikit-learn은 Fabric 기본 런타임에 들어 있습니다.

## 2. 모듈 업로드 (1회, 버전이 바뀔 때마다)

1. `LH_MarketRegime` → Files → `reference` 폴더에 `market_regime/v1` 폴더를 만듭니다.
2. 이 패키지의 `fabric/reference/market_regime/v1/` 안 파일 4개를 그대로 올립니다.
   - `hmm_numpy.py`, `regime_core.py`, `fabric_io.py`, `manifest.json`
3. 노트북은 실행할 때마다 `manifest.json`의 sha256과 파일을 대조합니다(팀 Gold 노트북과 같은 방식). 파일 하나만 바꿔 올리면 `REGIME_MODULE_HASH_MISMATCH`로 멈추므로, 코드를 고쳤다면 `local_test/build_notebooks.py`를 다시 실행해 매니페스트를 새로 만든 뒤 함께 올리세요.

## 3. 노트북 가져오기

1. 작업 영역에 `MarketRegime` 폴더를 만듭니다. 스트레스엔진의 `NB_WebAPI` 폴더와 분리합니다.
2. 가져오기(Import) → 노트북 → `fabric/notebooks/`의 3개 파일을 올립니다.
   - `NB_R01_Build_Regime_Features.ipynb`
   - `NB_R02_Train_Regime_HMM.ipynb`
   - `NB_R03_Publish_Regime_Snapshot.ipynb`
3. 각 노트북을 열어 **기본 Lakehouse를 `LH_MarketRegime`으로 연결**합니다(탐색기 → Lakehouse 추가 → 기존 → LH_MarketRegime). `lh_whatif`를 기본으로 연결하면 노트북이 스스로 멈춥니다.

## 4. 첫 실행 (수동, 순서대로)

| 순서 | 노트북 | 걸리는 시간(로컬 기준) | 확인할 출력 |
|---|---|---|---|
| 1 | NB_R01 | 수십 초 | `피처 (N, 23)`, 사용 가능 일수, 종목별 첫 사용일, HMM 피처 결측 비율 |
| 2 | NB_R02 | 약 1분 | BIC 표, 국면별 일수, **검증 결과**(하락 구간 포착, 연간 전환 횟수, 일치율), KOSPI·국면 그림 |
| 3 | NB_R03 | 수십 초 | `게시 완료: <버전>`, 현재 국면 |

수동 실행 때는 `RUN_ID`를 비워 둡니다. NB_R01이 새 RUN_ID를 만들어 `Files/regime/runs/current_run.json`에 적고, R02·R03가 그것을 이어받습니다.

**NB_R02 결과는 꼭 눈으로 확인하세요.** 실제 데이터로는 이번이 처음입니다(한계점 문서 1절 참고).
- 그림에서 2020년 3월, 2022년 하반기가 폭락장(빨강 계열)으로 칠해지는지
- 연간 전환 횟수가 대략 2~8회인지. 너무 많으면 라벨이 깜빡이는 것이고, 너무 적으면 국면이 고착된 것입니다
- 폭락장 비중이 지나치게 크지 않은지(합성 테스트 약 19%, 2026-11-24 실제 실행 16%)

결과가 이상하면 NB_R01의 `CONFIG_OVERRIDES_JSON`으로 설정을 바꿔 R01→R03를 다시 돌립니다. 예시는 다음과 같습니다.

```json
{"hmm_features": ["kospi_ret_20d","kospi_vol_20d_log","breadth_down_5d","vix_log"], "label_confirm_days": 3}
```

설정은 `context.json`에 저장돼 R02·R03에 그대로 전달됩니다.

### 실행 후 생기는 것

| 종류 | 이름 | 내용 |
|---|---|---|
| Delta | `gold_regime_features` | 날짜별 시장 상태 피처 |
| Delta | `gold_regime_daily` | 날짜별 국면 라벨, 3국면 확률, 판정 구분(walk_forward / initial_in_sample) |
| Delta | `gold_regime_runs`, `gold_regime_summary`, `gold_regime_transition`, `gold_regime_similar` | 구간·요약·전이·유사 시기 |
| Delta (단계) | `regime_pg_snapshot`(1행), `regime_pg_daily` | PostgreSQL로 복사할 이번 실행분 |
| 파일 | `Files/regime/snapshots/<버전>/regime_snapshot.json` + `certificate.json` | API·웹이 읽는 스냅샷 (sha256 포함) |
| 파일 | `Files/regime/latest.json`, `Files/regime/health.json` | 최신 포인터와 상태(ready / blocked) |
| 파일 | `Files/regime/runs/<RUN_ID>/` | context, model, bic, validation json |
| MLflow | 실험 `MarketRegime_HMM` | 파라미터·검증 지표 (`LOG_TO_MLFLOW=True`일 때) |

### 게시가 막히는 경우 (NB_R03)

검사를 통과하지 못하면 `health.json`이 `blocked`가 되고 `latest.json`은 바뀌지 않습니다. 이전 정상 스냅샷이 계속 서비스됩니다.

| 사유 코드 | 뜻 | 조치 |
|---|---|---|
| `AS_OF_NOT_GOLD_LATEST` | 국면 기준일 ≠ Gold 최신일 | Gold 재실행 여부 확인 후 R01부터 다시 실행 |
| `OUT_OF_SAMPLE_TOO_SHORT`, `HISTORY_TOO_SHORT` | 이력이 짧음 | Gold 기간 확인, 또는 `min_train_days`를 줄임(권장하지 않음) |
| `CURRENT_PROBABILITIES_INVALID` | 확률 합 오류 | R02 출력 확인 |
| `NOT_FABRIC_GOLD_DATA` | `DATA_MODE`가 fabric_gold가 아님 | 파라미터 확인 |
| `GOLD_NOT_READY` (R01) | Gold health가 ready가 아님 | Gold 파이프라인 먼저 성공시키기 |

## 5. PostgreSQL 준비 (1회)

1. 서비스 DB에 `fabric/sql/postgres_regime_schema.sql`을 실행합니다. `regime` 스키마와 `regime.snapshot`, `regime.daily` 테이블, `v_latest_snapshot` 뷰가 만들어집니다.
2. API용 읽기 전용 계정을 만들고 `select` 권한만 줍니다(SQL 파일 하단 예시). 비밀번호는 Key Vault(`kv-whatif-dev-…`)에 보관합니다.

## 6. 파이프라인 `PL_MarketRegime_Daily` 만들기

| 순서 | 활동 | 설정 |
|---|---|---|
| 1 | Notebook: NB_R01 | 기본 매개변수 `RUN_ID` (String) = `@pipeline().RunId` |
| 2 | Notebook: NB_R02 | `RUN_ID` = `@pipeline().RunId`, `LOG_TO_MLFLOW` (Bool) = true |
| 3 | Notebook: NB_R03 | `RUN_ID` = `@pipeline().RunId`, `DATA_MODE` = `fabric_gold` |
| 4 | Copy: snapshot | 원본: Lakehouse `LH_MarketRegime` 테이블 `regime_pg_snapshot` → 대상: PostgreSQL `regime.snapshot`, 쓰기 방식 **삽입(Insert)** |
| 5 | Copy: daily | 원본: `regime_pg_daily` → 대상: `regime.daily`, 삽입 (FK 때문에 반드시 4 다음에) |

- 각 활동은 앞 활동 **성공 시**에만 이어지게 연결합니다. R03가 막히면 Copy도 실행되지 않습니다.
- 열 매핑은 이름이 같아서 자동 매핑하면 됩니다. `as_of`는 date, `created_at`은 timestamp(UTC)입니다.
- 같은 `snapshot_version`을 두 번 복사하면 기본키 충돌로 실패합니다. 이것은 의도한 동작입니다. 재복사가 필요하면 먼저 `delete from regime.snapshot where snapshot_version = '<버전>'`을 실행합니다(daily는 cascade로 함께 지워짐).

**일정.** 국면 분석은 Gold가 갱신된 뒤에 돌아야 합니다. 현재 운영 순서는 08:00 KST 수집 → Silver → Gold(`PI_batch_bronze to gold`)이므로 둘 중 하나를 고릅니다.
- **현재 방식(권장):** 팀 파이프라인은 수정하지 않고 `PL_MarketRegime_Daily`의 **자체 일정**으로 Gold 갱신 뒤에 실행합니다. 일정은 매일 10:30 KST로 만들어 두었고 **꺼져 있습니다(enabled=false)**. 12:00 수집분까지 반영하려면 12:30으로 바꿉니다. Gold가 늦으면 R01이 `GOLD_NOT_READY`로 멈추므로 잘못된 게시는 생기지 않습니다.
- 대안: 팀 Gold 파이프라인 끝에 **Invoke pipeline** 활동을 추가하는 방식도 가능하지만, 팀 항목을 수정하는 일이므로 Gold 파이프라인 담당자와 합의한 뒤에만 진행합니다.
- 현재 구축된 파이프라인에는 1~3번 노트북 활동만 있습니다. 4·5번 복사 활동은 5절의 PostgreSQL 준비 뒤에 추가합니다.

## 7. API 붙이기

API 코드는 `api/regime_api/`에 있습니다. 읽기 전용 GET만 있고, PostgreSQL의 최신 스냅샷 1행을 읽어 5분 동안 캐시합니다.

### 방법 A (권장) — 기존 FastAPI 앱에 라우터만 추가

스트레스엔진 `/predict/auto`가 들어 있는 FastAPI 앱이나 시장 상태 API 앱의 백엔드 담당자에게 아래만 요청하면 됩니다.

```python
# requirements: psycopg[binary]>=3.1 추가
from regime_api.router import router as regime_router
app.include_router(regime_router)          # → /api/v1/market-regime/*
```

`regime_api` 폴더를 앱 소스에 복사하고 아래 환경 변수를 설정합니다(Container Apps → 비밀/환경 변수, DSN은 Key Vault 참조).

| 변수 | 값 |
|---|---|
| `REGIME_SOURCE` | `postgres` |
| `REGIME_PG_DSN` | `postgresql://regime_api_reader:<pw>@<host>:5432/<db>?sslmode=require` |
| `REGIME_CACHE_SECONDS` | `300` (선택) |
| `REGIME_ALLOW_SYNTHETIC` | `false` (운영에서는 반드시 false) |

### 방법 B — 별도 Container App

`api/Dockerfile`로 이미지를 만들어 ACR에 올리고 Container App으로 띄웁니다. 환경 변수는 위와 같고, 추가로 `REGIME_CORS_ORIGINS=https://<웹앱 도메인>`을 설정합니다. API Management를 쓰는 경우 `/api/v1/market-regime/*` 경로를 이 앱으로 보냅니다.

### 개발용 — PostgreSQL 없이 파일로

`REGIME_SOURCE=file`, `REGIME_SNAPSHOT_PATH=<Files/regime 폴더를 복사한 경로>`로 두면 `latest.json`을 따라 스냅샷 파일을 읽습니다. 샘플(합성) 파일로 화면만 띄울 때만 `REGIME_ALLOW_SYNTHETIC=true`를 씁니다.

### 확인

```bash
curl https://<api-host>/api/v1/market-regime/health      # {"status":"ok","as_of":...}
curl https://<api-host>/api/v1/market-regime/current
```

엔드포인트와 응답 형식은 `03_API_계약서.md`에 정리했습니다.

## 8. 웹앱 담당자에게 전달하기

전달물은 `web/regime-dashboard/` 폴더 전체입니다. 프레임워크가 필요 없는 순수 JS·CSS(SVG 차트)라서 어떤 웹앱에도 붙일 수 있습니다.

| 파일 | 용도 |
|---|---|
| `regime-dashboard.js`, `regime-dashboard.css` | 대시보드 모듈 (전역 `RegimeDashboard`) |
| `index.html` | 단독 페이지 / iframe 대상 (`?api=`, `?theme=`, `?tab=`) |
| `menu-integration-example.html` | 좌측 메뉴에 "시장 국면"을 붙이는 최소 예시 |
| `sample/regime_snapshot.sample.json` | 개발용 **합성** 스냅샷 (화면에 '샘플 데이터' 배너가 뜸) |
| `screenshots/` | 확정 화면 6장 (개요·이력·유사 시기·모델, 다크, 모바일) |

메뉴에 붙이는 방법은 세 가지입니다(담당자가 고르면 됩니다).

1. **스크립트로 마운트**: 메뉴 클릭 시 아래 코드를 실행합니다. 화면을 나갈 때 `destroy()`를 호출합니다.
   ```html
   <link rel="stylesheet" href="/regime/regime-dashboard.css">
   <script src="/regime/regime-dashboard.js"></script>
   <script>
     const dash = RegimeDashboard.mount(document.getElementById("menu-content"),
       { apiBase: "https://<api-host>", theme: "auto" });
   </script>
   ```
2. **iframe**: `<iframe src="/regime/index.html?api=https://<api-host>" style="width:100%;height:100%;border:0"></iframe>`
3. **React 등 프레임워크**: `03_API_계약서.md` 5절의 래퍼 예시를 씁니다.

API가 준비되기 전에는 `apiBase` 없이 `fallbackUrl`만 주면 샘플로 화면을 미리 붙여 볼 수 있습니다. 샘플은 합성 데이터라 배너가 항상 뜨고, API 연결 후에는 사라집니다.

## 9. 운영 점검표

- [ ] 매일 Gold 성공 뒤 `PL_MarketRegime_Daily` 성공
- [ ] `Files/regime/health.json`의 status가 `ready`이고, `as_of`가 Gold 최신일과 같음
- [ ] `select * from regime.v_latest_snapshot;`의 as_of가 오늘 기준 직전 거래일
- [ ] API `/health`가 ok
- [ ] 월 1회: MLflow `MarketRegime_HMM`에서 연간 전환 횟수·하락 구간 포착률 추이 확인
- [ ] 분기 1회: 오래된 스냅샷 정리(SQL 파일의 보관 정책 예시)

## 10. 문제 해결

| 증상 | 원인 | 조치 |
|---|---|---|
| R01 `GOLD_SNAPSHOT_HASH_MISMATCH` | Gold 인증서와 파일이 다름 | Gold 노트북 재실행. 국면 쪽에서 해결할 문제가 아님 |
| R01 `GOLD_SNAPSHOT_AND_DELTA_DATE_DIFFER` | 인증 스냅샷과 Delta 테이블의 최신일 불일치 | Gold 게시 중간 상태이므로 잠시 후 재실행 |
| R02가 오래 걸림 | 재학습 횟수가 많음 | `refit_every`를 63으로 올림 (정확도와 시간을 맞바꿈) |
| 웹 화면에 '샘플 데이터' 배너 | API가 합성 스냅샷을 주거나, 연결 실패로 예비 파일을 표시 중 | API `/health` 확인, `REGIME_ALLOW_SYNTHETIC=false` 확인 |
| API 503 `SYNTHETIC_SNAPSHOT_REFUSED` | DB에 운영 스냅샷이 없음 | 파이프라인 Copy 성공 여부 확인 |
| API 503 `SNAPSHOT_SHA256_MISMATCH` | 복사 중 payload 손상 | 해당 버전 삭제 후 Copy 재실행 |
