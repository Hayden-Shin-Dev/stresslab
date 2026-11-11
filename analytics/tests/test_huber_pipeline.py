import json
import numpy as np
import pandas as pd
import pytest
from huber_pipeline import model, snapshot
from huber_pipeline.result import contributions, historical_examples
from huber_pipeline.training import mature_training, residual_bank


def sample():
    rng = np.random.default_rng(12)
    x = pd.DataFrame(rng.normal(size=(500, 6)), columns=model.STATE + model.FACTORS)
    x["scale"] = rng.uniform(1, 5, len(x))
    x["target"] = rng.normal(size=len(x)) - 1.2*x.fx_pct + .5*x.oil_usd
    return x


def test_zero_shock_and_contributions_preserve_model():
    x = sample()
    fitted = model.fit(x)
    row = x.iloc[:1].copy()
    before = json.dumps(fitted, sort_keys=True)
    out = model.predict(row, fitted)
    parts = contributions(row, fitted)
    assert sum(parts.values()) == pytest.approx(out["shock_response"][0], abs=1e-10)
    row[model.FACTORS] = 0.
    zero = model.predict(row, fitted)
    assert zero["shock_response"][0] == 0
    assert all(v == 0 for v in contributions(row, fitted).values())
    assert json.dumps(fitted, sort_keys=True) == before


def test_training_excludes_unfinished_targets_and_late_factors():
    x = sample().iloc[:3].copy()
    x["origin"] = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"])
    x["target_end"] = pd.to_datetime(["2026-01-07", "2026-01-08", "2026-01-09"])
    x["shock_end"] = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"])
    x["factor_known_by"] = pd.to_datetime(["2026-01-05T06:00Z", "2026-01-10T06:00Z", "2026-01-07T06:00Z"])
    x["training_eligible"] = True
    x["state_valid"] = True
    assert mature_training(x, "2026-01-09").index.tolist() == [0]


def test_calibration_does_not_read_future_errors():
    p = pd.DataFrame({"origin": pd.to_datetime(["2025-01-01", "2026-01-01"]),
                      "target_end": pd.to_datetime(["2025-01-08", "2026-01-08"]),
                      "target": [1., 999.], "scale": [1., 1.], "location_z": [0., 0.]})
    expected = residual_bank(p, "2026-01-02")
    p.loc[1, "target"] = -99.
    np.testing.assert_array_equal(residual_bank(p, "2026-01-02"), expected)
    assert len(expected) == 1


def test_real_deletion_vectors_are_rejected(tmp_path, monkeypatch):
    (tmp_path / "_delta_log").mkdir()
    (tmp_path / "_delta_log" / "00000000000000000000.json").write_text(json.dumps(
        {"add": {"path": "data.parquet", "deletionVector": {"cardinality": 1}}}), encoding="utf-8")
    class Delta:
        def to_pyarrow_table(self):
            raise RuntimeError("deletionVectors unsupported")
    monkeypatch.setattr(snapshot, "DeltaTable", lambda *a, **k: Delta())
    with pytest.raises(ValueError, match="실제 삭제 벡터"):
        snapshot.read_local_delta(tmp_path, 0)


def test_history_excludes_future_opposite_and_overlapping_cases():
    h = pd.DataFrame({"origin": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-02-01", "2027-01-01"]),
                      "target_end": pd.to_datetime(["2025-01-08", "2025-01-09", "2025-02-08", "2027-01-08"]),
                      "horizon": 5, "target": [-2., -3., 1., -99.], "fx_pct": [1., 1., -1., 1.],
                      "us_rate_bp": 0., "oil_usd": 0., "vix_points": 0.})
    rows = historical_examples(h, np.array([1., 0., 0., 0.]), "2026-01-01", 5)
    assert len(rows) == 1
    assert rows[0]["actual_return_pct"] == -2.
