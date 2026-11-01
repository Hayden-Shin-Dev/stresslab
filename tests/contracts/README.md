# 계약 검사

`pip install -r tests/contracts/requirements.txt`로 검사 도구를 설치한 뒤 `python -m unittest discover -s tests/contracts -p "test_*.py"`로 실행합니다.

일별·실시간 예시가 스키마를 따르는지, 종목코드와 시각이 잘못된 값을 거절하는지 확인합니다. 이 테스트는 실제 데이터 적재나 ML 성능 검증이 아닙니다.
