# 공표 이력과 수정주가 확인

## 확인 결과

KRX 647개 기간 요청을 모두 완료했습니다. 지원 50종목의 일별 수익률 303,875쌍과 기준가격 변경 96건을 대조했고, 정한 반올림 허용 오차를 벗어난 차이와 유효 날짜 누락은 없었습니다. 가격 연결 검증은 통과했습니다.

고정 모델 API의 850개 종목·시나리오 계산도 통과했습니다. 모델 파일, Gold와 Azure는 변경하지 않았습니다. 공표 이력 문제 때문에 운영 배포는 계속 차단 상태입니다.

## 확보한 자료

KRX에서 지원 50종목의 수정 전 가격과 전일 대비 가격 차이를 기간별로 요청했습니다. Gold 수정주가의 일별 수익률을 KRX 기준가격 대비 수익률과 대조합니다. 성공 건수와 불일치는 `service_evidence/corporate_adjustment_audit.json`에서 확인하세요.

환율, 미국 10년 금리, WTI, VIX는 FRED의 과거 빈티지 이력을 받았습니다. 관측일과 공개 날짜는 다릅니다. 날짜만 있는 이력에는 정확한 공표 시각을 채우지 않았습니다. 시간대가 명시되지 않은 빈티지는 해당 날짜가 모든 시간대에서 끝난 뒤를 사용 가능 경계로 잡았습니다. 이는 보수적인 날짜 기준이며 실제 공개 시각을 알아냈다는 뜻은 아닙니다.

한국은행의 2026-10-29 금융시장 자료에서 10월 28일 국내 3년물 금리 3.799%를 확인했습니다. 이 자료 하나로 ECOS 전체 과거 이력을 검증했다고 판단하지 않습니다.

## 무엇을 처리했는가

공표 근거가 있고 기준 시각 이전에 확인되는 이전 관측값을 선택하도록 구현했습니다. 근거가 없으면 NULL로 남깁니다. 수신 시각을 과거 공표 시각으로 대체하지 않습니다.

기존 Gold와 다른 값은 별도 수정안에 저장했습니다. 로컬 `reports/service_certification_20261104/verified_macro_history_proposal.parquet`입니다. 기존 Gold와 모델 파일은 변경하지 않았습니다.

수정주가 검사는 분할이나 권리락 등에 따른 기준가격 변경이 수익률에 비정상적으로 섞이는지 확인합니다. 모든 기업행사의 명칭과 공시 내역을 복원한 검사나 배당 포함 총수익률 검사는 아닙니다. 현재 서비스의 가격 수익률 기준으로 해석하세요.

## 아직 필요한 처리

기존 학습에 사용한 거시 값 중 당시 이용 가능했다고 확인되지 않는 값이 있습니다. ALFRED의 초기 빈티지 이전 자료는 증거 부족이며, 그 자체로 미래 정보 유입이 입증된 것은 아닙니다. 최초 빈티지는 실제 최초 공표일과 다를 수도 있습니다.

ECOS는 과거 값별 공표 자료와 수정 이력이 추가로 필요합니다. 날짜가 명시된 한국은행 원문과 값을 대조하거나, 해당 관측을 사용하지 않는 방식으로 처리해야 합니다. 근거 없는 일괄 하루 지연으로 해결됐다고 표시하지 않습니다.

확인된 이전 값으로 학습 입력을 정정하면 고정 모델을 만들 때 사용한 입력과 달라집니다. 모델을 그대로 유지하면서 학습 시점 검증까지 완료됐다고 승인할 수는 없습니다. 현재 지시대로 재학습은 하지 않았습니다. 이후에는 모델 종류나 설정을 바꾸는 실험이 아니라, 정정된 입력으로 동일 모델을 다시 생성하고 기존 계산과 검증을 재실행하는 절차가 필요합니다. 또는 기존 입력의 당시 공표 근거를 추가 확보해야 합니다.

## 재실행

연구 폴더에서 `PYTHONPATH`를 팀 저장소의 `analytics/src`로 지정한 뒤 실행합니다.

```powershell
python -m conditional_service.collect_certification_evidence --macro
python -m conditional_service.collect_bok_dated_evidence
python -m conditional_service.collect_raw_price_evidence --all
python -m conditional_service.audit_publication_vintages
python -m conditional_service.prepare_verified_macro_history
python -m conditional_service.audit_corporate_adjustments
python -m conditional_service.package_source_certification
python -m conditional_service.verify_final_integration
```

수집기는 승인된 로컬 인증정보를 사용하고 비밀값을 출력하지 않습니다. 원본은 로컬 `data/research/service_certification_20261104`, 검증 결과는 `reports/service_certification_20261104`에 있습니다. 저장소에는 코드와 요약 증거만 올립니다.

공식 설명: [FRED 관측 이력 API](https://fred.stlouisfed.org/docs/api/fred/series_observations.html), [ALFRED 빈티지 날짜의 의미](https://alfred.stlouisfed.org/help), [한국은행 확인 자료](https://www.bok.or.kr/portal/bbs/P0002018/view.do?menuNo=200366&nttId=11066066).
