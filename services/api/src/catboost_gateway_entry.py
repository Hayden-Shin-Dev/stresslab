"""Keep the currently deployed scenario/news app and add pure CatBoost routes."""
from scenario_bridge_entry import app
from catboost_bridge import install
install(app)
