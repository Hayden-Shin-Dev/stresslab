# 민철 2026-11-11 추가 (기존 로컬 Huber 계산을 유지해야 하기 때문에 B152 학습과 추론 함수를 그대로 옮겼음.)
"""Fixed-scale robust ridge response, with zero-anchored asymmetric factors.

Huber objective is sum rho(y-Xb) + .5*b'P*b; rho has threshold1.35.
These are central point forecasts, not estimated arithmetic expectations.
"""
import numpy as np
STATE = ['ret20_z', 'vol_ratio']
FACTORS = ['fx_pct', 'us_rate_bp', 'oil_usd', 'vix_points']

def design(frame, metadata):
    s=(frame[STATE].to_numpy(float)-metadata['center'])/metadata['state_sd']
    f=frame[FACTORS].to_numpy(float)/frame.scale.to_numpy()[:,None]/metadata['shock_sd']
    parts=[np.ones((len(frame),1)),s,f]
    if metadata['asymmetric']:parts.append(abs(f))
    return np.column_stack(parts)

def fit(frame, asymmetric=False, robust=True):
    s=frame[STATE].to_numpy(float);f=frame[FACTORS].to_numpy(float)/frame.scale.to_numpy()[:,None]
    ss=s.std(0);fs=f.std(0);ss[ss==0]=1;fs[fs==0]=1
    m=dict(center=s.mean(0).tolist(),state_sd=ss.tolist(),shock_sd=fs.tolist(),asymmetric=asymmetric,robust=robust,threshold=1.35)
    x=design(frame,m);y=100*np.log1p(frame.target.to_numpy()/100)/frame.scale.to_numpy()
    p=np.array([0.,100.,100.]+[10.]*4+([100.]*4 if asymmetric else []));pen=np.diag(p)
    beta=np.linalg.solve(x.T@x+pen,x.T@y)
    for it in range(500):
        residual=y-x@beta
        weights=np.minimum(1.,1.35/np.maximum(abs(residual),1e-15)) if robust else np.ones(len(y))
        new=np.linalg.solve(x.T@(weights[:,None]*x)+pen,x.T@(weights*y))
        if np.max(abs(new-beta))<1e-10:
            beta=new;break
        beta=new
    else:raise RuntimeError('IRLS did not converge')
    residual=y-x@beta;psi=np.clip(residual,-1.35,1.35) if robust else residual
    grad=-x.T@psi+p*beta
    if abs(grad).max()>1e-5:raise RuntimeError('IRLS gradient too large')
    m.update(coef=beta.tolist(),penalty=p.tolist(),iterations=it+1,max_gradient=float(abs(grad).max()))
    return m

def predict(frame,model):
    x=design(frame,model);b=np.array(model['coef']);total=x@b
    base=x[:,:3]@b[:3];scale=frame.scale.to_numpy()
    central=100*np.expm1(total*scale/100);baseline=100*np.expm1(base*scale/100)
    if not np.isfinite(central).all() or (central < -100).any():raise ValueError('Invalid central return')
    return dict(central_return=central,baseline_return=baseline,shock_response=central-baseline,location_z=total)
