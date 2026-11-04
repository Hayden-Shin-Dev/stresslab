"""Design diagnostic: no returns or evaluation performance used to choose calipers."""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from .core import features,STATE,ASSET,SHOCKS,anchors

def run(gold,out):
    d=features(pd.read_parquet(gold)).dropna(subset=SHOCKS+['target','end_date']);rows=[]
    cols=STATE+ASSET+SHOCKS
    for year in [2023,2024,2025,2026]:
        tr=d[d.end_date<pd.Timestamp(year-1,1,1)-pd.Timedelta(days=20)]
        h=anchors(tr);iqr=(tr[cols].quantile(.75)-tr[cols].quantile(.25)).replace(0,1);mid=tr[cols].median()
        # One prespecified first available snapshot per asset and year, not selected by returns.
        q=d[d.date.dt.year.eq(year)].sort_values('date').groupby('asset').head(1)
        for _,r in q.iterrows():
            z=h[h.asset.eq(r.asset)]
            if len(z)<40:continue
            a=((z[cols]-mid)/iqr).to_numpy();v=((r[cols]-mid)/iqr).to_numpy(dtype=float)
            dist=((a[:,:len(STATE)]-v[:len(STATE)])**2).mean(1)
            for n in [120,360]:
                ids=np.argsort(dist,kind='stable')[:n];x=a[ids]
                for shock in SHOCKS:
                    s=cols.index(shock);c=[i for i in range(len(cols)) if i!=s];others=[cols.index(k) for k in SHOCKS if k!=shock]
                    dc=((x[:,None,c]-x[None,:,c])**2).mean(2)**.5
                    ds=abs(x[:,s,None]-x[None,:,s]);other=abs(x[:,None,others]-x[None,:,others]).max(2)
                    for caliper in [.5,.75,1.]:
                        ii,jj=np.where(np.triu((dc<=caliper)&(other<=caliper)&(ds>=.5),1));order=np.argsort(dc[ii,jj],kind='stable');used=set();sel=[]
                        for k in order:
                            i,j=int(ii[k]),int(jj[k])
                            if i not in used and j not in used:used.update([i,j]);sel.append((i,j))
                        rows.append(dict(year=year,asset=r.asset,shock=shock,candidates=len(ids),caliper_iqr=caliper,pairs=len(sel),median_A_distance=float(np.median(dist[ids])),mean_pair_control_distance=float(np.mean([dc[i,j] for i,j in sel])) if sel else None,mean_other_shock_gap_iqr=float(np.mean([other[i,j] for i,j in sel])) if sel else None))
    out=Path(out);out.mkdir(parents=True,exist_ok=True);r=pd.DataFrame(rows);r.to_csv(out/'support_sweep.csv',index=False)
    r.groupby(['candidates','caliper_iqr']).agg(comparisons=('pairs','size'),median_pairs=('pairs','median'),fraction_15_pairs=('pairs',lambda x:(x>=15).mean()),control_distance=('mean_pair_control_distance','mean'),other_shock_gap=('mean_other_shock_gap_iqr','mean')).to_csv(out/'support_sweep_summary.csv')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--gold',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.gold,a.out)
