"""Workspace contracts: participant filtering and explicit source resolution."""
import asyncio
from test_debate import make, start_req, run, FakeLLM
from test_api import env, H
import contracts as c
from selected_evidence import resolve


def test_selected_participants_only():
    orch, store, sender = make(FakeLLM())
    req = start_req().model_copy(update={'target_roles': ['macro', 'risk']})
    run(orch.handle(req))
    roles = {data['role'] for name, data in orch.llm.calls if name != 'debate_summary'}
    assert roles == {'macro', 'risk'}
    rounds = [e['payload']['speakers'] for _, e in sender.sent if e['type'] == 'debate.round']
    assert all(set(order) <= roles for order in rounds)


def test_api_passes_selection(env):
    client, queue, reader = env
    response = client.post('/debates', headers=H, json={'run_id':'stress_run','target_roles':['risk'],
        'selected_sources':[{'kind':'document','id':'20250327000281'}]})
    assert response.status_code == 202
    req = c.DebateRequest.model_validate(queue.sent[-1][2])
    assert req.target_roles == ['risk']
    assert req.selected_sources[0].id == '20250327000281'
    assert client.post('/debates',headers=H,json={'target_roles':[]}).status_code == 422


def test_news_resolves_from_server_not_browser(monkeypatch):
    import article_body
    import news_feed
    import selected_evidence
    feed_url = "https://news.google.com/rss/articles/a"
    publisher_url = "https://publisher.example.com/news/123"
    opened = []
    async def latest(topic):
        return {"articles": [{"url": feed_url, "title": "서버 제목"}]}
    def read(url):
        opened.append(url)
        return publisher_url, "기사 원문 문장"
    monkeypatch.setattr(news_feed, "latest", latest)
    monkeypatch.setattr(article_body, "read_article", read)
    result = run(resolve([c.SourceSelection(kind="news", id=feed_url)], None))[0]
    assert result["status"] == "ready" and result["content_status"] == "article"
    assert result["url"] == publisher_url and "기사 원문 문장" in result["excerpt"]
    rejected = run(resolve([c.SourceSelection(kind="news", id="http://127.0.0.1/secret")], None))[0]
    assert rejected["status"] == "unavailable" and opened == [feed_url]

    def inaccessible(url):
        raise ValueError("기사 원문을 읽지 못했습니다.")
    monkeypatch.setattr(article_body, "read_article", inaccessible)
    cached = run(resolve([c.SourceSelection(kind="news", id=feed_url)], None))[0]
    assert cached == result and opened == [feed_url]
    expired = selected_evidence.monotonic() + 181
    monkeypatch.setattr(selected_evidence, "monotonic", lambda: expired)
    blocked = run(resolve([c.SourceSelection(kind="news", id=feed_url)], None))[0]
    assert blocked["status"] == "ready" and blocked["content_status"] == "headline_only"
    assert blocked["url"] == feed_url and blocked["title"] == "서버 제목"
    assert "본문 미확인" in blocked["excerpt"] and "서버 제목" in blocked["excerpt"]


def test_market_snapshot_must_match():
    result=run(resolve([c.SourceSelection(kind='market',id='old')],{'snapshot_id':'new'}))[0]
    assert result['status']=='unavailable'
    matched=run(resolve([c.SourceSelection(kind='market',id='new')],{'snapshot_id':'new','applied_to_daily_ml':False}))[0]
    assert matched['status']=='ready' and 'false' in matched['excerpt']


def test_document_failure_is_not_success(monkeypatch):
    monkeypatch.delenv('DART_API_KEY',raising=False)
    result=run(resolve([c.SourceSelection(kind='document',id='20250327000281')],None))[0]
    assert result['status']=='unavailable' and 'excerpt' not in result


def test_selected_evidence_is_frozen(monkeypatch):
    import selected_evidence
    calls=[]
    async def resolver(selections,snapshot):
        calls.append(1)
        return [{'kind':'news','id':'article','status':'ready','title':'제목','url':'https://example.com','excerpt':'제목만 수집'}]
    monkeypatch.setattr(selected_evidence,'resolve',resolver)
    orch,store,sender=make()
    req=start_req()
    run(orch.handle(req))
    bundle=next(iter(store.bundles.values()))
    assert bundle['selected_sources'][0]['source_id'] in {s['id'] for s in bundle['S_sources']}
    run(orch.handle(req))
    assert len(calls)==1
