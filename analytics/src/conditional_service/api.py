import os
from functools import lru_cache
import joblib
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .core import analyze
from .service_contract import AnalysisResponse

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
    from .final_service import bundle as frozen_bundle
    return frozen_bundle()

@app.get('/model-info')
def info():
    from .final_service import model_info
    return model_info()

@app.get('/support')
def support():
    from .final_service import support as final_support
    return final_support()

@app.post('/analyze',response_model=AnalysisResponse)
def post(r:Request):
    from .final_service import post as final_post
    return final_post(r)
