# 공표 근거 자동 수집

2026-11-10 민철 수정. 기존 수집 Notebook에서 Key Vault의 `fred-api-key`를 읽어 공표 근거도 수집합니다. 키, 리소스, 실행 일정, Gold 34컬럼은 변경하지 않습니다.

## 자동 처리

1. `nb_ingest_official20`이 기존 KRX·ECOS·FRED 데이터와 함께 FRED 공개 이력, 한국은행 공표 원문, 연준 공개 알림, EIA·Cboe 원본을 수집합니다.
2. 최근 45일을 다시 확인합니다. 실패하면 마지막 정상 수집일 이전까지 조회 범위를 확장하여 다음 실행에서 재시도합니다.
3. Silver가 원문 해시와 관측일, 값을 확인해 `Files/silver_evidence/official_publication_events.parquet`에 근거를 정리합니다.
4. Gold가 같은 관측일과 값의 근거를 연결합니다. 공표 이전 행이나 다른 정정 버전의 근거를 사용하지 않습니다.

## 시간 필드

| 항목 | 처리 |
| --- | --- |
| 환율 observed_at | DEXKOUS의 공식 정의인 뉴욕 정오를 UTC로 변환합니다. 서머타임을 반영합니다. 공개 시각은 아닙니다. |
| available_at | 관측값과 연결되는 공식 공개 알림의 시각만 입력합니다. |
| 한국 3년 금리 available_at | 한국은행 RSS의 pubDate를 게시글 번호, 등록일, 원문 금리값과 대조해 연결합니다. 해당 게시글 공개 시각이며, 다른 기관을 포함한 최초 공개 시각을 뜻하지 않습니다. |
| 날짜만 있는 공표 근거 | 별도 근거 파일의 known_by에 보존합니다. 정확한 시각 칸에는 넣지 않습니다. |
| FRED last_updated | 지표 전체의 갱신 시각입니다. 모든 과거 관측의 공표 시각으로 복사하지 않습니다. |
| 나머지 미확인 시각 | NULL을 유지합니다. 예정 시각, 자정, 수집 시각으로 대체하지 않습니다. |

원문은 `Files/bronze/fred/publication/<실행번호>/`와 `Files/bronze/ecos/publication/<실행번호>/`에 있습니다. 실행 상태와 해시는 `Files/bronze/_publication/latest.json`을 확인하세요. 과거 근거 ZIP은 검증용 원문 보관이며, 담당자가 압축을 풀어 처리할 필요는 없습니다.

수집 상태 `complete`는 원천 조회가 완료됐다는 뜻입니다. 모든 관측의 정확한 시각을 확보했다는 뜻은 아닙니다. 원문에 시각이 없는 관측은 여전히 NULL입니다.

Gold 스냅샷의 `provenance.parquet`에서 `timing_status`를 확인하세요. `official_availability_after_cutoff`는 확보한 공개 근거의 시각 또는 날짜 상한이 기준 시점 이후라는 뜻입니다. 다른 기관에서 더 일찍 공개됐을 가능성까지 부정하는 값은 아닙니다. 공개 근거가 추가됐다고 ML의 `historical_availability_verified`를 일괄 True로 변경하면 안 됩니다.

과거 한국은행 RSS는 2000년부터 월별로 조회했습니다. 기존 금리 원문 3,724건을 게시글 시각과 연결했습니다. 이후 자동 수집에서도 월별 날짜 필터를 사용하며, RSS 100건 제한에 걸리거나 요청 범위 밖 자료가 반환되면 성공 처리하지 않습니다.

이번 변경은 수집과 시각 근거 연결입니다. 기존 Gold 숫자, 시장 피처 계산, ML Notebook의 승인 규칙은 변경하지 않습니다. 당시 이미 공개된 더 오래된 관측을 선택하는 문제와 정확한 발표 시각의 확보는 구분해야 합니다.

검증: `python -m unittest discover -s fabric/batch/quality -p test_publication_evidence.py`

공식 정의: [연준 H.10](https://www.federalreserve.gov/releases/h10/About.HTM), [FRED 시리즈 API](https://fred.stlouisfed.org/docs/api/fred/series.html). 일반 공표 일정만으로 실제 시각을 채우지 않습니다.
