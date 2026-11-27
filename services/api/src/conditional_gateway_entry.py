"""Extend the running gateway app without replacing its existing routes/auth."""
import os
from gateway import app
from conditional_gateway import install

if not any(getattr(route, 'path', None) == '/api/stress/scenario' for route in app.routes):
    install(app, os.environ.get('ML_API_URL', '').rstrip('/'))
