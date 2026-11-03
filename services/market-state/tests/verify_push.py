"""시장 상태 Web PubSub 수신 확인 (Cloud Shell용).

negotiate로 수신 전용 주소를 받아 접속하고, 들어오는 스냅샷을 출력합니다.
메시지를 보내지 않습니다. 실행: python3 verify_push.py <FQDN> [초, 기본 180]
필요: pip install --user websockets requests
"""
import asyncio
import json
import sys
from datetime import datetime, timezone

import requests
import websockets


async def main(fqdn: str, seconds: int) -> None:
    r = requests.post(f"https://{fqdn}/market-state/negotiate", timeout=10)
    r.raise_for_status()
    url = r.json()["url"]
    cur = requests.get(f"https://{fqdn}/market-state/current", timeout=10).json()
    print("현재값    ", cur["snapshot"]["snapshot_id"], "age", cur["delivery"]["age_seconds"], "s")
    got = []
    async with websockets.connect(url, open_timeout=10) as ws:
        print(f"접속됨. {seconds}초 동안 수신합니다.")
        loop = asyncio.get_running_loop()
        end = loop.time() + seconds
        while (left := end - loop.time()) > 0:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=left)
            except asyncio.TimeoutError:
                break
            msg = json.loads(raw)
            now = datetime.now(timezone.utc)
            as_of = datetime.fromisoformat(msg["as_of"].replace("Z", "+00:00"))
            got.append(msg["snapshot_id"])
            print("수신      ", msg["snapshot_id"], msg["quality_status"],
                  f"valid {msg['valid_asset_count']}/{msg['expected_asset_count']}",
                  f"지연 {(now - as_of).total_seconds():.0f}s")
    dup = len(got) - len(set(got))
    print(f"수신 {len(got)}건, 중복 {dup}건, 순서 {'정상' if got == sorted(got) else '역전 있음'}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 180))
