# Fabric 배치 작업

기준 작업 영역은 `ws-whatif-dev`, Lakehouse는 `lh_whatif`입니다. 아래 파일 경로는 이 Lakehouse의 `Files` 기준입니다.

2026-11-09 민철이 ML 연결에 필요한 부분을 수정했습니다. 변경한 코드에는 날짜, 시간, 이유를 주석으로 남겼습니다. [변경 기록](CHANGELOG.md)에서 수정 위치와 검증 결과를 확인하시면 됩니다.

## 실행 순서

기존 `pl_ingest_official20`이 오전 8시 KST에 원본을 수집합니다. 수집 성공 후 `nb_01_Bronze_to_Silver`, `nb_03_Gold_Build`가 차례로 실행됩니다. 기존 예약 종료일은 2027-01-02입니다.

원본 재수집 없이 다시 처리할 때는 `PI_batch_bronze to gold`를 실행하세요. Silver 실패 시 Gold는 실행되지 않습니다. `nb_02_Silver_Transform`을 별도로 함께 실행하지 마세요.

## 1. Bronze 원본

| 데이터 | 과거 자료 | 이후 수집 자료 |
| --- | --- | --- |
| 종목 주가 | `bronze/krx/history/stocks/*.json` | `bronze/krx/api/<배치명>/stocks/*.json` |
| 코스피 | `bronze/krx/history/index/kospi.json` | `bronze/krx/api/<배치명>/index/*.json` |
| 한국 3년 금리 | `bronze/ecos/history/korea_3y.json` | `bronze/ecos/api/<배치명>/observations/*.json` |
| 환율, 미국 10년 금리, WTI, VIX | `bronze/fred/history/*.parquet` | `bronze/fred/api/<배치명>/observations/*.json` |

주가는 2000년부터 각 종목의 상장 이후 자료입니다. 상장 전 데이터는 없습니다. API JSON의 `rows`가 실제 관측값이며, `bronze/_metadata/universe.json`이 수집 대상입니다. 완료 여부와 원본 해시는 `bronze/_runs/<배치명>/SUCCESS.json`에서 확인합니다.

## 2. Silver 정제

[nb_01_Bronze_to_Silver](notebooks/nb_01_Bronze_to_Silver.py)는 기존 Silver 7개 테이블을 갱신합니다.

- 종목 코드와 날짜, 숫자를 정리하고 신규 관측을 추가합니다. 기존 NULL에는 확인된 정상 값을 보완합니다. 이미 있는 정상 숫자는 자동으로 덮어쓰지 않습니다.
- 수정주가는 분할이나 권리락처럼 주식 조건이 바뀌면서 생긴 가격 단절을 반영한 가격입니다. 이를 확인하지 않으면 실제 손실이 아닌 가격 조정을 급락으로 학습할 수 있습니다.
- 과거 수정주가와 API 연결 검증은 완료된 자료를 재사용합니다. 새 날짜는 KRX 기준가격과 전일 대비 값을 대조합니다. 불일치하면 해당 행을 Silver에서 격리하고 Gold 갱신은 중단해 이전 Gold를 유지합니다. 새 기업행사는 공식 근거를 확인한 뒤 재처리해야 합니다.
- 정확한 관측 시각과 공표 시각을 모르면 NULL을 유지합니다. 검증된 공표 근거 또는 실제 수집 기록으로, 해당 날짜에 사용할 수 있었던 거시 값만 따로 정리합니다. 수집 시각을 공표 시각으로 바꾸지 않습니다.

검증 코드는 [batch_evidence.py](quality/batch_evidence.py)입니다. 기존 참고 코드 [price_bridge_reference.py](quality/price_bridge_reference.py)도 보존했습니다. 과거 연결 근거는 `reference/ml_input_validation/20261109_v1`, 매번 생성되는 검사 결과는 `silver_evidence`에 있습니다.

## 3. Gold 생성과 ML 연결

[nb_03_Gold_Build](notebooks/nb_03_Gold_Build.py)는 `Tables/gold_stock_market_daily_v11`을 갱신합니다. 기존 [34개 컬럼 계약](../../contracts/daily/schema.json)을 유지합니다. 한 행은 거래일 하나와 종목 하나입니다. 이전 `gold_stock_market_daily` 테이블은 ML 연결 대상으로 사용하지 않습니다.

Gold에는 검증된 가격 기준과 거시 관측일을 유지합니다. 거시 자료는 해당 거래일 15:30 KST까지 사용 가능하다는 근거가 있어야 하며, 관측일이 10일을 넘겨 오래됐으면 제외합니다. 10일 안이라는 이유만으로 미확인 자료를 사용하지 않습니다.

공표 시각 NULL을 0이나 임의 시각으로 채우지 마세요. ML에서는 Gold와 이용 가능 시점 근거를 함께 읽습니다. Gold 생성 후 아래 경로에 같은 실행의 묶음이 저장됩니다.

`gold_evidence/gold_stock_market_daily_v11/latest.json`

이 파일의 `path`를 읽으면 해당 버전 폴더가 나옵니다. 그 안의 `gold.parquet`, `provenance.parquet`, `certificate.json`을 함께 사용하세요. 다른 실행의 파일을 섞지 않도록 해시로 검사합니다. 별도 스키마의 학습 데이터가 아니라 Gold와 검증 근거를 고정한 묶음입니다.

ML의 [read_gold](../../analytics/src/conditional_service/gold_ready.py)에 위 세 경로를 전달하면 기존 로컬 검증과 같은 입력 검사 및 피처 계산을 사용합니다. 향후 5거래일 충격과 정답 수익률은 ML에서 생성합니다. 장중 분봉과 DART는 이 일별 Gold에 섞지 않습니다.

## 확인할 결과

Pipeline 실행 성공 후 Gold 최신 거래일, `certificate.json`의 `latest_eligible_date`, 제외 행 수를 확인하세요. 거래정지, 상장 전, 미공표, 오래된 관측은 정상적인 제외 사유일 수 있습니다. Gold에 최근 날짜가 있다는 사실만으로 모든 지표가 최신이라는 뜻은 아닙니다.

현재 Silver는 기존 테이블에 등록된 20종목을 처리합니다. 종목을 추가할 때는 Bronze뿐 아니라 Silver 관리 종목과 해당 종목의 과거 수정주가 근거도 보완해야 합니다. 기준 자료가 없는 종목을 자동으로 검증 완료 처리하지 않습니다. 모델 재학습이나 승격은 이 배치 파이프라인에서 수행하지 않습니다.

## 업종코드 연결

2026-11-10 민철 추가. KRX 공식 업종표를 Silver 마지막 단계에서 연결하고 기존 Gold가 그대로 전달합니다. 실시간 `asset_sector`도 같은 분류를 사용합니다. 전체 과거 행에는 현재 확인된 업종을 표시하며, 과거 당시 업종이 검증됐다는 뜻은 아닙니다. 적용 근거, 원본 경로, 갱신 방법은 [업종 연결](quality/SECTOR_MAPPING.md)을 확인하세요.

공표·관측 시각은 [공식 근거 수집](quality/PUBLICATION_EVIDENCE.md)을 확인하세요. 한국은행 RSS 공개 시각과 연준 환율 관측 정의를 연결했습니다. 미확인 시각을 예정 시각이나 수신 시각으로 채우지 않습니다. 변경 코드는 각 Notebook에 날짜와 민철 수정 기록을 남겼습니다.

2026-11-10 Gold의 거시 값 선택 전에 공표 근거 검사를 연결했습니다. [처리 기준과 파일 경로](quality/GOLD_AVAILABILITY.md), [출처별 확보한 시점과 미확인 항목](quality/TIMESTAMP_SOURCES.md)을 확인하세요. Gold 계약과 ML Notebook은 변경하지 않았습니다.
