import hashlib
import json
import sys
import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from service_auth import ServiceAuth

PRIVATE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(PRIVATE.public_key()))
ISSUER = "stresslab-common-api:test-principal"
BODY = b'{"asset_id":"005930"}'


def token(path="/service/predict/auto", body=BODY, **extra):
    now = int(time.time())
    claims = {"iss": ISSUER, "sub": ISSUER, "aud": "stresslab-ml-service", "iat": now,
        "nbf": now, "exp": now + 30, "jti": "test", "method": "POST", "path": path,
        "body_sha256": hashlib.sha256(body).hexdigest(), **extra}
    return jwt.encode(claims, PRIVATE, algorithm="RS256", headers={"kid": "test-key"})


@pytest.fixture
def client():
    original = FastAPI()
    @original.post("/predict/auto")
    async def predict(request: Request):
        assert "x-stresslab-service-token" not in request.headers
        return await request.json()
    return TestClient(ServiceAuth(original, {"test-key": PUBLIC}, ISSUER))


def test_valid_request_reaches_original_model(client):
    r = client.post("/service/predict/auto", content=BODY, headers={"x-stresslab-service-token": token()})
    assert r.status_code == 200 and r.json()["asset_id"] == "005930"


@pytest.mark.parametrize("change", [{"exp": 1}, {"aud": "wrong"}, {"iss": "wrong"},
    {"sub": "wrong"}, {"method": "GET"}, {"exp": int(time.time())+3600},
    {"body_sha256": "0"*64}, {"nbf": int(time.time())+60}])
def test_invalid_claims_rejected(client, change):
    assert client.post("/service/predict/auto", content=BODY,
        headers={"x-stresslab-service-token": token(**change)}).status_code == 401


def test_unsigned_wrong_route_and_tampering_rejected(client):
    assert client.post("/service/predict/auto", content=BODY).status_code == 401
    assert client.post("/service/admin", content=BODY).status_code == 404
    assert client.post("/service/predict/auto?x=1", content=BODY).status_code == 404
    assert client.post("/service/predict/auto", content=b'{}',
        headers={"x-stresslab-service-token": token()}).status_code == 401
    assert client.post("/service/predict/auto", content=BODY,
        headers={"x-stresslab-service-token": "invalid"}).status_code == 401


def test_different_private_key_rejected(client):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    claims = jwt.decode(token(), options={"verify_signature": False})
    forged = jwt.encode(claims, other, algorithm="RS256", headers={"kid": "test-key"})
    assert client.post("/service/predict/auto", content=BODY,
        headers={"x-stresslab-service-token": forged}).status_code == 401
