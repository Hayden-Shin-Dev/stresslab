# 공표 이력과 수정주가 확인

2026-11-05에 공식 자료 확인과 동일 설정 모델 재생성을 완료했습니다. Azure, Gold, 기존 운영 모델은 변경하지 않았습니다.

## 처리 결과

| 항목 | 결과 |
| --- | --- |
| ECOS 공표 근거 | 한국은행 원문 2,783건 중 관측일과 ECOS 값이 일치하는 2,753건을 사용했습니다. |
| 제외 자료 | 값 불일치 27건, 관측일 확인 불가 1건, 미래 관측일 또는 허용 시차 초과 2건입니다. |
| 수정주가 | 학습 68종목의 수익률 연결 392,012건과 기준가격 변경 125건을 대조했습니다. 불일치는 없습니다. |
| 코스피 | 공식 원본과 6,611개 날짜가 일치합니다. |
| API | 50종목의 무충격, 15개 충격 조합, 극단 충격까지 850개 계산을 통과했습니다. |

수정주가 검증은 KRX 기준가격 대비 가격 수익률의 연결을 확인합니다. 모든 기업행사 명칭을 복원하거나 배당 포함 총수익률을 검증한 것은 아닙니다.

## 공표 시각 처리

모델 기준은 확정 일별 상태의 한국 시간 15:30입니다. 한국은행 자료는 등록일 다음 날 00:00 이후에 사용합니다. FRED는 시간대가 없는 빈티지 날짜가 모든 시간대에서 끝난 뒤를 사용 가능 경계로 잡습니다. `known_by`는 이 보수적인 경계이며 정확한 공개 시각이 아닙니다. `available_at`은 NULL을 유지합니다.

기준 시각에 이미 확인된 관측 중 가장 최근 값을 선택합니다. 관측일이 10일보다 오래됐거나 근거가 없으면 제외합니다. 결측을 0으로 바꾸지 않습니다. 한국은행 원문 등록일도 본문과 대조했습니다.

5거래일 충격 계산식은 유지했습니다. 양 끝의 거시 값만 당시 확인 가능했던 값으로 바뀝니다. 미국 관측일과 한국 장 마감 시각이 같다고 가정하지 않습니다. 실제 시작·종료 관측일은 `shock_observation_windows.parquet`에 기록합니다.

이 조건으로 남은 학습 자료는 2014-04-17부터 68종목 103,578개 행입니다. 이전 자료가 틀렸다는 뜻은 아닙니다. 당시 공표 근거를 확인하지 못한 관측을 이번 재생성에서 제외했습니다.

## 모델 검증과 배포 판단

Ridge 설정, 두 학습 집단, 지원 50종목, 네 충격, 정규화 강도와 안정성 검사 기준을 유지했습니다. 새로운 알고리즘이나 튜닝은 없습니다. 2023~2026년은 이미 연구에 사용한 기간이므로 독립 블라인드 검증이 아닙니다.

| 85개 날짜, 4,150개 종목 관측 | 중심 수익률 MAE |
| --- | --- |
| 정정 모델 | 4.787%p |
| 0 수익률 기준선 | 4.621%p |
| 기존 설정의 업종 충격 기준선 | 4.615%p |

기존 평가와 날짜·종목이 겹치는 835개 관측에서는 기존 4.462%p, 재생성 4.883%p입니다. 제외된 데이터 때문에 평가 표본이 달라져 전체 평균끼리 개선율을 계산하지 않습니다.

공표 근거 누락과 가격 연결의 데이터 차단은 정정 버전에서 해소했습니다. 다만 기준선 대비 MAE 허용 범위 3%를 통과하지 못해 기존 모델을 대체하거나 서비스 승인으로 표시하지 않습니다. 추가 실험은 중단하고 로컬 검토용으로 보존합니다.

API는 확인된 과거 상태를 사용합니다. 최신 시장 상태가 아닙니다. 민감도, 기여도 합계와 가상 손익 계산은 통과했지만 미래 수익률이나 손실 한도를 보장하지 않습니다.

## 재현과 결과 위치

연구 폴더에서 팀 저장소 `analytics/src`를 `PYTHONPATH`로 지정하세요. 고정 설정은 `service_evidence/pit_rebuild/locked_protocol.json`입니다. 이를 연구 폴더의 `reports/pit_rebuild_20261105/locked_protocol.json`에 두고 실행합니다.

```powershell
python -m conditional_service.collect_bok_history
python -m conditional_service.collect_raw_price_evidence --all --manifest reports/pit_rebuild_20261105/locked_protocol.json --status-file reports/pit_rebuild_20261105/raw_collection_status.json
python -m conditional_service.audit_corporate_adjustments --manifest reports/pit_rebuild_20261105/locked_protocol.json --status-file reports/pit_rebuild_20261105/raw_collection_status.json --out reports/pit_rebuild_20261105
python -m conditional_service.prepare_pit_rebuild
python -m conditional_service.rebuild_fixed_model
python -m conditional_service.verify_pit_rebuild
```

기존 공식 Gold와 FRED 빈티지 원본이 필요한 재현 절차입니다. 새 PC에서 이 명령만으로 모든 원천 자료가 만들어지는 것은 아닙니다. 인증정보는 출력하지 않습니다.

원본은 `data/research/pit_rebuild_20261105/bok`와 `data/research/service_certification_20261104`에 있습니다. 정정 데이터, 새 모델, 제외 목록과 평가 결과는 `reports/pit_rebuild_20261105`입니다. 저장소에는 코드와 `service_evidence/pit_rebuild`의 검증 요약을 제공합니다.

공식 자료: [FRED 관측 이력 API](https://fred.stlouisfed.org/docs/api/fred/series_observations.html), [ALFRED 날짜 설명](https://alfred.stlouisfed.org/help), [한국은행 금융시장 자료](https://www.bok.or.kr/portal/singl/newsData/list.do?menuNo=201150).
