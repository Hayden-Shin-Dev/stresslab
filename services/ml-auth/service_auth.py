"""2026-11-11 민철 추가: 기존 ML/모델은 보존하고 서버 전용 3개 경로만 검증합니다.

원래 경로는 기존 Entra 인증을 계속 사용합니다. /service 경로는 아래 검증을
통과해야만 원래 예측 함수에 전달됩니다. 개인키와 Key Vault 접근권한은 없습니다.
"""
import hashlib
import hmac
import json
import os

import jwt
from starlette.responses import JSONResponse

ROUTES = {("GET", "/service/metadata"): "/metadata",
          ("GET", "/service/snapshot/metadata"): "/snapshot/metadata",
          ("POST", "/service/predict/auto"): "/predict/auto"}


class ServiceAuth:
    def __init__(self, original, keys, issuer):
        if not keys or not issuer:
            raise RuntimeError("ML service verification configuration is required")
        self.original = original
        self.keys = {k: jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(v)) for k, v in keys.items()}
        self.issuer = issuer

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/service"):
            return await self.original(scope, receive, send)
        target = ROUTES.get((scope["method"], scope["path"]))
        async def reject(status):
            await JSONResponse({"detail": "Service request rejected"}, status_code=status)(scope, receive, send)
        if not target or scope.get("query_string"):
            return await reject(404)
        headers = dict(scope["headers"])
        token = headers.get(b"x-stresslab-service-token", b"").decode("ascii", errors="ignore")
        if not token or len(token) > 8192:
            return await reject(401)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 32768:
                return await reject(413)
            if not message.get("more_body"):
                break
        try:
            header = jwt.get_unverified_header(token)
            key = self.keys.get(header.get("kid"))
            if key is None:
                return await reject(401)
            claims = jwt.decode(token, key, algorithms=["RS256"], issuer=self.issuer,
                audience="stresslab-ml-service", leeway=2,
                options={"require": ["iss", "sub", "aud", "iat", "nbf", "exp", "jti", "method", "path", "body_sha256"]})
            if (claims["sub"] != self.issuer or claims["exp"] - claims["iat"] > 30
                or claims["method"] != scope["method"] or claims["path"] != scope["path"]
                or not hmac.compare_digest(claims["body_sha256"], hashlib.sha256(body).hexdigest())):
                return await reject(401)
        except (jwt.PyJWTError, TypeError, ValueError, KeyError):
            return await reject(401)
        # 임의 프록시가 아닙니다. 서명된 3개 읽기/계산 요청만 원래 ASGI 앱으로 전달합니다.
        sent = False
        async def replay_body():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()
        forwarded = {**scope, "path": target, "raw_path": target.encode(),
                     "headers": [(k, v) for k, v in scope["headers"] if k != b"x-stresslab-service-token"]}
        await self.original(forwarded, replay_body, send)


def create_app():
    from app import app as original
    return ServiceAuth(original, json.loads(os.environ["ML_SERVICE_PUBLIC_KEYS"]), os.environ["ML_SERVICE_ISSUER"])
