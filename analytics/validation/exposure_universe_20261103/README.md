# 충격 민감도 기준 종목 선정 검증

206개 후보를 점검하고 학습 기간 기준을 통과한 6종목을 다시 학습했습니다. 기존 20종목과 추가 6종목 결과는 보존했습니다. Azure와 Gold 계약은 변경하지 않았습니다.

결론과 수치는 [결과.md](결과.md)에 있습니다.

| 파일 | 내용 |
| --- | --- |
| all_candidate_decisions.csv | 206개 종목의 선정 여부와 제외 이유 |
| selected_asset_shock_pairs.csv | 선정 종목과 충격별 방향, 학습 기간 근거 |
| per_asset_metrics.csv | 종목별 Ridge와 LightGBM 성능, 급락과 고변동성 결과 |
| matched_date_composition.csv | 동일 63개 평가 날짜의 기존 20종목 비교 |
| shock_added_comparison.csv | 같은 종목에서 네 충격을 추가한 효과 |
| selected_factor_ablation.csv | 선정 근거가 된 충격을 넣고 뺀 추가 진단 |
| direction_comparison.csv | 선정 때의 방향이 평가 기간에도 유지됐는지 |

평가 기간을 이전 연구에서도 사용했으므로 독립 블라인드 검증이 아닙니다. 실제 발생한 향후 충격을 사후 입력한 조건부 재구성 평가입니다. 정식 모델로 승인하지 않았습니다.

## 재실행

로컬 연구 묶음을 압축 해제하고 requirements.txt를 설치합니다. Python 3.10 환경에서 실행했습니다. `.env`를 Git에 올리지 않습니다. 원본 가격과 모델 파일은 공개 저장소에 포함하지 않았습니다.

```powershell
$env:STRESSLAB_AUDIT_ROOT = (Get-Location).Path
python scripts/select_exposure_universe.py
python scripts/evaluate_exposure_universe.py
python scripts/summarize_exposure_universe.py
python scripts/ablate_selected_exposures.py
python scripts/report_exposure_universe.py
```

수집까지 다시 할 때는 `collect_exposure_candidates.py`, 선정 후 추가 과거 수집은 같은 파일의 `--selected`를 사용합니다. API 키가 아니라 KRX 웹 원본 수집용 로그인 환경을 사용한 로컬 연구 코드입니다. 인증값은 출력하지 않습니다. 이미 완료된 기간 파일과 학습 체크포인트는 재사용합니다. 새로 학습하려면 다른 연구 폴더에 압축을 풀고 그 폴더의 `reports/exposure_universe_20261103/checkpoints`를 비워서 실행합니다. 운영 자료를 삭제하지 않습니다.

선정 기준은 selection_protocol.json, 평가 전 고정한 해시는 selection_frozen_before_evaluation.json에 있습니다. 모델 설정은 기존 비교 연구와 동일합니다. 종목 선정에는 2016~2021년만 사용했고, 결과를 보고 목록을 다시 고르지 않았습니다.
