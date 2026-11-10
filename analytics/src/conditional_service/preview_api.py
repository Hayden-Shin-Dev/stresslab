"""Local UI over the selected sector Ridge API. No training or cloud mutations."""
import json
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from .selected_web_service import app as model_api, model_info, bundle

ROOT=Path(__file__).parent/'preview'
app=FastAPI(title='StressLab local preview')

@app.get('/')
def home():return FileResponse(ROOT/'index.html')

@app.get('/preview-info')
def preview_info():
    info=model_info()
    _, selection=bundle()
    validation=dict(selection['comparison'][selection['selected_model']],
        zero_mae_pp=selection['comparison']['zero']['mae_pp'],
        artifact_sha256=selection['artifact_sha256'])
    return {'validation':validation,'selection':selection}

app.mount('/api',model_api)
