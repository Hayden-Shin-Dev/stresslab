"""모델 호출과 프롬프트 로딩.

Azure OpenAI는 관리 ID(Entra) 토큰으로 호출하고, 응답 형식은 structured outputs(strict JSON schema)로 강제합니다.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Protocol

log = logging.getLogger("debate.llm")
PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


class LLMError(Exception):
    """재시도해도 소용없는 응답 문제(거부, JSON 아님)."""


class LLM(Protocol):
    deployment: str

    async def complete(self, system: str, user: str, schema: dict, schema_name: str) -> dict: ...


class Prompts:
    """roles/<role>.md(공통 정책이 들어 있는 독립형 프롬프트), moderator.md. 시작할 때 한 번 읽습니다."""

    def __init__(self, directory: Path = PROMPT_DIR):
        self.persona = {}
        for f in sorted((directory / "roles").glob("*.md")):
            # 프롬프트 작성자가 메모장으로 저장하면 BOM이 붙어 옵니다.
            self.persona[f.stem] = f.read_text(encoding="utf-8-sig").strip() + "\n"
        self.moderator = (directory / "moderator.md").read_text(encoding="utf-8-sig")
        joined = json.dumps([self.persona, self.moderator], ensure_ascii=False, sort_keys=True)
        self.version = "p-" + hashlib.sha256(joined.encode()).hexdigest()[:12]


class AzureOpenAILLM:
    def __init__(self, endpoint: str, deployment: str, api_version: str, client_id: str | None = None,
                 timeout: float = 90.0, max_retries: int = 3):
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        from openai import AsyncAzureOpenAI

        token = get_bearer_token_provider(DefaultAzureCredential(managed_identity_client_id=client_id),
                                          "https://cognitiveservices.azure.com/.default")
        # openai SDK가 429/5xx/timeout을 지수 백오프로 재시도합니다.
        self._client = AsyncAzureOpenAI(azure_endpoint=endpoint, api_version=api_version,
                                        azure_ad_token_provider=token, timeout=timeout, max_retries=max_retries)
        self.deployment = deployment

    async def complete(self, system: str, user: str, schema: dict, schema_name: str) -> dict:
        resp = await self._client.chat.completions.create(
            model=self.deployment,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": schema_name, "schema": schema, "strict": True}},
        )
        choice = resp.choices[0]
        if getattr(choice.message, "refusal", None):
            raise LLMError(f"refusal: {choice.message.refusal[:200]}")
        if choice.finish_reason == "length":
            raise LLMError("응답이 길이 제한에서 잘림")
        try:
            return json.loads(choice.message.content)
        except (TypeError, json.JSONDecodeError) as e:
            raise LLMError(f"JSON 아님: {e}") from e


class LimitedLLM:
    """동시 호출 수를 제한합니다 (네 역할 병렬 × 여러 토론)."""

    def __init__(self, inner: LLM, max_concurrency: int):
        self._inner, self._sem = inner, asyncio.Semaphore(max_concurrency)
        self.deployment = inner.deployment

    async def complete(self, system, user, schema, schema_name):
        async with self._sem:
            return await self._inner.complete(system, user, schema, schema_name)
