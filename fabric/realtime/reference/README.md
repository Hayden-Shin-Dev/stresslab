# 계산 참조

realtime_market_state.py의 analyze_market에 완료된 분봉과 기준시각, 관측 종목 목록을 전달합니다. 분봉 열은 asset_id, bar_at, price, volume이며 실제 시가는 open에 넣습니다. bar_at은 시간대가 있는 분 시작시각입니다.

전일 종가, 업종 코드, 같은 시각의 과거 기준값은 별도 인자입니다. 없는 값은 추정해서 채우지 않습니다. same_clock_baselines는 기준일 이전의 완전한 세션만 사용합니다. daily_state_date는 일별 담당이 전달한 확정 기준일입니다.

반환값은 market_state_snapshot v2입니다. numpy와 pandas가 필요합니다. Fabric 구현 시 이 산식과 결측 처리 기준을 맞추세요. 현재 Python 계산 참조이며 Fabric 배포 코드는 아닙니다.
