"""Resolve explicit source identifiers using trusted service adapters.

Selected sources are frozen with the bundle. Text is evidence, never an instruction.
No URL supplied by the browser is fetched directly.
"""
import asyncio
import json
import os
import re


async def resolve(selections, snapshot):
    async def one(selection):
        item = selection.model_dump() if hasattr(selection, 'model_dump') else selection
        result = {"kind": item['kind'], "id": item['id'], "status": "unavailable"}
        try:
            if item['kind'] == 'news':
                if item['category'] == 'company':
                    from company_news import latest
                    payload = await latest(item['query'])
                else:
                    from news_feed import latest
                    payload = await latest(item['category'])
                article = next((a for a in payload['articles'] if a['url'] == item['id']), None)
                if not article:
                    raise ValueError('선택 기사를 서버 뉴스 목록에서 확인할 수 없습니다. 다시 검색해 주세요.')
                result.update(title=article['title'], url=article['url'], content_status='headline_only',
                              excerpt='기사 제목과 메타데이터만 확인했습니다. 본문은 수집하지 않았습니다.\n' + json.dumps(article, ensure_ascii=False))
            elif item['kind'] == 'document':
                if not re.fullmatch(r'\d{14}', item['id']):
                    raise ValueError('공시 접수번호가 올바르지 않습니다.')
                key = os.environ.get('DART_API_KEY')
                if not key:
                    raise ValueError('토론 실행기의 DART 연결이 설정되지 않았습니다.')
                from open_dart import OpenDartClient
                client = OpenDartClient(key)
                try:
                    text, _, truncated = await client.original_preview(item['id'])
                finally:
                    await client.close()
                if not text.strip():
                    raise ValueError('공시에서 읽을 수 있는 본문이 없습니다.')
                result.update(title='DART 공시 ' + item['id'], url='https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' + item['id'],
                              content_status='excerpt', excerpt='금융감독원 OpenDART에서 조회한 본문 발췌입니다. 전체 문서 분석이 아닙니다.\n' + text[:8000])
            else:
                if not snapshot or item['id'] != str(snapshot.get('snapshot_id')):
                    raise ValueError('선택한 시장 자료와 분석 시점이 다릅니다. 최신 자료로 스트레스테스트를 다시 실행해 주세요.')
                result.update(title='분석 시점 시장 관측', url='', content_status='snapshot',
                              excerpt='분석 결과에 고정된 관측 자료입니다. 일별 ML 결과를 갱신하지 않습니다.\n' + json.dumps(snapshot, ensure_ascii=False, default=str)[:16000])
            result['status'] = 'ready'
        except Exception as exc:
            result['reason'] = str(exc) if isinstance(exc, ValueError) else '자료 제공처 응답을 확인하지 못했습니다. 다시 시도해 주세요.'
        return result
    return await asyncio.gather(*(one(item) for item in selections))
