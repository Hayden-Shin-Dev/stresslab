# 2026-11-11 민철 추가: 배포된 모델/의존성은 고정하고 인증 래퍼만 추가합니다.
FROM acrwhatifdev5dt.azurecr.io/stresslab-api@sha256:7432b3cb19b1e9e86905ad1081d7306df5954b769719f60173a86a92d3121d3f
RUN pip install --no-cache-dir --no-deps PyJWT==2.10.1
COPY service_auth.py /opt/stresslab/service_auth.py
CMD ["python", "-m", "uvicorn", "service_auth:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
