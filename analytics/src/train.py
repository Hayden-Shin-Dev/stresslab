"""B 모델 학습: 학습 구간으로 Ridge를 맞추고 보정 구간으로 잔차를 만듭니다. (analytics/README.md 9절)

    python analytics/src/train.py          # VS Code ▶ 실행도 같습니다
    -> analytics/outputs/model/{model.joblib, model_card.json, market_scale.parquet/.csv, calibration_residuals.csv}

필요한 것: analytics/outputs/samples/training_samples.parquet (build_samples.py), Gold 원본(load_gold 기본 경로).
평가 구간(2023~)은 읽지도 쓰지도 않습니다. 표준화, 학습, 보정 모두 splits.py가 나눈 구간만 씁니다.
기존 Ridge와 같은 수식이지만 같은 숫자를 낸다는 증거(옛 패널 대조)는 아직 없습니다. model_card의 reproduction_status를 보세요.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd

try:
    from distribution import (ALPHA, COLUMN_MAP_TO_REFERENCE, INPUT_ORDER, MAX_DRAWS, MODEL_VERSION, REFERENCE,
                              ScaledRidgeModel, kospi_scale_table, with_scales)
    from features import ANALYTICS_ROOT, market_table
    from load_gold import DEFAULT_SOURCE, load_gold
    from splits import DEFAULT_SAMPLES, PROTOCOL_ID, SPLITS_VERSION, assign_splits, select_split
except ImportError:  # 패키지로 가져올 때
    from .distribution import (ALPHA, COLUMN_MAP_TO_REFERENCE, INPUT_ORDER, MAX_DRAWS, MODEL_VERSION, REFERENCE,
                               ScaledRidgeModel, kospi_scale_table, with_scales)
    from .features import ANALYTICS_ROOT, market_table
    from .load_gold import DEFAULT_SOURCE, load_gold
    from .splits import DEFAULT_SAMPLES, PROTOCOL_ID, SPLITS_VERSION, assign_splits, select_split

DEFAULT_OUT = ANALYTICS_ROOT / 'outputs/model'


def market_scale_from_gold(df: pd.DataFrame) -> pd.DataFrame:
    """날짜별 scale_kospi. build_samples와 같은 입력(mock 제외)을 씁니다."""
    return kospi_scale_table(market_table(df[~df['is_mock']].reset_index(drop=True)))


def train_model(samples: pd.DataFrame, kospi_scale: pd.DataFrame, *, nonoverlap_calibration: bool = True):
    """samples: build_samples 결과 전체. 반환: (model, assignments). 학습/보정 구간만 사용."""
    a = assign_splits(samples)
    d = with_scales(samples, kospi_scale)
    train = select_split(d, a, 'train')
    cal = select_split(d, a, 'calibration')
    model = ScaledRidgeModel().fit(train).calibrate(cal, nonoverlap=nonoverlap_calibration)
    # 모델이 없는 종목은 사유와 함께 기록합니다(학습 행이 한 건도 없는 종목 포함).
    for asset in sorted(set(samples['asset_id'].unique()) - set(model.models)):
        if asset not in model.card['ineligible_assets']:
            first = samples.loc[(samples['asset_id'] == asset) & samples['train_ready'], 'trading_date'].min()
            model.card['ineligible_assets'][asset] = (
                f'no_train_rows(학습 구간에 표본 없음; 첫 학습 가능 표본 {str(first)[:10]})')
    return model, a


def build_card(model: ScaledRidgeModel, a: pd.DataFrame, sample_meta: dict | None) -> dict:
    return {
        'model_version': MODEL_VERSION,
        'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': 'research_comparison_model_not_approved',
        'reproduction_status': 'code_equivalent_only',
        'reproduction_note': ('기존 코드와 같은 입력에서 같은 표본이 나오는 것만 확인했습니다. 옛 official_panel/predictions와의 '
                              '숫자 대조는 하지 않았습니다. 재현 완료라고 부르지 않습니다.'),
        'reference': REFERENCE,
        'algorithm': {'model': 'StandardScaler + Ridge', 'alpha': ALPHA, 'one_model_per_asset': True,
                      'shock_normalization': 'shock / max(scale_kospi, 0.05) (충격 4개)',
                      'target_normalization': 'y / max(scale_asset, 0.05), 예측에 scale_asset을 다시 곱함',
                      'scale': 'sqrt((var20 + var60)/2 * 5), 일간 로그수익률 % 분산',
                      'residual_scale_up_down': [1.0, 1.0], 'max_draws': MAX_DRAWS,
                      'draw_rule': '같은 날짜 잔차 행을 균등 간격으로 선택(요청 종목이 모두 있는 날짜만)'},
        'input_order': INPUT_ORDER, 'column_map_to_reference': COLUMN_MAP_TO_REFERENCE,
        'known_differences_from_reference': [
            '잔차 행을 종목별로 따로 뽑지 않고 날짜 기준으로 맞춤',
            'kospi_vol20 값은 우리 정의(연율화한 단순수익률 변동성); 변동성 척도 scale_kospi는 기존과 같은 정의로 별도 계산',
            '데이터가 Gold 20종목 + 연구용 공개 시각 미확인 자료. 옛 패널(18종목)과 같지 않음'],
        'splits': {'splits_version': SPLITS_VERSION, 'protocol_id': PROTOCOL_ID,
                   'rows_by_split': {k: int(v) for k, v in a['split'].value_counts().items()},
                   'evaluation_used': False},
        'dataset_version': (sample_meta or {}).get('dataset_version'),
        'point_in_time': (sample_meta or {}).get('point_in_time'),
        'assets_modeled': model.assets, **model.card,
        'caveats': ['기존 검증(RESULT.md)에서 상태 피처의 성능 이득은 입증되지 않았습니다.',
                    '극단 충격에서 반전, 꼬리는 보수적이라고 기록되어 있습니다.',
                    '충격 입력은 학습 충격 범위 안에서만 해석하세요(predict.py가 범위 밖을 표시).'],
    }


def write_model(model, a, scale_table, out_dir, sample_meta=None) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {'model': out / 'model.joblib', 'card': out / 'model_card.json',
             'market_scale': out / 'market_scale.parquet', 'market_scale_csv': out / 'market_scale.csv',
             'residuals_csv': out / 'calibration_residuals.csv'}
    joblib.dump(model.to_state(), paths['model'])
    paths['card'].write_text(json.dumps(build_card(model, a, sample_meta), ensure_ascii=False, indent=2,
                                        default=str) + '\n', encoding='utf8')
    scale_table.to_parquet(paths['market_scale'], index=False)
    scale_table.to_csv(paths['market_scale_csv'], index=False)
    r = model.residuals.copy()
    r.index.name = 'trading_date'
    r.to_csv(paths['residuals_csv'])
    return {k: str(v) for k, v in paths.items()}


def main(argv=None):
    p = argparse.ArgumentParser(description='B 모델(Ridge) 학습')
    p.add_argument('--samples', default=str(DEFAULT_SAMPLES))
    p.add_argument('--gold', default=str(DEFAULT_SOURCE))
    p.add_argument('--out', default=str(DEFAULT_OUT))
    p.add_argument('--all-calibration-rows', action='store_true',
                   help='보정에 겹치는 5거래일 구간까지 모두 사용(기본은 기존 검증처럼 겹치지 않는 구간만)')
    a = p.parse_args(argv)
    samples = pd.read_parquet(a.samples)
    scale = market_scale_from_gold(load_gold(a.gold))
    model, assign = train_model(samples, scale, nonoverlap_calibration=not a.all_calibration_rows)
    meta_path = Path(a.samples).with_name('samples_metadata.json')
    sample_meta = json.loads(meta_path.read_text(encoding='utf8')) if meta_path.exists() else None
    paths = write_model(model, assign, scale, a.out, sample_meta)
    c = model.card
    print(json.dumps({'files': paths, 'assets_modeled': len(model.assets), 'ineligible_assets': c['ineligible_assets'],
                      'train': [c['train_start'], c['train_end']], 'calibration': c['calibration']},
                     ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
