"""학습, 보정, 평가 기간을 시간순으로 나눕니다. (analytics/README.md 7절)

    python analytics/src/splits.py            # VS Code ▶ 실행도 같습니다 (build_samples.py를 먼저 실행)
    -> analytics/outputs/splits/split_assignments.parquet   (날짜, 종목)마다 어느 구간인지
       analytics/outputs/splits/split_dates.csv              구간별 날짜 목록
       analytics/outputs/splits/split_asset_counts.csv       종목별 표본 수
       analytics/outputs/splits/splits_metadata.json
       analytics/evaluation/protocol.json                    평가 규약(기간, 규칙, 공통 평가 키, 노출 기록)

원칙
  - 행을 섞지 않습니다. 과거 학습 -> 분포 보정 -> 이후 평가 순입니다.
  - 표준화와 모델 학습에는 학습 구간만 씁니다. 보정 구간은 분포 보정에만, 평가 구간은 평가에만 씁니다.
  - 정답 종료일(target_date, t+5)이 구간 마감일 이후이면 그 행을 제외(purged)합니다.
    학습 정답이 보정 구간의 가격을 이미 포함하거나, 보정 정답이 평가 구간의 가격을 포함하는 것을 막습니다.
    공개 시각이 NULL인 연구 자료라서 "정답을 확인할 수 있는 시각"은 정답 종료일의 종가로 보수적으로 잡습니다.
  - 인접한 날짜의 5거래일 구간은 겹칩니다. overlap_block(달력 위치 // 5)과 독립 블록 수를 함께 남겨
    행 수를 독립 사건 수처럼 쓰지 않게 합니다.
  - 비교 모델은 evaluation 구간의 같은 (날짜, 종목)을 평가합니다. 키 목록의 해시를 protocol.json에 기록합니다.
  - 평가 결과를 보고 모델을 수정했다면 mark_evaluation_exposed()로 기록합니다. 그 평가 기간은 더 이상
    독립 블라인드 테스트가 아닙니다.

기본 경계(학습 2020년 이전, 보정 2020~2022년, 평가 2023년 이후)는 기존 ECOS 실험과 같은 연도 구분입니다.
기존 실험은 선정된 184개 시점이었지만 여기서는 기간의 모든 가능한 날짜를 씁니다. 같은 실험이라고 부르지 않습니다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from features import ANALYTICS_ROOT
    from targets import HORIZON
except ImportError:  # 패키지로 가져올 때
    from .features import ANALYTICS_ROOT
    from .targets import HORIZON

SPLITS_VERSION = 'splits-v1.0'
PROTOCOL_ID = 'chrono-train-calibration-evaluation-v1'
DEFAULT_SAMPLES = ANALYTICS_ROOT / 'outputs/samples/training_samples.parquet'
DEFAULT_OUT = ANALYTICS_ROOT / 'outputs/splits'
PROTOCOL_PATH = ANALYTICS_ROOT / 'evaluation/protocol.json'
DEFAULT_CALIBRATION_START = '2020-01-01'
DEFAULT_EVALUATION_START = '2023-01-01'
USED_SPLITS = ['train', 'calibration', 'evaluation']


# ---------------------------------------------------------------- 구간 배정
def assign_splits(samples: pd.DataFrame, calibration_start=DEFAULT_CALIBRATION_START,
                  evaluation_start=DEFAULT_EVALUATION_START, horizon: int = HORIZON) -> pd.DataFrame:
    """samples: build_samples 결과(trading_date, target_date, asset_id, train_ready, exclude_reasons ...).

    반환: (날짜, 종목)마다 split(train/calibration/evaluation/purged/excluded)과 사유, overlap_block.
    """
    cal0, eval0 = pd.Timestamp(calibration_start), pd.Timestamp(evaluation_start)
    if not cal0 < eval0:
        raise ValueError('보정 시작일은 평가 시작일보다 앞이어야 합니다.')
    if samples.duplicated(['trading_date', 'asset_id']).any():
        raise ValueError('(trading_date, asset_id) 중복이 있습니다.')

    t, tgt, ready = samples['trading_date'], samples['target_date'], samples['train_ready'].astype(bool)
    in_train, in_cal, in_eval = ready & (t < cal0), ready & (t >= cal0) & (t < eval0), ready & (t >= eval0)
    ends_before_cal, ends_before_eval = tgt < cal0, tgt < eval0       # NaT는 False

    split = np.select(
        [~ready, in_train & ends_before_cal, in_train, in_cal & ends_before_eval, in_cal, in_eval],
        ['excluded', 'train', 'purged', 'calibration', 'purged', 'evaluation'], default='excluded')
    reason = np.select(
        [~ready, in_train & ~ends_before_cal, in_cal & ~ends_before_eval],
        [samples['exclude_reasons'].to_numpy(dtype=object), 'label_known_after_train_cutoff',
         'label_known_after_calibration_cutoff'], default='')

    calendar = pd.Index(sorted(t.unique()))
    block = pd.Series(np.arange(len(calendar)) // horizon, index=calendar)
    out = samples[['dataset_version', 'trading_date', 'target_date', 'asset_id']].copy()
    out['split'], out['split_reason'] = split, reason
    out['overlap_block'] = t.map(block).astype(int).to_numpy()
    out = out.sort_values(['trading_date', 'asset_id']).reset_index(drop=True)
    check_assignments(out, cal0, eval0)
    return out


def check_assignments(a: pd.DataFrame, cal0: pd.Timestamp, eval0: pd.Timestamp) -> None:
    """시간 경계와 정답 종료일을 검사합니다. 어기면 멈춥니다."""
    tr, ca, ev = (a[a['split'] == s] for s in USED_SPLITS)
    for name, part in zip(USED_SPLITS, (tr, ca, ev)):
        if part.empty:
            raise ValueError(f'{name} 구간에 표본이 없습니다. 경계 날짜를 확인하세요.')
    assert tr['target_date'].max() < cal0, '학습 정답이 보정 시작일 이후에 끝납니다.'
    assert ca['target_date'].max() < eval0, '보정 정답이 평가 시작일 이후에 끝납니다.'
    assert tr['trading_date'].max() < ca['trading_date'].min() <= ca['trading_date'].max() < ev['trading_date'].min()
    assert (ca['trading_date'] >= cal0).all() and (ev['trading_date'] >= eval0).all()


def select_split(samples: pd.DataFrame, assignments: pd.DataFrame, name: str) -> pd.DataFrame:
    """샘플 표에서 한 구간의 행만 가져옵니다. 표준화와 학습에는 select_split(..., 'train')만 쓰세요."""
    assert name in USED_SPLITS
    keys = assignments.loc[assignments['split'] == name, ['trading_date', 'asset_id']]
    return samples.merge(keys, on=['trading_date', 'asset_id'], how='inner', validate='one_to_one')


def evaluation_keys(assignments: pd.DataFrame) -> pd.DataFrame:
    """모든 비교 모델이 평가해야 하는 (날짜, 종목) 목록."""
    return (assignments.loc[assignments['split'] == 'evaluation', ['trading_date', 'asset_id']]
            .sort_values(['trading_date', 'asset_id']).reset_index(drop=True))


def keys_sha256(keys: pd.DataFrame, extra: pd.Series | None = None) -> str:
    lines = keys['trading_date'].dt.strftime('%Y-%m-%d') + '|' + keys['asset_id'].astype(str)
    if extra is not None:
        lines = extra.astype(str) + '|' + lines
    return hashlib.sha256('\n'.join(lines.tolist()).encode('utf8')).hexdigest()


# ---------------------------------------------------------------- 산출 표
def split_dates_table(a: pd.DataFrame) -> pd.DataFrame:
    used = a[a['split'].isin(USED_SPLITS)]
    return (used.groupby(['split', 'trading_date'])
            .agg(assets=('asset_id', 'nunique'), overlap_block=('overlap_block', 'first')).reset_index()
            .assign(split=lambda d: pd.Categorical(d['split'], USED_SPLITS, ordered=True))
            .sort_values(['split', 'trading_date']).assign(split=lambda d: d['split'].astype(str))
            .reset_index(drop=True))


def asset_counts_table(a: pd.DataFrame) -> pd.DataFrame:
    used = a[a['split'].isin(USED_SPLITS)]
    return (used.groupby(['asset_id', 'split'])
            .agg(rows=('trading_date', 'size'), independent_blocks=('overlap_block', 'nunique'),
                 first_date=('trading_date', 'min'), last_date=('trading_date', 'max')).reset_index()
            .assign(split=lambda d: pd.Categorical(d['split'], USED_SPLITS, ordered=True))
            .sort_values(['asset_id', 'split']).assign(split=lambda d: d['split'].astype(str))
            .reset_index(drop=True))


def summarize(a: pd.DataFrame) -> dict:
    out = {}
    for name in USED_SPLITS:
        part = a[a['split'] == name]
        out[name] = {'rows': int(len(part)), 'dates': int(part['trading_date'].nunique()),
                     'assets': int(part['asset_id'].nunique()),
                     'start': str(part['trading_date'].min())[:10], 'end': str(part['trading_date'].max())[:10],
                     'last_label_end': str(part['target_date'].max())[:10],
                     'independent_blocks': int(part['overlap_block'].nunique())}
    out['purged_rows'] = {k: int(v) for k, v in a.loc[a['split'] == 'purged', 'split_reason'].value_counts().items()}
    out['excluded_rows'] = int((a['split'] == 'excluded').sum())
    return out


# ---------------------------------------------------------------- 규약 파일
def build_protocol(a: pd.DataFrame, sample_meta: dict, calibration_start, evaluation_start,
                   previous: dict | None = None) -> dict:
    keys = evaluation_keys(a)
    dates = split_dates_table(a)
    exposures = list((previous or {}).get('blind_test', {}).get('evaluation_exposures', []))
    return {
        'protocol_id': PROTOCOL_ID, 'splits_version': SPLITS_VERSION,
        'created_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'data': {k: sample_meta.get(k) for k in
                 ['dataset_version', 'feature_version', 'target_version', 'market_state_sha256']},
        'periods': {
            'train': {'decision_dates': f'첫 학습 가능일 ~ {calibration_start} 이전', 'label_end': f'{calibration_start} 이전'},
            'calibration': {'decision_dates': f'{calibration_start} ~ {evaluation_start} 이전', 'label_end': f'{evaluation_start} 이전'},
            'evaluation': {'decision_dates': f'{evaluation_start} 이후', 'label_end': '데이터 마지막 정답 종료일'},
        },
        'summary': summarize(a),
        'rules': [
            '행을 무작위로 섞지 않는다. 과거 학습, 분포 보정, 이후 평가 순이다.',
            '표준화 기준(평균, 표준편차)과 모델 학습에는 train 구간만 쓴다.',
            '분포 보정은 calibration 구간의 오차로만 하고, evaluation 구간은 평가에만 쓴다.',
            '정답 종료일(target_date)이 구간 마감일(다음 구간 시작일) 이후인 행은 purged로 제외한다.',
            '정답을 확인할 수 있는 시각은 공개 시각이 NULL인 연구 자료에서는 정답 종료일의 종가로 본다.',
            '인접 날짜의 5거래일 구간은 겹친다. 행 수가 아닌 independent_blocks로 독립 표본 수를 보고한다.',
            '비교 모델은 evaluation_universe의 같은 (날짜, 종목)을 평가하고, 결과에 keys_sha256을 함께 적는다.',
            '평가 결과를 보고 모델을 수정했다면 mark_evaluation_exposed()로 기록하며 그 기간은 독립 블라인드가 아니다.',
        ],
        'overlap': {'horizon_trading_days': HORIZON, 'block': '달력 위치 // 5',
                    'note': '같은 블록의 날짜는 정답 구간이 서로 겹친다.'},
        'evaluation_universe': {'rows': int(len(keys)), 'dates': int(keys['trading_date'].nunique()),
                                'assets': int(keys['asset_id'].nunique()), 'keys_sha256': keys_sha256(keys)},
        'split_dates_sha256': keys_sha256(dates[['trading_date']].assign(asset_id=''), dates['split']),
        'relation_to_ecos_experiment': {
            'same_experiment': False,
            'note': ('기존 ECOS 실험은 선정된 184개 시점이었다. 여기서는 각 기간의 모든 가능한 날짜를 쓰므로 '
                     '같은 실험이라고 부르지 않는다. 재현하려면 선정 날짜 목록과 데이터 버전이 같아야 한다.')},
        'point_in_time': sample_meta.get('point_in_time'),
        'blind_test': {
            'status': 'exposed_not_independent_blind' if exposures else 'not_exposed',
            'evaluation_exposures': exposures,
            'rule': '평가 구간 결과를 보고 모델, 피처, 하이퍼파라미터를 바꿨다면 기록한다. 기록 후에는 독립 블라인드 테스트가 아니다.'},
    }


def mark_evaluation_exposed(reason: str, path=PROTOCOL_PATH) -> dict:
    """평가 결과를 보고 모델을 수정했을 때 호출합니다. 기록은 protocol.json을 다시 만들어도 유지됩니다."""
    p = Path(path)
    protocol = json.loads(p.read_text(encoding='utf8'))
    protocol['blind_test']['evaluation_exposures'].append(
        {'utc': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'reason': reason})
    protocol['blind_test']['status'] = 'exposed_not_independent_blind'
    p.write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    return protocol['blind_test']


# ---------------------------------------------------------------- 저장과 진입점
def write_splits(a: pd.DataFrame, protocol: dict, out_dir, protocol_path=PROTOCOL_PATH) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {'assignments': out / 'split_assignments.parquet', 'dates': out / 'split_dates.csv',
             'asset_counts': out / 'split_asset_counts.csv', 'metadata': out / 'splits_metadata.json',
             'protocol': Path(protocol_path)}
    a.to_parquet(paths['assignments'], index=False)
    split_dates_table(a).to_csv(paths['dates'], index=False, encoding='utf-8-sig', date_format='%Y-%m-%d')
    asset_counts_table(a).to_csv(paths['asset_counts'], index=False, encoding='utf-8-sig', date_format='%Y-%m-%d')
    meta = {k: protocol[k] for k in ['protocol_id', 'splits_version', 'created_utc', 'data', 'summary',
                                     'evaluation_universe', 'split_dates_sha256']}
    paths['metadata'].write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    paths['protocol'].parent.mkdir(parents=True, exist_ok=True)
    paths['protocol'].write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    return {k: str(v) for k, v in paths.items()}


def main(argv=None):
    p = argparse.ArgumentParser(description='학습/보정/평가 기간 분리')
    p.add_argument('samples', nargs='?', default=str(DEFAULT_SAMPLES),
                   help='build_samples.py 결과 (생략하면 analytics/outputs/samples/training_samples.parquet)')
    p.add_argument('--calibration-start', default=DEFAULT_CALIBRATION_START)
    p.add_argument('--evaluation-start', default=DEFAULT_EVALUATION_START)
    p.add_argument('--out', default=str(DEFAULT_OUT), help='저장 폴더 (기본: analytics/outputs/splits)')
    p.add_argument('--protocol', default=str(PROTOCOL_PATH), help='평가 규약 파일 (기본: analytics/evaluation/protocol.json)')
    a = p.parse_args(argv)

    src = Path(a.samples)
    if not src.exists():
        raise SystemExit(f'{src} 가 없습니다. 먼저 analytics/src/build_samples.py를 실행하세요.')
    samples = pd.read_parquet(src)
    meta_path = src.with_name('samples_metadata.json')
    sample_meta = json.loads(meta_path.read_text(encoding='utf8')) if meta_path.exists() else {}
    assignments = assign_splits(samples, a.calibration_start, a.evaluation_start)
    pp = Path(a.protocol)
    previous = json.loads(pp.read_text(encoding='utf8')) if pp.exists() else None
    protocol = build_protocol(assignments, sample_meta, a.calibration_start, a.evaluation_start, previous)
    paths = write_splits(assignments, protocol, a.out, pp)
    print(json.dumps({'files': paths, 'summary': protocol['summary'],
                      'evaluation_universe': protocol['evaluation_universe'],
                      'blind_test': protocol['blind_test']['status']}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
