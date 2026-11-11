"""Fabric 연결부: Gold 읽기 어댑터와 비밀값 조회. (analytics/README.md 12.5절)

Fabric의 실제 위치·이름을 몰라도 코드가 동작하도록, 모르는 값은 모두 GoldSource / 환경 설정으로 받습니다.
계산은 하지 않습니다. 읽은 표는 load_gold가 검사한 뒤 반환합니다.

    src = GoldSource(kind='delta_path', location='abfss://.../lh_whatif.Lakehouse/Tables/gold_stress_daily',
                     dataset_version='official20-gold-v1.1-...')
    df, report, info = read_gold(src, spark=spark)

kind
  parquet      로컬 또는 Lakehouse Files의 Parquet 파일/폴더 (개발용)
  delta_path   Delta 폴더 경로. spark가 있으면 Spark로, 없으면 deltalake로 읽음
  spark_table  Lakehouse 표 이름(예: lh_whatif.gold_stress_daily). spark 필요
  pandas       이미 읽은 DataFrame (테스트용). location에 DataFrame을 넣음
delta_version을 주면 그 Delta 버전으로 읽습니다(시간 여행). 읽은 결과의 info에 버전과 행 수를 남깁니다.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass

import pandas as pd

try:
    from load_gold import load_gold
except ImportError:  # 패키지로 가져올 때
    from .load_gold import load_gold

KINDS = ('parquet', 'delta_path', 'spark_table', 'pandas')


@dataclass
class GoldSource:
    kind: str
    location: object
    dataset_version: str | None = None
    delta_version: int | None = None     # 지정하면 이 Delta 버전으로 고정해서 읽음
    strict: bool = False                 # True면 공개 시각 NULL 행을 오류로 처리
    expected_adjustment_version: str | None = None

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f'kind는 {KINDS} 중 하나여야 합니다: {self.kind!r}')
        if self.location is None or (isinstance(self.location, str) and not self.location.strip()):
            raise ValueError('location이 비어 있습니다. 설정 칸에 Gold 위치를 채우세요.')

    def describe(self) -> dict:
        d = asdict(self)
        if self.kind == 'pandas':
            d['location'] = f'<DataFrame {len(self.location)} rows>'
        return d


def _spark_df(src: GoldSource, spark):
    if spark is None:
        raise ValueError(f'kind={src.kind}는 spark 세션이 필요합니다. Fabric 노트북에서는 spark를 넘기세요.')
    if src.kind == 'spark_table':
        reader = spark.read.format('delta')
        if src.delta_version is not None:
            reader = reader.option('versionAsOf', int(src.delta_version))
        return reader.table(str(src.location))
    reader = spark.read.format('delta')
    if src.delta_version is not None:
        reader = reader.option('versionAsOf', int(src.delta_version))
    return reader.load(str(src.location))


def _raw(src: GoldSource, spark=None):
    """load_gold가 받는 형태(Spark/pandas DataFrame 또는 경로)로 돌려줍니다."""
    if src.kind == 'pandas':
        return src.location
    if src.kind == 'spark_table':
        return _spark_df(src, spark)
    if src.kind == 'delta_path':
        if spark is not None:
            return _spark_df(src, spark)
        if src.delta_version is not None:
            from deltalake import DeltaTable
            return DeltaTable(str(src.location), version=int(src.delta_version)).to_pandas()
        return str(src.location)         # load_gold가 deltalake로 읽음
    return str(src.location)


def read_gold(src: GoldSource, *, spark=None, **load_kwargs):
    """Gold를 읽고 검사합니다. 반환: (df, GoldReport, info). 오류가 있으면 GoldValidationError."""
    raw = _raw(src, spark)
    kwargs = dict(dataset_version=src.dataset_version, strict=src.strict,
                  expected_adjustment_version=src.expected_adjustment_version)
    kwargs.update(load_kwargs)
    df, report = load_gold(raw, return_report=True, **kwargs)
    versions = sorted(df['dataset_version'].astype(str).unique())
    info = {'source': src.describe(), 'rows': int(len(df)), 'dataset_versions': versions,
            'trading_date_min': str(df['trading_date'].min())[:10], 'trading_date_max': str(df['trading_date'].max())[:10],
            'assets': int(df['asset_id'].nunique()), 'strict': src.strict}
    return df, report, info


def get_secret(name: str, vault_url: str | None = None, *, environ=None) -> str:
    """비밀값 조회. Fabric에서는 Key Vault, 그 외에는 환경 변수. 값 자체는 코드·노트북·로그에 남기지 않습니다.

    name은 Key Vault 비밀 이름 또는 환경 변수 이름입니다.
    """
    env = os.environ if environ is None else environ
    if vault_url:
        try:
            import notebookutils  # Fabric 런타임에만 있음
            return notebookutils.credentials.getSecret(vault_url, name)
        except ImportError:
            pass
    if name in env and env[name]:
        return env[name]
    raise KeyError(f'비밀값 {name!r}을(를) 찾을 수 없습니다(Key Vault 또는 환경 변수 확인). 값은 출력하지 않습니다.')
