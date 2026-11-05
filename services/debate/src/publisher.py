"""저장된 이벤트를 Web PubSub(hub=debate, group=debate-{debate_id})로 보냅니다.

순서: DB 저장(outbox) → 발행 → published_at 기록. 발행이 실패해도 이벤트는 DB에 남아
다음 단계에서 다시 보내고, 재접속한 화면은 after_seq로 받습니다.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Protocol

from contracts import group_name

log = logging.getLogger("debate.publisher")


class Sender(Protocol):
    async def send(self, group: str, message: dict) -> None: ...


class WebPubSubSender:
    def __init__(self, endpoint: str, hub: str, credential):
        from azure.messaging.webpubsubservice import WebPubSubServiceClient
        self._client = WebPubSubServiceClient(endpoint=endpoint, hub=hub, credential=credential)

    async def send(self, group, message):
        await asyncio.to_thread(self._client.send_to_group, group, message, content_type="application/json",
                                connection_timeout=10, read_timeout=20, retry_total=2)


class MemorySender:
    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    async def send(self, group, message):
        self.sent.append((group, message))


class Publisher:
    def __init__(self, store, sender: Sender):
        self.store, self.sender = store, sender

    async def flush(self, debate_id: str) -> None:
        for ev in await self.store.pending_events(debate_id):
            message = {
                "schema_version": "1.0",
                "debate_id": ev["debate_id"],
                "seq": ev["seq"],
                "event_id": ev["event_id"],
                "type": ev["type"],
                "created_at": ev["created_at"].isoformat() if hasattr(ev["created_at"], "isoformat") else ev["created_at"],
                "payload": ev["payload"],
            }
            try:
                await self.sender.send(group_name(debate_id), json.loads(json.dumps(message, default=str)))
            except Exception as e:  # 다음 flush에서 다시 보냄. 순서를 지키려고 여기서 멈춤
                log.warning("발행 실패 debate=%s seq=%s: %s", debate_id, ev["seq"], type(e).__name__)
                return
            await self.store.mark_published(debate_id, ev["seq"])
