"""정시 회의 요청 (Container Apps 예약 작업이 실행).

    python schedule.py 0830     # 08:30 장 전 회의
    python schedule.py 1300     # 13:00 장중 회의
    python schedule.py 1540     # 15:40 장 마감 후 회의

토론 요청 API의 POST /scheduled-debates를 한 번 부릅니다. API가 대상 사용자마다 그 사용자의
토론을 하나씩 큐에 넣습니다(사용자별 회의, 본인만 조회). 같은 날·시간대·사용자는 같은 debate_id라
작업이 재시도돼도 사용자마다 회의는 하나입니다.

환경변수: API_URL(토론 요청 API 주소), SCHEDULER_KEY(API와 같은 값)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

SLOTS = ("0830", "1300", "1540")


def request(slot: str, api_url: str, key: str, timeout: float = 60) -> dict:
    if slot not in SLOTS:
        raise ValueError(f"slot은 {SLOTS} 중 하나여야 합니다: {slot}")
    req = urllib.request.Request(
        api_url.rstrip("/") + "/scheduled-debates",
        data=json.dumps({"slot": slot}).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-Scheduler-Key": key})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read())


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    try:
        body = request(argv[1], os.environ["API_URL"], os.environ["SCHEDULER_KEY"])
    except urllib.error.HTTPError as e:
        print(f"정시 회의 요청 실패 {e.code}: {e.read().decode(errors='replace')}", file=sys.stderr)
        return 1
    print(f"정시 회의 접수 slot={body['slot']} 대상 {body['users']}명, 접수 {body['accepted']}, 실패 {body['failed']}"
          + (" (상한 도달)" if body.get("capped") else ""))
    return 1 if body["failed"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
