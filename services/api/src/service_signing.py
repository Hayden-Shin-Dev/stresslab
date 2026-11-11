"""2026-11-11 민철 추가: 관리 ID로 Key Vault에서만 서버 요청에 서명합니다."""
import base64
import hashlib
import json
import os
import time
import uuid

from azure.identity.aio import ManagedIdentityCredential


def encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


class ServiceSigner:
    def __init__(self, client, credential=None):
        self.client = client
        # 사용자 할당 토론 ID와 분리된 공통 API의 시스템 할당 ID입니다.
        self.credential = credential or ManagedIdentityCredential()
        self.key_id = os.environ["ML_SIGNING_KEY_ID"]
        self.issuer = os.environ["ML_SERVICE_ISSUER"]
        self.audience = "stresslab-ml-service"

    async def sign(self, method, path, body):
        now = int(time.time())
        header = {"alg": "RS256", "typ": "JWT", "kid": self.key_id}
        claims = {"iss": self.issuer, "sub": self.issuer, "aud": self.audience,
                  "iat": now, "nbf": now, "exp": now + 30, "jti": str(uuid.uuid4()),
                  "method": method, "path": path, "body_sha256": hashlib.sha256(body).hexdigest()}
        compact = lambda x: json.dumps(x, separators=(",", ":"), sort_keys=True).encode()
        message = encode(compact(header)) + "." + encode(compact(claims))
        token = await self.credential.get_token("https://vault.azure.net/.default")
        response = await self.client.post(self.key_id + "/sign?api-version=7.4",
            headers={"Authorization": "Bearer " + token.token},
            json={"alg": "RS256", "value": encode(hashlib.sha256(message.encode()).digest())})
        response.raise_for_status()
        return message + "." + response.json()["value"]

    async def close(self):
        await self.credential.close()
