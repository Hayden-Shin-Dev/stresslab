"""Fabric 노트북이 호출하는 두 진입점. 노트북에는 계산이 없고 이 함수만 부릅니다.

    run_train_validate(cfg, spark=spark)  -> 모델 학습·보정, 승인 게이트 확인, 패키지 생성, MLflow 기록
    run_export(cfg, conn, spark=spark)    -> Gold 피처/근거를 PostgreSQL 새 릴리스로 적재

cfg는 dict입니다(노트북 맨 위 설정 칸). 필수 키가 비어 있으면 시작 전에 멈추고 빈 키를 알려 줍니다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

try:
    import build_samples as BS
    import features as FT
    import model_package as MP
    import release_export as RE
    import splits as SP
    import targets as TG
    import train as TR
    from distribution import INPUT_ORDER, MODEL_VERSION, with_scales
    from fabric_io import GoldSource, read_gold
except ImportError:
    from . import build_samples as BS
    from . import features as FT
    from . import model_package as MP
    from . import release_export as RE
    from . import splits as SP
    from . import targets as TG
    from . import train as TR
    from .distribution import INPUT_ORDER, MODEL_VERSION, with_scales
    from .fabric_io import GoldSource, read_gold

SOURCE_KEYS = ('gold_kind', 'gold_location')
TRAIN_KEYS = ('work_dir', 'package_name')


def _need(cfg: dict, keys) -> None:
    empty = [k for k in keys if cfg.get(k) is None or (isinstance(cfg.get(k), str) and not cfg[k].strip())]
    if empty:
        raise ValueError(f'설정이 비어 있습니다: {empty}. 노트북 맨 위 설정 칸을 채우세요.')


def source_from_cfg(cfg: dict) -> GoldSource:
    _need(cfg, SOURCE_KEYS)
    return GoldSource(kind=cfg['gold_kind'], location=cfg['gold_location'], dataset_version=cfg.get('dataset_version'),
                      delta_version=cfg.get('delta_version'), strict=bool(cfg.get('strict', False)),
                      expected_adjustment_version=cfg.get('expected_adjustment_version'))


def leak_checks(model, assign: pd.DataFrame) -> dict:
    """보정 잔차가 평가 구간 날짜를 쓰지 않았는지, 구간 순서가 맞는지 확인합니다."""
    ev0 = assign.loc[assign['split'] == 'evaluation', 'trading_date'].min()
    ok_resid = bool(model.residuals.index.max() < ev0)
    ok_train = bool(pd.Timestamp(model.card['train_end']) < pd.Timestamp(model.card['calibration']['start']))
    return {'residuals_before_evaluation': ok_resid, 'train_before_calibration': ok_train,
            'passed': ok_resid and ok_train}


def run_train_validate(cfg: dict, *, spark=None, extra_metrics: dict | None = None) -> dict:
    _need(cfg, SOURCE_KEYS + TRAIN_KEYS)
    work = Path(cfg['work_dir'])
    df, report, info = read_gold(source_from_cfg(cfg), spark=spark)
    fs = FT.build_features(df)
    samples, sample_meta = BS.build_samples(df, fs)
    scale = TR.market_scale_from_gold(df)
    model, assign = TR.train_model(samples, scale)

    model_dir = work / 'model'
    TR.write_model(model, assign, scale, model_dir, sample_meta)

    leaks = leak_checks(model, assign)
    metrics = {'leak_tests_pass': leaks['passed'], 'gold_load_errors': len(report.errors),
               **(extra_metrics or {})}
    criteria = MP.load_criteria(cfg['criteria_path']) if cfg.get('criteria_path') else None
    gate = MP.check_gates(metrics, criteria)

    d = with_scales(samples, scale)
    train = SP.select_split(d, assign, 'train')
    support = MP.support_range(train, list(INPUT_ORDER))
    versions = {'model_version': MODEL_VERSION, 'feature_version': FT.FEATURE_VERSION,
                'target_version': TG.TARGET_VERSION, 'splits_version': SP.SPLITS_VERSION,
                'dataset_version': sample_meta.get('dataset_version'), 'delta_version': cfg.get('delta_version')}
    pkg = MP.build_package(model_dir, work / 'packages' / cfg['package_name'], feature_order=list(INPUT_ORDER),
                           versions=versions, support=support, gate=gate, source=info)
    verified = MP.verify_package(pkg['dir'])

    mlflow_info = None
    if cfg.get('mlflow_experiment') and cfg.get('mlflow_model_name'):
        mlflow_info = MP.log_package_to_mlflow(pkg['dir'], experiment=cfg['mlflow_experiment'],
                                               model_name=cfg['mlflow_model_name'],
                                               tracking_uri=cfg.get('mlflow_tracking_uri'),
                                               register=bool(cfg.get('mlflow_register', True)))
    out = {'package': pkg, 'verified': verified, 'gate': gate.to_dict(), 'leak_checks': leaks,
           'gold': info, 'mlflow': mlflow_info}
    (work / 'train_validate_result.json').write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str),
                                                     encoding='utf8')
    return out


def export_frame(fs) -> pd.DataFrame:
    """내보낼 표: 키 + 수치 피처 + 사용 가능/시점검증 플래그(0/1)."""
    a = fs.asset_features
    num = [c for c in a.columns if pd.api.types.is_float_dtype(a[c])]
    f = a[['trading_date', 'asset_id', *num]].copy()
    f['row_usable'] = a['row_usable'].astype('float64')
    f['point_in_time_verified'] = a['point_in_time_verified'].astype('float64')
    return f


def run_export(cfg: dict, conn, *, spark=None) -> dict:
    _need(cfg, SOURCE_KEYS)
    df, report, info = read_gold(source_from_cfg(cfg), spark=spark)
    fs = FT.build_features(df)
    frame = export_frame(fs)
    as_of = str(df['trading_date'].max())[:10]
    source_ref = f"{cfg['gold_location'] if cfg['gold_kind'] != 'pandas' else 'dataframe'}@delta_v{cfg.get('delta_version')}"
    res = RE.export_release(conn, frame, dataset_version=str(fs.meta['dataset_version']),
                            feature_version=FT.FEATURE_VERSION, as_of=as_of, source_ref=source_ref,
                            pointer=cfg.get('pointer', RE.POINTER_DEFAULT),
                            paramstyle=cfg.get('paramstyle', 'format'), dialect=cfg.get('dialect', 'postgres'),
                            dry_run=bool(cfg.get('dry_run', False)))
    return {**res, 'gold': info}
