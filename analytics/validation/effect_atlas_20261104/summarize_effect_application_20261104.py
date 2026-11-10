import pandas as pd,numpy as np,json
from analyze_effect_atlas_20261104 import OUT

def main():
    r=pd.read_parquet(OUT/'application_predictions.parquet');z=r[r.method=='baseline'].merge(r[r.method=='response_atlas_guided'],on=['asset','date'],suffixes=('_old','_new'),validate='one_to_one');months=pd.period_range(z.date.min(),z.date.max(),freq='M');rng=np.random.default_rng(20261104);n=len(months)
    draws=np.array([np.concatenate([(s+np.arange(3))%n for s in rng.integers(0,n,size=(n+2)//3)])[:n] for _ in range(2000)]);rows=[]
    for metric in ['mae_change','direction_change']:
        q=z if metric=='mae_change' else z[z.actual_new.ne(0)]
        delta=(q.actual_new-q.center_new).abs()-(q.actual_old-q.center_old).abs() if metric=='mae_change' else (q.actual_new*q.center_new>0).astype(float)-(q.actual_old*q.center_old>0).astype(float)
        block=q.date.dt.to_period('M');s=delta.groupby(block).sum().reindex(months,fill_value=0).to_numpy();count=q.groupby(block).size().reindex(months,fill_value=0).to_numpy();b=s[draws].sum(1)/count[draws].sum(1);lo,hi=np.quantile(b,[.025,.975]);rows.append(dict(metric=metric,change=float(delta.mean()),ci_low=float(lo),ci_high=float(hi)))
    pd.DataFrame(rows).to_csv(OUT/'application_uncertainty.csv',index=False)
    lines=['','## 적용 후 판단','',
        '분석 결과로 종목당 평균 약 13개 입력과 파생 상호작용을 사용했습니다. 입력 선택은 2022년 이전 관계와 관측 비교 기준으로 고정했습니다.',
        '중심 오차는 4.524%p에서 4.517%p, 방향 일치율은 57.28%에서 57.32%로 바뀌었습니다. 큰 성능 개선으로 해석할 수 없습니다. 급락 포착 수는 88건에서 74건, 급락 오경보는 135건에서 107건으로 함께 줄었습니다. 급락을 더 잘 잡았다고 보고하지 않습니다.',
        '관측 반응과 적용 범위를 설명하는 자료는 확보했지만, 분석 방법이 정교해졌다는 이유로 목표 성능을 달성했다고 판단하지 않습니다. 이번 모델을 운영으로 승격시키지 않습니다.','',
        '| 변화 | 추정값 | 95% 시간 블록 구간 |','|---|---:|---:|']
    for v in rows:lines.append(f'| {v["metric"]} | {v["change"]:+.6f} | {v["ci_low"]:+.6f} ~ {v["ci_high"]:+.6f} |')
    lines+=['','방향 변화는 비율 단위입니다. 같은 날짜의 모든 종목을 유지한 3개월 시간 블록 재표본추출이며, 재사용한 연구 평가 구간의 탐색 결과입니다.']
    path=OUT/'README.md';text=path.read_text(encoding='utf8');text=text.split('\n## 적용 후 판단')[0];path.write_text(text+'\n'.join(lines)+'\n',encoding='utf8')
if __name__=='__main__':main()
