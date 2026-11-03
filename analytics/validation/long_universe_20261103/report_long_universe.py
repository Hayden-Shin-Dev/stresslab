"""Report every selected pair and all failures, without post-test reselection."""
import json
import numpy as np
import pandas as pd
from select_long_universe import OUT
def metric(z):
    nz=z[z.actual.ne(0)];cr=z.actual<=-5;ra=z.actual>=5;cp=z.center<=-5;rp=z.center>=5
    return dict(n=len(z),direction_n=len(nz),direction_accuracy=(np.sign(nz.actual)==np.sign(nz.center)).mean(),mae=(z.actual-z.center).abs().mean(),fixed5_coverage=((z.actual-z.center).abs()<=2.5).mean(),crash_n=int(cr.sum()),crash_caught=int((cr&cp).sum()),crash_false=int((cp&~cr).sum()),rally_n=int(ra.sum()),rally_caught=int((ra&rp).sum()),rally_false=int((rp&~ra).sum()))
def main():
    status=json.loads((OUT/'training_progress.json').read_text());assert status['status']=='complete', 'Do not claim all trained if any failed'
    r=pd.read_parquet(OUT/'predictions.parquet');pairs=pd.read_csv(OUT/'eligible_pairs.csv',dtype={'asset':str});rows=[];group=[]
    for (asset,method),z in r.groupby(['asset','method']):
        group.append(dict(asset=asset,method=method,**metric(z)))
    for _,a in pairs.iterrows():
        for method,z in r[r.asset.eq(a.asset)].groupby('method'):
            z=z[z[a.shock+'_event']];rows.append(dict(asset=a.asset,name=a['name'],shock=a.shock,method=method,**metric(z)))
    pd.DataFrame(group).to_csv(OUT/'asset_metrics.csv',index=False);p=pd.DataFrame(rows);p.to_csv(OUT/'pair_metrics.csv',index=False)
    out=[]
    for method,z in r[r.selected].groupby('method'):out.append(dict(method=method,scope='all_selected',**metric(z)))
    pd.DataFrame(out).to_csv(OUT/'aggregate.csv',index=False)
    a=p[p.method.eq('all4_lgb')];b=p[p.method.eq('state_lgb')];c=a.merge(b,on=['asset','shock'],suffixes=('_shock','_state'),validate='one_to_one');c['direction_gain']=c.direction_accuracy_shock-c.direction_accuracy_state;c['mae_gain']=c.mae_state-c.mae_shock;c.to_csv(OUT/'paired_added_value.csv',index=False)
    s=pd.DataFrame(out);lines=['# 장기 이력 기반 종목 선정 및 학습','',f'2000년부터 확보 가능한 이력을 수집했습니다. 이후 상장 종목은 실제 관측 시작일부터 사용했습니다. 2021년까지의 정보만으로 {pairs.asset.nunique()}종목, {len(pairs)}개 종목·충격 조합을 선정했습니다. 평가 성적에 따른 재선정은 하지 않았습니다.','',
    '방향 판단은 조건부 반응의 설명력을 평가하는 보조 지표입니다. 실제 이후 5거래일 충격을 사후 입력했으며 충격의 발생 예측이나 인과효과 검증은 아닙니다. 2023~2026년은 기존 연구에서 재사용한 평가 기간이므로 독립 블라인드가 아닙니다.','',
    '| 모델 | 관측 수 | 방향 일치 | 중심 MAE | 5%p 폭 진단 포함률 |','|---|---:|---:|---:|---:|']
    for _,v in s.iterrows():lines.append(f'| {v.method} | {v.n} | {v.direction_accuracy:.1%} | {v.mae:.2f}%p | {v.fixed5_coverage:.1%} |')
    lines+=['','101종목이라는 이전 탐색 목록은 최종 선정으로 사용하지 않았습니다. 긴 이력에서 최소 6개 검증 연도, 80개 충격 표본, 방향 일치 60%, 상태 모델 대비 3%p 개선, 연도별 개선 비율 60%, 계수 부호 일관성 80%를 동시에 요구했습니다. 상위 몇 개를 억지로 채우는 규칙은 없습니다.','',
    'asset_metrics.csv는 종목별 결과, pair_metrics.csv는 종목·충격별 결과, paired_added_value.csv는 같은 표본에서 충격 추가의 개선 여부입니다. 실패 종목과 조합도 모두 포함합니다. 개별 조합의 높은 성적만 골라 전체 성능이라고 보고하지 않습니다.','',
    'source_quality.csv와 data_quality.csv에는 가격 수익률 불일치, 거래정지 및 거래량 0, 누락과 격리 현황이 기록됩니다. 유효한 가격과 거래량이 연속 6개 거래일에 존재할 때만 5거래일 정답을 만듭니다. 정상적인 대규모 등락이라는 이유만으로 제거하지 않습니다. 학습에는 정답 종료 후 20일이 지난 표본만 넣습니다. WTI 0 이하 관측을 포함한 변화율 구간은 학습에서 제외합니다.','',
    '분기 재학습과 동일 파라미터를 적용했습니다. 표본과 정답이 같은지 자동 확인했습니다. 분류 모델의 대표 손익과 직접 수익률 회귀를 구분합니다. 분류 점수는 검증된 미래 확률이 아니며 5%p 구간은 진단일 뿐 승인된 위험구간이 아닙니다.','',
    '현재 목록 기준 생존 편향, 공표 시각 및 수정 이력 미확인, 업종 및 기업 공시 피처 부재는 남습니다. 오래된 자료가 많아졌다고 현재 충격 관계가 안정적이라고 자동 판단하지 않습니다. Azure, 운영 모델과 Gold 계약을 변경하거나 모델을 자동 승인하지 않습니다.']
    (OUT/'결과.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
if __name__=='__main__':main()
