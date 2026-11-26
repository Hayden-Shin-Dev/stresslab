"""Generates the Fabric notebooks (NB_R01..R03) and the module manifest."""
import ast
import hashlib
import json
import sys
from pathlib import Path

PKG = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "fabric/market-regime"
MOD = PKG / "reference/market_regime/v1"
NB = PKG / "notebooks"
NB.mkdir(parents=True, exist_ok=True)

manifest = {"module": "market_regime", "version": "v1",
            "files": {f: hashlib.sha256((MOD / f).read_bytes()).hexdigest()
                      for f in ["hmm_numpy.py", "regime_core.py", "fabric_io.py"]}}
(MOD / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf8")

LOAD = '''# 모듈 무결성 확인 후 불러오기 (팀 Gold 노트북과 같은 해시 확인 방식)
import sys, json, hashlib, importlib, time
from pathlib import Path
import numpy as np, pandas as pd
assert Path("/lakehouse/default/Files").is_dir(), "기본 Lakehouse LH_MarketRegime을 연결하세요."
# 팀 원천 Lakehouse(lh_whatif)에는 쓰지 않습니다. 기본 Lakehouse가 lh_whatif이면 여기서 멈춥니다.
try:
    import notebookutils
    _lh = (notebookutils.runtime.context.get("defaultLakehouseName") or "")
except Exception:
    _lh = ""
if _lh.lower() == "lh_whatif" or Path("/lakehouse/default/Files/bronze").exists():
    raise RuntimeError("TEAM_LAKEHOUSE_DETECTED: 기본 Lakehouse를 LH_MarketRegime으로 연결하세요.")
MODULE_DIR = Path("/lakehouse/default/Files/reference/market_regime/v1")
_manifest = json.loads((MODULE_DIR / "manifest.json").read_text(encoding="utf8"))
for _f, _h in _manifest["files"].items():
    if hashlib.sha256((MODULE_DIR / _f).read_bytes()).hexdigest() != _h:
        raise RuntimeError("REGIME_MODULE_HASH_MISMATCH:" + _f)
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))
import hmm_numpy, regime_core as rc, fabric_io as fio
for _m in (hmm_numpy, rc, fio):
    importlib.reload(_m)
try:
    spark.conf.set("spark.sql.session.timeZone", "UTC")   # 팀 Gold 노트북과 같은 기준
except Exception:
    pass
print("market_regime", rc.CORE_VERSION, rc.MODEL_VERSION)'''


def md(t):
    return ("markdown", t.strip("\n"), [])


def code(t, tags=None):
    return ("code", t.strip("\n"), tags or [])


def write(name, cells):
    out = []
    for kind, src, tags in cells:
        lines = src.split("\n")
        source = [l + "\n" for l in lines[:-1]] + [lines[-1]]
        if kind == "code":
            ast.parse("\n".join(l for l in lines if not l.lstrip().startswith(("%", "!"))))
            out.append({"cell_type": "code", "execution_count": None, "outputs": [],
                        "metadata": {"tags": tags} if tags else {}, "source": source})
        else:
            out.append({"cell_type": "markdown", "metadata": {}, "source": source})
    nb = {"cells": out, "nbformat": 4, "nbformat_minor": 5,
          "metadata": {"kernel_info": {"name": "synapse_pyspark"},
                       "kernelspec": {"name": "synapse_pyspark", "display_name": "Synapse PySpark", "language": "Python"},
                       "language_info": {"name": "python"}}}
    (NB / name).write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf8")
    print("wrote", name, len(out), "cells")


# ------------------------------------------------------------------ NB_R01
write("NB_R01_Build_Regime_Features.ipynb", [
    md('''# NB_R01 · 시장 국면 피처 생성 (Gold → gold_regime_features)

**[시장국면분석ML] 1/3 단계.** 스트레스엔진ML과 같은 `gold_stress_daily` v1.1(Gold 인증 스냅샷)을 읽어 날짜 단위 시장 상태 피처를 만듭니다. Bronze·Silver·Gold는 새로 만들지 않고 그대로 씁니다.

- 입력: `Files/gold_evidence/gold_stock_market_daily_v11/` 의 `health.json`(ready 필수), `latest.json`, 인증서 해시가 맞는 `gold.parquet` + `input_eligibility.parquet`
- 처리: 수익률·이동창은 전체 거래일 달력에서 계산하고, 행별 사용 가능 여부(`input_eligible`)를 적용합니다(팀 Gold 인증서의 required_consumer_order). 사용 가능한 종목이 10개 미만인 날은 피처를 비웁니다.
- 출력: Delta `gold_regime_features`, `Files/regime/runs/<RUN_ID>/context.json`
- 기본 Lakehouse: **LH_MarketRegime** (팀 `lh_whatif`의 Gold는 읽기 전용 바로가기 `Files/gold_evidence`, `Tables/gold_stress_daily`로 읽고, 결과는 LH_MarketRegime에만 씀)'''),
    code('''RUN_ID = ""                 # 파이프라인에서 @pipeline().RunId 전달. 비우면 새로 만듭니다
USE_CERTIFIED_GOLD = True   # False면 Delta gold_stress_daily를 직접 읽음(quality_status='valid' 행만 사용)
GOLD_TABLE = "gold_stress_daily"
CONFIG_OVERRIDES_JSON = ""  # 예: '{"min_train_days": 750, "refit_every": 21}' ''', ["parameters"]),
    code(LOAD),
    code('''RUN_ID = RUN_ID or fio.new_run_id()
cfg = rc.make_config(json.loads(CONFIG_OVERRIDES_JSON) if CONFIG_OVERRIDES_JSON.strip() else None)
t0 = time.time()
gold, elig, gold_version = fio.load_gold(spark, USE_CERTIFIED_GOLD, GOLD_TABLE)
print("Gold:", gold.shape, json.dumps(gold_version, ensure_ascii=False, default=str))
feat, quality = rc.build_features(gold, elig, cfg)
print(f"피처 {feat.shape} | {quality['first_date']} → {quality['last_date']} | 사용 가능 {quality['dates_usable']}일, 제외 {quality['dates_excluded']}일 | {time.time()-t0:.1f}s")
print("종목별 첫 사용일:", {a["asset_id"]: a["first_usable_date"] for a in quality["assets"]})'''),
    code('''# 게시 전 검사: 마지막 피처 날짜 = Gold 최신일
last_ok = feat.index[feat["date_ok"]].max()
if gold_version.get("latest_gold_date") and str(last_ok.date()) != gold_version["latest_gold_date"]:
    raise RuntimeError(f"FEATURE_LATEST_DATE_MISMATCH: {last_ok.date()} != {gold_version['latest_gold_date']}")
need = cfg["min_train_days"] + 252
if int(feat["date_ok"].sum()) < need:
    raise RuntimeError(f"HISTORY_TOO_SHORT: 사용 가능 {int(feat['date_ok'].sum())}일 < 필요 {need}일")
missing_share = feat.loc[feat["date_ok"], cfg["hmm_features"]].isna().mean().round(4).to_dict()
print("HMM 피처 결측 비율(사용 가능일 기준):", missing_share)'''),
    code('''n = fio.save_table(spark, feat, "gold_regime_features")
ctx = {"run_id": RUN_ID, "created_at_utc": fio.now_utc().isoformat(), "config": cfg,
       "gold_version": gold_version, "quality": quality, "core_version": rc.CORE_VERSION,
       "module_manifest": _manifest}
fio.write_json_atomic(fio.run_dir(RUN_ID) / "context.json", ctx)
fio.write_json_atomic(fio.REGIME_ROOT / "runs/current_run.json", {"run_id": RUN_ID, "created_at_utc": ctx["created_at_utc"]})
print("gold_regime_features", n, "rows | RUN_ID", RUN_ID)
display(spark.table("gold_regime_features").orderBy("trading_date", ascending=False).limit(5))'''),
])

# ------------------------------------------------------------------ NB_R02
write("NB_R02_Train_Regime_HMM.ipynb", [
    md('''# NB_R02 · 국면 분류 HMM 학습과 검증 (walk-forward)

**[시장국면분석ML] 2/3 단계.**

- 모델: 가우시안 HMM(대각 공분산, numpy 구현이라 별도 설치 불필요), 상태 3개 → 상승장 / 횡보장 / 폭락장
- 미래 정보 차단: 첫 750거래일로 학습한 뒤, 21거래일마다 그때까지의 자료로만 다시 학습합니다. 각 날짜의 확률은 그날까지의 관측만 쓴 **필터링 확률**입니다. 첫 학습 구간의 라벨은 `initial_in_sample`로 따로 표시합니다.
- 상태 이름: 상태별 (20일 수익률 − 20일 변동성) 점수 순서로 붙입니다. 라벨은 새 국면 확률 0.6 이상이 5일 연속일 때만 바꿉니다.
- 검증: BIC(상태 수), 알려진 하락 구간 포착률, HMM과 GMM의 실루엣 비교, 연간 전환 횟수, 실시간 필터링과 사후 추정의 일치율, KNN 이웃의 국면 일치율
- 출력: Delta `gold_regime_daily`, `Files/regime/runs/<RUN_ID>/model.json · bic.json · validation.json`, (선택) MLflow 실험 `MarketRegime_HMM`'''),
    code('''RUN_ID = ""
LOG_TO_MLFLOW = True''', ["parameters"]),
    code(LOAD),
    code('''RUN_ID = fio.resolve_run_id(RUN_ID)
ctx = fio.read_json(fio.run_dir(RUN_ID) / "context.json")
cfg = ctx["config"]
feat = fio.load_table(spark, "gold_regime_features", "trading_date")
num = [c for c in feat.columns if c not in ("date_ok",)]
feat[num] = feat[num].apply(pd.to_numeric, errors="coerce")
print("RUN_ID", RUN_ID, "| features", feat.shape, feat.index.min().date(), "→", feat.index.max().date())'''),
    code('''t0 = time.time()
bic = rc.select_n_states(feat, cfg)
print("BIC (첫 학습 구간):", bic["table"], "| BIC 최적", bic["bic_best"], "| 사용", bic["used"])
daily, model_info = rc.walk_forward_regimes(feat, cfg)
print(f"walk-forward 완료 {time.time()-t0:.1f}s | 재학습 {model_info['n_refits']}회 | 학습 기준 {model_info['trained_through']}")
print(daily["regime_name"].value_counts().to_dict())'''),
    code('''t0 = time.time()
validation = rc.validate(feat, daily, model_info, cfg)
print(f"검증 {time.time()-t0:.1f}s")
print(json.dumps({k: validation[k] for k in ["oos_start", "oos_days", "events", "silhouette", "stability",
                                            "filtered_vs_smoothed_agreement", "knn_regime_agreement"]},
                 ensure_ascii=False, indent=1, default=str))
psum = daily[["p_bull", "p_sideways", "p_bear"]].sum(axis=1)
if not np.allclose(psum, 1.0, atol=1e-6):
    raise RuntimeError("PROBABILITY_SUM_INVALID")
if validation["oos_days"] < 252:
    raise RuntimeError("OUT_OF_SAMPLE_TOO_SHORT")'''),
    code('''# 눈으로 확인: KOSPI와 국면 구간 (폰트 문제를 피하려고 영어 라벨 사용)
import matplotlib.pyplot as plt
col = {"bull": "#2e9e6b", "sideways": "#8f99a6", "bear": "#d64545"}
fig, ax = plt.subplots(figsize=(15, 4.5))
ax.plot(daily.index, daily["kospi_close"], color="#1b2733", lw=1)
code_ = daily["regime_code"].to_numpy(); idx = daily.index
s = 0
for t in range(1, len(code_) + 1):
    if t == len(code_) or code_[t] != code_[s]:
        ax.axvspan(idx[s], idx[min(t, len(code_) - 1)], color=col[code_[s]], alpha=0.18, lw=0); s = t
ax.axvline(pd.Timestamp(model_info["walk_forward_start"]), color="k", ls="--", lw=1)
ax.set_title("KOSPI with regime labels (green=bull, gray=sideways, red=bear; dashed=walk-forward start)")
plt.show()'''),
    code('''fio.save_table(spark, daily.reset_index(), "gold_regime_daily")
rd = fio.run_dir(RUN_ID)
fio.write_json_atomic(rd / "model.json", model_info)
fio.write_json_atomic(rd / "bic.json", bic)
fio.write_json_atomic(rd / "validation.json", rc._clean(validation))
if LOG_TO_MLFLOW:
    try:
        import mlflow
        mlflow.set_experiment("MarketRegime_HMM")
        with mlflow.start_run(run_name=RUN_ID):
            mlflow.log_params({"model_version": model_info["model_version"], "n_states": cfg["n_states"],
                               "features": ",".join(cfg["hmm_features"]), "min_train_days": cfg["min_train_days"],
                               "refit_every": cfg["refit_every"], "label_threshold": cfg["label_threshold"],
                               "label_confirm_days": cfg["label_confirm_days"],
                               "gold_snapshot_version": str(ctx["gold_version"].get("gold_snapshot_version"))})
            m = {"oos_days": validation["oos_days"],
                 "switches_per_year": validation["stability"]["label_switches_per_year"],
                 "filtered_vs_smoothed": validation["filtered_vs_smoothed_agreement"] or 0,
                 "knn_agreement": validation["knn_regime_agreement"]["mean"] or 0,
                 "silhouette_hmm": validation["silhouette"]["hmm"] or 0,
                 "silhouette_gmm": validation["silhouette"]["gmm"] or 0}
            for e in validation["events"]:
                m["event_bear_share_" + e["start"]] = e["bear_share"]
            mlflow.log_metrics(m)
            mlflow.log_dict(rc._clean(validation), "validation.json")
            mlflow.log_dict({k: v for k, v in model_info.items()}, "model.json")
        print("MLflow 기록 완료")
    except Exception as e:
        print("MLflow 기록 생략:", type(e).__name__, str(e)[:200])
print("gold_regime_daily 저장 |", daily.index.max().date(), daily["regime_name"].iloc[-1])'''),
])

# ------------------------------------------------------------------ NB_R03
write("NB_R03_Publish_Regime_Snapshot.ipynb", [
    md('''# NB_R03 · 국면 스냅샷 게시 (API · 웹 대시보드 · PostgreSQL 전달용)

**[시장국면분석ML] 3/3 단계.** 국면 구간·요약·전이·유사 시기를 계산하고, 웹 대시보드와 API가 그대로 쓰는 **스냅샷 JSON 1개**를 만듭니다. 검사를 통과해야만 `latest`가 바뀝니다. 실패하면 이전 정상 스냅샷이 유지됩니다.

- 출력 파일: `Files/regime/snapshots/<버전>/regime_snapshot.json`, `certificate.json`, `Files/regime/latest.json`, `Files/regime/health.json`
- 출력 Delta: `gold_regime_runs`, `gold_regime_summary`, `gold_regime_transition`, `gold_regime_similar`
- PostgreSQL 복사용 단계 테이블: `regime_pg_snapshot`(1행), `regime_pg_daily` → 파이프라인 Copy 작업이 `regime.snapshot`, `regime.daily`로 적재'''),
    code('''RUN_ID = ""
DATA_MODE = "fabric_gold"   # 운영은 항상 fabric_gold. 합성 데이터는 게시 검사에서 차단됩니다''', ["parameters"]),
    code(LOAD),
    code('''RUN_ID = fio.resolve_run_id(RUN_ID)
rd = fio.run_dir(RUN_ID)
ctx, model_info = fio.read_json(rd / "context.json"), fio.read_json(rd / "model.json")
bic, validation = fio.read_json(rd / "bic.json"), fio.read_json(rd / "validation.json")
if not all([ctx, model_info, bic, validation]):
    raise RuntimeError("RUN_ARTIFACTS_MISSING: NB_R01, NB_R02를 같은 RUN_ID로 먼저 실행하세요")
cfg = ctx["config"]
feat = fio.load_table(spark, "gold_regime_features", "trading_date")
num = [c for c in feat.columns if c not in ("date_ok",)]
feat[num] = feat[num].apply(pd.to_numeric, errors="coerce")
daily = fio.load_table(spark, "gold_regime_daily", "trading_date")
for c in ["p_bull", "p_sideways", "p_bear", "kospi_close"]:
    daily[c] = pd.to_numeric(daily[c], errors="coerce")
daily["run_id"] = daily["run_id"].astype(int); daily["run_day"] = daily["run_day"].astype(int)
print("RUN_ID", RUN_ID, "| daily", daily.shape, daily.index.max().date())'''),
    code('''runs = rc.build_runs(daily, feat)
summary = rc.regime_summary(daily, feat, runs)
trans = rc.transition_tables(daily, runs)
sim, sim_query = rc.similar_periods(feat, daily, None, cfg)
quality = ctx["quality"]; quality["warnings"] = rc.quality_warnings(bic, quality)
snap = rc.build_snapshot(feat, daily, runs, summary, trans, sim, sim_query, validation, model_info, bic,
                         quality, cfg, DATA_MODE, ctx["gold_version"])
payload, sha = rc.snapshot_bytes(snap)
fails = rc.publish_checks(snap, ctx["gold_version"])
if len(payload) > 5_000_000:
    fails.append("PAYLOAD_TOO_LARGE")
print("snapshot", snap["snapshot_version"], "| as_of", snap["as_of"], "|", len(payload), "bytes | sha", sha[:12])
print("현재:", json.dumps({k: snap["current"][k] for k in ["regime_name", "confidence", "days_in_regime", "regime_since", "pending_switch"]}, ensure_ascii=False))
if fails:
    fio.write_json_atomic(fio.REGIME_ROOT / "health.json", {"status": "blocked", "checked_at_utc": fio.now_utc().isoformat(),
                                                            "run_id": RUN_ID, "reasons": fails})
    raise RuntimeError("REGIME_PUBLISH_BLOCKED: " + ", ".join(fails))'''),
    code('''# 1) 스냅샷 파일 + 인증서 (먼저 기록하고 해시 대조)
ver = snap["snapshot_version"]
sdir = fio.REGIME_ROOT / "snapshots" / ver
sdir.mkdir(parents=True, exist_ok=False)
(sdir / "regime_snapshot.json").write_bytes(payload)
if fio.sha256_file(sdir / "regime_snapshot.json") != sha:
    raise RuntimeError("SNAPSHOT_WRITE_HASH_MISMATCH")
cert = {"snapshot_version": ver, "run_id": RUN_ID, "as_of": snap["as_of"], "sha256": sha, "bytes": len(payload),
        "data_mode": DATA_MODE, "model_version": model_info["model_version"], "core_version": rc.CORE_VERSION,
        "gold_version": ctx["gold_version"], "module_manifest": _manifest, "created_at_utc": fio.now_utc().isoformat()}
fio.write_json_atomic(sdir / "certificate.json", cert)

# 2) 분석 Delta 테이블
fio.save_table(spark, runs, "gold_regime_runs")
fio.save_table(spark, summary, "gold_regime_summary")
fio.save_table(spark, trans[0], "gold_regime_transition")
fio.save_table(spark, sim.assign(snapshot_version=ver), "gold_regime_similar")

# 보고서(Power BI)용 현재 상태 1행 + 검증 지표
cur = snap["current"]
_ps = cur.get("pending_switch") or {}
current_tbl = pd.DataFrame([{"as_of": pd.Timestamp(snap["as_of"]), "regime_code": cur["regime_code"],
                             "regime_name": cur["regime_name"], "confidence": float(cur["confidence"] or 0),
                             "p_bull": float(cur["probabilities"]["bull"]), "p_sideways": float(cur["probabilities"]["sideways"]),
                             "p_bear": float(cur["probabilities"]["bear"]), "raw_argmax_code": str(cur.get("raw_argmax_code") or ""),
                             "days_in_regime": int(cur["days_in_regime"]), "regime_since": pd.Timestamp(cur["regime_since"]),
                             "changes_last_252d": int(cur.get("changes_last_252d") or 0),
                             "pending_to_name": str(_ps.get("to_name") or ""), "pending_days": int(_ps.get("consecutive_days") or 0),
                             "pending_required_days": int(_ps.get("required_days") or 0),
                             "snapshot_version": ver, "notice": snap["notice"]}])
fio.save_table(spark, current_tbl, "gold_regime_current")
_v, _rows = validation, []
for _e in _v["events"]:
    _rows += [{"grp": "event", "item": _e["name"], "metric": "bear_share", "value": float(_e["bear_share"] or 0)},
              {"grp": "event", "item": _e["name"], "metric": "mean_p_bear", "value": float(_e["mean_p_bear"] or 0)}]
_rows += [{"grp": "stability", "item": "label", "metric": "switches_per_year", "value": float(_v["stability"]["label_switches_per_year"] or 0)},
          {"grp": "agreement", "item": "filtered_vs_smoothed", "metric": "agreement", "value": float(_v["filtered_vs_smoothed_agreement"] or 0)},
          {"grp": "agreement", "item": "knn", "metric": "agreement", "value": float(_v["knn_regime_agreement"]["mean"] or 0)},
          {"grp": "agreement", "item": "knn", "metric": "random_baseline", "value": float(_v["knn_regime_agreement"]["random_baseline"] or 0)},
          {"grp": "silhouette", "item": "hmm", "metric": "silhouette", "value": float(_v["silhouette"]["hmm"] or 0)},
          {"grp": "silhouette", "item": "gmm", "metric": "silhouette", "value": float(_v["silhouette"]["gmm"] or 0)},
          {"grp": "coverage", "item": "out_of_sample", "metric": "days", "value": float(_v["oos_days"])}]
fio.save_table(spark, pd.DataFrame(_rows).assign(oos_start=str(_v["oos_start"]), snapshot_version=ver), "gold_regime_validation")

# 3) PostgreSQL 복사용 단계 테이블 (이번 실행분만)
created = pd.Timestamp(fio.now_utc()).tz_convert("UTC").tz_localize(None)
pg_snapshot = pd.DataFrame([{"snapshot_version": ver, "as_of": pd.Timestamp(snap["as_of"]),
                             "model_version": model_info["model_version"], "data_mode": DATA_MODE,
                             "gold_snapshot_version": str(ctx["gold_version"].get("gold_snapshot_version") or ""),
                             "payload_text": payload.decode("utf-8"), "payload_sha256": sha, "created_at": created}])
pg_daily = daily.reset_index()[["trading_date", "kospi_close", "regime_code", "p_bull", "p_sideways", "p_bear",
                                "raw_code", "label_basis"]].assign(snapshot_version=ver)
fio.save_table(spark, pg_snapshot, "regime_pg_snapshot")
fio.save_table(spark, pg_daily, "regime_pg_daily")

# 4) 최신 포인터와 상태 (모든 기록이 끝난 뒤 교체)
fio.write_json_atomic(fio.REGIME_ROOT / "latest.json", {"version": ver, "path": f"regime/snapshots/{ver}/regime_snapshot.json",
                                                        "sha256": sha, "as_of": snap["as_of"]})
fio.write_json_atomic(fio.REGIME_ROOT / "health.json", {"status": "ready", "checked_at_utc": fio.now_utc().isoformat(),
                                                        "run_id": RUN_ID, "snapshot_version": ver, "as_of": snap["as_of"],
                                                        "regime": snap["current"]["regime_code"]})
print("게시 완료:", ver, "| latest.json 갱신 | PostgreSQL 단계 테이블 준비")'''),
])
print("manifest", json.dumps(manifest)[:200])
