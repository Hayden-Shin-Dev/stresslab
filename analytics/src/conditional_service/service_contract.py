"""Service response contract; financial rates are percentages, changes are pp."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict

class AssetResult(BaseModel):
    model_config=ConfigDict(extra='allow',allow_inf_nan=False)
    asset_id:str
    name:str
    holding_krw:float
    analysis_class:Literal['exploratory']
    sensitivities:dict[str,dict[str,Any]]
    baseline_model_return_pct:float
    scenario_return_pct:float
    change_from_baseline_pp:float
    contributions_pp:dict[str,float]
    hypothetical_pnl_krw:float
    baseline_pnl_krw:float
    shock_incremental_pnl_krw:float
    shock_contribution_pnl_krw:dict[str,float]
    historical_examples:list[dict[str,Any]]
    model_version:str
    warnings:list[str]

class AnalysisResponse(BaseModel):
    model_config=ConfigDict(extra='allow',allow_inf_nan=False)
    api_version:Literal['1.0']
    model_artifact_sha256:str
    state_date:str
    horizon_trading_days:Literal[5]
    shocks:dict[str,float]
    assets:list[AssetResult]
    market_candidates:list[str]
    data_status:dict[str,Any]
    analysis_flow:dict[str,Any]
    portfolio_hypothetical_pnl_krw:float
    portfolio_baseline_pnl_krw:float
    portfolio_shock_incremental_pnl_krw:float
    portfolio_analysis_class:Literal['exploratory']
    production_approved:Literal[False]
    publication_verified:Literal[False]
