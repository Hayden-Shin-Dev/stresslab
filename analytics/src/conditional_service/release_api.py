"""Local selected-universe API. Does not replace a deployed service."""
import os
from functools import lru_cache
import joblib
from fastapi import FastAPI,HTTPException
from .api import Request
from .service_release import analyze_release

app=FastAPI(title='StressLab selected sensitivity service',version='1.0')

@lru_cache(maxsize=1)
def bundle():return joblib.load(os.environ['STRESSLAB_RELEASE_BUNDLE'])

@app.get('/support')
def support():
    b=bundle();return dict(version=b['support_version'],supported_shocks_by_asset=b['support'],selection_reasons=b['selection_reasons'],production_approved=False)

@app.get('/model-info')
def info():
    b=bundle();return dict(version=b['version'],coefficient_policy='global_partial_pool_only',audit=b['audit'],production_approved=False)

@app.post('/analyze')
def analyze(r:Request):
    try:return analyze_release(bundle(),[p.model_dump() for p in r.positions],r.shocks.model_dump())
    except (ValueError,OverflowError) as error:raise HTTPException(422,str(error)) from error
