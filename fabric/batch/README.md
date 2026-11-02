# Fabric 배치 작업

공식 데이터 수집과 Bronze 적재, 매일 자동 수집 설정까지 완료했습니다. Fabric 배치 담당자는 아래 원본을 읽어 Silver 정제와 Gold 생성을 시작하시면 됩니다.

## 완료한 부분과 구현할 부분

| 구분 | 내용 |
| --- | --- |
| 수집 담당 완료 | 공식 원본 적재와 자동 수집, 20종목의 과거 수정주가와 API 가격 대조, 2026-10-16 이후 10월 30일까지 200행 연결 검증을 완료했습니다. 삼성바이오로직스 권리락 차이도 확인했습니다. |
| Fabric 담당 구현 | 기존 검증 기준을 Silver 작업에 넣어 신규 배치마다 실행하고, 통과한 데이터만 Delta 테이블에 반영하세요. 처리 이력, 실패 보류, 재실행과 Gold 갱신까지 구현하시면 됩니다. |

검증을 취소한 것이 아닙니다. 역할을 Bronze 수집까지로 정리하면서 수집 노트북에서 연결 처리를 분리했습니다. **현재 자동 실행되는 것은 원본 수집이며, 일별 연결 검사와 Silver 반영은 아직 자동화돼 있지 않습니다.** 기존 구간의 통과 결과가 앞으로 발생할 기업행사까지 승인하는 것은 아닙니다.

## 1. Bronze 읽기

기준 위치는 `ws-whatif-dev → lh_whatif → Files → bronze`입니다. 아래 경로는 모두 bronze 기준입니다.

| 데이터 | 최초 과거 자료 | 이후 API 자료 |
| --- | --- | --- |
| 종목 주가 | `krx/history/stocks/*.json` | `krx/api/<배치명>/stocks/*.json` |
| 코스피 지수 | `krx/history/index/kospi.json` | `krx/api/<배치명>/index/*.json` |
| 한국 3년 국채 금리 | `ecos/history/korea_3y.json` | `ecos/api/<배치명>/observations/*.json` |
| 환율, 미국 10년 금리, WTI, VIX | `fred/history/*.parquet` | `fred/api/<배치명>/observations/*.json` |

과거 KRX 자료는 2000년부터 종목별 상장 이후 2026-10-16까지이며, 이후는 API 자료로 연결합니다. 2026-11-02 확인 기준 주가는 10월 30일까지 확보했습니다. 거시 자료의 최신 관측일은 지표마다 다릅니다.

- 과거 주가 JSON은 종목별 전체 이력이며 파일명이 종목 코드입니다. ZIP을 풀 필요는 없습니다.
- 과거 JSON은 배열이고, API JSON은 `rows` 배열이 실제 데이터입니다.
- `_runs/<배치명>/SUCCESS.json`의 상태와 누락 종목을 확인하고 `files` 목록에 있는 원본만 읽으세요. 파일 경로는 bronze 기준입니다.
- API 전체 종목 중 `_metadata/universe.json`의 20종목을 선택하세요. 코스피 계열 지수에서는 대표 코스피를 구분하세요.

## 2. Silver 만들기

Notebook에서 주가, 코스피, 거시 자료를 각각 정리해 Delta 테이블로 저장하세요.

| 작업 | 처리 기준 |
| --- | --- |
| 형식 통일 | 종목 코드는 6자리 문자열, 날짜는 date, 가격과 거래량은 숫자로 변환합니다. 숫자의 쉼표를 제거하고 코드 앞의 0은 유지합니다. |
| 과거와 최근 연결 | KRX 과거 수정 기준일은 2026-10-16이며 API 주가는 미수정 가격입니다. 연결일 기준가격과 수익률을 대조하고 기업행사를 확인합니다. 불일치하면 임의 보정하지 않고 연결을 보류합니다. |
| 중복과 정정 | 종목과 거래일, 또는 지표와 관측일을 기준으로 처리합니다. 수집 시각과 정정 전 원본을 보존합니다. |
| 결측과 거래정지 | 상장 전, 거래정지, 수집 누락, 미공표를 구분합니다. 임의로 보간하지 않습니다. |
| 시각 구분 | 관측일, 수집 시각, 실제 공표 시각을 구분합니다. 공표 시각을 모르면 NULL로 남깁니다. |

삼성바이오로직스의 2026-10-02 유상증자 권리락은 원인 확인과 연결 검증을 마쳤습니다. 검증 자료는 `Files/_audit/batch/20261102`에 있으며, 일반 입력으로 합치지 마세요. 수정주가 연결 운영은 Silver 단계에 구현해야 합니다.

### 참고할 연결 검증 코드

[price_bridge_reference.py](quality/price_bridge_reference.py)는 현재 Bronze 경로를 읽어 가격 연결을 검사합니다. 테이블에 쓰거나 조정 비율을 임의로 만들지 않습니다. [검사 테스트](quality/test_price_bridge_reference.py)도 함께 제공합니다.

노트북에서 해당 파일을 가져온 뒤 아래처럼 호출하세요.

```python
from price_bridge_reference import read_history, read_stock_batch, validate_connection

bronze = "/lakehouse/default/Files/bronze"
history = read_history(bronze)  # 최초 실행. 이후에는 최신 정상 Silver 주가를 사용합니다.
manifest, rows, days = read_stock_batch(bronze, batch_id)
report, new_rows = validate_connection(
    history, rows, manifest["requested_assets"], days,
    raw_comparable_from="2026-10-16",
)
if report["status"] != "passed":
    raise ValueError(report)  # 기존 Silver를 유지하고 원인을 확인합니다.
# 통과한 new_rows를 Silver에 반영하는 코드는 담당자가 구현합니다.
```

입력 history는 `asset_id`, `date`, `close`, `volume` 컬럼이 있는 pandas DataFrame입니다. 최초 연결은 `_runs/imported_20261001_20261030` 배치를 사용하면 10월 16일 경계와 이후 자료를 함께 검사할 수 있습니다. 이후에는 최신 정상 Silver를 기준으로 검사하세요. 경계 날짜가 빠지면 필요한 기간을 추가 수집해야 합니다. 새 기업행사가 감지되면 공식 수정 이력을 확인해 재검증하고, 오류를 없애려고 기준일만 바꾸지 마세요.

## 3. Gold 만들기

[일별 계약](../../contracts/daily/schema.json)에 맞춰 `gold_stress_daily` Delta 테이블 하나를 만드세요.

- 한 행은 거래일 하나와 종목 하나입니다. 주가와 거래량에 코스피 및 거시 관측값을 연결합니다.
- 같은 날짜의 시장 공통 값은 모든 종목에서 같아야 합니다. 한국 3년 금리를 미국 10년 금리 대신 넣지 마세요.
- 공개 전 거시 값을 해당 시점의 입력으로 사용하지 마세요. 공표 시각 미확인 자료는 별도 품질 상태와 적용 기준을 남기세요.
- 출처, 수정주가 버전, 데이터 버전, 품질 상태를 기록합니다. 미확인 업종이나 시각을 만들어 넣지 마세요.
- 시장 피처와 향후 5거래일 충격 및 정답 수익률은 ML 담당이 만듭니다. 장중 분봉과 DART 공시는 이 테이블에 직접 섞지 않습니다.

## 4. 매일 실행과 완료 기준

기존 수집 파이프라인은 매일 한국 시간 오전 8시에 전일까지 최근 8일을 받아 출처별 api 폴더에 추가합니다. 현재 예약 종료일은 2027-01-02입니다. 과거 파일을 덮어쓰는 방식이 아닙니다.

처리한 배치명을 기록하고 새 완료 배치만 Silver와 Gold에 반영하세요. 같은 배치를 다시 실행해도 중복이 없어야 하며, 검증 실패 시 이전 정상 버전을 유지해야 합니다.

완료 후 ML 담당에게 Gold 테이블 위치, 데이터 버전, 종목과 지표별 최신 날짜, 미확인 또는 제외 항목을 전달하세요. 별도의 전달용 파일 폴더는 사용하지 않습니다.
