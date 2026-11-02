FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY ingestion/kiwoom/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY ingestion/kiwoom/collector.py ./
COPY ingestion/kiwoom/sessions.py ./
COPY ingestion/kiwoom/universe.json ./
COPY contracts/realtime/schema.json ./
USER 10001
CMD ["python", "collector.py"]
