"""토론 실행기 개발용 도구. `az login`한 내 계정으로 실제 Azure 리소스를 씁니다.

  python services/debate/src/dev_tools.py apply-sql                     # debate 테이블 만들기
  python services/debate/src/dev_tools.py send --debate-id test-001     # 토론 시작 메시지 보내기
  python services/debate/src/dev_tools.py send --debate-id test-001 --question "금리만 보면?" --roles macro risk
  python services/debate/src/dev_tools.py events --debate-id test-001   # 저장된 이벤트 보기

환경변수: PG_HOST, PG_DB(기본 postgres), PG_USER(내 Entra 로그인 이메일),
          SERVICEBUS_NAMESPACE, SERVICEBUS_QUEUE(기본 debate-requests)
"""
from __future__ import annotations

import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

SQL = Path(__file__).resolve().parents[1] / "sql" / "debate_tables.sql"


def pg():
    import psycopg
    from azure.identity import DefaultAzureCredential
    token = DefaultAzureCredential().get_token("https://ossrdbms-aad.database.windows.net/.default").token
    return psycopg.connect(host=os.environ["PG_HOST"], dbname=os.environ.get("PG_DB", "postgres"),
                           user=os.environ["PG_USER"], password=token, sslmode="require", connect_timeout=15)


def apply_sql(_):
    with pg() as conn:
        conn.execute(SQL.read_text(encoding="utf-8"))
        names = [r[0] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'debate%' "
            "OR table_name = 'evidence_bundle' ORDER BY 1").fetchall()]
    print("테이블:", ", ".join(names))


def send(args):
    from azure.identity import DefaultAzureCredential
    from azure.servicebus import ServiceBusClient, ServiceBusMessage
    import contracts as c

    request_id = f"{args.debate_id}-{uuid.uuid4().hex[:8]}"
    body = {"type": "user_question" if args.question else "debate_start", "request_id": request_id,
            "debate_id": args.debate_id, "user_id": args.user_id, "run_id": args.run_id,
            "snapshot_id": args.snapshot_id, "created_at": datetime.now(timezone.utc).isoformat()}
    if args.question:
        body["question"] = {"question_id": "Q-" + uuid.uuid4().hex[:6], "text": args.question,
                            "target_roles": args.roles}
    c.DebateRequest.model_validate(body)   # 보내기 전에 계약 검사
    with ServiceBusClient(os.environ["SERVICEBUS_NAMESPACE"], DefaultAzureCredential()) as sb, \
            sb.get_queue_sender(os.environ.get("SERVICEBUS_QUEUE", "debate-requests")) as sender:
        sender.send_messages(ServiceBusMessage(json.dumps(body, ensure_ascii=False), session_id=args.debate_id,
                                               message_id=request_id, content_type="application/json"))
    print("보냄:", json.dumps(body, ensure_ascii=False))


def events(args):
    with pg() as conn:
        d = conn.execute("SELECT status, error, evidence_bundle_id, snapshot_id FROM debate WHERE debate_id=%s",
                         (args.debate_id,)).fetchone()
        if not d:
            print("토론 없음 (아직 처리 전이거나 debate_id가 다름)")
            return
        print(f"상태 {d[0]}  근거 {d[2]}  스냅샷 {d[3]}  {d[1] or ''}")
        for seq, typ, payload, published in conn.execute(
                "SELECT seq, type, payload, published_at IS NOT NULL FROM debate_event "
                "WHERE debate_id=%s ORDER BY seq", (args.debate_id,)).fetchall():
            who = f"{payload.get('name', '')}({payload.get('role', '')}) {payload.get('phase', '')}" if "role" in payload else ""
            text = payload.get("summary_text") or payload.get("reason") or ""
            print(f"[{seq:>2}] {'발행' if published else '미발행'} {typ:<22} {who} {text[:80]}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("apply-sql").set_defaults(fn=apply_sql)
    s = sub.add_parser("send")
    s.add_argument("--debate-id", required=True)
    s.add_argument("--run-id", default="stress_run")
    s.add_argument("--snapshot-id", default=None)
    s.add_argument("--user-id", default="local-test")
    s.add_argument("--question", default=None)
    s.add_argument("--roles", nargs="+", default=["macro", "risk"])
    s.set_defaults(fn=send)
    e = sub.add_parser("events")
    e.add_argument("--debate-id", required=True)
    e.set_defaults(fn=events)
    a = p.parse_args()
    a.fn(a)
