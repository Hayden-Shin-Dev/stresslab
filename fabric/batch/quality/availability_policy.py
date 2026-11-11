"""공표 확인과 신선도를 분리한 로컬/Fabric 공통 규칙입니다."""
# 2026-11-09 14:18 KST 민철 추가 — 관측일부터 10일을 세던 규칙을 공표 근거 기준으로 변경합니다.
import pandas as pd

POLICY_VERSION = 'publication-cadence-v2-20261109'
# 운영 허용값이며 공급자가 보장한 공표 시각이 아닙니다. 성능 결과로 튜닝하지 않습니다.
# 주간 환율은 공표 근거 후 2주, 나머지는 기존 허용 기간 10일을 공표 근거부터 셉니다.
# 기존에 통과한 최근 관측을 새 규칙 때문에 더 엄격하게 제외하지 않습니다.
PUBLICATION_GAP_DAYS = {'usdkrw':14, 'us_treasury_10y':10, 'wti':10, 'vix':10, 'korea_3y':10}
# 오래된 값을 오늘 다시 다운로드했다고 최신으로 인정하지 않습니다.
OBSERVATION_GAP_DAYS = {'usdkrw':21, 'us_treasury_10y':14, 'wti':14, 'vix':14, 'korea_3y':14}

def evidence_status(source, observation_date, known_by, day):
    day = pd.Timestamp(day).normalize()
    observed = pd.to_datetime(observation_date, errors='coerce')
    known = pd.to_datetime(known_by, utc=True, errors='coerce')
    cutoff = day.tz_localize('Asia/Seoul') + pd.Timedelta(hours=15, minutes=30)
    if pd.isna(observed) or pd.isna(known): return 'no_evidence'
    if observed > day or known > cutoff: return 'future_information'
    if (day-observed).days > OBSERVATION_GAP_DAYS[source]: return 'observation_gap'
    if cutoff-known > pd.Timedelta(days=PUBLICATION_GAP_DAYS[source]): return 'publication_gap'
    return 'usable'

def validate_provenance(p):
    for r in p[p.verified].itertuples():
        if evidence_status(r.source,r.observation_date,r.known_by,r.date) != 'usable':
            raise ValueError('공표 근거/신선도 검증 실패: '+r.source+' '+str(r.date))
    return True
