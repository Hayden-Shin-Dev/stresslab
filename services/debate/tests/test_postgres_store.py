"""PostgresStore로 같은 흐름을 검증합니다. PG_TEST_DSN이 있을 때만 실행합니다.

예: PG_TEST_DSN="host=/tmp port=55432 user=postgres dbname=debate_test" python -m pytest services/debate/tests -q
테스트 DB에 sql/debate_tables.sql을 먼저 적용하세요. 실행할 때마다 debate 관련 테이블을 비웁니다.
"""
import asyncio
import os

import pytest

from test_debate import FakeLLM, FIX, start_req  # noqa: F401  (sys.path 설정 포함)
import contracts as c
from llm import Prompts
from orchestrator import Orchestrator, TransientError
from publisher import MemorySender, Publisher
from sources import FileMarketStateSource, FileStressSource
from store import PostgresStore

DSN = os.environ.get("PG_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="PG_TEST_DSN 없음")


async def _setup(llm):
    from psycopg_pool import AsyncConnectionPool
    pool = AsyncConnectionPool(DSN, min_size=1, max_size=4, open=False)
    await pool.open()
    async with pool.connection() as conn:
        await conn.execute("TRUNCATE debate_event, debate_message, evidence_bundle, debate_request, debate CASCADE")
    store, sender = PostgresStore(pool), MemorySender()
    orch = Orchestrator(store, Publisher(store, sender), llm, Prompts(), FileStressSource(str(FIX)),
                        FileMarketStateSource(str(FIX / "market_snapshot.json")))
    return pool, store, sender, orch


def test_postgres_full_flow_resume_and_question():
    async def main():
        pool, store, sender, orch = await _setup(FakeLLM(fail={"risk": 1}))
        with pytest.raises(TransientError):
            await orch.handle(start_req())
        await orch.handle(start_req())           # 재배달 → 이어서 완료
        await orch.handle(start_req())           # 처리 완료 요청 재배달 → 무시
        q = c.DebateRequest(type="user_question", request_id="req-2", debate_id="dbt-1", user_id="u1",
                            run_id="stress_run", created_at="2026-11-04T05:05:00Z",
                            question=c.UserQuestion(question_id="Q1", text="질문", target_roles=["portfolio"]))
        await orch.handle(q)
        async with pool.connection() as conn:
            seqs = [r[0] for r in await (await conn.execute(
                "SELECT seq FROM debate_event WHERE debate_id='dbt-1' ORDER BY seq")).fetchall()]
            unpublished = (await (await conn.execute(
                "SELECT count(*) FROM debate_event WHERE published_at IS NULL")).fetchone())[0]
            status = (await (await conn.execute("SELECT status FROM debate")).fetchone())[0]
            n_msgs = (await (await conn.execute("SELECT count(*) FROM debate_message")).fetchone())[0]
        await pool.close()
        return seqs, unpublished, status, n_msgs, [m["type"] for _, m in sender.sent]

    seqs, unpublished, status, n_msgs, sent = asyncio.run(main())
    assert seqs == list(range(1, len(seqs) + 1))
    assert unpublished == 0 and status == "completed"
    assert n_msgs == 4 + 2 + 1 + 1                 # 초기·반론·요약·질문 답변
    assert sent.count("message.created") == 7 and len(sent) == len(seqs)
