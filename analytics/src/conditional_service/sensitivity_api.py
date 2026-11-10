"""Local sensitivity candidate endpoint; separate from existing API and production."""
import os
from functools import lru_cache
import joblib
from fastapi import FastAPI,HTTPException
from .api import Request
from .sensitivity_model import explain

app=FastAPI(title='StressLab sensitivity candidate',version='1.0')

@lru_cache(maxsize=1)
def bundle():return joblib.load(os.environ['STRESSLAB_SENSITIVITY_BUNDLE'])

@app.get('/model-info')
def info():
    b=bundle();return dict(version=b['version'],production_approved=False,audit=b['audit'])

@app.post('/analyze')
def analyze(r:Request):
    try:return explain(bundle(),[p.model_dump() for p in r.positions],r.shocks.model_dump())
    except (ValueError,OverflowError) as error:raise HTTPException(422,str(error)) from error
