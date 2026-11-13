-- 토론 실행기 테이블 (PostgreSQL, psql-whatif-dev)
-- 실행 순서: 이 파일 한 번. 다시 실행해도 안전합니다(IF NOT EXISTS).
-- 쓰기: 토론 실행기 관리 ID / 읽기: FastAPI(재접속 시 after_seq 조회, 회의록)

-- 토론 1건
CREATE TABLE IF NOT EXISTS debate (
    debate_id           text PRIMARY KEY,
    user_id             text        NOT NULL,
    trigger             text        NOT NULL CHECK (trigger IN ('user', 'scheduled')),
    scheduled_slot      text,
    run_id              text        NOT NULL,          -- Stress Engine 결과 (숫자 고정)
    snapshot_id         text,                          -- 시장 상태 스냅샷 (근거 고정 시 채움)
    evidence_bundle_id  text,
    status              text        NOT NULL DEFAULT 'accepted'
                        CHECK (status IN ('accepted', 'running', 'completed', 'failed')),
    error               text,
    last_seq            integer     NOT NULL DEFAULT 0,  -- 마지막으로 만든 이벤트 순번
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS debate_user_created ON debate (user_id, created_at DESC);

-- 큐로 받은 요청. request_id(=MessageId)로 중복 처리를 막습니다.
CREATE TABLE IF NOT EXISTS debate_request (
    request_id    text PRIMARY KEY,
    debate_id     text        NOT NULL REFERENCES debate (debate_id),
    type          text        NOT NULL CHECK (type IN ('debate_start', 'user_question')),
    payload       jsonb       NOT NULL,
    received_at   timestamptz NOT NULL DEFAULT now(),
    processed_at  timestamptz
);

-- 근거 묶음. 한 번 만들면 바꾸지 않습니다. 같은 토론의 모든 발언이 같은 묶음을 봅니다.
CREATE TABLE IF NOT EXISTS evidence_bundle (
    evidence_bundle_id  text PRIMARY KEY,
    debate_id           text        NOT NULL REFERENCES debate (debate_id),
    payload             jsonb       NOT NULL,   -- D_sources(역할별 범위 포함), S_sources, 원본 run/snapshot 요약
    sha256              text        NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- 페르소나 발언과 요약. message_id는 (토론, 라운드, 역할, 단계, 질문)으로 정해져 재처리해도 같습니다.
CREATE TABLE IF NOT EXISTS debate_message (
    message_id             text PRIMARY KEY,
    debate_id              text        NOT NULL REFERENCES debate (debate_id),
    round_id               text        NOT NULL,
    phase                  text        NOT NULL,    -- INITIAL, REBUTTAL, USER_ANSWER, SUMMARY
    role                   text        NOT NULL,    -- macro, market, risk, portfolio, moderator
    question_id            text,
    reference_message_id   text,
    status                 text        NOT NULL CHECK (status IN ('published', 'failed')),
    output                 jsonb,                   -- 검증 통과한 모델 출력 (실패 시 NULL)
    error                  text,
    model_deployment       text,
    prompt_version         text,
    created_at             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS debate_message_debate ON debate_message (debate_id, created_at);

-- 화면으로 보낼 이벤트 (outbox). 저장 후 발행하고 published_at을 채웁니다.
-- 재접속한 화면은 GET .../events?after_seq=N 으로 이 테이블을 읽습니다.
CREATE TABLE IF NOT EXISTS debate_event (
    debate_id     text        NOT NULL REFERENCES debate (debate_id),
    seq           integer     NOT NULL,
    event_id      text        NOT NULL UNIQUE,
    type          text        NOT NULL,
    payload       jsonb       NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    published_at  timestamptz,
    PRIMARY KEY (debate_id, seq)
);
CREATE INDEX IF NOT EXISTS debate_event_unpublished ON debate_event (debate_id, seq) WHERE published_at IS NULL;

-- 사용자 보유 종목 (웹앱에서 저장, 토론 요청 API가 읽고 씀). 금액 기준(원).
-- 정시 회의 대상과 (Stress Engine 연결 후) 분석 입력 positions[{asset_id, value_krw}]가 여기서 나옵니다.
CREATE TABLE IF NOT EXISTS user_holding (
    user_id     text        NOT NULL,          -- SWA 로그인 ID: '{identityProvider}:{userId}' (예: aad:1a2b...)
    asset_id    text        NOT NULL CHECK (asset_id ~ '^[0-9A-Z]{6}$'),
    amount_krw  numeric     NOT NULL CHECK (amount_krw > 0),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, asset_id)
);
CREATE INDEX IF NOT EXISTS user_holding_updated ON user_holding (updated_at DESC);

-- 권한 (Entra 관리자로 접속해 한 번 실행). 관리 ID 이름은 실제 이름으로 바꿉니다.
-- SELECT * FROM pgaadauth_create_principal('id-debate-whatif-dev', false, false);
-- GRANT USAGE ON SCHEMA public TO "id-debate-whatif-dev";
-- GRANT SELECT, INSERT, UPDATE ON debate, debate_request, debate_message, debate_event TO "id-debate-whatif-dev";
-- GRANT SELECT, INSERT ON evidence_bundle TO "id-debate-whatif-dev";
-- GRANT SELECT, INSERT, UPDATE, DELETE ON user_holding TO "id-debate-whatif-dev";   -- 보유 종목 저장(API)

-- 토론 요청 API(ca-debateapi-whatif-dev)는 토론 테이블은 읽기만 하고, user_holding만 씁니다.
-- 실행기와 같은 관리 ID를 쓰면 위 user_holding 권한 한 줄만 추가하면 됩니다.
-- 별도 관리 ID를 쓰면:
-- SELECT * FROM pgaadauth_create_principal('id-debateapi-whatif-dev', false, false);
-- GRANT USAGE ON SCHEMA public TO "id-debateapi-whatif-dev";
-- GRANT SELECT ON debate, debate_event TO "id-debateapi-whatif-dev";
-- GRANT SELECT, INSERT, UPDATE, DELETE ON user_holding TO "id-debateapi-whatif-dev";


-- 웹 분석 결과 (공통 API POST /api/stress/analyze가 저장, 토론 실행기가 run_id로 읽음). 저장 후 바꾸지 않음.
CREATE TABLE IF NOT EXISTS stress_run (
    run_id           text        PRIMARY KEY,           -- 응답의 analysis_id (a-...)
    user_id          text        NOT NULL,
    request          jsonb       NOT NULL,              -- 보유 종목·충격·모델
    result           jsonb       NOT NULL,              -- ai_context.stress_run (evidence.build_bundle 입력)
    market_snapshot  jsonb,                             -- 분석 시점 장중 스냅샷 (토론에서 그대로 사용)
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS stress_run_user ON stress_run (user_id, created_at DESC);
GRANT SELECT, INSERT ON stress_run TO "id-debate-whatif-dev";
