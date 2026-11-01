# 과거 데이터와 일별 처리

Fabric 담당 1의 작업 폴더입니다. 수집 코드는 ingestion에서 가져오고, 이곳에서는 실행 순서와 정제 로직을 관리합니다. 원본은 Bronze, 정제 자료는 Silver, 분석용 테이블은 Gold에 저장합니다. 실제 데이터는 OneLake와 Lakehouse에 두며 저장소에는 처리 코드만 올립니다.

| 폴더 | 내용 |
| --- | --- |
| [pipelines](pipelines/) | Fabric Data Factory 파이프라인 정의와 실행 순서 |
| [notebooks](notebooks/) | 일별 시세, 거시 지표, 공시 정제 및 Gold 생성 |
| [quality](quality/) | 결측, 중복, 수정주가, 종목 구성 이력, 발표 시각 검사 |
