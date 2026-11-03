"""gold_stress_daily(계약 v1.1)를 읽고 입력 검사(4절)를 수행합니다.

저장 위치(Parquet 파일, Parquet 폴더, Fabric Delta, pandas/Spark DataFrame)와 관계없이
같은 34개 컬럼과 타입의 표를 반환합니다. 이후 피처 계산 코드는 저장 위치를 몰라도 됩니다.

    from load_gold import load_gold, usable_mask
    df, report = load_gold("data/dev_gold/gold_stress_daily.parquet", return_report=True)
    keep = usable_mask(df, report.exclusions)      # 종목 행 단위 제외만 반영

실행: VS Code에서 이 파일을 열고 ▶(Run Python File)를 누르면 기본 경로로 검사합니다.
명령줄(경로 지정):
    python analytics/src/load_gold.py data/dev_gold/gold_stress_daily.parquet --out analytics/outputs/validation

검사 항목
  1. 34개 컬럼, 컬럼 타입, 숫자 단위, 날짜 타입. 종목코드 앞의 0을 보존합니다.
  2. (dataset_version, trading_date, asset_id) 중복
  3. 같은 날짜의 코스피, 거시 값, 관측 날짜가 종목마다 같은지
  4. 수정주가 버전 확인. 미수정 가격이 섞이면 오류
  5. mock, 격리된 가격, 결측, 거래정지 후보를 구분하고 제외 이유를 표로 남김

모드
  연구 모드(기본): 공개 시각이 NULL이어도 읽습니다. 시점 검증 미완료 상태를 보고서에 남깁니다.
  엄격 모드(strict=True): 공개 시각이 NULL인 행을 오류로 처리하고 제외 사유에 올립니다.
              결과 파일은 *_strict 이름으로 저장되어 연구 모드 결과를 덮어쓰지 않습니다.
  공개 시각을 수집 시각이나 예상 공표 일정으로 채우지 않습니다.

요구: pandas, numpy, pyarrow. Delta 폴더를 읽을 때만 deltalake가 추가로 필요합니다.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.api import types as pdt

__all__ = ['load_gold', 'exclusion_table', 'usable_mask', 'write_report',
           'GoldReport', 'Issue', 'GoldValidationError']

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA = REPO_ROOT / 'contracts/daily/schema.json'
DEFAULT_SOURCE = REPO_ROOT / 'data/dev_gold/gold_stress_daily.parquet'
ANALYTICS_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ANALYTICS_ROOT / 'outputs/validation'   # analytics 폴더 안에 저장
EXPECTED_COLUMN_COUNT = 34
KEY = ['dataset_version', 'trading_date', 'asset_id']
FACTORS = ['usdkrw', 'us_treasury_10y', 'korea_3y', 'wti', 'vix']
MARKET_VALUES = ['kospi_close'] + FACTORS
PRICED_KINDS = ['stock', 'sector_etf']   # 기업행사 조정이 의미 있는 종류. index는 제외합니다.
EXCLUSION_COLUMNS = ['trading_date', 'asset_id', 'dataset_version', 'reason', 'scope', 'detail']

# 단위 실수(소수 비율, bp, 천주 등)를 잡기 위한 느슨한 범위입니다. 시장 판단 기준이 아닙니다.
UNIT_BOUNDS = {
    'kospi_close': (50, 50_000),      # 지수
    'usdkrw': (300, 5_000),           # 원/달러
    'us_treasury_10y': (-1, 25),      # 연 %
    'korea_3y': (-1, 30),             # 연 %
    'wti': (-100, 500),               # 달러/배럴. 음수도 원본대로 보존
    'vix': (0, 200),                  # 지수
}


# ---------------------------------------------------------------- 결과 객체
@dataclass
class Issue:
    severity: str            # error | warning | info
    check: str
    message: str
    count: int = 0
    examples: list = field(default_factory=list)


@dataclass
class GoldReport:
    mode: str
    issues: list
    summary: dict
    exclusions: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=EXCLUSION_COLUMNS))

    @property
    def errors(self):
        return [i for i in self.issues if i.severity == 'error']

    @property
    def ok(self):
        return not self.errors

    def to_dict(self):
        return {'mode': self.mode, 'ok': self.ok, 'summary': self.summary,
                'issues': [i.__dict__ for i in self.issues]}


class GoldValidationError(ValueError):
    def __init__(self, report: GoldReport):
        self.report = report
        lines = [f'[{i.check}] {i.message} ({i.count}건) 예: {i.examples}' for i in report.errors]
        super().__init__('Gold 입력 검사 실패\n' + '\n'.join(lines))


class _Checker:
    def __init__(self, labels=None):
        self.labels = labels
        self.issues: list[Issue] = []

    def note(self, severity, check, message, count=0, examples=None):
        self.issues.append(Issue(severity, check, message, int(count), list(examples or [])[:5]))

    def flag(self, severity, check, message, mask):
        n = int(mask.sum())
        if n:
            examples = self.labels.loc[mask[mask].index].head(5).tolist() if self.labels is not None else []
            self.note(severity, check, message, n, examples)


# ---------------------------------------------------------------- 읽기
def _read(source) -> pd.DataFrame:
    if hasattr(source, 'toPandas'):                      # Fabric 노트북의 Spark DataFrame
        return source.toPandas()
    if isinstance(source, pd.DataFrame):
        return source.copy()
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(path)
    if path.is_dir() and (path / '_delta_log').is_dir():  # Delta 테이블 폴더
        try:
            from deltalake import DeltaTable
        except ImportError as exc:
            raise ImportError('Delta 폴더를 읽으려면 deltalake가 필요합니다: pip install deltalake. '
                              'Fabric 노트북에서는 spark.read.format("delta").load(...)를 넘겨도 됩니다.') from exc
        return DeltaTable(str(path)).to_pandas()
    return pd.read_parquet(path)                         # 파일 또는 Parquet 폴더


def _contract(schema_path=None):
    schema = json.loads(Path(schema_path or DEFAULT_SCHEMA).read_text(encoding='utf8'))
    item = schema['items']
    return list(item['required']), item['properties']


def _kind(spec):
    types = spec['type'] if isinstance(spec['type'], list) else [spec['type']]
    base = [t for t in types if t != 'null'][0]
    fmt = spec.get('format')
    if base == 'string' and fmt == 'date':
        return 'date', 'null' in types
    if base == 'string' and fmt == 'date-time':
        return 'timestamp', 'null' in types
    return {'number': 'float', 'boolean': 'bool'}.get(base, 'string'), 'null' in types


# ---------------------------------------------------------------- 1. 컬럼, 타입, 단위
def _coerce(raw: pd.DataFrame, columns, props, chk: _Checker) -> pd.DataFrame:
    out = {}
    for name in columns:
        spec, (kind, nullable) = props[name], _kind(props[name])
        s = raw[name]
        if kind == 'date':
            ts = pd.to_datetime(s, errors='coerce')
            if getattr(ts.dt, 'tz', None) is not None:
                ts = ts.dt.tz_localize(None)
            chk.flag('error', 'type_date', f'{name}: 날짜로 읽을 수 없는 값', ts.isna() & s.notna())
            chk.flag('error', 'type_date', f'{name}: 날짜에 시각이 섞여 있음', ts.notna() & (ts != ts.dt.normalize()))
            col = ts
        elif kind == 'timestamp':
            if pdt.is_datetime64_dtype(s) and s.notna().any():
                chk.note('error', 'type_timestamp', f'{name}: 시간대 없는 타임스탬프입니다. UTC로 저장해야 합니다.', int(s.notna().sum()))
            elif s.dtype == object and s.notna().any():
                text = s.dropna().astype(str)
                chk.flag('error', 'type_timestamp', f'{name}: 문자열 시각이 UTC(Z 또는 오프셋)로 끝나지 않음',
                         ~text.str.contains(r'(?:Z|[+-]\d\d:?\d\d)$').reindex(s.index, fill_value=True) & s.notna())
            ts = pd.to_datetime(s, utc=True, errors='coerce')
            chk.flag('error', 'type_timestamp', f'{name}: 시각으로 읽을 수 없는 값', ts.isna() & s.notna())
            col = ts
        elif kind == 'float':
            num = pd.to_numeric(s, errors='coerce')
            chk.flag('error', 'type_number', f'{name}: 숫자가 아닌 값', num.isna() & s.notna())
            col = num.astype('float64')
            chk.flag('error', 'type_number', f'{name}: inf 값', np.isinf(col))
        elif kind == 'bool':
            if s.dtype == bool:
                col = s
            else:
                mapped = s.map({True: True, False: False, 'true': True, 'false': False, 'True': True, 'False': False})
                chk.flag('error', 'type_bool', f'{name}: true/false가 아닌 값', mapped.isna())
                col = mapped.fillna(False).astype(bool)
        else:
            if name in ('asset_id', 'sector_id') and pdt.is_numeric_dtype(s) and not pdt.is_bool_dtype(s):
                chk.note('error', 'id_leading_zero', f'{name}: 숫자 타입입니다. 종목코드 앞의 0이 이미 사라졌을 수 있습니다.', int(s.notna().sum()))
                s = s.astype('string')
            is_text = s.map(lambda v: isinstance(v, str))
            chk.flag('error', 'type_string', f'{name}: 문자열이 아닌 값', s.notna() & ~is_text)
            col = s.astype(object).where(s.notna(), None)
        if not nullable:
            chk.flag('error', 'null_not_allowed', f'{name}: NULL 불가 컬럼에 NULL', col.isna())
        if kind == 'string':
            if 'minLength' in spec:
                chk.flag('error', 'min_length', f'{name}: 빈 문자열',
                         col.map(lambda v: v is not None and len(v) < spec['minLength']).astype(bool))
            if 'enum' in spec:
                chk.flag('error', 'enum', f'{name}: 허용값 {spec["enum"]} 밖의 값', col.notna() & ~col.isin(spec['enum']))
            if name in ('asset_id', 'sector_id'):
                chk.flag('error', 'id_whitespace', f'{name}: 앞뒤 공백', col.map(lambda v: v is not None and v != v.strip()).astype(bool))
        if kind == 'float':
            if 'minimum' in spec:
                chk.flag('error', 'range', f'{name}: {spec["minimum"]} 미만', col < spec['minimum'])
            if 'exclusiveMinimum' in spec:
                chk.flag('error', 'range', f'{name}: {spec["exclusiveMinimum"]} 이하', col <= spec['exclusiveMinimum'])
        out[name] = col
    return pd.DataFrame(out)[columns]


def _check_units(df, chk):
    for name, (lo, hi) in UNIT_BOUNDS.items():
        chk.flag('error', 'unit_range', f'{name}: 단위 의심 값(허용 범위 {lo}~{hi} 밖)', (df[name] < lo) | (df[name] > hi))
    for name in ['us_treasury_10y', 'korea_3y']:
        median = df[name].median()
        if pd.notna(median) and abs(median) < 0.2:
            chk.note('warning', 'unit_percent', f'{name}: 중앙값 {median:.3f}. 연 %가 아니라 소수 비율(0.03)일 수 있음')
    frac = df['volume'].notna() & (df['volume'] % 1 != 0)
    chk.flag('warning', 'unit_volume', 'volume: 정수가 아닌 값. 단위가 주가 아닐 수 있음', frac)


# ---------------------------------------------------------------- 2. 키 중복
def _check_key(df, chk):
    dup = df.duplicated(KEY, keep=False)
    if dup.any():
        n_keys = int(df[dup].drop_duplicates(KEY).shape[0])
        chk.flag('error', 'duplicate_key', f'(dataset_version, trading_date, asset_id) 중복 키 {n_keys}개', dup)


def _select_version(df, requested, chk):
    versions = sorted(df['dataset_version'].dropna().unique())
    if requested is not None:
        if requested not in versions:
            chk.note('error', 'dataset_version', f'dataset_version={requested!r}가 없음. 존재: {versions[:5]}')
            return df, requested
        return df[df['dataset_version'] == requested], requested
    if len(versions) > 1:
        chk.note('error', 'dataset_version', f'dataset_version {len(versions)}개가 섞여 있음 {versions[:5]}. dataset_version=을 지정하세요.')
        return df, None
    return df, (versions[0] if versions else None)


# ---------------------------------------------------------------- 3. 날짜별 공통 값
def _check_market_common(df, chk):
    common = MARKET_VALUES + [f'{f}_{s}' for f in FACTORS for s in ('observation_date', 'observed_at', 'available_at')]
    nun = df.groupby('trading_date')[common].nunique(dropna=False)
    for col in common:
        bad = nun.index[nun[col] > 1]
        if len(bad):
            chk.note('error', 'market_common_values', f'{col}: 같은 날짜인데 종목마다 값이 다른 날짜 {len(bad)}개',
                     len(bad), [str(d)[:10] for d in bad[:5]])


def _check_factor_dates(df, chk, max_age):
    td = df['trading_date']
    for f in FACTORS:
        od = df[f'{f}_observation_date']
        chk.flag('error', 'factor_date_pairing', f'{f}: 값과 관측일 중 하나만 NULL', df[f].notna() != od.notna())
        chk.flag('error', 'future_observation', f'{f}: 관측일이 trading_date보다 이후(미래 정보)', od > td)
        chk.flag('warning', 'same_day_observation', f'{f}: 관측일이 trading_date와 같음. 공개 시각 확인 필요', od == td)
        if max_age is not None:
            chk.flag('warning', 'stale_observation', f'{f}: 관측일이 {max_age}일보다 오래됨', (td - od).dt.days > max_age)
        chk.flag('error', 'available_before_observed', f'{f}: available_at이 observed_at보다 빠름',
                 df[f'{f}_available_at'] < df[f'{f}_observed_at'])
    avail_day = df['price_available_at'].dt.tz_convert('UTC').dt.tz_localize(None).dt.normalize()
    chk.flag('error', 'price_available_early', 'price_available_at이 trading_date보다 앞섬', avail_day < td)


# ---------------------------------------------------------------- 4. 수정주가
def _check_adjustment(df, chk, expected, allow_unadjusted, jump_threshold):
    priced = df['instrument_kind'].isin(PRICED_KINDS)
    mixed = df[priced].groupby('asset_id')['price_basis'].nunique()
    if (mixed > 1).any():
        bad = mixed.index[mixed > 1]
        chk.note('error', 'price_basis_mixed', f'수정/미수정/미확인 가격이 한 종목 이력에 섞임: {len(bad)}종목', len(bad), list(bad[:5]))
    chk.flag('warning' if allow_unadjusted else 'error', 'price_not_adjusted',
             'price_basis가 adjusted가 아님(미수정 또는 미확인 가격)', priced & df['price_basis'].ne('adjusted'))
    adj = df[priced & df['price_basis'].eq('adjusted')]
    chk.flag('error', 'adjustment_version_missing', 'adjusted인데 adjustment_version이 NULL', adj['adjustment_version'].isna())
    per_asset = adj.groupby('asset_id')['adjustment_version'].nunique()
    if (per_asset > 1).any():
        bad = per_asset.index[per_asset > 1]
        chk.note('error', 'adjustment_version_mixed', f'한 종목 이력에 adjustment_version이 둘 이상: {len(bad)}종목', len(bad), list(bad[:5]))
    versions = sorted(adj['adjustment_version'].dropna().unique())
    if expected is not None and any(v != expected for v in versions):
        chk.note('error', 'adjustment_version_expected', f'기대 버전 {expected!r}와 다름: {versions[:5]}')
    elif len(versions) > 1:
        chk.note('warning', 'adjustment_version_across_assets', f'종목마다 adjustment_version이 다름: {versions[:5]}')
    # 진단용입니다. 종목별로 인접 행만 비교하며 피처 계산이 아닙니다. 수정 전 가격이 섞이면 분할일에 큰 낙폭이 나타납니다.
    order = df.sort_values(['asset_id', 'trading_date'])
    px = order['close'].where(order['close'] > 0)
    jump = (px / px.groupby(order['asset_id']).shift(1) - 1).abs() > jump_threshold
    chk.flag('warning', 'price_jump', f'전일 대비 ±{jump_threshold:.0%} 초과 변동. 미수정 가격 혼입이나 거래재개 확인',
             (jump & priced.reindex(order.index)).reindex(df.index, fill_value=False))


# ---------------------------------------------------------------- 5. 품질 상태
def _check_quality(df, chk):
    q = df['quality_status']
    core_null = df[['close', 'volume', 'kospi_close']].isna().any(axis=1)
    chk.flag('error', 'status_value_mismatch', 'quality_status=valid인데 close/volume/kospi_close가 NULL', q.eq('valid') & core_null)
    chk.flag('warning', 'status_value_mismatch', 'quality_status=valid인데 거시 값이 NULL', q.eq('valid') & df[FACTORS].isna().any(axis=1))
    chk.flag('warning', 'zero_volume', 'volume=0 (거래정지 후보). 확정 정지로 단정하지 않음', df['volume'].eq(0) & q.ne('suspended'))
    chk.flag('warning', 'mock_rows', 'is_mock=true 행. 운영 적재와 학습에서 제외', df['is_mock'])
    chk.flag('warning', 'wti_nonpositive', 'wti가 0 이하. 원본은 보존하고 변화율 학습에서 제외', df['wti'] <= 0)


def _availability_needs(df):
    """(공개 시각 컬럼, 그 시각이 있어야 하는 행) 목록. 값이 있으면 공개 시각도 있어야 합니다."""
    return [('price_available_at', df['close'].notna())] + [(f'{f}_available_at', df[f].notna()) for f in FACTORS]


def _availability_unknown(df):
    needs = _availability_needs(df)
    mask = pd.Series(False, index=df.index)
    detail = pd.Series('', index=df.index, dtype=object)
    for col, need in needs:
        m = need & df[col].isna()
        mask |= m
        detail = detail + np.where(m, col + ',', '')
    return mask, detail.str.rstrip(',') if len(df) else detail


def _check_availability(df, chk, strict):
    unknown, _ = _availability_unknown(df)
    n = int(unknown.sum())
    if not n:
        return
    if strict:
        chk.flag('error', 'availability_unknown', '엄격 모드: 공개 시각이 NULL인 행(시점 검증 불가)', unknown)
    else:
        chk.note('warning', 'availability_unknown',
                 '공개 시각이 NULL인 행이 있음. 연구용이며 미래 정보 차단이 검증된 데이터가 아님', n, [])


# ---------------------------------------------------------------- 제외 이유 표
def _null_names(df, cols):
    out = pd.Series('', index=df.index, dtype=object)
    for c in cols:
        out = out + np.where(df[c].isna(), c + ',', '')
    return out.str.rstrip(',') if len(df) else out


def exclusion_table(df: pd.DataFrame, *, strict: bool = False) -> pd.DataFrame:
    """제외 사유를 (행, 사유) 단위로 나열합니다. 한 행이 여러 사유를 가질 수 있습니다.

    scope: asset_row     그 종목, 그 날짜 행 자체의 문제
           market_date   그 날짜의 시장 공통 값이 비어 모든 종목에 해당
           feature:wti   행은 유지하고 WTI 변화율 학습에서만 제외
    행을 지우지 않습니다. 다른 종목의 결측 때문에 정상 종목 행이 제외되지 않습니다.
    """
    parts = []
    q = df['quality_status']
    zero_volume = df['volume'].eq(0)

    def add(mask, reason, scope, detail):
        mask = mask.fillna(False).astype(bool)
        if not mask.any():
            return
        part = df.loc[mask, ['trading_date', 'asset_id', 'dataset_version']].copy()
        part['reason'], part['scope'] = reason, scope
        part['detail'] = detail[mask] if isinstance(detail, pd.Series) else detail
        parts.append(part)

    own_null = df['close'].isna() | df['volume'].isna()
    market_null = df[MARKET_VALUES].isna().any(axis=1)
    add(df['is_mock'], 'mock', 'asset_row', 'is_mock=true')
    add(q.eq('suspended'), 'suspended', 'asset_row', 'quality_status=suspended')
    add(zero_volume & q.ne('suspended'), 'suspension_candidate', 'asset_row', 'volume=0; quality_status=' + q)
    add(q.eq('quarantined') & ~zero_volume, 'quarantined_price', 'asset_row', 'quality_status=quarantined')
    add(own_null, 'missing_own_price', 'asset_row', _null_names(df, ['close', 'volume']))
    add(market_null, 'missing_market_factor', 'market_date', _null_names(df, MARKET_VALUES))
    add(q.eq('missing') & ~own_null & ~market_null, 'missing_status_unspecified', 'asset_row',
        'quality_status=missing이지만 NULL 컬럼 없음')
    add(df['price_basis'].ne('adjusted') & df['instrument_kind'].isin(PRICED_KINDS), 'not_adjusted', 'asset_row',
        'price_basis=' + df['price_basis'].astype(str))
    add(df['wti'] <= 0, 'wti_nonpositive', 'feature:wti', 'wti<=0')
    if strict:
        unknown, detail = _availability_unknown(df)
        add(unknown, 'availability_unknown', 'asset_row', 'NULL: ' + detail)
    if not parts:
        return pd.DataFrame(columns=EXCLUSION_COLUMNS)
    return (pd.concat(parts)[EXCLUSION_COLUMNS]
            .sort_values(['trading_date', 'asset_id', 'reason']).reset_index(drop=True))


def usable_mask(df: pd.DataFrame, exclusions: pd.DataFrame, scopes=('asset_row',)) -> pd.Series:
    """df와 같은 인덱스의 bool Series. 선택한 scope의 제외 사유가 없는 행이 True입니다."""
    ex = exclusions[exclusions['scope'].isin(scopes)]
    bad = pd.MultiIndex.from_frame(ex[KEY])
    rows = pd.MultiIndex.from_frame(df[KEY])
    return pd.Series(~rows.isin(bad), index=df.index)


# ---------------------------------------------------------------- 진입점
def load_gold(source, *, dataset_version: str | None = None, strict: bool = False,
              expected_adjustment_version: str | None = None, allow_unadjusted: bool = False,
              max_observation_age_days: int | None = 7, jump_threshold: float = 0.30,
              schema_path=None, raise_on_error: bool = True, return_report: bool = False):
    """Gold 표를 읽어 검사하고 계약 순서의 34개 컬럼으로 반환합니다.

    제외 대상 행도 지우지 않고 그대로 반환합니다. 제외 사유는 report.exclusions에 있습니다.
    5거래일 달력 계산이 행 삭제로 어긋나지 않게 하기 위함입니다.

    source: Parquet 파일/폴더, Delta 폴더, pandas 또는 Spark DataFrame
    dataset_version: 여러 버전이 들어 있는 테이블에서 사용할 버전
    strict: 공개 시각 NULL 행을 오류로 처리
    expected_adjustment_version: 지정하면 다른 수정주가 버전을 오류로 처리
    allow_unadjusted: True면 미수정 가격을 오류 대신 경고로 처리(권장하지 않음)
    max_observation_age_days: 거시 관측일이 이보다 오래되면 경고. None이면 검사하지 않음
    raise_on_error: 오류가 있으면 GoldValidationError를 발생시킴
    """
    raw = _read(source).reset_index(drop=True)
    columns, props = _contract(schema_path)
    mode = 'strict' if strict else 'research'
    structural = _Checker()
    if len(columns) != EXPECTED_COLUMN_COUNT:
        structural.note('error', 'columns', f'계약 스키마의 컬럼이 {len(columns)}개입니다. v1.1은 {EXPECTED_COLUMN_COUNT}개입니다.')
    missing = [c for c in columns if c not in raw.columns]
    extra = [c for c in raw.columns if c not in columns]
    if missing:
        structural.note('error', 'columns', f'없는 컬럼 {missing}', len(missing), missing)
    if extra:
        structural.note('error', 'columns', f'계약에 없는 컬럼 {extra}', len(extra), extra)
    if raw.empty:
        structural.note('error', 'empty', '행이 없습니다.')
    if structural.issues:
        raise GoldValidationError(GoldReport(mode, structural.issues, {'rows': len(raw)}))

    chk = _Checker((raw['trading_date'].astype(str).str[:10] + '/' + raw['asset_id'].astype(str)))
    df = _coerce(raw, columns, props, chk)
    _check_units(df, chk)
    _check_key(df, chk)
    df, version = _select_version(df, dataset_version, chk)
    if df.empty:
        chk.note('error', 'empty', '선택한 dataset_version에 행이 없습니다.')
    else:
        _check_market_common(df, chk)
        _check_factor_dates(df, chk, max_observation_age_days)
        _check_adjustment(df, chk, expected_adjustment_version, allow_unadjusted, jump_threshold)
        _check_quality(df, chk)
        _check_availability(df, chk, strict)

    df = df.sort_values(['trading_date', 'asset_id']).reset_index(drop=True)
    exclusions = exclusion_table(df, strict=strict) if len(df) else pd.DataFrame(columns=EXCLUSION_COLUMNS)
    unknown = _availability_unknown(df)[0] if len(df) else pd.Series(dtype=bool)
    has_error = any(i.severity == 'error' for i in chk.issues)
    if unknown.any():
        pit_status = 'rejected_unverified_rows' if strict else 'unverified_research'
    else:
        pit_status = 'not_verified' if (has_error or df.empty) else 'verified'
    usable = int(usable_mask(df, exclusions).sum()) if len(exclusions) else int(len(df))
    summary = {
        'rows': int(len(df)),
        'assets': int(df['asset_id'].nunique()),
        'start': str(df['trading_date'].min())[:10] if len(df) else None,
        'end': str(df['trading_date'].max())[:10] if len(df) else None,
        'dataset_version': version,
        'adjustment_versions': sorted(df['adjustment_version'].dropna().unique().tolist()),
        'quality_counts': {k: int(v) for k, v in df['quality_status'].value_counts().items()},
        'is_mock_rows': int(df['is_mock'].sum()),
        'exclusion_counts': {k: int(v) for k, v in exclusions.groupby('reason').size().items()},
        'availability_unknown_rows': int(unknown.sum()),
        'availability_by_column': {c: {'required_rows': int(need.sum()), 'null_rows': int((need & df[c].isna()).sum())}
                                   for c, need in _availability_needs(df)},
        'point_in_time_verified': pit_status == 'verified',
        'point_in_time_status': pit_status,
        'usable_asset_rows': usable,
        'notes': [
            '공개 시각이 NULL인 자료는 연구용입니다. 수집 시각이나 예상 공표 일정으로 채우지 않았습니다.',
            'quality_status=valid는 값의 품질이며 공개 시각 검증 완료를 뜻하지 않습니다.',
            '행은 삭제하지 않았습니다. 제외 사유는 exclusions 표를 보세요. 다른 종목의 결측으로 정상 종목 행을 제외하지 않습니다.',
        ],
    }
    report = GoldReport(mode, chk.issues, summary, exclusions)
    if raise_on_error and not report.ok:
        raise GoldValidationError(report)
    return (df, report) if return_report else df


def write_report(report: GoldReport, out_dir) -> dict:
    """검사 요약(JSON)과 제외 사유 표(CSV)를 저장합니다."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    suffix = '_strict' if report.mode == 'strict' else ''
    summary_path, table_path = out / f'gold_validation_summary{suffix}.json', out / f'gold_exclusions{suffix}.csv'
    summary_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf8')
    report.exclusions.to_csv(table_path, index=False, encoding='utf-8-sig')
    return {'summary': str(summary_path), 'exclusions': str(table_path)}


def main(argv=None):
    p = argparse.ArgumentParser(description='gold_stress_daily 읽기와 입력 검사')
    p.add_argument('source', nargs='?', default=str(DEFAULT_SOURCE),
                   help='Parquet 파일/폴더 또는 Delta 폴더 (생략하면 data/dev_gold/gold_stress_daily.parquet)')
    p.add_argument('--out', default=str(DEFAULT_OUT), help='검사 결과 저장 폴더 (기본: analytics/outputs/validation)')
    p.add_argument('--strict', action='store_true', help='공개 시각 NULL 행을 오류로 처리')
    p.add_argument('--dataset-version')
    p.add_argument('--expected-adjustment-version')
    a = p.parse_args(argv)
    try:
        _, report = load_gold(a.source, dataset_version=a.dataset_version, strict=a.strict,
                              expected_adjustment_version=a.expected_adjustment_version,
                              raise_on_error=False, return_report=True)
    except GoldValidationError as exc:
        report = exc.report
    paths = write_report(report, a.out)
    print(json.dumps({'ok': report.ok, 'mode': report.mode, 'summary': report.summary, 'files': paths},
                     ensure_ascii=False, indent=2, default=str))
    for i in report.issues:
        print(f'[{i.severity}] {i.check}: {i.message} ({i.count}건) {i.examples}')
    return 0 if report.ok else 1


if __name__ == '__main__':
    sys.exit(main())
