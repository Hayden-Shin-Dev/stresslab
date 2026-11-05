# 빌드 컨텍스트는 저장소 루트입니다.
#   docker build -f services/debate/Dockerfile -t debate .
FROM python:3.12-slim
WORKDIR /app
COPY services/debate/src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/debate/src/ ./src/
COPY services/debate/prompts/ ./prompts/
# stress-engine 구현 전 개발용 결과 파일 (STRESS_ENGINE_URL이 없을 때 사용)
COPY services/debate/runs/ ./runs/
ENV STRESS_RUN_DIR=/app/runs
WORKDIR /app/src
# 기본 실행: 토론 실행기(ingress 없음, Service Bus 세션 큐를 받아 처리).
# 같은 이미지로 토론 요청 API(ca-debateapi-whatif-dev)를 띄울 때는 명령을 바꿉니다:
#   command: uvicorn   args: api:app --host 0.0.0.0 --port 8000
EXPOSE 8000
CMD ["python", "worker.py"]
