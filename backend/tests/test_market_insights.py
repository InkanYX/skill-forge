import json
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.market_insights import MarketQuery, MarketWorker, XiyouClient, process_market_one
from app.sellersprite import ResearchError
from test_auth import accounts, member


def study(client, title='车棚市场'):
    response = client.post('/api/market-insights/studies', json={'title': title, 'marketplace': 'US'})
    assert response.status_code == 201, response.text
    return response.json()


def submit(client, identifier, **kwargs):
    return client.post('/api/market-insights/studies/'+identifier+'/queries', json={
        'request_id': str(uuid4()), 'provider': 'sellersprite', 'section': 'search',
        'keyword': 'Carports', 'accept_cost': True, **kwargs})


class Fake:
    calls = []
    failure = False
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def call(self, name, arguments):
        self.calls.append((name, arguments))
        if self.failure: raise ResearchError('查询超时，扣费待确认。', uncertain=True)
        return {'items': [{'categoryId': '1:2:3', 'name': '车棚'}], 'billing': {'chargedUnits': 1, 'remainingUnits': 99}}


def test_shared_studies_private_notes_and_origin_guard(accounts):
    admin, _, _, _ = accounts
    own = study(admin)
    other, _ = member(accounts)
    assert other.get('/api/market-insights/studies').json()[0]['id'] == own['id']
    assert other.get('/api/market-insights/studies/'+own['id']).json()['can_edit'] is False
    assert other.put('/api/market-insights/studies/'+own['id']+'/notes',json={'notes':'overwrite'}).status_code == 403
    assert admin.put('/api/market-insights/studies/'+own['id']+'/notes',json={'notes':'研究记录'}).status_code == 200
    assert admin.post('/api/market-insights/studies',json={'title':'evil','marketplace':'US'},headers={'Origin':'https://untrusted.invalid'}).status_code == 403


def test_worker_idempotency_cache_and_refresh(accounts, monkeypatch):
    admin, _, engine, _ = accounts
    monkeypatch.setattr('app.market_insights.shared_key', lambda: 'test-key')
    Fake.calls, Fake.failure = [], False
    own = study(admin)
    rid = str(uuid4())
    first = submit(admin, own['id'], request_id=rid).json()
    assert submit(admin, own['id'], request_id=rid).json()['id'] == first['id']
    assert submit(admin, own['id']).json()['id'] == first['id']
    assert process_market_one(engine, {'sellersprite': Fake})
    assert not process_market_one(engine, {'sellersprite': Fake})
    cached = submit(admin, own['id']).json()
    assert cached['status'] == 'succeeded' and cached['billing']['chargedUnits'] == 0
    assert cached['reused_from'] == first['id'] and len(Fake.calls) == 1
    assert submit(admin, own['id'], refresh=True).json()['status'] == 'queued'
    assert process_market_one(engine, {'sellersprite': Fake})
    assert len(Fake.calls) == 2


def test_shared_pending_survives_navigation_and_uncertain_never_retries(accounts, monkeypatch):
    admin, _, engine, _ = accounts
    monkeypatch.setattr('app.market_insights.shared_key', lambda: 'test-key')
    Fake.calls, Fake.failure = [], True
    a, b = study(admin), study(admin, '第二个项目')
    first = submit(admin, a['id']).json()
    linked = submit(admin, b['id']).json()
    assert linked['id'] != first['id'] and linked['status'] == 'queued'
    process_market_one(engine, {'sellersprite': Fake})
    view = admin.get('/api/market-insights/studies/'+b['id']).json()['queries'][0]
    assert view['status'] == 'unknown'
    assert submit(admin, a['id'], refresh=True).json()['status'] == 'unknown'
    assert not process_market_one(engine, {'sellersprite': Fake})
    assert len(Fake.calls) == 1
    assert admin.post('/api/market-insights/queries/'+linked['id']+'/resolve', json={}).status_code == 200
    assert submit(admin, a['id'], refresh=True).json()['status'] == 'queued'


def test_validate_scope_and_no_unconfirmed_paid_jobs(accounts, monkeypatch):
    admin, _, _, _ = accounts
    monkeypatch.setattr('app.market_insights.xiyou_key',lambda:'test-key')
    own=study(admin)
    assert submit(admin, own['id'], accept_cost=False).status_code == 422
    assert submit(admin, own['id'], section='overview').status_code == 422
    assert submit(admin, own['id'], provider='xiyou', month='').status_code == 422
    assert submit(admin, own['id'], provider='xiyou', month='2026-10',limit=100).status_code == 422
    result=submit(admin, own['id'], provider='xiyou',month='2026-10',limit=3).json()
    assert result['arguments']=={'country':'US','query':'Carports','cycleFilter':{'cycle':'monthly','startDate':'2026-10-01'},'page':1,'pageSize':3}


def test_xiyou_fixed_endpoint_bearer_and_business_error():
    requests=[]
    def handler(request):
        requests.append(request)
        assert str(request.url)=='https://mcp.xydc.com/mcp'
        assert request.headers['Authorization']=='Bearer test-xiyou'
        assert 'secret-key' not in request.headers
        body=json.loads(request.content)
        if body['method']=='notifications/initialized':return httpx.Response(202)
        result={'protocolVersion':'2025-03-26'} if body['method']=='initialize' else {'structuredContent':{'status':200,'cost_credits':5,'data':{'list':[]}}}
        return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'result':result})
    with XiyouClient('test-xiyou',httpx.MockTransport(handler)) as client:
        assert client.call('search_market_insight_categories',{})['cost_credits']==5
    assert len(requests)==3


def test_restart_marks_inflight_unknown_and_does_not_resubmit(accounts, monkeypatch):
    admin, _, engine, _=accounts
    monkeypatch.setattr('app.market_insights.shared_key',lambda:'test-key')
    own=study(admin);query=submit(admin,own['id']).json()
    with Session(engine) as session:
        session.get(MarketQuery,query['id']).status='running';session.commit()
    worker=MarketWorker(engine);worker.start();worker.stop()
    with Session(engine) as session:
        row=session.scalar(select(MarketQuery))
        assert row.status=='unknown' and row.active_key
