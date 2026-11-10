"""Read real pushed events without Azure credentials.

Run with Python containing requests and websockets. No mock events are sent.
"""
import asyncio
import json
from datetime import datetime, timezone

import requests
import websockets
from dateutil.parser import isoparse

HOST = 'https://func-whatif-dev-h6a0ebd4c6duhzg2.koreacentral-01.azurewebsites.net'


async def verify():
    started = datetime.now(timezone.utc)
    response = requests.post(HOST + '/api/quotes/negotiate', timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f'Negotiate HTTP {response.status_code}')
    url = response.json()['url']
    count = 0
    assets = set()
    new = 0
    async with websockets.connect(url) as ws:
        end = asyncio.get_running_loop().time() + 40
        while asyncio.get_running_loop().time() < end:
            try:
                message = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            except asyncio.TimeoutError:
                continue
            for q in message.get('quotes', [message]):
                if q.get('record_type') not in ('quote_event', 'quote_latest'):
                    continue
                assert q['is_mock'] is False
                count += 1
                assets.add(q['asset_id'])
                received = isoparse(q['received_at'])
                new += received >= started
    print(json.dumps({'started_at': started.isoformat(), 'messages': count,
                      'assets': sorted(assets), 'received_after_start': new,
                      'live_verified': new > 0}, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(verify())
