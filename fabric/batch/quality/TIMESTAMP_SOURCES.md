# 관측일과 공개 시점 근거

2026-11-10 민철 확인입니다. Gold 34컬럼은 유지합니다. 아래 날짜 기준은 실제 공개 시각과 구분합니다.

| 출처 | 확보한 정보 | 아직 확인되지 않은 정보 | 적용 방법 |
|---|---|---|---|
| KRX 주가·코스피 | 거래일, API 원문, 수집 기록, 정규장 가격 기준 | 과거 각 값의 최초 API 공개 시각과 당시 수정 버전 전체 | 종가 시각이나 수집 시각을 최초 공개 시각으로 넣지 않습니다. 가격 시점 검증은 거시 검증과 별도로 남깁니다. |
| FRED·ALFRED | 관측일, 빈티지별 값, `realtime_start/end`, 수정 이력 | 대부분의 개별 값에 대한 시·분·초 공개 시각 | 빈티지 날짜에 보수적인 지연을 적용한 `known_by`와 버전 유효기간으로 선택합니다. 정확한 `available_at`에는 넣지 않습니다. |
| 연준 H.10 환율 | 뉴욕 정오 관측 정의, 날짜별 환율 표, 일부 공개 알림 시각 | 모든 과거 날짜의 공개 알림 | 날짜·값·공식 알림이 연결된 경우만 공개 시각을 기록합니다. 관측 정오는 서머타임을 반영합니다. |
| 한국은행 국고채 3년 | 일일 금융시장 주요지표 문서의 관측일·값, 게시일, 일부 RSS 공개 시각 | 초기 과거 자료와 모든 문서의 정확한 최초 공개 시각 | 문서와 값이 일치하는 공식 게시 근거를 사용합니다. 날짜만 있으면 보수적 기준으로 구분합니다. |

한국은행 자료는 현재 사용하는 `korea_3y`를 확인했습니다. 기준금리 결정 시각이나 월간 예금·대출금리 공표 일정을 국고채 일별 수익률에 대신 적용하지 않습니다.

## 혼동하면 안 되는 기준

`observed_at`은 값을 관측한 시각이고 `available_at`은 공식 공개 알림으로 확인한 시각입니다. 예정된 발표 시각, API 요청 시각, 파일 생성 시각은 서로 다릅니다. 공식 알림 시각도 모든 기관을 통틀어 최초로 공개된 순간을 증명하는 것은 아닙니다.

FRED의 발표 일정은 FRED·ALFRED에 실제 값이 올라온 날짜와 다를 수 있습니다. 따라서 일정만으로 승인하지 않고 빈티지의 값과 기간을 확인합니다. `last_updated` 하나를 전체 관측값에 복사하지 않습니다.

KRX 정규장 종료 시각은 API 게시 시각이 아닙니다. 현재의 15:30을 2000년 이후 모든 거래일에 일괄 적용하지 않습니다. 거래시간 변경과 특별 개장일도 있습니다. 확인한 공식 서비스 안내에서 해당 API의 각 과거 값이 언제 게시됐는지는 확보하지 못했습니다. 검색에서 보이는 다른 제공기관의 갱신 일정을 KRX API에 적용하지 않았습니다.

## 자동 처리

기존 Bronze 수집은 공식 빈티지와 문서를 보관하고 Silver는 값별 근거를 연결합니다. Gold는 분석 기준시각 전에 이용 가능했던 값만 선택합니다. 정확한 시각을 모르면 NULL을 유지하고 날짜 근거는 `provenance.parquet`에 보존합니다. 근거가 없거나 허용 기간보다 오래된 값은 입력 제외로 표시합니다.

FRED 빈티지 날짜 +36시간(UTC 날짜 기준)은 기존 로컬의 보수적 상한 정책이며 공식 공개 시각이 아닙니다. 이후 빈티지가 존재하면 이전 버전의 유효기간도 검사합니다. 이 규칙과 Gold 선택 코드는 [Gold 시점 근거 연결](GOLD_AVAILABILITY.md)에 있습니다.

ML Notebook이나 `historical_availability_verified`는 변경하지 않았습니다. 이번 거시 입력 검증을 가격 수정 이력과 모델 전체 승인으로 확대 해석하면 안 됩니다.

## 공식 자료

- [KRX API 서비스 목록](https://openapi.krx.co.kr/contents/OPP/INFO/service/OPPINFO004.cmd)
- [KRX 유가증권 일별매매정보](https://openapi.krx.co.kr/contents/OPP/USES/service/OPPUSES002_S2.cmd?BO_ID=JvJFzlAENzZlPBDNGAWC)
- [KRX 정규장 가격 기준](https://data.krx.co.kr/contents/MDC/STAT/issue/MDCSTAT213.jsp)
- [KRX 특별 거래시간 변경 사례](https://www.krx.co.kr/2017_suneung_ko.pdf)
- [FRED 빈티지 날짜](https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html)
- [FRED 관측값과 실시간 기간](https://fred.stlouisfed.org/docs/api/fred/series_observations.html)
- [FRED 발표 일정의 주의사항](https://fred.stlouisfed.org/docs/api/fred/release_dates.html)
- [연준 H.10 관측 정의](https://www.federalreserve.gov/releases/h10/About.HTM)
- [한국은행 일일 금융시장 주요지표](https://www.bok.or.kr/portal/bbs/P0002018/list.do?menuNo=200366)
- [한국은행 공식 RSS](https://www.bok.or.kr/portal/bbs/P0002018/news.rss?menuNo=200366)
