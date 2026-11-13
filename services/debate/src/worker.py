"""whatif 토론 실행기 (Container Apps, ingress 없음).

Service Bus debate-requests(세션 큐)에서 요청을 받아 토론을 진행합니다.
- 세션 = debate_id. 같은 토론의 메시지는 한 실행기가 순서대로 처리합니다.
- 처리하는 동안 세션·메시지 잠금을 자동 연장하고, 끝나면 complete합니다.
- 모델·조회 장애는 abandon → 재배달되면 저장된 발언은 건너뛰고 이어서 진행합니다.
- 마지막 배달(MAX_DELIVERY)에서는 실패한 역할을 '실패'로 저장하고 토론을 마칩니다.

환경변수
  SERVICEBUS_NAMESPACE       예: sb-whatif-dev.servicebus.windows.net
  SERVICEBUS_QUEUE           기본 debate-requests (세션 사용, 중복 검색 사용)
  MAX_SESSIONS               동시에 처리할 토론 수 (기본 2)
  MAX_DELIVERY               큐의 최대 배달 횟수와 같게 (기본 5)
  AZURE_CLIENT_ID            사용자 할당 관리 ID
  AZURE_OPENAI_ENDPOINT      예: https://<이름>.openai.azure.com
  AZURE_OPENAI_DEPLOYMENT    배포 이름 (모델 ID 아님)
  AZURE_OPENAI_API_VERSION   기본 2024-10-21
  LLM_MAX_CONCURRENCY        동시 모델 호출 수 (기본 4)
  PG_HOST, PG_DB, PG_USER    PostgreSQL (PG_USER = 관리 ID 이름)
  WPS_ENDPOINT               예: https://wps-whatif-dev.webpubsub.azure.com
  WPS_HUB                    기본 debate
  MARKET_STATE_URL           시장 상태 API 주소
  STRESS_ENGINE_URL          Stress Engine 주소. 없으면 STRESS_RUN_DIR의 파일을 읽음(개발용)
  DART_API_KEY               OpenDART 인증키(비밀값). 없으면 공시 근거 없이 진행
  DART_LOOKBACK_DAYS         공시 조회 기간 (기본 7일)
  DART_MAX_PER_ASSET         종목당 공시 수 (기본 5)
  DART_CACHE_MINUTES         같은 종목 재사용 시간 (기본 30분)
  NEWS_ENABLED               true면 웹 뉴스 검색(Azure OpenAI web_search) 사용. 기본 꺼짐(과금 별도)
  NEWS_DEPLOYMENT            웹 검색에 쓸 배포 (기본 AZURE_OPENAI_DEPLOYMENT)
  NEWS_MAX_ASSETS            검색할 종목 수 (기본 3)
  NEWS_LOOKBACK_DAYS         뉴스 기간 (기본 7일)
  NEWS_CACHE_MINUTES         같은 종목 재사용 시간 (기본 1440분 = 같은 날 한 번)
  NEWS_MAX_SEARCHES          종목당 웹 검색 최대 횟수 (기본 2)
  NEWS_REASONING_EFFORT      웹 검색 추론 강도 (기본 low, 빈 값이면 보내지 않음)
  NEWS_DAILY_REQUEST_LIMIT   하루 Bing 요청 상한 (기본 300)
"""
from __future__ import annotations

import asyncio
import logging
import os

from pydantic import ValidationError

from contracts import DebateRequest
from orchestrator import Orchestrator, TransientError

log = logging.getLogger("debate.worker")


async def process(receiver, msg, orchestrator: Orchestrator, max_delivery: int) -> None:
    try:
        req = DebateRequest.model_validate_json(str(msg))
    except ValidationError as e:
        await receiver.dead_letter_message(msg, reason="invalid_request", error_description=str(e)[:1000])
        return
    if req.debate_id != msg.session_id or req.request_id != msg.message_id:
        await receiver.dead_letter_message(msg, reason="id_mismatch",
                                           error_description="SessionId=debate_id, MessageId=request_id 이어야 합니다")
        return
    final = (msg.delivery_count or 0) >= max_delivery
    try:
        await orchestrator.handle(req, final_attempt=final)
    except TransientError as e:
        log.warning("일시 오류, 재배달 %s (%d회째): %s", req.request_id, msg.delivery_count, e)
        await receiver.abandon_message(msg)
        return
    except Exception:
        log.exception("처리 실패 %s", req.request_id)
        await receiver.abandon_message(msg)
        return
    await receiver.complete_message(msg)


async def session_loop(client, queue: str, orchestrator: Orchestrator, max_delivery: int, n: int) -> None:
    from azure.servicebus import NEXT_AVAILABLE_SESSION
    from azure.servicebus.aio import AutoLockRenewer
    from azure.servicebus.exceptions import OperationTimeoutError

    renewer = AutoLockRenewer(max_lock_renewal_duration=900)
    while True:
        try:
            async with client.get_queue_receiver(queue, session_id=NEXT_AVAILABLE_SESSION, max_wait_time=30,
                                                 auto_lock_renewer=renewer) as receiver:
                log.info("[%d] 세션 %s 시작", n, receiver.session.session_id)
                async for msg in receiver:
                    await process(receiver, msg, orchestrator, max_delivery)
        except OperationTimeoutError:
            continue   # 처리할 세션 없음
        except Exception:
            log.exception("[%d] 수신 오류, 5초 후 다시", n)
            await asyncio.sleep(5)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    from azure.identity import DefaultAzureCredential
    from azure.identity.aio import DefaultAzureCredential as AioCredential
    from azure.servicebus.aio import ServiceBusClient

    import disclosures
    import news
    import llm as llm_mod
    import sources
    from publisher import Publisher, WebPubSubSender
    from store import PostgresStore

    client_id = os.environ.get("AZURE_CLIENT_ID")
    cred = DefaultAzureCredential(managed_identity_client_id=client_id)
    store = await PostgresStore.connect(os.environ["PG_HOST"], os.environ.get("PG_DB", "postgres"),
                                        os.environ["PG_USER"], cred)
    publisher = Publisher(store, WebPubSubSender(os.environ["WPS_ENDPOINT"], os.environ.get("WPS_HUB", "debate"), cred))
    model = llm_mod.LimitedLLM(
        llm_mod.AzureOpenAILLM(os.environ["AZURE_OPENAI_ENDPOINT"], os.environ["AZURE_OPENAI_DEPLOYMENT"],
                               os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"), client_id),
        int(os.environ.get("LLM_MAX_CONCURRENCY", "4")))
    fallback = (sources.HttpStressSource(os.environ["STRESS_ENGINE_URL"]) if os.environ.get("STRESS_ENGINE_URL")
                else sources.FileStressSource(os.environ.get("STRESS_RUN_DIR", "runs")))
    stress = sources.PostgresStressSource(store, fallback)   # 웹 분석 결과(stress_run 테이블) 먼저
    market = sources.HttpMarketStateSource(os.environ["MARKET_STATE_URL"])
    orch = Orchestrator(store, publisher, model, llm_mod.Prompts(), stress, market,
                        disclosures=disclosures.from_env(os.environ),
                        news=news.from_env(os.environ, client_id))

    queue = os.environ.get("SERVICEBUS_QUEUE", "debate-requests")
    max_delivery = int(os.environ.get("MAX_DELIVERY", "5"))
    sessions = int(os.environ.get("MAX_SESSIONS", "2"))
    async with ServiceBusClient(os.environ["SERVICEBUS_NAMESPACE"], AioCredential(managed_identity_client_id=client_id)) as sb:
        log.info("수신 시작 queue=%s sessions=%d", queue, sessions)
        await asyncio.gather(*(session_loop(sb, queue, orch, max_delivery, i) for i in range(sessions)))


if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        # Windows 기본 이벤트 루프(Proactor)는 psycopg 비동기 연결을 지원하지 않습니다. (로컬 실행용, 컨테이너는 Linux)
        asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(main())
