# 빌드 컨텍스트는 저장소 루트입니다 (contracts/realtime/schema.json 포함).
FROM python:3.11-slim
WORKDIR /app
COPY services/market-state/src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/market-state/src/ ./
COPY contracts/realtime/schema.json ./schema.json
ENV SCHEMA_PATH=/app/schema.json
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
