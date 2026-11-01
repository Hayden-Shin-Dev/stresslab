# 분석과 ML

분석 담당의 작업 폴더입니다. Fabric Gold를 입력으로 받아 과거 시장 검색과 사건 재현을 구현합니다. 순수 계산 코드는 src에 두고 서비스 계층이 가져다 사용합니다. Fabric Data Science에서 실행할 실험은 notebooks에 둡니다. 연구 결과는 검증 후에만 정식 계산에 반영합니다. 기존 조건부 Ridge는 비교 기준으로 유지하며, 실시간 상태와 과거 사례 연결 방식은 별도로 검증합니다. Historical Replay가 ML을 대체하는 구조로 확정된 것은 아닙니다.

| 폴더 | 내용 |
| --- | --- |
| [src](src/) | 시장 상태 비교, 사건 검색, 공동 수익률 적용, 손익 기여도 계산 |
| [notebooks](notebooks/) | Fabric Data Science 실험, MLflow 기록, 후보 모델 학습 |
| [evaluation](evaluation/) | 시간 순서 검증, 사건 제외 분석, 검색 안정성, 계산 정확성 평가 |
| [tests](tests/) | 분석 로직 단위 테스트 |
