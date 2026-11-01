-- Fabric Spark Notebook의 SQL 셀에서 실행. Lakehouse를 먼저 연결합니다.
-- PK와 중복은 품질 검사로 확인합니다. Delta가 PK를 강제하지 않습니다.
SET spark.sql.session.timeZone=UTC;

-- KEY: instrument_id, valid_from, available_at
CREATE TABLE IF NOT EXISTS instrument_history (
  instrument_id STRING NOT NULL,
  symbol STRING NOT NULL,
  name STRING NOT NULL,
  market STRING NOT NULL,
  instrument_type STRING NOT NULL,
  sector_code STRING,
  valid_from DATE NOT NULL,
  valid_to DATE,
  listed_on DATE NOT NULL,
  delisted_on DATE,
  available_at TIMESTAMP NOT NULL,
  source STRING NOT NULL,
  source_ref STRING NOT NULL
) USING DELTA;

-- KEY: market, trade_date
CREATE TABLE IF NOT EXISTS trading_calendar (
  market STRING NOT NULL,
  trade_date DATE NOT NULL,
  is_open BOOLEAN NOT NULL,
  session_open_at TIMESTAMP,
  session_close_at TIMESTAMP,
  source_ref STRING NOT NULL
) USING DELTA;

-- KEY: instrument_id, trade_date, available_at
CREATE TABLE IF NOT EXISTS daily_price (
  instrument_id STRING NOT NULL,
  trade_date DATE NOT NULL,
  open DOUBLE,
  high DOUBLE,
  low DOUBLE,
  close DOUBLE,
  reference_price DOUBLE,
  return_1d DOUBLE,
  return_basis STRING NOT NULL,
  volume BIGINT,
  turnover_krw DOUBLE,
  market_cap_krw DOUBLE,
  trading_status STRING NOT NULL,
  available_at TIMESTAMP NOT NULL,
  availability_basis STRING NOT NULL,
  source_ref STRING NOT NULL,
  quality_status STRING NOT NULL
) USING DELTA;

-- KEY: series_id, observation_date, available_at
CREATE TABLE IF NOT EXISTS macro_observation (
  series_id STRING NOT NULL,
  factor_id STRING NOT NULL,
  observation_date DATE NOT NULL,
  value DOUBLE,
  unit STRING NOT NULL,
  published_at TIMESTAMP,
  available_at TIMESTAMP NOT NULL,
  availability_basis STRING NOT NULL,
  source STRING NOT NULL,
  source_ref STRING NOT NULL,
  quality_status STRING NOT NULL
) USING DELTA;

-- KEY: receipt_id
CREATE TABLE IF NOT EXISTS disclosure (
  receipt_id STRING NOT NULL,
  corp_code STRING NOT NULL,
  instrument_id STRING,
  report_name STRING NOT NULL,
  published_at TIMESTAMP,
  available_at TIMESTAMP NOT NULL,
  availability_basis STRING NOT NULL,
  amends_receipt_id STRING,
  source_url STRING NOT NULL
) USING DELTA;

-- KEY: instrument_id, venue, session, bar_start_at, available_at
CREATE TABLE IF NOT EXISTS minute_bar (
  instrument_id STRING NOT NULL,
  venue STRING NOT NULL,
  session STRING NOT NULL,
  bar_start_at TIMESTAMP NOT NULL,
  open DOUBLE,
  high DOUBLE,
  low DOUBLE,
  close DOUBLE,
  volume BIGINT,
  is_complete BOOLEAN NOT NULL,
  available_at TIMESTAMP NOT NULL,
  source STRING NOT NULL,
  quality_status STRING NOT NULL
) USING DELTA;

-- KEY: snapshot_id, metric_id
CREATE TABLE IF NOT EXISTS market_state (
  snapshot_id STRING NOT NULL,
  as_of TIMESTAMP NOT NULL,
  computed_at TIMESTAMP NOT NULL,
  state_kind STRING NOT NULL,
  base_trade_date DATE NOT NULL,
  scope_id STRING NOT NULL,
  universe_version STRING NOT NULL,
  metric_id STRING NOT NULL,
  value DOUBLE,
  unit STRING NOT NULL,
  expected_count INT NOT NULL,
  observed_count INT NOT NULL,
  coverage DOUBLE NOT NULL,
  oldest_input_at TIMESTAMP,
  status STRING NOT NULL,
  method_version STRING NOT NULL,
  validation_status STRING NOT NULL
) USING DELTA;

-- KEY: snapshot_id, metric_id, instrument_id
CREATE TABLE IF NOT EXISTS state_member (
  snapshot_id STRING NOT NULL,
  metric_id STRING NOT NULL,
  instrument_id STRING NOT NULL,
  included BOOLEAN NOT NULL,
  exclusion_reason STRING,
  source_observed_at TIMESTAMP,
  source_available_at TIMESTAMP,
  source_ref STRING
) USING DELTA;
