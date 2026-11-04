"""Partial pooling, temporal cross-fit residuals, and joint support diagnostics."""
import json
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.neighbors import NearestNeighbors
from gold_quantile_benchmark import ROOT, FEATURES, STATE, EXTRA, SHOCKS, build

OUT=ROOT/'reports/pooled_hybrid_20261104'
SEED=20261104
SECTORS={'000270':'auto','005380':'auto','012330':'auto','000660':'semiconductor','005930':'semiconductor','005935':'semiconductor','009150':'electronics','006400':'battery','373220':'battery','055550':'bank','086790':'bank','105560':'bank','032830':'insurance','012450':'industrial','034020':'industrial','028260':'holding','034730':'holding','402340':'holding','068270':'biopharma','207940':'biopharma'}
ASSETS=sorted(SECTORS)
INTER=[s+'__'+c for s in SHOCKS for c in ['market_trend20','market_vol20']]
FACTORS=FEATURES+INTER
SUPPORT=STATE+SHOCKS
HAR=['rv1','rv5','rv22']

def prepare():
    g=pd.read_parquet(ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet')
    dates=pd.DatetimeIndex(sorted(pd.to_datetime(g.trading_date).unique()));extra=[]
    for a,z in g.groupby('asset_id'):
        z=z.copy();z.index=pd.to_datetime(z.trading_date);z=z.reindex(dates)
        rr=(z.close.pct_change(fill_method=None)*100).pow(2)
        h=pd.DataFrame({'asset':a,'date':dates,'oil_valid':z.wti.gt(0)&z.wti.shift(-5).gt(0),
            'rv1':np.log(rr.clip(lower=.01)),'rv5':np.log(rr.rolling(5).mean().clip(lower=.01)),
            'rv22':np.log(rr.rolling(22).mean().clip(lower=.01)),
            'future_log_rv5':np.log(rr.rolling(5).sum().shift(-5).clip(lower=.01))})
        extra.append(h.reset_index(drop=True))
    d=build(g);d=d[d.asset!='portfolio'].merge(pd.concat(extra),on=['asset','date'],validate='one_to_one')
    for s in SHOCKS:
        for c in ['market_trend20','market_vol20']:d[s+'__'+c]=d[s]*d[c]
    d['sector']=d.asset.map(SECTORS)
    assert len(d)==100871 and d[HAR].notna().all().all()
    return d.sort_values(['date','asset']).reset_index(drop=True),g

def weights(d):
    w=1/d.groupby('date').date.transform('size').to_numpy()
    return w/w.mean()

class PartialRidge:
    def __init__(self,alpha=300,ratio=10):self.alpha=alpha;self.ratio=ratio
    def design(self,d,fit=False):
        if fit:self.scaler=StandardScaler().fit(d[FACTORS])
        z=self.scaler.transform(d[FACTORS]);ids=np.array([ASSETS.index(a) for a in d.asset]);one=np.eye(len(ASSETS))[ids]
        shocks=z[:,[FACTORS.index(s) for s in SHOCKS]]
        return np.column_stack([z,one/np.sqrt(self.ratio),(one[:,:,None]*shocks[:,None,:]).reshape(len(d),-1)/np.sqrt(self.ratio)])
    def fit(self,d):
        self.model=Ridge(alpha=self.alpha).fit(self.design(d,True),d.target/d.scale,sample_weight=weights(d));return self
    def predict(self,d):return self.model.predict(self.design(d))
    def slopes(self,d):
        b=self.predict(d);rows=[]
        for s in SHOCKS:
            x=d.copy();x[s]+=1
            for c in ['market_trend20','market_vol20']:x[s+'__'+c]=x[s]*x[c]
            for i,a in enumerate(d.asset):rows.append(dict(asset=a,shock=s,slope_pp_per_unit=float((self.predict(x)[i]-b[i])*d.scale.iloc[i])))
        return rows

def fit_factor(d,origin):
    cut=pd.Timestamp(origin,1,1)-pd.Timedelta(days=20)
    tr=d[(d.end_date<cut)&d.oil_valid].copy()
    # One strictly earlier calendar year for internal tuning; no outer calibration/test targets.
    vstart=pd.Timestamp(origin-1,1,1)
    inner=tr[tr.end_date<vstart-pd.Timedelta(days=20)]
    val=tr[tr.date>=vstart]
    anchors=sorted(val.date.unique())[::6];val=val[val.date.isin(anchors)]
    trials=[]
    for alpha,ratio in [(300,10),(300,100),(3000,10),(3000,100)]:
        m=PartialRidge(alpha,ratio).fit(inner)
        loss=float(np.average(abs(val.target-m.predict(val)*val.scale),weights=weights(val)))
        trials.append(dict(origin=origin,alpha=alpha,ratio=ratio,mae=loss,inner_end=str(inner.end_date.max()),validation_start=str(val.date.min()),validation_label_end=str(val.end_date.max())))
    best=min(trials,key=lambda v:v['mae']);m=PartialRidge(best['alpha'],best['ratio']).fit(tr)
    assert inner.end_date.max()<val.date.min() and tr.end_date.max()<pd.Timestamp(origin,1,1)
    return m,tr,trials

class JointSupport:
    def fit(self,tr):
        h=tr.sort_values('date').drop_duplicates('date').iloc[::6]
        self.mid=h[SUPPORT].median();self.scale=(h[SUPPORT].quantile(.75)-h[SUPPORT].quantile(.25)).replace(0,1)
        self.nn=NearestNeighbors(n_neighbors=min(20,len(h)),n_jobs=2).fit((h[SUPPORT]-self.mid)/self.scale)
        ds,ix=self.nn.kneighbors((h[SUPPORT]-self.mid)/self.scale)
        dates=h.date.to_numpy();valid=[]
        for i in range(len(h)):
            far=ds[i][abs((dates[ix[i]]-dates[i])/np.timedelta64(1,'D'))>20]
            if len(far):valid.append(float(np.mean(far[:3])))
        self.threshold=float(np.quantile(valid,.95));self.bounds={s:(float(h[s].min()),float(h[s].max())) for s in SHOCKS}
        return self
    def inspect(self,x):
        ds,_=self.nn.kneighbors((x[SUPPORT]-self.mid)/self.scale,n_neighbors=3)
        ratio=ds.mean(axis=1)/max(self.threshold,1e-6)
        # Continuous taper. At joint-distance >=2x threshold residual correction is zero.
        gate=np.clip(2-ratio,0,1)
        outside=np.array([any(not self.bounds[s][0]<=v[s]<=self.bounds[s][1] for s in SHOCKS) for _,v in x.iterrows()])
        return gate,ratio,outside

def chronological_anchors(d):
    parts=[]
    for a,f in d.groupby('asset'):
        keep=[];last=pd.Timestamp.min
        for i,row in f.sort_values('date').iterrows():
            if row.date>last:keep.append(i);last=row.end_date
        parts.append(d.loc[keep])
    return pd.concat(parts).sort_values(['date','asset'])

def point_score(z):
    y=z.actual.to_numpy();p=z.center.to_numpy();nz=y!=0;cr=y<=-5
    ym=y-y.mean();within=z[['date','actual','center']].copy()
    if 'market_removed_actual' in z:
        within['actual']=z.market_removed_actual;within['center']=z.market_removed_center
    else:within[['actual','center']]-=within.groupby('date')[['actual','center']].transform('mean')
    good=within.actual.ne(0);multi=z.asset.nunique()>1 or 'market_removed_actual' in z
    return dict(n=len(z),dates=z.date.nunique(),stocks=z.asset.nunique(),mae=float(abs(y-p).mean()),zero_mae=float(abs(y).mean()),mae_gain_zero=1-float(abs(y-p).sum()/abs(y).sum()),r2=1-float(((y-p)**2).sum()/(ym**2).sum()),direction=float((np.sign(y[nz])==np.sign(p[nz])).mean()),demeaned_direction=float((np.sign(within.loc[good,'actual'])==np.sign(within.loc[good,'center'])).mean()) if multi else np.nan,demeaned_corr=float(within.actual.corr(within.center)) if multi else np.nan,crash_n=int(cr.sum()),crash_mae=float(abs(y[cr]-p[cr]).mean()) if cr.any() else np.nan,crash_center_mean=float(p[cr].mean()) if cr.any() else np.nan,crash_caught=int((p[cr]<=-5).sum()),false_crash=int(((p<=-5)&~cr).sum()))

def interval_score(z):
    y=z.actual;lo=z.lo;hi=z.hi;cr=y<=-5
    pb=(np.maximum(.1*(y-lo),-.9*(y-lo))+np.maximum(.9*(y-hi),-.1*(y-hi)))/2
    return dict(n=len(z),coverage80=float(((y>=lo)&(y<=hi)).mean()),width80=float((hi-lo).mean()),interval_score80=float((hi-lo+10*(lo-y).clip(lower=0)+10*(y-hi).clip(lower=0)).mean()),pinball_mean=float(pb.mean()),lower_breach=float((y<lo).mean()),crash_lower_breach=float((y[cr]<lo[cr]).mean()),crash_shortfall=float((lo[cr]-y[cr]).clip(lower=0).mean()))
