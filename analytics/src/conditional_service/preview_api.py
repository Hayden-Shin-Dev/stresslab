"""Local UI over the frozen Ridge API. No training or cloud mutations."""
import json
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from .api import app as model_api
from .final_service import model_info

ROOT=Path(__file__).parent/'preview'
app=FastAPI(title='StressLab local preview')

@app.get('/')
def home():return FileResponse(ROOT/'index.html')

@app.get('/preview-info')
def preview_info():
    info=model_info()
    validation=json.loads((ROOT/'validation.json').read_text(encoding='utf8'))
    if info['artifact']['sha256']!=validation['artifact_sha256']:
        return {'validation':None,'message':'현재 모델과 성능 자료의 버전이 다릅니다.'}
    return {'validation':validation}

app.mount('/api',model_api)
