# 별도 Container App으로 띄울 때만 사용. 기존 FastAPI에 router만 붙이는 경우 불필요.
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY regime_api ./regime_api
ENV REGIME_SOURCE=postgres \
    REGIME_CACHE_SECONDS=300 \
    REGIME_ALLOW_SYNTHETIC=false
EXPOSE 8000
CMD ["uvicorn", "regime_api.app:app", "--host", "0.0.0.0", "--port", "8000"]
