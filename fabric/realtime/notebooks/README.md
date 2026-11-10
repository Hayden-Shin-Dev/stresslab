# Notebooks

장 마감 후 그날의 체결 원문, 분봉, 시장 상태 스냅샷을 검사해 batch 담당이 읽는 Bronze에 게시합니다(마감 인계). 검증되지 않은 집계값을 확정 일별 종가로 표시하지 않습니다.

| 파일 | 내용 |
| --- | --- |
| [close_handoff.py](close_handoff.py) | KQL 쿼리, 검사·계산, 게시, batch용 읽기 함수 |
| [close_handoff_notebook.py](close_handoff_notebook.py) | Fabric 노트북 `nb_realtime_close_handoff`에 붙여 넣을 셀 |
| [test_close_handoff.py](test_close_handoff.py) | 합성 자료로 계산·게시·읽기 검증 (`python -m pytest fabric/realtime/notebooks -q`) |

## 게시 위치와 형식 (lh_whatif, `Files/bronze` 기준)

수집 담당의 KRX·ECOS·FRED 배치와 같은 방식입니다. `SUCCESS.json`을 마지막에 쓰므로, 이 파일이 있는 배치만 읽으면 됩니다.

| 경로 | 내용 |
| --- | --- |
| `realtime/close/<batch_id>/assets.json` | 종목별 마감 행 (`rows` 배열) |
| `realtime/close/<batch_id>/market.json` | 스냅샷 저장 현황과 전체 요약 (`market` 객체) |
| `_runs/<batch_id>/SUCCESS.json` | manifest: status, trade_date, requested/partial/missing_assets, files(sha256) |

- `batch_id` = `realtime_close_<YYYYMMDD>_<생성 시각 HHMMSS KST>`. 같은 거래일을 다시 실행하면 새 batch_id가 생기고, **같은 거래일의 가장 늦은 batch_id**를 사용합니다(`latest_batch_id`).
- `status`: 가격 자료(분봉) 기준. `complete`(모든 종목 380분봉), `partial`(일부 종목 누락), `no_market_observations`(체결·분봉 없음, 휴장일 가능). 시장 상태 스냅샷 누락은 `market.json`의 `snapshots_status`, `snapshots_missing_kst`로 따로 봅니다.
- `date_inferred_events`는 대부분 체결 수와 같습니다. 키움 실시간 체결은 시각만 주고 날짜는 수집기가 붙이기 때문이며 정상입니다.

### assets.json 종목 행

| 필드 | 뜻 |
| --- | --- |
| status | complete / partial / missing (분봉 기준) |
| bars_expected, bars_observed, bars_missing, missing_minutes_kst | 09:00~15:19 시작 분봉 380개 기준. 체결 없는 분과 수집 누락은 구분하지 못함 |
| bars_revised | 늦게 온 체결로 다시 만든 분봉 수 (bars_1m 정정 이력) |
| events, duplicate_events | 정규장 시간대 체결 원문 수, event_id 중복 수 |
| non_regular_events, date_inferred_events, no_event_time_events, late_events | 세션 미확인·날짜 추정·공급자 시각 없음·60초 넘게 늦은 수신 |
| first_event_time, last_event_time | 공급자 체결 시각 (UTC) |
| first_bar_open, high, low, last_bar_close, last_bar_at | 분봉 기반 장중 값. **last_bar_close는 종가 단일가 이전 가격이며 확정 종가가 아님** |
| continuous_volume, last_cumulative_volume | 분봉 거래량 합, 마지막 누적 거래량. 확정 거래량 아님 |
| price_basis, is_official_close | `raw_unadjusted`, `false` 고정 |

## batch에서 읽는 법

```python
from close_handoff import latest_batch_id, read_realtime_close

bronze = "/lakehouse/default/Files/bronze"
bid = latest_batch_id(bronze, trade_date)          # 없으면 None
manifest, assets, market = read_realtime_close(bronze, bid)   # 체크섬 검증 포함
```

KRX 일별 원본과 대조해 차이를 기록하는 용도입니다. 이 값으로 Gold의 종가·거래량을 채우지 않습니다.

## Fabric 적용 (2026-11-04 적용 완료)

1. 노트북 `nb_realtime_close_handoff` (PySpark), 기본 레이크하우스 `lh_whatif`. 셀 1은 매개 변수 셀(`trade_date`, `kusto_uri`, `kusto_database`, `bronze`), 셀 2는 `close_handoff.py` 전체, 셀 3은 `close_handoff_notebook.py`의 실행 부분(`ch.` 없이). 저장소의 `close_handoff.py`를 고치면 셀 2도 같이 바꿉니다.
2. 파이프라인 `pl_realtime_close`: 노트북 활동 하나. `trade_date`는 비워 둡니다(오늘 KST).
3. 일정: 평일 16:10 KST (`pl_realtime_session`의 마지막 분봉 저장 15:21 이후 여유). 주말·체결 없는 날은 노트북이 건너뜁니다.

## 실행 기록

| 거래일 | 결과 | 비고 |
| --- | --- | --- |
| 2026-11-04 | partial (종목 18 완전, 2 일부) | 000660 12:03, 402340 12:33 분봉 없음. 원문 체결도 없음(각 147~148초 공백, VI로 추정). 스냅샷 380/380, 중복·정정 0 |
