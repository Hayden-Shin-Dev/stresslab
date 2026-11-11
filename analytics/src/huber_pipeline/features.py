"""Gold 검사와 B152 피처 생성. 결측을 채우거나 거래일을 압축하지 않는다."""
from __future__ import annotations
import numpy as np
import pandas as pd
from .model import STATE, FACTORS

MACROS = ["usdkrw", "us_treasury_10y", "wti", "vix", "korea_3y"]
GOLD_COLUMNS = {"trading_date", "asset_id", "sector_id", "instrument_kind", "close", "volume",
                "price_basis", "adjustment_version", "kospi_close", "price_available_at", "source_ref",
                "dataset_version", "quality_status", "is_mock"} | set(MACROS) | {
                    m + suffix for m in MACROS for suffix in ["_observation_date", "_observed_at", "_available_at"]}


def normalize(gold):
    gold = gold.copy()
    if set(gold.columns) != GOLD_COLUMNS:
        raise ValueError("Gold 34개 컬럼 계약 불일치")
    for c in ["close", "volume", "kospi_close"] + MACROS:
        if not pd.api.types.is_numeric_dtype(gold[c]) or np.isinf(gold[c].dropna().to_numpy()).any():
            raise ValueError(f"{c}는 무한대가 없는 숫자 컬럼이어야 함")
    gold["trading_date"] = pd.to_datetime(gold.trading_date).astype("datetime64[ns]")
    if not gold.asset_id.map(lambda v: isinstance(v, str) and len(v) == 6 and v.isdigit()).all():
        raise ValueError("종목코드는 앞자리 0을 보존한 6자리 문자열이어야 함")
    if gold.duplicated(["trading_date", "asset_id"]).any():
        raise ValueError("Gold 종목/날짜 키 중복")
    if gold.dataset_version.nunique() != 1:
        raise ValueError("Gold 버전 혼합")
    market_cols = ["kospi_close"] + MACROS + [m + "_observation_date" for m in MACROS]
    if gold.groupby("trading_date")[market_cols].nunique(dropna=False).gt(1).any().any():
        raise ValueError("같은 날짜의 시장 데이터가 종목별로 다름")
    return gold.sort_values(["asset_id", "trading_date"]).reset_index(drop=True)


def audit(gold, provenance):
    gold = normalize(gold)
    p = provenance.copy()
    p["date"] = pd.to_datetime(p.date).astype("datetime64[ns]")
    p["observation_date"] = pd.to_datetime(p.observation_date).astype("datetime64[ns]")
    p["known_by"] = pd.to_datetime(p.known_by, utc=True)
    if p.duplicated(["date", "source"]).any():
        raise ValueError("공표 근거 날짜/지표 중복")
    good = p[p.verified.eq(True)]
    cutoff = pd.to_datetime(good.date, utc=True) + pd.Timedelta(hours=6, minutes=30)
    # 민철 2026-11-11 수정 (현행 Gold는 지표별 발표 주기를 적용하기 때문에 구형 10일 제한 대신 게시된 시점 근거를 검증하도록 수정함.)
    if (good.known_by.isna() | (good.known_by > cutoff) | good.observation_date.isna() |
        (good.observation_date > good.date)).any():
        raise ValueError("공표 근거가 Gold 기준 시점을 위반함")
    if not good.policy_version.eq("publication-cadence-v2-20261109").all():
        raise ValueError("새 공표 정책은 검토 후 연결해야 함")
    eligible = gold.quality_status.eq("valid") & gold.price_basis.eq("adjusted") & gold.is_mock.eq(False)
    eligible &= gold.instrument_kind.eq("stock") & gold.close.gt(0) & gold.volume.gt(0) & gold.adjustment_version.notna()
    for source in MACROS:
        q = p[p.source.eq(source)].set_index("date")
        values = gold.trading_date.map(q.value)
        observed = gold.trading_date.map(q.observation_date)
        verified = gold.trading_date.map(q.verified).eq(True)
        nonnull = gold[source].notna()
        match = gold[source].eq(values) & pd.to_datetime(gold[source + "_observation_date"]).eq(observed)
        if (nonnull & (~verified | ~match)).any():
            raise ValueError(f"{source}의 Gold 값과 공표 근거 불일치")
        if source != "korea_3y":
            eligible &= nonnull & verified & match
    summary = {"rows": len(gold), "assets": int(gold.asset_id.nunique()),
               "first_date": str(gold.trading_date.min().date()), "last_date": str(gold.trading_date.max().date()),
               "eligible_rows": int(eligible.sum()), "excluded_rows": int((~eligible).sum()),
               "null_counts": gold.isna().sum().astype(int).to_dict(),
               "max_observation_age_days": good.assign(age=(good.date-good.observation_date).dt.days).groupby("source").age.max().astype(int).to_dict(),
               "exact_publication_clocks": False, "availability_cutoff": "15:30 Asia/Seoul",
               "availability_basis": "Gold와 값이 일치하는 verified known_by 이용 가능 시점 상한"}
    return gold, eligible, p, summary


def build_asof_research(gold, provenance):
    gold, eligible, p, summary = audit(gold, provenance)
    gold["training_eligible"] = eligible
    market = gold[["trading_date", "kospi_close"] + MACROS].drop_duplicates().sort_values("trading_date")
    dates = pd.DatetimeIndex(market.trading_date)
    market = market.set_index("trading_date")
    # 민철 2026-11-11 추가 (기존 Huber의 충격 단위를 유지해야 하기 때문에 환율 로그변화, 금리 bp, 유가 달러 차이, VIX 포인트로 계산했음.)
    shocks = pd.DataFrame({"fx_pct": 100 * np.log(market.usdkrw / market.usdkrw.shift()),
                           "us_rate_bp": 100 * market.us_treasury_10y.diff(),
                           "oil_usd": market.wti.diff(), "vix_points": market.vix.diff()}).shift(-1)
    known = p[p.source.isin(MACROS[:4])].pivot(index="date", columns="source", values="known_by").reindex(dates)
    known_complete = known.notna().all(axis=1)
    factor_known = known.max(axis=1).where(known_complete).shift(-1)
    next_date = pd.Series(dates, index=dates).shift(-1)
    rows = []
    for asset, group in gold.groupby("asset_id"):
        g = group.set_index("trading_date").reindex(dates)
        price_ok = g.price_basis.eq("adjusted") & g.is_mock.eq(False) & g.close.gt(0)
        prices = g.close.where(price_ok)
        valid = g.volume.gt(0) & price_ok
        logp = 100 * np.log(prices)
        ret = logp.diff()
        vol = np.sqrt(ret.pow(2).ewm(alpha=.06, adjust=False).mean()).clip(lower=.05)
        state = pd.DataFrame({"origin": dates, "ret20_z": (logp.diff(20) / (vol * np.sqrt(20))).to_numpy(),
                              "vol_ratio": (ret.rolling(5).std() / ret.rolling(60).std()).to_numpy(),
                              "origin_valid": valid.to_numpy(), "asset_id": asset})
        for h in [1, 5]:
            x = state.copy()
            x["horizon"] = h
            x["scale"] = vol.to_numpy() * np.sqrt(h)
            x["target"] = (100 * (prices.shift(-h) / prices - 1)).where(valid & valid.shift(-h, fill_value=False)).to_numpy()
            x["target_end"] = pd.Series(dates).shift(-h)
            x[FACTORS] = shocks.to_numpy()
            x["factor_known_by"] = factor_known.to_numpy()
            x["shock_end"] = next_date.to_numpy()
            x["training_eligible"] = g.training_eligible.eq(True).to_numpy() & g.training_eligible.shift(-1).eq(True).to_numpy()
            x["state_valid"] = x.origin_valid & np.isfinite(x[STATE + ["scale"]]).all(axis=1)
            rows.append(x)
    return pd.concat(rows, ignore_index=True), summary


def build(gold, provenance, observations=None):
    from .shocks import observation_shocks, legacy_pool_membership
    if observations is None:
        raise ValueError("B152 충격 계산에는 원 관측자료가 필요함. 발표 상태 Gold 차분으로 대체하지 않음")
    frame, summary = build_asof_research(gold, provenance)
    shocks, _ = observation_shocks(sorted(frame.origin.unique()), observations)
    frame = frame.drop(columns=FACTORS+["factor_known_by", "shock_end"]).merge(shocks, on="origin", validate="many_to_one")
    frame["gold_state_eligible"] = frame.training_eligible
    # 민철 2026-11-11 수정 (현재 거시 발표 상태의 적합성으로 과거 시나리오 표본까지 제외했기 때문에 종목 가격 피처와 원 관측 충격의 학습 조건을 분리함.)
    frame["training_eligible"] = legacy_pool_membership(frame)
    summary.update(factor_contract="b152_observation_scenario_v1",
                   factor_availability_basis="legacy research publication proxy; not verified receipt time",
                   scenario_inputs_are_hypothetical_or_ex_post=True)
    return frame, summary
