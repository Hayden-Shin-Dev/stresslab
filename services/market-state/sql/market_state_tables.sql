-- whatif 시장 상태 API 테이블 (psql-whatif-dev, Function과 같은 DB)
-- Entra 관리자로 접속해 실행합니다. 여러 번 실행해도 안전합니다.

-- 이력: 스냅샷 1건 = 1행. snapshot_id가 같으면 다시 넣지 않습니다.
CREATE TABLE IF NOT EXISTS market_state_snapshot (
    snapshot_id     text        PRIMARY KEY,
    as_of           timestamptz NOT NULL,
    computed_at     timestamptz NOT NULL,
    universe_id     text        NOT NULL,
    quality_status  text        NOT NULL,
    schema_version  text        NOT NULL,
    payload         jsonb       NOT NULL,   -- market_state_snapshot v2 원본 그대로
    stored_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_market_state_snapshot_as_of
    ON market_state_snapshot (as_of DESC);

-- 최신값: 종목 범위(universe_id)마다 1행. 더 늦은 as_of만 덮어씁니다.
CREATE TABLE IF NOT EXISTS market_state_latest (
    universe_id     text        PRIMARY KEY,
    snapshot_id     text        NOT NULL REFERENCES market_state_snapshot (snapshot_id),
    as_of           timestamptz NOT NULL,
    quality_status  text        NOT NULL,
    payload         jsonb       NOT NULL,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- 시장 상태 API 관리 ID에는 이 두 테이블만 읽고 쓰는 권한을 줍니다 (삭제 권한 없음).
GRANT USAGE ON SCHEMA public TO "id-marketstate-whatif-dev";
GRANT SELECT, INSERT ON market_state_snapshot TO "id-marketstate-whatif-dev";
GRANT SELECT, INSERT, UPDATE ON market_state_latest TO "id-marketstate-whatif-dev";
