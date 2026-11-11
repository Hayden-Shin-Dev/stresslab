"""이전 로컬 원본 함수와 이식한 코드의 실제 수치 비교."""
import argparse
import ast
import hashlib
import importlib
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from .features import build
from .model import STATE, FACTORS, fit, predict
from .shocks import load_legacy_observations


def verify(original_root, original_models, snapshot, output, observations):
    root, snapshot = Path(original_root), Path(snapshot)
    sys.path.insert(0, str(root))
    original = importlib.import_module("stresslab.stock_response_v152")
    script = root / "scripts/project_b_asset_stress_v142.py"
    tree = ast.parse(script.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "panel_for")
    ns = {"np": np, "pd": pd}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(script), "exec"), ns)
    gold = pd.read_parquet(snapshot / "gold.parquet")
    features, _ = build(gold, pd.read_parquet(snapshot / "provenance.parquet"), load_legacy_observations(observations))
    market = gold[["trading_date", "kospi_close"]].drop_duplicates().sort_values("trading_date")
    dates = pd.DatetimeIndex(pd.to_datetime(market.trading_date)).astype("datetime64[ns]")
    max_feature_error, max_predict_error, replayed, refits = 0., 0., 0, 0
    models = json.loads(Path(original_models).read_text(encoding="utf-8"))
    for asset in sorted(gold.asset_id.unique()):
        old = ns["panel_for"](asset, gold, dates, market)
        new = features[features.asset_id.eq(asset)]
        paired = old.merge(new, on=["asset_id", "horizon", "origin"], suffixes=("_old", "_new"), validate="one_to_one")
        for c in STATE + ["scale", "target"]:
            a, b = paired[c+"_old"].to_numpy(), paired[c+"_new"].to_numpy()
            np.testing.assert_allclose(a, b, rtol=0, atol=1e-10, equal_nan=True)
            max_feature_error = max(max_feature_error, float(np.nanmax(abs(a-b))))
        for horizon in [1, 5]:
            x = new[new.horizon.eq(horizon) & new.state_valid].tail(20).copy()
            fitted = max((m for m in models if m["asset_id"] == asset and m["horizon"] == horizon and m["arm"] == "symmetric_huber"), key=lambda m: m["fit_origin"])
            for shock in [[0,0,0,0], [2,25,5,5], [-2,-25,-5,-5]]:
                x[FACTORS] = np.tile(shock, (len(x),1))
                a, b = original.predict(x, fitted), predict(x, fitted)
                for key in a:
                    np.testing.assert_allclose(a[key], b[key], rtol=0, atol=1e-12)
                    max_predict_error = max(max_predict_error, float(np.max(abs(a[key]-b[key]))))
                replayed += len(x)
            train = new[new.horizon.eq(horizon) & new.training_eligible & new.state_valid].dropna(subset=FACTORS+["target"]).tail(500)
            a, b = original.fit(train), fit(train)
            np.testing.assert_allclose(a["coef"], b["coef"], rtol=0, atol=1e-12)
            refits += 1
    result = {"status": "passed", "asset_horizon_refits": refits, "replayed_rows": replayed,
              "max_feature_difference": max_feature_error, "max_prediction_difference_pp": max_predict_error,
              "source_model_sha256": hashlib.sha256(Path(original.__file__).read_bytes()).hexdigest(),
              "source_features_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
              "scope": "same inputs and weights/functions; not proof that retraining changes no forecasts"}
    Path(output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    for key in ["original-root", "original-models", "snapshot", "output", "observations"]:
        p.add_argument("--"+key, required=True)
    a = p.parse_args()
    verify(a.original_root, a.original_models, a.snapshot, a.output, a.observations)
