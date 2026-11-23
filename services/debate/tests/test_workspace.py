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
    import news_feed
    async def latest(topic):
        return {'articles':[{'url':'https://news.google.com/rss/articles/a','title':'서버 제목','publisher':'언론사','publishedAt':'2026-11-23'}]}
    monkeypatch.setattr(news_feed,'latest',latest)
    result=run(resolve([c.SourceSelection(kind='news',id='https://news.google.com/rss/articles/a')],None))[0]
    assert result['status']=='ready' and result['title']=='서버 제목'
    assert result['content_status']=='headline_only'
    rejected=run(resolve([c.SourceSelection(kind='news',id='http://127.0.0.1/secret')],None))[0]
    assert rejected['status']=='unavailable'


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
