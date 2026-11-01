# 데이터 전달 계약

| 담당 | 볼 파일 | 용도 |
| --- | --- | --- |
| Fabric 일별 / ML | [daily/schema.json](daily/schema.json), [daily/mock.json](daily/mock.json) | 일별 테이블 정의와 2종목 × 2거래일 예시 |
| 수집 / Fabric 실시간 / 서비스 | [realtime/schema.json](realtime/schema.json), [realtime/mock.json](realtime/mock.json) | 시세 입력과 시장 위험 출력 정의 |

[실시간 작업 안내](realtime/README.md)에서 처리 순서와 계산 기준을 확인하세요. `schema.json`은 형식 정의이고 `mock.json`은 합성 예시입니다. 모든 예시의 `is_mock`은 true이며 운영 적재·학습에서 제외합니다.

## 일별 데이터

Fabric 일별 담당은 `gold_stress_daily` 한 테이블을 전달합니다. Lakehouse의 Delta 테이블이며, 로컬 테스트에는 Parquet로 내보내면 됩니다. JSON 메시지로 전달하는 데이터가 아닙니다.

한 행은 **거래일 하나와 종목 하나**입니다. 같은 날짜의 시장 공통 값은 모든 종목에서 같아야 합니다. Bronze와 Silver의 내부 구성은 Fabric 담당자가 정하면 됩니다.

## 필요한 컬럼

| 컬럼 | 타입 / 단위 | 설명 |
| --- | --- | --- |
| trading_date | date | 한국 거래일 |
| asset_id, sector_id | string | 종목 식별자와 업종 코드. 종목코드는 앞의 0을 유지합니다. |
| instrument_kind | string | stock, index, sector_etf 구분 |
| close, volume | double / 원, 주 | 종가와 일 거래량. 지수는 원이 아닌 지수 단위입니다. |
| price_basis, adjustment_version | string | 수정주가 여부와 기업행사 반영 버전 |
| kospi_close | double / 지수 | 해당 거래일 코스피 종가 |
| usdkrw | double / 원/달러 | 원/달러 관측값 |
| us_treasury_10y | double / % | 미국 10년 국채 금리. 한국 기준금리와 다릅니다. |
| wti | double / 달러/배럴 | WTI 관측값 |
| vix | double / 지수 | VIX 관측값 |
| price_available_at | UTC timestamp, NULL 허용 | 해당 가격을 실제로 사용할 수 있게 된 시각 |
| 각 요인의 observed_at, available_at | UTC timestamp, NULL 허용 | 관측 시각과 실제 공개 시각을 분리합니다. 아래 이름을 사용하세요. |
| source_ref, dataset_version | string | 원본 조회 위치와 데이터 버전 |
| quality_status | string | valid, missing, suspended, quarantined |
| is_mock | boolean | 합성 예시 여부. true는 운영·학습 제외 |

요인별 시각 컬럼은 `usdkrw_observed_at`, `usdkrw_available_at`처럼 만듭니다. `us_treasury_10y`, `wti`, `vix`에도 같은 접미사를 붙입니다. 시각 없이 날짜만 확인되면 `usdkrw_observation_date`처럼 날짜를 별도로 남기고 observed_at은 NULL로 둡니다.

## 전달할 때 지킬 기준

- 가격과 거시 자료의 원본 시리즈를 고정하고, 공급자를 바꾸면 버전을 변경합니다. 현재 연구의 거시 시리즈는 DEXKOUS, DGS10, DCOILWTICO, VIXCLS입니다. ECOS 자료를 같은 변수로 임의 대체하지 않습니다.
- 거시 값은 관측 기록입니다. **관측일이 과거여도 공개 전이면 ML의 현재 상태 입력으로 쓰지 않습니다.** 주간 공표되는 환율처럼 관측일과 공개일이 다른 자료가 있습니다.
- 시각을 모르면 NULL로 둡니다. 예상 공표 일정은 실제 available_at에 넣지 않습니다. 해당 자료는 엄격한 시점 검증에서 제외하거나 별도 연구용으로 표시합니다.
- 다른 종목이나 ETF에 결측이 있어도 정상 종목의 행은 삭제하지 않습니다. 자기 종목의 결측과 거래정지는 그대로 표시합니다.
- ETF는 보조 자료이며 정식 개별 종목 타깃에 넣지 않습니다. 상장폐지 종목도 삭제하지 않고 종목 이력을 보존합니다.
- 수정 전후 가격을 섞지 않습니다. 한 버전의 전체 이력을 넘기고, 품질 검사가 끝난 배치만 게시합니다.

**Fabric은 관측 데이터까지 전달하고, ML 담당이 시장 피처와 5거래일 정답을 만듭니다.** 실시간 분봉과 DART 공시 원문은 이 ML 테이블에 필수로 넣지 않습니다. 각각 장중 위험 표시와 AI 근거에 사용합니다.

현재 검증 대상은 삼성전자, 현대차, 신한지주입니다. 다른 종목 데이터도 같은 형식으로 준비하되 모델 지원 승인은 별도로 진행합니다.

스키마의 모든 컬럼을 생성하고 미확인 값은 허용된 NULL로 채웁니다. 같은 배치에서 `(dataset_version, trading_date, asset_id)`는 중복되면 안 됩니다. JSON Schema는 열 타입을 검사하며, 키 중복·날짜별 공통 값·시각 정합성은 별도 데이터 검사로 확인합니다.
