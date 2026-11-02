"""Build contract-compatible research data from verified official-source local inputs.

Usage: python build_research_gold.py --input INPUT_DIRECTORY --output OUTPUT_DIRECTORY
Requires pandas, pyarrow and jsonschema. Does not access Azure or train a model.
"""
import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from jsonschema import Draft202012Validator, FormatChecker

FACTORS = ['usdkrw', 'us_treasury_10y', 'korea_3y', 'wti', 'vix']


def build(source, destination):
    source, destination = Path(source), Path(destination)
    contract = Path(__file__).resolve().parents[2] / 'contracts/daily/schema.json'
    schema = json.loads(contract.read_text(encoding='utf8'))
    stocks = pd.read_parquet(source / 'stock_daily.parquet')
    market = pd.read_parquet(source / 'market_daily.parquet')
    macro = pd.read_parquet(source / 'macro_daily.parquet')
    assert set(stocks.source) <= {'KRX_WEB', 'KRX_API'}
    assert set(market.source) <= {'KRX_WEB', 'KRX_API'}
    assert set(macro.source) <= {'ECOS', 'FRED'}
    assert not stocks.duplicated(['date', 'asset_id']).any()
    assert not market.duplicated('date').any()
    assert stocks.asset_id.nunique() == 20
    assert stocks.adjustment_basis.eq('2026-10-16').all()
    for df in [stocks, market, macro]:
        df['date'] = pd.to_datetime(df.date)
    common = market[['date', 'close']].rename(columns={'close': 'kospi_close'}).sort_values('date')
    for factor in FACTORS:
        obs = macro[macro.series.eq(factor)].dropna(subset=['value']).sort_values('date')
        assert obs.source.eq('ECOS' if factor == 'korea_3y' else 'FRED').all()
        assert not obs.date.duplicated().any()
        obs = obs[['date', 'value']].rename(columns={'date': factor+'_observation_date', 'value': factor})
        common = pd.merge_asof(common, obs, left_on='date', right_on=factor+'_observation_date',
                               direction='backward', allow_exact_matches=False, tolerance=pd.Timedelta(days=7))
        valid = common[factor+'_observation_date'].notna()
        assert (common.loc[valid, factor+'_observation_date'] < common.loc[valid, 'date']).all()
        common[factor+'_observed_at'] = None
        common[factor+'_available_at'] = None
    data = stocks.merge(common, on='date', how='left', validate='many_to_one')
    data['trading_date'] = data.date
    data['sector_id'] = None
    data['instrument_kind'] = 'stock'
    data['price_basis'] = 'adjusted'
    data['adjustment_version'] = 'krx-20261016-verified-bridge-through-20261030'
    data['price_available_at'] = None
    data['dataset_version'] = 'official20-gold-v1.1-research-20261102'
    data['source_ref'] = 'metadata.json'
    data['is_mock'] = False
    data['quality_status'] = 'valid'
    required_values = ['close', 'volume', 'kospi_close'] + FACTORS
    data.loc[data[required_values].isna().any(axis=1), 'quality_status'] = 'missing'
    data.loc[data.volume.eq(0) | data.close.le(0), 'quality_status'] = 'quarantined'
    columns = schema['items']['required']
    data = data[columns].sort_values(['trading_date', 'asset_id']).reset_index(drop=True)
    fields = []
    for key in columns:
        if key == 'trading_date' or key.endswith('_observation_date'):
            dtype = pa.date32()
        elif key.endswith('_at'):
            dtype = pa.timestamp('us', tz='UTC')
        elif key in ['close', 'volume', 'kospi_close'] + FACTORS:
            dtype = pa.float64()
        elif key == 'is_mock':
            dtype = pa.bool_()
        else:
            dtype = pa.string()
        fields.append(pa.field(key, dtype))
    table = pa.Table.from_pandas(data, schema=pa.schema(fields), preserve_index=False)
    validator = Draft202012Validator(schema['items'], format_checker=FormatChecker())
    for row in table.to_pylist():
        serial = {k: v.isoformat().replace('+00:00', 'Z') if hasattr(v, 'isoformat') else v for k, v in row.items()}
        validator.validate(serial)
    assert not data.duplicated(['dataset_version', 'trading_date', 'asset_id']).any()
    assert data.groupby('trading_date')[['kospi_close'] + FACTORS].nunique(dropna=False).le(1).all().all()
    destination.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, destination/'gold_stress_daily.parquet', compression='snappy')
    assert pq.read_table(destination/'gold_stress_daily.parquet').equals(table)
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    metadata = {
        'schema_version': '1.1', 'schema_sha256': digest(contract), 'rows': len(data),
        'assets': sorted(data.asset_id.unique()), 'columns': columns,
        'start': str(data.trading_date.min().date()), 'end': str(data.trading_date.max().date()),
        'is_mock': False, 'strict_point_in_time_verified': False,
        'alignment': 'previous non-null observation date; strictly before trading_date; maximum age 7 calendar days; publication times unknown',
        'sources': {'prices': 'KRX', 'korea_3y': 'ECOS 817Y002/010200000/D',
                    'usdkrw': 'FRED DEXKOUS', 'us_treasury_10y': 'FRED DGS10', 'wti': 'FRED DCOILWTICO', 'vix': 'FRED VIXCLS'},
        'inputs': {p.name: {'sha256': digest(p)} for p in [source/'stock_daily.parquet', source/'market_daily.parquet', source/'macro_daily.parquet']},
        'data_sha256': digest(destination/'gold_stress_daily.parquet'),
        'null_counts': {k: int(v) for k, v in data.isna().sum().items()},
        'quality_counts': {k: int(v) for k, v in data.quality_status.value_counts().items()},
        'checks': ['every row matches JSON schema', 'unique primary key', 'same common values per date', 'source whitelist', 'prior observation dates', 'Parquet roundtrip'],
        'limitations': ['Research only: unknown publication and price availability timestamps.',
                        'Current 20-security universe has survivorship and historical market membership limitations.',
                        'Zero-volume observations are quarantined, not assumed confirmed suspensions.',
                        'No interpolation; nonpositive WTI must not be used in percentage-change features.',
                        'No labels or features supplied; ML must implement calendar-aligned targets and exclusion rules.'],
    }
    (destination/'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    (destination/'README.txt').write_text(
        '학습 개발용 실제 관측 데이터입니다. gold_stress_daily.parquet 한 파일을 읽으세요.\n'
        '20종목, 계약 v1.1의 34개 컬럼입니다. KRX 주가와 지수, ECOS 한국 3년 금리, FRED 4개 지표를 포함합니다.\n'
        'ML에서 날짜별 피처와 종목별 5거래일 정답을 생성하세요. 다른 종목 행을 섞어 shift하지 마세요.\n'
        '공개 시각이 NULL인 과거 자료는 연구용입니다. 독립 블라인드 또는 엄격한 시점 검증 완료 데이터가 아닙니다.\n'
        'quality_status는 값의 품질입니다. valid도 공개 시각 검증을 뜻하지 않습니다.\n'
        '출처, 결측, 검사 결과와 제한은 metadata.json에 있습니다.\n', encoding='utf8')
    print(json.dumps({'rows':len(data), 'columns':len(columns), 'assets':data.asset_id.nunique(), 'status':'validated'}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    build(args.input, args.output)
