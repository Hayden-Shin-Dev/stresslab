-- [시장국면분석ML] PostgreSQL 스키마 (Azure Database for PostgreSQL, 기존 서비스 DB에 별도 스키마로 추가)
-- Fabric 파이프라인 Copy 작업: Lakehouse regime_pg_snapshot → regime.snapshot,
--                                regime_pg_daily    → regime.daily   (snapshot 먼저, daily 나중)
-- API는 regime.snapshot의 최신 행(payload_text)만 읽습니다. regime.daily는 SQL 조회·BI용입니다.

create schema if not exists regime;

create table if not exists regime.snapshot (
    snapshot_version      text        primary key,            -- 예: 20261118T001503Z
    as_of                 date        not null,               -- 마지막 거래일 (Gold 최신일)
    model_version         text        not null,               -- regime-hmm-v1
    data_mode             text        not null check (data_mode in ('fabric_gold', 'synthetic_fixture')),
    gold_snapshot_version text,                               -- Gold 인증 스냅샷 버전 (추적용)
    payload_text          text        not null,               -- 스냅샷 JSON 원문 (sha256 대조를 위해 text로 보관)
    payload_sha256        char(64)    not null,
    created_at            timestamp   not null                -- UTC
);
create index if not exists snapshot_latest_idx on regime.snapshot (data_mode, as_of desc, created_at desc);

create table if not exists regime.daily (
    snapshot_version text             not null references regime.snapshot (snapshot_version) on delete cascade,
    trading_date     date             not null,
    kospi_close      double precision,
    regime_code      text             not null check (regime_code in ('bull', 'sideways', 'bear')),
    p_bull           double precision,
    p_sideways       double precision,
    p_bear           double precision,
    raw_code         text,
    label_basis      text,                                    -- walk_forward | initial_in_sample
    primary key (snapshot_version, trading_date)
);

-- 최신 운영 스냅샷 (API와 같은 기준)
create or replace view regime.v_latest_snapshot as
select snapshot_version, as_of, model_version, gold_snapshot_version, payload_sha256, created_at
from regime.snapshot
where data_mode = 'fabric_gold'
order by as_of desc, created_at desc
limit 1;

create or replace view regime.v_latest_daily as
select d.*
from regime.daily d
join regime.v_latest_snapshot s using (snapshot_version);

-- 보관 정책 예시: 최근 60개 스냅샷만 유지 (파이프라인 마지막 Script 작업으로 실행 가능)
-- delete from regime.snapshot where snapshot_version not in (
--     select snapshot_version from regime.snapshot order by created_at desc limit 60);

-- API 읽기 전용 계정 예시 (계정 이름은 팀 규칙에 맞게 변경)
-- create role regime_api_reader login password '<Key Vault에 보관>';
-- grant usage on schema regime to regime_api_reader;
-- grant select on all tables in schema regime to regime_api_reader;
