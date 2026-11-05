"""contracts.py를 기준으로 contracts/debate/*.schema.json을 다시 만듭니다.

실행: python services/debate/src/export_contracts.py
"""
import json
from pathlib import Path

import contracts as c

out = Path(__file__).resolve().parents[3] / "contracts" / "debate"
out.mkdir(parents=True, exist_ok=True)


def write(name, schema):
    (out / name).write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("저장:", out / name)


write("request.schema.json", c.DebateRequest.model_json_schema())
write("event.schema.json", c.DebateEvent.model_json_schema())
for role in c.ROLES:
    write(f"persona_output.{role}.schema.json", c.persona_output_schema(role))
write("summary_output.schema.json", c.summary_output_schema())
