"""Keep the deployed app and service authentication, add the scenario router."""
from app import app
from conditional_api import make_router
from service_auth import create_app

app.include_router(make_router())
