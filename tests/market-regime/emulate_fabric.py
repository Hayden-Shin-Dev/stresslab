"""Executes the Fabric notebook cells locally against a fake Spark + temporary Files root.

Checks: module hash gate, certified-Gold read, Delta round-trips, run context passing,
publish gate blocking (synthetic data must not publish), and the successful publish path.
    python -I emulate_fabric.py [<fabric/market-regime 폴더>] [<scratch_dir>]
"""
import functools
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
PKG = (Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parents[1] / "fabric/market-regime").resolve()
WORK = (Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "outputs/fabric_emulation").resolve()
FILES = WORK / "Files"
shutil.rmtree(WORK, ignore_errors=True)
(FILES / "reference/market_regime").mkdir(parents=True)
shutil.copytree(PKG / "reference/market_regime/v1", FILES / "reference/market_regime/v1")
sys.path.insert(0, str(HERE))
from make_synthetic_gold import make  # noqa: E402

# ---------------------------------------------------------------- fake Spark
STORE = {}


class _Writer:
    def __init__(self, pdf):
        self.pdf = pdf

    def format(self, *_):
        return self

    def mode(self, *_):
        return self

    def option(self, *_):
        return self

    def saveAsTable(self, name):
        STORE[name] = self.pdf.copy()


class FakeDF:
    def __init__(self, pdf):
        self.pdf = pdf

    @property
    def write(self):
        return _Writer(self.pdf)

    def count(self):
        return len(self.pdf)

    def toPandas(self):
        return self.pdf.copy()

    def agg(self, spec):
        (col, fn), = spec.items()
        val = getattr(pd.to_datetime(self.pdf[col]), fn)().date()
        return type("R", (), {"first": lambda s: [val]})()

    def orderBy(self, *a, **k):
        return self

    def limit(self, n):
        return FakeDF(self.pdf.head(n))


class FakeSpark:
    def createDataFrame(self, pdf):
        for c in pdf.columns:  # Spark cannot infer an all-null object column
            assert not (pdf[c].dtype == object and pdf[c].isna().all()), "all-null column " + c
        return FakeDF(pdf.copy())

    def table(self, name):
        if name not in STORE:
            raise KeyError("TABLE_NOT_FOUND:" + name)
        return FakeDF(STORE[name])


# ---------------------------------------------------------------- Gold evidence fixture
pd.read_parquet = lambda p, *a, **k: pd.read_pickle(p)  # pyarrow is unavailable locally
gold, _ = make()
elig = gold[["trading_date", "asset_id"]].copy()
elig["input_eligible"] = gold["quality_status"].eq("valid")
elig["reason"] = elig["input_eligible"].map({True: "ready", False: "quality_or_observation_date"})
ver = "20261118T000000000000Z"
run = FILES / "gold_evidence/gold_stock_market_daily_v11" / ver
run.mkdir(parents=True)
gold.to_pickle(run / "gold.parquet")
elig.to_pickle(run / "input_eligibility.parquet")
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()  # noqa: E731
last = str(pd.to_datetime(gold["trading_date"]).max().date())
(run / "certificate.json").write_text(json.dumps({"gold_sha256": sha(run / "gold.parquet"),
                                                  "input_eligibility_sha256": sha(run / "input_eligibility.parquet"),
                                                  "latest_gold_date": last, "latest_eligible_date": last,
                                                  "training_ready": True}))
base = run.parent
(base / "latest.json").write_text(json.dumps({"version": ver, "path": f"gold_evidence/gold_stock_market_daily_v11/{ver}"}))
(base / "health.json").write_text(json.dumps({"status": "ready", "checked_at_utc": "2026-11-18T00:00:00+00:00"}))
STORE["gold_stress_daily"] = gold


# ---------------------------------------------------------------- run notebooks
def run_nb(name, params=None, after_load=None):
    nb = json.loads((PKG / "notebooks" / name).read_text(encoding="utf8"))
    ns = {"spark": FakeSpark(), "display": lambda x: print("[display]", type(x).__name__)}
    for cell in nb["cells"]:
        if cell["cell_type"] != "code":
            continue
        src = "".join(cell["source"]).replace("/lakehouse/default/Files", str(FILES))
        if "parameters" in cell.get("metadata", {}).get("tags", []):
            exec(src, ns)
            ns.update(params or {})
            continue
        exec(compile(src, name, "exec"), ns)
        if "MODULE_DIR" in src and after_load:
            after_load(ns)
    return ns


import os  # noqa: E402
os.environ["REGIME_FILES_ROOT"] = str(FILES)
ns1 = run_nb("NB_R01_Build_Regime_Features.ipynb")
ns2 = run_nb("NB_R02_Train_Regime_HMM.ipynb", {"LOG_TO_MLFLOW": True})

# (a) synthetic data must be blocked from publishing
try:
    run_nb("NB_R03_Publish_Regime_Snapshot.ipynb", {"DATA_MODE": "synthetic_fixture"})
    raise SystemExit("FAIL: synthetic snapshot was published")
except RuntimeError as e:
    assert "NOT_FABRIC_GOLD_DATA" in str(e), e
    h = json.loads((FILES / "regime/health.json").read_text())
    assert h["status"] == "blocked" and not (FILES / "regime/latest.json").exists()
    print("OK publish gate blocked synthetic data:", h["reasons"])


# (b) publish path (gate relaxed only inside this emulation)
def relax(ns):
    ns["rc"].publish_checks = functools.partial(ns["rc"].publish_checks.__wrapped__ if hasattr(ns["rc"].publish_checks, "__wrapped__") else ns["rc"].publish_checks, allow_synthetic=True)


ns3 = run_nb("NB_R03_Publish_Regime_Snapshot.ipynb", {"DATA_MODE": "synthetic_fixture"}, relax)
latest = json.loads((FILES / "regime/latest.json").read_text())
snap_path = FILES / latest["path"]
assert sha(snap_path) == latest["sha256"]
snap = json.loads(snap_path.read_text(encoding="utf8"))
print("OK published", latest["version"], snap["as_of"], snap["current"]["regime_name"], "| tables:",
      sorted(k for k in STORE if k.startswith(("gold_regime", "regime_pg"))))
assert STORE["regime_pg_snapshot"].shape[0] == 1 and STORE["regime_pg_daily"].shape[0] == len(snap["history"])
ps = STORE["regime_pg_snapshot"].iloc[0]
assert str(type(ps["as_of"]).__name__) == "date", type(ps["as_of"])
assert hasattr(ps["created_at"], "hour") and str(ps["created_at"])[11:] != "00:00:00", ps["created_at"]   # keeps time
assert __import__("hashlib").sha256(ps["payload_text"].encode()).hexdigest() == ps["payload_sha256"]
print("OK pg stage: as_of date, created_at", ps["created_at"], "payload sha verified")
shutil.copy(snap_path, WORK / "regime_snapshot.emulated.json")
print("emulation passed")
