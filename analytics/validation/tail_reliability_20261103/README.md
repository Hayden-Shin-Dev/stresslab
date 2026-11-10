# 하방 위험 구간 진단과 수정

선정 6종목과 같은 918개 평가 표본을 유지했습니다. 중심값과 잔차 구간을 분리해 원인을 확인하고, 구간 산정 방법을 비교했습니다. Azure, Gold 계약, 운영 모델은 변경하지 않았습니다.

[결과.md](결과.md)에 판단과 실제 수치가 있습니다.

| 파일 | 내용 |
| --- | --- |
| center_interval_decomposition.csv | 중심값 변경과 잔차 변경의 영향 분리 |
| aggregate.csv / per_asset.csv | 전체 및 종목별 성능 |
| block_uncertainty.csv | 같은 날짜의 종목을 함께 재표본추출한 비교 |
| failure_cases.csv | 수정 후에도 놓친 실제 급락 |
| scenario_examples.json | 실제 모델과 일별 상태를 사용한 30개 가상 입력 예제 |
| service_decision.json | 유지할 계산, 미채택 방법, 남은 문제 |

하방 참고선은 보수적인 모델 위험 표시입니다. 검증된 80% 확률구간, VaR, 최대 손실로 표시하지 않습니다. 평가 기간을 이미 여러 연구에서 사용했으므로 독립 블라인드 테스트가 아닙니다.

## 재현

로컬 연구 묶음을 압축 해제한 폴더에서 requirements.txt를 설치한 뒤 실행합니다. 원본 자료와 모델은 공개 GitHub에 올리지 않았습니다.

```powershell
$env:STRESSLAB_AUDIT_ROOT = (Get-Location).Path
python scripts/tail_reliability_research.py
python scripts/tail_guard_diagnostic.py
python scripts/summarize_tail_reliability.py
python scripts/tail_scenario_examples.py
python scripts/report_tail_reliability.py
python scripts/verify_tail_reliability.py
```

완료된 종목의 체크포인트는 재사용합니다. 코드를 변경해 다시 학습할 때는 별도 작업 폴더를 사용하고 해당 복사본의 `reports/tail_reliability_20261103/*_checkpoint.parquet`를 제외한 상태에서 실행합니다. 원래 연구 결과를 덮어쓰지 않습니다.

온라인 잔차는 정답 종료 후 20일이 지난 자료만 사용합니다. 시나리오 예제의 보유금액 100만 원은 설명용이며 실제 계좌 자료가 아닙니다. 모델 내부 입력 변화에 따른 기여도를 금융 충격의 인과효과라고 해석하지 않습니다.
