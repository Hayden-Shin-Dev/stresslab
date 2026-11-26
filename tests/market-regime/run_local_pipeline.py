"""Run the whole regime pipeline locally on the synthetic fixture and write the sample snapshot.

    python -I run_local_pipeline.py <path/to/market_regime/v1> <out_dir>
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parents[1] / "fabric/market-regime/reference/market_regime/v1"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "outputs"
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(HERE))

import regime_core as rc  # noqa: E402
from make_synthetic_gold import make  # noqa: E402

t0 = time.time()
gold, true_state = make()
print("synthetic gold", gold.shape, f"{time.time()-t0:.1f}s")
res = rc.run_all(gold, None, rc.make_config(), data_mode="synthetic_fixture",
                 data_version={"gold_table": "gold_stress_daily", "dataset_version": "synthetic_fixture",
                               "gold_snapshot_version": None, "note": "합성 데이터. 실제 시장 결과가 아님"})
print(f"pipeline done {time.time()-t0:.1f}s")

# synthetic-only sanity: agreement with the simulated regime (impossible on real data)
d = res["daily"]
truth = true_state.reindex(d.index).map({0: "bull", 1: "sideways", 2: "bear"})
wf = d["label_basis"].eq("walk_forward")
print("synthetic agreement (walk-forward days):", round(float((d.loc[wf, "regime_code"] == truth[wf]).mean()), 3))

OUT.mkdir(parents=True, exist_ok=True)
b, sha = rc.snapshot_bytes(res["snapshot"])
(OUT / "regime_snapshot.sample.json").write_bytes(b)
(OUT / "regime_snapshot.sample.sha256").write_text(sha)
(OUT / "validation.sample.json").write_text(json.dumps(res["snapshot"]["validation"], ensure_ascii=False, indent=2))
print("snapshot bytes", len(b), "sha", sha[:12])
print(json.dumps(res["snapshot"]["current"], ensure_ascii=False, indent=1)[:1500])
