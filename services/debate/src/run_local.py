"""배포 전 로컬 테스트: 토론 한 건을 내 PC에서 실제 Azure OpenAI로 돌려봅니다.

Service Bus, PostgreSQL, Web PubSub 없이 실행합니다(메모리 저장, 이벤트는 화면과 파일로 출력).
인증은 `az login`한 내 계정을 씁니다. 내 계정에 Azure OpenAI 리소스의
'Cognitive Services OpenAI User' 역할이 있어야 합니다(소유자 역할만으로는 모델 호출 불가).

실행 (저장소 최상위, PowerShell)
  az login
  $env:AZURE_OPENAI_ENDPOINT = "https://<이름>.openai.azure.com"
  $env:AZURE_OPENAI_DEPLOYMENT = "<배포 이름>"
  $env:AZURE_OPENAI_API_VERSION = "2024-10-21"     # 오류 나면 포털 예시 코드의 api-version
  $env:MARKET_STATE_URL = "https://ca-marketstate-whatif-dev....azurecontainerapps.io"   # 없으면 합성 스냅샷
  python services/debate/src/run_local.py --run-id stress_run --question "금리 충격만 보면 어떤가요?"

결과: 화면에 발언 요약, services/debate/local_runs/<debate_id>.json에 전체 이벤트
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import contracts as c
import llm as llm_mod
import sources
from orchestrator import Orchestrator
from publisher import MemorySender, Publisher
from store import MemoryStore

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def show(event: dict) -> None:
    t, p = event["type"], event["payload"]
    if t == "message.created":
        print(f"\n[{event['seq']}] {p['name']}({p['role']}) {p['phase']}  {p['response_status']}/{p['view_status']}")
        print("   ", p["summary_text"])
        print("   ", p["display_text"][:400].replace("\n", " "))
        if p["questions_to_roles"]:
            q = p["questions_to_roles"][0]
            print(f"    -> {q['role']}에게: {q['question']}")
        print("    근거:", ", ".join(p["structured_source_ids"] + p["rag_source_ids"]) or "-")
    elif t == "message.failed":
        print(f"\n[{event['seq']}] 실패: {p['name']}({p['role']}) {p['phase']} 실패")
    elif t == "debate.summary":
        print(f"\n[{event['seq']}] 요약 ({p.get('status')}): {p.get('summary_text') or p.get('error')}")
        for d in p.get("disagreements", []):
            print("    이견:", d["issue"], "/", ", ".join(f"{x['role']}={x['stance']}" for x in d["positions"]))
    else:
        print(f"[{event['seq']}] {t} {json.dumps(p, ensure_ascii=False)[:200]}")


async def main(args) -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    model = llm_mod.LimitedLLM(
        llm_mod.AzureOpenAILLM(os.environ["AZURE_OPENAI_ENDPOINT"], os.environ["AZURE_OPENAI_DEPLOYMENT"],
                               os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")),
        4)
    market = (sources.HttpMarketStateSource(os.environ["MARKET_STATE_URL"]) if os.environ.get("MARKET_STATE_URL")
              else sources.FileMarketStateSource(str(ROOT / "tests" / "fixtures" / "market_snapshot.json")))
    store, sender = MemoryStore(), MemorySender()
    orch = Orchestrator(store, Publisher(store, sender), model, llm_mod.Prompts(),
                        sources.FileStressSource(str(ROOT / "runs")), market)

    debate_id = args.debate_id or "local-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    now = datetime.now(timezone.utc)
    started = time.perf_counter()
    printed = 0

    async def watch():
        nonlocal printed
        while True:
            while printed < len(sender.sent):
                show(sender.sent[printed][1]); printed += 1
            await asyncio.sleep(0.3)

    watcher = asyncio.create_task(watch())
    try:
        await orch.handle(c.DebateRequest(type="debate_start", request_id=f"{debate_id}-start", debate_id=debate_id,
                                          user_id="local", run_id=args.run_id, snapshot_id=args.snapshot_id,
                                          created_at=now), final_attempt=True)
        if args.question:
            await orch.handle(c.DebateRequest(
                type="user_question", request_id=f"{debate_id}-q1", debate_id=debate_id, user_id="local",
                run_id=args.run_id, created_at=now,
                question=c.UserQuestion(question_id="Q1", text=args.question, target_roles=args.roles)),
                final_attempt=True)
    finally:
        await asyncio.sleep(0.5)
        watcher.cancel()
        while printed < len(sender.sent):
            show(sender.sent[printed][1]); printed += 1

    out = ROOT / "local_runs" / f"{debate_id}.json"
    out.parent.mkdir(exist_ok=True)
    failed = [m for m in await store.list_messages(debate_id) if m["status"] == "failed"]
    out.write_text(json.dumps({"events": [m for _, m in sender.sent],
                               "failed": [{k: m[k] for k in ("role", "phase", "error")} for m in failed]},
                              ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\n완료 {time.perf_counter() - started:.0f}초, 이벤트 {len(sender.sent)}건, 실패 {len(failed)}건 -> {out}")
    for m in failed:
        print(f"  실패 {m['role']} {m['phase']}: {m['error']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", default="stress_run")
    p.add_argument("--snapshot-id", default=None, help="비우면 시장 상태 API의 현재값")
    p.add_argument("--debate-id", default=None)
    p.add_argument("--question", default=None, help="토론 뒤 이어서 할 사용자 질문")
    p.add_argument("--roles", nargs="+", default=["macro", "risk"], choices=list(c.ROLES))
    sys.exit(asyncio.run(main(p.parse_args())))
