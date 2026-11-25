import importlib.util
import sys
import types
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient


def test_entry_preserves_existing_routes_auth_and_does_not_duplicate(monkeypatch):
    source = Path(__file__).resolve().parents[1] / 'src'
    monkeypatch.syspath_prepend(str(source))
    app = FastAPI()

    @app.middleware('http')
    async def existing_auth(request: Request, call_next):
        if request.headers.get('x-test-auth') != 'valid':
            return JSONResponse({'detail':'original auth'},status_code=401)
        return await call_next(request)

    @app.get('/original')
    def original():
        return {'version':'existing'}

    monkeypatch.setitem(sys.modules, 'gateway', types.SimpleNamespace(app=app))
    for _ in range(2):
        spec=importlib.util.spec_from_file_location('tested_conditional_entry',source/'conditional_gateway_entry.py')
        entry=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        assert entry.app is app
    paths=[getattr(route,'path',None) for route in app.routes]
    assert paths.count('/api/stress/scenario') == 1
    with TestClient(app) as client:
        assert client.get('/original',headers={'x-test-auth':'valid'}).json()=={'version':'existing'}
        assert client.get('/api/stress/scenario/support').status_code==401
