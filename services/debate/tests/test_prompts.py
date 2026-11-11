"""프롬프트 파일이 출력 스키마·근거 묶음과 어긋나지 않는지 확인합니다."""
import json
from pathlib import Path

import contracts as c
import evidence
from llm import Prompts

FIX = Path(__file__).parent / "fixtures"


def test_each_role_prompt_is_standalone_and_matches_schema():
    p = Prompts()
    assert set(p.persona) == set(c.ROLES)
    for role, text in p.persona.items():
        assert not text.startswith("﻿")
        assert f'role은 "{role}"로 고정' in text
        assert '"intraday"' not in text and "intraday=" not in text   # 역할 코드는 market
        for key in c.PERSONA_DATA[role]:
            assert key in text, (role, key)
        for gone in ("N_sources", "news_source_ids", "OPEN_ANALYSIS_TAB", "LightGBM"):
            assert gone not in text, (role, gone)


def test_portfolio_totals_and_shares_from_assets():
    sr = json.loads((FIX / "stress_run.json").read_text(encoding="utf-8"))
    sr["portfolio"] = None
    b = evidence.build_bundle("d1", sr, None)
    d = {(x["metric_id"], x.get("asset_id")): x for x in b["D_sources"]}
    held = [a for a in sr["assets"] if evidence._holding(a)]
    total = sum(evidence._holding(a) for a in held)
    pnl = sum(a["center_pnl_krw"] for a in held)
    assert d[("portfolio_holding_value_krw", None)]["value"] == round(total)
    assert d[("portfolio_center_pnl_krw", None)]["value"] == round(pnl)
    assert d[("portfolio_center_return", None)]["value"] == round(pnl / total * 100, 2)
    a = held[0]
    assert d[("holding_weight", a["asset"])]["value"] == round(evidence._holding(a) / total * 100, 2)
    assert d[("center_pnl_share", a["asset"])]["value"] == round(a["center_pnl_krw"] / pnl * 100, 1)
    assert not any(x["metric_id"].startswith(("portfolio_var", "portfolio_es")) for x in b["D_sources"])


def test_portfolio_block_values_win_over_sum():
    sr = json.loads((FIX / "stress_run.json").read_text(encoding="utf-8"))
    sr["portfolio"] = {"holding_value_krw": 10_000_000, "center_pnl_krw": -120_000, "var95_krw": 999}
    b = evidence.build_bundle("d1", sr, None)
    d = {x["metric_id"]: x for x in b["D_sources"] if x["metric_id"].startswith("portfolio_")}
    assert d["portfolio_holding_value_krw"]["value"] == 10_000_000
    assert d["portfolio_center_pnl_krw"]["value"] == -120_000
    assert d["portfolio_center_return"]["value"] == -1.2
    assert "portfolio_var95_krw" not in d          # VaR/ES는 받지 않기로 함
