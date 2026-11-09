# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "93432592-8620-411e-808f-b91678bf78d2",
# META       "default_lakehouse_name": "lh_whatif",
# META       "default_lakehouse_workspace_id": "2c303c0d-6c10-4988-91cb-856fe5f56071",
# META       "known_lakehouses": [
# META         {
# META           "id": "93432592-8620-411e-808f-b91678bf78d2"
# META         }
# META       ]
# META     }
# META   }
# META }

# MARKDOWN ********************

# # MS_P3 — `nb_01_Bronze_to_Silver` 운영 통합본
# 
# **역할:** Bronze에 이미 저장된 파일을 읽어 기존 Silver 7개 Delta 테이블에 **신규 관측키 적재 및 검증된 결측 복구**합니다. 외부 API 호출은 하지 않습니다.
# 
# - 기존 연습용 `nb_01_Bronze_to_Silver`와 `nb_02_Silver_Transform`의 증분 로직을 **하나의 운영 Notebook**으로 통합했습니다. 두 Notebook을 Pipeline에서 동시에 실행하지 마세요.
# - `Files/bronze/...`는 OneLake 파일 경로입니다. 경로에 `/api/`가 포함되어도 **저장된 파일을 읽는 것**이지 외부 API 요청이 아닙니다.
# - 2026-11-09 12:50 KST 민철 수정: 원천 정규화 → 기존 정상 수치 보존/NULL 보완 → 가격 검증 → MERGE.
# - 기입된 종가·거래량·지표 수치는 **기존 Silver에 UPDATE하지 않습니다**. 같은 키의 수집 버전은 최신 정상 원천을 우선하되 기존 정상 수치를 덮어쓰지 않습니다. 거시 이력은 별도 PIT 근거를 사용합니다.
# - 2026-11-09 12:50 KST 민철 수정: 정확한 시각은 미확인 시 NULL. 이용 가능 상한은 Files/silver_evidence에 별도 보존. 가격 기준은 Gold까지 유지.
# - 주가 Bronze는 확인된 **KRX JSON** 경로를 기본으로 사용합니다. 키움 `ka10081`은 별도 입력 모드이며 실제 파일 구조/출처 확인 전 비활성화합니다.
# 
# **운영 일정:** 기존 오전 08:00 KST 수집 성공 → Silver 검증 → Gold 실행. 이 Notebook은 일정 자체를 생성하지 않습니다.


# MARKDOWN ********************

# ## Silver 계약 — 기존 7개 Delta 테이블 변경 금지
# 
# | 대상 테이블 | 기존 컬럼 수 | 관측키 | 신규 입력 주요 필드 |
# |---|---:|---|---|
# | `silver_stock_daily` | 22 | `trading_date`, `asset_id` | close, volume, OHLC, trading_value, market_cap, listed_shares, raw_*, sector_id, instrument_kind, price_basis, adjustment_version, price_available_at, dataset_version, is_mock, source_ref, quality_status |
# | `silver_kospi_daily` | 9 | `observation_date` | kospi_close, raw_date, raw_close, price_available_at, source_ref, dataset_version, is_mock, quality_status |
# | `silver_usdkrw_daily` | 10 | `observation_date` | value, series_id, value_unit, source_ref, quality_status, observed_at, available_at, dataset_version, missing_reason |
# | `silver_us_treasury_10y_daily` | 10 | `observation_date` | 위 FRED 공통 스키마 |
# | `silver_wti_daily` | 10 | `observation_date` | 위 FRED 공통 스키마 (WTI 음수·0 허용) |
# | `silver_vix_daily` | 10 | `observation_date` | 위 FRED 공통 스키마 |
# | `silver_korea_3y_daily` | 21 | `observation_date` | value, raw_time/raw_value, stat_code, item_code, unit_name, 통계명·세부코드·가중치, observed_at, available_at, source_ref, dataset_version, quality_status |
# 
# **이전 `nb_02_Silver_Transform`에서 통합한 내용:** KRX/KOSPI/FRED/ECOS `left_anti` → `Delta MERGE`, 신규 데이터 파싱 및 중복 검증, 7개 Silver 핵심키 확인. 별도의 진단 셀·최초 테이블 생성·Gold 생성 코드는 제외합니다.
# 
# **데이터 계약:** 원본 레코드가 `is_mock=true`이면 제외합니다. KRX `SECT_TP_NM`을 `sector_id`로 사용하지 않습니다. 동일 키의 기존 수치는 변경하지 않습니다. 기존 NULL은 정상 원천으로 보완합니다. 정상 수치의 정정은 별도 검증이 필요합니다.


# MARKDOWN ********************

# 2026-11-09 12:50 KST 민철 수정: 가격 검증/결측 복구/시점 근거 연결. 변경 위치에 설명을 남겼습니다.
# 기존 Gold 34컬럼과 ML Notebook은 변경하지 않습니다.

# CELL ********************

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re

from notebookutils import fs
from pyspark.sql import functions as F, types as T
from pyspark.sql.window import Window
from delta.tables import DeltaTable

spark.conf.set("spark.sql.session.timeZone", "UTC")
spark.conf.set("spark.sql.legacy.parquet.nanosAsLong", "true")

# 2026-11-09 12:50 KST 민철 추가 — 로컬 검증 파일을 해시 확인 후 읽습니다. 원본 Gold 계약과 실제 공표 시각은 변경하지 않습니다.

import json, hashlib
from pathlib import Path
import pandas as pd
import numpy as np
EVIDENCE_ROOT = Path('/lakehouse/default/Files/reference/ml_input_validation/20261109_v1')
_manifest = json.loads((EVIDENCE_ROOT/'manifest.json').read_text(encoding='utf8'))
for _file, _sha in _manifest['files'].items():
    if hashlib.sha256((EVIDENCE_ROOT/_file).read_bytes()).hexdigest() != _sha:
        raise RuntimeError('검증 자료 해시 불일치: '+_file)
exec(compile((EVIDENCE_ROOT/'batch_evidence.py').read_text(encoding='utf8'), 'batch_evidence.py', 'exec'))
_official_files = certified_files('/lakehouse/default/Files/bronze')
_verified_prices = pd.read_parquet(EVIDENCE_ROOT/'verified_prices.parquet')
_historical_provenance = pd.read_parquet(EVIDENCE_ROOT/'historical_provenance.parquet')

BRONZE = "Files/bronze"
STOCK_SOURCE_MODE = "krx"  # 현재 확인된 원천. 실제 키움 JSON 확보 시에만 "kiwoom"
KIWOOM_JSON_ROOT = f"{BRONZE}/kiwoom"  # 가정한 경로: 실제 저장 경로 확인 후 변경
KIWOOM_BRONZE_CONFIRMED_REAL = False   # 원천이 실거래 API임을 수집 로그로 확인 후 True
LOOKBACK_DAYS = 120  # 기존 Silver 최종일 기준 API 파일 조회 범위. 오래된 누락 백필은 별도 실행 필요
# 기존 정상 수치를 보존하면서 신규 키와 검증된 NULL 보완을 반영하는 모드. 초기 생성은 이 Notebook에서 하지 않음.

SILVER_TABLES = {
    "stock": "silver_stock_daily",
    "kospi": "silver_kospi_daily",
    "usdkrw": "silver_usdkrw_daily",
    "us_treasury_10y": "silver_us_treasury_10y_daily",
    "wti": "silver_wti_daily",
    "vix": "silver_vix_daily",
    "korea_3y": "silver_korea_3y_daily",
}

FRED_SPEC = {
    "usdkrw": ("DEXKOUS", "KRW/USD"),
    "us_treasury_10y": ("DGS10", "%"),
    "wti": ("DCOILWTICO", "USD/barrel"),
    "vix": ("VIXCLS", "index"),
}

SILVER_CONTRACT = {
    "stock": (22, ["trading_date", "asset_id", "close", "volume", "source_ref", "quality_status"]),
    "kospi": (9, ["observation_date", "kospi_close", "source_ref", "quality_status"]),
    "usdkrw": (10, ["observation_date", "value", "source_ref", "quality_status"]),
    "us_treasury_10y": (10, ["observation_date", "value", "source_ref", "quality_status"]),
    "wti": (10, ["observation_date", "value", "source_ref", "quality_status"]),
    "vix": (10, ["observation_date", "value", "source_ref", "quality_status"]),
    "korea_3y": (21, ["observation_date", "value", "source_ref", "quality_status"]),
}

for role, table in SILVER_TABLES.items():
    if not spark.catalog.tableExists(table):
        raise RuntimeError(f"기존 Silver 테이블 없음: {table}; 최초 생성은 별도 작업입니다.")
    actual = spark.table(table).columns
    expected_count, required = SILVER_CONTRACT[role]
    if len(actual) != expected_count or set(required) - set(actual):
        raise RuntimeError(
            f"{table}: 기존 Silver 스키마 계약 불일치 "
            f"({len(actual)}개 / 예상 {expected_count}개, 필수 누락 {sorted(set(required) - set(actual))})"
        )

print("Silver 7개 기존 스키마 확인 완료 | 주식 원천:", STOCK_SOURCE_MODE)

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# 공통 유틸리티 — 중복 없는 신규 적재와 NULL 보완, 기존 스키마 그대로 유지

def all_json_files(folder, depth=0, max_depth=6):
    if not fs.exists(folder):
        return []
    if depth > max_depth:
        raise RuntimeError(f"Bronze 파일 경로의 하위 폴더 깊이가 예상보다 큽니다: {folder}")
    result = []
    for item in fs.ls(folder):
        if item.isDir:
            result += all_json_files(item.path, depth + 1, max_depth)
        elif item.name.lower().endswith(".json"):
            result.append(item.path)
    return sorted(set(result))


def read_jsons(paths):
    if not paths:
        return None
    return (spark.read.option("multiLine", "true").json(paths)
            .withColumn("_source_path", F.input_file_name()))


def c_optional(df, field, dtype="string"):
    return F.col(field).cast(dtype) if field in df.columns else F.lit(None).cast(dtype)


def row_optional(row_fields, field, dtype="string"):
    return (F.col(f"r.`{field}`").cast(dtype)
            if field in row_fields else F.lit(None).cast(dtype))


def as_date(expr):
    s = F.regexp_replace(F.trim(expr.cast("string")), r"[^0-9]", "")
    return F.when(F.length(s) == 8, F.to_date(s, "yyyyMMdd"))


def as_number(expr, kind="double", strip_sign=False):
    s = F.regexp_replace(F.trim(expr.cast("string")), ",", "")
    if strip_sign:
        s = F.regexp_replace(s, r"^[+-]", "")
    if kind == "long":
        return F.when(s.rlike(r"^[+-]?[0-9]+$"), s.cast("long"))
    return F.when(
        s.rlike(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$"),
        s.cast("double")
    )


def rows_struct(raw, key="rows"):
    if key not in raw.columns:
        raise RuntimeError(f"Bronze JSON에서 {key!r} 배열을 찾지 못했습니다: {raw.columns}")
    dt = raw.schema[key].dataType
    if not isinstance(dt, T.ArrayType) or not isinstance(dt.elementType, T.StructType):
        raise RuntimeError(f"예상과 다른 JSON {key} 형식: {dt.simpleString()}")
    cols = set(dt.elementType.fieldNames())
    extra = [F.col(k) for k in ["is_mock", "price_basis", "retrieved_at", "available_at"]
             if k in raw.columns]
    flat = raw.select(F.explode_outer(key).alias("r"), "_source_path", *extra)
    return flat, cols


# 변경 정책: 기존 정상 숫자 보존, 검증된 NULL 보완 및 가격 메타데이터 복구.
PAYLOAD_COLUMNS = {
    "stock": ["close", "volume", "open", "high", "low", "trading_value", "market_cap", "listed_shares"],
    "kospi": ["kospi_close"],
    "usdkrw": ["value"],
    "us_treasury_10y": ["value"],
    "wti": ["value"],
    "vix": ["value"],
    "korea_3y": ["value"],
}


# 2026-11-09 12:50 KST 민철 수정 — 신규 삽입 전용에서 검증된 NULL 보완으로 변경. 기존 정상 수치는 자동 덮어쓰지 않습니다.

def merge_new(name, source_df, keys):
    table = SILVER_TABLES[name]
    target = spark.table(table)
    order = Window.partitionBy(*keys).orderBy(
        F.when(F.col('quality_status')=='valid', 1).otherwise(0).desc(),
        F.col('_priority').desc_nulls_last(), F.col('_retrieved_at').desc_nulls_last(),
        F.col('source_ref').desc_nulls_last())
    source = source_df.withColumn('_rn',F.row_number().over(order)).filter('_rn=1').drop('_rn')
    if source.filter(' OR '.join(f'`{k}` IS NULL' for k in keys)).limit(1).count():
        raise RuntimeError(table+': 원천 키 NULL')
    aligned = source.select(*[(F.col(f.name) if f.name in source.columns else F.lit(None)).cast(f.dataType).alias(f.name) for f in target.schema.fields])
    if name == 'stock':
        # 아래 가격 검증은 저장 전에 실행합니다. 검증된 과거 메타데이터도 함께 복구합니다.
        old = target.toPandas(); incoming = aligned.toPandas()
        old['trading_date']=pd.to_datetime(old.trading_date); incoming['trading_date']=pd.to_datetime(incoming.trading_date)
        # 같은 키의 기존 숫자는 유지하고 NULL만 원천 값으로 보완합니다.
        planned=old.set_index(keys).combine_first(incoming.set_index(keys)).reset_index()
        meta, issues=price_metadata(planned, _verified_prices, _official_files)
        planned=planned.drop(columns=['price_basis','adjustment_version','quality_status']).merge(meta,on=keys,validate='one_to_one')
        evidence_dir=Path('/lakehouse/default/Files/silver_evidence');evidence_dir.mkdir(parents=True,exist_ok=True)
        (evidence_dir/'price_validation.json').write_text(json.dumps({'issues':issues,'checked_rows':len(planned)},ensure_ascii=False,indent=2),encoding='utf8')
        # 기존 숫자는 보존하면서 행별 검증 상태를 적용합니다. 격리된 행은 ML에서 제외합니다.
        records=[]
        for r in planned.to_dict('records'):
            records.append(tuple(None if pd.isna(r.get(f.name)) else
                (pd.Timestamp(r[f.name]).date() if isinstance(f.dataType,T.DateType) else
                 pd.Timestamp(r[f.name]).to_pydatetime() if isinstance(f.dataType,T.TimestampType) else
                 int(r[f.name]) if isinstance(f.dataType,T.LongType) else r[f.name]) for f in target.schema.fields))
        aligned=spark.createDataFrame(records,target.schema)
    aligned=aligned.cache(); aligned.count()
    condition=' AND '.join(f't.`{k}` = s.`{k}`' for k in keys)
    updates={f.name:F.coalesce(F.col('t.`'+f.name+'`'),F.col('s.`'+f.name+'`')) for f in target.schema.fields if f.name not in keys}
    if name=='stock':
        for col in ['price_basis','adjustment_version','quality_status']:updates[col]=F.col('s.'+col)
        update_when=' OR '.join([f'NOT (t.`{c}` <=> s.`{c}`)' for c in ['price_basis','adjustment_version','quality_status']]+[f't.`{c}` IS NULL AND s.`{c}` IS NOT NULL' for c in PAYLOAD_COLUMNS[name]])
    else:
        value_cols=PAYLOAD_COLUMNS[name]
        update_when="s.quality_status = 'valid' AND ("+' OR '.join(f't.`{c}` IS NULL' for c in value_cols)+')'
        updates['quality_status']=F.col('s.quality_status')
        updates['source_ref']=F.col('s.source_ref')
    try:
        (DeltaTable.forName(spark,table).alias('t').merge(aligned.alias('s'),condition)
         .whenMatchedUpdate(condition=update_when,set=updates)
         .whenNotMatchedInsertAll().execute())
    finally:aligned.unpersist()

def selected_files(paths, cutoff, pattern):
    # 거래일을 파일명으로 확인할 수 있을 때만 최근 범위로 제한.
    result = []
    for path in paths:
        m = re.search(pattern, path, flags=re.I)
        if m:
            try:
                file_date = datetime.strptime(m.group(1), "%Y%m%d").date()
                if cutoff and file_date < cutoff:
                    continue
            except ValueError:
                pass
        result.append(path)
    return result


def cutoff_for(table, date_field):
    latest = spark.table(table).agg(F.max(date_field)).first()[0]
    return (latest - timedelta(days=LOOKBACK_DAYS)) if latest else None

print("공통 정제·MERGE 함수 로드 완료")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************


# =====================================================
# 1/4 KRX/키움 일별 주식 → silver_stock_daily
# 기존 Silver 22개 컬럼 유지 / 신규 적재 및 검증된 NULL 보완
# =====================================================

stock_target = SILVER_TABLES["stock"]
cutoff = cutoff_for(stock_target, "trading_date")

asset_list = [
    r["asset_id"]
    for r in (
        spark.table(stock_target)
        .select("asset_id")
        .distinct()
        .collect()
    )
    if r["asset_id"] is not None
]

if not asset_list:
    raise RuntimeError("Silver에 등록된 종목코드가 없습니다.")

print("Silver 관리 종목 수:", len(asset_list))
print("증분 조회 시작일:", cutoff)

records = None

# -----------------------------------------------------
# A. KRX Bronze JSON
# -----------------------------------------------------
if STOCK_SOURCE_MODE == "krx":

    paths = [
        p for p in all_json_files(f"{BRONZE}/krx/api")
        if re.search(r"/stocks/", p, re.I)
    ]

    paths = selected_files(
        paths,
        cutoff,
        r"/stocks/([0-9]{8})\.json$"
    )

    print("KRX 주식 Bronze JSON:", len(paths), "개")

    if paths:
        raw = read_jsons(paths)
        rec, fields = rows_struct(raw, "rows")

        needed = {
            "BAS_DD",
            "TDD_CLSPRC",
            "ACC_TRDVOL"
        }

        # KRX 단축코드가 별도로 있으면 우선 사용
        if "ISU_SRT_CD" in fields:
            code_field = "ISU_SRT_CD"
        elif "ISU_CD" in fields:
            code_field = "ISU_CD"
        else:
            raise RuntimeError(
                "KRX JSON에서 종목코드 필드를 찾지 못했습니다."
            )

        missing = needed - fields

        if missing or "is_mock" not in rec.columns:
            raise RuntimeError(
                f"KRX 원천 필드 누락: {sorted(missing)}"
            )

        print("사용할 KRX 종목코드 필드:", code_field)

        # 1. Bronze 원본 정규화
        records = rec.select(
            as_date(
                F.col("r.BAS_DD")
            ).alias("trading_date"),

            F.trim(
                F.col(f"r.`{code_field}`").cast("string")
            ).alias("asset_id"),

            as_number(
                F.col("r.TDD_CLSPRC")
            ).alias("close"),

            as_number(
                F.col("r.ACC_TRDVOL"), "long"
            ).alias("volume"),

            as_number(
                row_optional(fields, "TDD_OPNPRC")
            ).alias("open"),

            as_number(
                row_optional(fields, "TDD_HGPRC")
            ).alias("high"),

            as_number(
                row_optional(fields, "TDD_LWPRC")
            ).alias("low"),

            as_number(
                row_optional(fields, "ACC_TRDVAL")
            ).alias("trading_value"),

            as_number(
                row_optional(fields, "MKTCAP")
            ).alias("market_cap"),

            as_number(
                row_optional(fields, "LIST_SHRS"), "long"
            ).alias("listed_shares"),

            F.col("r.BAS_DD")
                .cast("string")
                .alias("raw_trading_date"),

            F.col("r.TDD_CLSPRC")
                .cast("string")
                .alias("raw_close"),

            F.col("r.ACC_TRDVOL")
                .cast("string")
                .alias("raw_volume"),

            "_source_path",
            "is_mock",

            c_optional(
                rec, "retrieved_at"
            ).alias("_retrieved_raw")
        )

        # 2. 실데이터 여부 확인
        if records.filter(
            F.col("is_mock").isNull()
        ).limit(1).count():
            raise RuntimeError(
                "KRX is_mock 값이 NULL입니다."
            )

        records = records.filter(
            F.col("is_mock") == F.lit(False)
        )

        # 3. MS_P3 관리 대상 20개 종목 먼저 필터링
        #    000660, 005930 등 앞의 0 유지
        #    분석 대상이 아닌 영문 포함 코드 제외
        managed = records.filter(
            F.col("asset_id").isin(asset_list)
        )

        # 4. 관리 대상 매칭 확인
        if managed.limit(1).count() == 0:

            if records.limit(1).count() == 0:
                print(
                    "KRX 실데이터 행 없음: "
                    "기존 Silver 유지"
                )
                records = None

            else:
                samples = [
                    r["asset_id"]
                    for r in (
                        records
                        .select("asset_id")
                        .distinct()
                        .limit(10)
                        .collect()
                    )
                ]

                raise RuntimeError(
                    "KRX Bronze 종목코드가 기존 "
                    "Silver 관리 종목과 매칭되지 않습니다. "
                    f"원천 코드 예시: {samples}. "
                    "표준코드와 단축코드 구분이 필요합니다."
                )

        else:
            records = managed

            # 5. 관리 대상에 대해서만 형식 검사
            invalid_codes = records.filter(
                F.col("asset_id").isNull()
                | ~F.col("asset_id").rlike(r"^[0-9]{6}$")
            )

            if invalid_codes.limit(1).count():
                raise RuntimeError(
                    "관리 대상 종목코드가 예상한 "
                    "6자리 숫자 형식과 다릅니다."
                )

            print("Silver 관리 종목 매칭 완료")


# -----------------------------------------------------
# B. 키움 Bronze JSON
# -----------------------------------------------------
elif STOCK_SOURCE_MODE == "kiwoom":

    paths = all_json_files(KIWOOM_JSON_ROOT)

    if not paths:
        raise RuntimeError(
            "키움 Bronze JSON 경로를 찾지 못했습니다."
        )

    if not KIWOOM_BRONZE_CONFIRMED_REAL:
        raise RuntimeError(
            "키움 실데이터 여부 미확인. MERGE 중단."
        )

    raw = read_jsons(paths)

    if "return_code" in raw.columns:
        if raw.filter(
            F.col("return_code").cast("int") != 0
        ).limit(1).count():
            raise RuntimeError(
                "키움 API 오류 응답이 포함되어 있습니다."
            )

    rec, fields = rows_struct(
        raw, "stk_dt_pole_chart_qry"
    )

    needed = {"dt", "cur_prc", "trde_qty"}

    if needed - fields or "stk_cd" not in rec.columns:
        raise RuntimeError(
            f"키움 ka10081 구조 불일치: "
            f"{sorted(needed - fields)}"
        )

    records = rec.select(
        as_date(F.col("r.dt")).alias("trading_date"),

        F.trim(
            F.col("stk_cd").cast("string")
        ).alias("asset_id"),

        as_number(
            F.col("r.cur_prc"), strip_sign=True
        ).alias("close"),

        as_number(
            F.col("r.trde_qty"), "long"
        ).alias("volume"),

        as_number(
            row_optional(fields, "open_pric"),
            strip_sign=True
        ).alias("open"),

        as_number(
            row_optional(fields, "high_pric"),
            strip_sign=True
        ).alias("high"),

        as_number(
            row_optional(fields, "low_pric"),
            strip_sign=True
        ).alias("low"),

        (
            as_number(
                row_optional(fields, "trde_prica")
            ) * F.lit(1_000_000.0)
        ).alias("trading_value"),

        F.lit(None).cast("double").alias("market_cap"),
        F.lit(None).cast("long").alias("listed_shares"),

        F.col("r.dt").cast("string").alias("raw_trading_date"),

        F.col("r.cur_prc")
            .cast("string")
            .alias("raw_close"),

        F.col("r.trde_qty")
            .cast("string")
            .alias("raw_volume"),

        "_source_path",

        F.lit(False).alias("is_mock"),

        c_optional(
            rec, "retrieved_at"
        ).alias("_retrieved_raw")
    )

    print(
        "주의: 키움 수정주가 설정과 "
        "기존 KRX 가격 기준의 일치 여부는 별도 검증 필요"
    )

else:
    raise ValueError(
        "STOCK_SOURCE_MODE는 krx 또는 kiwoom만 지원합니다."
    )


# -----------------------------------------------------
# C. 공통 Silver 증분 정제 및 MERGE
# -----------------------------------------------------
if records is not None:

    # 기존 Silver 관리 종목만 사용
    records = records.filter(
        F.col("asset_id").isin(asset_list)
    )

    # 최근 Bronze 수집 데이터만 처리
    if cutoff:
        records = records.filter(
            F.col("trading_date") >= F.lit(cutoff)
        )

    # 기존 Silver 22개 컬럼에 맞춘 메타데이터
    records = (
        records
        .withColumn(
            "source_ref",
            F.col("_source_path")
        )
        .withColumn(
            "_retrieved_at",
            F.to_timestamp("_retrieved_raw")
        )
        .withColumn("_priority", F.lit(2))
        .withColumn(
            "sector_id",
            F.lit(None).cast("string")
        )
        .withColumn(
            "instrument_kind",
            F.lit("stock")
        )
        .withColumn(
            "price_basis",
            F.lit("unknown")
        )
        .withColumn(
            "adjustment_version",
            F.lit(None).cast("string")
        )
        .withColumn(
            "price_available_at",
            F.lit(None).cast("timestamp")
        )
        .withColumn(
            "dataset_version",
            F.lit(None).cast("string")
        )
        .withColumn(
            "quality_status",
            F.when(
                F.col("trading_date").isNull()
                | F.col("close").isNull()
                | F.col("volume").isNull(),
                "missing"
            )
            .when(
                (F.col("close") <= 0)
                | (F.col("volume") < 0),
                "quarantined"
            )
            .otherwise("valid")
        )
    )

    # 기존 Silver에 없는 키만 삽입
    merge_new(
        "stock",
        records,
        ["trading_date", "asset_id"]
    )

else:
    print(
        "KRX 주식 신규 수집 데이터 없음: "
        "기존 Silver 유지"
    )

# 2026-11-09 12:50 KST 민철 추가 — 신규 체결일이 없어도 기존 가격 근거를 검증합니다.
if records is None:
    _old=spark.table(SILVER_TABLES['stock']).withColumn('_priority',F.lit(0)).withColumn('_retrieved_at',F.lit(None).cast('timestamp'))
    merge_new('stock',_old,['trading_date','asset_id'])
print("주식 Silver 증분 갱신 단계 종료")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# 2/4 KOSPI 지수 → silver_kospi_daily (기존 9개 컬럼 유지)

paths = [p for p in all_json_files(f"{BRONZE}/krx/api") if re.search(r"/index/", p, re.I)]
paths = selected_files(paths, cutoff_for(SILVER_TABLES["kospi"], "observation_date"), r"/index/([0-9]{8})\.json$")
print("KRX KOSPI Bronze JSON:", len(paths))

if paths:
    raw = read_jsons(paths)
    rec, fields = rows_struct(raw)
    dfield = next((x for x in ["BAS_DD","TRD_DD"] if x in fields), None)
    vfield = next((x for x in ["CLSPRC_IDX","TDD_CLSPRC"] if x in fields), None)
    if not dfield or not vfield or "is_mock" not in rec.columns:
        raise RuntimeError(f"KOSPI 원천 날짜/지수 또는 is_mock 누락: {sorted(fields)}")
    if "IDX_NM" in fields:
        rec = rec.filter(F.trim(F.upper(F.col("r.IDX_NM"))).isin(
            "코스피", "KOSPI", "코스피지수", "KOSPI COMPOSITE"))
    else:
        # 명칭 필드가 없는 다종 지수 파일은 코스피로 간주하지 않음
        if not any(re.search(r"(^|[/_])kospi([./_]|$)",p,re.I) for p in paths):
            raise RuntimeError("KOSPI 신규 JSON에서 IDX_NM/코스피 파일명이 없어 지수를 구분할 수 없습니다. 매핑 확인 필요")
        rec = rec.filter(F.lower(F.col("_source_path")).rlike(r"(^|[/_])kospi([./_]|$)"))
    data = rec.filter(F.col("is_mock") == False).select(
        as_date(F.col(f"r.`{dfield}`")).alias("observation_date"),
        as_number(F.col(f"r.`{vfield}`")).alias("kospi_close"),
        F.col(f"r.`{dfield}`").cast("string").alias("raw_date"),
        F.col(f"r.`{vfield}`").cast("string").alias("raw_close"),
        F.lit(None).cast("timestamp").alias("price_available_at"),
        F.col("_source_path").alias("source_ref"),
        F.lit(None).cast("string").alias("dataset_version"),
        F.lit(False).alias("is_mock"),
        F.to_timestamp(c_optional(rec, "retrieved_at")).alias("_retrieved_at"),
        F.lit(2).alias("_priority")
    ).withColumn("quality_status",
        F.when(F.col("observation_date").isNull() | F.col("kospi_close").isNull(),"missing")
         .when(F.col("kospi_close") <= 0,"quarantined").otherwise("valid"))
    if data.limit(1).count():
        merge_new("kospi",data,["observation_date"])
    else:
        raise RuntimeError("index JSON을 발견했지만 KOSPI 관측값을 추출하지 못했습니다. 지수 식별자 확인 필요")
else:
    print("KOSPI JSON 배치 없음 — 기존 Silver 유지")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# 3/4 FRED Parquet History + 수집된 FRED API JSON → Silver 4개
# 신규 관측일 적재 및 기존 NULL 보완. 정확한 공개/관측 시각 미확인은 NULL 유지.

NANOS_PER_DAY = 86_400_000_000_000

def fred_history(name):
    path = f"{BRONZE}/fred/history/{name}.parquet"
    if not fs.exists(path):
        return None
    df = spark.read.parquet(path)
    if not {"date",name}.issubset(df.columns):
        raise RuntimeError(f"FRED History 컬럼 불일치: {path} | {df.columns}")
    date_type = df.schema["date"].dataType
    if isinstance(date_type, (T.LongType,T.IntegerType)):
        d = F.date_add(F.lit("1970-01-01").cast("date"),
                       F.floor(F.col("date")/F.lit(NANOS_PER_DAY)).cast("int"))
    elif isinstance(date_type, (T.DateType,T.TimestampType)):
        d = F.to_date("date")
    else:
        raise RuntimeError(f"FRED History date 타입 불명확: {date_type}")
    return df.select(
        d.alias("observation_date"),
        as_number(F.col(name)).alias("value"),
        F.lit(path).alias("source_ref"),
        F.lit(None).cast("timestamp").alias("_retrieved_at"),
        F.lit(1).alias("_priority")
    )


def fred_api(name):
    folder = f"{BRONZE}/fred/api"
    paths = [p for p in all_json_files(folder)
             if re.search(rf"/observations/{re.escape(name)}\.json$", p, re.I)]
    if not paths:
        return None
    raw = read_jsons(paths)
    if "rows" not in raw.columns:
        raise RuntimeError(f"FRED API rows 누락: {name} | {raw.columns}")
    rt = raw.schema["rows"].dataType.elementType
    if isinstance(rt, T.StructType):
        rec, fields = rows_struct(raw)
        datev = row_optional(fields,"date")
        valuev = row_optional(fields,"value")
    elif isinstance(rt, T.StringType):
        st = T.StructType([T.StructField("date",T.StringType()),T.StructField("value",T.StringType())])
        rec = raw.select(F.explode_outer("rows").alias("r0"),"_source_path",
                         *[F.col(x) for x in ["is_mock","retrieved_at"] if x in raw.columns])
        rec = rec.withColumn("r", F.from_json("r0",st))
        fields = {"date","value"}
        if rec.filter(F.col("r").isNull() & F.col("r0").isNotNull()).limit(1).count():
            raise RuntimeError(f"FRED API 내부 레코드 JSON 파싱 실패: {name}")
        datev = F.col("r.date"); valuev = F.col("r.value")
    else:
        raise RuntimeError(f"FRED API 알 수 없는 rows 요소 타입: {rt}")
    if not {"date","value"}.issubset(fields):
        raise RuntimeError(f"FRED API 날짜/값 필드 누락: {name} | {fields}")
    if "is_mock" in rec.columns:
        rec = rec.filter(F.col("is_mock") == False)
    return rec.select(
        as_date(datev).alias("observation_date"),
        as_number(valuev).alias("value"),
        F.col("_source_path").alias("source_ref"),
        F.to_timestamp(c_optional(rec,"retrieved_at")).alias("_retrieved_at"),
        F.lit(2).alias("_priority")
    )

for name,(series_id,unit) in FRED_SPEC.items():
    candidates = [x for x in (fred_history(name),fred_api(name)) if x is not None]
    if not candidates:
        print(f"FRED {name}: Bronze 파일 없음. 기존 Silver 유지")
        continue
    src = candidates[0]
    for more in candidates[1:]:
        src = src.unionByName(more)
    src = src.filter(F.col("observation_date").isNotNull())
    recent = cutoff_for(SILVER_TABLES[name],"observation_date")
    if recent:
        src = src.filter(F.col("observation_date") >= F.lit(recent))
    src = (src.withColumn("series_id",F.lit(series_id))
        .withColumn("value_unit",F.lit(unit))
        .withColumn("observed_at",F.lit(None).cast("timestamp"))
        .withColumn("available_at",F.lit(None).cast("timestamp"))
        .withColumn("dataset_version",F.lit(None).cast("string"))
        .withColumn("quality_status",
           F.when(F.col("value").isNull() | F.isnan("value"),"missing")
           .when((F.lit(name)=="usdkrw") & (F.col("value")<=0),"quarantined")
           .when((F.lit(name)=="vix") & (F.col("value")<0),"quarantined")
           .otherwise("valid"))
        .withColumn("missing_reason",F.when(F.col("value").isNull(),"unknown")))
    merge_new(name,src,["observation_date"])

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# 4/4 ECOS 한국 3년물 History + API → silver_korea_3y_daily
# 원본 값과 식별코드를 검증하며, 새로운 날짜에 대해서만 삽입.

ECOS_STAT = "817Y002"
ECOS_ITEM = "010200000"
ECOS_UNIT = "연%"

history_path = f"{BRONZE}/ecos/history/korea_3y.json"
api_paths = [p for p in all_json_files(f"{BRONZE}/ecos/api")
             if re.search(r"/observations/kr3y\.json$",p,re.I)]

def ecos_normalize(flat, path_is_history=False):
    fields = set(flat.columns)
    need = {"TIME","DATA_VALUE","STAT_CODE","ITEM_CODE1","UNIT_NAME"}
    if need - fields:
        raise RuntimeError(f"ECOS 필수 식별 필드 누락: {sorted(need-fields)}")
    flat = flat.filter(
        (F.col("STAT_CODE")==ECOS_STAT) &
        (F.col("ITEM_CODE1")==ECOS_ITEM) &
        (F.col("UNIT_NAME")==ECOS_UNIT)
    )
    if "is_mock" in fields:
        flat = flat.filter(F.col("is_mock") == False)
    get = lambda x: c_optional(flat,x)
    return flat.select(
        as_date(F.col("TIME")).alias("observation_date"),
        as_number(F.col("DATA_VALUE")).alias("value"),
        get("TIME").alias("raw_time"), get("DATA_VALUE").alias("raw_value"),
        get("STAT_CODE").alias("stat_code"),get("ITEM_CODE1").alias("item_code"),
        get("UNIT_NAME").alias("unit_name"),
        get("STAT_NAME").alias("stat_name"),get("ITEM_NAME1").alias("item_name"),
        *[get("ITEM_CODE"+str(i)).alias("item_code"+str(i)) for i in [2,3,4]],
        *[get("ITEM_NAME"+str(i)).alias("item_name"+str(i)) for i in [2,3,4]],
        get("WGT").alias("raw_weight"),
        F.lit(None).cast("timestamp").alias("observed_at"),
        F.lit(None).cast("timestamp").alias("available_at"),
        (F.lit(history_path) if path_is_history else F.col("_source_path")).alias("source_ref"),
        F.lit(None).cast("string").alias("dataset_version"),
        F.to_timestamp(get("retrieved_at")).alias("_retrieved_at"),
        F.lit(1 if path_is_history else 2).alias("_priority")
    ).withColumn("quality_status",
        F.when(F.col("observation_date").isNull() | F.col("value").isNull(),"missing")
         .otherwise("valid"))

sources = []
if fs.exists(history_path):
    hist = spark.read.option("multiLine","true").json(history_path)
    sources.append(ecos_normalize(hist,path_is_history=True))

if api_paths:
    raw = read_jsons(api_paths)
    if "rows" in raw.columns:
        rec,fields = rows_struct(raw)
        extra = [F.col(c) for c in ["retrieved_at","is_mock"] if c in rec.columns]
        flat = rec.select("r.*","_source_path",*extra)
    elif "StatisticSearch" in raw.columns:
        flat = raw.select(F.explode_outer("StatisticSearch.row").alias("r"),"_source_path").select("r.*","_source_path")
    else:
        raise RuntimeError(f"ECOS API JSON 레코드 구조 미확인: {raw.columns}")
    sources.append(ecos_normalize(flat))

if sources:
    src = sources[0]
    for more in sources[1:]:
        src = src.unionByName(more)
    recent = cutoff_for(SILVER_TABLES["korea_3y"],"observation_date")
    if recent:
        src = src.filter(F.col("observation_date") >= F.lit(recent))
    merge_new("korea_3y",src,["observation_date"])
else:
    print("ECOS Bronze 원천 없음 — 기존 Silver 유지")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# 최종 7개 테이블 결과: 날짜·건수·키 중복·컬럼 수
# (데이터 정제 및 MERGE가 성공한 후 한 번만 실행)

specs = [
    ("stock","trading_date",["trading_date","asset_id"]),
    *[(name,"observation_date",["observation_date"])
      for name in ["kospi","usdkrw","us_treasury_10y","wti","vix","korea_3y"]]
]

print("=== MS_P3 Silver 일별 갱신 결과 ===")
failures = []
for name,date_col,keys in specs:
    t = SILVER_TABLES[name]
    df = spark.table(t)
    r = df.agg(F.count("*").alias("rows"), F.max(date_col).alias("latest")).first()
    dup = df.groupBy(*keys).count().filter("count>1").limit(1).count()
    if r["rows"] == 0 or dup:
        failures.append(t)
    print(f"{t:35s} 행 {r['rows']:>8,} | 최신 {r['latest']} | 컬럼 {len(df.columns):>2} | 키중복 {dup}")
if failures:
    raise RuntimeError(f"Silver 검증 실패: {failures}")

# 오래된 결과를 정상으로 오인하지 않도록 주식 최종일 확인.
stock_max = spark.table(SILVER_TABLES["stock"]).agg(F.max("trading_date")).first()[0]
kospi_max = spark.table(SILVER_TABLES["kospi"]).agg(F.max("observation_date")).first()[0]
if stock_max is not None:
    lag = (datetime.now(ZoneInfo("Asia/Seoul")).date() - stock_max).days
    print(f"KRX Silver 최신일로부터 경과: {lag}일 (주말/휴장일 감안)")
    if lag > 10:
        raise RuntimeError("Silver 주가 데이터가 10일 이상 오래되었습니다. Bronze 수집·원천 경로를 확인하세요")
    if kospi_max is None or kospi_max < stock_max:
        raise RuntimeError(f"KOSPI Silver 최신일 {kospi_max}이 주식 최신일 {stock_max}보다 오래되었습니다")

for macro in ["usdkrw","us_treasury_10y","wti","vix","korea_3y"]:
    latest = spark.table(SILVER_TABLES[macro]).agg(F.max("observation_date")).first()[0]
    if stock_max and (latest is None or (stock_max - latest).days > 14):
        raise RuntimeError(f"{macro} Silver가 주식 거래일보다 14일 이상 오래되었습니다: {latest}")
print("Silver 7개 테이블 증분 갱신 완료 — 후속 Gold Notebook 실행 가능")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# 2026-11-09 12:50 KST 민철 추가 — 공표 근거와 실제 수집 시각을 구분한 날짜별 이용 가능 자료를 Gold에 전달합니다.

_days=[r[0] for r in spark.table('silver_stock_daily').select('trading_date').distinct().collect()]
_curve=macro_curve(_days,_historical_provenance,_official_files)
_out=Path('/lakehouse/default/Files/silver_evidence');_out.mkdir(parents=True,exist_ok=True)
_curve.to_parquet(_out/'observation_provenance.parquet',index=False)
print('거시 이용 가능 근거',_curve.groupby('source').verified.sum().to_dict())
print('정확한 공표 시각은 미확인일 수 있습니다. known_by는 검증된 이용 가능 상한시각입니다.')

# METADATA ********************
# META {"language":"python","language_group":"synapse_pyspark"}
