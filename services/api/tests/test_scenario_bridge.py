import asyncio
import copy
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from test_gateway import HEADERS, PRINCIPAL
from test_api import FakeQueue, FakeReader, FakeTokens
from api import Deps
import gateway
import scenario_bridge as bridge
import news_scenarios as news

BODY = dict(positions=[dict(asset_id="005930", value_krw=1000000)],
            shocks=dict(fx_pct=1.5, us_rate_bp=25, wti_pct=3, vix_points=4),
            horizon_trading_days=5, model=bridge.MODEL, analysis_type="market")


class ConditionalModel:
    async def close(self):
        pass

    async def call(self, url, *, payload=None, ml=False):
        assert url.endswith("/predict/scenario")
        predictions = []
        for row in payload["scenarios"]:
            ret = -row["shock_usdkrw_pct"]
            predictions.append(dict(asset_id=payload["asset_id"], horizon_days=row["horizon_days"],
                base_close=100000, predicted_close=100000*(1+ret/100), point_simple_return_pct=ret,
                lower_90_close=80000, lower_80_close=85000, upper_80_close=110000, upper_90_close=120000))
        return dict(asset_id=payload["asset_id"], model=bridge.MODEL, research_only=True,
            scenario_inputs_are_assumptions=True, production_approval="NOT_APPROVED", price_basis="adjusted",
            currency="KRW", horizon_unit="trading_days", snapshot_sha256="snapshot", model_package_id="package",
            as_of_trading_date="2026-11-24", dataset_version="v1", predictions=predictions,
            scenarios=copy.deepcopy(payload["scenarios"]))


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ML_API_URL", "https://ml.example")
    monkeypatch.setenv("GATEWAY_SHARED_KEY", "test-secret")
    monkeypatch.delenv("MARKET_STATE_URL", raising=False)
    q, reader = FakeQueue(), FakeReader()
    app = gateway.create_app(Deps(q,reader,FakeTokens()), ConditionalModel(), "test-secret")
    bridge.install(app)
    news.install(app)
    with TestClient(app) as client:
        yield client, app, reader, q


@pytest.mark.parametrize("horizon", [1,5,20])
def test_conditional_result_is_saved_as_same_debate_evidence(api, horizon):
    client, app, reader, queue = api
    response = client.post("/api/stress/scenario/analyze", headers=HEADERS, json=dict(BODY,horizon_trading_days=horizon))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["horizon_trading_days"] == horizon
    assert result["assets"][0]["scenario_return_pct"] == -1.5
    assert result["ai_handoff"]["ready"] is True
    assert reader.runs[result["analysis_id"]]["result"] == result["ai_context"]["stress_run"]
    debate = client.post("/api/debates",headers=HEADERS,json=dict(run_id=result["analysis_id"]))
    assert debate.status_code == 202
    assert queue.sent[-1][2]["run_id"] == result["analysis_id"]
    saved=bridge.read_receipt(result["recovery_receipt"], "aad:gateway-test", "test-secret")
    assert saved["result"]["assets"] == result["assets"]


def test_news_reruns_original_model_and_passes_its_own_saved_evidence(api, monkeypatch):
    client,app,reader,_=api
    async def sources(cutoff):
        return [dict(id="https://news.example/1",url="https://publisher.example/1",title="환율",
                     excerpt="원/달러 환율이 1.5% 상승했다.")], cutoff
    class Reading:
        async def complete(self,*args):
            return dict(changes=[dict(variable="fx_pct",delta=1.5,source_id="https://news.example/1",
                                    quote="원/달러 환율이 1.5% 상승했다.",already_in_input=False)],explanation="환율 변화를 확인했습니다.")
    monkeypatch.setattr(news,"today_articles",sources)
    app.state.news_reader=Reading()
    result=client.post("/api/stress/scenario/analyze",headers=HEADERS,json=BODY).json()
    url="/api/stress/analyses/"+result["analysis_id"]+"/news-scenarios"
    body=dict(receipt=result["recovery_receipt"],prices={"005930":100000})
    response=client.post(url,headers=HEADERS,json=body)
    assert response.status_code==200,response.text
    adjusted=response.json()
    assert adjusted["assets"][0]["scenarios"]["baseline"]["return_pct"]==-3
    assert adjusted["analysis_id"]==result["analysis_id"]
    assert adjusted["news_analysis_id"]!=result["analysis_id"]
    assert adjusted["ai_handoff"]["ready"] is True
    assert reader.runs[adjusted["news_analysis_id"]]["result"]["shocks"]["shock_fx"]==3
    assert client.post(url,headers=HEADERS,json=body).json()==adjusted
    assert client.post(url,headers=HEADERS,json=dict(body,receipt=body["receipt"]+"x")).status_code==422
    assert client.post(url.replace(result["analysis_id"],"a-other"),headers=HEADERS,json=body).status_code==409


def test_numbers_without_matching_original_text_cannot_change_prices():
    reading=news.NewsReading(changes=[dict(variable="fx_pct",delta=7,source_id="a",quote="원/달러 환율 7% 상승",already_in_input=False)],
                            explanation="가정")
    original=dict(fx_pct=0,us_rate_bp=0,wti_pct=0,vix_points=0)
    assert news.verified_changes(reading,[dict(id="a",excerpt="원/달러 환율 1% 상승")],original)==(original,None)
