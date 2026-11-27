"""Extend the deployed app while retaining all existing routes and middleware."""
from conditional_gateway_entry import app
from scenario_bridge import install
from news_scenarios import install as install_news

install(app)
install_news(app)
