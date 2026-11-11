# 2026-11-11 민철 추가: 토론 요청 코드를 재사용하는 공통 API 전용 이미지입니다.
FROM python:3.12-slim
WORKDIR /opt/stresslab
COPY services/debate/src/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/debate/src/ ./services/debate/src/
COPY services/api/src/ ./services/api/src/
WORKDIR /opt/stresslab/services/api/src
EXPOSE 8000
CMD ["uvicorn", "gateway:app", "--host", "0.0.0.0", "--port", "8000"]
