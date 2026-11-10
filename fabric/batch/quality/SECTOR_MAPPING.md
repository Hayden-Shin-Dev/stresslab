# 업종 연결

2026-11-10 15:55 KST 민철 수정. 기존 `sector_id` 컬럼을 사용합니다. ML 모델과 Gold 34컬럼 계약은 변경하지 않습니다.

1. 공식 업종 원본은 `lh_whatif/Files/bronze/krx/reference/industry/krx_sector_20261109.json`입니다. KRX 업종분류 현황의 2026-11-09 조회 결과이며 실제 수집일은 11월 10일입니다.
2. `nb_01_Bronze_to_Silver` 마지막 셀에서 종목코드로 최신 공식 업종표를 연결해 전체 날짜의 `silver_stock_daily.sector_id`를 채웁니다. 기존 `nb_03_Gold_Build`가 그대로 Gold에 전달합니다. 가격과 거시 값은 수정하지 않습니다.
3. 실시간은 기존 `eventhouse_whatif.asset_sector`의 같은 매핑을 사용합니다. 지표 계산식과 틱 스키마는 유지했습니다. `market_state_current` 조회만 같은 기준 시각의 최신 재계산 결과를 먼저 선택하도록 수정했습니다.

값은 `KRX_KOSPI:전기·전자`처럼 KRX 업종명을 구분한 문자열입니다. 키움 숫자 업종코드나 DART 산업코드가 아닙니다. 삼성전자와 삼성전자우 모두 원본에서 직접 확인했습니다.

전체 과거 행에도 현재 확인된 업종을 표시합니다. 과거 당시의 업종이 검증됐다는 뜻은 아닙니다. `Files/silver_evidence/sector_mapping/assignments.parquet`에 원본 분류일, 수집 시각, 해시와 `classification_basis=current_reference_metadata`, `historical_backfill`, `point_in_time_known=false`를 남깁니다. 이 값을 과거 당시 알려진 업종으로 사용해 백테스트하지 마세요. 업종별 과거 분석에는 별도 시점 검증이 필요합니다.

기존 자동 파이프라인은 매번 이 업종표를 읽어 전체 날짜에 적용합니다. 종목의 공식 업종이 없으면 임의 값으로 채우지 않고 처리를 중단합니다. **업종표 자체를 매일 다시 수집하는 기능은 아닙니다.** 이후 공식 분류가 바뀌면 새 날짜의 원본을 같은 폴더에 추가하세요. 30일이 지나면 근거 파일의 `reference_review_needed`가 표시됩니다. 오래됐다는 이유만으로 기존 가격 수집과 ML 입력 전체를 중단하지 않습니다.

실시간 표는 종목당 한 행을 유지해야 합니다. 다음 분류 변경 시 기존 행을 교체하고, 여러 분류를 중복 추가하지 마세요. 현재 KQL이 `take_any`로 읽으므로 중복 분류는 결과를 불안정하게 만듭니다.

코드는 [sector_reference.py](sector_reference.py), 검증은 [test_sector_reference.py](test_sector_reference.py)입니다. 노트북 수정 셀에는 날짜와 수정 이유를 남겼습니다.

새 원본 수집은 [collect_krx_sector_reference.py](../../../ingestion/batch/collect_krx_sector_reference.py)를 사용하세요. 검증 환경은 pykrx 1.2.8이며, `KRX_ID`, `KRX_PW`는 실행 환경에만 설정합니다. `--date YYYYMMDD --output-dir <저장폴더>`로 수집하고 원본을 위 Bronze 경로에 추가합니다. 수집 코드는 클라우드 리소스를 변경하지 않습니다. KRX API 키로 받는 일별 주가와는 별도의 업종 참고자료입니다.
