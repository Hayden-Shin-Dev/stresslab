# Notebooks

전달받은 원본을 Bronze에 보존하고 종목, 거래일, 단위, 가격 기준을 통일해 Silver로 정리합니다. Realtime 마감 자료를 대조한 뒤 품질 검사를 통과한 데이터로 gold_stress_daily를 생성합니다.

Realtime에 전달할 종목·업종 정보와 전일 확정 종가도 준비합니다. 미래 정답과 ML 피처 생성은 ML 담당 작업입니다.
