"""Standalone app (separate Container App) — only needed if the router is not mounted into the
existing FastAPI service.   uvicorn regime_api.app:app --host 0.0.0.0 --port 8000"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .router import router

app = FastAPI(title="WHAT IF · Market Regime API", version="1.0.0",
              description="시장 국면 분석(HMM·KNN) 결과 조회. 과거 데이터 기반 시장 분석이며 투자 권유가 아닙니다.")
app.add_middleware(GZipMiddleware, minimum_size=1000)
origins = [o.strip() for o in os.environ.get("REGIME_CORS_ORIGINS", "").split(",") if o.strip()]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["*"],
                       expose_headers=["ETag"])
app.include_router(router)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
