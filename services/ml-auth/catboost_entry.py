"""Extend existing conditional app and retain its signed service middleware."""
import json,os
from conditional_entry import app
from catboost_api import make_router,install_existing_routes
from service_auth import ServiceAuth

app.include_router(make_router())
install_existing_routes(app)

def create_app():
    return ServiceAuth(app,json.loads(os.environ['ML_SERVICE_PUBLIC_KEYS']),os.environ['ML_SERVICE_ISSUER'])
