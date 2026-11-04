import os
from functools import lru_cache
import joblib
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .core import analyze

app=FastAPI(title='StressLab Gold conditional analysis',version='2.0')

class Position(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    asset_id:str
    value_krw:float=Field(gt=0)

class Shocks(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    fx_pct:float=Field(default=0,gt=-100)
    us_rate_bp:float=0
    wti_pct:float=Field(default=0,gt=-100)
    vix_points:float=0

class Request(BaseModel):
    model_config=ConfigDict(extra='forbid')
    positions:list[Position]=Field(min_length=1,max_length=200)
    shocks:Shocks=Field(default_factory=Shocks)

@lru_cache(maxsize=1)
def bundle():
    # Load only an internally produced trusted artifact. Never accept an upload path.
    return joblib.load(os.environ['STRESSLAB_BUNDLE'])

@app.get('/model-info')
def info():
    b=bundle();return {'version':b['version'],'production_approved':False,'audit':b['audit']}

@app.post('/analyze')
def post(r:Request):
    try:return analyze(bundle(),[p.model_dump() for p in r.positions],r.shocks.model_dump())
    except (ValueError,OverflowError) as e:raise HTTPException(422,str(e)) from e
